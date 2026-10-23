"""Run the fixed packaged test capsule without enabling a live model route."""
import argparse
from datetime import datetime, timezone
import faulthandler
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True
from verify_package import verify

ROOT = Path(__file__).resolve().parent


def command_result(command, timeout, log_path):
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        text = result.stdout + result.stderr
        info = {'exitCode': result.returncode, 'timedOut': False}
    except subprocess.TimeoutExpired as error:
        decoded = lambda value: value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        text = decoded(error.stdout) + decoded(error.stderr) + f'\nJudge subprocess exceeded {timeout}s and was terminated.\n'
        info = {'exitCode': None, 'timedOut': True}
    info['elapsedMs'] = round((time.perf_counter() - started) * 1000, 3)
    log_path.write_text(text, encoding='utf-8')
    return info, text


def test_plan(root):
    plan = json.loads((root / 'judge_test_plan.json').read_text(encoding='utf-8'))
    for key in ('primaryModules', 'separateSdkModules', 'nodeFiles'):
        names = plan[key]
        if not isinstance(names, list) or not names or len(names) != len(set(names)):
            raise ValueError(f'Empty or duplicate test plan entries: {key}')
        for name in names:
            if key == 'nodeFiles':
                valid = re.fullmatch(r'test_[A-Za-z0-9_]+\.cjs', name)
                filename = name
            else:
                valid = re.fullmatch(r'(?:test_[A-Za-z0-9_]+|mock_lifecycle_test)', name)
                filename = name + '.py'
            if not valid or not (root / filename).is_file():
                raise ValueError(f'Unsafe or missing test capsule entry: {key}')
    if set(plan['primaryModules']) & set(plan['separateSdkModules']):
        raise ValueError('SDK tests must run in separate processes')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory outside immutable package')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error('Output directory must be new and outside the immutable package')
    if sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 12, 2) or sys.platform != 'win32' or platform.machine().upper() != 'AMD64':
        parser.error('Requires exact CPython 3.12.2 Windows AMD64')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['TOUCHLINE_REVIEW_REPO'] = str(ROOT)
    before = verify(ROOT)
    plan = test_plan(ROOT)
    node_path = shutil.which('node')
    if not node_path:
        parser.error('Existing Node.js runtime required; no download attempted')
    output.mkdir(parents=True)
    faulthandler.dump_traceback_later(180, exit=True)
    started = time.perf_counter()
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(plan['primaryModules'])
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (output / 'judge-tests.txt').write_text(log.getvalue(), encoding='utf-8')
    sdk_import, import_log = command_result([sys.executable, '-B', 'sdk_import_smoke.py', str(output / 'sdk-import-result.json')], 45, output / 'sdk-import.txt')
    sdk_results = []
    logs = [log.getvalue(), import_log]
    for module in plan['separateSdkModules']:
        info, text = command_result([sys.executable, '-B', '-m', 'unittest', '-v', module], 60, output / (module + '.txt'))
        count = re.search(r'Ran (\d+) tests?', text)
        sdk_results.append({'module': module, 'separateProcess': True, 'testsRun': int(count.group(1)) if count else None, **info, 'transport': 'injected/mocked; no actual model request'})
        logs.append(text)
    node_results = []
    for filename in plan['nodeFiles']:
        info, text = command_result([node_path, '--test', '--test-reporter=tap', filename], 30, output / (filename + '.txt'))
        count = re.search(r'# tests (\d+)', text)
        node_results.append({'file': filename, 'testsRun': int(count.group(1)) if count else None, **info})
        logs.append(text)
    after = verify(ROOT)
    report = {
        'verifiedAtUtc': datetime.now(timezone.utc).isoformat(),
        'mode': 'recorded-default synthetic proof / injected SDK tests',
        'liveProviderEnabledByRunner': False,
        'runtime': {'python': platform.python_version(), 'platform': 'Windows AMD64'},
        'primaryModules': plan['primaryModules'], 'testsRun': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': len(result.skipped), 'elapsedMs': round((time.perf_counter() - started) * 1000, 3),
        'sdkImport': sdk_import, 'separateSdk': sdk_results, 'browserTests': node_results,
        'totalTestsRun': result.testsRun + sum(item['testsRun'] or 0 for item in sdk_results + node_results),
        'packageBefore': before, 'packageAfter': after,
        'limitations': ['Historical receipts are not fresh inference', 'Mock SDK tests do not prove live server cancellation', 'No contest submission or result claimed'],
    }
    success = result.wasSuccessful() and sdk_import['exitCode'] == 0 and all(item['exitCode'] == 0 and item['testsRun'] for item in sdk_results + node_results)
    report['passed'] = bool(success)
    (output / 'judge-results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps(report, indent=2))
    if not success:
        print('\n'.join(logs))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
