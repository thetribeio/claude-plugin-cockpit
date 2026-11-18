"""Stop hook: a session that just asked the PM a numbered question waits a few minutes for his click on the pinned
page « Mon Studio », instead of going to sleep.

Off by default. It does nothing, prints nothing and exits at once unless ~/Mon Studio/.parc/cockpit.json holds
`"reponses_directes": true`; with `"reponses_directes_sessions": [ids]`, only those sessions (CLI session id, or the
app's local_… id) are concerned, for a trial. It also stays silent when the stop already follows a stop hook
(`stop_hook_active`), on Windows, and when this session did not ask, during this turn, a question still open on its
chantier's mirror (~/Mon Studio/chantiers/<chantier>.json) of kind `go`, `clic`, or `decision` with numbered options. « During
this turn » means since the PM's last message in the transcript: the mirror line's `depuis` is not older.

Otherwise it sends one message to every live connector socket (~/Mon Studio/.parc/autorisations-<pid>.sock, the same
sockets as the authorization hook, autorisation.py): `{type: "attente", id, session_id, sessionId, numero, titre,
kind, choix, limite}`. `choix` is the closed list of accepted answers: `["go", "pas encore"]` for a go, `["ok"]` for a
clic, `["1", "2", …, "pas encore"]` for a decision. It waits for the first answer with the same id, at most `reponses_directes_minutes`
minutes (10 by default, 30 at most). The answer must be exactly one of `choix`: no free text ever reaches the session.
It then prints `{"decision": "block", "reason": "Réponse du PM depuis Mon Studio, mot pour mot : « Q11 go ». …"}` and
the session carries on with that answer. Time up, or every connection closed: it exits without output and the session
stops as usual. Nothing is written to disk.

Numbered questions of the session's own message (Q40, 2026-11-09): when no mirror line was asked this turn, every
« Qn · … » under « À trancher » of the last message that has closed answers (parc.questions_numerotees, the board's
rule) gets its own wait, `numero: "Qn"`; the first answer wins and reaches the session as « Qn go ».

A question without a number: when no mirror line and no numbered question was asked this turn, the session's last message
is read with the plugin's own parc.py (question_seule): exactly one question under « À trancher », a go (« go », « pas
encore »), a clic (« ok ») or a decision with numbered options (their labels, and « pas encore »). The message then has
`numero: ""`, and the answer reaches the session as the text alone (« go », the option's label), never free text.
"""
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import select
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autorisation  # noqa: E402  same sockets, same way to reach them

PARC = pathlib.Path(__file__).resolve().parent.parent / 'skills' / 'mon-studio' / 'scripts' / 'parc.py'

MON_STUDIO = autorisation.MON_STUDIO
ETAT = autorisation.ETAT
CHANTIERS = MON_STUDIO / 'chantiers'
MINUTES_DEFAUT, MINUTES_MAX = 10, 30
GENRES = ('go', 'decision', 'clic')
PAS_ENCORE = 'pas encore'
NUMERO = re.compile(r'^\s*Q(\d{1,4})\b')
OPTION_DETAIL = re.compile(r'(?:^|\s)([1-9])\s*[.)]\s+\S')
LOCAL = re.compile(r'^local_[0-9a-f-]{36}$')
# Text the app puts in a « user » message that the PM did not type (as parc.py's SYSTEME).
SYSTEME = ('<task-notification>', '<local-command', '<command-', 'This session is being continued', 'The app was quit',
           'Another Claude session sent', 'Continue from where you left off', '<system-reminder>', '<scheduled-task',
           'Caveat: The messages below', 'Stop hook feedback', '[Request interrupted')


def lire_json(chemin, defaut=None):
    try:
        return json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaut


def concerne(etat, entree, local):
    """True when the switch is on and this session is in the trial list, if there is one."""
    if not isinstance(etat, dict) or etat.get('reponses_directes') is not True:
        return False
    liste = etat.get('reponses_directes_sessions')
    if liste is None:
        return True
    ids = {entree.get('session_id'), local} - {None, ''}
    return isinstance(liste, list) and bool(ids & set(liste))


def attente_max(etat):
    """Seconds: MON_STUDIO_REPONSE_ATTENTE (tests), else reponses_directes_minutes, 10 by default, 30 at most."""
    if os.environ.get('MON_STUDIO_REPONSE_ATTENTE'):
        try:
            return max(0.0, float(os.environ['MON_STUDIO_REPONSE_ATTENTE']))
        except ValueError:
            pass
    m = etat.get('reponses_directes_minutes', MINUTES_DEFAUT)
    if isinstance(m, bool) or not isinstance(m, (int, float)) or m <= 0:
        m = MINUTES_DEFAUT
    return min(float(m), MINUTES_MAX) * 60


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


def heure(v):
    try:
        t = dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.astimezone()


