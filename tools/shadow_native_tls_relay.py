"""Bounded byte relay; no TLS termination, token, or client-selected peer."""
import ipaddress
import select
import socket
import sys
import time

ORIGIN = 'api.anthropic.com'
CONNECTIONS = 4  # TCP sessions, not a provider API request or spending limit.


def pump(first, second):
    """Copy bounded chunks, with no decryption or protocol rewriting."""
    ends = {first: second, second: first}
    deadline = time.monotonic() + 30
    remaining = 4_000_000
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
                chunk = source.recv(min(65536, remaining + 1))
                remaining -= len(chunk)
                if remaining < 0:
                    return
                if chunk:
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
            client, _ = listener.accept()
            with client:
                client.settimeout(5)
                header = b''
                while len(header) < 5:
                    chunk = client.recv(5 - len(header))
                    if not chunk:
                        break
                    header += chunk
                if len(header) != 5 or header[:2] != b'\x16\x03':
                    continue
                with socket.create_connection(peer, timeout=5) as remote:
                    remote.sendall(header)
                    print('TLS_STREAM', flush=True)
                    pump(client, remote)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('expected one explicit TLS relay mode')
    main(sys.argv[1])
