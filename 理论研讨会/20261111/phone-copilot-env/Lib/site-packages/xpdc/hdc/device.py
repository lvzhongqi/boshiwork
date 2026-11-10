import re
from pathlib import Path, PurePath

from .._base import DeviceBase
from ..screenshot import Screenshot
from ..utils import exec_cmd, now_str


class HDCDevice(DeviceBase):
    def __init__(self, *, device_id: str, hdc: str):
        self.device_id = device_id
        self._hdc = hdc

    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._hdc, '-t', self.device_id] + cmd
        return exec_cmd(cmd, timeout=timeout)

    def shell(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._hdc, '-t', self.device_id, 'shell'] + cmd
        return exec_cmd(cmd, timeout=timeout)

    def tap(self, x: int, y: int) -> str:
        return self.shell(['uitest', 'uiInput', 'click', str(x), str(y)])

    def double_tap(self, x: int, y: int) -> str:
        return self.shell(['uitest', 'uiInput', 'doubleClick', str(x), str(y)])

    def long_press(self, x: int, y: int, *, duration_ms: int = 3000) -> str:
        return self.shell(['uitest', 'uiInput', 'longClick', str(x), str(y)])

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, *, duration_ms: int = None) -> str:
        if duration_ms is None:
            dist_sq = (start_x - end_x) ** 2 + (start_y - end_y) ** 2
            duration_ms = int(dist_sq / 1000)
            duration_ms = max(1000, min(duration_ms, 2000))  # Clamp between 1000-2000ms

        return self.shell(
            ['uitest', 'uiInput', 'swipe', str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)]
        )

    def back(self) -> str:
        return self.shell(['uitest', 'uiInput', 'keyEvent', 'Back'])

    def home(self) -> str:
        return self.shell(['uitest', 'uiInput', 'keyEvent', 'Home'])

    def launch_app(self, bundle: str, ability: str = 'EntryAbility') -> str:
        return self.shell(['aa', 'start', '-b', bundle, '-a', ability])

    def stop_app(self, bundle: str) -> str:
        return self.shell(['aa', 'force-stop', bundle])

    def type_text(self, text: str) -> str:
        return self.shell(['uitest', 'uiInput', 'text', text])

    def clear_text(self) -> str:
        # Ctrl + A
        self.shell(['uitest', 'uiInput', 'keyEvent', '2072', '2017'])
        # Delete
        return self.shell(['uitest', 'uiInput', 'keyEvent', '2055'])

    def screenshot(self, path: Path = None) -> Screenshot:
        remote_path = PurePath('/data/local/tmp/tmp_screenshot.jpeg')
        path = path or Path(f'hdc-{self.device_id}-{now_str()}.png')

        self.shell(['snapshot_display', '-f', remote_path])
        self.cmd(['file', 'recv', remote_path, path])

        return Screenshot(path)

    def get_current_app(self) -> str:
        out = self.shell(['aa', 'dump', '-l'])

        foreground_bundle = current_bundle = None

        for line in out.split('\n'):
            if 'app name [' in line:
                if match := re.search(r'\[([^]]+)]', line):
                    current_bundle = match.group(1)

            if 'state #foreground' in line.lower():
                if current_bundle:
                    foreground_bundle = current_bundle
                    break

            if 'Mission ID' in line:
                current_bundle = None

        return foreground_bundle or ''

    def dump_bundles(self) -> str:
        return self.shell(['bm', 'dump', '-a'])

    def dump_bundle(self, bundle: str, *, shortcut: bool = False) -> str:
        cmd = ['bm', 'dump', '-n', bundle]
        if shortcut:
            cmd.append('-s')

        return self.shell(cmd)

    def clean_cache(self, bundle: str) -> str:
        return self.shell(['bm', 'clean', '-c', '-n', bundle])

    def clean_data(self, bundle: str) -> str:
        return self.shell(['bm', 'clean', '-d', '-n', bundle])
