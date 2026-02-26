from types import SimpleNamespace

from Machine_FreeRTOS import CLEAR_ACK, Machine


class _FakeTimer:
    def __init__(self):
        self.stopped = False
        self.deleted = False

    def stop(self):
        self.stopped = True

    def deleteLater(self):
        self.deleted = True


def _entry(counter):
    t = _FakeTimer()
    return {
        "timer": t,
        "ok": lambda: counter.__setitem__("ok", counter["ok"] + 1),
        "to": lambda: counter.__setitem__("to", counter["to"] + 1),
        "_timer_obj": t,
    }


def test_on_any_ack_matches_seq32_key_when_present(qapp, test_profile):
    m = Machine(SimpleNamespace(), profile=test_profile)
    counter = {"ok": 0, "to": 0}
    e = _entry(counter)
    key = m._ack_key(CLEAR_ACK, 1234, None)
    m._pending_acks[key] = {k: v for k, v in e.items() if not k.startswith("_")}

    m._on_any_ack({"ack_cmd": CLEAR_ACK, "seq8": 210, "seq32": 1234})

    assert counter["ok"] == 1
    assert counter["to"] == 0
    assert e["_timer_obj"].stopped is True
    assert e["_timer_obj"].deleted is True
    assert key not in m._pending_acks


def test_on_any_ack_falls_back_to_seq8_when_seq32_absent(qapp, test_profile):
    m = Machine(SimpleNamespace(), profile=test_profile)
    counter = {"ok": 0, "to": 0}
    e = _entry(counter)
    key = m._ack_key(CLEAR_ACK, None, 77)
    m._pending_acks[key] = {k: v for k, v in e.items() if not k.startswith("_")}

    m._on_any_ack({"ack_cmd": CLEAR_ACK, "seq8": 77, "seq32": None})

    assert counter["ok"] == 1
    assert key not in m._pending_acks


def test_on_any_ack_does_not_fallback_to_seq8_when_seq32_present_but_mismatched(qapp, test_profile):
    m = Machine(SimpleNamespace(), profile=test_profile)
    counter = {"ok": 0, "to": 0}
    e = _entry(counter)
    key = m._ack_key(CLEAR_ACK, None, 77)
    m._pending_acks[key] = {k: v for k, v in e.items() if not k.startswith("_")}

    m._on_any_ack({"ack_cmd": CLEAR_ACK, "seq8": 77, "seq32": 9999})

    assert counter["ok"] == 0
    assert key in m._pending_acks


def test_on_any_ack_duplicate_ack_only_consumes_once(qapp, test_profile):
    m = Machine(SimpleNamespace(), profile=test_profile)
    counter = {"ok": 0, "to": 0}
    e = _entry(counter)
    key = m._ack_key(CLEAR_ACK, 88, None)
    m._pending_acks[key] = {k: v for k, v in e.items() if not k.startswith("_")}

    ack = {"ack_cmd": CLEAR_ACK, "seq8": 88, "seq32": 88}
    m._on_any_ack(ack)
    m._on_any_ack(ack)

    assert counter["ok"] == 1
    assert key not in m._pending_acks
