#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reader and writer of a Studio's conflict register, `projet/conflits.md`, without LLM nor dependency.

The format is the shared one (« Format du registre des conflits ») that `/studio:auto-ingest` writes too: one level-3
heading per case, then fixed `- **Champ** : valeur` lines. Every regular expression below is copied from it, letter
for letter. Nothing here may write anything that format does not read back:

- an id is never reused: new id = the largest C<n> found in the file (readable or not) + 1, C1 for an empty file;
- a new case is only appended at the end of the file; an existing case is never rewritten nor moved, except its
  `État` line;
- a case whose required field is missing or malformed is reported as unreadable, the others are still read;
- dates are DD/MM/YYYY in the file; a reader converts to ISO itself when it needs to.

One line outside any case, « Dernier passage : JJ/MM/AAAA », right under the title, tells the incremental re-read
(`conflits.py releve --incremental`) where to start. The format ignores text outside a case, so other readers skip it.

Used by `conflits.py` (the /cockpit:conflits skill) and, read-only, by Mon Studio's project view (copied next to
projets.py in ~/Mon Studio/.parc as registre_conflits.py).
"""
import contextlib
import datetime as dt
import os
import pathlib
import re
import time

# The one price list of the plugin, $ per million tokens: input, output, cache read (a cache write is input x 1.25).
# Anthropic list prices checked on 2026-11-15: Opus 5.5 4 / 20, Sonnet 5.5 2 / 10, Haiku 5.5 0.10 / 0.50 (prompts of
# 100,000 tokens or fewer, which every cockpit call stays under), cache reads at a twentieth of the input for Opus and
# Sonnet, a tenth for Haiku. conflits.py and Mon Studio's install.py both read it from here.
PRIX = {'opus': (4.0, 20.0, 0.20), 'sonnet': (2.0, 10.0, 0.10), 'haiku': (0.10, 0.50, 0.01)}
TITRE = '# Registre des conflits'
CHOIX = ('remplacer', 'à confirmer avec le client', 'simple discussion')
OPTIONS = ' · '.join(CHOIX)
CHEMIN = pathlib.Path('projet') / 'conflits.md'

# The format's expressions, verbatim (« Règles de lecture »).
CAS = re.compile(r'^### (C[1-9][0-9]*) · (.+)$')
DETECTE = re.compile(r'^- \*\*Détecté le\*\* : (\d{2}/\d{2}/\d{4})$')
ANCIENNE = re.compile(r'^- \*\*Ancienne valeur\*\* : (.+) \(source : (.+), (\d{2}/\d{2}/\d{4})\)$')
NOUVELLE = re.compile(r'^- \*\*Nouvelle valeur\*\* : (.+) \(source : (.+), (\d{2}/\d{2}/\d{4})\)$')
COMMUNIQUE = re.compile(r'^- \*\*Déjà communiqué au client\*\* : (oui|non)$')
OPTIONS_LIGNE = re.compile(r'^- \*\*Options\*\* : (.+)$')
ETAT = re.compile(r'^- \*\*État\*\* : (ouvert|tranché le (\d{2}/\d{2}/\d{4}) par (.+) : '
                  r'(remplacer|à confirmer avec le client|simple discussion))$')

# What starts a case or a field, to tell a malformed line from an unknown one.
TITRE_CAS = re.compile(r'^### C(\d+)\b')
TITRE_QUELCONQUE = re.compile(r'^#{1,6} ')
CHAMPS = {'Détecté le': DETECTE, 'Ancienne valeur': ANCIENNE, 'Nouvelle valeur': NOUVELLE,
          'Déjà communiqué au client': COMMUNIQUE, 'Options': OPTIONS_LIGNE, 'État': ETAT}
CHAMP = re.compile(r'^- \*\*(.+?)\*\* : ')

# The queue (file d'attente) shared with /studio:auto-ingest (agreed with it on 2026-11-10): the open cases of the
# register, with optional fields between « Options » and « État ». The format ignores unknown fields, so a reader that
# does not know them still reads the case. A case without « Niveau » is a real decision (never pre-answered without an
# opinion); a « Raisons » line makes it one whatever « Niveau » says; « Recommandé » absent or unknown is « à confirmer
# avec le client ».
FACULTATIFS = ('Niveau', 'Recommandé', 'Pourquoi', 'Contexte', 'Raisons', 'Ajouté par', 'Réponse', 'Tranché dans')
# « Réponse » (the PM's own words, when richer than the choice) and « Tranché dans » (the Studio file where the PM
# settled it): written by the reprise of decisions settled by hand before the tool (PM, Q12, 2026-11-15).
NIVEAUX = {'évident': 'evident', 'evident': 'evident', 'arbitrage': 'arbitrage'}
RAISONS = ('texte parti au client', 'argent ou contrat', 'source seulement orale', 'savoir propre au PM')
AJOUTE_PAR = ('ingestion auto', 'passe hebdomadaire', 'rattrapage', 'relecture', 'reprise')
DIR_CONFLITS = pathlib.Path('projet') / '.conflits'
SEUILS = {'relance_cas': 10, 'relance_jours': 14}     # PM, 2026-11-10: a reminder from 10 open cases or 14 days
DERNIER_PASSAGE = re.compile(r'^Dernier passage : (\d{2}/\d{2}/\d{4})$')
DATE = re.compile(r'^\d{2}/\d{2}/\d{4}$')


# Every code shown to the PM is followed by « · » and a short title (PM, 2026-11-10): a case (C3), a decision, a rule,
# a question, a story, a ticket. One definition for the conflicts skill and for Mon Studio's tab.
# A Studio code (PRJ-1, PRJB-46), a one-letter code (C3, D2, T5, S1, E1.2) or « Q-008 ». Not V1, V2: a
# product version, plain words for the PM.
CODE = re.compile(r'(?<![\w-])((?:[A-Z]{1,6}-\d{1,4})|(?:[A-UW-Z]\d{1,4}(?:\.\d{1,3})?)|(?:Q-?\d{1,4}))(?![\w-])')
SANS_TITRE = 'titre introuvable dans le Studio'
_TITRE_CODE = re.compile(r'^#{2,4}\s+~*([A-Z]{1,6}-\d{1,4})~*\s*[:·—–-]+\s*(.+?)\s*$')
_PUCE_CODE = re.compile(r'^[-*+]\s+\*\*~*([A-Z]{1,6}-\d{1,4})~*\*\*\s*[:·—–-]?\s*(.+)$')


def codes_nus(texte):
    """The codes of `texte` not followed by « · » and a title: what the PM must never see alone."""
    return [m.group(1) for m in CODE.finditer(texte or '') if not texte[m.end():m.end() + 3].startswith(' · ')]


def etiqueter(texte, titres, defaut=None):
    """Adds « · <title> » after each code of `texte` that has none: its title when known, else `defaut` (a code
    left bare only when `defaut` is None)."""
    def un(m):
        code = m.group(1)
        if m.string[m.end():m.end() + 3].startswith(' · '):
            return code
        titre = (titres or {}).get(code) or defaut
        return f'{code} · {titre}' if titre else code
    return CODE.sub(un, texte or '')


# What the PM is shown carries no code at all (PM, 2026-11-10, replacing « code · title »): no Studio code (decision,
# rule, question, story, ticket, ADR), no case id, no internal id, no class or cause letter. Codes stay in the register
# and in the markings written in the Studio, for traceability, and are given to the PM only when he asks.
CODES_PM = re.compile(r"(?<![\w-])(?:[A-Z]{1,6}-\d{1,4}|[A-UW-Z]\d{1,4}(?:\.\d{1,3})?|Q-?\d{1,4})(?![\w-])"
                      r"|(?<![\w'’-])(?<!\ble )(?<!\bdu )(?<!\bau )(?<!\bLe )(?<!\bDu )(?<!\bAu )(?<!\bun )(?<!\bUn )(?<!\bce )"
                      r"(?<!\bCe )PM(?![\w'’-])"
                      r"|(?<![\w'’-])(?:M|A|B|C|D|E|F|G|H|I)(?![\w'’-])")
# « le PM », « du PM », « au PM » name the person, the project manager, not the class « PM » (seen on 2026-11-10: five
# judgments of a real Studio refused for « le PM a tranché »).


def codes_pour_le_pm(texte):
    """The codes, ids and class letters of a text meant for the PM: it must give none."""
    return [m.group(0) for m in CODES_PM.finditer(texte or '')]


def sans_codes(texte, titres=None):
    """A text for the PM: « PRJ-2 · Remise relevée » and « PRJ-2 » (title known) become « Remise relevée »; a code
    without a known title is dropped, with the brackets or commas it leaves."""
    def un(m):
        suite = m.string[m.end():m.end() + 3]
        if suite.startswith(' · '):
            return '\x00'                     # its title follows: keep the title only
        return (titres or {}).get(m.group(1)) or ''
    t = CODE.sub(un, texte or '')
    t = t.replace('\x00 · ', '').replace('\x00', '')
    # A Studio title may itself carry a code (« Remplacement : décision prise (PRJ-74) »): what a substitution
    # brought back goes too (seen on a real Studio, 2026-11-10).
    t = CODE.sub('', t)
    t = re.sub(r'\(\s*[,;:/]*\s*\)', '', t)
    t = re.sub(r'\(\s*[,;/]\s*', '(', t)
    t = re.sub(r'\s*[,;/]\s*\)', ')', t)
    t = re.sub(r'(?:,\s*){2,}', ', ', t)
    t = re.sub(r'«\s*»', '', t)
    t = re.sub(r'\s+([,.;:)])', r'\1', t)
    t = re.sub(r'([(«])\s+', r'\1', t)
    t = re.sub(r'\s+(?:et|ou)\s*(?=[,.;)]|$)', '', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' ,;·—–-')
    return t


def chemin_lisible(rel):
    """A Studio path as the PM reads it, without the codes its folder and file names carry:
    « backlog/EPR-001-socle/USR-004-emails.md » becomes « backlog › socle › emails »."""
    parts = []
    for p in str(rel or '').replace('\\', '/').split('/'):
        p = re.sub(r'\.(md|txt|json|html?|pdf|docx?)$', '', p)
        p = re.sub(r'(?<![A-Za-z])[A-Z]{1,6}-\d{1,4}(?=$|[-_ ])', '', p)
        p = re.sub(r'^[-_ ]*\d{3}-', '', p)
        p = ' '.join(re.sub(r'[-_]+', ' ', p).split())
        if p:
            parts.append(p)
    return ' › '.join(parts)


def titre_court(texte, n=8):
    mots_ = re.sub(r'[*_`~✅❓🟢🔴⚠️➡️]', ' ', texte or '').split()
    return ' '.join(mots_[:n]).rstrip(' :;,.—–-') or ''


def titres_du_studio(studio):
    """{code: short title} from the Studio's stores (decisions, rules, questions, their sub-folder copies too), read
    only, for the codes a PM is shown. A store that cannot be read gives nothing."""
    titres = {}
    racine = pathlib.Path(studio) / 'projet'
    if not racine.is_dir():
        return titres
    for chemin, sous, fichiers in os.walk(racine):
        sous[:] = [d for d in sous if not d.startswith('.') and not d.startswith('rattrapage') and d != 'pilotage']
        for f in fichiers:
            if not f.startswith(('decisions-log', 'regles-metier', 'questions-ouvertes')) or not f.endswith('.md'):
                continue
            try:
                lignes = pathlib.Path(chemin, f).read_text(encoding='utf-8').splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for l in lignes:
                m = _TITRE_CODE.match(l) or _PUCE_CODE.match(l)
                if m:
                    titres.setdefault(m.group(1), titre_court(m.group(2)))
    return titres


def jjmmaaaa(jour=None):
    """A date as the register writes it: DD/MM/YYYY (today by default; accepts a date or an ISO string)."""
    if jour is None:
        jour = dt.date.today()
    if isinstance(jour, str):
        if DATE.match(jour):
            return jour
        jour = dt.date.fromisoformat(jour[:10])
    return jour.strftime('%d/%m/%Y')


def iso(jjmmaaaa_texte):
    """DD/MM/YYYY -> YYYY-MM-DD, or None."""
    if not isinstance(jjmmaaaa_texte, str) or not DATE.match(jjmmaaaa_texte):
        return None
    j, m, a = jjmmaaaa_texte.split('/')
    try:
        return dt.date(int(a), int(m), int(j)).isoformat()
    except ValueError:
        return None


def _lignes(texte):
    return [l.rstrip('\r\n') for l in texte.splitlines()]


def lire(texte):
    """The register's cases: {'cas': [...], 'illisibles': [...], 'dernier_passage': 'JJ/MM/AAAA' | None, 'max_id': n}.

    A case: {'id', 'n', 'sujet', 'detecte', 'ancienne': {texte, source, date}, 'nouvelle': {...}, 'communique': bool,
    'etat': 'ouvert' | 'tranché', 'tranche': None | {date, par, choix}, 'ligne', 'file': lire_file(...)}
    (ligne: its heading, from 1).
    An unreadable case: {'id', 'sujet', 'ligne', 'erreurs'}. Unknown fields and text outside cases are ignored."""
    lignes = _lignes(texte or '')
    sortie = {'cas': [], 'illisibles': [], 'dernier_passage': None, 'max_id': 0}
    courant = None

    def fermer():
        if courant is None:
            return
        erreurs = [f'champ « {nom} » absent' for nom in CHAMPS if nom not in courant['champs']]
        erreurs = courant['erreurs'] + erreurs
        if erreurs or not courant.get('titre_ok'):
            if not courant.get('titre_ok'):
                erreurs.insert(0, 'titre hors format (« ### C<n> · <sujet> »)')
            sortie['illisibles'].append({'id': courant['id'], 'sujet': courant['sujet'], 'ligne': courant['ligne'],
                                         'erreurs': erreurs})
            return
        c = courant['champs']
        etat = c['État']
        cas = {'id': courant['id'], 'n': int(courant['id'][1:]), 'sujet': courant['sujet'], 'ligne': courant['ligne'],
               'detecte': c['Détecté le'].group(1),
               'ancienne': dict(zip(('texte', 'source', 'date'), c['Ancienne valeur'].groups())),
               'nouvelle': dict(zip(('texte', 'source', 'date'), c['Nouvelle valeur'].groups())),
               'communique': c['Déjà communiqué au client'].group(1) == 'oui',
               'etat': 'ouvert' if etat.group(1) == 'ouvert' else 'tranché',
               'tranche': None if etat.group(1) == 'ouvert' else
               {'date': etat.group(2), 'par': etat.group(3), 'choix': etat.group(4)}}
        cas['file'] = lire_file(courant['extra'])
        sortie['cas'].append(cas)

    for i, ligne in enumerate(lignes, 1):
        if TITRE_QUELCONQUE.match(ligne):
            fermer()
            courant = None
            m_num = TITRE_CAS.match(ligne)
            if not m_num:
                continue
            sortie['max_id'] = max(sortie['max_id'], int(m_num.group(1)))
            m = CAS.match(ligne)
            courant = {'id': m.group(1) if m else 'C' + m_num.group(1), 'sujet': m.group(2) if m else ligne[4:].strip(),
                       'ligne': i, 'champs': {}, 'erreurs': [], 'titre_ok': bool(m), 'extra': {}}
            continue
        if courant is None:
            m = DERNIER_PASSAGE.match(ligne)
            if m:
                sortie['dernier_passage'] = m.group(1)
            continue
        m = CHAMP.match(ligne)
        if m and m.group(1) in FACULTATIFS and m.group(1) not in courant['extra']:
            courant['extra'][m.group(1)] = _une_ligne(ligne[m.end():])
            continue
        if not m or m.group(1) not in CHAMPS or m.group(1) in courant['champs']:
            continue                       # unknown field, free text, or a repeated field: ignored
        trouve = CHAMPS[m.group(1)].match(ligne)
        if trouve:
            courant['champs'][m.group(1)] = trouve
        else:
            courant['champs'][m.group(1)] = None
            courant['erreurs'].append(f'champ « {m.group(1)} » hors format')
    fermer()
    for x in sortie['illisibles']:
        x['erreurs'] = [e for e in x['erreurs'] if e]
    return sortie


def lire_file(extra):
    """The queue fields of a case, normalized: {'niveau': 'evident'|'arbitrage', 'recommande': a choice or None,
    'pourquoi', 'contexte', 'raisons': [...], 'ajoute_par'}. No « Niveau », or any reason: 'arbitrage'."""
    extra = extra or {}
    raisons = [r for r in (x.strip() for x in re.split(r'\s*;\s*', extra.get('Raisons') or '')) if r]
    niveau = NIVEAUX.get((extra.get('Niveau') or '').strip().lower(), 'arbitrage')
    if raisons:
        niveau = 'arbitrage'
    recommande = (extra.get('Recommandé') or '').strip()
    return {'niveau': niveau, 'recommande': recommande if recommande in CHOIX else None,
            'pourquoi': extra.get('Pourquoi') or '', 'contexte': extra.get('Contexte') or '', 'raisons': raisons,
            'ajoute_par': extra.get('Ajouté par') or '',
            **{k: extra[n] for k, n in (('reponse', 'Réponse'), ('tranche_dans', 'Tranché dans')) if extra.get(n)}}


def lignes_file(file):
    """The optional queue lines of a case, in the agreed order, for what `file` gives (nothing for an empty dict)."""
    if not file:
        return []
    sortie = []
    niveau = file.get('niveau')
    if niveau in ('evident', 'arbitrage'):
        sortie.append(f"- **Niveau** : {'évident' if niveau == 'evident' else 'arbitrage'}")
    if file.get('recommande') in CHOIX:
        sortie.append(f"- **Recommandé** : {file['recommande']}")
    for cle, nom in (('pourquoi', 'Pourquoi'), ('contexte', 'Contexte')):
        if _une_ligne(file.get(cle)):
            sortie.append(f"- **{nom}** : {_une_ligne(file[cle])}")
    if file.get('raisons'):
        sortie.append(f"- **Raisons** : {' ; '.join(_une_ligne(r) for r in file['raisons'])}")
    if _une_ligne(file.get('ajoute_par')):
        sortie.append(f"- **Ajouté par** : {_une_ligne(file['ajoute_par'])}")
    for cle, nom in (('reponse', 'Réponse'), ('tranche_dans', 'Tranché dans')):
        if _une_ligne(file.get(cle)):
            sortie.append(f"- **{nom}** : {_une_ligne(file[cle])}")
    return sortie


def lire_fichier(chemin):
    """lire() on a file; an absent file is a register without cases."""
    try:
        texte = pathlib.Path(chemin).read_text(encoding='utf-8')
    except FileNotFoundError:
        texte = ''
    return lire(texte)


def chemin_du_studio(studio):
    return pathlib.Path(studio) / CHEMIN


def ouverts(studio):
    """The open cases of a Studio's register, and its unreadable ones."""
    r = lire_fichier(chemin_du_studio(studio))
    return {'ouverts': [c for c in r['cas'] if c['etat'] == 'ouvert'], 'illisibles': r['illisibles'],
            'dernier_passage': r['dernier_passage'], 'tous': r['cas']}


