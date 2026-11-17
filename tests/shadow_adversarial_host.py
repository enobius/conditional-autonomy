"""Hosted container-boundary probe; dummy host services, not live cache APIs.

Uses production container builder/topology/collector, replacing only the CLI
entrypoint with a Python attack stand-in. Does not exercise CLI checksum/OAuth
or establish platform cache-substitution resistance.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import urllib.request
import uuid

from tools.shadow_container import collect, docker_env, proxied_command, secret_file
from tools import shadow_network_run as network


def check_report(raw):
    value = json.loads(raw)
    expected = {'kind': 'hostile-client-v1', 'clean_environment': True,
                'placeholder_only': True, 'host_files_hidden': True,
                'writes_blocked': True, 'routes_blocked': {'artifact': True, 'cache': True}}
    # Exact canonical encoding also distinguishes Boolean true from integer 1.
    if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('hostile client did not establish every expected denial')


def main():
    root = Path(__file__).resolve().parents[1]
    attempts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            attempts.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'synthetic endpoint only')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('0.0.0.0', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:' + str(server.server_port) + '/positive-control', timeout=3) as response:
            if response.status != 200:
                raise ValueError('dummy listener positive control failed')
        if attempts != ['/positive-control']:
            raise ValueError('unexpected dummy listener traffic')
        dummy = 'dummy-adversarial-' + secrets.token_hex(32)
        with tempfile.TemporaryDirectory(prefix='host-only-canary-') as directory:
            canary = Path(directory) / 'host-secret'
            canary.write_text(dummy)
            host_env = {key: dummy for key in ['GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                                              'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL',
                                              'GITHUB_ENV', 'GITHUB_OUTPUT']}
            with patch.dict(os.environ, host_env), secret_file(dummy) as credential:
                with network.topology(root / 'tools', 'provider.example', credential) as isolated:
                    bridge = json.loads(network.execute(['network', 'inspect', 'bridge']))[0]
                    host = bridge['IPAM']['Config'][0]['Gateway']
                    name = 'ca-shadow-' + uuid.uuid4().hex
                    # Preserve actual production mounts, UID, resource restrictions,
                    # env and network; replace only the executable entrypoint.
                    command = proxied_command(name, root / 'tests/shadow_adversarial_client.py',
                                              root / 'tools', None, isolated)
                    index = command.index('--entrypoint')
                    command[index:] = ['--entrypoint', 'python', command[index + 2], '/cli/claude']
                    try:
                        created = subprocess.run(command, capture_output=True, env=docker_env(), timeout=30)
                        if created.returncode:
                            raise ValueError('hostile container creation failed')
                        config = {'host': host, 'port': server.server_port,
                                  'forbidden_paths': [str(canary), str(credential),
                                      '/run/shadow-provider.env', '/var/run/docker.sock',
                                      '/github/workspace/.git/config', str(root / '.git/config')]}
                        raw = collect(['docker', 'start', '-a', '-i', name],
                                      json.dumps(config).encode(), name, timeout=60)
                        if dummy.encode() in raw:
                            raise ValueError('dummy credential leaked into output')
                        check_report(raw)
                        if attempts != ['/positive-control']:
                            raise ValueError('hostile client reached dummy host services')
                    finally:
                        removed = subprocess.run(['docker', 'rm', '-f', name],
                            capture_output=True, env=docker_env(), timeout=20)
                        if removed.returncode and b'No such container' not in removed.stderr:
                            raise ValueError('hostile client cleanup unconfirmed')
            if Path(credential).exists():
                raise ValueError('credential survived hostile probe')
        print('PASS: hostile stand-in denied host environment/files, writes and synthetic cache/artifact routes.')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Hostile stand-in probe failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
