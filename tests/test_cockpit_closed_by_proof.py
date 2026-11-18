"""Tests of the questions that close by themselves: python3 -m unittest discover -s tests

The case of 10/11 (anonymised): a session outside any Studio, so without a question register, numbered its own « Q12 »
under « À trancher »: « ouvre une nouvelle session sur le dossier ~/… et colle ce prompt ». The PM opened that session
minutes later, wrote « c bon c fait », and the session listed Q12 again under « Encore ouvert ». The line stayed on the
board. The same day another session outside any Studio showed its own « Q12 ».

1. Proof: a line that asks to open a new session in a folder (a path, or a Studio of projets.json) closes once the app
   shows a session opened there (or inside) after the question; announced « réglé : session ouverte dans <dossier> ».
2. The PM's word: « Q12 c fait », « Q12 fait », « Q12 ok c'est fait », or « c bon c fait » for the single open question,
   closes it, register question or parsed one.
3. Order: the PM's word wins over a listing written before it; a listing written after it reopens the question.
4. Two sessions showing the same number: each keeps its number, and neither names the other (2026-11-17).
Transcripts here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

NOW = time.time()
ASKER, OTHER, NEW = 'local_asker', 'local_other', 'local_new'
TOOL_DIR = os.path.join(str(parc.HOME), 'Documents', 'plugins', 'outil')
ELSEWHERE = os.path.join(str(parc.HOME), 'Documents', 'plugins', 'autre')


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def card(sid, title, cwd, created_minutes_ago=600, task=None):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': task,
            'creee': NOW - created_minutes_ago * 60}


ASK_Q12 = ("Le prompt est prêt.\n\n## À trancher\n- **Q12 · Session dédiée aux conflits :** ouvre une nouvelle session "
           "sur le dossier `~/Documents/plugins/outil` et colle ce prompt :\n\n```\nTraite les conflits.\n```")
STILL_Q12 = ("Noté pour le modèle.\n\n## À trancher\nEncore ouvert :\n- **Q12 · Session dédiée aux conflits :** ouvrir "
             "une nouvelle session sur `~/Documents/plugins/outil` et y coller le prompt de mon message précédent.")
DONE_REPLY = "Noté.\n\nRien à faire de ton côté."


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()
        self.addCleanup(setattr, parc, 'CHANTIERS', saved)

    def session(self, sid, entries, cwd=TOOL_DIR, title=None):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, title or 'Session ' + sid, cwd), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def table(self, sessions, extra_cards=()):
        metas = [card(s['id'], s['titre'], s['cwd']) for s in sessions] + list(extra_cards)
        fermees = []
        lignes = parc.tableau(sessions, metas, [], 7, NOW, {}, fermees)
        return lignes, fermees


class SessionOpenedIsProof(Board):
    REAL = [final(60, ASK_Q12), pm(55, "c bon c fait, mais j'ai pas vu où régler le niveau"), final(54, STILL_Q12)]

    def test_the_real_case_closes_once_the_session_is_open(self):
        lignes, fermees = self.table([self.session(ASKER, self.REAL)], [card(NEW, 'Conflits', TOOL_DIR, 58)])
        self.assertEqual(lignes, [])
        f, = fermees
        self.assertEqual(f['preuve'], 'réglé : session ouverte dans ~/Documents/plugins/outil')
        self.assertEqual(f['ouverte'], NEW)
        self.assertIn('Q12', f['texte'])

    def test_announced_in_the_markdown_board(self):
        _, fermees = self.table([self.session(ASKER, self.REAL)], [card(NEW, 'Conflits', TOOL_DIR, 58)])
        md = parc.rendre_md({'genere': NOW, 'tableau': [], 'anciennes': [], 'sans_action': [{'studio': 'outil',
                             'titre': 'x', 'sessionId': ASKER, 'etat': 'rien', 'derniere': NOW}], 'pastilles_lues': True,
                             'fermees': fermees, 'lecture_app': {'etat': 'ok'}})
        self.assertIn('réglé : session ouverte dans ~/Documents/plugins/outil', md)

    def test_a_session_inside_the_folder_counts(self):
        lignes, _ = self.table([self.session(ASKER, self.REAL)], [card(NEW, 'Conflits', os.path.join(TOOL_DIR, 'sous'), 58)])
        self.assertEqual(lignes, [])

    def test_no_session_opened_keeps_it(self):
        lignes, fermees = self.table([self.session(ASKER, self.REAL)])
        self.assertEqual([l['num'] for l in lignes], [12])   # its last message lists it after the PM's word (rule 3)
        self.assertEqual(fermees, [])

    def test_a_session_opened_before_the_question_is_no_proof(self):
        lignes, _ = self.table([self.session(ASKER, self.REAL)], [card(NEW, 'Ancienne', TOOL_DIR, 120)])
        self.assertEqual([l['num'] for l in lignes], [12])

    def test_another_folder_or_a_scheduled_task_is_no_proof(self):
        lignes, _ = self.table([self.session(ASKER, self.REAL)],
                               [card(NEW, 'Ailleurs', ELSEWHERE, 58), card('local_task', 'Point du matin', TOOL_DIR, 58, task='matin')])
        self.assertEqual([l['num'] for l in lignes], [12])

    def test_a_known_studio_by_its_name(self):
        studio = os.path.join(str(parc.HOME), 'Studios', 'Studio - Alpha')
        ask = "## À trancher\n- **Q3 · Kickoff :** ouvre une nouvelle session sur le Studio Alpha et lance /studio:kickoff."
        with unittest.mock.patch.object(parc, 'dossiers_de_l_instantane', lambda: {studio}):
            lignes, fermees = self.table([self.session(ASKER, [final(30, ask)])], [card(NEW, 'Alpha', studio, 20)])
        self.assertEqual(lignes, [])
        self.assertEqual(fermees[0]['preuve'], 'réglé : session ouverte dans ~/Studios/Studio - Alpha')

    def test_no_folder_named_no_guess(self):
        ask = "## À trancher\n- **Q3 · Suite :** ouvre une nouvelle session et colle ce prompt."
        lignes, _ = self.table([self.session(ASKER, [final(30, ask)])], [card(NEW, 'Nouvelle', TOOL_DIR, 20)])
        self.assertEqual([l['num'] for l in lignes], [3])

    def test_a_register_question_closes_too(self):
        parc.CHANTIERS.joinpath('essai.json').write_text(json.dumps({'chantier': 'Essai', 'sessionId': 'local_foreman', 'attentes': [
            {'type': 'task', 'titre': 'Q7 · Session des conflits', 'depuis': at(60), 'sessionId': ASKER, 'source': ASKER,
             'detail': 'Ouvre une nouvelle session sur ~/Documents/plugins/outil et colle le prompt.'}]}))
        metas = [card('local_foreman', 'Contremaître', TOOL_DIR), card(ASKER, 'Kit', TOOL_DIR), card(NEW, 'Conflits', TOOL_DIR, 30)]
        fermees = []
        with unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True):
            lignes = parc.tableau([], metas, [], 7, NOW, {}, fermees)
        self.assertEqual(lignes, [])
        self.assertEqual((fermees[0]['chantier'], fermees[0]['num']), ('Essai', 7))


class PmWord(unittest.TestCase):
    def faites(self, entries):
        return parc.dites_faites(parc.suivi_session(entries))

    def test_the_forms_of_done(self):
        for text in ('Q12 c fait', 'Q12 fait', "Q12 ok c'est fait", 'Q12 : fait.', "Q12 c fait et tu devrais l'avoir vu"):
            self.assertEqual(parc.faits_dans(text), ([12], False), text)
        self.assertEqual(parc.faits_dans('c bon c fait'), ([], True))
        self.assertEqual(parc.faits_dans('Q11 désinstalle, Q10 c fait'), ([10], False))

    def test_not_done(self):
        for text in ('Au fait, tu peux regarder le Sheet ?', 'Q12 pas encore fait', "c'est fait ?", 'tout à fait',
                     'Q12 fait quoi exactement', 'Q10 c quoi déjà ?', 'Q3 go'):
            self.assertEqual(parc.faits_dans(text), ([], False), text)

    def test_the_word_after_the_listing_closes(self):
        self.assertIn(12, self.faites([final(60, ASK_Q12), pm(50, 'Q12 c fait')]))

    def test_a_listing_after_the_word_reopens(self):
        # Rule 3: the last word wins. The session listed it again after the PM: it still holds it.
        self.assertNotIn(12, self.faites([final(60, ASK_Q12), pm(50, 'Q12 c fait'), final(49, STILL_Q12)]))
        self.assertIn(12, self.faites([final(60, ASK_Q12), pm(50, 'Q12 c fait'), final(49, STILL_Q12), pm(40, 'Q12 fait')]))

    def test_without_a_number_only_the_single_open_question(self):
        self.assertEqual(self.faites([final(60, STILL_Q12), pm(50, 'c bon c fait')]).keys(), {12})
        two = STILL_Q12 + "\n- **Q13 · Autre point :** oui ou non ?"
        self.assertEqual(self.faites([final(60, two), pm(50, 'c bon c fait')]), {})

    def test_a_register_question_leaves_at_once(self):
        # Before, a word without the session at work kept it (None); « Q61 c fait » is proof by itself.
        sv = parc.suivi_session([final(60, ASK_Q12.replace('Q12', 'Q61')), pm(50, 'Q61 c fait')])
        a = {'titre': 'Q61 · Session dédiée aux conflits', 'depuis': at(60)}
        self.assertEqual(parc.reglee_dans_session(a, [], sv), parc.FORTE)
        sv = parc.suivi_session([final(60, ASK_Q12.replace('Q12', 'Q61')), pm(50, 'Q61 tu en es où ?')])
        self.assertIsNone(parc.reglee_dans_session(a, [], sv))


class ReviewCases(unittest.TestCase):
    """Cases of the independent review of 2026-11-10."""
    def test_fait_before_the_number_counts_only_when_it_touches_it(self):
        self.assertEqual(parc.faits_dans('ok c fait mais il reste la Q4'), ([], False))
        self.assertEqual(parc.faits_dans('c fait pour la Q12'), ([12], False))
        self.assertEqual(parc.faits_dans('pas encore fait pour la Q12'), ([], False))

    def test_fait_attention_is_not_done(self):
        for t in ('Fait attention au budget', 'fait gaffe'):
            self.assertEqual(parc.faits_dans(t), ([], False), t)

    def test_a_quoted_path_keeps_its_spaces(self):
        d = parc.dossier_du_geste('Ouvre une nouvelle session dans `~/Mon Studio/chantiers` pour ça')
        self.assertEqual(d, os.path.join(str(parc.HOME), 'Mon Studio', 'chantiers'))

    def test_an_unquoted_path_cut_at_a_space_falls_back_to_the_studio_name(self):
        studio = os.path.join(str(parc.HOME), 'Drive partagés', 'Studio - Alpha')
        with unittest.mock.patch.object(parc, 'nom_projet', lambda d: 'Alpha'):
            d = parc.dossier_du_geste(f'Ouvre une nouvelle session dans {studio} (Alpha)', [studio])
        self.assertEqual(d, studio)

    def test_a_denied_gesture_is_no_request(self):
        self.assertIsNone(parc.dossier_du_geste('Ne lance pas une nouvelle session dans ~/Documents/x'))


class ParsedLineAndPmWord(Board):
    def test_the_reply_that_drops_it_leaves_no_line(self):
        lignes, _ = self.table([self.session(ASKER, [final(60, ASK_Q12), pm(50, 'Q12 c fait'), final(49, DONE_REPLY)])])
        self.assertEqual(lignes, [])

    def test_a_question_said_done_before_its_last_listing_is_dropped(self):
        # The board reads the last message; numbers the PM said done after their last listing are not shown, and a
        # message whose numbered questions are all done leaves no fallback line.
        s = self.session(ASKER, [final(60, STILL_Q12)])
        s['faites'] = [12]
        self.assertEqual(parc.demandes(s), [])


class SameNumberTwoSessions(Board):
    def test_two_q12_say_nothing_of_each_other_and_keep_their_number(self):
        # PM, 2026-11-17: « une autre Q12 vient de… » on 67 lines out of 100 was noise; each line keeps its own number.
        go = "Prêt.\n\n**À trancher**\n\nQ12 · Publier la version : je publie, go ?"
        a = self.session(ASKER, [final(30, go)], cwd=TOOL_DIR, title='Corrections avant publication')
        b = self.session(OTHER, [final(20, go.replace('Publier la version : je publie', 'Relancer : je relance'))], cwd=ELSEWHERE,
                         title='Skill ingestion')
        lignes, _ = self.table([a, b])
        for l in lignes:   # the answer buttons still send « Q12 <choice> » to its own session
            self.assertEqual(l['question'], 'Q12')
            self.assertTrue(l['choix'])
            self.assertNotIn('homonyme', l)
            self.assertNotIn('une autre Q12', parc.rang_md(l, '', NOW))


class RuleLine(unittest.TestCase):
    def test_format_rule_says_a_done_item_is_no_longer_listed(self):
        text = (ROOT / 'regles' / 'format-reponses.md').read_text(encoding='utf-8')
        self.assertIn('dit faite', text)
        self.assertIn('session ouverte', text)


if __name__ == '__main__':
    unittest.main()
