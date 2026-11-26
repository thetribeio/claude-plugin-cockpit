"""The piece of a review line (PM, Q1 du 2026-11-17, confirmed 2026-11-25): python3 -m unittest discover -s tests

1. A question that asks to read a document carries its link: « Pièce : <lien> », else the first link to a document
   (artifact, Google Docs or Drive, Notion, wiki). Read from the text, never guessed: another link is not a piece.
2. The page shows « Ouvrir le document ↗ » on the row, beside the answer buttons, and in the unfold.
3. The Stop hook asks for a « Pièce : » on a review that names no link and no file; rule 2 says so.
Sessions and texts are made up, no client name."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

spec = importlib.util.spec_from_file_location('parc_piece', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)

ARTIFACT = 'https://claude.ai/artifact/abc123'
DOC = 'https://docs.google.com/document/d/1AbC/edit'


def question(corps):
    return ("Prêt.\n\n**À trancher**\n\nQ5 · Relire le compte rendu du comité : " + corps + "\n"
            "1) **C'est bon** (recommandé) : tu l'envoies tel quel.\n2) **Corrections** : tu me les dictes.\n"
            "Pourquoi : il part demain. Si tu ne fais rien : il attend.\n")


def board(texte):
    s = {'id': 'local_a', 'cwd': '/studios/Studio-Beta', 'titre': 'Comité', 'non_lue': True, 'derniere': 1e9,
         'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}
    cards = [{'id': 'local_a', 'archivee': False, 'cwd': s['cwd'], 'titre': s['titre'], 'parent': None}]
    return [parc.rang_page(l) for l in parc.tableau([s], cards, [], 7, 1e9 + 60, {})]


class Extraction(unittest.TestCase):
    def test_the_labelled_piece_is_the_link(self):
        d = board(question(f"Pièce : {ARTIFACT}"))[0]['depli']
        self.assertEqual(d['piece'], ARTIFACT)

    def test_a_labelled_link_of_any_host_is_taken(self):
        self.assertEqual(parc.piece_citee('', 'https://exemple.test/cr.pdf.'), 'https://exemple.test/cr.pdf')

    def test_a_markdown_link_to_a_document_is_taken_without_label(self):
        d = board(question(f"voici [le compte rendu]({DOC}) à relire."))[0]['depli']
        self.assertEqual(d['piece'], DOC)

    def test_a_link_that_is_not_a_document_is_not_a_piece(self):
        d = board(question("voir https://exemple.test/ticket/42 pour le contexte."))[0]['depli']
        self.assertEqual(d['piece'], '')

    def test_no_link_no_piece(self):
        self.assertEqual(board(question("la version du dossier."))[0]['depli']['piece'], '')

    def test_the_label_wins_over_another_document_link(self):
        d = board(question(f"voir {DOC}. Pièce : {ARTIFACT}"))[0]['depli']
        self.assertEqual(d['piece'], ARTIFACT)

    def test_the_question_does_not_swallow_the_label(self):
        d = board(question(f"Tu le relis. Pièce : {ARTIFACT}"))[0]['depli']
        self.assertNotIn('Pièce', d['question'])
        self.assertEqual(d['question'], 'Tu le relis.')

    def test_a_file_of_the_studio_is_still_offered_as_a_file(self):
        d = board(question("Pièce : `/studios/Studio-Beta/3-dev/cr.md`"))[0]['depli']
        self.assertEqual((d['piece'], d['fichiers']), ('', ['3-dev/cr.md']))


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def rendu(self, depli, type_='review', dossier='/S/Beta'):
        ligne = {'studio': 'Beta', 'session': 'Comité', 'cle': 'local_a', 'type': type_, 'verbe': 'Relire',
                 'affiche_titre': 'Q5 · Relire le compte rendu', 'affiche_suite': '', 'question': 'Q5', 'ouvrir': 'local_a',
                 'complet': 'Q5 · Relire le compte rendu : à relire', 'detail': 'Q5 · Relire le compte rendu : à relire',
                 'dossier': dossier, 'choix': ['1', '2', 'pas encore'], 'choix_libelles': {'1': "C'est bon", '2': 'Corrections'},
                 'choix_reco': '1', 'depuis': int(time.time() * 1000) - 60000,
                 'depli': dict({'enonce': 'Q5 · Relire le compte rendu', 'options': [], 'recommande': '', 'fichiers': []}, **depli)}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'lignes': [ligne], 'outils': ['lignes', 'projet', 'ouvrir', 'clore', 'lire']}, f)
        try:
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['tableau']

    def test_the_row_carries_the_link_beside_the_answers(self):
        html = self.rendu({'piece': ARTIFACT})
        debut = html.rfind('<tr', 0, html.index('Relire le compte rendu'))
        ligne = html[debut:html.index('</tr>', debut)]
        self.assertIn(f'href="{ARTIFACT}"', ligne)
        self.assertIn('Ouvrir le document ↗', ligne)
        self.assertIn('C&#39;est bon', ligne)
        self.assertIn('Corrections', ligne)

    def test_a_review_without_piece_shows_no_document_button(self):
        self.assertNotIn('Ouvrir le document', self.rendu({}))

    def test_a_studio_text_file_is_read_in_the_page(self):
        html = self.rendu({'fichiers': ['3-dev/cr.md']})
        self.assertIn('data-lecture', html)


class Controle(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'hooks'))
        s = importlib.util.spec_from_file_location('format_questions_piece', ROOT / 'hooks' / 'format_questions.py')
        self.hook = importlib.util.module_from_spec(s)
        s.loader.exec_module(self.hook)

    def ecarts(self, texte):
        items = [it for it in parc.a_trancher(texte)[0] if it['num']]
        return [k for k, _ in self.hook.ecarts(parc, items[0])]

    def test_a_review_without_piece_is_flagged(self):
        self.assertIn('relecture_sans_piece', self.ecarts(question('Tu le relis.')))

    def test_a_review_with_a_link_or_a_path_passes(self):
        self.assertNotIn('relecture_sans_piece', self.ecarts(question(f'Pièce : {ARTIFACT}')))
        self.assertNotIn('relecture_sans_piece', self.ecarts(question('Tu le relis. Pièce : `/Users/pm/Studio-Beta/3-dev/cr.md`')))

    def test_a_question_that_is_not_a_review_is_not_flagged(self):
        t = question('Tu le relis.').replace('Relire le compte rendu', 'Envoyer le compte rendu')
        self.assertNotIn('relecture_sans_piece', self.ecarts(t))

    def test_rule_two_asks_for_it(self):
        texte = (ROOT / 'regles' / 'format-reponses.md').read_text(encoding='utf-8')
        self.assertIn('Pièce : <lien du document>', texte)


if __name__ == '__main__':
    unittest.main()
