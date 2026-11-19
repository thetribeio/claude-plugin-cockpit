"""Tests: the app's end-of-turn card and the « Qn · » question of the same message make one line (2026-11-18):
python3 -m unittest discover -s tests

Measured on the PM's board: a session ended its turn with the app's card (« ask », « actions ») and a message whose
« À trancher » held the same decision as Q7, with « Encore ouvert : » alone on its line above Q1. That heading was read as
a reminder without a number, so the card came up as a line of its own: its « ask » as title, its labels as grey text, no
answer button, and a detail repeating the title.

Now: the heading followed by numbered questions is no such reminder; a card that asks a Qn of its message again (same
number, else the Qn whose options are the card's answers, else the only Qn under « À trancher ») gives no line, and the
Qn line keeps its title, its whole question unfolded and its answer buttons; a card of its own gets its labels as
buttons and unfolds to its question and the session's recap. Synthetic data only (temporary HOME)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import pathlib
import tempfile
import unittest

from test_cockpit_native_questions import parc, card, final, pm, NOW

ROOT = pathlib.Path(__file__).resolve().parents[1]
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here

MESSAGE = ("J'ai trouvé la cause.\n\n## À trancher\n\n"
           "Q7 · Ordre du correctif : Je le fais construire juste après le bouton, sur la même branche ?\n"
           "1) **Après le bouton** (recommandé) : les deux touchent la page, une seule installation.\n"
           "2) **Avant le bouton** : j'arrête le bouton et je passe ce correctif d'abord.\n"
           "Pourquoi : le bouton est déjà en route. Si tu ne fais rien : il part après le bouton.\n\n"
           "Encore ouvert :\n\n"
           "Q1 · Choisir le premier chantier : par quoi on commence ?\n"
           "1) **Relecture avec Ana** (recommandé) : tu ouvres la page et Ana note ce qui accroche.\n"
           "2) **Correctif de sécurité** : Léo ferme l'accès des sessions aux outils de la page.\n"
           "Pourquoi : Camille et Robin regardent déjà l'écran. Si tu ne fais rien : rien n'avance avant vendredi.")
ACTIONS = [('Oui, après le bouton', ''), ('Avant le bouton', '')]


class CardAndQuestion(unittest.TestCase):
    def board(self, entries, sid='local_00000000-0000-0000-0000-0000000000f1'):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 't.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')
            res = parc.analyser(str(path), NOW + 3600)
        s = dict(res, id=sid, cwd='/studios/Studio-Essai', titre='Kit · Sam', non_lue=True, derniere=NOW, chemin='/dev/null')
        cards = [{'id': sid, 'archivee': False, 'cwd': s['cwd'], 'titre': s['titre'], 'parent': None}]
        return res, [l for l in parc.tableau([s], cards, [], 7, NOW + 3600, {}) if l['cle'] == sid]

    def test_the_card_restating_q7_is_one_line_with_buttons_and_the_whole_question(self):
        res, lines = self.board([pm(3, 'Pourquoi la ligne revient ?'),
                                 *card(2, 'a', 'Je corrige après le bouton, sur la même branche ?', ACTIONS),
                                 final(1.9, MESSAGE, 'b')])
        self.assertIn('carte', res)
        self.assertEqual(sorted(l.get('question') for l in lines), ['Q1', 'Q7'])
        self.assertFalse([l for l in lines if l.get('native') or l.get('menu')], 'no line of the card')
        q7 = next(l for l in lines if l.get('question') == 'Q7')
        self.assertTrue(q7['titre'].startswith('Q7 · Ordre du correctif'))
        self.assertEqual(q7['choix'][-1], 'pas encore')
        self.assertIn('1', q7['choix'])
        self.assertIn('2', q7['choix'])
        self.assertEqual(q7.get('choix_libelles', {}).get('1'), 'Après le bouton')
        depli = q7.get('depli') or {}
        self.assertEqual(depli['question'], 'Je le fais construire juste après le bouton, sur la même branche ?')
        self.assertEqual([o['gras'] for o in depli['options']], ['Après le bouton', 'Avant le bouton'])
        self.assertIn("j'arrête le bouton", depli['options'][1]['entiere'])
        self.assertEqual((depli['pourquoi'], depli['sinon']), ('le bouton est déjà en route.', 'il part après le bouton.'))

    def test_the_card_matches_its_qn_by_number_or_by_its_answers(self):
        menu = [{'question': 'Je corrige après le bouton ?', 'options': [{'label': l} for l, _ in ACTIONS]}]
        lignes = [{'num': 7, 'lecture': 'format', 'brut': MESSAGE.split('Encore ouvert')[0], 'titre': 'Q7', 'suite': ''},
                  {'num': 1, 'lecture': 'format', 'brut': MESSAGE.split('Encore ouvert')[1], 'titre': 'Q1', 'suite': ''}]
        self.assertEqual(parc.carte_redit(menu, lignes)['num'], 7)
        menu[0]['options'] = [{'label': 'Relecture avec Ana'}, {'label': 'Correctif de sécurité'}]
        self.assertEqual(parc.carte_redit(menu, lignes)['num'], 1)
        menu[0]['options'] = [{'label': 'Plus tard'}, {'label': 'Jamais'}]
        self.assertIsNone(parc.carte_redit(menu, lignes), 'two questions, no answer in common: no guess')

    def test_a_card_of_its_own_gets_buttons_and_unfolds_to_its_question_and_recap(self):
        res, lines = self.board([pm(3, 'Lance le passage.'),
                                 *card(2, 'a', 'Je relance le passage de Sam ce soir ?', [('Oui, ce soir', ''), ('Demain', '')],
                                       recap="Le passage d'Alex s'est arrêté avant toute écriture."),
                                 final(1.9, "Le passage s'est arrêté.", 'b')])
        (l,) = [x for x in lines if x.get('native')]
        self.assertEqual((l['choix'], l.get('seule'), l.get('question')), (['Oui, ce soir', 'Demain'], True, ''))
        self.assertEqual(l['suite'], '', 'the answers are buttons, not grey text')
        self.assertIn('Je relance le passage de Sam ce soir ?', l['detail'])
        self.assertIn("Le passage d'Alex s'est arrêté avant toute écriture.", l['detail'])
        self.assertNotEqual(l['detail'].strip(), l['titre'].strip())
        page = parc.rang_page(l)
        self.assertEqual(page['choix'], ['Oui, ce soir', 'Demain'])

    def test_the_open_heading_alone_is_no_reminder_without_number(self):
        self.assertFalse(parc.rappel_sans_numero('Fait.\n\nEncore ouvert :\n\nQ1 · Premier chantier : lequel ?'))
        self.assertFalse(parc.rappel_sans_numero('Fait.\n\n**Encore ouvert :**\n- Q3 · Format : lequel ?'))
        self.assertTrue(parc.rappel_sans_numero("Encore ouvert : l'étape 3, en attente de ta réponse dans l'encadré."))
        self.assertTrue(parc.rappel_sans_numero('Encore ouvert :\n\nla relecture du devis par Léo.'))

    def test_the_rule_tells_sessions_to_title_the_card_like_the_question(self):
        texte = (ROOT / 'regles' / 'format-reponses.md').read_text(encoding='utf-8')
        self.assertIn('wrap_up', texte)
        self.assertIn('« Qn · titre »', texte)


if __name__ == '__main__':
    unittest.main()
