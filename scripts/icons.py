"""App icons for the manifest and the iOS home screen (NFA-02, A24).

python scripts/icons.py

Draws a green ▲ on ink, the Kursblatt colors (docs/design.md, section 2), with the
standard library only. The maskable icon keeps the triangle inside the safe zone, as
Android crops it to a circle or rounded square.
"""

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "icons"
INK = (0x11, 0x11, 0x11)
UP = (0x12, 0xD3, 0x7A)
SUPERSAMPLE = 4

# name → (size in px, triangle width as a share of the size)
ICONS = {
    "icon-192.png": (192, 0.56),
    "icon-512.png": (512, 0.56),
    "icon-maskable-512.png": (512, 0.42),  # inside the 80 % safe zone
    "apple-touch-icon.png": (180, 0.56),
}


def triangle(size: int, share: float) -> tuple[tuple[float, float], ...]:
    """An equilateral ▲, its centroid in the middle of the icon."""
    width = size * share
    height = width * 3**0.5 / 2
    cx, cy = size / 2, size / 2 + height / 6
    return (
        (cx, cy - 2 * height / 3),
        (cx + width / 2, cy + height / 3),
        (cx - width / 2, cy + height / 3),
    )


def inside(x: float, y: float, corners: tuple[tuple[float, float], ...]) -> bool:
    (ax, ay), (bx, by), (cx, cy) = corners

    def side(px: float, py: float, qx: float, qy: float) -> float:
        return (x - qx) * (py - qy) - (px - qx) * (y - qy)

    signs = (side(ax, ay, bx, by), side(bx, by, cx, cy), side(cx, cy, ax, ay))
    return all(s <= 0 for s in signs) or all(s >= 0 for s in signs)


def render(size: int, share: float) -> bytes:
    corners = triangle(size, share)
    step = 1 / SUPERSAMPLE
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter: none
        for x in range(size):
            hits = sum(
                inside(x + (i + 0.5) * step, y + (j + 0.5) * step, corners)
                for i in range(SUPERSAMPLE)
                for j in range(SUPERSAMPLE)
            )
            cover = hits / SUPERSAMPLE**2
            row += bytes(round(i + (u - i) * cover) for i, u in zip(INK, UP, strict=True))
        rows.append(bytes(row))
    return png(size, b"".join(rows))


def png(size: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (size, share) in ICONS.items():
        (OUT / name).write_bytes(render(size, share))
        print(OUT / name)


if __name__ == "__main__":
    main()
