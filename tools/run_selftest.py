#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone

try:
    import serial
except ImportError:
    serial = None


START_BYTE = 0xAA

CMD_HELLO = 0xF3
CMD_HELLO_ACK = 0xF4
CMD_GOODBYE = 0xF5
CMD_BYE_ACK = 0xF6
CMD_BYE_DONE = 0xF8
CMD_SELFTEST_START = 0xFA
CMD_SELFTEST_RESULT = 0xFB
CMD_SELFTEST_DONE = 0xFC
CMD_SELFTEST_ABORT = 0xFD

TAG_PROFILE = 0x20
TAG_RUN_ID = 0x21
TAG_TIMEOUT_MS = 0x22
TAG_TEST_ID = 0x30
TAG_NAME = 0x31
TAG_PASS = 0x32
TAG_METRICS = 0x33
TAG_TS_MS = 0x34
TAG_TOTAL = 0x35
TAG_PASSED = 0x36
TAG_FAILED = 0x37
TAG_ABORTED = 0x38
TAG_SEQ32 = 0x10


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
            crc &= 0xFFFF
    return crc


def frame_payload(payload: bytes) -> bytes:
    c = crc16(payload)
    return bytes([START_BYTE, len(payload)]) + payload + bytes([c & 0xFF, (c >> 8) & 0xFF])


def build_control(cmd: int, seq8: int, seq32: int, tlvs: bytes = b"") -> bytes:
    payload = bytes([cmd, seq8, TAG_SEQ32, 4]) + seq32.to_bytes(4, "little") + tlvs
    return frame_payload(payload)


def parse_tlvs(payload: bytes) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    i = 0
    while i + 1 < len(payload):
        tag = payload[i]
        ln = payload[i + 1]
        i += 2
        if i + ln > len(payload):
            break
        out[tag] = payload[i : i + ln]
        i += ln
    return out


