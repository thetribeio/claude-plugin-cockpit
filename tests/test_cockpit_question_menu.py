"""Tests of a recalled question asked in a box, or far up the transcript: python3 -m unittest discover -s tests

A question that a session recalls (« Encore ouvert : Q12 », the number alone) may have been asked in a menu
(AskUserQuestion) or in the app's end-of-turn card, not in Claude's text: its line takes the question as title and
its options, and its detail is the one of a waiting menu (the whole question, each option with its description, the
recommended one marked). A number missing from the end of the transcript already read is searched in the whole
transcript, for that number only. Only a question that exists nowhere, neither in a paragraph nor in a box, falls back
to « Une question t'attend dans cette session », and its detail then gives the last paragraphs of the session's last
message, announced as such. The real case (a session of the PM, 2026-10-15) is replayed anonymised; the other
transcripts are synthetic."""
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
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, ALONE = 'local_foreman', 'local_kit', 'local_alone'
STUDIO_CWD, OTHER_CWD = '/studios/Studio-Essai', '/studios/Studio-Autre'
NOW = time.time()


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def final(hours_ago, text, mid):
    return {'type': 'assistant', 'timestamp': at(hours_ago),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(hours_ago, text):
    return {'type': 'user', 'timestamp': at(hours_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


DISMISSED = "The user doesn't want to proceed with this tool use. The tool use was rejected."
SHOWN = 'Shown in the next-step box. The box ends your turn: write no text after this call.'


def box(hours_ago, mid, question, options, tool='AskUserQuestion', result=None):
    """A menu (AskUserQuestion) with one question, options as (label, description), dismissed by the PM; or the
    app's end-of-turn card (a question, ready-made replies as (label, message sent)), shown at once."""
    if tool == 'AskUserQuestion':
        entry = {'questions': [{'question': question, 'header': 'Q', 'multiSelect': False,
                                'options': [{'label': l, 'description': d} for l, d in options]}]}
    else:
        entry = {'recap': 'Le brouillon est prêt.', 'ask': question, 'blocked': True,
                 'actions': [{'label': l, 'message': d} for l, d in options]}
    return [{'type': 'assistant', 'timestamp': at(hours_ago),
             'message': {'id': mid, 'stop_reason': 'tool_use',
                         'content': [{'type': 'tool_use', 'id': 'u' + mid, 'name': tool, 'input': entry}]}},
            {'type': 'user', 'timestamp': at(hours_ago - 0.01),
             'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u' + mid,
                                      'content': result or (DISMISSED if tool == 'AskUserQuestion' else SHOWN)}]}}]


def peer(hours_ago, text):
    """A message from another session (the foreman): not a word from the PM."""
    return {'type': 'user', 'timestamp': at(hours_ago), 'origin': {'kind': 'peer'},
            'message': {'content': 'Another Claude session sent a message: ' + text}}


def filler(hours_ago, i, size=600):
    """A plain exchange that names no question: what pushes a question out of the window read first."""
    return [pm(hours_ago, f'Étape {i} ?'), final(hours_ago - 0.001, f'Étape {i} faite. ' + 'x' * size, f'f{i}')]


# The real case (a session of the PM, 15/10), anonymised: Q12 is asked in a menu, the PM answers in the session, and
# the session's next messages recall it by its number alone. The line used to read « Q12 · Une question t'attend dans
# cette session », with the same words in its detail.
Q12 = "Q12 · Je protège la branche principale du dépôt avant de l'ouvrir à deux collègues ?"
Q12_OPTIONS = [('Règle complète (Recommended)', "PR obligatoire, contrôle vert, relecture du propriétaire ; tu peux "
                "passer outre. Il te faudra saisir ton code GitHub."),
               ('PR et contrôle seulement', 'Pas de poussée directe, pas de fusion en rouge, pas de relecture obligatoire.'),
               ("Rien pour l'instant", "Comme aujourd'hui, tant que tu es seul à écrire.")]
