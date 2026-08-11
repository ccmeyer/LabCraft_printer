from GravimetricLedger import (
    EjectionCommandEvent,
    EjectionCommandLifecycle,
    GravimetricEjectionLedger,
    ImagingEjectionEvent,
    ImagingEjectionLifecycle,
)


def _event(number, lifecycle, *, command_type="DISPENSE", count=10, epoch=1):
    return EjectionCommandEvent(
        transport_epoch=epoch,
        command_number=number,
        command_type=command_type,
        requested_droplet_count=count,
        lifecycle=lifecycle,
        monotonic_ns=number * 100,
    )


def _imaging_event(
    attempt,
    lifecycle,
    *,
    count=1,
    epoch=1,
    generation=4,
    request_id="capture-1",
):
    return ImagingEjectionEvent(
        transport_epoch=epoch,
        capture_generation=generation,
        request_id=request_id,
        attempt_index=attempt,
        requested_droplet_count=count,
        lifecycle=lifecycle,
        monotonic_ns=attempt * 100,
    )


def test_queued_and_completed_ejections_are_counted_once():
    ledger = GravimetricEjectionLedger()
    queued = _event(1, EjectionCommandLifecycle.QUEUED, count=20)
    completed = _event(1, EjectionCommandLifecycle.COMPLETED, count=20)

    ledger.record(queued)
    ledger.record(queued)
    ledger.record(_event(1, EjectionCommandLifecycle.ACCEPTED, count=20))
    ledger.record(_event(1, EjectionCommandLifecycle.EXECUTING, count=20))
    ledger.record(completed)
    snapshot = ledger.record(completed)

    assert snapshot.attempt_generation == 1
    assert snapshot.command_attempt_generation == 1
    assert snapshot.imaging_attempt_generation == 0
    assert snapshot.completed_droplet_total == 20
    assert snapshot.serial_completed_droplet_total == 20
    assert snapshot.imaging_acknowledged_droplet_total == 0
    assert snapshot.uncertainty_generation == 0


def test_dispense_print_is_counted_and_transport_epoch_disambiguates_commands():
    ledger = GravimetricEjectionLedger()
    for epoch in (1, 2):
        ledger.record(
            _event(
                1,
                EjectionCommandLifecycle.QUEUED,
                command_type="DISPENSE_PRINT",
                count=3,
                epoch=epoch,
            )
        )
        ledger.record(
            _event(
                1,
                EjectionCommandLifecycle.COMPLETED,
                command_type="DISPENSE_PRINT",
                count=3,
                epoch=epoch,
            )
        )
    assert ledger.snapshot().attempt_generation == 2
    assert ledger.snapshot().completed_droplet_total == 6


def test_cancellation_is_uncertain_only_after_acceptance():
    clean = GravimetricEjectionLedger()
    clean.record(_event(1, EjectionCommandLifecycle.QUEUED))
    assert clean.record(_event(1, EjectionCommandLifecycle.CANCELLED)).uncertainty_generation == 0

    uncertain = GravimetricEjectionLedger()
    uncertain.record(_event(2, EjectionCommandLifecycle.QUEUED))
    uncertain.record(_event(2, EjectionCommandLifecycle.ACCEPTED))
    snapshot = uncertain.record(_event(2, EjectionCommandLifecycle.CANCELLED))
    assert snapshot.uncertainty_generation == 1


def test_reuse_requires_unchanged_attempt_and_uncertainty_generations():
    ledger = GravimetricEjectionLedger()
    baseline = ledger.snapshot()
    assert ledger.reusable_since(baseline, ledger.snapshot())

    ledger.record(_event(1, EjectionCommandLifecycle.QUEUED))
    assert not ledger.reusable_since(baseline, ledger.snapshot())

    second = GravimetricEjectionLedger()
    baseline = second.snapshot()
    second.mark_uncertain("transport fault")
    assert not second.reusable_since(baseline, second.snapshot())


def test_acknowledged_imaging_attempts_are_source_counted_once():
    ledger = GravimetricEjectionLedger()
    for attempt in (1, 2):
        triggered = _imaging_event(
            attempt,
            ImagingEjectionLifecycle.TRIGGERED,
            count=2,
        )
        acknowledged = _imaging_event(
            attempt,
            ImagingEjectionLifecycle.ACKNOWLEDGED,
            count=2,
        )
        ledger.record(triggered)
        ledger.record(triggered)
        ledger.record(acknowledged)
        ledger.record(acknowledged)

    snapshot = ledger.snapshot()
    assert snapshot.attempt_generation == 2
    assert snapshot.command_attempt_generation == 0
    assert snapshot.imaging_attempt_generation == 2
    assert snapshot.completed_droplet_total == 4
    assert snapshot.imaging_acknowledged_droplet_total == 4
    assert snapshot.uncertainty_generation == 0


def test_background_imaging_events_do_not_change_ledger():
    ledger = GravimetricEjectionLedger()
    baseline = ledger.snapshot()
    ledger.record(
        _imaging_event(1, ImagingEjectionLifecycle.TRIGGERED, count=0)
    )
    ledger.record(
        _imaging_event(1, ImagingEjectionLifecycle.ACKNOWLEDGED, count=0)
    )
    ledger.record(
        _imaging_event(1, ImagingEjectionLifecycle.UNCERTAIN, count=0)
    )
    assert ledger.snapshot() == baseline


def test_unknown_or_unacknowledged_imaging_attempt_is_uncertain():
    unknown = GravimetricEjectionLedger()
    snapshot = unknown.record(
        _imaging_event(1, ImagingEjectionLifecycle.TRIGGERED, count=None)
    )
    assert snapshot.imaging_attempt_generation == 1
    assert snapshot.completed_droplet_total == 0
    assert snapshot.uncertainty_generation == 1

    missing_ack = GravimetricEjectionLedger()
    missing_ack.record(
        _imaging_event(1, ImagingEjectionLifecycle.TRIGGERED, count=1)
    )
    snapshot = missing_ack.record(
        _imaging_event(1, ImagingEjectionLifecycle.UNCERTAIN, count=1)
    )
    assert snapshot.imaging_attempt_generation == 1
    assert snapshot.completed_droplet_total == 0
    assert snapshot.uncertainty_generation == 1


def test_uncertainty_after_acknowledgement_keeps_count_and_blocks_reuse():
    ledger = GravimetricEjectionLedger()
    baseline = ledger.snapshot()
    ledger.record(_imaging_event(1, ImagingEjectionLifecycle.TRIGGERED))
    ledger.record(_imaging_event(1, ImagingEjectionLifecycle.ACKNOWLEDGED))
    snapshot = ledger.record(
        _imaging_event(1, ImagingEjectionLifecycle.UNCERTAIN)
    )
    assert snapshot.imaging_acknowledged_droplet_total == 1
    assert snapshot.completed_droplet_total == 1
    assert snapshot.uncertainty_generation == 1
    assert not ledger.reusable_since(baseline, snapshot)


def test_invalid_events_fail_closed():
    try:
        _event(1, EjectionCommandLifecycle.QUEUED, command_type="DISPENSE_REFUEL")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("refuel-only command must not be accepted as an ejection")
