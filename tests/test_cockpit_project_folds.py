"""The project view of Mon Studio (PM, 2026-11-12): a dot on the « Projet » tab with the lines that appeared since the
last opening of the page (time kept in the browser, never a token), the first 5 old lines brought up under a short
main table, most urgent first and marked « ancienne », « Fils rouges » (the fold id stays « sujets ») unfolded and « Journal » folded by default."""
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
CLE = 'monstudio.vu.' + A
H = 3600 * 1000


def ligne(n, depuis, **more):
    return dict({'studio': 'projet', 'session': 'Pilier ' + n, 'cle': 'local_' + n, 'type': 'decision',
                 'affiche_suite': 'Q · ' + n + ' ?', 'projet': A, 'depuis': depuis}, **more)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class ProjectViewFolds(unittest.TestCase):

    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def vue(self, questions=(), anciennes=()):
        return {'dossier': A, 'nom': 'Client-A', 'genere': 0, 'questions': list(questions), 'anciennes': list(anciennes),
                'sujets': [{'titre': 'Pilier A', 'sessionId': 'local_a', 'etat': 'A avance.', 'depuis': 1, 'filles': []}],
                'tiers': [], 'journal': [{'depuis': 1, 'texte': 'Fait au journal.', 'session': 'Pilier A', 'genre': 'recap'}]}

    def page(self, vue, **more):
        return dict({'lignes': [], 'projets': [{'studio': 'projet', 'dossier': A, 'nom': 'Client-A'}],
                     'projet': vue, 'projetFixe': A}, **more)

    # --- the dot on « Projet » ---

    def test_dot_counts_the_lines_newer_than_the_last_opening_and_notes_this_one(self):
        now = int(time.time() * 1000)
        vue = self.vue([ligne('a', now - 1 * H), ligne('b', now - 2 * H), ligne('c', now - 30 * H)])
        out = self.run_page(self.page(vue, stockage={CLE: str(now - 5 * H)}))
        self.assertIn('<span class="pastille">2</span>', out['ongletProjet'])
        self.assertIn('2 nouvelles lignes', out['ongletProjetLabel'])
        self.assertGreaterEqual(int(out['stockageLu'][CLE]), now)   # this opening is the next one's reference

    def test_no_dot_on_the_first_opening_nor_without_storage(self):
        now = int(time.time() * 1000)
        vue = self.vue([ligne('a', now - 1 * H)])
        first = self.run_page(self.page(vue, stockage={}))
        self.assertNotIn('pastille', first['ongletProjet'])
        self.assertIn(CLE, first['stockageLu'])
        private = self.run_page(self.page(vue))                  # localStorage throws: the page still renders
        self.assertNotIn('pastille', private['ongletProjet'])
        self.assertIn('Q · a ?', private['projetQuestions'])

    # --- « Anciennes » brought up ---

    def test_short_table_brings_up_the_five_most_urgent_old_lines_marked(self):
        now = int(time.time() * 1000)
        vieilles = [ligne('v%d' % i, now - (200 + i) * H) for i in range(6)]
        vieilles.append(ligne('urgente', now - 400 * H, proche=True, echeance=now + 24 * H))
        out = self.run_page(self.page(self.vue([ligne('a', now - H)], vieilles)))
        q = out['projetQuestions']
        haut, _, bas = q.partition('Anciennes · ')
        self.assertEqual(haut.count('marque-ancienne'), 5)
        self.assertLess(haut.index('Q · urgente ?'), haut.index('Q · v0 ?'))   # most urgent first
        self.assertNotIn('Q · v5 ?', haut)                                     # the oldest stays folded
        self.assertTrue(bas.startswith('2<'))                                  # « Anciennes · 2 »: what is left

    def test_full_table_leaves_old_lines_folded(self):
        now = int(time.time() * 1000)
        out = self.run_page(self.page(self.vue([ligne(str(i), now - H) for i in range(5)], [ligne('v', now - 300 * H)])))
        self.assertNotIn('marque-ancienne', out['projetQuestions'])
        self.assertIn('Anciennes · 1', out['projetQuestions'])

    def test_main_board_brings_up_old_lines_too(self):
        now = int(time.time() * 1000)
        anciennes = [dict(ligne('v%d' % i, now - (200 + i) * H), studio='Alpha') for i in range(7)]
        out = self.run_page({'lignes': [], 'anciennes': anciennes})
        self.assertEqual(out['tableau'].count('marque-ancienne'), 5)
        self.assertNotIn('Rien de récent', out['tableau'])
        self.assertEqual(out['anciennes'].count('<td class="action">'), 2)   # the 2 others stay folded
        self.assertNotIn('Q · v0 ?', out['anciennes'])

    # --- « Fils rouges » (fold id « sujets ») unfolded, « Journal » folded ---

    def test_main_threads_unfolded_journal_folded_one_click_each(self):
        # The fold once called « Sujets » lists the studio's fils rouges, one row each (PM, 2026-11-17: unfolded).
        fils = [{'studio': 'Client-A', 'sessions': [{'sessionId': 'local_a', 'titre': 'Pilier A'}]}]
        out = self.run_page(self.page(self.vue(), fils_rouges=fils))
        self.assertFalse(out['sujetsReplies'])
        self.assertTrue(out['journalReplie'])
        self.assertEqual(out['sujetsOuvert'], 'true')
        self.assertIn('Pilier A', out['projetSujets'])
        self.assertNotIn('A avance.', out['projetSujets'], 'the session recaps are gone')
        out = self.run_page(self.page(self.vue(), fils_rouges=fils, cliquer=[['data-pli', 'sujets']]))
        self.assertTrue(out['sujetsReplies'])
        self.assertTrue(out['journalReplie'])
        out = self.run_page(self.page(self.vue(), fils_rouges=fils, cliquer=[['data-pli', 'journal']]))
        self.assertFalse(out['journalReplie'])

if __name__ == '__main__':
    unittest.main()
