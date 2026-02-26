from types import SimpleNamespace

from Machine_FreeRTOS import Machine

def test_connect_board_retry_does_not_leak_reader_or_serial(qapp, test_profile, fake_serial_factory):
    factory = fake_serial_factory
    machine = Machine(SimpleNamespace(), profile=test_profile, serial_factory=factory)
    machine.begin_reader_thread = lambda: None
    machine._start_ack_wait = lambda *a, **k: None

    machine.connect_board("COM_TEST")
    assert len(factory.instances) == 1
    first = factory.instances[0]
    assert first.is_open is True

    machine._hello_timeout()
    assert len(factory.instances) == 2
    second = factory.instances[1]
    assert first.is_open is False
    assert second.is_open is True

    machine._hello_timeout()
    assert len(factory.instances) == 3
    third = factory.instances[2]
    assert second.is_open is False
    assert third.is_open is True
