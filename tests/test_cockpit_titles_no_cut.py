"""Tests: a title is short and never cut with « … »; the unfold never repeats it (PM, 2026-11-19).

1. A request's title is the head of its sentence up to a natural break (comma, colon, dash, aside in parentheses), or
   whole words that do not end on a linking word: never « … », never inside a parenthesis, a command or a path.
2. A request noted before, whose stored title ends on « … », gets its title again from its text.
3. A line of a session on the board is cut the same way (parc.coupe_nette).
4. The unfold shows what the title does not say; when nothing remains, no repetition.
People, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import html as html_
import json
import pathlib
import re
import shutil
import tempfile
import unittest

from test_cockpit_board_actionable import a_toi, liste, rangee, run_page, state
from test_cockpit_projets import Base, MONDAY, FRIDAY

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc_titres', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

SECURITE = ("Un mot de passe d'admin du BO de prod et des comptes de test sont en clair dans #projet-interne "
            "(Ana, 02/11) : à passer dans le coffre et retirer du canal, sans délai.")
TETE = "Un mot de passe d'admin du BO de prod et des comptes de test sont en clair dans #projet-interne"


def report(*requests):
    return '📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {r}\n' for r in requests)


def texte(html):
    return html_.unescape(re.sub(r'<[^>]+>', ' ', html))


class Cut(unittest.TestCase):
    def test_head_up_to_a_natural_break_without_ellipsis(self):
        self.assertEqual(parc.coupe_nette(SECURITE, 100, premier=True), TETE)
        t = "Partager avec le reste de l'équipe les artefacts envoyés jusqu'ici à Léo, action notée à ton nom au daily."
        self.assertEqual(parc.coupe_nette(t, 100, premier=True), "Partager avec le reste de l'équipe les artefacts envoyés jusqu'ici à Léo")

    def test_a_short_text_is_untouched(self):
        self.assertEqual(parc.coupe_nette('Envoyer le devis', 100, premier=True), 'Envoyer le devis')

    def test_never_inside_a_parenthesis_and_never_on_a_linking_word(self):
        t = "Des identifiants de test et d'administration (site de prod, back-office) sont en clair dans #projet-interne (message d'Ana, 02/11) : à passer"
        coupe = parc.coupe_nette(t, 100, premier=True)
        self.assertEqual(coupe.count('('), coupe.count(')'))
        self.assertFalse(coupe.endswith((' dans', ' de', ' le', ' et')))
        self.assertNotIn('…', coupe)

    def test_no_break_at_all_cuts_on_whole_words(self):
        coupe = parc.coupe_nette('mot ' * 60, 50)
        self.assertNotIn('…', coupe)
        self.assertLessEqual(len(coupe), 50)
        self.assertTrue(coupe.endswith('mot'))

    def test_never_inside_a_command(self):
        t = "Pour lancer le tri de la réunion de jeudi avec toute l'équipe il faudra taper /studio:auto-ingest tri dans la session"
        self.assertNotIn('/studio', parc.coupe_nette(t, 90, premier=True)[-12:])


class RequestTitle(Base):
    def test_title_of_a_security_line_is_its_head(self):
        self.runs(self.alpha, (MONDAY - 600, report(SECURITE)))
        l = self.block(self.compute())['lignes'][0]
        self.assertEqual(l['titre'], TETE)
        self.assertEqual(l['texte'], SECURITE)

    def test_a_title_stored_with_an_ellipsis_is_given_again_from_its_text(self):
        self.runs(self.alpha, (FRIDAY - 4 * 86400, report(SECURITE)))
        self.compute(MONDAY - 3600)
        cle, ligne = next(iter(state(self.mon_studio).items()))
        ligne['titre'] = TETE[:60].rsplit(' ', 1)[0] + '…'   # what 0.3.11 stored
        path = self.mon_studio / '.parc' / 'projets-etat.json'
        brut = json.loads(path.read_text(encoding='utf-8'))
        brut['lignes'][cle] = ligne
        path.write_text(json.dumps(brut), encoding='utf-8')
        # The ingestion no longer lists it: only the stored line speaks.
        self.runs(self.alpha, (FRIDAY - 4 * 86400, report('Une autre demande')))
        out = self.compute()
        titres = [x['titre'] for x in self.block(out)['lignes'] if x['type'] == 'a_toi']
        self.assertIn(TETE, titres)
        self.assertFalse([t for t in titres if t.endswith('…')])


class Session(unittest.TestCase):
    def test_a_long_session_line_is_cut_on_a_break_not_on_an_ellipsis(self):
        question = 'Q3 · Budget : ' + 'Faut-il valider la version du devis avant la réunion, ou attendre la réponse du client sur le périmètre exact ?'
        cards = [{'id': 'local_a', 'archivee': False, 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'parent': None}]
        s = {'id': 'local_a', 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'non_lue': True, 'derniere': 1e9, 'etat': 'attend',
             'depuis': 1e9, 'chemin': '/dev/null', 'texte': '**À trancher**\n\n' + question + '\n'}
        for l in parc.tableau([s], cards, [], 7, 1e9 + 60, {}):
            self.assertNotIn('…', l['affiche_titre'] + l['affiche_suite'])


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Unfold(unittest.TestCase):
    def test_the_unfold_shows_only_what_the_title_does_not_say(self):
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', TETE, SECURITE)))
        r = texte(rangee(out['tableau'], 'Un mot de passe'))
        self.assertEqual(r.count("Un mot de passe d'admin"), 1, 'the title once, never again in the unfold')
        self.assertIn('à passer dans le coffre et retirer du canal, sans délai.', r)
        self.assertIn('(Ana, 02/11)', r)

    def test_no_unfold_text_when_nothing_remains(self):
        out, _ = run_page(liste_projets=liste(a_toi('aaaaaaaaaaa1', 'Envoyer le devis à Léo…', 'Envoyer le devis à Léo.')))
        r = texte(rangee(out['tableau'], 'Envoyer le devis'))
        self.assertEqual(r.count('Envoyer le devis'), 1)

    def test_a_session_line_does_not_repeat_its_cut_question(self):
        titre = 'Faut-il valider la version du devis avant la réunion'
        complet = titre + ', ou attendre la réponse du client sur le périmètre exact ?'
        ligne = {'studio': 'Alpha', 'session': 'Démarrage', 'cle': 'local_00000000-0000-0000-0000-0000000000c1', 'lien': '',
                 'type': 'decision', 'verbe': 'Répondre', 'affiche_titre': '', 'affiche_suite': titre, 'complet': complet,
                 'detail': complet, 'bloque': False, 'proche': False, 'impact': 'normal', 'raison': '', 'effort': '',
                 'hors_studio': False}
        out, _ = run_page(lignes=[ligne])
        r = texte(rangee(out['tableau'], titre))
        self.assertEqual(r.count('Faut-il valider'), 1)
        self.assertIn('attendre la réponse du client', r)

    def test_a_bullet_that_opens_on_the_title_says_only_what_follows(self):
        ligne = {'studio': 'Alpha', 'session': 'Démarrage', 'cle': 'local_00000000-0000-0000-0000-0000000000c1', 'lien': '',
                 'type': 'check', 'verbe': 'Vérifier', 'affiche_titre': '', 'affiche_suite': 'Tu veux que je lance la migration maintenant',
                 'complet': 'Tu veux que je lance la migration maintenant, ou tu vérifies d\'abord ?',
                 'puces': ['Tu veux que je lance la migration maintenant, ou tu vérifies d\'abord ?', 'Tu as dit oui hier.'],
                 'detail': '', 'bloque': False, 'proche': False, 'impact': 'normal', 'raison': '', 'effort': '', 'hors_studio': False}
        out, _ = run_page(lignes=[ligne])
        r = texte(rangee(out['tableau'], 'Tu veux que je lance'))
        self.assertEqual(r.count('Tu veux que je lance'), 1)
        self.assertIn("ou tu vérifies d'abord ?", r)
        self.assertIn('Tu as dit oui hier.', r)


if __name__ == '__main__':
    unittest.main()
