"""Tests never touch the real Claude app folder, ~/.claude or ~/Mon Studio.

Importing this module (done by every test file) points HOME at a temporary folder and clears the
variables that could point elsewhere, so scripts, hooks and subprocesses resolve their default paths
inside it. An audit hook records any open of a real path; test_zzz_isolation_guard.py fails on one.
"""
import atexit
import os
import pwd
import shutil
import sys
import tempfile

REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
_VARS = ('MON_STUDIO', 'MON_STUDIO_APP_SESSIONS', 'MON_STUDIO_TRANSCRIPTS', 'MON_STUDIO_MARQUEURS',
         'MON_STUDIO_PLUGINS', 'CLAUDE_CONFIG_DIR', 'APPDATA', 'XDG_CONFIG_HOME', 'COCKPIT_IDENTITE',
         'MON_STUDIO_CLAUDE')

if os.environ.get('COCKPIT_TEST_HOME'):
    TEST_HOME = os.environ['COCKPIT_TEST_HOME']
else:
    TEST_HOME = os.path.realpath(tempfile.mkdtemp(prefix='cockpit-tests-home-'))
    os.environ['COCKPIT_TEST_HOME'] = TEST_HOME
    atexit.register(shutil.rmtree, TEST_HOME, ignore_errors=True)
os.environ['HOME'] = TEST_HOME
for _v in _VARS:
    os.environ.pop(_v, None)
# The Mac account's full name stands for the PM when nothing else names them (projets.nom_du_compte): tests see none,
# unless one sets COCKPIT_COMPTE itself.
os.environ['COCKPIT_COMPTE'] = ''

_REAL = tuple(os.path.join(REAL_HOME, p) for p in (
    'Library/Application Support/Claude', '.claude', 'Mon Studio', '.config/Claude'))
VIOLATIONS = []

if not getattr(sys, '_cockpit_audit', False):
    sys._cockpit_audit = True

    def _audit(event, args):
        if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
            try:
                p = os.fspath(args[0])
                p = p.decode() if isinstance(p, bytes) else p
            except Exception:
                return
            if p.startswith(_REAL) and not p.startswith(TEST_HOME):
                VIOLATIONS.append(p)
    sys.addaudithook(_audit)


def make_studio(folder):
    """A Studio folder as the plugin recognises it: `.claude/.studio-manifest.json` inside (synthetic content)."""
    manifest = os.path.join(str(folder), '.claude', '.studio-manifest.json')
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, 'w', encoding='utf-8') as f:
        f.write('{}')
    return folder