Q12_SUITE = "Règle complète (recommandé) · PR et contrôle seulement · Rien pour l'instant"
Q12_DETAIL = (Q12 + " Règle complète (recommandé) : PR obligatoire, contrôle vert, relecture du propriétaire ; tu peux "
              "passer outre. Il te faudra saisir ton code GitHub. PR et contrôle seulement : Pas de poussée directe, pas "
              "de fusion en rouge, pas de relecture obligatoire. Rien pour l'instant : Comme aujourd'hui, tant que tu es "
              "seul à écrire.")
REAL_CASE = ([final(5, "La règle est posée dans le guide du dépôt.", 'm0')] + box(4, 'm1', Q12, Q12_OPTIONS)
             + [pm(3.9, "Avant de choisir : qui a les droits d'administration ?"),
                final(3.8, "Toi seul, comme propriétaire du dépôt.\n\nEncore ouvert : Q12", 'm2')])


def card(sid, title, cwd=STUDIO_CWD):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


class Transcripts(unittest.TestCase):
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

    def write(self, sid, entries):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        return str(path)

    def session(self, sid, entries, cwd=OTHER_CWD):
        """A session as construire() builds it, from a transcript written on disk."""
        path = self.write(sid, entries)
        r = parc._analyser(path, NOW)
        s = dict(card(sid, 'Session ' + sid, cwd), chemin=path, derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def recalled(self, entries, cwd=OTHER_CWD):
        return parc.demandes(self.session(ALONE, entries, cwd))

    def table(self, sessions):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(30), 'attentes': []}))
        metas = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A'), card(ALONE, 'Seule', OTHER_CWD)]
        lignes = parc.tableau(sessions, metas, [], 7, NOW, {})
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lignes, 'fils_rouges': [], 'sans_action': []}
        return parc.pour_la_page(e)['lignes'], e


class MenuQuestion(Transcripts):
    def test_the_real_case_gives_the_question_its_options_and_the_recommended_one(self):
        d, = self.recalled(REAL_CASE)
        self.assertEqual((d['num'], d['titre'], d['suite'], d['detail']), (12, Q12, Q12_SUITE, Q12_DETAIL))
        self.assertEqual(d['depuis'], parc.ts_iso(at(4)))  # since the menu
        self.assertNotIn(parc.QUESTION_SANS_TEXTE, d['titre'] + d['detail'])

    def test_on_the_page_the_line_and_its_detail(self):
        l, = self.table([self.session(ALONE, REAL_CASE)])[0]
        self.assertEqual(l['affiche_titre'], Q12)
        self.assertEqual(l['affiche_suite'], '')   # a title that asks shows alone (0.3.2); its options unfold
        self.assertEqual(l['detail'], Q12_DETAIL)
        self.assertEqual(l['verbe'], 'Répondre')

    def test_in_a_foreman_studio_title_and_detail_lose_the_number(self):
        l, = self.table([self.session(KIT, REAL_CASE, STUDIO_CWD)])[0]
        self.assertEqual(l['affiche_titre'], Q12[len('Q12 · '):])
        self.assertEqual(l['detail'], Q12_DETAIL[len('Q12 · '):])
        self.assertEqual(l['a_numeroter'], FOREMAN)

    def test_colon_form_and_french_mark(self):
        entries = box(3, 'm', 'Q7 : Je publie la page maintenant ?', [('Oui (Recommandé)', ''), ('Non', 'Plus tard.')])
        d, = self.recalled(entries + [final(1, 'Encore ouvert : Q7.', 'f')])
        self.assertEqual((d['titre'], d['suite']), ('Q7 · Je publie la page maintenant ?', 'Oui (recommandé) · Non'))
        self.assertEqual(d['detail'], 'Q7 : Je publie la page maintenant ? Oui (recommandé). Non : Plus tard.')

    def test_the_end_of_turn_card_counts_as_a_box(self):
        entries = box(3, 'm', 'Q9 · Feu vert pour écrire le plan dans le Studio pilote ?',
                      [('Feu vert', 'Q9 : a. Lance la suite.'), ('Retravailler', 'Q9 : b. Voici ce qui ne va pas : ')],
                      tool=parc.FIN_DE_TOUR)
        d, = self.recalled(entries + [final(1, 'Encore ouvert : Q9.', 'f')])
        self.assertEqual((d['titre'], d['suite']), ('Q9 · Feu vert pour écrire le plan dans le Studio pilote ?',
                                                    'Feu vert · Retravailler'))

    def test_the_most_recent_wins_paragraph_or_box(self):
        menu_then_text = box(5, 'a', Q12, Q12_OPTIONS) + [
            final(3, '**Q12 · Protection de la branche** : toujours ta décision, la règle complète reste recommandée.', 'b'),
            final(1, 'Encore ouvert : Q12', 'c')]
        d, = self.recalled(menu_then_text)
        self.assertEqual((d['titre'], d['suite']), ('Q12 · Protection de la branche',
                                                    'toujours ta décision, la règle complète reste recommandée.'))
        self.assertNotIn('detail', d)  # the paragraph's own text, as for any paragraph
        text_then_menu = [final(5, 'Q12 · Protection de la branche : à voir.', 'a')] + box(3, 'b', Q12, Q12_OPTIONS) + [
            final(1, 'Encore ouvert : Q12', 'c')]
        d, = self.recalled(text_then_menu)
        self.assertEqual((d['titre'], d['detail']), (Q12, Q12_DETAIL))
        self.assertEqual(d['depuis'], parc.ts_iso(at(5)))  # since it was first asked

    def test_an_unnumbered_menu_a_sidechain_or_another_tool_is_not_a_question(self):
        unnumbered = box(4, 'a', 'Je protège la branche ?', Q12_OPTIONS)
        sidechain = box(3, 'b', Q12, Q12_OPTIONS)
        for e in sidechain:
            e['isSidechain'] = True
        command = [{'type': 'assistant', 'timestamp': at(2), 'message': {'id': 'c', 'stop_reason': 'tool_use', 'content': [
            {'type': 'tool_use', 'id': 'uc', 'name': 'Bash', 'input': {'command': f'echo "{Q12}"'}}]}}]
        d, = self.recalled(unnumbered + sidechain + command + [final(1, 'Encore ouvert : Q12', 'f')])
        self.assertEqual(d['titre'], 'Q12 · ' + parc.QUESTION_SANS_TEXTE)


