"""A question to the PM takes its number as it is asked, from the session that asks it, in one call.

The app does what the foreman did (sessions, their end-of-turn card, the sidebar, messages between sessions): the
published board and its foreman are retired (decision of the PM, 2026-11-03). A session of
a project takes the next number from a counter shared on the Mac and writes its line in the project's mirror, which
Mon Studio and its project view read. Nothing here blocks: a session that cannot run this asks its question anyway.

    question.py hook               session-start hook: the instruction in a session of a project or of a Studio
                                   known in ~/Mon Studio/projets.json, nothing elsewhere
    question.py take [project]     the next number alone (« Q3 ») and its document id, for a check by hand
    question.py new --kind decision --title "..." [--subject "..."] [--detail "..."] [--lane <id or name>]
                    [--rattacher conflits|aucune]
                                   takes the number and writes the line in the mirror; --rattacher, for a scheduled
                                   task: the line goes to « <Projet> · Conflits Studio » (or to no session) instead of
                                   the routine's own session
    question.py settle <number> --decision "..."
                                   the PM answered and the session acts: the line leaves the mirror, the PM's words go
                                   to the local journal; only an open line this session asked, otherwise it refuses
    question.py event --type progress|done|blocked --title "..." [--detail "..."]
                                   an advance, an end of task, a wait on a third party: one line of the local journal
    question.py init [--name "..."] [--folder <path>]
                                   the project of this session gets its mirror, its counter and its project view
    question.py notices            UserPromptSubmit hook: in the session that asked it, one line per question the
                                   ingestion settled at its source or the PM reopened, once (see « Settled at the source »)

Numbers start again from 1 at the first question of each working day, Paris time (so the sequence stays short: the counter had reached Q140 after 12 days, with never more than 20 lines open at once). Within a day they go up, each question taking
the smallest free number above the last one given that day. A number is free when no open line holds it (mirror,
or a line written by `new` and not posted yet) and nothing has held it for 12 hours (given, open, or settled).
On a weekend or a public holiday the day's sequence goes on; nothing changes before the next working day.

A Studio known in ~/Mon Studio/projets.json (`studios`, written by projets.py) needs no `init`: its register (mirror,
counter, journal) is created by its first `new` (or `event`), named after the Studio, its folder first, the asking
session as anchor. Numbers are per register, so per Studio. A session outside any known Studio and any mirror gets
nothing and takes no number.

The counter of a chantier sits next to its mirror: ~/Mon Studio/chantiers/<chantier>.numeros.json (the day of the
sequence, the last number given that day, and when each number was last held) and <chantier>.numero (the highest
number ever given, which parc.py reads; older copies of this script read it as the last one). One lock per
chantier, taken on the .numero file, serialises the counter and every write of the mirror, so two sessions asking
in the same second get two numbers. Since a number comes back, it no longer names a board document: documents
written this way are named n<YYYYMMDD>-<number> (n20261022-3), unique for ever; older ones keep their name.
"""
import argparse
import datetime as dt
try:
    import fcntl
except ImportError:   # Windows: no flock; msvcrt locks the same lock file
    fcntl = None
    import msvcrt
import importlib.util
import json
import os
import pathlib
import re
import shlex
import sys
import unicodedata
from zoneinfo import ZoneInfo

HOME = pathlib.Path.home()
MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO', str(HOME / 'Mon Studio')))
CHANTIERS = MON_STUDIO / 'chantiers'
INTERNAL = MON_STUDIO / '.parc'
PENDING = INTERNAL / 'questions'   # lines an older version wrote for the board: they still hold their number


