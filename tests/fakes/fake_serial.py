import threading


class FakeSerialMain:
    def __init__(self, inbound: bytes = b""):
        self._buf = bytearray(inbound)
        self._lock = threading.Lock()
        self.writes = []
        self.is_open = True
        self.name = "FAKE_MAIN"

    def append_inbound(self, data: bytes):
        with self._lock:
            self._buf.extend(data)

    def read(self, n: int) -> bytes:
        with self._lock:
            if not self.is_open:
                return b""
            if not self._buf:
                self.is_open = False
                return b""
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out

    def read_until(self, expected=b"\n", size=1024) -> bytes:
        with self._lock:
            if not self.is_open:
                return b""
            if not self._buf:
                self.is_open = False
                return b""
            data = bytes(self._buf[:size])
            self._buf.clear()
            return data

    def write(self, data: bytes):
        if not self.is_open:
            raise OSError("serial closed")
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        if not self.is_open:
            raise OSError("serial closed")

    def reset_input_buffer(self):
        with self._lock:
            self._buf.clear()

    def cancel_read(self):
        self.is_open = False

    def close(self):
        self.is_open = False


class FakeSerialLog(FakeSerialMain):
    def __init__(self, lines: list[str] | None = None):
        payload = b""
        if lines:
            payload = b"".join((line.rstrip("\n") + "\n").encode("ascii", errors="ignore") for line in lines)
        super().__init__(payload)
        self.name = "FAKE_LOG"


class FakeSerialFactory:
    def __init__(self, main_inbound: bytes = b"", log_lines: list[str] | None = None):
        self.main_inbound = main_inbound
        self.log_lines = log_lines or []
        self.instances = []

    def __call__(self, port, baud, timeout=0.1):
        if str(port) == "/dev/ttyUSB0":
            ser = FakeSerialLog(self.log_lines)
        else:
            ser = FakeSerialMain(self.main_inbound)
        self.instances.append(ser)
        return ser
