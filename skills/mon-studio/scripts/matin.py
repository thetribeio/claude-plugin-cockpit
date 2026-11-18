#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le point du matin : lecture de ~/Mon Studio/matin.json, sans LLM.

    python3 matin.py                # une ligne d'état : état du fichier du jour et nombre d'éléments par bloc
    python3 matin.py fait <cle>     # « Fait » : un élément à traiter, à préparer pour demain, ou un brouillon, pour de bon
    python3 matin.py preparer       # pour la tâche du matin : JSON de ce qu'elle n'a pas à lire elle-même, ou « stop »
    python3 matin.py verifier       # pour la vérification : JSON des seuls éléments à vérifier, ou « stop »
    python3 matin.py ecrire         # vérifie le JSON lu sur l'entrée standard et le met à la place de matin.json

Les tâches planifiées n'utilisent aucun outil de fichier (2026-11-10) : `preparer` et `verifier` leur donnent ce
qu'elles liraient, et elles écrivent le point par l'outil `matin_ecrire` du connecteur, qui appelle `ecrire` (un JSON
dans un heredoc se heurte aux contrôles de Claude Code avant toute règle). Elles ne lancent que `preparer` ou
`verifier`, autorisés dans ~/.claude/settings.json par `install.py apply --autorisations`, après le go du PM.

Les deux dernières commandes bornent le travail du LLM (2026-11-09, coût mesuré des tâches du matin) : ce qu'un script
sait lire, il le lit. `preparer` dit « stop » quand le point du jour est déjà écrit (une exécution rejouée ne refait
rien) ; sinon il rend la liste des Studios, les demandes « À toi de jouer » déjà relevées (lues dans projets.json, le
LLM n'ouvre plus les fichiers d'ingestion) et, pour chaque Studio où la personne est PM, les jours qui ont déjà un
compte rendu dans un dossier `reunions`, et les seuls brouillons de .parc/brouillons.json à vérifier (posés avant
le dernier jour ouvré, pas faits, Slack dans ses 3 jours ouvrés, 10 Gmail au plus : 2026-11-10). `verifier` dit « stop » quand le fichier n'est pas d'aujourd'hui, quand il ne
reste rien à traiter, ou après VERIFS_MAX passages dans la journée (compte tenu dans matin-verif.json) ; sinon il rend
les seuls éléments « à traiter » encore ouverts, avec leur lien : la tâche ne lit rien d'autre.

matin.json est écrit chaque matin par la tâche planifiée du PM (seul endroit où un LLM travaille, consigne :
docs/consigne-point-du-matin.md). Mon Studio le lit et l'affiche, rien d'autre. Schéma :

    genere_le          date ISO de l'écriture
    jour               lourde | normale | ouverte
    agenda             [{heure, titre, projet}]
    a_traiter          [{cle, titre, phrase, source (gmail|slack|agenda|studio), lien, projet}]
    regle              [{qui, quand, quoi, lien, projet}]   (projet : celui de l'élément « à traiter » déplacé, s'il y en a un)
    preparer_demain    [{cle, titre, phrase, lien}]   (cle : `demain:<identifiant de l'événement>` ; absente, elle est
                       tirée du titre et du lien, pour que « Fait » la retienne)
    reunions_sans_cr   [{cle, projet, titre, date, lien}]   (lues par projets.py : lignes `reunion`)
    sans_reponse       [{cle, titre, qui, projet, depuis, lien}]   ce que le PM attend des autres depuis plus de 2 jours
                       ouvrés (ses mails ou messages restés sans réponse), à relancer. Dans « Sans réponse » de Today,
                       avec les attentes de tiers des chantiers ; « Fait » le retire.
    brouillons         [{cle, projet, outil (gmail|slack), destinataire, objet, depuis, lien}]
                       les brouillons posés par une session et pas envoyés depuis plus d'un jour ouvré (relevés par le
                       hook hooks/brouillons.py dans .parc/brouillons.json, vérifiés dans Gmail par la tâche du matin).
                       Seulement dans l'onglet Today. Un brouillon sans lien qui l'ouvre (Gmail : mail.google.com ;
                       Slack : *.slack.com) est écarté. Un champ absent (ancienne consigne) = liste vide.
                       Un brouillon Slack ne paraît que 3 jours ouvrés (lundi-vendredi) au plus après sa création
                       (`depuis`, sinon `cree_le` de .parc/brouillons.json ; sans date, il est écarté), puis s'efface
                       seul (PM, Q42, 2026-11-09). Un brouillon Gmail reste jusqu'à l'envoi ou « Fait ».

