"""
Pixoo 64 client implementation for communicating with Divoom hardware.
"""

import base64
import time
import requests
from PIL import Image

DIVOOM_DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"


class PixooClient:
    def __init__(self, ip: str = "", timeout: float = 8.0):
        self.ip = ip.strip()
        self.timeout = timeout
        self.post_url = f"http://{self.ip}/post" if self.ip else ""

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

    def ping(self, retries: int = 2) -> bool:
        """
        Pings the device with a lightweight config query to verify communication.
        """
        if not self.post_url:
            return False
        for _ in range(retries):
            try:
                resp = requests.post(
                    self.post_url,
                    json={"Command": "Channel/GetAllConf"},
                    timeout=5.0,
                )
                if resp.status_code == 200 and resp.json().get("error_code") == 0:
                    return True
            except Exception:
                time.sleep(0.4)
        return False

    def send_image(self, img: Image.Image, retries: int = 2) -> bool:
        """
        Sends a 64x64 PIL Image to the Pixoo 64 display.
        """
        if not self.post_url:
            if not self.ensure_connected():
                return False

        # Make sure image is RGB 64x64
        if img.size != (64, 64) or img.mode != "RGB":
            img = img.convert("RGB").resize((64, 64))

        raw_bytes = img.tobytes()
        b64_data = base64.b64encode(raw_bytes).decode("ascii")

        for attempt in range(retries + 1):
            try:
                # 1. Reset GIF ID on device
                r1 = requests.post(
                    self.post_url,
                    json={"Command": "Draw/ResetHttpGifId"},
                    timeout=self.timeout,
                )
                if r1.status_code != 200:
                    time.sleep(0.3)
                    continue

                # Small delay to let device internal state clear
                time.sleep(0.15)

                # 2. Push frame
                r2 = requests.post(
                    self.post_url,
                    json={
                        "Command": "Draw/SendHttpGif",
                        "PicNum": 1,
                        "PicWidth": 64,
                        "PicOffset": 0,
                        "PicID": 1,
                        "PicSpeed": 1000,
                        "PicData": b64_data,
                    },
                    timeout=self.timeout,
                )
                if r2.status_code == 200 and r2.json().get("error_code") == 0:
                    return True
            except (requests.RequestException, TimeoutError):
                if attempt < retries:
                    time.sleep(0.5)

        return False

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
        try:
            resp = requests.post(
                self.post_url,
                json={"Command": "Channel/SetBrightness", "Brightness": level},
                timeout=4.0,
            )
            return resp.status_code == 200 and resp.json().get("error_code") == 0
        except Exception:
            return False

    def get_brightness(self) -> int:
        """
        Returns current brightness level (0-100).
        """
        if not self.post_url and not self.ensure_connected():
            return 100
        try:
            resp = requests.post(
                self.post_url,
                json={"Command": "Channel/GetAllConf"},
                timeout=4.0,
            )
            if resp.status_code == 200:
                return resp.json().get("Brightness", 100)
        except Exception:
            pass
        return 100