# ---------- writing

def _une_ligne(texte):
    return ' '.join(str(texte or '').split())


def _valeur(v):
    return f"{_une_ligne(v['texte'])} (source : {_une_ligne(v['source'])}, {jjmmaaaa(v['date'])})"


def bloc_du_cas(cid, sujet, ancienne, nouvelle, communique, detecte=None, etat='ouvert', file=None):
    """The lines of one case, exactly as the format lays them out; the queue's optional fields between « Options »
    and « État »."""
    return [f'### {cid} · {_une_ligne(sujet)}',
            f'- **Détecté le** : {jjmmaaaa(detecte)}',
            f'- **Ancienne valeur** : {_valeur(ancienne)}',
            f'- **Nouvelle valeur** : {_valeur(nouvelle)}',
            f"- **Déjà communiqué au client** : {'oui' if communique else 'non'}",
            f'- **Options** : {OPTIONS}'] + lignes_file(file) + [f'- **État** : {etat}']


class Illisible(OSError):
    """A file that exists but cannot be read as UTF-8 text (another encoding, a Drive file not downloaded, a refusal):
    it is never written to."""


class Change(RuntimeError):
    """The file changed between the read and the write (another writer, the night ingestion): nothing written."""


VERROU_S = 10          # how long a writer waits for the lock
VERROU_MORT_S = 120    # a lock older than this is left over by a writer that died


