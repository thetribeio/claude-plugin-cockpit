#!/usr/bin/env python3
"""Checks Mon Studio's lines on the real data of this Mac, read-only: a development tool, never copied to a PM's Mac.

    python3 scripts/controle_lignes.py            # « 0 anomalie », or one line per anomaly (exit code 1)

It computes what the connector gives the page (the board, each project's view, the Today tab) from a temporary copy of
~/Mon Studio (nothing is written there, nor in any Studio, nor in the app's files), with this repository's parc.py and
projets.py, then checks:

- buttons: the session each button opens exists and is not archived; on a chantier line, never the foreman when the
  question has a source session (PM, 2026-11-06);
- order: within a Studio, close deadline first, then a session blocked for less than 24 h, then the newest; each
  Studio in one block;
- project views: every Studio of projets.json that has live sessions has a non-empty view (accented folders too);
- « En un clic »: only what one click settles (a clic line carries its closed answer);
- duplicates: no request twice on the board, nor on a project's page;
- « Pour info : ce qui est entré au Studio »: each entry has a button that leads somewhere (its task, an https link, a
  readable file of the Studio, a document, or the Studio's session);
- drafts not sent (Today tab): each has a link that opens it in its own tool (Gmail, Slack), its « Ouvrir la session »
  opens a live session, and it is on no line of the board nor of a project's list;
- unfold: no line unfolds to the copied block of its message, nor to the trigger that only explains Mon Studio;
- answers (Q40): each line with answer buttons reaches a session a wake can join (known, not archived, with its CLI
  session id and an existing folder), and each answer it would send is a closed one, never free text;
- numbered questions (Q40): every numbered question « Qn · … » with closed answers (go, oui, numbered options, clic),
  chantier or not, has its buttons, answers by its own number, and keeps « Ouvrir la session »;
- « Fait » in Today (PM, 2026-11-09): every item of a rubric that asks for a gesture (à traiter, préparer demain,
  brouillons, nouvelles demandes, entrées au Studio) has a key the tool « clore » takes and would close, and, when node
  is there, the Today tab rendered from these data shows its « Fait » button, the only word of its closing buttons
  besides « Tout vu ».
- scheduled tasks (PM, 2026-11-10): each task whose last pass waits for the PM (a question, an authorization, an
  error, a cut turn) has exactly one line on the board, unless a chantier already asks about that pass; it opens that
  pass, names the task, and its answer buttons are its question's own options; a task whose last pass went well has
  none, and no line points to an older pass.

Run it before every installation. Each check is a function of plain data, tested on made-up data in
tests/test_cockpit_line_control.py.
"""
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

RACINE = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = RACINE / 'skills' / 'mon-studio' / 'scripts'
PAGE = RACINE / 'skills' / 'mon-studio' / 'assets' / 'page-epinglee.html'
ESSAI_PAGE = RACINE / 'tests' / 'tester-epinglee.js'
LOCAL = re.compile(r'^local_[0-9a-f-]{36}$')
PAVE = ('Juste avant, son message disait', 'Juste après, son message disait')
A_VERIFIER = "Ne dit pas si elle attend quelque chose de toi"   # parc.A_VERIFIER_SUITE: a line kept on purpose
TEXTE = re.compile(r'(?i)\.(md|txt|csv)$')
LIEN_BROUILLON = {'gmail': re.compile(r'^https://mail\.google\.com/'), 'slack': re.compile(r'^https://([a-z0-9-]+\.)*slack\.com/')}


def nfc(s):
    return unicodedata.normalize('NFC', s or '')


def session_a_ouvrir(l):
    """The session the line's verb opens, as the page computes it (sessionAOuvrir)."""
    if l.get('ouvrir'):
        return l['ouvrir']
    if str(l.get('cle') or '').startswith('local_'):
        return l['cle']
    m = re.search(r'(local_[0-9a-f-]{36})$', str(l.get('lien') or ''))
    return m.group(1) if m else ''


def libelle(l):
    texte = ' : '.join(x for x in (l.get('affiche_titre'), l.get('affiche_suite')) if x) or l.get('titre') or ''
    return f"{l.get('studio') or l.get('projet') or '?'} · {l.get('session') or ''} · {texte[:70]}"


