"""Tests: sessions stopped on an authorization lead Mon Studio: python3 -m unittest discover -s tests

PM, 2026-10-29: a session stopped on a tool waiting for his consent does nothing until he answers, so these lines
come first, in their own band « En un clic (N) » (PM, Q24 of 2026-11-04), and are not repeated below. Each stop line carries
an explicit field `arret` (authorization, error, menu; interrupted when the session stopped between two tools without
asking anything), so that the page never reads the sentence to know it. An authorization also carries `extrait`: the
tool's name, then its command, path or first useful text field, on one line, cut at about 200 characters.

Cards and transcripts are synthetic; the page runs in a fake browser (tests/tester-epinglee.js) when node is there."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

NOW = time.time()


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def calls(minutes_ago, mid, *tools):
    """One message of Claude calling tools: each (id, name, input) in its own transcript entry, as the app writes them."""
    return [{'type': 'assistant', 'timestamp': at(minutes_ago),
             'message': {'id': mid, 'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': i, 'name': n, 'input': e}]}}
            for i, n, e in tools]


def result(minutes_ago, tool_id):
    return {'type': 'user', 'timestamp': at(minutes_ago),
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': tool_id, 'content': 'ok'}]}}


def api_error(minutes_ago):
    return {'type': 'assistant', 'timestamp': at(minutes_ago), 'isApiErrorMessage': True,
            'message': {'id': 'err', 'model': '<synthetic>', 'content': [{'type': 'text', 'text': 'API Error: overloaded'}]}}


def trace_request(cli):
    """The PermissionRequest hook's trace (hooks/autorisation.py): without it, a pending tool only runs long."""
    d = parc.INTERNE / 'demandes-autorisation'
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{cli}.json').write_text(json.dumps({'t': NOW, 'outil': ''}))


LONG = 'python3 scripts/export.py --from 2026-10-01 --to 2026-10-28 \\\n  --format csv ' + '--column x ' * 40

SESSIONS = {
    'local_bash': ('Kit A · déploiement', [pm(60, 'Pousse la branche.'),
                                          *calls(59, 'm1', ('t1', 'Bash', {'command': 'git push origin feat/x', 'description': 'Push'}))]),
    'local_write': ('Kit B · notes', [pm(50, 'Écris les notes.'),
                                     *calls(49, 'm2', ('t2', 'Write', {'file_path': '/tmp/essai/notes.md', 'content': 'Bonjour\nà tous'}))]),
    'local_mcp': ('Kit C · annonce', [pm(40, 'Annonce la démo.'),
                                     *calls(39, 'm3', ('t3', 'mcp__chat__send_message',
                                                       {'channel_id': 'C0000', 'text': 'La démo est\njeudi à 10 h.'}))]),
    'local_long': ('Kit D · export', [pm(35, 'Exporte.'), *calls(34, 'm4', ('t4', 'Bash', {'command': LONG}))]),
    # Two tools in one message: the first one ran, the second waits for the PM.
    'local_pair': ('Kit E · lecture', [pm(30, 'Lis et nettoie.'),
                                      *calls(29, 'm5', ('t5', 'Read', {'file_path': '/tmp/essai/a.md'}),
                                             ('t6', 'Bash', {'command': 'rm -rf build'})),
                                      result(28, 't5')]),
    'local_error': ('Kit F · erreur', [pm(25, 'Continue.'), api_error(24)]),
    'local_menu': ('Kit G · menu', [pm(20, 'Quel format ?'),
                                   *calls(19, 'm7', ('t7', 'AskUserQuestion',
                                                     {'questions': [{'question': 'Quel format ?', 'header': 'Format', 'multiSelect': False,
                                                                     'options': [{'label': 'Court', 'description': ''},
                                                                                 {'label': 'Long', 'description': ''}]}]}))]),
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS, parc.STOCKAGE_APP)
        parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS = root / 'app', root / 'transcripts', root / 'chantiers'
        parc.STOCKAGE_APP = root / 'leveldb'   # never the PM's real app storage
        parc.CHANTIERS.mkdir()
        (parc.TRANSCRIPTS / 'proj').mkdir(parents=True)
        (parc.APP / 'acct' / 'org').mkdir(parents=True)
        for sid, (title, entries) in SESSIONS.items():
            cli = 'cli-' + sid
            (parc.APP / 'acct' / 'org' / f'{sid}.json').write_text(json.dumps(
                {'sessionId': sid, 'cliSessionId': cli, 'title': title, 'cwd': '/studios/Studio-Essai'}))
            path = parc.TRANSCRIPTS / 'proj' / f'{cli}.jsonl'
            path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
            os.utime(path, (NOW - 900, NOW - 900))
            trace_request(cli)
        cache = {'version': parc.VERSION_CACHE, 'fiches': {}, 'transcripts': {}, 'suivi': {}, 'controle': {}}
        self.e = parc.construire(7, 7, NOW, cache)

    def tearDown(self):
        parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS, parc.STOCKAGE_APP = self.saved
        self.tmp.cleanup()

    def line(self, sid):
        (l,) = [l for l in self.e['tableau'] if l['cle'] == sid]
        return l


