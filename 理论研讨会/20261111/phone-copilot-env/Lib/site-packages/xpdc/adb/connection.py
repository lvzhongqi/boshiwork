import os
from shutil import which

from loguru import logger

from .._base import ConnectionBase
from ..utils import exec_cmd
from .device import ADBDevice


class ADBConnection(ConnectionBase):
    def __init__(self, *, adb: str = None):
        self._adb = adb or which('adb')

        if not self._adb:
            raise FileNotFoundError('No [adb] provided, and not configured in $PATH')

        if not os.access(self._adb, os.X_OK):
            raise PermissionError(f'`{self._adb}` is not executable')

        logger.debug(f'ADB initialized with path: {self._adb}')

    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._adb] + cmd
        return exec_cmd(cmd, timeout=timeout)

    @property
    def devices(self) -> list['ADBDevice']:
        out = self.cmd(['devices', '-l'])

        devices = []

        for line in out.split('\n')[1:]:  # Skip 'List of devices attached'
            if not line.strip():
                continue

            devices.append(ADBDevice(device_id=line.split()[0], adb=self._adb))

        return devices

    def device(self, device_id: str) -> 'ADBDevice':
        return ADBDevice(device_id=device_id, adb=self._adb)
