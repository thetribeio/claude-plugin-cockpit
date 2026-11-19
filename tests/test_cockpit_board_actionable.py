"""Tests: a board the PM can act on without opening the sessions (0.2.17): python3 -m unittest discover -s tests

1. A session's numbered line unfolds to its own question: the whole statement, its options, the recommendation, the
   files it cites (with « Lire »); never the bullets of the whole session in its place.
2. An ingestion request (« à toi ») has a short title that reads whole (cut on a word, never inside a command), its
   full text kept; its unfold exists only when it adds something (full text, what to type, the linked file).
3. A request the morning point lists as settled (`matin.json`, `regle`) with exactly the same link is closed, and its
   line says why; a mere resemblance of text closes nothing.
4. A file of the Studio is read in the page (« Lire », tool `lire`), never opened outside Claude unless the page cannot
   show it (« Ouvrir dans une autre application »); the snapshot keeps the requests' files; no new tool.
5. A request shows once: not repeated in the Projets block, nor in Today (whose count holds no double), nor as a
   request when it cites a question (« (Q2) ») already on the board.
6. The conflicts checks live in « Mise en route »; more than three Studios make one grouped line.
7. The Session column of a request says where it came from, as plain text: it opens nothing.
8. The button that opens a session says it opens at its start (the app has no anchor to a message).
Sessions, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

from test_cockpit_projets import Base, MONDAY, FRIDAY, local, utc

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
MAIL = 'local_00000000-0000-0000-0000-0000000000a1'

spec = importlib.util.spec_from_file_location('parc_tableau_actionnable', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here

SEPT = ("Voici le bilan.\n\n**À trancher**\n\n"
        + ''.join(f"Q{i} · Sujet {i} : on garde la règle {i} ?\n" for i in range(1, 7))
        + "Q7 · Format du compte rendu : lequel envoyer au client ? Le modèle est dans `2-cadrage/modele-cr.md`.\n"
          "1. Une page (recommandé)\n2. Un mail\n")


def session(texte, **more):
    return dict({'id': 'local_a', 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'non_lue': True, 'derniere': 1e9,
                 'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}, **more)


def board(texte):
    cards = [{'id': 'local_a', 'archivee': False, 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'parent': None}]
    return [parc.rang_page(l) for l in parc.tableau([session(texte)], cards, [], 7, 1e9 + 60, {})]


def report(*requests):
    return '📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {r}\n' for r in requests)


def state(mon_studio):
    return json.loads((mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))['lignes']


def run_page(**entree):
    now = int(time.time() * 1000)
    entree.setdefault('lignes', [])
    entree.setdefault('outils', ['lignes', 'projet', 'ouvrir', 'clore', 'lire'])
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(entree, f)
    try:
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout), now


def a_toi(cle, titre, texte=None, lien='', **more):
    return dict({'cle': cle, 'type': 'a_toi', 'titre': titre, 'texte': texte or titre, 'detail': '',
                 'depuis': int(time.time() * 1000) - 3600000, 'session': MAIL, 'repli': False, 'echeance': None,
                 'lien': lien, 'dossier': '/S/Alpha', 'ancienne': False, 'passage': int(time.time() * 1000) - 3600000}, **more)


def liste(*lignes, nom='Alpha', dossier='/S/Alpha'):
    return {'genere': 0, 'page': None, 'studios': [], 'projets': [
        {'nom': nom, 'dossier': dossier, 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': list(lignes)}]}


def rangee(html, texte):
    """The row that holds `texte` and its unfold row, if any."""
    debut = html.rfind('<tr', 0, html.index(texte))
    fin = html.index('</tr>', html.index(texte)) + 5
    if html.startswith('<tr class="detail"', fin):
        fin = html.index('</tr>', fin) + 5
    return html[debut:fin]


# --- 1 and 8 ---------------------------------------------------------------------------------------------

class OwnQuestion(unittest.TestCase):
    def test_a_numbered_line_carries_its_own_question_not_the_session_bullets(self):
        lignes = {l['affiche_titre'].split(' · ')[0]: l for l in board(SEPT)}
        q7 = lignes['Q7']
        self.assertFalse(q7.get('puces'), 'the session bullets no longer stand for the line')
        d = q7['depli']
        self.assertIn('Format du compte rendu', d['enonce'])
        self.assertIn('lequel envoyer au client', d['enonce'])
        self.assertNotIn('Q6', d['enonce'])
        self.assertEqual([o['libelle'] for o in d['options']], ['Une page', 'Un mail'])
        self.assertEqual([o['recommande'] for o in d['options']], [True, False])
        self.assertEqual(d['fichiers'], ['2-cadrage/modele-cr.md'])
        self.assertEqual(q7['dossier'], '/studios/Studio-Beta')
        self.assertIn('Sujet 2', lignes['Q2']['depli']['enonce'])

    def test_a_line_without_number_keeps_what_the_session_expects(self):
        lignes = board("J'ai fini l'analyse.\n\nDonne-moi le fichier des ventes. Valide aussi le périmètre.")
        self.assertTrue(lignes and lignes[0].get('puces'))

    def test_files_cited_outside_the_studio_are_not_offered(self):
        texte = ("**À trancher**\n\nQ1 · Relire : `/etc/hosts`, `../autre/a.md`, `/studios/Studio-Beta/notes/b.md` "
                 "et [la note](3-dev/c.txt) ?\n")
        self.assertEqual(board(texte)[0]['depli']['fichiers'], ['notes/b.md', '3-dev/c.txt'])


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class OwnQuestionPage(unittest.TestCase):
    LIGNE = {'studio': 'Beta', 'session': 'Démarrage', 'cle': 'local_a', 'type': 'decision', 'verbe': 'Trancher',
             'affiche_titre': 'Q7 · Format du compte rendu', 'affiche_suite': 'lequel', 'question': 'Q7', 'ouvrir': 'local_a',
             'complet': 'Q7 · Format du compte rendu : lequel envoyer ?', 'detail': 'Q7 · Format du compte rendu : lequel envoyer ?',
             'puces': ['Q1 · Sujet 1', 'Q2 · Sujet 2'], 'dossier': '/S/Beta',
             'depli': {'enonce': 'Q7 · Format du compte rendu : lequel envoyer au client ?',
                       'options': [{'libelle': 'Une page', 'recommande': True}, {'libelle': 'Un mail', 'recommande': False}],
                       'recommande': 'Une page', 'fichiers': ['2-cadrage/modele-cr.md']}}

    def test_the_unfold_shows_the_question_its_options_and_its_files(self):
        out, _ = run_page(lignes=[self.LIGNE])
        r = rangee(out['tableau'], 'Format du compte rendu')
        self.assertIn('lequel envoyer au client ?', r)
        self.assertIn('Une page', r)
        self.assertIn('<dt>Recommandé</dt>', r)   # the card's row, written once (« Recommandé » since 0.3.2)
        self.assertEqual(r.count('ecommand'), 1)
        self.assertIn('Un mail', r)
        self.assertIn('2-cadrage/modele-cr.md', r)
        self.assertIn('data-lecture=', r)
        self.assertNotIn('Q1 · Sujet 1', r, 'no other question of the session in its place')

    def test_lire_reads_a_cited_file_in_the_page(self):
        out, _ = run_page(lignes=[self.LIGNE], lire={'texte': '# Modèle\n\nUne page, trois parties.'},
                          cliquer=[['data-lecture', 'local_a|Q7|Q7 · Format du compte rendu|lequel|f|2-cadrage/modele-cr.md']])
        self.assertIn(['lire', {'dossier': '/S/Beta', 'fichier': '2-cadrage/modele-cr.md'}], out['appels'])
        self.assertIn('Une page, trois parties.', out['tableau'])
        self.assertFalse([a for a in out['appels'] if a[0] == 'ouvrir'])

    def test_the_open_button_says_the_session_opens_at_its_start(self):
        out, _ = run_page(lignes=[self.LIGNE])
        self.assertIn('à son début', rangee(out['tableau'], 'Format du compte rendu'))


# --- 2 -----------------------------------------------------------------------------------------------------

COMMANDE = ("Relis la proposition de tri des points de la réunion d'équipe de jeudi (deux points), puis donne ton "
            "« go » en tapant /studio:auto-ingest tri dans la session du Studio, au plus tard demain matin.")


class ShortTitle(Base):
    def test_a_long_request_has_a_title_cut_on_a_word_and_its_full_text(self):
        self.runs(self.alpha, (MONDAY - 600, report(COMMANDE)))
        line = self.block(self.compute())['lignes'][0]
        self.assertLessEqual(len(line['titre']), self.p.TITRE_COURT + 1)
        self.assertTrue(line['titre'].endswith('…'))
        coupe = line['titre'][:-1]
        self.assertTrue(COMMANDE.startswith(coupe))
        self.assertEqual(COMMANDE[len(coupe)], ' ', 'cut on a word')
        self.assertNotIn('/st', line['titre'][-12:])
        self.assertEqual(line['texte'], COMMANDE)
        self.assertEqual(line['commande'], '/studio:auto-ingest tri')

    def test_never_inside_a_command(self):
        t = self.p.titre_court('Pour lancer le tri de la réunion de jeudi avec toute l\'équipe, il faudra taper '
                               '/studio:auto-ingest tri dans la session')
        self.assertNotIn('/studio', t)
        self.assertTrue(t.endswith('…'))

    def test_a_short_title_before_a_colon_and_a_short_request_whole(self):
        self.assertEqual(self.p.titre_court('Relance du devis : le client attend notre réponse depuis lundi, avec le planning'),
                         'Relance du devis')
        self.assertEqual(self.p.titre_court('Envoyer le devis'), 'Envoyer le devis')
        self.assertEqual(self.p.titre_court('Slack #projet (A., 05/11) : envoyer le devis au client'),
                         'Slack #projet (A., 05/11) : envoyer le devis au client', 'an origin is not a title')


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class ShortTitlePage(unittest.TestCase):
    def test_no_unfold_when_it_adds_nothing(self):
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Envoyer le devis', lien='https://mail.google.com/x')))
        r = rangee(out['tableau'], 'Envoyer le devis')
        self.assertNotIn('class="detail"', r)
        self.assertNotIn('data-deplier', r)

    def test_the_unfold_shows_the_full_text_once(self):
        titre = 'Relis la proposition de tri des points de la réunion…'
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', titre, COMMANDE, commande='/studio:auto-ingest tri')))
        r = rangee(out['tableau'], titre)
        self.assertIn('class="detail"', r)
        self.assertEqual(r.count('Relis la proposition de tri'), 2, 'the title, then the full text, not the title twice')
        self.assertIn('au plus tard demain matin', r)
        self.assertIn('<code>/studio:auto-ingest tri</code>', r)
        self.assertNotIn('Relevé par l&#39;ingestion', r, 'never a name that is not a session')
        self.assertEqual(r.count('projet/.ingestion-auto-state.json'), 2, 'the Session column, then the source once')
        self.assertNotIn('Déclencheur', r)


# --- 3 -----------------------------------------------------------------------------------------------------

SLACK = 'https://exemple.slack.com/archives/C000/p100'


class SettledInTheMorningPoint(Base):
    def matin(self, quoi, lien, projet='Alpha', quand=MONDAY):
        (self.mon_studio / 'matin.json').write_text(json.dumps({
            'genere_le': dt.datetime.fromtimestamp(quand).astimezone().isoformat(), 'jour': 'normale', 'agenda': [],
            'a_traiter': [], 'regle': [{'qui': 'Toi', 'quand': 'hier', 'quoi': quoi, 'lien': lien, 'projet': projet}],
            'preparer_demain': [], 'reunions_sans_cr': [], 'brouillons': []}), encoding='utf-8')

    def test_same_link_closes_the_request_and_says_why(self):
        self.runs(self.alpha, (FRIDAY, report(f'Envoyer l\'invitation au daily ([source]({SLACK}))')))
        self.assertEqual(self.types(self.compute(MONDAY - 3600)), ['a_toi'])
        self.matin('Invitation au daily envoyée à l\'équipe.', SLACK)
        out = self.compute()
        self.assertEqual(self.types(out), [])
        ligne = next(iter(state(self.mon_studio).values()))
        self.assertEqual(ligne['par'], 'matin')
        self.assertIn('point du matin', ligne['journal'][-1]['texte'])
        self.assertIn('même lien', ligne['journal'][-1]['texte'])
        self.assertIn('réglé au point du matin', self.block(out)['fermees_titres'][0])

    def test_a_resemblance_of_text_closes_nothing(self):
        self.runs(self.alpha, (FRIDAY, report(f'Envoyer l\'invitation au daily ([source]({SLACK}))')))
        self.matin('Envoyer l\'invitation au daily', 'https://exemple.slack.com/archives/C000/p999')
        self.assertEqual(self.types(self.compute()), ['a_toi'])

    def test_same_link_in_another_project_closes_nothing(self):
        self.runs(self.alpha, (FRIDAY, report(f'Envoyer l\'invitation au daily ([source]({SLACK}))')))
        self.matin('Invitation envoyée.', SLACK, projet='Autre')
        self.assertEqual(self.types(self.compute()), ['a_toi'])


# --- 4 -----------------------------------------------------------------------------------------------------

class RequestFilesInTheSnapshot(Base):
    def test_the_file_of_a_request_is_kept_for_the_connector(self):
        (pathlib.Path(self.alpha) / 'notes').mkdir()
        (pathlib.Path(self.alpha) / 'notes' / 'tri.md').write_text('# Tri\n\nDeux points proposés.', encoding='utf-8')
        self.runs(self.alpha, (FRIDAY - 4 * 86400, report('Valider le tri ([source](notes/tri.md))')))
        s = self.p.lire_sources(self.alpha, MONDAY)
        self.assertIn('notes/tri.md', s['fichiers'])
        self.assertIn('Deux points proposés.', s['fichiers']['notes/tri.md']['texte'])


class NoNewTool(unittest.TestCase):
    def test_the_connector_declares_the_same_tools(self):
        import re
        src = (SCRIPTS / 'mcp_mon_studio.py').read_text(encoding='utf-8')
        page = PAGE.read_text(encoding='utf-8')
        appels = set(re.findall(r'callTool\(SERVEUR, "([a-z_]+)"', page)) | set(re.findall(r'watchTool\(SERVEUR, "([a-z_]+)"', page))
        self.assertLessEqual(appels, {'lignes', 'projet', 'ouvrir', 'autorisations', 'decider', 'attentes', 'repondre', 'clore', 'lire'})
        self.assertEqual(sorted(set(re.findall(r"\{'name': '([a-z_]+)'", src))),
                         sorted(['lignes', 'projet', 'ouvrir', 'autorisations', 'decider', 'attentes', 'repondre', 'clore',
                                 'lire', 'gabarit', 'matin_ecrire', 'conflits_juger', 'slack_juger', 'slack_ouvertes']))


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class FilesInThePage(unittest.TestCase):
    def test_a_text_file_is_read_in_the_row(self):
        lp = liste(a_toi('aaaaaaaaaaa1', 'Valider le tri', lien='notes/tri.md'))
        out, _ = run_page(liste_projets=lp, lire={'texte': 'Deux points proposés.'},
                          cliquer=[['data-lecture', 'aaaaaaaaaaa1|f|notes/tri.md']])
        r = rangee(out['tableau'], 'Valider le tri')
        self.assertNotIn('Fichier ↗', out['tableauAvant'])
        self.assertIn('>Lire<', out['tableauAvant'])
        self.assertIn(['lire', {'dossier': '/S/Alpha', 'fichier': 'notes/tri.md'}], out['appels'])
        self.assertIn('Deux points proposés.', r)
        self.assertFalse([a for a in out['appels'] if a[0] == 'ouvrir'])

    def test_a_file_the_page_cannot_show_has_a_discreet_second_gesture(self):
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Relire le devis', lien='2-cadrage/devis.pdf')))
        r = rangee(out['tableau'], 'Relire le devis')
        self.assertNotIn('Fichier ↗', r)
        self.assertIn('Ouvrir dans une autre application', r)
        self.assertIn('data-fichier="2-cadrage/devis.pdf"', r)


# --- 5 -----------------------------------------------------------------------------------------------------

class RequestCarriedByAQuestion(Base):
    def test_a_request_citing_a_question_on_the_board_is_not_a_second_line(self):
        self.runs(self.alpha, (MONDAY - 600, report('Valider le tri de la réunion (Q2)', 'Envoyer le devis')))
        self.table = [self.question('Tri de la réunion', 'Q2')]
        out = self.compute()
        titres = [l['titre'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi']
        self.assertEqual(titres, ['Envoyer le devis'])
        self.table = []
        titres = [l['titre'] for l in self.block(self.compute(MONDAY + 60))['lignes'] if l['type'] == 'a_toi']
        self.assertEqual(sorted(titres), ['Envoyer le devis', 'Valider le tri de la réunion (Q2)'], 'back once Q2 left')


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class OnceOnThePage(unittest.TestCase):
    def test_the_projects_block_repeats_neither_questions_nor_entries(self):
        now = int(time.time() * 1000)
        lp = liste({'cle': 'bbbbbbbbbbb1', 'type': 'question', 'titre': 'Q5 · Format du CR', 'detail': '', 'depuis': now,
                    'session': MAIL, 'repli': False},
                   {'cle': 'bbbbbbbbbbb2', 'type': 'entree', 'titre': 'CR du COPIL', 'detail': 'rangé', 'depuis': now,
                    'session': MAIL, 'repli': False, 'lien': ''},
                   {'cle': 'bbbbbbbbbbb3', 'type': 'reunion', 'titre': 'Point client', 'detail': '2026-11-10', 'depuis': now,
                    'session': MAIL, 'repli': False})
        out, _ = run_page(liste_projets=lp, matin={'etat': 'pas_passe'})
        self.assertNotIn('Format du CR', out['projets'])
        self.assertNotIn('CR du COPIL', out['projets'])
        # The meetings without minutes moved to Today, the morning stand-up (PM, 2026-11-17).
        self.assertNotIn('Point client', out['projets'])
        self.assertIn('Point client', out['matin'])

    def test_today_does_not_list_the_board_requests_again_nor_count_them(self):
        lp = liste(a_toi('aaaaaaaaaaa1', 'Envoyer le devis'), a_toi('aaaaaaaaaaa2', 'Caler le point'))
        matin = {'etat': 'ok', 'jour': 'normale', 'agenda': [], 'regle': [], 'preparer_demain': [], 'brouillons': [],
                 'entre_studio': [], 'a_traiter': [{'cle': 'm1', 'titre': 'Répondre à la cliente', 'phrase': '', 'source': 'gmail',
                                                    'lien': 'https://mail.google.com/y', 'projet': 'Alpha'}],
                 'demandes': [{'cle': 'aaaaaaaaaaa1', 'titre': 'Envoyer le devis', 'projet': 'Alpha', 'echeance': None, 'lien': '',
                               'dossier': '/S/Alpha', 'depuis': 0, 'session': MAIL, 'repli': False},
                              {'cle': 'aaaaaaaaaaa2', 'titre': 'Caler le point', 'projet': 'Alpha', 'echeance': None, 'lien': '',
                               'dossier': '/S/Alpha', 'depuis': 0, 'session': MAIL, 'repli': False}]}
        out, _ = run_page(liste_projets=lp, matin=matin)
        self.assertNotIn('Envoyer le devis', out['matin'])
        self.assertIn('>1<', out['ongletMatin'], 'the count holds no double')
        self.assertNotIn('au tableau', out['matin'])   # not even their number (PM, 2026-11-17: the board does it)
        self.assertEqual(out['tableau'].count('Envoyer le devis'), 1)


# --- 6 -----------------------------------------------------------------------------------------------------

@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class ConflictChecksInSetup(unittest.TestCase):
    def verifier(self, n):
        projets = []
        for i in range(n):
            projets.append({'nom': f'Studio {i}', 'dossier': f'/S/{i}', 'role': 'pm', 'fermees_depuis_hier': 0,
                            'fermees_titres': [], 'lignes': [{'cle': f'ccccccccccc{i}', 'type': 'verifier',
                                                              'titre': 'Vérifier les conflits du Studio, une fois',
                                                              'detail': 'Le premier relevé.', 'depuis': 0,
                                                              'session': f'local_{i}', 'repli': False, 'copier': ''}]})
        return {'genere': 0, 'page': None, 'studios': [], 'projets': projets}

    def test_three_studios_three_lines(self):
        out, _ = run_page(liste_projets=self.verifier(3), mise_en_route={'etapes': [], 'matin': 'fait'})
        self.assertEqual(out['miseEnRoute'].count('<li'), 3)
        self.assertFalse(out['miseEnRouteHidden'])
        self.assertNotIn('Vérifier les conflits', out['tableau'])

    def test_more_than_three_one_grouped_line(self):
        out, _ = run_page(liste_projets=self.verifier(13), mise_en_route={'etapes': [], 'matin': 'fait'})
        m = out['miseEnRoute']
        self.assertEqual(m.count('<li id='), 1)
        self.assertIn('13 Studios', m)
        self.assertIn('Studio 12', m)
        self.assertEqual(m.count('data-sid="local_'), 13, 'each Studio keeps its button, in the line')
        self.assertIn('Pas pour moi', m)

    def test_pas_pour_moi_on_the_group_closes_each_line(self):
        cles = ' '.join(f'ccccccccccc{i}' for i in range(5))
        out, _ = run_page(liste_projets=self.verifier(5), mise_en_route={'etapes': [], 'matin': 'fait'},
                          cliquer=[['data-ecarter-groupe', cles]])
        self.assertEqual(sorted(a[1]['cle'] for a in out['appels'] if a[0] == 'clore'), sorted(cles.split()))
        self.assertTrue(out['miseEnRouteHidden'])

    def test_the_conflicts_tab_points_to_the_setup_block(self):
        page = PAGE.read_text(encoding='utf-8')
        self.assertNotIn('a sa ligne « Vérifier les conflits » au tableau', page)
        self.assertIn('« Mise en route »', page.split('Un Studio jamais vérifié a sa ligne', 1)[1][:120])


# --- 7 -----------------------------------------------------------------------------------------------------

@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class SessionColumnOfARequest(unittest.TestCase):
    def test_the_origin_is_plain_text(self):
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Envoyer le devis', lien=SLACK)))
        r = rangee(out['tableau'], 'Envoyer le devis')
        cellule = r.split('<td class="session">', 1)[1].split('</td>', 1)[0]
        self.assertNotIn('<button', cellule)
        self.assertIn('Slack', cellule)
        self.assertNotIn('Message Slack', cellule)
        self.assertIn(f'href="{SLACK}"', r, 'the link to Slack is its own button')


if __name__ == '__main__':
    unittest.main()
