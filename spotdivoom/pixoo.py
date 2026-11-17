"""
Pixoo 64 client implementation for communicating with Divoom hardware.

The Pixoo 64 is easy to overwhelm with HTTP requests (it can freeze until power-cycled),
so every command goes through one lock, and the dashboard reads a cached status instead
of querying the device on each poll.
"""

import base64
import threading
import time
from typing import Optional

import requests
from PIL import Image

DIVOOM_DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"
STATUS_MAX_AGE = 30.0


class PixooClient:
    def __init__(self, ip: str = "", timeout: float = 8.0):
        self.ip = ip.strip()
        self.timeout = timeout
        self.post_url = f"http://{self.ip}/post" if self.ip else ""
        # Serializes all device traffic: the daemon thread and web requests share one client
        self._lock = threading.RLock()
        self._status: dict = {"connected": False, "brightness": 100}
        self._status_time: float = 0

    @staticmethod
    def discover_devices(timeout: float = 5.0) -> list[dict]:
        """
        Queries Divoom's cloud router API to discover devices on the current LAN.
        """
        try:
            resp = requests.post(DIVOOM_DISCOVERY_URL, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ReturnCode") == 0:
                    return data.get("DeviceList", [])
        except Exception:
            pass
        return []

    def ensure_connected(self) -> bool:
        """
        Verifies connectivity to the Pixoo device, auto-discovering IP if not set.
        """
        if not self.ip:
            devices = self.discover_devices()
            if not devices:
                return False
            # Look for Pixoo-64 or take first available
            pixoo_device = next(
                (d for d in devices if "64" in d.get("DeviceName", "")),
                devices[0]
            )
            self.ip = pixoo_device.get("DevicePrivateIP", "")
            if not self.ip:
                return False
            self.post_url = f"http://{self.ip}/post"

        return self.ping()

    def _command(self, payload: dict, timeout: Optional[float] = None) -> Optional[dict]:
        """
        Sends one command and returns the JSON reply, or None on any failure.
        """
        if not self.post_url:
            return None
        with self._lock:
            try:
                resp = requests.post(self.post_url, json=payload, timeout=timeout or self.timeout)
                if resp.status_code == 200:
                    return resp.json()
            except (requests.RequestException, ValueError):
                pass
        return None

    def _remember_status(self, connected: bool, brightness: Optional[int] = None):
        self._status = {
            "connected": connected,
            "brightness": brightness if brightness is not None else self._status.get("brightness", 100),
        }
        self._status_time = time.time()

    def ping(self, retries: int = 2) -> bool:
        """
        Pings the device with a lightweight config query to verify communication.
        """
        for attempt in range(retries):
            data = self._command({"Command": "Channel/GetAllConf"}, timeout=5.0)
            if data is not None and data.get("error_code") == 0:
                self._remember_status(True, data.get("Brightness"))
                return True
            if attempt < retries - 1:
                time.sleep(0.4)
        self._remember_status(False)
        return False

    def get_status(self, max_age: float = STATUS_MAX_AGE) -> dict:
        """
        Returns {'connected', 'brightness'}, querying the device at most every `max_age` seconds.
        """
        if time.time() - self._status_time > max_age:
            self.ping(retries=1)
        return dict(self._status)

    def send_image(self, img: Image.Image, retries: int = 2) -> bool:
        """
        Sends a 64x64 PIL Image to the Pixoo 64 display.
        """
        return self.send_frames([img], retries=retries)

    def send_frames(self, frames: list[Image.Image], speed_ms: int = 1000, retries: int = 2) -> bool:
        """
        Sends one or more 64x64 frames as a single animation (the device loops multi-frame ones).
        """
        if not self.post_url and not self.ensure_connected():
            return False

        encoded = []
        for img in frames:
            if img.size != (64, 64) or img.mode != "RGB":
                img = img.convert("RGB").resize((64, 64))
            encoded.append(base64.b64encode(img.tobytes()).decode("ascii"))

        with self._lock:
            for attempt in range(retries + 1):
                # 1. Reset GIF ID on device
                reset = self._command({"Command": "Draw/ResetHttpGifId"})
                if reset is None:
                    if attempt < retries:
                        time.sleep(0.5)
                    continue

                # Small delay to let device internal state clear
                time.sleep(0.15)

                # 2. Push frames
                ok = True
                for offset, data in enumerate(encoded):
                    reply = self._command({
                        "Command": "Draw/SendHttpGif",
                        "PicNum": len(encoded),
                        "PicWidth": 64,
                        "PicOffset": offset,
                        "PicID": 1,
                        "PicSpeed": speed_ms,
                        "PicData": data,
                    })
                    if reply is None or reply.get("error_code") != 0:
                        ok = False
                        break
                if ok:
                    self._remember_status(True)
                    return True
                if attempt < retries:
                    time.sleep(0.5)

        self._remember_status(False)
        return False

    def send_scrolling_text(self, text: str, y: int, color: str = "#FFFFFF", speed_ms: int = 60, font: int = 2) -> bool:
        """
        Scrolls text across the current frame using the device's own text engine,
        so the scroll costs one request instead of a frame per step.
        """
        reply = self._command({
            "Command": "Draw/SendHttpText",
            "TextId": 1,
            "x": 0,
            "y": max(0, min(56, int(y))),
            "dir": 0,
            "font": font,
            "TextWidth": 64,
            "speed": speed_ms,
            "TextString": text[:500],
            "color": color,
            "align": 1,
        })
        return reply is not None and reply.get("error_code") == 0

    def clear_text(self) -> bool:
        reply = self._command({"Command": "Draw/ClearHttpText"})
        return reply is not None and reply.get("error_code") == 0

    def set_screen_on(self, on: bool) -> bool:
        reply = self._command({"Command": "Channel/OnOffScreen", "OnOff": 1 if on else 0}, timeout=4.0)
        return reply is not None and reply.get("error_code") == 0

    def clear(self) -> bool:
        """
        Clears the display with a blank screen.
        """
        blank = Image.new("RGB", (64, 64), color=(0, 0, 0))
        return self.send_image(blank)

    def set_brightness(self, level: int) -> bool:
        """
        Sets display brightness level from 0 to 100.
        """
        level = max(0, min(100, int(level)))
        if not self.post_url and not self.ensure_connected():
            return False
        reply = self._command({"Command": "Channel/SetBrightness", "Brightness": level}, timeout=4.0)
        ok = reply is not None and reply.get("error_code") == 0
        if ok:
            self._remember_status(True, level)
        return ok

    def get_brightness(self) -> int:
        """
        Returns current brightness level (0-100), from the cached status.
        """
        return int(self.get_status().get("brightness", 100))