def boutons(lignes, metas):
    """Each button's session exists and is live; a chantier line never opens its foreman when a source exists."""
    par_id = {m['id']: m for m in metas if m.get('id')}
    sortie = []
    for l in lignes:
        for quoi, sid in (('verbe', session_a_ouvrir(l)), ('Voir la session', l.get('source') if l.get('source') != session_a_ouvrir(l) else '')):
            if not sid or not str(sid).startswith('local_'):
                continue
            m = par_id.get(sid)
            if m is None:
                sortie.append(('boutons', libelle(l), f"le bouton « {quoi} » ouvre une session inconnue ({sid})"))
            elif m.get('archivee'):
                sortie.append(('boutons', libelle(l), f"le bouton « {quoi} » ouvre une session archivée ({m.get('titre')})"))
        source = l.get('source')
        if l.get('sujet') is not None and source and source != l.get('cle') and session_a_ouvrir(l) == l.get('cle'):
            sortie.append(('boutons', libelle(l), 'le verbe ouvre le contremaître alors que la question vient d\'une autre session'))
    return sortie


def tri(tableau, maintenant, rang_urgence):
    """The board's order: each Studio in one block; within it, rank, then close deadline, then the newest."""
    sortie, vus, avant = [], set(), None
    for l in tableau:
        if l['studio'] != avant:
            if l['studio'] in vus:
                sortie.append(('tri', libelle(l), 'son Studio apparaît en deux blocs'))
            vus.add(l['studio'])
            avant, precedente = l['studio'], None
        if l.get('attend') or l.get('apres'):
            continue   # placed right after the question it waits for
        cle = (rang_urgence(l, maintenant), (l.get('echeance') or 0) if l.get('proche') else 0,
               -max(l.get('depuis') or 0, l.get('reprise') or 0))
        if precedente is not None and cle < precedente:
            sortie.append(('tri', libelle(l), 'rangée après une ligne moins urgente ou plus ancienne'))
        precedente = cle
    return sortie


def vues_projet(studios, metas, vue):
    """Every Studio with live sessions has a non-empty project view (vue: dossier -> the page's payload)."""
    sortie = []
    for s in studios:
        d = nfc(s.get('dossier'))
        vivantes = [m for m in metas if not m.get('archivee') and m.get('cwd')
                    and (nfc(m['cwd']) == d or nfc(m['cwd']).startswith(d + os.sep))]
        if not vivantes:
            continue
        v = vue(s['dossier'])
        if v.get('introuvable') or not (v.get('sujets') or v.get('questions')):
            sortie.append(('vue projet', s.get('nom') or d, f"{len(vivantes)} session(s) vivante(s), vue projet vide"))
    return sortie


def un_clic(lignes):
    """« En un clic » holds only what one click settles: a clic line carries its closed answer (« ok »)."""
    return [('en un clic', libelle(l), 'ligne « clic » sans réponse en un clic : le clic ouvre la session')
            for l in lignes if l.get('type') == 'clic' and l.get('arret') != 'authorization' and not l.get('choix')]


def taches(automates, lignes, vises):
    """One line per scheduled task whose last pass waits (automates: `carte` or `arret`), none for the others."""
    sortie = []
    attend = {a['lien']: a for a in automates if a.get('lien') and (a.get('carte') or a.get('arret'))}
    passages = {a['lien'] for a in automates if a.get('lien')}
    par_passage = {}
    for l in lignes:
        if l.get('tache'):
            par_passage.setdefault(l.get('ouvrir'), []).append(l)
    for lien, ls in par_passage.items():
        if lien not in passages:
            sortie.append(('tâches planifiées', libelle(ls[0]), "ouvre un passage qui n'est pas le dernier de sa tâche"))
        elif lien not in attend:
            sortie.append(('tâches planifiées', libelle(ls[0]), "le dernier passage de la tâche va bien : la ligne aurait dû se fermer"))
        if len(ls) > 1:
            sortie.append(('tâches planifiées', libelle(ls[0]), f"{len(ls)} lignes pour un même passage"))
    for lien, a in attend.items():
        ls = par_passage.get(lien) or []
        if not ls:
            if lien not in vises:
                sortie.append(('tâches planifiées', a['nom'], "le dernier passage attend le PM, aucune ligne au tableau"))
            continue
        l = ls[0]
        if l['tache'] != a['nom']:
            sortie.append(('tâches planifiées', libelle(l), f"ne nomme pas sa tâche ({a['nom']})"))
        if l.get('choix'):
            options = [o.get('label') for q in (a.get('carte') or {}).get('menu') or [] for o in q.get('options') or []]
            if l.get('question') or not l.get('seule') or any(x not in options for x in l['choix']):
                sortie.append(('tâches planifiées', libelle(l), 'boutons de réponse hors des options de la question'))
    return sortie


