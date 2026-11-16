"""Real pinned CLI -> internal fixed-origin proxy -> synthetic SSE upstream.

No external network, real provider or real credential. Windows dummy env-file
transport is not a test of production Linux-host secret delivery.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from tools.shadow_container import IMAGE, proxied_command
from tests.shadow_proxy_network_probe import checked

PAYLOAD = {'outcome': 'approve', 'findings': [], 'uncertainties': [], 'confidence': 0.5,
           'rationale': 'Synthetic isolated integration test, not a review.'}
PROXY = r'''
import json, os
from http.server import ThreadingHTTPServer
from tools.shadow_egress_proxy import handler_for
payload = PAYLOAD_PLACEHOLDER
assert not {'GITHUB_TOKEN','GH_TOKEN','ACTIONS_RUNTIME_TOKEN'} & set(os.environ)
class Response:
    status=200
    def __init__(self, body):
        events = [
            ('message_start', {'type':'message_start','message':{'id':'msg_stub','type':'message','role':'assistant','content':[], 'model':body.get('model','stub'),'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}}}),
            ('content_block_start', {'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'toolu_stub','name':'StructuredOutput','input':{}}}),
            ('content_block_delta', {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':json.dumps(payload)}}),
            ('content_block_stop', {'type':'content_block_stop','index':0}),
            ('message_delta', {'type':'message_delta','delta':{'stop_reason':'tool_use','stop_sequence':None},'usage':{'output_tokens':1}}),
            ('message_stop', {'type':'message_stop'})]
        self.data=''.join('event: '+name+'\ndata: '+json.dumps(event)+'\n\n' for name,event in events).encode()
    def getheader(self,key): return 'text/event-stream' if key=='Content-Type' else None
    def read1(self,size):
        data,self.data=self.data[:size],self.data[size:]
        return data
class Connection:
    def __init__(self,origin): assert origin=='provider.example'
    def request(self,method,path,body,headers):
        assert method=='POST' and path in ('/v1/messages','/v1/messages?beta=true')
        self.body=json.loads(body)
        assert {tool['name'] for tool in self.body.get('tools',[])}=={'DeferredToolPlaceholder','StructuredOutput'}
        assert not {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN'} & set(headers)
        assert headers.get('authorization') == 'Bearer dummy-proxy-only'
        print(json.dumps({'stub_request':True,'path':path,'tools':['DeferredToolPlaceholder','StructuredOutput']}),flush=True)
    def getresponse(self): return Response(self.body)
    def close(self): pass
ThreadingHTTPServer(('0.0.0.0',8080),handler_for('provider.example',Connection,token='dummy-proxy-only')).serve_forever()
'''.replace('PAYLOAD_PLACEHOLDER', repr(PAYLOAD))


def main():
    root = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex
    network, proxy, client = ('ca-shadow-net-' + suffix, 'ca-shadow-proxy-' + suffix, 'ca-shadow-' + suffix)
    try:
        checked(['network', 'create', '--internal', '--opt',
                 'com.docker.network.bridge.gateway_mode_ipv4=isolated', network])
        checked(['run', '-d', '--name', proxy, '--network', network, '--network-alias', 'shadow-egress',
                 '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                 '--user', '65534:65534', '--pids-limit', '32', '--memory', '256m',
                 '--env', 'PYTHONPATH=/sandbox', '--mount',
                 f'type=bind,source={root / "tools"},target=/sandbox/tools,readonly',
                 '--entrypoint', 'python', IMAGE, '-u', '-c', PROXY])
        with tempfile.TemporaryDirectory(prefix='dummy-proxy-cli-') as directory:
            env_file = Path(directory) / 'dummy.env'
            env_file.write_text('CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-dummy-only\n', encoding='ascii')
            args = proxied_command(client, root / 'work/claude-linux-stub/claude', root / 'tools', env_file, network)
            created = subprocess.run(args, capture_output=True, timeout=30)
            if created.returncode:
                raise RuntimeError(created.stderr.decode(errors='replace')[-1000:])
            inspected = json.loads(checked(['inspect', client]))[0]
            assert 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-shadow-placeholder' in inspected['Config']['Env']
            assert 'sk-ant-oat01-dummy-only' not in repr(inspected)
            assert not any(mount.get('Source') == str(env_file) for mount in inspected.get('Mounts', []))
            output = subprocess.run(['docker', 'start', '-a', '-i', client],
                                    input=b'Review the synthetic local diff.', capture_output=True, timeout=90)
            if output.returncode:
                raise RuntimeError(output.stderr.decode(errors='replace')[-1000:])
            if json.loads(output.stdout) != PAYLOAD:
                raise AssertionError('unexpected integrated result')
            logs = checked(['logs', proxy])
            rows = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
            if len(rows) != 1 or rows[0].get('stub_request') is not True:
                raise AssertionError('proxy did not observe exactly one message request')
            print(json.dumps({'status':'PASS','exact_structured_output':True,
                              'real_cli_and_proxy':True,'synthetic_upstream':True,
                              'cli_has_placeholder_only':True,'proxy_requests':rows}))
    finally:
        for name in (client, proxy):
            subprocess.run(['docker','rm','-f',name], capture_output=True, timeout=20)
        subprocess.run(['docker','network','rm',network], capture_output=True, timeout=20)


if __name__ == '__main__':
    main()
