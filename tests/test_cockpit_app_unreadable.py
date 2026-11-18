"""Tests: when Mon Studio can no longer read the app, it says so: python3 -m unittest discover -s tests

The foreman-pm 0.7 pilot (« fais le point »), 2026-10-27: an empty board must never let the PM believe nothing waits
for him when Mon Studio simply no longer reads the app. `construire(…)['lecture_app']` is {'etat': 'ok' | 'hors_service',
'raison': …}: out of service when the app's card folder is missing, when no card is readable, when the cards no
longer carry the identifiers Mon Studio reads (the app changed their shape), or when cards exist but none of their
transcripts is found. The page, the local screens and the connector show it; the pilot repeats it to the PM."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)


class AppUnreadable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS, parc.INTERNE)
        parc.APP, parc.TRANSCRIPTS = root / 'app', root / 'transcripts'
        parc.CHANTIERS = root / 'chantiers'
        parc.CHANTIERS.mkdir()
        (parc.TRANSCRIPTS / 'proj').mkdir(parents=True)
        parc.INTERNE = root / 'interne'
        parc.INTERNE.mkdir()
        self.read_once()

    def read_once(self):
        """Mon Studio has read the app once on this Mac: an absence now means it became unreadable."""
        (parc.INTERNE / parc.LECTURE_OK).write_text('2026-11-02T09:00:00\n')

    def tearDown(self):
        parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS, parc.INTERNE = self.saved
        self.tmp.cleanup()

    def card(self, **fields):
        folder = parc.APP / 'acct' / 'org'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'local_a.json').write_text(json.dumps(fields))

    def state(self):
        cache = {'version': parc.VERSION_CACHE, 'fiches': {}, 'transcripts': {}, 'suivi': {}, 'controle': {}}
        return parc.construire(7, 7, time.time(), cache)

    def test_missing_folder(self):
        st = self.state()['lecture_app']
        self.assertEqual(st['etat'], 'hors_service')
        self.assertIn('introuvable', st['raison'])

    def test_no_readable_card(self):
        (parc.APP / 'acct' / 'org').mkdir(parents=True)
        (parc.APP / 'acct' / 'org' / 'local_a.json').write_text('not json')
        self.assertIn('aucune session', self.state()['lecture_app']['raison'])

    def test_cards_that_changed_shape(self):
        self.card(id='local_a', transcript='cli-a', name='Kit A')        # renamed keys
        st = self.state()['lecture_app']
        self.assertEqual(st['etat'], 'hors_service')
        self.assertIn('autrement', st['raison'])

    def test_cards_without_any_transcript(self):
        self.card(sessionId='local_a', cliSessionId='cli-a', title='Kit A', cwd='/x')
        st = self.state()['lecture_app']
        self.assertEqual(st['etat'], 'hors_service')
        self.assertIn('aucun historique', st['raison'])

    def test_readable_app_is_ok(self):
        self.card(sessionId='local_a', cliSessionId='cli-a', title='Kit A', cwd='/x')
        (parc.TRANSCRIPTS / 'proj' / 'cli-a.jsonl').write_text('{}\n')
        self.assertEqual(self.state()['lecture_app'], {'etat': 'ok', 'raison': ''})

    def test_first_day_is_nothing_yet_not_out_of_service(self):
        # Never read on this Mac: no folder, no card, or a card whose transcript does not exist yet is the first day.
        (parc.INTERNE / parc.LECTURE_OK).unlink()
        e = self.state()
        self.assertEqual(e['lecture_app']['etat'], 'pas_encore')
        md = parc.rendre_md(e)
        self.assertNotIn("ne lit plus l'app", md)
        self.assertIn(parc.ACCUEIL, md)
        self.card(sessionId='local_a', cliSessionId='cli-a', title='Kit A', cwd='/x')
        self.assertEqual(self.state()['lecture_app']['etat'], 'pas_encore')
        self.assertIsNone(self.state()['sans_transcript'])
        # The first successful read is noted: from then on the same absence is out of service.
        (parc.TRANSCRIPTS / 'proj' / 'cli-a.jsonl').write_text('{}\n')
        self.assertEqual(self.state()['lecture_app']['etat'], 'ok')
        self.assertTrue((parc.INTERNE / parc.LECTURE_OK).exists())
        (parc.TRANSCRIPTS / 'proj' / 'cli-a.jsonl').unlink()
        self.assertEqual(self.state()['lecture_app']['etat'], 'hors_service')

    def test_an_install_from_before_the_mark_has_read_the_app(self):
        # An upgrade finds no mark: a cache of read transcripts, or a chantier mirror from before, says the app was
        # read on this Mac; a broken read then raises the alert, not the welcome line.
        (parc.INTERNE / parc.LECTURE_OK).unlink()
        (parc.INTERNE / 'cache.json').write_text(json.dumps({'version': 1, 'transcripts': {'/t/cli-a.jsonl': {}}}))
        self.assertEqual(self.state()['lecture_app']['etat'], 'hors_service')
        (parc.INTERNE / 'cache.json').write_text(json.dumps({'version': 1, 'transcripts': {}}))
        self.assertEqual(self.state()['lecture_app']['etat'], 'pas_encore')
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps({'chantier': 'Essai', 'sessionId': 'local_f', 'attentes': []}))
        self.assertEqual(self.state()['lecture_app']['etat'], 'hors_service')
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps({'chantier': 'Essai', 'sessionId': 'local_f', 'registre': True}))
        self.assertEqual(self.state()['lecture_app']['etat'], 'pas_encore')   # a register says nothing of the app

    def test_a_changed_shape_is_out_of_service_even_on_the_first_day(self):
        (parc.INTERNE / parc.LECTURE_OK).unlink()
        self.card(id='local_a', transcript='cli-a', name='Kit A')
        self.assertEqual(self.state()['lecture_app']['etat'], 'hors_service')

    def test_every_screen_says_it(self):
        e = self.state()
        self.assertEqual(parc.pour_la_page(e)['lecture_app']['etat'], 'hors_service')
        md = parc.rendre_md(e)
        self.assertIn("Mon Studio ne lit plus l'app", md)
        self.assertIn("Impossible de dire ce qui t'attend.", md)
        self.assertNotIn("Rien ne t'attend.", md)
        page = (ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html').read_text(encoding='utf-8')
        self.assertIn("Mon Studio ne lit plus l'app", page)


if __name__ == '__main__':
    unittest.main()
