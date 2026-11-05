"""Bounded pipe framing and byte-order adaptation. Never creates Atmos data."""
import array
import struct
import zlib

HEADER = struct.Struct('<4sIQQII')
CYCLE_BYTES = 61440


def checksum(data):
    return zlib.crc32(data) & 0xffffffff


def validate_header(header, expected_index):
    magic, version, index, pts, length, crc = HEADER.unpack(header)
    if version != 1:
        raise ValueError('pipe version')
    if magic == b'TVMS':
        if (index, pts, length, crc) != (7, 48000, 0, 0):
            raise ValueError('negotiated profile')
    elif magic == b'TVMT':
        if index != expected_index or pts != index * 960 or length != CYCLE_BYTES:
            raise ValueError('cycle sequence or dimensions')
    elif magic == b'TVME':
        if index != expected_index or pts != index * 960 or length or crc:
            raise ValueError('stream end count')
    else:
        raise ValueError('pipe magic')
    return magic, index, pts, length, crc


def to_lg_carrier(data, expected_checksum):
    if len(data) != CYCLE_BYTES or data[:4] != bytes.fromhex('72f81f4e'):
        raise ValueError('MAT carrier preamble or size')
    pc, pd = struct.unpack_from('<HH', data, 4)
    if pc & 31 != 0x16 or pc & 0x80 or pd < 2 or pd > 61432 or pd & 1:
        raise ValueError('MAT carrier type or payload dimensions')
    if checksum(data) != expected_checksum:
        raise ValueError('owned pipe payload corruption')
    words = array.array('H')
    words.frombytes(data)
    words.byteswap()
    return words.tobytes()
