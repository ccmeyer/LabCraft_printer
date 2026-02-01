class NullCamera:
    def start_camera(self): return
    def stop_camera(self): return
    def capture_image(self): return None
    def capture_with_retry_async(self, *args, **kwargs): return None
    def change_exposure_time(self, *args, **kwargs): return None
    def led_on(self): return
    def led_off(self): return

class NullLog:
    def start(self): return
    def stop(self): return