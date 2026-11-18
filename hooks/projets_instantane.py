"""SessionStart and Stop hook: keeps the snapshot of the Studios fresh for the Mon Studio connector, without an LLM.

The connector is launched by the desktop app, and macOS refuses it any read under ~/Library/CloudStorage (the Drive,
where the Studios live): without help, the list by project shows every Studio as « membre », with no « À toi » and no
entries. projets.py, run outside the connector, writes what it read of each Studio to
~/Mon Studio/.parc/projets-sources.json, and the connector falls back to it for a Studio it cannot read.

This hook runs that copy of projets.py in the background, detached, its output thrown away, so a session never waits
for it and nothing reaches the model's context. Throttled: nothing is launched when the snapshot, or the last launch,
is less than 5 minutes old. Silent and a no-op when Mon Studio is not installed (no ~/Mon Studio/.parc/projets.py);
never fails a session.
"""
import os
import pathlib
import subprocess
import sys
import time

FRAIS_S = 300


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def recent(chemin, maintenant):
    try:
        return maintenant - chemin.stat().st_mtime < FRAIS_S
    except OSError:
        return False


def main():
    base = mon_studio() / '.parc'
    script = base / 'projets.py'
    if not script.is_file():
        return
    maintenant = time.time()
    marque = base / 'projets-sources.lance'
    if recent(base / 'projets-sources.json', maintenant) or recent(marque, maintenant):
        return
    marque.write_text(str(int(maintenant)), encoding='utf-8')   # a second hook in the same minutes launches nothing
    subprocess.Popen([sys.executable, str(script)], cwd=str(base), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:   # a hook never stops a session
        pass
    sys.exit(0)
