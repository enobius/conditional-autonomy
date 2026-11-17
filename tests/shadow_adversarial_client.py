"""Synthetic hostile CLI stand-in, run only inside the test container.

No provider protocol or real credential is used. Prints only Boolean outcomes.
"""
import json
import os
from pathlib import Path
import socket
import sys


def inspect_boundary(config):
    names = ['GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
             'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL', 'GITHUB_ENV', 'GITHUB_OUTPUT']
    clean_env = not any(name in os.environ for name in names)
    placeholder = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') == 'sk-ant-oat01-shadow-placeholder'
    hidden = True
    for path in config['forbidden_paths']:
        try:
            with open(path, 'rb') as source:
                source.read(1)
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            continue
        hidden = False
    writes_blocked = True
    for path in ['/sandbox/tools/hostile-marker', '/hostile-marker']:
        try:
            with open(path, 'xb') as output:
                output.write(b'synthetic marker')
        except OSError:
            continue
        writes_blocked = False
    routes = {}
    for name in ['artifact', 'cache']:
        # Real connect/send attempt to a host-only synthetic service, not GitHub.
        try:
            with socket.create_connection((config['host'], config['port']), timeout=1) as connection:
                connection.sendall(('GET /' + name + ' HTTP/1.0\r\nHost: canary\r\n\r\n').encode())
                connection.recv(128)
            routes[name] = False
        except OSError as exc:
            # Refusal proves a route exists, not isolation; fail closed on it.
            routes[name] = exc.errno not in (111, 61, 10061)
    return {'kind': 'hostile-client-v1', 'clean_environment': clean_env,
            'placeholder_only': placeholder, 'host_files_hidden': hidden,
            'writes_blocked': writes_blocked, 'routes_blocked': routes}


if __name__ == '__main__':
    config = json.loads(sys.stdin.buffer.read(100_000))
    print(json.dumps(inspect_boundary(config), sort_keys=True))
