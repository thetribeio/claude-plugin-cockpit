"""Tests of the project view: python3 -m unittest discover -s tests

For the PM alone, on his Mac: one project, nothing of another (PM, 2026-11-03: « c'est la vue par projet, pour ne
pas tout mélanger quand on veut se focus sur un seul projet. Mon Studio reste pour la vue inter projets »). Computed
by parc.py from what Mon Studio already reads; the connector's read-only tool `projet` serves it to the page. A
project is a folder (a chantier's first folder, or the session's folder), never a displayed name. Synthetic data."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
NOW = time.time()
A, B = '/studios/Client-A/projet', '/autres/Client-B/projet'   # two folders, same displayed name « projet »


def meta(sid, cwd, parent=None, creee=0, titre=None):
    return {'id': sid, 'cwd': cwd, 'parent': parent, 'creee': creee, 'titre': titre or sid, 'archivee': False}


def session(sid, titre, recap=None, recaps=(), etat='attend', age_h=1):
    return {'id': sid, 'titre': titre, 'etat': etat, 'depuis': NOW - age_h * 3600, 'derniere': NOW - age_h * 3600,
            'recap': recap, 'recaps': [{'depuis': NOW - age_h * 3600 - i, 'texte': r} for i, r in enumerate(recaps)],
            'ouverture': 'Ouverture.', 'non_lue': False}


def row(sid, projet, texte):
    return {'studio': 'projet', 'session': sid, 'cle': sid, 'ouvrir': sid, 'type': 'decision', 'verbe': 'Répondre',
            'affiche_titre': '', 'affiche_suite': texte, 'complet': texte, 'depuis': NOW - 60, 'echeance': None,
            'proche': False, 'projet': projet}


class View(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _studio = unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True)   # synthetic folders: no manifest on disk
        _studio.start()
        self.addCleanup(_studio.stop)
        self.old = parc.CHANTIERS, parc.INTERNE
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.INTERNE = pathlib.Path(self.tmp.name) / '.parc'
        parc.CHANTIERS.mkdir()
        self.metas = [meta('local_pa', A, creee=1, titre='Pilier A'), meta('local_fa', A + '/sous', parent='local_pa', creee=2),
                      meta('local_wt', '/studios/Client-A/projet/.claude/worktrees/x', parent='local_fa', creee=3),
                      meta('local_pb', B, creee=4, titre='Pilier B')]
        self.sessions = [session('local_pa', 'Pilier A', recap='A avance.', recaps=['A commence.', 'A avance.']),
                         session('local_fa', 'Fille A', recap='La fille a fini.'),
                         session('local_wt', 'Copie A', etat='travaille'),
                         session('local_pb', 'Pilier B', recap='B attend.', recaps=['B attend.'])]

    def tearDown(self):
        parc.CHANTIERS, parc.INTERNE = self.old
        self.tmp.cleanup()

    def e(self, rows):
        return {'genere': NOW, 'tableau': rows, 'anciennes': [], '_metas': self.metas, '_sessions': self.sessions}

    def test_a_session_folder_is_its_project_and_two_same_names_never_mix(self):
        cle = parc.projets_des_sessions(self.metas)
        self.assertEqual(cle('local_pa'), A)
        self.assertEqual(cle('local_wt'), A)       # a worktree belongs to its repository
        self.assertEqual(cle('local_pb'), B)
        self.assertEqual(parc.nom_projet(A), parc.nom_projet(B))   # same displayed name…
        e = self.e([row('local_pa', A, 'Q1 · A ?'), row('local_pb', B, 'Q1 · B ?')])
        va, vb = parc.vue_projet(e, A), parc.vue_projet(e, B)
        self.assertEqual([l['complet'] for l in va['questions']], ['Q1 · A ?'])   # …two projects
        self.assertEqual([l['complet'] for l in vb['questions']], ['Q1 · B ?'])
        self.assertNotIn('Pilier B', json.dumps(va, ensure_ascii=False))

    def test_subjects_are_pillars_with_their_children_and_state_is_the_last_recap(self):
        v = parc.vue_projet(self.e([]), '/studios/Client-A/projet')
        # « sous » is a subfolder: another project; the worktree joins the pillar's project
        self.assertEqual([s['titre'] for s in v['sujets']], ['Pilier A'])
        self.assertEqual(v['sujets'][0]['etat'], 'A avance.')
        self.assertEqual([f['titre'] for f in v['sujets'][0]['filles']], ['Copie A'])
        self.assertEqual(v['sujets'][0]['filles'][0]['etat'], 'Claude travaille')

    def test_chantier_groups_its_folders_and_its_journal_gives_waits_on_third_parties(self):
        mirror = parc.CHANTIERS / 'essai.json'
        mirror.write_text(json.dumps({'chantier': 'Essai', 'sessionId': 'local_pa', 'dossiers': [B], 'attentes': []}))
        iso = lambda h: time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(NOW - h * 3600))
        mirror.with_suffix('.journal.jsonl').write_text('\n'.join(json.dumps(x) for x in [
            {'at': iso(5), 'type': 'blocked', 'sessionId': 'local_pb', 'session': 'Pilier B', 'text': 'Accès client attendus'},
            {'at': iso(4), 'type': 'blocked', 'sessionId': 'local_fa', 'session': 'Fille A', 'text': 'Maquettes du designer'},
            {'at': iso(3), 'type': 'done', 'sessionId': 'local_fa', 'session': 'Fille A', 'text': 'Maquettes reçues'},
        ]) + '\n')
        cle = parc.projets_des_sessions(self.metas)
        self.assertEqual({cle(s) for s in ('local_pa', 'local_fa', 'local_pb')}, {A})   # one chantier, one project
        v = parc.vue_projet(self.e([dict(row('local_pb', A, 'Q2 · B ?'), chantier='Essai')]), A)
        self.assertEqual(v['nom'], 'Essai')
        self.assertEqual([t['texte'] for t in v['tiers']], ['Accès client attendus'])
        genres = [j['genre'] for j in v['journal']]
        self.assertIn('recap', genres)
        self.assertIn('done', genres)
        self.assertEqual(v['journal'], sorted(v['journal'], key=lambda j: -j['depuis']))

    def test_an_accented_folder_matches_composed_or_decomposed(self):
        # The app writes a session's folder decomposed (NFD), a pinned project page passes it composed (NFC).
        nfd = '/Drive partagés/Client-C/projet'
        nfc = '/Drive partagés/Client-C/projet'
        self.metas.append(meta('local_pc', nfd, creee=5, titre='Pilier C'))
        self.sessions.append(session('local_pc', 'Pilier C', recap='C avance.'))
        e = self.e([row('local_pc', nfd, 'Q1 · C ?')])
        for dossier in (nfc, nfd):
            v = parc.vue_projet(e, dossier)
            self.assertIsNotNone(v, dossier)
            self.assertEqual([s['titre'] for s in v['sujets']], ['Pilier C'])
            self.assertEqual([l['complet'] for l in v['questions']], ['Q1 · C ?'])

    def test_unknown_project_is_none(self):
        self.assertIsNone(parc.vue_projet(self.e([]), '/nulle/part'))
        self.assertEqual(parc.vue_projet_pour_la_page(self.e([]), '/nulle/part'), {'dossier': '/nulle/part', 'introuvable': True})

    def test_page_payload_is_json_with_milliseconds(self):
        out = parc.vue_projet_pour_la_page(self.e([row('local_pa', A, 'Q1 · A ?')]), A)
        json.dumps(out)
        self.assertEqual(out['questions'][0]['projet'], A)
        self.assertEqual(out['sujets'][0]['depuis'], int(self.sessions[0]['derniere'] * 1000))


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class Page(unittest.TestCase):
    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def payload(self, **more):
        lignes = [{'studio': 'projet', 'session': 'Pilier A', 'cle': 'local_a', 'ouvrir': 'local_a', 'type': 'decision',
                   'affiche_suite': 'Q1 · A ?', 'projet': A},
                  {'studio': 'projet', 'session': 'Pilier B', 'cle': 'local_b', 'ouvrir': 'local_b', 'type': 'decision',
                   'affiche_suite': 'Q1 · B ?', 'projet': B}]
        return dict({'lignes': lignes, 'projets': [{'studio': 'projet', 'dossier': A, 'nom': 'Client-A'},
                                                   {'studio': 'projet', 'dossier': B, 'nom': 'Client-B'}]}, **more)

    def test_one_button_per_folder_next_to_the_studio(self):
        out = self.run_page(self.payload())
        self.assertIn('data-projet="' + A + '"', out['studios'])
        self.assertIn('data-projet="' + B + '"', out['studios'])
        self.assertIn('Vue projet · Client-A', out['studios'])
        self.assertTrue(out['projetCache'])
        self.assertFalse(out['boiteCachee'])

    def test_the_button_shows_that_project_only(self):
        vue = {'dossier': A, 'nom': 'Client-A', 'genere': 0,
               'questions': [{'studio': 'projet', 'session': 'Pilier A', 'cle': 'local_a', 'type': 'decision',
                              'affiche_suite': 'Q1 · A ?', 'depuis': int(time.time() * 1000)}],
               'anciennes': [], 'sujets': [{'titre': 'Pilier A', 'sessionId': 'local_a', 'etat': 'A avance.', 'depuis': 1,
                                            'filles': [{'titre': 'Fille A', 'sessionId': 'local_f', 'etat': 'Fini.', 'depuis': 1}]}],
               'tiers': [{'texte': 'Accès client attendus', 'session': 'Pilier A', 'depuis': 1}],
               'journal': [{'depuis': 1, 'texte': 'A avance.', 'session': 'Pilier A', 'genre': 'recap'}]}
        fils = [{'studio': 'Client-A', 'sessions': [{'sessionId': 'local_a', 'titre': 'Fil rouge A'}]}]
        out = self.run_page(self.payload(projet=vue, fils_rouges=fils, cliquer=[['data-projet', A]]))
        self.assertIn(['projet', {'dossier': A}], out['appels'])
        self.assertFalse(out['projetCache'])
        self.assertTrue(out['boiteCachee'])               # the rest of the page hides
        self.assertEqual(out['projetNom'], 'Client-A')
        self.assertIn('Q1 · A ?', out['projetQuestions'])
        self.assertNotIn('Q1 · B ?', out['projetQuestions'])
        self.assertIn('Fil rouge A', out['projetSujets'])   # « Fils rouges » replaced the session recaps
        self.assertNotIn('Fille A', out['projetSujets'])
        self.assertIn('Accès client attendus', out['projetTiers'])
        self.assertIn('A avance.', out['projetJournal'])

    def test_back_to_all_projects(self):
        out = self.run_page(self.payload(projet={'dossier': A, 'nom': 'Client-A', 'questions': [], 'sujets': [], 'tiers': [], 'journal': []},
                                         cliquer=[['data-projet', A], ['data-tous', '1']]))
        self.assertTrue(out['projetCache'])
        self.assertFalse(out['boiteCachee'])


if __name__ == '__main__':
    unittest.main()
