"""Tests: where a request the ingestion wrote without link, author or channel comes from (PM, Q9, 2026-11-19):
python3 -m unittest discover -s tests

The Session column names the session that ran that ingestion pass on that Studio (found by the pass time, the Studio's
folder and an ingestion-like title), with « Ouvrir » to it; with no such session (or a doubt), the Studio file where the
ingestion wrote the line. Never « Relevé par l'ingestion ». Sessions, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import shutil
import subprocess
import tempfile
import os
import unittest

from test_cockpit_projets import Base, MONDAY, RUNNER, PAGE
from test_cockpit_board_actionable import a_toi, liste, rangee

RUN = MONDAY - 3 * 3600
REQUEST = 'Passer les accès de Sam dans le coffre et les retirer du canal.'
REPORT = '📬 Alpha · nouveautés\nÀ toi de jouer :\n- ' + REQUEST + '\nCe qui est entré :\n- Note (Ana) : rien.\n'


def sid(n):
    return f'local_00000000-0000-0000-0000-00000000f{n:03d}'


class Origin(Base):
    def setUp(self):
        super().setUp()
        self.metas = []

    def ingestion(self, n, title, debut, fin, cwd=None, archived=False, task=None):
        c = self.card(sid(n), cwd or self.alpha, title, fin, archived)
        c.update(creee=debut, tache=task)
        self.metas.append(c)
        return sid(n)

    def line(self, request=REQUEST, run=RUN, text=None):
        self.runs(self.alpha, (run, text or REPORT))
        return self.block(self.compute())['lignes'][0]

    def test_the_session_that_ran_the_pass_is_named_and_opens(self):
        pris = self.ingestion(1, 'Auto-ingestion Alpha', RUN - 200, RUN + 120)
        self.ingestion(2, 'Auto-ingestion Alpha', RUN - 86400, RUN - 86400 + 300)   # the day before
        self.ingestion(3, 'Auto-ingestion Alpha', RUN - 200, RUN + 120, cwd=self.root / 'ailleurs')   # another folder
        l = self.line()
        self.assertEqual(l['origine_session'], 'Auto-ingestion Alpha')
        self.assertEqual((l['session'], l['repli']), (pris, False))
        self.assertNotIn('origine_fichier', l)

    def test_the_pass_may_come_a_little_before_the_card_or_after_its_last_activity(self):
        self.ingestion(1, 'Studio auto-ingest Alpha', RUN + 60, RUN + 200)
        self.assertEqual(self.line()['origine_session'], 'Studio auto-ingest Alpha')
        self.metas.clear()
        self.ingestion(1, 'Studio auto-ingest Alpha', RUN - 900, RUN - 300)
        self.assertEqual(self.line()['origine_session'], 'Studio auto-ingest Alpha')

    def test_an_ingestion_title_or_task_or_the_mailbox_mark_is_preferred_to_a_human_session(self):
        self.ingestion(1, 'Kit A', RUN - 200, RUN + 120)   # active at that time, not an ingestion
        self.assertNotIn('origine_session', self.line())
        self.metas.clear()
        self.ingestion(1, 'Kit A', RUN - 200, RUN + 120)
        pris = self.ingestion(2, 'Tri du matin', RUN - 200, RUN + 120, task='studio-auto-ingest-71d94e7f')
        self.assertEqual(self.line()['session'], pris)
        self.metas.clear()
        pris = self.ingestion(3, '📬 Alpha', RUN - 200, RUN + 120)
        self.assertEqual(self.line()['session'], pris)

    def test_same_title_twice_names_it_and_opens_the_latest_started(self):
        self.ingestion(1, 'Ingestion auto alpha', RUN - 500, RUN + 100, archived=True)
        dernier = self.ingestion(2, 'Ingestion auto alpha', RUN - 100, RUN + 130, archived=True)
        l = self.line()
        self.assertEqual((l['origine_session'], l['session']), ('Ingestion auto alpha', dernier))

    def test_two_different_ingestion_titles_are_a_doubt_so_the_file(self):
        self.ingestion(1, 'Auto-ingestion Alpha', RUN - 200, RUN + 120)
        self.ingestion(2, 'Ingestion Alpha, essai', RUN - 100, RUN + 120)
        l = self.line()
        self.assertNotIn('origine_session', l)
        self.assertEqual(l['origine_fichier'], 'projet/.ingestion-auto-state.json')

    def test_no_session_in_the_window_gives_the_file_and_no_foreign_session(self):
        self.ingestion(1, 'Auto-ingestion Alpha', RUN + 3600, RUN + 4000)
        self.metas.append(self.card(sid(9), self.alpha, 'Cadrage', RUN + 60))
        l = self.line()
        self.assertEqual(l['origine_fichier'], 'projet/.ingestion-auto-state.json')
        self.assertNotIn('origine_session', l)
        self.assertNotIn(l['session'], (sid(1), sid(9)) if l['repli'] is False else ())

    def test_a_request_with_a_link_an_author_or_a_channel_keeps_its_origin(self):
        self.ingestion(1, 'Auto-ingestion Alpha', RUN - 200, RUN + 120)
        mail = 'Répondre au client ([source](https://mail.google.com/mail/u/0/#inbox/abc))'
        self.runs(self.alpha, (RUN, '📬 Alpha\nÀ toi de jouer :\n- ' + mail + '\n- Ana te demande si le planning est validé.\n'))
        for l in self.block(self.compute())['lignes']:
            self.assertNotIn('origine_session', l)
            self.assertNotIn('origine_fichier', l)


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class OriginPage(unittest.TestCase):
    def run_page(self, **entree):
        entree.setdefault('lignes', [])
        entree.setdefault('outils', ['lignes', 'ouvrir', 'clore'])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_the_column_and_the_source_name_the_session_with_its_open_button(self):
        out = self.run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Passer les accès dans le coffre', 'Passer les accès de Sam dans le coffre, sans délai, et les retirer du canal.',
                                                      session=sid(1), origine_session='Auto-ingestion Alpha')))
        r = rangee(out['tableau'], 'Passer les accès dans le coffre')
        self.assertNotIn('Relevé par l&#39;ingestion', r)
        self.assertGreaterEqual(r.count('Auto-ingestion Alpha'), 2, 'the Session column, then the source')
        self.assertIn(sid(1), r)
        self.assertNotIn('.ingestion-auto-state', r)

    def test_without_session_the_studio_file_is_shown(self):
        out = self.run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Passer les accès dans le coffre', 'Passer les accès de Sam dans le coffre, sans délai, et les retirer du canal.',
                                                      origine_fichier='projet/.ingestion-auto-state.json')))
        r = rangee(out['tableau'], 'Passer les accès dans le coffre')
        self.assertNotIn('Relevé par l&#39;ingestion', r)
        self.assertEqual(r.count('projet/.ingestion-auto-state.json'), 2)


if __name__ == '__main__':
    unittest.main()
