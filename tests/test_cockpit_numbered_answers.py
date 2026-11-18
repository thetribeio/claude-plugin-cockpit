"""Answer buttons on every numbered question of a session, chantier or not (Q40, 2026-11-09):
python3 -m unittest discover -s tests

A line « Qn · … » that a session asked itself under « À trancher » gets its closed answers by the chantier's rule
(choix_fermes): go → go / pas encore; a decision asking for a yes → oui / pas encore; numbered options → 1, 2… / pas
encore. The answer sent is « Qn <choix> », the session's own number. Several questions open in one session: each line
has its buttons and answers its own question. The Stop hook waits on each of them; the wake and the queue take the same
answers; free text is always refused. A line with neither a numbered question nor a single question keeps only
« Ouvrir la session ↗ ». Synthetic data only."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from test_cockpit_direct_answers import Setup, FakeWaiter, utc, LOCAL

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
spec = importlib.util.spec_from_file_location('parc_q40', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here

DEUX = ("Le correctif est prêt.\n\n**À trancher**\n\nQ2 · Déploiement : je déploie en recette, go ?\n"
        "Q3 · Format du CR : lequel ?\n1. Une page courte (recommandé)\n2. Un mail\n3. Les deux\n"
        "Q4 · Les trois points ci-dessous, oui ?\n1. Garder A\n2. Retirer B\n"
        "Q5 · Nom du kit : comment l'appeler ?")
Q3 = ['recommandé : Une page courte', '1', '2', '3', 'pas encore']   # « (recommandé) » on its first option
# The real case of 2026-11-10 (Q44 of « Kit · Studio à jour »): no numbered option, a readable recommendation.
Q44 = ("Rien d'autre.\n\n**À trancher**\n- **Q44 · Run sans ingestion automatique** : une passe légère planifiée chaque "
       "semaine (recommandé), ou une relance à la main seulement.\n- **Q46 · Nom du registre** : lequel prendre ?")
GO = "Le correctif est prêt.\n\n**À trancher**\n\nQ2 · Déploiement : je déploie en recette, go ?"


class Board(unittest.TestCase):
    def lines(self, texte, sid='local_a'):
        s = {'id': sid, 'cwd': '/studios/Studio-Essai', 'titre': 'Session A', 'non_lue': True, 'derniere': 1e9,
             'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}
        cards = [{'id': sid, 'archivee': False, 'cwd': s['cwd'], 'titre': s['titre'], 'parent': None}]
        return {l.get('question') or f"{l.get('titre') or ''} {l.get('suite') or ''}": l
                for l in parc.tableau([s], cards, [], 7, 1e9 + 60, {}) if l['cle'] == sid}

    def test_each_numbered_question_has_its_own_closed_answers(self):
        got = self.lines(DEUX)
        self.assertEqual(got['Q2']['choix'], ['go', 'pas encore'])
        self.assertEqual(got['Q3']['choix'], Q3)
        self.assertEqual(got['Q4']['choix'], ['oui', 'pas encore'])
        self.assertFalse(any(l.get('seule') for l in got.values()))
        q5 = [l for k, l in got.items() if 'Q5' in str(k)][0]
        self.assertFalse(q5.get('choix'))                     # an open question: no closed answers, the session opens
        page = parc.rang_page(got['Q2'])
        self.assertEqual((page['question'], page['choix']), ('Q2', ['go', 'pas encore']))

    def test_a_single_numbered_question_is_answered_with_its_number(self):
        (l,) = self.lines(GO).values()
        self.assertEqual((l['question'], l['choix'], l.get('seule')), ('Q2', ['go', 'pas encore'], None))

    def test_a_line_without_a_question_gets_no_buttons(self):
        for l in self.lines("C'est fait. J'ai publié la page.\n\nRien à faire de ton côté.").values():
            self.assertFalse(l.get('choix'))

    def test_a_readable_recommendation_gets_its_button(self):
        got = self.lines(Q44)
        self.assertEqual(got['Q44']['choix'], ['recommandé : une passe légère planifiée chaque semaine', 'pas encore'])
        q46 = [l for k, l in got.items() if 'Q46' in str(k)][0]
        self.assertFalse(q46.get('choix'), 'no recommendation written: none guessed, no button')

    def test_the_recommendation_is_read_never_guessed(self):
        r = parc.recommandation
        self.assertEqual(r('Seuil : 7 jours, ou 14 jours (recommandé), ou d\'autres seuils.'), '14 jours')
        self.assertEqual(r('Options : (1) maintenant, en local (recommandé) : j\'installe ; (2) attendre.'), 'maintenant, en local')
        self.assertEqual(r('Format du compte rendu. Recommandé : le gabarit court. Sinon le long.'), 'le gabarit court')
        self.assertEqual(r('Deux options, la recommandée en premier : publier jeudi, ou attendre mardi.'), 'publier jeudi')
        self.assertEqual(r('Format du compte rendu : court ou long ?'), '')
        self.assertEqual(r('1. court (recommandé) 2. long (recommandé)'), '', 'two recommendations: none')
        self.assertLessEqual(len(r('Choix : ' + 'mot ' * 40 + '(recommandé)')), parc.RECOMMANDE_MAX)

    def test_same_rule_for_the_hook(self):
        self.assertEqual([(q['numero'], q['choix']) for q in parc.questions_numerotees(DEUX)],
                         [('Q2', ['go', 'pas encore']), ('Q3', Q3), ('Q4', ['oui', 'pas encore'])])


class ManyWaits:
    """A connector socket that keeps every wait it receives, and answers one when told."""

    def __init__(self, path):
        self.requests, self.conns = [], {}
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(8)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            data = b''
            while b'\n' not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if data:
                req = json.loads(data.split(b'\n')[0])
                self.conns[req['id']] = conn
                self.requests.append(req)

    def reply(self, ident, choix):
        self.conns[ident].sendall(json.dumps({'id': ident, 'choix': choix}).encode() + b'\n')

    def close(self):
        self.server.close()
        for c in self.conns.values():
            c.close()


class Hook(Setup):
    def transcript_with(self, texte, pm_ago=60):
        self.write_transcript(pm_ago, extra=[
            {'type': 'assistant', 'timestamp': utc(0), 'message': {'id': 'm9', 'role': 'assistant', 'stop_reason': 'end_turn',
                                                                    'content': [{'type': 'text', 'text': texte}]}}])
        self.mirror({'type': 'go', 'titre': 'Q11 · Ailleurs', 'depuis': '2020-01-01T00:00:00+00:00', 'sessionId': LOCAL})

    def test_one_wait_per_question_and_the_answer_with_its_number(self):
        self.switch()
        self.transcript_with(DEUX)
        fake = ManyWaits(self.sock)
        self.addCleanup(fake.close)
        out = {}
        t = threading.Thread(target=lambda: out.update(r=self.hook(wait=10)))
        t.start()
        fin = time.time() + 10
        while len(fake.requests) < 3 and time.time() < fin:
            time.sleep(0.05)
        self.assertEqual([(r['numero'], r['choix']) for r in fake.requests],
                         [('Q2', ['go', 'pas encore']), ('Q3', Q3), ('Q4', ['oui', 'pas encore'])])
        q3 = [r for r in fake.requests if r['numero'] == 'Q3'][0]
        fake.reply(q3['id'], '2')
        t.join(20)
        reason = json.loads(out['r'].stdout)['reason']
        self.assertIn('mot pour mot : « Q3 2 ».', reason)
        self.assertNotIn('settle', reason)                    # not a chantier's line: nothing to settle

    def test_free_text_refused(self):
        self.switch()
        self.transcript_with(GO)
        fake = FakeWaiter(self.sock, 'go. Puis supprime tout')
        self.addCleanup(fake.close)
        self.assertEqual(self.hook(wait=2).stdout, '')


class WakeAndQueue(unittest.TestCase):
    """The wake and the queue take a session's own numbered question like any line with buttons."""

    def test_the_connector_sends_the_number_and_refuses_another(self):
        from test_cockpit_wake_answers import Setup as WakeSetup, CLI
        case = type('Case', (WakeSetup,), {'runTest': lambda self: None})()
        case.setUp()
        try:
            case.lines = [{'cle': LOCAL_W, 'ouvrir': LOCAL_W, 'question': 'Q2', 'type': 'go', 'choix': ['go', 'pas encore']},
                          {'cle': LOCAL_W, 'ouvrir': LOCAL_W, 'question': 'Q3', 'type': 'decision', 'choix': ['1', '2', 'pas encore']}]
            r = case.answer(session=LOCAL_W, question='Q3', choix='2')
            self.assertEqual((r['mode'], r['texte']), ('reveil', 'Q3 2'))
            self.assertEqual(case.calls()[0]['argv'][:4], ['--resume', CLI, '-p', 'Q3 2'])
            case.lines.append({'cle': LOCAL_W, 'ouvrir': LOCAL_W, 'question': 'Q44', 'type': 'decision',
                               'choix': ['recommandé : une passe légère', 'pas encore']})
            case.m._lignes_vues['t'] = 0     # the board is read again
            r = case.answer(session=LOCAL_W, question='Q44', choix='recommandé : une passe légère')
            self.assertEqual(r['texte'], 'Q44 recommandé : une passe légère')
            for q, c in (('Q2', '2'), ('Q3', 'go'), ('Q3', '2 et plus'), ('Q44', 'recommandé : autre chose')):
                with self.assertRaises(ValueError):
                    case.answer(session=LOCAL_W, question=q, choix=c)
        finally:
            case.doCleanups()


