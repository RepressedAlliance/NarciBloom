"""CI-only, bounded startup check for an already-built NarciBloom launcher.

Usage: python tools/check_frozen_startup.py <launcher> --mode font --report <json>
Requires CI=true; Linux also needs DISPLAY and xwininfo under workflow-supplied
isolated Xvfb. No input is sent. Only an exact English Tk title, a mapped window
and a live process for three seconds are checked. This does not verify backend
imports, installation, game detection or game behavior. Child termination always
runs; temporary cwd/log files remain on the disposable CI runner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

TITLES = {'font': 'NarciBloom · Font patch', 'chinese': 'NarciBloom · Chinese bundle'}
TIMEOUT = 30.0
STABLE = 3.0


def parse_xwininfo(tree, expected_title):
    """Return exact-title XIDs, excluding unrelated/error windows."""
    found = []
    for line in tree.splitlines():
        match = re.match(r'^\s*(0x[0-9a-fA-F]+)\s+"([^"]*)":', line)
        if match and match[2] == expected_title:
            found.append(match[1])
    return found


def windows_window(pid, expected_title):
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowTextW.restype = ctypes.c_int
    api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetClassNameW.restype = ctypes.c_int
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    found = []

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and api.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            kind = ctypes.create_unicode_buffer(128)
            api.GetWindowTextW(hwnd, title, len(title))
            api.GetClassNameW(hwnd, kind, len(kind))
            if title.value == expected_title and kind.value == 'TkTopLevel':
                found.append(hex(hwnd))
        return True

    if not api.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found[0] if found else None


def linux_window(expected_title, remaining):
    expires = time.monotonic() + remaining
    def query(*args):
        return subprocess.run(['xwininfo', *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              timeout=max(0.01, min(1.0, expires - time.monotonic())))
    tree = query('-root', '-tree')
    if tree.returncode:
        raise RuntimeError('xwininfo could not inspect the supplied DISPLAY: ' + tree.stderr.strip())
    for xid in parse_xwininfo(tree.stdout, expected_title):
        mapped = query('-id', xid)
        if mapped.returncode == 0 and re.search(r'^\s*Map State:\s*IsViewable\s*$', mapped.stdout, re.M):
            return xid
    return None


def _read_log(path):
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 65536))
        return dict(text=stream.read().decode('utf-8', errors='replace'),
                    bytes=size, truncated=size > 65536)


def check(launcher, mode='font', report_path=None):
    if os.environ.get('CI', '').casefold() != 'true':
        raise ValueError('Refusing to launch a GUI outside CI=true')
    if sys.platform not in ('win32', 'linux'):
        raise ValueError('Only Windows and Linux CI runners are supported')
    if sys.platform == 'linux' and (not os.environ.get('DISPLAY') or not shutil.which('xwininfo')):
        raise ValueError('Linux CI requires isolated DISPLAY and xwininfo supplied by the workflow')
    launcher = Path(launcher).resolve(strict=True)
    if not launcher.is_file():
        raise ValueError('Launcher must be an existing frozen executable')
    expected = TITLES[mode]
    directory = Path(tempfile.mkdtemp(prefix='narcibloom-startup-'))
    cwd = directory / 'cwd'
    cwd.mkdir()
    stdout_path, stderr_path = directory / 'stdout.log', directory / 'stderr.log'
    result = dict(passed=False, scope='Frozen Tk main-window startup only', mode=mode,
                  expected_title=expected, required_stable_seconds=STABLE,
                  timeout_seconds=TIMEOUT, backend_import_verified=False)
    child = None
    started = time.monotonic()
    try:
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            child = subprocess.Popen([str(launcher), '--mode', mode, '--language', 'en'],
                                     cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            stable_since, identity = None, None
            # Reserve three seconds for bounded termination and wait/kill.
            deadline = started + TIMEOUT - 3.0
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(f'Launcher exited before stable startup: {child.returncode}')
                window = (windows_window(child.pid, expected) if sys.platform == 'win32'
                          else linux_window(expected, max(0.01, deadline - time.monotonic())))
                now = time.monotonic()
                if window is None:
                    stable_since, identity = None, None
                elif window != identity:
                    stable_since, identity = now, window
                elif now - stable_since >= STABLE and child.poll() is None:
                    result.update(passed=True, window_id=window, stable_seconds=round(now - stable_since, 3))
                    break
                time.sleep(max(0, min(0.2, deadline - time.monotonic())))
            if not result['passed']:
                raise RuntimeError('No exact-title mapped Tk window stayed alive for three seconds within the startup budget')
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if child is not None:
            result['returncode_before_cleanup'] = child.poll()
            try:
                if child.poll() is None:
                    try:
                        child.terminate()
                    except OSError:
                        if child.poll() is None:
                            child.kill()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired) as exc:
                result.update(passed=False, cleanup_error=f'{type(exc).__name__}: {exc}')
            result['returncode_after_cleanup'] = child.returncode
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        result['stdout'] = _read_log(stdout_path)
        result['stderr'] = _read_log(stderr_path)
        fatal = ('Traceback (most recent call last):', 'Failed to execute script',
                 'NarciBloom could not open its window.')
        if any(marker in result[name]['text'] for name in ('stdout', 'stderr') for marker in fatal):
            result.update(passed=False, error='Startup log contains an immediate Python/launcher failure')
        if report_path is not None:
            report_path = Path(report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stdout_path, report_path.with_suffix('.stdout.log'))
            shutil.copyfile(stderr_path, report_path.with_suffix('.stderr.log'))
            report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('launcher', type=Path)
    parser.add_argument('--mode', choices=tuple(TITLES), default='font')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = check(args.launcher, args.mode, args.report)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('stdout', 'stderr')}, ensure_ascii=False))
    if not result['passed']:
        print(result['stderr']['text'][-4096:], file=sys.stderr)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
