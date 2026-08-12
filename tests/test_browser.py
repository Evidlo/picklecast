#!/usr/bin/env python3
"""Drive headless chromium through a whole picklecast session.

Loads tests/page.html, which plays both the display and the sharing client, and
watches the console for milestones.  By default only the local-server transport
is checked; --trackers additionally checks that a page served without a
signaling server falls back to the public trackers (needs internet, and tracker
peering can take the better part of a minute).
"""

import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wsclient
from support import PicklecastServer, StaticServer, REPO, free_port

CHROME_CANDIDATES = ['chromium', 'chromium-browser', 'google-chrome', 'chrome']

failures = []


def check(name, ok, detail=''):
    print('{} {}{}'.format('ok  ' if ok else 'FAIL', name,
                           '' if ok else '  <- ' + str(detail)))
    if not ok:
        failures.append(name)


def find_chrome():
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


class Browser:
    """Headless chromium with a devtools endpoint."""

    def __init__(self, binary, profile):
        self.binary = binary
        self.profile = profile
        self.port = free_port()
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen([
            self.binary, '--headless=new', '--no-sandbox', '--disable-gpu',
            '--ignore-certificate-errors',
            '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
            '--autoplay-policy=no-user-gesture-required',
            '--remote-debugging-port={}'.format(self.port),
            '--user-data-dir={}'.format(self.profile),
            'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.targets()
                return self
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("chromium devtools did not come up")

    def targets(self):
        raw = urllib.request.urlopen(
            'http://127.0.0.1:{}/json'.format(self.port), timeout=1).read()
        return json.loads(raw)

    def page_ws(self):
        pages = [t for t in self.targets() if t['type'] == 'page']
        return pages[0]['webSocketDebuggerUrl']

    def __exit__(self, *exc):
        self.proc.terminate()
        self.proc.wait(timeout=10)


async def run_page(browser, url, expect, timeout):
    """Navigate to url, return the set of TEST: milestones seen."""
    ws_url = browser.page_ws()
    _, rest = ws_url.split('://', 1)
    hostport, _, path = rest.partition('/')
    host, _, port = hostport.partition(':')
    reader, writer = await wsclient.connect(host, int(port), '/' + path, secure=False)

    await wsclient.send_json(writer, {'id': 1, 'method': 'Runtime.enable'})
    await wsclient.send_json(writer, {'id': 2, 'method': 'Page.enable'})
    await wsclient.send_json(writer, {'id': 3, 'method': 'Page.navigate',
                                      'params': {'url': url}})

    seen = set()
    logs = []
    origin = '/'.join(url.split('/')[:3])
    # the previous page keeps running until navigation completes, so only
    # accept console output from the execution context we just created
    contexts = {}

    async def pump():
        while True:
            msg = await wsclient.recv_json(reader)
            if msg is None:
                return
            if msg.get('method') == 'Runtime.executionContextCreated':
                context = msg['params']['context']
                contexts[context['id']] = context.get('origin')
                continue
            if msg.get('method') != 'Runtime.consoleAPICalled':
                continue
            if contexts.get(msg['params'].get('executionContextId')) != origin:
                continue
            text = ' '.join(str(a.get('value', a.get('description', '')))
                            for a in msg['params']['args'])
            logs.append(text)
            if text.startswith('TEST:'):
                seen.add(text[5:].split(' ')[0])
            if expect <= seen:
                return

    try:
        await asyncio.wait_for(pump(), timeout)
    except asyncio.TimeoutError:
        pass
    writer.close()
    return seen, logs


MILESTONES = {'display-started', 'client-has-media', 'client-found-peer',
              'client-connected', 'display-ontrack'}


def report(label, seen, logs):
    for milestone in sorted(MILESTONES):
        check('{}: {}'.format(label, milestone), milestone in seen)
    if 'error' in seen:
        check('{}: no page errors'.format(label), False,
              [l for l in logs if 'TEST:error' in l])
    if failures:
        print('  console:')
        for line in logs:
            print('   ', line)


def main():
    trackers = '--trackers' in sys.argv
    binary = find_chrome()
    if not binary:
        print('SKIP: no chromium/chrome binary found')
        return 0

    profile = REPO / 'tests' / '.scratch' / 'chrome'
    profile.parent.mkdir(parents=True, exist_ok=True)

    with Browser(binary, profile) as browser:
        # served by the local server: signaling must stay on the LAN
        with PicklecastServer(base_dir=REPO, local=True) as server:
            seen, logs = asyncio.run(run_page(
                browser, server.url + '/tests/page.html', MILESTONES, 30))
            report('local', seen, logs)
            check('local: chose the local signaling server',
                  any('using local signaling server' in l for l in logs), logs[:5])
            check('local: never touched a public tracker',
                  not any('tracker' in l and 'local' not in l for l in logs))

        if trackers:
            # served as a static site: must fall back to the public trackers
            with StaticServer(REPO) as static:
                seen, logs = asyncio.run(run_page(
                    browser, static.url + '/tests/page.html', MILESTONES, 120))
                report('trackers', seen, logs)
                check('trackers: fell back after probing for a local server',
                      any('using public trackers' in l for l in logs), logs[:5])
        else:
            print('note: skipping tracker fallback test (pass --trackers)')

    print()
    if failures:
        print('{} failure(s)'.format(len(failures)))
        return 1
    print('all browser tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