class StopField(Fixture):
    def test_each_stop_line_says_which_stop_it_is(self):
        for sid in ('local_bash', 'local_write', 'local_mcp', 'local_long', 'local_pair'):
            self.assertEqual(self.line(sid)['arret'], 'authorization', sid)
        self.assertEqual(self.line('local_error')['arret'], 'error')
        self.assertEqual(self.line('local_menu')['arret'], 'menu')

    def test_the_extract_names_the_tool_then_what_it_would_do(self):
        self.assertEqual(self.line('local_bash')['extrait'], 'commande du terminal · git push origin feat/x')
        self.assertEqual(self.line('local_write')['extrait'], "écriture d'un fichier · /tmp/essai/notes.md")
        self.assertEqual(self.line('local_mcp')['extrait'], 'chat : send message · La démo est jeudi à 10 h.')

    def test_a_long_input_is_cut_on_one_line(self):
        x = self.line('local_long')['extrait']
        self.assertLessEqual(len(x), 200)
        self.assertNotIn('\n', x)
        self.assertTrue(x.startswith('commande du terminal · python3 scripts/export.py --from'))
        self.assertTrue(x.endswith('…'))

    def test_the_tool_still_waiting_is_the_one_shown_when_another_ran(self):
        self.assertEqual(self.line('local_pair')['extrait'], 'commande du terminal · rm -rf build')

    def test_an_error_and_a_menu_have_no_extract(self):
        self.assertNotIn('extrait', self.line('local_error'))
        self.assertNotIn('extrait', self.line('local_menu'))

    def test_the_lines_keep_their_words(self):
        """Nothing detected before is lost: the stop lines say what they said."""
        self.assertEqual(self.line('local_bash')['suite'],
                         'Arrêtée en plein travail (commande du terminal) : une autorisation à donner, ou la session à relancer')
        self.assertTrue(self.line('local_error')['suite'].startswith('Arrêtée sur une erreur, à relancer'))
        self.assertEqual(len(self.e['tableau']), len(SESSIONS))

    def test_a_session_stopped_between_two_tools_is_not_an_authorization(self):
        entries = [pm(30, 'Lis.'), *calls(29, 'm9', ('t9', 'Read', {'file_path': '/tmp/a'})), result(28, 't9')]
        path = pathlib.Path(self.tmp.name) / 'between.jsonl'
        path.write_text(''.join(json.dumps(e) + '\n' for e in entries))
        os.utime(path, (NOW - 900, NOW - 900))
        r = parc._analyser(str(path), NOW)
        self.assertEqual(r['etat'], 'suspens')
        self.assertNotIn('attente', r)

    def test_the_page_gets_both_fields(self):
        rows = {r['cle']: r for r in parc.pour_la_page(self.e)['lignes']}
        self.assertEqual(rows['local_bash']['arret'], 'authorization')
        self.assertEqual(rows['local_bash']['extrait'], 'commande du terminal · git push origin feat/x')
        self.assertEqual(rows['local_error']['arret'], 'error')
        self.assertIsNone(rows['local_error']['extrait'])


