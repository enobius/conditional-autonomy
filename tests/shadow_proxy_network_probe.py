"""Local Docker isolated-bridge probe: dummy proxy upstream, no provider egress."""
import json
from pathlib import Path
import subprocess
import uuid

from tools.shadow_container import IMAGE

PROXY = r'''
from http.server import ThreadingHTTPServer
from tools.shadow_egress_proxy import handler_for
class Response:
    status = 200
    def getheader(self, key):
        return 'application/json' if key == 'Content-Type' else None
    def read1(self, size):
        if getattr(self, 'sent', False): return b''
        self.sent = True
        return b'{"local_stub":true}'
class Connection:
    def __init__(self, origin): assert origin == 'provider.example'
    def request(self, method, path, **kwargs): assert method == 'POST'
    def getresponse(self): return Response()
    def close(self): pass
ThreadingHTTPServer(('0.0.0.0',8080),handler_for('provider.example',Connection,token='dummy-proxy-only')).serve_forever()
'''

CLIENT = r'''
import json, os, socket, sys, time, urllib.request
proxy, gateway = sys.argv[1:]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(30):
    try:
        req=urllib.request.Request('http://'+proxy+':8080/v1/messages', data=b'{}',headers={'Authorization':'dummy-only'})
        result=json.loads(opener.open(req,timeout=2).read())
        break
    except OSError:
        time.sleep(0.1)
else: raise AssertionError('proxy not reachable')
assert result == {'local_stub':True}
blocked=[]
for address in ['169.254.169.254','168.63.129.16','8.8.8.8',gateway]:
    try:
        with socket.create_connection((address,80),timeout=0.5):
            raise AssertionError('unexpected direct access: '+address)
    except OSError as error:
        assert error.errno not in (111,61,10061), 'connection refused is not isolation proof'
        blocked.append({'address':address,'error':type(error).__name__,'errno':error.errno})
assert not {'GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN'} & set(os.environ)
try:
    socket.getaddrinfo('example.com',443)
    external_dns='resolved'
except socket.gaierror:
    external_dns='blocked'
print(json.dumps({'status':'PASS' if external_dns=='blocked' else 'FAIL','proxy_stub':result,
                  'blocked_direct_routes':blocked,'external_dns':external_dns}),flush=True)
assert external_dns=='blocked', 'embedded DNS can resolve external names'
'''


def checked(args):
    result = subprocess.run(['docker'] + args, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-2000:])
    return result.stdout.decode().strip()


def main():
    suffix = uuid.uuid4().hex
    network, proxy, client = ('ca-shadow-' + tag + '-' + suffix for tag in ('net', 'proxy', 'client'))
    tools = Path(__file__).resolve().parents[1] / 'tools'
    try:
        checked(['network', 'create', '--internal', '--opt',
                 'com.docker.network.bridge.gateway_mode_ipv4=isolated', network])
        config = json.loads(checked(['network', 'inspect', network]))[0]
        assert config['Internal'] is True and not config['EnableIPv6']
        assert config['Options']['com.docker.network.bridge.gateway_mode_ipv4'] == 'isolated'
        assert not config['IPAM']['Config'][0].get('Gateway'), 'isolated bridge unexpectedly has a gateway'
        # Read the ordinary bridge's host address only as a denial-test target;
        # never attach either test container to that network.
        default_bridge = json.loads(checked(['network', 'inspect', 'bridge']))[0]
        gateway = default_bridge['IPAM']['Config'][0]['Gateway']
        checked(['run', '-d', '--name', proxy, '--network', network, '--read-only',
                 '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                 '--pids-limit', '32', '--memory', '256m', '--env', 'PYTHONPATH=/sandbox',
                 '--mount', f'type=bind,source={tools},target=/sandbox/tools,readonly',
                 '--entrypoint', 'python', IMAGE, '-c', PROXY])
        info = json.loads(checked(['inspect', proxy]))[0]
        ip = info['NetworkSettings']['Networks'][network]['IPAddress']
        output = checked(['run', '--rm', '--name', client, '--network', network, '--read-only',
                          '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                          '--pids-limit', '32', '--memory', '256m', '--entrypoint', 'python',
                          IMAGE, '-c', CLIENT, ip, gateway])
        print(output)
    finally:
        for name in (client, proxy):
            subprocess.run(['docker','rm','-f',name], capture_output=True, timeout=20)
        subprocess.run(['docker','network','rm',network], capture_output=True, timeout=20)


if __name__ == '__main__':
    main()
