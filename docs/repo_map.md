# Repository Map

## Directory overview

- `FreeRTOS-interface/`: Python desktop control app (Qt/PySide6) and MVC implementation.
  - `App.py`: process entrypoint and bootstrap.
  - `View.py`: UI widgets, button/signal hookups.
  - `Controller.py`: UI action handling, sequencing, machine/model coordination.
  - `Model.py`: state + domain models (`MachineModel`, rack/location/experiment/calibration).
  - `Machine_FreeRTOS.py`: host comms, command framing/queueing, serial TX/RX.
  - `Presets/`: runtime JSON/settings/assets.
  - `CalibrationClasses/`, `hardware/`, `legacy/`, `utilities/`: supporting modules.
- `firmware/`: STM32 + FreeRTOS firmware.
  - `Inc/`: headers (`Comm.h`, `Orchestrator.h`, motion/pressure components).
  - `Src/`: implementation (`main.c`, `Comm.cpp`, `Orchestrator.cpp`, etc.).
- `Documentation/`: hardware and project documentation assets.
- `docs/`: repo-level docs (this file lives here).
- Root support files: `README.md`, `requirements.txt`, setup scripts.

## Key entrypoints (how the app starts)

### Python app startup

- `FreeRTOS-interface/App.py` is the real executable entrypoint (`if __name__ == "__main__": main()`, lines 107-109).
- `main()` creates `QApplication` (line 49), then constructs core objects in this order:
  1. `model = Model(...)` (line 69)
  2. `machine = Machine(model, ...)` (line 71)
  3. `controller = Controller(machine, model, ...)` (line 72)
  4. `view = MainWindow(model, controller, ...)` (line 95)
- Event loop starts with `app.exec()` (line 104).

### README startup notes

- `README.md` includes run commands, but one path is stale (`python .\MVC-Interface\App.py`, line 80).
- Newer section references `python FreeRTOS_interface/App.py` (line 100), but current on-disk folder is `FreeRTOS-interface/` (hyphen).
- Source of truth in this repo is `FreeRTOS-interface/App.py`.

### Firmware startup

- In firmware default task, `MX_COMM_Init(&huart2)` is called (`firmware/Src/main.c`, line 1401) to start communication.
- `MX_COMM_Init` constructs `Comm` and calls `Comm::begin()` (`firmware/Src/Comm.cpp`, lines 94-97).
- `Orchestrator` startup is via `MX_ORCH_Init()` (`firmware/Src/Orchestrator.cpp`, lines 61-65), which creates command queue/task.

## MVC wiring (View -> Controller -> Model)

### Composition root

- Wiring is centralized in `App.py` by passing `model` and `controller` into `MainWindow`.

### View -> Controller

Examples from `View.py`:

- Connection flow:
  - `ConnectionWidget.connect_machine_requested` is connected to `controller.connect_machine` (line 485).
  - Connect/disconnect button triggers `request_machine_connect_change()` (line 551), then `connect_machine_requested.emit(port)` (line 633).
- Homing flow:
  - `MotorPositionWidget.home_requested` connects to `controller.home_machine` (line 739).
  - Home button emits `home_requested` via `request_homing()` (line 858).
- Print flow:
  - Plate widget start button calls `start_print_array()` (line 1235), which invokes `controller.print_array()` (line 1268).
- Pause/queue control:
  - Pause button calls `main_window.pause_machine` (line 1240), which routes to `controller.pause_commands()` / `resume_commands()` / `clear_command_queue()` (lines 336, 340, 344).

### Controller mediation

`Controller` holds both collaborators (`self.machine`, `self.model`; lines 40-41) and mediates:

- Machine->Model status updates:
  - `machine.status_updated -> controller.handle_status_update` (line 71), then `model.update_state(status_dict)` (line 141).
- Queue progress synchronization:
  - `model.machine_model.command_numbers_updated -> controller.update_command_numbers` (line 79).
  - `update_command_numbers()` pushes numbers into machine queue tracker (line 150).
- User actions usually forward to machine command APIs:
  - `home_machine()` -> `self.machine.home_motors()` (lines 639-642).
  - `print_droplets()` -> `self.machine.print_droplets(...)` (lines 898, 923).
  - `set_absolute_XY/Z/...` methods call corresponding `self.machine.*` methods.

### Model role

- `Model` aggregates submodels in `Model.__init__` (lines 5223-5242), including:
  - `MachineModel`, `RackModel`, `LocationModel`, `ExperimentModel`, calibration models.
- `Model.update_state()` applies parsed machine status to `MachineModel` fields and emits `machine_state_updated` (lines 5291-5347).

## Hardware command path (UI action -> queue -> serial -> firmware handler)

## 1) UI action triggers Controller

Example: Home button path:

- `View.py`: home button/user signal -> `controller.home_machine()` (lines 739, 858).
- `Controller.py`: `home_machine()` -> `machine.home_motors()` (lines 639-642).

## 2) Controller asks Machine to enqueue commands

- `Machine.home_motors()` enqueues `HOME_Z`, `HOME_XY`, `HOME_PR_BOTH` (lines 1957-1959 in `Machine_FreeRTOS.py`).
- Most machine operations are thin wrappers over `add_command_to_queue(...)` (e.g., lines 1789-2016).

## 3) Host-side queue and frame building

- `CommandQueue.add_command()` creates `Command` objects and appends to deque (lines 1104-1113).
- `Command` builds binary TLV payload + CRC frame:
  - command byte + seq8 + SEQ32 + P1/P2/P3 TLVs (lines 1031-1048).
  - frame = `[START, len, payload, crc]` (lines 1050-1054).
- `Machine.send_next_command()` pulls from queue and sends pending commands (lines 1639-1676).
- `send_command_to_board()` writes bytes to serial (`self.ser.write(frame)`) via `_write_frame()` (lines 1625-1637).

## 4) Firmware receive/parse path

- `Comm` RX ISR callback (`HAL_UART_RxCpltCallback`) performs frame state-machine parse + CRC check (lines 123-166 in `firmware/Src/Comm.cpp`).
- On valid packet, `Comm::handlePacket()` decodes TLVs into `Orchestrator::Command` (lines 172-197) and calls `Orchestrator::enqueueFromISR(...)` (lines 199-202).

## 5) Firmware queue and command execution

- `Orchestrator::enqueueFromISR` handles control commands immediately (`HELLO/GOODBYE/PAUSE/RESUME/CLEAR`) or pushes normal commands into `_cmdQueue` (lines 67-110 in `firmware/Src/Orchestrator.cpp`).
- Orchestrator task loop receives queued commands with `xQueueReceive(...)` and calls `executeCommand(cmd)` (lines 347-353).
- `executeCommand` dispatches by command enum and invokes hardware modules:
  - movement (`Stepper`, `Gantry`),
  - dispensing (`Printer`),
  - pressure control (`PressureRegulator`),
  - gripper (`MX_GRIPPER_*`), etc. (lines 374 onward; examples 384-518).

## 6) Status/ack return path back to host

- Firmware sends ACK/status via `Comm::sendAckWithSeq32` and status task (`Comm.cpp`, e.g., lines 228-250, 255+).
- Host reader updates `Machine.update_status()` -> emits `status_updated` (Machine_FreeRTOS.py lines 1569-1587).
- Controller receives that and calls `Model.update_state()` (Controller.py lines 139-142), completing the loop.
