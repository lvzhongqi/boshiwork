"""Minimal OLE2 / Compound File Binary reader — enough to pull named streams.

A legacy ``.doc`` is a tiny filesystem in a file: 512-byte sectors chained
through a FAT, small streams packed into a mini-stream chained through a mini
FAT, and a red-black directory whose entries name each stream. Only what
``extractor`` needs is implemented: list the directory, read a stream whole.
Everything else in the format — storages, timestamps, the CLSIDs — is skipped.

Reference: [MS-CFB], Compound File Binary File Format.
"""
from __future__ import annotations

import struct

_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HEADER_SIZE = 512
_DIR_ENTRY_SIZE = 128
_FREE_SECT = 0xFFFFFFFF
_END_OF_CHAIN = 0xFFFFFFFE
_MAX_CHAIN = 1 << 22  # A chain longer than this is a loop, not a document.

_TYPE_STREAM = 2
_TYPE_ROOT = 5


class CompoundFile:
    """Random access to the named streams of one compound file."""

    def __init__(self, data: bytes) -> None:
        if not data.startswith(_SIGNATURE):
            raise RuntimeError(
                "Not an OLE compound file: signature mismatch"
            )
        if len(data) < _HEADER_SIZE:
            raise RuntimeError(
                f"OLE compound file truncated: {len(data)} bytes, header needs "
                f"{_HEADER_SIZE}"
            )
        self._data = data
        self._sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self._mini_sector_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
        if self._sector_size not in (512, 4096):
            raise RuntimeError(
                f"Unsupported OLE sector size: {self._sector_size}"
            )
        self._first_dir = struct.unpack_from("<I", data, 0x30)[0]
        self._mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
        self._first_mini_fat = struct.unpack_from("<I", data, 0x3C)[0]
        self._n_mini_fat = struct.unpack_from("<I", data, 0x40)[0]
        self._first_difat = struct.unpack_from("<I", data, 0x44)[0]
        self._n_difat = struct.unpack_from("<I", data, 0x48)[0]
        self._n_fat = struct.unpack_from("<I", data, 0x2C)[0]

        self._fat = self._read_fat()
        self._entries = self._read_directory()
        self._mini_fat = self._read_mini_fat()
        self._mini_stream = self._read_mini_stream()

    # -- public ------------------------------------------------------------

    def entry_names(self) -> list[str]:
        return [name for name, _type, _sect, _size in self._entries]

    def read_stream(self, name: str) -> bytes:
        for entry_name, entry_type, start, size in self._entries:
            if entry_name == name and entry_type == _TYPE_STREAM:
                return self._read_chain_bytes(start, size, use_mini=size < self._mini_cutoff)
        raise RuntimeError(
            f"OLE compound file has no stream named {name!r} "
            f"(streams: {sorted(self.entry_names())[:20]})"
        )

    # -- sectors -----------------------------------------------------------

    def _sector_offset(self, sector: int) -> int:
        return _HEADER_SIZE + sector * self._sector_size

    def _sector_bytes(self, sector: int) -> bytes:
        start = self._sector_offset(sector)
        end = start + self._sector_size
        if end > len(self._data):
            raise RuntimeError(
                f"OLE sector {sector} runs past end of file "
                f"({end} > {len(self._data)})"
            )
        return self._data[start:end]

    def _read_fat(self) -> list[int]:
        sectors = list(struct.unpack_from("<109I", self._data, 0x4C))
        # DIFAT continuation sectors: (sector_size/4 - 1) entries then a link.
        per_sector = self._sector_size // 4
        sector = self._first_difat
        seen = 0
        while sector not in (_END_OF_CHAIN, _FREE_SECT) and seen < self._n_difat:
            block = self._sector_bytes(sector)
            entries = struct.unpack_from(f"<{per_sector}I", block, 0)
            sectors.extend(entries[:-1])
            sector = entries[-1]
            seen += 1

        fat: list[int] = []
        for i, sect in enumerate(sectors):
            if sect in (_FREE_SECT, _END_OF_CHAIN):
                continue
            if i >= self._n_fat and self._n_fat:
                break
            block = self._sector_bytes(sect)
            fat.extend(struct.unpack_from(f"<{per_sector}I", block, 0))
        if not fat:
            raise RuntimeError("OLE compound file has an empty FAT")
        return fat

    def _chain(self, start: int, fat: list[int]) -> list[int]:
        chain: list[int] = []
        sector = start
        while sector not in (_END_OF_CHAIN, _FREE_SECT):
            if sector >= len(fat):
                raise RuntimeError(
                    f"OLE sector chain leaves the FAT at sector {sector} "
                    f"(FAT has {len(fat)} entries)"
                )
            chain.append(sector)
            if len(chain) > _MAX_CHAIN:
                raise RuntimeError("OLE sector chain does not terminate")
            sector = fat[sector]
        return chain

    def _read_chain_bytes(self, start: int, size: int, *, use_mini: bool) -> bytes:
        if size == 0:
            return b""
        if use_mini:
            unit = self._mini_sector_size
            chain = self._chain(start, self._mini_fat)
            source = self._mini_stream
            out = b"".join(
                source[s * unit:(s + 1) * unit] for s in chain
            )
        else:
            out = b"".join(self._sector_bytes(s) for s in self._chain(start, self._fat))
        if len(out) < size:
            raise RuntimeError(
                f"OLE stream shorter than its declared size "
                f"({len(out)} < {size})"
            )
        return out[:size]

    # -- directory ---------------------------------------------------------

    def _read_directory(self) -> list[tuple[str, int, int, int]]:
        raw = b"".join(self._sector_bytes(s) for s in self._chain(self._first_dir, self._fat))
        entries: list[tuple[str, int, int, int]] = []
        for off in range(0, len(raw) - _DIR_ENTRY_SIZE + 1, _DIR_ENTRY_SIZE):
            chunk = raw[off:off + _DIR_ENTRY_SIZE]
            name_len = struct.unpack_from("<H", chunk, 0x40)[0]
            entry_type = chunk[0x42]
            if entry_type not in (_TYPE_STREAM, _TYPE_ROOT):
                continue
            if name_len < 2:
                continue
            name = chunk[:name_len - 2].decode("utf-16-le", errors="replace")
            start = struct.unpack_from("<I", chunk, 0x74)[0]
            size = struct.unpack_from("<Q", chunk, 0x78)[0]
            # v3 files leave the high half of the size undefined.
            if self._sector_size == 512:
                size &= 0xFFFFFFFF
            entries.append((name, entry_type, start, size))
        if not entries:
            raise RuntimeError("OLE compound file has an empty directory")
        return entries

    def _read_mini_fat(self) -> list[int]:
        if self._n_mini_fat == 0 or self._first_mini_fat in (_END_OF_CHAIN, _FREE_SECT):
            return []
        per_sector = self._sector_size // 4
        out: list[int] = []
        for sect in self._chain(self._first_mini_fat, self._fat):
            out.extend(struct.unpack_from(f"<{per_sector}I", self._sector_bytes(sect), 0))
        return out

    def _read_mini_stream(self) -> bytes:
        for name, entry_type, start, size in self._entries:
            if entry_type == _TYPE_ROOT:
                if size == 0:
                    return b""
                return b"".join(
                    self._sector_bytes(s) for s in self._chain(start, self._fat)
                )
        return b""


__all__ = ["CompoundFile"]