def empreinte(chemin):
    try:
        st = os.stat(chemin)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


def lire_existant(chemin):
    """(text, fingerprint): (None, None) when the file is absent; Illisible when it exists and cannot be read."""
    chemin = pathlib.Path(chemin)
    try:
        emp = empreinte(chemin)
        if emp is None:
            return None, None
        if chemin.is_dir():
            raise Illisible(f'{chemin} est un dossier')
        with open(chemin, encoding='utf-8', newline='') as f:
            return f.read(), emp
    except FileNotFoundError:
        return None, None
    except Illisible:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise Illisible(f'{chemin} : {exc}') from exc


@contextlib.contextmanager
def verrou(chemin):
    """An exclusive lock next to the file (`.<name>.lock`), waited for VERROU_S seconds at most. A leftover `.tmp` of an
    earlier version is removed."""
    chemin = pathlib.Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    lock = chemin.with_name('.' + chemin.name + '.lock')
    fin = time.time() + VERROU_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.stat(lock).st_mtime > VERROU_MORT_S:
                    os.unlink(lock)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > fin:
                raise Change(f'{chemin} : un autre outil écrit dedans (verrou {lock.name})')
            time.sleep(0.1)
    try:
        tmp = chemin.with_name('.' + chemin.name + '.tmp')
        if tmp.exists():
            tmp.unlink()
        yield
    finally:
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass


