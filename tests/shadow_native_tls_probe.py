"""Offline native Claude OAuth/TLS rehearsal. No production mode or egress.

Uses a locally available, hash-checked Claude binary and pinned Docker image.
The two networks are isolated; a synthetic endpoint holds the disposable TLS
key. The reviewer alone gets the dummy token, as a read-only file. Requires
Docker and host cryptography, but never pulls an image or calls a provider.
"""
from datetime import datetime, timedelta, timezone
from hashlib import file_digest
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid

from tools import run_claude_shadow as runner
from tools.shadow_container import IMAGE
from tools.shadow_native_tls import assert_private_bridge, reviewer_command
from tools.shadow_native_tls_entry import TOKEN_FILE, load_token
from tools.shadow_native_tls_relay import CONNECTIONS, ORIGIN

DUMMY = 'sk-ant-oat01-offline-native-probe-dummy-only'
REVIEW = {'outcome': 'approve', 'findings': [], 'uncertainties': [], 'confidence': 0.5,
          'rationale': 'Synthetic transport fixture, not a review.'}
FORBIDDEN_ENV = {'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_WORKSPACE', 'GITHUB_OUTPUT',
                 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL',
                 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'}
CLIENT_INPUT = b'Review the synthetic fixture: before -> after.'


class SyntheticEndpoint(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass  # Never log request lines, headers, or payloads.

    def do_GET(self):
        print('FIXTURE_UNEXPECTED_GET', flush=True)
        self.send_error(404)

    def do_POST(self):
        if self.path not in ('/v1/messages', '/v1/messages?beta=true'):
            print('FIXTURE_REJECTED_PATH', flush=True)
            self.send_error(404)
            return
        if (self.headers.get_all('Authorization') != ['Bearer ' + DUMMY] or
                self.headers.get('x-api-key') is not None):
            print('FIXTURE_REJECTED_AUTH', flush=True)
            self.send_error(403)
            return
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 200_000:
            self.send_error(400)
            return
        data = json.loads(self.rfile.read(size))
        tool_names = {entry['name'] for entry in data.get('tools', [])}
        if (tool_names != {'DeferredToolPlaceholder', 'StructuredOutput'} or
                CLIENT_INPUT.decode() not in json.dumps(data.get('messages', []))):
            print('FIXTURE_REJECTED_INPUT', flush=True)
            self.send_error(400)
            return
        events = [
            ('message_start', {'type': 'message_start', 'message': {
                'id': 'msg_stub', 'type': 'message', 'role': 'assistant', 'content': [],
                'model': data.get('model'), 'stop_reason': None, 'stop_sequence': None,
                'usage': {'input_tokens': 1, 'output_tokens': 1}}}),
            ('content_block_start', {'type': 'content_block_start', 'index': 0,
                'content_block': {'type': 'tool_use', 'id': 'toolu_stub', 'name': 'StructuredOutput', 'input': {}}}),
            ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(REVIEW)}}),
            ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
            ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use',
                'stop_sequence': None}, 'usage': {'output_tokens': 1}}),
            ('message_stop', {'type': 'message_stop'}),
        ]
        body = ''.join(f'event: {name}\ndata: {json.dumps(event)}\n\n' for name, event in events).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
        print('SYNTHETIC_MODEL_REQUEST', flush=True)


def endpoint():
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 8443), SyntheticEndpoint)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain('/endpoint/leaf.pem', '/endpoint/key.pem')
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    print('READY', flush=True)
    server.serve_forever()


def client(peer):
    if FORBIDDEN_ENV & set(os.environ) or Path('/.git').exists() or Path('/sandbox/.git').exists():
        raise RuntimeError('unexpected credential or checkout in reviewer')
    if any(row.split()[1] == '00000000' for row in Path('/proc/net/route').read_text().splitlines()[1:]):
        raise RuntimeError('reviewer unexpectedly has a default IPv4 route')
    try:
        with socket.create_connection((peer, 8443), timeout=1):
            raise RuntimeError('reviewer reached the upstream network directly')
    except OSError:
        pass
    tls = ssl.create_default_context(cafile='/test-ca.pem')
    try:
        with socket.create_connection((ORIGIN, 443), timeout=5) as raw:
            with tls.wrap_socket(raw, server_hostname='wrong.invalid'):
                raise RuntimeError('incorrect TLS identity was accepted')
    except ssl.SSLCertVerificationError as error:
        if 'hostname mismatch' not in error.verify_message.lower():
            raise RuntimeError('unexpected cause for wrong-host rejection') from error
    token = load_token(TOKEN_FILE)
    if token != DUMMY:
        raise RuntimeError('only the fixed nonsecret dummy token is allowed')
    run = subprocess.run

    def run_with_fixture_ca(argv, **kwargs):
        env = kwargs['env']
        if FORBIDDEN_ENV.intersection(env) or env['CLAUDE_CODE_OAUTH_TOKEN'] != DUMMY:
            raise RuntimeError('unexpected native CLI environment')
        # Only the test-only trust root is injected. The CLI and the normal
        # OAuth path are unmodified; there is no base URL/proxy override.
        log = Path(env['HOME']) / 'offline-cli-debug.log'
        options = kwargs | {'timeout': 24, 'env': env | {'NODE_EXTRA_CA_CERTS': '/test-ca.pem'}}

        def diagnose():
            if log.exists():
                lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
                for line in [line for line in lines if re.search('tls|certificate|retry|failed|error', line, re.I)][-20:]:
                    print(line.replace(DUMMY, '[dummy]')[:360], file=sys.stderr)
        try:
            result = run([*argv, '--debug-file', str(log)], **options)
        except subprocess.TimeoutExpired:
            diagnose()
            raise
        if result.returncode:
            diagnose()
        return result

    runner.subprocess = SimpleNamespace(run=run_with_fixture_ca)
    with tempfile.TemporaryDirectory() as temp:
        result = Path(temp) / 'result.json'
        runner.run('/cli/claude', result, prompt=CLIENT_INPUT.decode(), oauth_token=token, runner_temp=temp)
        if json.loads(result.read_bytes()) != REVIEW:
            raise RuntimeError('unexpected synthetic verdict')
    print(json.dumps({'native_cli': True, 'synthetic_verdict': True, 'wrong_host_rejected': True,
                      'upstream_direct_blocked': True, 'reviewer_has_no_github_credentials': True}))


