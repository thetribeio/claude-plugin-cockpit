#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mon Studio : un seul écran pour toutes ses sessions Claude, sans LLM.

    python3 parc.py                         # écrit ~/Mon Studio/mon-studio.md
    python3 parc.py --jours 7               # au-delà, une demande d'une session lue passe dans « Anciennes »
    python3 parc.py --silence 7             # un projet sans échange depuis N jours passe dans « silencieux »
    python3 parc.py --afficher              # rafraîchit si besoin et imprime mon-studio.md (ce que montre /parc)
    python3 parc.py --expliquer "<titre>"   # le tri phrase par phrase d'une session : gardé, écarté, pourquoi
    python3 parc.py --controle [JOURS]      # d'où vient le texte des lignes montrées au PM, et celles à vérifier (7 j)
    python3 parc.py --marqueur RUBRIQUE "<expression>"   # « ajoute ce marqueur » : le glossaire du PM

Quatre sources, sur le poste, en lecture seule : les fiches de session de l'app (titre, lien, archivée,
tâche planifiée), les pastilles de la barre latérale (stockage local de l'app), les transcripts, et les
miroirs des contremaîtres (~/Mon Studio/chantiers/*.json, ce que chaque chantier attend du PM).
L'écran est un tableau : une ligne par question ou action qui attend le PM (Studio, session, ce qui
l'attend, type, ancienneté), rien pour une session qui travaille ou a fini sans rien demander. Les
questions « À trancher » (« Q5 · Titre ») donnent une ligne chacune ; sinon, la phrase d'action la plus
forte du dernier message, mot pour mot. Le tableau se lit dans la page épinglée de l'app, par le connecteur
local (mcp_mon_studio.py, qui appelle construire et pour_la_page) ; mon-studio.md en garde une copie en Markdown.
Rien n'est écrit dans une session, rien n'est marqué lu ou non lu, rien n'est archivé.
"""
import argparse
import datetime as dt
import glob
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import stat
import struct
import sys
import time
import unicodedata

HOME = pathlib.Path.home()


def dossier_app(env=None, plateforme=None, home=None):
    """Le dossier de l'app Claude de bureau sur ce système : macOS ~/Library/Application Support/Claude, Windows
    %APPDATA%\\Claude, Linux ~/.config/Claude (XDG_CONFIG_HOME s'il est posé). Même règle que le point du kit
    foreman-pm 0.8 (fais_le_point.app_sessions_dir), pour que Mon Studio et le point lisent les mêmes fiches."""
    env = os.environ if env is None else env
    plateforme = plateforme or sys.platform
    home = pathlib.Path(home or HOME)
    if plateforme.startswith('win'):
        return (pathlib.Path(env['APPDATA']) if env.get('APPDATA') else home / 'AppData' / 'Roaming') / 'Claude'
    if plateforme == 'darwin':
        return home / 'Library' / 'Application Support' / 'Claude'
    return (pathlib.Path(env['XDG_CONFIG_HOME']) if env.get('XDG_CONFIG_HOME') else home / '.config') / 'Claude'


def dossier_fiches(env=None, plateforme=None, home=None):
    """Les fiches de session de l'app : MON_STUDIO_APP_SESSIONS d'abord, sur tout système."""
    env = os.environ if env is None else env
    if env.get('MON_STUDIO_APP_SESSIONS'):
        return pathlib.Path(env['MON_STUDIO_APP_SESSIONS'])
    return dossier_app(env, plateforme, home) / 'claude-code-sessions'


APP = dossier_fiches()
TRANSCRIPTS = HOME / '.claude' / 'projects'
STOCKAGE_APP = dossier_app() / 'Local Storage' / 'leveldb'
CLE_PASTILLES = b'epitaxy-unread-v1'
SORTIE = pathlib.Path(os.environ.get('MON_STUDIO', str(HOME / 'Mon Studio')))
INTERNE = SORTIE / '.parc'
LECTURE_OK = 'lecture-app-ok'   # in INTERNE: Mon Studio has read the app once on this Mac (lecture_app)

TRAVAIL_S = 180          # un tour inachevé dont le fichier a bougé il y a moins de 3 min : Claude travaille
FIN_INITIALE = 512 * 1024
LIGNES_MAX = 3
LONGUEUR_MAX = 420       # au-delà, la phrase est coupée net (les mots restent ceux de Claude)
VERSION_CACHE = 25   # 25 : titres courts, un titre garde son étiquette d'impact « (impact fort : échéance) » (0.3.2). une phrase qui cite une question répondue par son numéro ne la rouvre pas ; une carte de fin de tour suivie d'un texte garde sa question (« ask ») et son compte rendu ;
# une session arrêtée garde l'outil en attente et son extrait : les lignes déjà calculées sont refaites. 21 : les mots
# du PM d'un suivi de session sont rangés sous « pm ». 22 : un tour coupé sur un outil refusé garde cet outil (refus)
# 23 : un message du PM précédé des notes de l'app (<system-reminder>) est bien du PM : la carte à laquelle il répond se ferme.
# Une session dont la fiche a bougé il y a moins de 5 min et dont le transcript manque n'est pas « non lue » : le fichier
# d'un nouvel identifiant n'existe qu'avec son premier message. Cas du 30/10 à 17 h 53 : après une remise à zéro
# (clear_session) du contremaître, sa fiche pointait déjà vers le nouvel identifiant, sans transcript pendant une minute.
TRANSCRIPT_ATTENDU_S = 300
LIBELLE_MAX = 120        # tableau : une ligne de demande, coupée net
OUVERTURE_MAX = 160      # « sans action » : l'ouverture du dernier message de Claude, coupée net
CHANTIERS = SORTIE / 'chantiers'   # miroirs tenus par les contremaîtres : ce que chaque chantier attend du PM
FILS_ROUGES = SORTIE / 'fils-rouges.json'   # fils rouges des Studios sans chantier, tenus à la main : [{titre, sessionId}]
FIL_ROUGE_MESSAGES = 3   # a main thread by rule: a top-level session where the PM typed at least this many messages
HISTOIRE_MAX = 8 * 1024 * 1024     # la fin du transcript où suivre une question du tableau dans sa session (reglees)
NOUVELLE_S = 86400       # « Dernière nouvelle » d'une session de chantier : seulement si elle a moins d'un jour
NUMERO_REPRIS_S = 12 * 3600   # un numéro de chantier ne revient pas moins de 12 h après sa question (question.py)


# --- lecture des fiches de session de l'app ----------------------------------------------------------

def dossiers_app():
    return sorted(p for p in APP.glob('*/*') if p.is_dir())


def lire_json(chemin, defaut=None):
    try:
        with open(chemin, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecrire_atomique(chemin, texte):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # One temporary file per process: the connector (two instances at times) and the session hook write the same files.
    tmp = chemin.with_name(f'{chemin.name}.{os.getpid()}.tmp')
    tmp.write_text(texte, encoding='utf-8')
    os.replace(tmp, chemin)


def empreinte(chemin):
    st = os.stat(chemin)
    return [int(st.st_mtime), st.st_size]


def fiches(cache):
    """Toutes les fiches local_*.json, relues seulement si elles ont bougé."""
    vues, sortie = set(), []
    for dossier in dossiers_app():
        for chemin in glob.glob(str(dossier / 'local_*.json')):
            vues.add(chemin)
            try:
                emp = empreinte(chemin)
            except OSError:
                continue
            ent = cache['fiches'].get(chemin)
            if not ent or ent['emp'] != emp or 'detachee' not in ent['meta']:
                o = lire_json(chemin)
                if not isinstance(o, dict):
                    continue
                ent = {'emp': emp, 'meta': {
                    'id': o.get('sessionId'), 'cli': o.get('cliSessionId'), 'cwd': o.get('cwd') or '',
                    'titre': o.get('title') or '', 'archivee': bool(o.get('isArchived')),
                    'tache': o.get('scheduledTaskId'), 'activite': (o.get('lastActivityAt') or 0) / 1000,
                    'focus': (o.get('lastFocusedAt') or 0) / 1000,
                    'creee': (o.get('createdAt') or 0) / 1000,
                    'parent': (o.get('spawnedFrom') or {}).get('sessionId'),
                    # Launched by another session, then moved up to the top level of the sidebar (detach_session):
                    # the card keeps its spawnedFrom and says lineageDetached.
                    'detachee': bool(o.get('lineageDetached'))}}
                cache['fiches'][chemin] = ent
            sortie.append(ent['meta'])
    for chemin in list(cache['fiches']):
        if chemin not in vues:
            del cache['fiches'][chemin]
    return sortie


def taches_planifiees():
    taches = []
    for dossier in dossiers_app():
        o = lire_json(dossier / 'scheduled-tasks.json', {}) or {}
        taches.extend(o.get('scheduledTasks') or [])
    return taches


# --- les pastilles de la barre latérale ------------------------------------------------------------------
#
# L'app range l'état lu / non lu dans son stockage local (Chromium, base leveldb), clé `epitaxy-unread-v1` :
# {"state": {"unreadIds": [...], "explicitUnreadIds": [...]}}. La base se compacte toutes les quelques
# minutes : la clé vit tantôt dans le journal (.log), tantôt dans une table (.ldb, blocs compressés en
# Snappy). On lit les deux et on garde la version au numéro de séquence le plus haut. Lecture seule, sans
# verrou : un fichier qui disparaît pendant la lecture (compaction) fait recommencer une fois.

def _varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7f) << s
        if c < 0x80:
            return r, i
        s += 7


def _snappy(b):
    _, i = _varint(b, 0)
    out = bytearray()
    while i < len(b):
        t = b[i]
        i += 1
        if t & 3 == 0:
            n = t >> 2
            if n >= 60:
                k = n - 59
                n = int.from_bytes(b[i:i + k], 'little')
                i += k
            out += b[i:i + n + 1]
            i += n + 1
            continue
        if t & 3 == 1:
            n, off = ((t >> 2) & 7) + 4, ((t >> 5) << 8) | b[i]
            i += 1
        elif t & 3 == 2:
            n, off = (t >> 2) + 1, int.from_bytes(b[i:i + 2], 'little')
            i += 2
        else:
            n, off = (t >> 2) + 1, int.from_bytes(b[i:i + 4], 'little')
            i += 4
        for _ in range(n):
            out.append(out[-off])
    return bytes(out)


def _bloc(data, off, taille):
    brut = data[off:off + taille]
    return _snappy(brut) if data[off + taille] == 1 else brut


def _entrees_bloc(b):
    fin = len(b) - 4 - 4 * struct.unpack('<I', b[-4:])[0]
    i, cle = 0, b''
    while i < fin:
        partage, i = _varint(b, i)
        propre, i = _varint(b, i)
        lv, i = _varint(b, i)
        cle = cle[:partage] + b[i:i + propre]
        i += propre
        yield cle, b[i:i + lv]
        i += lv


def _versions_table(chemin):
    data = open(chemin, 'rb').read()
    pied = data[-48:]
    _, j = _varint(pied, 0)
    _, j = _varint(pied, j)
    off, j = _varint(pied, j)
    taille, j = _varint(pied, j)
    for _, poignee in _entrees_bloc(_bloc(data, off, taille)):
        o, k = _varint(poignee, 0)
        t, k = _varint(poignee, k)
        for cle, val in _entrees_bloc(_bloc(data, o, t)):
            if cle[:-8].endswith(CLE_PASTILLES):
                tag = int.from_bytes(cle[-8:], 'little')
                yield tag >> 8, tag & 0xff, val


def _versions_journal(chemin):
    data = open(chemin, 'rb').read()
    enregistrements, courant, i = [], b'', 0
    while i + 7 <= len(data):
        if 32768 - i % 32768 < 7:
            i += 32768 - i % 32768
            continue
        n, genre = struct.unpack('<H', data[i + 4:i + 6])[0], data[i + 6]
        morceau = data[i + 7:i + 7 + n]
        i += 7 + n
        if genre == 1:
            enregistrements.append(morceau)
        elif genre == 2:
            courant = morceau
        elif genre == 3:
            courant += morceau
        elif genre == 4:
            enregistrements.append(courant + morceau)
    for r in enregistrements:
        seq, n, j = int.from_bytes(r[:8], 'little'), struct.unpack('<I', r[8:12])[0], 12
        for k in range(n):
            genre = r[j]
            j += 1
            lk, j = _varint(r, j)
            cle = r[j:j + lk]
            j += lk
            val = b''
            if genre == 1:
                lv, j = _varint(r, j)
                val = r[j:j + lv]
                j += lv
            if cle.endswith(CLE_PASTILLES):
                yield seq + k, genre, val


def pastilles():
    """(non lues, marquées non lues à la main), ou None si le stockage de l'app est illisible."""
    for _ in range(2):
        try:
            versions = []
            for chemin in glob.glob(str(STOCKAGE_APP / '*.ldb')):
                versions.extend(_versions_table(chemin))
            for chemin in glob.glob(str(STOCKAGE_APP / '*.log')):
                versions.extend(_versions_journal(chemin))
            if not versions:
                return None
            _, genre, val = max(versions, key=lambda v: v[0])
            if genre == 0:
                return set(), set()
            texte = val[1:].decode('latin-1') if val[:1] == b'\x01' else val[1:].decode('utf-16-le')
            etat = json.loads(texte).get('state') or {}
            return set(etat.get('unreadIds') or []), set(etat.get('explicitUnreadIds') or [])
        except (OSError, ValueError, IndexError, struct.error):
            time.sleep(0.5)
    return None


def index_transcripts():
    return {os.path.basename(p)[:-6]: p for p in glob.glob(str(TRANSCRIPTS / '*' / '*.jsonl'))}


# --- lecture d'un transcript par la fin ----------------------------------------------------------------

SYSTEME = ('<task-notification>', '<local-command', 'This session is being continued', 'The app was quit',
           'Another Claude session sent', 'Continue from where you left off', '<system-reminder>',
           '<scheduled-task', 'Caveat: The messages below')


def texte_de(contenu):
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return '\n'.join(b.get('text', '') for b in contenu if isinstance(b, dict) and b.get('type') == 'text')
    return ''


NOTE_APP = re.compile(r'^(?:\s*<system-reminder>.*?</system-reminder>)+', re.S)


def nature_user(o):
    """'humain', 'outil' (résultat d'outil, milieu de tour) ou None (message système, à ignorer)."""
    if o.get('isMeta'):
        return None
    contenu = (o.get('message') or {}).get('content')
    if isinstance(contenu, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in contenu):
        return 'outil'
    origine = (o.get('origin') or {}).get('kind')
    if origine and origine != 'human':
        return None
    texte = texte_de(contenu).lstrip()
    # The app puts its own notes (« Linked sessions now… ») in front of the PM's words, in a <system-reminder> block
    # (seen on 2026-11-16): a message the app marks as the PM's is his once those notes are set aside. Without this, an
    # answer typed in the session never closed the card it answered.
    if origine == 'human' and NOTE_APP.match(texte):
        texte = NOTE_APP.sub('', texte).lstrip()
        if not texte and not any(isinstance(b, dict) and b.get('type') != 'text' for b in contenu or []):
            return None   # the app's notes alone, no word from the PM
    if texte.startswith(SYSTEME):
        return None
    if not texte and not (isinstance(contenu, list) and contenu):
        return None
    return 'humain'


def entrees_fin(chemin, taille):
    with open(chemin, 'rb') as f:
        f.seek(0, 2)
        n = f.tell()
        debut = max(0, n - taille)
        f.seek(debut)
        brut = f.read()
    lignes = brut.split(b'\n')
    if debut > 0:
        lignes = lignes[1:]
    entrees = []
    for ligne in lignes:
        if not ligne.strip():
            continue
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        if o.get('type') in ('user', 'assistant') and not o.get('isSidechain'):
            entrees.append(o)
    return entrees, debut == 0


def horodatage(o):
    try:
        return dt.datetime.fromisoformat(o['timestamp'].replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, AttributeError):
        return None


def analyser(chemin, maintenant):
    """État de la session, texte du dernier message final de Claude et son ouverture."""
    res = _analyser(chemin, maintenant)
    if res['etat'] != 'vide':
        res['ouverture'] = ouverture(res['texte']) if res.get('texte') else ouverture(dernier_texte_claude(chemin))
        res['recaps'] = recaps_de(chemin)
        if res['recaps']:
            res['recap'] = res['recaps'][-1]['texte']
    return res


RECAPS_MAX = 5


def recaps_de(chemin, n=RECAPS_MAX):
    """[{depuis, texte}] : les comptes rendus des dernières cartes de fin de tour (« recap ») dans la fin du transcript,
    du plus ancien au plus récent. Le journal de la vue projet, et l'état d'un sujet (le dernier)."""
    entrees, _ = entrees_fin(chemin, FIN_INITIALE)
    sortie = []
    for o in entrees:
        if o['type'] != 'assistant':
            continue
        for b in (o.get('message') or {}).get('content') or []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == FIN_DE_TOUR \
                    and isinstance(b.get('input'), dict) and str(b['input'].get('recap') or '').strip():
                sortie.append({'depuis': horodatage(o), 'texte': str(b['input']['recap']).strip()})
    return sortie[-n:]


def dernier_texte_claude(chemin):
    """Le dernier message final de Claude dans la fin du transcript, pour une session qui n'attend pas."""
    entrees, _ = entrees_fin(chemin, FIN_INITIALE)
    for j in range(len(entrees) - 1, -1, -1):
        m = entrees[j].get('message') or {}
        if entrees[j]['type'] == 'assistant' and m.get('stop_reason') == 'end_turn':
            mid, morceaux = m.get('id'), []
            while j >= 0 and entrees[j]['type'] == 'assistant' and (entrees[j].get('message') or {}).get('id') == mid:
                morceaux.append(texte_de((entrees[j].get('message') or {}).get('content')))
                j -= 1
            texte = '\n\n'.join(t for t in reversed(morceaux) if t.strip())
            if texte.strip():
                return texte
    return ''


def ouverture(texte, n=OUVERTURE_MAX):
    """Le premier paragraphe d'un message de Claude, sans décor : au format du PM, le résultat en deux ou
    trois lignes. Titres, blocs de code, tableaux et citations sont sautés."""
    bloc, en_code = [], False
    for ligne in texte.split('\n'):
        s = ligne.strip()
        if s.startswith('```'):
            en_code = not en_code
            if bloc:
                break
            continue
        if en_code or not s or s.startswith(('|', '>', '#')):
            if bloc:
                break
            continue
        bloc.append(s)
    # Une adresse web tiendrait la ligne à elle seule : on n'en garde que le site.
    texte = re.sub(r"https?://([^/\s)]+)[^\s)]*", r"\1/…", nettoyer(' '.join(bloc)))
    return couper(texte, n) if bloc else ''


def _analyser(chemin, maintenant):
    mtime = os.stat(chemin).st_mtime
    taille = FIN_INITIALE
    while True:
        entrees, tout = entrees_fin(chemin, taille)
        if entrees or tout:
            break
        taille *= 8
    if not entrees:
        return {'etat': 'vide', 'depuis': mtime}
    dernier = entrees[-1]
    # Le dernier événement qui compte : on saute les messages système (notifications, reprises).
    i = len(entrees) - 1
    while i >= 0 and entrees[i]['type'] == 'user' and nature_user(entrees[i]) is None:
        i -= 1
    if i < 0:
        return {'etat': 'vide', 'depuis': mtime}
    dernier = entrees[i]
    recent = maintenant - mtime < TRAVAIL_S
    if dernier['type'] == 'user':
        if nature_user(dernier) == 'outil':
            # La carte de fin de tour de l'app avec une question : l'outil répond aussitôt et le tour finit sur sa
            # réponse. La session attend le PM comme sur un menu, pas « arrêtée en plein travail ».
            carte = carte_en_attente(entrees[:i + 1])
            if carte:
                return dict(carte, etat='suspens', outil=FIN_DE_TOUR)
            res = {'etat': 'travaille' if recent else 'suspens', 'depuis': horodatage(dernier) or mtime}
            attente = outil_en_attente(entrees[:i + 1])
            if attente and res['etat'] == 'suspens':
                res['attente'] = attente
            return res
        if recent:
            return {'etat': 'travaille', 'depuis': mtime}
        res = {'etat': 'main', 'depuis': horodatage(dernier) or mtime}
        refus = outil_refuse(entrees[:i + 1])
        if refus:
            res['refus'] = refus   # the turn ended on a refused tool: an authorization nobody gave
        return res
    m = dernier.get('message') or {}
    if dernier.get('isApiErrorMessage') or m.get('model') == '<synthetic>':
        return {'etat': 'erreur', 'depuis': horodatage(dernier) or mtime, 'erreur': texte_de(m.get('content'))[:200]}
    if m.get('stop_reason') == 'end_turn' or m.get('stop_reason') is None and not any(
            b.get('type') == 'tool_use' for b in m.get('content') or [] if isinstance(b, dict)):
        mid, morceaux, j = m.get('id'), [], i
        while j >= 0 and entrees[j]['type'] == 'assistant' and (entrees[j].get('message') or {}).get('id') == mid:
            morceaux.append(texte_de((entrees[j].get('message') or {}).get('content')))
            j -= 1
        texte = '\n\n'.join(t for t in reversed(morceaux) if t.strip())
        if recent and not texte.strip():
            return {'etat': 'travaille', 'depuis': mtime}
        # Les questions « encore ouvertes » ont été posées dans un message précédent, ou dans un menu : on va chercher
        # leur titre dans la fin déjà lue, puis dans tout le transcript pour celles qui y manquent.
        _, ouverts = a_trancher(texte)
        ouverts += list(rappels_en_phrase(texte))   # rappelées dans une phrase, hors de « Encore ouvert »
        questions = historique_questions(entrees)
        manquent = [n for n in ouverts if str(n) not in questions]
        if manquent and not tout:
            questions.update(questions_anciennes(chemin, manquent))
        res = {'etat': 'attend', 'depuis': horodatage(dernier) or mtime, 'texte': texte, 'questions': questions}
        # Les questions que le PM a dites faites après leur dernière liste (dites_faites) : plus de ligne.
        sv = suivi_session(entrees[:i + 1])
        faites = sorted(dites_faites(sv))
        if faites:
            res['faites'] = faites
        # Celles auxquelles le PM a répondu par leur numéro depuis que la session les a posées : une phrase de la
        # réponse qui les cite rend compte, elle ne les repose pas (repondues).
        deja = sorted(repondues(sv))
        if deja:
            res['repondues'] = deja
        # La carte de fin de tour de l'app, suivie du dernier texte de Claude (le cas courant) : son compte rendu
        # (« recap ») dit l'état de la session, et sa question (« ask ») reste ouverte tant que le PM n'a pas écrit.
        fin = fin_de_tour(entrees)
        if fin and fin.get('recap'):
            res['recap'] = fin['recap']
        if fin and fin.get('menu'):
            res['carte'] = {'menu': fin['menu'], 'depuis': fin['depuis']}
        # Un rappel sans numéro (« Encore ouvert : l'étape 3, en attente de ta réponse dans l'encadré ») : la dernière
        # boîte à laquelle le PM n'a pas répondu porte la question.
        if rappel_sans_numero(texte):
            res['encadre'] = encadre_ouvert(entrees[:j + 1])
        return res
    outil = next((b.get('name') for b in m.get('content') or [] if isinstance(b, dict) and b.get('type') == 'tool_use'), None)
    # Un menu de questions (AskUserQuestion) attend le PM dès qu'il s'affiche, même dans les trois minutes : on garde
    # ses questions, ses options et la recommandation, pour les montrer en entier.
    mid, j, menu = m.get('id'), i, None
    while j >= 0 and menu is None and entrees[j]['type'] == 'assistant' and (entrees[j].get('message') or {}).get('id') == mid:
        menu = next((lire_menu(b.get('input')) for b in (entrees[j].get('message') or {}).get('content') or []
                     if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'AskUserQuestion'), None)
        j -= 1
    if menu:
        return {'etat': 'suspens', 'depuis': horodatage(dernier) or mtime, 'outil': 'AskUserQuestion', 'menu': menu}
    res = {'etat': 'travaille' if recent else 'suspens', 'depuis': horodatage(dernier) or mtime, 'outil': outil}
    attente = outil_en_attente(entrees[:i + 1])
    if attente and res['etat'] == 'suspens':
        res['attente'] = attente   # l'outil qui attend l'accord du PM, et un aperçu de ce qu'il ferait
    return res


EXTRAIT_MAX = 200
# Le champ qui dit le mieux ce que fera un outil, dans l'ordre : la commande, le chemin, l'adresse, le motif…
CHAMPS_EXTRAIT = ('command', 'file_path', 'notebook_path', 'path', 'url', 'pattern', 'query', 'prompt', 'text', 'message',
                  'body', 'title', 'subject', 'description')


# A tool's name as the PM reads it (PM, 2026-11-17: « Arrêtée sur une autorisation (mcp__749c…__slack_search_public_
# and_private) »). Never the raw name: an MCP tool is `mcp__<server>__<tool>`, the server often an opaque identifier.
NOMS_OUTILS = {
    'Bash': 'commande du terminal', 'Read': "lecture d'un fichier", 'Write': "écriture d'un fichier",
    'Edit': "modification d'un fichier", 'MultiEdit': "modification d'un fichier", 'NotebookEdit': "modification d'un notebook",
    'Glob': 'recherche de fichiers', 'Grep': 'recherche dans les fichiers', 'WebFetch': "lecture d'une page web",
    'WebSearch': 'recherche web', 'AskUserQuestion': 'question', 'Skill': "lancement d'un skill", 'Agent': 'sous-agent',
    'Task': 'sous-agent', 'ToolSearch': "chargement d'outils", 'TodoWrite': 'liste des tâches',
    # MCP tools, by the name after the server (the server's identifier changes from one Mac to another)
    'slack_search_public_and_private': 'recherche Slack', 'slack_search_public': 'recherche Slack',
    'slack_search_channels': 'recherche de canaux Slack', 'slack_search_users': 'recherche de personnes dans Slack',
    'slack_read_thread': "lecture d'un fil Slack", 'slack_read_channel': "lecture d'un canal Slack",
    'slack_read_user_profile': "lecture d'un profil Slack", 'slack_read_canvas': "lecture d'un canvas Slack",
    'slack_read_file': "lecture d'un fichier Slack", 'slack_list_user_channels': 'liste des canaux Slack',
    'slack_get_reactions': 'lecture des réactions Slack', 'slack_send_message': "envoi d'un message Slack",
    'slack_send_message_draft': "brouillon d'un message Slack", 'slack_schedule_message': "envoi programmé d'un message Slack",
    'slack_add_reaction': "réaction dans Slack",
    'search_threads': 'recherche dans Gmail', 'get_thread': "lecture d'un mail", 'get_message': "lecture d'un mail",
    'list_drafts': 'lecture des brouillons de mail', 'get_draft': "lecture d'un brouillon de mail",
    'search_events': "recherche dans l'agenda", 'get_event': "lecture de l'agenda", 'list_calendars': "lecture de l'agenda",
    'search_files': 'recherche dans le Drive', 'read_file_content': "lecture d'un fichier du Drive",
    'download_file_content': "lecture d'un fichier du Drive", 'get_file_metadata': "lecture d'un fichier du Drive",
    'searchJiraIssuesUsingJql': 'recherche Jira', 'getJiraIssue': "lecture d'un ticket Jira",
    'addCommentToJiraIssue': 'commentaire Jira', 'editJiraIssue': "modification d'un ticket Jira",
    'createJiraIssue': "création d'un ticket Jira", 'transitionJiraIssue': "changement de statut d'un ticket Jira",
    'getConfluencePage': "lecture d'une page Confluence", 'searchConfluenceUsingCql': 'recherche Confluence',
    'notion-search': 'recherche Notion', 'notion-fetch': "lecture d'une page Notion",
    'list_scheduled_tasks': 'liste des tâches planifiées', 'list_task_runs': "lecture des passages d'une tâche planifiée",
    'list_sessions': 'liste des sessions', 'list_events': "lecture d'une session", 'update_plan': 'liste des tâches de la session',
    'wrap_up': 'fin de tour', 'start_session': "lancement d'une session", 'archive_session': "archivage d'une session",
}
# Same tool name, other servers: the server says which
NOMS_PAR_SERVEUR = {('list_events', 'agenda'): "lecture de l'agenda"}
PRODUITS = (('slack', 'Slack'), ('gmail', 'Gmail'), ('jira', 'Jira'), ('confluence', 'Confluence'), ('notion', 'Notion'),
            ('drive', 'Drive'), ('calendar', "l'agenda"), ('figma', 'Figma'), ('miro', 'Miro'), ('boond', 'Boond'),
            ('mon-studio', 'Mon Studio'), ('scheduled-tasks', 'tâches planifiées'), ('ccd_session', 'sessions'))
SERVEUR_OPAQUE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def nom_outil(nom):
    """« recherche Slack » for `mcp__749c…__slack_search_public_and_private`, « commande du terminal » for Bash. An
    unknown tool: its words, with its product when its name or its server says it (« Boond : browser click »); never
    `mcp__`."""
    nom = str(nom or '').strip()
    if not nom:
        return ''
    if not nom.startswith('mcp__'):
        return NOMS_OUTILS.get(nom, nom)
    reste = nom[len('mcp__'):]
    serveur, _, outil = reste.rpartition('__')
    if not serveur:
        serveur, outil = '', reste
    connu = NOMS_OUTILS.get(outil)
    if outil == 'list_events' and serveur and 'session' not in serveur:
        connu = NOMS_PAR_SERVEUR[('list_events', 'agenda')]
    if connu:
        return connu
    vu = f"{serveur} {outil}".lower()
    produit = next((p for cle, p in PRODUITS if cle in vu), '')
    if not produit and serveur and not SERVEUR_OPAQUE.match(serveur):
        produit = serveur.replace('_', ' ').replace('-', ' ').strip()
    mots = ' '.join(re.sub(r'([a-z])([A-Z])', r'\1 \2', outil).replace('_', ' ').replace('-', ' ').split()).lower()
    for cle, _ in PRODUITS:   # « slack search public » under « Slack » says Slack once
        mots = ' '.join(m for m in mots.split() if m != cle) or mots
    return f"{produit} : {mots}" if produit else f"outil « {mots} »"


def extrait_lisible(extrait):
    """An extract « <tool> · <detail> » (extrait_outil, the authorization hook) with the tool's name translated."""
    s = str(extrait or '')
    tete, sep, reste = s.partition(' · ')
    if tete and ' ' not in tete and (tete.startswith('mcp__') or tete in NOMS_OUTILS):
        return nom_outil(tete) + sep + reste
    return s


def extrait_outil(nom, entree, n=EXTRAIT_MAX):
    """« Bash · git push origin main » : le nom de l'outil, puis sa commande, son chemin ou son premier champ texte,
    sur une ligne, coupé à n caractères environ. Ce que la session ferait si le PM l'autorise."""
    detail = ''
    if isinstance(entree, dict):
        cles = [k for k in CHAMPS_EXTRAIT if isinstance(entree.get(k), str) and entree[k].strip()]
        cles += [k for k, v in entree.items() if k not in cles and isinstance(v, str) and v.strip()]
        detail = entree[cles[0]] if cles else ''
    detail = ' '.join(detail.split())
    nom = nom_outil(nom)
    ligne = f"{nom} · {detail}" if nom and detail else (nom or detail or '')
    return ligne if len(ligne) <= n else ligne[:n - 1].rstrip() + '…'


def outil_en_attente(entrees):
    """{outil, extrait} : le premier appel d'outil du dernier message de Claude qui n'a pas encore de résultat, celui que
    la session attend de faire (une autorisation, le plus souvent) ; None quand tous ont leur résultat."""
    repondus, poses, mid = set(), [], None
    for o in reversed(entrees):
        contenu = (o.get('message') or {}).get('content')
        if o['type'] == 'user':
            if nature_user(o) == 'humain':
                break
            repondus |= {b.get('tool_use_id') for b in contenu if isinstance(b, dict) and b.get('type') == 'tool_result'} \
                if isinstance(contenu, list) else set()
            continue
        if o['type'] != 'assistant':
            continue
        m_id = (o.get('message') or {}).get('id')
        if mid is None:
            mid = m_id
        elif m_id != mid:
            break
        poses = [b for b in contenu if isinstance(b, dict) and b.get('type') == 'tool_use'] + poses \
            if isinstance(contenu, list) else poses
    for b in poses:
        if b.get('id') not in repondus:
            return {'outil': b.get('name') or '', 'extrait': extrait_outil(b.get('name'), b.get('input'))}
    return None


REFUS_OUTIL = re.compile(r"^\s*\[Request interrupted by user for tool use\]")


def outil_refuse(entrees):
    """{outil, extrait} when this piece of transcript ends on « [Request interrupted by user for tool use] »: the
    authorization of a tool was refused, or was never given and the app dropped it (measured on 2026-11-10: a scheduled
    pass waited 1 h 45 on Bash, then ended so). The tool is the last one Claude called before. None otherwise."""
    if not entrees or not REFUS_OUTIL.match(texte_de((entrees[-1].get('message') or {}).get('content'))):
        return None
    for o in reversed(entrees[:-1]):
        if o['type'] == 'user':
            if nature_user(o) == 'humain':
                return None
            continue
        contenu = (o.get('message') or {}).get('content')
        outils = [b for b in contenu if isinstance(b, dict) and b.get('type') == 'tool_use'] \
            if o['type'] == 'assistant' and isinstance(contenu, list) else []
        if outils:
            b = outils[-1]
            return {'outil': b.get('name') or '', 'extrait': extrait_outil(b.get('name'), b.get('input'))}
    return None


RECOMMANDE = re.compile(r"(?i)\s*\((?:recommandée?s?|recommended|conseillée?s?)\)")


def lire_menu(entree):
    """[{question, options: [{label, description, recommande}]}] : les questions d'un menu AskUserQuestion, ou None.
    La recommandation est l'option marquée « (Recommandé) », marque retirée du libellé."""
    sortie = []
    for q in (entree or {}).get('questions') or [] if isinstance(entree, dict) else []:
        if not isinstance(q, dict) or not str(q.get('question') or '').strip():
            continue
        options = []
        for o in q.get('options') or []:
            if isinstance(o, dict) and str(o.get('label') or '').strip():
                libelle = str(o['label'])
                options.append({'label': RECOMMANDE.sub('', libelle).strip(), 'recommande': bool(RECOMMANDE.search(libelle)),
                                'description': str(o.get('description') or '').strip()})
        sortie.append({'question': str(q['question']).strip(), 'options': options})
    return sortie or None


def options_menu(q):
    """« Go, tout (recommandé) · Pas encore » : les options d'une question de menu (lire_menu), la recommandée marquée."""
    return ' · '.join(o['label'] + (' (recommandé)' if o['recommande'] else '') for o in q['options'])


def detail_menu(q):
    """La question d'un menu en entier, puis chaque option avec sa description, la recommandée marquée."""
    def phrase(o):
        t = o['label'] + (' (recommandé)' if o['recommande'] else '') + (' : ' + o['description'] if o['description'] else '')
        return t if t.endswith(('.', '!', '?', '…')) else t + '.'
    return (q['question'] + ' ' + ' '.join(phrase(o) for o in q['options'])).strip()


FIN_DE_TOUR = 'mcp__ccd_turn__wrap_up'   # la carte de fin de tour de l'app : une question (« ask ») et ses réponses prêtes


def menus_de(contenu):
    """Les questions (lire_menu) qu'un message de Claude pose dans une boîte, dans l'ordre : ses menus AskUserQuestion,
    et la question de sa carte de fin de tour (« ask » ; ses « actions » pour options, le message que chacune envoie
    pour description)."""
    sortie = []
    for b in contenu if isinstance(contenu, list) else []:
        if not (isinstance(b, dict) and b.get('type') == 'tool_use' and isinstance(b.get('input'), dict)):
            continue
        if b.get('name') == 'AskUserQuestion':
            sortie += lire_menu(b['input']) or []
        elif b.get('name') == FIN_DE_TOUR and b['input'].get('ask'):
            options = [{'label': a.get('label'), 'description': a.get('message')}
                       for a in b['input'].get('actions') or [] if isinstance(a, dict)]
            sortie += lire_menu({'questions': [{'question': b['input']['ask'], 'options': options}]}) or []
    return sortie


def carte_en_attente(entrees):
    """{menu, depuis} si ce bout de transcript finit sur la carte de fin de tour de l'app avec une question : le
    dernier message de Claude la pose, et seules les réponses de ses outils le suivent. Sinon None."""
    k = len(entrees) - 1
    while k >= 0 and entrees[k]['type'] == 'user' and nature_user(entrees[k]) in ('outil', None):
        k -= 1
    if k < 0 or entrees[k]['type'] != 'assistant':
        return None
    mid = (entrees[k].get('message') or {}).get('id')
    while k >= 0 and entrees[k]['type'] == 'assistant' and (entrees[k].get('message') or {}).get('id') == mid:
        contenu = (entrees[k].get('message') or {}).get('content')
        if any(isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == FIN_DE_TOUR
               for b in (contenu if isinstance(contenu, list) else [])):
            menu = menus_de(contenu)
            return {'menu': menu, 'depuis': horodatage(entrees[k])} if menu else None
        k -= 1
    return None


def fin_de_tour(entrees):
    """{recap, depuis[, menu]} : la dernière carte de fin de tour de l'app dans ce bout de transcript, ou None. Son
    menu (sa question « ask » et ses réponses prêtes, menus_de) seulement si aucun message du PM ne la suit : un
    message du PM après la carte y répond, ou passe à autre chose. Elle reste lisible même suivie d'un texte de Claude,
    qui est le cas courant (mesuré le 2026-11-03 : la carte puis un message final)."""
    humain = False
    for o in reversed(entrees):
        contenu = (o.get('message') or {}).get('content')
        if o['type'] == 'user':
            if nature_user(o) == 'humain' and not INTERRUPTION.match(texte_de(contenu)):
                humain = True
            continue
        for b in contenu if isinstance(contenu, list) else []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == FIN_DE_TOUR \
                    and isinstance(b.get('input'), dict):
                res = {'recap': str(b['input'].get('recap') or '').strip(), 'depuis': horodatage(o)}
                menu = None if humain else menus_de([b])
                if menu:
                    res['menu'] = menu
                return res
    return None


REPONDU = re.compile(r"(?i)\banswered\b")   # réponse d'un menu : « Your questions have been answered: … »


def encadre_ouvert(entrees):
    """{menu, depuis} : la dernière boîte (menus_de) de ce bout de transcript à laquelle le PM n'a pas répondu, ni par
    un message ni dans le menu ; sinon None. Pour un rappel sans numéro, qui renvoie à « l'encadré »."""
    repondus = set()
    for o in reversed(entrees):
        contenu = (o.get('message') or {}).get('content')
        if o['type'] == 'user':
            nature = nature_user(o)
            if nature == 'humain' and not INTERRUPTION.match(texte_de(contenu)):
                return None
            if nature == 'outil':
                repondus |= {b.get('tool_use_id') for b in contenu if isinstance(b, dict)
                             and b.get('type') == 'tool_result' and REPONDU.search(texte_de(b.get('content')))}
            continue
        menu = menus_de(contenu)
        if menu:
            poses = {b.get('id') for b in contenu if isinstance(b, dict) and b.get('type') == 'tool_use'}
            return None if poses & repondus else {'menu': menu, 'depuis': horodatage(o)}
    return None


def rappel_sans_numero(texte):
    """Vrai si une ligne « Encore ouvert » du message ne porte aucun numéro de question."""
    en_code = False
    for ligne in (texte or '').split('\n'):
        if ligne.lstrip().startswith(('```', '~~~')):
            en_code = not en_code
        elif not en_code and debut_section(ligne) == 'ouvert' and not REF_QUESTION.search(ligne):
            return True
    return False


def analyser_cache(chemin, cache, maintenant):
    emp = empreinte(chemin)
    gl = signature_marqueurs()   # un marqueur ajouté au glossaire refait le tri des sessions déjà lues
    ent = cache['transcripts'].get(chemin)
    if ent and ent['emp'] == emp and ent.get('gl', '') == gl and ent['res']['etat'] != 'travaille':
        return ent['res']
    res = analyser(chemin, maintenant)
    cache['transcripts'][chemin] = {'emp': emp, 'gl': gl, 'res': res}
    return res


# --- le tri des phrases ----------------------------------------------------------------------------------
#
# Une phrase est gardée si elle attend une réponse ou un geste du PM. Priorités (la plus petite d'abord) :
#   1 feu vert, validation, décision demandée     2 question qui lui est adressée
#   3 élément d'une section ou d'une liste annoncée comme « pour toi »
#   4 geste à faire (impératif en tête, « tu peux », case à cocher)
#   5 proposition ou recommandation de Claude (attend un oui), seulement s'il n'y a rien de plus fort
# Les options qui suivent une question gardée la rejoignent sur sa ligne. Au plus trois lignes, les plus
# fortes, puis remises dans l'ordre du message.

DEUXIEME = r"(?:\btu\b|\bt['’]|\bte\b|\bton\b|\bta\b|\btes\b|\btoi\b|\bvous\b|\bvotre\b|\bvos\b)"
FEU = re.compile(r"""(?ix)
    feux?\s+verts? | \b(?:ton|un|le|ce)\s+go\b | \bgo\s*\? | [«"`]\s*go\s*[»"`] | \bréponds?\s+[«"`]?\s*(?:go|oui|ok)\b
  | \bdis[- ]moi\b | \bdites[- ]moi\b | \btu\s+me\s+dis\b | \bdis[- ]le[- ]moi\b
  | \bton\s+(?:accord|avis|choix|arbitrage|ok|aval|autorisation)\b | \battend(?:ent)?\s+(?:ton|ta|tes)\b | \bta\s+(?:validation|confirmation|décision)\b
  | \b(?:envoie|donne|fais|renvoie)[- ]moi\b | \bm['’](?:envoyer|envoies|donner|dire)\b
  | \bà\s+toi\s+de\b | \bà\s+toi\b\s*[:.!]? \s*$ | \bc['’]est\s+à\s+toi\b
  | \bà\s+(?:trancher|arbitrer|décider|valider)\b | \bj['’]attends\b | \ben\s+attente\s+de\s+(?:ta|ton|tes|toi)\b
  | \bil\s+me\s+faut\b | \bj['’]ai\s+besoin\s+de\b | \bsur\s+ton\s+signal\b
  | \bdès\s+que\s+tu\s+(?:as\s+|auras\s+)?(?:tranch|valid|confirm|décid|répond|me\s+di|m['’]|donn)
  | \bsi\s+tu\s+(?:valides|confirmes|es\s+d['’]accord|me\s+dis|me\s+donnes)\b
  | \bde\s+ton\s+côté\b | \bcôté\s+PM\b | \bton\s+tour\b | \bpour\s+toi\s*:
""")
NEGATION = re.compile(r"(?i)\brien\s+(?:à\s+faire|de\s+ton|d['’]autre|n['’]attend|ne\s+t['’]attend)|\bplus\s+rien\s+à\b"
                      r"|\baucun(?:e)?\s+(?:action|geste|retour|décision)\b|^possible\s+ensuite\b"
                      r"|\bpas\s+(?:à|pour)\s+(?:trancher|décider|valider|arbitrer)\b"
                      r"|\bpas\s+besoin\b|\bn['’]a\s+(?:pas|plus)\s+besoin\b|\bsans\s+(?:rien|action)\b|\bpas\s+de\s+feu\s+vert\b"
                      r"|\bsi\s+(?:ce\s+n['’]est\s+pas\s+le\s+cas|ça\s+ne\s+(?:marche|fonctionne|va)\s+pas|quelque\s+chose\s+(?:cloche|coince|ne\s+va\s+pas)"
                      r"|tu\s+(?:vois|as|rencontres)\s+(?:un|une)\s+(?:souci|problème|erreur|bug))")
# Une phrase qui annonce une question close (« Q144 (Kit : feu vert aux écritures…) est soldée au
# tableau. » sortait en feu vert) : un compte rendu, jamais une demande, même avec « feu vert », « go » ou « relire ».
CLOSE = re.compile(r"(?i)\b(?:est|sont|était|étaient|reste|restent|a\s+été|ont\s+été|déjà|bien|maintenant|désormais)\s+"
                   r"(?:(?:déjà|bien|maintenant|désormais|toutes?|tous)\s+)*"
                   r"(?:soldée?s?|réglée?s?|résolue?s?|fermée?s?|clos(?:es?)?)\b"
                   r"|\bsans\s+objet\b|\bdéjà\s+fait(?:e|es|s)?\b"
                   r"|\best\s+(?:\S+\s+){0,2}au\s+tableau\b|\bsont\s+(?:\S+\s+){0,2}au\s+tableau\b")
SUJET_QUESTION = re.compile(r"(?i)\bQ\d{1,3}\b|\b(?:questions?|attentes?|lignes?)\b")   # la phrase parle d'une question
# Une phrase qui dit que rien n'attend le PM (contremaître d'un Studio : « Rien n'est en attente de
# ta part de mon côté. », fin d'un message, restait 15 h au tableau en « Répondre », par « en attente de ta ») : jamais
# une demande, dans n'importe quel ordre (« De ta part, rien n'est attendu »). La négation ouvre sa proposition et porte
# sur l'attente ; le PM est nommé dans la phrase. Une autre proposition qui s'adresse au PM (« Une question t'attend,
# rien d'urgent », « Aucune question pour toi, relance la CI »), une exception (« sauf », « mais », « au-delà ») ou un
# PM attendu plus tard (« sans ton go », « avant ta validation ») la laisse au tri.
RIEN_POUR_TOI = re.compile(r"(?i)^(?:il\s+n['’]y\s+a|il\s+ne\s+(?:reste|manque)|tu\s+n['’]as|je\s+n['’](?:ai|attends)|on\s+n['’](?:a|attend))?"
                           r"\s*(?:(?:donc|du\s+coup|encore|toujours|plus|absolument)\s+)*"
                           r"(?:(?:rien|aucune?|nul(?:le)?)\b|(?:pas|plus)\s+(?:de\b|d['’]))")
ATTENTE = re.compile(r"(?i)\battend|\battente|\bdemandes?\b|\bgestes?\b|\bquestions?\b|\bactions?\b|\bdécisions?\b|\bréponses?\b"
                     r"|\bretours?\b|\bfeux?\s+verts?\b|\bgo\b|\bvalidations?\b|\brequise?s?\b"
                     r"|\bà\s+(?:faire|trancher|décider|valider|arbitrer|signaler|relire|confirmer)\b")
TOI = re.compile(DEUXIEME + r"|\bde\s+ta\s+part\b|\bcôté\s+PM\b", re.I)
# Une phrase qui parle d'une demande ou d'une ligne, sans s'adresser au PM (« Les vraies demandes restent, comme … ») : un compte rendu sur les demandes, pas une demande. Seulement « demande » et
# « ligne » précédés d'un déterminant : « Mes questions restent ouvertes (…) » ou « Feu vert, quand ce sera prêt : … »
# sont de vraies demandes (essai sur 14 jours de messages). Hors des sections « pour toi ».
PARLE_DE_DEMANDE = re.compile(r"(?i)^(?:les?|la|l['’]|une?|des|cette|ces|chaque|leurs?|ses|sa|son)\s+(?:\w+\s+){0,2}?(?:demandes?|lignes?)\b"
                              r"(?!\s*:)")
EXCEPTION = re.compile(r"(?i)\b(?:mais|sauf|hormis|excepté|seulement|sinon|hors)\b|\bà\s+part\b|\ben\s+dehors\s+d|\bsi\s+ce\s+n['’]est\b"
                       r"|\bau-delà\b|\bà\s+l['’]exception\b|\ben\s+plus\s+d"
                       # « Rien ne sort sans ton go », « …avant ta validation » : la négation porte sur l'écriture, le PM
                       # reste attendu.
                       r"|\b(?:sans|avant|tant\s+que|tant\s+qu['’]|en\s+attendant|jusqu['’]à)\b")
LOCATIF = re.compile(r"(?i)\bde\s+(?:ta|ma|notre)\s+part\b|\b(?:de\s+)?(?:ton|mon|notre)\s+côté\b|\bcôté\s+PM\b"
                     r"|\bpour\s+(?:toi|l['’]instant|le\s+moment)\b|\bà\s+ce\s+stade\b|\b(?:maintenant|aujourd['’]hui|donc|du\s+coup"
                     r"|bref|ici|voilà|et|bonne\s+nouvelle)\b")
# « …, jamais à toi », « pas à toi », « pas de ton côté » : la phrase dit justement que ce n'est pas au PM (contrôle des
# lignes du 2026-10-20 : « Un écart sans décision tracée se demande au fil rouge du sujet, jamais à toi. » sortait en
# demande, « à toi » en fin de phrase). Le morceau nié est retiré avant le tri, le reste de la phrase est jugé seul :
# « Pas à toi de trancher : dis-moi juste si le texte te va. » reste une demande.
NIE_TOI = re.compile(r"(?i)[,;]?\s*\b(?:jamais|pas|plus|non|ni)\s+(?:à\s+toi|pour\s+toi|de\s+ton\s+(?:côté|ressort)|toi)\b")
INVITE = re.compile(r"(?i)^(?:tu\s+peux|tu\s+dois|tu\s+pourras|il\s+te\s+(?:reste|faut|suffit)|il\s+faudra\s+que\s+tu"
                    r"|peux[- ]tu|pourrais[- ]tu|veux[- ]tu|merci\s+de|n['’]oublie\s+pas|pense\s+à)\b")
RAPPORT = re.compile(r"(?i)^(?:j['’]ai|je\s+n['’]ai|j['’]avais|je\s+viens|je\s+suis|c['’]est\s+fait|fait\b|corrigé|ajouté|écrit"
                     r"|vérifié|testé|mis\s+à\s+jour|terminé|livré|résultat)")
IMPERATIFS = set("""
ouvre rouvre lance relance colle copie clique renseigne remplis vérifie envoie réponds ajoute rajoute supprime
retire installe exécute approuve autorise connecte reconnecte regarde lis relis teste choisis donne indique précise
signe partage transmets demande préviens appelle écris crée mets passe garde coche tape saisis redémarre recharge
active désactive accepte refuse programme planifie valide confirme tranche décide dis fais prends note glisse dépose
ferme change remplace modifie corrige complète branche relève tranchez validez confirmez dites choisissez
révoque range fie va désinstalle réinstalle survole colorie enregistre recolle clos rappelle contacte poste publie
transfère déplace renomme importe exporte télécharge
""".split())
A_INFINITIF = re.compile(r"(?i)\b(?:prêtes?\s+|prêts?\s+)?à\s+(?:coller|lancer|relancer|ouvrir|copier|relire|signer|envoyer|transmettre"
                         r"|remplir|renseigner|tester|installer|exécuter|approuver|contester|poster)\b")
MESSAGE_A_ENVOYER = re.compile(r"(?i)^(?:le\s+|un\s+|ton\s+)?(?:message|mail|courriel|texte|brouillon|réponse)\s+"
                               r"(?:pour|à\s+(?:envoyer|poster|transmettre|coller|copier))\b[^.?!]{0,80}:$")
PROPOSE = re.compile(r"(?i)\b(?:je\s+te\s+propose|je\s+propose|je\s+recommande|je\s+suggère|ma\s+recommandation)\b")
CONNECTEURS = re.compile(r"(?i)^(?:puis|ensuite|enfin|alors|et|d['’]abord|après|sinon|maintenant)\b[\s,:]*")
SUBORDONNEE = re.compile(r"(?i)^(?:pour|si|s['’]ils?|quand|lorsque|dès\s+que|une\s+fois|avant\s+de|en\s+attendant|côté)\b[^,:]{0,140}[,:]\s*")
SECTION_POUR_TOI = re.compile(r"(?i)(?:\bà\s+toi\b|pour\s+toi|de\s+ton\s+côté|ton\s+tour|\btes\s+(?:actions?|gestes?|décisions?)"
                              r"|à\s+(?:contester|confirmer|relire|vérifier|revoir)\b"
                              r"|ce\s+que\s+j['’]attends|ce\s+qu['’]il\s+(?:te\s+)?reste|reste\s+à\s+faire|à\s+(?:valider|trancher|décider|arbitrer)"
                              r"|feux?\s+verts?|décisions?\s+(?:attendues?|à\s+prendre)|questions?\s+pour\s+toi|côté\s+PM"
                              r"|prochaines?\s+étapes?|next\s+steps?|à\s+faire\b|consignes?)")
PROCEDURE_TOI = re.compile(r"(?i)^(?:pour|avant\s+de|afin\s+de)\s+\w+(?:er|ir|re)\b.*\b(?:ton|ta|tes|toi|tu|te)\b")
# Une action, c'est une demande (PM, 2026-10-13 : « vérifier et comprendre si la session en elle-même attend une
# réponse de ma part ») : une question, un go, une réponse demandée, ou un geste sans lequel la session ne repart pas.
# Un intitulé qui demande une réponse : ses éléments sont des demandes, même à l'impératif.
SECTION_DEMANDE = re.compile(r"(?i)ce\s+que\s+j['’]attends|à\s+(?:valider|trancher|décider|arbitrer|contester|confirmer|relire|vérifier|revoir)\b"
                             r"|feux?\s+verts?|décisions?\s+(?:attendues?|à\s+prendre)|questions?\s+pour\s+toi|\btes\s+décisions?")
# Un geste attendu : la phrase lie la suite du travail au geste, ou montre un menu ou une autorisation en attente.
# Sans cela, un impératif est un conseil ou une nouvelle (« Tu peux fermer cette session », « Voici le texte à coller »).
REPART = re.compile(r"""(?ix)
    \b(?:relance|reviens|rappelle|recontacte)[- ]moi\b | \breviens\s+(?:ici|me\s+voir|vers\s+moi|dans\s+cette\s+session)\b
  | \bon\s+reprend\b | \bje\s+(?:reprends|reprendrai|continue(?:rai)?|poursuis|poursuivrai|termine(?:rai)?|finis|finirai|enchaîne(?:rai)?)\b
  | \bpour\s+(?:que\s+je|avancer|continuer|poursuivre|reprendre|débloquer|repartir)\b | \bavant\s+que\s+je\b
  | \bune\s+fois\s+(?:que\s+)?(?:c['’]est\s+)?fait\b | \bdès\s+que\s+c['’]est\s+fait\b | \bsans\s+(?:ça|cela|quoi)\b
  | \bvient\s+d['’]appara[iî]tre\b | \b(?:affichée?s?|apparue?s?)\s+(?:juste\s+)?(?:au-dessus|ci-dessus|plus\s+haut)\b
  | \bautoris(?:e|es|er|ation|ations)\b | \bapprouve\b | [«"]\s*connecter\s*[»"]
""")
# Avertissement pour plus tard (« Quand tu ouvriras le tableau…, accepte »), comme « si… » : pas une action.
CONDITION = re.compile(r"(?i)^(?:si|s['’]ils?|sinon|quand|lorsque?|la\s+prochaine\s+fois|le\s+jour\s+où|au\s+besoin|en\s+cas\s+de"
                       r"|à\s+l['’]occasion|le\s+moment\s+venu|plus\s+tard|la\s+première\s+fois)\b")
# Une demande annoncée pour plus tard, par quelqu'un d'autre (« puis te demandera ton go ») : pas encore une action.
A_VENIR = re.compile(r"(?i)\bte\s+(?:demandera|demanderont|posera|poseront|proposera|proposeront|enverra|enverront)\b")
# Facultatif : rien n'attend (« Tu peux fermer cette session-ci », « Dis-moi si tu veux ajuster le ton »).
FACULTATIF = re.compile(r"(?i)^(?:tu\s+peux|tu\s+pourras|libre\s+à\s+toi)\b|\bquand\s+tu\s+(?:veux|voudras)\b|\bn['’]importe\s+quand\b"
                        r"|\bdis[- ](?:le[- ])?(?:moi[- ])?si\s+tu\s+(?:veux|voulais|le\s+souhaites|préfères)\b")
# « Rien à faire de ton côté » (format du PM, règle 9) : le message ne demande rien hors de ses questions numérotées.
# La phrase pleine, au plus avec « pour l'instant » ou « d'ici là » : pas sous condition (« Si…, rien à faire de ton
# côté »), ni avec une exception (« …, sauf ce Q22 ok ») ou un sujet (« … sur le Studio pilote »), qui laissent le reste.
RIEN_A_FAIRE = re.compile(r"(?i)\brien\s+à\s+faire\s+de\s+ton\s+côté\b"
                          r"|\bnothing\s+(?:to\s+do|needed|required)\s+(?:on|from)\s+your\s+(?:side|end)\b")
RIEN_SEUL = re.compile(r"(?i)^(?:[\s,]*(?:pour\s+l['’]instant|pour\s+le\s+moment|d['’]ici\s+là|à\s+ce\s+stade|maintenant|aujourd['’]hui"
                       r"|ici|dans\s+cette\s+session))*[\s.!…*_]*$")
INTERROGATIFS = re.compile(r"(?i)^(?:pourquoi|comment|quoi|combien|où|quand|qui|lequel|laquelle|résultat|bilan|verdict)\b")
PUCE = re.compile(r"^(\s*)(?:[-*+•]\s+(?:\[[ xX]\]\s+)?|(\d{1,2}|[a-hA-H])[.)]\s+|\((\d{1,2}|[a-hA-H])\)\s+)")
CASE = re.compile(r"^\s*[-*+]\s+\[ \]\s+")
FIN_PHRASE = re.compile(r"(?<=[.!?…])\s+(?=[«\"“(\[*_`]*[A-ZÀ-ÖØ-Ý0-9])")
CITATION = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"|`[^`]*`")
# Le texte cité n'est jamais lu comme une demande (« Les vraies
# demandes restent, comme « Aucune question pour toi, mais j'attends ton go ». » sortait en « Go », par le « j'attends »
# de l'exemple cité) : une citation de trois mots ou plus devient « … » pour le tri, la ligne garde le texte entier. Une
# citation plus courte reste lue : c'est la réponse attendue (« go », « Q12 1 », « connecter »).
CITE_MOTS_MIN = 3


def sans_citations(p):
    """La phrase pour le tri : chaque citation de CITE_MOTS_MIN mots ou plus réduite à « … »."""
    return CITATION.sub(lambda m: m.group(0) if len(m.group(0)[1:-1].split()) < CITE_MOTS_MIN
                        else m.group(0)[0] + '…' + m.group(0)[-1], p or '')
ABREV = re.compile(r"(?i)(?:\b(?:ex|cf|p|M|Mme|env|etc|vs|n°|réf|art|fig|min|max|approx)\.|^[*_\s]*(?:\d{1,2}|[a-h])[.)])$")
NOM_DE_TETE = re.compile(r"(?i)^\S+\s*(?::|\bde\b|\bd['’]|\bdu\b|\bdes\b|\bet\b|,)")
ANAPHORE = re.compile(r"(?i)\b(?:le|la|l['’]|les|y|en|ça|cela|celle-ci|celui-ci)\b")


def nu(s):
    """La phrase sans décor markdown en tête et en queue, pour tester les règles (jamais pour l'affichage)."""
    s = PUCE.sub('', s)
    s = re.sub(r"^[\s>*_~#→⇒👉✅⚠️❓🟢🟠🔴•·-]+", '', s)
    return s.strip().strip('*_` ').strip()


def imperatif(n):
    """Le verbe à l'impératif qui ouvre la phrase, ou une proposition après « : », « ; », un connecteur
    (« Puis vérifie ») ou une subordonnée (« Pour l'annuler, va dans… »). None sinon."""
    candidats = [n] + re.split(r"\s*[:;]\s+", n)[1:]
    for c in list(candidats):
        c2 = CONNECTEURS.sub('', c)
        candidats.append(c2)
        m = SUBORDONNEE.match(c2)
        if m:
            candidats.append(c2[m.end():])
    for c in candidats:
        c = c.strip().strip('*_`«» ')
        mot = re.split(r"[\s,:;.!?']", c, 1)[0].lower().split('-')[0]
        if mot in IMPERATIFS and not NOM_DE_TETE.match(c):
            return mot
    return None


def termine_par_question(s):
    t = CITATION.sub('', s)
    t = re.sub(r"[\s*_`)\]»\"”'.]+$", '', t)
    return t.endswith('?')


def citation_ouverte(s):
    """Vrai si une citation ouverte dans s n'est pas refermée : la phrase citée continue, on ne coupe pas dedans."""
    return s.count('«') > s.count('»') or s.count('“') > s.count('”') or s.count('"') % 2 == 1 or s.count('`') % 2 == 1


def couper_phrases(ligne):
    morceaux, courant = [], ''
    for m in FIN_PHRASE.split(ligne):
        courant = (courant + ' ' + m) if courant else m
        if ABREV.search(courant.rstrip()) or citation_ouverte(courant):
            continue
        morceaux.append(courant)
        courant = ''
    if courant:
        morceaux.append(courant)
    return [m for m in (x.strip() for x in morceaux) if m]


def unites(texte):
    """Découpe le message en unités : (texte affichable, rôle, numéro de bloc, contexte)."""
    sortie, en_code, section_toi, niveau_toi, annonce_toi, bloc, liste_precedente = [], False, False, 9, False, 0, False
    item, a_savoir, demande_section, demande_annonce = 0, False, False, False
    for brute in texte.split('\n'):
        ligne = brute.rstrip()
        if ligne.lstrip().startswith('```') or ligne.lstrip().startswith('~~~'):
            if not en_code and sortie and sortie[-1][1] == 'phrase':
                # « Colle ceci dans ta session du projet : » puis le bloc : le geste porte sur le bloc qui suit.
                p_, r_, b_, c_ = sortie[-1]
                sortie[-1] = (p_, r_, b_, dict(c_, avant_code=True))
            en_code = not en_code
            continue
        if en_code:
            continue
        if not ligne.strip():
            bloc += 1
            continue
        # « À savoir » (format du PM) et une liste de sources : des informations, jamais une demande, jusqu'à
        # l'intitulé suivant.
        section = debut_section(ligne)
        if section or re.match(r"^\s*#{1,6}\s", ligne) or re.match(r"^\s*\*\*[^*]+\*\*\s*:?\s*$", ligne):
            a_savoir = section in ('savoir', 'sources')
        if a_savoir:
            sortie.append((ligne.strip(), 'phrase', bloc, {'a_savoir': True}))
            continue
        titre = re.match(r"^\s*(#{1,6})\s+(.*)$", ligne)
        if titre:
            niv = len(titre.group(1))
            if section_toi and niv <= niveau_toi:
                section_toi = False
            if SECTION_POUR_TOI.search(titre.group(2)):
                section_toi, niveau_toi = True, niv
                demande_section = bool(SECTION_DEMANDE.search(titre.group(2)))
            annonce_toi = False
            sortie.append((titre.group(2), 'titre', bloc, {}))
            continue
        if ligne.lstrip().startswith('|') or ligne.lstrip().startswith('>'):
            sortie.append((ligne.strip(), 'tableau' if ligne.lstrip().startswith('|') else 'citation', bloc, {}))
            continue
        est_liste = bool(PUCE.match(ligne))
        numero = bool(re.match(r"^\s*(?:\d{1,2}|[a-hA-H])[.)]\s+|^\s*\((?:\d{1,2}|[a-hA-H])\)\s+", ligne))
        if not est_liste:
            annonce_toi = False
        liste_precedente = est_liste
        affichable = PUCE.sub('', ligne).strip() if est_liste and not numero else ligne.strip()
        # Une ligne en gras seule (« **À toi :** ») vaut un titre pour la liste qui suit.
        label = re.match(r"^\s*\*\*([^*]+)\*\*\s*:?\s*$", ligne)
        if label and SECTION_POUR_TOI.search(label.group(1)):
            annonce_toi, demande_annonce = True, bool(SECTION_DEMANDE.search(label.group(1)))
            sortie.append((label.group(1), 'titre', bloc, {}))
            continue
        item += 1
        ctx = {'liste': est_liste, 'numero': numero, 'case': bool(CASE.match(ligne)), 'item': item,
               'retrait': len(ligne) - len(ligne.lstrip()),
               'section_toi': section_toi, 'annonce_toi': annonce_toi and est_liste,
               'demande_toi': section_toi and demande_section or annonce_toi and est_liste and demande_annonce}
        phrases = couper_phrases(affichable)
        for rang, p in enumerate(phrases):
            sortie.append((p, 'phrase', bloc, dict(ctx, tete=rang == 0, seule=len(phrases) == 1)))
        if not est_liste and affichable.rstrip('*_ ').endswith(':') and (
                SECTION_POUR_TOI.search(affichable) or PROCEDURE_TOI.match(nu(affichable))
                or INVITE.match(nu(affichable))):
            annonce_toi, demande_annonce = True, bool(SECTION_DEMANDE.search(affichable))
    return sortie


def demande_a_l_imperatif(n):
    """Vrai si la phrase demande une réponse à l'impératif (« Choisis… », « Valide… », « Donne le chemin… »), pas à
    un tiers (« Dis-lui… »)."""
    verbe = imperatif(n)
    return verbe in VERBES_DECISION and not re.search(r"(?i)\b" + re.escape(verbe) + r"(?:[- ](?:lui|leur)\b|(?:[- ]le)?\s+(?:vite\s+|aussi\s+)?(?:à|aux|au)\s)", n)


def rien_pour_toi(n):
    """Vrai si la phrase dit que rien n'attend le PM : une proposition ouvre sur la négation et parle d'attente, la
    phrase nomme le PM, et aucune autre proposition ne s'adresse à lui ni ne parle d'attente."""
    if EXCEPTION.search(n) or not TOI.search(n):
        return False
    vue = False
    for p in re.split(r"\s*[,;:—–()]\s*|\s+-\s+|(?<=[.!?…])[*_]*\s+", n):
        p = CONNECTEURS.sub('', p.strip(' .!…*_')).strip()
        if not p:
            continue
        if RIEN_POUR_TOI.match(p) and ATTENTE.search(p):
            vue = True
        elif not re.sub(r"[\s.!…,]", '', LOCATIF.sub('', p)) or not (TOI.search(p) or ATTENTE.search(p) or imperatif(p)):
            continue
        else:
            return False
    return vue


def rien_a_faire(texte, generique=False):
    """Vrai si le message dit qu'il n'attend rien du PM, sans condition ni exception, hors du code et des citations :
    « Rien à faire de ton côté » (la formule d'un PM) ou une formule de fin du glossaire du PM (marqueurs.md).
    generique : aussi, pour tout PM, une dernière phrase qui dit que rien ne l'attend (« Rien n'est attendu de toi. »),
    sans « d'autre » ni « sinon » qui laisseraient quelque chose avant. Seulement pour un message où le tri n'a trouvé
    aucune demande : une tournure libre n'efface jamais une demande (« Valide le devis. Pour le reste, rien… »)."""
    t = CITATION.sub('', re.sub(r"(?s)```.*?```|~~~.*?~~~", '', texte or ''))
    phrases = [ph for ligne in t.split('\n') for ph in couper_phrases(ligne.strip())]
    fins = marqueurs()['rien']
    for ph in phrases:
        if CONDITION.match(CONNECTEURS.sub('', nu(ph)).lstrip(' ,')):
            continue
        m = RIEN_A_FAIRE.search(ph)
        if m and RIEN_SEUL.match(ph[m.end():]):
            return True
        n = norm_marqueur(ph)
        for f in fins:
            i = n.find(f)
            if i >= 0 and RIEN_SEUL.match(n[i + len(f):]):
                return True
    if not generique:
        return False
    if partie_a_trancher_vide(texte):
        return True   # « À trancher : rien. », « ## À trancher / Aucune. » : la session dit qu'elle n'attend rien
    if not phrases:
        return False
    derniere = nu(phrases[-1])
    return bool(derniere and rien_pour_toi(derniere) and not RIEN_AUTRE.search(derniere) and rien_sans_reserve(derniere)
                and not CONDITION.match(CONNECTEURS.sub('', derniere).lstrip(' ,')))


RIEN_AUTRE = re.compile(r"(?i)\b(?:d['’]autre|de\s+plus|sinon|à\s+part|en\s+dehors|hormis|sauf)\b")
# « Rien ne t'attend au tableau », « rien n'est attendu de toi sur ce point », « là-dessus » : un rien limité à un lieu
# ou à un sujet laisse le reste du message ouvert (« il te restera à écrire à un collègue », juste avant).
RIEN_PORTEE = re.compile(r"(?i)\b(?:au\s+tableau|là[-\s]dessus|sur\s+(?:ce|cet|cette|ces|le|la|les|l['’])\s*\w"
                         r"|pour\s+(?:ce|cet|cette|ces)\s+\w|pour\s+(?:le|la|les|l['’])\s*(?!instant\b|moment\b)\w"
                         r"|dans\s+(?:ce|cet|cette|ces|le|la|les|l['’])\s*\w)")


def rien_sans_reserve(n):
    """La proposition qui dit « rien pour toi » ne le limite ni à un lieu ni à un sujet."""
    for p in re.split(r"\s*[,;:—–()]\s*|\s+-\s+", n):
        p = CONNECTEURS.sub('', p.strip(' .!…*_')).strip()
        if RIEN_POUR_TOI.match(p) and ATTENTE.search(p) and RIEN_PORTEE.search(p):
            return False
    return True


# --- le glossaire du PM -------------------------------------------------------------------------------------------
# Les marques d'un PM (« À trancher », « Rien à faire de ton côté »…) sont celles de ses propres règles d'écriture.
# Un autre PM a les siennes : il les note dans un fichier à lui, hors du plugin, qui survit aux mises à jour
# (plugin pilote, 2026-10-28). Trois rubriques, une expression par puce :
#   « ## Demande » : une phrase qui contient l'expression attend le PM ;
#   « ## Rien à faire » : une phrase qui finit par l'expression dit que le message n'attend rien ;
#   « ## À trancher » : un intitulé de section dont les éléments sont des questions au PM.
MARQUEURS = pathlib.Path(os.environ.get('MON_STUDIO_MARQUEURS', str(HOME / '.claude' / 'cockpit' / 'marqueurs.md')))
RUBRIQUES = {'demande': 'demande', 'demandes': 'demande', 'rien a faire': 'rien', 'rien': 'rien',
             'a trancher': 'trancher', 'intitules': 'trancher'}
_marqueurs = {'cle': None, 'vu': 0.0, 'valeur': {'demande': [], 'rien': [], 'trancher': []}}
MARQUEURS_RELUS_S = 2.0   # relu au plus toutes les deux secondes : le tri passe sur des milliers de lignes


def norm_marqueur(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower().replace('’', "'")
    return re.sub(r'\s+', ' ', re.sub(r'[*_`«»"]', '', s)).strip()


def marqueurs():
    """Les expressions du glossaire du PM, relues seulement quand le fichier change. Sans fichier : aucune."""
    if time.time() - _marqueurs['vu'] < MARQUEURS_RELUS_S and _marqueurs['cle'] and _marqueurs['cle'][0] == str(MARQUEURS):
        return _marqueurs['valeur']
    _marqueurs['vu'] = time.time()
    try:
        st = MARQUEURS.stat()
        cle = (str(MARQUEURS), st.st_mtime, st.st_size)
    except OSError:
        _marqueurs.update(cle=(str(MARQUEURS), None, None), valeur={'demande': [], 'rien': [], 'trancher': []})
        return _marqueurs['valeur']
    if _marqueurs['cle'] == cle:
        return _marqueurs['valeur']
    out, rubrique = {'demande': [], 'rien': [], 'trancher': []}, None
    for ligne in MARQUEURS.read_text(encoding='utf-8', errors='replace').splitlines():
        titre = re.match(r'^\s*#{1,6}\s+(.*)$', ligne)
        if titre:
            rubrique = RUBRIQUES.get(norm_marqueur(titre.group(1)).rstrip(' :'))
            continue
        puce = re.match(r'^\s*[-*+]\s+(.*\S)\s*$', ligne)
        if rubrique and puce:
            expr = norm_marqueur(puce.group(1)).rstrip(' .')
            if len(expr) >= 3 and expr not in out[rubrique]:
                out[rubrique].append(expr)
    _marqueurs.update(cle=cle, valeur=out)
    return out


def signature_marqueurs():
    """Une empreinte courte du glossaire du PM ('' sans glossaire), pour savoir quand refaire le tri."""
    m = marqueurs()
    if not any(m.values()):
        return ''
    return hashlib.sha1(json.dumps(m, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]


def ajouter_marqueur(rubrique, expression):
    """« Ajoute ce marqueur » : l'expression rejoint la rubrique du glossaire du PM, créé au besoin. Rien n'est retiré."""
    titres = {'demande': 'Demande', 'rien': 'Rien à faire', 'trancher': 'À trancher'}
    if rubrique not in titres or len(norm_marqueur(expression)) < 3:
        return False
    texte = MARQUEURS.read_text(encoding='utf-8') if MARQUEURS.exists() else (
        "# Mes marqueurs pour Mon Studio\n\nUne expression par puce. Mon Studio les lit en plus des siennes.\n")
    lignes = texte.rstrip('\n').split('\n')
    debut = next((k for k, l in enumerate(lignes) if l.startswith('#') and
                  RUBRIQUES.get(norm_marqueur(l.lstrip('#')).rstrip(' :')) == rubrique), None)
    if debut is None:
        lignes += ['', f'## {titres[rubrique]}', '']
        debut = len(lignes) - 2
    fin = next((k for k in range(debut + 1, len(lignes)) if lignes[k].startswith('#')), len(lignes))
    puces = [k for k in range(debut + 1, fin) if re.match(r'^\s*[-*+]\s', lignes[k])]
    # Sous la dernière puce de la rubrique : une note du PM entre les puces et la rubrique suivante reste en place.
    i = puces[-1] + 1 if puces else fin
    while not puces and i > debut + 1 and not lignes[i - 1].strip():
        i -= 1
    if not puces and i == debut + 1:
        lignes.insert(i, '')
        i += 1
    lignes.insert(i, f'- {expression.strip()}')
    MARQUEURS.parent.mkdir(parents=True, exist_ok=True)
    MARQUEURS.write_text('\n'.join(lignes) + '\n', encoding='utf-8')
    _marqueurs['vu'] = 0.0
    return True


def marqueur_demande(p):
    """L'expression du glossaire du PM que la phrase contient, ou None."""
    n = norm_marqueur(p)
    return next((m for m in marqueurs()['demande'] if m in n), None)


def classer(p, role, ctx):
    """(priorité, raison) si la phrase attend le PM, sinon (None, raison de l'écart). Un geste (3, 4) n'est gardé que
    si la session l'attend pour repartir, ou s'il répond à un intitulé qui demande une réponse."""
    cite = sans_citations(p)
    prio, raison = _classer(cite, role, ctx)
    if prio is not None and cite != p and _classer(p, role, ctx)[0] is None:
        # « « Rien à faire de ton côté » contredisait Q12, que je disais en attente de ta réponse » : la citation
        # retirée laissait une demande que la phrase entière n'est pas. Une demande l'est avec et sans la citation.
        return None, 'demande seulement sans sa citation (la phrase entière ne demande rien)'
    p = cite
    if prio in (3, 4):
        n = nu(p)
        # Un geste qui remet un bloc au PM (« colle ceci dans ta session du projet : » suivi du prompt) est une
        # demande, même si la session n'attend pas pour repartir (contremaître, 2026-10-26 : le prompt de test du kit
        # COPIL, terminé par « Rien d'autre à faire de ton côté », ne faisait aucune ligne).
        if ctx.get('avant_code'):
            return 4, f'geste avec un bloc à coller ({raison})'
        # Une case à cocher non cochée est à faire par nature, sans marque d'un PM ni formule de fin (plugin pilote,
        # 2026-10-28 : « coche ce qui est validé : - [ ] … » ne faisait plus de ligne une fois le message lu).
        if ctx.get('case'):
            return 4, f'case à cocher ({raison})'
        if not (ctx.get('demande_toi') or REPART.search(n) or demande_a_l_imperatif(n)):
            return None, f"geste que la session n'attend pas pour repartir ({raison})"
    return prio, raison


def _classer(p, role, ctx):
    if role != 'phrase':
        return None, role
    n = nu(NIE_TOI.sub('', p))
    if not n:
        return None, 'vide' if not nu(p) else 'négation (pas au PM)'
    question = termine_par_question(p)
    feu = FEU.search(n)
    if ctx.get('a_savoir'):
        return None, 'section « À savoir » (information)'
    if section_vide(p):
        return None, 'la partie se dit vide (« Aucune. », « rien pour l\'instant »)'
    if NEGATION.search(n) and not question:
        return None, 'négation (rien à faire)'
    if rien_pour_toi(n) and not question:
        return None, 'rien n\'attend le PM (« rien n\'est en attente de ta part »)'
    if (PARLE_DE_DEMANDE.match(CONNECTEURS.sub('', n)) and not question and not re.search(DEUXIEME, n, re.I)
            and not (ctx.get('section_toi') or ctx.get('annonce_toi'))):
        # Dans une section « pour toi », « La ligne 🌱 devient deux lignes : » est un changement proposé (une ligne de slide).
        return None, 'parle d\'une demande ou d\'une ligne, sans s\'adresser au PM'
    if CLOSE.search(n) and SUJET_QUESTION.search(n) and not question and not re.search(DEUXIEME, n, re.I):
        return None, 'question déjà close (« soldée », « sans objet », « au tableau »)'
    if RAPPORT.match(n) and not question and not re.search(DEUXIEME, n, re.I):
        # « J'ai ajouté une règle (à valider par Léo) » : un compte rendu, même s'il cite une validation.
        return None, 'compte rendu (première personne)'
    if CONDITION.match(CONNECTEURS.sub('', n).lstrip(' ,')) and not question and not feu:
        return None, 'geste conditionnel (« si… », « quand tu… »)'
    if A_VENIR.search(n) and not question:
        return None, 'demande annoncée pour plus tard (« te demandera… »)'
    if FACULTATIF.search(n) and not question and not TYPE_GO.search(n):
        return None, 'facultatif (« tu peux », « si tu veux »)'
    if feu:
        return 1, f'feu vert / décision : « {feu.group(0).strip()} »'
    marque = marqueur_demande(p)
    if marque:
        # Après les écarts (négation, « à savoir », conditionnel…) : une marque du PM ne force pas une ligne écartée.
        return 2, f'marqueur du glossaire du PM « {marque} »'
    if question:
        mots = n.split()
        if len(mots) <= 2 and INTERROGATIFS.match(n):
            return None, 'question-titre (rhétorique)'
        return 2, 'question'
    if RAPPORT.match(n):
        return None, 'compte rendu (première personne)'
    if ctx.get('case'):
        return 4, 'case à cocher'
    if MESSAGE_A_ENVOYER.match(n):
        return 4, 'geste (message à transmettre, annoncé)'
    verbe = imperatif(n)
    if verbe:
        return 4, f'geste (impératif « {verbe} »)'
    if INVITE.match(n):
        return 4, 'geste (« tu peux », « merci de »…)'
    inf = A_INFINITIF.search(n)
    if inf:
        return 4, f'geste (« {inf.group(0).strip()} »)'
    if ctx.get('section_toi') or ctx.get('annonce_toi'):
        if n.endswith(':') and (not ctx.get('liste') or len(n.split()) <= 4):
            return None, 'annonce (ses éléments sont jugés à part)'
        if not ctx.get('tete'):
            return None, "explication d'un élément « pour toi » (seule sa tête compte)"
        if re.match(r"(?i)^(?:je|j['’]|on\s+va|nous)\b", n):
            return None, 'plan de Claude (première personne) dans une section « pour toi »'
        return 3, 'élément de la section / liste « pour toi »'
    if PROPOSE.search(n):
        return 5, 'proposition ou recommandation (attend un oui)'
    return None, 'information ou compte rendu'


def trier(texte, expliquer=False):
    us = unites(texte or '')
    notes, rien = [], rien_a_faire(texte)
    for k, (p, role, bloc, ctx) in enumerate(us):
        prio, raison = classer(p, role, ctx)
        if rien and prio is not None and not ctx.get('avant_code'):
            prio, raison = None, f'« Rien à faire de ton côté » dans le message ({raison})'
        notes.append({'k': k, 'p': p, 'prio': prio, 'raison': raison, 'bloc': bloc, 'ctx': ctx, 'role': role})
    # Options : une liste qui suit immédiatement une question ou une annonce gardée la rejoint, si chaque
    # élément tient en une phrase courte. Un élément plus long est une demande à part entière.
    for i, n in enumerate(notes):
        if n['prio'] in (1, 2) and (termine_par_question(n['p']) or n['p'].rstrip('*_ ').endswith(':')):
            j, opts, retrait = i + 1, [], None
            while j < len(notes) and notes[j]['role'] == 'phrase' and notes[j]['ctx'].get('liste'):
                c = notes[j]['ctx']
                if retrait is None:
                    retrait = c['retrait']
                if c['retrait'] < retrait:
                    break
                if c['retrait'] == retrait:
                    if not c.get('seule') or len(notes[j]['p']) > 160:
                        opts = []
                        break
                    opts.append(notes[j])
                j += 1
            if 2 <= len(opts) <= 6:
                n['options'] = [o['p'] for o in opts]
                for o in opts:
                    o['prio'], o['raison'] = None, f'option rattachée à la ligne {i + 1}'
    for i, n in enumerate(notes):
        mots = nu(n['p']).split()
        renvoie = (len(mots) <= 4 and ANAPHORE.search(' '.join(mots))) or ANAPHORE.search(' '.join(mots[:3]))
        seule_ligne = n['ctx'].get('seule') and not n['ctx'].get('liste')
        if n['prio'] == 2 and len(mots) <= 4 and renvoie and seule_ligne:
            # « Je l'applique ? » seul dans son paragraphe : il renvoie à la proposition qui précède.
            for avant in reversed(notes[:i]):
                if avant['role'] == 'phrase' and PROPOSE.search(nu(avant['p'])):
                    n['avant'], avant['prio'] = avant['p'], None
                    avant['raison'] = f'proposition rattachée à la ligne {i + 1}'
                    break
            if n.get('avant'):
                continue
        if (n['prio'] in (1, 2) and nu(n['p']).endswith(':') and len(mots) <= 8 and i > 0
                and not n['ctx'].get('tete') and not n.get('options')):
            # « J'attends ton « go » : » : ce qui est attendu est dit juste avant, dans la même ligne.
            avant = notes[i - 1]
            if avant['role'] == 'phrase' and avant['ctx'].get('item') == n['ctx'].get('item') and avant['prio'] is None:
                n['avant'], avant['raison'] = avant['p'], f'antécédent rattaché à la ligne {i + 1}'
                continue
        if n['prio'] == 2 and renvoie and i > 0:
            avant = notes[i - 1]
            # « C'est court à faire. Je le fais ? » : « le » renvoie à l'offre faite juste avant (« Je peux… »).
            for k in range(i - 1, max(-1, i - 4), -1):
                o = notes[k]
                if o['role'] == 'phrase' and o['ctx'].get('item') == n['ctx'].get('item') and (
                        PROPOSE.search(nu(o['p'])) or re.match(r"(?i)^je\s+peux\b", nu(o['p']))):
                    avant = o
                    break
            if (avant['role'] == 'phrase' and (avant['prio'] is None or avant['prio'] >= 3)
                    and (avant['ctx'].get('item') == n['ctx'].get('item') or len(mots) <= 4 and avant['bloc'] == n['bloc'])):
                n['avant'] = avant['p']
                avant['prio'], avant['raison'] = None, f'antécédent rattaché à la ligne {i + 1}'
    # Demandes (1, 2) : les dernières d'abord, c'est là que Claude les met. Gestes et listes (3, 4) : dans l'ordre.
    gardees = sorted((n for n in notes if n['prio'] is not None),
                     key=lambda n: (n['prio'], -n['k'] if n['prio'] <= 2 else n['k']))
    retenues = sorted(gardees[:LIGNES_MAX], key=lambda n: n['k'])
    for n in gardees[LIGNES_MAX:]:
        n['raison'] += ' (hors des trois)'
    lignes = []
    for n in retenues:
        ligne = (n['avant'] + ' ' + n['p']) if n.get('avant') else n['p']
        if n.get('options'):
            ligne += ' ' + ' · '.join(n['options'])
        if len(ligne) > LONGUEUR_MAX:
            ligne = ligne[:LONGUEUR_MAX].rsplit(' ', 1)[0] + ' …'
        lignes.append(ligne)
    reste = max(0, len(gardees) - LIGNES_MAX)
    tete = ((gardees[0]['avant'] + ' ') if gardees and gardees[0].get('avant') else '') + (gardees[0]['p'] if gardees else '')
    if gardees and gardees[0]['ctx'].get('liste') and not gardees[0]['ctx'].get('tete') and not gardees[0].get('avant'):
        # « Ces mois sont clos, à arbitrer. » n'a de sens qu'avec la tête de son élément de liste.
        item = [n['p'] for n in notes if n['role'] == 'phrase' and n['ctx'].get('item') == gardees[0]['ctx'].get('item')]
        entier = ' '.join(item)
        if len(nettoyer(entier)) <= LIBELLE_MAX:
            tete = entier
        elif len(nettoyer(tete)) < 80:
            tete = couper(nettoyer(item[0]), LIBELLE_MAX - len(nettoyer(tete)) - 1) + ' ' + tete
    if expliquer:
        return lignes, reste, notes, {id(n) for n in retenues}
    return lignes, reste, tete, (gardees[0]['prio'] if gardees else None)


# --- le format des messages du PM : « À trancher », « Encore ouvert » ----------------------------------------
#
# Les messages de Claude suivent le format du PM (~/.claude/format-reponses.md) : les questions vont ensemble
# en fin de message sous « À trancher », numérotées et titrées (« Q2 · Format du CR »), la numérotation
# tient toute la session, et une ligne « Encore ouvert : Q1, Q3 » rappelle celles qui attendent encore. Le
# titre est le meilleur libellé possible : une ligne du tableau par question.

# Les mêmes intitulés en anglais, pour les projets où le PM travaille en anglais (PM, 2026-10-21).
SECTIONS = (('trancher', r"(?:à\s+trancher|to\s+decide)"), ('savoir', r"(?:à\s+savoir|good\s+to\s+know)"),
            ('ensuite', r"(?:possible\s+ensuite|possible\s+next)"), ('ouvert', r"(?:encore\s+ouverts?|still\s+open)"),
            ('rien', r"(?:rien\s+(?:à\s+faire|d['’]autre)|nothing\s+(?:to\s+do|else))"))
QUESTION_TITREE = re.compile(r"^(?:[-*+•]\s+|\d{1,2}[.)]\s+)?[*_]*Q(\d{1,3})\s*[·•.:–-]\s*(.*)$")
# « Sources : » seul sur sa ligne : la liste de liens qui suit n'est ni une question ni une demande.
SOURCES = re.compile(r"(?:sources?|références?|liens?|pour\s+aller\s+plus\s+loin)[\s*_]*:?[\s*_]*$")
LIEN_SEUL = re.compile(r"^[-*+•\s]*\[[^\]]+\]\([^)\s]+\)[\s.,;]*$")


def debut_section(ligne):
    """'trancher', 'savoir', 'ensuite', 'ouvert', 'rien' ou 'sources' si la ligne ouvre une de ces parties, sinon None.
    Les intitulés « à trancher » du glossaire du PM comptent aussi."""
    t = re.sub(r"^[\s#*_>]+", '', ligne).lower()
    for nom, motif in SECTIONS:
        if re.match(motif + r"\b", t):
            return nom
    intitules = marqueurs()['trancher']
    if intitules:
        # L'intitulé seul sur sa ligne (« Décisions attendues : » ou « … : Q1 et Q2 ») : pas une phrase qui commence
        # par les mêmes mots.
        n = norm_marqueur(t).rstrip(' :')
        if any(n == m or re.match(re.escape(m) + r'\s*:', n) for m in intitules):
            return 'trancher'
    return 'sources' if SOURCES.match(t) else None


def nettoyer(t):
    """Le texte sans décor markdown (liens réduits à leur libellé, gras retiré), pour une ligne du tableau."""
    t = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", t)
    t = t.replace('**', '').replace('__', '')
    t = PUCE.sub('', t)
    return re.sub(r"\s+", ' ', t).strip()


def couper(t, n=LIBELLE_MAX):
    if len(t) <= n:
        return t
    t = t[:n].rsplit(' ', 1)[0].rstrip(' ,;:') + ' …'
    return t.replace('`', '') if t.count('`') % 2 else t


def question_titree(m):
    """{num, titre, suite} d'une ligne « Qn · Titre : question » (m : QUESTION_TITREE). Le titre s'arrête au gras
    fermant, à « : », ou au premier point."""
    corps = m.group(2).strip()
    if corps.startswith('**') or '**' in corps[:3]:
        corps = corps.lstrip('*')
    # « (impact fort : échéance) » belongs to the title (rule 10): its colon does not end it.
    masque = ETIQUETTE_TITRE.sub(lambda e: '_' * len(e.group(0)), corps)
    fin = re.search(r"\*\*|\s:\s|:\s|\.\s|\s[–—]\s", masque)
    titre, suite = (corps[:fin.start()], corps[fin.end():]) if fin and fin.start() <= 90 else (corps, '')
    titre = nettoyer(titre).rstrip(' .:*')
    suite = nettoyer(suite.lstrip('*: ')).lstrip(': ')
    return {'num': int(m.group(1)), 'titre': f"Q{m.group(1)} · {titre}", 'suite': suite}


ETIQUETTE_TITRE = re.compile(r"\((?:impact|effort)\b[^()]{0,70}\)", re.I)


def gras_seul(ligne):
    """Vrai pour une ligne en gras seule (« **Pourquoi** »), qui ouvre une partie ; pas pour une question titrée en
    gras seule sur sa ligne (« **Q3 · Skill lançable par Claude** »), dont les options suivent."""
    return bool(re.match(r"^\s*\*\*[^*]+\*\*\s*:?\s*$", ligne)) and not QUESTION_TITREE.match(ligne.strip())


# Une partie « À trancher » qui dit qu'elle est vide (« Aucune. », « rien pour l'instant », « None. ») : pas une question.
# Sans cette garde, une session qui suit le rappel de Mon Studio en écrivant « À trancher : rien. » faisait une ligne
# « Répondre » fantôme, même lue (relecture adverse du 2026-10-29).
SECTION_VIDE = re.compile(r"^(?:aucune?|rien|neant|none|nothing|no|pas de)"
                          r"(?:\s+(?:questions?|decisions?|demandes?|points?|open questions?|nouvelle))?"
                          r"(?:\s+(?:pour l'instant|pour le moment|a ce stade|pour toi|de ton cote|aujourd'hui|ici|encore"
                          r"|for now|at this stage|from you|on your side))*$")


def apres_intitule(ligne):
    """Ce qui suit un intitulé « À trancher » sur sa ligne (« **À trancher** : Q4 · … », « ## To decide », un intitulé
    du glossaire du PM) : la question ou le reste, '' si l'intitulé est seul, la ligne telle quelle sans intitulé."""
    t = re.sub(r"^[\s#*_>]+", '', ligne)
    m = re.match(r"(?i)(?:à\s+trancher|to\s+decide)\b[^:]*:?[*_\s]*", t)
    if m:
        return t[m.end():]
    n = norm_marqueur(t)
    for mk in marqueurs()['trancher']:
        if n.rstrip(' :') == mk:
            return ''
        if re.match(re.escape(mk) + r'\s*:', n) and ':' in t:
            return t.split(':', 1)[1].strip('*_ ')
    return ligne


def section_vide(ligne):
    """Vrai si la ligne dit seulement que la partie est vide, avant un éventuel « : explication » qui ne s'adresse pas
    au PM (« Rien pour l'instant : je continue. » ; pas « Rien : valide le devis. »). Un intitulé « À trancher » en
    tête de ligne est retiré d'abord (« À trancher : rien. »)."""
    if debut_section(ligne) == 'trancher':
        ligne = apres_intitule(ligne)
    n = norm_marqueur(re.sub(r"^\s*(?:[-*+•]\s+|\d{1,2}[.)]\s+)", '', ligne))
    avant, sep, apres = n.partition(':')
    if sep and (re.search(DEUXIEME, apres, re.I) or imperatif(apres.strip())):
        return False
    avant = avant.strip(' .!…')
    return bool(avant) and not avant.endswith('?') and bool(SECTION_VIDE.match(avant))


def partie_a_trancher_vide(texte):
    """Vrai si le message a une partie « À trancher » dont tout le contenu dit qu'elle est vide (« Aucune. »,
    « rien pour l'instant »), hors code, tableaux, citations et liens seuls ; faux dès qu'une autre ligne s'y trouve."""
    dedans, vide, en_code = False, False, False
    for brute in (texte or '').split('\n'):
        ligne = brute.rstrip()
        if ligne.lstrip().startswith(('```', '~~~')):
            en_code = not en_code
            continue
        if en_code or not ligne.strip():
            continue
        section = debut_section(ligne)
        if section:
            dedans = section == 'trancher'
            reste = apres_intitule(ligne) if dedans else ''
            if reste.strip():
                if section_vide(reste):
                    vide = True
                else:
                    return False
            continue
        if re.match(r"^\s*#{1,6}\s", ligne) or gras_seul(ligne):
            dedans = False
            continue
        if dedans and not (ligne.lstrip().startswith(('|', '>')) or LIEN_SEUL.match(ligne)):
            if section_vide(ligne):
                vide = True
            else:
                return False
    return vide


def a_trancher(texte):
    """([{num, titre, suite}], [numéros encore ouverts]) : les questions de la partie « À trancher »."""
    items, ouverts, dedans, en_code = [], [], False, False
    for brute in (texte or '').split('\n'):
        ligne = brute.rstrip()
        if ligne.lstrip().startswith(('```', '~~~')):
            en_code = not en_code
            continue
        if en_code or not ligne.strip():
            continue
        section = debut_section(ligne)
        if section == 'ouvert':
            nums = [int(n) for n in re.findall(r"Q(\d{1,3})", ligne)]
            ouverts += nums
            # « Encore ouvert : » seul sur sa ligne, ses questions en liste dessous (le cas du 10/11 : la Q12 ainsi
            # reportée devenait une ligne « Vérifier » sans numéro, que ni « Q12 c fait » ni une preuve ne fermaient) :
            # la liste se lit comme celle de « À trancher ».
            dedans = not nums
            continue
        if section:
            dedans = section == 'trancher'
            # « **À trancher** : Q4 · … » sur la même ligne : la question suit l'intitulé.
            reste = apres_intitule(ligne) if dedans else ''
            if not (dedans and reste.strip()):
                continue
            ligne = reste
        elif re.match(r"^\s*#{1,6}\s", ligne) or gras_seul(ligne):
            dedans = False
            continue
        if not dedans or ligne.lstrip().startswith(('|', '>')) or LIEN_SEUL.match(ligne):
            continue
        m = QUESTION_TITREE.match(ligne.strip())
        if m:
            items.append(dict(question_titree(m), brut=ligne.strip()))
        elif items and items[-1].get('num'):
            # Sous une question numérotée, tout complète la question, ses options en liste comprises.
            items[-1]['suite'] = (items[-1]['suite'] + ' ' + nettoyer(ligne)).strip()
            items[-1]['brut'] += ' ' + ligne.strip()   # its list markers kept: its numbered options (options_libelles)
        elif not section_vide(ligne):
            items.append({'num': None, 'titre': '', 'suite': nettoyer(ligne)})
    if any(it['num'] for it in items):
        # Partie numérotée (format du PM) : une ligne sans numéro avant la première question n'en est pas une.
        items = [it for it in items if it['num']]
    return items, ouverts


OPTION = re.compile(r"^\s*(?:[-*+•]\s+|\d{1,2}[.)]\s+|\(?[a-hA-H][.)]\s+)")


def paragraphes_questions(texte):
    """{numéro: {num, titre, suite}} : chaque paragraphe d'un message qui commence par une question numérotée (« Q4 · … »
    ou « Q4 : … », en gras ou non, sous « À trancher » ou ailleurs), le dernier si le numéro revient. Le paragraphe va
    jusqu'à la ligne vide, un titre, un intitulé (« Encore ouvert »…) ou la question suivante ; un titre seul sur sa
    ligne prend aussi la liste d'options qui le suit après une ligne vide. Blocs de code, tableaux et citations écartés."""
    sortie, q, en_code, vide = {}, None, False, False
    for brute in (texte or '').split('\n'):
        ligne = brute.rstrip()
        if ligne.lstrip().startswith(('```', '~~~')):
            en_code, q = not en_code, None
            continue
        if en_code:
            continue
        if not ligne.strip():
            vide = q is not None
            continue
        m = QUESTION_TITREE.match(ligne.strip())
        if m:
            q = sortie[int(m.group(1))] = question_titree(m)
            vide = False
            continue
        if q is None:
            continue
        if (debut_section(ligne) or re.match(r"^\s*#{1,6}\s", ligne) or gras_seul(ligne)
                or ligne.lstrip().startswith(('|', '>')) or vide and (q['suite'] or not OPTION.match(ligne))):
            q = None
            continue
        if not LIEN_SEUL.match(ligne):
            q['suite'] = (q['suite'] + ' ' + nettoyer(ligne)).strip()
        vide = False
    return sortie


def questions_du_message(texte):
    """{numéro: {num, titre, suite}} : les questions numérotées d'un message de Claude, où qu'elles soient. Celles de
    « À trancher » telles que la partie les lit (options après une ligne vide comprises), les autres par leur paragraphe."""
    sortie = paragraphes_questions(texte)
    sortie.update({it['num']: it for it in a_trancher(texte)[0] if it['num']})
    return sortie


def questions_du_menu(menu):
    """{numéro: {num, titre, suite, detail}} : les questions posées dans une boîte (menus_de) qui commencent par
    leur numéro (« Q4 · … », « Q4 : … »). Le titre se lit comme celui d'un paragraphe, les options suivent ; le détail
    est celui de la ligne d'un menu en attente : la question entière, chaque option avec sa description, la
    recommandée marquée."""
    sortie = {}
    for q in menu or []:
        m = QUESTION_TITREE.match(' '.join(q['question'].split()))
        if m:
            it = question_titree(m)
            sortie[it['num']] = dict(it, suite=' '.join(x for x in (it['suite'], options_menu(q)) if x),
                                     detail=detail_menu(q))
    return sortie


def historique_questions(entrees):
    """{numéro: {titre, suite, depuis, detail ?}} pour les questions numérotées des messages de Claude de ce bout de
    transcript, sous « À trancher » ou ailleurs (PM, 2026-10-15 : une question rappelée par « Encore ouvert » était
    affichée « posée plus haut dans la session »), et celles posées dans une boîte, menu AskUserQuestion ou carte de
    fin de tour (PM, 2026-10-16 : « Le volet de détail ne sert à rien ») : le paragraphe ou la question de boîte le plus
    récent qui commence par son numéro, l'heure de la première fois où il est apparu. Une question de boîte porte son
    détail (questions_du_menu).
    Dans un chantier, un numéro revient chaque jour ouvré (PM, 2026-10-21) et une session peut en reprendre un : le
    même numéro, absent depuis plus de NUMERO_REPRIS_S et sous un autre titre, est une autre question, datée de son
    apparition. Le même titre reposé le lendemain reste la même question."""
    messages, ordre, vu = {}, [], {}
    for o in entrees:
        if o['type'] != 'assistant':
            continue
        m = o.get('message') or {}
        t, menu = texte_de(m.get('content')), menus_de(m.get('content'))
        if not t.strip() and not menu:
            continue
        cle = m.get('id') or id(o)
        if cle not in messages:
            messages[cle] = {'texte': '', 'menu': [], 'ts': horodatage(o)}
            ordre.append(cle)
        messages[cle]['texte'] += '\n\n' + t
        messages[cle]['menu'] += menu
    questions = {}
    for cle in ordre:
        # Dans un message, le menu vient après le texte (l'outil clôt le message) : il l'emporte.
        trouvees = questions_du_message(messages[cle]['texte'])
        trouvees.update(questions_du_menu(messages[cle]['menu']))
        ts = messages[cle]['ts']
        for n, it in trouvees.items():
            q = questions.get(str(n))
            if q and ts and vu.get(n) and ts - vu[n] > NUMERO_REPRIS_S and cle_titre(q['titre']) != cle_titre(it['titre']):
                q = None   # le numéro a été repris pour une autre question
            if q is None:
                q = questions[str(n)] = {'depuis': ts}
            vu[n] = ts or vu.get(n)
            q['titre'], q['suite'] = it['titre'], it['suite']
            if it.get('detail'):
                q['detail'] = it['detail']
            else:
                q.pop('detail', None)
    return questions


def questions_anciennes(chemin, nums):
    """historique_questions sur tout le transcript, pour les seuls numéros « nums » : rappelés par « Encore ouvert »
    et absents de la fin déjà lue. Seules les lignes du fichier qui citent un de ces numéros sont décodées (recherche
    sur les octets) : 0,02 s pour un transcript de 17 Mo. Avant, seuls les 8 derniers Mo étaient lus, et une question
    posée plus haut était perdue (constat du 2026-10-16)."""
    if not nums:
        return {}
    cite = re.compile(rb'Q(?:' + b'|'.join(str(n).encode() for n in sorted(set(nums))) + rb')\b')
    entrees = []
    with open(chemin, 'rb') as f:
        for ligne in f:
            if b'"assistant"' not in ligne or not cite.search(ligne):
                continue
            try:
                o = json.loads(ligne)
            except ValueError:
                continue
            if o.get('type') == 'assistant' and not o.get('isSidechain'):
                entrees.append(o)
    trouvees = historique_questions(entrees)
    return {n: q for n, q in trouvees.items() if int(n) in nums}


def encore_ouvert(texte):
    """{numéro: ce que dit sa parenthèse} sur la ligne « Encore ouvert » d'un message : « Encore ouvert : Q4 (l'entrée
    product-kits dans claude-plugins, que tu valides avec le référent). » donne {4: "l'entrée … avec le référent"}. Un titre
    après le numéro compte aussi : « Encore ouvert : Q1 · Ajouter le piège à la règle. » donne {1: 'Ajouter …'}."""
    sortie, en_code = {}, False
    for ligne in (texte or '').split('\n'):
        if ligne.lstrip().startswith(('```', '~~~')):
            en_code = not en_code
        elif not en_code and debut_section(ligne) == 'ouvert':
            for n, dit in re.findall(r"Q(\d{1,3})\s*[·•]\s*([^;()]+?)(?=\s*[,;]\s*Q\d|\s*$)", ligne):
                sortie[int(n)] = nettoyer(dit).strip(' .;,*_')
            for n, dit in re.findall(r"Q(\d{1,3})\s*\(([^()]+)\)", ligne):
                sortie[int(n)] = nettoyer(dit).strip(' .;,')
    return sortie


# Une phrase qui rappelle des questions numérotées hors de « Encore ouvert » (contrôle des lignes du 2026-10-20, Studio A
# : « J'attends tes réponses, déjà posées plus haut : Q8 pour la publication du kit, Q10 pour le commentaire
# et l'assignation de PRJ-1234, Q11 pour les écarts restants et Q12 pour le passage quotidien. ») : elle dit qu'elles
# attendent le PM. Une simple mention (« dis-le au contremaître pour qu'il ferme Q44 ») ne le dit pas, ni une réponse
# déjà donnée (« Une différence avec ta réponse à Q1 », « (ta réponse à Q3) »), ni l'état d'une question suivie
# ailleurs (« qu'il suit sous le numéro Q44, encore ouverte ») : seuls des mots d'attente du PM comptent.
RAPPEL_EN_PHRASE = re.compile(r"(?i)\bj['’]attends\b|\bt['’]attend(?:ent)?\b|\battend(?:ent)?\s+(?:toujours|encore)\b"
                              r"|\battend(?:ent)?\s+(?:ta|ton|tes)\b|\ben\s+attente\s+de\s+(?:ta|ton|tes|toi)\b"
                              r"|\b(?:toujours|encore|rest(?:e|ent))\s+(?:en\s+attente|sans\s+(?:ta\s+)?réponse)\b")
SEGMENT_RAPPEL = re.compile(r"\bQ(\d{1,3})\b\s*(?:\(([^()]+)\)|([·•:–])\s*)?(.*?)(?=\s*(?:[,;]|\bet\s+Q\d|\bQ\d|[.!?…]?\s*$))")
SUJET_DIT = re.compile(r"(?i)^(?:pour|sur|concernant|à\s+propos\s+d|au\s+sujet\s+d)")


def rappels_en_phrase(texte):
    """{numéro: {dit, phrase}} : les questions numérotées qu'une phrase du message rappelle comme attendant le PM, hors
    de « Encore ouvert » (RAPPEL_EN_PHRASE), dans la phrase même ou dans la liste qu'elle annonce (« … déjà posées plus
    haut : » puis « - Q8 pour … »). « dit » : ce que la phrase dit de chacune (« pour la publication du kit », ou sa
    parenthèse), qui la titre si le transcript ne la pose nulle part ; « phrase » : la phrase, pour le détail. Hors
    « À savoir », du code, des tableaux et des citations ; pas une négation, une condition, ni la ligne d'une question ;
    rien dans un message qui dit « Rien à faire de ton côté »."""
    sortie, annonce = {}, None
    if not REF_QUESTION.search(texte or '') or rien_a_faire(texte):
        return sortie
    for p, role, _, ctx in unites(texte or ''):
        if role != 'phrase' or ctx.get('a_savoir'):
            annonce = None
            continue
        n = nu(p)
        if annonce is not None and not ctx.get('liste'):
            annonce = None
        dans_la_liste = annonce is not None and ctx.get('liste')
        # Un élément de la liste annoncée porte un rappel s'il s'ouvre sur le numéro (« Q8, publication du kit : … ») ;
        # « Une fois fait, dis-le au contremaître pour qu'il ferme Q44 » est un geste qui cite un numéro, pas un rappel.
        porte = dans_la_liste and bool(re.match(r"Q\d{1,3}\b", n))
        if not porte and (QUESTION_TITREE.match(p.strip()) or debut_section(p) == 'ouvert'):
            continue
        attente = not NEGATION.search(n) and not CONDITION.match(CONNECTEURS.sub('', n).lstrip(' ,'))
        if not porte and not REF_QUESTION.search(n):
            if not dans_la_liste:
                # « … déjà posées plus haut : », « Il reste à toi : » : la liste qui suit porte les numéros.
                annonce = nettoyer(p) if n.endswith(':') and attente and (
                    RAPPEL_EN_PHRASE.search(n) or SECTION_POUR_TOI.search(n)) else None
            continue
        if not porte and not (attente and RAPPEL_EN_PHRASE.search(n)):
            continue
        sources = ([annonce] if porte else []) + [nettoyer(p)]
        for m in SEGMENT_RAPPEL.finditer(nettoyer(p)):
            # Ce que la phrase dit de la question : sa parenthèse, ce qui suit « Q8 · », ou « pour… », « sur… ».
            dit = (m.group(2) or m.group(4) or '').strip(' .;,*_')
            if not (m.group(2) or m.group(3) or SUJET_DIT.match(dit)) or RAPPEL_EN_PHRASE.search(dit):
                dit = ''
            # « source » : la phrase même du rappel (pas celle d'une annonce), qui ne fait plus sa ligne de phrase.
            r = sortie.setdefault(int(m.group(1)), {'dit': dit, 'phrase': couper(' '.join(sources), CONTEXTE_MAX),
                                                    'source': ''})
            r['source'] = r['source'] or ('' if porte else nettoyer(p))
    return sortie


TYPE_GO = re.compile(r"(?i)feux?\s+verts?|[«\"“`]\s*go\s*[»\"”`]|\b(?:ton|un|le)\s+go\b|\bgo\s*\?|\bton\s+(?:accord|aval|autorisation)\b"
                     r"|\bautorises?\b|\bj['’]attends\s+ton\b"
                     r"|\bje\s+(?:lance|pose|publie|déploie|installe|applique|envoie|passe|corrige|ouvre)\b[^.?]*\?")
TYPE_RELECTURE = re.compile(r"(?i)\brel(?:is|ire|ecture)\b|\b(?:tes|ton)\s+retours?\b|\bretours?\s+sur\b|\bjette\s+un\s+(?:œil|oeil)"
                            r"|\bregarde\b|\bà\s+(?:relire|contester|vérifier)\b")
# Un verbe par type, les mêmes que le tableau de chantier : Go, Répondre, Relire, Faire. L'ordre est celui de
# foreman : ce qui est immobilisé passe devant, pas le plus ancien. D'abord les feux verts, puis ce qui arrête une
# session en plein travail (« bloque »), puis les décisions, les relectures, les gestes ; à égalité, le plus ancien.
# « clic » : le fond est déjà décidé, la réponse tient en un clic (« ok ») ; la ligne va dans la
# bande « En un clic » en tête de la page, avec les autorisations.
TYPES = {'go': 'Go', 'decision': 'Répondre', 'review': 'Relire', 'task': 'Faire', 'check': 'Vérifier', 'clic': 'OK'}
RANG_TYPE = {'go': 0, 'decision': 2, 'review': 3, 'task': 4, 'check': 5, 'clic': 0}
OPTION_DETAIL = re.compile(r'(?:^|\s)([1-9])\s*[.)]\s+\S')   # comme hooks/reponse_directe.py (options_de)


# A decision that asks for a yes (« oui aux recommandations ? », « réponds « Q35 oui » »): its numbered points are a list
# to approve, not options to pick (PM, 2026-11-07: buttons « 1 » to « 5 » on such a question meant nothing).
DEMANDE_OUI = re.compile(r'\boui\b', re.I)
# A question whose options may be kept together (« tu peux en garder seulement certaines », « une ou plusieurs »): no
# answer buttons, the PM answers in the session (PM, 2026-11-17).
CUMULABLE = re.compile(r"(?i)\b(?:en garder (?:seulement )?certaines|garder seulement certaines|seulement certaines|une ou plusieurs"
                       r"|lesquelles (?:tu )?(?:gardes|retiens|veux)|plusieurs (?:choix|options|réponses) possibles|cumulables?)\b")


def demande_un_oui(titre, detail):
    """True when the question's own words, before its first numbered point, ask for « oui »."""
    tete = str(detail or '')
    m = OPTION_DETAIL.search(tete)
    tete = tete[:m.start()] if m else tete
    return bool(DEMANDE_OUI.search(str(titre or '') + ' ' + tete))


def choix_fermes(genre, detail, titre=''):
    """Les réponses fermées d'une question numérotée, celles que la page propose en boutons :
    « go » et « pas encore » pour un go, « ok » pour un clic, les options numérotées du détail (« 1. … 2. … ») et « pas
    encore » pour une décision qui en a au moins deux, de 1 en 1 ; sinon None. Même règle que le hook de la réponse en
    direct, pour qu'un bouton dise la même chose que la session attende ou non."""
    if genre == 'go':
        return ['go', 'pas encore']
    if genre == 'clic':
        return ['ok']
    if genre in ('review', 'task') and len(options_entieres(detail)) >= 2 and not demande_un_oui(titre, detail):
        genre = 'decision'   # « Envoyer le mail ? 1) **L'envoyer** 2) **Le resserrer** »: a choice (PM, 2026-11-18)
    if genre in ('review', 'task'):
        # A review or a gesture whose question writes its proposal (« Je propose : ok pour les trois »): one click
        # accepts it (PM, 2026-11-17); without a readable proposal, the line only opens its session.
        reco = recommandation(f"{titre or ''} {detail or ''}")
        return [RECOMMANDE_CHOIX + reco, 'pas encore'] if reco and not CUMULABLE.search(f"{titre or ''} {detail or ''}") else None
    if genre != 'decision':
        return None
    if CUMULABLE.search(f"{titre or ''} {detail or ''}"):
        return None   # several options may be kept: one button per option would send one only (PM, 2026-11-17)
    if demande_un_oui(titre, detail):
        choix = ['oui', 'pas encore']
    else:
        vus = sorted(set(OPTION_DETAIL.findall(str(detail or ''))), key=int)
        choix = vus + ['pas encore'] if len(vus) >= 2 and vus == [str(i) for i in range(1, len(vus) + 1)] else None
    # « Recommandé » (PM, 2026-11-10): the recommendation the question writes itself, never a guessed one.
    reco = recommandation(f"{titre or ''} {detail or ''}")
    return [RECOMMANDE_CHOIX + reco] + (choix or ['pas encore']) if reco else choix


RECOMMANDE_CHOIX = 'recommandé : '
RECOMMANDE_MAX = 60
# Where the recommended answer starts, before a « (recommandé) » mark: the question's colon, a sentence's end, an
# option's number (« (1) », « 1. ») or the « ou » between two answers.
DEBUT_RECO = re.compile(r"[:;?!]|\.(?:\s|$)|\(\d\)|(?:^|\s)\d[.)]\s|,?\s+ou\s+|^ou\s+", re.I)
RECO_ECRITE = re.compile(r"(?i)\brecommand(?:é|e|ée|ation)\s*:\s*(.+?)(?=[.;!?](?:\s|$)|$)")
# « Je propose : X » / « Proposition : X » (PM, 2026-11-17): the session's proposal, answered from the board like a
# recommendation. The colon is required: « je propose de lui demander… » in a sentence is not an answer to send.
RECO_PROPOSEE = re.compile(r"(?i)\b(?:je\s+(?:te\s+)?propose|proposition|ma\s+proposition)\s*:\s*(.+?)(?=[.;!?](?:\s|$)|$)")
RECO_EN_PREMIER = re.compile(r"(?i)\brecommandée?\s+en\s+premier\s*:\s*(.+?)(?=,?\s+ou\s+|[.;!?](?:\s|$)|$)")


def _texte_reco(texte):
    t = ' '.join(LIBELLE_HORS.sub(' ', texte.replace('*', '').replace('`', '')).split()).strip(" ,;:.-«»'’")
    if len(t) > RECOMMANDE_MAX:
        t = t[:RECOMMANDE_MAX].rsplit(' ', 1)[0].rstrip(' ,;:.')
    # Never an address as a button's label (PM, 2026-11-17: « //github.com/… (recommandé) »).
    if ADRESSE.search(texte) or ADRESSE.search(t):
        return ''
    return t if t and not re.match(r'Q\d', t) else ''


ADRESSE = re.compile(r"(?i)(?:https?:)?//\S|\bwww\.\S|\S+@\S+\.\w|^[~./]?[\w.-]+/[\w./-]+$")


def recommandation(texte):
    """The answer a question recommends in its own words, short, or '' (PM, 2026-11-10: never guessed): « Recommandé :
    X », « X (recommandé) » (X from the colon, the option number or the « ou » before it), or the first option of a list
    announced « la recommandée en premier : ». Two different recommendations: ''."""
    texte = ' '.join(str(texte or '').split())
    trouves = [_texte_reco(m.group(1)) for m in RECO_ECRITE.finditer(texte)]
    trouves += [_texte_reco(m.group(1)) for m in RECO_EN_PREMIER.finditer(texte)]
    trouves += [_texte_reco(m.group(1)) for m in RECO_PROPOSEE.finditer(texte)]
    for m in RECOMMANDE.finditer(texte):
        avant = texte[:m.start()]
        debuts = [d.end() for d in DEBUT_RECO.finditer(avant)]
        brut = avant[debuts[-1] if debuts else 0:]
        t = _texte_reco(brut)
        # « Options : (recommandée) Écrire… »: the mark before its option, nothing of it before.
        if not brut.strip(" ,;:.-«»'’*`") or t.casefold() in ('options', 'option', 'choix'):
            apres = re.match(r"\s*([^.;,()?!]+)", texte[m.end():])
            t = _texte_reco(apres.group(1)) if apres else ''
        trouves.append(t)
    trouves = {t.casefold(): t for t in trouves if t}
    return next(iter(trouves.values())) if len(trouves) == 1 else ''
OPTION_LIBELLE = re.compile(r'(?:^|\s)([1-9])\s*[.)]\s+(?=\S)')
LIBELLE_CHOIX_MAX = 80
# The characters an option's label keeps (the connector accepts no other, mcp_mon_studio.LIBELLE_MOTIF): one line,
# letters, digits and plain punctuation; anything else becomes a space.
LIBELLE_HORS = re.compile(r"[^A-Za-z0-9À-ÖØ-öø-ÿŒœ’'«»,.:()/+?!%€ -]")
FIN_LIBELLE = re.compile(r'(?<=\D)[.;!?](?:\s|$)|\s[–—-]\s')


def options_libelles(texte):
    """The labels of the numbered options of a question (« 1. court 2. long »), when they run 1, 2… with no gap: each
    label is its text up to the next option, or the end of its sentence, without « (recommandé) », cut at 80
    characters on a word. [] when there are fewer than two, or two are the same."""
    texte = str(texte or '')
    marques, attendu = [], 1
    for m in OPTION_LIBELLE.finditer(texte):
        if m.group(1) == str(attendu):
            marques.append(m)
            attendu += 1
    libelles = []
    for i, m in enumerate(marques):
        fin = marques[i + 1].start() if i + 1 < len(marques) else len(texte)
        lib = RECOMMANDE.sub('', texte[m.end():fin])
        lib = FIN_LIBELLE.split(lib, maxsplit=1)[0]
        lib = ' '.join(LIBELLE_HORS.sub(' ', lib.replace('*', '').replace('`', '')).split()).strip(' ,;:.-')
        if len(lib) > LIBELLE_CHOIX_MAX:
            lib = lib[:LIBELLE_CHOIX_MAX].rsplit(' ', 1)[0].rstrip(' ,;:.')
        libelles.append(lib)
    if len(libelles) < 2 or not all(libelles) or len(set(x.lower() for x in libelles)) != len(libelles) \
            or any(x.lower() in ('go', 'pas encore', 'ok') for x in libelles):
        return []
    return libelles


# Short titles (PM, 2026-11-18): a numbered question is « Qn · <title that says what to decide, 60 characters at most> :
# <the precise question> », its options « 1) **<label of 4 words at most>** : <the whole option> »
# (regles/format-reponses.md, rule 2; hooks/format_questions.py checks it). The board shows the title alone, the
# click shows the rest; an answer button carries the label.
TITRE_MAX = 60       # the title, without its impact label (rule 10)
BOUTON_MAX = 28      # an answer button's label; longer, cut on a word with « … »
LIGNE_MAX = 90       # a line of the board in the old format (title + start of the question): one line, never two
OPTION_GRAS = re.compile(r"^\s*(?:\*\*|__)(.+?)(?:\*\*|__)")


def options_entieres(texte):
    """[{texte, gras, recommande}] of the numbered options of a question (« 1) **Label** : the whole option »), when
    they run 1, 2… with at least two: the whole option without « (recommandé) », its bold label ('' when it has none),
    and whether it carries the mark (« (recommandé) », « (recommandée) »). The last one stops at a labelled rubric
    (« Pourquoi : », « Si tu ne fais rien : »). [] otherwise."""
    texte = ' '.join(str(texte or '').split())
    marques, attendu = [], 1
    for m in OPTION_LIBELLE.finditer(texte):
        if m.group(1) == str(attendu):
            marques.append(m)
            attendu += 1
    if len(marques) < 2:
        return []
    sortie = []
    for i, m in enumerate(marques):
        brut = texte[m.end():marques[i + 1].start() if i + 1 < len(marques) else len(texte)]
        if i + 1 == len(marques):
            r = RUBRIQUE.search(brut)
            brut = brut[:r.start()] if r else brut
        g = OPTION_GRAS.match(brut)
        gras = nettoyer(RECOMMANDE.sub('', g.group(1))).strip(' :;,.') if g else ''
        sortie.append({'texte': nettoyer(RECOMMANDE.sub('', brut)).strip(' ;,'), 'gras': gras,
                       'recommande': bool(RECOMMANDE.search(brut))})
    return sortie


def couper_bouton(t, n=BOUTON_MAX):
    """A button's label under n characters, cut on a word with « … » (« Laisser la page telle… »)."""
    t = ' '.join(str(t or '').replace('`', '').split()).strip(' ,;:.-')
    if len(t) < n:
        return t
    coupe = t[:n - 2]
    if t[n - 2] != ' ' and ' ' in coupe:
        coupe = coupe.rsplit(' ', 1)[0]
    return coupe.rstrip(' ,;:.-«(—–') + '…'


def boutons_options(texte, choix):
    """({'1': label, …}, recommended number or '') for the numbered choices of a line: the option's bold label, else
    the option cut on a word (couper_bouton); the recommended one by its mark, else by the recommendation the question
    writes (« Recommandé : X » naming an option). ({}, '') when the choices are not the options' numbers."""
    if not isinstance(choix, list):
        return {}, ''
    nums = [c for c in choix if re.fullmatch(r'[1-9]', str(c))]
    opts = options_entieres(texte)
    if not nums or len(opts) != len(nums) or nums != [str(i) for i in range(1, len(nums) + 1)]:
        return {}, ''
    libelles = {str(i + 1): couper_bouton(o['gras'] or o['texte']) for i, o in enumerate(opts)}
    marques = [str(i + 1) for i, o in enumerate(opts) if o['recommande']]
    reco = marques[0] if len(marques) == 1 else ''
    if not reco and not marques:
        dit = next((c[len(RECOMMANDE_CHOIX):] for c in choix if str(c).startswith(RECOMMANDE_CHOIX)), '')
        if dit:
            pareils = [str(i + 1) for i, o in enumerate(opts) for x in (o['gras'], o['texte'])
                       if x and (nu(x) == nu(dit) or nu(x).startswith(nu(dit)) or nu(dit).startswith(nu(x)))]
            reco = pareils[0] if len(set(pareils)) == 1 else ''
    return libelles, reco


def format_court(titre, texte):
    """True when a numbered question follows the short-title format (rule 2 since 0.3.2): its title asks (« … ? ») or
    its options carry bold labels. Its line then shows the title alone; an older question keeps the start of its text."""
    t = ETIQUETTE_TITRE.sub('', re.sub(r'^Q\d+\s*·\s*', '', str(titre or ''))).strip()
    if t.endswith('?'):
        return True
    opts = options_entieres(texte)
    return len(opts) >= 2 and all(o['gras'] for o in opts)


def choix_sans_numero(genre, texte):
    """The closed answers of a question without a number, the only question its session waits
    on: « go » and « pas encore » for a go, « ok » for a clic, the labels of its numbered options and « pas encore » for
    a decision; None otherwise. The answer sent is the text alone, without a number. Same rule as the Stop hook
    (hooks/reponse_directe.py, question_seule)."""
    if genre == 'go':
        return ['go', 'pas encore']
    if genre == 'clic':
        return ['ok']
    if genre != 'decision' or CUMULABLE.search(str(texte or '')):
        return None
    libelles = options_libelles(texte)
    return libelles + ['pas encore'] if libelles else None


def choix_de_question(genre, titre, suite, brut=''):
    """The closed answers of a numbered question a session asked itself (« Q3 · … » under « À trancher »), by the same
    rule as a chantier's line (choix_fermes): the question's own words and options are its detail. None otherwise."""
    complet = f"{titre or ''} {suite or ''}".strip()
    return choix_fermes(genre, brut or complet, complet)


def questions_numerotees(texte):
    """[{numero, titre, type, choix}] for each numbered question under « À trancher » of a message that has closed
    answers: the Stop hook waits on all of them, each answered by its own number (Q40, 2026-11-09)."""
    sortie = []
    for it in a_trancher(texte)[0]:
        if not it['num']:
            continue
        genre = type_demande(it['titre'] + ' ' + it['suite'])
        choix = choix_de_question(genre, it['titre'], it['suite'], it.get('brut'))
        if choix:
            sortie.append({'numero': f"Q{it['num']}", 'titre': ' : '.join(x for x in (it['titre'], it['suite']) if x),
                           'type': genre, 'choix': choix})
    return sortie


def question_seule(texte):
    """{titre, type, choix} when a message asks the PM exactly one question under « À trancher » (and recalls no
    other), with closed answers (choix_sans_numero); else None. The Stop hook waits on it."""
    items, ouverts = a_trancher(texte)
    if len(items) != 1 or any(n != items[0]['num'] for n in ouverts):
        return None
    if items[0]['num']:
        return None   # a numbered question is answered by its number (questions_numerotees, Q40)
    it = items[0]
    complet = ' : '.join(x for x in (it['titre'], it['suite']) if x)
    genre = type_demande(complet)
    choix = choix_sans_numero(genre, it.get('brut') or complet)
    return {'titre': complet, 'type': genre, 'choix': choix} if choix else None


ECHEANCE_JOURS = 3            # une échéance dans les trois jours (du calendrier) s'affiche en rouge ; elle ne reclasse rien


def echeance_proche(echeance, maintenant):
    return bool(echeance) and (dt.date.fromtimestamp(echeance) - dt.date.fromtimestamp(maintenant)).days <= ECHEANCE_JOURS


VERBES_DECISION = {'dis', 'dites', 'réponds', 'choisis', 'choisissez', 'tranche', 'tranchez', 'décide', 'valide', 'validez',
                   'confirme', 'confirmez', 'indique', 'précise', 'donne'}


def type_demande(texte, prio=None):
    """Feu vert, Relecture, Geste ou Décision (les types du tableau de chantier), par mots-clés."""
    if TYPE_GO.search(texte):
        return 'go'
    if TYPE_RELECTURE.search(texte):
        return 'review'
    if prio == 2 or termine_par_question(texte):
        return 'decision'
    n = nu(nettoyer(texte))
    verbe = imperatif(n) or imperatif(re.sub(r"(?i)^[^:]{0,60}:\s*", '', n))
    if verbe in VERBES_DECISION:
        return 'decision'
    if verbe or prio == 4 or INVITE.match(n) or A_INFINITIF.search(n):
        return 'task'
    return 'decision'


# --- assemblage de l'écran ---------------------------------------------------------------------------------

def nom_projet(cwd):
    """Le nom du dossier, allégé : « Studio - Projet Alpha » et « Studio-Projet-Alpha » deviennent « Projet Alpha »."""
    if not cwd or os.path.normpath(cwd) == str(HOME):
        return '~ (dossier personnel)'
    chemin = os.path.normpath(cwd)
    # Une session ouverte dans une copie de travail de l'app (<dépôt>/.claude/worktrees/<nom tiré au hasard>)
    # appartient au dépôt : sans ça, le nom tiré au hasard devenait un Studio.
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', chemin)
    if m:
        chemin = m.group(1)
    nom = os.path.basename(chemin)
    court = re.sub(r"(?i)^studio\s*[-–]\s*|\s*[-–]\s*studio$", '', nom).strip()
    if ' ' not in court and '-' in court:
        court = court.replace('-', ' ')
    return court or nom


def duree(depuis, maintenant):
    s = max(0, maintenant - depuis)
    if s < 3600:
        return f'{max(1, int(s // 60))} min'
    if s < 86400:
        return f'{int(s // 3600)} h'
    return f'{int(s // 86400)} j'


JOURS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.']


def quand(ts, maintenant):
    d = dt.datetime.fromtimestamp(ts)
    auj = dt.datetime.fromtimestamp(maintenant).date()
    if d.date() == auj:
        return d.strftime('%H:%M')
    if (auj - d.date()).days == 1:
        return 'hier ' + d.strftime('%H:%M')
    if (auj - d.date()).days < 7:
        return JOURS[d.weekday()] + ' ' + d.strftime('%H:%M')
    return d.strftime('%d/%m')


def libelle_etat(s, maintenant):
    e = s['etat']
    if e == 'attend':
        return f"attend ta réponse depuis {duree(s['depuis'], maintenant)}"
    if e == 'travaille':
        return 'Claude travaille'
    if e == 'main':
        return f"tu as la main depuis {duree(s['depuis'], maintenant)}"
    if e == 'suspens':
        quoi = f" sur {nom_outil(s['outil'])}" if s.get('outil') else ''
        return f"arrêtée en cours de tour{quoi} depuis {duree(s['depuis'], maintenant)} (autorisation en attente ou app fermée)"
    if e == 'erreur':
        return f"arrêtée sur une erreur depuis {duree(s['depuis'], maintenant)} : {s.get('erreur', '').strip()}"
    return 'vide'


def automates(taches, metas, index, cache, maintenant):
    par_tache = {}
    for m in metas:
        if m['tache'] and (m['tache'] not in par_tache or m['creee'] > par_tache[m['tache']]['creee']):
            par_tache[m['tache']] = m
    lignes = []
    for t in taches:
        if not t.get('enabled', True):
            continue
        nom = t.get('displayName') or t.get('id')
        dernier = t.get('lastRunAt')
        if not dernier:
            lignes.append({'nom': nom, 'quand': 'jamais lancée', 'ok': None})
            continue
        ts = dt.datetime.fromisoformat(dernier.replace('Z', '+00:00')).timestamp()
        ok, detail, carte, arret = None, '', None, None
        m = par_tache.get(t.get('id'))
        chemin = index.get(m['cli']) if m and m.get('cli') else None
        if chemin:
            r = analyser_cache(chemin, cache, maintenant)
            # What the last pass waits from the PM (only the last pass of the task: the next one that goes well closes
            # the line): a question (its end-of-turn card, or a menu), an authorization (pending, or refused and the
            # turn cut), an error, or a turn cut in the middle of a tool. Nothing when it went well, still runs, or the
            # PM wrote in it himself.
            if r['etat'] == 'attend' and r.get('carte'):
                carte = r['carte']
            elif r['etat'] == 'suspens' and r.get('menu'):
                carte = {'menu': r['menu'], 'depuis': r['depuis']}
            elif r['etat'] == 'suspens' and r.get('attente'):
                arret = dict(r['attente'], quoi='authorization', depuis=r['depuis'])
            elif r['etat'] == 'main' and r.get('refus'):
                arret = dict(r['refus'], quoi='refused', depuis=r['depuis'])
            elif r['etat'] == 'suspens':
                arret = {'quoi': 'interrupted', 'outil': r.get('outil') or '', 'depuis': r['depuis']}
            elif r['etat'] == 'erreur':
                arret = {'quoi': 'error', 'raison': raison_courte(r.get('erreur')), 'depuis': r['depuis']}
            ok = False if arret else True if r['etat'] == 'attend' else None
            if r['etat'] == 'travaille':
                detail = 'en cours'
            elif arret:
                detail = libelle_arret(arret)
        lignes.append({'nom': nom, 'id': t.get('id'), 'quand': quand(ts, maintenant), 'ok': ok, 'detail': detail, 'ts': ts,
                       'lien': m['id'] if m else None, 'cwd': m['cwd'] if m else (t.get('cwd') or ''), 'carte': carte,
                       'arret': arret})
    return lignes


def deja_lue():
    """Mon Studio has read the app on this Mac before: its mark (LECTURE_OK), or, for an install from before the mark,
    a cache holding read transcripts or a chantier mirror from before the registers (a foreman read the sessions)."""
    if (INTERNE / LECTURE_OK).exists():
        return True
    cache = lire_json(INTERNE / 'cache.json', {})
    if isinstance(cache, dict) and isinstance(cache.get('transcripts'), dict) and cache['transcripts']:
        return True
    for chemin in CHANTIERS.glob('*.json'):
        o = lire_json(chemin)
        if isinstance(o, dict) and o.get('chantier') and o.get('registre') is not True:
            return True
    return False


RAISON_MAX = 100


def raison_courte(erreur):
    """The reason of an error in a few words: its first line, cut on a word."""
    premiere = next((x.strip() for x in str(erreur or '').splitlines() if x.strip()), '')
    return couper(nettoyer(premiere), RAISON_MAX) if premiere else ''


def libelle_arret(arret):
    """« arrêtée sur une autorisation (Bash) », « arrêtée sur une erreur : … » : what stopped a scheduled pass."""
    outil = f" ({nom_outil(arret['outil'])})" if arret.get('outil') else ''
    if arret['quoi'] in ('authorization', 'refused'):
        return 'arrêtée sur une autorisation' + outil
    if arret['quoi'] == 'error':
        return 'arrêtée sur une erreur' + (f" : {arret['raison']}" if arret.get('raison') else '')
    return 'arrêtée en plein travail' + outil + ', à relancer'


def choix_de_carte(menu):
    """The labels of the options of a single question (end-of-turn card or menu), the answers its buttons send, word
    for word what the app's own button sends; None when there is not exactly one question, or an option the
    connector would refuse (mcp_mon_studio.LIBELLE_MOTIF: one line, 80 characters, plain punctuation)."""
    if not menu or len(menu) != 1:
        return None
    libelles = [str(o.get('label') or '').strip() for o in menu[0].get('options') or []]
    if not libelles or any(not LIBELLE_CARTE.match(x) for x in libelles) or len(set(libelles)) != len(libelles):
        return None
    return libelles


LIBELLE_CARTE = re.compile(r"(?!Q\d)[A-Za-z0-9À-ÖØ-öø-ÿŒœ](?:[A-Za-z0-9À-ÖØ-öø-ÿŒœ’'«»,.:()/+?!%€-]| (?! )){0,79}$")


def lecture_app(metas, index):
    """Mon Studio lit-il encore l'app ? « hors_service » avec la raison, quand ce qu'il lit a disparu ou changé de forme :
    jamais un tableau vide qui laisserait croire que rien n'attend le PM (pilote foreman-pm 0.7, 2026-10-27).
    « pas_encore » le premier jour : rien n'a encore été lu (dossier, fiche ou transcript absents) et Mon Studio n'a
    jamais lu l'app sur ce Mac (deja_lue). Une fois l'app lue, la même absence est « hors_service ».
    Une fiche qui a changé de forme est toujours « hors_service »."""
    def absent(raison):
        if not deja_lue():
            return {'etat': 'pas_encore', 'raison': raison}
        return {'etat': 'hors_service', 'raison': raison}
    if not APP.is_dir():
        return absent(f"le dossier où l'app range ses sessions est introuvable ({APP})")
    if not metas:
        return absent(f"aucune session de l'app lisible dans {APP}")
    if not any(m.get('id') for m in metas):
        return {'etat': 'hors_service', 'raison': f"l'app enregistre ses sessions autrement qu'avant (identifiant "
                                                  f"absent) : une mise à jour de cockpit est nécessaire"}
    clis = [m['cli'] for m in metas if m.get('cli')]
    if not clis:
        return {'etat': 'hors_service', 'raison': f"l'app enregistre ses sessions autrement qu'avant (lien vers leur "
                                                  f"historique absent) : une mise à jour de cockpit est nécessaire"}
    if not any(c in index for c in clis):
        return absent(f"{len(metas)} session(s) de l'app, mais aucun historique de conversation dans {TRANSCRIPTS}")
    if not (INTERNE / LECTURE_OK).exists():
        try:
            INTERNE.mkdir(parents=True, exist_ok=True)
            (INTERNE / LECTURE_OK).write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
        except OSError:
            pass
    return {'etat': 'ok', 'raison': ''}


def construire(jours, silence, maintenant, cache):
    metas = fiches(cache)
    index = index_transcripts()
    lues = pastilles()
    humaines = [m for m in metas if not m['tache'] and not m['archivee'] and m['id']
                and os.path.normpath(m['cwd']) != os.path.normpath(str(SORTIE))]
    sessions, sans_transcript = [], []
    for m in humaines:
        chemin = index.get(m['cli']) if m['cli'] else None
        if not chemin:
            # Une session de l'app dont le transcript n'est pas sur ce Mac (session dans le cloud, dossier déplacé…)
            # ne se lit pas : comptée, pour que l'écran le dise au lieu de la taire. Seules les récentes comptent.
            if TRANSCRIPT_ATTENDU_S < maintenant - m['activite'] <= jours * 86400:
                sans_transcript.append(m)
            continue
        r = analyser_cache(chemin, cache, maintenant)
        if r['etat'] == 'vide':
            continue
        s = dict(m, chemin=chemin, derniere=r['depuis'], **r)
        if lues is not None:
            s['non_lue'], s['a_la_main'] = m['id'] in lues[0], m['id'] in lues[1]
        else:
            # Pastilles illisibles : une réponse de Claude arrivée après le dernier passage du PM dans la session.
            s['non_lue'], s['a_la_main'] = r['etat'] == 'attend' and r['depuis'] > m['focus'] > 0, False
        if s['etat'] == 'attend':
            s['lignes'], s['reste'], s['tete'], s['prio'] = trier(s.get('texte', ''))
        else:
            s['lignes'], s['reste'], s['tete'], s['prio'] = [], 0, '', None
        sessions.append(s)
    # En haut : ce qui porte une pastille de couleur dans la barre (non lu, Claude travaille, session bloquée).
    couleur = [s for s in sessions if s['non_lue'] or s['etat'] in ('travaille', 'suspens', 'erreur')]
    # En dessous : déjà lu, mais le dernier message de Claude attend encore quelque chose, dans la fenêtre.
    # Seulement si une action du PM est attendue (une recommandation seule ne suffit pas) et qu'il n'a pas répondu.
    grises = [s for s in sessions if s not in couleur and s['etat'] == 'attend' and s['prio'] in (1, 2, 3, 4)
              and maintenant - s['derniere'] <= jours * 86400]
    recence = {}
    for s in sessions:
        p = nom_projet(s['cwd'])
        recence[p] = max(recence.get(p, 0), s['derniere'])
    # Un bloc par Studio : d'abord ceux qui ont une pastille de couleur, puis les autres, les plus récents en tête.
    blocs = {}
    for s in couleur + grises:
        b = blocs.setdefault(nom_projet(s['cwd']), {'projet': nom_projet(s['cwd']), 'couleur': [], 'grises': []})
        b['couleur' if s in couleur else 'grises'].append(s)
    for b in blocs.values():
        b['couleur'].sort(key=lambda s: -s['derniere'])
        b['grises'].sort(key=lambda s: -s['derniere'])
    studios = sorted(blocs.values(), key=lambda b: (not b['couleur'], -recence[b['projet']]))
    silencieux = []
    for p, t in recence.items():
        if maintenant - t > silence * 86400:
            der = max((s for s in sessions if nom_projet(s['cwd']) == p), key=lambda s: s['derniere'])
            silencieux.append({'projet': p, 'depuis': t, 'session': der})
    silencieux.sort(key=lambda p: -p['depuis'])
    e = {'genere': maintenant, 'jours': jours, 'silence': silence, 'pastilles_lues': lues is not None,
         'couleur': couleur, 'grises': grises, 'studios': studios, 'silencieux': silencieux,
         'automates': automates(taches_planifiees(), metas, index, cache, maintenant),
         'lecture_app': lecture_app(metas, index)}
    # Les demandes fraîches, et à part les anciennes : rien ne sort de Mon Studio pour son âge.
    e['fermees'] = []
    e['tableau'], e['anciennes'] = lignes_et_anciennes(sessions, metas, e['automates'], jours, maintenant, cache,
                                                       e['fermees'])
    # Toutes les questions réglées dans leur session, sur preuve forte ou à confirmer : le tableau du chantier les
    # range dans son groupe « À confirmer » jusqu'à ce que le contremaître les solde.
    e['reglees'] = {chef: sorted(nums) for chef, nums in reglees(sessions, chantiers_actifs(metas), cache).items()}
    for f in e['fermees']:   # une question d'un chantier réglée sur preuve : « À confirmer » au tableau du chantier
        if f.get('chantier') and f.get('num') is not None and f.get('cle'):
            e['reglees'][f['cle']] = sorted(set(e['reglees'].get(f['cle'], [])) | {f['num']})
    e['nouvelles'] = nouvelles(sessions, metas, maintenant)
    e['menus'] = sorted(menus_ouverts(sessions))
    e['archivees'] = archivees_des_chantiers(chantiers_actifs(metas), metas)
    e['fils_rouges'] = fils_rouges(sessions, metas, e['tableau'], ecrits_du_pm(metas, index, cache))
    e['sans_action'] = sans_action(sessions, e['tableau'], e['fils_rouges'])
    e['sans_transcript'] = resume_sans_transcript(sans_transcript, e['lecture_app'])
    e['matin_retard'] = retard_du_matin(maintenant)
    noter_controle(cache, e['tableau'] + e['anciennes'], maintenant)
    # La vue par projet (vue_projet) : la clé de projet de chaque ligne, et de quoi la calculer sans relire l'app.
    cle_de = projets_des_sessions(metas)
    for l in e['tableau'] + e['anciennes']:
        l['projet'] = cle_de(l.get('ouvrir') or l.get('cle') or '', l.get('chantier'))
    e['_sessions'], e['_metas'] = sessions, metas
    return e


# --- la vue par projet ----------------------------------------------------------------------------------
#
# Pour le PM seul, sur son Mac (PM, 2026-11-03 : « c'est la vue par projet, pour ne pas tout mélanger quand on veut se
# focus sur un seul projet. Mon Studio reste pour la vue inter projets »). Calculée ici, sans LLM, des mêmes lectures
# que Mon Studio ; rien n'y est écrit par Claude. Un projet est un dossier : celui d'un chantier (son premier dossier,
# toutes ses sessions par regle_des_chantiers), sinon le dossier de la session (copie de travail rattachée à son dépôt).
# Deux dossiers qui portent le même nom restent deux projets : la clé est le chemin, jamais le nom affiché.

JOURNAL_MAX = 40
TIERS_JOURS = 30


def racine(cwd):
    """Le dossier d'une session, une copie de travail de l'app (<dépôt>/.claude/worktrees/<nom>) ramenée à son dépôt ;
    '' pour le dossier personnel, qui contiendrait tout."""
    d = os.path.normpath(cwd) if cwd else ''
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', d)
    d = m.group(1) if m else d
    return '' if not d or d == os.path.normpath(str(HOME)) else d


def projets_des_sessions(metas):
    """La fonction (session, chantier) -> clé du projet (un chemin), '' si aucune. Une ligne de chantier : le premier
    dossier de son chantier ; une session d'un chantier, de même ; sinon le dossier de la session."""
    par_id = {m['id']: m for m in metas if m['id']}
    actifs = chantiers_actifs(metas)
    couloirs = couloirs_de(actifs, metas)
    premier, par_nom = {}, {}
    for c in actifs:
        ds = dossiers_du_miroir(c, (par_id.get(c.get('sessionId')) or {}).get('cwd'))
        cle = ds[0] if ds else 'chantier:' + str(c.get('chantier'))
        premier[c.get('sessionId')], par_nom[c.get('chantier')] = cle, cle

    def cle_de(sid, chantier=None):
        if chantier and chantier in par_nom:
            return par_nom[chantier]
        chef = couloirs.get(sid)
        if chef and chef in premier:
            return premier[chef]
        return racine((par_id.get(sid) or {}).get('cwd'))
    return cle_de


def projets_de_la_page(lignes, metas):
    """[{studio, dossier, nom}] : les projets des lignes, dans leur ordre, pour les boutons « Vue projet »."""
    noms = {}
    for c in miroirs():
        noms[c.get('chantier')] = c.get('chantier')
    sortie, vus = [], set()
    for l in lignes:
        d = l.get('projet')
        if d and (l['studio'], d) not in vus:
            vus.add((l['studio'], d))
            sortie.append({'studio': l['studio'], 'dossier': d,
                           'nom': l.get('chantier') or (nom_projet(d) if not d.startswith('chantier:') else d[9:])})
    return sortie


def journal_du_miroir(c):
    """Les événements locaux d'un chantier (question.py event et settle), du plus ancien au plus récent."""
    chemin = pathlib.Path(c.get('_chemin') or '').with_suffix('.journal.jsonl') if c.get('_chemin') else None
    sortie = []
    try:
        with open(chemin, encoding='utf-8') as f:
            for ligne in f:
                try:
                    o = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get('at'):
                    sortie.append(o)
    except (OSError, TypeError):
        pass
    return sortie


def attentes_de_tiers(evenements, maintenant):
    """Les attentes d'un tiers (question.py event --type blocked) encore ouvertes : pas de « done » plus récent de la
    même session, et moins de TIERS_JOURS jours."""
    sortie, recus = [], tiers_recus()
    for i, o in enumerate(evenements):
        quand = ts_iso(o.get('at'))
        if o.get('type') != 'blocked' or not quand or maintenant - quand > TIERS_JOURS * 86400:
            continue
        if any(x.get('type') == 'done' and x.get('sessionId') == o.get('sessionId') and (ts_iso(x.get('at')) or 0) >= quand
               for x in evenements[i + 1:]):
            continue
        cle = cle_tiers(o)
        if cle in recus:
            continue
        sortie.append({'texte': o.get('text') or '', 'detail': o.get('detail') or '', 'session': o.get('session') or '',
                       'sessionId': o.get('sessionId') or '', 'depuis': quand, 'cle': cle})
    return sortie


TIERS_RECUS = 'tiers-recus.json'   # in ~/Mon Studio/.parc: the waits the PM marked « Reçu », by their key


def cle_tiers(o):
    """« t » and twelve hex digits: the key of a third-party wait, from its session, text and time."""
    brut = f"{o.get('sessionId') or ''}|{o.get('text') or ''}|{o.get('at') or ''}"
    return 't' + hashlib.sha1(brut.encode('utf-8')).hexdigest()[:12]


def tiers_recus():
    r = lire_json(INTERNE / TIERS_RECUS, {})
    return r if isinstance(r, dict) else {}


MOT_SIGNIFIANT = re.compile(r"[a-zà-ÿœ0-9]{4,}")


def mots_signifiants(texte):
    return set(MOT_SIGNIFIANT.findall(unicodedata.normalize('NFC', str(texte or '')).lower()))


def meme_sujet(a, b):
    """Two texts on the same subject, without a model: at least three shared words of four letters or more, and at
    least half of the shorter one's."""
    ma, mb = mots_signifiants(a), mots_signifiants(b)
    commun = ma & mb
    return len(commun) >= 3 and len(commun) * 2 >= min(len(ma), len(mb))


def sans_doublon_du_tableau(tiers, lignes):
    """The waits the board does not already carry (PM, 2026-11-17: « contrat signé » was in both): a wait on the same
    subject as a line of the same project leaves; the line stays, it is the one with a gesture."""
    textes = [' '.join(str(l.get(k) or '') for k in ('affiche_titre', 'affiche_suite', 'complet')) for l in lignes]
    return [x for x in tiers if not any(meme_sujet(f"{x['texte']} {x['detail']}", t) for t in textes)]


def jours_ouvres_entre(debut, fin):
    """Whole working days (Monday to Friday) from `debut` to `fin`, both epoch seconds."""
    a, b = dt.date.fromtimestamp(debut), dt.date.fromtimestamp(fin)
    n, j = 0, a
    while j < b:
        j += dt.timedelta(days=1)
        if j.weekday() < 5:
            n += 1
    return n


SANS_REPONSE_JOURS_OUVRES = 2


def sans_reponse(e, maintenant=None):
    """« Sans réponse » of the morning stand-up (PM, 2026-11-17): what the PM waits for from others for more than two
    working days, the third-party waits of every chantier still open and not marked « Reçu »."""
    maintenant = maintenant or e['genere']
    metas = e.get('_metas') or []
    par_id = {m['id']: m for m in metas if m['id']}
    sortie = []
    for c in chantiers_actifs(metas):
        dossier = (dossiers_du_miroir(c, (par_id.get(c.get('sessionId')) or {}).get('cwd')) or [''])[0]
        projet = c.get('chantier') or nom_projet(dossier)
        lignes = [l for l in e.get('tableau') or [] if unicodedata.normalize('NFC', l.get('projet') or '') == unicodedata.normalize('NFC', dossier)]
        for x in sans_doublon_du_tableau(attentes_de_tiers(journal_du_miroir(c), maintenant), lignes):
            if jours_ouvres_entre(x['depuis'], maintenant) >= SANS_REPONSE_JOURS_OUVRES:
                sortie.append({'cle': x['cle'], 'titre': x['texte'], 'qui': '', 'projet': projet,
                               'session': x['sessionId'], 'depuis': int(x['depuis'] * 1000)})
    return sorted(sortie, key=lambda x: x['depuis'])


def vue_projet(e, dossier, maintenant=None):
    """La vue d'un seul projet (clé : projets_des_sessions) : ses questions et actions (les lignes de Mon Studio de ce
    projet, rien d'autre), ses sujets (une ligne par session pilier, ses sessions filles dessous par le lien parent de
    l'app, l'état = le dernier compte rendu de fin de tour), ses attentes de tiers et son journal (comptes rendus de fin
    de tour et événements de question.py). None si aucune session ni ligne n'est de ce projet."""
    maintenant = maintenant or e['genere']
    metas, sessions = e.get('_metas') or [], e.get('_sessions') or []
    cle_de = projets_des_sessions(metas)
    par_id = {m['id']: m for m in metas if m['id']}
    # The app writes a session's folder decomposed (NFD: « partagés »), a pinned project page and projets.json
    # composed (NFC): the same Studio must match either way (PM, 2026-11-06, project pages with an accent were empty).
    nfc = lambda x: unicodedata.normalize('NFC', x or '')
    dossier = nfc(dossier)
    miennes = [s for s in sessions if nfc(cle_de(s['id'])) == dossier]
    questions = [l for l in e['tableau'] if nfc(l.get('projet')) == dossier]
    anciennes = [l for l in e.get('anciennes') or [] if nfc(l.get('projet')) == dossier]
    if not miennes and not questions and not anciennes:
        return None
    ids = {s['id'] for s in miennes}
    chantier = next((c for c in chantiers_actifs(metas)
                     if nfc((dossiers_du_miroir(c, (par_id.get(c.get('sessionId')) or {}).get('cwd')) or ['chantier:' + str(c.get('chantier'))])[0]) == dossier), None)

    def pilier_de(sid):
        """Le plus haut ancêtre de ce projet, par le lien parent de l'app (« spawnedFrom »), même à travers une session
        d'un autre dossier (une fille lancée dans un sous-dossier, une copie de travail)."""
        pilier, p = sid, sid
        for _ in range(8):
            p = (par_id.get(p) or {}).get('parent')
            if not p:
                break
            if p in ids:
                pilier = p
        return pilier

    def etat(s):
        if s['etat'] == 'travaille':
            texte = 'Claude travaille'
        else:
            texte = s.get('recap') or s.get('ouverture') or libelle_etat(s, maintenant)
        return {'titre': titre_lien(s['titre']), 'sessionId': s['id'], 'etat': texte, 'depuis': s['derniere'],
                'non_lue': bool(s.get('non_lue')), 'travaille': s['etat'] == 'travaille'}
    sujets = {}
    for s in sorted(miennes, key=lambda s: par_id.get(s['id'], {}).get('creee') or 0):
        racine_id = pilier_de(s['id'])
        if racine_id == s['id']:
            sujets.setdefault(s['id'], {'filles': []}).update(etat(s))
        else:
            sujets.setdefault(racine_id, {'filles': []})['filles'].append(etat(s))
    # Un pilier sans transcript lisible mais dont des filles le sont : il garde sa ligne, nommé par sa fiche.
    for sid, sj in sujets.items():
        if 'sessionId' not in sj:
            sj.update({'titre': titre_lien((par_id.get(sid) or {}).get('titre')), 'sessionId': sid, 'etat': '',
                       'depuis': max(f['depuis'] for f in sj['filles']), 'non_lue': False, 'travaille': False})
    recents = lambda sj: max([sj['depuis']] + [f['depuis'] for f in sj['filles']])
    evenements = journal_du_miroir(chantier) if chantier else []
    journal = [{'depuis': r['depuis'], 'texte': r['texte'], 'session': titre_lien(s['titre']), 'sessionId': s['id'],
                'genre': 'recap'} for s in miennes for r in s.get('recaps') or [] if r.get('depuis')]
    journal += [{'depuis': ts_iso(o['at']), 'texte': o.get('text') or '', 'session': o.get('session') or '',
                 'sessionId': o.get('sessionId') or '', 'genre': o.get('type') or ''}
                for o in evenements if ts_iso(o.get('at'))]
    journal.sort(key=lambda j: -j['depuis'])
    return {'dossier': dossier, 'nom': (chantier or {}).get('chantier') or nom_projet(dossier),
            'questions': questions, 'anciennes': anciennes,
            'sujets': sorted(sujets.values(), key=lambda sj: -recents(sj)),
            'tiers': sans_doublon_du_tableau(attentes_de_tiers(evenements, maintenant), questions + anciennes),
            'journal': journal[:JOURNAL_MAX]}


def retard_du_matin(maintenant):
    """La phrase « Point du matin pas passé aujourd'hui (dernier : JJ/MM) » de matin.py (même dossier), ou None ;
    jamais d'erreur : sans matin.py, rien."""
    global _MATIN
    try:
        if _MATIN is None:
            spec = importlib.util.spec_from_file_location('matin_retard', pathlib.Path(__file__).resolve().parent / 'matin.py')
            _MATIN = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_MATIN)
        _MATIN.parc.SORTIE = SORTIE   # le Mon Studio de ce calcul, même s'il a changé depuis le chargement
        return _MATIN.retard(maintenant)
    except Exception:
        return None


_MATIN = None


def resume_sans_transcript(metas, lecture):
    """Les sessions récentes de l'app que Mon Studio n'a pas pu lire, faute de transcript : leur nombre, cinq titres,
    et la phrase que la page et mon-studio.md affichent en tête. None quand il n'y en a pas, ou quand Mon Studio ne
    lit plus l'app du tout (le bandeau « Mon Studio ne lit plus l'app » le dit déjà)."""
    if not metas or lecture.get('etat') in ('hors_service', 'pas_encore'):
        return None
    metas = sorted(metas, key=lambda m: -m['activite'])
    n = len(metas)
    titres = [m['titre'] or 'Session sans titre' for m in metas[:5]]
    texte = (f"{n} sessions de l'app non lues : leur historique est introuvable sur ce Mac" if n > 1
             else "1 session de l'app non lue : son historique est introuvable sur ce Mac")
    texte += (" (session dans le cloud, dossier déplacé…) : " + ', '.join(f'« {t} »' for t in titres)
              + (f' et {n - len(titres)} autre(s)' if n > len(titres) else '') + '.')
    return {'nombre': n, 'titres': titres, 'texte': texte}


# --- le contrôle des lignes : d'où vient le texte de chaque ligne montrée au PM ----------------------------------
#
# Cadrage du 2026-10-19 : une ligne mal lue doit être repérée avant le PM, et aucune règle de lecture
# ne s'ajoute sans un cas compté. Chaque ligne du tableau dit d'où vient son texte (« lecture ») ; le calcul la note
# dans le cache, que seuls le connecteur de la page épinglée et l'écran local enregistrent : le relevé ne garde donc
# que ce que le PM a eu sous les yeux (ni les tests, ni lignes-brutes.py). `parc.py --controle` l'imprime pour le
# contremaître, qui juge les lignes à vérifier et signale une ligne muette à qui maintient Mon Studio.

LECTURES = {'inscrite': 'inscrites au tableau du chantier', 'format': 'questions au format « À trancher »',
            'rappel': 'questions rappelées et retrouvées', 'menu': 'questions de menu ou de carte',
            'native': 'questions de la carte de fin de tour, suivie d\'un texte',
            'auto': 'lignes automatiques (arrêt, erreur, automate)', 'phrase': 'phrases libres',
            'a_verifier': 'sessions qui ne disent pas si elles attendent',
            'introuvable': 'questions rappelées introuvables'}
A_VERIFIER = {'phrase': 'phrase libre', 'a_verifier': 'session qui ne dit pas si elle attend', 'introuvable': 'question introuvable'}   # pas une question posée : à juger
CONTROLE_JOURS = 30


def noter_controle(cache, lignes, maintenant):
    """Note dans cache['controle'] chaque ligne du tableau : d'où vient son texte, quand elle est apparue, quand elle a
    été vue pour la dernière fois. Une ligne non revue depuis CONTROLE_JOURS s'efface."""
    releve = cache.setdefault('controle', {})
    for l in lignes:
        texte = (l.get('complet') or '').strip()
        cle = f"{l.get('cle', '')}|{texte[:200]}"
        ent = releve.get(cle)
        if not ent:
            ent = releve[cle] = {'lecture': l.get('lecture') or '?', 'studio': l.get('studio') or '',
                                 'session': l.get('session') or '', 'texte': couper(texte, 300),
                                 'detail': couper((l.get('detail') or '').strip(), 300), 'vue': maintenant}
        ent['revue'] = maintenant
    for cle in [c for c, ent in releve.items() if maintenant - ent.get('revue', 0) > CONTROLE_JOURS * 86400]:
        del releve[cle]


def rapport_controle(releve, jours, maintenant):
    """Le relevé des lignes apparues ces derniers jours : combien par provenance du texte, puis celles à vérifier."""
    vues = sorted((x for x in releve.values() if maintenant - x.get('vue', 0) <= jours * 86400), key=lambda x: x['vue'])
    debut = dt.datetime.fromtimestamp(maintenant - jours * 86400).strftime('%d/%m')
    sortie = [f"Contrôle des lignes de Mon Studio, apparues depuis le {debut} : {len(vues)} ligne(s)."]
    for cle, nom in LECTURES.items():
        n = sum(1 for x in vues if x['lecture'] == cle)
        if n:
            sortie.append(f"- {n} {nom}")
    autres = sum(1 for x in vues if x['lecture'] not in LECTURES)
    if autres:
        sortie.append(f"- {autres} de provenance inconnue")
    a_voir = [x for x in vues if x['lecture'] in A_VERIFIER]
    sortie.append('')
    if not a_voir:
        sortie.append('À vérifier : rien.')
        return '\n'.join(sortie)
    sortie.append(f"À vérifier ({len(a_voir)}) : chaque ligne dit-elle ce que la session attend du PM ? Sinon, "
                  "signale-la à qui maintient Mon Studio, avec sa session.")
    for x in a_voir:
        quand = dt.datetime.fromtimestamp(x['vue']).strftime('%d/%m %H:%M')
        sortie.append(f"- {quand} · {x['studio']} · {x['session']} · {A_VERIFIER[x['lecture']]} : « {x['texte']} »")
        if x.get('detail') and x['detail'] != x['texte']:
            sortie.append(f"  détail : « {x['detail']} »")
    return '\n'.join(sortie)


# --- le tableau : une ligne par question ou action qui attend le PM -------------------------------------------
#
# Studio, session, ce qui l'attend, type, ancienneté. La colonne Session nomme, à chaque ligne, la session que
# le bouton ouvre. Une session qui travaille, ou qui a fini sans rien demander, ne donne pas de ligne. Les
# chantiers d'un contremaître (foreman-pm) arrivent par leur miroir : chaque attente devient une ligne qui ouvre
# la session de l'attente (sinon le contremaître), avec « Chantier <nom> · <kit> » en dessous ; une session
# du chantier ne donne de ligne que pour ce que le tableau ne porte pas encore (le contremaître la remplace
# par la sienne dès qu'il l'a reprise).

def soldees_au_journal(chemin):
    """Ce que le journal local d'un chantier (<chantier>.journal.jsonl, question.py settle) dit soldé : les documents
    soldés, et pour une ligne écrite sans document, (session, titre, heure du solde). Dans l'ordre du journal : une
    question réglée par la source puis rouverte par le PM (`reopened`, question.py) n'est plus soldée."""
    docs, sans_doc = set(), []
    try:
        with open(pathlib.Path(chemin).with_suffix('.journal.jsonl'), encoding='utf-8') as f:
            for ligne in f:
                if '"settled"' not in ligne and '"reopened"' not in ligne:
                    continue
                try:
                    o = json.loads(ligne)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get('type') not in ('settled', 'reopened'):
                    continue
                if o['type'] == 'reopened':
                    titres = {o.get('title'), o.get('settledTitle')} - {None}
                    if o.get('doc'):
                        docs.discard(o['doc'])
                    sans_doc = [x for x in sans_doc if not (x[0] == o.get('sessionId') and x[1] in titres)]
                elif o.get('doc'):
                    docs.add(o['doc'])
                elif o.get('title') and o.get('sessionId'):
                    sans_doc.append((o['sessionId'], o['title'], ts_iso(o.get('at')) or 0))
    except OSError:
        pass
    return docs, sans_doc


def soldee(a, docs, sans_doc):
    """Vrai si l'attente « a » du miroir est soldée au journal : même document, ou, sans document, même session et même
    titre soldés après qu'elle a été posée (un numéro revient chaque jour ouvré : jamais le numéro seul)."""
    if not isinstance(a, dict):
        return False
    if a.get('doc'):
        return a['doc'] in docs
    cree = ts_iso(a.get('depuis')) or 0
    return any(sid == a.get('sessionId') and titre == a.get('titre') and quand >= cree - REPRISE_S
               for sid, titre, quand in sans_doc)


def miroirs():
    """Les miroirs des chantiers, chacun avec « _numero » : le dernier numéro de question donné par son compteur
    (<chantier>.numero à côté du miroir, tenu par question.py et miroir.py ; 0 sans compteur). Lu ici, jamais écrit.
    Une attente soldée au journal local quitte la liste (« _soldees » les compte) : le solde d'une session écrit au
    journal d'abord, le miroir ne la retire qu'une fois le tableau publié soldé, ce qui peut ne jamais arriver (settled in the journal, but still open in the mirror)."""
    sortie = []
    for chemin in sorted(CHANTIERS.glob('*.json')):
        o = lire_json(chemin)
        if isinstance(o, dict) and o.get('chantier'):
            docs, sans_doc = soldees_au_journal(chemin)
            if isinstance(o.get('attentes'), list) and (docs or sans_doc):
                gardees = [a for a in o['attentes'] if not soldee(a, docs, sans_doc)]
                o['_soldees'] = len(o['attentes']) - len(gardees)
                o['attentes'] = gardees
            try:
                brut = chemin.with_suffix('.numero').read_text(encoding='ascii', errors='ignore').strip()
            except OSError:
                brut = ''
            o['_numero'] = int(brut) if brut.isdigit() else 0
            o['_chemin'] = str(chemin)
            sortie.append(o)
    return sortie


def tableau_publie():
    """False when the PM chose the app's own follow-up before the upgrade (`"tableau_publie": false` in cockpit.json):
    every mirror showed then, whatever its anchor session. True by default."""
    etat = lire_json(INTERNE / 'cockpit.json', {})
    return not (isinstance(etat, dict) and etat.get('tableau_publie') is False)


def miroir_cache(c, ancre):
    """True for a chantier mirror from before the registers (no `registre: true`) whose anchor session is archived or
    gone (`ancre`: its card as {'archivee': bool}, or None): its foreman ended, its old lines are not questions. As
    before the upgrade, nothing is hidden when the PM had chosen the app's own follow-up. A register is never hidden:
    the session that anchors it may be archived, its folder still says which sessions are the project's."""
    if c.get('registre') is True or not tableau_publie():
        return False
    return ancre is None or bool(ancre.get('archivee'))


def chantiers_actifs(metas):
    """Les miroirs des projets suivis : tous les registres, et les miroirs d'avant dont la session d'ancrage vit
    encore (miroir_cache)."""
    par_id = {m['id']: m for m in metas if m.get('id')}
    return [c for c in miroirs() if not miroir_cache(c, par_id.get(c.get('sessionId')))]


def dans_un_dossier(cwd, dossiers):
    """Vrai si le dossier de la session est l'un de ces dossiers, ou un de leurs sous-dossiers."""
    d = os.path.normpath(cwd) if cwd else ''
    return bool(d) and any(d == x or d.startswith(x + os.sep) for x in dossiers)


MANIFESTE_STUDIO = os.path.join('.claude', '.studio-manifest.json')
MARQUES_STUDIO = (os.path.join('projet', 'fiche-projet.md'), MANIFESTE_STUDIO)   # either one marks a Studio
ABSENT = (FileNotFoundError, NotADirectoryError, IsADirectoryError)   # a missing file; any other OSError: refused
PROFONDEUR_STUDIOS = 4   # how deep a Studio may hide under a chantier folder


def dossiers_de_l_instantane():
    """The Studio folders of projets-sources.json, the snapshot projets.py writes outside the connector."""
    i = lire_json(INTERNE / 'projets-sources.json', {})
    d = i.get('dossiers') if isinstance(i, dict) else None
    return {k for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else set()


def est_un_studio(d, instantane=None):
    """One rule for parc, projets and question.py: a folder with projet/fiche-projet.md or .claude/.studio-manifest.json
    (the manifest alone is enough: a Studio just created has no project card yet). When the read is refused (the
    connector, launched by the app, may not read the Drive), the folder is a Studio if the snapshot knows it:
    `instantane`, a set or dict of folders, read from projets-sources.json when None."""
    refus = False
    for marque in MARQUES_STUDIO:
        try:
            if stat.S_ISREG(os.stat(os.path.join(d, marque)).st_mode):
                return True
        except ABSENT:
            pass
        except OSError:
            refus = True
    if not refus:
        return False
    connus = dossiers_de_l_instantane() if instantane is None else instantane
    return d in connus or unicodedata.normalize('NFC', d) in connus


def contient_d_autres_studios(d):
    """True when a Studio mark sits in a subfolder of `d` (to PROFONDEUR_STUDIOS levels): the folder groups Studios,
    it is not one. Hidden folders and dependency folders are not entered; a refused folder is not entered either."""
    base = d.rstrip(os.sep).count(os.sep)
    for racine, noms, _ in os.walk(d):
        niveau = racine.rstrip(os.sep).count(os.sep) - base
        if niveau >= 1 and any(os.path.isfile(os.path.join(racine, m)) for m in MARQUES_STUDIO):
            return True
        noms[:] = [n for n in noms if not n.startswith('.') and n != 'node_modules'] if niveau < PROFONDEUR_STUDIOS else []
    return False


def dossier_du_chantier(cwd):
    """Le dossier qu'un chantier couvre, sous-dossiers compris : celui de la session du contremaître. Jamais le dossier
    personnel, qui contiendrait tout, ni un dossier qui n'est pas un Studio (est_un_studio), ni un
    dossier qui en regroupe plusieurs (un manifeste dans un sous-dossier) : il ferait lire à un chantier les Studios des autres."""
    d = os.path.normpath(cwd) if cwd else ''
    if not d or d == os.path.normpath(str(HOME)):
        return []
    if not est_un_studio(d) or contient_d_autres_studios(d):
        return []
    return [d]


def dossier_d_avant(cwd):
    """The folder a mirror from before the registers covers: its own, never the home folder."""
    d = os.path.normpath(cwd) if cwd else ''
    return [d] if d and d != os.path.normpath(str(HOME)) else []


def dossiers_du_miroir(c, cwd_du_chef):
    """Les dossiers qu'un chantier couvre : celui de son contremaître, plus ceux que son miroir ajoute (clé facultative
    « dossiers », liste de chemins). Un projet peut grouper plusieurs dossiers sous un seul tableau (PM, 2026-10-21 :
    Product kits regroupé dans un seul Studio, un projet, un tableau, un contremaître). Sous-dossiers et worktrees
    compris ; jamais le dossier personnel. Une session d'ancrage ouverte dans un de ces dossiers n'en ajoute pas un
    devant : le registre d'un Studio, créé par la question d'une session d'un sous-dossier, garde le Studio pour clé."""
    vus = []
    extra = [os.path.expanduser(x) for x in (c.get('dossiers') or []) if isinstance(x, str) and x.strip()]
    normaux = [os.path.normpath(x) for x in extra]
    if c.get('registre') is not True:
        # A mirror from before the registers keeps the rule it was written under (any folder but the home folder):
        # the upgrade neither renumbers its project nor orphans its open lines.
        chef, couvre = [cwd_du_chef], dossier_d_avant
    else:
        chef = [] if cwd_du_chef and dans_un_dossier(cwd_du_chef, normaux) else [cwd_du_chef]
        couvre = dossier_du_chantier
    for cwd in chef + extra:
        for d in couvre(cwd):
            if d not in vus:
                vus.append(d)
    return vus


def cites_par(c):
    """Les sessions qu'un miroir nomme : « couloirs » (identifiant, titre exact, ou fiche {titre, sessionId}),
    « piliers », et la session et le fil rouge de chacun de ses sujets (« lanes »)."""
    cites = set()
    for x in c.get('couloirs') or []:
        if isinstance(x, dict):
            cites.update(v for v in (x.get('sessionId'), x.get('titre')) if isinstance(v, str) and v)
        elif isinstance(x, str):
            cites.add(x)
    for x in c.get('piliers') or []:
        v = x.get('sessionId') if isinstance(x, dict) else x
        if isinstance(v, str) and v:
            cites.add(v)
    for x in c.get('lanes') or []:
        if isinstance(x, dict):
            cites.update(v for v in (x.get('sessionId'), x.get('pillarId')) if isinstance(v, str) and v)
    return cites


def regle_des_chantiers(chantiers, fiche):
    """La règle qui dit à quel chantier une session appartient. Une seule règle, pour l'écran et pour le numéro d'une
    question au PM (question.py la charge d'ici) : avec deux règles, une session prenait le numéro d'un chantier et
    attendait au tableau d'un autre. Un tableau égale un projet, donc :
    1. le contremaître appartient à son chantier ;
    2. une session ouverte dans le dossier d'un Studio qui a un contremaître (celui de sa session, plus ceux que le
       miroir ajoute dans « dossiers », sous-dossiers et worktrees compris ; jamais le dossier personnel, qui contiendrait
       tout) appartient à ce chantier, même si un
       autre miroir la nomme ; deux dossiers emboîtés : le plus profond ;
    3. hors de tout dossier de chantier seulement, une session lancée par un contremaître (descendantes comprises),
       sinon une session qu'un miroir nomme (cites_par).
    À égalité, le premier miroir. `fiche(id)` rend {cwd, titre, parent} d'une session, {} si inconnue. Rend la
    fonction : fiche {id, cwd, titre, parent} d'une session -> session du contremaître de son chantier, ou None."""
    regles = [(c['sessionId'], dossiers_du_miroir(c, (fiche(c['sessionId']) or {}).get('cwd')), cites_par(c))
              for c in chantiers if c.get('sessionId')]
    chefs = {chef for chef, _, _ in regles}

    def chef_de(m):
        sid = m.get('id')
        if not sid:
            return None
        if sid in chefs:
            return sid
        dossiers = [(len(x), chef) for chef, ds, _ in regles for x in ds if dans_un_dossier(m.get('cwd'), [x])]
        if dossiers:
            return max(dossiers, key=lambda x: x[0])[1]
        p, vus = m.get('parent'), 0
        while p and vus < 8:
            if p in chefs:
                return p
            p, vus = (fiche(p) or {}).get('parent'), vus + 1
        titre = m.get('titre')
        return next((chef for chef, _, cites in regles if sid in cites or (titre and titre in cites)), None)
    return chef_de


def couloirs_de(chantiers, metas):
    """{session: session du contremaître} pour les sessions qui appartiennent à un chantier (regle_des_chantiers), y
    compris une session ouverte demain dans le dossier d'un Studio."""
    par_id = {m['id']: m for m in metas if m['id']}
    chef_de = regle_des_chantiers(chantiers, lambda sid: par_id.get(sid) or {})
    dedans = {c['sessionId']: c['sessionId'] for c in chantiers if c.get('sessionId')}
    for m in metas:
        chef = chef_de(m)
        if chef:
            dedans[m['id']] = chef
    return dedans


REF_QUESTION = re.compile(r"\bQ(\d{1,3})\b")
ATTEND_ICI = re.compile(r"(?i)^[\s#*_>]*ce\s+qui\s+t['’]attend\b")
INTERRUPTION = re.compile(r"^\s*\[Request interrupted")


def ouvertes_dans(texte):
    """(posées, citées, sans_numero) : ce qu'un message final de Claude présente comme encore ouvert. Posées : les
    questions « À trancher », la ligne « Encore ouvert », les questions titrées sous « Ce qui t'attend ici », que la
    session tient jusqu'à réponse (format du PM, règle 4). Citées : un numéro dans une phrase qui demande quelque
    chose au PM (« Une fois fait, dis-le au contremaître pour qu'il ferme Q44 ») ; elle la rappelle, sans la tenir.
    « sans_numero » si « À trancher » porte une question sans numéro (on ne sait pas laquelle)."""
    items, ouverts = a_trancher(texte)
    nums = {i['num'] for i in items if i['num']} | set(ouverts)
    sans_numero = any(not i['num'] for i in items)
    dedans = False
    for ligne in (texte or '').split('\n'):
        if ATTEND_ICI.match(ligne):
            dedans = True
            continue
        if dedans and (debut_section(ligne) or re.match(r"^\s*#{1,6}\s", ligne)):
            dedans = False
        m = QUESTION_TITREE.match(ligne.strip()) if dedans else None
        if m:
            nums.add(int(m.group(1)))
    citees = set()
    if REF_QUESTION.search(texte or ''):
        _, _, notes, _ = trier(texte, expliquer=True)
        citees = {int(x) for nt in notes if nt['prio'] in (1, 2, 3, 4) for x in REF_QUESTION.findall(nt['p'])} - nums
    return nums, citees, sans_numero


# Le PM cite une question par son numéro (the only strong proof that he answers it, with the answer
# to the menu that carried it) : « Q112 », « Q112 : … », « q 112 », « pour la 112 », « sur la 112 », « la question 112 »,
# et en toutes lettres jusqu'à vingt après « pour la » ou « sur la » (« pour la deux… », format du PM, règle 3). Un
# nombre seul (« 1 », une option) ne cite rien ; « Q130 et 131 » ne cite que Q130. Dans le doute, rien : une preuve
# manquée laisse la ligne « à confirmer », une preuve fausse la ferait disparaître.
NOMBRES = {'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5, 'six': 6, 'sept': 7, 'huit': 8,
           'neuf': 9, 'dix': 10, 'onze': 11, 'douze': 12, 'treize': 13, 'quatorze': 14, 'quinze': 15, 'seize': 16,
           'dix-sept': 17, 'dix-huit': 18, 'dix-neuf': 19, 'vingt': 20}
CITE = re.compile(r"""(?ix)
    \bQ\s?(\d{1,4})\b(?![,.]\d)
  | \bla\s+question\s+(?:n[°o]\.?\s*)?(\d{1,4})\b(?![,.]\d)
  | \b(?:pour|sur)\s+la\s+(?:(\d{1,4})|(""" + '|'.join(sorted(NOMBRES, key=len, reverse=True)) + r"""))\b(?![,.\-]\w)
""")


def numeros_cites(texte):
    """Les numéros de question qu'un message du PM cite (CITE), triés."""
    nums = set()
    for m in CITE.finditer(texte or ''):
        chiffres = next((g for g in m.groups()[:3] if g), None)
        nums.add(int(chiffres) if chiffres else NOMBRES[m.group(4).lower()])
    return sorted(nums)


# Le PM dit qu'une question est faite (PM, 2026-11-10 : « Q12 c fait », et la ligne restait au tableau) : « Q12 c fait »,
# « Q12 fait », « Q12 ok c'est fait », « c bon c fait ». Un numéro cité prend le morceau du message qui le suit, jusqu'au
# numéro suivant (« Q11 désinstalle, Q10 c fait » : seule Q10 est faite). Jamais une négation (« pas encore fait »), une
# question (« c'est fait ? ») ni « fait » verbe d'une autre phrase (« fait le point », « fait quoi »).
FAIT_PM = re.compile(r"(?i)(?:(?<![\w'’])(?:c\s+|c['’]\s*|c['’]est\s+|ok\s+c['’]?\s*(?:est\s+)?|c['’]?\s*(?:est\s+)?déjà\s+)"
                     r"|^[\s:,.·–-]*(?:ok\s+|bon\s+|déjà\s+)?)fai(?:t|te|ts|tes)\b(?![\s,]*[?-])"
                     r"(?!\s+(?:quoi|comment|moi|le|la|les|l['’]|un|une|des|du|ça|ce|cela|que|qu['’]|en|pour|par|si|il|elle|on|attention|gaffe)\b)")
# « fait » avant le seul numéro cité ne compte que s'il le touche : « c fait pour la Q12 », « fait : Q12 » ; jamais
# « ok c fait mais il reste la Q4 » (revue indépendante, 2026-11-10).
FAIT_COLLE = re.compile(r"(?i)(?:^[\s:,.·–-]*|(?<![\w'’])c\s+|c['’]\s*|c['’]est\s+|\bok\s+|\bbon\s+|\bdéjà\s+)"
                        r"fai(?:t|te|ts|tes)\s*(?:pour\s+(?:la\s+)?|:\s*)?$")
PAS_FAIT = re.compile(r"(?i)\b(?:pas|plus|jamais|rien|ni)\s+(?:encore\s+|déjà\s+|tout\s+)?(?:été\s+)?(?:c['’]?\s*(?:est\s+)?)?"
                      r"fai(?:t|te|ts|tes)\b")


def faits_dans(texte):
    """(numéros dits faits, fait sans numéro) : ce qu'un message du PM dit fait (FAIT_PM). Sans numéro cité, le second
    est vrai si le message dit « fait » ; dites_faites le rapporte à la seule question que la session tenait."""
    t = texte or ''
    fait = lambda morceau: bool(FAIT_PM.search(morceau)) and not PAS_FAIT.search(morceau)
    cites = list(CITE.finditer(t))
    if not cites:
        return [], fait(t)
    nums = set()
    for i, m in enumerate(cites):
        fin = cites[i + 1].start() if i + 1 < len(cites) else len(t)
        avant = len(cites) == 1 and bool(FAIT_COLLE.search(t[:m.start()])) and not PAS_FAIT.search(t[:m.start()])
        if avant or fait(t[m.end():fin]):
            chiffres = next((g for g in m.groups()[:3] if g), None)
            nums.add(int(chiffres) if chiffres else NOMBRES[m.group(4).lower()])
    return sorted(nums), False


def dites_faites(sv):
    """{numéro: heure du mot} : les questions que le PM a dites faites dans la session (faits_dans), d'après son suivi
    (suivi_session). Règle d'ordre, la dernière parole l'emporte : le mot du PM ferme une question que la session a posée
    ou reportée AVANT lui (« À trancher », « Encore ouvert », un menu) ; une sortie de la session qui la pose encore APRÈS
    son mot la rouvre (la session la tient toujours, à elle de dire pourquoi ; la règle 5 du format lui demande de ne plus
    lister une question dite faite). Sans numéro (« c bon c fait »), le mot vise la question que la dernière sortie
    d'avant tenait, si elle n'en tenait qu'une ; sinon rien."""
    derniere = {}
    for t, nums, _, _, _ in sv['sorties']:
        for n in nums:
            derniere[n] = max(derniere.get(n, 0), t)
    sortie = {}
    for t, nums, seul in sv.get('faits') or []:
        cibles = set(nums)
        if seul:
            avant = [x for x in sv['sorties'] if x[0] < t]
            if avant and len(avant[-1][1]) == 1:
                cibles = set(avant[-1][1])
        for n in cibles:
            if 0 < derniere.get(n, 0) < t:
                sortie[n] = max(sortie.get(n, 0), t)
    return {n: t for n, t in sortie.items() if derniere[n] < t}


def repondues(sv):
    """{numéro: heure du mot} : les questions auxquelles le PM a répondu en citant leur numéro (« Q14 ok », numeros_cites)
    ou par le menu qui les portait, après la dernière sortie de la session qui les posait (« À trancher », « Encore
    ouvert », un menu). Même règle d'ordre que dites_faites : une sortie qui la pose encore après son mot la rouvre ;
    une sortie qui ne fait que la citer (« Audit final (Q14) : j'attends… ») rend compte de la réponse (PM, 2026-11-17)."""
    derniere = {}
    for t, nums, _, _, _ in sv['sorties']:
        for n in nums:
            derniere[n] = max(derniere.get(n, 0), t)
    sortie = {}
    for t, nums, _ in sv.get('pm') or []:
        for n in nums:
            if 0 < derniere.get(n, 0) < t:
                sortie[n] = max(sortie.get(n, 0), t)
    return sortie


def suivi_session(entrees):
    """Le fil d'une session source de questions du tableau, sur la fin de son transcript : ses sorties (message final
    ou menu de questions), dans l'ordre, avec ce que chacune présente comme ouvert, et les mots que le PM lui a écrits.
    Une sortie : [heure, posées, citées, menu, sans_numero] (voir ouvertes_dans ; un menu sans numéro est
    « sans_numero »). Un mot du PM : [heure, numéros, menu] ; pour un message, les numéros qu'il cite (numeros_cites) et
    menu None ; pour une réponse à un menu, les numéros que ce menu porte et l'heure du menu. « travail » : l'heure du
    dernier message de Claude, fini ou non (la session s'est mise au travail après le dernier mot du PM s'il est plus
    tard)."""
    sorties, pm, menus_poses, travail, faits = [], [], {}, 0, []
    j = 0
    while j < len(entrees):
        o = entrees[j]
        if o['type'] == 'user':
            contenu = (o.get('message') or {}).get('content')
            nature = nature_user(o)
            if nature == 'humain' and not INTERRUPTION.match(texte_de(contenu)):
                # Sans les notes de l'app en tête (« Linked sessions now : q18-conflits = … ») : pas ses mots.
                mots = NOTE_APP.sub('', texte_de(contenu))
                pm.append([horodatage(o) or 0, numeros_cites(mots), None])
                nums, seul = faits_dans(mots)
                if nums or seul:
                    faits.append([horodatage(o) or 0, nums, seul])
            elif nature == 'outil':
                repondu = next((menus_poses[b.get('tool_use_id')] for b in contenu or [] if isinstance(b, dict)
                                and b.get('type') == 'tool_result' and b.get('tool_use_id') in menus_poses), None)
                if repondu:   # une réponse à un menu
                    pm.append([horodatage(o) or 0, repondu[1], repondu[0]])
            j += 1
            continue
        # Un message de Claude : ses morceaux consécutifs (même identifiant), texte et menu compris.
        mid, morceaux, final, menu, ids, k = (o.get('message') or {}).get('id'), [], False, None, [], j
        while k < len(entrees) and entrees[k]['type'] == 'assistant' and (entrees[k].get('message') or {}).get('id') == mid:
            m = entrees[k].get('message') or {}
            morceaux.append(texte_de(m.get('content')))
            for b in m.get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'AskUserQuestion':
                    ids.append(b.get('id'))
                    menu = (menu or []) + (lire_menu(b.get('input')) or [])
            final = final or m.get('stop_reason') == 'end_turn'
            k += 1
        ts = horodatage(entrees[k - 1]) or 0
        travail = max(travail, ts)
        if menu is not None:
            texte = ' '.join(q['question'] + ' ' + ' '.join(x['label'] + ' ' + x['description'] for x in q['options'])
                             for q in menu)
            nums = sorted({int(x) for x in REF_QUESTION.findall(texte)})
            sorties.append([ts, nums, [], True, not nums])
            menus_poses.update({i: (ts, nums) for i in ids})
        elif final:
            posees, citees, sans_numero = ouvertes_dans('\n\n'.join(t for t in morceaux if t.strip()))
            sorties.append([ts, sorted(posees), sorted(citees), False, sans_numero])
        j = k
    return {'sorties': sorties, 'pm': sorted(pm, key=lambda w: w[0]), 'travail': travail,
            'faits': sorted(faits, key=lambda w: w[0])}


FORTE, A_CONFIRMER = 'forte', 'a_confirmer'
# La session a répondu au PM sans la reporter (ni « À trancher », ni « Encore ouvert ») : elle quitte Mon Studio comme
# une réglée sur preuve forte. La session reporte toute question
# encore ouverte (format du PM, règle 4) : ne plus la reporter, c'est qu'elle est réglée ou abandonnée.
SANS_REPORT = 'sans_report'
QUITTE = (FORTE, SANS_REPORT)   # ces lignes quittent le tableau ; A_CONFIRMER reste (la session travaille encore)


def reglee_dans_session(a, autres, sv):
    """FORTE, A_CONFIRMER ou None : l'attente numérotée « a » est-elle réglée dans sa session source ? La session a posé
    la question, le PM lui a écrit ensuite, et elle s'est mise au travail sur sa réponse sans la reposer (from that
    moment, without waiting for the end of the turn) ; elle redevient ouverte si la réponse de la session la repose.
    Preuve forte (un mot du PM ne suffit pas, quels que soient ses mots : il peut parler d'autre chose) : depuis la dernière fois que la
    session l'a posée, un message du PM qui cite son numéro (numeros_cites), ou sa réponse au menu qui la portait (un
    menu à son numéro, ou sans numéro et daté de l'attente). Sinon A_CONFIRMER : la ligne reste, « à confirmer ».
    « Posée » : la session la tient sous son numéro (« À trancher », « Encore ouvert », « Ce qui t'attend ici », un
    menu), ou par un menu daté de l'attente (le contremaître date une attente du moment où la question est posée).
    Une session qui ne fait que la citer (« dis-le au contremaître pour qu'il ferme Q44 ») ne l'a pas posée : le PM
    n'y répond pas. « Reposée » : son numéro revient dans ce qu'un message présente ou demande ; ou, dans la réponse
    au PM, un menu ou une question « À trancher » sans numéro qu'aucune autre attente de cette session ne date (on ne
    sait pas laquelle) : on attend alors son mot suivant. En cas de doute, None. « autres » : les autres attentes
    ouvertes de la même session source. « sv » : suivi_session de cette session."""
    n = num_question(a.get('titre'))
    cree = ts_iso(a.get('depuis')) or 0
    if n is None:
        return None
    # Un numéro revient chaque jour ouvré (PM, 2026-10-21) : un message qui le cite ne vise cette attente que s'il
    # vient après elle (à REPRISE_S près, le contremaître date une attente du moment où la question est posée). Un
    # ancien message de la session sous le même numéro parlait d'une autre question.
    apres = lambda t: t >= cree - REPRISE_S
    sorties = sv['sorties']
    posee = [t for t, nums, _, menu, _ in sorties
             if n in nums and apres(t) or menu and not nums and abs(t - cree) <= REPRISE_S]
    if not posee:
        return None   # rien ne montre que cette session l'a posée : le contremaître la soldera
    dates = [d for d in (ts_iso(b.get('depuis')) for b in autres) if d]

    def cite(mot):
        _, nums, menu = mot
        if menu is None:
            return n in nums   # un mot du PM écrit après la question (mots[0][0] > question)
        return n in nums and apres(menu) or not nums and abs(menu - cree) <= REPRISE_S

    # Une sortie qui ne fait que citer le numéro (« Audit final (Q14) : j'attends… ») après que le PM y a répondu en le
    # citant rend compte de sa réponse : elle ne la repose pas. Seule une sortie qui la pose de nouveau (« À trancher »,
    # « Encore ouvert », un menu) la rouvre (PM, 2026-11-17 : « Q14 ok » resté au tableau).
    base = max(posee + [cree - REPRISE_S])
    question = max([base] + [t for t, _, citees, _, _ in sorties if n in citees and apres(t)
                             and not any(base < w[0] < t and cite(w) for w in sv['pm'])])
    # Le PM l'a dite faite après la dernière fois que la session l'a posée (dites_faites) : réglée sans attendre que la
    # session se mette au travail.
    if dites_faites(sv).get(n, 0) > question:
        return FORTE

    forte = False
    while True:
        mots = [w for w in sv['pm'] if w[0] > question]
        if not mots:
            return None   # le PM ne lui a rien écrit depuis
        reponse = next((x for x in sorties if x[0] > mots[0][0]), None)
        forte = forte or any(cite(w) for w in mots if not reponse or w[0] < reponse[0])
        if not reponse:
            # Elle travaille sur sa réponse ; rien encore : elle ne l'a pas reprise.
            return (FORTE if forte else A_CONFIRMER) if sv.get('travail', 0) > mots[0][0] else None
        t, _, _, _, sans_numero = reponse
        if not (sans_numero and not any(abs(t - d) <= REPRISE_S for d in dates)):
            return FORTE if forte else SANS_REPORT
        question = t


def reprise_dans_session(a, sv):
    """L'heure de la dernière sortie de sa session source qui pose encore l'attente numérotée « a » (« À trancher »,
    « Encore ouvert », un menu à son numéro), depuis qu'elle a été posée ; None sinon. Le tri du tableau met en tête la
    question posée ou reportée le plus récemment, et une question que rien ne reporte depuis « jours » jours va dans
    « Anciennes »."""
    n = num_question(a.get('titre'))
    cree = ts_iso(a.get('depuis')) or 0
    if n is None:
        return None
    vues = [t for t, nums, _, _, _ in sv['sorties'] if n in nums and t >= cree - REPRISE_S]
    return max(vues) if vues else None


def reglees(sessions, chantiers, cache):
    """{session du contremaître: {numéro: FORTE, SANS_REPORT ou A_CONFIRMER}} : les questions du tableau réglées dans
    leur session, sans attendre le contremaître (voir reglee_dans_session). Sur preuve forte, ou quand la session a
    répondu sans la reporter, elles quittent le tableau de Mon Studio ; sinon elles y restent. Le tableau du chantier les
    range toutes dans son groupe « À confirmer » jusqu'à ce que le contremaître les solde avec les mots du PM. Lu dans la
    fin du transcript de la session source (8 Mo), gardé dans le cache par empreinte (`cache['suivi']`)."""
    return {chef: {n: v[0] for n, v in nums.items() if v[0]}
            for chef, nums in suivis(sessions, chantiers, cache).items() if any(v[0] for v in nums.values())}


def suivis(sessions, chantiers, cache):
    """{session du contremaître: {numéro: (réglée, reprise)}} : pour chaque question numérotée d'un miroir dont la session
    source est lue, ce que dit reglee_dans_session et l'heure de sa dernière reprise (reprise_dans_session)."""
    vues, sortie = {s['id']: s for s in sessions}, {}
    cache = cache if cache is not None else {}
    for c in chantiers:
        chef = c.get('sessionId')
        attentes = [a for a in c.get('attentes') or [] if isinstance(a, dict) and a.get('titre')]
        for a in attentes:
            s = vues.get(a.get('source'))
            if num_question(a['titre']) is None or not s or s['id'] == chef:
                continue
            emp = empreinte(s['chemin'])
            ent = cache.setdefault('suivi', {}).get(s['chemin'])
            if not ent or ent['emp'] != emp:
                entrees, _ = entrees_fin(s['chemin'], HISTOIRE_MAX)
                ent = cache['suivi'][s['chemin']] = {'emp': emp, 'res': suivi_session(entrees)}
            autres = [b for b in attentes if b is not a and b.get('source') == a.get('source')]
            sortie.setdefault(chef, {})[num_question(a['titre'])] = (reglee_dans_session(a, autres, ent['res']),
                                                                      reprise_dans_session(a, ent['res']))
    return sortie
REPRISE_S = 300   # une attente datée jusqu'à 5 min avant la question la reprend encore (horloges, secondes arrondies)


def au_tableau(chantiers):
    """Ce que le tableau de chaque chantier porte déjà (clé : la session du contremaître) : les numéros de ses
    attentes ouverts, avec la session qui en parle (champ « source »), et, par session, la date de sa dernière
    attente (le contremaître date une attente du moment où la question a été posée). « plafond » : le plus grand
    numéro que le chantier a donné, ouvert au tableau ou pris à son compteur (soldé depuis, peut-être). « crees » : la
    date de création de l'attente ouverte sous chaque numéro (la plus ancienne s'il y en a deux) ; un message ne vise
    cette attente que s'il vient après elle, puisqu'un numéro revient chaque jour ouvré."""
    sortie = {}
    for c in chantiers:
        nums, derniere, crees = {}, {}, {}
        for a in c.get('attentes') or []:
            if not a.get('titre'):
                continue
            src = a.get('source') or a.get('sessionId') or ''
            n = num_question(a['titre'])
            t = ts_iso(a.get('depuis')) or ts_iso(c.get('misAJour'))
            if n is not None:
                nums.setdefault(n, set()).add(src)
                crees[n] = min(crees.get(n, t or 0), t or 0)
            if src and t:
                derniere[src] = max(derniere.get(src, 0), t)
        sortie[c.get('sessionId')] = {'nums': nums, 'derniere': derniere, 'crees': crees,
                                      'plafond': max([c.get('_numero') or 0] + list(nums))}
    return sortie


def deja_au_tableau(d, sid, chef, tableau_du, quand=None):
    """Vrai si le tableau du chantier porte déjà cette demande d'une de ses sessions : la question sous son numéro
    (attente de la même session, ou n'importe laquelle pour le contremaître, qui numérote au tableau) ; un simple
    rappel de questions toutes au tableau (« Toujours en attente de toi : Q12, Q15 ») ; ou une attente de cette
    session datée au plus tôt de la question. Une question posée après la dernière reprise reste visible.
    Aussi (contrôle des lignes du 2026-10-20) : une question rappelée que la session n'a jamais posée (« introuvable »)
    sous un numéro que le chantier a donné : c'est celle d'une autre session ou du contremaître, au tableau ou déjà
    soldée (« Encore ouvert (autres sessions) : Q112, Q113 ») ; et une phrase qui renvoie à une autre session dont les
    questions sont au tableau (« renvoi », voir renvois_au_tableau) : le PM a déjà leur ligne.
    Un numéro revient chaque jour ouvré (PM, 2026-10-21) : le message de la session (« quand », l'heure du message qui
    porte la demande, sinon « depuis ») ne vise une attente ouverte sous ce numéro que s'il vient après sa création ;
    un ancien message qui cite le même numéro parlait d'une autre question, et sa ligne reste."""
    t = tableau_du.get(chef) or {'nums': {}, 'derniere': {}, 'plafond': 0}
    quand = d['depuis'] if quand is None else quand
    ouvertes = {k for k, v in t['nums'].items() if quand >= (t.get('crees') or {}).get(k, 0) - REPRISE_S}
    n = d.get('num')
    if n is not None and (sid == chef or n in ouvertes and sid in t['nums'][n]):
        return True
    if d.get('renvoi') or n is not None and d.get('lecture') == 'introuvable' and n <= t.get('plafond', 0):
        return True
    # Un « Qn » que le message cite (rappel : « Encore ouvert », phrase) sans qu'aucune ligne ouverte du miroir porte ce
    # numéro, sous un numéro que le chantier a donné : la question est soldée (hier ou tout à l'heure), puisqu'une
    # question posée par une session passe au tableau. Elle ne rouvre jamais une ligne (PM, 2026-10-22). Si le numéro
    # est repris par une autre question ouverte, la règle de la date ci-dessous décide (PM, 2026-10-21). Les questions
    # que la session pose elle-même (« À trancher », lecture « format ») gardent leur règle.
    if (n is not None and (d.get('lecture') == 'rappel' or d.get('rappel_phrase'))
            and n not in t['nums'] and n <= t.get('plafond', 0)):
        return True
    # Une question qu'une phrase rappelle (« Toujours en attente de toi : Q12, Q15 ») et que le tableau porte, de cette
    # session ou d'une autre : la phrase ne faisait déjà pas de ligne, son rappel non plus.
    if n is not None and d.get('rappel_phrase') and n in ouvertes:
        return True
    refs = {int(x) for x in REF_QUESTION.findall((d.get('titre') or '') + ' ' + (d.get('suite') or ''))}
    if n is None and refs and refs <= ouvertes:
        return True
    return sid in t['derniere'] and d['depuis'] <= t['derniere'][sid] + REPRISE_S


def renvois_au_tableau(d, sid, chef, chantiers, tableau_du, metas):
    """Une phrase qui dit qu'une autre session attend le PM (contrôle des lignes du 2026-10-20 : « Je la vois : [Kit]
    (#local_…). Elle a bien repris le kit […] et attend ta réponse à une question. », sans la question) : si la session
    désignée (autour_de_la_phrase : son lien, ou son titre exact entre « ») a des questions ouvertes au tableau d'un
    chantier, la ligne les nomme à la suite de la phrase (« · Q121 au tableau », puis le nom du chantier quand ce n'est
    pas celui de la session) et porte « renvoi » : dans un chantier, elle s'efface derrière leurs lignes, que le PM a
    déjà (deja_au_tableau). Sinon, rien ne change."""
    ids, titres = set(d.get('renvoie_a') or ()), set(d.get('renvoie_titres') or ())
    if titres:
        par_titre = {}
        for m in metas:
            if m['id'] and not m['archivee'] and m['titre'] in titres:
                par_titre.setdefault(m['titre'], []).append(m['id'])
        ids |= {v[0] for v in par_titre.values() if len(v) == 1}   # un titre porté par deux sessions ne désigne rien
    ids.discard(sid)
    bouts = []
    for c in chantiers if ids else []:
        nums = sorted(n for n, srcs in (tableau_du.get(c.get('sessionId')) or {}).get('nums', {}).items() if srcs & ids)
        if nums:
            bouts.append(', '.join(f"Q{n}" for n in nums) + ' au tableau'
                         + ('' if c.get('sessionId') == chef else f" {c.get('chantier')}"))
    if bouts:
        d['suite'] = d['suite'].rstrip(' .') + ' · ' + ' ; '.join(bouts)
        d['renvoi'] = True
    return d


def ts_iso(v):
    try:
        return dt.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


QUESTION_SANS_TEXTE = "Une question t'attend dans cette session"
CONTEXTE_MAX = 600       # le détail d'une question introuvable : la fin du dernier message, coupée net


def avant_encore_ouvert(texte, n=2):
    """Les n derniers paragraphes d'un message juste avant sa ligne « Encore ouvert », sans décor (sinon ceux qui la
    suivent) : ce que disait la session en rappelant une question introuvable dans son transcript. Titres, blocs de
    code et tableaux sautés."""
    avant, apres, bloc, en_code, passe = [], [], [], False, False
    for ligne in (texte or '').split('\n'):
        s = ligne.strip()
        if s.startswith(('```', '~~~')):
            en_code = not en_code
            continue
        ouvert = not en_code and debut_section(ligne) == 'ouvert'
        if en_code or ouvert or not s or s.startswith(('|', '#')):
            if bloc:
                (apres if passe else avant).append(bloc)
                bloc = []
            passe = passe or ouvert
            continue
        bloc.append(nettoyer(s))
    if bloc:
        (apres if passe else avant).append(bloc)
    return couper(' '.join(' '.join(b) for b in (avant or apres)[-n:]), CONTEXTE_MAX)


def question_introuvable(texte):
    """Le détail d'une question rappelée qu'aucun paragraphe ni menu du transcript ne pose (2026-10-16 : le détail ne
    doit jamais être vide, ni répéter le titre) : annoncé comme tel, avec la fin du dernier message de la session."""
    dit = avant_encore_ouvert(texte)
    return (f"Question introuvable dans la session ; son dernier message disait : « {dit} »" if dit
            else "Question introuvable dans la session, et son dernier message n'en dit pas plus.")


# --- le détail d'une phrase libre : le bloc auquel elle renvoie --------------------------------------------------
#
# Contrôle des lignes du 2026-10-20 : « Dis « ok » ou corrige une ligne : je fais alors les points 4.1 à 4.4. » avait
# pour titre et pour détail la même phrase, et la liste à valider, juste au-dessus dans le message, n'était nulle
# part. Une ligne tirée d'une phrase (pas d'une question numérotée) porte au détail, en plus de la phrase, le bloc qui
# la précède : la liste, le tableau ou le paragraphe auquel elle renvoie ; ou le bloc qui la suit, quand elle
# l'annonce (« Reste à faire de ton côté : » devant sa liste) ou qu'elle ouvre le message. Annoncé comme tel, coupé.

CONTEXTE_PHRASE_MAX = 900   # le bloc cité au détail d'une phrase libre, coupé net
ELEMENT_MIN = 100           # chaque élément d'une liste citée, ou rang d'un tableau, garde au moins 100 caractères
PROCHE_MAX = 300            # le texte du même paragraphe, juste avant ou après la phrase
SEPARATEUR_TABLEAU = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
NUMERO_LISTE = re.compile(r"^\s*(?:(?:\d{1,2}|[a-hA-H])[.)]|\((?:\d{1,2}|[a-hA-H])\))\s+")
# Une phrase qui renvoie à une autre session (contrôle du 2026-10-20 : « Je la vois : [Kit](#local_…). Elle a bien
# repris le kit […] et attend ta réponse à une question. ») : le lien de la session, ou son titre exact entre « ».
LIEN_SESSION = re.compile(r"(?:#|claude://[^\s)]*?/)(local_[0-9A-Za-z-]+)")
TITRE_CITE = re.compile(r"«\s*([^«»]+?)\s*»")
SUJET_REPRIS = re.compile(r"(?i)^(?:elle|il|elles|ils|celle-ci|celui-ci|celles-ci|ceux-ci|cette\s+session|la\s+session"
                          r"|ces\s+sessions)\b")
ATTEND_LE_PM = re.compile(r"(?i)\battend(?:ent)?\s+(?:ta|ton|tes)\b|\bt['’]attend(?:ent)?\b")
PREMIERE_PERSONNE = re.compile(r"(?i)\b(?:je|moi|me)\b|\b[jm]['’]")


def blocs_du_message(texte):
    """Le message en blocs, dans l'ordre : [(genre, [lignes])]. Genres : 'titre' (titre, ligne en gras seule), 'code',
    'liste' (ses éléments, leurs suites en retrait et les lignes vides entre eux), 'tableau', 'texte' (un paragraphe)."""
    blocs, en_code, vide = [], False, False
    for brute in (texte or '').split('\n'):
        ligne = brute.rstrip()
        s = ligne.strip()
        if s.startswith(('```', '~~~')):
            if not en_code:
                blocs.append(('code', []))
            en_code, vide = not en_code, True
            continue
        if en_code:
            blocs[-1][1].append(ligne)
            continue
        if not s:
            vide = True
            continue
        genre = ('titre' if re.match(r"^#{1,6}\s", s) or gras_seul(ligne) else 'tableau' if s.startswith('|')
                 else 'liste' if PUCE.match(ligne) else 'texte')
        d = blocs[-1] if blocs else None
        if d and (d[0] == 'liste' and (genre == 'liste' or ligne[:1] in ' \t' or genre == 'texte' and not vide)
                  or d[0] == genre and genre in ('texte', 'tableau') and not vide):
            d[1].append(ligne)
        else:
            blocs.append((genre, [ligne]))
        vide = False
    return blocs


def texte_du_bloc(genre, lignes, budget):
    """Un bloc en une ligne, sans décor : une liste élément par élément (« · » entre eux, leur numéro gardé), un
    tableau rang par rang (« / » entre les cellules), un paragraphe tel quel. Chaque élément est coupé pour que tous
    tiennent dans le budget ; le tout est coupé net."""
    if genre == 'liste':
        elements = []
        for l in lignes:
            if PUCE.match(l) or not elements:
                m = NUMERO_LISTE.match(l)
                elements.append((m.group(0).strip() + ' ' if m else '') + nettoyer(l))
            else:
                elements[-1] += ' ' + nettoyer(l)
    elif genre == 'tableau':
        elements = [' / '.join(nettoyer(c) for c in l.strip().strip('|').split('|') if c.strip())
                    for l in lignes if not SEPARATEUR_TABLEAU.match(l)]
    else:
        return couper(nettoyer(' '.join(lignes)), budget)
    part = max(ELEMENT_MIN, budget // max(1, len(elements)))
    return couper(' · '.join(couper(e, part) for e in elements if e), budget)


def autour_de_la_phrase(texte, tete):
    """Ce qui entoure la phrase d'action « tete » dans son message : {avant, apres, renvoie_a, renvoie_titres}.
    « avant » : le bloc qui la précède (liste, tableau, paragraphe ; jamais au-delà d'un titre ou d'un bloc de code),
    puis le début de son paragraphe ; pour un élément de liste, les éléments qui le précèdent, puis le début de
    l'élément. « apres » : la fin de son paragraphe, puis le bloc qui la suit ; pour un élément de liste, la fin de
    l'élément et sa sous-liste, sinon le bloc qui suit la liste. « renvoie_a » et « renvoie_titres » : les sessions
    qu'elle désigne par un lien ou par leur titre entre « », dans la phrase ou, si elle commence par « Elle… »,
    « Cette session… », dans ce qui la précède sur sa ligne ; seulement si elle dit qu'une session attend le PM
    (« attend ta réponse », « t'attend »). None si la phrase n'est pas retrouvée."""
    phrase = nettoyer(tete or '')
    # Retrouvée par la fin de sa dernière phrase : le tri lui rattache parfois une phrase prise ailleurs (« Je peux…
    # Je le fais ? ») ou la tête coupée de son élément de liste.
    cle = (couper_phrases(phrase.rstrip(' :')) or [''])[-1][-40:]
    if not cle:
        return None
    blocs = blocs_du_message(texte)
    ou = next(((b, k) for b in range(len(blocs) - 1, -1, -1) if blocs[b][0] != 'code'
               for k in range(len(blocs[b][1]) - 1, -1, -1) if cle in nettoyer(blocs[b][1][k])), None)
    if ou is None:
        return None
    b, k = ou
    genre, lignes = blocs[b]
    ligne = nettoyer(lignes[k])
    fin = ligne.rfind(cle) + len(cle)
    # La phrase commence où commencent ses premiers mots (le tri la fait parfois précéder de la tête coupée de son
    # élément, « … » compris : sa longueur ne dit alors plus où elle commence).
    debut = ligne.rfind(phrase[:25], 0, fin)
    debut = debut if debut >= 0 else max(0, fin - len(phrase.rstrip(' :')))
    # Le reste de son paragraphe ; dans une liste, le reste de son élément, sous-liste comprise, et avant lui les
    # éléments qui le précèdent (« Enregistre le fichier sur Drive… » devant « Si tu me dis où tu l'as mis… »).
    meme = genre == 'texte'
    proche_avant = ' '.join([nettoyer(l) for l in lignes[:k]] * meme + [ligne[:debut]]).strip()
    proche_apres = ' '.join([ligne[fin:]] + [nettoyer(l) for l in lignes[k + 1:]] * meme).strip(' :')
    sous = []
    if genre == 'liste':
        retrait = len(lignes[k]) - len(lignes[k].lstrip())
        for l in lignes[k + 1:]:
            if len(l) - len(l.lstrip()) <= retrait:
                break
            sous.append(l)

    def voisin(i):
        return blocs[i] if 0 <= i < len(blocs) and blocs[i][0] not in ('titre', 'code') else None

    def assembler(loin, proche, avant):
        proche = couper(proche, PROCHE_MAX) if proche else ''
        loin = texte_du_bloc(loin[0], loin[1], CONTEXTE_PHRASE_MAX - len(proche)) if loin else ''
        return ' '.join(x for x in ((loin, proche) if avant else (proche, loin)) if x)

    ids, titres = [], []
    # Seulement une phrase qui dit qu'une autre session attend le PM, sans rien demander elle-même (ni « je », ni
    # question) : une demande de la session ne doit jamais se cacher derrière une question d'une autre.
    if ATTEND_LE_PM.search(tete) and not termine_par_question(tete) and not PREMIERE_PERSONNE.search(tete):
        portee = tete
        if not LIEN_SESSION.search(tete) and not TITRE_CITE.search(tete) and SUJET_REPRIS.match(nu(tete)):
            i = lignes[k].find(tete.strip()[:30])
            portee = lignes[k][:i] if i > 0 else ''
        ids = LIEN_SESSION.findall(portee)
        titres = [nettoyer(t) for t in TITRE_CITE.findall(LIEN_SESSION.sub('', portee))]
    return {'avant': assembler(('liste', lignes[:k]) if genre == 'liste' and k else voisin(b - 1), proche_avant, True),
            'apres': assembler(('liste', sous) if sous else voisin(b + 1), proche_apres, False),
            'renvoie_a': ids, 'renvoie_titres': titres}


def detail_de_phrase(texte, tete, autour):
    """Le détail d'une ligne tirée d'une phrase : la phrase entière, puis le bloc auquel elle renvoie, annoncé comme
    tel (« Juste avant, son message disait : « … » ») ; le bloc d'après quand elle l'annonce (elle finit par « : ») ou
    que rien ne la précède. Jamais la phrase seule : sans rien autour, le détail le dit. « autour » :
    autour_de_la_phrase(texte, tete)."""
    phrase = nettoyer(tete).rstrip(' :')
    phrase += '' if phrase.endswith(('.', '!', '?', '…', '»')) else '.'
    if autour is None:
        dit = avant_encore_ouvert(texte)
        return f"{phrase} Son message disait : « {dit} »" if dit else f"{phrase} Son message n'en dit pas plus."
    annonce = nettoyer(tete).endswith(':')
    if autour['avant'] and not (annonce and autour['apres']):
        return f"{phrase} Juste avant, son message disait : « {autour['avant']} »"
    if autour['apres']:
        return f"{phrase} Juste après, son message disait : « {autour['apres']} »"
    return f"{phrase} Son message n'en dit pas plus."


NUMERO_EN_TETE = re.compile(r"^\s*[*_]*Q\d{1,3}\b[*_]*\s*(?:[·•:–]|[.-](?=\s))\s*")


def sans_numero_propre(d):
    """Une ligne d'une session d'un Studio qui a un contremaître, sans le numéro qu'elle donne elle-même à sa question
    (« Q4 · », « Q4 : ») : il se confond avec ceux du tableau du chantier (PM, 2026-10-15). Le numéro reste dans
    « num » pour le calcul (deja_au_tableau, ordre)."""
    d = dict(d)
    champ = 'titre' if d.get('titre') else 'suite'
    d[champ] = NUMERO_EN_TETE.sub('', d.get(champ) or '', count=1)
    if d.get('detail'):
        d['detail'] = NUMERO_EN_TETE.sub('', d['detail'], count=1)
    return d


def demandes(s):
    """Les lignes d'une session qui attend (_demandes), et la question de sa carte de fin de tour quand le PM n'y a pas
    encore répondu (question native de l'app, 2026-11-03) : une ligne de plus, sauf si le message la porte déjà (même
    numéro, ou même texte). La carte dit ce que la session attend : la ligne « Ne dit pas si elle attend quelque chose
    de toi » n'a plus lieu d'être."""
    lignes = _demandes(s)
    carte = s.get('carte')
    if not carte or not carte.get('menu'):
        return lignes
    d = ligne_menu(carte['menu'], carte.get('depuis') or s['depuis'])
    m = QUESTION_TITREE.match(carte['menu'][0]['question'])
    num = int(m.group(1)) if m else None
    nums = {l.get('num') for l in lignes} - {None}
    # Une carte sans numéro dans un message qui numérote ses questions la redit dans la boîte, en d'autres mots (mesuré
    # sur un Studio : « Relancer le passage maintenant ? » pour « Q1 · Relance du passage »).
    if (num in nums if num is not None else bool(nums)) or any(
            nu(d['titre']) in (nu(l.get('titre') or ''), nu(l.get('suite') or '')) for l in lignes):
        return lignes
    d.update(num=num, lecture='native', bloque=False, native=True)
    return sorted([l for l in lignes if l.get('suite') != A_VERIFIER_SUITE] + [d], key=lambda l: l.get('num') or 0)


def _demandes(s):
    """Les lignes d'une session qui attend : ses questions « À trancher » (et celles encore ouvertes), sinon
    la phrase d'action la plus forte de son dernier message."""
    texte = s.get('texte') or ''
    premiere = next((l for l in texte.split('\n') if l.strip()), '')
    if re.sub(r"^[\s#*_>]+", '', premiere).startswith('📬'):
        return []  # l'introduction d'un fil 📬 : elle présente le fil, elle ne demande rien
    items, ouverts = a_trancher(texte)
    faites = set(s.get('faites') or [])
    # Toutes ses questions numérotées dites faites : la session a dit ce qu'elle attendait, plus rien.
    tenues = {it['num'] for it in items if it['num']} | set(ouverts)
    toutes_faites = bool(tenues) and tenues <= faites
    items = [it for it in items if it['num'] not in faites]
    hist = s.get('questions') or {}
    lignes, vus = [], set(faites)
    for it in items:
        q = hist.get(str(it['num'])) if it['num'] else None
        lignes.append({'titre': it['titre'], 'suite': it['suite'], 'brut': it.get('brut') or '',
                       'depuis': (q or {}).get('depuis') or s['depuis'], 'num': it['num'], 'lecture': 'format'})
        vus.add(it['num'])
    # Une question rappelée par « Encore ouvert » : son paragraphe ou sa question de menu dans tout le transcript
    # (historique_questions, questions_anciennes), le menu avec son détail ; sinon la parenthèse du rappel en titre,
    # sinon une phrase qui dit qu'une question attend, et au détail la fin du dernier message. Jamais « posée plus haut ».
    rappels = encore_ouvert(texte)
    for n in ouverts:
        if n in vus:
            continue
        vus.add(n)
        q, lecture = hist.get(str(n)), 'rappel'
        if not q:
            dit, lecture = rappels.get(n) or QUESTION_SANS_TEXTE, 'introuvable'
            q = {'titre': f"Q{n} · {dit[:1].upper()}{dit[1:]}", 'suite': '', 'detail': question_introuvable(texte)}
        lignes.append({'titre': q['titre'], 'suite': q['suite'], 'depuis': q.get('depuis') or s['depuis'], 'num': n,
                       'lecture': lecture})
        if q.get('detail'):
            lignes[-1]['detail'] = q['detail']
    # Une phrase qui rappelle des questions numérotées hors de « Encore ouvert » (contrôle des lignes du 2026-10-20) :
    # chacune comme un rappel, retrouvée dans le transcript ; sinon titrée par ce que la phrase en dit. La phrase ne
    # fait plus de ligne. Pas dans un fil 📬, qui ne reçoit que des nouvelles.
    en_phrase = {} if (s.get('titre') or '').lstrip().startswith('📬') else rappels_en_phrase(texte)
    en_phrase = {n: r for n, r in en_phrase.items() if n not in faites and n not in set(s.get('repondues') or [])}
    for n, r in en_phrase.items():
        if n in vus:
            continue
        vus.add(n)
        q, lecture = hist.get(str(n)), 'rappel'
        if not q:
            dit, lecture = r['dit'] or QUESTION_SANS_TEXTE, 'introuvable'
            q = {'titre': f"Q{n} · {dit[:1].upper()}{dit[1:]}", 'suite': '',
                 'detail': f"Question introuvable dans la session ; son dernier message disait : « {r['phrase']} »"}
        lignes.append({'titre': q['titre'], 'suite': q['suite'], 'depuis': q.get('depuis') or s['depuis'], 'num': n,
                       'lecture': lecture, 'rappel_phrase': True})
        if q.get('detail'):
            lignes[-1]['detail'] = q['detail']
    for l in lignes:
        l['type'] = type_demande(l['titre'] + ' ' + l['suite'])
    # Un rappel sans numéro (« Encore ouvert : l'étape 3, en attente de ta réponse dans l'encadré », 2026-10-16) : la
    # question de la dernière boîte restée sans réponse (encadre_ouvert), comme une ligne de menu en attente ; sans
    # boîte, la phrase de repli quand le tri aurait gardé le rappel. Jamais la phrase du rappel comme question. Dans un
    # message qui porte lui-même des questions numérotées, le rappel renvoie à elles : pas de ligne de repli à part
    # (contrôle des lignes du 2026-10-20).
    if rappel_sans_numero(texte):
        boite = s.get('encadre')
        m = QUESTION_TITREE.match(boite['menu'][0]['question']) if boite else None
        if boite and not (m and int(m.group(1)) in vus):
            lignes.append(ligne_menu(boite['menu'], boite.get('depuis') or s['depuis']))
        elif not boite and not any(l['num'] for l in lignes) and debut_section(s.get('tete') or '') == 'ouvert':
            lignes.append({'titre': '', 'suite': QUESTION_SANS_TEXTE, 'detail': question_introuvable(texte),
                           'depuis': s['depuis'], 'num': None, 'type': type_demande(QUESTION_SANS_TEXTE),
                           'lecture': 'introuvable'})
    # Un message hors format dont seule une phrase rappelle des questions : sa phrase d'action la plus forte garde sa
    # ligne si ce n'est pas ce rappel (« Colle le script pour que je continue », ou « Il reste à toi : » devant une
    # liste où une autre demande côtoie les numéros).
    # Des questions numérotées « À trancher » ou « Encore ouvert » : la session a dit ce qu'elle attend. Des numéros
    # rappelés dans une phrase seulement : une autre demande du message garde sa ligne « Vérifier » plus bas.
    if lignes and not all(l.get('rappel_phrase') for l in lignes) or toutes_faites and not lignes:
        return sorted(lignes, key=lambda l: l.get('num') or 0)
    # « Rien à faire de ton côté » (format du PM, dans toutes ses sessions) : hors questions numérotées et hors geste
    # avec un bloc à coller (que le tri garde malgré la formule), aucune ligne.
    if rien_a_faire(texte, generique=True) and s.get('prio') is None:
        return sorted(lignes, key=lambda l: l.get('num') or 0)
    # Un fil 📬 reçoit des nouvelles (des comptes rendus) : seule une question « À trancher » y fait une ligne.
    if (s.get('titre') or '').lstrip().startswith('📬'):
        return []
    # Ni question numérotée, ni « Rien à faire de ton côté » : Mon Studio ne devine plus la demande dans le texte libre
    # (des lignes inventées ou périmées, comme « COPIL · init » qui relayait une
    # autorisation déjà donnée ailleurs), mais il n'oublie pas la session. Une demande probable sans numéro : une ligne
    # « Vérifier », sa phrase en titre, jamais un « Go ». Aucune demande probable : une ligne « Vérifier » tant que le
    # PM n'a pas lu le message, puis rien. Un rappel à chaque message du PM (hook UserPromptSubmit du plugin) demande
    # aux sessions de finir par leurs questions numérotées ou par « Rien à faire de ton côté ».
    tete = nettoyer(s.get('tete') or '')
    rappel = any(r['source'] and r['source'] in tete for r in en_phrase.values())
    proche = s.get('tete') if (s.get('prio') in (1, 2, 3, 4, 5) and tete and not rappel) else ''
    # A sentence that waits for nothing (PM, 2026-11-18: « L'inventaire des ateliers est rendu… », « … est chez
    # <session>, qui travaille ») is information: no line. Kept as soon as it asks the PM anything (demande_au_pm); a
    # question (2), a gesture (4: a box to tick, an imperative) or a proposal (5) always keeps it.
    if proche and s.get('prio') in (1, 3) and not demande_au_pm(proche):
        proche = ''
    if proche:
        # Le titre est la phrase, mot pour mot ; le détail porte aussi le bloc auquel elle renvoie (detail_de_phrase).
        # Une phrase qui dit qu'une autre session attend le PM garde les sessions désignées (renvois_au_tableau).
        autour = autour_de_la_phrase(texte, proche)
        lignes.append({'titre': '', 'suite': nettoyer(proche).rstrip(' :'), 'depuis': s['depuis'],
                       'detail': detail_de_phrase(texte, proche, autour), 'declencheur': NON_DECLAREE, 'type': 'check',
                       'lecture': 'a_verifier', 'renvoie_a': (autour or {}).get('renvoie_a') or [],
                       'renvoie_titres': (autour or {}).get('renvoie_titres') or []})
        return sorted(lignes, key=lambda l: l.get('num') or 0)
    if lignes:
        return sorted(lignes, key=lambda l: l.get('num') or 0)   # seulement des numéros rappelés : c'est déclaré
    if not s.get('non_lue'):
        return []   # aucune demande probable, et le PM a lu le message (pastille bleue partie) : il l'a vu
    debut = nettoyer(couper(premiere_phrase(texte), LIBELLE_MAX)) if texte.strip() else ''
    lignes.append({'titre': '', 'suite': A_VERIFIER_SUITE, 'depuis': s['depuis'], 'type': 'check', 'lecture': 'a_verifier',
                   'declencheur': NON_DECLAREE,
                   'detail': f"Son dernier message commence par : « {debut} »" if debut else "Son dernier message n'a pas de texte."})
    return lignes


# What a line unfolds to (PM, 2026-11-06: tired of opening sessions to understand): short bullets saying what is
# expected of him, nothing else. The open numbered questions of the session (« Qn · titre », its options in a few
# words), then the sentences of its last message that ask him something; else its last sentence. Never the copied
# block around the sentence (« Juste avant, son message disait… »), never the trigger that only explains Mon Studio.
DEMANDE_AU_PM = re.compile(
    r"(?i)\bj['’]attends\b|\bj['’]ai\s+besoin\b|\bil\s+me\s+faut\b"
    r"|\b(?:donne|dis|envoie|indique|montre|transmets|colle|passe|confirme)[- ]moi\b"
    r"|(?:^|[,;]\s+)(?:valide|choisis|tranche|confirme|précise|décide|relis|réponds|envoie|donne|indique|colle|lance"
    r"|ouvre|relance|vérifie|regarde)\b"
    r"|\bà\s+toi\s+de\b|\b(?:ton|tes)\s+(?:go|feu\s+vert|accord|retours?|avis|ajouts?)\b"
    r"|\bta\s+(?:réponse|validation|décision)\b|\bpeux[- ]tu\b|\btu\s+(?:peux|dois)\b|\bil\s+te\s+(?:faut|reste)\b")
NUMERO_CITE = re.compile(r"\bQ\d{1,3}\b")


def demande_au_pm(phrase):
    """True when a sentence asks the PM something: a question, words addressed to him (« tu », « ton go »), a
    request (DEMANDE_AU_PM), an imperative, an invitation, a gesture to do (« à relire »), a marker of his glossary or
    a proposal awaiting his yes. False for plain information (« X est rendu », « Y est chez <session> »)."""
    p = sans_citations(nettoyer(phrase or ''))
    n = nu(p)
    return bool('?' in p or re.search(DEUXIEME, n, re.I) or DEMANDE_AU_PM.search(p) or imperatif(n) or INVITE.match(n)
                or A_INFINITIF.search(n) or PROPOSE.search(n) or marqueur_demande(p)
                or re.search(r"(?i)\bfeux?\s+verts?\b|[«\"`]\s*go\s*[»\"`]", p))
PUCES_MAX, PUCE_MAX = 6, 140


def puce_de_question(titre, suite, brut=''):
    """One bullet for a numbered question: its title, then its options in a few words, else the start of its text."""
    options = options_libelles(brut or f"{titre} {suite}")
    if options:
        return couper(f"{titre} : " + ' / '.join(couper(o, 40) for o in options), PUCE_MAX)
    return couper(f"{titre} : {suite}" if suite else titre, PUCE_MAX)


# What a numbered line unfolds to (0.2.17): its own question, never the bullets of its whole session (a Q7 used to
# unfold to Q1 to Q6). The PM decides from the board: the whole statement, its options, the one the session
# recommends, the files it cites (read in the page, « Lire »). The app opens a session at its start, never on a message.
FICHIERS_MAX = 5
EXT_FICHIER = r"(?:md|txt|csv|pdf|docx|xlsx|pptx|html)"
FICHIER_CITE = re.compile(r"`([^`\s]+\." + EXT_FICHIER + r")`|\]\(<?([^)\s>]+\." + EXT_FICHIER + r")>?\)"
                          r"|(?<![\w/.~`])((?:[\w.-]+/)+[\w.-]+\." + EXT_FICHIER + r")(?![\w/])", re.I)
PREMIERE_OPTION = re.compile(r'(?:^|\s)1\s*[.)]\s+(?=\S)')


def fichiers_cites(texte, dossier):
    """The files a question cites, relative to its Studio: a relative path without `..`, or an absolute one inside the
    Studio's folder. Anything else (outside the Studio, ~/…, a URL) is not offered."""
    base = os.path.normpath(dossier or '')
    sortie = []
    for m in FICHIER_CITE.finditer(str(texte or '')):
        c = next(g for g in m.groups() if g)
        if re.match(r'^[a-z]+://', c, re.I) or c.startswith('~'):
            continue
        if os.path.isabs(c):
            if not dossier or not os.path.normpath(c).startswith(base.rstrip(os.sep) + os.sep):
                continue
            c = os.path.relpath(os.path.normpath(c), base)
        if '..' not in pathlib.PurePosixPath(c).parts and c not in sortie:
            sortie.append(c)
    return sortie[:FICHIERS_MAX]


# The card of a session's question (PM, 2026-11-17): Pourquoi · Ce qu'on attend de toi · Si tu ne fais rien ·
# Recommandation · Pièce. Read from the labels the question writes itself (regles/format-reponses.md asks for them),
# never guessed; a rubric the question does not write stays empty and the page does not show it.
RUBRIQUES_FICHE = (('pourquoi', r"pourquoi|enjeu|why"),
             ('attendu', r"ce qu['’]on attend de toi|ce que j['’]attends de toi|ce qu['’]il te faut faire|what I need from you"),
             ('sinon', r"si tu ne fais rien|sans r[ée]ponse de ta part|sinon|if you do nothing"),
             ('reco', r"recommandations?|recommand[ée]e?s?|je (?:te )?propose|ma proposition|proposition"),
             ('piece', r"pi[èe]ces?(?: jointes?)?|à lire"))
RUBRIQUE = re.compile(r"(?i)(?:^|(?<=[\s.;(·—-]))(" + '|'.join(f"(?P<{k}>{m})" for k, m in RUBRIQUES_FICHE) + r")\s*:\s*")


def rubriques(texte):
    """({rubric: text}, the text before the first label) of a question that writes « Pourquoi : … », « Si tu ne fais
    rien : … »… Each rubric runs to the next label, stripped of its trailing punctuation."""
    texte = ' '.join(str(texte or '').split())
    marques = list(RUBRIQUE.finditer(texte))
    sortie = {}
    for i, m in enumerate(marques):
        fin = marques[i + 1].start() if i + 1 < len(marques) else len(texte)
        nom = next(k for k, _ in RUBRIQUES_FICHE if m.group(k))
        val = texte[m.end():fin].strip(' ;,·—-')
        if val and nom not in sortie:
            sortie[nom] = val
    return sortie, (texte[:marques[0].start()].rstrip(' :;,·—-') if marques else texte)


def depli_de_question(titre, suite, brut='', dossier=''):
    """{enonce, options: [{libelle, recommande}], recommande, pourquoi, attendu, sinon, fichiers} of a numbered
    question: the statement before its numbered options and its labelled rubrics, whole, without « (recommandé) »; the
    options and the recommendation as the question writes them (options_libelles, recommandation: never guessed)."""
    complet = (titre + (' : ' if titre and suite else '') + (suite or '')).strip()
    source = brut or complet
    libelles = options_libelles(source)
    reco = recommandation(source)
    parts, avant = rubriques(complet)
    enonce = avant or complet
    if libelles:
        m = PREMIERE_OPTION.search(enonce)
        enonce = enonce[:m.start()].rstrip(' :') if m and m.start() > len(titre) else enonce
    # Never « : . » nor « : , » (what a cut left before the punctuation, revue du 2026-11-17).
    enonce = re.sub(r'\s*:\s*[.,](?=\s)', ' :', ' '.join(RECOMMANDE.sub('', enonce).split()))
    options = [{'libelle': o, 'recommande': bool(reco) and (nu(o) == nu(reco) or nu(reco).startswith(nu(o)))}
               for o in libelles]
    # The options in full (PM, 2026-11-18: the click shows the real question in full precision), the label of each.
    entieres = options_entieres(source)
    if len(entieres) == len(options):
        for o, e in zip(options, entieres):
            o.update(entiere=e['texte'], gras=e['gras'])
            o['recommande'] = o['recommande'] or e['recommande']
    if not parts and brut:
        parts = rubriques(brut)[0]
    # The precise question: the text after the title, before the options and the rubrics (never the title twice).
    question = ' '.join(str(brut or complet).split())
    premiere = next((m for m in OPTION_LIBELLE.finditer(question) if m.group(1) == '1'), None)
    if entieres and premiere:
        question = question[:premiere.start()]
    question = rubriques(question)[1]
    m = QUESTION_TITREE.match(question.strip())
    question = question_titree(m)['suite'] if m else nettoyer(question)
    if titre and not m and nu(question).startswith(nu(titre)):
        question = question[len(titre):] if question.startswith(titre) else question
    question = re.sub(r'(?i)(?:^|\s)(?:les\s+)?(?:options?|choix)\s*:?\s*$', '', ' '.join(RECOMMANDE.sub('', question).split()))
    question = question.strip(' :·—-')
    return {'enonce': enonce, 'question': question, 'options': options, 'recommande': reco,
            'pourquoi': parts.get('pourquoi', ''), 'attendu': parts.get('attendu', ''), 'sinon': parts.get('sinon', ''),
            'fichiers': fichiers_cites(f"{brut or ''} {complet}", dossier)}


def phrases_du_message(texte):
    """[(sentence, list items that follow it)] of a message, in order, outside code blocks, tables and titles, without
    markdown decoration. A sentence that ends a block with « : » carries the items of the list right after it."""
    blocs, sortie = blocs_du_message(texte), []
    for i, (genre, lignes) in enumerate(blocs):
        if genre == 'texte':
            phrases = couper_phrases(nettoyer(' '.join(l.strip() for l in lignes if not l.strip().startswith('>'))))
        elif genre == 'liste':
            phrases = [p for l in lignes if PUCE.match(l) for p in couper_phrases(nettoyer(l))]
        else:
            continue
        for k, ph in enumerate(phrases):
            suite = []
            if k == len(phrases) - 1 and ph.rstrip().endswith(':') and i + 1 < len(blocs) and blocs[i + 1][0] == 'liste':
                suite = [nettoyer(l) for l in blocs[i + 1][1] if PUCE.match(l)]
            sortie.append((ph, suite))
    return sortie


def ce_qu_attend(s):
    """The bullets a session's line unfolds to (see DEMANDE_AU_PM): at most PUCES_MAX, each cut at PUCE_MAX."""
    texte = s.get('texte') or ''
    hist = s.get('questions') or {}
    items, ouverts = a_trancher(texte)
    faites = set(s.get('faites') or [])
    items = [it for it in items if it['num'] not in faites]
    puces, vus, couverts = [], set(faites), []
    for it in items:
        if it['num'] and it['num'] in vus:
            continue
        vus.add(it['num'])
        couverts.append(nu(f"{it['titre']} {it['suite']}"))
        puces.append(puce_de_question(it['titre'], it['suite'], it.get('brut')) if it['num'] else couper(it['suite'], PUCE_MAX))
    rappels, en_phrase = encore_ouvert(texte), rappels_en_phrase(texte)
    for n in list(ouverts) + list(en_phrase):
        if n in vus:
            continue
        vus.add(n)
        q = hist.get(str(n))
        if q:
            couverts.append(nu(f"{q['titre']} {q.get('suite') or ''}"))
            puces.append(puce_de_question(q['titre'], q.get('suite') or ''))
        else:
            dit = rappels.get(n) or (en_phrase.get(n) or {}).get('dit') or QUESTION_SANS_TEXTE
            puces.append(couper(f"Q{n} · {dit[:1].upper()}{dit[1:]}", PUCE_MAX))
    tete = nettoyer(s.get('tete') or '').rstrip(' :')
    phrases = phrases_du_message(texte)
    for ph, liste in phrases:
        if NUMERO_CITE.search(ph) or NEGATION.search(ph) or QUESTION_TITREE.match(ph) \
                or any(nu(ph.rstrip(' :')) in c for c in couverts):
            continue
        demande = DEMANDE_AU_PM.search(ph) or (tete and nu(tete) in nu(ph))
        if demande and liste:
            puces += [couper(x, PUCE_MAX) for x in liste if not NUMERO_CITE.search(x)]
        elif demande and not ph.rstrip().endswith(':'):
            puces.append(couper(ph, PUCE_MAX))
    puces = list(dict.fromkeys(p for p in puces if p))[:PUCES_MAX]
    if not puces:
        derniere = tete or next((ph for ph, _ in reversed(phrases) if not NEGATION.search(ph)), '')
        puces = [couper(derniere, PUCE_MAX)] if derniere else []
    return puces


NON_DECLAREE = ("La session n'a ni numéroté de question ni écrit « Rien à faire de ton côté » : Mon Studio ne devine pas "
                "si elle attend quelque chose, regarde dans la session.")
A_VERIFIER_SUITE = "Ne dit pas si elle attend quelque chose de toi"


def premiere_phrase(texte):
    """La première phrase d'un message, sans titre ni décor markdown."""
    for ligne in (texte or '').split('\n'):
        brut = re.sub(r"^[\s#>*_\-•·]+", '', ligne).strip()
        if brut:
            phrases = couper_phrases(brut)
            return phrases[0] if phrases else brut
    return ''


def tableau(sessions, metas, autos, jours, maintenant, cache=None, fermees=None):
    """Les lignes fraîches du tableau (lignes_et_anciennes), sans les anciennes."""
    return lignes_et_anciennes(sessions, metas, autos, jours, maintenant, cache, fermees)[0]


# Le geste « ouvre une nouvelle session sur <dossier> » est fait quand l'app montre une session ouverte dans ce dossier
# (ou dedans) après la question (PM, 2026-11-10 : la Q12 restait au tableau, la session demandée tournait depuis la
# veille). Strict : un chemin écrit dans la question (« ~/… », « /Users/… »), sinon le nom d'un Studio connu de
# projets.json, seul de son espèce dans la phrase ; jamais une devinette. Ne comptent ni une tâche planifiée, ni la
# session qui demande.
GESTE_SESSION = re.compile(r"(?i)\b(?:nouvelle\s+session|(?:ouvre|ouvrir|rouvre|lance|lancer|démarre|démarrer|crée|créer)"
                           r"\s+une\s+(?:nouvelle\s+)?session)\b")
CHEMIN_GESTE = re.compile(r"(?<![\w/~])(~/[^\s`«»\"'’,;()]*|/(?:Users|home|Volumes|private)/[^\s`«»\"'’,;()]*)")
# Un chemin entre backticks, guillemets ou chevrons garde ses espaces (« ~/Mon Studio/… », « …/Drive partagés/… »).
CHEMIN_CITE = re.compile(r"[`\"«]\s*(~/[^`\"»\n]+?|/(?:Users|home|Volumes|private)/[^`\"»\n]+?)\s*[`\"»]")
GESTE_NIE = re.compile(r"(?i)\b(?:ne|n['’])\s*(?:\w+\s+){0,2}(?:pas|plus|jamais)\b")
FENETRE_GESTE = 160   # caractères après le geste où chercher le dossier


def dossier_du_geste(texte, studios=()):
    """Le dossier où la question demande d'ouvrir une nouvelle session (GESTE_SESSION), ou None."""
    m = GESTE_SESSION.search(texte or '')
    if not m:
        return None
    if GESTE_NIE.search(texte[max(0, m.start() - 30):m.end()]):
        return None   # « ne lance pas une nouvelle session dans … »
    fenetre = texte[m.start():m.end() + FENETRE_GESTE]
    for c in (CHEMIN_CITE.search(fenetre), CHEMIN_GESTE.search(fenetre)):
        if not c:
            continue
        d = c.group(1).rstrip('.:/*_ ')
        d = os.path.normpath(str(HOME) + d[1:] if d.startswith('~') else d)
        if c.re is CHEMIN_CITE or os.path.isdir(d) or not studios:
            return d
        break   # un chemin sans guillemets coupé à sa première espace : le nom du Studio, plus bas
    noms = {d for d in studios if nom_projet(d) and re.search(r"(?i)(?<!\w)" + re.escape(nom_projet(d)) + r"(?!\w)", fenetre)}
    return noms.pop() if len(noms) == 1 else None


def session_ouverte_dans(dossier, apres, metas, sauf=()):
    """La première session de l'app ouverte dans « dossier » (ou dedans) après « apres », hors tâches planifiées et
    hors « sauf » ; archivée ou non (elle a été ouverte). None sinon."""
    for m in sorted(metas, key=lambda m: m.get('creee') or 0):
        if m.get('tache') or not m.get('id') or m['id'] in sauf:
            continue
        if (m.get('creee') or 0) > apres and dans_un_dossier(m.get('cwd'), [dossier]):
            return m
    return None


def preuve_du_geste(texte, depuis, metas, studios, sauf=()):
    """« réglé : session ouverte dans <dossier> » quand la question demande d'ouvrir une session et que l'app la montre
    ouverte depuis (session_ouverte_dans) ; None sinon."""
    dossier = dossier_du_geste(texte, studios)
    m = session_ouverte_dans(dossier, depuis, metas, sauf) if dossier and depuis else None
    if not m:
        return None
    court = '~' + dossier[len(str(HOME)):] if dossier.startswith(str(HOME) + os.sep) else dossier
    return {'preuve': f"réglé : session ouverte dans {court}", 'ouverte': m['id'], 'ouverte_titre': m.get('titre') or '',
            'quand': m.get('creee') or 0}


A_CONFIRMER_TEXTE = ("Tu as écrit à la session après la question et elle s'est mise au travail. Ce n'est pas toujours "
                     "la réponse : confirme, ou garde la ligne ouverte.")   # les mots du tableau du chantier
RANG_A_CONFIRMER = 5   # une ligne « à confirmer » passe sous les lignes ouvertes de son Studio, comme au tableau
RANG_PROCHE, RANG_ATTEND, RANG_OUVERTE = 0, 1, 2
ATTEND_DEVANT_S = 86400   # « une session attend » puts a line in front for 24 h after it appeared


# Impact and effort (PM, 2026-11-17: « ce qui est très impactant et très peu coûteux en premier »). Each line of the
# board carries `impact` (fort, normal, faible), `raison` (a few words shown on the line) and `effort` (court, long or
# ''). No model here: whoever writes the line may label it once, in its own text, and plain rules stand in otherwise.
#   label, anywhere in a request of the ingestion or in a question: « (impact fort : client attend) », « (impact faible) »,
#   « (effort court) ». « fort » needs a reason of the closed list below, else the line is « normal »: every session
#   finds its own question important.
IMPACTS, EFFORTS = ('fort', 'normal', 'faible'), ('court', 'long')
RAISONS = ('client attend', 'échéance', "bloque l'équipe", 'argent ou contrat', 'sécurité')
ETIQUETTE_IMPACT = re.compile(r"\s*\(impact\s+(fort|normal|faible)(?:\s*:\s*([^()]{1,60}?))?\s*\)", re.I)
ETIQUETTE_EFFORT = re.compile(r"\s*\(effort\s+(court|long)\)", re.I)
EN_RETARD, SECURITE, BLOQUE, URGENT, RANGEMENT = 'en retard', 'sécurité', 'bloqué', 'urgent', 'rangement'
MOT_SECURITE = re.compile(r"(?i)\ben clair\b")
MOT_BLOQUE = re.compile(r"(?i)(?<!non )(?<!pas )\bbloqu(?:ée?s?|ante?s?)\b")
MOT_URGENT = re.compile(r"(?i)\bsans délai\b|\burgent(?:e|es|s)?\b")
MOT_ARCHIVAGE = re.compile(r"(?i)\barchiv(?:er|age|e)\b[^.:;]{0,40}\bsession\b|\bj['’]archive\b")
QUELQU_UN_ATTEND = re.compile(r"^((?:[A-ZÀ-Ý][\w’'-]+)(?:\s+[A-ZÀ-Ý][\w’'-]+)?(?:\s+et\s+[A-ZÀ-Ý][\w’'-]+(?:\s+[A-ZÀ-Ý][\w’'-]+)?)?)"
                              r"\s+(?:te\s+demande(?:nt)?|demande(?:nt)?|attend(?:ent)?)\b")
EFFORT_COURT = ('go', 'clic')


def etiquettes(texte):
    """(the text without its labels, {'impact', 'raison', 'effort'}): what the writer of a line said of it. Missing
    labels are absent from the dict. « fort » without a reason of RAISONS is read « normal »."""
    s, dit = str(texte or ''), {}
    m = ETIQUETTE_IMPACT.search(s)
    if m:
        impact, raison = m.group(1).lower(), ' '.join((m.group(2) or '').lower().split())
        raison = raison.replace('’', "'")
        if impact == 'fort' and raison not in RAISONS:
            impact, raison = 'normal', ''
        dit.update(impact=impact, raison=raison if impact == 'fort' else '')
        s = ETIQUETTE_IMPACT.sub('', s)
    m = ETIQUETTE_EFFORT.search(s)
    if m:
        dit['effort'] = m.group(1).lower()
        s = ETIQUETTE_EFFORT.sub('', s)
    return (s.strip() if dit else s), dit


def priorite(texte, maintenant, dit=None, echeance=None, proche=False, bloque=False, arret=None, type_=None,
             choix=None, demande=False):
    """{'impact', 'raison', 'effort'} of a line. What its writer said (`dit`, from etiquettes) comes first; else the
    rules: a deadline close or passed, a session that waits or stopped, a word that says so (« bloqué », « en clair »,
    « sans délai ») make it « fort »; for a request of the ingestion (`demande`), a person who asks or waits too;
    « archiver cette session » makes it « faible ». The effort is « court » when the board answers it in one click.
    `echeance`: a timestamp in seconds or None. `raison` is '' when the line already says it (date, « une session
    attend »)."""
    dit = dit or {}
    t = ' '.join(str(texte or '').split())
    effort = dit.get('effort') or ('court' if choix or type_ in EFFORT_COURT else '')
    if dit.get('impact'):
        return {'impact': dit['impact'], 'raison': dit.get('raison') or '', 'effort': effort}
    retard = bool(echeance) and dt.date.fromtimestamp(echeance) < dt.date.fromtimestamp(maintenant)
    if MOT_ARCHIVAGE.search(t) and not demande:
        return {'impact': 'faible', 'raison': RANGEMENT, 'effort': effort}
    for vrai, raison in ((retard, EN_RETARD), (proche or bloque or bool(arret), ''), (MOT_SECURITE.search(t), SECURITE),
                         (MOT_URGENT.search(t), URGENT), (MOT_BLOQUE.search(t), BLOQUE)):
        if vrai:
            return {'impact': 'fort', 'raison': raison, 'effort': effort}
    m = QUELQU_UN_ATTEND.match(t) if demande else None
    if m:
        return {'impact': 'fort', 'raison': f"{m.group(1)} attend", 'effort': effort}
    return {'impact': 'normal', 'raison': '', 'effort': effort}


def rang_urgence(l, maintenant):
    """The rank of a line within its Studio: close deadline, then a session blocked for less
    than 24 h, then every other open line; « à confirmer » last. A tuple, compared as such."""
    if l.get('reglee'):
        return (RANG_A_CONFIRMER,)
    if l.get('proche'):
        return (RANG_PROCHE,)
    if l.get('bloque') and maintenant - (l.get('depuis') or 0) < ATTEND_DEVANT_S:
        return (RANG_ATTEND,)
    return (RANG_OUVERTE,)


def ligne_de_tache(a, par_id, couloirs, vise, jours, maintenant):
    """[the line] of a scheduled task whose last pass waits for the PM (automates), or []: in the Studio of the task's
    folder, the pass's session in the Session column, which its button opens (PM, 2026-11-10: the app only shows a dot
    on « Tâches planifiées », one had to open each task to find the one that waits).
    - a question (end-of-turn card, menu): its words, and its options as answer buttons when they are one question with
      plain labels; the answer sent is the label, as the app's own button would;
    - an authorization (pending, or refused and the turn cut) or a cut turn: « <task> : arrêtée sur une autorisation
      (Bash) », the pending one in « En un clic » when the page can give it;
    - an error: its reason in a few words.
    The line has no number of its own and closes by itself when the next pass goes well (only the last pass counts)."""
    if not a.get('lien') or a['lien'] in vise or not (a.get('carte') or a.get('arret')):
        return []
    titre = (par_id.get(a['lien']) or {}).get('titre') or a['nom']   # the pass's session, that the button opens
    studio = nom_projet(a['cwd']) if a.get('cwd') else None
    base = {'studio': studio or 'Automates', 'session': titre_lien(titre, studio),
            'lien': lien_app(a['lien']), 'ouvrir': a['lien'], 'cle': a['lien'], 'non_lue': False,
            'a_numeroter': couloirs.get(a['lien']) or '', 'tache': a['nom']}
    if a.get('carte'):
        depuis = a['carte'].get('depuis') or a['ts']
        d = ligne_menu(a['carte']['menu'], depuis)
        d.update(lecture='native', bloque=False, native=True)
        choix = choix_de_carte(a['carte']['menu'])
        if choix:
            d.update(choix=choix, seule=True, question='')
        return [dict(base, **d, ancienne=maintenant - depuis > jours * 86400)]
    arret, depuis = a['arret'], a['arret'].get('depuis') or a['ts']
    # The task's name leads the text, unless the Session column already says it.
    tete = '' if nu(a['nom']).lower() == nu(base['session']).lower() else f"{a['nom']} : "
    texte = tete + libelle_arret(arret)
    d = {'titre': '', 'suite': texte[:1].upper() + texte[1:], 'depuis': depuis, 'type': 'task', 'verbe': 'Ouvrir',
         'lecture': 'auto', 'arret': arret['quoi'] if arret['quoi'] in ('authorization', 'error') else 'interrupted',
         'ancienne': maintenant - depuis > jours * 86400}
    if arret['quoi'] == 'authorization':
        d.update(bloque=True, extrait=extrait_lisible(arret.get('extrait')))
    if arret.get('extrait'):   # what the pass wanted to do, for the unfold (a cache of an older version kept the raw name)
        d['detail'] = f"Ce que le passage voulait faire : {extrait_lisible(arret['extrait'])}"
    # A pass stopped on its way leads the board (PM, 2026-11-17: the app marks it « réussie », nobody sees it).
    d['en_tete'] = True
    return [dict(base, **d)]


MATIN_TACHE = 'point-du-matin'
RELANCER_MATIN = "À relancer depuis « Planifiées »."   # the scheduled task that writes ~/Mon Studio/matin.json (matin.py)


def heure_courte(ts):
    """« 8 h 26 », « 7 h » : an hour as the PM says it."""
    d = dt.datetime.fromtimestamp(ts)
    return f"{d.hour} h {d.minute:02d}" if d.minute else f"{d.hour} h"


def ligne_du_matin(retard, lignes, autos, par_id, couloirs, maintenant):
    """The morning point has not written today's file (matin.retard): one line at the head of the board, that says why
    when its last pass says it, and opens that pass. The line of the task's stopped pass, when there is one, becomes this
    line (one line, not two). No pass at all: no line, Today says it."""
    a = next((x for x in autos if x.get('id') == MATIN_TACHE and x.get('lien')), None)
    if not a:
        return lignes
    du_jour = dt.date.fromtimestamp(a['ts']) == dt.date.fromtimestamp(maintenant)
    arret = a.get('arret') if du_jour else None
    if arret:
        quand_ = f" à {heure_courte(arret['depuis'])}" if arret.get('depuis') else ''
        outil = f" ({nom_outil(arret['outil'])})" if arret.get('outil') else ''
        pourquoi = {'authorization': f"arrêté{quand_} : il attend ton autorisation{outil}",
                    'refused': f"arrêté{quand_} sur une autorisation{outil}",
                    'error': f"arrêté{quand_} sur une erreur" + (f" : {arret['raison']}" if arret.get('raison') else '')
                    }.get(arret['quoi'], f"arrêté{quand_} en plein travail{outil}")
    elif du_jour and a.get('detail') == 'en cours':
        pourquoi = f"son passage de {heure_courte(a['ts'])} est encore en cours"
    elif du_jour:
        pourquoi = f"son passage de {heure_courte(a['ts'])} a fini sans écrire le point"
    else:
        pourquoi = 'à lancer dans « Planifiées »'
    texte = f"{retard} : {pourquoi}"
    for l in lignes:
        if l.get('tache') and l.get('cle') == a['lien']:
            l.update(titre='', suite=texte, en_tete=True, ancienne=False,
                     detail=' '.join(x for x in (l.get('detail') or '', RELANCER_MATIN) if x))
            return lignes
    titre = (par_id.get(a['lien']) or {}).get('titre') or a['nom']
    studio = nom_projet(a['cwd']) if a.get('cwd') else None
    return lignes + [{'studio': studio or 'Automates', 'session': titre_lien(titre, studio), 'lien': lien_app(a['lien']),
                      'ouvrir': a['lien'], 'cle': a['lien'], 'non_lue': False, 'a_numeroter': couloirs.get(a['lien']) or '',
                      'tache': a['nom'], 'titre': '', 'suite': texte, 'depuis': a['ts'], 'type': 'task', 'verbe': 'Ouvrir',
                      'lecture': 'auto', 'arret': 'interrupted', 'bloque': False, 'ancienne': False, 'en_tete': True,
                      'detail': RELANCER_MATIN}]


def lignes_et_anciennes(sessions, metas, autos, jours, maintenant, cache=None, fermees=None):
    """(fraîches, anciennes) : les lignes du tableau, et à part les demandes d'une session lue dont le dernier message
    a plus de « jours » jours (either done and not updated, or missing and still to handle, but at another level than fresh actions). They never leave the screen silently. Les anciennes ne comptent pas avec les fraîches."""
    par_id = {m['id']: m for m in metas if m['id']}
    actifs = chantiers_actifs(metas)
    couloirs = couloirs_de(actifs, metas)
    tableau_du = au_tableau(actifs)
    # Les sessions qu'une attente d'un miroir vise déjà : leur ligne automatique (arrêtée en cours de tour, en erreur,
    # automate en échec) s'efface derrière celle du contremaître. Tant qu'aucune attente ne la vise, elle reste visible.
    # Une attente réglée dans sa session ne la vise plus : si la session s'arrête en travaillant sur la réponse, sa
    # ligne « Arrêtée en plein travail » se voit.
    suivi = suivis(sessions, actifs, cache)
    regle = {chef: {n: v[0] for n, v in nums.items() if v[0]} for chef, nums in suivi.items()}
    vise = {a.get('source') or a.get('sessionId') for c in actifs for a in c.get('attentes') or []
            if num_question(a.get('titre')) not in regle.get(c.get('sessionId'), {})} - {None, ''}
    menus = menus_ouverts(sessions)
    # Réglées sur preuve (preuve_du_geste) : elles quittent le tableau et sont dites dans « fermees » (une liste
    # fournie par l'appelant), avec leur preuve.
    fermees = fermees if fermees is not None else []
    studios = dossiers_de_l_instantane()

    def prouvee(d, texte, depuis, sid, **plus):
        f = preuve_du_geste(texte, depuis, metas, studios, {sid})
        if f:
            libelle = ' : '.join(x for x in (d.get('titre'), d.get('suite')) if x)
            fermees.append(dict(f, texte=couper(nettoyer(libelle), 200), depuis=depuis, **plus))
        return bool(f)
    # Une session d'un chantier garde ses lignes tant que le tableau ne les porte pas (deja_au_tableau) : le PM parle
    # aussi directement à ses fils rouges, et le contremaître ne passe pas assez souvent pour tout reprendre. Ces lignes
    # portent « a_numeroter » (la session du contremaître) : le tableau du chantier les montre en tête de « À faire ».
    # Dans un chantier, une session (hors contremaître, qui numérote au tableau) s'affiche sans ses propres numéros de
    # question : ils se confondent avec ceux du tableau (PM, 2026-10-15). Ailleurs, le PM répond « Q2 : … » dans la
    # session, d'après sa numérotation : le numéro reste.
    lignes = []
    for s in sessions:
        chef = couloirs.get(s['id']) or ''
        # Une session lue dont le dernier message a plus de « jours » jours : ses lignes vont dans « Anciennes ».
        groupe = {'studio': nom_projet(s['cwd']), 'session': titre_lien(s['titre'], nom_projet(s['cwd'])), 'lien': lien_app(s['id']),
                  'cle': s['id'], 'non_lue': s.get('non_lue'), 'a_numeroter': chef, 'dossier': s['cwd'],
                  'ancienne': not s.get('non_lue') and maintenant - s['derniere'] > jours * 86400}
        affiche = sans_numero_propre if chef and chef != s['id'] else dict
        if s['etat'] == 'suspens' and s.get('menu'):
            # Un menu de questions : la question et ses options en entier, comme une question de la session. Le tableau
            # du chantier la porte dès que le contremaître l'a reprise (même règle que les autres questions).
            d = ligne_menu(s['menu'], s['depuis'])
            if prouvee(d, d['titre'], d['depuis'], s['id'], studio=groupe['studio'], session=groupe['session'], cle=s['id']):
                pass
            elif not (chef and deja_au_tableau(d, s['id'], chef, tableau_du, s['depuis'])):
                lignes.append(dict(groupe, arret='menu', **affiche(d)))
        elif s['etat'] == 'suspens' and s['id'] not in vise:
            quoi = f" ({nom_outil(s['outil'])})" if s.get('outil') else ''
            # « arret » dit à la page et au tableau en Markdown de quel arrêt il s'agit, sans lire la phrase : un outil
            # attend l'accord du PM (authorization, avec l'extrait de ce qu'il ferait), ou la session s'est arrêtée
            # entre deux outils, sans rien demander (interrupted : app fermée, session coupée).
            attente = s.get('attente')
            lignes.append(dict(groupe, titre='', suite=f"Arrêtée en plein travail{quoi} : une autorisation à donner, ou la session à relancer",
                               depuis=s['depuis'], type='task', bloque=True, lecture='auto',
                               arret='authorization' if attente else 'interrupted',
                               **({'extrait': extrait_lisible(attente['extrait'])} if attente else {})))
        elif s['etat'] == 'erreur' and not (chef and s['id'] in vise):
            lignes.append(dict(groupe, titre='', suite='Arrêtée sur une erreur, à relancer : ' + (s.get('erreur') or '').strip(),
                               depuis=s['depuis'], type='task', lecture='auto', arret='error'))
        elif s['etat'] == 'attend':
            # Jamais deux lignes identiques pour une même session (two
            # unfindable reminders became two « Une question t'attend dans cette session » sans leur numéro).
            vues, puces = set(), ce_qu_attend(s)
            if affiche is sans_numero_propre:   # its own numbers would mix with the board's (PM, 2026-10-15)
                puces = [NUMERO_EN_TETE.sub('', x, count=1) for x in puces]
            for d in demandes(s):
                if prouvee(d, ' '.join(x for x in (d.get('titre'), d.get('suite'), d.get('brut')) if x), d['depuis'],
                           s['id'], studio=groupe['studio'], session=groupe['session'], cle=s['id'], num=d.get('num')):
                    continue
                if d.get('menu') or d.get('native'):
                    pass   # its detail is the whole menu question (detail_menu)
                elif d.get('num') is not None:
                    # A numbered line unfolds to its own question (0.2.17), never to the session's bullets; an
                    # unfindable one keeps its detail, which says so.
                    if d.get('lecture') != 'introuvable':
                        q = depli_de_question(d.get('titre') or '', d.get('suite') or '', d.get('brut') or '', s['cwd'])
                        if affiche is sans_numero_propre:   # the same rule as its title: no number of its own
                            q['enonce'] = NUMERO_EN_TETE.sub('', q['enonce'], count=1)
                        d = dict(d, depli=q)
                else:
                    d = dict(d, puces=puces)   # a line without number: what the session expects of the PM
                renvois_au_tableau(d, s['id'], chef, actifs, tableau_du, metas)
                if chef and deja_au_tableau(d, s['id'], chef, tableau_du, s['depuis']):
                    continue
                d = affiche(d)
                if (d['titre'], d['suite']) not in vues:
                    vues.add((d['titre'], d['suite']))
                    lignes.append(dict(groupe, **d))
    non_lue = {s['id']: bool(s.get('non_lue')) for s in sessions}
    for c in actifs:
        chef = par_id.get(c.get('sessionId')) or {}
        studio = nom_projet(chef['cwd']) if chef.get('cwd') else (c.get('studio') or '?')
        vocabulaire = c.get('vocabulaire') if isinstance(c.get('vocabulaire'), dict) else {}
        for a in c.get('attentes') or []:
            if not a.get('titre'):
                continue
            # Réglée dans sa session sur preuve forte (le PM a cité son numéro, ou répondu au menu qui la portait) : elle
            # quitte le tableau sans attendre le contremaître. Sans preuve forte, elle reste, « à confirmer » (a PM word on another subject must not make it leave).
            force = regle.get(c.get('sessionId'), {}).get(num_question(a['titre']))
            if force in QUITTE:
                continue
            # Sa session est archivée : la question part avec elle.
            if (par_id.get(a.get('sessionId') or '') or {}).get('archivee'):
                continue
            if prouvee(a, f"{a['titre']} {a.get('detail') or ''}", ts_iso(a.get('depuis')) or 0,
                       a.get('source') or a.get('sessionId') or '', studio=studio, session=str(a.get('sessionLabel') or ''),
                       cle=c.get('sessionId') or '', chantier=c.get('chantier'), num=num_question(a['titre'])):
                continue
            genre = a.get('type') if a.get('type') in TYPES else 'decision'
            # Posée ou reportée par sa session : l'heure la plus récente range la ligne ; rien depuis « jours » jours,
            # elle va dans « Anciennes ».
            pose = ts_iso(a.get('depuis')) or ts_iso(c.get('misAJour')) or maintenant
            reprise = max(pose, (suivi.get(c.get('sessionId'), {}).get(num_question(a['titre'])) or (None, None))[1] or 0)
            echeance = ts_iso(f"{a['echeance']}T23:59:00" if len(str(a.get('echeance'))) == 10 else a['echeance']) if a.get('echeance') else None
            # The verb leads to the session that asked the question, or where to act (PM, 2026-11-06, replacing the
            # rules of 2026-10-12 and 2026-10-20): the « source » of the wait, else the kit's main session; the
            # foreman only when neither exists (or it is archived, or it is the foreman). The direct answer buttons
            # answer that same session. « Voir la session » is gone: it would open the same session as the verb.
            chef_id = c.get('sessionId') or ''
            cible = chef_id
            nom = ((par_id.get(cible) or {}).get('titre') or c.get('session') or f"Chantier {c['chantier']}")
            src = session_qui_en_parle(a, cible, par_id)
            if src:
                cible, nom = src['id'], src['titre']
            # La session où vit le sujet : celle de « Voir la session », ou celle où mène le verbe s'il n'y en a pas
            # (« Relire », menu ouvert, sinon le contremaître). Le point bleu de la ligne la suit.
            vit, titre = (src['id'], src['titre']) if src else (cible, nom)
            # La colonne Session porte le sujet seul, comme la première colonne du tableau du chantier (PM, 2026-10-20 :
            # « Le cockpit est juste un niveau au-dessus ») : le couloir de l'attente (« ou »), que le Studio situe
            # déjà, sans « Chantier <nom> » ; il n'ouvre rien. Sans sujet (« Chantier » est ce que miroir.py écrit
            # faute de couloir), la session où vit le sujet, « Chantier <nom> » dessous, et son nom l'ouvre.
            sujet = str(a.get('ou') or '').strip()
            sujet = '' if sujet == 'Chantier' else sujet
            # Le texte finit comme au tableau du chantier, même règle et mêmes mots (todoItem) : « · à traiter dans la
            # session « <sessionLabel> » » quand la question a sa session au tableau et que ce n'est pas le
            # contremaître. Jamais déduit du couloir : le tableau ne le dit pas non plus.
            agir_dans = (titre_lien(str(a['sessionLabel'])) if a.get('sessionId') and a.get('sessionLabel')
                         and a['sessionId'] != c.get('sessionId') else '')
            lignes.append({'studio': studio, 'session': sujet or titre_lien(titre, studio), 'sujet': sujet, 'nommee': vit,
                           'dossier': chef.get('cwd') or '',
                           'detail': str(a.get('detail') or '').strip(), 'declencheur': str(a.get('declencheur') or '').strip(),
                           'agir_dans': agir_dans, 'sous': '' if sujet else f"Chantier {c['chantier']}",
                           'lien': lien_app(cible) if cible else (c.get('tableau') or ''), 'ouvrir': cible,
                           'cle': chef_id or 'chantier:' + c['chantier'], 'non_lue': non_lue.get(vit, False),
                           'titre': '', 'suite': nettoyer(a['titre']),
                           'depuis': ts_iso(a.get('depuis')) or ts_iso(c.get('misAJour')) or maintenant,
                           'type': genre, 'verbe': vocabulaire.get(genre) or TYPES[genre], 'echeance': echeance, 'entier': True,
                           'chantier': c['chantier'], 'num': num_question(a['titre']), 'attend': num_question(a.get('apres')),
                           'bloque': a.get('bloque') is True,
                           'source': src['id'] if src else '', 'source_titre': titre_lien(src['titre']) if src else '',
                           'question': f"Q{num_question(a['titre'])}" if num_question(a['titre']) is not None else '',
                           # The number goes to the clipboard only when it is the target session's own (it took it
                           # with question.py new), or when the verb opens the foreman, whose board it is.
                           'copie_numero': cible == chef_id or a.get('sessionId') == cible,
                           'choix': choix_fermes(genre, a.get('detail'), a.get('titre')) if num_question(a['titre']) is not None else None,
                           'reprise': reprise, 'ancienne': maintenant - reprise > jours * 86400,
                           # Sans preuve forte, une ligne ouverte ordinaire, sans mention (PM, 2026-10-20 : « ça fait
                           # tellement pas pro, manque de confiance ») : plus de « réglée dans la session, à confirmer ».
                           'lecture': 'inscrite', 'reglee': False})
    for a in autos:
        lignes += ligne_de_tache(a, par_id, couloirs, vise, jours, maintenant)
    retard = retard_du_matin(maintenant)
    if retard:
        lignes = ligne_du_matin(retard, lignes, autos, par_id, couloirs, maintenant)
    # Order: within a Studio, lines with a close deadline first
    # (soonest first), then the most recently asked or postponed. « Une session attend » (bloque) stays written on the
    # line but only puts it in front for 24 h after it appeared; then it takes its place by age (a 7-day-old blocked line
    # used to sit above questions of 4 minutes). « À confirmer » lines stay below the others. Studios: the one with the
    # most urgent line first, then the one with the newest. « En un clic » lines (authorizations, type « clic ») are
    # ranked the same way; the page and the Markdown take them out to the top.
    # A question without a number, the only line of its session, gets the same answer buttons as a numbered one (only
    # one under « À trancher », as the Stop hook reads it (question_seule).
    par_session = {}
    for l in lignes:
        if not l.get('chantier'):
            par_session[l['cle']] = par_session.get(l['cle'], 0) + 1
    # A numbered question a session asked itself (« Q3 · … »), chantier or not, gets its closed answers too (Q40,
    # 2026-11-09): « Q3 go », the session's own number. Several open in one session: each line answers its own.
    for l in lignes:
        if l.get('chantier') or l.get('question') or l.get('arret') or l.get('num') is None \
                or l.get('lecture') not in ('format', 'rappel') or not str(l.get('cle') or '').startswith('local_'):
            continue
        choix = choix_de_question(l.get('type'), l.get('titre'), l.get('suite'), l.get('brut') or l.get('detail'))
        if choix:
            l.update(question=f"Q{l['num']}", choix=choix)
    for l in lignes:
        if l.get('chantier') or l.get('question') or l.get('num') is not None or l.get('arret') \
                or l.get('lecture') != 'format' or par_session.get(l['cle']) != 1:
            continue
        choix = choix_sans_numero(l.get('type'), l.get('brut') or f"{l.get('titre') or ''} {l.get('suite') or ''}".strip())
        if choix:
            l.update(choix=choix, seule=True)
    # Worded buttons (PM, 2026-11-18): each numbered option shows its label, the recommended one first; the answer
    # sent stays its number.
    for l in lignes:
        if isinstance(l.get('choix'), list) and not l.get('seule'):
            source = l.get('brut') or (l.get('detail') if l.get('chantier') else '') \
                or f"{l.get('titre') or ''} {l.get('suite') or ''}"
            libelles, reco = boutons_options(source, l['choix'])
            if libelles:
                l['choix_libelles'] = libelles
                if reco:
                    l['choix_reco'] = reco
    # Lines the PM took off the board (« Fait / Retirer du tableau », PM 2026-11-17): gone until their session asks again
    # in other words. The session that asked is told once, at its next turn (hooks/retirees.py).
    retirees = cles_retirees()
    for l in lignes:
        l['retrait'] = cle_retrait(l)
    lignes = [l for l in lignes if not retiree(l, retirees)]
    classements = classements_du_pm()
    hors = {}   # a line outside any Studio (a code repository) comes after the Studios' own, in its band
    for i, l in enumerate(lignes):
        l['rang'] = i
        l.setdefault('ouvrir', l['cle'] if l['cle'].startswith('local_') else '')
        l.setdefault('verbe', TYPES[l['type']])
        l.setdefault('echeance', None)
        l['proche'] = echeance_proche(l['echeance'], maintenant)
        l['bloque'] = bool(l.get('bloque'))
        l['reglee'] = bool(l.get('reglee'))
        l['ancienne'] = bool(l.get('ancienne'))
        l['urgence'] = rang_urgence(l, maintenant)
        l['recente'] = max(l['depuis'], l.get('reprise') or 0)
        # What its writer said of it, taken out of the words shown; then the rules (priorite).
        dit = {}
        for champ in ('titre', 'suite', 'detail'):
            l[champ], vu = etiquettes(l.get(champ) or '')
            dit = {**vu, **dit}
        calcul = priorite(f"{l['titre']} {l['suite']}", maintenant, dit, l['echeance'], l['proche'], l['bloque'],
                          l.get('arret'), l['type'], l.get('choix'))
        l.update(calcul)
        # What the rules gave, kept for the PM's journal; his own order, when he set one, holds over it.
        l['calcul'] = dict(calcul, regle=regle_du_calcul(dit, calcul, l['proche'], l['bloque'], l.get('arret')))
        if l['retrait'] in classements:
            appliquer_classement(l, classements[l['retrait']])
        d = l.get('dossier') or ''
        if d not in hors:
            hors[d] = bool(d) and not est_un_studio(d)
        l['hors_studio'] = hors[d]
    fraiches = [l for l in lignes if not l['ancienne']]
    anciennes = [l for l in lignes if l['ancienne']]
    urgence_studio, recente_studio = {}, {}
    for l in fraiches:
        if l['studio'] not in urgence_studio or l['urgence'] < urgence_studio[l['studio']]:
            urgence_studio[l['studio']] = l['urgence']
    for l in fraiches:
        if l['urgence'] == urgence_studio[l['studio']]:
            recente_studio[l['studio']] = max(recente_studio.get(l['studio'], 0), l['recente'])
    for l in lignes:
        l['titre'], l['suite'] = sans_numero_repete(l['titre'], l['suite'])
        complet = (l['titre'] + (' : ' if l['titre'] and l['suite'] else '') + l['suite']).strip()
        l['complet'] = complet
        if l.get('menu'):
            # A card's question and its answers on one line, never two (PM, 2026-11-18): the question is cut, its
            # answers stay whole; the click shows the question in full.
            place = max(25, LIGNE_MAX - len(l['suite'] or '') - 3)
            l['affiche_titre'], l['affiche_suite'] = couper(l['titre'], place), l['suite']
            l['complet'] = l['detail']
        elif l.get('entier'):
            l['affiche_titre'], l['affiche_suite'] = '', couper(complet, LIGNE_MAX)
        elif l['titre'] and l.get('num') is not None and not l.get('chantier') \
                and format_court(l['titre'], l.get('brut') or complet):
            # Short titles (PM, 2026-11-18): « Qn · <title> » alone; the click shows the question in full.
            l['affiche_titre'], l['affiche_suite'] = couper(l['titre'], LIGNE_MAX), ''
        elif l['titre']:
            # An older question (its title a topic, the decision in its text): one line, never two (PM, 2026-11-18).
            place = LIGNE_MAX - len(l['titre']) - 3
            l['affiche_titre'] = couper(l['titre'], LIGNE_MAX)
            l['affiche_suite'] = couper(l['suite'], place) if l['suite'] and place >= 25 else ''
        elif l.get('renvoi') and ' · ' in l['suite'] and len(l['suite'].rsplit(' · ', 1)[1]) <= 40:
            # « … · Q21 au tableau Essai »: the questions it names stay on the line, the sentence is cut before them.
            tete, renvoi = l['suite'].rsplit(' · ', 1)
            l['affiche_titre'], l['affiche_suite'] = '', couper(tete, LIGNE_MAX - len(renvoi) - 3) + ' · ' + renvoi
        else:
            l['affiche_titre'], l['affiche_suite'] = '', couper(l['suite'], LIGNE_MAX)
        # Le dépli d'une ligne hors chantier : son texte complet, que l'affichage coupe ; une question rappelée posée
        # dans un menu, ou introuvable, porte le sien (demandes). Une ligne de chantier sans texte au tableau montre son
        # titre entier s'il a été coupé.
        if not l.get('chantier'):
            l['detail'] = l.get('detail') or l['complet']
        elif not l['detail'] and l['affiche_suite'] != complet:
            l['detail'] = complet
        # A numbered question of a foreman's board unfolds to itself too (0.2.17): its whole statement, then the
        # options, recommendation and files its detail gives; the detail follows.
        if l.get('chantier') and l.get('num') is not None:
            q = depli_de_question('', complet, f"{complet} {l.get('detail') or ''}", l.get('dossier') or '')
            l['depli'] = dict(q, enonce=complet)
    fraiches.sort(key=lambda l: (urgence_studio[l['studio']], -recente_studio[l['studio']], l['studio'],
                                 l['urgence'], (l['echeance'] or 0) if l['proche'] else 0, -l['recente'], l['rang']))
    # Les anciennes : par Studio, celui de la demande la plus récente d'abord, et dans un Studio la plus récente d'abord.
    recente_ancienne = {}
    for l in anciennes:
        recente_ancienne[l['studio']] = max(recente_ancienne.get(l['studio'], 0), l['recente'])
    anciennes.sort(key=lambda l: (-recente_ancienne[l['studio']], l['studio'], -l['recente'], l['rang']))
    return apres_leur_question(fraiches), anciennes


NUMERO_REPETE = re.compile(r'^(Q\d+)\s*·\s*(.+?)\s*:\s*\1\s*·\s*')


def sans_numero_repete(titre, suite):
    """« Q3 · Projet · FSP » then « Q3 · Boond : … »: the number once (PM, 2026-11-17). The title keeps it; the text after
    it loses its own copy, in the suite or inside a title that holds both."""
    titre, suite = titre or '', suite or ''
    m = re.match(r'(Q\d+)\s*·', titre)
    if m and suite:
        suite = re.sub(r'^' + m.group(1) + r'\s*·\s*', '', suite, count=1)
    return NUMERO_REPETE.sub(r'\1 · \2 : ', titre, count=1), NUMERO_REPETE.sub(r'\1 · \2 : ', suite, count=1)


RETIREES = 'retirees.json'   # in ~/Mon Studio/.parc: the lines the PM took off the board, by their key
RETIREES_JOURS = 60          # an entry is forgotten after that; its line, if still asked, comes back


def cle_retrait(l):
    """The key of a line the PM may take off the board: « r » and 12 hex digits, from its session and what it asks
    (its number and title for a question, the stop and its time for a stopped session, its text otherwise). The same
    question recalled the next day keeps its key; a new question, a new stop, gets a new one."""
    if l.get('num') is not None or l.get('question'):
        quoi = f"Q{l['num']}" if l.get('num') is not None else str(l.get('question'))
        quoi += '|' + ' '.join(str(l.get('titre') or '').split()).casefold()[:160]
    elif l.get('arret') in ('authorization', 'interrupted', 'error'):
        quoi = f"{l['arret']}|{int(l.get('depuis') or 0)}"
    else:
        quoi = ' '.join(f"{l.get('titre') or ''} {l.get('suite') or ''}".split()).casefold()[:200]
    qui = l.get('chantier') or l.get('cle') or ''
    return 'r' + hashlib.sha1(f'{qui}|{quoi}'.encode('utf-8')).hexdigest()[:12]


def cles_retirees():
    """{key: when} of the lines the PM took off the board (retirees.json), younger than RETIREES_JOURS."""
    r = lire_json(INTERNE / RETIREES, {})
    limite = time.time() - RETIREES_JOURS * 86400
    return {k: v['quand'] for k, v in (r.items() if isinstance(r, dict) else [])
            if isinstance(v, dict) and isinstance(v.get('quand'), (int, float)) and v['quand'] >= limite}


RETRAIT_MARGE_S = 120   # a question asked again later than this after its retrait is a new one: it comes back


def retiree(l, retirees):
    """True when the PM took this line off the board and its session has not asked it again since."""
    quand = retirees.get(l.get('retrait'))
    return quand is not None and max(l.get('depuis') or 0, l.get('reprise') or 0) <= quand + RETRAIT_MARGE_S


# The PM's own order (PM, 2026-11-17, for him alone at first): with "reclassement_tableau" on in cockpit.json, each line
# of the main board has one button that moves it into « D'abord » (« À faire d'abord ») or out of it (« Pas si urgent »);
# one more click undoes it. His order holds over the computed one while the line is there, by the line's stable key
# (cle_retrait for a line of a session, the request's own key for the ingestion). Every click is noted, one JSON line,
# in RECLASSEMENTS: what was computed and what he chose, to correct the rules later (reclassements.py). Nothing of it
# leaves the Mac. Switch off: nothing is read, the board is the computed one.
RECLASSEES = 'reclassees.json'           # in ~/Mon Studio/.parc: {key: {'vers': 'dabord'|'ensuite', 'quand'}}
RECLASSEMENTS = 'reclassements.jsonl'    # in ~/Mon Studio/.parc: the journal of his clicks
RECLASSEES_JOURS = 60                    # an order older than that is forgotten
CLASSE_PAR_TOI = 'classé par toi'
VERS_IMPACT = {'dabord': 'fort', 'ensuite': 'normal'}


def reclassement_actif():
    etat = lire_json(INTERNE / 'cockpit.json', {}) or {}
    return isinstance(etat, dict) and etat.get('reclassement_tableau') is True


def classements_du_pm():
    """{key: 'dabord' or 'ensuite'}: the PM's order of the lines he moved, younger than RECLASSEES_JOURS. Empty while
    the switch is off."""
    if not reclassement_actif():
        return {}
    r = lire_json(INTERNE / RECLASSEES, {})
    limite = time.time() - RECLASSEES_JOURS * 86400
    return {k: v['vers'] for k, v in (r.items() if isinstance(r, dict) else [])
            if isinstance(v, dict) and v.get('vers') in VERS_IMPACT and isinstance(v.get('quand'), (int, float))
            and v['quand'] >= limite}


def regle_du_calcul(dit, p, proche=False, bloque=False, arret=None):
    """In a few words, where the computed impact came from: the writer's label, or the rule that gave it."""
    if (dit or {}).get('impact'):
        return 'étiquette'
    if p.get('raison'):
        return f"règle : {p['raison']}"
    if p.get('impact') == 'fort':
        return 'règle : ' + ('échéance proche' if proche else 'session qui attend' if bloque else
                             'session arrêtée' if arret else 'échéance')
    return 'aucune règle'


def appliquer_classement(l, vers):
    """The PM's order over the computed one: « D'abord » is a strong impact, « Ensuite » a normal one; the reason says
    who decided. The effort stays."""
    l.update(impact=VERS_IMPACT[vers], raison=CLASSE_PAR_TOI, reclassee=vers)
    if vers == 'dabord':
        l['ancienne'] = False   # what he put first never hides among the old lines
    return l


def session_qui_en_parle(a, chef, par_id):
    """La fiche de la session que « Voir la session » ouvre pour l'attente « a » : sa source ; si elle est archivée ou
    introuvable, le fil rouge de son kit (champ « pilier » du miroir, pillarId du couloir) ; sinon rien. Jamais une
    session archivée (« Voir la session » must not lead to an archived session), ni le contremaître."""
    for sid in (a.get('source'), a.get('pilier')):
        f = par_id.get(sid) if sid else None
        if f and not f['archivee']:
            return f if f['id'] != chef else None
    return None


def archivees_des_chantiers(chantiers, metas):
    """Les sessions archivées qu'un tableau de chantier pourrait ouvrir : celles du chantier (couloirs_de) et celles que
    son miroir cite (sources, fils rouges, couloirs). Le tableau du chantier ne les ouvre jamais."""
    par_id = {m['id']: m for m in metas if m['id']}
    ids = set(couloirs_de(chantiers, metas))
    for c in chantiers:
        for a in c.get('attentes') or []:
            if isinstance(a, dict):
                ids.update(x for x in (a.get('source'), a.get('pilier'), a.get('sessionId')) if isinstance(x, str))
        for x in (c.get('piliers') or []) + (c.get('couloirs') or []):
            ids.update(v for v in ((x.get('sessionId'),) if isinstance(x, dict) else (x,)) if isinstance(v, str))
    return sorted(i for i in ids if (par_id.get(i) or {}).get('archivee'))


def menus_ouverts(sessions):
    """Les sessions figées sur un menu de questions encore ouvert."""
    return {s['id'] for s in sessions if s['etat'] == 'suspens' and s.get('menu')}


def nouvelles(sessions, metas, maintenant):
    """Les sessions d'un chantier qui ont fini sans rien demander (compte rendu, fin de tâche, avertissement), depuis
    moins d'un jour : l'ouverture de leur dernier message. Jamais une ligne du tableau (PM, 2026-10-13 : ce n'est pas
    une action) ; le tableau du chantier la montre, discrète, sur la carte du kit de la session, onglet État."""
    couloirs = couloirs_de(chantiers_actifs(metas), metas)
    sortie = []
    for s in sessions:
        chef = couloirs.get(s['id'])
        # « Rien à faire de ton côté. » seul n'apprend rien : pas de nouvelle.
        texte = ' '.join(p for p in couper_phrases(s.get('ouverture') or '') if not rien_a_faire(p, generique=True))
        if (chef and s['id'] != chef and s['etat'] == 'attend' and texte
                and maintenant - s['depuis'] < NOUVELLE_S and not demandes(s)):
            sortie.append({'chef': chef, 'sessionId': s['id'], 'session': titre_lien(s['titre']),
                           'texte': texte, 'depuis': s['depuis']})
    return sorted(sortie, key=lambda x: -x['depuis'])


def ligne_menu(menu, depuis):
    """La ligne d'une session arrêtée sur un menu de questions : la question en titre, les options en suite (« Go, tout
    (recommandé) · Pas encore »), le détail des options pour le survol et le dépli. Une session qui attend."""
    questions = ' · '.join(q['question'] for q in menu)
    return {'titre': questions, 'suite': ' | '.join(options_menu(q) for q in menu if q['options']),
            'detail': ' '.join(detail_menu(q) for q in menu), 'depuis': depuis, 'type': type_demande(questions),
            'bloque': True, 'menu': True, 'num': None, 'lecture': 'menu'}


def num_question(v):
    """5 pour « Q5 · … », « Q5 », « 5 » ou 5 ; None sinon."""
    m = re.match(r"\s*Q?(\d+)\b", str(v)) if v not in (None, '') else None
    return int(m.group(1)) if m else None


def apres_leur_question(lignes):
    """Une question qui en attend une autre (champ « apres » de l'attente, même chantier) se range juste sous
    elle, avec « · après Qn » ; si la question attendue n'est plus en attente, elle garde sa place normale.
    Une chaîne (Q7 après Q6 après Q5) se suit dans l'ordre ; une boucle est ignorée. La question attendue existait
    quand la ligne a été écrite : un numéro revient chaque jour ouvré, une question plus récente sous le même numéro
    n'est pas celle qu'elle attend."""
    par_num = {(l['chantier'], l['num']): l for l in lignes if l.get('chantier') and l.get('num') is not None}
    def ref(l):
        if l.get('attend') is None or not l.get('chantier'):
            return None
        r = par_num.get((l['chantier'], l['attend']))
        return r if r is not l and r is not None and r['depuis'] <= l['depuis'] + REPRISE_S else None
    sous = {}
    for l in lignes:
        r, vus = ref(l), {id(l)}
        while r is not None and id(r) not in vus:  # remonte la chaîne pour écarter une boucle
            vus.add(id(r))
            r = ref(r)
        if r is None and ref(l) is not None:
            l['apres'] = f"Q{l['attend']}"
            sous.setdefault(id(ref(l)), []).append(l)
    sortie = []
    def poser(l):
        sortie.append(l)
        for d in sous.get(id(l), []):
            poser(d)
    for l in lignes:
        if not l.get('apres'):
            poser(l)
    return sortie


def cle_titre(t):
    """Le rang d'un titre dans la barre latérale, triée par nom : sans casse ni accents."""
    return ''.join(c for c in unicodedata.normalize('NFD', t.casefold()) if not unicodedata.combining(c))


def de_premier_niveau(m):
    """A session at the top level of the sidebar: nobody launched it, or it was moved up after its launch."""
    return not m.get('parent') or bool(m.get('detachee'))


def messages_du_pm(chemin, cache):
    """How many messages the PM typed in this transcript. Counted once, then only on what the file gained since
    (cache['pm']: size read and count); a file that shrank is counted again."""
    memo = cache.setdefault('pm', {}) if isinstance(cache, dict) else {}
    try:
        taille = os.path.getsize(chemin)
    except OSError:
        return 0
    ent = memo.get(chemin)
    debut, n = (ent['taille'], ent['n']) if ent and ent.get('taille', 0) <= taille else (0, 0)
    if debut < taille:
        with open(chemin, 'rb') as f:
            f.seek(debut)
            bloc = f.read(taille - debut)
        fin = bloc.rfind(b'\n') + 1   # a line still being written is read next time
        for ligne in bloc[:fin].splitlines():
            try:
                o = json.loads(ligne)
            except ValueError:
                continue
            if isinstance(o, dict) and o.get('type') == 'user' and nature_user(o) == 'humain' \
                    and not INTERRUPTION.match(texte_de((o.get('message') or {}).get('content'))):
                n += 1
        taille = debut + fin
    memo[chemin] = {'taille': taille, 'n': n}
    return n


def ecrits_du_pm(metas, index, cache):
    """{sessionId: messages typed by the PM}, for the top-level sessions of the Studios that have a foreman: the
    only ones the main-thread rule looks at."""
    par_id = {m['id']: m for m in metas if m['id']}
    actifs = chantiers_actifs(metas)
    dossiers = [d for c in actifs if c.get('sessionId') in par_id for d in dossiers_du_miroir(c, par_id[c['sessionId']]['cwd'])]
    sortie = {}
    for m in metas:
        if m['id'] and not m['archivee'] and m.get('cli') and de_premier_niveau(m) and dans_un_dossier(m['cwd'], dossiers):
            chemin = index.get(m['cli'])
            if chemin:
                sortie[m['id']] = messages_du_pm(chemin, cache)
    return sortie


def fils_rouges(sessions, metas, lignes, ecrits=None):
    """Les sessions fil rouge, celles où le PM revient discuter d'un sujet. Dans un Studio qui a un contremaître : les
    sessions de premier niveau (de_premier_niveau) où le PM a écrit au moins FIL_ROUGE_MESSAGES messages (ecrits, par
    session ; sans ce relevé, le seuil ne joue pas), dans le dossier du contremaître et ses sous-dossiers (le périmètre
    du chantier), sauf un titre qui commence par « ᐅ », une tâche planifiée ou un fil 📬 ; le contremaître toujours.
    Une session lancée par une autre (sous-tâche, session de travail) n'en est pas (PM, 2026-11-17 : sur un projet, 14
    des 23 « fils rouges » étaient des sessions de travail). En plus, le champ « piliers » des miroirs de chantier, puis la liste locale des Studios sans
    chantier (FILS_ROUGES). Chacune sous le Studio de sa fiche, avec son titre de la barre latérale ; archivée ou sans
    fiche, elle n'apparaît pas. Dans un Studio qui a un contremaître, par titre, comme la barre latérale ; ailleurs,
    dans l'ordre des sources. Les Studios dans l'ordre du tableau, puis ceux qui n'ont que des fils rouges, le plus
    récemment actif d'abord."""
    par_id = {m['id']: m for m in metas if m['id']}
    vues = {s['id']: s for s in sessions}
    actifs = chantiers_actifs(metas)
    chefs = [c['sessionId'] for c in actifs if c.get('sessionId') in par_id]
    dossiers = [d for c in actifs if c.get('sessionId') in par_id for d in dossiers_du_miroir(c, par_id[c['sessionId']]['cwd'])]
    par_regle = chefs + [m['id'] for m in metas if m['id'] and dans_un_dossier(m['cwd'], dossiers) and not m.get('tache')
                         and not m['titre'].lstrip().startswith(('ᐅ', '📬')) and de_premier_niveau(m)
                         and (ecrits is None or ecrits.get(m['id'], 0) >= FIL_ROUGE_MESSAGES)]
    locale = lire_json(FILS_ROUGES, [])
    sources = par_regle + [x for c in actifs for x in (c.get('piliers') or [])]
    sources += locale if isinstance(locale, list) else []
    blocs, deja, par_titre = {}, set(), set()
    for x in sources:
        sid = x.get('sessionId') if isinstance(x, dict) else x
        m = par_id.get(sid) if isinstance(sid, str) else None
        if not m or m['archivee'] or sid in deja:
            continue
        deja.add(sid)
        s = vues.get(sid) or {}
        studio = nom_projet(m['cwd'])
        blocs.setdefault(studio, []).append({
            'titre': titre_lien(m['titre'] or (x.get('titre') if isinstance(x, dict) else '')), 'sessionId': sid,
            'non_lue': bool(s.get('non_lue')), 'derniere': s.get('derniere') or 0})
        if sid in par_regle:
            par_titre.add(studio)
    for st in par_titre:
        blocs[st].sort(key=lambda f: cle_titre(f['titre']))
    ordre = list(dict.fromkeys(l['studio'] for l in lignes))
    seuls = sorted((st for st in blocs if st not in ordre), key=lambda st: -max(f['derniere'] for f in blocs[st]))
    return [{'studio': st, 'sessions': blocs[st], 'avec_lignes': st in ordre}
            for st in [st for st in ordre if st in blocs] + seuls]


def sans_action(sessions, lignes, fils):
    """Les Studios qui ont des sessions non archivées mais aucune ligne dans le tableau : où on en est, d'après
    l'ouverture du dernier message de Claude dans leur session la plus récente. Le plus récent d'abord.
    Ce qui est vraiment ancien, le PM l'archive : tout ce qui reste ici est encore en cours quelque part."""
    avec = {l['studio'] for l in lignes}
    derniere = {}
    for s in sessions:
        st = nom_projet(s['cwd'])
        if st not in avec and (st not in derniere or s['derniere'] > derniere[st]['derniere']):
            derniere[st] = s
    sortie = [{'studio': st, 'titre': titre_lien(s['titre'], st), 'sessionId': s['id'], 'non_lue': bool(s.get('non_lue')),
               'derniere': s['derniere'],
               'etat': 'Claude travaille en ce moment.' if s['etat'] == 'travaille' and not s.get('ouverture')
               else s.get('ouverture') or ''}
              for st, s in derniere.items()]
    for b in fils:  # un Studio qui n'a que des fils rouges sans transcript lisible : il figure quand même
        if b['studio'] not in avec and b['studio'] not in derniere:
            f = max(b['sessions'], key=lambda f: f['derniere'])
            sortie.append({'studio': b['studio'], 'titre': f['titre'], 'sessionId': f['sessionId'],
                           'non_lue': f['non_lue'], 'derniere': f['derniere'], 'etat': ''})
    return sorted(sortie, key=lambda x: -x['derniere'])


# A question relayed by another session (PM, 2026-11-17: « réponds dans X », « (dans X) », « À répondre dans X »): the
# line is hidden when session X has its own open line on the same subject; when the match is not sure, both stay and
# the relay says « aussi dans X ». In the computation, without a model: the sessions are not trusted to never relay.
RELAIS = re.compile(r"(?i)(?:\br[ée]ponds?\s+dans|\b[àa]\s+r[ée]pondre\s+dans|\(\s*dans|\b[àa]\s+trancher\s+dans)\s+"
                    r"(?:la\s+session\s+)?(?:\[([^\]]+)\]\(#?(local_[0-9a-f-]{36})\)|[«\"“]\s*([^»\"”]{3,120}?)\s*[»\"”]|([^().;:\n]{3,80}))")


def nom_de_session(t):
    return ' '.join(re.sub(r"[^\w\s'’-]", ' ', unicodedata.normalize('NFC', str(t or '')).lower()).split())


def dedoublonner_relais(rangs, cibles=None):
    """The board's lines without the relays of a question its own session already carries (RELAIS)."""
    cibles = rangs if cibles is None else cibles
    sortie = []
    for l in rangs:
        texte = ' '.join(str(l.get(k) or '') for k in ('affiche_titre', 'affiche_suite', 'complet'))
        m = RELAIS.search(texte)
        if not m:
            sortie.append(l)
            continue
        titre, sid = (m.group(1) or m.group(3) or m.group(4) or '').strip(), m.group(2) or ''
        coupe = titre.rstrip().endswith(('…', '...'))
        noms = {nom_de_session(titre), nom_de_session(titre.split(' · ')[-1])} - {''}
        def vise(x):
            if x is l or x.get('cle') == l.get('cle'):
                return False
            if sid:
                return x.get('cle') == sid or x.get('ouvrir') == sid
            # The board names a session without its Studio (« Backlog lot 1 ») when the relay writes « Alpha · Backlog
            # lot 1 »; a name cut by « … » matches the start of the title.
            for n in {nom_de_session(x.get('session')), nom_de_session(str(x.get('session') or '').split(' · ')[-1])} - {''}:
                for nom in noms:
                    if n == nom or (min(len(n), len(nom)) >= (5 if coupe else 8) and (n.startswith(nom) or nom.startswith(n))):
                        return True
            return False
        visees = [x for x in cibles if vise(x)]
        if not visees:
            sortie.append(l)
            continue
        sujet = re.sub(RELAIS, ' ', texte)
        sur = any((l.get('question') and l.get('question') == x.get('question') and l.get('copie_numero') is not False)
                  or meme_sujet(sujet, ' '.join(str(x.get(k) or '') for k in ('affiche_titre', 'affiche_suite', 'complet')))
                  for x in visees)
        if not sur:
            sortie.append(dict(l, aussi_dans=visees[0].get('session') or titre))
    return sortie


def pour_la_page(e):
    """Ce que le connecteur envoie à la page épinglée. Ici plutôt que dans le connecteur : il recharge ce fichier
    quand install.py en pose une copie, une évolution du tableau ne demande donc pas de l'arrêter."""
    rang = rang_page
    tous = [rang(l) for l in e['tableau']] + [rang(l) for l in e.get('anciennes') or []]
    rangs = dedoublonner_relais([rang(l) for l in e['tableau']], tous)
    fils = [{'studio': b['studio'], 'sessions': [dict({k: f[k] for k in ('titre', 'sessionId', 'non_lue')},
                                                    derniere=int((f.get('derniere') or 0) * 1000)) for f in b['sessions']]}
            for b in e.get('fils_rouges') or []]
    chantiers = [{'chantier': c.get('chantier'), 'studio': c.get('studio'), 'tableau': c.get('tableau'),
                  'misAJour': c.get('misAJour')} for c in miroirs() if c.get('tableau')]
    sans = [dict(x, derniere=int(x['derniere'] * 1000)) for x in e.get('sans_action') or []]
    nouv = [dict(x, depuis=int(x['depuis'] * 1000)) for x in e.get('nouvelles') or []]
    # « anciennes » : un champ à part, que le tableau du chantier (qui lit « lignes ») ne voit pas.
    return {'genere': int(e['genere'] * 1000), 'pastilles_lues': e['pastilles_lues'], 'lignes': rangs,
            'anciennes': dedoublonner_relais([rang(l) for l in e.get('anciennes') or []], tous),
            'fils_rouges': fils, 'sans_action': sans, 'chantiers': chantiers, 'nouvelles': nouv,
            'menus': e.get('menus') or [], 'reglees': e.get('reglees') or {}, 'archivees': e.get('archivees') or [],
            'fermees': [{k: f.get(k) for k in ('studio', 'session', 'texte', 'preuve', 'ouverte', 'ouverte_titre')}
                        for f in e.get('fermees') or []],
            'lecture_app': e.get('lecture_app') or {'etat': 'ok', 'raison': ''},
            'sans_transcript': e.get('sans_transcript'),
            'projets': projets_de_la_page(e['tableau'], e.get('_metas') or []),
            'rangees': rangees_du_jour(e['genere'])}


def rangees_du_jour(maintenant):
    """The sessions the rangement archived today (hooks/rangement.py writes them in .parc/rangement.json), so the PM
    can reopen one from the Archived list: [{'id', 'titre', 'quand' (ms)}], the latest first."""
    jour = dt.datetime.fromtimestamp(maintenant).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = (lire_json(INTERNE / 'rangement.json', {}) or {}).get('rangees') or []
    return sorted(({'id': x.get('id'), 'titre': x.get('titre') or '', 'quand': int(x['quand'] * 1000)} for x in r
                   if isinstance(x, dict) and isinstance(x.get('quand'), (int, float)) and x['quand'] >= jour),
                  key=lambda x: -x['quand'])


GARDER_PAGE = ('studio', 'session', 'sous', 'lien', 'ouvrir', 'cle', 'non_lue', 'type', 'verbe', 'complet',
               'affiche_titre', 'affiche_suite', 'apres', 'bloque', 'source', 'source_titre', 'question', 'a_numeroter',
               'detail', 'declencheur', 'agir_dans', 'nommee', 'sujet', 'reglee', 'arret', 'extrait', 'projet', 'choix',
               'seule', 'puces', 'copie_numero', 'tache', 'depli', 'dossier', 'retrait', 'impact', 'raison', 'effort',
               'hors_studio', 'en_tete', 'choix_libelles', 'choix_reco')


def rang_page(l):
    """Une ligne telle que la page la reçoit (temps en millisecondes). Une ligne numérotée d'une session porte sa
    question (depli : énoncé, options, recommandation, fichiers cités) ; une ligne sans numéro, ses puces
    (ce_qu_attend). `dossier` : le dossier de la session, où « Lire » cherche les fichiers cités."""
    r = dict({k: l.get(k) for k in GARDER_PAGE}, depuis=int(l['depuis'] * 1000),
             echeance=int(l['echeance'] * 1000) if l.get('echeance') else None, proche=bool(l.get('proche')))
    if l.get('reclassee'):
        # The PM moved it (reclassement switch on), and what the rules gave, for his undo: absent otherwise.
        r['reclassee'] = l['reclassee']
        r['calcul'] = {k: (l.get('calcul') or {}).get(k) or '' for k in ('impact', 'raison', 'effort')}
    return r


def vue_projet_pour_la_page(e, dossier):
    """La vue d'un projet telle que la page la reçoit (vue_projet), ou {'introuvable': True}."""
    v = vue_projet(e, dossier)
    if v is None:
        return {'dossier': dossier, 'introuvable': True}
    ms = lambda t: int(t * 1000) if t else None
    sujet = lambda x: dict(x, depuis=ms(x['depuis']))
    return {'genere': int(e['genere'] * 1000), 'dossier': dossier, 'nom': v['nom'],
            'questions': dedoublonner_relais([rang_page(l) for l in v['questions']], [rang_page(l) for l in e['tableau'] + (e.get('anciennes') or [])]),
            'anciennes': dedoublonner_relais([rang_page(l) for l in v['anciennes']], [rang_page(l) for l in e['tableau'] + (e.get('anciennes') or [])]),
            'sujets': [dict(sujet(sj), filles=[sujet(f) for f in sj['filles']]) for sj in v['sujets']],
            'tiers': [sujet(x) for x in v['tiers']], 'journal': [sujet(j) for j in v['journal']]}


# --- rendus -----------------------------------------------------------------------------------------------

def titre_lien(t, studio=None):
    """Le titre d'une session pour un lien. À côté de son Studio, sans le préfixe « <Studio> · » que la règle des sessions
    met en tête du nom : « Alpha · Compte rendu du kick-off » se lit « Compte rendu du kick-off » dans la ligne du Studio
    « Projet Alpha ». Le préfixe vaut le nom du Studio ou ses derniers mots."""
    t = t or 'Session sans titre'
    if studio:
        avant, sep, apres = t.partition(' · ')
        nom, court = ' '.join(studio.casefold().split()), ' '.join(avant.casefold().split())
        if sep and apres.strip() and court and (nom == court or nom.endswith(' ' + court)):
            t = apres.strip()
    return t.replace('[', '(').replace(']', ')')


def anciennete(depuis, maintenant):
    """Comme le tableau de chantier : 12 min, 3 h, 4 j, 3 sem."""
    m = round(max(0, maintenant - depuis) / 60)
    if m < 60:
        return f'{m} min'
    h = round(m / 60)
    if h < 24:
        return f'{h} h'
    d = round(h / 24)
    return f'{d} j' if d < 14 else f'{round(d / 7)} sem'


def hors_service(e):
    return (e.get('lecture_app') or {}).get('etat') == 'hors_service'


def pas_encore(e):
    return (e.get('lecture_app') or {}).get('etat') == 'pas_encore'


ACCUEIL = "Aucun Studio trouvé pour l'instant. Ouvre une session dans le dossier d'un Studio : il apparaît ici."


def rendre_md(e):
    m = e['genere']
    lignes = e['tableau']
    out = [f"**Mon Studio** · {dt.datetime.fromtimestamp(m).strftime('%d/%m %H:%M')} · "
           f"{len(lignes)} en attente dans {len({l['studio'] for l in lignes})} Studio(s)", '']
    if hors_service(e):
        out += [f"**Mon Studio ne lit plus l'app : {e['lecture_app']['raison']}.** Le tableau ne dit pas ce qui t'attend.", '']
    if e.get('sans_transcript'):
        out += [f"_{e['sans_transcript']['texte']}_", '']
    if e.get('matin_retard'):
        out += [f"**{e['matin_retard']}.** Ouvre son exécution dans « Planifiées » : une autorisation l'attend peut-être.", '']
    if not e['pastilles_lues']:
        out += ["_Pastilles de la barre illisibles : « non lue » est déduit des heures de passage._", '']
    anciennes = e.get('anciennes') or []
    if not lignes and not e.get('sans_action') and not anciennes:
        return '\n'.join(out + ["Impossible de dire ce qui t'attend." if hors_service(e) else ACCUEIL if pas_encore(e)
                               else "Rien ne t'attend."]) + '\n'
    fils = {b['studio']: b['sessions'] for b in e.get('fils_rouges') or []}
    # En tête, la bande « En un clic » : les sessions arrêtées sur une autorisation (un outil
    # attend l'accord du PM, la session ne fait rien d'autre en attendant ; PM, 2026-10-29), puis les questions de type
    # « clic », dont le fond est déjà décidé. Rien à lire au-delà d'une ligne ; elles ne sont pas répétées plus bas.
    autorisations = [l for l in lignes if l.get('arret') == 'authorization']
    clics = [l for l in lignes if en_un_clic(l) and l.get('arret') != 'authorization']
    if autorisations or clics:
        out += [f"**{TITRE_UN_CLIC} ({len(autorisations) + len(clics)})**", '', f"_{SOUS_TITRE_UN_CLIC}_", '',
                '| Studio | Session | Ce que la session veut faire | Depuis |', '|---|---|---|---|']
        out += [rang_autorisation_md(l, m) for l in autorisations]
        out += [f"| {l['studio']} | {lien_session_md(l)} | "
                f"{' : '.join(x for x in (l['affiche_titre'], l['affiche_suite']) if x).replace('|', '/')} | "
                f"{anciennete(l['depuis'], m)} |" for l in clics] + ['']
        lignes = [l for l in lignes if not en_un_clic(l)]
    ordre = list(dict.fromkeys(l['studio'] for l in lignes))
    entete = ["| Studio | Session | Ce qui t'attend | Type | Depuis |", '|---|---|---|---|---|']
    if ordre:
        out += [' · '.join(f"{st} ({sum(1 for l in lignes if l['studio'] == st)})" for st in ordre), '']
        out += entete
    def rang_fils(studio):
        liens = ' · '.join(f"[{f['titre']}](#{f['sessionId']})" for f in fils.get(studio) or [])
        return [f"| {studio} | Fils rouges | {liens} | | |"] if liens else []
    avant = None
    for l in lignes:
        studio = l['studio'] if l['studio'] != avant else ''
        if studio and fils.get(studio):  # les fils rouges en tête du Studio, son nom avec eux
            out += rang_fils(studio)
            studio = ''
        out.append(rang_md(l, studio, m))
        avant = l['studio']
    # Sous les demandes fraîches, les anciennes, avec leur propre nombre.
    if anciennes:
        out += ['', f"**{TITRE_ANCIENNES}** · {len(anciennes)}", ''] + entete
        avant = None
        for l in anciennes:
            out.append(rang_md(l, l['studio'] if l['studio'] != avant else '', m))
            avant = l['studio']
    if e.get('fermees'):
        out += ['', f"**{TITRE_FERMEES}**", '']
        out += [f"- {f['studio']} · {f['session']} · {f['texte']} : {f['preuve']}".replace('|', '/') for f in e['fermees']]
    if e.get('sans_action'):
        out += ['', '**Sans action en ce moment**', '', '| Studio | Dernière session | Où on en est | Dernière activité |', '|---|---|---|---|']
        for x in e['sans_action']:
            quand = dt.datetime.fromtimestamp(x['derniere']).strftime('%d/%m') if x['derniere'] else ''
            out.append(f"| {x['studio']} | [{x['titre']}](#{x['sessionId']}) | {x['etat'].replace('|', '/')} | {quand} |")
            if fils.get(x['studio']):
                out.append('|  | Fils rouges | ' + ' · '.join(f"[{f['titre']}](#{f['sessionId']})" for f in fils[x['studio']]) + ' | |')
    return '\n'.join(out) + '\n'


TITRE_ANCIENNES = 'Anciennes : à traiter ou à archiver'
TITRE_FERMEES = 'Réglé sur preuve'
TITRE_UN_CLIC = 'En un clic'
SOUS_TITRE_UN_CLIC = 'Autorisations et gestes déjà décidés : un clic suffit.'


def en_un_clic(l):
    """Une ligne de la bande « En un clic » : une autorisation à donner, ou une question de type « clic »."""
    return l.get('arret') == 'authorization' or l.get('type') == 'clic'
SANS_EXTRAIT = 'détail dans la session'


def lien_session_md(l):
    if l['lien'].startswith('claude://'):
        return f"[{l['session']}](#{l['lien'].rsplit('/', 1)[-1]})"
    return f"[{l['session']}]({l['lien']})" if l['lien'] else l['session']


def rang_autorisation_md(l, m):
    """Un rang du bloc « Autorisations en attente » : Studio, session (le lien l'ouvre), ce que l'outil ferait, depuis."""
    quoi = ("`" + l['extrait'].replace('`', "'") + "`" if l.get('extrait') else SANS_EXTRAIT).replace('|', '/')
    return f"| {l['studio']} | {lien_session_md(l)} | {quoi} | {anciennete(l['depuis'], m)} |"
MARQUE_A_CONFIRMER = ' · réglée dans la session, à confirmer'   # les mots du tableau du chantier


def rang_md(l, studio, m):
    """Un rang du tableau en Markdown : Studio (vide sous le premier de son bloc), session, ce qui attend, verbe, depuis."""
    if l.get('sujet'):  # ligne de chantier : son sujet, qui n'ouvre rien, comme au tableau du chantier
        session = l['session']
    elif l.get('nommee'):  # ligne de chantier sans sujet : le nom ouvre la session nommée, le verbe la sienne
        session = f"[{l['session']}](#{l['nommee']})"
    elif l['lien'].startswith('claude://'):
        session = f"[{l['session']}](#{l['lien'].rsplit('/', 1)[-1]})"
    else:
        session = f"[{l['session']}]({l['lien']})" if l['lien'] else l['session']
    if l.get('sous'):
        session += f"<br>{l['sous']}"
    quoi = (' : '.join(x for x in (l['affiche_titre'], l['affiche_suite']) if x)
            + (f" · après {l['apres']}" if l.get('apres') else '')
            + (' · une session attend' if l.get('bloque') else '')
            + (MARQUE_A_CONFIRMER if l.get('reglee') else '')).replace('|', '/')
    quand = (f"avant le {dt.datetime.fromtimestamp(l['echeance']).strftime('%d/%m')}" if l.get('echeance')
             else anciennete(l['depuis'], m))
    voir = f" · [Voir la session](#{l['source']})" if l.get('source') and l['source'] != l.get('ouvrir') else ''
    verbe = (f"[{l['verbe']}](#{l['ouvrir']})" if l.get('ouvrir') and (l.get('sujet') or l.get('nommee') and l['ouvrir'] != l['nommee'])
             else l['verbe'])
    return f"| {studio} | {session} | {quoi} | {verbe}{voir} | {quand} |"


def lien_app(sid):
    return f"claude://claude.ai/epitaxy/{sid}"


# --- entrée -----------------------------------------------------------------------------------------------

def charger_cache():
    c = lire_json(INTERNE / 'cache.json', {}) or {}
    if c.get('version') != VERSION_CACHE:
        # Le relevé du contrôle n'est pas un calcul à refaire : il survit à un changement de version du cache.
        c = {'version': VERSION_CACHE, 'controle': c.get('controle') if isinstance(c.get('controle'), dict) else {}}
    c.setdefault('fiches', {})
    c.setdefault('transcripts', {})
    c.setdefault('suivi', {})
    c.setdefault('pm', {})   # messages_du_pm: how many messages the PM typed per transcript, counted incrementally
    c.setdefault('controle', {})
    return c


def expliquer(cible, maintenant):
    cache = {'version': VERSION_CACHE, 'fiches': {}, 'transcripts': {}}
    metas = fiches(cache)
    index = index_transcripts()
    cible_n = cible.lower()
    trouvees = [m for m in metas if m['id'] and (cible_n in (m['titre'] or '').lower() or cible_n in m['id']
                                                  or (m['cli'] and cible_n in m['cli']))]
    if not trouvees:
        print(f'Aucune session ne correspond à « {cible} ».')
        return 1
    m = max(trouvees, key=lambda m: m['activite'])
    chemin = index.get(m['cli'])
    if not chemin:
        print(f"Session trouvée ({m['titre']}) mais transcript absent.")
        return 1
    r = analyser(chemin, maintenant)
    print(f"{m['titre']} · {m['id']} · {libelle_etat(r, maintenant)}\n")
    if r['etat'] != 'attend':
        print("Pas de tri : seule une session qui attend ta réponse porte des phrases.")
        return 0
    lignes, reste, notes, retenues = trier(r['texte'], expliquer=True)
    for n in notes:
        if n['role'] != 'phrase' and n['role'] != 'titre':
            continue
        marque = '★ GARDÉE ' if id(n) in retenues else ('  candidate' if n['prio'] is not None else '  écartée ')
        print(f"{marque} [{n['prio'] or '-'}] {n['raison']}\n           {n['p'][:300]}")
    print('\nAncien écran :')
    for l in lignes:
        print('  > ' + l)
    if reste:
        print(f'  (+{reste} autre(s) dans la session)')
    s = dict(r, prio=None, tete='')
    _, _, s['tete'], s['prio'] = trier(r['texte'])
    print('\nTableau (avant les règles de fenêtre et de chantier) :')
    for d in demandes(s) or [{'titre': '', 'suite': '(aucune ligne)', 'type': None}]:
        print(f"  [{TYPES.get(d['type'], '-')}] " + ' : '.join(x for x in (d['titre'], d['suite']) if x))
    return 0


def passage(jours, silence):
    if not APP.exists():
        print(f"Fiches de session de l'app introuvables ({APP}) : l'app Claude desktop est-elle installée ?")
        return 2
    debut = maintenant = time.time()
    cache = charger_cache()
    ecran = construire(jours, silence, maintenant, cache)
    ecrire_atomique(SORTIE / 'mon-studio.md', rendre_md(ecran))
    ecrire_atomique(INTERNE / 'cache.json', json.dumps(cache, ensure_ascii=False))
    print(f"ok {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {len(ecran['tableau'])} ligne(s) en attente dans "
          f"{len({l['studio'] for l in ecran['tableau']})} Studio(s) · pastilles {'lues' if ecran['pastilles_lues'] else 'ILLISIBLES'} · "
          f"{time.time() - debut:.1f} s")
    return 0


def main():
    ap = argparse.ArgumentParser(description='Mon Studio : où tu en es sur toutes tes sessions, sans LLM.')
    ap.add_argument('--jours', type=int, default=int(os.environ.get('MON_STUDIO_JOURS', 7)))
    ap.add_argument('--silence', type=int, default=int(os.environ.get('MON_STUDIO_SILENCE', 7)))
    ap.add_argument('--afficher', action='store_true')
    ap.add_argument('--expliquer', metavar='SESSION')
    ap.add_argument('--controle', nargs='?', const=7, type=int, metavar='JOURS')
    ap.add_argument('--marqueur', nargs=2, metavar=('RUBRIQUE', 'EXPRESSION'),
                    help="« ajoute ce marqueur » : demande, rien ou trancher, puis l'expression du PM")
    a = ap.parse_args()
    if a.marqueur:
        rubrique, expression = a.marqueur
        if not ajouter_marqueur(rubrique, expression):
            print('Rubrique : demande, rien ou trancher ; expression : trois caractères au moins.')
            return 2
        print(f'Ajouté à {MARQUEURS} ({rubrique}) : {expression.strip()}')
        return 0
    if a.expliquer:
        return expliquer(a.expliquer, time.time())
    if a.controle is not None:
        print(rapport_controle(charger_cache()['controle'], a.controle, time.time()))
        return 0
    if a.afficher:
        f = SORTIE / 'mon-studio.md'
        # /parc : l'écran du dernier passage, refait sur place s'il a plus d'une minute (0,1 s).
        if not f.exists() or time.time() - f.stat().st_mtime > 60:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                passage(a.jours, a.silence)
        print(f.read_text(encoding='utf-8') if f.exists() else 'Pas encore de mon-studio.md.')
        return 0
    return passage(a.jours, a.silence)


if __name__ == '__main__':
    sys.exit(main())
