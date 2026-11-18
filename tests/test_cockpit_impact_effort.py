"""Tests: the board sorted by impact and effort (PM, 2026-11-17): python3 -m unittest discover -s tests

« Ce qui est très impactant et très peu coûteux en premier. » Each line carries `impact` (fort, normal, faible), a
`raison` in a few words and an `effort` (court, long or ''). No model: whoever writes the line may label it in its own
words (« (impact fort : client attend) », « (effort court) »), and plain rules stand in otherwise.
1. The labels are read apart and leave the text; « fort » without a reason of the closed list is « normal ».
2. The rules: a late or close due date, a session that waits or stopped, « bloqué », « en clair », « sans délai », and
   for a request of the ingestion a person who asks or waits, make a line « fort »; « archiver cette session » makes it
   « faible »; one click to answer makes the effort « court ».
3. A request of the ingestion keeps its label through projets.py, its key ignores it, and a late or labelled one never
   folds into « Anciennes ».
4. The page shows three bands, « D'abord » (short answers first), « Ensuite » (lines outside any Studio last) and
   « Peut attendre », folded; a strong line says why.
People, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

import test_cockpit_exits_and_sort as board_tests
from test_cockpit_projets import Base, FRIDAY, MONDAY, local

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

spec = importlib.util.spec_from_file_location('parc_impact', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
NOW = time.time()
DAY = 86400


def report(*requests):
    return '📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {r}\n' for r in requests)


class Labels(unittest.TestCase):
    def test_read_apart_and_taken_out_of_the_text(self):
        self.assertEqual(parc.etiquettes('Valider la maquette (impact fort : client attend) (effort court)'),
                         ('Valider la maquette', {'impact': 'fort', 'raison': 'client attend', 'effort': 'court'}))
        self.assertEqual(parc.etiquettes("Ranger l'échange (impact faible)"), ("Ranger l'échange", {'impact': 'faible', 'raison': ''}))
        self.assertEqual(parc.etiquettes('Q3 · Budget (Impact Fort : Argent ou contrat) : lequel ?'),
                         ('Q3 · Budget : lequel ?', {'impact': 'fort', 'raison': 'argent ou contrat'}))

    def test_a_text_without_label_is_untouched(self):
        self.assertEqual(parc.etiquettes('  Relire (v2) le plan  '), ('  Relire (v2) le plan  ', {}))
        self.assertEqual(parc.etiquettes("L'impact fort du retard (voir le plan)"), ("L'impact fort du retard (voir le plan)", {}))

    def test_strong_needs_a_reason_of_the_list(self):
        for texte in ('Choisir la couleur (impact fort)', 'Choisir la couleur (impact fort : important pour moi)'):
            self.assertEqual(parc.etiquettes(texte)[1], {'impact': 'normal', 'raison': ''})
        for raison in parc.RAISONS:
            self.assertEqual(parc.etiquettes(f'X (impact fort : {raison})')[1], {'impact': 'fort', 'raison': raison})


class Rules(unittest.TestCase):
    def p(self, texte, **plus):
        return parc.priorite(texte, NOW, **plus)

    def test_what_was_said_comes_first(self):
        dit = {'impact': 'faible', 'raison': '', 'effort': 'long'}
        self.assertEqual(self.p('Production bloquée, sans délai', dit=dit), {'impact': 'faible', 'raison': '', 'effort': 'long'})
        self.assertEqual(self.p('Choisir', dit={'effort': 'court'}), {'impact': 'normal', 'raison': '', 'effort': 'court'})

    def test_due_dates(self):
        self.assertEqual(self.p('Envoyer le devis', echeance=NOW - 3 * DAY)['raison'], 'en retard')
        self.assertEqual(self.p('Envoyer le devis', echeance=NOW - 3 * DAY)['impact'], 'fort')
        self.assertEqual(self.p('Envoyer le devis', echeance=NOW + DAY, proche=True), {'impact': 'fort', 'raison': '', 'effort': ''})
        self.assertEqual(self.p('Envoyer le devis', echeance=NOW + 20 * DAY)['impact'], 'normal')

    def test_a_session_that_waits_or_stopped(self):
        self.assertEqual(self.p('Q2 · Format', bloque=True)['impact'], 'fort')
        self.assertEqual(self.p('Arrêtée en plein travail', arret='interrupted')['impact'], 'fort')

    def test_words_that_say_so(self):
        self.assertEqual(self.p('Des identifiants sont en clair dans le canal')['raison'], 'sécurité')
        self.assertEqual(self.p('À retirer du canal, sans délai')['raison'], 'urgent')
        self.assertEqual(self.p('La production est bloquée à 20 mails par jour')['raison'], 'bloqué')
        self.assertEqual(self.p('Q1 · Issue du comité (bloquante pour la page 3)')['raison'], 'bloqué')
        for texte in ('Il doit bloquer ses rendez-vous', 'Le point est débloqué', 'Sujet non bloquant', 'Écrire en clairière'):
            self.assertEqual(self.p(texte)['impact'], 'normal', texte)

    def test_a_person_who_asks_only_for_a_request(self):
        self.assertEqual(self.p('Ana te demande si on exporte aussi en CSV', demande=True),
                         {'impact': 'fort', 'raison': 'Ana attend', 'effort': ''})
        self.assertEqual(self.p('Ana Martin et Léo Petit attendent un accès', demande=True)['raison'], 'Ana Martin et Léo Petit attend')
        self.assertEqual(self.p('Ana préfère prévoir les cartes', demande=True)['impact'], 'normal')
        self.assertEqual(self.p('Relancer Léo pour le poste de test', demande=True)['impact'], 'normal')
        self.assertEqual(self.p('Ana te demande si on exporte aussi en CSV')['impact'], 'normal')

    def test_tidying_is_weak(self):
        for texte in ('Q40 · Archiver cette session : oui (recommandé), ou tu la gardes.', "J'archive cette session maintenant ?",
                      'Archivage de cette session : j’archive, ou tu la gardes.'):
            self.assertEqual(self.p(texte)['impact'], 'faible', texte)
            self.assertEqual(self.p(texte)['raison'], 'rangement')
        self.assertEqual(self.p('Archiver les maquettes dans le Drive')['impact'], 'normal')

    def test_effort(self):
        self.assertEqual(self.p('Q2 · Format', choix=['A', 'B'])['effort'], 'court')
        self.assertEqual(self.p('Q2 · Envoi', type_='go')['effort'], 'court')
        self.assertEqual(self.p('Q2 · Relire', type_='review')['effort'], '')


class Requests(Base):
    def lines(self, when=MONDAY):
        return {l['titre']: l for l in self.block(self.compute(when))['lignes']}

    def test_the_label_is_kept_and_leaves_the_words(self):
        self.runs(self.alpha, (FRIDAY, report('Valider la maquette (impact fort : client attend) (effort court) (échéance 2026-11-20)',
                                              "Ranger l'échange resté en file (impact faible)", 'Caler le point')))
        lines = self.lines()
        self.assertEqual(sorted(lines), ['Caler le point', "Ranger l'échange resté en file", 'Valider la maquette'])
        v = lines['Valider la maquette']
        self.assertEqual((v['impact'], v['raison'], v['effort'], v['echeance']), ('fort', 'client attend', 'court', '2026-11-20'))
        self.assertNotIn('impact', v['texte'])
        self.assertEqual(lines["Ranger l'échange resté en file"]['impact'], 'faible')
        self.assertEqual(lines['Caler le point']['impact'], 'normal')

    def test_the_key_ignores_the_label(self):
        self.assertEqual(self.p.cle_a_toi('Valider la maquette (impact fort : client attend) (échéance 2026-11-20)'),
                         self.p.cle_a_toi('Valider la maquette'))

    def test_the_rules_when_nothing_is_said(self):
        self.runs(self.alpha, (FRIDAY, report('Ana te demande de confirmer le type de cellule', 'Des identifiants sont en clair dans le canal')))
        lines = self.lines()
        self.assertEqual(lines['Ana te demande de confirmer le type de cellule']['raison'], 'Ana attend')
        self.assertEqual(lines['Des identifiants sont en clair dans le canal']['raison'], 'sécurité')

    def test_what_presses_never_folds_into_anciennes(self):
        self.runs(self.alpha, (local(2026, 10, 20), report('Valider la maquette (impact fort : client attend)', 'Ana te demande un accès',
                                                           'Des identifiants sont en clair dans le canal', 'Caler le point')))
        self.compute(local(2026, 10, 21))
        old = {t: l['ancienne'] for t, l in self.lines(local(2026, 11, 10)).items()}
        self.assertEqual(old, {'Valider la maquette': False, 'Des identifiants sont en clair dans le canal': False,
                               'Ana te demande un accès': True, 'Caler le point': True})


class BoardLines(unittest.TestCase):
    """The lines of the board itself (parc.lignes_et_anciennes), through the harness of the sort tests."""
    def setUp(self):
        self.b = board_tests.Board('board')
        self.b.setUp()
        self.addCleanup(self.b.doCleanups)
        self.addCleanup(self.b.tearDown)

    def lines(self, *attentes):
        fresh = self.b.board(attentes)[2]
        return {l['question']: l for l in fresh if l.get('chantier')}

    def test_a_question_carries_its_label_and_loses_it_on_screen(self):
        line, KIT = board_tests.line, board_tests.KIT
        lines = self.lines(line(1, KIT, 30, title='Date de recette (impact fort : échéance)'),
                           line(2, KIT, 20, title='Archiver cette session'),
                           line(3, KIT, 10, title='Production bloquée : que faire ?', kind='go'),
                           line(4, KIT, 5))
        self.assertEqual([(q, lines[q]['impact'], lines[q]['raison'], lines[q]['effort']) for q in ('Q1', 'Q2', 'Q3', 'Q4')],
                         [('Q1', 'fort', 'échéance', ''), ('Q2', 'faible', 'rangement', ''), ('Q3', 'fort', 'bloqué', 'court'),
                          ('Q4', 'normal', '', '')])
        self.assertNotIn('impact', lines['Q1']['complet'])
        self.assertIn('Date de recette', lines['Q1']['complet'])
        self.assertFalse(lines['Q1']['hors_studio'])
        page = board_tests.parc.rang_page(lines['Q1'])
        self.assertEqual((page['impact'], page['raison'], page['effort'], page['hors_studio']), ('fort', 'échéance', '', False))


def run_page(**entree):
    entree.setdefault('outils', ['lignes', 'projet', 'ouvrir', 'clore', 'lire', 'repondre', 'attentes'])
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(entree, f)
    try:
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def ligne(titre, studio='Alpha', **plus):
    return dict({'studio': studio, 'session': 'Démarrage', 'cle': 'local_00000000-0000-0000-0000-0000000000c1', 'lien': '',
                 'type': 'decision', 'verbe': 'Répondre', 'affiche_titre': titre, 'affiche_suite': '', 'bloque': False,
                 'proche': False, 'impact': 'normal', 'raison': '', 'effort': '', 'hors_studio': False}, **plus)


def demande(titre, **plus):
    return dict({'cle': 'a' * 12, 'type': 'a_toi', 'titre': titre, 'texte': titre, 'depuis': int((NOW - 3600) * 1000),
                 'session': '', 'repli': False, 'echeance': None, 'lien': '', 'dossier': '/x/alpha', 'ancienne': False,
                 'auteur': '', 'canal': '', 'impact': 'normal', 'raison': '', 'effort': ''}, **plus)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def order(self, html, *titres):
        places = [html.find(t) for t in titres]
        self.assertNotIn(-1, places, (titres, places))
        self.assertEqual(places, sorted(places), titres)

    def test_three_bands(self):
        out = run_page(lignes=[ligne('Question ordinaire'), ligne('Question du dépôt', studio='Outil', hors_studio=True),
                               ligne('Question du Studio B', studio='Beta'),
                               ligne('Production arrêtée', impact='fort', raison='bloqué'),
                               ligne('Go attendu', impact='fort', raison='client attend', effort='court'),
                               ligne('Archiver cette session', impact='faible', raison='rangement')],
                       liste_projets={'projets': [{'nom': 'Alpha', 'dossier': '/x/alpha', 'lignes': [
                           demande('Ana demande un accès', impact='fort', raison='Ana attend'),
                           demande('Caler le point', cle='b' * 12)]}], 'studios': ['Alpha']})
        t = out['tableau']
        self.order(t, "D'abord", 'Go attendu', 'Ana demande un accès', 'Production arrêtée', 'Ensuite', 'Caler le point',
                   'Question ordinaire', 'Question du Studio B', 'Question du dépôt')
        self.assertIn('D\'abord <span class="n">· 3</span>', t)
        self.assertIn('Ensuite <span class="n">· 4</span>', t)
        self.assertIn('<span class="raison">client attend</span><span class="raison court">réponse courte</span>', t)
        self.assertIn('<span class="raison">Ana attend</span>', t)
        self.assertNotIn('Archiver cette session', t)
        self.assertIn('Archiver cette session', out['attendre'])
        self.assertFalse(out['attendreHidden'])
        self.assertTrue(out['attendreReplie'], 'folded until the PM opens it')

    def test_peut_attendre_opens_on_a_click(self):
        out = run_page(lignes=[ligne('Archiver cette session', impact='faible')], cliquer=[['attendre-bascule', '1']])
        self.assertFalse(out['attendreReplie'])

    def test_no_band_title_when_nothing_is_strong(self):
        out = run_page(lignes=[ligne('Question ordinaire'), ligne('Autre question')])
        self.assertNotIn('bande-titre', out['tableau'])
        self.assertTrue(out['attendreHidden'])
        self.order(out['tableau'], 'Question ordinaire', 'Autre question')

    def test_a_line_without_the_new_fields_stays_in_the_table(self):
        # An older connector serves lines without impact: the board shows them as before.
        vieille = {k: v for k, v in ligne('Question ancienne version').items() if k not in ('impact', 'raison', 'effort', 'hors_studio')}
        out = run_page(lignes=[vieille])
        self.assertIn('Question ancienne version', out['tableau'])


if __name__ == '__main__':
    unittest.main()