def _sur_place(chemin, texte, attendu):
    """Writes `texte` into the same file (same identity for the Drive), after checking it did not change."""
    if empreinte(chemin) != attendu:
        raise Change(f'{chemin} a changé depuis sa lecture')
    if attendu is None:
        with open(chemin, 'x', encoding='utf-8', newline='') as f:
            f.write(texte)
        return
    with open(chemin, 'r+', encoding='utf-8', newline='') as f:
        f.write(texte)
        f.truncate()


def modifier(chemin, fonction):
    """Under the lock: reads the file, `fonction(text or None)` gives the new text (None: nothing to write), writes it
    in place if the file did not change meanwhile. Returns what `fonction` returned. Illisible, Change."""
    with verrou(chemin):
        texte, emp = lire_existant(chemin)
        nouveau = fonction(texte)
        if nouveau is not None and nouveau != texte:
            _sur_place(chemin, nouveau, emp)
        return nouveau


def ajouter_fin(chemin, fonction):
    """Under the lock: `fonction(text or None)` gives what to append (None: nothing), appended in append mode, never a
    rewrite of what is there. Returns the appended text."""
    with verrou(chemin):
        texte, emp = lire_existant(chemin)
        ajout = fonction(texte)
        if not ajout:
            return None
        if empreinte(chemin) != emp:
            raise Change(f'{chemin} a changé depuis sa lecture')
        with open(chemin, 'a' if emp else 'x', encoding='utf-8', newline='') as f:
            f.write(ajout)
        return ajout


