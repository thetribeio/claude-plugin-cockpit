"""« Pour info : ce qui est entré au Studio » (PM, Q34 of 2026-11-06): python3 -m unittest discover -s tests

Grouped by project, one short line per entry (its own short title, else its first twelve words), its origin (« Slack
#canal · Alex », « Mail · Robin », « Drive », « Fichier du Studio »), the detail on a click, one button: the task it
created (« Voir la tâche », the board's line highlighted), else its source link, else the Studio's file unfolded in the
page (« Lire », read-only tool `lire`: text only, capped, escaped, never raw HTML), else the Studio's session. « Fait »
hides it for good (`clore`), « Tout vu » the whole group. Studios, files and pages here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from test_cockpit_projets import Base, MONDAY, FRIDAY, MAIL

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

NOUVEAU = ("📬 Alpha · 2 nouveautés · 1 action pour toi\nÀ toi de jouer :\n"
           "- Répondre à Robin sur le devis ([source](https://mail.google.com/m1))\n"
           "Ce qui est entré :\n"
           "- Devis de Robin reçu : Mail de Robin (30/10) avec le devis signé ([source](https://mail.google.com/m1))\n"
           "- CR du COPIL rangé : #alpha-interne (Alex, Robin, 30/10) le compte rendu est au Studio ([source](3-dev/cr.md))\n"
           "- Slack #alpha-interne (Alex, 30/10 10:12) : la recette commence lundi, Sam prépare les jeux de données "
           "et Léo relit les cas de test avant vendredi\n")


class Titles(Base):
    def test_short_title_or_first_twelve_words(self):
        t = self.p.titre_et_detail
        self.assertEqual(t('Devis reçu', 'le détail'), ('Devis reçu', 'le détail'))
        titre, detail = t('Slack #alpha (Alex, 30/10 10:12)', 'la recette commence lundi, Sam prépare les jeux de données et Léo relit')
        self.assertEqual(titre, 'la recette commence lundi, Sam prépare les jeux de données et Léo …')
        self.assertTrue(detail.startswith('Slack #alpha'))
        long = ' '.join(f'mot{i}' for i in range(20))
        self.assertEqual(t(long, '')[0], ' '.join(f'mot{i}' for i in range(12)) + ' …')

    def test_origin(self):
        o = self.p.origine_entree
        self.assertEqual(o('https://acme.slack.com/archives/C1/p2', '#alpha-interne (Alex, 04/11 16:09) : x'), 'Slack #alpha-interne · Alex')
        self.assertEqual(o('3-dev/cr.md', 'Slack #alpha-interne (Alex, Robin, Charlie, 05/11) : x'), 'Slack #alpha-interne · Alex, Robin')
        self.assertEqual(o('https://mail.google.com/m1', 'Devis reçu : Mail de Robin (30/10) avec le devis'), 'Mail · Robin')
        self.assertEqual(o('https://docs.google.com/d/1', 'Maquette v2 : nouvelle version'), 'Drive')
        self.assertEqual(o('2-cadrage/notes.md', 'Notes rangées : le plan'), 'Fichier du Studio')
        self.assertEqual(o('', 'Rien ne dit d’où'), '')


class Entries(Base):
    def test_live_entries_carry_title_origin_and_the_task_they_created(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        out = self.compute()
        m = self.p.matin_pour_la_page(MONDAY, self.metas, out)
        e = {x['titre']: x for x in m['entre_studio']}
        tache = next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi')
        self.assertEqual(e['Devis de Robin reçu']['tache'], tache)
        self.assertEqual(e['Devis de Robin reçu']['origine'], 'Mail · Robin')
        self.assertEqual(e['CR du COPIL rangé']['tache'], None)
        self.assertEqual(e['CR du COPIL rangé']['lien'], '3-dev/cr.md')
        self.assertEqual(e['CR du COPIL rangé']['origine'], 'Slack #alpha-interne · Alex, Robin')
        vieux = next(x for x in m['entre_studio'] if x['detail'].startswith('Slack #alpha-interne (Alex, 30/10 10:12)'))
        self.assertTrue(vieux['titre'].startswith('la recette commence lundi'))

    def test_seen_entries_leave_and_are_not_counted_as_closed(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        out = self.compute()
        cle = self.p.matin_pour_la_page(MONDAY, self.metas, out)['entre_studio'][0]['cle']
        self.p.fermer(cle, MONDAY + 60)
        out = self.compute(MONDAY + 120)
        m = self.p.matin_pour_la_page(MONDAY + 120, self.metas, out)
        self.assertNotIn(cle, [x['cle'] for x in m['entre_studio']])
        self.assertEqual(self.block(out)['fermees_depuis_hier'], 0)


class ReadAFile(Base):
    def setUp(self):
        super().setUp()
        (pathlib.Path(self.alpha) / '3-dev').mkdir()
        (pathlib.Path(self.alpha) / '3-dev' / 'cr.md').write_text('# CR\n\n- point **un**\n<script>x</script>\n', encoding='utf-8')

    def read(self, fichier, dossier=None):
        return self.p.lire_fichier(dossier or self.alpha, fichier, self.metas)

    def test_a_text_file_of_the_studio(self):
        r = self.read('3-dev/cr.md')
        self.assertEqual((r['fichier'], r['tronque']), ('3-dev/cr.md', False))
        self.assertIn('<script>x</script>', r['texte'])   # raw text: the page escapes it

    def test_refused(self):
        (pathlib.Path(self.alpha) / 'a.pdf').write_bytes(b'%PDF')
        dehors = pathlib.Path(self.root) / 'secret.md'
        dehors.write_text('secret', encoding='utf-8')
        os.symlink(dehors, pathlib.Path(self.alpha) / 'lien.md')
        for fichier in ('a.pdf', '../secret.md', '/etc/hosts', 'lien.md', '3-dev', 'absent.md'):
            with self.assertRaises(ValueError, msg=fichier):
                self.read(fichier)
        with self.assertRaises(ValueError):
            self.read('3-dev/cr.md', dossier=str(self.root))   # not a known Studio

    def test_capped(self):
        (pathlib.Path(self.alpha) / 'long.txt').write_text('é' * (self.p.LIRE_MAX), encoding='utf-8')
        r = self.read('long.txt')
        self.assertTrue(r['tronque'])
        self.assertLessEqual(len(r['texte'].encode('utf-8')), self.p.LIRE_MAX + 3)

    def test_from_the_snapshot_when_the_drive_refuses(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        self.compute()   # outside the connector: the snapshot keeps the text of the day's entry files
        lu = self.p.lire_instantane()
        self.assertIn('3-dev/cr.md', next(iter(lu.values()))['fichiers'])
        with mock.patch.object(self.p, 'lire_texte', side_effect=PermissionError('refusé')):
            r = self.p.lire_fichier(self.alpha, '3-dev/cr.md', self.metas)
        self.assertIn('point **un**', r['texte'])

    def test_the_connector_declares_lire_read_only(self):
        src = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py').read_text(encoding='utf-8')
        self.assertIn("{'name': 'lire'", src)
        bloc = src[src.index("{'name': 'lire'"):src.index("{'name': 'clore'")]
        self.assertIn("'readOnlyHint': True", bloc)
        install = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py').read_text(encoding='utf-8')
        self.assertIn("'clore', 'lire', 'gabarit']", install)


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    def run_page(self, **entree):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'p.json'
            data.write_text(json.dumps(entree, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def payload(self, **more):
        now = int(time.time() * 1000)
        liste = {'genere': now, 'page': None, 'studios': [], 'projets': [
            {'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [
                {'cle': 'aaaaaaaaaaa1', 'type': 'a_toi', 'titre': 'Répondre à Robin', 'detail': '', 'depuis': now - 3600000,
                 'session': MAIL, 'repli': False, 'echeance': None, 'lien': 'https://mail.google.com/m1', 'dossier': '/S/Alpha'}]}]}
        entrees = [
            {'cle': 'eeeeeeeeeee1', 'projet': 'Alpha', 'titre': 'Devis de Robin reçu', 'detail': 'Mail de Robin avec le devis',
             'origine': 'Mail · Robin', 'lien': 'https://mail.google.com/m1', 'tache': 'aaaaaaaaaaa1', 'dossier': '/S/Alpha'},
            {'cle': 'eeeeeeeeeee2', 'projet': 'Alpha', 'titre': 'CR rangé', 'detail': 'le CR', 'origine': 'Fichier du Studio',
             'lien': '3-dev/cr.md', 'tache': None, 'dossier': '/S/Alpha'},
            {'cle': 'eeeeeeeeeee3', 'projet': 'Beta', 'titre': 'Maquette v2', 'detail': 'nouvelle version', 'origine': 'Drive',
             'lien': 'https://docs.google.com/d/1', 'tache': None, 'dossier': '/S/Beta'},
            {'cle': 'eeeeeeeeeee4', 'projet': 'Beta', 'titre': 'Sans source', 'detail': 'rien', 'origine': '',
             'lien': '', 'tache': None, 'dossier': '/S/Beta', 'session': MAIL}]
        return dict({'lignes': [], 'liste_projets': liste, 'outils': ['lignes', 'clore', 'lire'],
                     'matin': {'etat': 'pas_passe', 'entre_studio': entrees, 'demandes': []}}, **more)

    def test_one_button_per_entry(self):
        h = self.run_page(**self.payload())['matin']
        rows = {r.split('</span>')[0].split('>')[-1]: r for r in h.split('<li class="entree">')[1:]}
        self.assertIn('data-voir-tache="aaaaaaaaaaa1"', rows['Devis de Robin reçu'])
        self.assertNotIn('Gmail ↗', rows['Devis de Robin reçu'])
        self.assertIn('data-lire="eeeeeeeeeee2"', rows['CR rangé'])
        self.assertNotIn('data-fichier', rows['CR rangé'])
        self.assertIn('>Drive ↗</a>', rows['Maquette v2'])
        self.assertIn(f'data-sid="{MAIL}"', rows['Sans source'])
        for r in rows.values():
            self.assertEqual(r.count('data-clore='), 1)   # « Fait »
        self.assertIn('data-tout-vu="Alpha"', h)
        self.assertIn('<span class="source">· Mail · Robin</span>', h)

    def test_the_task_button_goes_to_the_board_line(self):
        out = self.run_page(**self.payload(cliquer=[['data-onglet', 'matin'], ['data-voir-tache', 'aaaaaaaaaaa1']]))
        self.assertEqual(out['ongletTableauSelected'], 'true')
        self.assertIn('class="nouveau-studio surligne" data-demande="aaaaaaaaaaa1"', out['tableau'])

    def test_a_task_closed_meanwhile_falls_back_to_the_source(self):
        p = self.payload()
        p['liste_projets']['projets'][0]['lignes'] = []
        h = self.run_page(**p)['matin']
        self.assertNotIn('data-voir-tache', h)
        self.assertIn('Gmail ↗', h)

    def test_read_unfolds_the_file_escaped(self):
        texte = "# CR du COPIL\n\n- point **un**\n- point deux\n\n<script>alert(1)</script> et `code`\n"
        out = self.run_page(**self.payload(cliquer=[['data-lire', 'eeeeeeeeeee2']], lire={'texte': texte, 'tronque': True}))
        self.assertIn(['lire', {'dossier': '/S/Alpha', 'fichier': '3-dev/cr.md'}], out['appels'])
        h = out['matin']
        self.assertIn('<div class="lu"><h4>CR du COPIL</h4><ul><li>point <strong>un</strong></li><li>point deux</li></ul>', h)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; et <code>code</code>', h)
        self.assertNotIn('<script>', h)
        self.assertIn('seul le début est affiché', h)
        self.assertIn('>Replier</button>', h)

    def test_read_error_says_so(self):
        out = self.run_page(**self.payload(cliquer=[['data-lire', 'eeeeeeeeeee2']], lireErreur='tool_error'))
        self.assertIn('Fichier illisible depuis la page', out['matin'])

    def test_without_the_tool_no_read_button(self):
        h = self.run_page(**self.payload(outils=['lignes', 'clore']))['matin']
        self.assertNotIn('data-lire', h)

    def test_seen_and_all_seen(self):
        out = self.run_page(**self.payload(cliquer=[['data-clore', 'eeeeeeeeeee3']]))
        self.assertIn(['clore', {'cle': 'eeeeeeeeeee3'}], out['appels'])
        self.assertNotIn('Maquette v2', out['matin'])
        out = self.run_page(**self.payload(cliquer=[['data-tout-vu', 'Alpha']]))
        self.assertEqual([a for a in out['appels'] if a[0] == 'clore'],
                         [['clore', {'cle': 'eeeeeeeeeee1'}], ['clore', {'cle': 'eeeeeeeeeee2'}]])
        self.assertNotIn('Devis de Robin reçu', out['matin'])
        self.assertIn('Maquette v2', out['matin'])

    def test_the_line_unfolds_its_detail(self):
        h = self.run_page(**self.payload(cliquer=[['data-entre', 'eeeeeeeeeee3']]))['matin']
        self.assertIn('<span class="plus">nouvelle version</span>', h)
        self.assertNotIn('<span class="plus">le CR</span>', h)


if __name__ == '__main__':
    unittest.main()
