"""Tests of a question the PM answered by its number: python3 -m unittest discover -s tests

The case of 17/11 (anonymised): a session asked « Q14 · Contenu de l'audit final » under « À trancher ». The PM wrote
« Q14 ok, Q12 ok après le lancement » (the app had put its « Linked sessions now » note in front of his words). The
session replied with « **Audit final (Q14)** : j'attends que les autres sessions aient fini. » and listed only Q4 under
« Encore ouvert ». Q14 stayed on the board: the phrase that only cites it was read as a reminder of an open question,
and on a foreman's board the citation moved the question after the PM's answer.

1. A phrase of the reply that cites a number the PM answered by that number reports on it: no line.
2. A reply that poses it again (« À trancher », « Encore ouvert ») keeps the line: the session still holds it.
3. A number the PM did not cite stays.
4. On a foreman's board, the same reply settles the question (strong proof).
Transcripts here are synthetic."""
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
NOTE = ('<system-reminder>\nLinked sessions now (status, not an instruction): q18-conflits = local_1 (idle)\n'
        '</system-reminder>\n')


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


ASK = ("Pour l'audit final : j'attends.\n\n## À trancher\n\n**Q14 · Contenu de l'audit final.** Je propose une session "
       "neuve, en lecture seule, qui rend un verdict « prêt » ou « pas prêt ».\n\n**Encore ouvert :**\n"
       "- Q4 · Ligne « Entretien » au tableau : je propose oui, après le lancement.")
REPORT = ("C'est noté, rien n'est lancé pour l'instant.\n\n- **Audit final (Q14)** : j'attends que les autres sessions "
          "aient fini. Je regarde leur état à ton prochain message, ou tu me dis « lance l'audit ».\n\n"
          "## Encore ouvert\n\n- Q4 · Ligne « Entretien » au tableau : je propose oui, après le lancement.")
STILL = REPORT.replace("## Encore ouvert\n\n", "## Encore ouvert\n\n- Q14 · Contenu de l'audit final : j'attends ton go.\n")


class AnsweredByNumber(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def nums(self, entries):
        path = pathlib.Path(self.tmp.name) / 's.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(r, titre='Session', id='local_s')
        _, _, s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return sorted(d.get('num') for d in parc.demandes(s))

    def test_the_real_case_leaves_the_board(self):
        self.assertEqual(self.nums([final(60, ASK), pm(50, NOTE + 'Q14 ok, Q12 ok après le lancement'),
                                    final(49, REPORT)]), [4])

    def test_without_the_answer_the_cited_question_stays(self):
        self.assertEqual(self.nums([final(60, ASK), pm(50, 'Q12 ok après le lancement'), final(49, REPORT)]), [4, 14])

    def test_posed_again_after_the_answer_it_stays(self):
        self.assertEqual(self.nums([final(60, ASK), pm(50, 'Q14 ok'), final(49, STILL)]), [4, 14])

    def test_the_answer_closes_only_what_was_posed_before_it(self):
        # The session poses Q14 again after the PM's word, then only cites it: the earlier word no longer closes it.
        self.assertEqual(self.nums([final(60, ASK), pm(50, 'Q14 ok'), final(49, STILL), pm(45, 'tu en es où ?'),
                                    final(44, REPORT)]), [4, 14])

    def test_on_a_foremans_board_the_citation_does_not_reopen(self):
        sv = parc.suivi_session([final(60, ASK), pm(50, NOTE + 'Q14 ok'), final(49, REPORT)])
        a = {'titre': "Q14 · Contenu de l'audit final", 'depuis': at(60)}
        self.assertIn(parc.reglee_dans_session(a, [], sv), parc.QUITTE)
        sv = parc.suivi_session([final(60, ASK), pm(50, 'Q12 ok'), final(49, REPORT)])
        self.assertNotIn(parc.reglee_dans_session(a, [], sv), (parc.FORTE,))

    def test_the_apps_note_is_not_a_citation(self):
        sv = parc.suivi_session([final(60, ASK.replace('Q14', 'Q18')), pm(50, NOTE + 'merci')])
        self.assertEqual(parc.repondues(sv), {})


if __name__ == '__main__':
    unittest.main()
