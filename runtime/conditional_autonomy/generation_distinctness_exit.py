"""Isolated constant-generator fail-and-restore proof for T-19b."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    test = 'tests.test_generation_distinctness.GeneratorDistinctnessTests.test_approved_grid_is_reproducible_and_semantically_distinct'
    with tempfile.TemporaryDirectory() as directory:
        checkout = Path(directory)
        for name in ('runtime', 'tests', 'architecture'):
            shutil.copytree(root / name, checkout / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        target = checkout / 'runtime/conditional_autonomy/generation.py'
        original = target.read_bytes()
        content = original.decode('utf-8')
        if content.count('offset = seed % 120') != 1:
            print('Constant-generator proof: FAIL (mutation target not unique)')
            return 1

        def run():
            return subprocess.run([sys.executable, '-B', '-m', 'unittest', test, '-v'],
                                  cwd=checkout, capture_output=True, text=True,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0'),
                                  timeout=180)

        pristine = run()
        if pristine.returncode:
            print(pristine.stdout + pristine.stderr)
            return 1
        target.write_text(content.replace('offset = seed % 120', 'offset = 0'), encoding='utf-8')
        mutant = run()
        target.write_bytes(original)
        restored = run()
        if (mutant.returncode == 0 or 'test_approved_grid_is_reproducible' not in mutant.stderr
                or restored.returncode != 0):
            print('Constant-generator proof: FAIL')
            print(mutant.stdout + mutant.stderr + restored.stdout + restored.stderr)
            return 1
        print('Constant-generator proof: pristine PASS; seeded constant RED; restored PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
