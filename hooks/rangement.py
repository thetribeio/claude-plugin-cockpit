#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rangement: the finished one-action sessions are archived without the PM, the dialogue sessions never.

    python3 rangement.py lister [--heures N] [--json]   # dry run: every open session, kept or to archive, and why
    python3 rangement.py calculer                       # writes ~/Mon Studio/.parc/rangement.json (run detached)
    python3 rangement.py hook                           # UserPromptSubmit: keeps the list fresh, proposes once a day
    python3 rangement.py proposer [--apercu]            # the day's proposal for this session (--apercu: noted nowhere)
    python3 rangement.py confirmer [--max N]            # on the PM's yes: the list checked again, noted in ranger.json

The list is computed without a model, from the app's session cards and the transcripts (parc.py). A session is
archived only when ALL of these hold; the first one that fails is the reason it stays:
  - it was started by another session (`spawnedFrom`), or its brief carries the marker « [jetable] »;
  - its title does not start with « 📬 », it is not pinned, not exempted in the app, not moved to the top level;
  - the PM never wrote in it, or, for a session started by another one, Claude answered his last message after it
    (PM, 2026-11-17: « les ranger aussi ») — a session the PM opened himself never moves;
  - its turn is over and its last message asks nothing (no « À trancher », « Encore ouvert », final question mark,
    open menu or app card question, action awaited), and it has no line on the board;
  - no activity for `rangement_heures` hours (24 by default, cockpit.json);
  - it did not work on the ready-to-dev tickets of an epic (backlog plugin, folder `.../<epic>/pret-a-dev/`) whose
    tickets are not yet pushed to Jira, that is `pret-a-dev/05-jira/cles-jira.json` is missing, and it did not use the
    backlog plugin (`backlog:` skill, agent or command) without citing any epic folder (an epic sheet waiting for its
    review, PM 2026-11-25) (PM, 2026-11-24:
    « je garde toutes ces micro-sessions par EPIC tant qu'elles ne sont pas poussées sur JIRA »); the epics of a
    session are the `/pret-a-dev` paths of its tool calls, an epic folder that no longer exists keeps nothing;
  - its work folder has nothing unsaved and is not shared with an open session;
  - no session it started is still under way.
Any doubt (unreadable card, transcript or folder) keeps the session.

Who archives: the PM, from the board (PM, Q5, 2026-11-18). The app refuses `archive_session` in a scheduled run nobody
opened (tried 2026-11-16: « needs a person's approval, and nobody has opened this scheduled run »), and in auto mode it
refuses it too when the order comes from a hook's text handed to an unrelated session (2026-11-18, twice on the same
session: « judged dangerous »). So nothing here hands an order to a session any more: the list is a line of Mon Studio,
« N sessions finies à ranger », whose « Ranger » button copies a request in the PM's words (parc.texte_a_ranger) that he
pastes in a session of his; his message is his consent. Since 0.3.19 (PM, Q7, 2026-11-25) the hook also asks it,
once a day, in a top-level session of the desktop app: a numbered question the session ends its answer with, his « 1 »
being his consent (proposer, confirmer; off with `rangement_propose: false`; `rangement_sans_demander`, off by default,
is the trial of a standing agreement). The sessions of a click or a yes are noted in .parc/ranger.json, and
once archived they move to `rangees` of rangement.json, which the page shows as « Rangées aujourd'hui ». The stopped
sessions the PM gave up (« Abandonner », .parc/abandonnees.json) join the same line. Off with `install.py switch
rangement off` (`"rangement_auto": false`), and silent once Mon Studio is disabled. Nothing here writes
~/.claude/settings.json.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
PARC_SOURCE = PLUGIN_ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py'
MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO', str(pathlib.Path.home() / 'Mon Studio')))
INTERNAL = MON_STUDIO / '.parc'
STATE = INTERNAL / 'cockpit.json'
OUT = INTERNAL / 'rangement.json'
LOCK = INTERNAL / 'rangement.lock'

HEURES_DEFAUT = 24
RECALCUL_S = 3600          # the list is recomputed at most every hour, in the background
RANGER_CLICS = INTERNAL / 'ranger.json'   # written by the connector: the sessions of a « Ranger » click
GARDER_RANGEES_J = 30
MARQUEUR = '[jetable]'
BOITE = '📬'
QUESTION_MOTS = re.compile(r"(?im)^\W*(?:à trancher|a trancher|encore ouvert|to decide|still open)\b")
# Work the session itself says is left: not finished, kept.
# Gestures the message hands to the PM (« Tes gestes », « À toi de jouer »): an action awaited, kept.
GESTES_MOTS = re.compile(r"(?i)\b(?:tes gestes|ton geste|à toi de jouer|a toi de jouer|your move|your next step)\b")
EPIC_FICHE = 'fiche-epic'                # the epic sheet's folder, before any ready-to-dev ticket (PM, 2026-11-25)
EPIC_DOSSIER = 'pret-a-dev'               # the backlog plugin's working folder of an epic
EPIC_POUSSE = pathlib.PurePosixPath('05-jira', 'cles-jira.json')   # written by creer_lot.py once pushed
BACKLOG_SANS_EPIC = '<backlog>'          # backlog plugin used, no epic folder cited: kept, nothing pushed is known
EPIC_CANDIDATS_MAX = 40                   # starts tried per path found: the reading stays bounded
RESTE_MOTS = re.compile(r"(?i)\b(?:encore à faire|reste à faire|il reste à|still to do|left to do)\b")


def lire_json(chemin, defaut=None):
    try:
        return json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaut


def ecrire_atomique(chemin, objet):
    chemin = pathlib.Path(chemin)
    tmp = chemin.with_suffix(chemin.suffix + '.tmp')
    tmp.write_text(json.dumps(objet, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, chemin)


def reglages():
    """(allumé, heures): off when Mon Studio is not installed, disabled, or `rangement_auto` is false."""
    etat = lire_json(STATE)
    if not isinstance(etat, dict) or etat.get('disabled'):
        return False, HEURES_DEFAUT
    h = etat.get('rangement_heures')
    heures = h if isinstance(h, (int, float)) and not isinstance(h, bool) and h >= 1 else HEURES_DEFAUT
    return etat.get('rangement_auto') is not False, heures


def charger_parc():
    spec = importlib.util.spec_from_file_location('parc_rangement', PARC_SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the verdict, on plain facts (tested one guard at a time) --------------------------------------------------

def a_une_question(f, parc=None):
    """True when the last message asks the PM something, or anything says an answer is awaited."""
    texte = f.get('texte') or ''
    if f.get('carte') or f.get('encadre') or f.get('besoin'):
        return True
    if f.get('prio') in (1, 2, 3, 4):
        return True
    if QUESTION_MOTS.search(texte) or GESTES_MOTS.search(texte):
        return True
    paragraphes = [p for p in re.split(r'\n\s*\n', texte) if p.strip()]
    if paragraphes and re.sub(r"[\s*_`)\]»\"”'.]+$", '', paragraphes[-1]).endswith('?'):
        return True
    if parc is not None and texte:
        numerotees, ouverts = parc.a_trancher(texte)
        if numerotees or ouverts:
            return True
    return False


def juger(f, heures, maintenant, parc=None):
    """(True, why) to archive, or (False, why) to keep. `f`: the facts of one open session (see faits)."""
    titre = f.get('titre') or ''
    if titre.lstrip().startswith(BOITE):
        return False, 'titre « 📬 » : boîte du PM'
    if f.get('epinglee'):
        return False, 'épinglée'
    if f.get('exemptee'):
        return False, "exclue de l'archivage dans l'app"
    if not f.get('parent') and not f.get('jetable'):
        return False, 'session de dialogue : ouverte par le PM, sans marqueur « [jetable] »'
    if f.get('detachee'):
        return False, 'remontée au premier niveau (fil rouge)'
    if f.get('humains') is None:
        return False, 'transcript illisible : doute'
    if f['humains'] > 0 and not f.get('parent'):
        return False, f"le PM y a écrit ({f['humains']} message{'s' if f['humains'] > 1 else ''}) : dialogue"
    if f['humains'] > 0 and not f.get('repondu'):
        return False, 'le dernier message du PM attend la réponse de Claude'
    etat = f.get('etat')
    if etat != 'attend':
        return False, {'travaille': 'Claude travaille', 'suspens': 'en suspens (outil, menu ou autorisation)',
                       'erreur': 'arrêtée sur une erreur', 'main': 'un message attend la réponse de Claude'
                       }.get(etat, 'état du tour inconnu : doute')
    if a_une_question(f, parc):
        return False, 'question ou action ouverte pour le PM'
    if RESTE_MOTS.search(f.get('texte') or ''):
        return False, 'son dernier message dit qu’il reste du travail'
    if f.get('au_tableau'):
        return False, 'ligne ouverte au tableau'
    inactif = maintenant - (f.get('activite') or maintenant)
    if inactif < heures * 3600:
        return False, f'active il y a {fmt_h(inactif)} (seuil {fmt_h(heures * 3600)})'
    if 'epic_attente' in f:
        if f['epic_attente'] is None:
            return False, "dossiers d'epic illisibles : doute"
        if f['epic_attente'] == BACKLOG_SANS_EPIC:
            return False, "écriture de backlog (plugin backlog) : rien de poussé dans Jira n'est connu"
        if f['epic_attente']:
            return False, f"tickets de l'epic {f['epic_attente']} pas encore poussés dans Jira"
    if f.get('dossier_sale') is None:
        return False, 'dossier de travail illisible : doute'
    if f['dossier_sale']:
        return False, 'fichiers non enregistrés dans son dossier de travail'
    if f.get('dossier_partage'):
        return False, 'partage son dossier de travail avec une session ouverte'
    if f.get('filles_en_route'):
        return False, 'une session lancée par elle est encore en route'
    origine = f"lancée par « {f['parent_titre']} »" if f.get('parent_titre') else (
        'marquée [jetable]' if f.get('jetable') else 'lancée par une autre session')
    return True, f'{origine}, rapport rendu, rien à trancher, inactive depuis {fmt_h(inactif)}'


def fmt_h(s):
    h = s / 3600
    return f'{round(h)} h' if h < 48 else f'{round(h / 24)} j'


# --- the facts, from the app's cards and the transcripts ----------------------------------------------------------

def humains_et_marqueur(chemin, parc):
    """(messages typed by the PM, brief carries the marker, Claude answered the PM's last message after it), or
    (None, False, False) when the transcript is unreadable.
    The first message is the brief: written by the session that started this one (origin not « human »), or pasted
    by the PM when it carries the marker. Any other human message is the PM talking to the session."""
    humains, premier, marque, repondu = 0, True, False, True
    try:
        with open(chemin, encoding='utf-8') as fh:
            for ligne in fh:
                try:
                    o = json.loads(ligne)
                except ValueError:
                    continue
                if o.get('type') == 'assistant':
                    m = o.get('message') or {}
                    if m.get('model') != '<synthetic>' and parc.texte_de(m.get('content')).strip():
                        repondu = True
                    continue
                if o.get('type') != 'user' or o.get('isMeta'):
                    continue
                contenu = (o.get('message') or {}).get('content')
                if isinstance(contenu, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result'
                                                     for b in contenu):
                    continue
                texte = parc.texte_de(contenu)
                if premier:
                    premier = False
                    marque = MARQUEUR in texte
                    if marque:
                        continue
                if (o.get('origin') or {}).get('kind') == 'human' and texte.strip():
                    humains += 1
                    repondu = False
    except OSError:
        return None, False, False
    return humains, marque, repondu


def _chaines(o):
    """Every string of a tool call's input (nested)."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _chaines(v)
    elif isinstance(o, list):
        for v in o:
            yield from _chaines(v)

def dossiers_epic(texte, cwd):
    """The epic folders (the part before `/pret-a-dev`) named in one string, only those that exist on disk. The path may
    hold spaces and parentheses (Drive): every start that follows a space, a quote or « = » is tried, the earliest
    existing one wins. A relative path is resolved against the session's folder."""
    texte = texte.replace('\\ ', ' ')
    trouves = []
    for m in re.finditer(r'/(' + EPIC_DOSSIER + '|' + EPIC_FICHE + r')(?![\w.-])', texte):
        avant = texte[:m.start()]
        debuts = [0] + [i + 1 for i, c in enumerate(avant) if c in ' \t\n\'"=:,(']
        debuts = [d for d in debuts if d < len(avant)][-EPIC_CANDIDATS_MAX:]
        for d in debuts:
            cand = avant[d:].strip().rstrip('/')
            if not cand:
                continue
            if not cand.startswith('/'):
                if not cwd:
                    continue
                cand = os.path.join(cwd, cand)
            cand = os.path.normpath(cand)
            if os.path.isdir(os.path.join(cand, m.group(1))):
                trouves.append(cand)
                break
    return trouves

def backlog_utilise(o):
    """True when one transcript entry uses the backlog plugin: a `backlog:` skill or agent called by Claude, or a
    `/backlog:` command in a user message (the brief included)."""
    if o.get('type') == 'assistant':
        for b in ((o.get('message') or {}).get('content') or []) if isinstance((o.get('message') or {}).get('content'),
                                                                                list) else []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' and isinstance(b.get('input'), dict):
                v = b['input'].get('skill') if b.get('name') == 'Skill' else (
                    b['input'].get('subagent_type') if b.get('name') == 'Agent' else None)
                if isinstance(v, str) and v.startswith('backlog:'):
                    return True
        return False
    if o.get('type') == 'user':
        contenu = (o.get('message') or {}).get('content')
        textes = [contenu] if isinstance(contenu, str) else [b.get('text') for b in contenu or []
                                                                 if isinstance(b, dict) and b.get('type') == 'text']
        return any(isinstance(t, str) and re.search(r'(?<![\w/])/backlog:[a-z]', t) for t in textes)
    return False


def epic_en_attente(chemin, cwd):
    """The name of an epic folder this session worked in whose tickets are not pushed to Jira yet (no
    `pret-a-dev/05-jira/cles-jira.json`); BACKLOG_SANS_EPIC when it used the backlog plugin without citing any epic
    folder (an epic sheet waiting for its review, PM 2026-11-25: « elles, il ne faut pas y toucher »); '' when there is
    none; None when the transcript is unreadable (doubt)."""
    epics = set()
    backlog = False
    try:
        with open(chemin, encoding='utf-8') as fh:
            for ligne in fh:
                if not backlog and 'backlog:' in ligne:
                    try:
                        backlog = backlog_utilise(json.loads(ligne))
                    except ValueError:
                        pass
                if (EPIC_DOSSIER not in ligne and EPIC_FICHE not in ligne) or '"tool_use"' not in ligne:
                    continue
                try:
                    o = json.loads(ligne)
                except ValueError:
                    continue
                contenu = (o.get('message') or {}).get('content') if o.get('type') == 'assistant' else None
                for b in contenu if isinstance(contenu, list) else []:
                    if isinstance(b, dict) and b.get('type') == 'tool_use':
                        for t in _chaines(b.get('input')):
                            if EPIC_DOSSIER in t or EPIC_FICHE in t:
                                epics.update(dossiers_epic(t, cwd))
    except OSError:
        return None
    for e in sorted(epics):
        if not os.path.isfile(os.path.join(e, EPIC_DOSSIER, *EPIC_POUSSE.parts)):
            return os.path.basename(e)
    return BACKLOG_SANS_EPIC if backlog and not epics else ''

def dossier_sale(chemin):
    """True: uncommitted files; False: clean or no folder of its own; None: unreadable (doubt)."""
    if not chemin or not os.path.isdir(chemin):
        return False
    try:
        r = subprocess.run(['git', '-C', chemin, 'status', '--porcelain'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


def cartes_brutes(parc):
    """sessionId → the app's card (the raw JSON), open sessions only."""
    sortie = {}
    for dossier in parc.dossiers_app():
        for chemin in dossier.glob('local_*.json'):
            o = lire_json(chemin)
            if isinstance(o, dict) and o.get('sessionId') and not o.get('isArchived'):
                sortie[o['sessionId']] = o
    return sortie


def releve(maintenant, parc=None):
    """[(facts, archive?, why)] for every open session that is not a scheduled run, and the board's facts."""
    parc = parc or charger_parc()
    cache = parc.charger_cache()
    e = parc.construire(7, 7, maintenant, cache)
    cartes = cartes_brutes(parc)
    lues = {s['id']: s for s in e['_sessions']}
    au_tableau = set()
    for l in (e.get('tableau') or []) + (e.get('anciennes') or []):
        for k in ('ouvrir', 'cle', 'session'):
            v = l.get(k)
            if isinstance(v, str) and v.startswith('local_'):
                au_tableau.add(v)
    index = parc.index_transcripts()
    dossiers = {}
    for sid, o in cartes.items():
        for p in {o.get('worktreePath'), o.get('cwd')} - {None, ''}:
            dossiers.setdefault(os.path.normpath(p), set()).add(sid)
    filles = {}
    for sid, o in cartes.items():
        mere = (o.get('spawnedFrom') or {}).get('sessionId')
        if mere:
            filles.setdefault(mere, []).append(sid)
    faits_de = {}
    for sid, o in cartes.items():
        if o.get('scheduledTaskId'):
            continue
        s = lues.get(sid) or {}
        chemin = s.get('chemin') or index.get(o.get('cliSessionId') or '')
        humains, marque, repondu = humains_et_marqueur(chemin, parc) if chemin else (None, False, False)
        mere = (o.get('spawnedFrom') or {}).get('sessionId')
        wt = o.get('worktreePath')
        resume = o.get('postTurnSummary') or {}
        faits_de[sid] = {
            'id': sid, 'titre': o.get('title') or '', 'parent': mere,
            'parent_titre': (cartes.get(mere) or {}).get('title') or (o.get('spawnedFrom') or {}).get('title'),
            'jetable': marque, 'detachee': bool(o.get('lineageDetached')), 'epinglee': bool(o.get('isStarred')),
            'exemptee': bool(o.get('autoArchiveExempt')), 'humains': humains, 'repondu': repondu,
            'etat': s.get('etat') if s else None, 'texte': s.get('texte') or '', 'prio': s.get('prio'),
            'carte': bool(s.get('carte')), 'encadre': bool(s.get('encadre')),
            'besoin': bool((resume.get('needs_action') or '').strip()) if isinstance(resume, dict) else False,
            'au_tableau': sid in au_tableau,
            'activite': max((o.get('lastActivityAt') or 0) / 1000, s.get('derniere') or 0),
            'worktree': wt, 'cwd': o.get('cwd'), 'chemin': chemin,
            'dossier_partage': bool(wt) and len(dossiers.get(os.path.normpath(wt), set()) - {sid}) > 0,
        }
    sortie = []
    heures = reglages()[1]
    for sid, f in faits_de.items():
        en_route = [x for x in filles.get(sid, []) if x in faits_de and not juger_sans_dossier(faits_de[x], heures,
                                                                                              maintenant, parc)]
        f['filles_en_route'] = bool(en_route)
        ok, pourquoi = juger(dict(f, dossier_sale=False), heures, maintenant, parc)
        if ok:   # the folder is read only for a session that passed every other guard
            f['dossier_sale'] = dossier_sale(f['worktree'])
            f['epic_attente'] = epic_en_attente(f['chemin'], f.get('cwd') or f['worktree'])
            ok, pourquoi = juger(f, heures, maintenant, parc)
        sortie.append((f, ok, pourquoi))
    sortie.sort(key=lambda x: (not x[1], -(x[0]['activite'] or 0)))
    return sortie


def juger_sans_dossier(f, heures, maintenant, parc):
    """A daughter is « en route » unless she would be archived herself (folder aside)."""
    return juger(dict(f, dossier_sale=False, filles_en_route=False), heures, maintenant, parc)[0]


# --- the three commands ---------------------------------------------------------------------------------------

def calculer(maintenant=None):
    maintenant = maintenant or time.time()
    allume, heures = reglages()
    ancien = lire_json(OUT, {}) or {}
    rangees = [r for r in ancien.get('rangees') or [] if maintenant - r.get('quand', 0) < GARDER_RANGEES_J * 86400]
    parc = charger_parc()
    archivees = {m['id']: m for m in parc.fiches({'fiches': {}}) if m['id'] and m['archivee']}
    deja = {r['id'] for r in rangees}
    # The sessions of a « Ranger » click, and those handed to a session before 0.3.10 (`confiees`, no longer written):
    # archived since, they enter `rangees` once; the others wait for the PM's click on the board.
    clics = lire_json(RANGER_CLICS, {}) or {}
    origines = dict(ancien.get('confiees') or {}, **(clics if isinstance(clics, dict) else {}))
    for sid, c in origines.items():
        c = c if isinstance(c, dict) else {}
        if sid in archivees and sid not in deja and maintenant - (c.get('quand') or 0) < 7 * 86400:
            deja.add(sid)
            rangees.append({'id': sid, 'titre': archivees[sid]['titre'] or c.get('titre') or '',
                            'quand': maintenant,
                            'raison': c.get('raison') or 'bouton « Ranger » de Mon Studio'})
    a_ranger = []
    if allume:
        a_ranger = [{'id': f['id'], 'titre': f['titre'], 'raison': pourquoi}
                    for f, ok, pourquoi in releve(maintenant, parc) if ok]
    ecrire_atomique(OUT, {'calcule': maintenant, 'heures': heures, 'allume': allume, 'a_ranger': a_ranger,
                          'rangees': rangees})
    return a_ranger


def lancer_calcul_detache():
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            if time.time() - LOCK.stat().st_mtime < 600:
                return
        except OSError:
            return
        LOCK.touch()
    except OSError:
        return
    subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), 'calculer', '--verrou'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def hook(entree, maintenant=None):
    """The UserPromptSubmit hook: starts the computation in the background when the list is more than an hour old, and,
    once a day in a top-level session of the desktop app, prints the proposal (proposer); otherwise prints nothing.
    Until 0.3.9 it handed the list to the PM's next top-level session as an order to archive; the app refuses that
    order in auto mode (it comes from a hook, not from the PM), so since 0.3.19 it hands a question to ask instead."""
    maintenant = maintenant or time.time()
    allume, _ = reglages()
    if not allume:
        return ''
    etat = lire_json(OUT, {}) or {}
    if maintenant - (etat.get('calcule') or 0) > RECALCUL_S:
        lancer_calcul_detache()
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import perimetre
        if not perimetre.session_de_studio((entree or {}).get('cwd') if isinstance(entree, dict) else None):
            return ''   # the list stays fresh for the board; the proposal goes only to a session opened in a Studio
        return proposer(entree, maintenant)
    except Exception:   # noqa: BLE001 (a hook never breaks the PM's message)
        return ''

# --- the daily proposal (0.3.19, PM, Q7, 2026-11-25) --------------------------------------------------------------
#
# The « Ranger » line of the board alone left the PM with no proposal at all (last pass 2026-11-19). The app refused
# archive_session when a hook's text ordered it (auto mode, 2026-11-18), and accepted it when the PM asked in his own
# session (2026-11-23). So the hook orders nothing: once a day, in a top-level session of the desktop app, it asks the
# session to end its answer with one numbered question whose text it gives; the PM's « 1 » is his consent. On that
# answer, `confirmer` checks the list again (a session active since, or a worktree whose work is not in main, is kept)
# and notes the confirmed sessions in ranger.json like the button, so that « Rangées aujourd'hui » follows.
# `rangement_sans_demander` (off by default) is the trial of a standing agreement: the session archives the checked
# list without asking, then says so in one line.

PROPOSE = INTERNAL / 'rangement-propose.json'   # {'jour', 'session', 'quand', 'ids'}: the day's proposal, once a day
ARCHIVE_CHECK = PLUGIN_ROOT / 'skills' / 'mon-studio' / 'scripts' / 'archive_check.py'
FRAIS_S = 24 * 3600        # a list computed longer ago than that is not proposed
PROPOSE_MAX = 20           # sessions in one question (parc.RANGER_MAX)
ESSAI_MAX = PROPOSE_MAX    # without asking: every checked session (trial of one a day passed, PM, Q4, 2026-11-25)
RANGER_JOURS = 7           # a ranger.json entry older than that is forgotten (parc.RANGER_JOURS)
# A message that does not come from the PM's keyboard: another session, an event of the app, a scheduled run.
PAS_DU_PM = ('<cross-session-message', '<side-sessions-event', '<task-notification', '<scheduled-task',
             '<ci-monitor-event', '<local-command')


def reglages_proposition():
    """(propose, sans_demander): off when Mon Studio is off, the rangement is off, or `rangement_propose` is false."""
    etat = lire_json(STATE)
    if not isinstance(etat, dict) or etat.get('disabled') or etat.get('rangement_auto') is False:
        return False, False
    propose = etat.get('rangement_propose') is not False
    return propose, propose and etat.get('rangement_sans_demander') is True


def dossier_cartes():
    v = os.environ.get('MON_STUDIO_APP_SESSIONS')
    if v:
        return pathlib.Path(v)
    return pathlib.Path.home() / 'Library' / 'Application Support' / 'Claude' / 'claude-code-sessions'


def carte(sid):
    """The app's card of one session (raw JSON), or None."""
    if not isinstance(sid, str) or not re.fullmatch(r'local_[\w-]+', sid):
        return None
    for chemin in dossier_cartes().glob(f'*/*/{sid}.json'):
        o = lire_json(chemin)
        if isinstance(o, dict):
            return o
    return None


def depuis(secondes):
    """« plus d'un jour », « 3 jours », « 20 heures »: how long the sessions have done nothing, in plain words."""
    h = secondes / 3600
    if h < 24:
        return f'{max(1, int(h))} heure{"s" if int(h) > 1 else ""}'
    if h < 48:
        return "plus d'un jour"
    return f'{int(h // 24)} jours'


def raison_en_clair(raison, inactif):
    """The reason of rangement.json, said for the PM: who started it, what it left, since when it does nothing."""
    origine = (raison or '').split(', rapport rendu')[0].strip()
    if origine.startswith('marquée'):
        origine = 'lancée comme une tâche ponctuelle (« [jetable] »)'
    elif not origine.startswith('lancée par'):
        origine = 'lancée par une autre session'
    return f"{origine}, a rendu son rapport, sans activité depuis {depuis(inactif)}"


def deja_proposees(etat, maintenant):
    """{session: when} the sessions put to the PM as a question in the last RANGER_JOURS days. One he kept (still open)
    is never archived without asking (PM, 2026-11-25: « garde-les pour l'instant »)."""
    etat = etat if isinstance(etat, dict) else {}
    d = {k: v for k, v in (etat.get('proposees') or {}).items() if isinstance(v, (int, float))}
    if etat.get('mode') == 'question' and isinstance(etat.get('quand'), (int, float)):
        for i in etat.get('ids') or []:
            d.setdefault(i, etat['quand'])
    return {k: v for k, v in d.items() if maintenant - v < RANGER_JOURS * 86400}


def a_proposer(entree, maintenant):
    """The sessions to propose in this session today ([{'id', 'titre', 'raison', 'inactif'}]), or [] when nothing is
    due: not in the desktop app, off, already proposed today, a message that is not the PM's, a session started by
    another one, a list too old, or no session still open and idle since the list was computed."""
    hote = (os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or '').strip()
    if not hote or not reglages_proposition()[0]:
        return []
    prompt = entree.get('prompt') if isinstance(entree, dict) else None
    if isinstance(prompt, str) and prompt.lstrip().startswith(PAS_DU_PM):
        return []
    jour = time.strftime('%Y-%m-%d', time.localtime(maintenant))
    if (lire_json(PROPOSE, {}) or {}).get('jour') == jour:
        return []
    ici = carte(hote)
    if ici is None or ici.get('scheduledTaskId'):
        return []
    if (ici.get('spawnedFrom') or {}).get('sessionId') and not ici.get('lineageDetached'):
        return []
    calcul = lire_json(OUT, {}) or {}
    quand = calcul.get('calcule') if isinstance(calcul, dict) else None
    if not isinstance(quand, (int, float)) or maintenant - quand > FRAIS_S:
        return []
    gardees = deja_proposees(lire_json(PROPOSE, {}), maintenant) if reglages_proposition()[1] else {}
    sortie = []
    for x in calcul.get('a_ranger') or []:
        if not isinstance(x, dict) or x.get('id') in (None, hote) or x.get('id') in gardees:
            continue
        c = carte(x['id'])
        if c is None or c.get('isArchived'):
            continue
        activite = (c.get('lastActivityAt') or 0) / 1000
        if activite > quand:
            continue
        sortie.append({'id': x['id'], 'titre': ' '.join(str(c.get('title') or x.get('titre') or '').split()),
                       'raison': x.get('raison') or '', 'inactif': maintenant - activite})
    return sortie[:PROPOSE_MAX]


def commande_confirmer(ids=None):
    return f'python3 "{pathlib.Path(__file__).resolve()}" confirmer' + (f' --ids {",".join(ids)}' if ids else '')


def lien(x):
    titre = (x['titre'] or 'sans titre').replace('[', '(').replace(']', ')')
    return f"[{titre}](#{x['id']})"


def question(liste):
    """The numbered question, « Qn » left for the session to number, worded as the PM asked (Q7, 2026-11-25)."""
    n = len(liste)
    x = depuis(min(s['inactif'] for s in liste))
    if n == 1:
        titre = 'Ranger 1 session finie ?'
        corps = (f"Cette session a été lancée par moi (ou par une autre session), elle ne fait plus rien depuis {x}, "
                 "tout ce qu'elle a produit est enregistré au Studio, elle n'attend pas de réponse de ta part. On "
                 "l'archive pour alléger ta liste ? Elle reste récupérable dans les archivées.")
        oui, non = 'La ranger', 'La garder'
        dit_oui, dit_non = "je l'archive maintenant", 'elle reste dans ta liste, je te reposerai la question demain'
    else:
        titre = f'Ranger {n} sessions finies ?'
        corps = (f"Ces {n} sessions ont été lancées par moi (ou par d'autres sessions), elles ne font plus rien depuis "
                 f"{x}, tout ce qu'elles ont produit est enregistré au Studio, aucune n'attend de réponse de ta part. "
                 "On les archive pour alléger ta liste ? Elles restent récupérables dans les archivées.")
        oui, non = 'Les ranger', 'Les garder'
        dit_oui, dit_non = 'je les archive maintenant', 'elles restent dans ta liste, je te reposerai la question demain'
    lignes = '\n'.join(f"- {lien(s)} : {raison_en_clair(s['raison'], s['inactif'])}." for s in liste)
    return (f"Qn · {titre} : {corps}\n{lignes}\n1) **{oui}** (recommandé) : {dit_oui}.\n2) **{non}** : {dit_non}.\n"
            "Pourquoi : ta liste de sessions s'allège, rien de ce qu'elles ont fait n'est perdu. Si tu ne fais rien : "
            "elles restent dans ta liste.")


def consigne(liste, sans_demander=False):
    """The text the hook hands to the session: a question to ask, never an order to archive (except the trial)."""
    if sans_demander:
        liste = liste[:ESSAI_MAX]
    n = len(liste)
    verifier = (f"lance `{commande_confirmer([s['id'] for s in liste])}` : il revérifie la liste (une session redevenue active en sort, un "
                "dossier de travail dont le travail n'est pas dans main la garde) et rend en JSON les sessions à "
                "archiver (`a_archiver`) ; archive celles-là seulement, une par une, avec "
                "mcp__ccd_session_mgmt__archive_session. Si l'app refuse un premier appel en te rendant un champ "
                "`session`, renvoie le même appel avec ce champ ; un autre refus : passe à la suivante.")
    if sans_demander:
        lignes = '\n'.join(f"- {lien(s)} : {raison_en_clair(s['raison'], s['inactif'])}." for s in liste)
        return ("Mon Studio, rangement du jour : le PM t'a donné un accord permanent, écrit dans ses règles, pour "
                "ranger sans lui demander les sessions finies que Mon Studio a vérifiées (réglage "
                f"`rangement_sans_demander`). {n} session{'s' if n > 1 else ''} :\n{lignes}\n"
                "Réponds d'abord à son message comme d'habitude. Puis " + verifier +
                " Termine ta réponse par une ligne « Rangé : N sessions finies, récupérables dans les archivées », "
                "avec leurs titres liés ; si un archivage est refusé, dis-le dans cette ligne avec le motif de l'app.")
    return ("Mon Studio, rangement du jour (une fois par jour) : des sessions finies peuvent être rangées. N'archive "
            "rien de toi-même. Réponds d'abord au message du PM comme d'habitude, puis termine ta réponse par la "
            "question ci-dessous, sous « À trancher » (après tes autres questions s'il y en a), en remplaçant « Qn » "
            "par le prochain numéro libre de cette session ; reprends le reste tel quel, liens compris :\n\n"
            f"{question(liste)}\n\n"
            "Si le PM répond 1 (ou oui) : " + verifier +
            " S'il n'en accepte qu'une partie, archive celles-là seulement. Dis-lui ensuite en une ligne combien sont rangées. S'il répond 2 : ne fais rien, la question reviendra "
            "demain.")


def proposer(entree, maintenant=None, apercu=False):
    """The day's proposal for this session ('' when none is due); noted in rangement-propose.json unless `apercu`."""
    maintenant = maintenant or time.time()
    liste = a_proposer(entree, maintenant)
    if not liste:
        return ''
    sans_demander = reglages_proposition()[1]
    texte = consigne(liste, sans_demander)
    if not apercu:
        proposees = deja_proposees(lire_json(PROPOSE, {}), maintenant)
        if not sans_demander:
            proposees.update({s['id']: maintenant for s in liste})
        try:
            ecrire_atomique(PROPOSE, {'jour': time.strftime('%Y-%m-%d', time.localtime(maintenant)),
                                      'session': os.environ.get('CLAUDE_CODE_HOST_SESSION_ID'), 'quand': maintenant,
                                      'ids': [s['id'] for s in liste][:ESSAI_MAX] if sans_demander else
                                      [s['id'] for s in liste],
                                      'mode': 'sans_demander' if sans_demander else 'question',
                                      'proposees': proposees})
        except OSError:
            return ''
    return texte


def worktree_pret(wt):
    """(True, '') when the session's worktree can go, or (False, why): uncommitted files, or lines of its branch that
    never reached main (archive_check.py). A missing folder or one outside git has nothing to lose."""
    if not wt or not os.path.isdir(wt):
        return True, ''
    sale = dossier_sale(wt)
    if sale is None:
        return False, 'dossier de travail illisible : doute'
    if sale:
        return False, 'fichiers non enregistrés dans son dossier de travail'
    try:
        r = subprocess.run(['git', '-C', wt, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False, 'dossier de travail illisible : doute'
    if r.returncode != 0:
        return True, ''   # not a git folder
    repo = str(pathlib.Path(r.stdout.strip()).parent)
    try:
        v = subprocess.run([sys.executable, str(ARCHIVE_CHECK), repo, wt], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False, 'vérification du dossier de travail impossible : doute'
    if v.returncode != 0:
        return False, "des lignes de sa branche ne sont pas dans main (archive_check.py)"
    return True, ''


def confirmer(maintenant=None, maximum=None, ids=None):
    """On the PM's yes: the list checked again, and its sessions noted in ranger.json like the « Ranger » button.
    {'a_archiver': [{'id', 'titre'}], 'gardees': [{'id', 'titre', 'raison'}]}."""
    maintenant = maintenant or time.time()
    calcul = lire_json(OUT, {}) or {}
    quand = calcul.get('calcule') or 0
    a_archiver, gardees = [], []
    for x in calcul.get('a_ranger') or []:
        if not isinstance(x, dict) or not x.get('id') or (ids is not None and x['id'] not in ids):
            continue
        c = carte(x['id'])
        titre = ' '.join(str((c or {}).get('title') or x.get('titre') or '').split())
        if c is None:
            gardees.append({'id': x['id'], 'titre': titre, 'raison': 'session introuvable dans l’app : doute'})
            continue
        if c.get('isArchived'):
            continue
        if (c.get('lastActivityAt') or 0) / 1000 > quand:
            gardees.append({'id': x['id'], 'titre': titre, 'raison': 'redevenue active depuis le calcul de la liste'})
            continue
        if maximum is not None and len(a_archiver) >= maximum:
            continue
        ok, pourquoi = worktree_pret(c.get('worktreePath'))
        if not ok:
            gardees.append({'id': x['id'], 'titre': titre, 'raison': pourquoi})
            continue
        a_archiver.append({'id': x['id'], 'titre': titre})
    if a_archiver:
        clics = lire_json(RANGER_CLICS, {})
        clics = {k: v for k, v in (clics if isinstance(clics, dict) else {}).items()
                 if isinstance(v, dict) and maintenant - (v.get('quand') or 0) < RANGER_JOURS * 86400}
        for x in a_archiver:
            clics[x['id']] = {'titre': x['titre'], 'quand': maintenant, 'raison': 'rangement accepté dans une session'}
        ecrire_atomique(RANGER_CLICS, clics)
    return {'a_archiver': a_archiver, 'gardees': gardees}


def lister(heures=None, en_json=False, maintenant=None):
    maintenant = maintenant or time.time()
    if heures is not None:
        global reglages
        _r = reglages
        reglages = lambda: (_r()[0], heures)   # noqa: E731 (a dry run with another threshold)
    lignes = releve(maintenant)
    if en_json:
        print(json.dumps([{'id': f['id'], 'titre': f['titre'], 'ranger': ok, 'raison': pourquoi}
                          for f, ok, pourquoi in lignes], ensure_ascii=False, indent=1))
        return
    oui = [(f, p) for f, ok, p in lignes if ok]
    non = [(f, p) for f, ok, p in lignes if not ok]
    print(f'À ranger ({len(oui)}) :')
    for f, p in oui:
        print(f"  - {f['titre'] or f['id']} — {p}")
    print(f'Gardées ({len(non)}) :')
    for f, p in non:
        print(f"  - {f['titre'] or f['id']} — {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sous = ap.add_subparsers(dest='cmd', required=True)
    l = sous.add_parser('lister')
    l.add_argument('--heures', type=float)
    l.add_argument('--json', action='store_true')
    c = sous.add_parser('calculer')
    c.add_argument('--verrou', action='store_true')
    sous.add_parser('hook')
    p = sous.add_parser('proposer')
    p.add_argument('--apercu', action='store_true')
    f = sous.add_parser('confirmer')
    f.add_argument('--max', type=int)
    f.add_argument('--ids', help='only these sessions, comma separated (those the proposal named)')
    a = ap.parse_args(argv)
    if a.cmd == 'lister':
        lister(a.heures, a.json)
    elif a.cmd == 'proposer':
        texte = proposer({}, apercu=a.apercu)
        print(texte or 'Rien à proposer dans cette session aujourd’hui.')
    elif a.cmd == 'confirmer':
        print(json.dumps(confirmer(maximum=a.max, ids=a.ids.split(',') if a.ids else None), ensure_ascii=False, indent=1))
    elif a.cmd == 'calculer':
        try:
            calculer()
        finally:
            if a.verrou:
                try:
                    LOCK.unlink()
                except OSError:
                    pass
    else:
        try:
            entree = json.load(sys.stdin)
        except ValueError:
            entree = {}
        texte = hook(entree)
        if texte:
            print(texte)
    return 0


if __name__ == '__main__':
    sys.exit(main())
