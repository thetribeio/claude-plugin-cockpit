"""Tests: the ingestion part of the morning tab is computed live, Mon Studio's status asks for the two scheduled tasks
(2026-11-05, Q13 and Q14; 2026-11-06, Q23): python3 -m unittest discover -s tests

The tab « Today » reads the auto ingestion itself, without an LLM, at each computation: the entries (« Ce qui est
entré », all projects) and the new « À toi de jouer » requests (projects where the person is PM) since midnight of the
last working day. The morning task (an LLM) no longer writes `entre_studio`; it reads the ingestion state only to keep
out of `a_traiter` a request the ingestion already raised. The tasks are checked on a temporary HOME, never the real
~/.claude: `install.py` only reports (`create_morning_task`, `update_morning_task`, `create_morning_check_task`,
`update_morning_check_task`), it never writes them."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from test_cockpit_matin import MatinBase, item
from test_cockpit_projets import MONDAY, FRIDAY, REPORT, local

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PROMPT = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin.md'
CHECK_PROMPT = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin-verif.md'


class LiveIngestion(MatinBase):
    def test_the_tab_reads_the_ingestion_live_even_before_the_morning_task(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        out = self.compute()
        m = self.p.matin_pour_la_page(MONDAY, self.metas, out)
        self.assertEqual(m['etat'], 'pas_passe')
        self.assertEqual([(x['projet'], x['dossier']) for x in m['entre_studio']], [('Alpha', self.alpha)] * 2)
        self.assertTrue(m['entre_studio'][0]['phrase'].startswith('Email client (Léo, 30/10 08:10) : devis reçu.'))
        self.assertEqual([x['titre'] for x in m['demandes']], ['Valider le devis avant jeudi.'])
        self.write(a_traiter=[item(1)])
        m = self.p.matin_pour_la_page(MONDAY, self.metas, out)
        self.assertEqual((m['etat'], [x['cle'] for x in m['a_traiter']], len(m['entre_studio']), len(m['demandes'])),
                         ('ok', ['k1'], 2, 1))
        self.assertEqual(self.types(out), ['a_toi', 'entree', 'entree'], 'Projets keeps the whole stock')

    def test_only_since_the_last_working_day_and_open(self):
        older = local(2026, 10, 29, 14)   # Thursday, before Friday 00:00: still a request of the main table
        self.runs(self.alpha, (older, REPORT))
        out = self.compute()
        m = self.p.matin_pour_la_page(MONDAY, self.metas, out)
        self.assertEqual((m['entre_studio'], m['demandes']), ([], []))
        self.assertEqual(self.types(out), ['a_toi'])
        self.runs(self.alpha, (FRIDAY, REPORT))
        out = self.compute(MONDAY + 60)
        cle = next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi')
        self.p.fermer(cle, MONDAY + 120)
        out = self.compute(MONDAY + 180)
        self.assertEqual(self.p.matin_pour_la_page(MONDAY + 180, self.metas, out)['demandes'], [], 'closed by hand: gone')

    def test_requests_sorted_by_due_date_then_age_with_their_source(self):
        self.runs(self.alpha, (FRIDAY, "À toi de jouer :\n- Relire le planning.\n"
                                       "- Répondre au client (échéance 2026-11-04) ([source](https://mail.google.com/x))\n"),
                  (FRIDAY + 3600, "À toi de jouer :\n- Valider la maquette (échéance 2026-11-03)\n"))
        m = self.p.matin_pour_la_page(MONDAY, self.metas, self.compute())
        self.assertEqual([(x['titre'], x['echeance']) for x in m['demandes']],
                         [('Valider la maquette', '2026-11-03'), ('Répondre au client', '2026-11-04'), ('Relire le planning.', None)])
        self.assertEqual(m['demandes'][1]['lien'], 'https://mail.google.com/x')

    def test_a_member_gets_entries_but_no_request_and_no_list_gives_nothing(self):
        with mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': 'Sam Autre'}):
            self.runs(self.alpha, (FRIDAY, REPORT))
            m = self.p.matin_pour_la_page(MONDAY, self.metas, self.compute())
        self.assertEqual((len(m['entre_studio']), m['demandes']), (2, []))
        self.assertEqual(self.p.matin_pour_la_page(MONDAY, self.metas, None), {'etat': 'pas_passe', 'entre_studio': [], 'demandes': []})


class MorningPrompts(unittest.TestCase):
    def test_the_morning_prompt_reads_the_ingestion_only_against_duplicates(self):
        c = PROMPT.read_text(encoding='utf-8')
        # The script reads the ingestion and the Studio's files; the LLM reads only its output (2026-11-09).
        self.assertIn('python3 ~/Mon\\ Studio/.parc/matin.py preparer', c)
        self.assertIn('`deja_releve`', c)
        self.assertIn('Tu n\'ouvres aucun fichier : ce JSON les a lus pour toi', c)
        self.assertNotIn('.ingestion-auto-state.json', c)
        self.assertIn("n'entre pas dans « à traiter » : Mon Studio l'affiche déjà", c)
        self.assertIn('20 fils au plus', c)
        self.assertIn('une seule recherche', c)
        self.assertNotIn('entre_studio', c)
        self.assertNotIn('Entré au Studio', c)
        self.assertIn('`gmail`, `slack`, `agenda` ou `studio`', c)
        for gesture in ('`a_traiter`', '`regle`', '`preparer_demain`', '`reunions_sans_cr`', '`matin_ecrire`'):
            self.assertIn(gesture, c)
        self.assertIn('`maintenant`', c)
        self.assertNotRegex(c, r'`(date|mv) ')

    def test_the_check_prompt_only_moves_to_regle(self):
        c = CHECK_PROMPT.read_text(encoding='utf-8')
        self.assertIn('python3 ~/Mon\\ Studio/.parc/matin.py verifier', c)
        self.assertIn('« stop »', c)
        self.assertIn('ouvre son `lien` une fois, sans autre recherche', c)
        self.assertIn('Tu ne cherches rien de nouveau. Tu n\'envoies rien', c)
        self.assertIn('Tous les autres champs restent exactement tels quels', c)
        self.assertIn("appelle l'outil `matin_ecrire` du connecteur mon-studio, une fois", c.replace('Appelle', 'appelle'))
        self.assertIn('`maintenant`', c)
        self.assertIn('ni `mv`', c)  # named only as forbidden
        self.assertNotIn('```', c)

    def test_the_doc_points_to_both_prompts(self):
        doc = (ROOT / 'docs' / 'consigne-point-du-matin.md').read_text(encoding='utf-8')
        self.assertIn('skills/mon-studio/assets/consigne-point-du-matin.md', doc)
        self.assertIn('skills/mon-studio/assets/consigne-point-du-matin-verif.md', doc)
        self.assertIn('0 11,14,17 * * 1-5', doc)


def load_install(home):
    env = {'HOME': str(home)}
    with mock.patch.dict(os.environ, env):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location('install_matin_essai', SCRIPTS / 'install.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class MorningTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.i = load_install(self.home)

    def task(self, body, frontmatter='---\nname: point-du-matin\ndescription: Point du matin\n---\n\n'):
        self.i.MORNING_TASK.parent.mkdir(parents=True, exist_ok=True)
        self.i.MORNING_TASK.write_text(frontmatter + body, encoding='utf-8')

    def status(self):
        with mock.patch.object(self.i.sys, 'platform', 'darwin'):
            self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
            return self.i.status()

    def test_the_task_lives_under_the_temporary_home(self):
        self.assertTrue(str(self.i.MORNING_TASK).startswith(str(self.home)))
        self.assertEqual(self.i.MORNING_PROMPT, PROMPT)
        self.assertTrue(PROMPT.is_file())

    def test_absent_task_asks_for_its_creation(self):
        # Since 2026-11-15 the morning point is a step of « Mise en route »: nothing asked before the PM starts it.
        s = self.status()
        self.assertEqual(s['morningTask'], 'absent')
        self.assertEqual(s['morningTaskPrompt'], str(PROMPT))
        self.assertNotIn('create_morning_task', s['todo'])
        self.assertEqual(s['miseEnRoute']['matin'], 'a_faire')
        self.check_task(CHECK_PROMPT.read_text(encoding='utf-8'))
        s = self.status()
        self.assertIn('create_morning_task', s['todo'], 'one task there: the step was started, the other one is asked')
        self.assertNotIn('update_morning_task', s['todo'])
        self.assertFalse(self.i.MORNING_TASK.exists(), 'status never creates the task')

    def test_a_current_task_asks_for_nothing_even_with_other_trailing_blanks_and_frontmatter(self):
        self.task(PROMPT.read_text(encoding='utf-8').rstrip() + '\n\n\n  ', frontmatter='---\nname: x\n---\n')
        s = self.status()
        self.assertEqual(s['morningTask'], 'current')
        self.assertNotIn('create_morning_task', s['todo'])
        self.assertNotIn('update_morning_task', s['todo'])

    def test_an_outdated_task_asks_for_its_update_and_is_left_untouched(self):
        self.task('Une ancienne consigne.\n')
        before = self.i.MORNING_TASK.read_bytes()
        s = self.status()
        self.assertEqual(s['morningTask'], 'outdated')
        self.assertIn('update_morning_task', s['todo'])
        self.assertNotIn('create_morning_task', s['todo'])
        self.assertEqual(self.i.MORNING_TASK.read_bytes(), before)

    def check_task(self, body):
        self.i.MORNING_CHECK_TASK.parent.mkdir(parents=True, exist_ok=True)
        self.i.MORNING_CHECK_TASK.write_text('---\nname: point-du-matin-verif\n---\n\n' + body, encoding='utf-8')

    def test_the_check_task_is_reported_like_the_morning_one(self):
        self.assertTrue(str(self.i.MORNING_CHECK_TASK).startswith(str(self.home)))
        self.assertEqual(self.i.MORNING_CHECK_TASK.parent.name, 'point-du-matin-verif')
        self.assertEqual(self.i.MORNING_CHECK_PROMPT, CHECK_PROMPT)
        s = self.status()
        self.assertEqual((s['morningCheckTask'], s['morningCheckTaskPrompt']), ('absent', str(CHECK_PROMPT)))
        self.assertNotIn('create_morning_check_task', s['todo'], 'step not started: nothing asked')
        self.task(PROMPT.read_text(encoding='utf-8'))
        s = self.status()
        self.assertIn('create_morning_check_task', s['todo'])
        self.assertNotIn('update_morning_check_task', s['todo'])
        self.i.MORNING_TASK.unlink()
        self.check_task('Une ancienne vérification.\n')
        before = self.i.MORNING_CHECK_TASK.read_bytes()
        s = self.status()
        self.assertEqual(s['morningCheckTask'], 'outdated')
        self.assertIn('update_morning_check_task', s['todo'])
        self.assertNotIn('create_morning_check_task', s['todo'])
        self.assertEqual(self.i.MORNING_CHECK_TASK.read_bytes(), before)
        self.check_task(CHECK_PROMPT.read_text(encoding='utf-8'))
        s = self.status()
        self.assertEqual(s['morningCheckTask'], 'current')
        self.assertFalse({'create_morning_check_task', 'update_morning_check_task'} & set(s['todo']))
        self.assertIn('create_morning_task', s['todo'], 'the two tasks are independent')

    def test_the_morning_prompt_does_not_make_the_check_task_current(self):
        self.check_task(PROMPT.read_text(encoding='utf-8'))
        self.assertEqual(self.status()['morningCheckTask'], 'outdated')

    def test_apply_never_writes_the_task(self):
        with mock.patch.object(self.i.sys, 'platform', 'darwin'), contextlib.redirect_stdout(io.StringIO()):
            self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
            self.i.apply()
        self.assertFalse(self.i.MORNING_TASK.exists())
        self.assertFalse(self.i.MORNING_CHECK_TASK.exists())

    def run_record(self, task, model, effort, created):
        folder = self.i.APP_SESSIONS / 'a' / 'b'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'local_{task}_{created}.json').write_text(json.dumps(
            {'scheduledTaskId': task, 'model': model, 'effort': effort, 'createdAt': created}), encoding='utf-8')

    def test_the_tasks_model_is_read_from_their_latest_run(self):
        self.assertNotIn('set_task_models', self.status()['todo'], 'no run yet: nothing to say')
        self.run_record('point-du-matin', 'claude-opus-5-5', 'medium', 1)
        self.run_record('point-du-matin', 'claude-sonnet-5-5', 'low', 2)
        self.run_record('point-du-matin-verif', 'claude-sonnet-5-5', 'low', 1)
        s = self.status()
        self.assertEqual(s['taskModels']['point-du-matin']['lastRun'], {'model': 'claude-sonnet-5-5', 'effort': 'low'})
        self.assertNotIn('set_task_models', s['todo'])
        self.run_record('point-du-matin', 'claude-sonnet-5-5', 'medium', 3)
        self.assertNotIn('set_task_models', self.status()['todo'], 'the effort cannot be chosen: not compared')
        self.run_record('point-du-matin-verif', 'claude-opus-5-5', 'medium', 3)
        s = self.status()
        self.assertIn('set_task_models', s['todo'])
        self.assertEqual(s['taskModels']['point-du-matin-verif']['wanted'], {'model': 'sonnet'})

    def test_the_prompt_is_neutral_and_self_contained(self):
        c = PROMPT.read_text(encoding='utf-8')
        self.assertIn('`maintenant`', c)
        self.assertIn("appelle l'outil `matin_ecrire` du connecteur mon-studio, une fois", c.replace('Appelle', 'appelle'))
        self.assertIn("`~` désigne le dossier personnel de l'utilisateur.", c)
        self.assertNotIn('Windows', c)
        self.assertIn('ni `mv`', c)  # named only as forbidden
        self.assertNotIn('avec `date`', c)
        self.assertNotIn('```', c)
        doc = (ROOT / 'docs' / 'consigne-point-du-matin.md').read_text(encoding='utf-8')
        self.assertNotIn('Tu prépares le point du matin', doc)
        self.assertNotIn('le PM lui-même', doc)


class MacOnly(MorningTask):
    """Every path the installer writes is a macOS one: elsewhere, nothing is posed (2026-11-09, point 7 of the review)."""

    def test_status_says_unsupported_and_has_no_pioneer_mode(self):
        for platform in ('win32', 'linux'):
            with mock.patch.object(self.i.sys, 'platform', platform):
                self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
                s = self.i.status()
            self.assertEqual(s['todo'], ['unsupported'])
            self.assertNotIn('windowsPioneer', s)

    def test_apply_and_disable_refuse_before_touching_anything(self):
        for platform in ('win32', 'linux'):
            for run in (self.i.apply, self.i.disable):
                out = io.StringIO()
                with mock.patch.object(self.i.sys, 'platform', platform), \
                        mock.patch.object(self.i.os, 'getuid', side_effect=AssertionError('no getuid'), create=True), \
                        contextlib.redirect_stdout(out):
                    self.assertEqual(run(), 2)
                self.assertIn("Mon Studio s'installe sur Mac seulement", out.getvalue())
                self.assertFalse(self.i.INTERNAL.exists())
                self.assertFalse(self.i.APP_CONFIG.exists())

    def test_the_platform_file_keeps_only_the_maintainer(self):
        flags = json.loads((ROOT / 'skills' / 'mon-studio' / 'assets' / 'plateformes.json').read_text(encoding='utf-8'))
        self.assertEqual(set(flags), {'maintainer'})
        self.assertNotIn('@', flags['maintainer'])

if __name__ == '__main__':
    unittest.main()
