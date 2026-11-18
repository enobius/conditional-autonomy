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

from tools.shadow_container import IMAGE, collect, docker_env, proxied_command, secret_file
from tools import shadow_network_run as network


def check_report(raw):
    value = json.loads(raw)
    expected = {'kind': 'hostile-client-v1', 'clean_environment': True,
                'readonly_mount_view': True,
                'placeholder_only': True, 'host_files_hidden': True,
                'writes_blocked': True, 'routes_blocked': {'artifact': True, 'cache': True}}
    # Exact canonical encoding also distinguishes Boolean true from integer 1.
    if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('hostile client did not establish every expected denial')


def inspect_client(info, image, root, isolated):
    """Compare daemon-reported configuration to test policy before starting the client."""
    cfg, host = info['Config'], info['HostConfig']
    expected_env = {entry.partition('=')[0]: entry.partition('=')[2]
                    for entry in image['Config']['Env']}
    expected_env.update(PYTHONPATH='/sandbox', SHADOW_PROXY_TRANSPORT='1',
                        CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat01-shadow-placeholder')
    if (info['Image'] != image['Id'] or
            sorted(cfg['Env']) != sorted(k + '=' + v for k, v in expected_env.items()) or
            cfg['User'] != '65534:65534' or host['ReadonlyRootfs'] is not True or
            host['Privileged'] is not False or host['CapAdd'] or host['CapDrop'] != ['ALL'] or
            'no-new-privileges' not in (host['SecurityOpt'] or []) or
            host['NetworkMode'] != isolated or set(info['NetworkSettings']['Networks']) != {isolated}):
        raise ValueError('client configuration rejected')
    expected = sorted([(str(root / 'tests/shadow_adversarial_client.py'), '/cli/claude'),
                       (str(root / 'tools'), '/sandbox/tools')])
    if host['Tmpfs'] != {'/tmp': 'rw,exec,nosuid,nodev,size=64m'}:
        raise ValueError('client tmpfs rejected')
    binds = []
    for mount in info['Mounts']:
        if mount['Type'] == 'tmpfs' and mount['Destination'] == '/tmp':
            continue  # Some daemon versions enumerate HostConfig.Tmpfs here too.
        if mount['Type'] != 'bind' or mount['RW'] is not False:
            raise ValueError('client mount rejected')
        binds.append((mount['Source'], mount['Destination']))
    if sorted(binds) != expected:
        raise ValueError('client mount inventory rejected')


def bridge_control(host, port):
    """A trusted client, no mounts or credentials, GETs the synthetic host listener."""
    script = ("import sys,urllib.request as u; "
              "o=u.build_opener(u.ProxyHandler({})); "
              "r=o.open(sys.argv[1],timeout=3); "
              "sys.exit(0 if r.read(64)==b'synthetic endpoint only' else 1)")
    network.execute(['run', '--rm', '--pull', 'never', '--network', 'bridge',
                     '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
                     '--security-opt', 'no-new-privileges', '--entrypoint', 'python',
                     IMAGE, '-c', script, f'http://{host}:{port}/bridge-control'])


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
                    bridge_control(host, server.server_port)
                    controls = ['/positive-control', '/bridge-control']
                    if attempts != controls:
                        raise ValueError('bridge control not observed')
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
                        inspect_client(json.loads(network.execute(['inspect', name]))[0],
                                       json.loads(network.execute(['image', 'inspect', IMAGE]))[0],
                                       root, isolated)
                        config = {'host': host, 'port': server.server_port,
                                  'forbidden_paths': [str(canary), str(credential),
                                      '/run/shadow-provider.env', '/var/run/docker.sock',
                                      '/github/workspace/.git/config', str(root / '.git/config')]}
                        raw = collect(['docker', 'start', '-a', '-i', name],
                                      json.dumps(config).encode(), name, timeout=60)
                        if dummy.encode() in raw:
                            raise ValueError('dummy credential leaked into output')
                        check_report(raw)
                        if attempts != controls:
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
