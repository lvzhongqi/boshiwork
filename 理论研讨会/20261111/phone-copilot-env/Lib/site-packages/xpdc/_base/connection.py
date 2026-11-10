from abc import ABC, abstractmethod

from .device import DeviceBase


class ConnectionBase(ABC):
    @abstractmethod
    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        pass

    @property
    @abstractmethod
    def devices(self) -> list['DeviceBase']:
        pass

    @abstractmethod
    def device(self, device_id: str) -> 'DeviceBase':
        pass
