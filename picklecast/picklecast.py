#!/usr/bin/env python3

import asyncio
import functools
from http import HTTPStatus
import json
import os
import socket
import ssl
import websockets
from .version import __version__

MIME_TYPES = {
    "html": "text/html",
    "js": "text/javascript",
    "css": "text/css"
}

base_dir = os.path.dirname(os.path.realpath(__file__))
localhost_pem = os.path.join(base_dir, 'localhost.pem')

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

# thanks to https://gist.github.com/artizirk/04eb23d957d7916c01ca632bb27d5436
async def process_request(sever_root, path, request_headers):
    """Serves a file when doing a GET request with a valid path."""

    if "Upgrade" in request_headers:
        return  # Probably a WebSocket connection

    if path == '/':
        path = '/index.html'
    if path in ('/display', '/display.html'):
        path = '/display.html'

    response_headers = [
        ('Server', 'asyncio websocket server'),
        ('Connection', 'close'),
    ]

    # Derive full system path
    full_path = os.path.realpath(os.path.join(sever_root, path[1:]))

    # Validate the path
    if os.path.commonpath((sever_root, full_path)) != sever_root or \
            not os.path.exists(full_path) or not os.path.isfile(full_path):
        print("HTTP GET {} 404 NOT FOUND".format(path))
        return HTTPStatus.NOT_FOUND, [], b'404 NOT FOUND'

    # Guess file content type
    extension = full_path.split(".")[-1]
    mime_type = MIME_TYPES.get(extension, "application/octet-stream")
    response_headers.append(('Content-Type', mime_type))

    # Read the whole file into memory and send it out
    body = open(full_path, 'rb').read()
    response_headers.append(('Content-Length', str(len(body))))
    print("HTTP GET {} 200 OK".format(path))
    return HTTPStatus.OK, response_headers, body

async def on_connect(ws):
    print("client connected")
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
            if connection.open:
                await connection.send(json.dumps(
                    {
                        "sender": "client",
                        "message": json.loads(message)
                    }
                ))
                # await connection.send("{{\"sender\":\"client\", \"message\":{}}}".format(message))
        # await ws.broadcast(connections, message)

async def run(args):
    # handler = functools.partial(process_request, os.getcwd())
    handler = functools.partial(process_request, base_dir)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(localhost_pem)

    async with websockets.serve(on_connect, "0.0.0.0", 8443, ssl=ssl_context, process_request=handler):
        await asyncio.Future()


def main():
    asyncio.run(run(None))

if __name__ == "__main__":
    main()

# const wss = new WebSocketServer({server: httpsServer});

# wss.on('connection', function(ws) {
#   ws.on('message', function(message) {
#     // Broadcast any received message to all clients
#     console.log('received: %s', message);
#     wss.broadcast(message);
#   });
# });

# wss.on('error', function(error) {
#   console.log(error);
# })

# wss.broadcast = function(data) {
#   this.clients.forEach(function(client) {
#     if(client.readyState === WebSocket.OPEN) {
#       client.send(data);
#     }
#   });
# };
