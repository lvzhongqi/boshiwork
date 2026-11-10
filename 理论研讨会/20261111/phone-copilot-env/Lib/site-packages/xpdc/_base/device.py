from abc import ABC, abstractmethod
from pathlib import Path

from xpdc.screenshot import Screenshot


class DeviceBase(ABC):
    @abstractmethod
    def cmd(self, cmd: list[str], *, timeout: int = 10) -> str:
        pass

    @abstractmethod
    def shell(self, cmd: list[str], *, timeout: int = 10) -> str:
        pass

    @abstractmethod
    def tap(self, x: int, y: int) -> str:
        pass

    @abstractmethod
    def double_tap(self, x: int, y: int) -> str:
        pass

    @abstractmethod
    def long_press(self, x: int, y: int, *, duration_ms: int = 3000) -> str:
        pass

    @abstractmethod
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, *, duration_ms: int = None) -> str:
        pass

    @abstractmethod
    def back(self) -> str:
        pass

    @abstractmethod
    def home(self) -> str:
        pass

    @abstractmethod
    def launch_app(self, bundle: str, ability: str) -> str:
        pass

    @abstractmethod
    def stop_app(self, bundle: str) -> str:
        pass

    @abstractmethod
    def type_text(self, text: str) -> str:
        pass

    @abstractmethod
    def clear_text(self) -> str:
        pass

    @abstractmethod
    def screenshot(self, path: Path = None) -> Screenshot:
        pass

    @abstractmethod
    def get_current_app(self) -> str:
        pass

    @abstractmethod
    def dump_bundles(self) -> str:
        pass

    @abstractmethod
    def dump_bundle(self, bundle: str, *, shortcut: bool = False) -> str:
        pass

    @abstractmethod
    def clean_cache(self, bundle: str) -> str:
        pass

    @abstractmethod
    def clean_data(self, bundle: str) -> str:
        pass