def texte_de(contenu):
    """The typed text of a user message, or None when it carries a tool result (not the PM)."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in contenu):
            return None
        return '\n'.join(b.get('text', '') for b in contenu if isinstance(b, dict) and b.get('type') == 'text')
    return None


def debut_du_tour(transcript):
    """When the PM's last message was written in the transcript (JSON lines), or None."""
    try:
        with open(transcript, 'rb') as f:
            f.seek(0, os.SEEK_END)
            taille = f.tell()
            f.seek(max(0, taille - 4_000_000))
            lignes = f.read().decode('utf-8', errors='replace').splitlines()
    except (OSError, TypeError):
        return None
    for brut in reversed(lignes):
        try:
            o = json.loads(brut)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get('type') != 'user' or o.get('isMeta') or o.get('isSidechain') \
                or o.get('isCompactSummary'):
            continue
        msg = o.get('message') or {}
        texte = texte_de(msg.get('content') if isinstance(msg, dict) else None)
        if texte is None or not texte.strip() or texte.lstrip().startswith(SYSTEME):
            continue
        return heure(o.get('timestamp'))
    return None


def options_de(a):
    """['1', '2', …] for a decision: the numbered options of its detail (« 1. … 2. … », « 1) … »), only when they run
    1, 2, … with at least two. The mirror has no other field for options (question.py new --detail)."""
    vus = []
    for n in OPTION_DETAIL.findall(str(a.get('detail') or '')):
        if n not in vus:
            vus.append(n)
    vus = sorted(vus, key=int)
    if len(vus) >= 2 and vus == [str(i) for i in range(1, len(vus) + 1)]:
        return vus
    return []


def choix_de(a):
    if a.get('type') == 'go':
        return ['go', PAS_ENCORE]
    if a.get('type') == 'clic':
        return ['ok']   # the substance is decided: one click
    if demande_un_oui(a):
        return ['oui', PAS_ENCORE]   # a list of points to approve, not options (same rule as parc.demande_un_oui)
    opts = options_de(a)
    return opts + [PAS_ENCORE] if opts else []


def demande_un_oui(a):
    """True when the question's own words, before its first numbered point, ask for « oui »."""
    tete = str(a.get('detail') or '')
    m = OPTION_DETAIL.search(tete)
    tete = tete[:m.start()] if m else tete
    return bool(re.search(r'\boui\b', str(a.get('titre') or '') + ' ' + tete, re.I))


def question_du_tour(local, debut):
    """The latest open line of a mirror that this session asked since `debut`, of kind go or decision, with its
    closed list of answers: (line, numero, choix) or None."""
    if not local or debut is None or not CHANTIERS.is_dir():
        return None
    debut = debut.replace(microsecond=0)   # question.py writes its times to the second
    trouvees = []
    for chemin in sorted(CHANTIERS.glob('*.json')):
        m = lire_json(chemin)
        if not isinstance(m, dict):
            continue
        for a in m.get('attentes') or []:
            if not isinstance(a, dict) or a.get('sessionId') != local or a.get('type') not in GENRES or a.get('arret'):
                continue
            n, quand = NUMERO.match(str(a.get('titre') or '')), heure(a.get('depuis'))
            if not n or quand is None or quand < debut:
                continue
            choix = choix_de(a)
            if choix:
                trouvees.append((quand, a, f'Q{int(n.group(1))}', choix))
    if not trouvees:
        return None
    _, a, numero, choix = max(trouvees, key=lambda t: t[0])
    return a, numero, choix


def charger_parc():
    """The plugin's own parc.py (same version as this hook), loaded under its own name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('parc_reponse_directe', PARC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def dernier_message(parc, transcript, debut):
    """The text of Claude's final message of this turn (end_turn, written after the PM's last message), or ''."""
    entrees, _ = parc.entrees_fin(transcript, parc.FIN_INITIALE)
    for j in range(len(entrees) - 1, -1, -1):
        m = entrees[j].get('message') or {}
        if entrees[j]['type'] != 'assistant':
            if entrees[j].get('isMeta'):
                continue
            return ''   # the PM (or a tool result) spoke after Claude's last words
        if m.get('stop_reason') != 'end_turn':
            continue
        quand = heure(entrees[j].get('timestamp'))
        if debut is None or quand is None or quand < debut:
            return ''
        mid, morceaux = m.get('id'), []
        while j >= 0 and entrees[j]['type'] == 'assistant' and (entrees[j].get('message') or {}).get('id') == mid:
            morceaux.append(parc.texte_de((entrees[j].get('message') or {}).get('content')))
            j -= 1
        return '\n\n'.join(x for x in reversed(morceaux) if x and x.strip())
    return ''

def questions_du_message(transcript, debut):
    """[(line, 'Qn', choix)] for each numbered question of the session's last message that has closed answers (Q40,
    2026-11-09: every numbered question gets its buttons, chantier or not); [] otherwise."""
    if not transcript or not PARC.exists():
        return []
    parc = charger_parc()
    return [({'titre': q['titre'], 'type': q['type']}, q['numero'], q['choix'])
            for q in parc.questions_numerotees(dernier_message(parc, transcript, debut))]


def question_sans_numero(transcript, debut):
    """(line, '', choix) for the only question of the session's last message, without a mirror number; or None."""
    if not transcript or not PARC.exists():
        return None
    parc = charger_parc()
    q = parc.question_seule(dernier_message(parc, transcript, debut))
    if not q:
        return None
    return {'titre': q['titre'], 'type': q['type']}, '', q['choix']

