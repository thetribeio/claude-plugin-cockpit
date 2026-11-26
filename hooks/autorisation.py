#!/usr/bin/env python3
"""PermissionRequest hook: lets the PM allow or deny a waiting tool from the pinned page « Mon Studio ».

Off by default. It does nothing, prints nothing and exits at once unless ~/Mon Studio/.parc/cockpit.json holds
`"autorisations_tableau": true`; with `"autorisations_sessions": [ids]`, only those sessions (CLI session id, or the
app's local_… id) are concerned, for a trial on one session.

When on, it lists the Unix sockets held by the local connector (mcp_mon_studio.py), one per running instance:
~/Mon Studio/.parc/autorisations-<pid>.sock. The desktop app starts two instances, one per client (« claude-ai » and
« local-agent-mode »), and the pinned page talks to the instance of its own client, so the hook does not know which one
will answer. It connects to each socket (2 s to connect; one that refuses is skipped), sends the same request (random
id, session, cwd, tool, extract cut at 300 characters, time) on every connection, and waits on all of them at once for
the PM's click, relayed by the MCP tool `decider` of whichever instance the page called:

  allow  this request only: no permanent rule, no `updatedPermissions`
  deny   with a short message for Claude

The first valid answer (same id, allow or deny) wins; the hook then closes every connection, so the request leaves the
other instances too. No socket reachable, every connection closed, unreadable answers only, or no answer in time: it
exits without output, and the app's normal permission window stays (the hook runs alongside it; whichever answers first
applies). It never writes the request's content, or any nonce, to disk. On Windows (no Unix socket everywhere) it does
nothing more.

Switch on or off, it first leaves a trace of the request: ~/Mon Studio/.parc/demandes-autorisation/<session>.json, with
the time and the tool's name only. The board reads it to tell a tool that waits for the PM's authorization from a tool
that simply runs long (a 10 min test suite, PM 2026-11-26: two running sessions read « arrêtée sur une autorisation »).
"""
import json
import os
import pathlib
import re
import secrets
import select
import socket
import sys
import time

MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO', str(pathlib.Path.home() / 'Mon Studio')))
INTERNE = MON_STUDIO / '.parc'
ETAT = INTERNE / 'cockpit.json'
MOTIF_SOCKET = 'autorisations-*.sock'   # one per connector instance
# The hook is declared with a 30 min timeout: it gives up just before, so that it always ends on its own.
ATTENTE_S = float(os.environ.get('MON_STUDIO_AUTORISATION_ATTENTE', 1790))
CONNEXION_S = 2
EXTRAIT_MAX = 300
CHAMPS = ('command', 'file_path', 'notebook_path', 'path', 'url', 'pattern', 'query', 'prompt', 'text', 'message',
          'body', 'title', 'subject', 'description')
REFUS = 'Refusé par le PM depuis Mon Studio.'


def extrait(nom, entree, n=EXTRAIT_MAX):
    """« Bash · git push origin main »: the tool, then its command, path or first text field, on one line."""
    detail = ''
    if isinstance(entree, dict):
        cles = [k for k in CHAMPS if isinstance(entree.get(k), str) and entree[k].strip()]
        cles += [k for k, v in entree.items() if k not in cles and isinstance(v, str) and v.strip()]
        detail = ' '.join(entree[cles[0]].split()) if cles else ''
    ligne = f'{nom} · {detail}' if nom and detail else (nom or detail or '')
    return ligne if len(ligne) <= n else ligne[:n - 1].rstrip() + '…'


