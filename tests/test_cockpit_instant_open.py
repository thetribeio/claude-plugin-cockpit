"""The board opens at once and is computed again cheaply (2026-11-23): python3 -m unittest discover -s tests

A reading of the board took 4 to 8 s on a PM's Mac, and the page showed nothing until it came. The connector now
answers the page's « lignes » at once with the last board it computed (in memory, or kept on disk by an earlier
instance), marked `frais: false`, computes it again in a background thread, and the page asks again within seconds.
A click that changes the board is never hidden by that kept board: the next « lignes » computes before answering.
The reading of each message is kept by its text, so a session whose transcript changes is read again, and the board
computed with what is kept equals the board computed from nothing. Sessions and folders here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from test_cockpit_permission_hook import load_connector

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
LOCAL, CLI = 'local_00000000-0000-0000-0000-0000000000e1', 'cli-instant'
ASKED_2 = "Le plan est prêt.\n\n## À trancher\n\n**Q2 · Format du CR** : court ou long ? Je recommande court."
ASKED_5 = "Deux options.\n\n## À trancher\n\n**Q5 · Hébergement** : chez le client ou chez nous ? Je recommande chez nous."


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.mon_studio = self.root / 'MS'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.app, self.transcripts = self.root / 'app', self.root / 'tr'
        self.app.mkdir()
        self.transcripts.mkdir()
        self.m = self.connector()

    def tearDown(self):
        for m in getattr(self, 'loaded', []):
            fil = m._fond['fil']
            if fil is not None:
                fil.join(10)
        self.tmp.cleanup()

    def connector(self):
        m = load_connector(self.mon_studio, self.app, self.transcripts)
        m.parc.pastilles = lambda: None
        self.loaded = getattr(self, 'loaded', []) + [m]
        return m

    def call(self, m, name, args=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.traiter({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args or {}}})
        return json.loads(buf.getvalue())['result']


class Counted(Base):
    """`_lignes` replaced by a counter: each computation returns its number, and may wait on an event."""
    def setUp(self):
        super().setUp()
        self.count(self.m)

    def count(self, m):
        m.n, m.porte, m.echec = 0, None, None

        def calcul():
            m.n += 1
            if m.porte is not None:
                m.porte.wait(10)
            if m.echec:
                raise RuntimeError(m.echec)
            return {'lignes': [], 'n': m.n}
        m._lignes = calcul
        return m

    def wait_background(self, m):
        fil = m._fond['fil']
        if fil is not None:
            fil.join(10)
        self.assertIsNone(m._fond['fil'])

    def age(self, m, s=60):
        m._dernier['fini'] = time.monotonic() - s

    def test_first_call_computes_then_a_stale_board_is_served_and_computed_again(self):
        m = self.m
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 1, 'frais': True})   # nothing kept: computed now
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 1, 'frais': True})   # just computed: fresh, none started
        self.assertEqual(m.n, 1)
        self.age(m)
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 1, 'frais': False})   # at once, the last board
        self.wait_background(m)
        self.assertEqual(m.n, 2)
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 2, 'frais': True})

    def test_one_computation_at_a_time(self):
        m = self.m
        m.lignes_page()
        self.age(m)
        m.porte = threading.Event()
        self.assertFalse(m.lignes_page()['frais'])
        for _ in range(3):   # the page asks again while the background computes: the same board, nothing started
            self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 1, 'frais': False})
        m.porte.set()
        self.wait_background(m)
        self.assertEqual((m.n, m.lignes_page()), (2, {'lignes': [], 'n': 2, 'frais': True}))

    def test_the_tool_answers_through_the_kept_board(self):
        m = self.m
        self.assertEqual(json.loads(self.call(m, 'lignes')['content'][0]['text'])['n'], 1)
        self.age(m)
        self.assertIs(json.loads(self.call(m, 'lignes')['content'][0]['text'])['frais'], False)
        self.wait_background(m)

    def test_a_restarted_instance_answers_at_once_with_the_board_kept_on_disk(self):
        self.m.lignes_page()
        self.assertTrue((self.mon_studio / '.parc' / 'lignes-derniere.json').is_file())
        m2 = self.count(self.connector())
        m2.porte = threading.Event()
        r = m2.lignes_page()   # answered before its own computation ends
        self.assertEqual(r, {'lignes': [], 'n': 1, 'frais': False})
        m2.porte.set()
        self.wait_background(m2)
        self.assertEqual(m2.lignes_page()['frais'], True)

    def test_a_board_kept_by_another_version_is_not_served(self):
        self.m.lignes_page()
        chemin = self.mon_studio / '.parc' / 'lignes-derniere.json'
        d = json.loads(chemin.read_text(encoding='utf-8'))
        d['plugin'] = '0.0.1'
        chemin.write_text(json.dumps(d), encoding='utf-8')
        m2 = self.count(self.connector())
        self.assertEqual(m2.lignes_page(), {'lignes': [], 'n': 1, 'frais': True})   # its own, computed now
        self.assertEqual(m2.n, 1)

    def test_a_click_is_never_hidden_by_the_kept_board(self):
        m = self.m
        m.lignes_page()
        self.assertTrue(self.call(m, 'clore', {'cle': 'f' * 12})['isError'])   # even a click that fails may have written
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 2, 'frais': True})   # computed before answering
        self.call(m, 'autorisations')   # read-only: the board kept stays good
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 2, 'frais': True})

    def test_a_click_during_a_background_computation_makes_its_board_stale(self):
        m = self.m
        m.lignes_page()
        self.age(m)
        m.porte = threading.Event()
        self.assertFalse(m.lignes_page()['frais'])   # computation 2 starts, reading the inputs before the click
        self.call(m, 'clore', {'cle': 'f' * 12})
        m.porte.set()
        self.wait_background(m)
        m.porte = None
        self.assertEqual(m.lignes_page(), {'lignes': [], 'n': 3, 'frais': True})

    def test_a_failed_background_computation_reaches_the_page(self):
        m = self.m
        m.lignes_page()
        self.age(m)
        m.echec = 'cassé'
        self.assertFalse(m.lignes_page()['frais'])   # the background fails
        self.wait_background(m)
        with self.assertRaises(RuntimeError):   # the next call computes, and the page sees the error as before
            m.lignes_page()
        r = self.call(m, 'lignes')
        self.assertTrue(r['isError'])
        m.echec = None
        self.assertTrue(m.lignes_page()['frais'])


class Session(Base):
    """A real computation over one session of the app: its transcript changes, its line changes."""
    def setUp(self):
        super().setUp()
        (self.app / 'acct' / 'org').mkdir(parents=True)
        self.studio = self.root / 'Studio-Essai'
        self.studio.mkdir()
        (self.app / 'acct' / 'org' / f'{LOCAL}.json').write_text(json.dumps(
            {'sessionId': LOCAL, 'cliSessionId': CLI, 'title': 'Essai · plan', 'cwd': str(self.studio),
             'lastActivityAt': int((time.time() - 3600) * 1000)}))
        (self.transcripts / 'proj').mkdir()
        self.transcript = self.transcripts / 'proj' / f'{CLI}.jsonl'

    def say(self, text, minutes_ago, mid):
        t = time.time() - minutes_ago * 60
        entries = [{'type': 'user', 'timestamp': iso(t - 60), 'origin': {'kind': 'human'}, 'message': {'content': 'On avance ?'}},
                   {'type': 'assistant', 'timestamp': iso(t),
                    'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}]
        self.transcript.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        os.utime(self.transcript, (t, t))

    def titres(self, r):
        return ' | '.join(str(l.get('affiche_titre') or l.get('titre') or '') for l in r['lignes'])

    def test_a_changed_transcript_is_read_again(self):
        self.say(ASKED_2, 30, 'm1')
        first = self.m.lignes()
        self.assertIn('Format du CR', self.titres(first))
        self.say(ASKED_5, 20, 'm2')
        second = self.m.lignes()
        self.assertIn('Hébergement', self.titres(second))
        self.assertNotIn('Format du CR', self.titres(second))

    def test_the_board_computed_with_what_is_kept_equals_the_board_computed_from_nothing(self):
        self.say(ASKED_2, 30, 'm1')
        parc = self.m.parc
        fige = time.time()
        real = time.time
        try:
            parc.time.time = lambda: fige   # one instant for both readings: only what is kept differs
            warm_up = self.m.lignes()
            kept = self.m.lignes()
            self.assertGreater(sum(len(x['res']) for x in parc._textes_lus) + len(parc._tris['res']), 0)
            for memo in parc._textes_lus:
                memo.update(gl=None, res={})
            parc._tris.update(gl=None, res={})
            parc._tables_lues.clear()
            parc._studios_dedans.clear()
            parc._journaux_lus.clear()
            parc._nom_projet.cache_clear()
            parc._norm_marqueur.cache_clear()
            parc._normpath.cache_clear()
            p = self.m.charger_projets()
            p._normaliser.cache_clear()
            p._dossier_normal.cache_clear()
            p._modules.clear()
            p._git_lu.update(cle=None, nom=None)
            fresh = self.m.lignes()
        finally:
            parc.time.time = real
        self.assertEqual(json.dumps(kept, sort_keys=True), json.dumps(fresh, sort_keys=True))
        self.assertEqual(json.dumps(warm_up, sort_keys=True), json.dumps(fresh, sort_keys=True))


class KeptReadings(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('parc_garde', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
        self.parc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.parc)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_kept_reading_equals_the_computation_and_is_never_changed_by_its_caller(self):
        p = self.parc
        for texte in (ASKED_2, ASKED_5, "Rien à faire de ton côté.", "Encore ouvert : Q5, Q7", ''):
            self.assertEqual(p.a_trancher(texte), p.a_trancher.calculer(texte))
            self.assertEqual(p.rappels_en_phrase(texte), p.rappels_en_phrase.calculer(texte))
            self.assertEqual(p.trier(texte), p._trier(texte))
        items, _ = p.a_trancher(ASKED_2)
        items[0]['titre'] = 'changé'
        self.assertNotEqual(p.a_trancher(ASKED_2)[0][0]['titre'], 'changé')

    def test_a_chantier_journal_is_read_again_when_it_changes(self):
        p = self.parc
        miroir = pathlib.Path(self.tmp.name) / 'essai.json'
        journal = miroir.with_suffix('.journal.jsonl')
        journal.write_text(json.dumps({'type': 'settled', 'doc': 'a.md'}) + '\n', encoding='utf-8')
        self.assertEqual(p.soldees_au_journal(miroir)[0], {'a.md'})
        with journal.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'settled', 'doc': 'b.md'}) + '\n')
        self.assertEqual(p.soldees_au_journal(miroir)[0], {'a.md', 'b.md'})

    def test_a_studio_inside_a_folder_is_seen_within_the_kept_time(self):
        p = self.parc
        d = pathlib.Path(self.tmp.name) / 'Groupe'
        (d / 'projet').mkdir(parents=True)
        self.assertFalse(p.contient_d_autres_studios(str(d)))
        (d / 'Sous-Studio' / 'projet').mkdir(parents=True)
        (d / 'Sous-Studio' / 'projet' / 'fiche-projet.md').write_text('# Fiche', encoding='utf-8')
        self.assertFalse(p.contient_d_autres_studios(str(d)))   # kept STUDIOS_DEDANS_S
        horodate, r = p._studios_dedans[str(d)]
        p._studios_dedans[str(d)] = (horodate - p.STUDIOS_DEDANS_S - 1, r)
        self.assertTrue(p.contient_d_autres_studios(str(d)))


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def run_page(self, **entree):
        entree.setdefault('lignes', [])
        entree.setdefault('outils', ['lignes', 'projet', 'ouvrir', 'clore'])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(entree, f)
        try:
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True,
                               timeout=60)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_stale_board_is_shown_then_read_again_within_seconds(self):
        out = self.run_page(frais=False, lancerMs=1500)
        self.assertIn(1500, out['minuteurs'])
        self.assertEqual(out['invalidations'], ['lignes'])
        self.assertNotIn('se charge', out['tableau'])

    def test_a_fresh_board_asks_nothing_more(self):
        out = self.run_page(frais=True, lancerMs=1500)
        self.assertNotIn(1500, out['minuteurs'])
        self.assertEqual(out['invalidations'], [])

    def test_the_fresh_board_after_a_stale_one_is_not_drawn_again_when_nothing_changed(self):
        out = self.run_page(frais=False, puisFrais=True)
        self.assertIs(out['redessine'], False)
        changed = self.run_page(frais=False, puisFrais=True, puisLignes=[
            {'studio': 'Studio-Essai', 'session': 'Essai · plan', 'cle': LOCAL, 'ouvrir': LOCAL, 'titre': 'Q5 · Hébergement',
             'type': 'decision', 'prio': 2}])
        self.assertIs(changed['redessine'], True)


if __name__ == '__main__':
    unittest.main()
