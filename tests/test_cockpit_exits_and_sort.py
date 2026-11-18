"""Tests of Q24 (PM, 2026-11-04): questions leave Mon Studio, and the rest is sorted. python3 -m unittest discover -s tests

A line leaves when it is settled anywhere (here: the local journal of its chantier, even when the mirror still holds
it, as Q25 of 30/10), when its session is archived, or when the PM wrote to its session after the question and the
session answered without carrying it over. The rest: at the top a band « En un clic » (authorizations and questions of
kind « clic »), then the questions, blocking first and then the most recently asked or carried over; a line no session
carried over for seven days goes to « Anciennes ». Cards, transcripts and mirrors here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

NOW = time.time()
FOREMAN, KIT, OTHER, GONE = 'local_foreman', 'local_kit', 'local_other', 'local_gone'


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def card(sid, title, archived=False):
    return {'id': sid, 'archivee': archived, 'cwd': '/studios/Studio-Essai', 'titre': title, 'parent': None, 'tache': None}


CARDS = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A'), card(OTHER, 'Kit B'), card(GONE, 'Kit C', archived=True)]
DAY = 24 * 60


def line(n, sid, minutes_ago, kind='decision', title=None, **more):
    return dict({'type': kind, 'titre': f'Q{n} · ' + (title or f'Question {n}'), 'source': sid, 'sessionId': sid,
                 'depuis': at(minutes_ago), 'doc': f'n20261104-{n}'}, **more)


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _studio = unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True)   # synthetic folders: no manifest on disk
        _studio.start()
        self.addCleanup(_studio.stop)
        self.saved = parc.CHANTIERS, parc.INTERNE
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.INTERNE = pathlib.Path(self.tmp.name) / '.parc'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS, parc.INTERNE = self.saved
        self.tmp.cleanup()

    def session(self, sid, entries):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(next(c for c in CARDS if c['id'] == sid), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def board(self, attentes, journal=(), sessions=()):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(1), 'attentes': list(attentes)}))
        (parc.CHANTIERS / 'essai.journal.jsonl').write_text(''.join(json.dumps(j) + '\n' for j in journal))
        fresh, old = parc.lignes_et_anciennes(list(sessions), CARDS, [], 7, NOW, {})
        q = lambda ls: [l['question'] for l in ls if l.get('chantier')]
        return q(fresh), q(old), fresh

    # --- exits

    def test_a_question_settled_in_the_journal_leaves_even_if_the_mirror_holds_it(self):
        settled = {'type': 'settled', 'at': at(5), 'number': 25, 'doc': 'n20261104-25', 'title': 'Q25 · Question 25',
                   'sessionId': KIT, 'text': 'go'}
        fresh, old, _ = self.board([line(25, KIT, 30), line(26, KIT, 20)], journal=[settled])
        self.assertEqual(fresh + old, ['Q26'])

    def test_a_number_taken_again_is_not_closed_by_an_old_settle(self):
        # Numbers start again each working day: only the same document (or, without one, same session, same title,
        # settled after the question) closes a line.
        old_settle = {'type': 'settled', 'at': at(3 * DAY), 'number': 25, 'doc': 'n20261030-25', 'title': 'Q25 · Question 25',
                      'sessionId': KIT}
        no_doc = {'type': 'settled', 'at': at(3 * DAY), 'number': 26, 'title': 'Q26 · Question 26', 'sessionId': KIT}
        fresh, _, _ = self.board([line(25, KIT, 30), dict(line(26, KIT, 20), doc=None)], journal=[old_settle, no_doc])
        self.assertEqual(sorted(fresh), ['Q25', 'Q26'])
        no_doc_after = dict(no_doc, at=at(10))
        fresh, _, _ = self.board([line(25, KIT, 30), dict(line(26, KIT, 20), doc=None)], journal=[no_doc_after])
        self.assertEqual(fresh, ['Q25'])

    def test_a_question_of_an_archived_session_leaves(self):
        fresh, old, _ = self.board([line(3, GONE, 30), line(4, KIT, 20)])
        self.assertEqual(fresh + old, ['Q4'])

    def test_a_reply_that_drops_the_question_makes_it_leave(self):
        kit = self.session(KIT, [final(40, "Prêt.\n\n## À trancher\n- **Q7 · Format :** A ou B ?"),
                                 pm(30, "fais comme tu le sens"), final(20, 'Format A posé.')])
        fresh, old, _ = self.board([line(7, KIT, 41)], sessions=[kit])
        self.assertEqual(fresh + old, [])

    def test_a_reply_that_carries_it_over_keeps_it(self):
        kit = self.session(KIT, [final(40, "Prêt.\n\n## À trancher\n- **Q7 · Format :** A ou B ?"),
                                 pm(30, "autre chose : le logo ?"), final(20, "Logo posé.\n\nEncore ouvert : Q7 · Format")])
        fresh, _, _ = self.board([line(7, KIT, 41)], sessions=[kit])
        self.assertEqual(fresh, ['Q7'])

    # --- sort

    def test_blocking_first_then_the_most_recent_and_the_kind_is_only_a_label(self):
        attentes = [line(1, KIT, 300, kind='go'), line(2, KIT, 100, kind='task'), line(3, OTHER, 200, kind='review', bloque=True),
                    line(4, OTHER, 50, kind='decision')]
        fresh, _, _ = self.board(attentes)
        self.assertEqual(fresh, ['Q3', 'Q4', 'Q2', 'Q1'])

    def test_a_question_carried_over_comes_back_on_top(self):
        kit = self.session(KIT, [final(400, "## À trancher\n- **Q1 · Vieux :** A ou B ?"),
                                 pm(30, 'je regarde demain'), final(10, "D'accord.\n\nEncore ouvert : Q1 · Vieux")])
        fresh, _, _ = self.board([line(1, KIT, 401), line(2, OTHER, 100)], sessions=[kit])
        self.assertEqual(fresh, ['Q1', 'Q2'])

    def test_nothing_carried_over_for_seven_days_goes_to_old_lines(self):
        fresh, old, _ = self.board([line(1, KIT, 8 * DAY), line(2, KIT, 6 * DAY)])
        self.assertEqual((fresh, old), (['Q2'], ['Q1']))
        kit = self.session(KIT, [final(8 * DAY, "## À trancher\n- **Q1 · Vieux :** A ou B ?"),
                                 pm(2 * DAY, 'pas encore'), final(2 * DAY - 1, "Bien.\n\nEncore ouvert : Q1 · Vieux")])
        fresh, old, _ = self.board([line(1, KIT, 8 * DAY + 1)], sessions=[kit])
        self.assertEqual((fresh, old), (['Q1'], []))

    def test_closed_answers_go_with_the_line(self):
        attentes = [line(1, KIT, 10, kind='go'), line(2, KIT, 11, kind='clic'),
                    line(3, KIT, 12, detail='Options : 1. Drive seul 2. Drive et Slack. Je recommande 2.'),
                    line(4, KIT, 13, detail='Drive ou Slack ?'), line(5, KIT, 14, kind='review')]
        _, _, rows = self.board(attentes)
        choix = {l['question']: l['choix'] for l in rows}
        self.assertEqual(choix, {'Q1': ['go', 'pas encore'], 'Q2': ['ok'], 'Q3': ['1', '2', 'pas encore'], 'Q4': None, 'Q5': None})
        self.assertEqual(next(l for l in rows if l['question'] == 'Q2')['verbe'], 'OK')
        self.assertIn('choix', parc.rang_page(rows[0]))


class MarkdownBand(unittest.TestCase):
    def test_authorizations_and_clic_lines_open_the_page_in_their_band(self):
        base = {'studio': 'Essai', 'session': 'Kit A', 'lien': 'claude://claude.ai/epitaxy/local_kit', 'depuis': NOW - 60,
                'affiche_titre': '', 'type': 'task', 'verbe': 'Faire', 'complet': ''}
        lignes = [dict(base, affiche_suite='Q2 · Garder la ligne ?', type='decision'),
                  dict(base, affiche_suite='Q3 · Lancer la fusion décidée hier', type='clic', verbe='OK'),
                  dict(base, affiche_suite='Arrêtée', arret='authorization', extrait='git push')]
        md = parc.rendre_md({'genere': NOW, 'tableau': lignes, 'anciennes': [], 'pastilles_lues': True})
        head, _, rest = md.partition('**En un clic (2)**')
        self.assertTrue(rest, md)
        band, _, table = rest.partition("| Studio | Session | Ce qui t'attend |")
        self.assertIn('git push', band)
        self.assertIn('Lancer la fusion', band)
        self.assertNotIn('Lancer la fusion', table)
        self.assertIn('Garder la ligne', table)


class QuestionKind(unittest.TestCase):
    def test_clic_is_a_kind_and_the_native_instruction_reserves_it(self):
        with tempfile.TemporaryDirectory() as d:
            home = pathlib.Path(d)
            ms = home / 'Mon Studio'
            (ms / '.parc').mkdir(parents=True)
            (ms / '.parc' / 'cockpit.json').write_text(json.dumps({}))
            app = home / 'app'
            (app / 'x' / 'y').mkdir(parents=True)
            sid = 'local_aaaaaaaa-0000-0000-0000-000000000001'
            (app / 'x' / 'y' / f'{sid}.json').write_text(json.dumps({'sessionId': sid, 'cwd': '/studios/Essai', 'title': 'Kit A'}))
            (ms / 'chantiers').mkdir()
            (ms / 'chantiers' / 'essai.json').write_text(json.dumps(
                {'chantier': 'Essai', 'sessionId': sid, 'dossiers': ['/studios/Essai'], 'attentes': []}))
            env = dict(os.environ, HOME=str(home), MON_STUDIO=str(ms), CLAUDE_CODE_HOST_SESSION_ID=sid,
                       MON_STUDIO_APP_SESSIONS=str(app))
            run = lambda *a, stdin='': subprocess.run([sys.executable, str(SCRIPTS / 'question.py'), *a], input=stdin,
                                                      capture_output=True, text=True, env=env, cwd='/', timeout=30)
            hook = run('hook', stdin=json.dumps({'cwd': '/studios/Essai'}))
            self.assertIn('--kind decision|go|review|task|clic', hook.stdout)
            self.assertIn('--kind clic seulement quand le fond est déjà décidé', hook.stdout)
            r = run('new', '--kind', 'clic', '--title', 'Lancer la fusion décidée hier')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            m = json.loads((ms / 'chantiers' / 'essai.json').read_text())
            self.assertEqual([a['type'] for a in m['attentes']], ['clic'])


class HookAndConnector(unittest.TestCase):
    def test_a_clic_waits_with_one_closed_answer(self):
        spec = importlib.util.spec_from_file_location('reponse_directe', ROOT / 'hooks' / 'reponse_directe.py')
        hook = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / 'hooks'))
        spec.loader.exec_module(hook)
        self.assertEqual(hook.choix_de({'type': 'clic'}), ['ok'])
        self.assertIn('clic', hook.GENRES)

    def test_the_connector_accepts_ok_and_copies_only_closed_answers(self):
        src = (SCRIPTS / 'mcp_mon_studio.py').read_text(encoding='utf-8')
        ns = {}
        exec(compile('import re\n' + src[src.index('LETTRES ='):src.index('\nOUTILS = [')], 'motif', 'exec'), ns)
        motif = ns['COPIE_MOTIF']
        import re
        # Without a number (Q33 of 2026-11-06): the answer alone, or an option's label in plain characters.
        for ok in ('Q25', 'Q25 go', 'Q25 pas encore', 'Q25 ok', 'Q3 2', 'go', 'pas encore', 'Garder la version courte'):
            self.assertTrue(re.fullmatch(motif[1:-1], ok), ok)
            self.assertTrue(re.match(motif, ok), ok)
        for ko in ('Q25 go; rm -rf', 'Q25 fais-le', 'Q25 0', 'Q25  go', 'go\nrm', ' go', 'a' * 81):
            self.assertFalse(re.fullmatch(motif[1:-1], ko), ko)


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class PageBand(unittest.TestCase):
    LOCAL = 'local_00000000-0000-0000-0000-00000000000a'

    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(ROOT / 'tests' / 'tester-epinglee.js'),
                                str(ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'), str(data)],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def row(self, n, kind, **more):
        return dict({'studio': 'Studio-Essai', 'session': 'Kit A', 'cle': self.LOCAL, 'ouvrir': self.LOCAL, 'type': kind,
                     'verbe': {'clic': 'OK', 'go': 'Go'}.get(kind, 'Répondre'), 'affiche_suite': f'Q{n} · Question {n}',
                     'question': f'Q{n}'}, **more)

    def test_a_clic_line_sits_in_the_band_with_one_button(self):
        # A gesture done elsewhere (only « ok ») stays in the band only with its https link (« Y aller ↗ »); without
        # a link it goes to the main table (PM, 2026-11-17).
        out = self.run_page({'lignes': [self.row(1, 'clic', choix=['ok'], detail='A faire sur https://example.org/geste'),
                                        self.row(2, 'go', choix=['go', 'pas encore']),
                                        self.row(3, 'clic', choix=['ok'])]})
        self.assertFalse(out['blocHidden'])
        self.assertEqual(out['blocTitre'], 'En un clic (1)')
        self.assertIn('Q1 · Question 1', out['clics'])
        self.assertNotIn('Q1 · Question 1', out['tableau'])
        self.assertIn('Q2 · Question 2', out['tableau'])
        self.assertIn('Q3 · Question 3', out['tableau'])
        self.assertNotIn('Q3 · Question 3', out['clics'])
        self.assertEqual(out['clics'].count('<button type="button" class="decide'), 1)
        self.assertIn('data-copier="Q1 ok"', out['clics'])
        self.assertIn('C&#39;est fait</button>', out['clics'])
        self.assertIn('Y aller ↗', out['clics'])

    def test_no_clic_and_no_authorization_hides_the_band(self):
        out = self.run_page({'lignes': [self.row(2, 'go', choix=['go', 'pas encore'])]})
        self.assertTrue(out['blocHidden'])
        self.assertEqual(out['clics'], '')

    def test_old_lines_are_collapsed_and_unfold_on_a_click(self):
        # Five fresh lines: no old one comes up (PM, 2026-11-12: below five, the first five old ones do).
        payload = {'lignes': [self.row(n, 'go') for n in range(2, 7)], 'anciennes': [self.row(9, 'decision')]}
        out = self.run_page(payload)
        self.assertNotIn('Q9 · Question 9', out['tableau'])
        self.assertFalse(out['anciennesHidden'])
        self.assertTrue(out['anciennesRepliees'])
        out = self.run_page(dict(payload, cliquer=[['anciennes-bascule', '1']]))
        self.assertFalse(out['anciennesRepliees'])
        self.assertIn('Q9 · Question 9', out['anciennes'])


if __name__ == '__main__':
    unittest.main()
