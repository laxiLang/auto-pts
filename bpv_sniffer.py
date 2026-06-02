#
# auto-pts - The Bluetooth PTS Automation Framework
#
# BPV (Bluetooth Protocol Viewer) capture export via PTS ETSManager.dll.
# PTSControl RunTestCase writes .xml history; .cfa/.frm/.fsc require an
# explicit SnifferSave* call (see Google ACTS bluetooth_pts_device.py).

import ctypes
import os
import time

logging = __import__('logging').getLogger('server')
log = logging.debug

DEFAULT_SIG_ROOT = r'C:\Program Files (x86)\Bluetooth SIG'
ETS_MANAGER_REL = os.path.join('Bluetooth PTS', 'bin', 'ETSManager.dll')


def format_pts_test_case_name(test_case_name):
    """PTS workspace folder name for a test case (slashes/dashes -> underscores)."""
    return test_case_name.replace('/', '_').replace('-', '_')


def find_latest_test_log_dir(log_root, project_name, test_case_name):
    """Return newest workspace test log directory for a completed test case."""
    profile_dir = os.path.join(log_root, project_name)
    if not os.path.isdir(profile_dir):
        return None

    prefix = format_pts_test_case_name(test_case_name) + '_'
    candidates = []
    for name in os.listdir(profile_dir):
        path = os.path.join(profile_dir, name)
        if os.path.isdir(path) and name.startswith(prefix):
            candidates.append((os.path.getmtime(path), path))

    if not candidates:
        return None

    return max(candidates, key=lambda item: item[0])[1]


def default_ets_manager_path():
    sig_root = os.environ.get('PTS_SIG_ROOT', DEFAULT_SIG_ROOT)
    return os.path.join(sig_root, ETS_MANAGER_REL)


class PtsBpvSniffer:
    """Thin ctypes wrapper around ETSManager SnifferSave* exports."""

    def __init__(self, dll_path=None):
        self._lib = None
        dll_path = dll_path or default_ets_manager_path()
        if not os.path.isfile(dll_path):
            logging.warning('ETSManager.dll not found at %s', dll_path)
            return

        try:
            self._lib = ctypes.CDLL(dll_path)
            log('Loaded ETSManager from %s', dll_path)
        except OSError as exc:
            logging.warning('Failed to load ETSManager.dll from %s: %s', dll_path, exc)

    @property
    def available(self):
        return self._lib is not None

    def save(self, cfa_path, timeout=60):
        """Export BPV capture to cfa_path. Returns True if file appears."""
        if not self._lib:
            return False

        os.makedirs(os.path.dirname(cfa_path), exist_ok=True)
        path_bytes = cfa_path.encode('mbcs')

        self._lib.SnifferCanSaveEx.restype = ctypes.c_bool
        self._lib.SnifferCanSaveAndClearEx.restype = ctypes.c_bool

        can_save = bool(self._lib.SnifferCanSaveEx())
        can_save_clear = bool(self._lib.SnifferCanSaveAndClearEx())
        log('SnifferCanSaveEx=%s SnifferCanSaveAndClearEx=%s path=%s',
            can_save, can_save_clear, cfa_path)

        if not can_save and not can_save_clear:
            logging.warning('BPV sniffer cannot save (Fts.exe not capturing?)')
            return False

        self._lib.SnifferSaveEx.argtypes = [ctypes.c_char_p]
        self._lib.SnifferSaveAndClearEx.argtypes = [ctypes.c_char_p]

        if can_save:
            self._lib.SnifferSaveEx(path_bytes)
        else:
            self._lib.SnifferSaveAndClearEx(path_bytes)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.isfile(cfa_path) and os.path.getsize(cfa_path) > 0:
                log('BPV capture saved: %s (%d bytes)', cfa_path,
                    os.path.getsize(cfa_path))
                return True
            time.sleep(0.5)

        logging.warning('BPV capture not found after save: %s', cfa_path)
        return False

