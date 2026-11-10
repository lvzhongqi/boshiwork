import base64
import re
import subprocess
import time
from pathlib import Path

from loguru import logger

from .._base import DeviceBase
from ..resource import ADB_KEYBOARD_APK
from ..screenshot import Screenshot
from ..utils import exec_cmd, now_str


class ADBDevice(DeviceBase):
    def __init__(self, *, device_id: str, adb: str):
        self.device_id = device_id
        self._adb = adb

    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._adb, '-s', self.device_id] + cmd
        return exec_cmd(cmd, timeout=timeout)

    def shell(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._adb, '-s', self.device_id, 'shell'] + cmd
        return exec_cmd(cmd, timeout=timeout)

    def tap(self, x: int, y: int) -> str:
        return self.shell(['input', 'tap', str(x), str(y)])

    def double_tap(self, x: int, y: int) -> str:
        self.shell(['input', 'tap', str(x), str(y)])
        return self.shell(['input', 'tap', str(x), str(y)])

    def long_press(self, x: int, y: int, *, duration_ms: int = 3000) -> str:
        return self.shell(['input', 'swipe', str(x), str(y), str(x), str(y), str(duration_ms)])

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, *, duration_ms: int = None) -> str:
        if duration_ms is None:
            dist_sq = (start_x - end_x) ** 2 + (start_y - end_y) ** 2
            duration_ms = int(dist_sq / 1000)
            duration_ms = max(1000, min(duration_ms, 2000))  # Clamp between 1000-2000ms

        return self.shell(['input', 'swipe', str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)])

    def back(self) -> str:
        return self.shell(['input', 'keyevent', 'KEYCODE_BACK'])

    def home(self) -> str:
        return self.shell(['input', 'keyevent', 'KEYCODE_HOME'])

    def launch_app(self, bundle: str, ability: str = None) -> str:
        return self.shell(['monkey', '-p', bundle, '-c', 'android.intent.category.LAUNCHER', '1'])

    def stop_app(self, bundle: str) -> str:
        return self.shell(['am', 'force-stop', bundle])

    def type_text(self, text: str) -> str:
        encoded_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')

        return self.shell(['am', 'broadcast', '-a', 'ADB_INPUT_B64', '--es', 'msg', encoded_text])

    def clear_text(self) -> str:
        return self.shell(['am', 'broadcast', '-a', 'ADB_CLEAR_TEXT'])

    def install_and_set_adb_keyboard(self) -> str:
        # Get current IME
        out = self.shell(['settings', 'get', 'secure', 'default_input_method'])

        if 'com.android.adbkeyboard/.AdbIME' in out:
            return out

        # Check weather ADBKeyboard.apk installed
        try:
            self.shell(['pm', 'path', 'com.android.adbkeyboard'])
        except subprocess.CalledProcessError:
            logger.info('ADBKeyboard.apk is not installed, try to install it')
            self.cmd(['install', str(ADB_KEYBOARD_APK)])
            time.sleep(0.1)

        logger.info('Enable input method [com.android.adbkeyboard]')
        self.shell(['ime', 'enable', 'com.android.adbkeyboard/.AdbIME'])

        logger.info('Set default input method to [com.android.adbkeyboard]')
        return self.shell(['ime', 'set', 'com.android.adbkeyboard/.AdbIME'])

    def screenshot(self, path: Path = None) -> Screenshot:
        path = path or Path(f'adb-{self.device_id}-{now_str()}.png')

        cmd = [self._adb, '-s', self.device_id, 'shell', 'screencap', '-p']
        logger.debug(f'Executing command: {cmd}')

        with open(path, 'wb') as f:
            subprocess.run(cmd, stdout=f, check=True, timeout=30)  # noqa: S603

        return Screenshot(path)

    def get_current_app(self) -> str:
        out = self.shell(['dumpsys', 'window'])

        re_current = re.compile(r'mCurrentFocus=Window\{\S+\s+\S+\s+(?P<bundle>[^\s/]+)/(?P<ability>[^\s}]+)}')
        re_focused = re.compile(r'mFocusedApp=ActivityRecord\{\S+\s+\S+\s+(?P<bundle>[^\s/]+)/(?P<ability>[^\s}]+)')

        if m := (re_current.search(out) or re_focused.search(out)):
            return m['bundle']

        return ''

    def dump_bundles(self) -> str:
        return self.shell(['pm', 'list', 'packages'])

    def dump_bundle(self, bundle: str, *, shortcut: bool = False) -> str:
        cmd = ['dumpsys', 'package', '--checkin', bundle] if shortcut else ['dumpsys', 'package', bundle]

        return self.shell(cmd)

    def clean_cache(self, bundle: str) -> str:
        return self.shell(['pm', 'clear', '--cache-only', bundle])

    def clean_data(self, bundle: str) -> str:
        return self.shell(['pm', 'clear', bundle])
