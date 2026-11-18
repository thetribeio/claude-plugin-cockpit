"""Tests of the « réglée dans la session » rule of skills/cockpit/scripts/parc.py: python3 -m unittest discover -s tests

A numbered question of a foreman's board is settled in its session once its source session asked it, the PM wrote to
that session afterwards, and the session started working on its reply; it comes back if that reply asks it again.
Since Q130 (2026-10-20), it leaves Mon Studio only on strong proof (FORTE: the PM cited its number, or answered the
menu that carried it), or once the session answered the PM without carrying it over (SANS_REPORT, PM, Q24 of
2026-11-04); while the session still works on its reply, it stays (A_CONFIRMER). Transcripts here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

DAY = '2026-10-13T'


def at(hhmm):
    return DAY + hhmm + ':00+02:00'


def pm(hhmm, text, origin='human'):
    return {'type': 'user', 'timestamp': at(hhmm), 'origin': {'kind': origin}, 'message': {'content': text}}


def final(hhmm, text, mid=None):
    return {'type': 'assistant', 'timestamp': at(hhmm),
            'message': {'id': mid or 'm' + hhmm, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def tool(hhmm):
    return [{'type': 'assistant', 'timestamp': at(hhmm),
             'message': {'id': 't' + hhmm, 'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'b' + hhmm, 'name': 'Bash', 'input': {}}]}},
            {'type': 'user', 'timestamp': at(hhmm), 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'b' + hhmm, 'content': 'ok'}]}}]


def menu(hhmm, question, options=('Oui (Recommandé)', 'Non')):
    entry = {'questions': [{'question': question, 'options': [{'label': o, 'description': ''} for o in options]}]}
    return {'type': 'assistant', 'timestamp': at(hhmm),
            'message': {'id': 'q' + hhmm, 'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'u' + hhmm, 'name': 'AskUserQuestion', 'input': entry}]}}


def menu_answer(menu_hhmm, hhmm, text='Oui'):
    return {'type': 'user', 'timestamp': at(hhmm),
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u' + menu_hhmm, 'content': 'The user answered: ' + text}]}}


ASK_61 = "La colonne est prête.\n\n## À trancher\n- **Q61 · Photos :** Drive seul, ou Drive et Slack ? Je recommande Drive et Slack."
ASK_61_62 = ("Deux points.\n\n## À trancher\n- **Q61 · Photos :** Drive seul, ou Drive et Slack ?\n"
             "- **Q62 · Niveaux :** relire la grille chaque mois, ou laisser tels quels ?")


def settled(entries, title='Q61 · Photos', created='10:00', others=()):
    sv = parc.suivi_session(entries)
    return parc.reglee_dans_session({'titre': title, 'depuis': at(created)},
                                    [{'titre': t, 'depuis': at(c)} for t, c in others], sv)


class SettledInSession(unittest.TestCase):
    def test_answer_without_the_number_and_a_reply_that_drops_it_leaves(self):
        # Q24 du 2026-11-04 (cas Q40 et Q43 du 02/11) : la session a répondu sans la reporter.
        entries = [final('10:01', ASK_61), pm('10:05', 'Drive, et Slack pour ceux qui manquent'), *tool('10:06'),
                   final('10:20', 'Les photos sont en place : 56 fiches sur 60.')]
        self.assertEqual(settled(entries), parc.SANS_REPORT)
        self.assertIn(parc.SANS_REPORT, parc.QUITTE)

    def test_still_working_without_the_number_stays(self):
        entries = [final('10:01', ASK_61), pm('10:05', 'Drive, et Slack pour ceux qui manquent'), *tool('10:06')]
        self.assertEqual(settled(entries), parc.A_CONFIRMER)
        self.assertNotIn(parc.A_CONFIRMER, parc.QUITTE)

    def test_leaves_as_soon_as_the_session_works_on_the_reply(self):
        entries = [final('10:01', ASK_61), pm('10:05', 'Q61 : Drive et Slack'), *tool('10:06'), *tool('10:09')]
        self.assertEqual(settled(entries), parc.FORTE)

    def test_not_picked_up_yet_keeps_it(self):
        entries = [final('10:01', ASK_61), pm('10:05', 'Q61 : Drive et Slack')]
        self.assertIsNone(settled(entries))

    def test_comes_back_when_the_reply_asks_it_again(self):
        entries = [final('10:01', ASK_61), pm('10:05', "Q61 : c'était quoi le dossier déjà ?"), *tool('10:06')]
        self.assertEqual(settled(entries), parc.FORTE)
        entries.append(final('10:07', "C'est le dossier des photos de l'équipe.\n\nEncore ouvert : Q61"))
        self.assertIsNone(settled(entries))

    def test_asked_again_keeps_it(self):
        entries = [final('10:01', ASK_61), pm('10:05', "Q61 : c'était quoi le dossier déjà ?"),
                   final('10:07', "C'est le dossier des photos de l'équipe.\n\nEncore ouvert : Q61")]
        self.assertIsNone(settled(entries))

    def test_no_word_from_the_pm_keeps_it(self):
        entries = [pm('09:50', 'Où en est-on ?'), final('10:01', ASK_61)]
        self.assertIsNone(settled(entries))

    def test_only_the_answered_question_leaves(self):
        entries = [final('10:01', ASK_61_62), pm('10:05', 'Drive et Slack. Pour les niveaux je ne sais pas encore'),
                   final('10:12', "C'est fait pour les photos.\n\nEncore ouvert : Q62")]
        self.assertEqual(settled(entries), parc.SANS_REPORT)
        self.assertIsNone(settled(entries, title='Q62 · Niveaux'))

    def test_unnumbered_menu_in_the_reply_waits(self):
        # The PM asks back, the session asks again through a menu without a number: maybe the same question.
        entries = [final('10:01', ASK_61), pm('10:05', 'Q61 : pourquoi pas Slack seul ?'),
                   menu('10:06', 'Pour les photos, on fait comment ?', ('Drive et Slack (Recommandé)', 'Drive seul'))]
        self.assertIsNone(settled(entries))
        entries += [menu_answer('10:06', '10:30', 'Drive et Slack'), *tool('10:31'), final('10:40', 'Photos posées.')]
        self.assertEqual(settled(entries), parc.FORTE)  # the PM's question back cited Q61

    def test_menu_dated_with_another_question_settles(self):
        # The reply is a menu the foreman already holds as another question (dated at the menu): not this one.
        entries = [final('10:01', ASK_61), pm('10:05', 'Drive et Slack'), menu('10:20', 'Je lance la fusion ?')]
        self.assertEqual(settled(entries, others=[('Q49 · Fusion', '10:20')]), parc.SANS_REPORT)
        self.assertIsNone(settled(entries))

    def test_question_asked_by_a_menu_dated_with_it(self):
        entries = [menu('23:00', 'Je lance la fusion ?'), menu_answer('23:00', '23:10', 'Go, tout'), *tool('23:11'),
                   final('23:40', 'La fusion est faite : 251 fiches.')]
        self.assertEqual(settled(entries, title='Q49 · Fusion', created='23:00'), parc.FORTE)  # the menu carried it

    def test_mere_mention_is_not_asking(self):
        # A session that only reminds the PM of a foreman's question did not ask it: he answers elsewhere.
        entries = [final('10:01', "Ce n'est pas encore fait. Une fois fait, dis-le au contremaître pour qu'il ferme Q44."),
                   pm('10:05', 'Je peux archiver cette session ?'), final('10:06', 'Archive-la.')]
        self.assertIsNone(settled(entries, title='Q44 · Raccourci clavier', created='09:00'))

    def test_asked_again_later_comes_back(self):
        entries = [final('10:01', ASK_61), pm('10:05', 'Drive et Slack'), final('10:20', 'Photos posées.')]
        self.assertEqual(settled(entries), parc.SANS_REPORT)
        entries += [pm('11:00', 'Et pour les externes ?'), final('11:02', ASK_61)]
        self.assertIsNone(settled(entries))

    def test_interruption_is_not_an_answer(self):
        entries = [final('10:01', ASK_61), pm('10:05', '[Request interrupted by user]'),
                   pm('10:06', 'Un message de la session du contremaître', origin='peer'), final('10:07', 'Bien reçu.')]
        self.assertIsNone(settled(entries))

    def test_last_carry_over_is_the_latest_reply_that_holds_it(self):
        entries = [final('10:01', ASK_61), pm('10:05', 'Je regarde demain'),
                   final('10:07', "D'accord.\n\nEncore ouvert : Q61 · Photos"), pm('10:30', 'Autre chose : le logo ?'),
                   final('10:32', "Le logo est posé.\n\nEncore ouvert : Q61 · Photos")]
        sv = parc.suivi_session(entries)
        self.assertEqual(parc.reprise_dans_session({'titre': 'Q61 · Photos', 'depuis': at('10:00')}, sv),
                         parc.ts_iso(at('10:32')))
        self.assertIsNone(parc.reprise_dans_session({'titre': 'Q62 · Niveaux', 'depuis': at('10:00')}, sv))

    def test_question_held_under_what_awaits_you(self):
        text = "## Ce qui t'attend ici\n\n**Q38 · Relier l'équipe des projets.** Je te propose deux options."
        self.assertIn(38, parc.ouvertes_dans(text)[0])


if __name__ == '__main__':
    unittest.main()