def raison(numero, choix, miroir=True):
    if numero and not miroir:
        dit = f'Réponse du PM depuis Mon Studio, mot pour mot : « {numero} {choix} ».'
        if choix == PAS_ENCORE:
            return dit + ' La question reste ouverte : arrête-toi là.'
        return dit + ' Poursuis.'
    if not numero:
        dit = f'Réponse du PM depuis Mon Studio, mot pour mot : « {choix} ».'
        if choix == PAS_ENCORE:
            return dit + ' La question reste ouverte : arrête-toi là.'
        return dit + ' Poursuis.'
    dit = f'Réponse du PM depuis Mon Studio, mot pour mot : « {numero} {choix} ».'
    if choix == PAS_ENCORE:
        return dit + ' La question reste ouverte au tableau : ne la solde pas, arrête-toi là.'
    return dit + ' Solde la ligne (question.py settle) et poursuis.'


def attendre_reponses(entree, local, questions, attente):
    """Several questions of one message: one wait per question, each on its own connections, so each line of the page
    answers its own. The first valid answer wins: (numero, choix), or None. Closing every connection ends them all."""
    fin = time.monotonic() + attente
    par_connexion, toutes = {}, []
    try:
        for a, numero, choix in questions:
            ident = secrets.token_hex(16)
            titre = ' '.join(str(a.get('titre') or '').split())
            message = {'v': 1, 'type': 'attente', 'id': ident, 'session_id': entree.get('session_id') or '',
                       'sessionId': local, 'numero': numero, 'titre': titre[:300], 'kind': a.get('type'), 'choix': choix,
                       'limite': int(attente) + 5, 'heure': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
            for s in autorisation.connecter(message):
                par_connexion[s] = (ident, numero, choix)
                toutes.append(s)
        recus = {s: b'' for s in toutes}
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
                    del recus[s]
                    continue
                recus[s] += bout
                if b'\n' not in recus[s]:
                    if len(recus[s]) > 65536:
                        del recus[s]
                    continue
                ident, numero, choix = par_connexion[s]
                try:
                    r = json.loads(recus[s].split(b'\n', 1)[0])
                except ValueError:
                    r = None
                if isinstance(r, dict) and r.get('id') == ident and isinstance(r.get('choix'), str) and r['choix'] in choix:
                    return numero, r['choix']
                del recus[s]   # unreadable, foreign or outside the list: this connection is out
        return None
    finally:
        for s in toutes:
            s.close()


def attendre_reponse(entree, local, a, numero, choix, attente):
    """The PM's answer, exactly one of `choix`, or None."""
    ident = secrets.token_hex(16)
    titre = ' '.join(str(a.get('titre') or '').split())
    message = {'v': 1, 'type': 'attente', 'id': ident, 'session_id': entree.get('session_id') or '',
               'sessionId': local, 'numero': numero, 'titre': titre[:300], 'kind': a.get('type'), 'choix': choix,
               'limite': int(attente) + 5, 'heure': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    connexions = []
    try:
        connexions = autorisation.connecter(message)
        reponse = autorisation.attendre(connexions, ident, time.monotonic() + attente,
                                        lambda r: isinstance(r.get('choix'), str) and r['choix'] in choix)
        return reponse['choix'] if reponse else None
    finally:
        for s in connexions:   # closing tells every instance the wait is over
            s.close()


def main():
    if os.name == 'nt' or not hasattr(socket, 'AF_UNIX'):
        return 0
    etat = lire_json(ETAT)
    if not isinstance(etat, dict) or etat.get('reponses_directes') is not True:
        return 0
    try:
        entree = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return 0
    if not isinstance(entree, dict) or entree.get('stop_hook_active'):
        return 0
    local = id_local(entree.get('session_id'))
    if not concerne(etat, entree, local):
        return 0
    debut = debut_du_tour(entree.get('transcript_path'))
    trouvee = question_du_tour(local, debut)
    if not trouvee:
        try:
            questions = questions_du_message(entree.get('transcript_path'), debut)
        except Exception:   # an unreadable transcript or parc.py: the session stops as usual
            questions = []
        if questions:
            try:
                fait = attendre_reponses(entree, local, questions, attente_max(etat))
            except (OSError, ValueError):
                return 0
            if fait:
                sys.stdout.write(json.dumps({'decision': 'block', 'reason': raison(fait[0], fait[1], miroir=False)},
                                            ensure_ascii=False))
            return 0
        try:
            trouvee = question_sans_numero(entree.get('transcript_path'), debut)
        except Exception:   # an unreadable transcript or parc.py: the session stops as usual
            trouvee = None
    if not trouvee:
        return 0
    a, numero, choix = trouvee
    try:
        reponse = attendre_reponse(entree, local, a, numero, choix, attente_max(etat))
    except (OSError, ValueError):
        return 0
    if reponse:
        sys.stdout.write(json.dumps({'decision': 'block', 'reason': raison(numero, reponse)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:  # never in the way of a normal stop
        sys.exit(0)