def doublons(lignes, demandes, vues):
    """No request twice on the board (lines, and the ingestion's requests), nor on a project's page."""
    sortie = []

    def verifier(ou, items):
        vus = {}
        for l in items:
            k = (nfc(l.get('studio') or l.get('projet') or ''), session_a_ouvrir(l) or l.get('cle'),
                 re.sub(r'\s+', ' ', nfc(' : '.join(x for x in (l.get('affiche_titre'), l.get('affiche_suite') or l.get('titre')) if x))).lower())
            if k in vus:
                sortie.append(('doublon', libelle(l), f"deux fois sur {ou}"))
            vus[k] = 1
        cles = [l['cle'] for l in items if l.get('a_toi')]
        for c in set(cles):
            if cles.count(c) > 1:
                sortie.append(('doublon', c, f"demande deux fois sur {ou}"))
    verifier('le tableau', list(demandes) + list(lignes))
    for nom, items in vues.items():
        verifier(f"la page du projet {nom}", items)
    return sortie


def entrees(entre_studio, liste, lire_fichier):
    """Each entry has a button that leads somewhere: its open task, an https link, a readable text file of the Studio,
    another document of the Studio, or the Studio's session."""
    ouvertes = {l['cle'] for p in (liste or {}).get('projets') or [] for l in p.get('lignes') or [] if l.get('type') == 'a_toi'}
    sortie = []
    for x in entre_studio or []:
        lien = x.get('lien') or ''
        if x.get('tache') in ouvertes or lien.startswith('https://'):
            continue
        if lien and TEXTE.search(lien):
            try:
                lire_fichier(x.get('dossier'), lien)
                continue
            except Exception as exc:   # noqa: BLE001  the reason is what the PM would read
                sortie.append(('entrée', f"{x.get('projet')} · {x.get('titre') or x.get('phrase', '')[:60]}", f"« Lire » échouerait : {exc}"))
                continue
        if lien and x.get('dossier') and (pathlib.Path(x['dossier']) / lien).exists():
            continue
        if not lien and x.get('session'):
            continue
        sortie.append(('entrée', f"{x.get('projet')} · {x.get('titre') or x.get('phrase', '')[:60]}",
                       'aucun bouton ne mène quelque part (ni tâche, ni lien, ni fichier, ni session)'))
    return sortie


def brouillons(liste_b, lignes, liste, metas):
    """Each draft shown has a link that opens it, a live session if any, and is on no line of the board nor of a project."""
    vivantes = {m['id'] for m in metas if m.get('id') and not m.get('archivee')}
    ailleurs = list(lignes) + [l for p in (liste or {}).get('projets') or [] for l in p.get('lignes') or []]
    sortie = []
    for b in liste_b or []:
        nom = f"{b.get('projet') or '?'} · {b.get('outil')} · {(b.get('objet') or b.get('destinataire') or '')[:60]}"
        motif = LIEN_BROUILLON.get(b.get('outil'))
        if not motif or not motif.match(str(b.get('lien') or '')):
            sortie.append(('brouillon', nom, "pas de lien qui ouvre le brouillon"))
        if b.get('session') and b['session'] not in vivantes:
            sortie.append(('brouillon', nom, f"« Ouvrir la session » ouvre une session inconnue ou archivée ({b['session']})"))
        if any(l.get('cle') == b.get('cle') or (b.get('lien') and l.get('lien') == b.get('lien')) for l in ailleurs):
            sortie.append(('brouillon', nom, 'le brouillon apparaît au tableau ou dans un projet'))
    return sortie