def _texte(chemin):
    return lire_existant(chemin)[0]


def _fin_de_ligne(texte):
    return '\r\n' if texte and '\r\n' in texte else '\n'


def trouver(texte, ancienne, nouvelle, sujet=None, par_sources=False):
    """An existing case with the same old and new value and sources (and subject, when given), or None: a re-run
    never registers a case twice."""
    for c in lire(texte or '')['cas']:
        if par_sources:
            # The case's identity: where the old and the new value come from, and when; not their wording.
            # A value dated by its file (« date inconnue, celle du fichier ») keeps its identity when the file changes:
            # the same case as /studio:auto-ingest sees it (agreed on 2026-11-10).
            # Its date then gives no identity: its wording does (two undated conflicts between the same files are two
            # cases).
            if all(_une_ligne(c[k]['source']) == _une_ligne(v['source'])
                   and ((_date_du_fichier(c[k]['texte']) and _date_du_fichier(v['texte'])
                         and _sans_date(c[k]['texte']) == _sans_date(v['texte']))
                        or (not (_date_du_fichier(c[k]['texte']) and _date_du_fichier(v['texte']))
                            and c[k]['date'] == jjmmaaaa(v['date'])))
                   for k, v in (('ancienne', ancienne), ('nouvelle', nouvelle))):
                return c
            continue
        if (_une_ligne(c['ancienne']['source']) == _une_ligne(ancienne['source'])
                and _une_ligne(c['nouvelle']['source']) == _une_ligne(nouvelle['source'])
                and _une_ligne(c['ancienne']['texte']) == _une_ligne(ancienne['texte'])
                and _une_ligne(c['nouvelle']['texte']) == _une_ligne(nouvelle['texte'])
                and (sujet is None or _une_ligne(c['sujet']) == _une_ligne(sujet))):
            return c
    return None


