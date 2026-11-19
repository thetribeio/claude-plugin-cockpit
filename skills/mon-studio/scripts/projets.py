#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liste par projet : ce qui attend la personne sur chacun de ses Studios, sans LLM.

    python3 projets.py              # calcule, écrit ~/Mon Studio/projets.json et projets.md, une ligne d'état
    python3 projets.py --essai      # calcule sans rien écrire : par Studio, le rôle et le nombre de lignes par type
    python3 projets.py fait <cle>   # ferme une ligne à la main (un coup de fil, ce qu'aucune source ne voit)

Un bloc par Studio qui a quelque chose, lu par deux écrans : le brief du matin (/morning, section « Projets »,
qui lit projets.md) et la page épinglée de Mon Studio (bloc « Projets », par le connecteur, champ `liste_projets`).

Les Studios sont ceux des fiches de session de ce Mac (dossier de travail qui a un projet/fiche-projet.md), plus
ceux de ~/Mon Studio/studios.json (une liste de chemins) ; le disque n'est jamais parcouru. Trois sources :
    a_toi     « À toi de jouer » des passages de l'ingestion auto (projet/.ingestion-auto-state.json) : pour le PM
              du Studio seulement. Notée si son passage a moins de 14 jours, puis ouverte, avec son âge et son
              échéance, jusqu'à ce qu'elle soit réglée (`reglees` de l'ingestion) ou fermée à la main. La page la
              montre aussi au tableau principal (champ `lignes` de son bloc).
    entree    « Ce qui est entré » des mêmes passages : pour tous, tant que le passage est dans la fenêtre, puis
              s'efface d'elle-même.
    question  les lignes ouvertes du tableau de Mon Studio pour ce Studio : pour tous (ce sont les sessions de ce
              Mac) ; fermée d'elle-même quand elle quitte le tableau.
    reunion   les réunions sans compte rendu de ~/Mon Studio/matin.json (`reunions_sans_cr`, écrit par la tâche du point
              du matin, la seule à lire l'agenda) : pour le PM du Studio seulement, rattachées au Studio par le nom du
              projet. Ouvertes jusqu'à ce que la tâche ne les liste plus (un point du jour qui ne les contient plus), ou
              fermées à la main.
Les alertes (budget, sprint) sont abandonnées : aucun type `alerte`.

L'état des lignes vit dans ~/Mon Studio/.parc/projets-etat.json : première apparition, fermeture, par qui.

Le connecteur, lancé par l'app, n'a pas le droit de lire le Drive (macOS refuse : PermissionError) ; ~/Mon Studio, si.
Chaque calcul hors du connecteur (ligne de commande, hook de session) écrit donc ce qu'il a lu de chaque Studio dans
~/Mon Studio/.parc/projets-sources.json (le PM de la fiche, les items des passages récents, `reglees`, l'heure de
lecture) ; le connecteur s'en sert pour un Studio qu'il ne peut pas lire. Les questions restent lues en direct.

Le registre des conflits du Studio (projet/conflits.md, écrit par /cockpit:conflits et /studio:auto-ingest) est lu de
même, pour l'onglet « Conflits » de la vue projet (`conflits_du_projet`), en lecture seule : ses cas ouverts et la
session « <Projet> · Conflits Studio » qui les traite. Le lecteur est celui du skill conflits (registre.py), copié à
côté de ce fichier sous le nom registre_conflits.py.
"""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import unicodedata

try:
    import fcntl
except ImportError:   # Windows: no flock, the writes stay as they were
    fcntl = None

ICI = pathlib.Path(__file__).resolve().parent


def _charger_parc():
    """parc.py du même dossier, chargé comme le fait le connecteur : marche depuis le dépôt et depuis la copie de
    ~/Mon Studio/.parc. Le connecteur remplace ce module par le sien (projets.parc = parc), rechargé à chaud."""
    spec = importlib.util.spec_from_file_location('parc', ICI / 'parc.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parc = _charger_parc()


def _charger_matin():
    """matin.py du même dossier, rechargé à chaque appel (petit, et le connecteur ne se relance pas), sur le parc de
    ce module."""
    spec = importlib.util.spec_from_file_location('matin', ICI / 'matin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.parc = parc
    return module

PURGE_S = 8 * 86400       # une ligne fermée depuis plus de 8 jours quitte l'état ; une entrée aussi, ouverte ou non
FENETRE_A_TOI_S = 14 * 86400   # un « À toi » est noté si son passage a moins de 14 jours
LECTURE_S = max(PURGE_S, FENETRE_A_TOI_S)   # les passages lus (et gardés dans l'instantané)
ANCIENNE_A_TOI_S = 7 * 86400   # au tableau, un « À toi » de plus de 7 jours sans échéance à venir va dans « Anciennes »
FERMEES_MONTREES = 3      # « Fermé depuis hier » : trois titres au plus par Studio
TITRE_MAX = 160
RECRIT_S = 600            # depuis le connecteur, projets.json n'est récrit que s'il a changé, ou toutes les 10 min
LIGNE_PM = re.compile(r'^\|\s*\*{0,2}PM\*{0,2}\s*\|\s*([^|]*?)\s*\|', re.M)
ADRESSE_PAGE = re.compile(r'^https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+$')
CLE = re.compile(r'^[0-9a-f]{12}$')
ORDRE_TYPES = {'a_toi': 0, 'reunion': 1, 'question': 2, 'entree': 3}
SOURCES = {'a_toi': 'à toi de jouer (ingestion)', 'entree': 'entré au Studio (ingestion)',
           'reunion': 'réunion sans compte rendu', 'conflits': 'conflits à trancher (session des conflits)',
           'verifier': 'premier relevé des conflits (session des conflits)'}
# Ce que projets-sources.json garde d'une entrée `reglees` du kit, en plus de `ts` et `texte` (contrat du kit
# d'ingestion, « Demande au cockpit : points réglés par la source ») : le genre (a_toi ou question), la question
# nommée {numero, doc, sessionId, chantier}, la réouverture par le PM, la référence et la preuve.
CHAMPS_REGLEE = ('genre', 'question', 'rouverte', 'ref', 'preuve')
ABSENT = (FileNotFoundError, NotADirectoryError, IsADirectoryError)   # un fichier qui manque ; tout autre OSError : refusé
_LIRE = object()


def _sortie():
    return parc.SORTIE


def _etat_chemin():
    return parc.INTERNE / 'projets-etat.json'

def _instantane_chemin():
    return parc.INTERNE / 'projets-sources.json'


# --- textes -----------------------------------------------------------------------------------------------

def _sans_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def normaliser(s):
    """Pour comparer : sans accents, en minuscules, espaces réduits, sans ponctuation finale."""
    s = re.sub(r'\s+', ' ', _sans_accents(texte_simple(s)).lower()).strip()
    return s.rstrip(' .;:!')


def texte_simple(s):
    """Le Markdown d'un rapport en texte plat : liens, gras, code."""
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', str(s or ''))
    s = re.sub(r'(\*\*|__)(.+?)\1', r'\2', s)
    s = s.replace('`', '')
    return re.sub(r'\s+', ' ', s).strip()


# Les suffixes que le kit d'ingestion ajoute en fin de puce : ` (échéance AAAA-MM-JJ)` puis ` ([source](<lien>))`.
SUFFIXE_SOURCE = re.compile(r'\(\[([^\]]*)\]\(<?(.+?)>?\)\)\s*$')
SUFFIXE_ECHEANCE = re.compile(r'\s*\([ée]ch[ée]ance (\d{4}-\d{2}-\d{2})(?:\s*[,;]\s*([^)]*?))?\)\s*$', re.I)
# ` (reçu le AAAA-MM-JJ)`: the day a mail reached the PM, written by the ingestion when it knows it.
SUFFIXE_RECU = re.compile(r'\s*\(re[çc]u le (\d{4}-\d{2}-\d{2})\)\s*$', re.I)


def _origine_echeance(note):
    """Where a due date comes from, read of the note after the date: « (échéance 2026-11-23, lue dans le mail) » →
    ('lue', ''), « (échéance 2026-11-23, calculée : 8 jours ouvrés après la réception) » → ('calculee', '8 jours ouvrés
    après la réception'). ('', '') when the ingestion does not say: the page then says it does not know."""
    note = ' '.join((note or '').split())
    m = re.match(r'(?i)^(lue?|trouv[ée]e?|[ée]crite?)\b', note)
    if m:
        return 'lue', ''
    m = re.match(r'(?i)^(calcul[ée]e?|d[ée]duite?|estim[ée]e?)\b\s*(?:[:\-]\s*)?(.*)$', note)
    if m:
        return 'calculee', m.group(2).strip()
    return '', ''


def decouper_puce(texte):
    """(corps, échéance, lien) d'une puce du kit : le corps sans ses suffixes, l'échéance AAAA-MM-JJ (None si absente
    ou invalide), le lien de la source ('' si absent). Les suffixes sont lus de la fin, dans n'importe quel ordre."""
    return decouper_puce_meta(texte)[:3]


def decouper_puce_meta(texte):
    """(corps, échéance, lien, meta) : comme `decouper_puce`, plus `meta`, ce que la puce dit de ses dates :
    `recu` (AAAA-MM-JJ, le jour où le mail est arrivé), `echeance_mode` ('lue' dans le mail, 'calculee', ou '' si la
    puce ne le dit pas) et `echeance_regle` (la règle de calcul, quand elle est dite). Rien d'inventé : une clé absente
    est une donnée inconnue."""
    s, echeance, lien, meta = unicodedata.normalize('NFC', str(texte or '')).strip(), None, '', {}
    s = parc.etiquettes(s)[0]   # « (impact fort : client attend) », « (effort court) »: read apart, never part of the body
    while True:
        m = None if lien else _suffixe_source(s)
        if m:
            lien, s = m.group(2), s[:m.start()].rstrip()
            continue
        m = SUFFIXE_RECU.search(s)
        if m and 'recu' not in meta:
            try:
                meta['recu'] = dt.date.fromisoformat(m.group(1)).isoformat()
            except ValueError:
                pass
            s = s[:m.start()]
            continue
        m = SUFFIXE_ECHEANCE.search(s)
        if m and echeance is None:
            try:
                echeance = dt.date.fromisoformat(m.group(1)).isoformat()
            except ValueError:
                echeance = ''
            if echeance:
                mode, regle = _origine_echeance(m.group(2))
                if mode:
                    meta['echeance_mode'] = mode
                if regle:
                    meta['echeance_regle'] = regle
            s = s[:m.start()]
            continue
        return s.strip(), echeance or None, lien, meta


def _suffixe_source(s):
    """Le suffixe ` ([texte](lien))` en fin de chaîne, pris au `([` le plus à droite qui le forme : un lien peut porter
    des espaces ou des parenthèses, un lien Markdown plus tôt dans la phrase n'est pas pris."""
    i = len(s)
    while True:
        i = s.rfind('([', 0, i)
        if i < 0:
            return None
        m = SUFFIXE_SOURCE.match(s, i)
        if m:
            return m


def cle_a_toi(texte):
    """Le texte d'un « À toi » tel que la clé le compare : sans ses suffixes, normalisé. Le même calcul des deux côtés,
    la puce d'un passage et `reglees[].texte` (que le kit écrit mot pour mot, suffixes compris)."""
    return normaliser(decouper_puce(texte)[0])


def couper(s, n=TITRE_MAX):
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


# The title of a request (0.2.17): short, read whole. The kit's « titre court : détail » gives it; else the first
# sentence; else the text cut on a word, never inside a command, a path or a code span (« …en tapant /st… » hid the
# very command to type). The full text stays in the line (`texte`), shown in its unfold.
TITRE_COURT = 100
TEXTE_MAX = 1000
FIN_PHRASE = re.compile(r'[.!?](?=\s)')
MOT_TECHNIQUE = re.compile(r'[/`\\]|^\S+\.\w{1,4}$')
COMMANDE = re.compile(r'`(/[a-z][\w-]*(?::[\w-]+)?(?: [^`]{1,40})?)`|(?<![\w/.])(/[a-z][\w-]*:[\w-]+(?: (?![a-zà-ÿ]+\b(?:dans|pour|avec|et|ou|puis|au|à|de)\b)[a-z][\w-]*)?)', re.I)


def titre_court(texte, n=TITRE_COURT):
    t = ' '.join(str(texte or '').split())
    tete = re.split(r'\s*:\s+', t, maxsplit=1)[0]
    if tete != t and 12 <= len(tete) <= n and not ORIGINE_EN_TETE.search(tete) and tete.count('`') % 2 == 0:
        return tete.rstrip(' ,;')
    if len(t) <= n:
        return t
    m = FIN_PHRASE.search(t, 20)
    if m and m.end() <= n:
        return t[:m.end()]
    sortie = t[:n + 1].split(' ')[:-1]   # whole words only: the last piece is cut, or empty
    while sortie and (MOT_TECHNIQUE.search(sortie[-1]) or ' '.join(sortie).count('`') % 2):
        sortie.pop()   # never end on a command, a path or inside a code span
    return ' '.join(sortie).rstrip(' ,;:(«-–') + '…'


def commande_de(texte):
    """The command a request asks to type (« /studio:auto-ingest tri »), or ''."""
    m = COMMANDE.search(str(texte or ''))
    return (m.group(1) or m.group(2)).strip() if m else ''


def cle_de(*parts):
    return hashlib.sha1('\x1f'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:12]


# --- Studios et rôle --------------------------------------------------------------------------------------

def dossier_normal(cwd):
    """Le dossier d'un Studio, sans la copie de travail de l'app (<dépôt>/.claude/worktrees/<nom>), comme nom_projet."""
    # NFC : macOS rend le même dossier tantôt composé, tantôt décomposé (« partagés ») selon la fiche.
    chemin = unicodedata.normalize('NFC', os.path.normpath(os.path.expanduser(cwd)))
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', chemin)
    return m.group(1) if m else chemin


def _est_un_studio(dossier, instantane=None):
    """parc.est_un_studio, the one rule; here the snapshot counts only when it is passed (from the connector)."""
    return parc.est_un_studio(dossier, {} if instantane is None else instantane)

def studios(metas, instantane=None):
    """Les dossiers Studio connus de ce Mac : les dossiers de travail des fiches de session, plus ceux de
    ~/Mon Studio/studios.json, gardés s'ils ont une fiche projet ou un manifeste de Studio. Rien n'est cherché sur le disque.
    `instantane` (depuis le connecteur) : les dossiers de projets-sources.json, gardés quand le Drive refuse de lire."""
    candidats = [m.get('cwd') for m in metas or [] if m.get('cwd')]
    extra = parc.lire_json(_sortie() / 'studios.json', [])
    if isinstance(extra, list):
        candidats += [x for x in extra if isinstance(x, str) and x.strip()]
    vus, sortie = set(), []
    for c in candidats:
        d = dossier_normal(c)
        if d in vus or d in (os.path.normpath(str(parc.HOME)), os.path.normpath(str(_sortie()))):
            continue
        vus.add(d)
        if _est_un_studio(d, instantane):
            sortie.append(d)
    return sorted(sortie)


def identite():
    """Le nom de la personne qui regarde (celui qui rend un projet « à toi »), ou None : voir identite_et_source."""
    return identite_et_source()[0]


def identite_et_source():
    """(nom, source) de la personne qui regarde, le seul point d'entrée de ce nom (audit du 2026-11-18 : un PM sans git
    configuré n'avait aucun projet « à toi », sans un mot). Dans l'ordre :
    - COCKPIT_IDENTITE (essais) ;
    - `reglage` : la clé `pm` de ~/Mon Studio/.parc/cockpit.json, posée par `install.py switch pm "Prénom Nom"` ;
    - `git` : le user.name global de git (la commande, sinon ~/.gitconfig : l'app lance le connecteur sans git) ;
    - `compte` : le nom complet du compte du Mac (`id -F`) ; COCKPIT_COMPTE le remplace dans les essais ;
    - (None, 'aucun')."""
    if 'COCKPIT_IDENTITE' in os.environ:
        v = os.environ['COCKPIT_IDENTITE'].strip()
        return (v, 'reglage') if v else (None, 'aucun')
    reglage = (parc.lire_json(parc.INTERNE / 'cockpit.json', {}) or {})
    nom = reglage.get('pm') if isinstance(reglage, dict) else None
    if isinstance(nom, str) and nom.strip():
        return ' '.join(nom.split()), 'reglage'
    nom = nom_de_git()
    if nom:
        return nom, 'git'
    nom = nom_du_compte()
    if nom:
        return nom, 'compte'
    return None, 'aucun'


def nom_de_git():
    for git in ('git', '/usr/bin/git', '/opt/homebrew/bin/git', '/usr/local/bin/git'):
        try:
            r = subprocess.run([git, 'config', '--global', 'user.name'], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return nom_du_gitconfig(pathlib.Path.home() / '.gitconfig')


def nom_du_compte():
    """Le nom complet du compte macOS (`id -F`, sans shell, 2 s au plus), ou None ; COCKPIT_COMPTE dans les essais."""
    if 'COCKPIT_COMPTE' in os.environ:
        return os.environ['COCKPIT_COMPTE'].strip() or None
    try:
        r = subprocess.run(['/usr/bin/id', '-F'], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    nom = ' '.join((r.stdout or '').split())
    return nom if r.returncode == 0 and nom else None


def nom_du_gitconfig(chemin):
    """Le name de la section [user] du fichier de git : l'app lance le connecteur sans git dans son PATH."""
    try:
        lignes = chemin.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    section = ''
    for l in lignes:
        l = l.strip()
        if l.startswith('['):
            section = l.strip('[]').strip().lower()
        elif section == 'user' and re.match(r'name\s*=', l):
            return l.split('=', 1)[1].strip().strip('"') or None
    return None


def _nom(s):
    return re.sub(r'\s+', ' ', _sans_accents(s).lower()).strip()


def pm_de(dossier):
    """Le PM écrit dans la fiche projet, ou None (ligne absente, à compléter, vide, fiche illisible)."""
    try:
        texte = (pathlib.Path(dossier) / 'projet' / 'fiche-projet.md').read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    return pm_dans(texte)

LIGNE_RESPONSABLE = re.compile(r'^\|\s*\*{0,2}Responsables?\*{0,2}\s*\|\s*([^|]*?)\s*\|', re.M)
# A marking of /cockpit:conflits next to the old value: « ⚠️ *Remplacé le 2026-10-28 par « PM Camille Durand, … »,
# source … — rattrapage du …* ». The replacement is the value now (PM, Q32, 2026-11-15).
REMPLACE_PAR = re.compile(r'Remplacé le [^«]*?par «\s*(.+?)\s*»')
NOM_PM = re.compile(r'([^,;/()]+?)\s*\(\s*PM\s*\)')


def pm_dans(texte):
    """The PM of a project sheet: the « PM » row, its replacement when a marking says the old name was replaced
    (« PM Camille Durand, Léo Durand sur l'infra » gives Camille Durand); without a « PM » row, the names
    marked « (PM) » in the « Responsable » row. None when absent, empty or to fill in."""
    m = LIGNE_PM.search(texte)
    if m:
        v = m.group(1).strip()
        r = REMPLACE_PAR.findall(v)
        if r:
            v = r[-1]
            if re.match(r'(?i)^PM\b', v):
                v = re.sub(r'(?i)^PM\s+', '', v).split(',')[0]
        v = v.split('⚠️')[0].strip()
        if not v or m.group(1).strip().startswith('_'):
            return None
        return v
    m = LIGNE_RESPONSABLE.search(texte)
    noms = [n.strip(' *_') for n in NOM_PM.findall(m.group(1))] if m else []
    return ', '.join(n for n in noms if n) or None


def role(dossier, qui=None, pm=_LIRE):
    """'pm' quand la personne qui regarde est le PM de la fiche, sinon 'membre' (absente, ou sans identité).
    `pm` : le PM déjà lu (ou repris de l'instantané) ; sans lui, la fiche est lue."""
    qui = identite() if qui is None else qui
    pm = pm_de(dossier) if pm is _LIRE else pm
    if not qui or not pm:
        return 'membre'
    # Une case peut porter plusieurs noms (« A / B », « A, B ») ou une précision entre parenthèses.
    noms = re.split(r'\s*(?:,|/|&|\+|\bet\b)\s*', re.sub(r'\([^)]*\)', '', texte_simple(pm)))
    return 'pm' if _nom(qui) in {_nom(n) for n in noms if n.strip()} else 'membre'


# --- ingestion auto ---------------------------------------------------------------------------------------

def sections_nouvelle(texte):
    """Les items « Ce qui est entré » et « À toi de jouer » d'un rapport de passage. Même découpage que
    _sections_nouvelle du plugin ingestion-auto (pre-filtre.py), recopié ici pour ne pas en dépendre ; l'entrée garde
    tout son texte (titre avant « : », le reste en détail)."""
    entres, actions, section = [], [], None
    for l in str(texte).splitlines():
        s = l.strip()
        bas = _sans_accents(s).lower()
        if bas.startswith('a toi de jouer'):
            section = 'actions'
            continue
        if bas.startswith('ce qui est entre'):
            section = 'entres'
            continue
        if not s.startswith('- '):
            if s and section:
                section = None if not s[0].isdigit() else section
            continue
        item = s[2:]
        if section == 'actions':
            actions.append(item)
        elif section == 'entres':
            entres.append(item)
    return entres, actions


def instant(ts):
    """« 2026-11-03T13:25:25Z » (ou avec décalage) en secondes, None si illisible."""
    try:
        return dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def etat_ingestion(dossier):
    e = parc.lire_json(pathlib.Path(dossier) / 'projet' / '.ingestion-auto-state.json', None)
    return e if isinstance(e, dict) else None


def lire_sources(dossier, maintenant):
    """Ce que le calcul lit d'un Studio : le PM de la fiche, les passages de l'ingestion des 14 derniers jours (déjà
    découpés), `reglees`, l'heure de lecture. `refus` : le système a refusé une lecture (connecteur lancé par l'app,
    sans accès au Drive) ; un fichier absent ou abîmé n'est pas un refus."""
    projet, refus = pathlib.Path(dossier) / 'projet', False
    try:
        pm = pm_dans((projet / 'fiche-projet.md').read_text(encoding='utf-8'))
    except ABSENT + (UnicodeDecodeError,):
        pm = None
    except OSError:
        pm, refus = None, True
    try:
        ing = json.loads((projet / '.ingestion-auto-state.json').read_text(encoding='utf-8'))
    except ABSENT + (ValueError,):
        ing = None
    except OSError:
        ing, refus = None, True
    ing = ing if isinstance(ing, dict) else {}
    passages = []
    derniere = max([i for i in (instant(n.get('ts')) for n in ing.get('nouvelles') or [] if isinstance(n, dict))
                    if i is not None], default=None)
    for n in ing.get('nouvelles') or []:
        t = instant(n.get('ts')) if isinstance(n, dict) else None
        if t is not None and maintenant - t <= LECTURE_S:
            entres, actions = sections_nouvelle(n.get('texte') or '')
            passages.append({'ts': t, 'entres': entres, 'actions': actions})
    reglees = [dict({'ts': x.get('ts'), 'texte': x['texte']}, **{k: x[k] for k in CHAMPS_REGLEE if x.get(k)})
               for x in ing.get('reglees') or [] if isinstance(x, dict) and x.get('texte')]
    # The conflicts register alone: a failure to read it costs only the « Conflits » tab (None: « illisible pour
    # l'instant »), never the rest of the Studio, which stays read live.
    try:
        conflits = lire_texte(projet / 'conflits.md')['texte']
    except ABSENT:
        conflits = ''
    except OSError:
        conflits = None
    # What the PM has seen of it and the reminder's thresholds (projet/.conflits, written by /cockpit:conflits): kept
    # with the register in the snapshot, for when the Drive refuses the connector.
    vu = parc.lire_json(projet / '.conflits' / 'vu.json', None)
    reglages = parc.lire_json(projet / '.conflits' / 'reglages.json', None)
    # The backlog's contradictions and decisions (/backlog:nettoyer), parsed, kept for the same reason.
    try:
        backlog = lire_backlog(dossier)
    except OSError:
        backlog = None
    s = {'pm': pm, 'ingestion': bool(ing), 'ingestion_derniere': derniere, 'passages': sorted(passages, key=lambda n: n['ts']),
         'reglees': reglees, 'lu': maintenant, 'refus': refus, 'conflits': conflits,
         'conflits_vu': vu if isinstance(vu, dict) else None, 'conflits_reglages': reglages if isinstance(reglages, dict) else None,
         'backlog': backlog}
    if not refus:
        s['fichiers'] = textes_des_entrees(dossier, s['passages'], maintenant)
    return s


# --- the files of the Studio that « Lire » unfolds --------------------------------------
# Text only, read-only, capped: the page shows them escaped, never as HTML. The connector cannot read the Drive (macOS
# refuses it), so the calculation run outside it (hook) keeps the text of the files the day's entries point to in the
# snapshot (projets-sources.json, `fichiers`), as it does for the Studio's sources.
EXTENSIONS_TEXTE = frozenset({'md', 'txt', 'csv'})
LIRE_MAX = 200 * 1024
FICHIERS_MAX = 2 * 1024 * 1024   # per Studio, in the snapshot


def texte_autorise(chemin):
    nom = os.path.basename(chemin)
    return '.' in nom.strip('.') and nom.rsplit('.', 1)[1].lower() in EXTENSIONS_TEXTE


def lire_texte(reel):
    """{texte, tronque, taille} of a text file, cut at LIRE_MAX bytes. OSError when it cannot be read."""
    with open(reel, 'rb') as f:
        brut = f.read(LIRE_MAX + 1)
        taille = os.fstat(f.fileno()).st_size
    return {'texte': brut[:LIRE_MAX].decode('utf-8', errors='replace'), 'tronque': len(brut) > LIRE_MAX, 'taille': taille}


def chemin_dans_le_studio(dossier, fichier):
    """(relative path, resolved path) of a text file of the Studio, or ValueError: relative, without `..`, a text
    extension, and still in the Studio once links are resolved (same rules as `ouvrir`)."""
    chemin = _charger_matin()._chemin(fichier)
    if not chemin:
        raise ValueError('chemin de fichier invalide')
    if not texte_autorise(chemin):
        raise ValueError('seuls les fichiers texte (md, txt, csv) se lisent dans la page')
    base = os.path.realpath(dossier)
    reel = os.path.realpath(os.path.join(dossier, chemin))
    if not reel.startswith(base.rstrip(os.sep) + os.sep) or not texte_autorise(reel):
        raise ValueError('le fichier sort du dossier du Studio')
    return chemin, reel


def textes_des_entrees(dossier, passages, maintenant, autres=()):
    """{relative path: {texte, tronque, taille}} of the text files the entries since the last working day point to,
    then those of the requests (« À toi ») of the runs read (0.2.17: their « Lire » in the board), then `autres` (the
    files the board's questions cite), within FICHIERS_MAX."""
    debut = debut_fenetre(maintenant)
    liens = [decouper_puce(x)[2] for n in passages if n['ts'] >= debut for x in n['entres']]
    liens += [decouper_puce(x)[2] for n in passages for x in n.get('actions') or []]
    sortie, total = {}, 0
    for lien in liens + list(autres):
        if not lien or lien.startswith('https://') or lien in sortie:
            continue
        try:
            chemin, reel = chemin_dans_le_studio(dossier, lien)
            lu = lire_texte(reel)
        except (ValueError, OSError):
            continue
        if total + len(lu['texte']) > FICHIERS_MAX:
            return sortie
        total += len(lu['texte'])
        sortie[chemin] = lu
    return sortie


def fichiers_cites_au_tableau(e, dossier):
    """The files the board's questions of this Studio cite (parc: depli.fichiers of the lines whose session runs in it)."""
    nfc = lambda x: os.path.normpath(unicodedata.normalize('NFC', str(x or '')))
    return [f for l in (e.get('tableau') or []) + (e.get('anciennes') or []) if l.get('dossier') and nfc(l['dossier']) == nfc(dossier)
            for f in ((l.get('depli') or {}).get('fichiers') or [])]


def lire_fichier(dossier, fichier, metas=None):
    """The text of a file of a known Studio, for « Lire » (tool `lire` of the connector, read-only): read directly, else
    from the snapshot when the Drive refuses the connector. ValueError otherwise."""
    d = dossier_du_matin(dossier, metas)
    chemin, reel = chemin_dans_le_studio(d, fichier)
    if os.path.isdir(reel):
        raise ValueError('ce chemin est un dossier')
    try:
        lu = lire_texte(reel)
    except ABSENT:
        raise ValueError('fichier introuvable dans le Studio')
    except OSError:
        gardee = ((lire_instantane().get(d) or {}).get('fichiers') or {}).get(chemin)
        if not isinstance(gardee, dict) or not isinstance(gardee.get('texte'), str):
            raise ValueError("fichier pas encore lu hors de l'app : réessaie dans quelques minutes")
        lu = gardee
    return {'dossier': d, 'fichier': chemin, 'texte': lu['texte'], 'tronque': bool(lu.get('tronque')),
            'taille': lu.get('taille')}

# --- the conflicts tab of a project view ---------------------------------------------------------------
# Read-only, without LLM: the open cases of the Studio's register (projet/conflits.md) and the session that handles
# them, found by its title « <Projet> · Conflits Studio » (a title that starts so counts: « … (rattrapage) »), the most
# recent when there are several. No answer from the page: the PM answers in that session.
SESSION_CONFLITS = 'Conflits Studio'


def _charger_registre():
    """The conflicts skill's register reader: its copy next to this file (~/Mon Studio/.parc), else the plugin's."""
    for chemin in (ICI / 'registre_conflits.py', ICI.parent.parent / 'conflits' / 'scripts' / 'registre.py'):
        if chemin.exists():
            spec = importlib.util.spec_from_file_location('registre_conflits', chemin)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def titre_session_conflits(dossier):
    return f"{parc.nom_projet(dossier)} · {SESSION_CONFLITS}"


def est_session_conflits(titre, dossier):
    """True for « <Projet> · Conflits Studio… »: the Studio's short name exactly, then « Conflits Studio », any suffix
    after (« (rattrapage) »). « Alpha » never takes the session of « Client Alpha »."""
    avant, sep, apres = (titre or '').partition(' · ')
    nom = ' '.join(normaliser(parc.nom_projet(dossier)).split())
    court = ' '.join(normaliser(avant).split())
    return bool(sep and court and court == nom
                and normaliser(apres).strip().startswith(normaliser(SESSION_CONFLITS)))


def session_conflits(dossier, metas):
    """The session « <Projet> · Conflits Studio » of this Studio, the most recent; one opened in the Studio first,
    archived ones last. None when there is none."""
    d = dossier_normal(dossier)
    siennes = [m for m in metas or [] if m.get('id') and est_session_conflits(m.get('titre'), d)]
    if not siennes:
        return None
    m = max(siennes, key=lambda m: (_dans(m.get('cwd'), d), not m.get('archivee'), m.get('activite') or 0))
    return {'sessionId': m['id'], 'titre': m.get('titre') or titre_session_conflits(d)}


RETARD_COPIE_S = 60


def activite_session_conflits(dossier, metas):
    """The last activity (seconds) of this Studio's conflicts sessions, 0 without one."""
    d = dossier_normal(dossier)
    return max([m.get('activite') or 0 for m in metas or [] if m.get('id') and not m.get('archivee')
                and est_session_conflits(m.get('titre'), d)], default=0)


def _vu_et_reglages(reg, d, instantane=None):
    """(the largest case number the PM has seen, the reminder's thresholds) of a Studio: read live, else from the
    snapshot, else 0 and the defaults."""
    gardee = None
    vu = parc.lire_json(pathlib.Path(d) / 'projet' / '.conflits' / 'vu.json', None)
    reglages = parc.lire_json(pathlib.Path(d) / 'projet' / '.conflits' / 'reglages.json', None)
    if vu is None or reglages is None:
        gardee = (lire_instantane() if instantane is None else instantane).get(d) or {}
        vu = vu if vu is not None else gardee.get('conflits_vu')
        reglages = reglages if reglages is not None else gardee.get('conflits_reglages')
    n = (vu or {}).get('vu') if isinstance(vu, dict) else None
    n = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0
    seuils = dict(getattr(reg, 'SEUILS', {'relance_cas': 10, 'relance_jours': 14}))
    for k in list(seuils):
        v = (reglages or {}).get(k) if isinstance(reglages, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 365:
            seuils[k] = v
    return n, seuils


# --- the conflicts a session is settling now, and the backlog's decisions (2026-11-19) ---------------------------
# The register is not the only place conflicts are handled: /backlog:nettoyer writes its contradictions to
# backlog/_contexte/contradictions.md, records each PM decision in decisions-pm.md, and asks its questions one at a
# time in its session, which the board already holds as a question line. The tab shows all three, read-only.
MARQUEURS_TRI = ('nettoyage du contexte', 'backlog:nettoyer', 'contradictions', 'conflits')   # normalised title parts
TRI_ACTIF_S = 24 * 3600               # a settling session is « en cours » when active within a day
SESSION_ID = re.compile(r'^local_[0-9a-f-]{36}$')
BACKLOG_CONTRADICTIONS = ('backlog', '_contexte', 'contradictions.md')
BACKLOG_DECISIONS = ('backlog', '_contexte', 'decisions-pm.md')


def sessions_qui_tranchent(dossier, metas):
    """The non-archived sessions of a Studio that settle conflicts: « <Projet> · Conflits Studio… », or, opened in the
    Studio's folder, a title that holds one of MARQUEURS_TRI. Most recently active first."""
    d = dossier_normal(dossier)
    sortie = []
    for m in metas or []:
        if not m.get('id') or m.get('archivee'):
            continue
        titre = m.get('titre') or ''
        n = normaliser(titre)
        if est_session_conflits(titre, d) or (_dans(m.get('cwd'), d) and any(k in n for k in MARQUEURS_TRI)):
            sortie.append(m)
    return sorted(sortie, key=lambda m: -(m.get('activite') or 0))


def _texte_de_question(l):
    """(question in full, short options) of a board line, whichever shape it has: the computed board's line
    (type 'question': titre, detail = the answers) or the parc line (complet / detail = the whole statement)."""
    if l.get('type') == 'question' and 'affiche_titre' not in l:
        return texte_simple(l.get('titre') or ''), texte_simple(l.get('detail') or '')
    texte = texte_simple(l.get('detail') or l.get('complet') or l.get('titre') or l.get('affiche_titre') or '')
    options = l.get('choix_libelles')
    if isinstance(options, list):
        options = ' · '.join(texte_simple(o if isinstance(o, str) else (o or {}).get('libelle') or (o or {}).get('texte') or '')
                             for o in options)
    else:
        options = ''
    # A menu's statement holds its answers after the question mark (« … que voit-il ? Écran d'attente : … »): the
    # question alone in bold, the answers in small.
    if not options.strip(' ·'):
        m = re.match(r'^(.+?\?)\s+(\S.*)$', texte, re.S)
        if m:
            texte, options = m.group(1), m.group(2)
    return texte, options.strip(' ·')


def questions_en_cours(dossier, metas, questions):
    """The pending board questions of a Studio asked by one of its settling sessions:
    [{'question', 'options', 'session', 'session_titre', 'depuis'}] (`depuis` as the board gives it)."""
    tranchent = {m['id']: m for m in sessions_qui_tranchent(dossier, metas)}
    sortie = []
    for l in questions or []:
        if not isinstance(l, dict) or l.get('type') in ('a_toi', 'reunion', 'entree', 'verifier', 'conflits'):
            continue
        sid = next((x for x in (session_de_ligne(l), l.get('source'), l.get('session')) if x in tranchent), None)
        if not sid:
            continue
        texte, options = _texte_de_question(l)
        if texte:
            sortie.append({'question': texte, 'options': options, 'session': sid,
                           'session_titre': tranchent[sid].get('titre') or '', 'depuis': l.get('depuis')})
    return sortie


def _date_backlog(iso):
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', str(iso or ''))
    return f'{m.group(3)}/{m.group(2)}/{m.group(1)}' if m else None


def lire_backlog(dossier):
    """What /backlog:nettoyer left in the Studio: {'releve': 'JJ/MM/AAAA' | None, 'contradictions': n, 'decisions':
    [{'sujet', 'date', 'choix'}]}, None when neither file exists. OSError when one cannot be read. Lenient: a line it
    does not understand is skipped."""
    racine, trouve, sortie = pathlib.Path(dossier), False, {'releve': None, 'contradictions': 0, 'decisions': []}
    try:
        texte = lire_texte(racine.joinpath(*BACKLOG_CONTRADICTIONS))['texte']
        trouve = True
        m = re.search(r'relevé du (\d{4}-\d{2}-\d{2})', texte.split('\n', 1)[0])
        sortie['releve'] = _date_backlog(m.group(1)) if m else None
        sortie['contradictions'] = len(re.findall(r'(?m)^###\s+\d+\.\s+\S', texte))
    except ABSENT:
        pass
    try:
        texte = lire_texte(racine.joinpath(*BACKLOG_DECISIONS))['texte']
        trouve = True
        for ligne in texte.split('\n'):
            m = re.match(r'^\s*\d+\.\s+(\d{4}-\d{2}-\d{2})\s*·\s*(.+)$', ligne)
            gras = re.search(r'\*\*(.+?)\*\*', m.group(2)) if m else None
            if not gras:
                continue
            sujet = re.split(r'\s*:\s*\*\*', m.group(2), 1)[0]
            sujet = re.sub(r'\s*\((?:la )?contradictions?[^)]*\)', '', sujet).strip(' ,;:')
            if sujet:
                sortie['decisions'].append({'sujet': couper(sujet, 200), 'date': _date_backlog(m.group(1)),
                                            'choix': couper(gras.group(1).strip(' .'), 200)})
    except ABSENT:
        pass
    sortie['decisions'] = sortie['decisions'][:200]
    return sortie if trouve else None


def _backlog_du_studio(d, instantane=None):
    """lire_backlog, else the snapshot's copy when the Drive refuses it; None when unknown. Never an exception."""
    try:
        return lire_backlog(d)
    except OSError:
        gardee = ((lire_instantane() if instantane is None else instantane).get(d) or {}).get('backlog')
    except Exception:
        return None
    return gardee if isinstance(gardee, dict) and isinstance(gardee.get('decisions'), list) else None


def conflits_du_projet(dossier, metas=None, instantane=None, depuis_connecteur=False, questions=None, maintenant=None):
    """The conflicts tab: what the register gives (conflits_du_registre), plus what is being settled elsewhere:
    'en_cours' (pending board questions of the Studio's settling sessions: `questions` = the board lines of this Studio),
    'sessions_actives' (settling sessions active within a day) and 'backlog' ({'releve', 'contradictions', 'decisions'}
    from backlog/_contexte), whose decisions join 'journal' (« Tranché »). A failure of these costs only these fields."""
    sortie = conflits_du_registre(dossier, metas, instantane, depuis_connecteur)
    d = dossier_normal(dossier)
    maintenant = time.time() if maintenant is None else maintenant
    sortie.update(en_cours=[], sessions_actives=[], backlog=None)
    try:
        sortie['en_cours'] = questions_en_cours(d, metas, questions)
        sortie['sessions_actives'] = [{'sessionId': m['id'], 'titre': m.get('titre') or '', 'activite': m.get('activite') or 0}
                                      for m in sessions_qui_tranchent(d, metas)
                                      if maintenant - (m.get('activite') or 0) <= TRI_ACTIF_S]
    except Exception:
        pass
    try:
        b = _backlog_du_studio(d, instantane)
        if b:
            sortie['backlog'] = {'releve': b.get('releve'), 'contradictions': int(b.get('contradictions') or 0),
                                 'decisions': len(b['decisions'])}
            ajoutes = [{'sujet': x['sujet'], 'date': x['date'] or '', 'par': 'le PM', 'choix': x['choix'], 'reponse': '',
                        'reprise': False, 'origine': 'backlog'} for x in b['decisions']]
            tous = sorted(sortie['journal'] + ajoutes, key=lambda x: _iso_du_passage(x.get('date')), reverse=True)
            sortie['journal'] = tous[:JOURNAL_CONFLITS]
            sortie['tranches'] += len(ajoutes)
    except Exception:
        sortie['backlog'] = None
    return sortie


def conflits_du_registre(dossier, metas=None, instantane=None, depuis_connecteur=False):
    """The conflicts tab: {'ouverts': [...], 'illisibles': n, 'session': {...} | None, 'titre_session', 'lu',
    'nouveaux' (open cases the PM has not been shown yet: the tab's dot), 'relance' and 'raison' (the reminder in
    « Ce qui t'attend »), 'a_traiter', 'jours', 'seuils'}.
    `lu` is False when the register could not be read (the Drive refused, and no snapshot holds it)."""
    d = dossier_normal(dossier)
    sortie = {'ouverts': [], 'illisibles': 0, 'session': session_conflits(d, metas), 'titre_session':
              titre_session_conflits(d), 'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False,
              'raison': '', 'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': None,
              'journal': [], 'tranches': 0, 'verification': None, 'premiere': None, 'relecture': None,
              'copie_le': None, 'en_retard': False}
    reg = _charger_registre()
    if reg is None:
        sortie['lu'] = False
        return sortie
    try:
        texte = lire_texte(pathlib.Path(d) / 'projet' / 'conflits.md')['texte']
    except ABSENT:
        texte = ''
    except OSError:
        entree = (lire_instantane() if instantane is None else instantane).get(d) or {}
        gardee = entree.get('conflits')
        if not isinstance(gardee, str):
            sortie['lu'] = False
            return sortie
        texte = gardee
        # The copy of the register, from Mon Studio's snapshot. conflits.py refreshes it at each write; when the
        # conflicts session worked after the copy, the tab says the copy may lag instead of looking empty.
        copie = entree.get('conflits_copie') or entree.get('lu')
        if isinstance(copie, (int, float)) and not isinstance(copie, bool):
            sortie['copie_le'] = time.strftime('%d/%m %H:%M', time.localtime(copie))
            sortie['en_retard'] = activite_session_conflits(d, metas) > copie + RETARD_COPIE_S
    r = reg.lire(texte)
    sortie['illisibles'] = len(r['illisibles'])
    vu = 0
    if hasattr(reg, 'etat_du_registre'):
        vu, seuils = _vu_et_reglages(reg, d, instantane)
        x = reg.etat_du_registre(texte, vu, seuils)
        sortie.update({k: x[k] for k in ('nouveaux', 'relance', 'raison', 'a_traiter', 'jours', 'seuils')})
    ouverts = [c for c in r['cas'] if c['etat'] == 'ouvert']
    titres = {}
    if ouverts and hasattr(reg, 'titres_du_studio'):
        try:
            titres = reg.titres_du_studio(d)
        except OSError:
            titres = {}
    # The tab shows no code at all (PM, 2026-11-10): a code's title in its place when the Studio gives one; places in
    # words. The register keeps the codes.
    e = (lambda x: reg.sans_codes(x, titres)) if hasattr(reg, 'sans_codes') else (lambda x: x)
    lisible = getattr(reg, 'chemin_lisible', lambda x: x)
    v = lambda x: dict(x, texte=e(x['texte']), source=lisible(x['source']))
    sortie['ouverts'] = [{'id': c['id'], 'sujet': e(c['sujet']), 'ancienne': v(c['ancienne']), 'nouvelle': v(c['nouvelle']),
                          'communique': c['communique'], 'detecte': c['detecte'], 'nouveau': c['n'] > vu,
                          'niveau': (c.get('file') or {}).get('niveau', 'arbitrage')} for c in ouverts]
    # The journal of the register (PM, Q12, 2026-11-15), like the project's journal of actions: what was settled,
    # when, by whom; and « Studio à jour depuis le … », the last complete pass.
    sortie['dernier_passage'] = r.get('dernier_passage')
    if hasattr(reg, 'tranches'):
        tous = reg.tranches(texte)
        if tous and not titres and hasattr(reg, 'titres_du_studio'):
            try:
                titres = reg.titres_du_studio(d)
            except OSError:
                titres = {}
        sortie['tranches'] = len(tous)
        sortie['journal'] = [{'sujet': e(x['sujet']), 'date': x['date'], 'par': x['par'], 'choix': x['choix'],
                              'reponse': e(x['reponse']), 'reprise': x['ajoute_par'] == 'reprise'}
                             for x in tous[:JOURNAL_CONFLITS]]
    # Three states for an empty tab (PM, Q13): never checked, checked without a conflict, decisions in the journal.
    sortie['verification'] = 'verifie' if sortie['dernier_passage'] else 'jamais'
    if sortie['dernier_passage']:
        try:
            sortie['relecture'] = relecture_du_studio(d, sortie['dernier_passage'], instantane)
        except Exception:
            sortie['relecture'] = None     # a failure costs only these words: the tab then gives the last pass's date
    if sortie['verification'] == 'jamais':
        # Never a survey from the connector (the page's call): only the estimate kept by the last computation.
        try:
            sortie['premiere'] = premiere_verification(d, depuis_connecteur or instantane is not None)
        except Exception:
            sortie['premiere'] = None      # a failure costs only the first check's words, never the tab nor the board
        sortie['texte_premiere'] = texte_premiere(sortie)
        if not sortie['session']:
            sortie['session_studio'] = session_du_studio(d, metas)[0]
    return sortie


# --- what became of the re-read since the last complete pass (2026-11-17) ---------------------------------------
# « Dernier passage » is the date of the last complete pass, not of the last look. The Monday pass of the morning point
# notes what it did of each checked Studio in ~/Mon Studio/.parc/conflits-semaine.json (matin.py); the tab says it in
# words, with its reason and its date, and writes « à jour » only when a re-read found nothing or was judged whole.
INGESTION_ACTIVE_S = 8 * 86400        # the same as conflits.INGESTION_ACTIVE_S (kept in step by a test)


def _jour_fr(iso):
    """'2026-11-16…' → '16/11' ; '' when unreadable."""
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', str(iso or ''))
    return f'{m.group(3)}/{m.group(2)}' if m else ''


def _iso_du_passage(jjmmaaaa):
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', str(jjmmaaaa or ''))
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''


def ingestion_recente(d, instantane=None, maintenant=None):
    """True when the automatic ingestion gave a news within INGESTION_ACTIVE_S (the Monday pass then skips the Studio),
    False when not, None when it cannot be known (the Drive refused and no snapshot holds it)."""
    maintenant = time.time() if maintenant is None else maintenant
    try:
        ing = json.loads((pathlib.Path(d) / 'projet' / '.ingestion-auto-state.json').read_text(encoding='utf-8'))
        nouvelles = ing.get('nouvelles') if isinstance(ing, dict) else None
        derniere = max([i for i in (instant(n.get('ts')) for n in nouvelles or [] if isinstance(n, dict))
                        if i is not None], default=None)
    except ABSENT + (ValueError,):
        return False
    except OSError:
        gardee = (lire_instantane() if instantane is None else instantane).get(d) or {}
        if 'ingestion_derniere' not in gardee:
            return None
        derniere = gardee.get('ingestion_derniere')
    return isinstance(derniere, (int, float)) and maintenant - derniere <= INGESTION_ACTIVE_S


def relecture_du_studio(d, dernier_passage, instantane=None, maintenant=None):
    """{'etat', 'a_jour', 'le' (JJ/MM of the Monday pass, or ''), 'sujets', 'texte'} for a Studio checked once.
    `etat`: 'rien' (re-read, nothing new), 'faite' (re-read and judged whole), 'remise' (subjects handed to the morning
    task, not all judged), 'ingestion' (skipped: automatic ingestion active), 'trop' (over the morning point's ceiling),
    'erreur', 'aucune' (no re-read since the last complete pass). `a_jour` only for 'rien' and 'faite'. `texte` is ''
    for 'ingestion' and 'aucune': the tab never speaks of a Monday re-read that is no longer promised."""
    passage = _jour_fr(_iso_du_passage(dernier_passage))
    semaine = parc.lire_json(parc.INTERNE / 'conflits-semaine.json', {})
    semaine = semaine if isinstance(semaine, dict) else {}
    le_iso = str(semaine.get('le') or '')[:10]
    studios = semaine.get('studios') if isinstance(semaine.get('studios'), dict) else {}
    x = studios.get(d) if isinstance(studios.get(d), dict) else None
    # A complete pass made after that Monday replaces what the Monday said.
    if x and not (le_iso and le_iso >= _iso_du_passage(dernier_passage)):
        x = None
    le = _jour_fr(le_iso) if x else ''
    n = x.get('sujets') if x and isinstance(x.get('sujets'), int) and not isinstance(x.get('sujets'), bool) else 0
    sujets = f"{n} sujet{'s' if n > 1 else ''} nouveau{'x' if n > 1 else ''}"
    dernier = f'Dernier passage complet : le {passage}.'
    etat = x.get('etat') if x else 'aucune'
    if etat == 'ouverte':
        etat = 'faite' if _iso_du_passage(dernier_passage) >= le_iso else 'remise'
    if etat == 'rien':
        texte = f'Relu le {le} : rien de nouveau depuis le passage complet du {passage}.'
    elif etat == 'faite':
        texte = f'Relu le {le} : les nouveautés sont jugées.'
    elif etat == 'remise':
        texte = f'Relecture du {le} pas finie : {sujets} remis au point du matin, pas tous jugés. {dernier}'
    elif etat == 'ingestion':
        texte = ''     # the Monday re-read is no longer promised (2026-11-17): the check moves into the ingestion
    elif etat == 'trop':
        texte = (f"Relecture du {le} pas faite : {sujets}, plus que ce qu'un point du matin relit. Rien de relu "
                 f'depuis. {dernier}')
    elif etat == 'erreur':
        texte = f"Relecture du {le} en échec : le Studio n'a pas pu être relu. {dernier}"
    else:
        etat, texte = 'aucune', ''     # nothing re-read since the last complete pass: the tab says nothing of it
    return {'etat': etat, 'a_jour': etat in ('rien', 'faite'), 'le': le, 'sujets': n, 'texte': texte}


# --- the first check of a Studio (PM, Q14, 2026-11-15) -------------------------------------------------------
# Nothing at installation. A Studio whose register has no « Dernier passage » was never checked: for its PM, one line
# in « Ce qui t'attend », with its cost, until he does it or closes it; the same action in the empty « Conflits » tab.
# Its button opens « <Projet> · Conflits Studio », or, without it, the Studio's most recent session with
# « /cockpit:conflits rattrapage » to paste, which creates it. One catch-up per project, once; then the Monday pass of the
# morning point (Q18) or the automatic ingestion takes over. « Préparer l'aperçu » (tab) runs it on demand, validated later.
JOURNAL_CONFLITS = 60                 # settled cases shown in the tab, the most recent first
ESTIMATION_S = 7 * 86400             # the cost of a first check is computed again after a week
# The cost model of conflits.py the kept estimate was made with: an estimate of an older model is never shown (0.3.3:
# the first relevé measured on a real Studio, 2026-11-18, replaced the 2026-11-10 model).
ESTIMATION_BAREME = 2
COLLER_VERIFIER = '/cockpit:conflits rattrapage'
_estimation_faite = {'n': 0}          # one survey per computation at most: it reads the whole Studio (2 to 6 s)


def _estimations_chemin():
    return parc.INTERNE / 'conflits-estimations.json'


def _charger_releve():
    """The conflicts survey (no LLM): its copy next to this file (~/Mon Studio/.parc), else the plugin's."""
    for chemin in (ICI / 'conflits.py', ICI.parent.parent / 'conflits' / 'scripts' / 'conflits.py'):
        if chemin.exists():
            spec = importlib.util.spec_from_file_location('conflits_releve', chemin)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def estimation_premiere(dossier, maintenant=None, calculer=False):
    """What a first check of this Studio would ask and cost, kept a week in ~/Mon Studio/.parc: {'t', 'sujets',
    'decisions', 'minutes', 'pourcent', 'pourcent_preparer', 'au_dessus'}, or None. Computed (the survey, without
    LLM) only when `calculer` and outside the connector, one Studio per computation."""
    maintenant = time.time() if maintenant is None else maintenant
    d = dossier_normal(dossier)
    cache = parc.lire_json(_estimations_chemin(), {})
    cache = cache if isinstance(cache, dict) else {}
    x = cache.get(d) if isinstance(cache.get(d), dict) and cache[d].get('bareme') == ESTIMATION_BAREME else None
    if x and maintenant - (x.get('t') or 0) < ESTIMATION_S or not calculer or _estimation_faite['n']:
        return x
    m = _charger_releve()
    if m is None or not m.est_un_studio(d):
        return x
    _estimation_faite['n'] += 1
    try:
        c = m.releve(d)['cout']
        p = m.cout_preparer(c)
    except Exception:
        return x
    x = {'t': maintenant, 'bareme': ESTIMATION_BAREME, 'sujets': c['sujets'], 'decisions': c['decisions_estimees'],
         'minutes': m.minutes_pm(0, c['decisions_estimees']), 'pourcent': c['pourcent_semaine'],
         'pourcent_preparer': p['pourcent_semaine'], 'au_dessus': bool(c['au_dessus_du_plafond'])}
    cache[d] = x
    try:
        parc.ecrire_atomique(_estimations_chemin(), json.dumps(cache, ensure_ascii=False, indent=1))
    except OSError:
        pass
    return x


def premiere_verification(dossier, depuis_connecteur=False, maintenant=None):
    """What the PM is told about the first check: {'estimation', 'pret' (a preview prepared ahead, waiting),
    'reprise' (decisions settled by hand, to take up first), 'studio' (False: not a Studio, no check possible)}."""
    d = dossier_normal(dossier)
    racine = pathlib.Path(d)
    studio = (racine / '.claude' / '.studio-manifest.json').exists()
    pret = parc.lire_json(racine / 'projet' / '.conflits' / 'pret.json', None)
    if not (isinstance(pret, dict) and isinstance(pret.get('plan'), str) and os.path.exists(pret['plan'])
            and all(isinstance(pret.get(k), int) for k in ('marquages', 'evidents', 'arbitrages', 'minutes'))):
        pret = None
    try:
        reprise = any(re.match(r'^rattrapage-\d{4}-\d{2}-\d{2}$', p.name) and p.is_dir() for p in (racine / 'projet').iterdir())
    except OSError:
        reprise = False
    return {'studio': studio, 'pret': pret, 'reprise': reprise,
            'estimation': estimation_premiere(d, maintenant, calculer=studio and not depuis_connecteur and not pret)}


def _fr(x):
    return f'{x:.2f}'.replace('.', ',') if isinstance(x, float) else str(x)


def texte_premiere(c):
    """The words of the first check, for the board and the tab: what it is, what waits, how long, what it costs."""
    p = c.get('premiere') or {}
    morceaux = ["Le premier relevé des conflits de ce Studio : il correspond à l'onglet « Conflits » de la page du projet."]
    if p.get('reprise'):
        morceaux.append("Les décisions déjà tranchées à la main sont reprises d'abord, sans être reposées.")
    x, e = p.get('pret'), p.get('estimation')
    if x:
        morceaux.append(f"Aperçu prêt : {x['arbitrages']} vraie{'s' if x['arbitrages'] > 1 else ''} question"
                        f"{'s' if x['arbitrages'] > 1 else ''}, {x['evidents']} cas évident{'s' if x['evidents'] > 1 else ''} "
                        f"en liste, {x['marquages']} marquage{'s' if x['marquages'] > 1 else ''} sûr{'s' if x['marquages'] > 1 else ''} "
                        f"d'un seul go ; environ {x['minutes']} min.")
    elif e:
        morceaux.append(f"Environ {e['decisions']} question{'s' if e['decisions'] > 1 else ''} à trancher "
                        f"({e['sujets']} sujets relus), environ {e['minutes']} min ; coût estimé "
                        f"{_fr(float(e['pourcent']))} % de ta semaine"
                        + (", au-dessus du plafond d'un lancement : un dossier à la fois." if e.get('au_dessus') else '.'))
    if not x:
        morceaux.append("Dans l'onglet « Conflits », « Préparer l'aperçu » le fait tourner maintenant, sur go du coût ; tu valides ensuite quand tu veux.")
    morceaux.append("Une seule fois ; ensuite l'ingestion automatique inscrit les nouveaux cas ; une relecture reste "
                    "possible quand tu veux.")
    return ' '.join(morceaux)


def ligne_verifier_conflits(dossier, c, etat, maintenant, metas):
    """The one line of a never-checked Studio in « Ce qui t'attend » (PM, Q14), or None. Noted in the state: closed
    by the PM, it never comes back; closed by its source once « Dernier passage » is in the register."""
    cle = cle_de(dossier, 'conflits', 'verifier')
    ligne = etat.get(cle)
    if c.get('verification') != 'jamais' or not c.get('lu', True):
        if c.get('verification') == 'verifie' and ligne and not ligne['fermee']:
            ligne.update(fermee=maintenant, par='source')
        return None
    if not (c.get('premiere') or {}).get('studio'):
        return None
    titre = 'Vérifier les conflits du Studio, une fois'
    ligne = _noter(etat, cle, dossier, 'verifier', titre, maintenant)
    if ligne['fermee']:
        return None
    ligne['vue'] = maintenant
    if c.get('session'):
        sid, repli, copier = c['session']['sessionId'], False, ''
    else:
        sid, repli = session_du_studio(dossier, metas)
        copier = COLLER_VERIFIER if sid else ''
    detail = texte_premiere(c) + (f" Dans la session « {c['titre_session']} »." if c.get('session') else
                                  f" Le bouton ouvre la session la plus récente du Studio, « {COLLER_VERIFIER} » copié : "
                                  f"colle-le, elle crée « {c['titre_session']} »." if sid else
                                  f" Ouvre une session dans le dossier du Studio et lance « {COLLER_VERIFIER} ».")
    return {'cle': cle, 'type': 'verifier', 'titre': titre, 'detail': couper(detail, 600), 'depuis': ligne['premiere'],
            'session': sid, 'repli': repli, 'copier': copier, 'dossier': dossier}


def ligne_relance_conflits(dossier, metas, maintenant, instantane=None, c=None, questions=None):
    """The reminder line of a Studio's conflicts in « Ce qui t'attend » (PM, 2026-11-10), or None: from 10 open cases
    or 14 days without a treatment (thresholds per Studio, set in the conflicts session), with the button that opens
    « <Projet> · Conflits Studio » (or, without it, the Studio's most recent session). No Slack, no mail."""
    c = conflits_du_projet(dossier, metas, instantane, questions=questions) if c is None else c
    if not c.get('relance'):
        return None
    sid, repli = (c['session']['sessionId'], False) if c.get('session') else session_du_studio(dossier, metas)
    detail = (f"À trancher dans la session « {c['titre_session']} »" + ('' if c.get('session') else
              ' (à créer : ouvre une session dans le dossier du Studio et lance /cockpit:conflits)')
              + f". Relance à partir de {c['seuils']['relance_cas']} conflits ou de {c['seuils']['relance_jours']} jours "
              "sans traitement, réglable dans cette session.")
    return {'cle': cle_de(dossier, 'conflits', 'relance'), 'type': 'conflits',
            'titre': couper(f"Conflits du Studio : {c['raison']}"), 'detail': couper(detail, 400),
            'depuis': maintenant - c.get('jours', 0) * 86400, 'session': sid, 'repli': repli, 'dossier': dossier}


def _lignes_du_projet(tableau, dossier):
    """The board lines of one Studio (their `projet` is the Studio's folder, written composed or decomposed)."""
    nfc = lambda x: unicodedata.normalize('NFC', str(x or ''))
    return [l for l in tableau or [] if isinstance(l, dict) and nfc(l.get('projet')) == nfc(dossier)]


def conflits_global(studios_vus, metas, instantane=None, tableau=None):
    """The global « Conflits » tab: one row per Studio of the PM with open or unreadable cases (a failure costs only
    its row). A Studio is listed too when a session settling its conflicts has a question open (`tableau`: the board lines)."""
    sortie = []
    for s in studios_vus or []:
        if s.get('role') != 'pm':
            continue
        try:
            c = conflits_du_projet(s['dossier'], metas, instantane, questions=_lignes_du_projet(tableau, s['dossier']))
        except Exception:
            continue
        if c.get('ouverts') or c.get('illisibles') or c.get('en_cours'):
            sortie.append({'nom': s['nom'], 'dossier': s['dossier'], 'ouverts': len(c['ouverts']), 'en_cours': len(c.get('en_cours') or []),
                           'nouveaux': c['nouveaux'],
                           'illisibles': c['illisibles'], 'relance': c['relance'], 'raison': c['raison'],
                           'a_traiter': c['a_traiter'], 'session': c['session'], 'titre_session': c['titre_session'],
                           'commande': c['commande'], 'lu': c['lu']})
    sortie.sort(key=lambda x: (-x['nouveaux'], not x['relance'], x['nom'].lower()))
    return sortie


def lire_instantane():
    i = parc.lire_json(_instantane_chemin(), {})
    d = i.get('dossiers') if isinstance(i, dict) else None
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}

def sources_du_studio(dossier, maintenant, instantane=None):
    """Les sources lues en direct ; depuis le connecteur (`instantane` passé), celles du dernier calcul hors du
    connecteur quand le Drive refuse la lecture (`instantane: True` dans le résultat). Sans instantané : comme lues."""
    s = lire_sources(dossier, maintenant)
    gardee = (instantane or {}).get(dossier) if s['refus'] else None
    if isinstance(gardee, dict) and isinstance(gardee.get('passages'), list) and isinstance(gardee.get('reglees'), list):
        return dict(gardee, refus=False, instantane=True)
    return s

# What conflits.py copies into the snapshot as soon as it writes the register (registre.copier_dans_mon_studio).
CHAMPS_COPIE_CONFLITS = ('conflits', 'conflits_vu', 'conflits_reglages', 'conflits_copie')


def _garder_la_copie(neuf, ancien):
    """A Studio read before conflits.py's last copy (its `lu` earlier) keeps that copy of the register: a refresh that
    started before a write never brings the old register back. A later read wins (and drops `conflits_copie`)."""
    c = ancien.get('conflits_copie') if isinstance(ancien, dict) else None
    if isinstance(c, (int, float)) and not isinstance(c, bool) and c >= (neuf.get('lu') or 0):
        return dict(neuf, **{k: ancien.get(k) for k in CHAMPS_COPIE_CONFLITS})
    return neuf


def ecrire_instantane(lues, maintenant):
    """projets-sources.json : par Studio, ce qu'il a donné ; un Studio refusé garde son instantané précédent."""
    avant = lire_instantane()
    dossiers = {d: (avant[d] if s['refus'] and d in avant else
                    _garder_la_copie({k: v for k, v in s.items() if k != 'refus'}, avant.get(d)))
                for d, s in lues.items() if not s['refus'] or d in avant}
    try:
        parc.ecrire_atomique(_instantane_chemin(), json.dumps({'version': 1, 'ecrit': maintenant, 'dossiers': dossiers},
                                                              ensure_ascii=False, indent=1))
    except OSError:
        pass

def debut_fenetre(maintenant):
    """Minuit (heure locale) du jour ouvré précédent : lundi → vendredi. Pas de calendrier des jours fériés : un
    lendemain de férié remonte seulement à la veille, un jour de plus que nécessaire n'est jamais perdu."""
    jour = dt.date.fromtimestamp(maintenant) - dt.timedelta(days=1)
    while jour.weekday() >= 5:
        jour -= dt.timedelta(days=1)
    return time.mktime(jour.timetuple())


def age(depuis, maintenant):
    """« aujourd'hui », « depuis hier », « depuis 3 j » : en jours du calendrier."""
    n = (dt.date.fromtimestamp(maintenant) - dt.date.fromtimestamp(depuis)).days
    return "aujourd'hui" if n <= 0 else 'depuis hier' if n == 1 else f'depuis {n} j'


# --- sessions à ouvrir ------------------------------------------------------------------------------------

def _dans(cwd, dossier):
    d = dossier_normal(cwd) if cwd else ''
    return d == dossier or d.startswith(dossier + os.sep)


def session_du_studio(dossier, metas):
    """(session « 📬 » la plus récente du Studio, False), sinon (la plus récente du Studio, True), sinon (None, True)."""
    vivantes = [m for m in metas or [] if not m.get('archivee') and m.get('id') and _dans(m.get('cwd'), dossier)]
    boites = [m for m in vivantes if (m.get('titre') or '').startswith('📬')]
    if boites:
        return max(boites, key=lambda m: m.get('activite') or 0)['id'], False
    humaines = [m for m in vivantes if not m.get('tache')] or vivantes
    if humaines:
        return max(humaines, key=lambda m: m.get('activite') or 0)['id'], True
    return None, True


# A request the ingestion wrote without a link, an author or a channel (2026-11-19): the board names the session that
# ran that pass, found by the pass time and the Studio's folder, else the Studio file the line was read from.
FICHIER_INGESTION = 'projet/.ingestion-auto-state.json'   # where the run's report, hence the line, is kept in the Studio
PASSAGE_AVANT_S = 120      # a pass is stamped by the run itself: a minute or two before the card says it started is still it
PASSAGE_APRES_S = 600      # ... and a few minutes after its last activity (the card is updated when the turn ends)


def session_de_passage(dossier, passage, metas):
    """(id, title) of the session that ran the ingestion pass stamped `passage` on this Studio, else None. A session
    of the Studio whose title (or scheduled task) says « ingest » or opens with 📬 and whose window (created → last
    activity, with a short margin) holds the pass time. Several: the same title for all, the latest created; two
    different titles is a doubt, so none."""
    d = dossier_normal(dossier)
    if not passage:
        return None
    trouvees = []
    for m in metas or []:
        if not m.get('id') or not _dans(m.get('cwd'), d):
            continue
        titre = m.get('titre') or ''
        if not (titre.startswith('📬') or 'ingest' in normaliser(titre) or 'ingest' in normaliser(m.get('tache') or '')):
            continue
        fin = m.get('activite') or 0
        debut = m.get('creee') or fin
        if debut - PASSAGE_AVANT_S <= passage <= fin + PASSAGE_APRES_S:
            trouvees.append(m)
    if not trouvees or len({normaliser(m.get('titre')) for m in trouvees}) > 1:
        return None
    m = max(trouvees, key=lambda x: (x.get('creee') or 0, x.get('activite') or 0))
    return m['id'], m.get('titre') or ''


def session_de_ligne(l):
    if l.get('ouvrir'):
        return l['ouvrir']
    if str(l.get('cle') or '').startswith('local_'):
        return l['cle']
    m = re.search(r'(local_[0-9a-f-]{36})$', str(l.get('lien') or ''))
    return m.group(1) if m else None


# --- calcul -----------------------------------------------------------------------------------------------

def lire_etat():
    e = parc.lire_json(_etat_chemin(), {})
    lignes = e.get('lignes') if isinstance(e, dict) else None
    return {k: v for k, v in lignes.items() if isinstance(v, dict) and CLE.match(k)} if isinstance(lignes, dict) else {}


def ecrire_etat(lignes):
    try:
        parc.ecrire_atomique(_etat_chemin(), json.dumps({'version': 1, 'lignes': lignes}, ensure_ascii=False, indent=1))
    except OSError:
        pass   # un autre passage écrit au même instant : le suivant reprendra


# Lost update measured on 2026-11-18 (23:11): a « Fait » closed a line at 23:11:22, a computation that had read the state
# before wrote it back at 23:11:24 and the line came back. Every read-modify-write of projets-etat.json now holds this
# lock (the connector's two instances, the session hook, the command line), and the computation, which reads long
# before it writes, re-reads the disk under the lock and keeps what a click or a judgement wrote since its read.
@contextlib.contextmanager
def verrou_etat():
    chemin = _etat_chemin().with_name('projets-etat.verrou')
    fd = None
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        pass   # no lock possible: write as before
    try:
        yield
    finally:
        if fd is not None:
            try:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def fusionner_etat(lu, calcule, disque):
    """The state a computation writes: its own result, plus what changed on disk since it read the state (a « Fait »,
    a reopening, a Slack judgement, a suite): for a line someone else changed, each field that differs between what the
    computation read and the disk takes the disk's value; a line added since is kept. The computation's own changes
    stay on the other fields."""
    out = dict(calcule)
    for cle, d in disque.items():
        avant = lu.get(cle)
        if avant is None:
            if cle not in calcule:
                out[cle] = d
            continue
        if d == avant or cle not in calcule:
            continue
        ligne = dict(calcule[cle])
        for champ in set(d) | set(avant):
            if d.get(champ, _ABSENT) != avant.get(champ, _ABSENT):
                if champ in d:
                    ligne[champ] = d[champ]
                else:
                    ligne.pop(champ, None)
        out[cle] = ligne
    return out


_ABSENT = object()


def _noter(etat, cle, studio, type_, titre, premiere):
    if cle not in etat:
        etat[cle] = {'studio': studio, 'type': type_, 'titre': titre, 'premiere': premiere, 'vue': premiere,
                     'fermee': None, 'par': None}
    return etat[cle]


def lignes_du_studio(dossier, r, e, metas, etat, maintenant, debut, sources=None, reunions=None, regles=None):
    """Les lignes ouvertes d'un Studio, l'état mis à jour en passant. Une personne qui n'est pas PM n'a jamais
    de ligne « à toi » ni « reunion » : elles ne sont même pas notées. `reunions` : les réunions sans compte rendu du
    matin.json d'aujourd'hui pour ce Studio, ou None quand le point du jour n'est pas là (les lignes ouvertes restent).
    `regles` : les points « Réglé » de ce matin.json (tous projets), qui ferment un « À toi » au même lien."""
    nom = unicodedata.normalize('NFC', parc.nom_projet(dossier))
    sid, repli = session_du_studio(dossier, metas)
    ouvertes = []
    reclassement = parc.reclassement_actif()
    classements = parc.classements_du_pm() if reclassement else {}
    sources = lire_sources(dossier, maintenant) if sources is None else sources
    canaux = canaux_slack(sources['passages'])
    for n in sources['passages']:
        t, entres, actions = n['ts'], n['entres'], n['actions']
        if r == 'pm':
            for a in actions:
                corps, echeance, lien, dates = decouper_puce_meta(a)
                cle = _cle_a_toi_migree(etat, dossier, a)
                # Notée seulement si son passage a moins de 14 jours ; ensuite elle reste jusqu'à sa fermeture.
                if cle in etat or maintenant - t < FENETRE_A_TOI_S:
                    plat = texte_simple(corps)
                    ligne = _noter(etat, cle, dossier, 'a_toi', titre_court(plat), t)
                    ligne['titre'] = titre_court(plat)   # sans les suffixes, même pour une ligne plus ancienne
                    ligne['texte'] = couper(plat, TEXTE_MAX)
                    ligne['passage'] = max(ligne.get('passage') or 0, t)
                    if echeance:
                        ligne['echeance'] = echeance
                        # What the latest pass says of the date replaces the older word: a date moved is not « lue » any more.
                        ligne.pop('echeance_mode', None), ligne.pop('echeance_regle', None)
                        ligne.update({k: dates[k] for k in ('echeance_mode', 'echeance_regle') if dates.get(k)})
                    if dates.get('recu'):
                        ligne['recu'] = dates['recu']
                    if lien:
                        ligne['lien'] = lien
                    dit = parc.etiquettes(unicodedata.normalize('NFC', str(a)))[1]
                    if dit:
                        ligne['dit'] = dit   # what the ingestion said of it: impact, its reason, effort
        if t < debut:
            continue
        for x in entres:
            corps, _, lien = decouper_puce(x)
            plat = texte_simple(corps)
            # « titre court : détail » (the ingestion kit, 2026-11-06), « titre: détail » too; never a URL's colon.
            titre, reste = (re.split(r'\s*:\s+', plat, maxsplit=1) + [''])[:2]
            cle = cle_de(dossier, 'entree', normaliser(x))
            ligne = _noter(etat, cle, dossier, 'entree', couper(titre), t)
            if not ligne['fermee']:
                ouvertes.append({'cle': cle, 'type': 'entree', 'titre': couper(titre), 'detail': couper(reste, 400),
                                 'depuis': t, 'session': sid, 'repli': repli, 'lien': lien, 'dossier': dossier})
    # Une action que l'ingestion a vue faite (mail parti, CR rangé, ticket fini) : `reglees`, fermée par la source.
    # Une entrée `question` n'est pas un « À toi » (question.py la traite) ; une entrée que le PM a rouverte
    # (`rouverte`, « rouvre A3 ») ne ferme rien et rouvre la ligne qu'elle avait fermée.
    # La clé compare le texte sans ses suffixes, des deux côtés (cle_a_toi) : `reglees[].texte` est la puce mot pour mot.
    a_toi = [x for x in sources['reglees'] if x.get('genre', 'a_toi') == 'a_toi']
    rouvertes = {cle_a_toi(x['texte']) for x in a_toi if x.get('rouverte')}
    for x in a_toi:
        cle = cle_a_toi(x['texte'])
        ligne = etat.get(_cle_a_toi_migree(etat, dossier, x['texte']))
        if not ligne:
            continue
        if cle in rouvertes:
            if ligne['fermee'] and ligne['par'] == 'source':
                ligne.update(fermee=None, par=None)
            continue
        quand = instant(x.get('ts')) or maintenant
        if not ligne['fermee'] and quand >= ligne['premiere']:
            ligne.update(fermee=quand, par='source')
    # Le point du matin dit réglée la même demande, avec exactement le même lien (et le même projet quand il le
    # nomme) : la preuve ferme la ligne, et la ligne le dit (0.2.17 : « réglé » dans Today, « à faire » au tableau).
    # Une ressemblance de texte seule ne ferme rien.
    if r == 'pm' and regles:
        for cle, ligne in etat.items():
            if ligne['studio'] != dossier or ligne['type'] != 'a_toi' or ligne['fermee'] or not ligne.get('lien'):
                continue
            x = next((x for x in regles if x.get('lien') == ligne['lien']
                      and (not x.get('projet') or normaliser(x['projet']) == normaliser(nom))), None)
            if x:
                ligne.update(fermee=maintenant, par='matin', preuve='réglé au point du matin')
                ligne['journal'] = (ligne.get('journal') or []) + [{'quand': maintenant, 'texte':
                    f"Fermée : le point du matin la dit réglée (« {couper(x['quoi'], 160)} »), même lien."}]
    # Une demande qui cite une question numérotée (« (Q2) ») déjà au tableau pour ce Studio : la question la porte, la
    # demande ne fait pas une seconde ligne. Elle revient si la question quitte le tableau sans qu'elle soit fermée.
    au_tableau = set()
    for l in e.get('tableau') or []:
        if unicodedata.normalize('NFC', l.get('studio') or '') == nom:
            m = re.match(r'Q(\d+)\b', l.get('question') or l.get('affiche_titre') or l.get('affiche_suite') or '')
            if m:
                au_tableau.add(m.group(1))
    if r == 'pm':
        for cle, ligne in etat.items():
            if ligne['studio'] == dossier and ligne['type'] == 'a_toi' and not ligne['fermee']:
                ligne['vue'] = maintenant
                texte = ligne.get('texte') or ligne['titre']
                if set(re.findall(r'\(Q(\d+)\)', texte)) & au_tableau:
                    continue
                priorite = priorite_a_toi(ligne, texte, maintenant)
                ancienne = a_toi_ancienne(ligne, maintenant, priorite)
                # Switch « reclassement » on: what the rules gave, for the PM's journal, and his own order over it.
                pm = {}
                if reclassement:
                    pm['calcul'] = dict(priorite, regle=parc.regle_du_calcul(ligne.get('dit'), priorite))
                    if cle in classements:
                        vu = parc.appliquer_classement(dict(priorite, ancienne=ancienne), classements[cle])
                        priorite = {k: vu[k] for k in priorite}
                        pm['reclassee'], ancienne = vu['reclassee'], vu['ancienne']
                # A Slack line judged by the morning check shows its short summary, never the message (PM, Q8).
                resume = ligne.get('resume') or ''
                auteur, canal = ligne.get('qui') or auteur_demande(texte), canal_du_lien(ligne.get('lien'), canaux)
                ligne_sid, ligne_repli, origine = sid, repli, {}
                if not (ligne.get('lien') or auteur or canal):
                    # Nothing says where it came from: the session that ran that pass, else the file it was read from.
                    trouvee = session_de_passage(dossier, ligne.get('passage'), metas)
                    if trouvee:
                        ligne_sid, ligne_repli, origine = trouvee[0], False, {'origine_session': trouvee[1]}
                    else:
                        origine = {'origine_fichier': FICHIER_INGESTION}
                ouvertes.append({'cle': cle, 'type': 'a_toi', 'titre': couper(resume) if resume else ligne['titre'],
                                 'texte': resume or texte, **priorite, **pm, **origine,
                                 'commande': commande_de(texte), 'detail': '',
                                 'passage': int(ligne['passage'] * 1000) if ligne.get('passage') else None,
                                 'depuis': ligne['premiere'], 'session': ligne_sid, 'repli': ligne_repli,
                                 'echeance': ligne.get('echeance'), 'lien': ligne.get('lien') or '', 'dossier': dossier,
                                 'ancienne': ancienne, 'auteur': auteur, 'canal': canal,
                                 'mail': origine_entree(ligne.get('lien'), texte).startswith('Mail'),
                                 'recu': ligne.get('recu') or None, 'echeance_mode': ligne.get('echeance_mode') or '',
                                 'echeance_regle': ligne.get('echeance_regle') or ''})
    if r == 'pm':
        if reunions is not None:
            vues = set()
            for x in reunions:
                cle = cle_de(dossier, 'reunion', x['cle'])
                vues.add(cle)
                ligne = _noter(etat, cle, dossier, 'reunion', couper(x['titre']), instant(x['date']) or maintenant)
                ligne['detail'] = x['date']
                if ligne['fermee'] and ligne['par'] == 'source':
                    ligne.update(fermee=None, par=None)
            # Une réunion que le point du jour ne liste plus a son compte rendu : fermée par sa source.
            for cle, ligne in etat.items():
                if ligne['studio'] == dossier and ligne['type'] == 'reunion' and not ligne['fermee'] and cle not in vues:
                    ligne.update(fermee=maintenant, par='source')
        for cle, ligne in etat.items():
            if ligne['studio'] == dossier and ligne['type'] == 'reunion' and not ligne['fermee']:
                ligne['vue'] = maintenant
                ouvertes.append({'cle': cle, 'type': 'reunion', 'titre': ligne['titre'],
                                 'detail': ligne.get('detail') or '', 'depuis': ligne['premiere'], 'session': sid,
                                 'repli': repli})
    for l in e.get('tableau') or []:
        if unicodedata.normalize('NFC', l.get('studio') or '') != nom:
            continue
        titre = texte_simple(l.get('affiche_titre') or l.get('affiche_suite') or l.get('complet') or '')
        detail = texte_simple(l.get('affiche_suite') or '') if l.get('affiche_titre') else ''
        if l.get('question') and not re.match(re.escape(l['question']) + r'(?!\w)', titre):
            titre = f"{l['question']} · {titre}"
        cle = cle_de(dossier, 'question', l.get('cle') or l.get('lien') or '', l.get('question') or '', titre)
        ligne = _noter(etat, cle, dossier, 'question', couper(titre), l.get('depuis') or maintenant)
        ligne['vue'] = maintenant
        if ligne['fermee'] and ligne['par'] == 'source':
            ligne.update(fermee=None, par=None)   # revenue au tableau : rouverte
        if not ligne['fermee']:
            ouvertes.append({'cle': cle, 'type': 'question', 'titre': couper(titre), 'detail': couper(detail, 400),
                             'depuis': l.get('depuis') or maintenant, 'session': session_de_ligne(l), 'repli': False,
                             'session_titre': l.get('session') or ''})
    ouvertes.sort(key=lambda x: (ORDRE_TYPES[x['type']], x.get('echeance') or '9999-12-31', x['depuis']))
    return nom, ouvertes


def _cle_a_toi_migree(etat, dossier, texte):
    """La clé d'un « À toi » (texte sans suffixes). Une ligne notée avant sous l'ancienne clé (texte entier, suffixes
    compris) la prend, une fois : elle garde son âge et sa fermeture."""
    cle, ancienne = cle_de(dossier, 'a_toi', cle_a_toi(texte)), cle_de(dossier, 'a_toi', normaliser(texte))
    if ancienne != cle and ancienne in etat and cle not in etat:
        etat[cle] = etat.pop(ancienne)
    return cle


def priorite_a_toi(ligne, texte, maintenant):
    """{'impact', 'raison', 'effort'} of a request (parc.priorite): what the ingestion said of it, else the rules."""
    jour, ts, proche = dt.date.fromtimestamp(maintenant), None, False
    try:
        d = dt.date.fromisoformat(ligne['echeance']) if ligne.get('echeance') else None
    except ValueError:
        d = None
    if d:
        ts, proche = dt.datetime.combine(d, dt.time(12)).timestamp(), 0 <= (d - jour).days <= parc.ECHEANCE_JOURS
    return parc.priorite(texte, maintenant, ligne.get('dit'), ts, proche, demande=True)


def a_toi_ancienne(ligne, maintenant, priorite=None):
    """Au tableau, « Anciennes » : notée il y a plus de 7 jours et sans échéance aujourd'hui ou plus tard. Jamais une
    demande en retard, ni une que sa source ou ses mots disent importante sans attendre (sécurité, urgent) : l'âge ne
    cache pas ce qui presse (PM, 2026-11-17)."""
    p = priorite or {}
    if p.get('impact') == 'fort' and (p.get('raison') in (parc.EN_RETARD, parc.SECURITE, parc.URGENT) or (ligne.get('dit') or {}).get('impact') == 'fort'):
        return False
    if ligne.get('echeance') and ligne['echeance'] >= dt.date.fromtimestamp(maintenant).isoformat():
        return False
    return maintenant - (ligne.get('premiere') or maintenant) > ANCIENNE_A_TOI_S


def _charger_question():
    """question.py du même dossier (le plugin, ou sa copie de ~/Mon Studio/.parc), ses chemins pris sur ceux de parc :
    jamais un autre ~/Mon Studio que celui de ce calcul."""
    spec = importlib.util.spec_from_file_location('question_projets', ICI / 'question.py')
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    q.MON_STUDIO, q.CHANTIERS, q.INTERNAL = parc.SORTIE, parc.CHANTIERS, parc.INTERNE
    q.PENDING, q.STATE = parc.INTERNE / 'questions', parc.INTERNE / 'cockpit.json'
    q._parc = parc
    return q


def regler_questions(reglees):
    """Les questions numérotées que l'ingestion a vues réglées à leur source (entrées `genre: question` de `reglees`) :
    soldées au miroir de leur chantier, ou remises si le PM les a rouvertes (question.apply_source). Rien d'autre :
    jamais un choix, un go, ni une ligne d'arrêt. Ne lève jamais : le calcul de la liste passe avant."""
    entrees = [x for x in reglees or [] if isinstance(x, dict) and x.get('genre') == 'question']
    if not entrees:
        return []
    try:
        return _charger_question().apply_source(entrees)
    except Exception:
        return []


def page_mon_studio():
    c = parc.lire_json(parc.INTERNE / 'cockpit.json', {}) or {}
    p = c.get('page') if isinstance(c, dict) else None
    return p if isinstance(p, str) and ADRESSE_PAGE.match(p) else None


def _regles_du_jour(maintenant):
    """Les points « Réglé » du matin.json d'aujourd'hui ([] sans point du jour, ou quand sa lecture échoue)."""
    try:
        m = _charger_matin().lire(maintenant)
    except Exception:
        return []
    return list((m or {}).get('regle') or [])


def _reunions_du_jour(maintenant):
    """Les réunions sans compte rendu du matin.json d'aujourd'hui, par nom de projet normalisé ; None quand le point
    du jour n'est pas là (absent, illisible, d'un autre jour) ou que sa lecture échoue."""
    try:
        m = _charger_matin().lire(maintenant)
    except Exception:
        return None
    if m is None:
        return None
    par_projet = {}
    for x in m['reunions_sans_cr']:
        par_projet.setdefault(normaliser(x['projet']), []).append(x)
    return par_projet


def ingestion_du_matin(liste, maintenant):
    """La partie ingestion de l'onglet du matin, calculée sans LLM depuis la liste par projet (`calculer`) : les entrées
    au Studio (tous les projets) et les nouvelles demandes « À toi » (projets où la personne est PM, la liste n'en a pas
    d'autres) dont le passage date d'après minuit du dernier jour ouvré, encore ouvertes. Échéance la plus proche
    d'abord, puis la plus ancienne. Rien quand la liste manque (son calcul a échoué)."""
    debut = debut_fenetre(maintenant) * 1000
    entre, demandes = [], []
    moi = identite()
    for p in (liste or {}).get('projets') or []:
        # An entry that gave an open « À toi de jouer » carries the same source link (ingestion kit, 2026-11-06).
        taches = {l['lien']: l['cle'] for l in p.get('lignes') or [] if l['type'] == 'a_toi' and l.get('lien')}
        for l in p.get('lignes') or []:
            if l['type'] == 'entree':
                lien = l.get('lien') or ''
                titre, detail = titre_et_detail(l['titre'], l.get('detail') or '')
                origine = origine_entree(lien, f"{l['titre']} : {l.get('detail') or ''}")
                # What the PM wrote himself is not news to him (PM, 2026-11-17: « Ton accusé de réception… · Mail · <le PM> »).
                if ecrite_par(origine, moi):
                    continue
                entre.append({'cle': l['cle'], 'projet': p['nom'], 'lien': lien,
                              'phrase': l['titre'] + (f" : {l['detail']}" if l.get('detail') else ''),
                              'titre': titre, 'detail': detail, 'origine': origine,
                              'tache': taches.get(lien) if lien else None, 'dossier': p['dossier'],
                              'session': l.get('session')})   # without a link, « Ouvrir ↗ » the Studio's session
            elif l['type'] == 'a_toi' and l['depuis'] >= debut:
                demandes.append({'cle': l['cle'], 'titre': l['titre'], 'projet': p['nom'], 'echeance': l.get('echeance'),
                                 'lien': l.get('lien') or '', 'dossier': p['dossier'], 'depuis': l['depuis'],
                                 'session': l.get('session'), 'repli': l.get('repli')})
    demandes.sort(key=lambda x: (x['echeance'] or '9999-12-31', x['depuis']))
    return entre, demandes


# « Pour info : ce qui est entré au Studio »: one short line per entry, its origin, the
# detail on a click. A bullet that starts with a short title followed by « : » gives it (the ingestion kit writes one
# since 2026-11-06); an older bullet starts with where it came from (« Slack #canal (A., 05/11) : … »): its title
# is then the first twelve words of what follows.
MOTS_TITRE = 12
ORIGINE_EN_TETE = re.compile(r"(?i)^#[\w-]+|^(?:slack|mail|gmail|e-?mail|drive|r[ée]union|agenda)\b[^:]*\("
                             r"|\([^)]*\d{1,2}/\d{1,2}[^)]*\)\s*$")
CANAL = re.compile(r"#([\w][\w-]*)")
QUI = re.compile(r"\(([^)]*)\)")
MAIL_DE = re.compile(r"(?i)\bmail\s+(?:de|d['’])\s*([A-ZÀ-Ý][\w-]+)")


def titre_et_detail(titre, detail):
    """(short title, detail) of an entry: its own short title when it has one, else its first twelve words."""
    titre, detail = (titre or '').strip(), (detail or '').strip()
    if titre and detail and len(titre.split()) <= MOTS_TITRE and not ORIGINE_EN_TETE.search(titre):
        return titre, detail
    complet = ' : '.join(x for x in (titre, detail) if x)
    corps = detail if detail and ORIGINE_EN_TETE.search(titre) else complet
    mots = corps.split()
    return ' '.join(mots[:MOTS_TITRE]).rstrip(' ,;:.') + (' …' if len(mots) > MOTS_TITRE else ''), complet


SLACK_CANAL = re.compile(r'^https://([a-z0-9-]+\.)*slack\.com/archives/([A-Z0-9]+)/', re.I)
# Who asks, at the head of a request (« Ana te demande… », « Ana et Léo attendent… »): one or two people, then the verb.
AUTEUR = re.compile(r"^((?:[A-ZÀ-Ý][\w’'-]+)(?:\s+[A-ZÀ-Ý][\w’'-]+)?(?:\s+et\s+[A-ZÀ-Ý][\w’'-]+(?:\s+[A-ZÀ-Ý][\w’'-]+)?)?)"
                    r"\s+(?:te|t['’]|attend|attendent|demande|demandent|préfère|préfèrent|propose|proposent|relance|"
                    r"relancent|souhaite|souhaitent|veut|veulent|aimerait|aimeraient|signale|signalent|rappelle|"
                    r"rappellent|confirme|confirment|valide|valident|refuse|refusent)\b")


def canaux_slack(passages):
    """{Slack channel id: '#name'}: the channels the ingestion named in a bullet (« Slack #projet-interne (…) ») that
    links a message of that channel. A request's link carries the id only; this gives it its name."""
    out = {}
    for n in passages or []:
        for x in list(n.get('entres') or []) + list(n.get('actions') or []):
            corps, _, lien = decouper_puce(x)
            m, c = SLACK_CANAL.match(lien or ''), CANAL.search((corps or '')[:240])
            if m and c:
                out.setdefault(m.group(2).upper(), '#' + c.group(1))
    return out


def canal_du_lien(lien, canaux):
    """'#name' of the Slack channel a request links to, when an entry of the Studio named it; '' otherwise."""
    m = SLACK_CANAL.match(lien or '')
    return canaux.get(m.group(2).upper(), '') if m else ''


def auteur_demande(texte):
    """Who asks, read at the head of a request (« Ana te demande si… » → « Ana »); '' when the request does not
    start with a person and a verb (« Relancer Léo… », « Trancher le mode clair »)."""
    m = AUTEUR.match(' '.join(str(texte or '').split()))
    return m.group(1) if m else ''


def ecrite_par(origine, qui):
    """True when the people an entry's origin names (« Mail · A. B. », after the « · ») are the person `qui` alone:
    the full name, or the first name it starts with."""
    if not qui or '·' not in (origine or ''):
        return False
    gens = [_nom(g) for g in re.split(r'\s*(?:,|→|\bet\b)\s*', origine.split('·', 1)[1]) if g.strip()]
    moi = _nom(qui)
    prenom = moi.split(' ')[0]
    return bool(gens) and all(g == moi or g == prenom for g in gens)


def origine_entree(lien, texte):
    """« Slack #projet-interne · A. », « Mail · B. », « Drive », « Fichier du Studio »…: where an entry came from,
    from its source link and the start of its bullet. '' when nothing says it."""
    tete = (texte or '')[:240]
    gens = []
    m = QUI.search(tete)
    if m:
        for x in re.split(r"[,→;]|\bet\b", m.group(1)):
            x = x.strip()
            if x and x[0].isupper() and not re.search(r'\d', x) and len(x.split()) <= 3:
                gens.append(x)
    canal = CANAL.search(tete)
    lien = lien or ''
    if re.match(r'^https://([a-z0-9-]+\.)*slack\.com/', lien, re.I) or (canal and not lien.startswith('https://')):
        base = 'Slack' + (f" #{canal.group(1)}" if canal else '')
    elif re.match(r'^https://mail\.google\.com/', lien, re.I) or re.match(r'(?i)^\s*(?:g?mail|e-?mail)\b', tete):
        base = 'Mail'
        if not gens and MAIL_DE.search(tete):
            gens = [MAIL_DE.search(tete).group(1)]
    elif re.match(r'^https://(drive|docs)\.google\.com/', lien, re.I):
        base = 'Drive'
    elif re.match(r'^https://(calendar\.google\.com|www\.google\.com/calendar)/', lien, re.I):
        base = 'Agenda'
    elif lien and not lien.startswith('https://'):
        base = 'Fichier du Studio'
    elif lien:
        base = 'Lien'
    else:
        return ''
    return base + (' · ' + ', '.join(gens[:2]) if gens and base != 'Fichier du Studio' else '')


def matin_pour_la_page(maintenant=None, metas=None, liste=None):
    """Le point du matin tel que la page l'affiche (matin.py), avec la partie ingestion lue en direct : `entre_studio` et `demandes` (ingestion_du_matin, depuis `liste`, la liste par projet du même calcul),
    même quand la tâche du matin n'est pas encore passée. Chaque élément de `a_traiter` et `regle` dont le lien est un
    chemin relatif porte le dossier de son Studio (`dossier`, None si le projet n'est pas reconnu) : la page l'ouvre
    par l'outil `ouvrir` du connecteur. Le projet se reconnaît à son nom, comme pour les réunions."""
    maintenant = time.time() if maintenant is None else maintenant
    matin = _charger_matin()
    m = matin.pour_la_page(maintenant)
    m['entre_studio'], m['demandes'] = ingestion_du_matin(liste, maintenant)
    if m.get('etat') != 'ok':
        retard = matin.retard(maintenant)
        if retard:
            m['retard'] = retard
        return m
    if metas is None:
        metas = parc.fiches(parc.charger_cache())
    par_nom = None
    for x in m['a_traiter'] + m['regle']:
        if not x['lien'] or x['lien'].startswith('https://'):
            continue
        if par_nom is None:
            par_nom = {normaliser(unicodedata.normalize('NFC', parc.nom_projet(d))): d
                       for d in studios(metas, lire_instantane())}
        x['dossier'] = par_nom.get(normaliser(x['projet'])) if x['projet'] else None
    sessions_des_brouillons(m.get('brouillons') or [], metas)
    return m


def sessions_des_brouillons(brouillons, metas):
    """Each draft carries `session`, the live local_… session that wrote it (from .parc/brouillons.json, noted by the
    hook: its local id, else its CLI id matched on the app's cards), or None: the page then has no « Ouvrir la session »."""
    if not brouillons:
        return
    notes = parc.lire_json(parc.INTERNE / 'brouillons.json', {})
    notes = {e.get('cle'): e for e in (notes.get('brouillons') if isinstance(notes, dict) else None) or [] if isinstance(e, dict)}
    vivantes = {x['id']: x for x in metas if x.get('id') and not x.get('archivee')}
    par_cli = {x['cli']: x['id'] for x in vivantes.values() if x.get('cli')}
    for b in brouillons:
        n = notes.get(b['cle']) or {}
        sid = n.get('session_locale') if n.get('session_locale') in vivantes else par_cli.get(n.get('session'))
        b['session'] = sid or None


def dossier_du_matin(dossier, metas=None):
    """Le dossier tel quel s'il est un Studio connu de ce Mac, sinon ValueError : l'outil `ouvrir` n'ouvre un fichier
    que dans un Studio."""
    if metas is None:
        metas = parc.fiches(parc.charger_cache())
    d = dossier_normal(dossier) if isinstance(dossier, str) and dossier else ''
    if not d or d not in studios(metas, lire_instantane()):
        raise ValueError('Studio inconnu')
    return d


def fait_matin(cle, maintenant=None):
    """« Fait » on an item of the point of the day (matin.py): à traiter, préparer demain or a draft, for good.
    ValueError if unknown or already done."""
    return _charger_matin().fait(cle, maintenant)


def calculer(e=None, maintenant=None, metas=None, ecrire=True, depuis_connecteur=False):
    """Tout le calcul : les Studios, leurs lignes, l'état mis à jour, projets.json et projets.md écrits (sauf
    ecrire=False). Rend ce que projets.json contient : ce que la personne qui regarde a le droit de voir, rien d'autre."""
    maintenant = time.time() if maintenant is None else maintenant
    if e is None or metas is None:
        cache = parc.charger_cache()
        if e is None:
            e = parc.construire(int(os.environ.get('MON_STUDIO_JOURS', 7)), 7, maintenant, cache)
        metas = parc.fiches(cache) if metas is None else metas
        if ecrire:
            try:
                parc.ecrire_atomique(parc.INTERNE / 'cache.json', json.dumps(cache, ensure_ascii=False))
            except OSError:
                pass
    debut = debut_fenetre(maintenant)
    reunions = _reunions_du_jour(maintenant)
    regles = _regles_du_jour(maintenant)
    etat = lire_etat()
    avant = json.dumps(etat, sort_keys=True)
    qui = identite()
    instantane = lire_instantane() if depuis_connecteur else None
    connus, projets, presentes, lues = [], [], set(), {}
    for d in studios(metas, instantane):
        s = lues[d] = sources_du_studio(d, maintenant, instantane)
        cites = fichiers_cites_au_tableau(e, d) if not depuis_connecteur and 'fichiers' in s else []
        if cites:   # the snapshot keeps them too: the connector cannot read the Drive
            s['fichiers'] = textes_des_entrees(d, s['passages'], maintenant, cites)
        if ecrire:
            regler_questions(s['reglees'])
        r = role(d, qui, s['pm'])
        nom, ouvertes = lignes_du_studio(d, r, e, metas, etat, maintenant, debut, s,
                                         None if reunions is None else reunions.get(normaliser(unicodedata.normalize('NFC', parc.nom_projet(d))), []),
                                         regles)
        if r == 'pm':
            try:
                qs = _lignes_du_projet(e.get('tableau'), d)
                c = conflits_du_projet(d, metas, instantane, questions=qs)
                relance = ligne_relance_conflits(d, metas, maintenant, instantane, c, qs)
                verifier = ligne_verifier_conflits(d, c, etat, maintenant, metas)
            except Exception:
                relance = verifier = None   # a failure costs only these lines
            if relance:
                ouvertes.append(relance)
            if verifier:
                ouvertes.append(verifier)
        vu = {'nom': nom, 'dossier': d, 'role': r}
        if s.get('instantane'):
            vu['lu'] = int((s.get('lu') or 0) * 1000)   # lu par le dernier calcul hors du connecteur, à cette heure
        connus.append(vu)
        presentes.update(x['cle'] for x in ouvertes if x['type'] == 'question')
        projets.append(dict(vu, lignes=ouvertes))
    # Une question qui a quitté le tableau a eu sa réponse. Pas quand Mon Studio ne lit plus l'app : le tableau
    # vide ne dit alors rien.
    if not parc.hors_service(e):
        for cle, ligne in etat.items():
            if ligne['type'] == 'question' and not ligne['fermee'] and cle not in presentes:
                ligne.update(fermee=maintenant, par='source')
    # Un « À toi » fermé reste tant que son passage est lu (14 jours) : sinon le passage le noterait de nouveau, ouvert.
    for cle in [k for k, l in etat.items() if l['type'] != 'verifier' and (l['fermee'] and maintenant - l['fermee'] > PURGE_S
                                                 and (l['type'] != 'a_toi' or maintenant - max(l.get('passage') or 0, l.get('premiere') or 0) > LECTURE_S))
                or (l['type'] == 'entree' and maintenant - (l.get('premiere') or 0) > PURGE_S)]:
        del etat[cle]
    if ecrire:
        # Under the lock, against the disk as it is now: a click made during the computation is kept.
        with verrou_etat():
            disque = lire_etat()
            calcule = etat
            etat = fusionner_etat(json.loads(avant), calcule, disque)
            if json.dumps(etat, sort_keys=True) != json.dumps(disque, sort_keys=True):
                ecrire_etat(etat)
        fermees_ailleurs = {k for k, l in etat.items() if l.get('fermee') and not (calcule.get(k) or {}).get('fermee')}
        if fermees_ailleurs:
            for p in projets:
                p['lignes'] = [l for l in p['lignes'] if l.get('cle') not in fermees_ailleurs]
    roles = {p['dossier']: p['role'] for p in projets}
    for p in projets:
        fermees = sorted((l for l in etat.values() if l['studio'] == p['dossier'] and l['fermee']
                          and l['fermee'] >= debut and l['type'] != 'entree'   # an entry seen is not a thing done
                          and (l['type'] not in ('a_toi', 'reunion') or roles[p['dossier']] == 'pm')),
                         key=lambda l: -l['fermee'])
        p['fermees_depuis_hier'] = len(fermees)
        p['fermees_titres'] = [couper(l['titre'], 80) + (f" ({l['preuve']})" if l.get('preuve') else '')
                               for l in fermees[:FERMEES_MONTREES]]
    projets = [p for p in projets if p['lignes'] or p['fermees_depuis_hier']]
    projets.sort(key=lambda p: (not any(l['type'] != 'entree' for l in p['lignes']), p['nom'].lower()))
    sortie = {'genere': int(maintenant * 1000), 'page': page_mon_studio(), 'studios': connus,
              'projets': [dict(p, lignes=[dict(l, depuis=int(l['depuis'] * 1000)) for l in p['lignes']])
                          for p in projets]}
    if ecrire:
        ecrire_sorties(sortie, maintenant, depuis_connecteur)
        if not depuis_connecteur:
            ecrire_instantane(lues, maintenant)
    return sortie


def rendre_md(sortie, maintenant):
    """projets.md pour /morning : un « ## » par Studio, une ligne par chose qui attend, et le lien https de la page
    Mon Studio en tête (le HTML du brief n'accepte que des liens https)."""
    out = ['# Projets', '']
    if sortie.get('page'):
        out += [f"Tout ouvrir depuis Mon Studio : {sortie['page']}", '']
    if not sortie['projets']:
        out.append('Rien ne t\'attend sur tes projets.')
    for p in sortie['projets']:
        out.append(f"## {p['nom']}" + (' (vue membre)' if p['role'] == 'membre' else ''))
        for l in p['lignes']:
            titre = l['titre'] + (f" : {couper(l['detail'], 120)}" if l['type'] == 'entree' and l['detail'] else '')
            if l.get('echeance'):
                titre += f" (échéance {dt.date.fromisoformat(l['echeance']).strftime('%d/%m')})"
            source = SOURCES.get(l['type']) or f"question de « {l.get('session_titre') or 'sa session'} »"
            out.append(f"- {titre} · {source} · {age(l['depuis'] / 1000, maintenant)}")
        if p['fermees_depuis_hier']:
            reste = p['fermees_depuis_hier'] - len(p['fermees_titres'])
            out.append('Fermé depuis hier : ' + ' ; '.join(p['fermees_titres']) + (f' (et {reste} autre{"s" if reste > 1 else ""})' if reste > 0 else ''))
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def ecrire_sorties(sortie, maintenant, depuis_connecteur=False):
    jsn, md = _sortie() / 'projets.json', _sortie() / 'projets.md'
    if depuis_connecteur:
        # Toutes les 15 s depuis la page : rien n'est récrit qui n'a pas changé, sauf pour rafraîchir la date.
        ancien = parc.lire_json(jsn, None)
        if isinstance(ancien, dict) and dict(ancien, genere=0) == dict(sortie, genere=0) \
                and maintenant * 1000 - (ancien.get('genere') or 0) < RECRIT_S * 1000 and md.exists():
            return
    try:
        parc.ecrire_atomique(jsn, json.dumps(sortie, ensure_ascii=False, indent=1))
        parc.ecrire_atomique(md, rendre_md(sortie, maintenant))
    except OSError:
        pass


# --- La mise en route (PM, revue du 2026-11-15, Q4 et Q8) ----------------------------------------------------
# The installation lays only the base (folder, connector, pages, rules). The other steps are lines of a « Mise en
# route » block at the head of the board, from the first day, with no delay and no reminder: one line per step, its
# cost and its button, until it is done (seen on the Mac) or the PM says « Pas pour moi ». The never-checked Studios'
# conflict lines (type `verifier`, ligne_verifier_conflits) join the block on the page. Nothing here writes a setting:
# the morning step's permissions are written only by `install.py apply --autorisations`, after the PM's go in the
# session the button opens.
ETAPES = ('matin', 'terminal')
ETAPE_CLE = re.compile(r'^etape-(matin|terminal)$')
ETAPE_COMMANDE = {'matin': '/cockpit:mon-studio point du matin', 'terminal': '/cockpit:mon-studio terminal'}
TERMINAL_VERIF_S = 600    # `claude auth status` (local, no token) asked at most every 10 minutes while the step waits
# The cost of each step, written by install.py into cockpit.json (`etapes`) from its one cost list; these defaults
# only serve before that.
COUT_ETAPE = {'matin': 'environ 0,94 $ par jour ouvré, 0,32 % de ta semaine chaque semaine (« Point du matin » sur '
                       'Sonnet, estimation à remesurer ; sa vérification sur Haiku, mesurée)',
              'terminal': "moins d'un centime pour la vérification ; ensuite, une réponse par bouton coûte le même tour "
                          "de la session que si tu répondais dedans"}


def _mise_en_route_chemin():
    return parc.INTERNE / 'mise-en-route.json'


def lire_mise_en_route():
    e = parc.lire_json(_mise_en_route_chemin(), {})
    e = e if isinstance(e, dict) else {}
    ecartees = e.get('ecartees') if isinstance(e.get('ecartees'), dict) else {}
    terminal = e.get('terminal') if isinstance(e.get('terminal'), dict) else {}
    return {'ecartees': {k: v for k, v in ecartees.items() if k in ETAPES}, 'terminal': terminal}


def _ecrire_mise_en_route(e):
    try:
        parc.ecrire_atomique(_mise_en_route_chemin(), json.dumps(e, ensure_ascii=False, indent=1))
    except OSError:
        pass


def taches_du_matin_posees():
    """Both morning tasks exist in the app (their SKILL.md): the step is done. Their model, their permissions and their
    first run stay the repair items of `install.py status` (set_task_models, allow_scripts, morning_blocked)."""
    base = pathlib.Path.home() / '.claude' / 'scheduled-tasks'
    return all((base / t / 'SKILL.md').exists() for t in ('point-du-matin', 'point-du-matin-verif'))


def _claude_du_terminal():
    exe = os.environ.get('MON_STUDIO_CLAUDE') or str(pathlib.Path.home() / '.local' / 'bin' / 'claude')
    return exe if os.path.isfile(exe) and os.access(exe, os.X_OK) else None


def terminal_connecte(e, maintenant):
    """True (logged in), False (not yet) or None (no Terminal Claude on this Mac). terminal.json, written by
    install.py or by a wake, is believed when it says logged in; otherwise `claude auth status` (local, no token), at most
    every TERMINAL_VERIF_S, its answer kept in mise-en-route.json. The full check (one short `claude -p`) stays install.py's."""
    note = parc.lire_json(parc.INTERNE / 'terminal.json', {})
    if isinstance(note, dict) and note.get('connecte') is True:
        return True
    exe = _claude_du_terminal()
    if not exe:
        return None
    vu = e['terminal']
    if isinstance(vu.get('t'), (int, float)) and maintenant - vu['t'] < TERMINAL_VERIF_S:
        return vu.get('connecte') is True
    env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE') or k == 'CLAUDE_CONFIG_DIR'}
    try:
        r = subprocess.run([exe, 'auth', 'status'], capture_output=True, text=True, timeout=8, env=env,
                           stdin=subprocess.DEVNULL, errors='replace')
        connecte = json.loads(r.stdout or '{}').get('loggedIn') is True
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        connecte = False
    e['terminal'] = {'t': maintenant, 'connecte': connecte}
    _ecrire_mise_en_route(e)
    return connecte


def couts_des_etapes():
    c = parc.lire_json(parc.INTERNE / 'cockpit.json', {})
    etapes = c.get('etapes') if isinstance(c, dict) and isinstance(c.get('etapes'), dict) else {}
    return {k: str(etapes.get(k) or COUT_ETAPE[k])[:300] for k in ETAPES}


def etape_matin(cout):
    return {'cle': 'etape-matin', 'etape': 'matin', 'titre': 'Mettre en route le point du matin', 'cout': cout,
            'note': 'La passe des conflits du lundi en dépend.',
            'detail': "Chaque jour ouvré à 7h30, une tâche lit tes mails, Slack et ton agenda et remplit l'onglet "
                      "« Today » ; une vérification range dans la journée ce qui a eu sa réponse. Le lundi, la même tâche "
                      "relit les conflits nouveaux de tes Studios sans ingestion automatique : sans elle, cette passe ne "
                      "se fait pas. Le bouton copie « " + ETAPE_COMMANDE['matin'] + " » : colle-le dans une nouvelle "
                      "session (Cmd+N), Claude te dit ce qu'il pose et ce que ça coûte, puis attend ton go. Environ "
                      "5 minutes.",
            'copier': ETAPE_COMMANDE['matin']}


def etape_terminal(cout, installe):
    detail = ("Une fois connecté, un bouton de réponse du tableau (« Go », « Oui », une option) répond à la session "
              "sans que tu l'ouvres, dès que son tour est fini ; sans lui, le bouton copie la réponse et ouvre la "
              "session. Six gestes dans l'app Terminal, environ 2 minutes. Le bouton copie « "
              + ETAPE_COMMANDE['terminal'] + " » : colle-le dans une nouvelle session (Cmd+N), Claude te donne les "
              "gestes un par un et vérifie.")
    if not installe:
        detail = ("Le Claude du Terminal n'est pas installé sur ce Mac : les boutons de réponse copient la réponse et "
                  "ouvrent la session, où la coller. « Pas pour moi » retire cette ligne. " + detail)
    return {'cle': 'etape-terminal', 'etape': 'terminal', 'titre': 'Connecter le Claude du Terminal', 'cout': cout,
            'note': '', 'detail': detail, 'copier': ETAPE_COMMANDE['terminal']}


def mise_en_route(maintenant=None):
    """{'etapes': [...]} : the steps neither done nor set aside, in order (the morning point first: the « Today » tab and
    the Monday pass of the conflicts depend on it). Each step: cle (for « Pas pour moi »: `clore`), etape, titre, cout,
    note, detail, copier (the command its button copies). Read only, but for the Terminal check's note."""
    maintenant = time.time() if maintenant is None else maintenant
    e = lire_mise_en_route()
    couts = couts_des_etapes()
    etapes = []
    if 'matin' not in e['ecartees'] and not taches_du_matin_posees():
        etapes.append(etape_matin(couts['matin']))
    if 'terminal' not in e['ecartees']:
        connecte = terminal_connecte(e, maintenant)
        if connecte is not True:
            etapes.append(etape_terminal(couts['terminal'], connecte is not None))
    return {'etapes': etapes, 'matin': 'ecarte' if 'matin' in e['ecartees'] else
            'fait' if taches_du_matin_posees() else 'a_faire'}


def ecarter_etape(cle, maintenant=None):
    """« Pas pour moi » on a step: it leaves the block for good (the skill can still lay it on demand)."""
    m = ETAPE_CLE.match(cle or '')
    if not m:
        raise ValueError('étape inconnue')
    e = lire_mise_en_route()
    if m.group(1) in e['ecartees']:
        raise ValueError('étape déjà écartée')
    e['ecartees'][m.group(1)] = time.time() if maintenant is None else maintenant
    _ecrire_mise_en_route(e)
    return {'ecarte': cle}


def fermer(cle, maintenant=None):
    """Ferme à la main une ligne ouverte (par = 'main'). ValueError pour une clé inconnue ou déjà fermée."""
    maintenant = time.time() if maintenant is None else maintenant
    with verrou_etat():
        etat = lire_etat()
        ligne = etat.get(cle) if isinstance(cle, str) and CLE.match(cle) else None
        if not ligne:
            raise ValueError('ligne inconnue')
        if ligne['fermee']:
            raise ValueError('ligne déjà fermée')
        ligne.update(fermee=maintenant, par='main')
        ecrire_etat(etat)
    return {'ferme': cle}


ROUVRIR_S = 60   # « Annuler » reopens only a closure of the PM's own click, made less than a minute ago


def rouvrir(cle, maintenant=None):
    """« Annuler » after « Fait » (the page sends « clore » at the click, then gives 10 s to take it back): reopens a
    line closed by hand (par = 'main') less than ROUVRIR_S ago. ValueError otherwise: a closure by a source, the
    morning check or Slack, or an older one, is never undone from the page."""
    maintenant = time.time() if maintenant is None else maintenant
    with verrou_etat():
        etat = lire_etat()
        ligne = etat.get(cle) if isinstance(cle, str) and CLE.match(cle) else None
        if not ligne:
            raise ValueError('ligne inconnue')
        if not ligne['fermee'] or ligne.get('par') != 'main' or not 0 <= maintenant - ligne['fermee'] <= ROUVRIR_S:
            raise ValueError('rien à annuler')
        ligne.update(fermee=None, par=None)
        ecrire_etat(etat)
    return {'rouvert': cle}


# --- Lignes Slack réglées dans leur fil (PM, Q6, 2026-11-17) ------------------------------------------------
# Une demande de l'ingestion qui pointe vers Slack ne se fermait qu'au passage de l'ingestion (`reglees`), qui ne le
# faisait pas : une question répondue à 9 h 50 restait au tableau des jours. La vérification du point du matin
# (11 h, 14 h, 17 h) lit le fil de chaque ligne ouverte (slack_ouvertes) et rend son jugement (slack_juger) : le PM a
# répondu après la demande, la ligne se ferme ; sa réponse annonce une suite, la suite prend sa place. Elle écrit aussi
# le résumé court de chaque ligne (PM, Q8) : le tableau ne recopie jamais le message ni le fil.
# Le jugement s'écrit sous le verrou de l'état, et un calcul concurrent le garde (fusionner_etat, 2026-11-18).
# La preuve d'une fermeture est un message plus tardif que la demande (mesuré le 2026-11-18 : 3 fermetures sur 8 étaient à tort,
# dont une suite fermée avec le message qui l'avait créée) : le lien de la demande, celui du message parent du fil ou un message
# antérieur ne ferment rien. Le jugement est écarté, la ligne reste ouverte.

SLACK_MESSAGE = re.compile(r'^https://[a-z0-9-]+\.slack\.com/archives/([A-Z0-9]+)/p(\d{10})(\d{6})(?:\?(\S*))?$', re.I)
RESUME_MAX = 160
VERDICTS = ('reglee', 'ouverte')


def fil_slack(lien):
    """Le canal et le message parent du fil d'un lien Slack (« …/archives/C0…/p1794…?thread_ts=1794….… ») ; None sinon."""
    m = SLACK_MESSAGE.match(str(lien or ''))
    if not m:
        return None
    ts = f'{m.group(2)}.{m.group(3)}'
    parent = re.search(r'(?:^|&)thread_ts=(\d{10}\.\d{6})(?:&|$)', m.group(4) or '')
    return {'channel_id': m.group(1).upper(), 'message_ts': parent.group(1) if parent else ts, 'demande_ts': ts}


def slack_ouvertes():
    """Les demandes « À toi » ouvertes qui pointent vers un message Slack, toutes Studios confondus (elles n'existent que
    pour le PM du Studio), les plus anciennes d'abord : la clé, le projet, la demande telle que l'ingestion l'a
    écrite, son lien, le fil à lire (channel_id, message_ts du parent) et l'heure de la demande. Lecture seule."""
    out = []
    for cle, l in lire_etat().items():
        f = fil_slack(l.get('lien')) if l.get('type') == 'a_toi' and not l.get('fermee') else None
        if not f:
            continue
        out.append({'cle': cle, 'projet': unicodedata.normalize('NFC', parc.nom_projet(l['studio'])),
                    'depuis': dt.datetime.fromtimestamp(l['premiere']).strftime('%Y-%m-%d %H:%M'),
                    'demande': l.get('texte') or l.get('titre') or '', 'lien': l['lien'], **f,
                    'resume': l.get('resume') or ''})
    return sorted(out, key=lambda x: x['depuis'])


def _phrase(x, n=RESUME_MAX):
    return couper(' '.join(x.split()), n) if isinstance(x, str) else ''


def _ts_slack(ts):
    """L'heure d'un message Slack (« 1794123456.123456 ») en couple d'entiers, comparable."""
    s, _, us = str(ts).partition('.')
    return int(s), int(us or 0)


def _preuve_refusee(ligne, reponse):
    """Pourquoi le lien de preuve ne peut pas fermer cette ligne, ou None : c'est la demande elle-même, le message parent
    de son fil, ou un message antérieur à la demande. Le lien d'une suite est le message qui l'a créée : elle est refusée par le premier cas."""
    demande, preuve = fil_slack(ligne.get('lien')), fil_slack(reponse)
    if _ts_slack(preuve['demande_ts']) == _ts_slack(demande['demande_ts']):
        return 'preuve = la demande elle-même'
    if demande['message_ts'] != demande['demande_ts'] and _ts_slack(preuve['demande_ts']) == _ts_slack(demande['message_ts']):
        return 'preuve = le message parent du fil'
    if _ts_slack(preuve['demande_ts']) < _ts_slack(demande['demande_ts']):
        return 'preuve antérieure à la demande'
    return None


def slack_juger(jugements, maintenant=None):
    """Les jugements de la vérification sur les lignes Slack ouvertes, un objet par ligne :
        cle      la clé rendue par slack_ouvertes
        verdict  « reglee » (le PM a répondu dans le fil après la demande, ou le geste est fait) ou « ouverte »
        resume   la ligne en une phrase courte, jamais le message recopié (160 signes au plus)
        qui      qui a écrit la demande (« Ana », « Toi » pour un message du PM lui-même)
        reponse  pour « reglee » : le lien https Slack de la réponse du PM, un message plus tardif que la demande (ni la demande
                 elle-même, ni le parent de son fil, ni un message antérieur : le jugement est alors écarté, la ligne reste ouverte)
        suite    pour « reglee », facultatif : ce que sa réponse annonce, en une phrase ; elle devient une ligne.
    Un jugement invalide est écarté, les autres passent. Rend les nombres et les écartés avec leur raison."""
    maintenant = time.time() if maintenant is None else maintenant
    if not isinstance(jugements, list):
        raise ValueError('« jugements » doit être une liste')
    with verrou_etat():
        return _slack_juger(jugements, maintenant)


def _slack_juger(jugements, maintenant):
    etat = lire_etat()
    fermees, suites, resumes, ecartes = [], 0, 0, []
    for j in jugements[:200]:
        j = j if isinstance(j, dict) else {}
        cle, verdict = j.get('cle'), j.get('verdict')
        ligne = etat.get(cle) if isinstance(cle, str) and CLE.match(cle) else None
        if not ligne or ligne.get('type') != 'a_toi' or ligne.get('fermee') or not fil_slack(ligne.get('lien')):
            ecartes.append({'cle': str(cle)[:20], 'raison': 'pas une ligne Slack ouverte'})
            continue
        if verdict not in VERDICTS:
            ecartes.append({'cle': cle, 'raison': 'verdict inconnu'})
            continue
        resume, qui, suite = _phrase(j.get('resume')), _phrase(j.get('qui'), 60), _phrase(j.get('suite'))
        if resume:
            ligne['resume'], resumes = resume, resumes + 1
        if qui:
            ligne['qui'] = qui
        if verdict == 'ouverte':
            continue
        reponse = j.get('reponse')
        if not fil_slack(reponse):
            ecartes.append({'cle': cle, 'raison': 'réponse sans lien Slack'})
            continue
        refus = _preuve_refusee(ligne, reponse)
        if refus:
            ecartes.append({'cle': cle, 'raison': refus})
            continue
        ligne.update(fermee=maintenant, par='slack', preuve=reponse)
        ligne['journal'] = (ligne.get('journal') or []) + [{'quand': maintenant, 'texte':
            'Fermée : réglée dans Slack (ta réponse, ou la décision prise par les personnes concernées).' + (f" Suite : « {suite} »." if suite else '')}]
        fermees.append(cle)
        if suite:
            nouvelle = cle_de(ligne['studio'], 'suite', cle)
            etat[nouvelle] = {'studio': ligne['studio'], 'type': 'a_toi', 'titre': suite, 'texte': suite,
                              'resume': suite, 'qui': 'Toi', 'premiere': maintenant, 'vue': maintenant,
                              'passage': maintenant, 'lien': reponse, 'fermee': None, 'par': None, 'suite_de': cle}
            suites += 1
    ecrire_etat(etat)
    return {'fermees': len(fermees), 'suites': suites, 'resumes': resumes, 'ecartes': ecartes}


def essai():
    """Le calcul sans rien écrire, en nombres seulement : aucun nom, aucun texte de projet."""
    s = calculer(ecrire=False)
    print(f"{len(s['studios'])} Studio(s) connu(s), dont {sum(1 for x in s['studios'] if x['role'] == 'pm')} en PM ; "
          f"{len(s['projets'])} avec quelque chose ; page {'connue' if s['page'] else 'inconnue'}")
    for i, x in enumerate(s['studios'], 1):
        p = next((p for p in s['projets'] if p['dossier'] == x['dossier']), None)
        n = {t: sum(1 for l in (p or {}).get('lignes', []) if l['type'] == t) for t in ('a_toi', 'reunion', 'question', 'entree')}
        ing = 'ingestion' if etat_ingestion(x['dossier']) else 'sans ingestion'
        print(f"Studio {i} · {x['role']} · {ing} · à toi {n['a_toi']} · réunions {n['reunion']} · questions {n['question']} · entrées {n['entree']}"
              f" · fermées depuis hier {(p or {}).get('fermees_depuis_hier', 0)}")
    return 0


def main(args):
    if args[:1] == ['--essai']:
        return essai()
    if args[:1] == ['fait']:
        if len(args) != 2:
            print('Usage : projets.py fait <cle>')
            return 2
        try:
            fermer(args[1])
        except ValueError as exc:
            print(f'Refusé : {exc} ({args[1]}).')
            return 2
        print(f'Fermée à la main : {args[1]}.')
        return 0
    if args:
        print(__doc__)
        return 2
    debut = time.time()
    s = calculer()
    n = sum(len(p['lignes']) for p in s['projets'])
    print(f"ok {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {n} ligne(s) dans {len(s['projets'])} projet(s) "
          f"sur {len(s['studios'])} Studio(s) · {time.time() - debut:.1f} s")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
