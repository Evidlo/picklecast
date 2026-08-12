#!/usr/bin/env python3
"""Exercise the local server: static serving, and the websocket relay."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wsclient
from support import PicklecastServer, no_verify_opener

failures = []


def check(name, ok, detail=''):
    print('{} {}{}'.format('ok  ' if ok else 'FAIL', name,
                           '' if ok else '  <- ' + str(detail)))
    if not ok:
        failures.append(name)


def test_http(server):
    opener = no_verify_opener()

    def get(path):
        try:
            r = opener.open(server.url + path, timeout=5)
            return r.status, r.read()
        except Exception as e:
            return getattr(e, 'code', 0), b''

    for path, expect in [('/', 200), ('/display', 200), ('/display.html', 200),
                         ('/style.css', 200), ('/webrtc.js', 200),
                         ('/p2pt.iife.js', 200), ('/missing.html', 404)]:
        status, _ = get(path)
        check('GET {} -> {}'.format(path, expect), status == expect, status)

    status, body = get('/config.js')
    check('config.js announces the local server',
          status == 200 and b'"local": true' in body, body[:120])

    status, _ = get('/../pyproject.toml')
    check('path traversal refused', status == 403, status)


async def test_relay(server):
    port = server.port
    path = '/ws?room=picklecast-ABCD'

    dr, dw = await wsclient.connect('127.0.0.1', port, path)
    display = await wsclient.recv_json(dr)
    check('display gets welcome',
          display['type'] == 'welcome' and display['peers'] == [], display)
    check('welcome carries the LAN address', ':' in display.get('address', ''), display)

    cr, cw = await wsclient.connect('127.0.0.1', port, path)
    client = await wsclient.recv_json(cr)
    check('joining client sees the display as an existing peer',
          client['peers'] == [display['id']], client)

    event = await wsclient.recv_json(dr)
    check('display is told the client joined',
          event == {'type': 'peerconnect', 'id': client['id']}, event)

    # a peer in another room must be invisible
    orr, ow = await wsclient.connect('127.0.0.1', port, '/ws?room=picklecast-ZZZZ')
    other = await wsclient.recv_json(orr)
    check('other room starts empty', other['peers'] == [], other)

    await wsclient.send_json(cw, {'type': 'msg', 'to': display['id'],
                                  'msg': '{"sdp":"offer"}'})
    got = await wsclient.recv_json(dr)
    check('client -> display relayed',
          got == {'type': 'msg', 'from': client['id'], 'msg': '{"sdp":"offer"}'}, got)

    await wsclient.send_json(dw, {'type': 'msg', 'to': client['id'],
                                  'msg': '{"sdp":"answer"}'})
    got = await wsclient.recv_json(cr)
    check('display -> client relayed',
          got == {'type': 'msg', 'from': display['id'], 'msg': '{"sdp":"answer"}'}, got)

    # SDP offers are bigger than a 125 byte frame; check both length paths
    for size in (200, 5000, 70000):
        big = 'x' * size
        await wsclient.send_json(cw, {'type': 'msg', 'to': display['id'], 'msg': big})
        got = await wsclient.recv_json(dr)
        check('{} byte message intact'.format(size), got['msg'] == big,
              len(got.get('msg', '')))

    try:
        leaked = await asyncio.wait_for(wsclient.recv_json(orr), 0.5)
    except asyncio.TimeoutError:
        leaked = None
    check('nothing leaked into the other room', leaked is None, leaked)

    cw.close()
    event = await asyncio.wait_for(wsclient.recv_json(dr), 5)
    check('display is told the client left',
          event == {'type': 'peerclose', 'id': client['id']}, event)

    dw.close()
    ow.close()


def main():
    with PicklecastServer() as server:
        test_http(server)
        asyncio.run(test_relay(server))

    print()
    if failures:
        print('{} failure(s): {}'.format(len(failures), ', '.join(failures)))
        return 1
    print('all signaling tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
