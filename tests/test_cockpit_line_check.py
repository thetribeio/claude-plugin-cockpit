"""Tests of the check of Mon Studio's lines: python3 -m unittest discover -s tests

Framing of 2026-10-19 (Q103, Q105): a misread line is spotted before the PM sees it, and no reading rule is added
without a counted case. Every line of the board says where its text comes from (« lecture »); the calculation notes
it in the cache, which only the pinned page's connector and the local screen save; `parc.py --controle` prints the
tally and the lines to check (free sentences, recalled questions found nowhere). Transcripts here are synthetic."""
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

NOW = time.time()
FOREMAN = 'local_foreman'
STUDIO, OTHER = '/studios/Studio-Essai', '/studios/Studio-Autre'


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def final(hours_ago, text, mid):
    return {'type': 'assistant', 'timestamp': at(hours_ago),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(hours_ago, text):
    return {'type': 'user', 'timestamp': at(hours_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def card(sid, title, cwd=OTHER):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


FORMAT = "Le plan est prêt.\n\n## À trancher\n\n**Q2 · Format du CR** : court ou long ? Je recommande court."
PHRASE = ("J'ai préparé le devis et le planning.\n\nReste à faire de ton côté, hors de cette conversation :\n\n"
          "- appeler le client pour la date\n- signer le devis")
ASKED_5 = "Deux options.\n\n## À trancher\n\n**Q5 · Hébergement** : chez le client ou chez nous ? Je recommande chez nous."
RECALL_5 = "La maquette est faite.\n\nEncore ouvert : Q5"
LOST_7 = "La PR est ouverte.\n\nEncore ouvert : Q7"


class Lines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def session(self, sid, entries, cwd=OTHER):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, 'Session ' + sid, cwd), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def board(self):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps({
            'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(3),
            'attentes': [{'type': 'go', 'titre': 'Q40 · Kit A : je publie ?', 'depuis': at(3), 'detail': 'Publication du kit.'}]}))
        sessions = [self.session('local_format', [final(2, FORMAT, 'm1')]),
                    self.session('local_phrase', [final(2, PHRASE, 'm2')]),
                    self.session('local_recall', [final(5, ASKED_5, 'm3'), pm(4, 'Je regarde.'), final(2, RECALL_5, 'm4')]),
                    self.session('local_lost', [final(2, LOST_7, 'm5')])]
        metas = [card(FOREMAN, 'Contremaître', STUDIO)] + [card(s['id'], s['titre']) for s in sessions]
        autos = [{'ok': False, 'nom': 'Ingestion auto', 'lien': 'local_auto', 'cwd': OTHER, 'detail': 'limite atteinte', 'ts': NOW - 600,
                  'carte': None, 'arret': {'quoi': 'error', 'raison': 'limite atteinte', 'depuis': NOW - 600}}]
        return parc.tableau(sessions, metas, autos, 7, NOW, {})

    def test_every_line_says_where_its_text_comes_from(self):
        got = {(l['cle'], l['lecture']) for l in self.board()}
        self.assertEqual(got, {('local_format', 'format'), ('local_phrase', 'a_verifier'), ('local_recall', 'rappel'),
                               ('local_lost', 'introuvable'), ('local_auto', 'auto'), (FOREMAN, 'inscrite')})

    def test_a_menu_line_says_menu(self):
        menu = [{'question': 'Je publie ?', 'options': [{'label': 'Oui', 'description': '', 'recommande': True}]}]
        self.assertEqual(parc.ligne_menu(menu, NOW)['lecture'], 'menu')

    def test_the_report_counts_them_and_lists_those_to_check(self):
        cache = {}
        parc.noter_controle(cache, self.board(), NOW)
        report = parc.rapport_controle(cache['controle'], 7, NOW)
        for line in ('6 ligne(s)', '- 1 inscrites au tableau du chantier', '- 1 questions au format « À trancher »',
                     '- 1 questions rappelées et retrouvées', '- 1 lignes automatiques',
                     '- 1 sessions qui ne disent pas si elles attendent',
                     '- 1 questions rappelées introuvables', 'À vérifier (2)'):
            self.assertIn(line, report)
        self.assertIn('session qui ne dit pas si elle attend : « Reste à faire de ton côté, hors de cette conversation »', report)
        self.assertIn('question introuvable : « Q7 · ', report)
        self.assertNotIn('Format du CR', report.split('À vérifier')[1])


class Record(unittest.TestCase):
    LINE = {'cle': 'local_a', 'complet': 'Reste à faire de ton côté', 'lecture': 'phrase', 'studio': 'Studio-Autre',
            'session': 'Session a', 'detail': 'Reste à faire de ton côté'}

    def test_first_seen_stays_last_seen_moves(self):
        cache = {}
        parc.noter_controle(cache, [self.LINE], NOW - 3600)
        parc.noter_controle(cache, [self.LINE], NOW)
        (ent,) = cache['controle'].values()
        self.assertEqual((ent['vue'], ent['revue'], ent['lecture']), (NOW - 3600, NOW, 'phrase'))

    def test_a_line_not_seen_for_a_month_goes(self):
        cache = {}
        parc.noter_controle(cache, [self.LINE], NOW - 31 * 86400)
        parc.noter_controle(cache, [], NOW)
        self.assertEqual(cache['controle'], {})

    def test_nothing_to_check(self):
        cache = {}
        parc.noter_controle(cache, [dict(self.LINE, lecture='format', complet='Q2 · Format du CR')], NOW)
        self.assertIn('À vérifier : rien.', parc.rapport_controle(cache['controle'], 7, NOW))

    def test_lines_older_than_the_window_are_left_out(self):
        cache = {}
        parc.noter_controle(cache, [self.LINE], NOW - 10 * 86400)
        parc.noter_controle(cache, [self.LINE], NOW)
        self.assertIn(': 0 ligne(s).', parc.rapport_controle(cache['controle'], 7, NOW))
        self.assertIn(': 1 ligne(s).', parc.rapport_controle(cache['controle'], 14, NOW))


class SavedCache(unittest.TestCase):
    """Only the callers that save the cache (connector, local screen) keep the record; a cache version change keeps
    it; `--controle` reads it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mon_studio = pathlib.Path(self.tmp.name) / 'Mon Studio'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.saved = parc.INTERNE
        parc.INTERNE = self.mon_studio / '.parc'

    def tearDown(self):
        parc.INTERNE = self.saved
        self.tmp.cleanup()

    def write_cache(self, version):
        rec = {'local_a|Reste à faire': {'lecture': 'phrase', 'studio': 'Studio-Autre', 'session': 'Session a',
                                         'texte': 'Reste à faire de ton côté', 'detail': '', 'vue': NOW - 60, 'revue': NOW}}
        (parc.INTERNE / 'cache.json').write_text(json.dumps({'version': version, 'fiches': {'x': 1}, 'controle': rec}))

    def test_a_cache_version_change_keeps_the_record(self):
        self.write_cache(parc.VERSION_CACHE - 1)
        c = parc.charger_cache()
        self.assertEqual((c['fiches'], list(c['controle'])), ({}, ['local_a|Reste à faire']))

    def test_the_command_prints_the_report(self):
        self.write_cache(parc.VERSION_CACHE)
        env = dict(os.environ, MON_STUDIO=str(self.mon_studio))
        out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'parc.py'), '--controle'], capture_output=True,
                             text=True, env=env, check=True).stdout
        self.assertIn('Contrôle des lignes de Mon Studio', out)
        self.assertIn('phrase libre : « Reste à faire de ton côté »', out)


if __name__ == '__main__':
    unittest.main()