def deplis(lignes, non_declaree, demande_au_pm=None, ligne_max=None):
    """No line unfolds to the copied block of its message, nor to the trigger that only explains Mon Studio. Short
    titles (PM, 2026-11-18): a question's unfold never repeats its title, a row holds on one line (ligne_max characters
    and its « … »), and a « Vérifier » line that waits for nothing (demande_au_pm) is not on the board."""
    sortie = []
    for l in lignes:
        q = l.get('depli') or {}
        titre = re.sub(r'\s*…$', '', l.get('affiche_titre') or '')
        if titre and len(titre) > 8 and str(q.get('question') or '').startswith(titre):
            sortie.append(('dépli', libelle(l), 'le dépli répète le titre de la ligne'))
        affiche = ' : '.join(x for x in (l.get('affiche_titre'), l.get('affiche_suite')) if x)
        if ligne_max and l.get('arret') != 'menu' and not l.get('menu') and len(affiche) > ligne_max + 5:
            sortie.append(('dépli', libelle(l), f'la ligne dépasse {ligne_max} caractères : deux lignes au tableau'))
        if demande_au_pm and l.get('type') == 'check' and l.get('complet') != A_VERIFIER \
                and not demande_au_pm(l.get('complet') or affiche):
            sortie.append(('dépli', libelle(l), "ligne d'information au tableau : elle n'attend rien du PM"))
        if l.get('puces'):
            continue   # the page unfolds to its bullets only
        if any(p in (l.get('detail') or '') for p in PAVE):
            sortie.append(('dépli', libelle(l), 'le dépli recopie le pavé du message'))
        if non_declaree and l.get('declencheur') == non_declaree:
            sortie.append(('dépli', libelle(l), 'le dépli explique la mécanique de Mon Studio'))
    return sortie


# « recommandé : … » (2026-11-10): the answer the question recommends in its own words, on one line, 60 characters at
# most (parc.RECOMMANDE_MAX); the connector checks its characters.
FERMEE = re.compile(r'^(?:Q\d{1,4} )?(?:go|oui|pas encore|ok|[1-9]\d?|recommandé : [^\n]{1,60})$')
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def session_de_la_reponse(l):
    """The session an answer goes to, as the page and the connector compute it: the one that asked, else the verb's."""
    return l['source'] if LOCAL.match(str(l.get('source') or '')) else session_a_ouvrir(l)


def reponses(lignes, metas):
    """Each line with answer buttons can be answered without opening its session (Q40), and only with closed words."""
    par_id = {m['id']: m for m in metas if m.get('id')}
    sortie = []
    for l in lignes:
        if not l.get('choix'):
            continue
        sid, q = session_de_la_reponse(l), l.get('question') or ''
        m = par_id.get(sid)
        if m is None or m.get('archivee'):
            sortie.append(('réponses', libelle(l), f"les boutons répondent à une session inconnue ou archivée ({sid or 'aucune'})"))
        elif not UUID.match(str(m.get('cli') or '')) or not os.path.isdir(str(m.get('cwd') or '')):
            sortie.append(('réponses', libelle(l), "la session ne peut pas être réveillée : identifiant ou dossier manquant"))
        for c in l['choix']:
            texte = f'{q} {c}' if q and l.get('copie_numero') is not False else c
            libre = not FERMEE.match(texte) and (q or '\n' in c or len(c) > 80)
            if libre:
                sortie.append(('réponses', libelle(l), f"réponse hors des formes fermées : « {texte[:40]} »"))
    return sortie


