"""UserPromptSubmit hook: a session is told, once, which of its lines the PM took off the Mon Studio board.

On the pinned page, « Fait / Retirer du tableau » (PM, 2026-11-17) takes a line off the board for good: the connector
notes it in ~/Mon Studio/.parc/retirees.json with the session that asked, the question number and its title, all
computed on the Mac from the session's own transcript (never a text sent by the page). At the next message of the PM in
that session, this hook prints one line per line retired, so the session stops recalling it in « Encore ouvert », then
marks it told.

Silent without Mon Studio (no cockpit.json), and never fails a prompt.
"""
import json
import os
import pathlib
import re
import sys
import time

LOCAL = re.compile(r'^local_[0-9a-f-]{36}$')
NUMERO = re.compile(r'^Q\d{1,4}$')


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def lire_json(chemin, defaut=None):
    try:
        return json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaut


def dossier_fiches():
    if os.environ.get('MON_STUDIO_APP_SESSIONS'):
        return pathlib.Path(os.environ['MON_STUDIO_APP_SESSIONS'])
    base = pathlib.Path.home() / ('Library/Application Support' if sys.platform == 'darwin' else '.config')
    return base / 'Claude' / 'claude-code-sessions'


def id_local(cli):
    """The app's local_… id of this session: CLAUDE_CODE_HOST_SESSION_ID, else its card (cliSessionId)."""
    env = os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or ''
    if LOCAL.match(env):
        return env
    if not cli:
        return ''
    for chemin in dossier_fiches().glob('*/*/local_*.json'):
        c = lire_json(chemin)
        if isinstance(c, dict) and c.get('cliSessionId') == cli and LOCAL.match(str(c.get('sessionId') or '')):
            return c['sessionId']
    return ''


def texte_avis(e):
    """The line the session reads: the number when there is one, the title in quotes, and what to do."""
    numero = e.get('question') if NUMERO.match(str(e.get('question') or '')) else ''
    titre = ' '.join(str(e.get('titre') or '').split())[:120]
    if numero and titre.startswith(numero):
        numero = ''   # the title already carries it
    quoi = ' '.join(x for x in (numero, f'« {titre} »' if titre else '') if x) or 'une de tes demandes'
    return (f"[Mon Studio] Le PM a retiré du tableau {quoi} (fait, ou plus d'actualité) : ne la rappelle plus dans "
            f"« Encore ouvert ». Si tu la reposes plus tard, elle revient au tableau.")


def avis(sid, chemin):
    """The lines for session `sid`, and the file updated so each is told once. A write that fails tells nothing."""
    r = lire_json(chemin, {})
    if not isinstance(r, dict):
        return []
    a_dire = [(k, e) for k, e in r.items() if isinstance(e, dict) and e.get('session') == sid and not e.get('prevenue')]
    if not a_dire:
        return []
    maintenant = time.time()
    for k, e in a_dire:
        e['prevenue'] = maintenant
    tmp = chemin.with_name(f'{chemin.name}.{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, chemin)
    except OSError:
        return []
    return [texte_avis(e) for _, e in sorted(a_dire, key=lambda x: x[1].get('quand') or 0)]


def main():
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        data = {}
    racine = mon_studio()
    chemin = racine / '.parc' / 'retirees.json'
    if not (racine / '.parc' / 'cockpit.json').exists() or not chemin.exists():
        return
    sid = id_local(str((data or {}).get('session_id') or ''))
    if not sid:
        return
    lignes = avis(sid, chemin)
    if lignes:
        print('\n'.join(lignes))


if __name__ == '__main__':
    try:
        main()
    except Exception:  # a hook never stops a turn
        pass
