#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ticket corrections of a settled conflict (/cockpit:conflits), without LLM nor dependency.

    tickets.py heure                                                   business hours now? (read with `date`, Paris)
    tickets.py recherche <studio> [--cas Cn]...                        what to search in the tool, capped, and its cost
    tickets.py dossier                                                 a new working folder, outside the Studio
    tickets.py lot       <studio> <dossier> <k> --sortie F             the tickets read, batch k, for one sub-agent
    tickets.py preparer  <studio> <dossier>                            drafts from the tickets read and the judgments
    tickets.py brouillons <studio>                                     every draft, grouped, and the one form
    tickets.py valider   <studio> --pm NOM [--ecarter JSON] [--changer JSON] [--tout-ecarter]
                                                                       the PM's one go (free text: set aside, change)
    tickets.py pousser   <studio>                                      what may be pushed now (nothing out of hours)
    tickets.py verifier  <studio> <Tn> --actuel F --sortie F           re-read just before the push: unchanged ->
                                                                       the description to push is written to F
    tickets.py pousse    <studio> <Tn> [--relu F] [--echec MESSAGE]    the push is done (checked on a re-read), or failed
    tickets.py etat      <studio>                                      one line: what waits

Nothing here talks to Jira or Linear, and nothing depends on another plugin: the session reads and pushes with acli
or the project's connector, this script says what to search, keeps the drafts and says what may go. A draft only
touches the description, never a comment. By default a ticket gets a dated addition at the top and its text is kept
byte for byte (ADF: one paragraph before the existing nodes; Markdown: one quoted line before the existing text). Only
a ticket in a status the project sheet lists as internal (« Statuts internes ») may be rewritten (PM, Q16, 2026-11-12).
A finished ticket is never corrected: it is only named in the recap (Q18).

Nothing is pushed without the PM's explicit go (`valider`), nor out of business hours (Monday to Friday, 8:00 to
20:00, Paris time, French public holidays excluded): out of hours the go is a preparation and the push is offered at
the next pass. Just before each push the ticket is read again: if its description changed since the draft, nothing is
pushed and the PM is told.

State: `<studio>/projet/.conflits/tickets.json` (next to the register's machine state). Nothing else in the Studio;
the tickets read go to a working folder outside it.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('registre_tickets', HERE / 'registre.py')
registre = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registre)

STATE = pathlib.Path('projet') / '.conflits' / 'tickets.json'
TOOLS = {'jira': 'Jira', 'linear': 'Linear'}
OPEN_FROM, OPEN_UNTIL = 8, 20          # PM rule « Heures de publication »: 8:00 to 20:00, Paris time
DAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')

# The search (PM, Q17, 2026-11-12: « si ça n'ajoute pas trop de conso tokens »): the words of the old value, open
# tickets only, a few per conflict, short descriptions, one Sonnet sub-agent per batch.
OPEN_PER_CASE = 8                      # open tickets read (with their description) per settled conflict
DONE_PER_CASE = 5                      # finished tickets listed (title only, never read nor judged)
DESCRIPTION_CHARS = 1000               # what the sub-agent reads of a description
BATCH_CHARS = 45000                    # one batch, read in one go
SESSION_CONTEXT = 60000                # the conflicts session when it searches (Opus, cache read per call)
SESSION_CALLS_PER_CASE = 3             # two searches and one script call
OUTPUT_PER_TICKET = 150

# What the PM reads (one place each).
LABEL_GO = 'Valider et pousser'
LABEL_ALL_ASIDE = 'Tout écarter'
LABEL_DISCUSS = "Discuter d'abord"
RECOMMENDED = ' (Recommandé)'
ADDITION = 'Mise à jour du {date} : {nouvelle} remplace {ancienne}.'
DONE_STATES = {'done', 'termine', 'terminee', 'closed', 'ferme', 'fermee', 'resolu', 'resolue', 'resolved', 'livre',
               'canceled', 'cancelled', 'annule', 'annulee', 'completed', 'duplicate'}


