"""Fail-closed, no-egress container prototype. Not yet wired into Actions.

Deliberately cannot contact a real provider: approved proxy-only networking is
not implemented. Linux host required for tmpfs credential-file delivery.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

IMAGE = 'python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39'
MAX_BYTES = 1_000_000


@contextmanager
def secret_file(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,4096}', token):
        raise ValueError('invalid provider credential encoding')
    # This file is tmpfs-backed, but env-file consumers persist values in Docker
    # configuration. The isolated path instead mounts it in the proxy only.
    if os.name != 'posix' or not Path('/proc/mounts').exists():
        raise ValueError('Linux tmpfs host required')
    mounts = Path('/proc/mounts').read_text().splitlines()
    if not any(line.split()[1:3] == ['/dev/shm', 'tmpfs'] for line in mounts):
        raise ValueError('credential directory is not the expected tmpfs')
    with tempfile.TemporaryDirectory(prefix='ca-shadow-secret-', dir='/dev/shm') as directory:
        path = Path(directory) / 'provider.env'
        with open(path, 'x', encoding='ascii', opener=lambda p, f: os.open(p, f, 0o600)) as output:
            output.write('CLAUDE_CODE_OAUTH_TOKEN=' + token + '\n')
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


def command(name, binary, tools, credential_file):
    if not re.fullmatch('ca-shadow-[0-9a-f]{32}', name):
        raise ValueError('invalid private container name')
    binary, tools = (Path(value).resolve(strict=True) for value in (binary, tools))
    credential_file = Path(credential_file).resolve(strict=True) if credential_file is not None else None
    if not binary.is_file() or not tools.is_dir() or credential_file is not None and not credential_file.is_file():
        raise ValueError('invalid container inputs')
    if not (tools / 'shadow_container_entry.py').is_file():
        raise ValueError('missing trusted container entrypoint')
    if any(',' in str(path) or '\n' in str(path) or '\r' in str(path)
           for path in (binary, tools) + ((credential_file,) if credential_file is not None else ())):
        raise ValueError('unsafe mount path')
    return ['docker', 'create', '--name', name, '-i', '--pull', 'never',
            '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--user', '65534:65534',
            '--pids-limit', '64', '--memory', '2g', '--cpus', '2',
            '--ulimit', 'fsize=1048576:1048576',
            '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=64m',
            '--env', 'PYTHONPATH=/sandbox',
            *(['--env-file', str(credential_file)] if credential_file is not None else
              ['--env', 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-shadow-placeholder']),
            '--mount', f'type=bind,source={binary},target=/cli/claude,readonly',
            '--mount', f'type=bind,source={tools},target=/sandbox/tools,readonly',
            '--entrypoint', 'python', IMAGE, '-m', 'tools.shadow_container_entry']


def docker_env():
    # No DOCKER_HOST/context overrides, GitHub token, runtime/cache credentials,
    # provider credentials or runner command files are inherited by the client.
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/nonexistent',
            'DOCKER_CONFIG': '/nonexistent'}


def proxied_command(name, binary, tools, credential_file, network):
    """Only use with a verified private isolated bridge and trusted proxy peer.

    This builder does not create/verify that network; the orchestrator must.
    """
    if not re.fullmatch('ca-shadow-net-[0-9a-f]{32}', network):
        raise ValueError('invalid private network name')
    # Real provider authentication belongs to the proxy, never this container.
    args = command(name, binary, tools, None)
    args[args.index('--network') + 1] = network
    index = args.index('--entrypoint')
    args[index:index] = ['--env', 'SHADOW_PROXY_TRANSPORT=1']
    return args


def collect(args, prompt, name, *, timeout=600):
    """Bound both pipes while running; force-remove the entire container."""
    if not re.fullmatch('ca-shadow-[0-9a-f]{32}', name):
        raise ValueError('invalid private container name')
    if not prompt or len(prompt) > 100_000 or not 0 < timeout <= 600:
        raise ValueError('invalid prompt or deadline')
    overflow = threading.Event()
    lock = threading.Lock()
    stdout = bytearray()
    total = 0
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=docker_env())

    def drain(stream, retain):
        nonlocal total
        while True:
            data = stream.read(4096)
            if not data:
                return
            with lock:
                total += len(data)
                if total > MAX_BYTES:
                    overflow.set()
                elif retain:
                    stdout.extend(data)

    def feed():
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    workers = [threading.Thread(target=drain, args=(proc.stdout, True), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, False), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    failed = False
    cleanup_ok = False
    try:
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if overflow.is_set() or time.monotonic() >= deadline:
                failed = True
                break
            time.sleep(0.05)
    finally:
        # Exact generated target only; never enumerate or remove other containers.
        try:
            removal = subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                                     env=docker_env(), timeout=20)
            # --rm may have removed a normally completed container already.
            cleanup_ok = removal.returncode == 0 or b'No such container' in removal.stderr
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            for worker in workers:
                if worker.ident is not None:
                    worker.join(timeout=2)
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
    if (failed or overflow.is_set() or proc.returncode != 0 or not cleanup_ok or
            any(worker.is_alive() for worker in workers)):
        raise ValueError('isolated review failed, exceeded bounds, or cleanup was not confirmed')
    return bytes(stdout)


def run(binary, tools, prompt, token):
    """Legacy TEST-ONLY no-egress fixture; use dummy tokens, never real secrets.

    Unlike the isolated workflow's proxy-only path, this old env-file fixture
    persists its dummy token in Docker configuration. No workflow calls it.
    """
    name = 'ca-shadow-' + uuid.uuid4().hex
    with secret_file(token) as credential:
        try:
            created = subprocess.run(command(name, binary, tools, credential),
                                     capture_output=True, env=docker_env(), timeout=30)
            if created.returncode:
                raise ValueError('container creation failed')
            # Confirm creation before starting the attach/timeout phase, so
            # cleanup cannot race an in-flight docker run/create operation.
            return collect(['docker', 'start', '-a', '-i', name], prompt.encode('utf-8'), name)
        finally:
            # Also cover failed/ambiguous creation. Errors propagate; never
            # claim an uncertain daemon operation was successfully cleaned up.
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                           env=docker_env(), timeout=20)
