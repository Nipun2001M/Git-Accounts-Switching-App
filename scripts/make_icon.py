#!/usr/bin/env python3
"""Draw a simple app icon and write a PNG."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def inside_round_rect(nx: float, ny: float, left: float, top: float, width: float, height: float, radius: float) -> bool:
    cx = left + width / 2
    cy = top + height / 2
    dx = abs(nx - cx) - (width / 2 - radius)
    dy = abs(ny - cy) - (height / 2 - radius)
    outside_x = max(dx, 0.0)
    outside_y = max(dy, 0.0)
    outside = (outside_x * outside_x + outside_y * outside_y) ** 0.5
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius <= 0


def color_at(px: float, py: float, size: int) -> tuple[int, int, int, int]:
    nx = px / size
    ny = py / size
    if not inside_round_rect(nx, ny, 0.08, 0.08, 0.84, 0.84, 0.18):
        return (0, 0, 0, 0)
    red, green, blue = 13, 17, 23
    if inside_round_rect(nx, ny, 0.20, 0.40, 0.60, 0.20, 0.10):
        red, green, blue = 48, 54, 61
    if (nx - 0.64) ** 2 + (ny - 0.50) ** 2 <= 0.085 ** 2:
        red, green, blue = 31, 111, 235
    return (red, green, blue, 255)


def pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    channels = [0, 0, 0, 0]
    for oy in (0.25, 0.75):
        for ox in (0.25, 0.75):
            color = color_at(x + ox, y + oy, size)
            for index, value in enumerate(color):
                channels[index] += value
    return tuple(value // 4 for value in channels)  # type: ignore[return-value]


def write_png(path: Path, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(pixel(x, y, size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    write_png(destination, 1024)
