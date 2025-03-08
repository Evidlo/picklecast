#!/usr/bin/env python3

import argparse
import asyncio
import functools
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import socket
import sysconfig
import ssl
import websockets
import websockets.legacy.server as server

from .version import __version__

log = logging.getLogger('picklecast')
logging.basicConfig()


# websocket connections to clients
connections = set()

# thanks to https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

async def process_request(base_dir, path, request_headers):
    """Serve up HTML
    thanks to https://gist.github.com/artizirk/04eb23d957d7916c01ca632bb27d5436
    """

    if "Upgrade" in request_headers:
        return  # Probably a WebSocket connection

    # basic URL rewriting
    if path == '/':
        path = "index.html"
    if path in ('/display', '/display.html'):
        path = "display.html"
    path = path.lstrip('/')

    file_path = base_dir.joinpath(path)

    response_headers = [
        ('Server', 'picklecast webserver'),
        ('Connection', 'close'),
    ]

    # Validate the path
    if file_path is None or not file_path.exists() or not file_path.is_file():
        log.error("File not found: {}".format(file_path))
        print("HTTP GET {} 404 NOT FOUND".format(path))
        return HTTPStatus.NOT_FOUND, [], b'404 NOT FOUND'
    if not file_path.is_relative_to(base_dir):
        print("HTTP GET {} 403 FORBIDDEN".format(path))
        return HTTPStatus.NOT_FOUND, [], b'403 FORBIDDEN'

    MIME_TYPES = {
        ".html": "text/html",
        ".js": "text/javascript",
        ".css": "text/css"
    }
    mime_type = MIME_TYPES.get(file_path.suffix, "application/octet-stream")
    response_headers.append(('Content-Type', mime_type))

    # Read the whole file into memory and send it out
    body = file_path.read_bytes()
    response_headers.append(('Content-Length', str(len(body))))
    print("HTTP GET {} 200 OK".format(file_path))
    return HTTPStatus.OK, response_headers, body

async def on_connect(ws):
    """Callback when a client connects to the websocket"""

    # maintain list of connected clients
    connections.add(ws)
    address = f"https://{get_ip()}:{ws.port}"
    await ws.send(json.dumps(
        {
            "sender": "server",
            "message": {"version": f"picklecast {__version__}", "address": address}
        }
    ))

    # broadcast every message received to all clients
    async for message in ws:
        for connection in connections:
            try:
                if connection.open:
                    await connection.send(json.dumps(
                        {
                            "sender": "client",
                            "message": json.loads(message)
                        }
                    ))
            except websockets.exceptions.ConnectionClosedError:
                log.debug("Client disconnected")
                continue


def run(*, port, host, base_dir, certificate, **_):
    """Run pickle cast"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(Path(certificate).expanduser())

    if host == '0.0.0.0':
        print("Server address:", get_ip())
        print("Display URL:", f"https://localhost:{port}/display", f"  https://{get_ip()}:{port}/display")
        print("Client URL:", f"https://{get_ip()}:{port}/")
    else:
        print("Server address:", host)
        print("Display URL:", f"  https://{host}:{port}/display")
        print("Client URL:", f"https://{host}:{port}/")

    handler = functools.partial(process_request, Path(base_dir).expanduser())

    async def asyncio_run(host, port):
        async with server.serve(on_connect, host, port, ssl=ssl_context, process_request=handler):
            await asyncio.Future()

    asyncio.run(asyncio_run(host, port))

def install_service(*, base_dir, **_):
    """Install systemd service to ~/.config/systemd/user"""

    service = base_dir.joinpath("picklecast.service")
    dest = Path.home().joinpath(".config/systemd/user").joinpath(service.name)
    dest.parent.mkdir(exist_ok=True, parents=True)

    picklecast_path = Path(sysconfig.get_path('scripts')).joinpath('picklecast')
    assert picklecast_path.exists(), "Couldn't find picklecast install location"

    # insert picklecast path into template
    service_text = service.read_text().format(picklecast_path=picklecast_path)
    dest.write_text(service_text)
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

    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help="enable debugging"
    )

    parser.add_argument('-v', '--version', action='version', version=__version__, help="show version information")

    parser.add_argument(
        '--host',
        metavar='HOST',
        type=str,
        default="0.0.0.0",
        help="Host address to listen on"
    )

    parser.add_argument(
        '--port',
        metavar='PORT',
        type=int,
        default=8443,
        help="Port to listen on"
    )

    parser.add_argument(
        '--base_dir',
        metavar='DIR',
        type=str,
        default=Path(__file__).parent,
        help="Base directory containing custom index.html/display.html"
    )

    parser.add_argument(
        '--certificate',
        metavar='DIR',
        type=str,
        default=Path(__file__).parent.joinpath('localhost.pem'),
        help="Path to custom certificate"
    )

    args = parser.parse_args()

    if args.debug:
        print('Debugging enabled...')
        log.setLevel(logging.DEBUG)

    try:
        args.func(**vars(args))
    except KeyboardInterrupt:
        print()

if __name__ == "__main__":
        main()
