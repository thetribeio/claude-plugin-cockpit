"""Tests: one sort everywhere, Mon Studio, the project view, the morning point (PM, Q5 to Q8, 2026-11-25/26).

Measured on 2026-11-25: « D'abord » held 8 lines, 7 of them requests of the ingestion aged 1 h to 5 days, in the order they
came in; « Ensuite » held 25 lines of less than 24 h.
Q5  « Prénom attend/demande » makes a request of the ingestion « fort » for 7 days after it appeared, then it goes to
    « Ensuite » and says « Prénom attend depuis N j ». « Une session attend » makes a line « fort » for 24 h only.
Q6  « D'abord »: scheduled passes stopped first; then the late lines (oldest due date first); then the due dates (nearest
    first); then the other strong lines, the most recent first. A due date of unknown origin counts, and says so.
Q7  The project view shows the board's band titles (a band with no line has none), « Peut attendre » folded.
Q8  The lists of the morning point: close due date first, then the most recent; projects by urgence then recency.
People, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import shutil
import time
import unittest

from test_cockpit_impact_effort import DAY, NOW, demande, ligne, parc, report, run_page
from test_cockpit_projets import Base, MONDAY, local

HEURE = 3600
ASK = 'Léo attend la validation du mode clair'


def il_y_a(secondes):
    return int((NOW - secondes) * 1000)


def raison_echeance(decalage):
    """What parc.priorite writes for a close due date: « échéance JJ/MM »."""
    return 'échéance ' + (dt.date.today() + dt.timedelta(days=decalage)).strftime('%d/%m')


def jour(decalage):
    return (dt.date.today() + dt.timedelta(days=decalage)).isoformat()


class PrenomAttendSevenDays(unittest.TestCase):
    def p(self, texte, age=None, **plus):
        return parc.priorite(texte, NOW, demande=True, depuis=None if age is None else NOW - age, **plus)

    def test_before_the_seventh_day_the_line_is_strong(self):
        for age in (HEURE, 5 * DAY, 7 * DAY - 60):
            self.assertEqual(self.p(ASK, age), {'impact': 'fort', 'raison': 'Léo attend', 'effort': ''}, age)
        self.assertEqual(self.p('Ana te demande un accès', 6 * DAY)['raison'], 'Ana attend')

    def test_from_the_seventh_day_it_is_normal_and_names_who_waits(self):
        for age in (7 * DAY, 8 * DAY, 20 * DAY):
            self.assertEqual(self.p(ASK, age), {'impact': 'normal', 'raison': '', 'effort': '', 'attend_nom': 'Léo'}, age)
        self.assertEqual(self.p('Ana te demande un accès', 9 * DAY)['attend_nom'], 'Ana')

    def test_an_age_that_is_not_known_changes_nothing(self):
        self.assertEqual(self.p(ASK)['impact'], 'fort')
        self.assertEqual(parc.priorite(ASK, NOW, demande=True)['impact'], 'fort')

    def test_what_else_makes_it_strong_still_does(self):
        # Late, or a word that says so: the age of the wait does not hide it.
        self.assertEqual(self.p(ASK, 9 * DAY, echeance=NOW - DAY)['raison'], 'en retard')
        self.assertEqual(self.p('Léo attend, c’est urgent', 9 * DAY)['raison'], 'urgent')
        self.assertEqual(self.p(ASK, 9 * DAY, dit={'impact': 'fort', 'raison': 'client attend'})['raison'], 'client attend')


class SessionAttend24Hours(unittest.TestCase):
    def p(self, age=None):
        return parc.priorite('Q2 · Format du CR', NOW, bloque=True, depuis=None if age is None else NOW - age)

    def test_strong_for_24_hours(self):
        self.assertEqual(self.p(2 * HEURE), {'impact': 'fort', 'raison': 'une session attend', 'effort': ''})
        self.assertEqual(self.p(24 * HEURE - 60)['impact'], 'fort')

    def test_normal_after(self):
        self.assertEqual(self.p(24 * HEURE)['impact'], 'normal')
        self.assertEqual(self.p(30 * HEURE), {'impact': 'normal', 'raison': '', 'effort': ''})

    def test_the_rank_says_the_same(self):
        for age, rang in ((2 * HEURE, parc.RANG_ATTEND), (30 * HEURE, parc.RANG_OUVERTE)):
            self.assertEqual(parc.rang_urgence({'bloque': True, 'depuis': NOW - age}, NOW), (rang,))

    def test_an_age_that_is_not_known_changes_nothing(self):
        self.assertEqual(self.p()['impact'], 'fort')


class PrenomAttendThroughTheMorningPoint(Base):
    """The age is the one projets.py noted (`premiere`): the same rule from the file of the ingestion."""
    def lines(self, quand):
        return {l['titre']: l for l in self.block(self.compute(quand))['lignes']}

    def setUp(self):
        super().setUp()
        self.runs(self.alpha, (local(2026, 11, 2), report(ASK, 'Caler le point')))
        self.compute(local(2026, 11, 2))

    def test_day_5_strong_day_8_normal_and_named_not_folded_day_25_old(self):
        l = self.lines(local(2026, 11, 7))[ASK]
        self.assertEqual((l['impact'], l['raison'], l['ancienne'], l.get('attend_nom')), ('fort', 'Léo attend', False, None))
        l = self.lines(local(2026, 11, 10))[ASK]
        self.assertEqual((l['impact'], l['raison'], l['ancienne'], l['attend_nom']), ('normal', '', False, 'Léo'))
        # Without a wait named, the same age goes to « Anciennes », as before.
        self.assertTrue(self.lines(local(2026, 11, 10))['Caler le point']['ancienne'])
        # After 21 days it is old like the others.
        l = self.lines(local(2026, 11, 27))[ASK]
        self.assertEqual((l['impact'], l['ancienne']), ('normal', True))


def reponse(**entree):
    return run_page(lignes=entree.pop('lignes', []), liste_projets={'projets': [
        {'nom': 'Alpha', 'dossier': '/x/alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [],
         'lignes': entree.pop('demandes', [])}], 'studios': ['Alpha']}, **entree)


def place(html, *titres):
    return [html.find(t) for t in titres]


@unittest.skipUnless(shutil.which('node'), 'node absent')
class DabordOrder(unittest.TestCase):
    def donnees(self):
        fort = dict(impact='fort')
        demandes = [
            # Arrival order is the reverse of the new order, on purpose (the old order was the arrival order).
            demande('Attente ancienne de Léo', cle='1' * 12, depuis=il_y_a(5 * HEURE), raison='Léo attend', **fort),
            demande('Attente récente de Ana', cle='2' * 12, depuis=il_y_a(HEURE), raison='Ana attend', **fort),
            demande('Échéance lointaine', cle='3' * 12, echeance=jour(9), raison=raison_echeance(9), **fort),
            demande('Échéance proche', cle='4' * 12, echeance=jour(1), raison=raison_echeance(1), echeance_mode='lue', **fort),
            demande('Retard récent', cle='5' * 12, echeance=jour(-1), raison='en retard', echeance_mode='lue', **fort),
            demande('Retard ancien', cle='6' * 12, echeance=jour(-6), raison='en retard', echeance_mode='lue', **fort),
        ]
        lignes = [ligne('Blocage de session', impact='fort', raison='une session attend', depuis=il_y_a(2 * HEURE),
                        recente=il_y_a(2 * HEURE), bloque=True),
                  ligne('Passage arrêté', impact='fort', raison='arrêtée sur une erreur', en_tete=True, depuis=il_y_a(DAY),
                        recente=il_y_a(DAY), cle='local_00000000-0000-0000-0000-0000000000c9')]
        return demandes, lignes

    def test_the_order(self):
        demandes, lignes = self.donnees()
        t = reponse(demandes=demandes, lignes=lignes)['tableau']
        titres = ('Passage arrêté', 'Retard ancien', 'Retard récent', 'Échéance proche', 'Échéance lointaine',
                  'Attente récente de Ana', 'Blocage de session', 'Attente ancienne de Léo')
        places = place(t, *titres)
        self.assertNotIn(-1, places, places)
        self.assertEqual(places, sorted(places), titres)
        self.assertIn('D\'abord <span class="n">· 8</span>', t)

    def test_unknown_origin_counts_and_is_said_known_origin_is_not_marked(self):
        demandes, lignes = self.donnees()
        t = reponse(demandes=demandes, lignes=lignes)['tableau']
        loin = jour(9)[8:] + '/' + jour(9)[5:7]
        self.assertIn(f'<span class="raison">échéance {loin} · origine inconnue</span>', t)
        proche = jour(1)[8:] + '/' + jour(1)[5:7]
        self.assertIn(f'<span class="raison">échéance {proche}</span>', t)
        self.assertNotIn(f'échéance {proche} · origine', t)
        # A late line with an unknown origin says both.
        retard = reponse(demandes=[demande('Retard sans origine', echeance=jour(-3), impact='fort', raison='en retard')])['tableau']
        self.assertRegex(retard, r'<span class="raison">en retard · échéance \d\d/\d\d · origine inconnue</span>')

    def test_a_line_that_is_not_in_dabord_carries_no_origin_mark(self):
        t = reponse(demandes=[demande('Simple demande', echeance=jour(30))])['tableau']
        self.assertNotIn('origine inconnue', t.split('class="detail"')[0])

    def test_before_the_old_order_was_the_arrival_order(self):
        # The arrival order of the same lines (what the board did): this is not the order shown any more.
        demandes, lignes = self.donnees()
        arrivee = [d['titre'] for d in demandes]
        t = reponse(demandes=demandes, lignes=[])['tableau']
        places = place(t, *arrivee)
        self.assertNotEqual(places, sorted(places))

    def test_prenom_attend_leaves_dabord_after_seven_days_and_says_how_long(self):
        cinq = demande('Léo attend … mode clair (5 j)', cle='7' * 12, depuis=il_y_a(5 * DAY), impact='fort', raison='Léo attend')
        huit = demande('Léo attend … mode clair (8 j)', cle='8' * 12, depuis=il_y_a(8 * DAY), impact='normal',
                       attend_nom='Léo')
        t = reponse(demandes=[huit, cinq, demande('Autre demande', cle='9' * 12, impact='fort', raison='Ana attend')])['tableau']
        dabord, ensuite = t.split('Ensuite', 1)
        self.assertIn('(5 j)', dabord)
        self.assertNotIn('(8 j)', dabord)
        self.assertIn('(8 j)', ensuite)
        self.assertIn('<span class="raison court">Léo attend depuis 8 j</span>', ensuite)
        self.assertNotIn('attend depuis', dabord)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class ProjectViewBands(unittest.TestCase):
    VUE = {'nom': 'Alpha', 'questions': [], 'sujets': [], 'anciennes': [], 'journal': [], 'tiers': []}

    def vue(self, demandes, cliquer=None):
        entree = dict(outils=['lignes', 'projet'], projet=self.VUE, projetFixe='/x/alpha')
        if cliquer:
            entree['cliquer'] = cliquer
        return reponse(demandes=demandes, **entree)['projetQuestions']

    def test_the_three_titles_as_on_the_board_peut_attendre_folded(self):
        t = self.vue([demande('Urgente', cle='a' * 12, impact='fort', raison='Ana attend'),
                      demande('Ordinaire', cle='b' * 12), demande('Ordinaire bis', cle='c' * 12),
                      demande('Rangement', cle='d' * 12, impact='faible')])
        self.assertIn('D\'abord <span class="n">· 1</span>', t)
        self.assertIn('Ensuite <span class="n">· 2</span>', t)
        self.assertIn('id="projet-attendre-bascule" aria-expanded="false"', t)
        self.assertIn('Peut attendre', t)
        self.assertNotIn('Rangement', t, 'folded')
        places = place(t, "D'abord", 'Urgente', 'Ensuite', 'Ordinaire', 'Peut attendre')
        self.assertNotIn(-1, places)
        self.assertEqual(places, sorted(places))

    def test_peut_attendre_opens_on_a_click(self):
        t = self.vue([demande('Rangement', cle='d' * 12, impact='faible')], cliquer=[['projet-attendre-bascule', '1']])
        self.assertIn('aria-expanded="true"', t)
        self.assertIn('Rangement', t)

    def test_a_band_with_no_line_has_no_title(self):
        # Only ordinary lines: no title at all, nothing added for nothing (as on the board).
        t = self.vue([demande('Ordinaire', cle='b' * 12), demande('Autre', cle='c' * 12)])
        self.assertNotIn('bande-titre', t)
        self.assertNotIn('Peut attendre', t)
        # Strong lines only: « D'abord » alone.
        t = self.vue([demande('Urgente', cle='a' * 12, impact='fort', raison='Ana attend')])
        self.assertIn("D'abord", t)
        self.assertNotIn('Ensuite', t)
        self.assertNotIn('Peut attendre', t)

    def test_the_same_order_as_the_board(self):
        demandes, lignes = DabordOrder().donnees()
        t = self.vue(demandes)
        titres = ('Retard ancien', 'Retard récent', 'Échéance proche', 'Échéance lointaine', 'Attente récente de Ana',
                  'Attente ancienne de Léo')
        places = place(t, *titres)
        self.assertNotIn(-1, places, places)
        self.assertEqual(places, sorted(places))


class MorningLists(Base):
    """projets.py (the morning point): the order of the board, close due date then the most recent."""
    def setUp(self):
        super().setUp()
        self.beta = self.studio('Studio - Beta', pm='Éric  EXEMPLE')
        self.metas.append(self.card('local_00000000-0000-0000-0000-00000000bb01', self.beta, '📬 Beta', 90))

    def test_ordre_ligne(self):
        o = lambda **l: self.p.ordre_ligne(dict({'type': 'a_toi', 'depuis': 100}, **l), MONDAY)
        self.assertLess(o(echeance='2026-11-01'), o(echeance='2026-11-03'))   # late before close
        self.assertLess(o(echeance='2026-11-03'), o(depuis=500))               # close before recent
        self.assertLess(o(depuis=500), o(depuis=100))                          # the most recent first
        self.assertLess(o(echeance='2026-11-30', depuis=500), o(depuis=100, echeance='2026-12-30'))
        self.assertLess(o(echeance='2026-11-30', depuis=500)[0], o(type='entree', depuis=900)[0], 'an entry comes last')
        self.assertEqual(o(echeance='pas une date')[0], 1)

    def test_the_lines_of_a_project(self):
        self.runs(self.alpha, (local(2026, 10, 30, 10), report('Ancienne demande')),
                  (local(2026, 10, 30, 14), report('Récente demande', 'Échéance lointaine (échéance 2026-12-20)',
                                                   'Échéance proche (échéance 2026-11-03)')))
        titres = [l['titre'] for l in self.block(self.compute())['lignes']]
        self.assertEqual(titres[0], 'Échéance proche')
        self.assertLess(titres.index('Récente demande'), titres.index('Ancienne demande'), 'the most recent first')

    def test_the_new_requests_of_the_morning(self):
        self.runs(self.alpha, (local(2026, 10, 30, 10), report('Ancienne demande')),
                  (local(2026, 10, 30, 14), report('Récente demande', 'Échéance proche (échéance 2026-11-03)')))
        out = self.compute()
        _, demandes = self.p.ingestion_du_matin(out, MONDAY)
        titres = [d['titre'] for d in demandes]
        self.assertEqual(titres[0], 'Échéance proche')
        self.assertLess(titres.index('Récente demande'), titres.index('Ancienne demande'))

    def test_projects_by_urgence_then_recency_not_by_name(self):
        # Alpha (first by name) has only an old ordinary line; Beta a line with a close due date; Gamma a recent ordinary line.
        self.gamma = self.studio('Studio - Gamma', pm='Éric  EXEMPLE')
        self.metas.append(self.card('local_00000000-0000-0000-0000-00000000cc01', self.gamma, '📬 Gamma', 80))
        self.runs(self.alpha, (local(2026, 10, 30, 9), report('Vieille ordinaire')))
        self.runs(self.beta, (local(2026, 10, 30, 11), report('Échéance proche (échéance 2026-11-03)')))
        self.runs(self.gamma, (local(2026, 10, 30, 15), report('Récente ordinaire')))
        noms = [p['nom'] for p in self.compute()['projets']]
        self.assertEqual(noms, ['Beta', 'Gamma', 'Alpha'])


if __name__ == '__main__':
    unittest.main()