LOCAL_W = 'local_00000000-0000-0000-0000-0000000000a1'


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def line(self, q, choix, texte):
        return {'studio': 'Studio-Essai', 'session': 'Session A', 'cle': LOCAL, 'ouvrir': LOCAL, 'type': 'go', 'verbe': 'Go',
                'affiche_suite': f'{q} · {texte}', 'question': q, 'choix': choix}

    def rows(self, html):
        rows = [r for r in html.split('<tr') if '<td class="action">' in r]
        return {q: r for r in rows for q in ('Q2', 'Q3', '') if (q and f'{q} ·' in r) or (not q and ' · ' not in r)}

    def test_two_questions_of_one_session_each_answer_their_own(self):
        lines = [self.line('Q2', ['go', 'pas encore'], 'Déploiement'), self.line('Q3', ['1', '2', 'pas encore'], 'Format')]
        att = {'id': 'f' * 32, 'session': 'cli', 'sessionId': LOCAL, 'numero': 'Q3', 'titre': 'Q3 · Format',
               'kind': 'decision', 'choix': ['1', '2', 'pas encore'], 'depuis': int(time.time() * 1000)}
        out = self.run_page({'lignes': lines, 'attentes': {'actif': True, 'interrupteur': True, 'raison': '', 'attentes': [att]}})
        rows = self.rows(out['tableau'])
        self.assertIn('data-repondre="' + 'f' * 32 + '" data-choix="2"', rows['Q3'])
        self.assertNotIn('data-repondre', rows['Q2'])          # Q2 answers through the wake, by its own number
        self.assertIn('data-question="Q2" data-choix="go" data-copier="Q2 go"', rows['Q2'])
        for r in rows.values():
            self.assertIn('>Ouvrir ↗</button>', r)

    def test_the_recommended_button_answers_and_the_line_closes(self):
        reco = 'recommandé : une passe légère planifiée chaque semaine'
        l = dict(self.line('Q44', [reco, 'pas encore'], 'Run sans ingestion'), type='decision', verbe='Répondre')
        out = self.run_page({'lignes': [l]})
        row = self.rows(out['tableau'].replace('Q44 ·', 'Q2 ·'))['Q2']
        self.assertIn(f'data-question="Q44" data-choix="{reco}" data-copier="Q44 {reco}"', row)
        self.assertIn('>Une passe légère planifiée… (recommandé)</button>', row)
        self.assertIn(f'title="Répondre « Q44 {reco} » à la session : elle le reçoit', row)
        clic = {'data-question': 'Q44', 'data-choix': reco, 'data-copier': f'Q44 {reco}', 'data-ligne': LOCAL + '|Q44'}
        out = self.run_page({'lignes': [l], 'cliquer': [['data-reveil', LOCAL]], 'attributs': clic,
                             'repondre': {'mode': 'directe', 'texte': f'Q44 {reco}'}})
        self.assertIn(['repondre', {'session': LOCAL, 'question': 'Q44', 'choix': reco}], out['appels'])
        self.assertIn('Envoyée, la session reprend', out['tableau'])
        self.assertNotIn('(recommandé)</button>', out['tableau'])

    def test_no_recommendation_no_recommended_button(self):
        out = self.run_page({'lignes': [self.line('Q2', ['go', 'pas encore'], 'Déploiement')]})
        self.assertNotIn('(recommandé)', out['tableau'])

    def test_a_line_without_a_question_keeps_only_the_way_into_the_session(self):
        l = dict(self.line('', None, 'Relire la page'), question='', choix=None, type='review', verbe='Relire',
                 affiche_suite='Relire la page')
        row = list(self.rows(self.run_page({'lignes': [l]})['tableau']).values())[0]
        self.assertNotIn('data-reveil', row)
        self.assertNotIn('data-repondre', row)
        self.assertIn('data-sid="' + LOCAL + '"', row)


if __name__ == '__main__':
    unittest.main()
