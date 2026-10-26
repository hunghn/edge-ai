"""The raw preview file the engine writes and the kiosk reads (C-09).

An 8-byte header, then width * height * 3 bytes of RGB, row after row. RGB rather than
OpenCV's BGR because Qt 5.9 (JetPack) has no BGR888 format, and swapping the channels on
the kiosk would put that cost back on its UI thread. Kept here, not in the engine or the
kiosk, because both processes have to agree on it and neither should import the other.
"""
import struct

RAW_MAGIC = b"EFP1"
RAW_HEADER = struct.Struct("<4sHH")


def encode_header(width, height):
    return RAW_HEADER.pack(RAW_MAGIC, int(width), int(height))


def decode_header(data):
    """(width, height) if `data` starts with a raw preview header, else None."""
    if data is None or len(data) < RAW_HEADER.size:
        return None
    magic, width, height = RAW_HEADER.unpack_from(data, 0)
    if magic != RAW_MAGIC:
        return None
    return width, height


def expected_size(width, height):
    return RAW_HEADER.size + int(width) * int(height) * 3