def app_sessions_dir(env=None, platform=None, home=None):
    """Where the Claude app keeps its session records: MON_STUDIO_APP_SESSIONS first, then by OS (macOS
    ~/Library/Application Support/Claude, Windows %APPDATA%\\Claude, Linux ~/.config/Claude), as parc.py does."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    home = pathlib.Path(home or HOME)
    if env.get('MON_STUDIO_APP_SESSIONS'):
        return pathlib.Path(env['MON_STUDIO_APP_SESSIONS'])
    if platform.startswith('win'):
        base = pathlib.Path(env['APPDATA']) if env.get('APPDATA') else home / 'AppData' / 'Roaming'
    elif platform == 'darwin':
        base = home / 'Library' / 'Application Support'
    else:
        base = pathlib.Path(env['XDG_CONFIG_HOME']) if env.get('XDG_CONFIG_HOME') else home / '.config'
    return base / 'Claude' / 'claude-code-sessions'


APP_SESSIONS = app_sessions_dir()
STATE = INTERNAL / 'cockpit.json'
# « clic » : le fond est déjà décidé et la réponse tient en un clic (« ok ») ; Mon Studio la range
# avec les autorisations, dans la bande « En un clic » en tête de la page.
KINDS = ('go', 'decision', 'review', 'task', 'clic')
EVENT_TYPES = ('progress', 'done', 'blocked')
NUMBER = re.compile(r'^\s*Q(\d+)\b')
NUMBER_PREFIX = re.compile(r'^\s*Q\d+\s*[·:.-]?\s*')
# « Qn » where an answer or a title will carry the number (« Réponds « Qn : 1 » », « Qn · … »), which the session
# does not know yet. Not a bare « Qn » in a sentence: a question about the placeholder itself keeps it.
PLACEHOLDER = re.compile(r'\bQn\b(?=\s*[:·])')
SAFE_ID = re.compile(r'^local_[A-Za-z0-9_-]+$')
PARIS = ZoneInfo('Europe/Paris')
RETENUE_S = 12 * 3600      # a number held (given, open or settled) less than 12 h ago is not given again
VU_GARDE_S = 7 * 86400     # how long the counter remembers when a number was last held


def read_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def now():
    """The time, to the second. MON_STUDIO_NOW (ISO 8601) replaces the clock in tests."""
    fixed = parse_time(os.environ.get('MON_STUDIO_NOW')) if os.environ.get('MON_STUDIO_NOW') else None
    return (fixed or dt.datetime.now().astimezone()).replace(microsecond=0)


def parse_time(v):
    """An ISO 8601 time of the board (« 2026-10-21T08:39:21+02:00 », « …Z », a date alone), or None."""
    try:
        return dt.datetime.fromisoformat(str(v).replace('Z', '+00:00')).astimezone()
    except (TypeError, ValueError):
        return None


# ---------- Daily numbers

def easter(year):
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, (b, c) = year % 19, divmod(year, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def public_holidays(year):
    """French public holidays (metropolitan France)."""
    e = easter(year)
    return {dt.date(year, 1, 1), e + dt.timedelta(1), dt.date(year, 5, 1), dt.date(year, 5, 8), e + dt.timedelta(39),
            e + dt.timedelta(50), dt.date(year, 7, 14), dt.date(year, 8, 15), dt.date(year, 11, 1),
            dt.date(year, 11, 11), dt.date(year, 12, 25)}


def working_day(day):
    return day.weekday() < 5 and day not in public_holidays(day.year)


def paris_day(when):
    return when.astimezone(PARIS).date()


def document_id(number, when):
    """The board document of a question numbered by this counter: unique for ever, a number comes back but never
    twice in one day (n20261022-3)."""
    return f'n{paris_day(when):%Y%m%d}-{number}'


def number_of_document(doc_id):
    """3 for n20261022-3 and for n3 (a document of before the daily numbers); None for another name (q12)."""
    m = re.match(r'^n(?:\d{8}-)?(\d+)$', str(doc_id or ''))
    return int(m.group(1)) if m else None


def choose(state, when, held, retention=RETENUE_S):
    """(number, new state): the rule of the daily numbers, without any file (take, the tests and the replay of the
    boards' history use it as it is).
    state: {'jour': ISO date of the working day the sequence started, or None; 'dernier': last number given in that
    sequence; 'vus': {number: ISO time it was last held}}. held: the numbers an open line holds now.
    At the first question of a working day (Paris time) the sequence starts again from 1; otherwise from the last
    number given + 1. The number is the smallest one from there that no open line holds and that nothing held for
    `retention` seconds. On a weekend or a public holiday, the sequence goes on."""
    today = paris_day(when)
    restart = working_day(today) and state.get('jour') != today.isoformat()
    n = 1 if restart else int(state.get('dernier') or 0) + 1
    vus = {int(k): parse_time(v) for k, v in (state.get('vus') or {}).items() if str(k).isdigit() and parse_time(v)}
    while n in held or (n in vus and (when - vus[n]).total_seconds() < retention):
        n += 1
    new = dict(state, dernier=n, jour=today.isoformat() if working_day(today) else state.get('jour'))
    new['vus'] = dict(state.get('vus') or {}, **{str(n): when.isoformat()})
    return n, new


def highest(titles):
    """The highest « Qn » that starts one of these titles, 0 if none."""
    return max([int(m.group(1)) for m in (NUMBER.match(str(t or '')) for t in titles) if m] or [0])


# ---------- The chantier of a session

def card(sid):
    """The app's card of a session (cwd, title, parent), or {}."""
    if not isinstance(sid, str) or not SAFE_ID.match(sid):
        return {}
    for path in APP_SESSIONS.glob(f'*/*/{sid}.json'):
        c = read_json(path)
        if isinstance(c, dict):
            return c
    return {}


_parc = None


def parc():
    """parc.py, next to this file in the plugin and in ~/Mon Studio/.parc (install.py copies both). Mon Studio's rule
    for the chantier of a session lives there: one rule for the screen and for the number. Loaded on first use."""
    global _parc
    if _parc is None:
        spec = importlib.util.spec_from_file_location('parc', pathlib.Path(__file__).resolve().with_name('parc.py'))
        _parc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_parc)
    return _parc


def mirrors():
    """[(path, mirror)] of the projects (chantiers) that have a mirror."""
    if not CHANTIERS.is_dir():
        return []
    out = []
    for path in sorted(CHANTIERS.glob('*.json')):
        m = read_json(path)
        if isinstance(m, dict) and m.get('chantier') and m.get('sessionId'):
            out.append((path, m))
    return out


def chantier_of(sid, cwd):
    """(mirror path, mirror, foreman's card) of the chantier this session belongs to, or None, by Mon Studio's rule
    (parc.regle_des_chantiers): the foreman itself; a session opened in a foreman's Studio folder or below, even if
    another mirror names it; elsewhere only, one a foreman launched, then one a mirror names."""
    if not sid:
        return None
    cards = {}

    def card_of(i):
        if i not in cards:
            cards[i] = card(i)
        return cards[i]

    def fiche(i):
        c = card_of(i)
        return {'cwd': c.get('cwd') or '', 'titre': c.get('title') or '',
                'parent': (c.get('spawnedFrom') or {}).get('sessionId')}

    # The page's rule (parc.miroir_cache): a register keeps an archived anchor; a mirror from before stays hidden then.
    active = [(path, m) for path, m in mirrors()
              if not parc().miroir_cache(m, {'archivee': bool(card_of(m['sessionId']).get('isArchived'))}
                                         if card_of(m['sessionId']) else None)]
    if not active:
        return None
    me = dict(fiche(sid), id=sid)
    me['cwd'] = cwd or me['cwd']
    chef = parc().regle_des_chantiers([m for _, m in active], fiche)(me)
    return next(((path, m, card_of(chef)) for path, m in active if m['sessionId'] == chef), None)


def studio_folder(cwd):
    """A session's folder as projets.py names a Studio: NFC, the app's working copy brought back to its repository."""
    d = unicodedata.normalize('NFC', os.path.normpath(os.path.expanduser(cwd or '')))
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', d)
    return m.group(1) if m else d