SUFFIXE_FICHIER = '(date inconnue, celle du fichier)'


def _date_du_fichier(texte):
    return _une_ligne(texte).endswith(SUFFIXE_FICHIER)


def _sans_date(texte):
    t = _une_ligne(texte)
    return t[:-len(SUFFIXE_FICHIER)].strip() if t.endswith(SUFFIXE_FICHIER) else t


def ajouter(chemin, sujet, ancienne, nouvelle, communique, detecte=None, par_sources=False, file=None, etat='ouvert'):
    """Appends a new case at the end of the register (created with its title when absent) and returns its id: open,
    or already settled when `etat` is a full « tranché le … par … : … » (the reprise of hand-made decisions).
    The same case already there (same values and sources): nothing written, its id returned. Raises ValueError when
    the case would not read back as written (a value on several lines, a date out of format)."""
    lignes_cas = {}

    def suite(texte):
        deja = trouver(texte, ancienne, nouvelle, None if par_sources else sujet, par_sources)
        if deja:
            lignes_cas['id'] = deja['id']
            return None
        cid = f"C{lire(texte or '')['max_id'] + 1}"
        lignes = bloc_du_cas(cid, sujet, ancienne, nouvelle, communique, detecte, etat=etat, file=file)
        relu = lire('\n'.join(lignes) + '\n')
        if relu['illisibles'] or len(relu['cas']) != 1 \
                or _une_ligne(relu['cas'][0]['ancienne']['texte']) != _une_ligne(ancienne['texte']) \
                or _une_ligne(relu['cas'][0]['nouvelle']['texte']) != _une_ligne(nouvelle['texte']):
            raise ValueError(f'cas illisible une fois écrit : {sujet!r}')
        lignes_cas['id'] = cid
        if texte is None:
            return TITRE + '\n\n' + '\n'.join(lignes) + '\n'
        nl = _fin_de_ligne(texte)
        debut = '' if texte.endswith(('\n', '\r')) or not texte else nl
        if texte.strip():
            debut += nl                  # a blank line before the new heading
        return debut + nl.join(lignes) + nl
    ajouter_fin(chemin, suite)
    return lignes_cas['id']


def _bornes(lignes, cid):
    """(start, end) indexes of case `cid` in `lignes` (end excluded), or None."""
    debut = None
    for i, l in enumerate(lignes):
        if TITRE_QUELCONQUE.match(l.rstrip('\r\n')):
            if debut is not None:
                return debut, i
            m = CAS.match(l.rstrip('\r\n'))
            if m and m.group(1) == cid:
                debut = i
    return (debut, len(lignes)) if debut is not None else None


def changer_etat(chemin, cid, choix=None, par=None, jour=None):
    """Rewrites the `État` line of case `cid`, and only that line, in place and under the lock: « tranché le
    JJ/MM/AAAA par <par> : <choix> », or « ouvert » when `choix` is None (« rouvre C3 »). Returns the new line, or None
    when it was already that. KeyError when the case is absent, ValueError when it has no État line or the choice is
    unknown, Illisible, Change."""
    nouvelle = '- **État** : ' + texte_etat(choix, par, jour)
    resultat = {}

    def changer(texte):
        if texte is None:
            raise KeyError(cid)
        lignes = texte.splitlines(keepends=True)
        bornes = _bornes(lignes, cid)
        if not bornes:
            raise KeyError(cid)
        for i in range(*bornes):
            brute = lignes[i].rstrip('\r\n')
            m = CHAMP.match(brute)
            if m and m.group(1) == 'État':
                if brute == nouvelle:
                    return None
                lignes[i] = nouvelle + lignes[i][len(brute):]
                resultat['ligne'] = nouvelle
                return ''.join(lignes)
        raise ValueError(f'{cid} : pas de ligne État')
    modifier(chemin, changer)
    return resultat.get('ligne')