def questions_numerotees(lignes, choix_de_question, choix_fermes):
    """Every numbered question with closed answers has its buttons, answered by its number, and a session to open."""
    sortie = []
    for l in lignes:
        if l.get('arret'):
            continue
        if l.get('chantier'):
            if not l.get('question'):
                continue
            attendu = choix_fermes(l.get('type'), l.get('detail'), l.get('suite'))
        elif l.get('num') is not None and l.get('lecture') in ('format', 'rappel') and LOCAL.match(str(l.get('cle') or '')):
            attendu = choix_de_question(l.get('type'), l.get('titre'), l.get('suite'), l.get('brut') or l.get('detail'))
        else:
            continue
        if not attendu:
            continue
        if not l.get('choix'):
            sortie.append(('questions', libelle(l), 'question numérotée sans ses boutons de réponse'))
        elif not l.get('chantier') and l.get('question') != f"Q{l['num']}":
            sortie.append(('questions', libelle(l), 'les boutons ne répondent pas par le numéro de la question'))
        if not session_a_ouvrir(l):
            sortie.append(('questions', libelle(l), 'pas de « Ouvrir la session »'))
    return sortie


# Today's rubrics that ask for a gesture, and the attribute of the « Fait » button that closes each item: an item of
# matin.json (tool « clore » with matin: true) or a line of the list by project (tool « clore »). The agenda and
# « Réglé » only inform: no button. The new requests (`demandes`) are rows of the board, closed there (0.2.17).
TODAY_A_FERMER = {'a_traiter': 'data-matin-fait', 'preparer_demain': 'data-matin-fait', 'brouillons': 'data-matin-fait',
                  'entre_studio': 'data-clore'}
CLE_LIGNE = re.compile(r'^[0-9a-f]{12}$')
BOUTON_FERMER = re.compile(r'<button type="button" class="fait"[^>]*>([^<]*)</button>')
LIBELLES_FERMER = {'Fait', 'Vu', 'Tout vu'}   # « Vu » on an entry « Pour info » (2026-11-17)


def esc(s):
    """The page's esc()."""
    return html.escape(str(s), quote=True).replace('&#x27;', '&#39;')


def fermeture_today(matin, liste, html_today=None):
    """Every actionable item of Today has its « Fait »: a key the tool « clore » takes and would close (any key of 80
    characters at most for an item of the point of the day, an open line of the list by project otherwise) and, when the
    tab was rendered (`html_today`), its button; « Fait », « Vu » and « Tout vu » are the only words of its closing buttons."""
    ouvertes = {l.get('cle') for p in (liste or {}).get('projets') or [] for l in p.get('lignes') or []}
    sortie = []
    for bloc, attr in TODAY_A_FERMER.items():
        for x in (matin or {}).get(bloc) or []:
            cle = x.get('cle')
            nom = f"Today · {bloc} · {(x.get('titre') or x.get('objet') or x.get('phrase') or '')[:60]}"
            if attr == 'data-clore':
                ok = isinstance(cle, str) and bool(CLE_LIGNE.match(cle)) and cle in ouvertes
            else:
                ok = isinstance(cle, str) and 1 <= len(cle) <= 80
            if not ok:
                sortie.append(('fermeture', nom, 'aucune clé que « Fait » fermerait'))
            elif html_today is not None and f'{attr}="{esc(cle)}"' not in html_today:
                sortie.append(('fermeture', nom, 'pas de bouton « Fait »'))
    for mot in sorted(set(BOUTON_FERMER.findall(html_today or '')) - LIBELLES_FERMER):
        sortie.append(('fermeture', 'Today', f"un bouton de fermeture dit « {mot} » au lieu de « Fait », « Vu » ou « Tout vu »"))
    return sortie