def _conflits():
    spec = importlib.util.spec_from_file_location('conflits_tickets', HERE / 'conflits.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- time

def easter(year):
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def holidays(year):
    """French public holidays (metropolitan France)."""
    e = easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    return {dt.date(year, m, d) for m, d in fixed} | {e + dt.timedelta(days=1), e + dt.timedelta(days=39),
                                                      e + dt.timedelta(days=50)}


def now_paris():
    """Paris time, read with `date` (never estimated)."""
    env = dict(os.environ, TZ='Europe/Paris')
    out = subprocess.run(['date', '+%Y-%m-%d %H:%M'], capture_output=True, text=True, env=env, check=True).stdout
    return dt.datetime.strptime(out.strip(), '%Y-%m-%d %H:%M')


def is_working_day(day):
    return day.weekday() < 5 and day not in holidays(day.year)


def business_hours(now=None):
    """{'ouvre': bool, 'maintenant': 'mercredi 11/11 à 23 h 25', 'prochain': 'jeudi 12/11 à 8 h' | None}."""
    now = now or now_paris()
    open_now = is_working_day(now.date()) and OPEN_FROM <= now.hour < OPEN_UNTIL
    nxt = now.date() if (is_working_day(now.date()) and now.hour < OPEN_FROM) else now.date() + dt.timedelta(days=1)
    while not is_working_day(nxt):
        nxt += dt.timedelta(days=1)
    return {'ouvre': open_now, 'maintenant': f"{DAYS[now.weekday()]} {now.strftime('%d/%m')} à {now.hour} h {now.minute:02d}",
            'prochain': None if open_now else f"{DAYS[nxt.weekday()]} {nxt.strftime('%d/%m')} à {OPEN_FROM} h"}


def out_of_hours_line(h):
    return (f"Hors des heures ouvrées ({h['maintenant']}) : rien ne part. Ton go vaut préparation ; "
            f"je te propose le push au prochain passage, à partir de {h['prochain']}.")


# ---------- descriptions (Markdown text for Linear, ADF document for Jira)

def canonical(description):
    """A description as the tools may return it, made comparable: an ADF document given as a JSON string is decoded;
    ADF node ids (`attrs.localId`), which differ between a search and a view, are dropped, and empty `attrs` too."""
    if isinstance(description, str) and description.lstrip().startswith('{'):
        try:
            decoded = json.loads(description)
        except ValueError:
            decoded = None
        if isinstance(decoded, dict) and decoded.get('type') == 'doc':
            description = decoded

    def clean(n):
        if isinstance(n, list):
            return [clean(x) for x in n]
        if not isinstance(n, dict):
            return n
        out = {}
        for k, v in n.items():
            if k == 'attrs' and isinstance(v, dict):
                v = {a: b for a, b in v.items() if a != 'localId'}
                if not v:
                    continue
            out[k] = clean(v)
        return out
    return clean(description) if isinstance(description, dict) else description


def fingerprint(description):
    """Same description, same fingerprint: ADF canonical JSON, text with normalized line ends and no trailing space."""
    description = canonical(description)
    if isinstance(description, dict):
        raw = json.dumps(description, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    else:
        raw = '\n'.join(l.rstrip() for l in str(description or '').replace('\r\n', '\n').split('\n')).strip()
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def text_fingerprint(description):
    return hashlib.sha256(plain(canonical(description)).encode('utf-8')).hexdigest()


def plain(description, limit=None):
    """What a reader sees of a description: its text, on one line."""
    if isinstance(description, dict):
        parts = []

        def walk(n):
            if isinstance(n, dict):
                if n.get('type') == 'text':
                    parts.append(n.get('text', ''))
                for c in n.get('content') or []:
                    walk(c)
                if n.get('type') in ('paragraph', 'heading', 'listItem'):
                    parts.append(' ')
        walk(description)
        text = ''.join(parts)
    else:
        text = re.sub(r'[*_`>#]+', '', str(description or ''))
    text = ' '.join(text.split())
    if limit and len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    return text


def _inline(text):
    """Markdown **bold** -> ADF text nodes."""
    nodes = []
    for i, part in enumerate(re.split(r'\*\*(.+?)\*\*', text)):
        if part:
            nodes.append({'type': 'text', 'text': part, **({'marks': [{'type': 'strong'}]} if i % 2 else {})})
    return nodes or [{'type': 'text', 'text': ' '}]


def md_to_adf(markdown):
    """Simple Markdown (headings, bullet and numbered lists, paragraphs, bold) -> ADF document. Enough for a rewritten
    description; the dated addition never needs it."""
    content, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            content.append({'type': kind, 'content': [{'type': 'listItem', 'content': [
                {'type': 'paragraph', 'content': _inline(t)}]} for t in items]})
        items, kind = [], None

    para = []

    def flush_para():
        nonlocal para
        if para:
            content.append({'type': 'paragraph', 'content': _inline(' '.join(para))})
            para = []

    for line in str(markdown or '').replace('\r\n', '\n').split('\n'):
        s = line.strip()
        m_head = re.match(r'^(#{1,6})\s+(.+)$', s)
        m_bullet = re.match(r'^[-*+]\s+(.+)$', s)
        m_num = re.match(r'^\d+[.)]\s+(.+)$', s)
        if not s:
            flush_para(); flush()
        elif m_head:
            flush_para(); flush()
            content.append({'type': 'heading', 'attrs': {'level': len(m_head.group(1))}, 'content': _inline(m_head.group(2))})
        elif m_bullet or m_num:
            flush_para()
            want = 'bulletList' if m_bullet else 'orderedList'
            if kind and kind != want:
                flush()
            kind = want
            items.append((m_bullet or m_num).group(1))
        else:
            flush()
            para.append(s)
    flush_para(); flush()
    return {'type': 'doc', 'version': 1, 'content': content}


SIMPLE_NODES = {'doc', 'paragraph', 'heading', 'bulletList', 'orderedList', 'listItem', 'text', 'hardBreak', 'rule'}
SIMPLE_MARKS = {'strong', 'em'}


def is_simple(description):
    """A description a Markdown rewrite can carry without loss: no table, image, link, panel, code, mention, or (in
    Markdown) no link, image, table nor code. Otherwise the ticket gets the dated addition."""
    if description is None or description == '':
        return True
    if isinstance(description, dict):
        stack = [description]
        while stack:
            n = stack.pop()
            if not isinstance(n, dict):
                continue
            if n.get('type') not in SIMPLE_NODES:
                return False
            if any(isinstance(m, dict) and m.get('type') not in SIMPLE_MARKS for m in n.get('marks') or []):
                return False
            stack.extend(n.get('content') or [])
        return True
    return not re.search(r'\]\(|!\[|^\s*\|.*\|\s*$|```|<[a-z]', str(description), re.M)


def adf_paragraph(text):
    head, _, rest = text.partition(' : ')
    content = [{'type': 'text', 'text': head + (' :' if rest else ''), 'marks': [{'type': 'strong'}]}]
    if rest:
        content.append({'type': 'text', 'text': ' ' + rest})
    return {'type': 'paragraph', 'content': content}


def with_addition(description, addition, tool):
    """The description with the dated addition at the top, the original kept as it is."""
    if tool == 'jira':
        doc = description if isinstance(description, dict) and description.get('type') == 'doc' else \
            {'type': 'doc', 'version': 1, 'content': []}
        new = json.loads(json.dumps(doc))
        new['content'] = [adf_paragraph(addition)] + list(doc.get('content') or [])
        return new
    head, _, rest = addition.partition(' : ')
    line = f"> **{head} :** {rest}" if rest else f"> **{addition}**"
    original = str(description or '')
    return line + ('\n\n' + original if original.strip() else '\n')


def starts_with(description, addition):
    """The addition is already at the top."""
    return plain(description).startswith(plain(addition))


ADDED = re.compile(r'^Mise à jour du \d{2}/\d{2}/\d{4} :')


def already_added(description, case):
    """A dated addition for this conflict is already at the top, whatever its date (a re-run, another day, never
    adds a second one)."""
    text = plain(description)
    head = text[:300 + len(case['nouvelle']['texte'])]
    return bool(ADDED.match(text)) and plain(case['nouvelle']['texte']) in head


# ---------- what the tool returns (acli JSON, the Atlassian or Linear connector), normalized

def _issues(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ('issues', 'nodes', 'items', 'results', 'workItems', 'data'):
            if isinstance(raw.get(k), list):
                return raw[k]
            if isinstance(raw.get(k), dict):
                return _issues(raw[k])
        return [raw]
    return []


def normalize(issue):
    """One ticket as the tool gives it -> {'cle', 'titre', 'statut', 'termine', 'description'}."""
    f = issue.get('fields') if isinstance(issue.get('fields'), dict) else issue
    status = f.get('status') if 'status' in f else f.get('state')
    name, done = '', False
    if isinstance(status, dict):
        name = status.get('name') or ''
        cat = status.get('statusCategory') or {}
        done = (isinstance(cat, dict) and cat.get('key') == 'done') or norm(status.get('type')) in ('completed', 'canceled')
    elif isinstance(status, str):
        name = status
    if not done:
        done = norm(f.get('statusType') or f.get('stateType')) in ('completed', 'canceled') or \
            re.sub(r'[^a-z]', '', norm(name)) in DONE_STATES
    return {'cle': issue.get('key') or issue.get('identifier') or issue.get('id') or '',
            'titre': ' '.join(str(f.get('summary') or f.get('title') or '').split()),
            'statut': name, 'termine': bool(done), 'description': canonical(f.get('description')),
            'lu': 'description' in f}


def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


# ---------- state

def state_path(studio):
    return pathlib.Path(studio) / STATE


def load(studio):
    data = read_json(state_path(studio)) or {}
    data.setdefault('brouillons', [])
    data.setdefault('cherches', {})
    return data


def save(studio, data):
    p = state_path(studio)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.tickets-', suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def next_id(data):
    return 'T' + str(1 + max([int(d['id'][1:]) for d in data['brouillons']] or [0]))


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '').lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def words(s):
    return {w for w in re.findall(r'[a-z0-9]+', norm(s)) if len(w) >= 3}


# ---------- the project sheet

def _sheet(studio):
    try:
        return (pathlib.Path(studio) / 'projet' / 'fiche-projet.md').read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''


def _field(text, name):
    """A field of the sheet, written « - **Nom** : valeur », « Nom : valeur » or as a table row « | **Nom** | valeur |
    utilisé par | » (the first cell after the name only)."""
    m = re.search(r'(?im)^\W*' + name + r'(?:\*\*)?\s*([:|])[ \t]*(.*)$', text)
    if not m:
        return ''
    value = m.group(2).split('|')[0] if m.group(1) == '|' else m.group(2)
    return value.strip()


BLANK = ('non utilis', 'n/a', 'a completer', 'a configurer', 'a renseigner', 'linear ou jira', 'jira ou linear')


def empty(value):
    """A sheet field left blank or still a template: « _N/A_ », « — (non utilisé) », « _À compléter_ », « `linear` ou
    `jira` — détermine… »."""
    n = re.sub(r'[`*_]', '', norm(value))
    return not n.strip(' -—–().') or n.strip(' -—–().') == 'aucun' or any(k in n for k in BLANK)


def project_ref(studio):
    """{'outil': 'jira'|'linear'|None, 'projet': key or team or None} from the project sheet: « Outil ticketing »
    first, else a filled « Jira » or « Linear » field."""
    text = _sheet(studio)
    tool = None
    declared = _field(text, r'outil ticketing')
    if not empty(declared):
        n = norm(declared)
        if ('jira' in n) != ('linear' in n):
            tool = 'jira' if 'jira' in n else 'linear'
    jira = _field(text, r'jira') or _field(text, r'jira_project_key')
    linear = _field(text, r'(?:é|e)quipe linear') or _field(text, r'linear')
    if not tool:
        if not empty(jira):
            tool = 'jira'
        elif not empty(linear):
            tool = 'linear'
    project = None
    if tool == 'jira':
        for value in (jira, declared, _field(text, r'jira_project_key')):
            if empty(value):
                continue
            m = (re.search(r'/(?:projects|browse)/([A-Z][A-Z0-9]{1,9})\b', value) or re.search(r'`([A-Z][A-Z0-9]{1,9})`', value)
                 or re.search(r'\[([A-Z][A-Z0-9]{1,9})\b', value) or re.match(r'\s*([A-Z][A-Z0-9]{1,9})(?![\w.-])', value))
            if m:
                project = m.group(1)
                break
    elif tool == 'linear':
        team = _field(text, r'(?:é|e)quipe linear')
        project = None if empty(team) else team
    return {'outil': tool, 'projet': project}


def status_key(status):
    """A status as compared with the sheet's internal ones: no accent, no case, spaces folded, no markup."""
    return re.sub(r'\s+', ' ', norm(status)).strip(' *_`«»"')


def internal_statuses(studio):
    """The statuses the sheet lists as internal (« Statuts internes » : À rédiger, Brouillon): only a ticket in one of
    them may be rewritten; every other ticket gets a dated addition (PM, Q16, 2026-11-12)."""
    value = _field(_sheet(studio), r'statuts? internes?(?: du ticketing)?')
    return {status_key(x) for x in re.split(r'[,;·/]', value) if x.strip()} - {''}


# ---------- the search

def settled_cases(studio):
    reg = registre.lire_fichier(registre.chemin_du_studio(studio))
    return [c for c in reg['cas'] if c['etat'] == 'tranché' and c['tranche']['choix'] == 'remplacer']


def terms(case):
    """The words of the old value that the new one does not carry, longest first (three at most), and the old value
    itself as a phrase when it is short."""
    c = _conflits()
    old = re.sub(r'[^\w\s-]', ' ', case['ancienne']['texte'])        # no quote nor apostrophe: safe in a shell
    new_words = {norm(w) for w in re.findall(r"[\w'-]+", case['nouvelle']['texte'])}
    found = []
    for w in re.findall(r'[\w-]+', old):
        n = norm(w)
        if len(n) >= 4 and re.search(r'[a-z0-9]', n) and n not in c.STOP and n not in new_words and n not in [norm(x) for x in found]:
            found.append(w)
    found.sort(key=len, reverse=True)
    phrase = ' '.join(old.split())
    return {'phrase': phrase if len(phrase.split()) <= 6 else None, 'mots': found[:3]}


def _jql(project, t, done):
    parts = []
    if t['phrase']:
        parts.append('text ~ "\\"' + t['phrase'].replace('"', '') + '\\""')
    if t['mots']:
        parts.append('(' + ' AND '.join(f'text ~ "{w}"' for w in t['mots']) + ')')
    if not parts:
        return None
    scope = f'project = "{project}" AND ' if project else ''
    return f"{scope}statusCategory {'=' if done else '!='} Done AND ({' OR '.join(parts)}) ORDER BY updated DESC"


def estimate(n_cases):
    """A ceiling for searching the tickets of n settled conflicts: one Sonnet sub-agent per batch, and the session's
    calls (Opus, cache read)."""
    c = _conflits()
    if not n_cases:
        return {'conflits': 0, 'usd': 0.0, 'pourcent_semaine': 0.0}
    per_case = OPEN_PER_CASE * (DESCRIPTION_CHARS + 200) + 400
    batches = math.ceil(n_cases * per_case / BATCH_CHARS)
    tok = n_cases * per_case / c.CARACTERES_PAR_TOKEN
    agents = c.cout_sous_agents(batches, tok, n_cases * OPEN_PER_CASE * OUTPUT_PER_TICKET)[0]
    session = c.cout_usd('opus', 2000 * n_cases, 300 * n_cases, n_cases * SESSION_CALLS_PER_CASE * SESSION_CONTEXT)
    usd = (agents + session) * c.MARGE
    return {'conflits': n_cases, 'lots': batches, 'usd': round(usd, 2), 'pourcent_semaine': round(usd / c.POURCENT_USD, 2)}


def cost_line(e):
    c = _conflits()
    n = e['conflits']
    return (f"Retrouver les tickets de {n} conflit{'s' if n > 1 else ''} tranché{'s' if n > 1 else ''} : environ "
            f"{c.fr(float(e['pourcent_semaine']))} % de ta semaine ({c.fr(float(e['usd']))} $), {OPEN_PER_CASE} tickets "
            "ouverts lus au plus par conflit, jugés par un sous-agent Sonnet.")


def search(studio, only=()):
    """What to search, per settled conflict not searched yet: the queries (open tickets with their description, capped;
    finished ones, title only), and the cost of the whole search."""
    ref = project_ref(studio)
    if not ref['outil']:
        return {'outil': None, 'conflits': [], 'message': "Aucun outil ticketing sur la fiche projet (« Outil ticketing », "
                "« Jira » ou « Linear ») : aucun ticket à chercher."}
    if ref['outil'] == 'jira' and not ref['projet']:
        return {'outil': 'jira', 'conflits': [], 'message': "La clé du projet Jira n'est pas sur la fiche projet (ligne "
                "« Jira ») : dis-la-moi, ou ajoute-la à la fiche, avant que je cherche les tickets."}
    data = load(studio)
    cases = [c for c in settled_cases(studio) if (c['id'] in only if only else c['id'] not in data['cherches'])]
    out = []
    for c in cases:
        t = terms(c)
        item = {'cas': c['id'], 'titre': registre.sans_codes(c['sujet']), 'ancienne': c['ancienne']['texte'],
                'nouvelle': c['nouvelle']['texte'], 'phrase': t['phrase'], 'mots': t['mots']}
        if ref['outil'] == 'jira':
            item['jql_ouverts'] = _jql(ref['projet'], t, done=False)
            item['jql_termines'] = _jql(ref['projet'], t, done=True)
        else:
            item['requete'] = t['phrase'] or ' '.join(t['mots'])
        out.append(item)
    e = estimate(len(out))
    return {'outil': ref['outil'], 'projet': ref['projet'], 'conflits': out, 'ouverts_par_conflit': OPEN_PER_CASE,
            'termines_par_conflit': DONE_PER_CASE, 'cout': e,
            'message': cost_line(e) if out else 'Aucun conflit tranché « remplacer » dont les tickets restent à chercher.'}


def _read_case(folder, case_id):
    """The tickets the session saved for one conflict: open ones (capped, finished ones moved aside) and finished
    ones (capped)."""
    opened, done = [], []
    for name, bucket in ((f'{case_id}.json', opened), (f'{case_id}-termines.json', done)):
        raw = read_json(pathlib.Path(folder) / name)
        for i in _issues(raw) if raw is not None else []:
            if isinstance(i, dict):
                t = normalize(i)
                if t['cle'] and t['titre']:
                    (done if t['termine'] else bucket).append(t)
    seen = set()
    opened = [t for t in opened if not (t['cle'] in seen or seen.add(t['cle']))][:OPEN_PER_CASE]
    done = [t for t in done if not (t['cle'] in seen or seen.add(t['cle']))][:DONE_PER_CASE]
    return opened, done


def _folder_cases(studio, folder):
    by_id = {c['id']: c for c in settled_cases(studio)}
    ids = sorted({p.name.split('.')[0].split('-')[0] for p in pathlib.Path(folder).glob('C*.json')},
                 key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    return [by_id[i] for i in ids if i in by_id]


def batches(studio, folder):
    """The sub-agent's text, cut in batches of less than BATCH_CHARS: per conflict, the old and new values, then each
    open ticket (key, title, status, whether it may be rewritten, its description, short)."""
    internal = internal_statuses(studio)
    blocks = []
    for c in _folder_cases(studio, folder):
        opened, _ = _read_case(folder, c['id'])
        if not opened:
            continue
        lines = [f"## Conflit {c['id']} · {c['sujet']}", f"Ancienne valeur : {c['ancienne']['texte']}",
                 f"Nouvelle valeur (fait foi) : {c['nouvelle']['texte']}", '']
        for t in opened:
            rewrite = status_key(t['statut']) in internal
            lines += [f"### Ticket {t['cle']} · {t['titre']}",
                      f"Statut : {t['statut'] or 'inconnu'}" + (' (statut interne : réécriture permise)' if rewrite else ''),
                      f"Description : {plain(t['description'], DESCRIPTION_CHARS) or '(vide)'}", '']
        blocks.append('\n'.join(lines))
    out, cur = [], ''
    for b in blocks:
        if cur and len(cur) + len(b) > BATCH_CHARS:
            out.append(cur)
            cur = ''
        cur += b + '\n'
    if cur:
        out.append(cur)
    return out


def batch_text(studio, folder, k):
    all_batches = batches(studio, folder)
    if not 1 <= k <= len(all_batches):
        return None
    target = pathlib.Path(folder) / f'jugements-{k}.json'
    return (f"# Tickets à juger, lot {k} sur {len(all_batches)}\n\n" + all_batches[k - 1] +
            f"\nÉcris tes jugements dans : {target}\n")


def prepare_folder(studio, folder, today=None):
    """Drafts from what the session saved in `folder` and the sub-agents' judgments: a ticket judged touched gets a
    draft; a finished one is only named; every conflict of the folder is noted as searched."""
    judged = {}
    for p in sorted(pathlib.Path(folder).glob('jugements-*.json')):
        for j in read_json(p) or []:
            if isinstance(j, dict) and j.get('touche'):
                judged[(j.get('cas'), j.get('cle'))] = j
    internal = internal_statuses(studio)
    result = {'prepares': 0, 'tickets': [], 'termines': [], 'deja_corriges': [], 'erreurs': [], 'conflits': 0}
    for c in _folder_cases(studio, folder):
        opened, done = _read_case(folder, c['id'])
        chosen = []
        for t in opened:
            j = judged.get((c['id'], t['cle']))
            if not j:
                continue
            t = dict(t)
            if status_key(t['statut']) in internal and str(j.get('apres') or '').strip():
                t['reecriture_permise'] = True
                t['apres'] = j['apres']
            chosen.append(t)
        r = prepare(studio, c['id'], chosen + [dict(t, termine=True) for t in done], today=today, mark_searched=True)
        result['conflits'] += 1
        result['prepares'] += r.get('prepares', 0)
        for k in ('tickets', 'termines', 'deja_corriges', 'erreurs'):
            result[k] += r.get(k, [])
    return result


# ---------- drafts

def settled_case(studio, case_id):
    reg = registre.lire_fichier(registre.chemin_du_studio(studio))
    for c in reg['cas']:
        if c['id'] == case_id:
            return c
    return None


def prepare(studio, case_id, tickets, today=None, mark_searched=False):
    """Drafts for the tickets of one settled case.

    A ticket: {'cle', 'titre', 'statut', 'description', 'termine'?, 'outil'?, 'reecriture_permise'?, 'apres'?}. The
    draft is a dated addition at the top, unless the ticket may be rewritten and a new description is given
    (Markdown; converted to ADF for Jira). A finished ticket gets no draft: it is named in the recap. Only a case
    settled with « remplacer » gets drafts. A draft not yet pushed is replaced by a new one for the same ticket."""
    case = settled_case(studio, case_id)
    if not case:
        return {'prepares': 0, 'erreurs': [f'conflit introuvable au registre : {case_id}']}
    if case['etat'] != 'tranché' or case['tranche']['choix'] != 'remplacer':
        return {'prepares': 0, 'erreurs': [f"« {registre.sans_codes(case['sujet'])} » n'est pas tranché « remplacer » : "
                                           "aucun ticket à corriger."]}
    tool_default = project_ref(studio)['outil']
    date = registre.jjmmaaaa(today)
    addition = ADDITION.format(date=date, nouvelle=case['nouvelle']['texte'], ancienne=case['ancienne']['texte'])
    data = load(studio)
    made, skipped, done, errors = [], [], [], []
    for t in tickets:
        tool = (t.get('outil') or tool_default or '').lower()
        if not t.get('cle') or not t.get('titre'):
            errors.append('un ticket sans clé ou sans titre est ignoré')
            continue
        title = ' '.join(str(t['titre']).split())
        if t.get('termine'):
            done.append(title)
            if not any(d['cas'] == case_id and d['cle'] == t['cle'] and d['etat'] == 'termine' for d in data['brouillons']):
                data['brouillons'].append({'id': next_id(data), 'cas': case_id, 'sujet': case['sujet'], 'outil': tool,
                                           'cle': t['cle'], 'titre': title, 'statut': t.get('statut') or '',
                                           'etat': 'termine', 'signale': False, 'prepare_le': date})
            continue
        if tool not in TOOLS:
            errors.append(f"« {title} » : outil ticketing inconnu (fiche projet)")
            continue
        before = canonical(t.get('description'))
        if tool == 'jira' and before is not None and not isinstance(before, dict):
            errors.append(f"« {title} » : la description Jira doit être lue en ADF")
            continue
        rewrite = bool(t.get('reecriture_permise')) and t.get('apres') is not None and is_simple(before)
        if any(x['cas'] == case_id and x['cle'] == t['cle'] and x['etat'] == 'pousse' for x in data['brouillons']) \
                or (not rewrite and already_added(before, case)):
            skipped.append(title)
            continue
        if rewrite:
            after = t['apres'] if isinstance(t['apres'], dict) or tool != 'jira' else md_to_adf(t['apres'])
        else:
            after = with_addition(before, addition, tool)
        for old in data['brouillons']:
            if old['cas'] == case_id and old['cle'] == t['cle'] and old['etat'] in ('brouillon', 'valide', 'change'):
                old['etat'] = 'remplace'
        d = {'id': next_id(data), 'cas': case_id, 'sujet': case['sujet'], 'outil': tool, 'cle': t['cle'],
             'titre': title, 'statut': t.get('statut') or '',
             'mode': 'reecriture' if rewrite else 'ajout', 'ajout': None if rewrite else addition,
             'avant': before, 'empreinte': fingerprint(before), 'empreinte_texte': text_fingerprint(before),
             'apres': after, 'etat': 'brouillon', 'prepare_le': date}
        data['brouillons'].append(d)
        made.append(title)
    if mark_searched:
        data['cherches'][case_id] = date
    save(studio, data)
    return {'prepares': len(made), 'tickets': made, 'termines': done, 'deja_corriges': skipped, 'erreurs': errors}


def pending(data, states=('brouillon',)):
    return [d for d in data['brouillons'] if d['etat'] in states]


def drafts(studio):
    """Every draft waiting for the PM, grouped by conflict, before and after, each ticket by its title; the finished
    tickets not corrected; and one form. Showing them marks the finished ones as told."""
    data = load(studio)
    items = pending(data)
    done = [d for d in data['brouillons'] if d['etat'] == 'termine' and not d.get('signale')]
    if not items and not done:
        return {'texte': '', 'formulaire': None, 'n': 0}
    lines, subject = [], None
    for d in items:
        if d['sujet'] != subject:
            subject = d['sujet']
            lines.append(f"Conflit « {registre.sans_codes(subject)} » :")
        status = f", {d['statut'].lower()}" if d['statut'] else ''
        lines.append(f"- « {d['titre']} » ({TOOLS.get(d['outil'], d['outil'])}{status})")
        lines.append(f"  Avant : {plain(d['avant'], 280) or '(description vide)'}")
        if d['mode'] == 'ajout':
            lines.append(f"  Après : ajout en tête, « {d['ajout']} » ; le reste ne change pas.")
        else:
            lines.append(f"  Après (réécrit, statut interne) : {plain(d['apres'], 280)}")
    if done:
        lines.append('Tickets terminés, jamais corrigés (ils parlent peut-être de l\'ancienne valeur) : '
                     + ' ; '.join(f"« {d['titre']} »" for d in done) + '.')
        for d in done:
            d['signale'] = True
        save(studio, data)
    n = len(items)
    if not n:
        return {'texte': '\n'.join(lines), 'formulaire': None, 'n': 0}
    s = 's' if n > 1 else ''
    question = (f"{n} correction{s} de ticket{s} en brouillon, ci-dessus : la description seulement, aucun commentaire.\n"
                "Rien ne part sans ton go. Chaque ticket est relu juste avant ; s'il a changé, il ne part pas. "
                "Dans « Autre », tu peux en écarter un (« écarte <titre> ») ou changer son texte "
                "(« pour <titre>, écris … »).")
    options = [{'label': LABEL_GO + RECOMMENDED,
                'description': 'Chaque ticket reçoit sa correction, en heures ouvrées seulement (lundi à vendredi, 8 h à 20 h).'},
               {'label': LABEL_ALL_ASIDE, 'description': 'Aucun ticket ne change ; les brouillons sont mis de côté.'},
               {'label': LABEL_DISCUSS, 'description': "Tu m'expliques, on en parle, puis tu me reposes la question."}]
    return {'texte': '\n'.join(lines), 'n': n,
            'formulaire': {'header': 'Tickets', 'question': question, 'options': options, 'multiSelect': False}}


def _designate(items, what):
    wanted = words(what)
    if not wanted:
        return []
    exact = [d for d in items if norm(d['titre']).strip() == norm(what).strip()]
    return exact or [d for d in items if wanted <= words(d['titre'])]


def _ambiguous(what, found):
    if not found:
        return f"aucun ticket en brouillon ne répond à « {what} »"
    return f"plusieurs tickets répondent à « {what} » : " + ' ; '.join(f"« {d['titre']} »" for d in found) + '. Lequel ?'


def validate(studio, pm, aside=(), change=(), all_aside=False, now=None, today=None):
    """The PM's one go. Set-aside tickets never go; a changed one takes the PM's text as its dated addition (a
    rewrite takes it as its whole new description). A word that points at no ticket or at several writes nothing."""
    data = load(studio)
    items = pending(data)
    if not items:
        return {'valides': 0, 'ecartes': 0, 'erreurs': [], 'point': 'Aucun brouillon de ticket en attente.'}
    errors, out, changed = [], [], {}
    for what in aside:
        found = _designate(items, what)
        if len(found) != 1:
            errors.append(_ambiguous(what, found))
        else:
            out.append(found[0])
    for c in change:
        found = _designate(items, c.get('quoi') or '')
        text = ' '.join(str(c.get('texte') or '').split())
        if len(found) != 1:
            errors.append(_ambiguous(c.get('quoi') or '', found))
        elif not text:
            errors.append(f"texte vide pour « {found[0]['titre']} »")
        else:
            changed[found[0]['id']] = text
    if errors:
        return {'valides': 0, 'ecartes': 0, 'erreurs': errors, 'point': 'Rien écrit.'}
    if all_aside:
        out = list(items)
    date = registre.jjmmaaaa(today)
    for d in items:
        if d in out:
            d['etat'], d['ecarte_le'] = 'ecarte', date
            continue
        if d['id'] in changed:
            text = changed[d['id']]
            if d['mode'] == 'ajout':
                if not norm(text).startswith('mise a jour du'):
                    text = f"Mise à jour du {date} : {text}"
                d['ajout'], d['apres'] = text, with_addition(d['avant'], text, d['outil'])
            else:
                d['apres'] = md_to_adf(text) if d['outil'] == 'jira' else text
        d['etat'], d['go_le'], d['go_par'] = 'valide', date, pm
    save(studio, data)
    n_ok = sum(1 for d in items if d['etat'] == 'valide')
    h = business_hours(now)
    point = f"{n_ok} ticket{'s' if n_ok > 1 else ''} à pousser, {len(out)} écarté{'s' if len(out) > 1 else ''}."
    if n_ok and not h['ouvre']:
        point += ' ' + out_of_hours_line(h)
    return {'valides': n_ok, 'ecartes': len(out), 'erreurs': [], 'point': point, 'heures': h}


def to_push(studio, now=None):
    """What may be pushed now: the validated drafts, only in business hours."""
    items = pending(load(studio), ('valide',))
    h = business_hours(now)
    if not items:
        return {'pousser': [], 'heures': h, 'message': 'Aucun ticket validé en attente.'}
    if not h['ouvre']:
        return {'pousser': [], 'heures': h, 'message': out_of_hours_line(h)}
    return {'pousser': [{'id': d['id'], 'outil': d['outil'], 'cle': d['cle'], 'titre': d['titre']} for d in items],
            'heures': h, 'message': f"{len(items)} ticket{'s' if len(items) > 1 else ''} à pousser, un par un, chacun relu juste avant."}


def _find(data, ticket_id):
    for d in data['brouillons']:
        if d['id'] == ticket_id:
            return d
    return None


def _current_description(current):
    """The description out of what the tool returned for one ticket (a whole ticket, or the description alone)."""
    if isinstance(current, dict) and current.get('type') == 'doc':
        return current
    if isinstance(current, (dict, list)):
        issues = _issues(current)
        if issues and isinstance(issues[0], dict):
            return normalize(issues[0])['description']
    return current


def unchanged(d, current):
    current = canonical(current)
    if isinstance(canonical(d['avant']), dict) and isinstance(current, dict):
        return fingerprint(current) == d['empreinte']
    return text_fingerprint(current) == d.get('empreinte_texte', text_fingerprint(d['avant']))


def verify(studio, ticket_id, current, out_file=None, now=None, today=None):
    """Just before a push: the hour again, then the ticket as read now against the draft. Unchanged: the description
    to push is written to `out_file` (outside the Studio). Changed: nothing is pushed, the PM is told."""
    data = load(studio)
    d = _find(data, ticket_id)
    if not d or d['etat'] != 'valide':
        return {'pousser': False, 'message': f'{ticket_id} : aucun ticket validé sous ce nom.'}
    h = business_hours(now)
    if not h['ouvre']:
        return {'pousser': False, 'message': out_of_hours_line(h)}
    if current is None or (isinstance(current, (dict, list)) and not (isinstance(current, dict) and current.get('type') == 'doc')
                           and not any(isinstance(i, dict) and normalize(i)['lu'] for i in _issues(current))):
        return {'pousser': False, 'message': f"« {d['titre']} » n'a pas pu être relu dans {TOOLS.get(d['outil'], d['outil'])} : "
                                             "rien n'est poussé ; je réessaie au prochain passage."}
    ticket = normalize(_issues(current)[0]) if isinstance(current, (dict, list)) and not (
        isinstance(current, dict) and current.get('type') == 'doc') else None
    if ticket and ticket['termine']:
        d['etat'], d['termine_le'] = 'termine', registre.jjmmaaaa(today)
        d['signale'] = True
        save(studio, data)
        return {'pousser': False, 'message': f"« {d['titre']} » est terminé depuis le brouillon : il n'est pas corrigé."}
    if ticket and d['mode'] == 'reecriture' and status_key(ticket['statut']) not in internal_statuses(studio):
        d['etat'], d['change_le'] = 'change', registre.jjmmaaaa(today)
        save(studio, data)
        return {'pousser': False, 'change': True, 'cas': d['cas'],
                'message': f"« {d['titre']} » n'est plus dans un statut interne : il ne peut plus être réécrit, rien "
                           "n'est poussé. Je refais le brouillon en ajout daté si tu veux."}
    current = _current_description(current)
    if not unchanged(d, current):
        d['etat'], d['change_le'] = 'change', registre.jjmmaaaa(today)
        save(studio, data)
        return {'pousser': False, 'change': True, 'cas': d['cas'],
                'message': f"« {d['titre']} » a changé dans {TOOLS.get(d['outil'], d['outil'])} depuis le brouillon : "
                           "rien n'est poussé. Je refais le brouillon sur sa version actuelle si tu veux."}
    if out_file:
        p = pathlib.Path(out_file)
        p.write_text(json.dumps(d['apres'], ensure_ascii=False) if isinstance(d['apres'], dict) else d['apres'],
                     encoding='utf-8')
    return {'pousser': True, 'outil': d['outil'], 'cle': d['cle'], 'fichier': str(out_file) if out_file else None,
            'format': 'adf' if d['outil'] == 'jira' else 'markdown',
            'message': f"« {d['titre']} » n'a pas changé : il peut partir."}


def pushed(studio, ticket_id, reread=None, failure=None, today=None):
    """The push is done: checked on the ticket read again when given (the correction must be there), else noted.
    A failure keeps the ticket validated, for the next pass."""
    data = load(studio)
    d = _find(data, ticket_id)
    if not d:
        return {'message': f'{ticket_id} : inconnu.'}
    if not failure and reread is not None:
        now_text = plain(_current_description(reread))
        ok = now_text.startswith(plain(d['ajout'])) if d['mode'] == 'ajout' else now_text == plain(d['apres'])
        if not ok:
            failure = 'la relecture après le push ne montre pas la correction'
    if failure:
        d['echec'] = ' '.join(str(failure).split())
        save(studio, data)
        return {'message': f"« {d['titre']} » n'est pas corrigé : {d['echec']}. Il reste validé."}
    d['etat'], d['pousse_le'] = 'pousse', registre.jjmmaaaa(today)
    d.pop('echec', None)
    save(studio, data)
    return {'message': f"« {d['titre']} » corrigé."}


def status(studio, now=None):
    """One line for the session's head: drafts waiting for the go, validated tickets waiting for business hours,
    tickets that changed since their draft, settled conflicts whose tickets were not searched yet."""
    data = load(studio)
    n_draft, n_ok, n_changed = (len(pending(data, (s,))) for s in ('brouillon', 'valide', 'change'))
    parts = []
    if n_draft:
        parts.append(f"{n_draft} correction{'s' if n_draft > 1 else ''} de ticket en brouillon, qui attend{'ent' if n_draft > 1 else ''} ton go")
    if n_ok:
        h = business_hours(now)
        parts.append(f"{n_ok} ticket{'s' if n_ok > 1 else ''} validé{'s' if n_ok > 1 else ''}, "
                     + ('à pousser maintenant' if h['ouvre'] else f"à pousser à partir de {h['prochain']}"))
    if n_changed:
        parts.append(f"{n_changed} ticket{'s' if n_changed > 1 else ''} changé{'s' if n_changed > 1 else ''} depuis le brouillon, pas poussé{'s' if n_changed > 1 else ''}")
    if project_ref(studio)['outil']:
        n_new = sum(1 for c in settled_cases(studio) if c['id'] not in data['cherches'])
        if n_new:
            parts.append(f"{n_new} conflit{'s' if n_new > 1 else ''} tranché{'s' if n_new > 1 else ''} dont les tickets restent à chercher")
    return {'texte': ' ; '.join(parts) + '.' if parts else '', 'brouillons': n_draft, 'valides': n_ok, 'changes': n_changed}


# ---------- command line

def _json_arg(value):
    if value is None:
        return []
    p = pathlib.Path(value)
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else json.loads(value)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('heure')
    sp.add_parser('dossier')
    x = sp.add_parser('recherche'); x.add_argument('studio'); x.add_argument('--cas', action='append', default=[])
    x = sp.add_parser('lot'); x.add_argument('studio'); x.add_argument('dossier'); x.add_argument('k', type=int)
    x.add_argument('--sortie', required=True)
    x = sp.add_parser('preparer'); x.add_argument('studio'); x.add_argument('dossier')
    x = sp.add_parser('brouillons'); x.add_argument('studio')
    x = sp.add_parser('valider'); x.add_argument('studio'); x.add_argument('--pm', required=True)
    x.add_argument('--ecarter'); x.add_argument('--changer'); x.add_argument('--tout-ecarter', action='store_true')
    x = sp.add_parser('pousser'); x.add_argument('studio')
    x = sp.add_parser('verifier'); x.add_argument('studio'); x.add_argument('id'); x.add_argument('--actuel', required=True)
    x.add_argument('--sortie', required=True)
    x = sp.add_parser('pousse'); x.add_argument('studio'); x.add_argument('id'); x.add_argument('--relu'); x.add_argument('--echec')
    x = sp.add_parser('etat'); x.add_argument('studio')
    a = ap.parse_args(argv)
    if a.cmd == 'heure':
        r = business_hours()
    elif a.cmd == 'dossier':
        r = {'dossier': tempfile.mkdtemp(prefix='cockpit-tickets-')}
    elif a.cmd == 'recherche':
        r = search(a.studio, a.cas)
    elif a.cmd == 'lot':
        text = batch_text(a.studio, a.dossier, a.k)
        if text is None:
            r = {'erreurs': [f'lot {a.k} inexistant ({len(batches(a.studio, a.dossier))} lot(s))']}
        else:
            pathlib.Path(a.sortie).write_text(text, encoding='utf-8')
            r = {'lot': a.k, 'lots': len(batches(a.studio, a.dossier)), 'fichier': a.sortie,
                 'jugements': str(pathlib.Path(a.dossier) / f'jugements-{a.k}.json')}
    elif a.cmd == 'preparer':
        r = prepare_folder(a.studio, a.dossier)
        r['lots'] = len(batches(a.studio, a.dossier))
    elif a.cmd == 'brouillons':
        r = drafts(a.studio)
    elif a.cmd == 'valider':
        r = validate(a.studio, a.pm, _json_arg(a.ecarter), _json_arg(a.changer), a.tout_ecarter)
    elif a.cmd == 'pousser':
        r = to_push(a.studio)
    elif a.cmd == 'verifier':
        r = verify(a.studio, a.id, read_json(a.actuel), a.sortie)
    elif a.cmd == 'pousse':
        r = pushed(a.studio, a.id, read_json(a.relu) if a.relu else None, a.echec)
    else:
        r = status(a.studio)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 1 if r.get('erreurs') else 0


if __name__ == '__main__':
    sys.exit(main())