def texte_etat(choix=None, par=None, jour=None):
    """The value of an `État` line: « ouvert » (choix None), else « tranché le JJ/MM/AAAA par <par> : <choix> ».
    ValueError for an unknown choice, a missing name or anything the format would not read back."""
    if choix is None:
        return 'ouvert'
    if choix not in CHOIX:
        raise ValueError(f'choix inconnu : {choix!r}')
    par = _une_ligne(par)
    if not par:
        raise ValueError('le nom du PM manque')
    valeur = f'tranché le {jjmmaaaa(jour)} par {par} : {choix}'
    if not ETAT.match('- **État** : ' + valeur):
        raise ValueError(f'état hors format : {valeur!r}')
    return valeur


def poser_dernier_passage(chemin, jour=None):
    """Writes « Dernier passage : JJ/MM/AAAA » outside any case, right under the title (the line is replaced when
    present). Creates the register with its title when absent. Never touches a case."""
    ligne = f'Dernier passage : {jjmmaaaa(jour)}'

    def poser(texte):
        if texte is None:
            return TITRE + '\n\n' + ligne + '\n'
        nl = _fin_de_ligne(texte)
        lignes = texte.splitlines(keepends=True)
        dans_un_cas = False
        for i, l in enumerate(lignes):
            brute = l.rstrip('\r\n')
            if TITRE_QUELCONQUE.match(brute):
                dans_un_cas = bool(TITRE_CAS.match(brute))
                continue
            if not dans_un_cas and DERNIER_PASSAGE.match(brute):
                if brute == ligne:
                    return None
                lignes[i] = ligne + l[len(brute):]
                return ''.join(lignes)
        # Not there yet: under the title (or at the top when the file has none), before the first case.
        pos = 0
        for i, l in enumerate(lignes):
            if l.rstrip('\r\n') == TITRE:
                pos = i + 1
                break
        ajout = [nl, ligne + nl] if pos else [ligne + nl, nl]
        if pos and pos < len(lignes) and lignes[pos].strip() == '':
            lignes[pos:pos + 1] = [nl, ligne + nl, lignes[pos]]
        else:
            if pos and pos == len(lignes) and not lignes[-1].endswith(('\n', '\r')):
                lignes[-1] += nl
            lignes[pos:pos] = ajout
        return ''.join(lignes)
    modifier(chemin, poser)
    return ligne


# ---------- what Mon Studio shows: the new cases not seen yet, the reminder (PM, 2026-11-10)
#
# Two small files of the conflicts session, in projet/.conflits/, read here and by Mon Studio, never by the ingestion:
# - vu.json {"vu": <the largest case number the PM has been shown>}: ids are never reused, so a case above it is new;
# - reglages.json {"relance_cas": 10, "relance_jours": 14}: the reminder's thresholds for this Studio.

def _lire_json(chemin):
    import json
    try:
        x = json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return x if isinstance(x, dict) else None


def lire_vu(studio):
    x = _lire_json(pathlib.Path(studio) / DIR_CONFLITS / 'vu.json') or {}
    v = x.get('vu')
    return v if isinstance(v, int) and v >= 0 else 0


def lire_reglages(studio):
    """The reminder's thresholds of this Studio, each a whole number from 1 to 365, else the default."""
    x = _lire_json(pathlib.Path(studio) / DIR_CONFLITS / 'reglages.json') or {}
    return {k: x[k] if isinstance(x.get(k), int) and not isinstance(x.get(k), bool) and 1 <= x[k] <= 365 else d
            for k, d in SEUILS.items()}


def _jour(jjmmaaaa_texte):
    try:
        return dt.date.fromisoformat(iso(jjmmaaaa_texte))
    except (TypeError, ValueError):
        return None


def tranches(texte):
    """The register's journal (PM, Q12, 2026-11-15): every settled case, the most recent first: {'id', 'sujet', 'date'
    (JJ/MM/AAAA), 'par', 'choix', 'reponse' (the PM's own words, when the register keeps them), 'ajoute_par',
    'tranche_dans'}. What was settled, when, by whom; the open cases are not in it."""
    sortie = []
    for c in lire(texte or '')['cas']:
        if not c['tranche']:
            continue
        f = c.get('file') or {}
        sortie.append({'id': c['id'], 'n': c['n'], 'sujet': c['sujet'], 'date': c['tranche']['date'],
                       'par': c['tranche']['par'], 'choix': c['tranche']['choix'], 'reponse': f.get('reponse') or '',
                       'ajoute_par': f.get('ajoute_par') or '', 'tranche_dans': f.get('tranche_dans') or ''})
    sortie.sort(key=lambda x: (iso(x['date']) or '', x['n']), reverse=True)
    return sortie


