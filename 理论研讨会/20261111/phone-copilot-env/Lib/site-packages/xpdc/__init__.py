from enum import StrEnum

from .adb import ADBConnection
from .hdc import HDCConnection


class DeviceType(StrEnum):
    ADB = 'adb'
    HDC = 'hdc'
    # IOS = 'ios'


def connection(device_type: DeviceType) -> ADBConnection | HDCConnection:
    match device_type:
        case DeviceType.ADB:
            return ADBConnection()
        case DeviceType.HDC:
            return HDCConnection()
        case _:
            raise ValueError(f'Invalid DeviceType: {device_type}')
