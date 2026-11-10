import os
from shutil import which

from loguru import logger

from .._base import ConnectionBase
from ..utils import exec_cmd
from .device import HDCDevice


class HDCConnection(ConnectionBase):
    def __init__(self, *, hdc: str = None):
        self._hdc = hdc or which('hdc')

        if not self._hdc:
            raise FileNotFoundError('No [hdc] provided, and not configured in $PATH')

        if not os.access(self._hdc, os.X_OK):
            raise PermissionError(f'`{self._hdc}` is not executable')

        logger.debug(f'hdc initialized with path: {self._hdc}')

    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        cmd = [self._hdc] + cmd
        return exec_cmd(cmd, timeout=timeout)

    @property
    def devices(self) -> list['HDCDevice']:
        out = self.cmd(['list', 'targets'])

        devices = []

        for line in out.split('\n'):
            if not line.strip() or line.strip() == '[Empty]':
                continue

            devices.append(HDCDevice(device_id=line.split()[0], hdc=self._hdc))

        return devices

    def device(self, device_id: str) -> 'HDCDevice':
        return HDCDevice(device_id=device_id, hdc=self._hdc)
