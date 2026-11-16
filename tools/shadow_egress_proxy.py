"""Fixed-origin API reverse-proxy prototype; NOT deployed or enabled.

No CONNECT, URL forwarding, redirects or configurable request destinations.
Intended only for a trusted proxy container on an internal provider network.
The proxy sees provider authentication; it must never receive runner tokens.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import re
import socket
import ssl
import threading
import time
from pathlib import Path

LIMIT = 1_000_000
PATHS = {'/v1/messages', '/v1/messages?beta=true',
         '/v1/messages/count_tokens', '/v1/messages/count_tokens?beta=true'}
REQUEST_BUDGET = 4  # Engineering candidate cap, not authorization for live spend.


def check_origin(origin):
    if (not isinstance(origin, str) or len(origin) > 253 or '.' not in origin or
            origin != origin.lower() or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                           for label in origin.split('.'))):
        raise ValueError('invalid fixed origin')
    try:
        ipaddress.ip_address(origin)
    except ValueError:
        return
    raise ValueError('origin must be a DNS name, not an address')


def public_addresses(origin, resolver=None):
    check_origin(origin)
    resolver = resolver or socket.getaddrinfo
    addresses = set()
    for family, kind, protocol, _name, sockaddr in resolver(origin, 443, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0])
        if (family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM or
                not ip.is_global or str(ip) == '168.63.129.16' or
                getattr(ip, 'ipv4_mapped', None) is not None or
                (len(sockaddr) > 3 and sockaddr[3] != 0)):
            raise ValueError('non-public or host/metadata destination')
        addresses.add(str(ip))
    if not addresses:
        raise ValueError('no approved destination addresses')
    return sorted(addresses, key=lambda address: (ipaddress.ip_address(address).version != 4, address))


def proxy_token(path):
    with Path(path).open('rb') as source:
        raw = source.read(8200)
    prefix = b'CLAUDE_CODE_OAUTH_TOKEN='
    if not raw.startswith(prefix) or not raw.endswith(b'\n'):
        raise ValueError('invalid proxy credential file')
    token = raw[len(prefix):-1].decode('ascii')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,4096}', token):
        raise ValueError('invalid proxy credential encoding')
    return token


class FixedHTTPS(http.client.HTTPSConnection):
    def __init__(self, origin):
        check_origin(origin)
        super().__init__(origin, port=443, timeout=30, context=ssl.create_default_context())

    def connect(self):
        # Resolve and check once, then connect to the checked numeric address.
        # TLS SNI and certificate verification still use the fixed DNS origin.
        address = public_addresses(self.host)[0]
        raw = socket.create_connection((address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def handler_for(origin, connection_factory=FixedHTTPS, *, token):
    check_origin(origin)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,4096}', token):
        raise ValueError('invalid proxy credential')
    slots = threading.BoundedSemaphore(4)
    budget_lock = threading.Lock()
    remaining = REQUEST_BUDGET

    class Proxy(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *_args):
            pass

        def reject(self, code):
            self.send_response(code)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True

        def do_CONNECT(self):
            self.reject(405)

        def do_GET(self):
            self.reject(405)

        def do_POST(self):
            nonlocal remaining
            if not slots.acquire(blocking=False):
                self.reject(503)
                return
            conn = None
            started = False
            try:
                if self.path not in PATHS or self.headers.get_all('Transfer-Encoding'):
                    raise ValueError('path or transfer encoding')
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or not re.fullmatch('[0-9]{1,7}', lengths[0]):
                    raise ValueError('length')
                length = int(lengths[0])
                if not 0 < length <= LIMIT:
                    raise ValueError('body limit')
                forwarded = {'Content-Type': 'application/json', 'Connection': 'close', 'Host': origin}
                auth_count = 0
                for key in ('authorization', 'x-api-key', 'anthropic-version', 'anthropic-beta'):
                    values = self.headers.get_all(key, [])
                    if len(values) > 1 or any(len(value) > 8192 for value in values):
                        raise ValueError('ambiguous header')
                    if values:
                        if key in ('authorization', 'x-api-key'):
                            auth_count += 1
                        else:
                            forwarded[key] = values[0]
                if auth_count != 1:
                    raise ValueError('authentication header')
                forwarded['authorization'] = 'Bearer ' + token
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('incomplete body')
                with budget_lock:
                    if remaining <= 0:
                        self.reject(429)
                        return
                    # Attempts count even when the upstream fails. No refunds
                    # or resets per connection, client key, or endpoint.
                    remaining -= 1
                conn = connection_factory(origin)
                conn.request('POST', self.path, body=body, headers=forwarded)
                response = conn.getresponse()
                if 300 <= response.status < 400:
                    raise ValueError('redirect refused')
                announced = response.getheader('Content-Length')
                if announced is not None and (not announced.isdigit() or int(announced) > LIMIT):
                    raise ValueError('upstream body limit')
                content_type = (response.getheader('Content-Type') or 'application/json').split(';')[0].strip()
                if content_type not in ('application/json', 'text/event-stream'):
                    raise ValueError('unsupported upstream content type')
                self.send_response(response.status)
                self.send_header('Content-Type', content_type)
                self.send_header('Connection', 'close')
                self.end_headers()
                started = True
                total = 0
                deadline = time.monotonic() + 600
                while True:
                    data = response.read1(8192)
                    if not data:
                        break
                    total += len(data)
                    if total > LIMIT or time.monotonic() >= deadline:
                        raise ValueError('upstream stream limit')
                    self.wfile.write(data)
                    self.wfile.flush()
            except (ValueError, OSError, http.client.HTTPException):
                if not started:
                    self.reject(502)
            finally:
                self.close_connection = True
                if conn is not None:
                    conn.close()
                slots.release()

    return Proxy


def server(origin, bind, *, token):
    """No CLI/default provider. A reviewed caller must supply trusted policy."""
    result = ThreadingHTTPServer(bind, handler_for(origin, token=token))
    result.daemon_threads = True
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--bind', required=True)
    parser.add_argument('--credential-file', required=True)
    args = parser.parse_args()
    bind = ipaddress.ip_address(socket.gethostbyname('shadow-egress') if args.bind == 'shadow-egress' else args.bind)
    if bind.version != 4 or not bind.is_private or bind.is_loopback or bind.is_link_local:
        raise SystemExit('proxy requires its private internal-network address')
    server(args.origin, (str(bind), 8080), token=proxy_token(args.credential_file)).serve_forever()
