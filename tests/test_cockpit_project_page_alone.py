"""A project's page shows no other project (PM, 2026-11-17): neither the sessions the rangement archived today, nor
the Studios bar, nor the Today/Conflits tabs, and its counter counts its own lines only. Only the main board spans every
project. Its « Fils rouges » are one row per session, the most recently active first. Data here is synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
A = '/Studios/Client-A'
H = 3600 * 1000


def ligne(n, studio, projet, depuis, **more):
    return dict({'studio': studio, 'session': 'Pilier ' + n, 'cle': 'local_' + n, 'type': 'decision',
                 'affiche_suite': 'Q · ' + n + ' ?', 'projet': projet, 'depuis': depuis}, **more)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class ProjectPageAlone(unittest.TestCase):

    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def donnees(self, now, **more):
        urgente = dict(impact='fort')
        autre = ligne('b', 'Beta', '/Studios/Beta', now - H, **urgente)
        sienne = ligne('a', 'Client-A', A, now - H, **urgente)
        vue = {'dossier': A, 'nom': 'Client-A', 'genere': 0, 'questions': [sienne], 'anciennes': [], 'tiers': [], 'journal': []}
        return dict({'lignes': [autre, sienne], 'projets': [{'studio': 'Client-A', 'dossier': A, 'nom': 'Client-A'}],
                     'projet': vue, 'rangees': [{'id': 'local_r', 'titre': 'Beta · rangée', 'quand': now}]}, **more)

    def test_the_main_board_keeps_every_project(self):
        now = int(time.time() * 1000)
        out = self.run_page(self.donnees(now))
        self.assertTrue(out['rangeesVisibles'])
        self.assertFalse(out['studiosHidden'])
        self.assertEqual(out['compte'], "2 à faire d'abord")

    def test_a_pinned_project_page_shows_nothing_of_another_project(self):
        now = int(time.time() * 1000)
        out = self.run_page(self.donnees(now, projetFixe=A))
        self.assertFalse(out['rangeesVisibles'])
        self.assertTrue(out['studiosHidden'])
        self.assertTrue(out['ongletsHidden'])
        self.assertTrue(out['boiteCachee'])
        self.assertEqual(out['compte'], "1 à faire d'abord")

    def test_the_project_view_opened_from_the_board_hides_the_rest(self):
        now = int(time.time() * 1000)
        out = self.run_page(self.donnees(now, cliquer=[['data-projet', A]]))
        self.assertFalse(out['projetCache'])
        self.assertFalse(out['rangeesVisibles'])
        self.assertTrue(out['studiosHidden'])
        self.assertTrue(out['ongletsHidden'])
        self.assertEqual(out['compte'], "1 à faire d'abord")

    def test_main_threads_are_rows_most_recent_first(self):
        now = int(time.time() * 1000)
        fils = [{'studio': 'Client-A', 'sessions': [
            {'sessionId': 'local_old', 'titre': 'Fil ancien', 'non_lue': False, 'derniere': now - 72 * H},
            {'sessionId': 'local_new', 'titre': 'Fil récent', 'non_lue': True, 'derniere': now - 2 * H}]}]
        out = self.run_page(self.donnees(now, projetFixe=A, fils_rouges=fils))
        s = out['projetSujets']
        self.assertIn('<table class="fils-rouges">', s)
        self.assertNotIn('class="fil"', s)                               # no more pill buttons
        self.assertLess(s.index('Fil récent'), s.index('Fil ancien'))
        self.assertEqual(s.count('Ouvrir ↗</button>'), 2)
        self.assertEqual(s.count('class="non-lue"'), 1)
        self.assertIn('2 h', s)
        self.assertIn('3 j', s)


if __name__ == '__main__':
    unittest.main()
