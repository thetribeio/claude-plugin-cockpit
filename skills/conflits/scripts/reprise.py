#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The reprise of conflict decisions settled by hand, before /cockpit:conflits existed (PM, Q12, 2026-11-15).

Some Studios were caught up by hand: a folder `projet/rattrapage-AAAA-MM-JJ/` holds the survey, the PM's answers and
the journal of what was applied. Their register `projet/conflits.md` is empty, so Mon Studio says nothing was ever
checked and a new survey would ask again what the PM already settled. The reprise writes those decisions into the
register as settled, with their date, who settled them and where, then « Dernier passage » at the date of the hand
survey: the next re-read only looks at what came after.

Three steps, the same as the rest of the skill:
1. `entree(studio)`: the hand files that hold decisions, gathered in one text a Sonnet sub-agent reads once; the
   sub-agent writes one JSON object per PM decision (the extraction). The script never interprets free text.
2. `verifier(studio, extraction)`: every object checked against the register's format; nothing is guessed (a value
   without a date takes its file's date and says so, as the register already does).
3. `apercu(...)` shows what would be written, and `ecrire(...)`, after the PM's go, appends the cases already settled
   (« tranché le … par … : … »), never twice, then « Dernier passage », then one row in `projet/changelog.md`.

Nothing else is written; with `--sortie`, nothing at all in the Studio. What the PM reads carries no code.
"""
import datetime as dt
import json
import pathlib
import re

DOSSIER = re.compile(r'^rattrapage-(\d{4}-\d{2}-\d{2})$')
# The files of a hand catch-up that hold the PM's decisions: its answers and its journal. The survey's preview only
# when the folder has no answer file (a catch-up may keep its questions there and its answers in the journal).
REPONSES = re.compile(r'decision|journal', re.I)
APERCU = re.compile(r'apercu|aperçu', re.I)
ENTREE_MAX = 120_000          # characters given to the sub-agent at most; above, one folder at a time
TITRE_MAX = 90
REPONSE_MAX = 300


def dossiers(studio):
    """The hand catch-up folders of a Studio, oldest first: [(path, 'AAAA-MM-JJ')]."""
    racine = pathlib.Path(studio) / 'projet'
    try:
        noms = sorted(p.name for p in racine.iterdir() if p.is_dir())
    except OSError:
        return []
    sortie = []
    for n in noms:
        m = DOSSIER.match(n)
        try:
            if m and dt.date.fromisoformat(m.group(1)) <= dt.date.today():
                sortie.append((racine / n, m.group(1)))
        except ValueError:
            continue                      # « rattrapage-2026-02-30 »: not a date, not a catch-up
    return sortie


def fichiers(studio, dossier=None):
    """The files to read, relative to the Studio: [(rel, date of the folder, size)]."""
    sortie = []
    for d, jour in dossiers(studio):
        if dossier and d.name != dossier:
            continue
        mds = sorted(p for p in d.iterdir() if p.is_file() and p.suffix == '.md')
        choisis = [p for p in mds if REPONSES.search(p.name)]
        if not any('decision' in p.name.lower() for p in choisis):
            choisis += [p for p in mds if APERCU.search(p.name) and p not in choisis]
        for p in choisis:
            try:
                taille = p.stat().st_size
            except OSError:
                continue
            sortie.append((p.relative_to(studio).as_posix(), jour, taille))
    return sortie


def texte_entree(studio, dossier=None):
    """What the sub-agent reads, in one go: each file whole, under its path and the date of its catch-up."""
    morceaux = []
    for rel, jour, _ in fichiers(studio, dossier):
        try:
            contenu = (pathlib.Path(studio) / rel).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            morceaux.append(f'===== {rel} (rattrapage du {jour}) : illisible, ignoré =====')
            continue
        morceaux.append(f'===== {rel} (rattrapage du {jour}) =====\n{contenu.strip()}')
    return '\n\n'.join(morceaux)


def estimer(studio, registre_module, cout_usd, pourcent_usd, dossier=None):
    """The cost of the extraction: one Sonnet sub-agent reads the files once and writes about 150 tokens per
    decision; the session only runs the script. {'fichiers', 'caracteres', 'usd', 'pourcent_semaine', 'trop_gros'}."""
    fs = fichiers(studio, dossier)
    car = sum(t for _, _, t in fs)
    tok = car / 3.5 + 6000                       # the files, the brief and the agent's own start
    decisions = max(1, car // 1000)              # about one decision per kilobyte of answers (32 in 31 Ko for one Studio)
    usd = cout_usd('sonnet', tok, decisions * 150 + 500, tok) * 1.3
    return {'fichiers': fs, 'caracteres': car, 'usd': round(usd, 2), 'pourcent_semaine': round(usd / pourcent_usd, 3),
            'trop_gros': car > ENTREE_MAX}


# ---------- the extraction, checked

def _date(x, registre):
    """JJ/MM/AAAA from JJ/MM/AAAA or AAAA-MM-JJ, else None."""
    if not isinstance(x, str):
        return None
    x = x.strip()
    if registre.DATE.match(x):
        return x if registre.iso(x) else None
    try:
        return dt.date.fromisoformat(x[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return None


def _une_ligne(x):
    return ' '.join(str(x or '').split())


def verifier(studio, extraction, registre, pm=None, aujourdhui=None):
    """(decisions, refus): the extraction's objects that read back as register cases, normalized, and the refused
    ones with why. A decision: {'titre', 'ancienne', 'nouvelle', 'communique', 'choix', 'par', 'tranche_le',
    'detecte', 'reponse', 'tranche_dans', 'reste'}."""
    aujourdhui = aujourdhui or dt.date.today()
    dates_des_dossiers = {d.name: jour for d, jour in dossiers(studio)}
    decisions, refus, vus = [], [], set()
    for k, x in enumerate(extraction if isinstance(extraction, list) else [], 1):
        if not isinstance(x, dict):
            refus.append((f'objet {k}', 'pas un objet'))
            continue
        titre = _une_ligne(x.get('titre'))
        nom = titre or f'objet {k}'
        pourquoi = []
        if not titre:
            pourquoi.append('titre vide')
        elif titre.lower() in vus:
            pourquoi.append('en double dans l\'extraction')
        elif len(titre) > TITRE_MAX:
            pourquoi.append('titre trop long')
        elif registre.codes_pour_le_pm(titre):
            pourquoi.append(f"titre avec un code ({', '.join(registre.codes_pour_le_pm(titre))})")
        choix = _une_ligne(x.get('choix'))
        if choix not in registre.CHOIX:
            pourquoi.append(f'choix inconnu : {choix!r}')
        tranche_dans = _une_ligne(x.get('tranche_dans')).lstrip('./')
        chemin = (pathlib.Path(studio) / tranche_dans) if tranche_dans else None
        try:
            dedans = chemin is not None and chemin.resolve().is_relative_to(pathlib.Path(studio).resolve()) and chemin.is_file()
        except OSError:
            dedans = False
        if not dedans:
            pourquoi.append(f'fichier de la décision introuvable dans le Studio : {tranche_dans!r}')
        # The catch-up's date: the folder the decision was settled in (« rattrapage-2026-11-09 »).
        jour_dossier = next((dates_des_dossiers[p] for p in pathlib.PurePosixPath(tranche_dans).parts
                             if p in dates_des_dossiers), None)
        jour_dossier = _date(jour_dossier, registre) if jour_dossier else None
        tranche_le = _date(x.get('tranche_le'), registre)
        if not tranche_le:
            pourquoi.append('date de la décision absente ou illisible')
        elif dt.date.fromisoformat(registre.iso(tranche_le)) > aujourdhui:
            pourquoi.append('date de la décision dans le futur')
        par = _une_ligne(x.get('par')) or _une_ligne(pm)
        if not par:
            pourquoi.append('qui a tranché : inconnu')
        valeurs = {}
        for cle in ('ancienne', 'nouvelle'):
            v = x.get(cle) if isinstance(x.get(cle), dict) else {}
            texte, source = _une_ligne(v.get('texte')), _une_ligne(v.get('source'))
            if not texte or not source:
                pourquoi.append(f'{cle} valeur : texte ou source manquant')
                continue
            jour = _date(v.get('date'), registre)
            if not jour:
                # Never a date made up: the date of its source file when the Studio has it, else of the catch-up that
                # read it; said in the value, the register's way.
                jour = _date_du_fichier(studio, source) or jour_dossier
                texte = f'{texte} {registre.SUFFIXE_FICHIER}'
            if not jour:
                pourquoi.append(f'{cle} valeur : aucune date')
                continue
            if dt.date.fromisoformat(registre.iso(jour)) > aujourdhui:
                pourquoi.append(f'{cle} valeur : date dans le futur')
                continue
            for car in '()':
                source = source.replace(car, ' ')
            valeurs[cle] = {'texte': texte.replace('(source :', '(source'), 'source': _une_ligne(source), 'date': jour}
        if pourquoi:
            refus.append((nom, ' ; '.join(pourquoi)))
            continue
        vus.add(titre.lower())
        reponse = registre.sans_codes(_une_ligne(x.get('reponse')))[:REPONSE_MAX]
        decisions.append({'titre': titre, 'ancienne': valeurs['ancienne'], 'nouvelle': valeurs['nouvelle'],
                          'communique': x.get('communique') is True, 'choix': choix, 'par': par,
                          'tranche_le': tranche_le, 'detecte': jour_dossier or tranche_le, 'reponse': reponse,
                          'tranche_dans': tranche_dans, 'reste': registre.sans_codes(_une_ligne(x.get('reste')))[:REPONSE_MAX]})
    return decisions, refus


def _date_du_fichier(studio, source):
    """JJ/MM/AAAA of a Studio file's last change, or None (a link, a file outside the Studio or absent)."""
    try:
        p = (pathlib.Path(studio) / source.lstrip('./')).resolve()
        if not p.is_relative_to(pathlib.Path(studio).resolve()) or not p.is_file():
            return None
        return dt.date.fromtimestamp(p.stat().st_mtime).strftime('%d/%m/%Y')
    except (OSError, ValueError):
        return None


