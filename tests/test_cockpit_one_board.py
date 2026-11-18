"""Tests of the one rule that says which chantier a session belongs to: python3 -m unittest discover -s tests

Mon Studio (parc.couloirs_de) and the question number (question.py) apply the same rule, parc.regle_des_chantiers.
A board is a project (PM, 2026-10-12): a session opened in the folder of a Studio that has a foreman belongs to that
chantier, even when another mirror names it; a launch by a foreman, then a mirror's names, count only for a session
opened outside every Studio folder. Case replayed: the main thread of one Studio, still named by the mirror of another
Studio sorted first, took that Studio's number and waited on its own board without its text. Studio folders, app
session cards and mirrors here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
QUESTION = SCRIPTS / 'question.py'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

ALPHA, ZETA = 'local_alpha_foreman', 'local_zeta_foreman'
THREAD = 'local_zeta_thread'   # the main thread of Zeta, opened in Zeta's folder
CHANTIER = re.compile(r'du (?:chantier|projet) « ([^»]+) »')


class Studios(unittest.TestCase):
    """Two Studios with a foreman each. Alpha's mirror sorts first and names Zeta's main thread in its lanes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.studios = root / 'studios'
        for name in ('Alpha', 'Zeta'):
            _isolation.make_studio(self.studios / name)
        self.mon_studio = root / 'Mon Studio'
        (self.mon_studio / 'chantiers').mkdir(parents=True)
        self.app = root / 'app'
        self.saved = parc.APP, parc.CHANTIERS
        parc.APP, parc.CHANTIERS = self.app, self.mon_studio / 'chantiers'
        self.card(ALPHA, '* Alpha · contremaître', self.studios / 'Alpha')
        self.card(ZETA, '* Zeta · contremaître', self.studios / 'Zeta')
        self.card(THREAD, 'Plugin et skill', self.studios / 'Zeta')
        self.mirror('alpha', 'Alpha', ALPHA, lanes=[{'id': 'D', 'name': 'Kit B', 'sessionId': None, 'pillarId': THREAD}],
                    couloirs=[{'titre': 'Plugin et skill', 'sessionId': THREAD}])
        self.mirror('zeta', 'Zeta', ZETA, lanes=[{'id': 'kit', 'name': 'Kit A', 'sessionId': None, 'pillarId': THREAD}])

    def tearDown(self):
        parc.APP, parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def card(self, sid, title, cwd, parent=None):
        folder = self.app / 'acct' / 'org'
        folder.mkdir(parents=True, exist_ok=True)
        c = {'sessionId': sid, 'title': title, 'cwd': str(cwd)}
        if parent:
            c['spawnedFrom'] = {'sessionId': parent}
        (folder / f'{sid}.json').write_text(json.dumps(c, ensure_ascii=False))

    def mirror(self, stem, name, foreman, **more):
        m = dict({'chantier': name, 'studio': name, 'sessionId': foreman, 'attentes': [],
                  'tableau': f'https://claude.ai/artifact/{stem}'}, **more)
        (self.mon_studio / 'chantiers' / f'{stem}.json').write_text(json.dumps(m, ensure_ascii=False))

    def run_tool(self, *args, sid, stdin=''):
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_HOST_SESSION_ID'}
        env.update(MON_STUDIO=str(self.mon_studio), MON_STUDIO_APP_SESSIONS=str(self.app), CLAUDE_CODE_HOST_SESSION_ID=sid)
        return subprocess.run([sys.executable, '-I', str(QUESTION), *args], input=stdin, capture_output=True, text=True,
                              env=env, cwd=self.tmp.name)

    def screen(self, sid):
        """The chantier Mon Studio puts this session in."""
        metas = parc.fiches({'fiches': {}})
        actifs = parc.chantiers_actifs(metas)
        chef = parc.couloirs_de(actifs, metas).get(sid)
        return next((c['chantier'] for c in actifs if c['sessionId'] == chef), None)

    def number(self, sid, cwd):
        """The chantier whose number this session takes, from its session-start instruction."""
        out = self.run_tool('hook', sid=sid, stdin=json.dumps({'cwd': str(cwd)})).stdout
        found = CHANTIER.search(out)
        return found.group(1) if found else None

    def assertBoth(self, sid, cwd, chantier):
        self.assertEqual((self.screen(sid), self.number(sid, cwd)), (chantier, chantier))