def parse_metrics(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        return {}
    # Try JSON first if firmware emits it later.
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    out = {}
    for part in raw.replace(",", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
            continue
        try:
            out[k] = int(v, 10)
            continue
        except Exception:
            pass
        try:
            out[k] = float(v)
            continue
        except Exception:
            pass
        out[k] = v
    return out


class FrameReader:
    WAIT_START = 0
    WAIT_LEN = 1
    WAIT_DATA = 2

    def __init__(self) -> None:
        self.state = self.WAIT_START
        self.length = 0
        self.buf = bytearray()

    def feed(self, b: int):
        if self.state == self.WAIT_START:
            if b == START_BYTE:
                self.state = self.WAIT_LEN
            return None
        if self.state == self.WAIT_LEN:
            self.length = b
            self.buf.clear()
            self.state = self.WAIT_DATA
            return None

        self.buf.append(b)
        if len(self.buf) < self.length + 2:
            return None

        payload = bytes(self.buf[: self.length])
        rec_crc = self.buf[self.length] | (self.buf[self.length + 1] << 8)
        self.state = self.WAIT_START
        self.buf.clear()
        if crc16(payload) != rec_crc:
            return None
        return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".selftest_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(args: argparse.Namespace) -> int:
    if serial is None:
        print("Missing dependency: pyserial (import serial failed).")
        return 3

    profile = args.profile.upper()
    if profile != "SAFE":
        print(f"Unsupported profile '{profile}'. Only SAFE is currently supported.")
        return 3

    run_id = int(time.time() * 1000) & 0xFFFFFFFF
    started_at = now_iso()
    results = []
    host_checks = []
    summary = {"total": 0, "passed": 0, "failed": 0}
    aborted = False

    with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
        reader = FrameReader()

        # HELLO handshake (best-effort compatibility with current flow).
        hello_seq8 = 1
        ser.write(build_control(CMD_HELLO, hello_seq8, run_id))
        hello_deadline = time.monotonic() + 2.0
        got_hello_ack = False
        while time.monotonic() < hello_deadline:
            chunk = ser.read(128)
            for v in chunk:
                frame = reader.feed(v)
                if not frame or len(frame) < 2:
                    continue
                if frame[0] == CMD_HELLO_ACK and frame[1] == hello_seq8:
                    got_hello_ack = True
                    break
            if got_hello_ack:
                break
        if not got_hello_ack:
            print("No HELLO_ACK before self-test start.")

        profile_val = 0
        tlvs = bytes([TAG_PROFILE, 1, profile_val]) + bytes([TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
        tlvs += bytes([TAG_TIMEOUT_MS, 4]) + int(args.timeout_ms).to_bytes(4, "little")
        ser.write(build_control(CMD_SELFTEST_START, 2, run_id, tlvs))

        deadline = time.monotonic() + (args.timeout_ms / 1000.0)
        done_seen = False
        while time.monotonic() < deadline:
            chunk = ser.read(256)
            if not chunk:
                continue
            for v in chunk:
                frame = reader.feed(v)
                if not frame or len(frame) < 2:
                    continue
                cmd = frame[0]
                body = frame[2:]
                tlv = parse_tlvs(body)

                if cmd == CMD_SELFTEST_RESULT:
                    test_id = int.from_bytes(tlv.get(TAG_TEST_ID, b"\x00\x00"), "little")
                    name = tlv.get(TAG_NAME, b"").decode("utf-8", errors="replace")
                    passed = bool(tlv.get(TAG_PASS, b"\x00")[0] if tlv.get(TAG_PASS) else 0)
                    metrics_raw = tlv.get(TAG_METRICS, b"").decode("utf-8", errors="replace")
                    results.append(
                        {
                            "test_id": test_id,
                            "name": name,
                            "pass": passed,
                            "metrics": parse_metrics(metrics_raw),
                            "timestamp": now_iso(),
                        }
                    )
                    continue

                if cmd == CMD_SELFTEST_DONE:
                    done_run = int.from_bytes(tlv.get(TAG_RUN_ID, b"\x00\x00\x00\x00"), "little")
                    if done_run != run_id:
                        continue
                    summary = {
                        "total": int.from_bytes(tlv.get(TAG_TOTAL, b"\x00\x00"), "little"),
                        "passed": int.from_bytes(tlv.get(TAG_PASSED, b"\x00\x00"), "little"),
                        "failed": int.from_bytes(tlv.get(TAG_FAILED, b"\x00\x00"), "little"),
                    }
                    aborted = bool(tlv.get(TAG_ABORTED, b"\x00")[0] if tlv.get(TAG_ABORTED) else 0)
                    done_seen = True
                    break
            if done_seen:
                break

        if not done_seen:
            print("Timed out waiting for CMD_SELFTEST_DONE.")
            aborted = True
            rc = 3
        elif aborted:
            rc = 3
        elif summary["failed"] > 0:
            rc = 2
        else:
            rc = 0

        if done_seen:
            goodbye_seq8 = 3
            ser.write(build_control(CMD_GOODBYE, goodbye_seq8, run_id))

            # Wait for BYE_ACK first.
            bye_ack_timeout_ms = 2000
            ack_deadline = time.monotonic() + (bye_ack_timeout_ms / 1000.0)
            got_bye_ack = False
            ack_details = {
                "seq8": goodbye_seq8,
                "run_id": run_id,
                "timeout_ms": bye_ack_timeout_ms,
            }
            while time.monotonic() < ack_deadline and not got_bye_ack:
                chunk = ser.read(128)
                for v in chunk:
                    frame = reader.feed(v)
                    if not frame or len(frame) < 2:
                        continue
                    cmd = frame[0]
                    seq8 = frame[1]
                    if cmd == CMD_BYE_ACK and seq8 == goodbye_seq8:
                        got_bye_ack = True
                        break
                    ack_details["observed_cmd"] = cmd
                    ack_details["observed_seq8"] = seq8

            if got_bye_ack:
                print("GOODBYE ACK received.")
            else:
                print("Timed out waiting for GOODBYE ACK.")
            host_checks.append(
                {
                    "name": "goodbye_ack",
                    "pass": got_bye_ack,
                    "details": ack_details,
                    "timestamp": now_iso(),
                }
            )

            # Wait for BYE_DONE only after BYE_ACK succeeds.
            bye_done_timeout_ms = 3000
            got_bye_done = False
            done_details = {
                "seq8": goodbye_seq8,
                "run_id": run_id,
                "timeout_ms": bye_done_timeout_ms,
            }
            if got_bye_ack:
                done_deadline = time.monotonic() + (bye_done_timeout_ms / 1000.0)
                while time.monotonic() < done_deadline and not got_bye_done:
                    chunk = ser.read(128)
                    for v in chunk:
                        frame = reader.feed(v)
                        if not frame or len(frame) < 2:
                            continue
                        cmd = frame[0]
                        seq8 = frame[1]
                        if cmd != CMD_BYE_DONE:
                            done_details["observed_cmd"] = cmd
                            done_details["observed_seq8"] = seq8
                            continue
                        if seq8 != goodbye_seq8:
                            done_details["observed_cmd"] = cmd
                            done_details["observed_seq8"] = seq8
                            continue
                        tlv = parse_tlvs(frame[2:])
                        seq32 = None
                        if TAG_SEQ32 in tlv and len(tlv[TAG_SEQ32]) == 4:
                            seq32 = int.from_bytes(tlv[TAG_SEQ32], "little")
                            done_details["observed_seq32"] = seq32
                            if seq32 != run_id:
                                continue
                        got_bye_done = True
                        break
            else:
                done_details["skipped"] = "BYE_ACK not received"

            if got_bye_done:
                print("GOODBYE DONE received.")
            else:
                print("Timed out waiting for GOODBYE DONE.")
            host_checks.append(
                {
                    "name": "goodbye_done",
                    "pass": got_bye_done,
                    "details": done_details,
                    "timestamp": now_iso(),
                }
            )

            if not (got_bye_ack and got_bye_done):
                rc = 3

        report = {
            "run_id": run_id,
            "profile": profile,
            "started_at": started_at,
            "finished_at": now_iso(),
            "aborted": aborted,
            "summary": summary,
            "results": results,
            "host_checks": host_checks,
        }
        write_json_atomic(args.out, report)
        print(f"Wrote self-test report: {args.out}")
        return rc


def main() -> int:
    p = argparse.ArgumentParser(description="Run LabCraft SAFE firmware self-test and write JSON report.")
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--profile", default="SAFE")
    p.add_argument("--timeout-ms", type=int, default=30000)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted.")
        return 3
    except Exception as e:
        print(f"Self-test runner error: {e}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