def concerne(etat, demande):
    """True when the switch is on and this session is in the trial list, if there is one."""
    if not isinstance(etat, dict) or etat.get('autorisations_tableau') is not True:
        return False
    liste = etat.get('autorisations_sessions')
    if liste is None:
        return True
    ids = {demande.get('session_id'), os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')} - {None, ''}
    return isinstance(liste, list) and bool(ids & set(liste))


def sortie(decision):
    d = {'behavior': decision}
    if decision == 'deny':
        d['message'] = REFUS
    return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': d}}


def connecter(message):
    """One connection per live connector socket, each already holding `message`: the same for every instance. A
    socket that refuses (dead, or an instance that just stopped) is skipped. Shared with reponse_directe.py."""
    ligne = (json.dumps(message, ensure_ascii=False) + '\n').encode()
    connexions = []
    for chemin in sorted(INTERNE.glob(MOTIF_SOCKET)):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(CONNEXION_S)
            s.connect(str(chemin))
            s.sendall(ligne)
        except OSError:
            s.close()
            continue
        connexions.append(s)
    return connexions

def demander(demande, attente=ATTENTE_S):
    """'allow', 'deny', or None (no answer: the normal window stays)."""
    ident = secrets.token_hex(16)
    message = {'v': 1, 'type': 'demande', 'id': ident, 'session_id': demande.get('session_id') or '',
               'cwd': demande.get('cwd') or '', 'tool_name': demande.get('tool_name') or '',
               'extrait': extrait(demande.get('tool_name'), demande.get('tool_input')),
               'heure': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    connexions = []
    try:
        connexions = connecter(message)
        reponse = attendre(connexions, ident, time.monotonic() + attente,
                           lambda r: r.get('decision') in ('allow', 'deny'))
        return reponse['decision'] if reponse else None
    finally:
        for s in connexions:   # closing tells the other instances the request is over
            s.close()

def attendre(connexions, ident, fin, valide):
    """The first answer with this id that `valide` accepts, on any connection, or None once all are closed or the
    time is up. An unreadable, foreign or refused answer puts its instance out; the others may still answer."""
    recus = {s: b'' for s in connexions}
    while recus:
        reste = fin - time.monotonic()
        if reste <= 0:
            return None
        lisibles, _, _ = select.select(list(recus), [], [], min(reste, 60))
        for s in lisibles:
            try:
                bout = s.recv(4096)
            except OSError:
                bout = b''
            if not bout:
                del recus[s]   # this instance closed: restarted, or the request expired there
                continue
            recus[s] += bout
            if b'\n' not in recus[s]:
                if len(recus[s]) > 65536:
                    del recus[s]
                continue
            try:
                reponse = json.loads(recus[s].split(b'\n', 1)[0])
            except ValueError:
                reponse = None
            if isinstance(reponse, dict) and reponse.get('id') == ident and valide(reponse):
                return reponse
            del recus[s]   # unreadable or foreign: this instance is out, the others may still answer
    return None

TRACES = INTERNE / 'demandes-autorisation'


def tracer(demande):
    """The trace of a request (time and tool, nothing of what it would do): what the board needs to say « arrêtée sur
    une autorisation » rather than « travaille ». One file per session, replaced at each request."""
    sid = str(demande.get('session_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', sid):
        return
    TRACES.mkdir(parents=True, exist_ok=True)
    tmp = TRACES / f'.{sid}.tmp'
    tmp.write_text(json.dumps({'t': time.time(), 'outil': str(demande.get('tool_name') or '')}), encoding='utf-8')
    os.replace(tmp, TRACES / f'{sid}.json')


def main():
    try:
        demande = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return 0
    if not isinstance(demande, dict):
        return 0
    try:
        tracer(demande)
    except OSError:
        pass
    if os.name == 'nt' or not hasattr(socket, 'AF_UNIX'):
        return 0
    try:
        etat = json.loads(ETAT.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0
    if not isinstance(etat, dict) or etat.get('autorisations_tableau') is not True:
        return 0
    if not concerne(etat, demande):
        return 0
    try:
        decision = demander(demande)
    except (OSError, ValueError):
        return 0
    if decision:
        sys.stdout.write(json.dumps(sortie(decision), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:  # never in the way of the normal window
        sys.exit(0)
