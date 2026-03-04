import datetime as dt

import Machine_FreeRTOS as mfr


def test_wait_edge_events_compat_supports_timedelta_only_waiters():
    seen = {"arg": None}

    def _wait(arg):
        if isinstance(arg, dt.timedelta):
            seen["arg"] = arg
            return True
        raise TypeError("'float' object cannot be interpreted as an integer")

    ok = mfr._wait_edge_events_compat(_wait, 0.25)
    assert ok is True
    assert isinstance(seen["arg"], dt.timedelta)


def test_wait_edge_events_compat_supports_integer_only_waiters():
    calls = []

    def _wait(arg):
        calls.append(arg)
        if isinstance(arg, int):
            return False
        raise TypeError("'float' object cannot be interpreted as an integer")

    ok = mfr._wait_edge_events_compat(_wait, 1.0)
    assert ok is False
    assert any(isinstance(v, int) for v in calls)


def test_wait_edge_events_compat_supports_two_arg_waiters():
    seen = {"args": None}

    def _wait(*args, **kwargs):
        if len(args) == 2 and all(isinstance(v, int) for v in args):
            seen["args"] = args
            return True
        if "sec" in kwargs and "nsec" in kwargs:
            seen["args"] = (kwargs["sec"], kwargs["nsec"])
            return True
        raise TypeError("bad timeout signature")

    ok = mfr._wait_edge_events_compat(_wait, 0.4)
    assert ok is True
    assert seen["args"] is not None


def test_wait_edge_events_compat_raises_when_no_signature_matches():
    def _wait(*args, **kwargs):
        raise TypeError("always bad")

    try:
        mfr._wait_edge_events_compat(_wait, 0.1)
        assert False, "Expected TypeError"
    except TypeError as e:
        assert "Unable to call edge wait" in str(e)
