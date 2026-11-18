"""Tests: points settled at their source by the ingestion kit (2026-11-05): python3 -m unittest discover -s tests

The kit's contract (« Demande au cockpit : points réglés par la source »): a pass of the ingestion writes, in
projet/.ingestion-auto-state.json, `reglees` entries for what its source shows done, with the proof; never a choice nor
a go. Mon Studio:
  - « À toi »: an entry of genre question is not an « À toi »; an entry the PM reopened (`rouverte`) closes nothing and
    reopens the line it had closed; projets-sources.json keeps genre, question, rouverte;
  - a numbered question named by an entry leaves its chantier's mirror once (number at rest 12 h), journal `settled`,
    `par: source`, with the line as it was; a decision, a go, a click or a stop line is never touched;
  - the session that asked is told once, at its next turn (question.py notices), and Mon Studio makes no line from an
    « Encore ouvert » it wrote before;
  - « rouvre Qn »: the line comes back (same number if free, otherwise the next), journal `reopened`, `par: pm`, and the
    session is told once.

Studios, mirrors, journals and transcripts are synthetic; the real ~/Mon Studio is never read."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_cockpit_projets import Base, ASKER, MONDAY, FRIDAY, REPORT, utc   # noqa: E402
import test_cockpit_exits_and_sort as board_tests   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUESTION = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'question.py'
FOREMAN = 'local_00000000-0000-0000-0000-0000000000f1'
OTHER = 'local_00000000-0000-0000-0000-0000000000f2'
PROOF = 'mail envoyé (Léo, 02/11 10:00, https://mail.google.com/x)'


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def wait(n, kind='task', since=MONDAY - 7200, sid=ASKER, doc=True, **more):
    a = dict({'type': kind, 'titre': f'Q{n} · Titre {n}', 'ou': 'Cadrage', 'depuis': iso(since), 'sessionId': sid,
              'sessionLabel': 'Cadrage', 'source': sid}, **more)
    if doc:
        a['doc'] = f'n20261102-{n}'
    return a


def entry(n, ts=MONDAY - 600, doc=True, sid=ASKER, **more):
    q = {'numero': n, 'sessionId': sid, 'chantier': 'Essai'}
    if doc:
        q['doc'] = f'n20261102-{n}'
    return dict({'ts': utc(ts), 'texte': f'Q{n} · Titre {n}', 'preuve': PROOF, 'ref': f'Q{n}', 'genre': 'question',
                 'quand': utc(ts - 60), 'question': q}, **more)


class Source(Base):
    def setUp(self):
        super().setUp()
        self.chantiers = self.mon_studio / 'chantiers'
        self.chantiers.mkdir()
        self.q = self.p._charger_question()

    def mirror(self, *attentes):
        (self.chantiers / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'studio': 'Alpha', 'sessionId': FOREMAN, 'attentes': list(attentes)}), encoding='utf-8')

    def attentes(self):
        return json.loads((self.chantiers / 'essai.json').read_text(encoding='utf-8'))['attentes']

    def titles(self):
        return [a['titre'] for a in self.attentes()]

    def journal(self):
        path = self.chantiers / 'essai.journal.jsonl'
        return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def settle(self, *entries, when=MONDAY, write=True):
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=list(entries))
        return self.compute(when, write)


class Settle(Source):
    def test_a_task_settled_by_its_source_leaves_the_mirror_once(self):
        self.mirror(wait(5), wait(6))
        self.settle(entry(5))
        self.settle(entry(5), when=MONDAY + 60)
        self.assertEqual(self.titles(), ['Q6 · Titre 6'])
        j = self.journal()
        self.assertEqual(len(j), 1)
        self.assertEqual({k: j[0][k] for k in ('type', 'par', 'number', 'doc', 'sessionId', 'title', 'ref')},
                         {'type': 'settled', 'par': 'source', 'number': 5, 'doc': 'n20261102-5', 'sessionId': ASKER,
                          'title': 'Q5 · Titre 5', 'ref': 'Q5'})
        self.assertEqual(j[0]['text'], "Réglé par l'ingestion auto : " + PROOF)
        self.assertEqual(j[0]['ligne'], wait(5))
        rest = json.loads((self.chantiers / 'essai.numeros.json').read_text(encoding='utf-8'))
        self.assertIn('5', rest['vus'])   # the number rests 12 h

    def test_a_review_and_a_line_without_document_by_number_and_session(self):
        self.mirror(wait(5, kind='review'), wait(7, doc=False), wait(7, doc=False, sid=OTHER))
        self.settle(entry(5), entry(7, doc=False))
        self.assertEqual(self.attentes(), [wait(7, doc=False, sid=OTHER)])

    def test_a_choice_a_go_or_a_stop_line_is_never_touched(self):
        kept = [wait(1, kind='decision'), wait(2, kind='go'), wait(4, arret='authorization')]
        self.mirror(*kept)
        self.settle(*(entry(n) for n in (1, 2, 4)))
        self.assertEqual(self.attentes(), kept)
        self.assertEqual(self.journal(), [])

    def test_a_click_is_settled_by_its_source(self):
        self.mirror(wait(3, kind='clic'), wait(1, kind='decision'))
        self.settle(entry(3), entry(1))
        self.assertEqual(self.titles(), ['Q1 · Titre 1'])

    def test_a_line_asked_after_the_settlement_stays(self):
        self.mirror(wait(5, since=MONDAY))
        self.settle(entry(5, ts=MONDAY - 600))
        self.assertEqual(self.titles(), ['Q5 · Titre 5'])

    def test_another_chantier_or_an_absent_line_changes_nothing(self):
        self.mirror(wait(5))
        self.settle(dict(entry(5), question={'numero': 5, 'doc': 'n20261102-5', 'sessionId': ASKER, 'chantier': 'Autre'}),
                    entry(9))
        self.assertEqual(self.titles(), ['Q5 · Titre 5'])
        self.assertEqual(self.journal(), [])

    def test_a_trial_run_writes_nothing(self):
        self.mirror(wait(5))
        self.settle(entry(5), write=False)
        self.assertEqual(self.titles(), ['Q5 · Titre 5'])

    def test_mon_studio_no_longer_shows_it(self):
        self.mirror(wait(5), wait(6))
        self.settle(entry(5))
        m = next(m for m in self.p.parc.miroirs() if m['chantier'] == 'Essai')
        self.assertEqual([a['titre'] for a in m['attentes']], ['Q6 · Titre 6'])

    def test_with_a_published_board_the_journal_hides_it_even_when_the_board_puts_it_back(self):
        self.mirror(wait(5), wait(6))
        self.settle(entry(5))
        self.mirror(wait(5), wait(6))   # miroir.py rewrote the mirror from the board, which still holds Q5
        m = next(m for m in self.p.parc.miroirs() if m['chantier'] == 'Essai')
        self.assertEqual([a['titre'] for a in m['attentes']], ['Q6 · Titre 6'])


class Reopen(Source):
    def test_reopened_the_line_comes_back_with_its_number(self):
        self.mirror(wait(5), wait(6))
        self.settle(entry(5))
        self.settle(entry(5, rouverte=utc(MONDAY + 30)), when=MONDAY + 60)
        self.settle(entry(5, rouverte=utc(MONDAY + 30)), when=MONDAY + 120)
        self.assertEqual(sorted(self.titles()), ['Q5 · Titre 5', 'Q6 · Titre 6'])
        self.assertEqual(next(a for a in self.attentes() if a['titre'].startswith('Q5')), wait(5))
        j = self.journal()
        self.assertEqual([(x['type'], x['par']) for x in j], [('settled', 'source'), ('reopened', 'pm')])
        self.assertIsNone(j[1]['previous'])
        m = next(m for m in self.p.parc.miroirs() if m['chantier'] == 'Essai')
        self.assertEqual(sorted(a['titre'] for a in m['attentes']), ['Q5 · Titre 5', 'Q6 · Titre 6'])

    def test_its_number_taken_by_another_question_gives_the_next(self):
        self.mirror(wait(5))
        self.settle(entry(5))
        self.mirror(wait(5, kind='decision', sid=OTHER, doc=False, titre='Q5 · Une autre'))
        self.settle(entry(5, rouverte=utc(MONDAY + 30)), when=MONDAY + 60)
        back = [a for a in self.attentes() if a.get('doc') == 'n20261102-5']
        self.assertEqual(len(back), 1)
        self.assertNotEqual(back[0]['titre'], 'Q5 · Titre 5')
        self.assertTrue(back[0]['titre'].endswith(' · Titre 5'))
        self.assertEqual(self.journal()[-1]['previous'], 5)

    def test_reopened_before_any_settlement_does_nothing(self):
        self.mirror(wait(5))
        self.settle(entry(5, rouverte=utc(MONDAY + 30)))
        self.assertEqual(self.titles(), ['Q5 · Titre 5'])
        self.assertEqual(self.journal(), [])

    def test_a_toi_reopened(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        done = {'ts': utc(MONDAY + 60), 'texte': 'Valider le devis avant jeudi', 'preuve': 'mail envoyé', 'ref': 'A3',
                'genre': 'a_toi'}
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=[done])
        self.assertEqual(self.types(self.compute(MONDAY + 120)), ['entree', 'entree'])
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=[dict(done, rouverte=utc(MONDAY + 180))])
        self.assertEqual(self.types(self.compute(MONDAY + 240)), ['a_toi', 'entree', 'entree'])

    def test_a_question_entry_is_not_an_a_toi(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=[dict(entry(5), texte='Valider le devis avant jeudi')])
        self.assertEqual(self.types(self.compute(MONDAY + 120)), ['a_toi', 'entree', 'entree'])

    def test_the_snapshot_keeps_the_new_fields(self):
        self.mirror(wait(5))
        self.settle(entry(5, rouverte=utc(MONDAY + 30)))
        snap = json.loads((self.mon_studio / '.parc' / 'projets-sources.json').read_text(encoding='utf-8'))
        r = snap['dossiers'][self.alpha]['reglees'][0]
        self.assertEqual((r['genre'], r['question']['numero'], r['rouverte'], r['ref'], r['preuve']),
                         ('question', 5, utc(MONDAY + 30), 'Q5', PROOF))


class Notice(Source):
    def test_the_asking_session_is_told_once(self):
        self.mirror(wait(5))
        self.settle(entry(5))
        self.assertEqual(self.q.notices(OTHER), [])
        told = self.q.notices(ASKER)
        self.assertEqual(told, ['[Mon Studio] Q5 · Titre 5 est réglée par la source : ' + PROOF + '. Ne la rappelle '
                                'plus dans « Encore ouvert ». Si le PM écrit « rouvre Q5 », elle revient.'])
        self.assertEqual(self.q.notices(ASKER), [])
        self.settle(entry(5, rouverte=utc(MONDAY + 30)), when=MONDAY + 60)
        self.assertEqual(self.q.notices(ASKER), ['[Mon Studio] Q5 · Titre 5 est rouverte par le PM : rappelle-la de nouveau.'])
        self.assertEqual(self.q.notices(ASKER), [])

    def test_a_settlement_by_the_session_itself_is_not_told(self):
        self.mirror(wait(5))
        with open(self.chantiers / 'essai.journal.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps({'id': 'settled-x', 'type': 'settled', 'number': 5, 'sessionId': ASKER, 'title': 'Q5'}) + '\n')
        self.assertEqual(self.q.notices(ASKER), [])

    def test_the_hook_prints_it_and_never_fails(self):
        self.mirror(wait(5))
        self.settle(entry(5))
        env = dict(os.environ, MON_STUDIO=str(self.mon_studio), CLAUDE_CODE_HOST_SESSION_ID=ASKER)
        r = subprocess.run([sys.executable, str(QUESTION), 'notices'], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0)
        self.assertIn('Q5 · Titre 5 est réglée par la source', r.stdout)
        r = subprocess.run([sys.executable, str(QUESTION), 'notices'], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        env.pop('CLAUDE_CODE_HOST_SESSION_ID')
        r = subprocess.run([sys.executable, str(QUESTION), 'notices'], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout), (0, ''))


class EncoreOuvert(unittest.TestCase):
    """A recall written before the settlement makes no line; after a reopening, the question is back. The fixtures of
    test_cockpit_exits_and_sort, without its tests."""
    setUp, tearDown = board_tests.Board.setUp, board_tests.Board.tearDown
    session, board = board_tests.Board.session, board_tests.Board.board
    RECALL = "Logo posé.\n\nEncore ouvert : Q7 · Format"

    def settled(self, minutes_ago):
        return {'id': 'settled-source-Q7-x', 'type': 'settled', 'par': 'source', 'at': board_tests.at(minutes_ago),
                'number': 7, 'doc': 'n20261104-7', 'sessionId': board_tests.KIT, 'title': 'Q7 · Format',
                'text': "Réglé par l'ingestion auto : CR rangé"}

    def rows(self, journal):
        (board_tests.parc.CHANTIERS / 'essai.numero').write_text('9')
        kit = self.session(board_tests.KIT, [
            board_tests.final(40, "Prêt.\n\n## À trancher\n- **Q7 · Format :** A ou B ?"),
            board_tests.pm(30, "autre chose : le logo ?"), board_tests.final(20, self.RECALL)])
        line = board_tests.line(7, board_tests.KIT, 41, kind='task', title='Format')
        fresh, old, all_fresh = self.board([line], journal=journal, sessions=[kit])
        return fresh + old, [l for l in all_fresh if 'Q7' in (l.get('complet') or '') and not l.get('chantier')]

    def test_settled_by_the_source_no_line_from_an_older_recall(self):
        board, session = self.rows([self.settled(10)])
        self.assertEqual((board, session), ([], []))

    def test_reopened_it_is_back(self):
        reopened = {'id': 'reopened-source-Q7-x', 'type': 'reopened', 'par': 'pm', 'at': board_tests.at(5), 'number': 7,
                    'doc': 'n20261104-7', 'sessionId': board_tests.KIT, 'title': 'Q7 · Format'}
        board, _ = self.rows([self.settled(10), reopened])
        self.assertEqual(board, ['Q7'])


if __name__ == '__main__':
    unittest.main()
