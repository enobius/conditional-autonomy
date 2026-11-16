"""Private-network orchestration candidate; requires separately approved policy.

Not used by the existing single-job workflow. Never defaults to a live origin.
"""
from contextlib import contextmanager
import json
import ipaddress
import os
from pathlib import Path
import subprocess
import time
import uuid

from tools.shadow_container import IMAGE, docker_env, secret_file, proxied_command, collect
from tools.shadow_egress_proxy import check_origin
from tools.shadow_artifact_binding import parse, read_regular


def policy(path):
    value = parse(read_regular(Path(path), 4096))
    if (not isinstance(value, dict) or set(value) != {'version', 'enabled', 'origin'} or
            value['version'] != 'shadow-provider-policy-1' or value['enabled'] is not True):
        raise ValueError('no enabled owner-approved provider policy')
    check_origin(value['origin'])
    return value['origin']


def execute(args):
    result = subprocess.run(['docker'] + args, capture_output=True, env=docker_env(), timeout=30)
    if result.returncode:
        raise ValueError('Docker topology operation failed')
    return result.stdout


@contextmanager
def topology(tools, origin, credential_file):
    check_origin(origin)
    tools = Path(tools).resolve(strict=True)
    credential_file = Path(credential_file).resolve(strict=True)
    if any(',' in str(path) or '\n' in str(path) or '\r' in str(path) for path in (tools, credential_file)):
        raise ValueError('unsafe trusted-code path')
    uid = getattr(os, 'getuid', lambda: 65534)()
    gid = getattr(os, 'getgid', lambda: 65534)()
    if uid == 0:
        raise ValueError('non-root proxy host identity required')
    suffix = uuid.uuid4().hex
    network, proxy = 'ca-shadow-net-' + suffix, 'ca-shadow-proxy-' + suffix
    try:
        execute(['network', 'create', '--internal', '--opt',
                 'com.docker.network.bridge.gateway_mode_ipv4=isolated', network])
        info = json.loads(execute(['network', 'inspect', network]))[0]
        if (info.get('Internal') is not True or info.get('EnableIPv6') is not False or
                info.get('Options', {}).get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated' or
                any(item.get('Gateway') for item in info['IPAM']['Config'])):
            raise ValueError('network isolation policy not enforced')
        execute(['create', '--name', proxy, '--pull', 'never', '--network', network,
                 '--network-alias', 'shadow-egress', '--read-only', '--cap-drop', 'ALL',
                 '--security-opt', 'no-new-privileges', '--user', f'{uid}:{gid}',
                 '--pids-limit', '32', '--memory', '256m', '--cpus', '1',
                 '--env', 'PYTHONPATH=/sandbox', '--mount',
                 f'type=bind,source={tools},target=/sandbox/tools,readonly',
                 '--mount', f'type=bind,source={credential_file},target=/run/shadow-provider.env,readonly',
                 '--entrypoint', 'python', IMAGE, '-m', 'tools.shadow_egress_proxy',
                 '--origin', origin, '--bind', 'shadow-egress', '--credential-file', '/run/shadow-provider.env'])
        execute(['network', 'connect', 'bridge', proxy])
        execute(['start', proxy])
        # The entrypoint resolves its internal-only alias and binds only that
        # interface. Docker assigns the endpoint address when it starts.
        inspected = json.loads(execute(['inspect', proxy]))[0]
        internal_ip = inspected['NetworkSettings']['Networks'][network]['IPAddress']
        address = ipaddress.ip_address(internal_ip)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError('invalid internal proxy address')
        internal_ip = str(address)
        ready = False
        for _ in range(30):
            result = subprocess.run(['docker', 'exec', proxy, 'python', '-c',
                'import socket; socket.create_connection(("' + internal_ip + '",8080),timeout=1).close()'],
                capture_output=True, env=docker_env(), timeout=3)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            raise ValueError('proxy did not become ready')
        yield network
    finally:
        removed = subprocess.run(['docker', 'rm', '-f', proxy], capture_output=True, env=docker_env(), timeout=20)
        net_removed = subprocess.run(['docker', 'network', 'rm', network], capture_output=True, env=docker_env(), timeout=20)
        if (removed.returncode and b'No such container' not in removed.stderr or
                net_removed.returncode and b'not found' not in net_removed.stderr):
            raise ValueError('topology cleanup not confirmed')


def run(binary, tools, prompt, token, policy_path):
    origin = policy(policy_path)  # Reject disabled/absent policy before creating resources.
    with secret_file(token) as credential, topology(tools, origin, credential) as network:
        name = 'ca-shadow-' + uuid.uuid4().hex
        try:
            args = proxied_command(name, binary, tools, None, network)
            created = subprocess.run(args, capture_output=True, env=docker_env(), timeout=30)
            if created.returncode:
                raise ValueError('review container creation failed')
            return collect(['docker', 'start', '-a', '-i', name], prompt.encode('utf-8'), name)
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, env=docker_env(), timeout=20)
