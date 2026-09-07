"""Isolated, cancellable editor computations; Qt publication stays with the UI."""
from dataclasses import dataclass, field
import copy
import hashlib
import pickle
import threading
import time
import uuid
import weakref

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QEvent, QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class OptimizationCancelled(Exception):
    """Control flow, never an optimizer feasibility/fallback result."""


class ComputationControl:
    SLOW_OPTIMIZER_SECONDS = 3.0

    def __init__(self, phase_callback=None, *, clock=None):
        self.cancelled = threading.Event()
        self.phase_callback = phase_callback
        self.phase = None
        self._last_yield = time.monotonic()
        self._clock = clock or time.monotonic
        self._optimizer_started = None
        self._slow_reported = False
        self.slow_callback = None
        self._activity_lock = threading.Lock()
        self._activity = None
        self._counts = {}

    def begin_optimizer(self):
        self._optimizer_started = self._clock()

    def end_optimizer(self):
        self._check_slow()
        self._optimizer_started = None

    def _check_slow(self):
        if (self._optimizer_started is not None and not self._slow_reported
                and self._clock() - self._optimizer_started >= self.SLOW_OPTIMIZER_SECONDS):
            self._slow_reported = True
            if self.slow_callback:
                self.slow_callback()

    def activity(self, label, *, increment=0, completed=None, total=None):
        """A bounded mailbox, not one queued Qt event per search candidate."""
        self.check()
        with self._activity_lock:
            count = self._counts.get(label, 0) + increment if completed is None else completed
            self._counts[label] = count
            self._activity = (self.phase, label, count, total)

    def activity_snapshot(self):
        with self._activity_lock:
            return self._activity

    def check(self):
        if self.cancelled.is_set():
            raise OptimizationCancelled()
        self._check_slow()
        if time.monotonic() - self._last_yield >= 0.005:
            # Give Qt's Python callbacks a turn even when this worker repeatedly
            # reacquires the GIL. This affects latency, never search work/ranking.
            time.sleep(0.001)
            self._last_yield = time.monotonic()
            if self.cancelled.is_set():
                raise OptimizationCancelled()

    def report(self, phase):
        self.check()
        if phase != self.phase:
            self.phase = phase
            with self._activity_lock:
                self._activity = None
                self._counts.clear()
            if self.phase_callback:
                self.phase_callback(phase)


def input_fingerprint(snapshot):
    return hashlib.sha256(pickle.dumps(snapshot, protocol=4)).hexdigest()


@dataclass
class OptimizationRequest:
    snapshot: dict
    kind: str = "design"
    options: dict = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class OptimizationOutcome:
    job_id: str
    status: str
    result: dict = field(default_factory=dict)
    computed: dict = field(default_factory=dict)
    error: str = ""


class _StartOptimizationEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, request, control):
        super().__init__(self.TYPE)
        self.request, self.control = request, control


class _OptimizationWorker(QObject):
    completed = Signal(object)
    phase_changed = Signal(str, str)
    slow_optimizer = Signal(str)

    @Slot(object, object)
    def run(self, request, control):
        # Import lazily: neither the job service nor its snapshots own a model.
        outcome = OptimizationOutcome(request.job_id, "failed")
        try:
            from Model import ExperimentModel
            control.phase_callback = lambda phase: self.phase_changed.emit(request.job_id, phase)
            if request.kind == "design" and request.options.get("automatic"):
                control.slow_callback = lambda: self.slow_optimizer.emit(request.job_id)
            control.report("Preparing inputs")
            draft = ExperimentModel()
            draft.restore_optimization_inputs(request.snapshot)
            draft._optimization_control = control
            draft.blockSignals(True)
            if request.kind == "import":
                control.report("Calculating feasibility")
                outcome.result = draft.build_import_feasibility_report(**request.options)
            else:
                options = dict(request.options)
                if request.kind == "import_apply":
                    reuse = draft.prepare_import_application(options["payload"], options["metadata"])
                    available = options.get("available_wells")
                    if available is not None and draft.estimate_design_size().total_runs > available:
                        raise ValueError("The imported design exceeds the available wells on the selected plate.")
                    options.update(reuse_allocation=bool(reuse.get("reused")),
                                   previous_result=reuse.get("result"))
                if options.get("reuse_allocation"):
                    outcome.result = copy.deepcopy(options.get("previous_result") or {})
                    outcome.result.update(best=True, stock_allocation_reused=True)
                else:
                    control.begin_optimizer()
                    try:
                        outcome.result = draft.optimize_stock_solutions(
                            quantum=0.1, max_refine=60, two_max_refine=40,
                            allow_two=options["allow_two"],
                        )
                    finally:
                        control.end_optimizer()
                if outcome.result.get("best"):
                    draft.validate_optimization_allocation(outcome.result)
                    control.report("Generating reactions")
                    draft.generate_experiment()
                    outcome.computed = (draft.capture_import_application() if request.kind == "import_apply"
                                        else draft.capture_optimization_outputs())
            control.check()
            outcome.status = "succeeded"
        except OptimizationCancelled:
            outcome.status = "cancelled"
        except Exception as exc:
            outcome.error = str(exc) or type(exc).__name__
        finally:
            control.phase_callback = None
            control.slow_callback = None
        self.completed.emit(outcome)


