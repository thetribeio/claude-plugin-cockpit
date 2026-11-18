"""Tests of the daily question numbers: python3 -m unittest discover -s tests

The PM, 2026-10-21: « pour moi ça peut se remettre à zéro par moment pour éviter cette grande suite, mais en évitant
les doublons ». The counter was at Q140 after 12 days and 192 questions, with never more than 20 lines open at once,
and the PM dictates the numbers by voice. So:

  - numbers start again from 1 at the first question of each working day (Paris time), then go up, each question
    taking the smallest free number above the last one given that day; a weekend or a public holiday goes on with the
    day before;
  - a number an open line holds is never given, and a number held less than 12 h ago (given, open, settled) neither;
  - a board document is no longer named by the number: n<YYYYMMDD>-<number>, unique for ever; old ones keep theirs;
  - `settle` acts only on an open line the settling session asked, otherwise it refuses and says who asked it;
  - Mon Studio never takes an old message that cites a number for the question that has it now: a message names an
    open line only if it came after the line was created.

Mon Studio folders, app cards, transcripts and mirrors here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
QUESTION = SCRIPTS / 'question.py'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


question, parc = load('question'), load('parc')
PARIS = question.PARIS
FOREMAN, KIT, OTHER = 'local_foreman', 'local_kit', 'local_other'
BOARD = 'https://claude.ai/artifact/AbCdEf'


def paris(text):
    """« 2026-10-21 09:00 », Paris time."""
    return dt.datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=PARIS)


def taken(steps, state=None, held=()):
    """The numbers `choose` gives at these times (« YYYY-MM-DD HH:MM »), from this state."""
    state, out = dict(state or {'jour': None, 'dernier': 0, 'vus': {}}), []
    for when in steps:
        n, state = question.choose(state, paris(when), set(held))
        out.append(n)
    return out, state


class Rule(unittest.TestCase):
    """The rule itself (question.choose), without any file."""

    def test_the_first_question_of_a_working_day_starts_again_from_1(self):
        got, _ = taken(['2026-10-21 09:00', '2026-10-21 09:05', '2026-10-21 16:00', '2026-10-22 09:30'])
        self.assertEqual(got, [1, 2, 3, 1])

    def test_within_a_day_numbers_go_up_even_when_a_lower_one_is_free_again(self):
        # Q1 given at 8:00 has rested 12 h by 20:30: the day goes on above the last number, Q1 waits for tomorrow.
        got, _ = taken(['2026-10-21 08:00', '2026-10-21 20:30', '2026-10-22 08:30'])
        self.assertEqual(got, [1, 2, 1])

    def test_an_open_number_is_reserved(self):
        got, _ = taken(['2026-10-22 09:00', '2026-10-22 09:01', '2026-10-22 09:02'], held={1, 3, 124, 140})
        self.assertEqual(got, [2, 4, 5])

    def test_the_smallest_free_number_above_the_last(self):
        state = {'jour': '2026-10-22', 'dernier': 3, 'vus': {}}
        got, _ = taken(['2026-10-22 10:00'], state, held={4, 5, 7})
        self.assertEqual(got, [6])

    def test_a_number_held_less_than_12_hours_ago_is_not_given_again(self):
        state = {'jour': '2026-10-21', 'dernier': 9, 'vus': {'1': paris('2026-10-21 20:31').isoformat(),
                                                             '2': paris('2026-10-21 20:29').isoformat()}}
        got, _ = taken(['2026-10-22 08:30'], state)
        self.assertEqual(got, [2])   # Q1 settled at 20:31 rests until 8:31; Q2, settled at 20:29, is free
        got, _ = taken(['2026-10-22 08:31'], state)
        self.assertEqual(got, [1])

    def test_the_retention_can_be_set(self):
        state = {'jour': '2026-10-21', 'dernier': 9, 'vus': {'1': paris('2026-10-21 20:00').isoformat()}}
        self.assertEqual(question.choose(state, paris('2026-10-22 08:30'), set(), retention=6 * 3600)[0], 1)
        self.assertEqual(question.choose(state, paris('2026-10-22 08:30'), set(), retention=24 * 3600)[0], 2)

    def test_a_weekend_goes_on_with_friday_and_monday_starts_again(self):
        got, _ = taken(['2026-10-23 10:00', '2026-10-23 11:00', '2026-10-24 10:00', '2026-10-25 18:00',
                        '2026-10-26 09:00'])
        self.assertEqual(got, [1, 2, 3, 4, 1])

    def test_a_weekend_after_a_quiet_friday_goes_on_with_thursday(self):
        got, _ = taken(['2026-10-22 10:00', '2026-10-24 10:00', '2026-10-26 09:00'])
        self.assertEqual(got, [1, 2, 1])

    def test_a_public_holiday_goes_on_with_the_day_before(self):
        # 11 November 2026 is a Wednesday; Ascension 2026 is Thursday 14 May (Easter on 5 April).
        got, _ = taken(['2026-11-10 10:00', '2026-11-11 10:00', '2026-11-12 10:00'])
        self.assertEqual(got, [1, 2, 1])
        self.assertEqual(question.easter(2026), dt.date(2026, 4, 5))
        self.assertFalse(question.working_day(dt.date(2026, 5, 14)))
        self.assertTrue(question.working_day(dt.date(2026, 5, 13)))

    def test_the_day_is_the_paris_day_across_the_clock_change(self):
        # Summer time ends on Sunday 25 October 2026 at 3:00. Monday 00:30 in Paris is still Sunday in UTC.
        state = {'jour': '2026-10-23', 'dernier': 7, 'vus': {}}
        monday = dt.datetime(2026, 10, 25, 23, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(question.choose(state, monday, set())[0], 1)
        sunday = dt.datetime(2026, 10, 25, 22, 30, tzinfo=dt.timezone.utc)   # 23:30 in Paris, Sunday
        self.assertEqual(question.choose(state, sunday, set())[0], 8)

    def test_12_hours_are_real_hours_across_the_clock_change(self):
        # Q1 held on Sunday 25/10 at 0:30 (summer time); at 11:45 (winter time), 12 h 15 have passed, 11 h 15 on the clock.
        state = {'jour': '2026-10-23', 'dernier': 0, 'vus': {'1': paris('2026-10-25 00:30').isoformat()}}
        self.assertEqual(paris('2026-10-25 00:30').utcoffset(), dt.timedelta(hours=2))
        self.assertEqual(question.choose(state, paris('2026-10-25 11:45'), set())[0], 1)
        self.assertEqual(question.choose(state, paris('2026-10-25 11:15'), set())[0], 2)

    def test_the_document_is_unique_for_ever_and_old_ones_still_read(self):
        self.assertEqual(question.document_id(3, paris('2026-10-22 00:30')), 'n20261022-3')
        self.assertEqual(question.document_id(3, dt.datetime(2026, 10, 21, 22, 30, tzinfo=dt.timezone.utc)), 'n20261022-3')
        self.assertEqual([question.number_of_document(d) for d in ('n20261022-3', 'n140', 'q12', '')], [3, 140, None, None])


class Chantier(unittest.TestCase):
    """A Mon Studio folder with one chantier and three sessions; the clock is MON_STUDIO_NOW."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.studio = root / 'studios' / 'Studio-Essai'
        (self.studio / 'projet').mkdir(parents=True)
        _isolation.make_studio(self.studio)
        self.mon_studio = root / 'Mon Studio'
        (self.mon_studio / 'chantiers').mkdir(parents=True)
        self.app = root / 'app'
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio)
        self.card(KIT, 'ᐅ Kit A · tâche', self.studio / 'projet')
        self.card(OTHER, 'ᐅ Kit B · photos', self.studio / 'projet')
        self.mirror = self.mon_studio / 'chantiers' / 'essai.json'
        self.pending = self.mon_studio / '.parc' / 'questions' / 'essai'
        self.write_mirror([])

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, sid, title, cwd):
        folder = self.app / 'acct' / 'org'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{sid}.json').write_text(json.dumps({'sessionId': sid, 'title': title, 'cwd': str(cwd)}))

    def write_mirror(self, waits):
        self.mirror.write_text(json.dumps({
            'chantier': 'Essai', 'studio': 'Studio-Essai', 'tableau': BOARD, 'sessionId': FOREMAN,
            'session': '* Studio-Essai · contremaître', 'attentes': waits,
            'lanes': [{'id': 'A', 'name': 'Kit A', 'sessionId': KIT}, {'id': 'B', 'name': 'Kit B', 'sessionId': OTHER}]},
            ensure_ascii=False))

    def waits(self):
        return json.loads(self.mirror.read_text())['attentes']

    def run_tool(self, *args, now, sid=KIT):
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_HOST_SESSION_ID'}
        env.update(MON_STUDIO=str(self.mon_studio), MON_STUDIO_APP_SESSIONS=str(self.app),
                   MON_STUDIO_NOW=paris(now).isoformat(), CLAUDE_CODE_HOST_SESSION_ID=sid)
        return subprocess.run([sys.executable, '-I', str(QUESTION), *args], capture_output=True, text=True, env=env,
                              cwd=self.tmp.name, input='')   # never the runner's stdin: `hook` reads it

    def take(self, now):
        return self.run_tool('take', 'Essai', now=now, sid=FOREMAN).stdout.splitlines()[0]

    def ask(self, title, now, sid=KIT):
        """A session asks a question (new), one call: (number, document)."""
        r = self.run_tool('new', '--title', title, now=now, sid=sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        n = int(r.stdout.split(' ', 1)[0][1:])
        (doc,) = [a['doc'] for a in self.waits() if question.highest([a['titre']]) == n and a.get('sessionId') == sid]
        return n, doc

    def settle(self, n, now, sid=KIT):
        return self.run_tool('settle', str(n), '--decision', f'Le PM : « go pour {n} »', now=now, sid=sid)


class Counter(Chantier):
    def test_a_day_then_the_next_one(self):
        self.assertEqual(self.ask('Photos : Drive seul ?', '2026-10-21 09:00'), (1, 'n20261021-1'))
        self.assertEqual(self.ask('Budget : on garde la ligne ?', '2026-10-21 09:05')[0], 2)
        self.assertEqual(self.settle(1, '2026-10-21 10:00').returncode, 0)
        # Thursday: Q1 settled 23 h ago comes back, Q2 still open keeps its number.
        self.assertEqual(self.ask('Slack : quel canal ?', '2026-10-22 09:00'), (1, 'n20261022-1'))
        self.assertEqual(self.take('2026-10-22 09:01'), 'Q3')
        self.assertEqual(sorted(a['doc'] for a in self.waits()), ['n20261021-2', 'n20261022-1'])
        # The highest number given stays in .numero for whoever reads it as such (parc.py).
        self.assertEqual((self.mon_studio / 'chantiers' / 'essai.numero').read_text().strip(), '3')

    def test_a_settled_number_rests_12_hours(self):
        self.ask('Photos : Drive seul ?', '2026-10-21 18:00')
        self.settle(1, '2026-10-21 21:00')
        self.assertEqual(self.take('2026-10-22 08:30'), 'Q2')   # Q1 settled 11 h 30 ago
        self.assertEqual(self.take('2026-10-23 08:30'), 'Q1')

    def test_a_line_an_older_version_left_pending_holds_its_number(self):
        self.pending.mkdir(parents=True)
        (self.pending / 'n20261021-1.json').write_text(json.dumps({'title': 'Q1 · Photos : Drive seul ?'}))
        self.assertEqual(self.take('2026-10-22 09:00'), 'Q2')

    def test_nothing_changes_before_the_next_working_day(self):
        # Wednesday 21/10, before the change: the counter is at 140 and Q124 to Q140 are open.
        numero = self.mon_studio / 'chantiers' / 'essai.numero'
        numero.write_text('140\n')
        os.utime(numero, (paris('2026-10-21 10:00').timestamp(),) * 2)
        self.write_mirror([{'type': 'decision', 'titre': f'Q{n} · Ouverte', 'doc': f'n{n}', 'sessionId': KIT}
                           for n in range(124, 141)])
        self.assertEqual(self.take('2026-10-21 15:00'), 'Q141')
        self.assertEqual(self.take('2026-10-21 15:01'), 'Q142')
        self.assertEqual(self.take('2026-10-22 09:00'), 'Q1')
        self.assertEqual([a['titre'][:4] for a in self.waits()][:2], ['Q124', 'Q125'])   # open lines keep their number

    def test_a_counter_left_on_another_day_starts_again_at_the_first_question(self):
        numero = self.mon_studio / 'chantiers' / 'essai.numero'
        numero.write_text('140\n')
        os.utime(numero, (paris('2026-10-21 18:00').timestamp(),) * 2)
        self.assertEqual(self.take('2026-10-22 09:00'), 'Q1')

    def test_take_gives_the_document_to_write(self):
        r = self.run_tool('take', 'Essai', now='2026-10-22 09:00', sid=FOREMAN)
        self.assertEqual(r.stdout.splitlines()[0], 'Q1')
        self.assertIn('Document : n20261022-1', r.stdout)
        self.assertIn('son titre', r.stdout)

    def test_old_documents_keep_their_name(self):
        self.write_mirror([{'type': 'decision', 'titre': 'Q5 · Ancienne', 'doc': 'n5', 'sessionId': KIT}])
        for when in ('2026-10-22 09:00', '2026-10-22 09:01', '2026-10-22 09:02', '2026-10-22 09:03', '2026-10-22 09:04'):
            self.ask('Une question ?', when)
        self.assertEqual(sorted(question.highest([a['titre']]) for a in self.waits()), [1, 2, 3, 4, 5, 6])
        self.assertEqual(sorted(a['doc'] for a in self.waits()),
                         ['n20261022-1', 'n20261022-2', 'n20261022-3', 'n20261022-4', 'n20261022-6', 'n5'])


class Settle(Chantier):
    def test_refused_for_a_question_another_session_asked(self):
        self.ask('Photos : Drive seul ?', '2026-10-22 09:00', sid=OTHER)
        r = self.settle(1, '2026-10-22 10:00', sid=KIT)
        self.assertEqual(r.returncode, 4)
        self.assertIn('Rien soldé', r.stdout)
        self.assertIn(f'« Q1 · Kit B : Photos : Drive seul ? », posée par la session « ᐅ Kit B · photos » ({OTHER})', r.stdout)
        self.assertIn('message natif', r.stdout)
        self.assertEqual(len(self.waits()), 1)
        self.assertFalse((self.mon_studio / 'chantiers' / 'essai.journal.jsonl').exists())

    def test_refused_for_a_line_of_the_foreman(self):
        self.write_mirror([{'type': 'go', 'titre': 'Q2 · Publier le kit ?', 'doc': 'q2'}])
        r = self.settle(2, '2026-10-22 10:00')
        self.assertEqual(r.returncode, 4)
        self.assertIn("« Q2 · Publier le kit ? », posée par une session d'avant", r.stdout)

    def test_accepted_for_its_own_question(self):
        n, doc = self.ask('Photos : Drive seul ?', '2026-10-22 09:00')
        r = self.settle(n, '2026-10-22 10:00')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('« Q1 · Kit A : Photos : Drive seul ? » soldée', r.stdout)   # one call, it names the question
        self.assertNotIn('ArtifactData', r.stdout)
        self.assertEqual(self.waits(), [])
        (entry,) = [json.loads(l) for l in (self.mon_studio / 'chantiers' / 'essai.journal.jsonl').read_text().splitlines()]
        self.assertEqual(entry['doc'], doc)


class Mentions(Chantier):
    """Each mention of a question outside its session carries its title."""

    def test_the_instructions_say_numbers_come_back_and_to_cite_the_title(self):
        out = self.run_tool('hook', now='2026-10-22 09:00').stdout
        self.assertIn('repartent de 1 chaque jour ouvré', out)
        self.assertIn('son numéro et son titre', out)

    def test_the_journal_and_the_fallbacks_carry_the_title(self):
        r = self.run_tool('new', '--title', 'Photos : Drive seul ?', now='2026-10-22 09:00')
        self.assertIn('Q1 · Kit A : Photos : Drive seul ?', r.stdout)
        self.run_tool('settle', '1', '--decision', 'go', now='2026-10-22 10:00')
        (entry,) = [json.loads(l) for l in (self.mon_studio / 'chantiers' / 'essai.journal.jsonl').read_text().splitlines()]
        self.assertEqual((entry['number'], entry['title'], entry['doc']),
                         (1, 'Q1 · Kit A : Photos : Drive seul ?', 'n20261022-1'))


# ---------- Mon Studio: a message names an open line only if it came after the line was created

NOW = time.time()


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def tool(minutes_ago):
    return [{'type': 'assistant', 'timestamp': at(minutes_ago),
             'message': {'id': f't{minutes_ago}', 'stop_reason': 'tool_use',
                         'content': [{'type': 'tool_use', 'id': f'b{minutes_ago}', 'name': 'Bash', 'input': {}}]}},
            {'type': 'user', 'timestamp': at(minutes_ago),
             'message': {'content': [{'type': 'tool_result', 'tool_use_id': f'b{minutes_ago}', 'content': 'ok'}]}}]


def card(sid, title):
    return {'id': sid, 'archivee': False, 'cwd': '/studios/Studio-Essai', 'titre': title, 'parent': None, 'tache': None}


CARDS = [card(FOREMAN, 'Contremaître'), card(KIT, 'ᐅ Kit A · tâche'), card(OTHER, 'ᐅ Kit B · photos')]
DAYS_3, HOURS_13 = 3 * 24 * 60, 13 * 60
ASK_PHOTOS = "Le kit est prêt.\n\n## À trancher\n- **Q5 · Photos :** Drive seul, ou Drive et Slack ?"
RECALL_PHOTOS = "Les fiches sont à jour.\n\nJ'attends ta réponse à Q5 pour les photos."


class Matching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _studio = unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True)   # synthetic folders: no manifest on disk
        _studio.start()
        self.addCleanup(_studio.stop)
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def session(self, sid, entries):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(next(c for c in CARDS if c['id'] == sid), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def board(self, *waits):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(1), 'attentes': list(waits)}))

    def rows(self, sessions):
        return parc.lignes_et_anciennes(sessions, CARDS, [], 7, NOW, {})[0]

    def recall_case(self, recalled_minutes_ago, created_minutes_ago):
        """KIT recalls its Q5 (Photos); the board's open Q5 now is another session's (Budget)."""
        self.board({'type': 'decision', 'titre': 'Q5 · Budget : on garde la ligne ?', 'source': OTHER,
                    'sessionId': OTHER, 'depuis': at(created_minutes_ago), 'ou': 'Kit B', 'doc': 'n20261022-5'})
        kit = self.session(KIT, [pm(recalled_minutes_ago + 20, 'vas-y'), final(recalled_minutes_ago + 10, ASK_PHOTOS),
                                 pm(recalled_minutes_ago + 5, 'je regarde'), final(recalled_minutes_ago, RECALL_PHOTOS)])
        return [(l.get('cle'), l.get('complet')) for l in self.rows([kit])]

    def test_an_old_recall_of_a_number_taken_again_another_day_keeps_its_line(self):
        rows = self.recall_case(DAYS_3, 60)
        self.assertIn((KIT, 'Photos : Drive seul, ou Drive et Slack ?'), rows)
        self.assertIn((FOREMAN, 'Q5 · Budget : on garde la ligne ?'), rows)

    def test_an_old_recall_of_a_number_taken_again_the_same_day_after_12_hours_keeps_its_line(self):
        rows = self.recall_case(HOURS_13, 30)
        self.assertIn((KIT, 'Photos : Drive seul, ou Drive et Slack ?'), rows)

    def test_a_recall_written_after_the_line_names_it(self):
        rows = self.recall_case(10, 60)
        self.assertNotIn((KIT, 'Photos : Drive seul, ou Drive et Slack ?'), rows)   # the board carries it

    def test_deja_au_tableau_dates_the_message(self):
        mirror = {'sessionId': FOREMAN, 'attentes': [{'titre': 'Q12 · Une', 'source': OTHER, 'depuis': at(60)},
                                                     {'titre': 'Q15 · Deux', 'source': OTHER, 'depuis': at(60)}]}
        on_board = parc.au_tableau([mirror])
        phrase = {'num': None, 'titre': '', 'suite': 'Toujours en attente de toi : Q12, Q15', 'depuis': NOW - DAYS_3 * 60}
        self.assertFalse(parc.deja_au_tableau(phrase, KIT, FOREMAN, on_board, NOW - DAYS_3 * 60))
        self.assertTrue(parc.deja_au_tableau(dict(phrase, depuis=NOW - 600), KIT, FOREMAN, on_board, NOW - 600))

    def settled(self, entries, created_minutes_ago):
        self.board({'type': 'decision', 'titre': 'Q5 · Budget : on garde la ligne ?', 'source': KIT, 'sessionId': KIT,
                    'depuis': at(created_minutes_ago), 'ou': 'Kit A', 'doc': 'n20261022-5'})
        return parc.reglees([self.session(KIT, entries)], parc.chantiers_actifs(CARDS), {})

    def test_an_old_question_under_the_same_number_does_not_settle_the_new_one(self):
        # KIT asked Q5 (Photos) three days ago and the PM answered. Its new Q5 (Budget), an hour ago, was put in prose:
        # nothing shows that KIT asked it under that number, so a word of the PM followed by work settles nothing.
        entries = [final(DAYS_3, ASK_PHOTOS), pm(DAYS_3 - 5, 'Q5 : Drive et Slack'), *tool(DAYS_3 - 6),
                   final(59, 'Je regarde le budget. On garde la ligne ou on la coupe ?'),
                   pm(30, 'Pour le Sheet, regarde la colonne C'), *tool(29)]
        self.assertEqual(self.settled(entries, 60), {})

    def test_same_number_same_day_after_12_hours(self):
        entries = [final(HOURS_13, ASK_PHOTOS), pm(HOURS_13 - 5, 'Q5 : Drive et Slack'), *tool(HOURS_13 - 6),
                   final(29, 'Je regarde le budget. On garde la ligne ou on la coupe ?'),
                   pm(20, 'Autre chose : le Sheet'), *tool(19)]
        self.assertEqual(self.settled(entries, 30), {})

    def test_the_new_question_asked_and_answered_still_settles(self):
        entries = [final(DAYS_3, ASK_PHOTOS), pm(DAYS_3 - 5, 'Q5 : Drive et Slack'), *tool(DAYS_3 - 6),
                   final(59, "Prêt.\n\n## À trancher\n- **Q5 · Budget :** on garde la ligne ?"),
                   pm(30, 'Q5 : on la garde'), *tool(29)]
        self.assertEqual(self.settled(entries, 60), {FOREMAN: {5: parc.FORTE}})

    def test_a_session_that_takes_a_number_again_asks_a_new_question(self):
        entries = [final(DAYS_3, ASK_PHOTOS), final(59, "Prêt.\n\n## À trancher\n- **Q5 · Budget :** on garde la ligne ?")]
        q = parc.historique_questions(entries)['5']
        self.assertEqual((q['titre'], q['depuis']), ('Q5 · Budget', parc.horodatage(entries[1])))
        # The same question asked again the next day stays the same question, with its first date.
        entries[1] = final(DAYS_3 - 24 * 60, ASK_PHOTOS)
        q = parc.historique_questions(entries)['5']
        self.assertEqual((q['titre'], q['depuis']), ('Q5 · Photos', parc.horodatage(entries[0])))

    def test_after_q5_means_the_q5_that_existed_then(self):
        def line(n, minutes_ago, attend=None):
            return {'chantier': 'Essai', 'num': n, 'attend': attend, 'depuis': NOW - minutes_ago * 60}
        old_wait, new_q5 = line(7, DAYS_3, attend=5), line(5, 60)
        out = parc.apres_leur_question([new_q5, old_wait])
        self.assertEqual(out, [new_q5, old_wait])
        self.assertNotIn('apres', old_wait)
        q5, wait = line(5, 120), line(7, 60, attend=5)
        out = parc.apres_leur_question([wait, q5])
        self.assertEqual((out, wait.get('apres')), ([q5, wait], 'Q5'))


if __name__ == '__main__':
    unittest.main()
