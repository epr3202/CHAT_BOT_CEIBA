"""Bounded, pure Python duration measurement for a single Ogg/Opus stream."""
from __future__ import annotations

import struct


class InvalidOpus(ValueError):
    """The input does not contain a complete supported Ogg/Opus stream."""


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
    return crc


def opus_duration_seconds(data: bytes) -> float:
    """Read final granule at 48 kHz, less OpusHead pre-skip; never decode audio."""
    if not data or len(data) > 16 * 1024 * 1024:
        raise InvalidOpus('INVALID_SIZE')
    offset = 0
    serial = None
    sequence = 0
    packet = bytearray()
    packet_count = 0
    pre_skip = None
    final_granule = None
    ended = False
    while offset < len(data):
        if ended or len(data) - offset < 27:
            raise InvalidOpus('INVALID_PAGE')
        header = data[offset:offset + 27]
        if header[:4] != b'OggS' or header[4] != 0 or header[5] & ~7:
            raise InvalidOpus('INVALID_HEADER')
        flags = header[5]
        granule, page_serial, page_sequence, checksum = struct.unpack_from('<QIII', header, 6)
        count = header[26]
        table_end = offset + 27 + count
        if table_end > len(data):
            raise InvalidOpus('TRUNCATED_LACING')
        lacing = data[offset + 27:table_end]
        end = table_end + sum(lacing)
        if end > len(data):
            raise InvalidOpus('TRUNCATED_PAGE')
        page = bytearray(data[offset:end])
        page[22:26] = b'\x00' * 4
        if _ogg_crc(page) != checksum:
            raise InvalidOpus('INVALID_CHECKSUM')
        if serial is None:
            serial = page_serial
            if flags != 2 or page_sequence != 0:
                raise InvalidOpus('MISSING_BOS')
        elif page_serial != serial or flags & 2:
            raise InvalidOpus('MULTIPLE_STREAMS')
        if page_sequence != sequence or bool(flags & 1) != bool(packet):
            raise InvalidOpus('INVALID_SEQUENCE')
        sequence += 1
        cursor = table_end
        for size in lacing:
            packet.extend(data[cursor:cursor + size])
            cursor += size
            if len(packet) > 1024 * 1024:
                raise InvalidOpus('PACKET_TOO_LARGE')
            if size < 255:
                if packet_count == 0:
                    if len(packet) < 19 or packet[:8] != b'OpusHead':
                        raise InvalidOpus('MISSING_OPUS_HEAD')
                    if not 1 <= packet[8] <= 15 or not packet[9]:
                        raise InvalidOpus('INVALID_OPUS_HEAD')
                    pre_skip = struct.unpack_from('<H', packet, 10)[0]
                elif packet_count == 1 and packet[:8] != b'OpusTags':
                    raise InvalidOpus('MISSING_OPUS_TAGS')
                packet_count += 1
                packet.clear()
        if flags & 4:
            if packet or granule == 0xFFFFFFFFFFFFFFFF:
                raise InvalidOpus('INVALID_END')
            ended = True
            final_granule = granule
        offset = end
    if not ended or packet_count < 3 or pre_skip is None or final_granule is None:
        raise InvalidOpus('INCOMPLETE_STREAM')
    if final_granule < pre_skip:
        raise InvalidOpus('INVALID_GRANULE')
    return (final_granule - pre_skip) / 48000
