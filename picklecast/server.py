#!/usr/bin/env python3
"""Local signaling server for picklecast.

Serves the static picklecast files over HTTPS and relays signaling messages
between browsers over a WebSocket.  This is the offline fallback for the
public WebTorrent trackers: nothing leaves the LAN.

Implemented with the standard library only, so picklecast has no runtime
dependencies.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import socket
import ssl
import struct
import subprocess
import sys
import sysconfig
from pathlib import Path

try:
    from importlib.metadata import version
    __version__ = version("picklecast")
except Exception:
    __version__ = "dev"

log = logging.getLogger('picklecast')
logging.basicConfig()

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

MIME_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


# thanks to https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


# ---------------------------------------------------------------- websocket

class WSError(Exception):
    pass


class WebSocket:
    """Minimal server-side WebSocket (RFC 6455), text frames only."""

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.closed = False

    @staticmethod
    def accept_key(client_key):
        digest = hashlib.sha1((client_key + WS_GUID).encode()).digest()
        return base64.b64encode(digest).decode()

    async def handshake(self, headers):
        key = headers.get('sec-websocket-key')
        if not key or headers.get('sec-websocket-version') != '13':
            raise WSError("bad websocket handshake")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n"
        ).format(self.accept_key(key))
        self.writer.write(response.encode())
        await self.writer.drain()

    async def _read_frame(self):
        """Read one frame, returning (fin, opcode, payload)."""
        header = await self.reader.readexactly(2)
        fin = bool(header[0] & 0x80)
        opcode = header[0] & 0x0f
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7f

        if length == 126:
            length = struct.unpack('!H', await self.reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack('!Q', await self.reader.readexactly(8))[0]

        # clients must mask; refuse absurd payloads (signaling messages are tiny)
        if not masked:
            raise WSError("unmasked frame from client")
        if length > 1 << 20:
            raise WSError("oversized frame")

        mask = await self.reader.readexactly(4)
        payload = bytearray(await self.reader.readexactly(length))
        for i in range(length):
            payload[i] ^= mask[i & 3]
        return fin, opcode, bytes(payload)

    async def recv(self):
        """Return the next text message, or None once the peer closes."""
        buffer = b''
        buffer_opcode = None
        while True:
            try:
                fin, opcode, payload = await self._read_frame()
            except (asyncio.IncompleteReadError, ConnectionResetError):
                return None

            if opcode == 0x8:  # close
                await self.close()
                return None
            if opcode == 0x9:  # ping
                await self._send_frame(0xa, payload)
                continue
            if opcode == 0xa:  # pong
                continue

            if opcode == 0x0:  # continuation
                if buffer_opcode is None:
                    raise WSError("unexpected continuation frame")
            else:
                buffer_opcode = opcode
            buffer += payload

            if fin:
                message = buffer
                opcode, buffer, buffer_opcode = buffer_opcode, b'', None
                if opcode == 0x1:
                    return message.decode('utf-8', 'replace')
                # ignore binary messages

    async def _send_frame(self, opcode, payload):
        if self.closed:
            return
        length = len(payload)
        if length < 126:
            header = struct.pack('!BB', 0x80 | opcode, length)
        elif length < (1 << 16):
            header = struct.pack('!BBH', 0x80 | opcode, 126, length)
        else:
            header = struct.pack('!BBQ', 0x80 | opcode, 127, length)
        try:
            self.writer.write(header + payload)
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self.closed = True

    async def send(self, message):
        await self._send_frame(0x1, message.encode())

    async def close(self):
        if self.closed:
            return
        await self._send_frame(0x8, b'')
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass


# ------------------------------------------------------------------- rooms

class Rooms:
    """Signaling peers grouped by room name (one room per display code)."""

    def __init__(self):
        self.rooms = {}
        self.next_id = 1

    def add(self, room, ws):
        peer_id = str(self.next_id)
        self.next_id += 1
        self.rooms.setdefault(room, {})[peer_id] = ws
        return peer_id

    def remove(self, room, peer_id):
        peers = self.rooms.get(room)
        if not peers:
            return
        peers.pop(peer_id, None)
        if not peers:
            self.rooms.pop(room, None)

    def others(self, room, peer_id):
        return [(i, ws) for i, ws in self.rooms.get(room, {}).items() if i != peer_id]

    def get(self, room, peer_id):
        return self.rooms.get(room, {}).get(peer_id)


# ------------------------------------------------------------------ server

class Server:

    def __init__(self, base_dir, address, local_only):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.address = address
        self.local_only = local_only
        self.rooms = Rooms()

    # -- http

    async def handle(self, reader, writer):
        try:
            request = await self.read_request(reader)
        except Exception as e:
            log.debug("malformed request: %s", e)
            writer.close()
            return

        if request is None:
            writer.close()
            return

        method, path, headers = request

        try:
            if headers.get('upgrade', '').lower() == 'websocket':
                await self.handle_websocket(reader, writer, path, headers)
            else:
                await self.handle_http(writer, method, path)
        except (ConnectionResetError, BrokenPipeError, WSError, ssl.SSLError) as e:
            log.debug("connection error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def read_request(self, reader):
        """Parse the request line and headers of an HTTP request."""
        line = await reader.readline()
        if not line:
            return None
        parts = line.decode('latin-1').split()
        if len(parts) < 2:
            raise ValueError("bad request line")
        method, path = parts[0], parts[1]

        headers = {}
        while True:
            line = await reader.readline()
            if line in (b'\r\n', b'\n', b''):
                break
            if b':' not in line:
                continue
            name, _, value = line.decode('latin-1').partition(':')
            headers[name.strip().lower()] = value.strip()
        return method, path, headers

    def respond(self, writer, status, body, content_type='text/plain'):
        if isinstance(body, str):
            body = body.encode()
        head = (
            "HTTP/1.1 {}\r\n"
            "Server: picklecast\r\n"
            "Content-Type: {}\r\n"
            "Content-Length: {}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).format(status, content_type, len(body))
        writer.write(head.encode() + body)

    async def handle_http(self, writer, method, path):
        path = path.split('?')[0].split('#')[0]

        if method not in ('GET', 'HEAD'):
            self.respond(writer, "405 Method Not Allowed", b'405')
            await writer.drain()
            return

        # config injected into the served pages (see config.js in the repo)
        if path in ('/config.js', '/picklecast/config.js'):
            config = json.dumps({
                'local': True,
                'localOnly': self.local_only,
                'address': self.address,
            })
            self.respond(
                writer, "200 OK",
                "window.PICKLECAST_CONFIG = {};\n".format(config),
                'text/javascript',
            )
            print("HTTP GET {} 200 OK".format(path))
            await writer.drain()
            return

        # basic URL rewriting
        if path == '/':
            path = 'index.html'
        if path in ('/display', '/display.html'):
            path = 'display.html'
        path = path.lstrip('/')

        file_path = (self.base_dir / path).resolve()

        if not file_path.is_relative_to(self.base_dir):
            print("HTTP GET {} 403 FORBIDDEN".format(path))
            self.respond(writer, "403 Forbidden", b'403 FORBIDDEN')
            await writer.drain()
            return
        if not file_path.is_file():
            log.error("File not found: %s", file_path)
            print("HTTP GET {} 404 NOT FOUND".format(path))
            self.respond(writer, "404 Not Found", b'404 NOT FOUND')
            await writer.drain()
            return

        body = file_path.read_bytes()
        mime = MIME_TYPES.get(file_path.suffix, "application/octet-stream")
        print("HTTP GET {} 200 OK".format(file_path))
        self.respond(writer, "200 OK", body if method == 'GET' else b'', mime)
        await writer.drain()

    # -- signaling

    async def handle_websocket(self, reader, writer, path, headers):
        query = path.split('?')[1] if '?' in path else ''
        room = 'default'
        for param in query.split('&'):
            key, _, value = param.partition('=')
            if key == 'room' and value:
                room = value[:64]

        ws = WebSocket(reader, writer)
        await ws.handshake(headers)

        peer_id = self.rooms.add(room, ws)
        log.debug("peer %s joined %s", peer_id, room)
        await ws.send(json.dumps({
            'type': 'welcome',
            'id': peer_id,
            'address': self.address,
            'version': __version__,
            'peers': [i for i, _ in self.rooms.others(room, peer_id)],
        }))
        # announce in both directions so either side can open the connection
        await self.broadcast(room, peer_id, {'type': 'peerconnect', 'id': peer_id})

        try:
            while True:
                message = await ws.recv()
                if message is None:
                    break
                try:
                    data = json.loads(message)
                except ValueError:
                    continue
                if data.get('type') != 'msg':
                    continue
                frame = json.dumps({
                    'type': 'msg', 'from': peer_id, 'msg': data.get('msg'),
                })
                target = data.get('to')
                if target is None:
                    await self.broadcast(room, peer_id, json.loads(frame))
                else:
                    peer = self.rooms.get(room, str(target))
                    if peer:
                        await peer.send(frame)
        finally:
            self.rooms.remove(room, peer_id)
            await self.broadcast(room, peer_id, {'type': 'peerclose', 'id': peer_id})
            await ws.close()
            log.debug("peer %s left %s", peer_id, room)

    async def broadcast(self, room, sender_id, payload):
        frame = json.dumps(payload)
        for _, peer in self.rooms.others(room, sender_id):
            try:
                await peer.send(frame)
            except Exception:
                continue


# ------------------------------------------------------------ certificates

def default_cert_path():
    config_home = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(config_home) / 'picklecast' / 'cert.pem'


def generate_cert(path, ip):
    """Write a self-signed cert+key to path.  Browsers will warn once."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ['localhost', ip, '127.0.0.1']

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime
        import ipaddress

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'picklecast')])
        alt = []
        for name in names:
            try:
                alt.append(x509.IPAddress(ipaddress.ip_address(name)))
            except ValueError:
                alt.append(x509.DNSName(name))
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .sign(key, hashes.SHA256())
        )
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ) + cert.public_bytes(serialization.Encoding.PEM)
        path.write_bytes(pem)
    except ImportError:
        # no cryptography module — shell out to openssl
        san = ','.join(
            ('IP:' + n if n[0].isdigit() else 'DNS:' + n) for n in names
        )
        try:
            subprocess.run([
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-days', '3650', '-subj', '/CN=picklecast',
                '-addext', 'subjectAltName=' + san,
                '-keyout', str(path), '-out', str(path) + '.crt',
            ], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise SystemExit(
                "Couldn't generate a certificate.  Install the 'cryptography' "
                "package or the 'openssl' binary, or pass --certificate.\n{}".format(e)
            )
        crt = Path(str(path) + '.crt')
        path.write_bytes(path.read_bytes() + crt.read_bytes())
        crt.unlink()

    path.chmod(0o600)
    print("Generated certificate:", path)


# --------------------------------------------------------------- commands

def run(*, port, host, base_dir, certificate, local, **_):
    ip = get_ip() if host == '0.0.0.0' else host
    address = "{}:{}".format(ip, port)

    certificate = Path(certificate).expanduser()
    if not certificate.exists():
        generate_cert(certificate, ip)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certificate)

    print("Server address:", ip)
    print("Display URL:  https://{}/display".format(address))
    print("Client URL:   https://{}/".format(address))
    if local:
        print("Public trackers disabled (--local)")
    print("Note: your browser will warn about the self-signed certificate.")

    server = Server(base_dir, address, local)

    async def serve():
        srv = await asyncio.start_server(server.handle, host, port, ssl=ssl_context)
        async with srv:
            await srv.serve_forever()

    asyncio.run(serve())


