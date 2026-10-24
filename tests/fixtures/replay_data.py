"""Minimal modern replay framing, with opaque packet payloads."""
import struct


def header():
    return struct.pack('<IQ',0x12345678,0)+b'\x02ab\x0711.21.0\x00'


def packet(kind,clock,payload=b''):
    return struct.pack('<IIf',len(payload),kind,clock)+payload


def replay_data(origin=4.25):
    return header()+packet(0,0,b'opaque')+packet(0x11,origin)+packet(0xFFFFFFFF,0)