class WholeTranscript(Transcripts):
    """The end of the transcript read first is shrunk to 4 Ko: a question asked before it is out of the window."""
    def setUp(self):
        super().setUp()
        self.window = mock.patch.object(parc, 'FIN_INITIALE', 4096)
        self.window.start()

    def tearDown(self):
        self.window.stop()
        super().tearDown()

    def long_session(self, early, late, recall):
        entries = list(early)
        for i in range(40):
            entries += filler(20 - i * 0.1, i)
        entries += list(late) + [final(0.5, 'Le reste est fait.\n\nEncore ouvert : ' + recall, 'last')]
        return entries

    def test_a_question_out_of_the_window_is_found_in_the_whole_transcript(self):
        early = [final(30, '## À trancher\n\n**Q3 · Format du CR** : court ou long ? Je recommande court.', 'q3')]
        early += box(29, 'q4', 'Q4 · Je publie la page ?', [('Oui (Recommandé)', 'Elle part aujourd\'hui.'), ('Non', '')])
        entries = self.long_session(early, [], 'Q3, Q4')
        window, everything = parc.entrees_fin(self.write(ALONE, entries), parc.FIN_INITIALE)
        self.assertFalse(everything)
        self.assertEqual(parc.historique_questions(window), {})
        q3, q4 = self.recalled(entries)
        self.assertEqual((q3['titre'], q3['suite']), ('Q3 · Format du CR', 'court ou long ? Je recommande court.'))
        self.assertEqual((q4['titre'], q4['detail']), ('Q4 · Je publie la page ?',
                                                       "Q4 · Je publie la page ? Oui (recommandé) : Elle part aujourd'hui. Non."))
        self.assertEqual(q3['depuis'], parc.ts_iso(at(30)))

    def test_only_the_missing_numbers_are_searched(self):
        early = [final(30, 'Q5 · Ancien titre : première version.\n\nQ6 · Date du COPIL : jeudi ou vendredi ?', 'old')]
        late = [final(1, 'Q5 · Nouveau titre : version reprise.', 'new')]
        calls = []
        real = parc.questions_anciennes
        with mock.patch.object(parc, 'questions_anciennes', lambda chemin, nums: calls.append(list(nums)) or real(chemin, nums)):
            q5, q6 = self.recalled(self.long_session(early, late, 'Q5, Q6'))
        self.assertEqual(calls, [[6]])
        self.assertEqual(q5['titre'], 'Q5 · Nouveau titre')  # the window's, the most recent
        self.assertEqual(q6['titre'], 'Q6 · Date du COPIL')

    def test_a_short_transcript_is_not_read_twice(self):
        with mock.patch.object(parc, 'questions_anciennes', side_effect=AssertionError('read twice')):
            d, = self.recalled([final(1, 'Fait.\n\nEncore ouvert : Q8.', 'f')])
        self.assertEqual(d['titre'], 'Q8 · ' + parc.QUESTION_SANS_TEXTE)


