"""Tests: a click on a project name at the top of the main board filters that board in place (PM, 2026-11-19).

The board keeps only that project's lines, in every band (« D'abord », « Ensuite », « Peut attendre », « Anciennes »),
session lines and ingestion requests alike. The project is shown as selected (aria-pressed), « Tout afficher » (or a second
click) brings everything back. It happens in the page: no tool call, no new page. « Vue projet » stays the way to the
project page. python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from test_cockpit_projets import RUNNER, PAGE
from test_cockpit_board_actionable import a_toi, liste

ALPHA, BETA = '/S/Alpha', '/S/Beta'
NOW = int(time.time() * 1000)


def sess(n, studio, titre, **more):
    return dict({'studio': studio, 'session': 'S' + n, 'cle': f'local_00000000-0000-0000-0000-0000000000{n}', 'type': 'go', 'verbe': 'Go',
                 'question': 'Q' + n, 'affiche_titre': titre, 'affiche_suite': '', 'depuis': NOW - 3600000}, **more)


def projets():
    a = liste(a_toi('aaaaaaaaaaa1', 'Demande Alpha', 'Demande Alpha', impact='fort'), nom='Alpha', dossier=ALPHA)['projets'][0]
    b = liste(a_toi('bbbbbbbbbbb1', 'Demande Beta', 'Demande Beta'), nom='Beta', dossier=BETA)['projets'][0]
    return {'genere': 0, 'page': None, 'studios': [], 'projets': [a, b]}


LIGNES = [sess('a1', 'Alpha', 'Session Alpha forte', impact='fort'), sess('a2', 'Alpha', 'Session Alpha normale'),
          sess('b1', 'Beta', 'Session Beta forte', impact='fort'), sess('b2', 'Beta', 'Session Beta normale')]
VUES = [{'studio': 'Alpha', 'dossier': ALPHA, 'nom': 'Alpha'}, {'studio': 'Beta', 'dossier': BETA, 'nom': 'Beta'}]


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Filter(unittest.TestCase):
    def page(self, *clics, **more):
        entree = dict({'lignes': LIGNES, 'projets': VUES, 'liste_projets': projets(), 'outils': ['lignes', 'projet', 'ouvrir', 'clore'],
                       'cliquer': [list(c) for c in clics]}, **more)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_without_a_click_everything_shows_and_nothing_is_selected(self):
        out = self.page()
        for t in ('Session Alpha forte', 'Session Beta normale', 'Demande Alpha', 'Demande Beta'):
            self.assertIn(t, out['tableau'])
        self.assertEqual(out['studios'].count('aria-pressed="true"'), 0)
        self.assertEqual(out['studios'].count('aria-pressed="false"'), 2)
        self.assertNotIn('Tout afficher', out['studios'])

    def test_the_click_keeps_only_that_project_across_every_band(self):
        out = self.page(('data-filtre', 'Alpha'))
        t = out['tableau']
        for x in ('Session Alpha forte', 'Session Alpha normale', 'Demande Alpha'):
            self.assertIn(x, t)
        for x in ('Session Beta forte', 'Session Beta normale', 'Demande Beta'):
            self.assertNotIn(x, t)
        self.assertIn("D'abord", t)
        self.assertIn('Ensuite', t, 'both bands of the project are there')

    def test_the_active_project_is_selected_and_the_way_back_is_visible(self):
        out = self.page(('data-filtre', 'Beta'))
        s = out['studios']
        self.assertEqual(s.count('aria-pressed="true"'), 1)
        self.assertRegex(s, r'aria-pressed="true"[^>]*>Beta')
        self.assertIn('data-filtre="" title="Remettre tous les projets">Tout afficher', s)

    def test_tout_afficher_and_a_second_click_bring_everything_back(self):
        for clics in ((('data-filtre', 'Alpha'), ('data-filtre', '')), (('data-filtre', 'Alpha'), ('data-filtre', 'Alpha'))):
            out = self.page(*clics)
            self.assertIn('Session Beta forte', out['tableau'])
            self.assertIn('Demande Beta', out['tableau'])
            self.assertNotIn('Tout afficher', out['studios'])
            self.assertEqual(out['studios'].count('aria-pressed="true"'), 0)

    def test_it_is_client_side_only(self):
        sans = self.page()
        avec = self.page(('data-filtre', 'Alpha'))
        self.assertEqual(avec['appels'], sans['appels'], 'no tool call at the click')

    def test_vue_projet_is_still_the_way_to_the_project_page(self):
        out = self.page(('data-filtre', 'Alpha'))
        self.assertIn('data-projet="' + ALPHA + '"', out['studios'])
        self.assertIn('data-projet="' + BETA + '"', out['studios'])
        self.assertNotIn('data-aller', out['studios'])

    def test_a_project_with_only_requests_has_its_button_and_its_count(self):
        out = self.page(lignes=[])
        self.assertIn('data-filtre="Alpha"', out['studios'])
        self.assertIn('Alpha <span class="n">· 1</span>', out['studios'])

    def test_a_project_without_lines_says_so_and_offers_the_way_back(self):
        out = self.page(('data-filtre', 'Gamma'))
        self.assertIn('Rien ne t\'attend sur « Gamma »', out['tableau'].replace('&#39;', "'"))
        self.assertIn('Tout afficher', out['studios'])


class Css(unittest.TestCase):
    def test_the_selected_project_looks_selected(self):
        css = PAGE.read_text(encoding='utf-8')
        self.assertIn('button.aller[aria-pressed="true"] { background:var(--accent)', css)


if __name__ == '__main__':
    unittest.main()