class OptimizationJobManager(QObject):
    """One application-owned worker; no callbacks execute on the worker thread."""
    _dispatch = Signal(object, object)
    settled = Signal()
    phase_changed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._active = None
        self._publication_pending = False
        self._shutting_down = False
        self._quit_pending = False
        self._shutdown_callbacks = []

    @property
    def busy(self):
        return self._active is not None or self._publication_pending

    def begin_publication(self):
        """Keep submission/shutdown interlocks through queued UI completion."""
        self._publication_pending = True

    def finish_publication(self):
        self._publication_pending = False
        self.settled.emit()
        if self._shutting_down and self._thread is not None:
            self._thread.quit()

    def submit(self, owner, request, completed, phase_changed=None, slow_optimizer=None):
        if self.busy or self._shutting_down:
            return False
        request = copy.deepcopy(request)
        if self._thread is None:
            self._thread = QThread(self)
            self._worker = _OptimizationWorker()
            self._worker.moveToThread(self._thread)
            self._dispatch.connect(self._worker.run, Qt.QueuedConnection)
            self._worker.completed.connect(self._completed, Qt.QueuedConnection)
            self._worker.phase_changed.connect(self._phase_changed, Qt.QueuedConnection)
            self._worker.slow_optimizer.connect(self._slow_optimizer, Qt.QueuedConnection)
            self._thread.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._stopped)
            self._thread.start()
        control = ComputationControl()
        self._active = (weakref.ref(owner), request.job_id, control, completed, phase_changed, slow_optimizer)
        # Finish pending control repaints before worker allocations can trigger
        # a process-wide GC. Never combine both pauses in the first UI frame.
        QCoreApplication.postEvent(self, _StartOptimizationEvent(request, control),
                                   Qt.LowEventPriority.value)
        return True

    def event(self, event):
        if event.type() == _StartOptimizationEvent.TYPE:
            self._dispatch.emit(event.request, event.control)
            return True
        return super().event(event)

    def cancel(self, owner=None):
        if self._active and (owner is None or self._active[0]() is owner):
            self._active[2].cancelled.set()

    def activity_snapshot(self, owner):
        if self._active and self._active[0]() is owner:
            return self._active[2].activity_snapshot()
        return None

    @Slot(str)
    def _slow_optimizer(self, job_id):
        active = self._active
        if (active and active[1] == job_id and active[0]() is not None
                and isValid(active[0]()) and active[5]):
            active[5]()

    @Slot(str, str)
    def _phase_changed(self, job_id, phase):
        active = self._active
        if (active and active[1] == job_id and active[0]() is not None
                and isValid(active[0]()) and not active[2].cancelled.is_set() and active[4]):
            active[4](phase)
            self.phase_changed.emit(job_id, phase)

    @Slot(object)
    def _completed(self, outcome):
        active = self._active
        if not active or active[1] != outcome.job_id:
            return
        self._active = None
        if active[2].cancelled.is_set():
            outcome = OptimizationOutcome(outcome.job_id, "cancelled")
        try:
            if active[0]() is not None and isValid(active[0]()):
                active[3](outcome)
        finally:
            if not self._publication_pending:
                self.settled.emit()
                if self._shutting_down:
                    self._thread.quit()

    def shutdown(self, completed=None):
        self._shutting_down = True
        if completed:
            self._shutdown_callbacks.append(completed)
        self.cancel()
        if self._thread is None:
            self._stopped()
        elif not self.busy:
            self._thread.quit()

    @Slot()
    def _stopped(self):
        if self._publication_pending:
            QTimer.singleShot(1, self._stopped)
            return
        # finished is emitted before all native thread-local cleanup completes.
        # Poll without blocking the UI before allowing QApplication teardown.
        if self._thread is not None and not self._thread.wait(0):
            QTimer.singleShot(1, self._stopped)
            return
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = self._worker = None
        callbacks, self._shutdown_callbacks = self._shutdown_callbacks, []
        for callback in callbacks:
            callback()
        if self._quit_pending:
            QTimer.singleShot(0, QApplication.instance().quit)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Quit and self._thread is not None:
            self._quit_pending = True
            self.shutdown()
            return True
        return super().eventFilter(watched, event)


def optimization_job_manager():
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Optimization jobs require a Qt application.")
    manager = getattr(app, "_optimization_job_manager", None)
    if manager is None:
        manager = OptimizationJobManager(app)
        app._optimization_job_manager = manager
        app.installEventFilter(manager)
    return manager
