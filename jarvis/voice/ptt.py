"""Push-to-Talk (PTT) controller using native Windows GetAsyncKeyState and programmatic triggers."""

import ctypes
import threading
import time
from typing import Callable

from jarvis.utils.logging import logger

# Virtual Key Codes on Windows
VK_CONTROL = 0x11
VK_SPACE = 0x20


class PTTController:
    """Manages Push-to-Talk state via hotkey monitoring (e.g. Ctrl+Space) or manual programmatic calls."""

    def __init__(
        self,
        on_press: Callable[[], None] | None = None,
        on_release: Callable[[], None] | None = None,
        poll_interval: float = 0.02,
    ) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.poll_interval = poll_interval

        self._is_pressed = False
        self._is_monitoring = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_pressed(self) -> bool:
        return self._is_pressed

    def press(self) -> None:
        """Trigger PTT press (active speech capture)."""
        with self._lock:
            if not self._is_pressed:
                self._is_pressed = True
                logger.debug("PTT activated (pressed).")
                if self.on_press:
                    try:
                        self.on_press()
                    except Exception as ex:
                        logger.error("Error in PTT on_press callback: %s", ex)

    def release(self) -> None:
        """Trigger PTT release (end of user speech turn)."""
        with self._lock:
            if self._is_pressed:
                self._is_pressed = False
                logger.debug("PTT deactivated (released).")
                if self.on_release:
                    try:
                        self.on_release()
                    except Exception as ex:
                        logger.error("Error in PTT on_release callback: %s", ex)

    def start_hotkey_listener(self) -> None:
        """Start background polling thread checking for Ctrl+Space keypresses on Windows."""
        if self._is_monitoring:
            return

        self._is_monitoring = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self._thread.start()
        logger.info("PTT hotkey listener started (Hold [Ctrl+Space] to speak).")

    def stop_hotkey_listener(self) -> None:
        """Stop background hotkey polling thread."""
        if not self._is_monitoring:
            return

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
        self._is_monitoring = False
        logger.debug("PTT hotkey listener stopped.")

    def _monitor_worker(self) -> None:
        """Background thread polling Windows GetAsyncKeyState."""
        user32 = ctypes.windll.user32

        while not self._stop_event.is_set():
            ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            space_down = bool(user32.GetAsyncKeyState(VK_SPACE) & 0x8000)
            hotkey_held = ctrl_down and space_down

            if hotkey_held and not self._is_pressed:
                self.press()
            elif not hotkey_held and self._is_pressed:
                self.release()

            time.sleep(self.poll_interval)
