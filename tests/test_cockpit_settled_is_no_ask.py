"""Tests: a settled question is never an ask, in Mon Studio: python3 -m unittest discover -s tests

The PM, 2026-10-22, 17:09: a « Go » line with no object, « (Kit COPIL : feu vert aux écritures du kit dans le Studio
A) est soldée au tableau. », in the foreman's session. The foreman was saying that Mon Studio was up to date; the
sentence came out as a go because of « feu vert ». So:

  - a sentence that announces a closed question (« soldée », « sans objet », « déjà fait », « est … au tableau ») is
    never an ask, whatever words it contains; a closed word that is not about a question stays what it was;
  - in a chantier session, a « Qn » the message recalls that no open line of the chantier's mirror holds makes no line:
    its question is settled. A number open on the board under another question (taken again) keeps the date rule.

Transcripts, cards and mirrors here are synthetic; the message is the real one, with its names changed."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

REAL_MESSAGE = """**Garde-fous de phase**
- Page de cadrage absente ou pas validée. Geste : /audit-cadrage.
- Lean UX Canvas vide. Geste : à remplir avec Claude dans le Studio.

Q144 (Kit COPIL : feu vert aux écritures du kit dans le Studio A) est soldée au tableau. C'était sans objet, selon tes mots du 22/10 : « Q144 efface c'est déjà en cours dans le projet A ». L'init se rejoue dans une session du projet A, et la session « COPIL · init » n'avait rien écrit. Mon Studio est à jour : Q150 · Kits ou plugin y restait affichée alors qu'elle était déjà soldée au tableau depuis le 21/10.

Il reste 7 lignes ouvertes pour toi au [tableau](https://claude.ai/artifact/AbCdEf)."""


def asks(text):
    """The sentences of a message that make a line of Mon Studio (priority 1 or 2: asks)."""
    _, _, notes, _ = parc.trier(text, expliquer=True)
    return [n['p'] for n in notes if n['prio'] in (1, 2)]


class SentenceSorting(unittest.TestCase):
    def test_the_real_message_makes_no_ask(self):
        self.assertEqual(asks(REAL_MESSAGE), [])

    def test_a_settled_sentence_with_a_green_light_is_no_ask(self):
        for phrase in ('Q12 (feu vert pour le déploiement) est soldée au tableau.',
                       'Q12 : le go est sans objet, ligne fermée.',
                       'La question Q7 (relire la propale) est réglée, rien à relire.',
                       'Q9 · Choix du format est déjà au tableau.',
                       'Le feu vert de Q3 était déjà fait.'):
            self.assertEqual(asks(phrase), [], phrase)

    def test_a_real_go_stays_an_ask(self):
        for phrase in ('Q12 : j\'attends ton feu vert pour déployer.',
                       'Donne-moi ton go pour le déploiement.',
                       'Ces mois sont clos, à arbitrer.',
                       'Q12 est soldée, mais dis-moi si tu valides le déploiement.',
                       'Le feu vert au déploiement est-il soldé ?'):
            self.assertEqual(len(asks(phrase)), 1, phrase)


# ---------- chantier session: a recalled number no open line holds makes no line

NOW = time.time()
FOREMAN, KIT, OTHER = 'local_foreman', 'local_kit', 'local_other'


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def card(sid, title):
    return {'id': sid, 'archivee': False, 'cwd': '/studios/Studio-Essai', 'titre': title, 'parent': None, 'tache': None}


CARDS = [card(FOREMAN, 'Contremaître'), card(KIT, 'ᐅ Kit A · tâche'), card(OTHER, 'ᐅ Kit B · photos')]
ASK = "Le kit est prêt.\n\n## À trancher\n- **Q5 · Photos :** Drive seul, ou Drive et Slack ?"
RECALL = "Les fiches sont à jour.\n\nEncore ouvert : Q5 · Photos, Drive seul ou Drive et Slack."
PHRASE = "Les fiches sont à jour.\n\nJ'attends ta réponse à Q5 pour les photos."
GO = "Les fiches sont à jour.\n\nJ'attends ton go pour lancer le kit."
ROW = 'Photos : Drive seul, ou Drive et Slack ?'


class RecalledNumber(unittest.TestCase):
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

    def session(self, entries):
        path = pathlib.Path(self.tmp.name) / f'{KIT}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(CARDS[1], chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def rows(self, final_text, board, counter=9):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(1), 'attentes': board}))
        (parc.CHANTIERS / 'essai.numero').write_text(str(counter))
        kit = self.session([pm(40, 'vas-y'), final(30, ASK), pm(20, 'je regarde'), final(10, final_text)])
        out = parc.lignes_et_anciennes([kit], CARDS, [], 7, NOW, {})[0]
        return [(l.get('cle'), l.get('complet')) for l in out]

    def other_line(self, n=6):
        return {'type': 'decision', 'titre': f'Q{n} · Budget : on garde la ligne ?', 'source': OTHER,
                'sessionId': OTHER, 'depuis': at(60), 'ou': 'Kit B', 'doc': f'n20261022-{n}'}

    def test_a_settled_number_cited_in_a_recall_makes_no_line(self):
        for text in (RECALL, PHRASE):
            rows = self.rows(text, [self.other_line()])
            self.assertNotIn((KIT, ROW), rows, text)
            self.assertNotIn((KIT, 'Q5 · Photos : Drive seul, ou Drive et Slack ?'), rows, text)
            self.assertEqual([r for r in rows if r[0] == KIT], [], text)

    def test_the_open_number_cited_stays_visible_on_the_board(self):
        line = dict(self.other_line(5), source=KIT, sessionId=KIT, titre='Q5 · Photos : Drive seul, ou Drive et Slack ?')
        rows = self.rows(RECALL, [line])
        self.assertEqual([r for r in rows if r[0] == KIT], [])          # the session line gives way
        self.assertIn((FOREMAN, 'Q5 · Photos : Drive seul, ou Drive et Slack ?'), rows)   # the board line stays

    def test_a_number_taken_again_by_another_question_keeps_the_date_rule(self):
        rows = self.rows(RECALL, [self.other_line(5)])
        self.assertTrue([r for r in rows if r[0] == KIT])                 # asked before the board's Q5 existed
        self.assertIn((FOREMAN, 'Q5 · Budget : on garde la ligne ?'), rows)

    def test_a_question_the_session_asks_now_stays(self):
        kit = self.session([pm(20, 'vas-y'), final(10, ASK)])
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(1), 'attentes': [self.other_line()]}))
        (parc.CHANTIERS / 'essai.numero').write_text('9')
        out = parc.lignes_et_anciennes([kit], CARDS, [], 7, NOW, {})[0]
        self.assertIn((KIT, ROW), [(l.get('cle'), l.get('complet')) for l in out])

    def test_a_real_go_of_a_chantier_session_stays(self):
        rows = self.rows(GO, [self.other_line()])
        self.assertTrue([r for r in rows if r[0] == KIT and 'go' in (r[1] or '')])

    def test_without_a_chantier_the_numbers_are_the_sessions_own(self):
        kit = self.session([pm(40, 'vas-y'), final(30, ASK), pm(20, 'je regarde'), final(10, RECALL)])
        out = parc.lignes_et_anciennes([kit], CARDS, [], 7, NOW, {})[0]
        self.assertIn((KIT, 'Q5 · ' + ROW), [(l.get('cle'), l.get('complet')) for l in out])


if __name__ == '__main__':
    unittest.main()