class MarkdownBlock(Fixture):
    def test_the_block_comes_first_and_its_lines_are_not_repeated(self):
        md = parc.rendre_md(self.e)
        head, _, rest = md.partition('**En un clic (5)**')
        self.assertTrue(rest, md)
        self.assertNotIn('| Studio | Session | Ce qui t\'attend |', head)
        block, _, below = rest.partition('| Studio | Session | Ce qui t\'attend |')
        self.assertIn('`commande du terminal · git push origin feat/x`', block)
        self.assertIn('`chat : send message · La démo est jeudi à 10 h.`', block)
        self.assertNotIn('Kit F · erreur', block)
        self.assertNotIn('Kit G · menu', block)
        self.assertNotIn('Kit A · déploiement', below)
        self.assertIn('Kit F · erreur', below)
        self.assertIn('Kit G · menu', below)

    def test_a_line_without_extract_says_where_the_detail_is(self):
        l = dict(self.line('local_bash'))
        l.pop('extrait')
        self.assertIn('détail dans la session', parc.rang_autorisation_md(l, NOW))


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class PinnedPage(Fixture):
    def run_page(self, payload, **env):
        data = pathlib.Path(self.tmp.name) / 'payload.json'
        data.write_text(json.dumps(payload, ensure_ascii=False))
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL, env=dict(os.environ, **env))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    DEMANDE = {'id': 'd' * 32, 'session': 'x', 'sessionId': 'local_bash', 'extrait': 'commande du terminal · git push origin feat/x',
               'depuis': 1}

    def live(self, rows, *demandes):
        return self.run_page({'lignes': rows, 'autorisations': {'actif': True, 'demandes': list(demandes), 'decisions': []}})

    def test_the_block_heads_the_page_and_its_lines_are_not_repeated(self):
        out = self.live(parc.pour_la_page(self.e)['lignes'], self.DEMANDE)
        self.assertFalse(out['blocHidden'])
        self.assertEqual(out['blocTitre'], 'En un clic (1)')
        self.assertIn('commande du terminal · git push origin feat/x', out['bloc'])
        self.assertIn('Kit A · déploiement', out['bloc'])
        self.assertIn('data-sid="local_bash"', out['bloc'])
        self.assertNotIn('Kit F · erreur', out['bloc'])
        self.assertNotIn('Kit A · déploiement', out['tableau'])
        self.assertIn('Kit F · erreur', out['tableau'])
        self.assertIn('Kit G · menu', out['tableau'])

    def test_a_line_without_extract_says_where_the_detail_is(self):
        rows = parc.pour_la_page(self.e)['lignes']
        for r in rows:
            r['extrait'] = None
        self.assertIn('détail dans la session', self.live(rows, dict(self.DEMANDE, extrait=''))['bloc'])

    def test_a_line_without_request_goes_to_the_board(self):
        # PM, Q31 of 2026-11-06: only what a click settles stays in « En un clic »; a stop without a pending request
        # is an ordinary line of the board, « Ouvrir ↗ » to its session.
        rows = parc.pour_la_page(self.e)['lignes']
        texte = 'Session arrêtée sur une autorisation : à rouvrir'
        for payload in ({'actif': False, 'demandes': [], 'decisions': []}, {'actif': True, 'demandes': [], 'decisions': []}):
            out = self.run_page({'lignes': rows, 'autorisations': payload})
            self.assertTrue(out['blocHidden'])
            self.assertEqual(out['tableau'].count('class="titre">' + texte), 5)
            self.assertIn('Ouvrir ↗', out['tableau'])
            self.assertNotIn("avant l'allumage", out['tableau'] + out['bloc'])
        one = self.live(rows, self.DEMANDE)
        self.assertEqual(one['tableau'].count('class="titre">' + texte), 4)
        self.assertEqual(one['bloc'].count('Autoriser cette fois'), 1)

    def test_the_page_never_reads_the_sentence(self):
        """A stop line without the field stays in the table: the page knows the stop by `arret` alone."""
        rows = parc.pour_la_page(self.e)['lignes']
        for r in rows:
            r.pop('arret', None)
        out = self.run_page({'lignes': rows})
        self.assertTrue(out['blocHidden'])
        self.assertIn('Kit A · déploiement', out['tableau'])


if __name__ == '__main__':
    unittest.main()
