"""Bounded byte relay; no TLS termination, token, or client-selected peer."""
import ipaddress
import select
import socket
import sys
import time

ORIGIN = 'api.anthropic.com'
CONNECTIONS = 4  # TCP sessions, not a provider API request or spending limit.
SESSION_BYTES = 4_000_000
SESSION_SECONDS = 30
HELLO_SECONDS = 5
MAX_RECORD_BYTES = 16_384
MAX_HELLO_BYTES = 32_768
MAX_HELLO_RECORDS = 8
ECH_EXTENSION = 0xFE0D  # RFC 9849 / IANA TLS ExtensionType registry.


class Cursor:
    def __init__(self, data):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, size):
        end = self.offset + size
        if end > len(self.data):
            raise ValueError('truncated TLS field')
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def unsigned(self, size):
        return int.from_bytes(self.take(size), 'big')

    def vector(self, width):
        return self.take(self.unsigned(width))

    def done(self):
        return self.offset == len(self.data)


def check_name(hello):
    """Check the visible first ClientHello only; not HTTP or account identity."""
    fields = Cursor(hello)
    fields.take(34)  # Legacy version and client random.
    if len(fields.vector(1)) > 32:
        raise ValueError('invalid TLS session ID')
    ciphers = len(fields.vector(2))
    if ciphers < 2 or ciphers % 2 or 0 not in fields.vector(1):
        raise ValueError('invalid TLS cipher or compression list')
    extensions = Cursor(fields.vector(2))
    if not fields.done():
        raise ValueError('trailing ClientHello fields')
    seen = set()
    while not extensions.done():
        kind = extensions.unsigned(2)
        value = extensions.vector(2)
        if kind in seen or kind == ECH_EXTENSION:
            raise ValueError('duplicate or encrypted TLS extension')
        seen.add(kind)
        if kind == 0:  # RFC 6066 server_name: one DNS hostname only.
            wrapper = Cursor(value)
            names = Cursor(wrapper.vector(2))
            if (not wrapper.done() or names.unsigned(1) != 0 or
                    names.vector(2) != ORIGIN.encode('ascii') or not names.done()):
                raise ValueError('TLS hostname is not the pinned origin')
    if 0 not in seen:
        raise ValueError('missing TLS hostname')


def timeout_before(deadline, maximum=5):
    remaining = min(maximum, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('TLS relay deadline')
    return remaining


def read_exact(client, size, deadline):
    data = bytearray()
    while len(data) < size:
        client.settimeout(timeout_before(deadline))
        part = client.recv(size - len(data))
        if not part:
            raise ValueError('incomplete TLS ClientHello')
        data += part
    return data


def read_client_hello(client, deadline):
    """Buffer bounded TLS records without forwarding before hostname validation."""
    payload, wire = bytearray(), bytearray()
    for _ in range(MAX_HELLO_RECORDS):
        header = read_exact(client, 5, deadline)
        length = int.from_bytes(header[3:5], 'big')
        if (header[0] != 22 or not b'\x03\x01' <= header[1:3] <= b'\x03\x03' or
                not 0 < length <= MAX_RECORD_BYTES or len(payload) + length > MAX_HELLO_BYTES + 4):
            raise ValueError('invalid TLS handshake record')
        fragment = read_exact(client, length, deadline)
        wire += header + fragment
        payload += fragment
        if len(payload) < 4:
            continue
        expected_size = int.from_bytes(payload[1:4], 'big')
        if payload[0] != 1 or not 0 < expected_size <= MAX_HELLO_BYTES:
            raise ValueError('expected a bounded TLS ClientHello')
        if len(payload) >= expected_size + 4:
            if len(payload) != expected_size + 4:
                raise ValueError('unexpected data after first ClientHello')
            check_name(payload[4:])
            return bytes(wire)
    raise ValueError('too many initial TLS records')


def pump(first, second, *, deadline, remaining):
    """Copy bounded chunks, with no decryption or protocol rewriting."""
    ends = {first: second, second: first}
    while ends:
        wait = min(5, deadline - time.monotonic())
        if wait <= 0:
            return
        readable, _, _ = select.select(list(ends), [], [], wait)
        if not readable:
            return
        for source in readable:
            destination = ends[source]
            try:
                source.settimeout(timeout_before(deadline))
                chunk = source.recv(min(65536, remaining + 1))
                remaining -= len(chunk)
                if remaining < 0:
                    return
                if chunk:
                    destination.settimeout(timeout_before(deadline))
                    destination.sendall(chunk)
                else:
                    del ends[source]
                    destination.shutdown(socket.SHUT_WR)
            except OSError:
                return


def upstream(mode):
    if mode == 'fixture':
        peer = ipaddress.IPv4Address(socket.gethostbyname('native-tls-endpoint'))
        if not peer.is_private or peer.is_loopback or peer.is_link_local or peer.is_unspecified:
            raise ValueError('fixture peer is not private')
        return str(peer), 8443
    if mode != 'live':
        raise ValueError('invalid TLS relay mode')
    addresses = {ipaddress.IPv4Address(row[4][0]) for row in
                 socket.getaddrinfo(ORIGIN, 443, socket.AF_INET, socket.SOCK_STREAM)}
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise ValueError('native TLS origin did not resolve to public IPv4 only')
    return str(min(addresses)), 443


def main(mode):
    bind = socket.gethostbyname('native-tls-relay')
    address = ipaddress.IPv4Address(bind)
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError('relay listener is not on the private review bridge')
    peer = upstream(mode)
    with socket.create_server((bind, 443)) as listener:
        listener.settimeout(45)
        print('READY', flush=True)
        for _ in range(CONNECTIONS):
            try:
                client, _ = listener.accept()
            except TimeoutError:
                return
            with client:
                started = time.monotonic()
                deadline = started + SESSION_SECONDS
                try:
                    hello = read_client_hello(client, min(started + HELLO_SECONDS, deadline))
                    if len(hello) >= SESSION_BYTES:
                        raise ValueError('ClientHello exceeds session byte budget')
                except (OSError, ValueError):
                    print('TLS_PREFACE_REJECTED', flush=True)
                else:
                    try:
                        with socket.create_connection(peer, timeout=timeout_before(deadline)) as remote:
                            remote.settimeout(timeout_before(deadline))
                            remote.sendall(hello)
                            print('TLS_STREAM', flush=True)
                            pump(client, remote, deadline=deadline, remaining=SESSION_BYTES - len(hello))
                    except OSError:
                        print('TLS_RELAY_CLOSED', flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('expected one explicit TLS relay mode')
    main(sys.argv[1])