La partie ingestion (entrées au Studio, nouvelles demandes « À toi ») n'est plus dans ce fichier : projets.py la calcule
en direct (ingestion_du_matin). Un ancien matin.json qui porte encore `entre_studio` est lu sans ce champ.

Un lien est https, sauf dans `a_traiter` et `regle` : un chemin relatif au Studio du projet y est aussi
accepté (un élément « studio » déplacé dans `regle` garde son lien) (sans `..`, sans racine ni schéma), que la page ouvre par le connecteur (outil `ouvrir`, bouton « Fichier »).
La seconde tâche, `point-du-matin-verif` (consigne : assets/consigne-point-du-matin-verif.md), ne fait que déplacer
dans `regle` les éléments de `a_traiter` qui ont eu leur réponse, dans la journée.

La lecture ne lève jamais : fichier absent, illisible ou périmé = « pas encore passé » ; un champ manquant ou
mal formé = un élément écarté ou un bloc vide. Chaque bloc est tronqué à son plafond.

« Fait » vit dans ~/Mon Studio/matin-etat.json, champ `fermes` : {clé: {le, empreinte}}, les 500 dernières. Un
élément fait (à traiter, préparer demain, brouillon) disparaît pour de bon : la tâche du matin peut le récrire le
lendemain sous la même clé, il ne revient pas (PM, 2026-11-09). L'empreinte (titre normalisé ; objet et destinataire
d'un brouillon) fait revenir une nouvelle demande écrite sous la même clé. L'ancien état (`jours`, `brouillons_vus`) est
relu, sans empreinte.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import time
import unicodedata

ICI = pathlib.Path(__file__).resolve().parent


