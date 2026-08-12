"""Helpers for launching a picklecast server during tests."""

import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def no_verify_opener():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


class PicklecastServer:
    """Run `python -m picklecast.server` on a free port with a scratch cert."""

    def __init__(self, base_dir=REPO / 'picklecast', local=False, config_home=None):
        self.base_dir = base_dir
        self.local = local
        self.port = free_port()
        self.config_home = config_home or (REPO / 'tests' / '.scratch')
        self.proc = None

    @property
    def url(self):
        return 'https://127.0.0.1:{}'.format(self.port)

    def __enter__(self):
        env = dict(os.environ, PYTHONUNBUFFERED='1',
                   XDG_CONFIG_HOME=str(self.config_home))
        cmd = [sys.executable, '-m', 'picklecast.server',
               '--host', '127.0.0.1', '--port', str(self.port),
               '--base_dir', str(self.base_dir)]
        if self.local:
            cmd.append('--local')
        self.proc = subprocess.Popen(cmd, cwd=str(REPO), env=env,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.STDOUT)
        opener = no_verify_opener()
        for _ in range(100):
            try:
                opener.open(self.url + '/config.js', timeout=1).read()
                return self
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("server exited immediately")
                time.sleep(0.1)
        raise RuntimeError("server did not come up")

    def __exit__(self, *exc):
        self.proc.terminate()
        self.proc.wait(timeout=5)


class StaticServer:
    """Plain http.server, standing in for Github Pages (no signaling server)."""

    def __init__(self, base_dir=REPO):
        self.base_dir = base_dir
        self.port = free_port()
        self.proc = None

    @property
    def url(self):
        return 'http://127.0.0.1:{}'.format(self.port)

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'http.server', str(self.port),
             '--bind', '127.0.0.1', '--directory', str(self.base_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url, timeout=1).read()
                return self
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("static server did not come up")

    def __exit__(self, *exc):
        self.proc.terminate()
        self.proc.wait(timeout=5)