def etat_du_registre(texte, vu=0, reglages=None, aujourdhui=None):
    """What Mon Studio shows of a register: {'ouverts', 'nouveaux' (open cases above `vu`), 'a_traiter' (open, by
    level), 'jours' (days without a treatment, counted from the last answer or from the oldest open case if it came
    after), 'relance' (True from `relance_cas` open cases, or `relance_jours` days without a treatment), 'raison' (in
    words), 'seuils', 'illisibles'}."""
    r = lire(texte or '')
    seuils = dict(SEUILS, **(reglages or {}))
    aujourdhui = aujourdhui or dt.date.today()
    ouverts = [c for c in r['cas'] if c['etat'] == 'ouvert']
    tranches = [d for d in (_jour(c['tranche']['date']) for c in r['cas'] if c['tranche']) if d]
    detectes = [d for d in (_jour(c['detecte']) for c in ouverts) if d]
    jours = 0
    if ouverts and (tranches or detectes):
        depuis = max(([max(tranches)] if tranches else []) + ([min(detectes)] if detectes else []))
        jours = max(0, (aujourdhui - depuis).days)
    n = len(ouverts)
    raisons = []
    if n and n >= seuils['relance_cas']:
        raisons.append(f"{n} conflit{'s' if n > 1 else ''} à traiter")
    if n and jours >= seuils['relance_jours']:
        raisons.append(f"rien de traité depuis {jours} jours")
    return {'ouverts': n, 'nouveaux': sum(1 for c in ouverts if c['n'] > (vu or 0)),
            'a_traiter': {'evident': sum(1 for c in ouverts if c['file']['niveau'] == 'evident'),
                          'arbitrage': sum(1 for c in ouverts if c['file']['niveau'] == 'arbitrage')},
            'jours': jours, 'relance': bool(raisons), 'raison': ', '.join(raisons), 'seuils': seuils,
            'illisibles': len(r['illisibles']), 'max_id': r['max_id'], 'dernier_passage': r['dernier_passage'],
            'tranches': sum(1 for c in r['cas'] if c['tranche'])}


# ---------- the copy Mon Studio's tab reads (2026-11-18)
#
# The connector that serves Mon Studio's page cannot read the Drive (macOS refuses it): it reads the register from the
# snapshot ~/Mon Studio/.parc/projets-sources.json, refreshed by a hook at a session's start and turn's end, five
# minutes at most often. Right after the first relevé of a real Studio the tab showed no case while the register held
# 19. So every command of conflits.py that writes the register, or what the PM has seen of it, copies them into that
# snapshot at once, without an LLM: the register's text, vu.json, reglages.json and the time of the copy
# (`conflits_copie`, which a refresh read before it never overwrites). Nothing is written when Mon Studio is not
# installed (no ~/Mon Studio/.parc).

INSTANTANE = 'projets-sources.json'


def _dossier_mon_studio(studio):
    """The Studio's key in the snapshot, as projets.dossier_normal makes it (NFC, without the app's worktree)."""
    import unicodedata
    chemin = unicodedata.normalize('NFC', os.path.normpath(os.path.expanduser(str(studio))))
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', chemin)
    return m.group(1) if m else chemin


def copier_dans_mon_studio(studio, maintenant=None):
    """Copies the register of `studio` into Mon Studio's snapshot. True when it is there (or Mon Studio is not
    installed: nothing to follow), False when the copy could not be written: the tab then follows within minutes."""
    import json
    base = pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio')) / '.parc'
    if not base.is_dir():
        return True
    try:
        texte = chemin_du_studio(studio).read_text(encoding='utf-8')
    except FileNotFoundError:
        texte = ''
    except (OSError, UnicodeDecodeError):
        return False
    chemin = base / INSTANTANE
    try:
        tout = json.loads(chemin.read_text(encoding='utf-8'))
    except FileNotFoundError:
        tout = None
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(tout, dict) or not isinstance(tout.get('dossiers'), dict):
        tout = {'version': 1, 'ecrit': 0, 'dossiers': {}}
    # Mon Studio keys a Studio as the sessions' folder says it; a plan keeps its real path (/private/var, a symlink):
    # every key of the same real folder gets the copy, else the Studio's own key.
    vrai = os.path.realpath(_dossier_mon_studio(studio))
    cles = [k for k in tout['dossiers'] if os.path.realpath(k) == vrai] or [_dossier_mon_studio(studio)]
    copie = {'conflits': texte, 'conflits_vu': _lire_json(pathlib.Path(studio) / DIR_CONFLITS / 'vu.json'),
             'conflits_reglages': _lire_json(pathlib.Path(studio) / DIR_CONFLITS / 'reglages.json'),
             'conflits_copie': time.time() if maintenant is None else maintenant}
    for cle in cles:
        entree = tout['dossiers'].get(cle)
        tout['dossiers'][cle] = dict(entree if isinstance(entree, dict) else {}, **copie)
    tmp = chemin.with_name(f'{chemin.name}.{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(tout, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, chemin)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True