def known_studio(cwd):
    """{nom, dossier} of the Studio of ~/Mon Studio/projets.json (`studios`) that holds this folder, the deepest one,
    or None. Never the home folder."""
    data = read_json(MON_STUDIO / 'projets.json', {})
    listed = data.get('studios') if isinstance(data, dict) else None
    if not cwd or not isinstance(listed, list):
        return None
    here = studio_folder(cwd)
    best = None
    for st in listed:
        d = studio_folder(st.get('dossier')) if isinstance(st, dict) and isinstance(st.get('dossier'), str) else ''
        if not d or d == os.path.normpath(str(HOME)):
            continue
        if (here == d or here.startswith(d + os.sep)) and (best is None or len(d) > len(best['dossier'])):
            best = {'nom': (st.get('nom') or os.path.basename(d)).strip() or os.path.basename(d), 'dossier': d}
    return best


def open_register(sid, cwd):
    """The register of the known Studio that holds cwd, created on first use: a mirror named after the Studio, its
    folder first, this session as anchor. (mirror path, mirror, card) as chantier_of gives, or None outside any
    known Studio. Two sessions asking at once use one register: it is created under its lock, once."""
    st = known_studio(cwd)
    if not st:
        return None
    stem = re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', st['nom']).encode('ascii', 'ignore').decode()
                  .casefold()).strip('-') or 'projet'
    CHANTIERS.mkdir(parents=True, exist_ok=True)
    for i in range(1, 50):
        path = CHANTIERS / (f'{stem}.json' if i == 1 else f'{stem}-{i}.json')
        with Lock(path):
            m = read_json(path)
            if not isinstance(m, dict):
                write_mirror(path, {'chantier': st['nom'], 'studio': st['nom'], 'sessionId': sid,
                                    'dossiers': [st['dossier']], 'registre': True, 'misAJour': now().isoformat(),
                                    'attentes': [], 'lanes': []})
                break
            if st['dossier'] in (m.get('dossiers') or []):
                break   # another session created it a moment ago
    else:
        return None
    # The rule of chantiers decides as everywhere; a folder the app wrote decomposed (NFD) still finds its register.
    m = read_json(path, {})
    return chantier_of(sid, cwd) or (path, m, card(m.get('sessionId')))


def existing_register(cwd):
    """(mirror path, mirror, card) of the register already created for the known Studio that holds cwd, or None. Never
    creates one: settle finds the register `new` wrote in, even where the rule of chantiers covers no folder."""
    st = known_studio(cwd)
    if not st:
        return None
    for path, m in mirrors():
        if st['dossier'] in [studio_folder(x) for x in m.get('dossiers') or [] if isinstance(x, str)]:
            return path, m, card(m.get('sessionId'))
    return None


# ---------- Counter and mirror, under the chantier's lock

class Lock:
    """Exclusive lock of a chantier, taken on its counter file: guards the counter and the mirror."""

    def __init__(self, mirror_path):
        self.path = pathlib.Path(mirror_path).with_suffix('.numero')

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        if fcntl:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        else:
            # Windows: lock the first byte of the counter file; LK_LOCK retries for ten seconds, then raises.
            os.lseek(self.fd, 0, os.SEEK_SET)
            msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, *exc):
        if fcntl:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        else:
            os.lseek(self.fd, 0, os.SEEK_SET)
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        os.close(self.fd)

    def last(self):
        os.lseek(self.fd, 0, os.SEEK_SET)
        raw = os.read(self.fd, 64).decode('ascii', 'ignore').strip()
        return int(raw) if raw.isdigit() else 0

    def set(self, n):
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f'{n}\n'.encode('ascii'))
        os.fsync(self.fd)

    # The daily sequence, next to the .numero file (see the module's docstring).
    def state(self):
        """The counter's state; from a counter of before the daily numbers, the day of its last write and its number:
        a sequence started that day goes on until the next working day (nothing changes in the middle of a day)."""
        s = read_json(self.path.with_suffix('.numeros.json'))
        if isinstance(s, dict) and isinstance(s.get('vus', {}), dict):
            return s
        last = self.last()
        day = dt.datetime.fromtimestamp(os.fstat(self.fd).st_mtime).astimezone() if last else None
        return {'jour': paris_day(day).isoformat() if day else None, 'dernier': last, 'vus': {}}

    def save(self, state, when):
        """Writes the state (numbers held for more than VU_GARDE_S forgotten) and keeps .numero at the highest
        number ever given."""
        keep = {k: v for k, v in (state.get('vus') or {}).items()
                if parse_time(v) and (when - parse_time(v)).total_seconds() < VU_GARDE_S}
        write_mirror(self.path.with_suffix('.numeros.json'), dict(state, vus=keep))
        self.set(max(self.last(), int(state.get('dernier') or 0)))


def numbers_of(lines, key='titre'):
    """The numbers these mirror lines (or board documents, key='title') start with."""
    return {highest([l.get(key)]) for l in lines if isinstance(l, dict)} - {0}


def held_numbers(mirror_path, mirror):
    """The numbers an open line holds: open in the mirror, or written by `new` and not posted yet."""
    held = numbers_of(mirror.get('attentes') or [])
    folder = PENDING / pathlib.Path(mirror_path).stem
    for f in folder.glob('n*.json') if folder.is_dir() else []:
        held |= numbers_of([read_json(f, {})], 'title')
    return held


def note_held(state, numbers, when):
    """These numbers are held at `when` (open, settled, given): none comes back within RETENUE_S."""
    vus = dict(state.get('vus') or {})
    for n in numbers:
        old = parse_time(vus.get(str(n)))
        if not old or old < when:
            vus[str(n)] = when.isoformat()
    return dict(state, vus=vus)


def take(mirror_path, when=None):
    """(number, board document) of the next question of the chantier (choose)."""
    when = when or now()
    with Lock(mirror_path) as lock:
        n, state = choose(lock.state(), when, held_numbers(mirror_path, read_json(mirror_path, {}) or {}))
        lock.save(state, when)
        return n, document_id(n, when)