def rendre_today(matin, liste, dossier):
    """The Today tab's HTML as the page renders it from these data (node, with tests/tester-epinglee.js and the tools
    « lignes » and « clore » declared), or None when node is not there. Writes only in `dossier`."""
    node = shutil.which('node')
    if not node or not ESSAI_PAGE.exists():
        return None
    entree = pathlib.Path(dossier) / 'today.json'
    entree.write_text(json.dumps({'lignes': [], 'matin': matin, 'liste_projets': liste, 'outils': ['lignes', 'clore']},
                                 ensure_ascii=False), encoding='utf-8')
    r = subprocess.run([node, str(ESSAI_PAGE), str(PAGE), str(entree)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"la page ne se rend pas : {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)['matin']


def calculer(mon_studio):
    """What the connector computes, from a copy of `mon_studio` (never written), with this repository's scripts."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='controle-lignes-'))
    copie = tmp / 'Mon Studio'
    shutil.copytree(mon_studio, copie, ignore=lambda d, noms: [n for n in noms if n.endswith('.sock')])
    os.environ['MON_STUDIO'] = str(copie)
    sys.path.insert(0, str(SCRIPTS))
    import parc  # noqa: E402
    import projets  # noqa: E402
    maintenant = time.time()
    cache = parc.charger_cache()
    e = parc.construire(int(os.environ.get('MON_STUDIO_JOURS', 7)), 7, maintenant, cache)
    metas = parc.fiches(cache)
    liste = projets.calculer(e=e, maintenant=maintenant, metas=metas, ecrire=False)
    matin = projets.matin_pour_la_page(maintenant, metas, liste)
    page = parc.pour_la_page(e)
    return {'parc': parc, 'projets': projets, 'e': e, 'metas': metas, 'liste': liste, 'matin': matin, 'page': page,
            'maintenant': maintenant, 'tmp': tmp}


def demandes_du_tableau(liste):
    """The ingestion's « À toi » requests as the page puts them on the board (fresh ones)."""
    out = []
    for p in (liste or {}).get('projets') or []:
        for l in p.get('lignes') or []:
            if l.get('type') == 'a_toi' and not l.get('ancienne'):
                out.append({'studio': p['nom'], 'cle': l['cle'], 'a_toi': True, 'titre': l['titre'], 'projet': p['dossier'],
                            'ouvrir': l.get('session') if not l.get('repli') else ''})
    return out


def controler(c):
    parc, projets, page = c['parc'], c['projets'], c['page']
    lignes = page['lignes'] + page.get('anciennes', [])
    vues, pages_projet = {}, {}
    for s in c['liste'].get('studios') or []:
        v = parc.vue_projet_pour_la_page(c['e'], s['dossier'])
        vues[s['dossier']] = v
        dem = [d for d in demandes_du_tableau(c['liste']) if nfc(d['projet']) == nfc(s['dossier'])]
        pages_projet[s.get('nom') or s['dossier']] = dem + (v.get('questions') or [])
    anomalies = []
    anomalies += boutons(lignes + [l for v in vues.values() for l in v.get('questions') or []], c['metas'])
    anomalies += tri(c['e']['tableau'], c['maintenant'], parc.rang_urgence)
    anomalies += vues_projet(c['liste'].get('studios') or [], c['metas'], lambda d: vues.get(d) or parc.vue_projet_pour_la_page(c['e'], d))
    anomalies += un_clic(page['lignes'])
    anomalies += doublons(page['lignes'], demandes_du_tableau(c['liste']), pages_projet)
    anomalies += entrees(c['matin'].get('entre_studio'), c['liste'],
                         lambda d, f: projets.lire_fichier(d, f, c['metas']))
    anomalies += brouillons((c['matin'] or {}).get('brouillons'), lignes, c['liste'], c['metas'])
    anomalies += deplis(lignes, parc.NON_DECLAREE, parc.demande_au_pm, parc.LIGNE_MAX)
    anomalies += reponses(lignes, c['metas'])
    anomalies += questions_numerotees(c['e']['tableau'] + (c['e'].get('anciennes') or []), parc.choix_de_question,
                                      parc.choix_fermes)
    anomalies += fermeture_today(c['matin'], c['liste'], rendre_today(c['matin'], c['liste'], c['tmp']))
    vises = {a.get('source') or a.get('sessionId') for ch in parc.chantiers_actifs(c['metas'])
             for a in ch.get('attentes') or []} - {None, ''}
    anomalies += taches(c['e']['automates'], lignes, vises)
    return anomalies


def main(argv):
    mon_studio = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path.home() / 'Mon Studio'
    c = calculer(mon_studio)
    try:
        anomalies = controler(c)
    finally:
        shutil.rmtree(c['tmp'], ignore_errors=True)
    if not anomalies:
        print('0 anomalie')
        return 0
    print(f"{len(anomalies)} anomalie{'s' if len(anomalies) > 1 else ''}")
    for regle, ligne, quoi in anomalies:
        print(f"- [{regle}] {ligne} : {quoi}")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
