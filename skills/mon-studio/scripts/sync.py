#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session-start hook: brings Mon Studio up to the plugin's version, without a word.

Does nothing unless Mon Studio was installed by the mon-studio skill (~/Mon Studio/.parc/cockpit.json) and the
plugin's version differs from the one recorded there. It compares versions, not files: a copy installed by
hand (to try a change before it ships) is left alone until the next version of the plugin. Nothing either once the
PM has disabled Mon Studio (`disabled` in cockpit.json, set by `install.py disable`): the next version of the
plugin must not install it again.

When the version moved, a detached process runs `install.py apply`: it copies parc.py, the connector, the page's
served code and the question tools into ~/Mon Studio/.parc, takes away what an older installation left for the local server (gone) and records the new version; the session does not wait.
A new connector runs from the app's next start. Nothing is ever printed: what a hook prints enters the
session's context and costs tokens. What happened goes to ~/Mon Studio/.parc/cockpit.log.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPTS.parent.parent.parent
INSTALL = SCRIPTS / 'install.py'
MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO', str(pathlib.Path.home() / 'Mon Studio')))
INTERNAL = MON_STUDIO / '.parc'
STATE = INTERNAL / 'cockpit.json'
LOCK = INTERNAL / 'cockpit.lock'
LOG = INTERNAL / 'cockpit.log'
LOCK_STALE_S = 300


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def plugin_version():
    return (read_json(PLUGIN_ROOT / '.claude-plugin' / 'plugin.json') or {}).get('version')


def log(text):
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass


def lock_is_fresh():
    try:
        return time.time() - LOCK.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return False


def needs_update():
    if sys.platform != 'darwin':
        return None
    state = read_json(STATE)
    version = plugin_version()
    if not isinstance(state, dict) or state.get('disabled') or not version or state.get('version') == version:
        return None
    return state.get('version'), version


def check():
    if not needs_update() or lock_is_fresh():
        return
    subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), '--apply'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def apply_update():
    versions = needs_update()
    if not versions:
        return
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if lock_is_fresh():
            return
        LOCK.touch()
    try:
        before, after = versions
        env = dict(os.environ, MON_STUDIO=str(MON_STUDIO))
        r = subprocess.run([sys.executable, str(INSTALL), 'apply'], capture_output=True, text=True, env=env, timeout=180)
        output = ' | '.join(l.strip() for l in (r.stdout + r.stderr).splitlines() if l.strip())
        if r.returncode == 0:
            log(f'mise à jour {before} → {after} : {output}')
        else:
            log(f'échec de la mise à jour {before} → {after} (nouvel essai au prochain démarrage de session) : {output}')
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def main():
    try:
        if '--apply' in sys.argv[1:]:
            apply_update()
        else:
            check()
    except Exception as exc:  # a hook never stops a session from starting
        log(f'erreur : {exc!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