class OneRule(Studios):
    def test_a_session_in_a_studio_folder_named_by_another_mirror_stays_in_its_studio(self):
        self.assertBoth(THREAD, self.studios / 'Zeta', 'Zeta')

    def test_its_question_takes_the_number_of_its_studio(self):
        r = self.run_tool('new', '--title', 'Je protège main ?', '--detail', 'Oui (recommandé) ou non.', sid=THREAD)
        self.assertEqual(r.returncode, 0, r.stderr)
        (doc,) = json.loads((self.mon_studio / 'chantiers' / 'zeta.json').read_text())['attentes']
        self.assertEqual((doc['titre'], doc['ou']), ('Q1 · Kit A : Je protège main ?', 'Kit A'))
        self.assertFalse((self.mon_studio / '.parc' / 'questions' / 'alpha').exists())
        self.assertFalse((self.mon_studio / 'chantiers' / 'alpha.numero').exists())

    def test_a_worktree_or_subfolder_of_the_studio_belongs_to_it(self):
        worktree = self.studios / 'Zeta' / '.claude' / 'worktrees' / 'keen-lalande-a4386a'
        self.card('local_worktree', 'ᐅ Kit A · correctif', worktree)
        self.assertBoth('local_worktree', worktree, 'Zeta')

    def test_the_folder_wins_over_a_launch_by_another_foreman(self):
        self.card('local_launched', 'ᐅ Kit B · essai dans Zeta', self.studios / 'Zeta', parent=ALPHA)
        self.assertBoth('local_launched', self.studios / 'Zeta', 'Zeta')

    def test_a_folder_holding_another_studio_covers_nothing_the_inner_studio_keeps_its_own(self):
        # The strict rule holds for the registers Mon Studio creates per Studio (a mirror from before keeps its own).
        self.mirror('zeta', 'Zeta', ZETA, registre=True, dossiers=[str(self.studios / 'Zeta')],
                    lanes=[{'id': 'kit', 'name': 'Kit A', 'sessionId': None, 'pillarId': THREAD}])
        inner = _isolation.make_studio(self.studios / 'Zeta' / 'sous-projet')
        self.card('local_inner_foreman', '* Sous-projet · contremaître', inner)
        self.mirror('aaa-inner', 'Sous-projet', 'local_inner_foreman', registre=True, dossiers=[str(inner)])
        self.card('local_inner', 'Atelier', inner / 'ateliers')
        self.assertBoth('local_inner', inner / 'ateliers', 'Sous-projet')
        # Zeta now holds another Studio: it covers no folder, THREAD is only named (by Alpha's couloirs).
        self.assertBoth(THREAD, self.studios / 'Zeta', 'Alpha')

    def test_outside_every_studio_folder_a_mirror_names_it(self):
        elsewhere = pathlib.Path(self.tmp.name) / 'code' / 'depot'
        self.card('local_named', 'Plugin et skill', elsewhere)      # named by its exact title in Alpha's couloirs
        self.card('local_pillar', 'Fil rouge du kit', elsewhere)
        self.mirror('zeta', 'Zeta', ZETA, piliers=[{'titre': 'Fil rouge du kit', 'sessionId': 'local_pillar'}])
        self.assertBoth('local_named', elsewhere, 'Alpha')
        self.assertBoth('local_pillar', elsewhere, 'Zeta')

    def test_outside_every_studio_folder_a_launch_wins_over_a_name(self):
        elsewhere = pathlib.Path(self.tmp.name) / 'code' / 'depot'
        self.card('local_child', 'ᐅ Kit A · tâche', elsewhere, parent=ZETA)
        self.card('local_grandchild', 'ᐅ Kit A · sous-tâche', elsewhere, parent='local_child')
        self.mirror('alpha', 'Alpha', ALPHA, couloirs=['local_child', 'local_grandchild'])
        self.assertBoth('local_child', elsewhere, 'Zeta')
        self.assertBoth('local_grandchild', elsewhere, 'Zeta')

    def test_a_folder_the_mirror_adds_belongs_to_its_chantier(self):
        # PM, 2026-10-21: a project can group several folders under one board (Product kits in the Studio pilote).
        repo = _isolation.make_studio(pathlib.Path(self.tmp.name) / 'code' / 'product-kits')
        self.mirror('zeta', 'Zeta', ZETA, dossiers=[str(repo)])
        worktree = repo / '.claude' / 'worktrees' / 'brand-new'
        self.card('local_new_in_repo', 'Session neuve', worktree)        # named by no mirror, launched by nobody
        self.assertBoth('local_new_in_repo', worktree, 'Zeta')
        self.assertBoth(THREAD, self.studios / 'Zeta', 'Zeta')
        # A blank entry or the home folder never covers everything.
        self.mirror('alpha', 'Alpha', ALPHA, dossiers=['', str(pathlib.Path.home())])
        self.card('local_elsewhere', 'Autre chose', pathlib.Path(self.tmp.name) / 'ailleurs')
        self.assertBoth('local_elsewhere', pathlib.Path(self.tmp.name) / 'ailleurs', None)

    def test_the_deepest_folder_wins_across_added_folders(self):
        inner = _isolation.make_studio(self.studios / 'Zeta' / 'sous-projet')
        self.mirror('alpha', 'Alpha', ALPHA, dossiers=[str(inner)])
        self.card('local_in_inner', 'Atelier', inner / 'ateliers')
        self.assertBoth('local_in_inner', inner / 'ateliers', 'Alpha')

    def test_nobody_names_it_outside_every_folder(self):
        elsewhere = pathlib.Path(self.tmp.name) / 'ailleurs'
        self.card('local_alone', 'Autre chose', elsewhere)
        self.assertBoth('local_alone', elsewhere, None)