def generate_fixture_tls(ca_file, endpoint_dir):
    if openssl := shutil.which('openssl'):
        # Ubuntu hosted runner already supplies OpenSSL. No dependency install.
        parent = ca_file.parent
        ca_key = parent / 'ca-key.pem'
        csr = parent / 'leaf.csr'
        ext = parent / 'leaf.ext'
        ext.write_text(f'basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:{ORIGIN}\n', encoding='ascii')
        commands = [
            ['req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-days', '1',
             '-subj', '/CN=Offline shadow probe CA', '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
             '-keyout', ca_key, '-out', ca_file],
            ['req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
             '-subj', f'/CN={ORIGIN}', '-keyout', endpoint_dir / 'key.pem', '-out', csr],
            ['x509', '-req', '-in', csr, '-CA', ca_file, '-CAkey', ca_key, '-CAcreateserial',
             '-days', '1', '-extfile', ext, '-out', endpoint_dir / 'leaf.pem'],
        ]
        for command in commands:
            subprocess.run([openssl, *command], check=True, capture_output=True, timeout=10)
        # No long-lived trust material; the CA private key is never mounted.
        ca_key.unlink()
        (endpoint_dir / 'key.pem').chmod(0o644)  # Synthetic leaf key must be readable by fixture UID.
        return
    # Optional host dependency for the local Windows rehearsal.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    time_now = datetime.now(timezone.utc)
    ca_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Offline shadow probe CA')])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ORIGIN)])

    def template(key, issuer, subject):
        return (x509.CertificateBuilder().issuer_name(issuer).subject_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(time_now - timedelta(minutes=5)).not_valid_after(time_now + timedelta(hours=1)))

    root_cert = (template(ca_key, ca_name, ca_name)
                 .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                 .sign(ca_key, hashes.SHA256()))
    leaf_cert = (template(leaf_key, ca_name, leaf_name)
                 .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                 .add_extension(x509.SubjectAlternativeName([x509.DNSName(ORIGIN)]), critical=False)
                 .sign(ca_key, hashes.SHA256()))
    ca_file.write_bytes(root_cert.public_bytes(serialization.Encoding.PEM))
    (endpoint_dir / 'leaf.pem').write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    (endpoint_dir / 'key.pem').write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def docker(*args, timeout=40):
    proc = subprocess.run(['docker', *args], capture_output=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f'Docker {args[0]} failed: {proc.stderr.decode(errors="replace")[-2000:]}')
    return proc.stdout.decode()


def get_info(name):
    return json.loads(docker('inspect', name))[0]


def wait_ready(name):
    for _ in range(20):
        if 'READY' in docker('logs', name).splitlines():
            return
        time.sleep(0.25)
    raise RuntimeError('isolated fixture did not become ready')


