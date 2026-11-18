"""Tests: the rest of the usage review of Mon Studio (PM, 2026-11-17): python3 -m unittest discover -s tests

A. One « C'est fait » on a gesture done elsewhere; a clean recommendation (never an address, « recommandée » too, one
   « Oui », a short button, no « : . » at the head of a line); « Fermé depuis hier » gone; « Sans action » folded to
   client projects; one style for « Ouvrir ↗ »; the count of « Anciennes » without the lines already retired.
B. The card of a session's question: Pourquoi · Ce qu'on attend de toi · Si tu ne fais rien · Recommandation · Pièce;
   nothing beyond the title, no unfold.
C. « Plus tard » hides the line until tomorrow on the board only, sends nothing to the session.
D. 21 days without movement: « Peut attendre »; « Tout retirer pour ce projet »; « Abandonner » a session stopped 48 h.
E. A question relayed by another session is hidden when that session carries it, « aussi dans X » when unsure.
F. « Reçu » on a third-party wait; no wait that the board already carries.
G. Today, the morning stand-up: no copy of the board's requests, no entry the PM wrote himself, « Sans réponse », what
   waits for each meeting, the meetings without minutes.
Sessions, Studios, people and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import shutil
import tempfile
import time
import unittest

from test_cockpit_board_lighter import SID, charger, ligne, run_page

parc = charger('parc_reste', 'parc.py')
projets = charger('projets_reste', 'projets.py')
JOUR = 86400000


def maintenant_ms():
    return int(time.time() * 1000)


class Recommendation(unittest.TestCase):
    def test_never_an_address_and_the_feminine_too(self):
        self.assertEqual(parc.recommandation('Q5 · Dépôt : //github.com/organisation/depot (recommandé) ou rien'), '')
        self.assertEqual(parc.recommandation('Lien : https://exemple.org/page (recommandé)'), '')
        self.assertEqual(parc.recommandation('Q8 · Format : 1. court 2. long (recommandée) 3. aucun'), 'long')


class QuestionCard(unittest.TestCase):
    def test_the_rubrics_the_question_writes(self):
        d = parc.depli_de_question('Q3 · Format du compte rendu', 'lequel envoyer ? Pourquoi : la cliente lit sur mobile. '
                                   'Si tu ne fais rien : je garde le long. Je propose : court.')
        self.assertEqual((d['pourquoi'], d['sinon'], d['recommande']), ('la cliente lit sur mobile.', 'je garde le long.', 'court'))
        self.assertEqual(d['enonce'], 'Q3 · Format du compte rendu : lequel envoyer ?')

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_page_shows_a_card_and_recommends_once(self):
        d = parc.depli_de_question('Q3 · Format', 'lequel ? Pourquoi : la cliente lit sur mobile. Je propose : court.')
        r = run_page(lignes=[ligne(depli=d, choix=['recommandé : court', 'pas encore'])])['tableau']
        self.assertIn('<dt>Pourquoi</dt>', r)
        self.assertIn('<dt>Recommandé</dt>', r)   # « Recommandé » since 0.3.2 (PM, 2026-11-18)
        self.assertNotIn('<dt>Si tu ne fais rien</dt>', r)   # an empty rubric is not shown
        self.assertEqual(r.count('Recommandé'), 1)

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_nothing_beyond_the_title_still_unfolds_without_repeating_it(self):
        # Every line opens on click (PM, 2026-11-18): when nothing adds to the row, where it came from and when.
        d = parc.depli_de_question('Q7 · Format', 'lequel ?')
        r = run_page(lignes=[ligne(depli=d)])['tableau']
        self.assertIn('data-deplier', r)
        detail = r.split('class="detail"')[1]
        self.assertNotIn('Q7 · Format', detail)
        self.assertNotIn('lequel ?', detail)
        self.assertIn('Apparue', detail)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Buttons(unittest.TestCase):
    def test_one_yes_a_short_label_and_no_punctuation_at_the_head(self):
        r = run_page(lignes=[ligne(choix=['recommandé : Oui, par défaut sous chaque question', 'oui', 'pas encore'],
                                   affiche_suite='. La page dit deux choses')])['tableau']
        self.assertEqual(r.count('data-choix='), 1)
        self.assertIn('>Oui (recommandé)</button>', r)
        self.assertNotIn(': .', r)
        long = run_page(lignes=[ligne(choix=['recommandé : Une passe légère planifiée chaque semaine', 'pas encore'])])['tableau']
        self.assertIn('>Une passe légère planifiée… (recommandé)<', long)

    def test_plus_tard_hides_until_tomorrow_and_sends_nothing(self):
        r = run_page(lignes=[ligne(choix=['go', 'pas encore'])], cliquer=[['data-plus-tard', 'r00000000000a']])
        self.assertIn('>Plus tard</button>', r['tableauAvant'])
        self.assertNotIn('Q7 · Format', r['tableau'])
        self.assertEqual([a for a in r['appels'] if a[0] == 'clore'], [['clore', {'cle': 'r00000000000a', 'plus_tard': True}]])
        self.assertFalse([a for a in r['appels'] if a[0] == 'repondre'])
        demain = maintenant_ms() + JOUR
        self.assertNotIn('Q7 · Format', run_page(lignes=[ligne()], plus_tard={'r00000000000a': demain})['tableau'])
        self.assertIn('Q7 · Format', run_page(lignes=[ligne()], plus_tard={'r00000000000a': maintenant_ms() - 1000})['tableau'])

    def test_every_open_button_has_one_style(self):
        r = run_page(lignes=[ligne(type='go', choix=['go', 'pas encore']), ligne(retrait='r00000000000b', question='Q8',
                                                                                affiche_titre='Q8 · Autre', type='review')])['tableau']
        self.assertNotIn('class="act k-go"', r)
        self.assertNotIn('class="act k-review"', r)
        self.assertEqual(r.count('Ouvrir ↗'), r.count('class="act k-task ouvrir'))


@unittest.skipUnless(shutil.which('node'), 'node absent')
class OldLines(unittest.TestCase):
    def test_21_days_without_movement_waits_and_a_project_retires_at_once(self):
        vieille = ligne(depuis=maintenant_ms() - 22 * JOUR, impact='fort')
        r = run_page(lignes=[vieille, ligne(retrait='r00000000000b', question='Q8', affiche_titre='Q8 · Récente')])
        self.assertNotIn('Q7 · Format', r['tableau'])
        self.assertIn('Q7 · Format', r['attendre'])
        self.assertIn('data-retirer-groupe="r00000000000a"', r['attendre'])
        self.assertIn('Tout retirer pour ce projet', r['attendre'])
        r = run_page(lignes=[vieille], cliquer=[['data-retirer-groupe', 'r00000000000a']])
        self.assertIn('data-annuler-groupe="r00000000000a"', r['attendre'])

    def test_a_session_stopped_for_two_days_can_be_abandoned(self):
        arretee = ligne(arret='interrupted', depuis=maintenant_ms() - 3 * JOUR, cle=SID)
        r = run_page(lignes=[arretee], cliquer=[['data-abandonner', 'r00000000000a']])
        self.assertIn('>Abandonner</button>', r['tableauAvant'])
        self.assertNotIn('Fait / Retirer du tableau', r['tableauAvant'])
        self.assertIn('la session sera archivée', r['tableau'])
        self.assertNotIn('Abandonner', run_page(lignes=[ligne(arret='interrupted', cle=SID)])['tableau'])

    def test_the_old_lines_count_without_those_already_retired(self):
        r = run_page(lignes=[ligne()], anciennes=[ligne(retrait='r00000000000b'), ligne(retrait='r00000000000c', question='Q9')],
                     plus_tard={'r00000000000b': maintenant_ms() + JOUR})
        self.assertNotIn('r00000000000b', r['anciennes'])


class Relays(unittest.TestCase):
    def lignes(self, suite):
        return [{'cle': 'local_a', 'session': 'Alpha · Cadrage', 'affiche_titre': 'Q2 · Date de recette', 'affiche_suite': suite,
                 'question': 'Q2'},
                {'cle': 'local_b', 'session': 'Alpha · Recette', 'affiche_titre': 'Q4 · Date de recette planifiée côté client',
                 'affiche_suite': 'je propose : le 20/11', 'question': 'Q4'}]

    def test_a_sure_relay_is_hidden(self):
        r = parc.dedoublonner_relais(self.lignes('date de recette planifiée côté client : réponds dans « Alpha · Recette »'))
        self.assertEqual([x['cle'] for x in r], ['local_b'])

    def test_an_unsure_relay_says_where_else(self):
        r = parc.dedoublonner_relais(self.lignes('réponds dans « Alpha · Recette »'))
        self.assertEqual([(x['cle'], x.get('aussi_dans')) for x in r], [('local_a', 'Alpha · Recette'), ('local_b', None)])

    def test_no_line_in_the_named_session_keeps_the_relay(self):
        r = parc.dedoublonner_relais(self.lignes('réponds dans « Beta · Kick-off »'))
        self.assertEqual(len(r), 2)
        self.assertFalse(any(x.get('aussi_dans') for x in r))


class ThirdParties(unittest.TestCase):
    def test_a_received_wait_leaves_and_a_board_line_wins(self):
        saved = parc.INTERNE
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parc.INTERNE = pathlib.Path(tmp.name)
        self.addCleanup(setattr, parc, 'INTERNE', saved)
        ev = [{'type': 'blocked', 'text': 'Contrat signé à verser au dossier', 'sessionId': SID, 'session': 'Alpha',
               'at': time.strftime('%Y-%m-%dT%H:%M:%S')},
              {'type': 'blocked', 'text': 'Accès au serveur de recette', 'sessionId': SID, 'session': 'Alpha',
               'at': time.strftime('%Y-%m-%dT%H:%M:%S')}]
        t = parc.attentes_de_tiers(ev, time.time())
        self.assertEqual(len(t), 2)
        self.assertTrue(all(x['cle'].startswith('t') and len(x['cle']) == 13 for x in t))
        lignes = [{'affiche_titre': 'PDF signé du contrat', 'affiche_suite': 'le demander pour le verser au dossier signé'}]
        self.assertEqual([x['texte'] for x in parc.sans_doublon_du_tableau(t, lignes)], ['Accès au serveur de recette'])
        (parc.INTERNE / parc.TIERS_RECUS).write_text(json.dumps({t[1]['cle']: time.time()}), encoding='utf-8')
        self.assertEqual(len(parc.attentes_de_tiers(ev, time.time())), 1)

    def test_working_days(self):
        lundi = time.mktime((2026, 11, 16, 10, 0, 0, 0, 0, -1))
        self.assertEqual(parc.jours_ouvres_entre(lundi - 3 * 86400, lundi), 1)   # Friday to Monday
        self.assertEqual(parc.jours_ouvres_entre(lundi, lundi + 2 * 86400), 2)


class Connector(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.m = charger('mcp_reste', 'mcp_mon_studio.py')
        self.m.charger_parc()
        saved = self.m.parc.INTERNE
        self.m.parc.INTERNE = pathlib.Path(tmp.name)
        self.addCleanup(setattr, self.m.parc, 'INTERNE', saved)

    def test_plus_tard_lasts_until_tomorrow(self):
        r = self.m.clore({'cle': 'r0123456789ab', 'plus_tard': True})
        self.assertEqual(r['plus_tard'], 'r0123456789ab')
        self.assertGreater(r['jusqua'], time.time() * 1000)
        self.assertLessEqual(r['jusqua'], (time.time() + 86400) * 1000)
        self.assertIn('r0123456789ab', self.m.plus_tard_actifs())
        self.assertNotIn('r0123456789ab', self.m.plus_tard_actifs(time.time() + 2 * 86400))
        with self.assertRaises(ValueError):
            self.m.clore({'cle': 'rien', 'plus_tard': True})

    def test_received_and_abandoned(self):
        self.assertEqual(self.m.clore({'cle': 't0123456789ab'}), {'recu': 't0123456789ab'})
        self.assertIn('t0123456789ab', self.m.parc.tiers_recus())
        stoppee = 'local_00000000-0000-0000-0000-0000000000f1'
        ligne_ = {'retrait': 'r0123456789ac', 'cle': stoppee, 'affiche_suite': 'Session arrêtée', 'session': 'Alpha · Essai'}
        self.m._retirables.update(t=time.time(), lignes={'r0123456789ac': self.m.a_prevenir(ligne_)})
        self.assertEqual(self.m.clore({'cle': 'r0123456789ac', 'abandon': True}), {'retiree': 'r0123456789ac', 'abandon': True})
        a = json.loads((self.m.parc.INTERNE / self.m.ABANDONNEES).read_text(encoding='utf-8'))
        self.assertEqual(a[stoppee]['titre'], 'Alpha · Essai')


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Today(unittest.TestCase):
    MATIN = {'etat': 'ok', 'jour': 'normale', 'agenda': [{'heure': '10:00', 'titre': 'Point hebdo', 'projet': 'Alpha'}],
             'a_traiter': [], 'regle': [], 'preparer_demain': [], 'brouillons': [], 'entre_studio': [],
             'demandes': [{'cle': 'aaaaaaaaaaa1', 'titre': 'Envoyer le devis', 'projet': 'Alpha'}],
             'sans_reponse': [{'cle': 't0123456789ab', 'titre': 'Accès au serveur de recette', 'projet': 'Alpha',
                               'session': SID, 'depuis': 0}]}

    def test_the_morning_stand_up(self):
        r = run_page(lignes=[ligne(), ligne(retrait='r00000000000b', question='Q8', affiche_titre='Q8 · Autre')], matin=self.MATIN)
        m = r['matin']
        self.assertNotIn('nouvelle', m)
        self.assertIn('2 questions ouvertes', m)
        self.assertIn('<h3>Sans réponse</h3>', m)
        self.assertIn('data-retirer="t0123456789ab"', m)
        self.assertIn('>Reçu</button>', m)

    def test_an_entry_the_pm_wrote_is_not_news(self):
        self.assertTrue(projets.ecrite_par('Mail · Camille Martin', 'Camille Martin'))
        self.assertTrue(projets.ecrite_par('Slack #alpha · Camille', 'Camille Martin'))
        self.assertFalse(projets.ecrite_par('Mail · Dominique Petit', 'Camille Martin'))
        self.assertFalse(projets.ecrite_par('Mail · Camille Martin, Dominique Petit', 'Camille Martin'))
        self.assertFalse(projets.ecrite_par('Drive', 'Camille Martin'))


@unittest.skipUnless(shutil.which('node'), 'node absent')
class ClientProjects(unittest.TestCase):
    def test_sans_action_is_folded_to_client_projects(self):
        studios = [{'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm'}, {'nom': 'Studio de test', 'dossier': '/S/Test', 'role': 'membre'}]
        sans = [{'studio': n, 'titre': 'S', 'sessionId': SID, 'derniere': time.time() * 1000, 'etat': ''}
                for n in ('Alpha', 'Studio de test', 'outillage')]
        r = run_page(lignes=[ligne()], sans_action=sans, liste_projets={'genere': 0, 'page': None, 'studios': studios, 'projets': []})
        self.assertIn('Alpha', r['sans'])
        self.assertNotIn('Studio de test', r['sans'])
        self.assertNotIn('outillage', r['sans'])


if __name__ == '__main__':
    unittest.main()