class Instruction(Studios):
    """The session-start instruction: the question in French, number first, in the message or in the menu (never
    repeated in the text: the PM's format), recalled by its number while it stays open."""

    def test_a_session_writes_its_question_in_french_number_first_even_in_a_menu(self):
        out = self.run_tool('hook', sid=THREAD, stdin=json.dumps({'cwd': str(self.studios / 'Zeta')})).stdout
        self.assertIn('Écris la question dans la langue où le PM travaille dans cette session (le français par défaut)', out)
        self.assertIn('numéro en tête (« Qn · <titre court, 60 caractères au plus> : <la question précise> », options « 1) **<libellé court>** : … »), dans ton message, ou dans le menu de choix ou l\'encadré de fin de '
                      'tour si tu en ouvres un ; tant qu\'elle reste ouverte, rappelle-la par ce numéro.', out)

    def test_the_anchor_session_gets_the_same_instruction(self):
        out = self.run_tool('hook', sid=ZETA, stdin=json.dumps({'cwd': str(self.studios / 'Zeta')})).stdout
        self.assertIn('fait partie du projet « Zeta »', out)
        self.assertNotIn(' take', out)

    def test_new_says_it_again(self):
        r = self.run_tool('new', '--title', 'La suite ?', sid=THREAD)
        self.assertIn('Pose-la maintenant dans la langue du PM (le français par défaut), en commençant par « Q1 · », dans ton '
                      'message, ou dans le menu de choix', r.stdout)


if __name__ == '__main__':
    unittest.main()