def raise_floor(lock, n):
    """.numero never goes below n (miroir.py: the board's highest number), for whoever reads it as the highest number
    given (parc.py). Called under the lock."""
    if lock.last() < n:
        lock.set(n)


def write_mirror(mirror_path, mirror):
    """Atomic: Mon Studio may read the mirror at any moment. Called under the lock."""
    mirror_path = pathlib.Path(mirror_path)
    tmp = mirror_path.with_name(f'.{mirror_path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(mirror, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, mirror_path)


def journal_path(mirror_path):
    return pathlib.Path(mirror_path).with_suffix('.journal.jsonl')


def journal_add(mirror_path, entry):
    """The project's journal: what sessions did (advances, ends of task, waits on a third party, settled questions),
    one JSON line each, in order, local and append only. The project view of Mon Studio reads it."""
    with Lock(mirror_path):
        with open(journal_path(mirror_path), 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def waiting(q, lanes, doc_id=None):
    """A board line (userQueue document) as the mirror carries it for Mon Studio. `doc` is the line's document id
    on the board, which lets the session that gets the PM's answer settle it (settle)."""
    lane = next((l for l in lanes if isinstance(l, dict) and l.get('id') == q.get('lane')), {})
    a = {'type': q.get('kind'), 'titre': q.get('title'),
         'ou': (lane.get('name') or lane.get('id')) if lane else (q.get('sessionLabel') or 'Chantier'),
         'depuis': q.get('createdAt')}
    if doc_id:
        a['doc'] = doc_id
    if q.get('due'):
        a['echeance'] = q['due']
    if q.get('blocks'):
        a['bloque'] = True  # a session is stopped on this wait
    if q.get('after'):
        a['apres'] = q['after']  # number of the question to settle before this one
    if q.get('arret'):
        a['arret'] = q['arret']  # a line opened for a stopped session: the foreman settles it once the session resumes
    # What a line of Mon Studio unfolds to, as on the board: the full text and what made it appear.
    if q.get('detail'):
        a['detail'] = q['detail']
    if q.get('trigger'):
        a['declencheur'] = q['trigger']
    # The question's own session, as the board writes it: the board ends the line with « · à traiter dans la session
    # « <sessionLabel> » » when it is not the foreman's. Only the question's: a lane's sessions never say it.
    for k in ('sessionId', 'sessionLabel'):
        if q.get(k):
            a[k] = q[k]
    # Two buttons: the verb opens the foreman (the mirror's sessionId); « Voir la session » opens the source.
    src = q.get('sessionId') or lane.get('sessionId') or lane.get('pillarId')
    if src:
        a['source'] = src
    if lane.get('pillarId'):
        a['pilier'] = lane['pillarId']  # the kit's main session: « Voir la session » falls back to it
    # A quick answer the PM gave from Mon Studio (go, not yet, an option), kept while it is « deposee ».
    rr = q.get('reponseRapide')
    if isinstance(rr, dict) and rr.get('texte'):
        a['reponseRapide'] = {k: rr[k] for k in ('texte', 'a', 'etat', 'canal') if rr.get(k)}
    return a


def lane_for(mirror, sid, wanted):
    lanes = [l for l in mirror.get('lanes') or [] if isinstance(l, dict)]
    if wanted:
        w = wanted.strip().casefold()
        return next((l for l in lanes if w in (str(l.get('id', '')).casefold(), str(l.get('name', '')).casefold())), None)
    return next((l for l in lanes if sid in (l.get('sessionId'), l.get('pillarId'))), None)


def tool_path(name='question.py'):
    """The copy in ~/Mon Studio/.parc when installed: the plugin's folder changes with each version."""
    copy = INTERNAL / name
    return copy if copy.exists() else pathlib.Path(__file__).resolve().with_name(name)


# ---------- Settled at the source (the ingestion kit, projet/.ingestion-auto-state.json, `reglees`)
#
# A pass of the ingestion settles alone what its source shows done (message sent, document filed, ticket finished),
# with its proof; never a choice nor a go. projets.py hands this module the entries of genre « question »; this is the
# only place a question leaves the mirror without its session: the passage itself never runs `settle` for another
# session. Nothing here sends anything to a session: the session that asked reads the notice at its next turn
# (`notices`, UserPromptSubmit hook).

SOURCE_TEXT = "Réglé par l'ingestion auto : "
# Kinds the source never settles, whatever an entry says: a choice, a go. A click (« confirme que c'est parti ») can be
# settled by a later dated fact that shows it done.
NEVER_BY_SOURCE = ('decision', 'go')
NOTICES = 'prevenues.json'   # in ~/Mon Studio/.parc: the journal ids each asking session was already told


def mirror_named(name):
    """The mirror path of the chantier named `name` (its file stem, `chantier` or `studio`), or None."""
    if not name or not CHANTIERS.is_dir():
        return None
    for path in sorted(CHANTIERS.glob('*.json')):
        m = read_json(path)
        if isinstance(m, dict) and m.get('chantier') and name in (path.stem, m.get('chantier'), m.get('studio')):
            return path
    return None


def journal_entries(mirror_path):
    out = []
    try:
        with open(journal_path(mirror_path), encoding='utf-8') as f:
            for raw in f:
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    out.append(o)
    except OSError:
        pass
    return out


def _journal_write(mirror_path, entry):
    """journal_add without the lock: for a caller that already holds it (flock is per open file, not per process)."""
    with open(journal_path(mirror_path), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def source_ids(entry):
    """(id of its settlement, id of its reopening) in the chantier's journal: one entry of the kit, one of each."""
    key = f'{entry.get("ref") or ""}-{entry.get("ts") or ""}'
    return f'settled-source-{key}', f'reopened-source-{key}'


def _source_question(entry):
    q = entry.get('question') if isinstance(entry, dict) else None
    if entry.get('genre') != 'question' or not isinstance(q, dict) or not q.get('chantier'):
        return None
    try:
        number = int(str(q.get('numero') or '').lstrip('Qq'))
    except ValueError:
        return None
    return dict(q, numero=number)


def _matches(a, q):
    """The mirror line the entry names: same board document; without one, same number and same asking session."""
    if not isinstance(a, dict):
        return False
    if q.get('doc'):
        return a.get('doc') == q['doc']
    return highest([a.get('titre')]) == q['numero'] and bool(q.get('sessionId')) and a.get('sessionId') == q['sessionId']


def settle_from_source(entry, when=None):
    """One `reglees` entry of genre question, without `rouverte`: the line it names leaves the mirror (number at rest
    12 h) and the journal says `settled`, `par: source`, with the line as it was. Only a line of a kind the source may
    settle (task, review), not opened for a stopped session, that appeared before the settlement. Idempotent: an entry
    already in the journal, or a line no longer in the mirror, changes nothing. Returns a short line of what was done, or None."""
    q = _source_question(entry)
    if not q or entry.get('rouverte'):
        return None
    path = mirror_named(q['chantier'])
    if not path:
        return None
    settled_id, _ = source_ids(entry)
    t = parse_time(entry.get('ts'))
    if not t:
        return None
    with Lock(path) as lock:
        if any(j.get('id') == settled_id for j in journal_entries(path)):
            return None
        mirror = read_json(path, {}) or {}
        lines = [a for a in mirror.get('attentes') or [] if _matches(a, q)]
        if len(lines) != 1:
            return None
        a = lines[0]
        since = parse_time(a.get('depuis'))
        if a.get('type') in NEVER_BY_SOURCE or a.get('type') not in KINDS or a.get('arret') or not since or since > t:
            return None
        n = highest([a.get('titre')]) or q['numero']
        mirror['attentes'] = [x for x in mirror.get('attentes') or [] if x is not a]
        mirror['misAJour'] = now().isoformat()
        write_mirror(path, mirror)
        lock.save(note_held(lock.state(), {n}, t), t)
        _journal_write(path, {'id': settled_id, 'at': t.isoformat(), 'type': 'settled', 'par': 'source', 'number': n,
                              'doc': a.get('doc'), 'sessionId': a.get('sessionId'), 'session': a.get('sessionLabel'),
                              'title': a.get('titre'), 'text': SOURCE_TEXT + str(entry.get('preuve') or '').strip(),
                              'ref': entry.get('ref'), 'ligne': a})
    return f'{a.get("titre")} : réglée par la source'


def reopen_from_source(entry, when=None):
    """An entry the PM reopened (`rouverte`, « rouvre Qn »): the line kept in the journal comes back to the mirror, same
    document, title, kind, detail and session; same number if no open line holds it, otherwise the next one (said in
    the journal and to the asking session). Journal `reopened`, `par: pm`. Only after a settlement by the source of
    this very entry, once. Returns a short line, or None."""
    q = _source_question(entry)
    if not q or not entry.get('rouverte'):
        return None
    path = mirror_named(q['chantier'])
    if not path:
        return None
    settled_id, reopened_id = source_ids(entry)
    t = parse_time(entry.get('rouverte')) or now()
    with Lock(path) as lock:
        journal = journal_entries(path)
        settled = next((j for j in journal if j.get('id') == settled_id), None)
        if not settled or not isinstance(settled.get('ligne'), dict) or any(j.get('id') == reopened_id for j in journal):
            return None
        line = dict(settled['ligne'])
        old = highest([line.get('titre')]) or settled.get('number')
        mirror = read_json(path, {}) or {}
        attentes = mirror.get('attentes') or []
        back = any(isinstance(a, dict) and line.get('doc') and a.get('doc') == line['doc'] for a in attentes)
        n, state = old, lock.state()
        if not back and old in held_numbers(path, mirror):
            n, state = choose(state, t, held_numbers(path, mirror))
            line['titre'] = f'Q{n} · ' + NUMBER_PREFIX.sub('', line.get('titre') or '')
        lock.save(note_held(state, {n}, t), t)
        if not back:
            mirror['attentes'] = attentes + [line]
            mirror['misAJour'] = now().isoformat()
            write_mirror(path, mirror)
        moved = f' sous Q{n} (Q{old} était repris)' if n != old else ''
        _journal_write(path, {'id': reopened_id, 'at': t.isoformat(), 'type': 'reopened', 'par': 'pm', 'number': n,
                              'previous': old if n != old else None, 'doc': line.get('doc'),
                              'sessionId': line.get('sessionId'), 'session': line.get('sessionLabel'),
                              'title': line.get('titre'), 'settledTitle': settled.get('title'),
                              'text': f'Rouverte par le PM{moved}.', 'ref': entry.get('ref')})
    return f'{line.get("titre")} : rouverte{moved}'


def apply_source(entries, when=None):
    """The kit's `reglees` entries of one Studio: settlements first, then reopenings. Returns what was done."""
    done = []
    for e in entries or []:
        if isinstance(e, dict) and not e.get('rouverte'):
            done.append(settle_from_source(e, when))
    for e in entries or []:
        if isinstance(e, dict) and e.get('rouverte'):
            done.append(reopen_from_source(e, when))
    return [d for d in done if d]


def notice_text(j):
    title = j.get('title') or (f'Q{j["number"]}' if j.get('number') else 'Une question')
    if j.get('type') == 'reopened':
        n = j.get('number')
        moved = f' (elle porte maintenant le numéro Q{n})' if j.get('previous') else ''
        return f'[Mon Studio] {title} est rouverte par le PM{moved} : rappelle-la de nouveau.'
    preuve = str(j.get('text') or '')[len(SOURCE_TEXT):] if str(j.get('text') or '').startswith(SOURCE_TEXT) else j.get('text') or ''
    n = j.get('number')
    return (f'[Mon Studio] {title} est réglée par la source : {preuve}. Ne la rappelle plus dans « Encore ouvert ». '
            f'Si le PM écrit « rouvre Q{n} », elle revient.')


def notices(sid=None):
    """The lines of context for this session: each question it asked that the source settled, or that the PM reopened,
    once (UserPromptSubmit hook). Reads the chantiers' journals; remembers what it told in .parc/prevenues.json."""
    sid = sid or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')
    if not sid or not CHANTIERS.is_dir():
        return []
    told_path = INTERNAL / NOTICES
    told = read_json(told_path, {})
    told = told if isinstance(told, dict) else {}
    mine = set(told.get(sid) or [])
    out, new = [], []
    for path in sorted(CHANTIERS.glob('*.json')):
        if path.name.endswith(('.numeros.json',)):
            continue
        for j in journal_entries(path):
            by_source = (j.get('type') == 'settled' and j.get('par') == 'source') or \
                        (j.get('type') == 'reopened' and str(j.get('id') or '').startswith('reopened-source-'))
            if by_source and j.get('sessionId') == sid and j.get('id') and j['id'] not in mine:
                out.append(notice_text(j))
                new.append(j['id'])
    if new:
        told[sid] = sorted(mine | set(new))
        INTERNAL.mkdir(parents=True, exist_ok=True)
        write_mirror(told_path, told)
    return out


# ---------- Commands

def hook():
    """Session start: the instruction in a session of a chantier or of a known Studio, nothing elsewhere. Never fails
    the session."""
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        data = {}
    sid = os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')
    if not sid:
        return
    cwd = (data or {}).get('cwd') or os.getcwd()
    found = chantier_of(sid, cwd)
    # A known Studio without a register yet gets the same instruction: its first `new` creates the register.
    name = found[1]['chantier'] if found else (known_studio(cwd) or {}).get('nom')
    if not name:
        return
    script = f'python3 {shlex.quote(str(tool_path()))}'
    print(f'Cette session fait partie du projet « {name} » (vue projet de Mon Studio).\n'
          f'Avant toute question au PM (décision, go, texte à relire, geste à faire, dont un prompt à coller dans une '
          f'autre session : --kind task), prends son numéro en un seul appel : '
          f'`{script} new --kind decision|go|review|task|clic --subject "<sujet>" --title "<la question en clair>" '
          f'--detail "<options, recommandation, comment répondre>"` (« Qn » y devient le numéro pris). --kind clic '
          f'seulement quand le fond est déjà décidé et que la réponse tient en un clic, « ok » (lancer ce qui est '
          f'décidé, ou confirmer qu\'un geste simple est fait) : la ligne va en tête de Mon Studio, avec les '
          f'autorisations ; sinon decision ou go. Il écrit la '
          f'ligne dans ~/Mon Studio : c\'est voulu, c\'est l\'écran du PM, rien d\'autre à faire. Écris la question '
          f'dans la langue où le PM travaille dans cette session (le français par défaut), numéro en tête '
          f'(« Qn · <titre court, 60 caractères au plus> : <la question précise> », options « 1) **<libellé court>** : … »), dans ton message, ou dans le menu de choix ou l\'encadré de fin de tour si tu en ouvres un ; tant '
          f'qu\'elle reste ouverte, rappelle-la '
          f'par ce numéro. Un message qui demande un geste au PM ne finit jamais par « Rien à faire de ton côté » '
          f'ni par « Rien d\'autre à faire de ton côté ». Les '
          f'numéros repartent de 1 chaque jour ouvré : hors de cette session, cite une question par son numéro et son '
          f'titre (« Q3 · Photos »). Si le script échoue, pose-la quand même.\n'
          f'Quand le PM a répondu et que tu agis : `{script} settle <numéro> --decision "<ses mots, cités>"`. Une '
          f'attente d\'un tiers (client, collègue) : `{script} event --type blocked --title "<qui, quoi>"` ; elle '
          f's\'affiche dans la vue projet. Pour relayer à une autre session, ses messages natifs ; un arbitrage entre '
          f'sessions devient une question au PM.')


def by_name(name):
    for path, m in mirrors():
        if name in (path.stem, m.get('chantier'), m.get('studio')):
            return path, m, card(m['sessionId'])
    return None


def cmd_take(args):
    found = by_name(args.chantier) if args.chantier else chantier_of(
        os.environ.get('CLAUDE_CODE_HOST_SESSION_ID'), os.getcwd())
    if not found:
        print('Aucun projet trouvé (miroir dans ~/Mon Studio/chantiers).', file=sys.stderr)
        return 3
    n, doc_id = take(found[0])
    print(f'Q{n}\nDocument : {doc_id}. Les numéros repartent de 1 chaque jour ouvré : hors de sa session, cite la question '
          f'par son numéro et son titre.')
    return 0


STOP_FR = {'authorization': 'sur une autorisation', 'error': 'sur une erreur', 'menu': 'sur un menu de choix'}


def cmd_new(args):
    if args.arret and not args.session:
        print("--arret marque la ligne d'une session arrêtée : donne aussi son identifiant (--session <id>).")
        return 2
    sid = args.session or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')
    if not sid:
        print("Pas d'identifiant de session de l'app : pose ta question sans numéro.")
        return 3
    me = card(sid)
    cwd = me.get('cwd') or os.getcwd()
    found = chantier_of(sid, cwd) or open_register(sid, cwd)
    if not found:
        print("Cette session n'est d'aucun Studio connu de Mon Studio : pose ta question comme d'habitude, sans numéro.")
        return 3
    path, m, _ = found
    lane = lane_for(m, sid, args.lane)
    t = now()
    n, doc_id = take(path, t)
    subject = (args.subject or (lane or {}).get('name') or '').strip()
    # The session writes its detail before it knows the number (« Réponds « Qn : 1 » ») : the PM reads the real one
    # on the board (foreman, 2026-10-19, after correcting two lines by hand).
    question = PLACEHOLDER.sub(f'Q{n}', NUMBER_PREFIX.sub('', args.title).strip())
    label = me.get('title') or None
    when = f'{t:%d/%m} à {t.hour} h {t:%M}'
    doc = {
        'createdAt': t.isoformat(), 'decision': None, 'detail': PLACEHOLDER.sub(f'Q{n}', (args.detail or '').strip()),
        'kind': args.kind,
        'lane': (lane or {}).get('id'), 'resolvedAt': None, 'sessionId': sid, 'sessionLabel': label,
        'status': 'open', 'target': None, 'title': f'Q{n} · ' + (f'{subject} : ' if subject else '') + question,
        'trigger': f'posée par la session « {label} », {when}' if label else f'posée par une session du Studio, {when}',
    }
    if args.rattacher:
        # A question asked by a scheduled pass (the ingestion, the weekly conflicts pass): the routine's own session is
        # one the PM never opens (PM, 2026-11-10). It goes to « <Projet> · Conflits Studio » when that session exists,
        # else to no session; the routine still takes the number in its Studio's register.
        # The Studio is the register's (the mirror's folder), not the routine's working folder.
        studio = next((x for x in m.get('dossiers') or [] if isinstance(x, str)), None) or cwd
        cible = conflicts_session(studio) if args.rattacher == 'conflits' else None
        doc['sessionId'], doc['sessionLabel'] = (cible['id'], cible['title']) if cible else (None, None)
        doc['trigger'] = (f"posée par une tâche planifiée du Studio, {when}, à traiter dans « {cible['title']} »" if cible
                          else f"posée par une tâche planifiée du Studio, {when}")
    if args.arret:
        # A line for a stopped session: the mark keeps the source from settling it (see settle_from_source).
        doc['arret'] = args.arret
        doc['trigger'] = f"session « {label or sid} » arrêtée {STOP_FR[args.arret]}, relevé le {when}"
    # One call: the line goes into the mirror now, under the lock (no board, no pending file, no message).
    with Lock(path):
        mirror = read_json(path, {}) or {}
        mirror['attentes'] = [a for a in mirror.get('attentes') or [] if not (isinstance(a, dict) and a.get('doc') == doc_id)] \
            + [waiting(doc, mirror.get('lanes') or [], doc_id)]
        mirror['misAJour'] = t.isoformat()
        write_mirror(path, mirror)
    if args.rattacher == 'conflits' and not doc['sessionId']:
        print("Pas de session « <Projet> · Conflits Studio » dans ce Studio : la question n'est rattachée à aucune session.")
    print(f'{doc["title"]}\nNuméro pris, la question est dans Mon Studio (écrit dans ~/Mon Studio, c\'est voulu). '
          f'Pose-la maintenant dans la langue du PM (le français par défaut), en commençant par « Q{n} · », dans ton '
          f'message, ou dans le menu de choix ou l\'encadré de fin de tour si tu en ouvres un. Rien d\'autre à faire.')
    return 0


def conflicts_session(cwd):
    """{'id', 'title'} of the session « <Projet> · Conflits Studio » of the Studio holding `cwd` (a title that starts
    so counts, « … (rattrapage) »), the most recently written; None when there is none."""
    try:
        nom = parc().nom_projet(cwd)
    except Exception:
        return None
    norm = lambda s: ' '.join(unicodedata.normalize('NFC', s or '').casefold().split())
    voulu = norm(f'{nom} · Conflits Studio')
    trouves = []
    for path in APP_SESSIONS.glob('*/*/*.json'):
        c = read_json(path)
        sid = c.get('sessionId') if isinstance(c, dict) else None
        if isinstance(sid, str) and SAFE_ID.match(sid) and not c.get('isArchived') \
                and norm(c.get('title')).startswith(voulu):
            try:
                trouves.append((path.stat().st_mtime, sid, c.get('title')))
            except OSError:
                continue
    if not trouves:
        return None
    _, sid, title = max(trouves)
    return {'id': sid, 'title': title}


def own_chantier(args, what, create=False):
    """(session id, chantier of the session) or an error line and None: shared by settle and event. With create (an
    event), a known Studio gets its register now, so a wait on a third party shows in its project view."""
    sid = args.session or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')
    if not sid:
        print(f"Pas d'identifiant de session de l'app : {what} dans ton message au PM.")
        return sid, None
    me = card(sid)
    cwd = me.get('cwd') or os.getcwd()
    found = chantier_of(sid, cwd) or (open_register(sid, cwd) if create else existing_register(cwd))
    if not found:
        print(f"Cette session n'est d'aucun projet suivi : {what} dans ton message au PM.")
    return sid, found


def cmd_settle(args):
    sid, found = own_chantier(args, 'dis ce qui est réglé')
    if not found:
        return 3
    path, m, _ = found
    n = highest([f'Q{args.number.lstrip("Qq")}'])
    if not n:
        print(f'Numéro illisible : {args.number}', file=sys.stderr)
        return 2
    t = now()
    decision = args.decision.strip()
    # Only an open line this session asked (the PM, 2026-10-21: a number comes back, so a number alone may name
    # another session's question). Anything else is refused, with who asked it and its title.
    open_lines = [a for a in (read_json(path, {}) or {}).get('attentes') or []
                  if isinstance(a, dict) and highest([a.get('titre')]) == n]
    mine = [a for a in open_lines if a.get('sessionId') == sid]
    if len(mine) != 1:
        asked = lambda a: (f'la session « {a.get("sessionLabel") or a["sessionId"]} » ({a["sessionId"]})'
                           if a.get('sessionId') else 'une session d\'avant')
        if not open_lines:
            print(f'Rien soldé : aucune ligne ouverte Q{n} dans ce projet. Les numéros repartent de 1 chaque jour '
                  f'ouvré : vérifie le numéro de ta question. Si le PM a répondu à la question d\'une autre session, '
                  f'transmets-lui ses mots par un message natif, avec le numéro et le titre de la question.')
        elif mine:
            print(f'Rien soldé : Q{n} est ouverte plusieurs fois pour cette session ('
                  + ' ; '.join(f'« {a.get("titre")} »' for a in mine)
                  + f'). Demande au PM laquelle solder.')
        else:
            print(f'Rien soldé : Q{n} n\'a pas été posée par cette session. Ouverte : '
                  + ' ; '.join(f'« {a.get("titre")} », posée par {asked(a)}' for a in open_lines)
                  + f'. Si le PM y a répondu ici, transmets ses mots à cette session par un message natif : '
                    f'« {open_lines[0].get("titre")} : {decision[:120]} »')
        return 4
    a = mine[0]
    title, doc_id, label = a.get('titre'), a.get('doc'), card(sid).get('title') or None
    journal_add(path, {'id': f'settled-{doc_id or f"Q{n}"}-{t:%Y%m%d%H%M%S}', 'at': t.isoformat(), 'type': 'settled',
                       'number': n, 'title': title, 'doc': doc_id, 'sessionId': sid, 'session': label, 'text': decision})
    # One call: the line leaves the mirror now; the PM's words are in the local journal.
    with Lock(path) as lock:
        mirror = read_json(path, {}) or {}
        mirror['attentes'] = [x for x in mirror.get('attentes') or [] if x != a]
        mirror['misAJour'] = t.isoformat()
        write_mirror(path, mirror)
        lock.save(note_held(lock.state(), {n}, t), t)
    print(f'« {title} » soldée : retirée de Mon Studio, les mots du PM sont au journal du projet.')
    return 0


def cmd_event(args):
    sid, found = own_chantier(args, 'annonce-le', create=True)
    if not found:
        return 3
    path, m, _ = found
    me = card(sid)
    lane = lane_for(m, sid, args.lane)
    label = me.get('title') or None
    full = dt.datetime.now().astimezone()
    t = full.replace(microsecond=0)
    suffix = re.sub(r'[^A-Za-z0-9]', '', sid)[-6:]
    doc_id = f'e{full:%Y%m%d%H%M%S}{full.microsecond // 1000:03d}-{suffix}'
    text = (f'{label} : ' if label else '') + args.title.strip() + (f'\n{args.detail.strip()}' if args.detail else '')
    doc = {'at': t.isoformat(), 'kind': args.type, 'text': text, 'lane': (lane or {}).get('id'),
           'sessionId': sid, 'sessionLabel': label}
    entry = {'id': doc_id, 'at': t.isoformat(), 'type': args.type, 'sessionId': sid, 'session': label,
             'text': args.title.strip()}
    if args.detail:
        entry['detail'] = args.detail.strip()
    journal_add(path, entry)   # one call: the project view reads the local journal (a « blocked » waits on a third party)
    print(f'Événement noté ({args.type}) au journal du projet, dans ~/Mon Studio (c\'est voulu). Rien d\'autre à faire.')
    return 0


def cmd_init(args):
    """The project of this session gets a mirror (its name, its folder, this session as its
    anchor), hence its counter and its project view. Refuses when a mirror already covers the folder."""
    sid = args.session or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID')
    if not sid:
        print("Pas d'identifiant de session de l'app : lance-le depuis une session du projet.")
        return 3
    folder = os.path.normpath(os.path.expanduser(args.folder or card(sid).get('cwd') or os.getcwd()))
    if folder == os.path.normpath(str(HOME)):
        print('Le dossier personnel contiendrait tous les projets : ouvre la session dans le dossier du projet.')
        return 2
    found = chantier_of(sid, folder)
    if found:
        print(f'Ce dossier a déjà son projet : « {found[1]["chantier"]} ».')
        return 0
    name = (args.name or os.path.basename(folder)).strip()
    stem = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-') or 'projet'
    path = CHANTIERS / f'{stem}.json'
    if path.exists():
        print(f'Un projet porte déjà ce nom ({path.name}) : donne un autre nom (--name).')
        return 2
    CHANTIERS.mkdir(parents=True, exist_ok=True)
    with Lock(path):
        write_mirror(path, {'chantier': name, 'studio': name, 'sessionId': sid, 'dossiers': [folder], 'registre': True,
                            'misAJour': now().isoformat(), 'attentes': [], 'lanes': []})
    print(f'Projet « {name} » créé pour {folder} : ses questions prennent leurs numéros, sa vue s\'ouvre depuis Mon Studio.')
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog='question.py', description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('hook')
    sub.add_parser('notices')
    t = sub.add_parser('take')
    t.add_argument('chantier', nargs='?')
    n = sub.add_parser('new')
    n.add_argument('--kind', choices=KINDS, default='decision')
    n.add_argument('--title', required=True)
    n.add_argument('--subject')
    n.add_argument('--detail')
    n.add_argument('--lane')
    n.add_argument('--session')
    n.add_argument('--arret', choices=sorted(STOP_FR))
    n.add_argument('--rattacher', choices=('conflits', 'aucune'),
                   help="pour une tâche planifiée : la ligne va à la session « <Projet> · Conflits Studio », ou à aucune")
    r = sub.add_parser('settle')
    r.add_argument('number')
    r.add_argument('--decision', required=True)
    r.add_argument('--session')
    e = sub.add_parser('event')
    e.add_argument('--type', choices=EVENT_TYPES, default='progress')
    e.add_argument('--title', required=True)
    e.add_argument('--detail')
    e.add_argument('--lane')
    e.add_argument('--session')
    i = sub.add_parser('init')
    i.add_argument('--name')
    i.add_argument('--folder')
    i.add_argument('--session')
    args = p.parse_args(argv)
    if args.cmd == 'hook':
        try:
            hook()
        except Exception:  # a hook never stops a session from starting
            pass
        return 0
    if args.cmd == 'notices':
        try:
            lines = notices()
        except Exception:  # a hook never stops a turn
            lines = []
        if lines:
            print('\n'.join(lines))
        return 0
    return {'init': cmd_init, 'take': cmd_take, 'new': cmd_new, 'settle': cmd_settle, 'event': cmd_event}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
