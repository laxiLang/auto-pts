#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2017, Intel Corporation
# Copyright (c) 2023, Codecoup
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of Intel Corporation nor the names of its contributors
#       may be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

"""Windows utilities"""
import glob
import logging
import os
import re
import struct
import subprocess
import sys

import win32gui
import win32process
import wmi

try:
    import winreg
except ImportError:
    winreg = None


def python_bitness():
    return struct.calcsize('P') * 8


def _is_python32_exe(exe):
    try:
        proc = subprocess.run(
            [exe, '-c', 'import struct; print(struct.calcsize("P") * 8)'],
            capture_output=True, text=True, timeout=15, check=False)
        return proc.returncode == 0 and proc.stdout.strip() == '32'
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _iter_32bit_python_candidates(server_root=None):
    env_python = os.environ.get('AUTO_PTS_PYTHON32')
    if env_python:
        yield env_python

    for py_arg in ('-3-32', '-3.13-32', '-3.12-32', '-3.11-32', '-3.10-32'):
        try:
            proc = subprocess.run(
                ['py', py_arg, '-c', 'import sys; print(sys.executable)'],
                capture_output=True, text=True, timeout=15, check=False)
            if proc.returncode == 0:
                exe = proc.stdout.strip()
                if exe:
                    yield exe
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    if server_root:
        yield os.path.join(server_root, 'python32', 'python.exe')

    if winreg is not None:
        for root, key_path in (
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Python\PythonCore'),
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\WOW6432Node\Python\PythonCore'),
        ):
            try:
                with winreg.OpenKey(root, key_path) as core_key:
                    for index in range(winreg.QueryInfoKey(core_key)[0]):
                        version_key = winreg.EnumKey(core_key, index)
                        try:
                            with winreg.OpenKey(core_key, f'{version_key}\\InstallPath') as ip_key:
                                install_path = winreg.QueryValueEx(ip_key, '')[0]
                                yield os.path.join(install_path, 'python.exe')
                        except OSError:
                            pass
            except OSError:
                pass

    local_app = os.environ.get('LOCALAPPDATA')
    if local_app:
        yield from glob.iglob(os.path.join(local_app, 'Programs', 'Python', 'Python*-32', 'python.exe'))

    yield from glob.iglob(r'C:\Program Files (x86)\Python*\python.exe')

    current = sys.executable
    sibling = re.match(r'^(.*\\)(Python\d+)(\\python.exe)$', current, re.I)
    if sibling:
        yield sibling.group(1) + sibling.group(2) + '-32' + sibling.group(3)

    for where_cmd in (['where.exe', 'py'], ['where.exe', 'python']):
        try:
            proc = subprocess.run(where_cmd, capture_output=True, text=True,
                                  timeout=15, check=False)
            if proc.returncode != 0:
                continue
            for line in proc.stdout.splitlines():
                exe = line.strip()
                if exe.lower().endswith('.exe'):
                    yield exe
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass


def find_32bit_python(server_root=None):
    """Return path to a 32-bit python.exe for loading 32-bit PTS DLLs."""
    if server_root is None:
        server_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    seen = set()
    for candidate in _iter_32bit_python_candidates(server_root):
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(candidate) and _is_python32_exe(candidate):
            return candidate
    return None


def bundled_32bit_python_path(server_root=None):
    if server_root is None:
        server_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(server_root, 'python32', 'python.exe')

def get_pid_by_window_title(title):
    def callback(hwnd, hwnd_list):
        window_title = win32gui.GetWindowText(hwnd)
        if window_title.startswith(title):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                hwnd_list.append(pid)
            except Exception as e:
                logging.warning(f"Failed to get PID for hwnd {hwnd}: {e}")

    hwnd_list = []
    win32gui.EnumWindows(callback, hwnd_list)
    if hwnd_list:
        return hwnd_list[0]
    else:
        return None


def _terminate_process_safely(process, name):
    try:
        process.Terminate()
        logging.debug(f"{name} process (PID {process.ProcessId}) terminated successfully")
    except BaseException as exc:
        logging.exception(exc)
        logging.debug(f"There is no {name} process running with id: {process.ProcessId}")


def kill_all_processes(name):
    c = wmi.WMI()
    for ps in c.Win32_Process(name=name):
        _terminate_process_safely(ps, name)
