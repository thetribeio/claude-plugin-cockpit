"""The page's other readings answer at once too (2026-11-24): python3 -m unittest discover -s tests

On the PM's Mac, « projet » took 0.6 to 1.6 s at each opening and waited besides for the board's background
computation (CALCUL); « attentes » once took 11.89 s, right after a « lignes » that had started that computation: its
map of the app's sessions parsed every card of the app (1 MB each) at the first call after a start, and each card's
system call waited for the GIL held by the computation. Now « projet » is served like « lignes » (the last view of the
folder at once, `frais: false`, computed again in the background, one computation per folder, a click makes it
stale), and « attentes » and « autorisations » read the sessions from a kept map, refreshed by the board's computation,
never waiting for it. Sessions and folders here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock

from test_cockpit_instant_open import ASKED_2, LOCAL, CLI, PAGE, RUNNER, Base, Session

ASKED_7 = "Voilà.\n\n## À trancher\n\n**Q7 · Lot 2** : on le lance ? Je recommande oui."


class ProjetCounted(Base):
    """`_projet` replaced by a counter per folder: each computation returns its number, and may wait on an event."""
    def setUp(self):
        super().setUp()
        m = self.m
        m.n, m.porte, m.echec = {}, None, None

        def calcul(dossier):
            m.n[dossier] = m.n.get(dossier, 0) + 1
            if m.porte is not None:
                m.porte.wait(10)
            if m.echec:
                raise RuntimeError(m.echec)
            return {'dossier': dossier, 'n': m.n[dossier], 'version': m.VERSION}
        m._projet = calcul

    def tearDown(self):
        if self.m.porte is not None:
            self.m.porte.set()
        for st in list(self.m.GARDE_PROJET.etats.values()):
            if st['fil'] is not None:
                st['fil'].join(10)
        super().tearDown()

    def age(self, dossier, s=60):
        self.m.GARDE_PROJET.etats[dossier]['fini'] = time.monotonic() - s

    def wait(self, dossier):
        fil = self.m.GARDE_PROJET.etats[dossier]['fil']
        if fil is not None:
            fil.join(10)
        self.assertIsNone(self.m.GARDE_PROJET.etats[dossier]['fil'])

    def test_a_kept_view_is_served_at_once_then_computed_again(self):
        m = self.m
        self.assertEqual(m.projet({'dossier': '/a'}), {'dossier': '/a', 'n': 1, 'version': m.VERSION, 'frais': True})
        self.assertTrue(m.projet({'dossier': '/a'})['frais'])   # just computed: fresh, nothing started
        self.age('/a')
        r = m.projet({'dossier': '/a'})
        self.assertEqual((r['n'], r['frais']), (1, False))
        self.wait('/a')
        r = m.projet({'dossier': '/a'})
        self.assertEqual((r['n'], r['frais']), (2, True))

    def test_one_computation_per_folder(self):
        m = self.m
        m.projet({'dossier': '/a'})
        m.projet({'dossier': '/b'})
        self.age('/a')
        self.age('/b')
        m.porte = threading.Event()
        for _ in range(4):
            self.assertFalse(m.projet({'dossier': '/a'})['frais'])
            self.assertFalse(m.projet({'dossier': '/b'})['frais'])
        m.porte.set()
        self.wait('/a')
        self.wait('/b')
        self.assertEqual(m.n, {'/a': 2, '/b': 2})   # one more each, not four

    def test_a_click_makes_the_kept_view_stale(self):
        m = self.m
        m.projet({'dossier': '/a'})
        self.call(m, 'clore', {'cle': 'f' * 12})   # a tool that writes, even failing
        r = m.projet({'dossier': '/a'})
        self.assertEqual((r['n'], r['frais']), (2, True))   # computed before answering
        self.call(m, 'attentes')   # read-only: the kept view stays good
        self.assertEqual(m.projet({'dossier': '/a'})['n'], 2)

    def test_the_view_kept_does_not_wait_for_the_board(self):
        m = self.m
        m.projet({'dossier': '/a'})
        self.age('/a')
        tenu, fin = threading.Event(), threading.Event()

        def tenir():   # the board's computation, in the background, holds CALCUL
            with m.CALCUL:
                tenu.set()
                fin.wait(10)
        threading.Thread(target=tenir, daemon=True).start()
        tenu.wait(5)
        debut = time.monotonic()
        r = m.projet({'dossier': '/a'})
        self.assertLess(time.monotonic() - debut, 0.5)
        self.assertEqual((r['n'], r['frais']), (1, False))
        fin.set()
        self.wait('/a')

    def test_a_failed_background_computation_reaches_the_page_and_is_noted(self):
        m = self.m
        m.projet({'dossier': '/x/Studio - Essai'})
        self.age('/x/Studio - Essai')
        m.echec = 'cassé'
        self.assertFalse(m.projet({'dossier': '/x/Studio - Essai'})['frais'])
        self.wait('/x/Studio - Essai')
        with self.assertRaises(RuntimeError):
            m.projet({'dossier': '/x/Studio - Essai'})
        journal = m.JOURNAL.read_text(encoding='utf-8')
        self.assertIn("projet en fond · Studio - Essai · échec : RuntimeError('cassé')", journal)

    def test_each_background_computation_is_noted_with_its_duration(self):
        m = self.m
        m.projet({'dossier': '/x/Studio - Essai/'})
        self.age('/x/Studio - Essai/')
        m.projet({'dossier': '/x/Studio - Essai/'})
        self.wait('/x/Studio - Essai/')
        self.assertRegex(m.JOURNAL.read_text(encoding='utf-8'), r'projet en fond · Studio - Essai · \d+\.\d\d s\n')

    def test_the_memory_of_views_is_bounded(self):
        m = self.m
        for i in range(m.GARDE_PROJET.garder_max + 10):
            m.projet({'dossier': f'/d{i}'})
        self.assertLessEqual(len(m.GARDE_PROJET.etats), m.GARDE_PROJET.garder_max)


class LignesNoted(Base):
    def test_the_board_computed_in_the_background_is_noted_with_its_duration(self):
        m = self.m
        m._lignes = lambda: {'lignes': []}
        m.lignes_page()
        m._dernier['fini'] = time.monotonic() - 60
        self.assertFalse(m.lignes_page()['frais'])
        m._fond['fil'].join(10)
        self.assertRegex(m.JOURNAL.read_text(encoding='utf-8'), r'lignes en fond · \d+\.\d\d s\n')


class Real(Session):
    """A real computation over one session of the app, its Studio and its waiting hook."""
    def setUp(self):
        super().setUp()
        self.say(ASKED_2, 30, 'm1')
        (self.mon_studio / '.parc' / 'cockpit.json').write_text(json.dumps({'reponses_directes': True,
                                                                            'autorisations_tableau': True}))
        self.m.AUTORISATIONS.serveur = object()   # the socket is up: the hook has handed its waits

    def wait_for(self, cli=CLI):
        a = self.m.Attente(None, {'id': 'a' * 32, 'session_id': cli, 'numero': 'Q2', 'kind': 'go', 'choix': ['go', 'pas encore']})
        self.m.AUTORISATIONS.attentes[a.id] = a
        return a

    def request_from(self, cli=CLI):
        d = self.m.Demande(None, {'id': 'b' * 32, 'session_id': cli, 'tool_name': 'Bash', 'extrait': 'ls', 'cwd': '/'})
        self.m.AUTORISATIONS.demandes[d.id] = d
        return d

    def frozen(self):
        fige = time.time()
        return unittest.mock.patch('time.time', lambda: fige)

    def test_the_fresh_view_equals_the_computation_of_before(self):
        m = self.m
        with self.frozen():
            before = m._projet(str(self.studio))   # the body of « projet » before 2026-11-24, unchanged
            first = m.projet({'dossier': str(self.studio)})
            m.GARDE_PROJET.etats[str(self.studio)]['fini'] = time.monotonic() - 60
            self.assertIs(m.projet({'dossier': str(self.studio)})['frais'], False)
            m.GARDE_PROJET.etats[str(self.studio)]['fil'].join(10)
            fresh = m.projet({'dossier': str(self.studio)})
        self.assertIs(fresh['frais'], True)
        for r in (first, fresh):
            r = dict(r)
            del r['frais']
            self.assertEqual(json.dumps(r, sort_keys=True, ensure_ascii=False), json.dumps(before, sort_keys=True, ensure_ascii=False))
        self.assertIn('Format du CR', json.dumps(before, ensure_ascii=False))

    def test_the_waits_name_their_session_as_before(self):
        m = self.m
        self.wait_for()
        self.request_from()
        m.repondue_ailleurs = lambda d, i: False
        with self.frozen():
            att, auto = m.attentes(), m.autorisations()
            ancien = {x['cli']: (x['id'], x['titre']) for x in m.parc.fiches({'fiches': {}}) if x.get('cli')}
        self.assertEqual(att['attentes'][0]['titre_session'], ancien[CLI][1])
        self.assertEqual(att['attentes'][0]['titre_session'], 'Essai · plan')
        self.assertEqual(auto['demandes'][0]['titre'], 'Essai · plan')
        self.assertEqual(auto['demandes'][0]['sessionId'], LOCAL)

    def test_a_first_reading_after_a_start_parses_no_card_the_board_has_read(self):
        self.m.lignes()   # the board reads the cards and keeps them in cache.json
        m2 = self.connector()   # the app restarted
        m2.AUTORISATIONS.serveur = object()
        a = m2.Attente(None, {'id': 'c' * 32, 'session_id': CLI, 'numero': 'Q2', 'kind': 'go', 'choix': ['go', 'pas encore']})
        m2.AUTORISATIONS.attentes[a.id] = a
        lues = []
        lire = m2.parc.lire_json
        with unittest.mock.patch.object(m2.parc, 'lire_json', lambda c, d=None: (lues.append(str(c)), lire(c, d))[1]):
            r = m2.attentes()
        self.assertEqual(r['attentes'][0]['titre_session'], 'Essai · plan')
        self.assertEqual([c for c in lues if 'local_' in os.path.basename(c)], [])

    def test_a_fast_reading_never_waits_for_a_long_computation(self):
        m = self.m
        self.wait_for()
        self.request_from()
        m.repondue_ailleurs = lambda d, i: False
        m.lignes()   # hands the map of the sessions
        m.attentes(), m.autorisations()
        tenu, fin = threading.Event(), threading.Event()

        def calcul_long():   # a board computation that holds CALCUL and keeps the cards busy
            with m.CALCUL:
                tenu.set()
                fin.wait(10)
        threading.Thread(target=calcul_long, daemon=True).start()
        tenu.wait(5)
        lent = lambda *a, **k: time.sleep(5)
        try:
            with unittest.mock.patch.object(m.parc, 'fiches', lent), unittest.mock.patch.object(m.parc, 'index_transcripts', lent):
                debut = time.monotonic()
                att, auto = m.attentes(), m.autorisations()
                self.assertLess(time.monotonic() - debut, 0.5)
        finally:
            fin.set()
        self.assertEqual(att['attentes'][0]['titre_session'], 'Essai · plan')
        self.assertEqual(auto['demandes'][0]['titre'], 'Essai · plan')

    def test_a_new_session_is_named_at_its_first_wait_and_a_session_without_card_is_not_read_again_at_once(self):
        m = self.m
        m.lignes()
        new_local, new_cli = 'local_00000000-0000-0000-0000-0000000000e2', 'cli-nouvelle'
        (self.app / 'acct' / 'org' / f'{new_local}.json').write_text(json.dumps(
            {'sessionId': new_local, 'cliSessionId': new_cli, 'title': 'Nouvelle', 'cwd': str(self.studio)}))
        self.wait_for(new_cli)
        self.assertEqual(m.attentes()['attentes'][0]['titre_session'], 'Nouvelle')   # unknown: the cards read again
        m.AUTORISATIONS.attentes.clear()
        self.wait_for('cli-sans-fiche')
        appels = []
        fiches = m.parc.fiches
        with unittest.mock.patch.object(m.parc, 'fiches', lambda c: (appels.append(1), fiches(c))[1]):
            for _ in range(3):
                self.assertIsNone(m.attentes()['attentes'][0]['titre_session'])
        self.assertEqual(len(appels), 1)   # once, then not before MANQUE_S

    def test_the_board_hands_a_renamed_session(self):
        m = self.m
        self.wait_for()
        m.lignes()
        self.assertEqual(m.attentes()['attentes'][0]['titre_session'], 'Essai · plan')
        fiche = self.app / 'acct' / 'org' / f'{LOCAL}.json'
        o = json.loads(fiche.read_text())
        o['title'] = 'Essai · renommée'
        fiche.write_text(json.dumps(o))
        os.utime(fiche, (time.time() + 5, time.time() + 5))
        m.lignes()
        self.assertEqual(m.attentes()['attentes'][0]['titre_session'], 'Essai · renommée')


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def run_page(self, **entree):
        entree.setdefault('lignes', [])
        entree.setdefault('frais', True)
        entree.setdefault('outils', ['lignes', 'projet', 'ouvrir', 'clore'])
        entree.setdefault('projetFixe', '/studios/Client-A/projet')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(entree, f)
        try:
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True,
                               timeout=60)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def projet(self, **plus):
        return dict({'dossier': '/studios/Client-A/projet', 'nom': 'projet', 'questions': [], 'sujets': [], 'tiers': [],
                     'journal': []}, **plus)

    def test_a_stale_view_is_read_again_within_seconds(self):
        out = self.run_page(projet=self.projet(frais=False), lancerMs=1500)
        self.assertIn(1500, out['minuteurs'])
        self.assertEqual([a[0] for a in out['appels']].count('projet'), 2)

    def test_a_fresh_view_or_an_older_connector_asks_nothing_more(self):
        for v in (self.projet(frais=True), self.projet()):
            out = self.run_page(projet=v, lancerMs=1500)
            self.assertNotIn(1500, out['minuteurs'])
            self.assertEqual([a[0] for a in out['appels']].count('projet'), 1)


if __name__ == '__main__':
    unittest.main()
