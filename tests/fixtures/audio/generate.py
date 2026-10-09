"""Generate deterministic Ogg/Opus containers without recorded speech.

The terminal granule controls duration. These fixtures exercise the bounded
container parser rather than the acoustic decoder; the long fixture deliberately
does not contain 65 seconds of encoded packets.
"""

from __future__ import annotations

import struct
from pathlib import Path

SAMPLE_RATE = 48_000
PRE_SKIP = 312
SERIAL_NUMBER = 0x43454942


def ogg_crc(data: bytes) -> int:
    """Compute the Ogg CRC-32 (unreflected polynomial, zero initial value)."""
    checksum = 0
    for value in data:
        checksum ^= value << 24
        for _ in range(8):
            checksum = (
                ((checksum << 1) ^ 0x04C11DB7) if checksum & 0x80000000 else checksum << 1
            ) & 0xFFFFFFFF
    return checksum


def page(packet: bytes, *, sequence: int, flags: int, granule: int) -> bytes:
    """Wrap one bounded packet in an Ogg page with a valid checksum."""
    if len(packet) >= 255:
        raise ValueError("Fixture packets must fit in one lacing segment")
    header = b"OggS" + struct.pack("<BBQIIIB", 0, flags, granule, SERIAL_NUMBER, sequence, 0, 1)
    raw = header + bytes([len(packet)]) + packet
    checksum = struct.pack("<I", ogg_crc(raw))
    return raw[:22] + checksum + raw[26:]


def opus_fixture(seconds: int) -> bytes:
    """Build OpusHead, OpusTags and an EOS page containing synthetic silence."""
    opus_head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, PRE_SKIP, 16_000, 0, 0)
    vendor = b"ceiba-audio-fixtures-v1"
    opus_tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    return b"".join(
        (
            page(opus_head, sequence=0, flags=2, granule=0),
            page(opus_tags, sequence=1, flags=0, granule=0),
            page(
                b"\xf8\xff\xfe",
                sequence=2,
                flags=4,
                granule=PRE_SKIP + seconds * SAMPLE_RATE,
            ),
        )
    )


def main() -> None:
    destination = Path(__file__).resolve().parent
    (destination / "ok_5s.ogg").write_bytes(opus_fixture(5))
    (destination / "long_65s.ogg").write_bytes(opus_fixture(65))
    (destination / "corrupt.ogg").write_bytes(b"invalid synthetic Ogg fixture\n")


if __name__ == "__main__":
    main()
