"""Disabled-pilot topology: native TLS through a fixed, credential-free relay."""
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from tools.shadow_container import IMAGE, collect, command, docker_env, secret_file
from tools.shadow_native_tls_entry import FORBIDDEN, TOKEN_FILE
from tools.shadow_native_tls_relay import ORIGIN
from tools.shadow_network_run import execute, policy


def native_policy(path):
    if policy(path) != ORIGIN:
        raise ValueError('native TLS requires its fixed approved origin')


def mount(path, destination):
    resolved = Path(path).resolve(strict=True)
    if any(char in str(resolved) for char in ',\r\n'):
        raise ValueError('unsafe bind-mount source')
    return ['--mount', f'type=bind,source={resolved},target={destination},readonly']


def reviewer_command(name, binary, tools, credential, network, relay_ip, uid, gid):
    if (not re.fullmatch('ca-shadow-net-[0-9a-f]{32}', network) or
            any(type(value) is not int or not 0 < value < 2**32 - 1 for value in (uid, gid))):
        raise ValueError('invalid private network or non-root reviewer identity')
    address = ipaddress.IPv4Address(relay_ip)
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError('invalid private TLS relay address')
    args = command(name, binary, tools, None)
    args[args.index('--network') + 1] = network
    args[args.index('--user') + 1] = f'{uid}:{gid}'
    env_pos = args.index('CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-shadow-placeholder')
    del args[env_pos - 1:env_pos + 1]
    pos = args.index('--entrypoint')
    args[pos:pos] = ['--add-host', f'{ORIGIN}:{address}', '--dns', '127.0.0.1', *mount(credential, TOKEN_FILE)]
    args[-1] = 'tools.shadow_native_tls_entry'
    return args


def assert_private_bridge(info):
    if (info.get('Internal') is not True or info.get('EnableIPv6') is not False or
            info.get('Options', {}).get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated' or
            any(item.get('Gateway') for item in info['IPAM']['Config'])):
        raise ValueError('native reviewer bridge is not isolated')


def assert_reviewer(info, network):
    mounts = info['Mounts']
    if (set(info['NetworkSettings']['Networks']) != {network} or
            {item['Destination'] for item in mounts} != {'/cli/claude', '/sandbox/tools', TOKEN_FILE} or
            len(mounts) != 3 or any(item.get('RW') is not False for item in mounts) or
            any(item.split('=', 1)[0].upper() in FORBIDDEN for item in info['Config']['Env'])):
        raise ValueError('unexpected network, mount or environment on native reviewer')


def remove(args, missing):
    result = subprocess.run(['docker', *args], capture_output=True, env=docker_env(), timeout=20)
    if result.returncode and missing not in result.stderr:
        raise ValueError('native TLS cleanup was not confirmed')


@contextmanager
def topology(tools, suffix):
    front, relay = 'ca-shadow-net-' + suffix, 'ca-shadow-tls-' + suffix
    try:
        execute(['network', 'create', '--internal', '--opt',
                 'com.docker.network.bridge.gateway_mode_ipv4=isolated', front])
        assert_private_bridge(json.loads(execute(['network', 'inspect', front]))[0])
        execute(['create', '--name', relay, '--pull', 'never', '--network', front,
                 '--network-alias', 'native-tls-relay', '--read-only', '--cap-drop', 'ALL',
                 '--security-opt', 'no-new-privileges', '--user', '65534:65534',
                 '--sysctl', 'net.ipv4.ip_unprivileged_port_start=0', '--pids-limit', '32',
                 '--memory', '128m', '--cpus', '1',
                 *mount(Path(tools) / 'shadow_native_tls_relay.py', '/relay.py'),
                 '--entrypoint', 'python', IMAGE, '-B', '/relay.py', 'live'])
        execute(['network', 'connect', 'bridge', relay])
        execute(['start', relay])
        info = json.loads(execute(['inspect', relay]))[0]
        networks = info['NetworkSettings']['Networks']
        if (set(networks) != {front, 'bridge'} or
                {item['Destination'] for item in info['Mounts']} != {'/relay.py'}):
            raise ValueError('unexpected network or mount on TLS relay')
        for _ in range(25):
            if b'READY' in execute(['logs', relay]).splitlines():
                break
            time.sleep(0.2)
        else:
            raise ValueError('TLS relay did not become ready')
        yield front, networks[front]['IPAddress']
    finally:
        try:
            remove(['rm', '-f', relay], b'No such container')
        finally:
            remove(['network', 'rm', front], b'not found')


def run(binary, tools, prompt, token, policy_path):
    native_policy(policy_path)  # Must precede credential and Docker operations.
    uid, gid = getattr(os, 'getuid', lambda: 0)(), getattr(os, 'getgid', lambda: 0)()
    if uid <= 0 or gid <= 0:
        raise ValueError('native review requires a non-root Linux host user')
    suffix = uuid.uuid4().hex
    name = 'ca-shadow-' + suffix
    with secret_file(token) as credential, topology(tools, suffix) as (network, relay_ip):
        try:
            args = reviewer_command(name, binary, tools, credential, network, relay_ip, uid, gid)
            execute(args[1:])
            assert_reviewer(json.loads(execute(['inspect', name]))[0], network)
            return collect(['docker', 'start', '-a', '-i', name], prompt.encode('utf-8'), name)
        finally:
            remove(['rm', '-f', name], b'No such container')
