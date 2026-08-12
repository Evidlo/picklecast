"""Minimal stdlib websocket client, shared by the tests."""

import asyncio
import base64
import json
import os
import ssl
import struct


async def connect(host, port, path, secure=True):
    if secure:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = None
    reader, writer = await asyncio.open_connection(host, port, ssl=ctx)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write((
        "GET {} HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: {}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n".format(path, host, port, key)
    ).encode())
    await writer.drain()
    status = await reader.readline()
    assert b'101' in status, status
    while True:
        line = await reader.readline()
        if line in (b'\r\n', b'\n', b''):
            break
    return reader, writer


async def send(writer, text):
    payload = text.encode()
    n = len(payload)
    if n < 126:
        header = struct.pack('!BB', 0x81, 0x80 | n)
    elif n < 1 << 16:
        header = struct.pack('!BBH', 0x81, 0x80 | 126, n)
    else:
        header = struct.pack('!BBQ', 0x81, 0x80 | 127, n)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    writer.write(header + mask + masked)
    await writer.drain()


async def send_json(writer, obj):
    await send(writer, json.dumps(obj))


async def recv(reader):
    """Return the next text message, or None if the peer closed."""
    data = b''
    message_opcode = None
    while True:
        head = await reader.readexactly(2)
        fin, opcode = head[0] & 0x80, head[0] & 0xf
        n = head[1] & 0x7f
        if n == 126:
            n = struct.unpack('!H', await reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack('!Q', await reader.readexactly(8))[0]
        payload = await reader.readexactly(n)
        if opcode == 0x8:
            return None
        if opcode in (0x9, 0xa):
            continue
        if opcode != 0x0:
            message_opcode = opcode
        data += payload
        if fin:
            return data.decode() if message_opcode == 0x1 else None


async def recv_json(reader):
    message = await recv(reader)
    return None if message is None else json.loads(message)
