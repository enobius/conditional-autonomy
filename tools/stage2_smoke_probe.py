"""Synthetic-only smoke probe for the pinned llama.cpp server (no evaluation data)."""
import argparse
import hashlib
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    args = parser.parse_args()
    evidence = args.root / 'evidence'
    evidence.mkdir(exist_ok=True)
    samples = []
    stopped = threading.Event()

    def monitor():
        while not stopped.is_set():
            output = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                                              '--format=csv,noheader,nounits'], text=True)
            samples.append({'time': time.time(), 'gpu_mib': int(output.strip())})
            stopped.wait(0.2)

    def request(endpoint, body=None):
        req = urllib.request.Request(args.url + endpoint,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as response:
            return json.load(response)

    def save(name, data):
        (evidence / (name + '.json')).write_text(json.dumps(data, indent=2))

    # Explicit smoke-test sampler order; not a final preregistration amendment.
    settings = dict(temperature=0.2, top_p=0.95, top_k=0, min_p=0.0,
        repeat_penalty=1.0, repeat_last_n=0, presence_penalty=0.0,
        frequency_penalty=0.0, typical_p=1.0, dry_multiplier=0.0,
        dry_penalty_last_n=0, xtc_probability=0.0, mirostat=0,
        dynatemp_range=0.0, top_n_sigma=-1.0, samplers=['top_p', 'temperature'],
        seed=11, cache_prompt=False, n_cache_reuse=0, id_slot=0,
        return_tokens=True, stream=False, n_predict=256)
    summary = {'synthetic_only': True, 'settings_requested': settings,
               'warmups_excluded_from_performance': True, 'runs': []}
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        save('props', request('/props'))
        unit = request('/tokenize', {'content': ' A synthetic memory test repeats ordinary words.',
                                     'add_special': False})['tokens']

        def run(name, count, erase):
            if erase:
                save(name + '_erase', request('/slots/0?action=erase', {}))
            tokens = (unit * ((count + len(unit) - 1) // len(unit)))[:count]
            result = request('/completion', dict(settings, prompt=tokens, ignore_eos=True))
            save(name, result)
            timings = result['timings']
            record = {'name': name, 'input_tokens': count, 'timings': timings,
                      'tokens_cached': result.get('tokens_cached'),
                      'truncated': result.get('truncated'),
                      'generation_settings': result.get('generation_settings')}
            summary['runs'].append(record)
            # In this pinned runtime tokens_cached is retained KV size AFTER
            # generation, not reused input. timings.cache_n measures reuse.
            assert timings['cache_n'] == 0, record
            assert timings['prompt_n'] == count, record
            assert timings['predicted_n'] == 256, record
            assert not result.get('truncated'), record
            actual = result['generation_settings']
            for key in ('temperature', 'top_p', 'top_k', 'min_p', 'repeat_penalty',
                        'presence_penalty', 'frequency_penalty', 'typical_p',
                        'dry_multiplier', 'xtc_probability', 'mirostat', 'dynatemp_range'):
                assert abs(actual[key] - settings[key]) < 1e-5, (key, actual[key])
            assert actual['samplers'] == settings['samplers'], actual['samplers']
            print(json.dumps({'completed': name, 'timings': timings}), flush=True)

        for index in range(3):
            run('warmup_' + str(index + 1), 8192, True)
        save('post_warmup_erase', request('/slots/0?action=erase', {}))
        # The pinned server reserves a boundary token: an exact 32768 sum
        # returns truncated=true even with all requested tokens generated.
        # Keep one token of headroom and require no truncation.
        run('near_full_context', 32511, True)
        # Identical consecutive request WITHOUT erase tests cache_prompt=False itself.
        run('cache_isolation_repeat', 32511, False)
        save('functional_erase', request('/slots/0?action=erase', {}))
        prompt = request('/apply-template', {'messages': [
            {'role': 'user', 'content': 'What is 2 plus 2? Answer briefly.'}]})['prompt']
        functional = request('/completion', dict(settings, prompt=prompt,
                                                 n_predict=128, ignore_eos=False))
        save('functional', functional)
        summary['functional_content'] = functional['content']
        assert functional['content'].strip(), 'Empty functional response'
        save('final_erase', request('/slots/0?action=erase', {}))
        summary['passed'] = True
    except Exception as error:
        summary['passed'] = False
        summary['error'] = repr(error)
        raise
    finally:
        stopped.set()
        thread.join(timeout=5)
        save('memory_samples', samples)
        summary['peak_gpu_mib'] = max((s['gpu_mib'] for s in samples), default=0)
        summary['under_16_decimal_gb'] = summary['peak_gpu_mib'] * 1024**2 <= 16_000_000_000
        save('summary', summary)
    hashes = {}
    for path in sorted((args.root / 'model').glob('*.safetensors')) + sorted(args.root.glob('*.gguf')):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                digest.update(block)
        hashes[path.name] = {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
    save('artifact_hashes', hashes)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