LAST_MESSAGE = """Le correctif est en ligne.

```
sortie du test
```

## Où on en est

La page se relit seule. Le tableau du chantier a repris les deux lignes.

Il reste la vérification de demain matin, que je ferai.

Encore ouvert : Q8

Rien d'autre à faire de ton côté."""


class Fallback(Transcripts):
    def test_nowhere_in_the_transcript_the_detail_gives_the_last_paragraphs(self):
        entries = [final(3, 'Pour la question au référent (Q8), rien de neuf.', 'a'), final(1, LAST_MESSAGE, 'b')]
        d, = self.recalled(entries)
        self.assertEqual(d['titre'], 'Q8 · ' + parc.QUESTION_SANS_TEXTE)
        self.assertEqual(d['detail'], "Question introuvable dans la session ; son dernier message disait : « La page se "
                                      "relit seule. Le tableau du chantier a repris les deux lignes. Il reste la "
                                      "vérification de demain matin, que je ferai. »")
        l, = self.table([self.session(ALONE, entries)])[0]
        self.assertEqual(l['detail'], d['detail'])

    def test_a_message_that_only_recalls(self):
        d, = self.recalled([final(1, 'Encore ouvert : Q8.', 'f')])
        self.assertEqual(d['detail'], "Question introuvable dans la session, et son dernier message n'en dit pas plus.")

    def test_the_paragraphs_after_the_recall_when_nothing_comes_before(self):
        d, = self.recalled([final(1, 'Encore ouvert : Q8.\n\nJe relance les essais cette nuit.', 'f')])
        self.assertEqual(d['detail'], 'Question introuvable dans la session ; son dernier message disait : '
                                      '« Je relance les essais cette nuit. »')

    def test_a_parenthesis_or_a_title_in_the_recall_still_titles_the_line(self):
        d7, d8 = self.recalled([final(1, "C'est en ligne.\n\nEncore ouvert : Q7 (le nom du dossier partagé), "
                                         "Q8 · Ajouter le piège à la règle d'écriture.", 'f')])
        self.assertEqual(d7['titre'], 'Q7 · Le nom du dossier partagé')
        self.assertEqual(d8['titre'], "Q8 · Ajouter le piège à la règle d'écriture")
        for d in (d7, d8):
            self.assertEqual(d['detail'], "Question introuvable dans la session ; son dernier message disait : "
                                          "« C'est en ligne. »")

    def test_never_an_empty_detail(self):
        texts = ['Encore ouvert : Q8', '```\ncode\n```\n\nEncore ouvert : Q8', '## Titre\n\nEncore ouvert : Q8, Q9']
        for t in texts:
            for d in self.recalled([final(1, t, 'f')]):
                self.assertTrue(d['detail'].startswith('Question introuvable dans la session'))


# The second real case (a session of a Studio with a foreman, 15/10), anonymised: the session asks its question in
# the app's end-of-turn card. Mon Studio no longer makes a line from a recall without a number (« Encore ouvert :
# l'étape 3, en attente de ta réponse dans l'encadré. »): the card's own line stays.
STEP3 = "Je lance l'étape 3 (la commande en forme de skill) ?"
STEP3_ACTIONS = [('Oui, étape 3', "Lance l'étape 3 : la commande en forme de skill, en PR sur le dépôt."),
                 ('Pas maintenant', "Pas maintenant, je relis le plan d'abord.")]
