"""Exercise orchestration/readiness/cleanup with a reserved .example origin.

No API requests or credentials. The trusted proxy has an egress interface, but
the only connection attempted is its internal readiness socket.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools import shadow_network_run as network


def main():
    client_env = {'PATH': os.environ['PATH'], 'SYSTEMROOT': os.environ.get('SYSTEMROOT', ''),
                  'DOCKER_CONFIG': str(Path(__file__).resolve().parents[1] / 'work/no-docker-credentials')}
    with patch.object(network, 'docker_env', return_value=client_env), tempfile.TemporaryDirectory() as directory:
        credential = Path(directory) / 'dummy.env'
        credential.write_bytes(b'CLAUDE_CODE_OAUTH_TOKEN=dummy-proxy-only\n')
        with network.topology(Path('tools'), 'provider.example', credential) as name:
            config = json.loads(network.execute(['network', 'inspect', name]))[0]
            proxy_id = next(iter(config['Containers']))
            proxy = json.loads(network.execute(['inspect', proxy_id]))[0]
            assert 'dummy-proxy-only' not in repr(proxy)
            assert not any(value.startswith('CLAUDE_CODE_OAUTH_TOKEN=') for value in proxy['Config']['Env'])
            assert any(mount['Destination'] == '/run/shadow-provider.env' and mount['RW'] is False
                       for mount in proxy['Mounts'])
            assert set(proxy['NetworkSettings']['Networks']) == {name, 'bridge'}
            outward = proxy['NetworkSettings']['Networks']['bridge']['IPAddress']
            code = ('import socket; s=socket.socket(); s.settimeout(1); '
                    'r=s.connect_ex(("' + outward + '",8080)); '
                    'assert r in (111,61,10061), str(r)')
            network.execute(['exec', proxy_id, 'python', '-c', code])
            print(json.dumps({'status':'PASS','isolated_network':True,'internal_ready':True,
                              'external_interface_not_listening':True,'provider_requests':0,
                              'proxy_secret_readonly_mount':True,'token_absent_from_docker_config':True}))
        print(json.dumps({'cleanup':'confirmed by orchestrator','provider_origin':'reserved .example only'}))


if __name__ == '__main__':
    main()
