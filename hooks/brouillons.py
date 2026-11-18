#!/usr/bin/env python3
"""Drafts a session left for the PM (Gmail, Slack), noted without an LLM in ~/Mon Studio/.parc/brouillons.json.

    python3 brouillons.py                     # PostToolUse hook: reads the hook's JSON on stdin
    python3 brouillons.py rattrapage [jours]  # catch-up: the drafts of the last 30 days of transcripts

Sessions write drafts the PM never sends, and nobody reminds him (two Gmail drafts of late October, Q39 of 2026-11-07).
This hook notes each draft a session creates or updates, and forgets the one it deletes; the morning task checks in
Gmail which are still drafts and the Today tab lists them, nowhere else.

The connectors' tool names carry an opaque prefix (`mcp__<uuid>__`): tools are recognised by their suffix.

- `__create_draft` / `__update_draft` (Gmail): input {to, cc, subject, body | htmlBody, replyToMessageId} or {draftId,
  …}; result {id, messageId, threadId, viewUrl}. `id` is the draft (stable across updates), `viewUrl` opens it.
- `__delete_draft` (Gmail): input {draftId}. The draft is forgotten.
- `__slack_send_message_draft` (Slack): input {channel_id, message, thread_ts}; result {draft_id, channel_link,
  channel_info {channel_id, name, is_dm}}. Slack keeps one draft per conversation: a new draft in the same channel
  (and thread) replaces the noted one.

The result comes as a JSON text, bare or in content blocks [{type: text, text}]. An error or a result without an id
notes nothing.

One entry per draft, keyed `gmail:<draft id>` or `slack:<channel>[:<thread>]`: {cle, outil, brouillon, message, fil,
destinataire, objet, canal, lien, session, session_locale, dossier, cree_le, maj_le}. Entries older than 30 days
(maj_le) leave the file. Written atomically under a lock (brouillons.json.lock); a lock not obtained within two seconds
and any error leave the file as it was: the hook never fails nor slows a session, and prints nothing.
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time

try:
    import fcntl
except ImportError:   # Windows: the atomic replace alone
    fcntl = None

GARDE_S = 30 * 86400
PLAFOND = 200
TEXTE_MAX = 160
LOCAL = re.compile(r'^local_[0-9a-f-]{36}$')
ID = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')
SUFFIXES = ('__create_draft', '__update_draft', '__delete_draft', '__slack_send_message_draft')


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def fichier():
    return mon_studio() / '.parc' / 'brouillons.json'


def transcripts():
    return pathlib.Path(os.environ.get('MON_STUDIO_TRANSCRIPTS') or (pathlib.Path.home() / '.claude' / 'projects'))


def maintenant_iso(t=None):
    return dt.datetime.fromtimestamp(time.time() if t is None else t).astimezone().isoformat(timespec='seconds')


def instant(v):
    try:
        d = dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return (d if d.tzinfo else d.astimezone()).timestamp()


def texte(v, n=TEXTE_MAX):
    if not isinstance(v, str):
        return ''
    s = ' '.join(v.split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def outil_de(nom):
    nom = str(nom or '')
    return next((s[2:] for s in SUFFIXES if nom.endswith(s)), '')


def resultat(reponse):
    """The JSON object the tool returned, from a bare text, content blocks, or an already parsed object."""
    if isinstance(reponse, dict):
        if 'content' in reponse and not any(k in reponse for k in ('id', 'draft_id')):
            return resultat(reponse['content'])
        return reponse
    if isinstance(reponse, list):
        for b in reponse:
            r = resultat(b.get('text') if isinstance(b, dict) and b.get('type') == 'text' else b)
            if r:
                return r
        return None
    if isinstance(reponse, str):
        try:
            o = json.loads(reponse)
        except ValueError:
            return None
        return o if isinstance(o, dict) else None
    return None


def destinataires(v):
    v = [v] if isinstance(v, str) else v
    if not isinstance(v, list):
        return ''
    noms = [str(x).strip() for x in v if isinstance(x, str) and x.strip()]
    if not noms:
        return ''
    return texte(noms[0] + (f' (+{len(noms) - 1})' if len(noms) > 1 else ''), 120)


def debut_slack(message):
    """The start of a Slack message, its mentions and links made readable."""
    s = re.sub(r'<@[A-Z0-9]+>', '@…', str(message or ''))
    s = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2', s)
    s = re.sub(r'<(https?://[^>]+)>', r'\1', s)
    return texte(s, 100)


def lien_https(v):
    return v if isinstance(v, str) and v.startswith('https://') and len(v) <= 1000 else ''


def evenement(nom, entree, reponse):
    """('noter', entry) or ('oublier', key) for one draft tool call, None when nothing is to be noted."""
    outil = outil_de(nom)
    entree = entree if isinstance(entree, dict) else {}
    if outil == 'delete_draft':
        d = entree.get('draftId')
        return ('oublier', f'gmail:{d}') if isinstance(d, str) and ID.match(d) else None
    r = resultat(reponse)
    if not r:
        return None
    if outil in ('create_draft', 'update_draft'):
        d = r.get('id') or entree.get('draftId')
        if not isinstance(d, str) or not ID.match(d):
            return None
        message = r.get('messageId') if isinstance(r.get('messageId'), str) else ''
        lien = lien_https(r.get('viewUrl'))
        if not lien and message and ID.match(message):
            lien = f'https://mail.google.com/mail/u/0/#drafts?compose={message}'
        e = {'cle': f'gmail:{d}', 'outil': 'gmail', 'brouillon': d, 'message': message,
             'fil': r.get('threadId') if isinstance(r.get('threadId'), str) else '', 'lien': lien}
        if 'to' in entree:
            e['destinataire'] = destinataires(entree.get('to'))
        if 'subject' in entree:
            e['objet'] = texte(entree.get('subject'))
        return ('noter', e)
    if outil == 'slack_send_message_draft':
        info = r.get('channel_info') if isinstance(r.get('channel_info'), dict) else {}
        canal = info.get('channel_id') or entree.get('channel_id')
        if not isinstance(canal, str) or not ID.match(canal):
            return None
        fil = entree.get('thread_ts') if isinstance(entree.get('thread_ts'), str) and ID.match(entree['thread_ts']) else ''
        lien = lien_https(r.get('channel_link'))
        if lien and fil:
            lien = f"{lien.rstrip('/')}/p{fil.replace('.', '')}?thread_ts={fil}&cid={canal}"
        nom_canal = info.get('name') if isinstance(info.get('name'), str) else ''
        dest = 'message direct' if info.get('is_dm') else (f'#{nom_canal}' if nom_canal else '')
        d = r.get('draft_id') if isinstance(r.get('draft_id'), str) else ''
        return ('noter', {'cle': f'slack:{canal}' + (f':{fil}' if fil else ''), 'outil': 'slack', 'brouillon': d,
                          'canal': canal, 'fil': fil, 'lien': lien, 'destinataire': texte(dest, 120),
                          'objet': debut_slack(entree.get('message'))})
    return None


def appliquer(brouillons, ev, session='', session_locale='', dossier='', quand=None):
    """Applies one event to {cle: entry}. A new draft keeps its first session and date; an update refreshes its link."""
    if not ev:
        return
    action, x = ev
    if action == 'oublier':
        brouillons.pop(x, None)
        return
    q = maintenant_iso(quand)
    avant = brouillons.get(x['cle'])
    if avant and x['outil'] == 'slack' and avant.get('brouillon') and x.get('brouillon') != avant.get('brouillon'):
        avant = None   # a new Slack draft in the same conversation replaces the old one
    e = dict(avant or {'cle': x['cle'], 'outil': x['outil'], 'destinataire': '', 'objet': '', 'session': session,
                       'session_locale': session_locale, 'dossier': dossier, 'cree_le': q})
    for k, v in x.items():
        if v or k not in e:
            e[k] = v
    if not e.get('session_locale') and session_locale and e.get('session') == session:
        e['session_locale'] = session_locale
    e['maj_le'] = q
    brouillons[x['cle']] = e


def elaguer(brouillons, maintenant=None):
    maintenant = time.time() if maintenant is None else maintenant
    garde = {k: e for k, e in brouillons.items() if (instant(e.get('maj_le')) or 0) >= maintenant - GARDE_S}
    plus_recents = sorted(garde.values(), key=lambda e: instant(e.get('maj_le')) or 0, reverse=True)[:PLAFOND]
    return {e['cle']: e for e in plus_recents}


def lire():
    try:
        o = json.loads(fichier().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    lst = o.get('brouillons') if isinstance(o, dict) else None
    return {e['cle']: e for e in lst or [] if isinstance(e, dict) and isinstance(e.get('cle'), str)}


class Verrou:
    """Exclusive lock on brouillons.json.lock, tried for two seconds at most; `pris` says whether it was obtained."""

    def __enter__(self):
        self.fd, self.pris = None, fcntl is None
        if fcntl is None:
            return self
        chemin = fichier().with_name('brouillons.json.lock')
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o644)
        fin = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.pris = True
                return self
            except OSError:
                if time.monotonic() > fin:
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            if self.pris:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)


def ecrire(brouillons):
    f = fichier()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + '.tmp')
    lst = sorted(brouillons.values(), key=lambda e: e.get('cree_le') or '')
    tmp.write_text(json.dumps({'version': 1, 'brouillons': lst}, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, f)


def mettre_a_jour(changer):
    """Reads, changes, prunes and writes the file under the lock. False when the lock was not obtained."""
    with Verrou() as v:
        if not v.pris:
            return False
        b = lire()
        changer(b)
        ecrire(elaguer(b))
        return True


def hook(donnees):
    ev = evenement(donnees.get('tool_name'), donnees.get('tool_input'), donnees.get('tool_response'))
    if not ev:
        return
    local = os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or ''
    session = donnees.get('session_id') if isinstance(donnees.get('session_id'), str) else ''
    dossier = donnees.get('cwd') if isinstance(donnees.get('cwd'), str) else ''
    mettre_a_jour(lambda b: appliquer(b, ev, session, local if LOCAL.match(local) else '', dossier))


# --- Catch-up: the transcripts of the last days ---------------------------------------------------------------

def _ids_locaux():
    """{cli session id: local_… id} from the app's session cards."""
    base = os.environ.get('MON_STUDIO_APP_SESSIONS')
    if base:
        base = pathlib.Path(base)
    else:
        racine = pathlib.Path.home() / ('Library/Application Support' if sys.platform == 'darwin' else '.config')
        base = racine / 'Claude' / 'claude-code-sessions'
    sortie = {}
    for chemin in base.glob('*/*/local_*.json'):
        try:
            c = json.loads(chemin.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(c, dict) and isinstance(c.get('cliSessionId'), str) and LOCAL.match(str(c.get('sessionId') or '')):
            sortie[c['cliSessionId']] = c['sessionId']
    return sortie


def evenements_des_transcripts(jours=30, maintenant=None):
    """[(time, event, cli session, cwd)] of every draft call of the last `jours` days, each tool call once (a forked
    session copies its parent's lines), in time order."""
    maintenant = time.time() if maintenant is None else maintenant
    debut = maintenant - jours * 86400
    appels, sortie, vus = {}, [], set()
    for f in transcripts().rglob('*.jsonl'):
        try:
            if f.stat().st_mtime < debut:
                continue
            donnees = f.read_bytes()
        except OSError:
            continue
        if b'_draft' not in donnees:
            continue
        for ligne in donnees.split(b'\n'):
            if b'_draft' not in ligne and b'tool_result' not in ligne:
                continue
            try:
                o = json.loads(ligne)
            except ValueError:
                continue
            contenu = (o.get('message') or {}).get('content') if isinstance(o, dict) else None
            if not isinstance(contenu, list) or not o.get('timestamp'):
                continue
            for b in contenu:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'tool_use' and outil_de(b.get('name')):
                    appels[b.get('id')] = (b.get('name'), b.get('input'), o.get('sessionId') or '', o.get('cwd') or '')
                elif b.get('type') == 'tool_result' and b.get('tool_use_id') in appels and b['tool_use_id'] not in vus:
                    t = instant(o.get('timestamp'))
                    if t is None or t < debut or b.get('is_error'):
                        continue
                    nom, entree, session, cwd = appels[b['tool_use_id']]
                    ev = evenement(nom, entree, b.get('content'))
                    if ev:
                        vus.add(b['tool_use_id'])
                        sortie.append((t, ev, session, cwd))
    return sorted(sortie, key=lambda x: x[0])


def rattrapage(jours=30, maintenant=None):
    """Fills brouillons.json with the drafts of the transcripts: those already noted keep what the hook wrote, a draft
    deleted since is forgotten. Returns the drafts found, as the file now holds them."""
    trouves, oublies = {}, set()
    locaux = _ids_locaux()
    for t, ev, session, cwd in evenements_des_transcripts(jours, maintenant):
        appliquer(trouves, ev, session, locaux.get(session, ''), cwd, quand=t)
        if ev[0] == 'oublier':
            oublies.add(ev[1])
        else:
            oublies.discard(ev[1]['cle'])

    def fusion(b):
        for cle, e in trouves.items():
            b.setdefault(cle, e)
        for cle in oublies:
            b.pop(cle, None)
    if not mettre_a_jour(fusion):
        raise RuntimeError('brouillons.json est verrouillé, réessaie dans un instant')
    return [e for e in lire().values() if e['cle'] in trouves]


def main(args):
    if args[:1] == ['rattrapage']:
        jours = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
        trouves = rattrapage(jours)
        par_outil = {}
        for e in trouves:
            par_outil[e['outil']] = par_outil.get(e['outil'], 0) + 1
        detail = ', '.join(f'{n} {o}' for o, n in sorted(par_outil.items())) or 'aucun'
        print(f'Brouillons des {jours} derniers jours notés : {len(trouves)} ({detail}).')
        return 0
    try:
        hook(json.loads(sys.stdin.read() or '{}'))
    except Exception:
        pass   # never a visible error in a session
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