def run_probe(binary=None):
    root = Path(__file__).resolve().parents[1]
    binary = Path(binary) if binary is not None else root / 'work' / 'claude-linux-stub' / 'claude'
    with binary.open('rb') as source:
        if file_digest(source, 'sha256').hexdigest() != runner.BINARY_SHA256:
            raise RuntimeError('local CLI does not match the pinned binary')
    label = uuid.uuid4().hex
    front, back = 'ca-shadow-net-' + label, 'ca-native-back-' + label
    receiver, bridge, reviewer = 'ca-native-endpoint-' + label, 'ca-native-relay-' + label, 'ca-shadow-' + label

    def mount(source, target):
        return ['--mount', f'type=bind,source={source},target={target},readonly']

    def create(name, network, mounts, flags, *args):
        docker('create', '--name', name, '--network', network, '--pull', 'never', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65534:65534',
               '--pids-limit', '64', '--memory', '2g', '--cpus', '2', '--env', 'PYTHONPATH=/sandbox',
               *mounts, *flags, '--entrypoint', 'python', IMAGE, '-B', *args)

    probe = mount(Path(__file__).resolve(), '/probe.py') + mount(root / 'tools', '/sandbox/tools')

    with tempfile.TemporaryDirectory(prefix='ca-native-tls-') as directory:
        fixture = Path(directory)
        certs, ca, token = fixture / 'endpoint', fixture / 'ca.pem', fixture / 'dummy-oauth'
        certs.mkdir()
        token.write_text('CLAUDE_CODE_OAUTH_TOKEN=' + DUMMY + '\n', encoding='ascii', newline='\n')
        token.chmod(0o600)
        generate_fixture_tls(ca, certs)
        try:
            for network in (front, back):
                docker('network', 'create', '--internal', '--opt',
                       'com.docker.network.bridge.gateway_mode_ipv4=isolated', network)
                config = json.loads(docker('network', 'inspect', network))[0]
                assert_private_bridge(config)
            create(receiver, back, probe, ['--network-alias', 'native-tls-endpoint', *mount(certs, '/endpoint')],
                   '/probe.py', 'endpoint')
            docker('start', receiver)
            wait_ready(receiver)
            create(bridge, front, mount(root / 'tools' / 'shadow_native_tls_relay.py', '/relay.py'),
                   ['--network-alias', 'native-tls-relay', '--sysctl', 'net.ipv4.ip_unprivileged_port_start=0'],
                   '/relay.py', 'fixture')
            docker('network', 'connect', back, bridge)
            docker('start', bridge)
            wait_ready(bridge)
            relay_info = get_info(bridge)
            relay_networks = relay_info['NetworkSettings']['Networks']
            if (set(relay_networks) != {front, back} or
                    {entry['Destination'] for entry in relay_info['Mounts']} != {'/relay.py'} or
                    any(key.split('=', 1)[0] in FORBIDDEN_ENV | {'CLAUDE_CODE_OAUTH_TOKEN'}
                        for key in relay_info['Config']['Env'])):
                raise RuntimeError('relay had an unexpected network or sensitive mount')
            endpoint_ip = get_info(receiver)['NetworkSettings']['Networks'][back]['IPAddress']
            identity = (getattr(os, 'getuid', lambda: 65534)(), getattr(os, 'getgid', lambda: 65534)())
            argv = reviewer_command(reviewer, binary, root / 'tools', token, front,
                                    relay_networks[front]['IPAddress'], *identity)
            # Keep production image, mounts and sandbox flags. Only the fixture
            # entrypoint and disposable trust root differ from the live CLI job.
            pos = argv.index('--entrypoint')
            argv[pos:pos] = [*mount(Path(__file__).resolve(), '/probe.py'), *mount(ca, '/test-ca.pem')]
            args = argv[:-2] + ['-B', '/probe.py', 'client', endpoint_ip]
            docker(*args[1:])
            client_info = get_info(reviewer)
            client_env = client_info['Config']['Env']
            if (set(client_info['NetworkSettings']['Networks']) != {front} or DUMMY in repr(client_info) or
                    any(key.split('=', 1)[0] in FORBIDDEN_ENV | {'CLAUDE_CODE_OAUTH_TOKEN'} for key in client_env) or
                    {entry['Destination'] for entry in client_info['Mounts']} !=
                    {'/probe.py', '/sandbox/tools', '/cli/claude', '/test-ca.pem', TOKEN_FILE}):
                raise RuntimeError('reviewer had unexpected networks, mounts, or credentials')
            try:
                evidence = json.loads(docker('start', '-a', reviewer, timeout=60))
            except RuntimeError:
                print(docker('logs', receiver).strip(), file=sys.stderr)
                print(docker('logs', bridge).strip(), file=sys.stderr)
                raise
            endpoint_log = docker('logs', receiver).splitlines()
            streams = docker('logs', bridge).splitlines().count('TLS_STREAM')
            if endpoint_log.count('SYNTHETIC_MODEL_REQUEST') != 1 or not 2 <= streams <= CONNECTIONS:
                print(json.dumps({'endpoint_events': endpoint_log, 'tls_streams': streams}), file=sys.stderr)
                raise RuntimeError('expected one verified model request and bounded TLS streams')
            print(json.dumps(evidence | {'encrypted_tls_passthrough': True, 'relay_has_no_token_or_key': True,
                                        'tls_streams': streams, 'model_requests': 1, 'live_provider_requests': 0,
                                        'other_fixture_requests_rejected': sum(
                                            line.startswith(('FIXTURE_REJECTED_', 'FIXTURE_UNEXPECTED_'))
                                            for line in endpoint_log)}))
        finally:
            for target in (reviewer, bridge, receiver):
                subprocess.run(['docker', 'rm', '-f', target], capture_output=True, timeout=20)
            for target in (front, back):
                subprocess.run(['docker', 'network', 'rm', target], capture_output=True, timeout=20)


if __name__ == '__main__':
    match sys.argv[1:]:
        case []:
            run_probe()
        case ['--binary', binary]:
            run_probe(binary)
        case ['endpoint']:
            endpoint()
        case ['client', peer]:
            client(peer)
        case _:
            raise SystemExit('invalid offline fixture mode')