def changer(decisions, changements):
    """The PM corrects a choice before the go, by words of its title: [{'quoi': 'pages publiques', 'choix': 'remplacer'}].
    Returns the errors (no case or several for the words): then nothing is changed."""
    erreurs, a_faire = [], []
    for c in changements or []:
        quoi = _une_ligne((c or {}).get('quoi')).lower()
        trouves = [d for d in decisions if quoi and quoi in d['titre'].lower()]
        if len(trouves) != 1:
            erreurs.append(f"« {quoi} » : {'aucune décision' if not trouves else str(len(trouves)) + ' décisions'} "
                           + ('' if not trouves else '(' + ' ; '.join(d['titre'] for d in trouves) + ')'))
            continue
        a_faire.append((trouves[0], _une_ligne((c or {}).get('choix'))))
    if not erreurs:
        for d, choix in a_faire:
            d['choix'] = choix
    return erreurs


def dernier_passage_propose(studio, registre, dossier=None):
    """The date the hand catch-up read the Studio up to: the most recent catch-up folder. None without one, and None
    when only an older folder is taken up (its decisions are not the whole Studio's)."""
    ds = dossiers(studio)
    if not ds or (dossier and ds[-1][0].name != dossier):
        return None
    return _date(ds[-1][1], registre)


# ---------- what the PM reads, and what is written

