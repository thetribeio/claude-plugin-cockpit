"""Tests of question.py without a published board: python3 -m unittest discover -s tests

Without a published board (retired 2026-11-03), a question costs one call: `new` takes the number and writes the
line in the mirror, `settle` takes it out, `event` writes the local journal; no ArtifactData step, no pending file.
The chantier no longer needs a living foreman. Synthetic folders and cards, as in test_cockpit_question."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_cockpit_question import Chantier, FOREMAN, KIT, OTHER, KnownStudios  # noqa: E402


class Native(Chantier):
    def setUp(self):
        super().setUp()
        (self.mon_studio / '.parc').mkdir(exist_ok=True)
        self.state = self.mon_studio / '.parc' / 'cockpit.json'
        self.state.write_text(json.dumps({}))   # native follow-up is implicit: no switch

    def mirror_lines(self):
        return json.loads(self.mirror.read_text())['attentes']

    def test_new_is_one_call_and_writes_the_mirror(self):
        r = self.run_tool('new', '--kind', 'go', '--title', 'On publie ? Réponds « Qn : go »', sid=KIT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('ArtifactData', r.stdout)
        self.assertNotIn('posted', r.stdout)
        self.assertIn('~/Mon Studio', r.stdout)
        (line,) = self.mirror_lines()
        self.assertTrue(line['titre'].startswith('Q1 · Kit A : On publie ? Réponds « Q1 : go »'))
        self.assertEqual(line['sessionId'], KIT)
        pending = self.mon_studio / '.parc' / 'questions' / 'essai'
        self.assertEqual(list(pending.glob('*.json')) if pending.exists() else [], [])

    def test_two_questions_two_numbers(self):
        self.run_tool('new', '--title', 'Un', sid=KIT)
        self.run_tool('new', '--title', 'Deux', sid=KIT)
        self.assertEqual(sorted(parc_num(l['titre']) for l in self.mirror_lines()), [1, 2])

    def test_settle_is_one_call(self):
        self.run_tool('new', '--title', 'On publie ?', sid=KIT)
        r = self.run_tool('settle', 'Q1', '--decision', 'go', sid=KIT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('ArtifactData', r.stdout)
        self.assertEqual(self.mirror_lines(), [])
        journal = [json.loads(x) for x in self.mirror.with_suffix('.journal.jsonl').read_text().splitlines()]
        self.assertEqual(journal[-1]['type'], 'settled')
        self.assertEqual(journal[-1]['text'], 'go')

    def test_settle_refuses_another_sessions_question(self):
        self.run_tool('new', '--title', 'On publie ?', sid=KIT)
        self.card('local_kit2', 'Kit B', self.studio)
        r = self.run_tool('settle', 'Q1', '--decision', 'go', sid='local_kit2')
        self.assertEqual(r.returncode, 4)
        self.assertEqual(len(self.mirror_lines()), 1)

    def test_blocked_event_stays_local(self):
        r = self.run_tool('event', '--type', 'blocked', '--title', 'Le client doit envoyer les accès', sid=KIT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('ArtifactData', r.stdout)
        (entry,) = [json.loads(x) for x in self.mirror.with_suffix('.journal.jsonl').read_text().splitlines()]
        self.assertEqual((entry['type'], entry['text'], entry['sessionId']), ('blocked', 'Le client doit envoyer les accès', KIT))

    def test_archived_anchor_keeps_the_register(self):
        self.write_mirror(dict(json.loads(self.mirror.read_text()), registre=True))
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio, isArchived=True)
        r = self.run_tool('new', '--title', 'On publie ?', sid=KIT)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.mirror_lines()), 1)

    def test_a_mirror_from_before_with_an_archived_foreman_takes_no_question(self):
        # A chantier mirror as main wrote it (board, foreman, no `registre`): its foreman ended, it stays hidden.
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio, isArchived=True)
        r = self.run_tool('new', '--title', 'On publie ?', sid=KIT)
        self.assertEqual(self.mirror_lines(), [], r.stdout)

    def test_the_apps_own_follow_up_chosen_before_keeps_every_mirror(self):
        self.state.write_text(json.dumps({'tableau_publie': False}))
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio, isArchived=True)
        r = self.run_tool('new', '--title', 'On publie ?', sid=KIT)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.mirror_lines()), 1)

    def test_hook_says_one_call_and_no_foreman(self):
        out = self.hook(KIT, self.studio / 'projet')
        self.assertIn('un seul appel', out)
        self.assertIn("c'est voulu", out)
        self.assertNotIn('contremaître', out)
        self.assertNotIn('ArtifactData', out)

    def test_init_creates_a_project_for_a_folder_without_one(self):
        r = self.run_tool('init', '--name', 'Autre projet', sid=OTHER)
        self.assertEqual(r.returncode, 0, r.stdout)
        m = json.loads((self.mon_studio / 'chantiers' / 'autre-projet.json').read_text())
        self.assertEqual((m['chantier'], m['sessionId']), ('Autre projet', OTHER))
        r = self.run_tool('new', '--title', 'Ici ?', sid=OTHER)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('Q1 ·', r.stdout)
        again = self.run_tool('init', sid=KIT)
        self.assertIn('déjà son projet', again.stdout)


class NativeInAKnownStudio(KnownStudios):
    """The native follow-up needs no switch and no init: a Studio of projets.json is enough."""

    def test_no_switch_no_init_one_call(self):
        self.assertFalse((self.mon_studio / '.parc' / 'cockpit.json').exists())
        self.assertIn('un seul appel', self.run_tool('hook', sid='local_b1').stdout)
        self.assertEqual(self.ask('local_b1', 'On publie ?'), 'Q1')

    def test_a_wait_on_a_third_party_opens_the_register_too(self):
        r = self.run_tool('event', '--type', 'blocked', '--title', 'Le client doit envoyer les accès', sid='local_a1')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.registers(), ['studio-a.json'])
        (entry,) = [json.loads(x) for x in (self.mon_studio / 'chantiers' / 'studio-a.journal.jsonl').read_text().splitlines()]
        self.assertEqual(entry['type'], 'blocked')
        self.assertEqual(self.ask('local_a1', 'Et ensuite ?'), 'Q1')


def parc_num(title):
    return int(title.split('·')[0].strip().lstrip('Q'))


if __name__ == '__main__':
    unittest.main()