STEP3_DETAIL = (STEP3 + " Oui, étape 3 : Lance l'étape 3 : la commande en forme de skill, en PR sur le dépôt. "
                "Pas maintenant : Pas maintenant, je relis le plan d'abord.")


class UnnumberedRecall(Transcripts):
    def test_a_numbered_recall_keeps_its_number(self):
        entries = box(3, 'c', 'Q5 · ' + STEP3, STEP3_ACTIONS, parc.FIN_DE_TOUR) + [final(2, 'Encore ouvert : Q5.', 'r')]
        s = self.session(ALONE, entries)
        self.assertNotIn('encadre', s)
        d, = parc.demandes(s)
        self.assertEqual((d['num'], d['titre']), (5, 'Q5 · ' + STEP3))


class EndOfTurnCard(Transcripts):
    def test_a_session_that_ends_on_its_card_waits_like_on_a_menu(self):
        s = self.session(ALONE, [final(5, 'Le plan est écrit.', 'a')] + box(0.001, 'c', STEP3, STEP3_ACTIONS, parc.FIN_DE_TOUR))
        self.assertEqual((s['etat'], s['outil'], s['depuis']), ('suspens', parc.FIN_DE_TOUR, parc.ts_iso(at(0.001))))
        l, = self.table([s])[0]
        self.assertEqual((l['affiche_titre'], l['affiche_suite'], l['detail'], l['verbe'], l['bloque']),
                         (STEP3, 'Oui, étape 3 · Pas maintenant', STEP3_DETAIL, 'Go', True))

    def test_a_card_without_question_changes_nothing(self):
        recap = [{'type': 'assistant', 'timestamp': at(0.001), 'message': {'id': 'c', 'stop_reason': 'tool_use', 'content': [
                     {'type': 'tool_use', 'id': 'uc', 'name': parc.FIN_DE_TOUR, 'input': {'recap': 'Fait.'}}]}},
                 {'type': 'user', 'timestamp': at(0.0005), 'message': {'content': [
                     {'type': 'tool_result', 'tool_use_id': 'uc', 'content': 'Nothing is pending, so the app draws no box.'}]}}]
        s = self.session(ALONE, [final(5, 'Le plan est écrit.', 'a')] + recap)
        self.assertEqual(s['etat'], 'travaille')
        self.assertNotIn('menu', s)


class RawLines(unittest.TestCase):
    """lignes-brutes.py, run as the foreman runs it, on a fake home: a recalled menu question gives its text."""
    def test_lignes_brutes_reads_the_menu(self):
        with tempfile.TemporaryDirectory() as home:
            home = pathlib.Path(home)
            cards = home / 'Library/Application Support/Claude/claude-code-sessions/compte/org'
            cards.mkdir(parents=True)
            (cards / f'{KIT}.json').write_text(json.dumps({
                'sessionId': KIT, 'cliSessionId': 'cli-' + KIT, 'cwd': STUDIO_CWD, 'title': 'Kit A',
                'lastActivityAt': int(NOW * 1000), 'createdAt': int((NOW - 86400) * 1000)}))
            projects = home / '.claude/projects/essai'
            projects.mkdir(parents=True)
            (projects / f'cli-{KIT}.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in REAL_CASE))
            outils = home / 'Mon Studio/.parc'
            outils.mkdir(parents=True)
            shutil.copy(SCRIPTS / 'parc.py', outils / 'parc.py')
            # a macOS layout on any OS: the child process is told where the app keeps its cards
            env = dict(os.environ, HOME=str(home), MON_STUDIO_APP_SESSIONS=str(cards.parent.parent))
            out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'lignes-brutes.py'), 'Essai'],
                                 check=True, capture_output=True, text=True, env=env).stdout
            self.assertIn(Q12 + ' : ' + Q12_SUITE, out)


if __name__ == '__main__':
    unittest.main()