def _bloc(registre, cid, d):
    return registre.bloc_du_cas(cid, d['titre'], d['ancienne'], d['nouvelle'], d['communique'], d['detecte'],
                                etat=registre.texte_etat(d['choix'], d['par'], d['tranche_le']), file=_file(d))


def _file(d):
    return {'ajoute_par': 'reprise', 'reponse': d['reponse'], 'tranche_dans': d['tranche_dans']}


def deja(registre, texte, d):
    """The register's case for this decision, when it is already there: same values, sources and title, or a case
    already taken up under the same title (a second extraction words the values otherwise)."""
    c = registre.trouver(texte, d['ancienne'], d['nouvelle'], d['titre'])
    if c:
        return c
    titre = _une_ligne(d['titre']).lower()
    return next((c for c in registre.lire(texte or '')['cas']
                 if (c.get('file') or {}).get('ajoute_par') == 'reprise' and _une_ligne(c['sujet']).lower() == titre), None)


def apercu(studio, decisions, refus, registre, dernier_passage):
    """The preview, for the PM: no code. Then, for a dry run, the exact lines the register would receive."""
    chemin = registre.chemin_du_studio(studio)
    texte = registre.lire_existant(chemin)[0] or ''
    nouvelles = [d for d in decisions if not deja(registre, texte, d)]
    pl = lambda n, un, plusieurs: f"{n} {un if n == 1 else plusieurs}"
    lignes = [f"{pl(len(nouvelles), 'décision tranchée à la main', 'décisions tranchées à la main')} à inscrire au "
              f"registre des conflits, comme tranchée{'' if len(nouvelles) == 1 else 's'}"
              + (f" ({pl(len(decisions) - len(nouvelles), 'déjà inscrite', 'déjà inscrites')})" if len(decisions) > len(nouvelles) else '')
              + '.']
    par_choix = {}
    for d in nouvelles:
        par_choix[d['choix']] = par_choix.get(d['choix'], 0) + 1
    if par_choix:
        lignes.append('Réponses : ' + ', '.join(f'{v} {k}' for k, v in sorted(par_choix.items(), key=lambda x: -x[1])) + '.')
    for d in nouvelles:
        lignes.append(f"- {d['titre']} : {d['choix']}, le {d['tranche_le']} par {d['par']}"
                      + (f" ({d['reponse']})" if d['reponse'] and d['reponse'].lower() != d['choix'] else ''))
    restes = [d for d in decisions if d['reste']]
    if restes:
        lignes += ['', 'Encore à faire, d\'après les fichiers du rattrapage (rien de cela n\'entre au registre) :']
        lignes += [f"- {d['titre']} : {d['reste']}" for d in restes]
    if refus:
        lignes += ['', f"Écartées, à revoir : {len(refus)}"] + [f'- {n} : {p}' for n, p in refus]
    lignes.append('')
    if dernier_passage:
        lignes.append(f"Studio à jour depuis le {dernier_passage} : la relecture suivante ne lira que ce qui est arrivé "
                      "depuis, et ne reposera aucune de ces décisions.")
    else:
        lignes.append("Aucune date de dernier passage : le Studio reste « pas encore vérifié » en entier.")
    return '\n'.join(lignes), nouvelles


