"""Tests of the app's end-of-turn card read as a question: python3 -m unittest discover -s tests

The app's end-of-turn card (tool mcp__ccd_turn__wrap_up: « recap », « ask », « actions ») is usually followed by a
last text from Claude (measured on the test Studio, 2026-11-03). Its question stays open until the PM writes in the
session: a line « questions natives » for Mon Studio and the project view, unless the message already carries it.
Its recap is the session's state for the project view."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
NOW = time.time()


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def pm(h, text):
    return {'type': 'user', 'timestamp': at(h), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def card(h, mid, ask, actions=(), recap='Le brouillon est prêt.'):
    inp = {'recap': recap, 'actions': [{'label': l, 'message': m} for l, m in actions]}
    if ask:
        inp['ask'] = ask
    return [{'type': 'assistant', 'timestamp': at(h),
             'message': {'id': mid, 'stop_reason': 'tool_use',
                         'content': [{'type': 'tool_use', 'id': 'u' + mid, 'name': parc.FIN_DE_TOUR, 'input': inp}]}},
            {'type': 'user', 'timestamp': at(h - 0.001),
             'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u' + mid, 'content': 'Shown.'}]}}]


def final(h, text, mid):
    return {'type': 'assistant', 'timestamp': at(h),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


class NativeQuestion(unittest.TestCase):
    def lines(self, entries):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 't.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')
            res = parc.analyser(str(path), NOW + 3600)
        s = dict(res, id='local_x', titre='Kit', cwd='/studios/Essai', non_lue=True)
        return res, parc.demandes(s)

    def test_card_then_text_is_an_open_question(self):
        res, lines = self.lines([pm(3, 'Lance le passage.'),
                                 *card(2, 'a', 'Je reprends la fin du passage vers 8h ?', [('Oui', 'oui'), ('Non', 'non')]),
                                 final(1.9, 'Le passage s\'est arrêté avant toute écriture.', 'b')])
        self.assertEqual(res['recap'], 'Le brouillon est prêt.')
        self.assertEqual([l['lecture'] for l in lines], ['native'])
        self.assertEqual(lines[0]['titre'], 'Je reprends la fin du passage vers 8h ?')
        self.assertIn('Oui', lines[0]['suite'])
        self.assertFalse(lines[0]['bloque'])
        self.assertNotIn(parc.A_VERIFIER_SUITE, [l['suite'] for l in lines])

    def test_a_message_of_the_pm_closes_it(self):
        res, lines = self.lines([*card(3, 'a', 'Je reprends vers 8h ?'), final(2.9, 'Arrêté.', 'b'),
                                 pm(2, 'Non, attends.'), final(1, 'Rien à faire de ton côté.', 'c')])
        self.assertNotIn('carte', res)
        self.assertEqual(res['recap'], 'Le brouillon est prêt.')   # the state stays the last recap
        self.assertEqual(lines, [])

    def test_same_number_in_the_message_is_one_line(self):
        _, lines = self.lines([*card(2, 'a', 'Q4 · On publie ?', [('Q4 go', 'Q4 go')]),
                               final(1.9, 'Prêt.\n\n**À trancher**\n\n1. Q4 · Publication : on publie ?', 'b')])
        self.assertEqual([l['num'] for l in lines], [4])
        self.assertEqual(lines[0]['lecture'], 'format')

    def test_an_unnumbered_card_restating_a_numbered_question_adds_nothing(self):
        _, lines = self.lines([*card(2, 'a', 'Relancer le passage maintenant ?'),
                               final(1.9, 'Arrêté.\n\n**À trancher**\n\n1. Q1 · Relance du passage : maintenant ?', 'b')])
        self.assertEqual([l['lecture'] for l in lines], ['format'])

    def test_a_card_without_question_gives_only_its_recap(self):
        res, lines = self.lines([*card(2, 'a', None, recap='Les tests passent.'),
                                 final(1.9, 'Fait. Rien à faire de ton côté.', 'b')])
        self.assertEqual(res['recap'], 'Les tests passent.')
        self.assertEqual(lines, [])


class ScheduledRun(unittest.TestCase):
    """A scheduled task's last pass that ends on a card question waits for the PM (the five open native questions of the
    test Studio on 2026-11-03 were all passes of one task): one line, for the last pass only."""

    def test_last_pass_with_a_question_is_a_line(self):
        with tempfile.TemporaryDirectory() as d:
            old = parc.CHANTIERS
            parc.CHANTIERS = pathlib.Path(d)
            try:
                card_ = {'menu': [{'question': 'Relancer le passage maintenant ?', 'options': []}], 'depuis': NOW - 600}
                auto = {'nom': 'Passage', 'ok': True, 'ts': NOW - 700, 'lien': 'local_run', 'cwd': '/studios/Essai',
                        'carte': card_, 'detail': ''}
                metas = [{'id': 'local_run', 'cwd': '/studios/Essai', 'titre': 'Passage du matin', 'archivee': False,
                          'parent': None, 'tache': 't1', 'creee': NOW - 800}]
                fresh, _ = parc.lignes_et_anciennes([], metas, [auto], 7, NOW, None)
                self.assertEqual([(l['lecture'], l['titre'], l['studio']) for l in fresh],
                                 [('native', 'Relancer le passage maintenant ?', 'Essai')])
                auto['carte'] = None
                self.assertEqual(parc.lignes_et_anciennes([], metas, [auto], 7, NOW, None)[0], [])
            finally:
                parc.CHANTIERS = old


if __name__ == '__main__':
    unittest.main()
