#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rangement: the finished one-action sessions are archived without the PM, the dialogue sessions never.

    python3 rangement.py lister [--heures N] [--json]   # dry run: every open session, kept or to archive, and why
    python3 rangement.py calculer                       # writes ~/Mon Studio/.parc/rangement.json (run detached)
    python3 rangement.py hook                           # UserPromptSubmit: keeps the list fresh, prints nothing

The list is computed without a model, from the app's session cards and the transcripts (parc.py). A session is
archived only when ALL of these hold; the first one that fails is the reason it stays:
  - it was started by another session (`spawnedFrom`), or its brief carries the marker « [jetable] »;
  - its title does not start with « 📬 », it is not pinned, not exempted in the app, not moved to the top level;
  - the PM never wrote in it, or, for a session started by another one, Claude answered his last message after it
    (PM, 2026-11-17: « les ranger aussi ») — a session the PM opened himself never moves;
  - its turn is over and its last message asks nothing (no « À trancher », « Encore ouvert », final question mark,
    open menu or app card question, action awaited), and it has no line on the board;
  - no activity for `rangement_heures` hours (24 by default, cockpit.json);
  - its work folder has nothing unsaved and is not shared with an open session;
  - no session it started is still under way.
Any doubt (unreadable card, transcript or folder) keeps the session.

Who archives: the PM, from the board (PM, Q5, 2026-11-18). The app refuses `archive_session` in a scheduled run nobody
opened (tried 2026-11-16: « needs a person's approval, and nobody has opened this scheduled run »), and in auto mode it
refuses it too when the order comes from a hook's text handed to an unrelated session (2026-11-18, twice on the same
session: « judged dangerous »). So nothing here hands an order to a session any more: the list is a line of Mon Studio,
« N sessions finies à ranger », whose « Ranger » button copies a request in the PM's words (parc.texte_a_ranger) that he
pastes in a session of his; his message is his consent. The sessions of a click are noted in .parc/ranger.json, and
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
            'worktree': wt,
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
    """The UserPromptSubmit hook: starts the computation in the background when the list is more than an hour old, and
    prints nothing. Until 0.3.9 it handed the list to the PM's next top-level session as an order to archive; the app
    refuses that order in auto mode (it comes from a hook, not from the PM), so the list is now a line of the board
    with its « Ranger » button (PM, Q5, 2026-11-18)."""
    maintenant = maintenant or time.time()
    allume, _ = reglages()
    if not allume:
        return ''
    etat = lire_json(OUT, {}) or {}
    if maintenant - (etat.get('calcule') or 0) > RECALCUL_S:
        lancer_calcul_detache()
    return ''

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
    a = ap.parse_args(argv)
    if a.cmd == 'lister':
        lister(a.heures, a.json)
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