def _charger_parc():
    """parc.py du même dossier, comme projets.py ; le connecteur remplace ce module par le sien (matin.parc = parc)."""
    spec = importlib.util.spec_from_file_location('parc', ICI / 'parc.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parc = _charger_parc()

PLAFOND_A_TRAITER = 7
PLAFOND_REGLE = 5
PLAFOND_PREPARER_DEMAIN = 3
PLAFOND_AGENDA = 20
PLAFOND_REUNIONS = 20
PLAFOND_BROUILLONS = 10
PLAFOND_SANS_REPONSE = 7
BROUILLONS_GMAIL_MAX = 10   # Gmail drafts the morning task reads, at most (one read each)
FERMES_MAX = 500
SLACK_JOURS_OUVRES = 3
OUTILS = {'gmail': re.compile(r'^https://mail\.google\.com/'), 'slack': re.compile(r'^https://([a-z0-9-]+\.)*slack\.com/')}
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
JOURS = ('lourde', 'normale', 'ouverte')
SOURCES = ('gmail', 'slack', 'agenda', 'studio')
CHEMIN_MAX = 500
TITRE_MAX = 120
PHRASE_MAX = 300
CLE_MAX = 80
VERIFS_MAX = 3            # passages de la vérification par jour, au plus (cron 11h, 14h, 17h ; une relance de l'app compte)
A_TOI_MAX = 60            # demandes « À toi » rendues à la tâche du matin, au plus
JOURS_CR = 10             # jours couverts par la recherche des comptes rendus (5 jours ouvrés et leurs week-ends)
DATE_NOM = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
HEURE_TACHE = (7, 30)     # cron de la tâche « Point du matin » : 30 7 * * 1-5
MARGE_MIN = 30            # le temps de son exécution : avant, « pas encore passé » n'est pas un retard


def _sortie():
    return parc.SORTIE


def _texte(v, n):
    """Une chaîne propre de n caractères au plus, '' pour tout ce qui n'en est pas une."""
    if not isinstance(v, str):
        return ''
    s = ' '.join(v.split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def _lien(v):
    """Le seul lien accepté : https. Le reste est écarté."""
    v = v.strip() if isinstance(v, str) else ''
    return v if v.startswith('https://') and len(v) <= 1000 else ''


def _chemin(v):
    """Un chemin relatif au Studio : ni racine, ni lecteur, ni schéma, ni `..`, ni caractère de contrôle. '' sinon."""
    v = v.strip() if isinstance(v, str) else ''
    if not v or len(v) > CHEMIN_MAX or v[0] in '/~' or '\\' in v or ':' in v:
        return ''
    if any(ord(c) < 32 for c in v) or any(part in ('', '.', '..') for part in v.split('/')):
        return ''
    return v


def _lien_ou_chemin(v):
    return _lien(v) or _chemin(v)


def _liste(brut, plafond, nettoyer):
    if not isinstance(brut, list):
        return []
    sortie = []
    for x in brut:
        item = nettoyer(x) if isinstance(x, dict) else None
        if item:
            sortie.append(item)
        if len(sortie) >= plafond:
            break
    return sortie


def _agenda(x):
    heure, titre = _texte(x.get('heure'), 20), _texte(x.get('titre'), TITRE_MAX)
    return {'heure': heure, 'titre': titre, 'projet': _texte(x.get('projet'), 80)} if heure and titre else None


def _a_traiter(x):
    cle, titre = _texte(x.get('cle'), CLE_MAX), _texte(x.get('titre'), TITRE_MAX)
    if not cle or not titre:
        return None
    source = x.get('source') if x.get('source') in SOURCES else ''
    return {'cle': cle, 'titre': titre, 'phrase': _texte(x.get('phrase'), PHRASE_MAX), 'source': source,
            'lien': _lien_ou_chemin(x.get('lien')), 'projet': _texte(x.get('projet'), 80)}


def _sans_reponse(x):
    cle, titre = _texte(x.get('cle'), CLE_MAX), _texte(x.get('titre'), TITRE_MAX)
    if not cle or not titre:
        return None
    return {'cle': cle, 'titre': titre, 'qui': _texte(x.get('qui'), 80), 'projet': _texte(x.get('projet'), 80),
            'depuis': _texte(x.get('depuis'), 40), 'lien': _lien_ou_chemin(x.get('lien'))}


def _regle(x):
    qui, quoi = _texte(x.get('qui'), 80), _texte(x.get('quoi'), PHRASE_MAX)
    if not qui or not quoi:
        return None
    return {'qui': qui, 'quand': _texte(x.get('quand'), 40), 'quoi': quoi, 'lien': _lien_ou_chemin(x.get('lien')),
            'projet': _texte(x.get('projet'), 80)}


def _preparer(x):
    titre = _texte(x.get('titre'), TITRE_MAX)
    if not titre:
        return None
    lien = _lien(x.get('lien'))
    # A stable key, so that « Fait » holds: the task's own, else one drawn from the title and the link.
    cle = _texte(x.get('cle'), CLE_MAX) or 'demain:' + hashlib.sha1(f'{titre}|{lien}'.encode('utf-8')).hexdigest()[:12]
    return {'cle': cle, 'titre': titre, 'phrase': _texte(x.get('phrase'), PHRASE_MAX), 'lien': lien}


def _reunion(x):
    cle, projet, titre = _texte(x.get('cle'), CLE_MAX), _texte(x.get('projet'), 80), _texte(x.get('titre'), TITRE_MAX)
    if not cle or not projet or not titre:
        return None
    return {'cle': cle, 'projet': projet, 'titre': titre, 'date': _texte(x.get('date'), 40), 'lien': _lien(x.get('lien'))}


def _brouillon(x):
    """A draft with a link that opens it in its own tool, else None."""
    cle, outil, lien = _texte(x.get('cle'), CLE_MAX), x.get('outil'), _lien(x.get('lien'))
    if not cle or outil not in OUTILS or not OUTILS[outil].match(lien):
        return None
    depuis = x.get('depuis') if isinstance(x.get('depuis'), str) and DATE.match(x['depuis']) else ''
    return {'cle': cle, 'projet': _texte(x.get('projet'), 80), 'outil': outil,
            'destinataire': _texte(x.get('destinataire'), 120), 'objet': _texte(x.get('objet'), TITRE_MAX),
            'depuis': depuis, 'lien': lien}


def jours_ouvres_apres(debut, jour):
    """The working days (Monday to Friday) after `debut` up to `jour` included: 0 on the same day."""
    if jour <= debut:
        return 0
    if (jour - debut).days > 60:
        return (jour - debut).days   # far enough: no need to count
    return sum(1 for i in range(1, (jour - debut).days + 1) if (debut + dt.timedelta(days=i)).weekday() < 5)


def _cree_le_des_notes():
    """{cle: AAAA-MM-JJ} of the drafts noted by the hook (.parc/brouillons.json, `cree_le`); {} when unreadable."""
    notes = parc.lire_json(parc.INTERNE / 'brouillons.json', {})
    notes = notes.get('brouillons') if isinstance(notes, dict) else None
    return {e['cle']: e['cree_le'][:10] for e in notes or [] if isinstance(e, dict) and isinstance(e.get('cle'), str)
            and isinstance(e.get('cree_le'), str) and DATE.match(e['cree_le'][:10])}


def brouillons_du_jour(brouillons, aujourdhui):
    """A Slack draft shows for 3 working days at most after it was written (`depuis`, else the hook's `cree_le`), then
    goes by itself, « Fait » or not (PM, Q42, 2026-11-09). Without a date it cannot be bounded: it goes. A Gmail draft
    stays until it is sent or marked « Fait »."""
    notes, sortie = None, []
    for x in brouillons:
        if x['outil'] == 'slack':
            depuis = x['depuis']
            if not depuis:
                notes = _cree_le_des_notes() if notes is None else notes
                depuis = notes.get(x['cle'], '')
            try:
                cree = dt.date.fromisoformat(depuis)
            except ValueError:
                continue
            if jours_ouvres_apres(cree, aujourdhui) > SLACK_JOURS_OUVRES:
                continue
        sortie.append(x)
    return sortie


def _jour_de(genere_le):
    """La date locale d'un instant ISO (sans fuseau : déjà locale), None si illisible."""
    try:
        d = dt.datetime.fromisoformat(str(genere_le).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return (d.astimezone() if d.tzinfo else d).date()


def lire(maintenant=None):
    """Le contenu validé de matin.json, ou None quand il est absent, illisible, sans `genere_le` lisible, ou pas
    d'aujourd'hui. Aucun élément marqué fait n'est retiré ici : voir `pour_la_page`."""
    maintenant = time.time() if maintenant is None else maintenant
    brut = parc.lire_json(_sortie() / 'matin.json', None)
    if not isinstance(brut, dict):
        return None
    jour = _jour_de(brut.get('genere_le'))
    if jour is None or jour != dt.date.fromtimestamp(maintenant):
        return None
    return {'genere_le': brut['genere_le'], 'jour': brut.get('jour') if brut.get('jour') in JOURS else 'normale',
            'agenda': _liste(brut.get('agenda'), PLAFOND_AGENDA, _agenda),
            'a_traiter': _liste(brut.get('a_traiter'), PLAFOND_A_TRAITER, _a_traiter),
            'regle': _liste(brut.get('regle'), PLAFOND_REGLE, _regle),
            'preparer_demain': _liste(brut.get('preparer_demain'), PLAFOND_PREPARER_DEMAIN, _preparer),
            'reunions_sans_cr': _liste(brut.get('reunions_sans_cr'), PLAFOND_REUNIONS, _reunion),
            'sans_reponse': _liste(brut.get('sans_reponse'), PLAFOND_SANS_REPONSE, _sans_reponse),
            'brouillons': brouillons_du_jour(_liste(brut.get('brouillons'), 100, _brouillon), jour)[:PLAFOND_BROUILLONS]}


def tache_du_matin():
    """La tâche planifiée « Point du matin » existe sur ce Mac (sans elle, rien n'est promis : pas de retard)."""
    return (pathlib.Path.home() / '.claude' / 'scheduled-tasks' / 'point-du-matin' / 'SKILL.md').exists()


def dernier_passage():
    """La date (dt.date) du dernier matin.json écrit, quel que soit son jour, ou None."""
    brut = parc.lire_json(_sortie() / 'matin.json', None)
    return _jour_de(brut.get('genere_le')) if isinstance(brut, dict) else None


def retard(maintenant=None):
    """« Point du matin pas passé aujourd'hui (dernier : JJ/MM) » quand la tâche existe, qu'on est un jour ouvré
    (lundi-vendredi) après son heure et sa marge, et que le point d'aujourd'hui manque ; sinon None. Un contenu d'un
    autre jour n'est jamais montré comme celui d'aujourd'hui : la page et mon-studio.md disent ce retard à la place."""
    maintenant = time.time() if maintenant is None else maintenant
    quand = dt.datetime.fromtimestamp(maintenant)
    limite = quand.replace(hour=HEURE_TACHE[0], minute=HEURE_TACHE[1], second=0, microsecond=0) \
        + dt.timedelta(minutes=MARGE_MIN)
    if quand.weekday() >= 5 or quand < limite or lire(maintenant) is not None or not tache_du_matin():
        return None
    jour = dernier_passage()
    return "Point du matin pas passé aujourd'hui" + (f" (dernier : {jour.strftime('%d/%m')})" if jour else '')


# --- « Fait » ---------------------------------------------------------------------------------------------

def _etat_chemin():
    return _sortie() / 'matin-etat.json'


def _aujourdhui(maintenant):
    return dt.date.fromtimestamp(maintenant).isoformat()


def _maintenant(maintenant):
    """The local time, ISO: the tasks may run no shell command but the plugin's, so `date` would wait on a prompt."""
    return dt.datetime.fromtimestamp(maintenant).isoformat(timespec='seconds')


def _sans_tmp():
    """A matin.json.tmp left by an earlier run goes: the Write tool would not overwrite a file it has not read, and
    reading it would wait on a prompt nobody answers (2026-11-10, independent review)."""
    try:
        (_sortie() / 'matin.json.tmp').unlink()
    except OSError:
        pass


def empreinte(bloc, x):
    """What « Fait » closed, besides its key: the normalized title (the subject and the recipient for a draft). The
    morning task may write a new request under the same key (a new message in the same thread): it then comes back."""
    texte = ' '.join((x.get('objet') or '', x.get('destinataire') or '')) if bloc == 'brouillons' else x.get('titre') or ''
    plat = unicodedata.normalize('NFKD', texte.casefold())
    plat = ''.join(c for c in plat if not unicodedata.combining(c))
    return hashlib.sha1(' '.join(re.findall(r'\w+', plat)).encode('utf-8')).hexdigest()[:12]


def fermes():
    """The items marked « Fait » by hand, any day: {cle: {'le': AAAA-MM-JJ, 'empreinte': fingerprint}}. The older state
    is read too (a date alone, a day's done items `jours`, the drafts seen `brouillons_vus`): no fingerprint, the key
    alone closes."""
    e = parc.lire_json(_etat_chemin(), {})
    if not isinstance(e, dict):
        return {}
    sortie = {}
    f = e.get('fermes')
    for k, v in (f.items() if isinstance(f, dict) else ()):
        if isinstance(k, str) and isinstance(v, str):
            sortie[k] = {'le': v, 'empreinte': ''}
        elif isinstance(k, str) and isinstance(v, dict) and isinstance(v.get('le'), str):
            sortie[k] = {'le': v['le'], 'empreinte': v['empreinte'] if isinstance(v.get('empreinte'), str) else ''}
    jours = e.get('jours')
    for jour, cles in (jours.items() if isinstance(jours, dict) else ()):
        for c in cles if isinstance(cles, list) and isinstance(jour, str) else ():
            if isinstance(c, str):
                sortie.setdefault(c, {'le': jour, 'empreinte': ''})
    vus = e.get('brouillons_vus')
    for c in vus if isinstance(vus, list) else ():
        if isinstance(c, str):
            sortie.setdefault(c, {'le': '', 'empreinte': ''})
    return sortie


def est_ferme(bloc, x, deja):
    """True when this very item was closed: same key and, when the closing kept one, same fingerprint."""
    f = deja.get(x['cle'])
    return bool(f) and (not f['empreinte'] or f['empreinte'] == empreinte(bloc, x))


BLOCS_FERMABLES = ('a_traiter', 'preparer_demain', 'brouillons', 'sans_reponse')


def cles_fermables(m):
    """The keys « Fait » can close in a point of the day: à traiter, préparer demain, brouillons."""
    return {x['cle'] for bloc in BLOCS_FERMABLES for x in m.get(bloc) or []}


def fait(cle, maintenant=None):
    """« Fait » on an item of today's matin.json (à traiter, préparer demain, brouillon): it leaves for good, the same
    item written again by a later morning task stays hidden; a new title under the same key comes back. ValueError for
    an unknown key or one already done."""
    maintenant = time.time() if maintenant is None else maintenant
    m = lire(maintenant)
    trouve = [(b, x) for b in BLOCS_FERMABLES for x in (m or {}).get(b) or [] if x['cle'] == cle] if isinstance(cle, str) else []
    if not trouve:
        raise ValueError('élément inconnu')
    bloc, x = trouve[0]
    deja = fermes()
    if est_ferme(bloc, x, deja):
        raise ValueError('élément déjà fait')
    deja[cle] = {'le': _aujourdhui(maintenant), 'empreinte': empreinte(bloc, x)}
    gardees = sorted(deja.items(), key=lambda kv: kv[1]['le'], reverse=True)[:FERMES_MAX]
    contenu = {'version': 3, 'fermes': dict(sorted(gardees))}
    parc.ecrire_atomique(_etat_chemin(), json.dumps(contenu, ensure_ascii=False, indent=1))
    return {'fait': cle}


def pour_la_page(maintenant=None):
    """Ce que la page affiche : {'etat': 'pas_passe'} quand le point d'aujourd'hui n'est pas là, sinon le contenu
    sans les éléments faits."""
    maintenant = time.time() if maintenant is None else maintenant
    _sans_tmp()
    m = lire(maintenant)
    if m is None:
        return {'etat': 'pas_passe'}
    deja = fermes()
    for bloc in BLOCS_FERMABLES:
        m[bloc] = [x for x in m[bloc] if not est_ferme(bloc, x, deja)]
    return dict(m, etat='ok')


# --- Ce que les tâches du matin n'ont pas à lire elles-mêmes -------------------------------------------------

def _projets_json():
    brut = parc.lire_json(_sortie() / 'projets.json', None)
    return brut if isinstance(brut, dict) else {}


def _dates_de_comptes_rendus(dossier, maintenant):
    """Les jours (AAAA-MM-JJ) des JOURS_CR derniers jours qui ont un fichier dans un dossier `reunions` du Studio, à
    trois niveaux au plus : la date du nom du fichier, sinon celle de sa modification."""
    debut = dt.date.fromtimestamp(maintenant) - dt.timedelta(days=JOURS_CR)
    jours, racine = set(), pathlib.Path(dossier)
    for motif in ('reunions', '*/reunions', '*/*/reunions'):
        try:
            dossiers = list(racine.glob(motif))
        except OSError:
            continue
        for d in dossiers:
            try:
                fichiers = [f for f in d.iterdir() if f.is_file() and not f.name.startswith('.')]
            except OSError:
                continue
            for f in fichiers:
                m = DATE_NOM.search(f.name)
                try:
                    jour = dt.date(*map(int, m.groups())) if m else dt.date.fromtimestamp(f.stat().st_mtime)
                except (ValueError, OSError):
                    continue
                if jour >= debut:
                    jours.add(jour.isoformat())
    return sorted(jours)


def preparer(maintenant=None):
    """Pour la tâche du matin : {'stop': raison} quand le point d'aujourd'hui est déjà écrit, sinon ce qu'elle n'a pas
    à lire : `studios`, `deja_releve` (les « À toi de jouer » ouverts) et `comptes_rendus` (projets où elle est PM)."""
    maintenant = time.time() if maintenant is None else maintenant
    _sans_tmp()
    if lire(maintenant) is not None:
        return {'stop': "le point d'aujourd'hui est déjà écrit"}
    pj = _projets_json()
    studios = [{'nom': _texte(x.get('nom'), 80), 'dossier': x.get('dossier'), 'role': x.get('role')}
               for x in pj.get('studios') or [] if isinstance(x, dict) and isinstance(x.get('dossier'), str)]
    releve = []
    for p in pj.get('projets') or []:
        for l in (p.get('lignes') or []) if isinstance(p, dict) else []:
            if isinstance(l, dict) and l.get('type') == 'a_toi' and len(releve) < A_TOI_MAX:
                releve.append({'projet': _texte(p.get('nom'), 80), 'titre': _texte(l.get('titre'), 200),
                               'lien': _lien(l.get('lien'))})
    comptes_rendus = {s['nom']: _dates_de_comptes_rendus(s['dossier'], maintenant)
                      for s in studios if s['role'] == 'pm'}
    sortie = {'aujourdhui': _aujourdhui(maintenant), 'maintenant': _maintenant(maintenant), 'studios': studios,
              'deja_releve': releve, 'comptes_rendus': comptes_rendus,
              'brouillons': brouillons_a_verifier(studios, maintenant)}
    conflits = passes_de_la_semaine(studios, maintenant)
    if conflits:
        sortie.update(conflits=conflits, conflits_consigne=CONSIGNE_CONFLITS + _charger_conflits().CONSIGNE_JUGEMENT)
    return sortie


# --- La passe des conflits du lundi (PM, Q18, 2026-11-15) ----------------------------------------------------
# Aucune tâche planifiée par Studio : le premier point du matin de la semaine (le lundi, ou le jour ouvré suivant si
# le lundi n'a pas tourné) ouvre la passe de chaque Studio où la personne est PM, déjà vérifié une fois (« Dernier
# passage » au registre) et sans ingestion automatique active (elle inscrit ses cas elle-même). `preparer` rend leurs
# sujets ; la tâche les juge et les rend par l'outil `conflits_juger` du connecteur. Rien n'est marqué dans les
# documents : les décisions vont au registre, les marquages sûrs attendent le go du PM dans la session des conflits.

# The Monday gestures, given with the subjects only when there are some: the daily prompt stays short.
CONSIGNE_CONFLITS = (
    "Chaque entrée de `conflits` : `studio`, `plan`, `sujets` (leur nombre) et `texte`, les sujets à juger avec leurs "
    "extraits. Pour chaque entrée, juge son `texte` comme dit plus bas, sans rien lire d'autre, puis appelle l'outil "
    "`conflits_juger` du connecteur mon-studio, une fois, avec `plan` tel quel et `jugements`. Il les inscrit au registre "
    "du Studio ; rien n'est marqué dans les documents. Un jugement mal formé est écarté par l'outil, qui le dit : ne le "
    "rappelle pas pour ce Studio. S'il répond « Refusé », passe au Studio suivant. Enfin, ajoute à ta réponse une ligne "
    "par Studio : son nom et le compte rendu de l'outil.\n\n")


def _semaine_chemin():
    return parc.INTERNE / 'conflits-semaine.json'


def _charger_conflits():
    """conflits.py : sa copie à côté de ce fichier (~/Mon Studio/.parc), sinon celle du plugin."""
    for chemin in (ICI / 'conflits.py', ICI.parent.parent / 'conflits' / 'scripts' / 'conflits.py'):
        if chemin.exists():
            spec = importlib.util.spec_from_file_location('conflits_matin', chemin)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError('conflits.py')


def passes_de_la_semaine(studios, maintenant):
    """[{studio, plan, sujets, texte}] : les passes à juger aujourd'hui, une fois par semaine ; [] sinon. Une passe qui
    dépasse ce qui reste du plafond (conflits.PASSE_MATIN_CARACTERES) attend : le lundi suivant relit depuis le même
    « Dernier passage ». Un échec n'arrête jamais le point du matin."""
    an, semaine, _ = dt.date.fromtimestamp(maintenant).isocalendar()
    cle = f'{an}-S{semaine:02d}'
    etat = parc.lire_json(_semaine_chemin(), {})
    if isinstance(etat, dict) and etat.get('semaine') == cle:
        return []
    try:
        parc.ecrire_atomique(_semaine_chemin(), json.dumps({'semaine': cle, 'le': _maintenant(maintenant)}))
        c = _charger_conflits()
    except Exception:
        return []
    # What the pass did of each checked Studio, kept with the week's marker (2026-11-17): the « Conflits » tab says
    # « re-read », « skipped » or « too large » with its reason instead of « up to date ».
    sortie, reste, faits = [], c.PASSE_MATIN_CARACTERES, {}
    for s in studios:
        if s.get('role') != 'pm':
            continue
        try:
            if not c.est_un_studio(s['dossier']):
                continue
            if not c.registre.lire_fichier(c.registre.chemin_du_studio(s['dossier']))['dernier_passage']:
                continue                       # never checked: the first check has its own line and its own words
            if c.ingestion_active(s['dossier'], maintenant):
                faits[s['dossier']] = {'etat': 'ingestion'}
                continue
            x = c.passe_du_matin(s['dossier'], reste)
        except Exception:
            faits[s['dossier']] = {'etat': 'erreur'}
            continue
        if x and not x.get('trop'):
            reste -= len(x['texte'])
            sortie.append({'studio': s['nom'], 'plan': x['plan'], 'sujets': x['sujets'], 'texte': x['texte']})
            faits[s['dossier']] = {'etat': 'ouverte', 'sujets': x['sujets']}
        else:
            faits[s['dossier']] = {'etat': 'trop', 'sujets': x['sujets']} if x else {'etat': 'rien'}
    try:
        parc.ecrire_atomique(_semaine_chemin(), json.dumps({'semaine': cle, 'le': _maintenant(maintenant), 'studios': faits},
                                                           ensure_ascii=False))
    except Exception:
        pass
    return sortie


def _projet_du_dossier(dossier, studios):
    """The `nom` of the Studio whose folder holds `dossier` (the deepest one), '' otherwise."""
    if not isinstance(dossier, str) or not dossier:
        return ''
    trouves = [s for s in studios if dossier == s['dossier'] or dossier.startswith(s['dossier'].rstrip('/') + '/')]
    return max(trouves, key=lambda s: len(s['dossier']))['nom'] if trouves else ''


def brouillons_a_verifier(studios, maintenant):
    """The drafts of .parc/brouillons.json the morning task has to check, and only those (2026-11-10): written before the
    last working day, not marked « Fait », a Slack one still inside its 3 working days; at most BROUILLONS_GMAIL_MAX Gmail
    drafts (one read each), the oldest first. The task no longer reads the file itself."""
    notes = parc.lire_json(parc.INTERNE / 'brouillons.json', {})
    notes = notes.get('brouillons') if isinstance(notes, dict) else None
    aujourdhui, deja, sortie, gmail = dt.date.fromtimestamp(maintenant), fermes(), [], 0
    entrees = [e for e in notes or [] if isinstance(e, dict) and e.get('outil') in OUTILS and isinstance(e.get('cle'), str)
               and isinstance(e.get('cree_le'), str) and DATE.match(e['cree_le'][:10])]
    for e in sorted(entrees, key=lambda e: e['cree_le']):
        try:
            n = jours_ouvres_apres(dt.date.fromisoformat(e['cree_le'][:10]), aujourdhui)
        except ValueError:
            continue
        x = {'cle': _texte(e['cle'], CLE_MAX), 'outil': e['outil'], 'brouillon': _texte(e.get('brouillon'), 120),
             'destinataire': _texte(e.get('destinataire'), 120), 'objet': _texte(e.get('objet'), TITRE_MAX),
             'canal': _texte(e.get('canal'), 120), 'fil': _texte(e.get('fil'), 80), 'lien': _lien(e.get('lien')),
             'projet': _projet_du_dossier(e.get('dossier'), studios), 'depuis': e['cree_le'][:10]}
        if n < 2 or (e['outil'] == 'slack' and n > SLACK_JOURS_OUVRES) or est_ferme('brouillons', x, deja):
            continue
        if e['outil'] == 'gmail':
            if gmail >= BROUILLONS_GMAIL_MAX:
                continue
            gmail += 1
        sortie.append(x)
    return sortie


def _verifs_chemin():
    return _sortie() / 'matin-verif.json'


def verifier(maintenant=None):
    """Pour la vérification : {'stop': raison}, ou {'a_verifier': [{cle, source, lien}]} et le passage est compté."""
    maintenant = time.time() if maintenant is None else maintenant
    m = lire(maintenant)
    if m is None:
        return {'stop': "pas de point du matin aujourd'hui"}
    deja = fermes()
    ouverts = [{'cle': x['cle'], 'source': x['source'], 'lien': x['lien']} for x in m['a_traiter']
               if not est_ferme('a_traiter', x, deja)]
    if not ouverts:
        return {'stop': 'plus rien à traiter'}
    jour = _aujourdhui(maintenant)
    compte = parc.lire_json(_verifs_chemin(), {})
    n = compte.get(jour, 0) if isinstance(compte, dict) and isinstance(compte.get(jour), int) else 0
    if n >= VERIFS_MAX:
        return {'stop': f'{VERIFS_MAX} vérifications déjà faites aujourd\'hui'}
    parc.ecrire_atomique(_verifs_chemin(), json.dumps({jour: n + 1}))
    # The whole point too (2026-11-10): the task rewrites it without reading any file.
    point = parc.lire_json(_sortie() / 'matin.json', None)
    return {'maintenant': _maintenant(maintenant), 'a_verifier': ouverts, 'point': point}


def ecrire(texte):
    """Puts `texte`, the whole point as the task writes it, in place of matin.json, atomically, when it is a JSON object
    with a readable `genere_le`. Returns (True, report) or (False, reason); refused, matin.json stays as it is. The task
    gives the text, never a file (2026-11-10: a file tool outside the task's folder waits on a prompt nobody answers)."""
    _sans_tmp()
    try:
        brut = json.loads(texte)
    except (TypeError, ValueError) as exc:
        return False, f'JSON illisible ({exc.__class__.__name__})'
    if not isinstance(brut, dict):
        return False, "ce n'est pas un objet JSON"
    if _jour_de(brut.get('genere_le')) is None:
        return False, 'genere_le manquant ou illisible'
    parc.ecrire_atomique(_sortie() / 'matin.json', json.dumps(brut, ensure_ascii=False, indent=1))
    return True, 'matin.json écrit'


def main(args):
    if args == ['ecrire']:
        ok, texte = ecrire(sys.stdin.read())
        print(texte if ok else f'Refusé : {texte}.')
        return 0 if ok else 2
    if args in (['preparer'], ['verifier']):
        r = preparer() if args[0] == 'preparer' else verifier()
        print(f"stop : {r['stop']}" if 'stop' in r else json.dumps(r, ensure_ascii=False))
        return 0
    if args[:1] == ['fait'] and len(args) == 2:
        try:
            fait(args[1])
        except ValueError as exc:
            print(f'Refusé : {exc} ({args[1]}).')
            return 2
        print(f'Fait : {args[1]}.')
        return 0
    if args:
        print(__doc__)
        return 2
    m = pour_la_page()
    if m['etat'] != 'ok':
        print((retard() or 'Point du matin pas encore passé') + '.')
        return 0
    print(f"ok · journée {m['jour']} · à traiter {len(m['a_traiter'])} · réglé {len(m['regle'])} · "
          f"agenda {len(m['agenda'])} · réunions sans compte rendu {len(m['reunions_sans_cr'])} · "
          f"préparer demain {len(m['preparer_demain'])} · brouillons pas envoyés {len(m['brouillons'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