def texte_registre(studio, nouvelles, registre, dernier_passage):
    """The lines the register would receive, exactly: for a dry run (`--sortie`)."""
    texte = registre.lire_existant(registre.chemin_du_studio(studio))[0] or ''
    n = registre.lire(texte)['max_id']
    sortie = [] if texte.strip() else [registre.TITRE, '']
    if dernier_passage:
        sortie += [f'Dernier passage : {dernier_passage}', '']
    for d in nouvelles:
        n += 1
        sortie += _bloc(registre, f'C{n}', d) + ['']
    return '\n'.join(sortie)


def ecrire(studio, decisions, registre, dernier_passage, journal=None):
    """After the PM's go: each decision appended as a settled case (never twice), then « Dernier passage », then one
    journal row. {'inscrites', 'deja', 'dernier_passage'}."""
    chemin = registre.chemin_du_studio(studio)
    inscrites = deja_la = 0
    echecs = []
    for d in decisions:
        try:
            avant = registre.lire_existant(chemin)[0] or ''
            if deja(registre, avant, d):
                deja_la += 1
                continue
            registre.ajouter(chemin, d['titre'], d['ancienne'], d['nouvelle'], d['communique'], d['detecte'],
                             file=_file(d), etat=registre.texte_etat(d['choix'], d['par'], d['tranche_le']))
            inscrites += 1
        except (ValueError, OSError, RuntimeError) as exc:     # unreadable once written, register busy or unreadable
            echecs.append((d['titre'], str(exc)))
    # « Dernier passage » only when every decision is in the register, and never back in time.
    pose = None
    if dernier_passage and not echecs:
        try:
            avant = registre.lire_fichier(chemin)['dernier_passage']
            if not avant or registre.iso(avant) <= registre.iso(dernier_passage):
                registre.poser_dernier_passage(chemin, dernier_passage)
                pose = dernier_passage
            else:
                pose = avant
        except (OSError, RuntimeError) as exc:
            echecs.append(('Dernier passage', str(exc)))
    dernier_passage = pose
    if journal and inscrites:
        journal(studio, f"Registre des conflits : {inscrites} décisions tranchées à la main reprises"
                + (f", Studio à jour depuis le {dernier_passage}" if dernier_passage else ''))
    return {'inscrites': inscrites, 'deja': deja_la, 'dernier_passage': dernier_passage, 'echecs': echecs}


def charger(chemin):
    with open(chemin, encoding='utf-8') as f:
        x = json.load(f)
    return x if isinstance(x, list) else (x.get('decisions') or [])