def install_service(*, base_dir, **_):
    """Install systemd user service to ~/.config/systemd/user"""
    service = Path(base_dir).expanduser() / "picklecast.service"
    dest = Path.home() / ".config/systemd/user" / service.name
    dest.parent.mkdir(exist_ok=True, parents=True)

    picklecast_path = Path(sysconfig.get_path('scripts')) / 'picklecast'
    if not picklecast_path.exists():
        # fall back to whatever launched us
        picklecast_path = Path(sys.argv[0]).resolve()
    assert picklecast_path.exists(), "Couldn't find picklecast install location"

    dest.write_text(service.read_text().format(picklecast_path=picklecast_path))
    print("Installed service to {}".format(dest))
    print("Enable the service by running:")
    print("    systemctl --user daemon-reload")
    print("    systemctl --user start picklecast")


def main():
    parser = argparse.ArgumentParser(description="Screen share receiver")
    parser.set_defaults(func=run)
    parser._positionals.title = "commands"

    subparsers = parser.add_subparsers()
    subparsers.dest = 'command'

    install_parser = subparsers.add_parser(
        'install_service',
        help="install systemd service on Linux",
    )
    install_parser.set_defaults(func=install_service)

    parser.add_argument('--debug', action='store_true', default=False,
                        help="enable debugging")
    parser.add_argument('-v', '--version', action='version', version=__version__,
                        help="show version information")
    parser.add_argument('--host', metavar='HOST', type=str, default="0.0.0.0",
                        help="Host address to listen on")
    parser.add_argument('--port', metavar='PORT', type=int, default=8443,
                        help="Port to listen on")
    parser.add_argument('--local', action='store_true', default=False,
                        help="Disable public tracker fallback (offline only)")
    parser.add_argument('--base_dir', metavar='DIR', type=str,
                        default=Path(__file__).parent,
                        help="Base directory containing custom index.html/display.html")
    parser.add_argument('--certificate', metavar='FILE', type=str,
                        default=default_cert_path(),
                        help="Path to certificate (generated if missing)")

    args = parser.parse_args()

    # keep request logs readable when piped to a file or journald
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    if args.debug:
        print('Debugging enabled...')
        log.setLevel(logging.DEBUG)

    try:
        args.func(**vars(args))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
