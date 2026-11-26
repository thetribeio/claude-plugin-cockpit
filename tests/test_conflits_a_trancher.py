"""The Conflits tab lists each conflict once, under « À trancher » (PM, Q21, 2026-11-24): python3 -m unittest discover -s tests

The tab showed the same conflict twice: as the question the conflicts session was asking (« En cours ») and as the
register's open case (« Dans le registre du Studio »). A question that is about an open case now marks that case
(`posee`, « posé maintenant », its answer button); the others stay under « Questions de la session ». Matching is
by words, without LLM: the case's subject inside the question, or at least 4 significant words shared with the case's
subject, old and new values. Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import unittest

import test_conflits_en_cours as T

CONFLITS = T.CONFLITS

REGISTRE = """# Registre des conflits

Dernier passage : 10/11/2026

### C1 · Mise à jour du poste : clé USB ou à distance seulement
- **Détecté le** : 23/11/2026
- **Ancienne valeur** : mise à jour sur place par clé USB, une fois par trimestre (source : projet/regles-metier.md, 02/09/2026)
- **Nouvelle valeur** : la mise à jour se fera uniquement à distance, sans déplacement (source : sources/2026-11-23-mail.md, 23/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : ouvert

### C2 · Plafond de remise
- **Détecté le** : 23/11/2026
- **Ancienne valeur** : remise limitée à dix pour cent des commandes en ligne (source : projet/regles-metier.md, 15/09/2026)
- **Nouvelle valeur** : remise portée à quinze pour cent des commandes de plus de cinquante pièces (source : sources/2026-11-03-cr.md, 03/11/2026)
- **Déjà communiqué au client** : oui
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : ouvert
"""

QUESTION_USB = ("Le 23/11 à 12:33, Ana proposait une mise à jour sur place par clé USB. Léo écrit que la mise à jour se fera "
                "uniquement à distance. À trancher dans la session « Alpha · Conflits Studio »")


class Appariement(T.Base):
    def setUp(self):
        super().setUp()
        self.ecrire('projet/conflits.md', REGISTRE)
        self.metas0 = self.metas()
        self.metas0.append({'id': CONFLITS, 'titre': 'Alpha · Conflits Studio', 'cwd': self.d, 'archivee': False,
                            'activite': self.maintenant - 60})

    def onglet2(self, *textes):
        lignes = [self.ligne(CONFLITS, t) for t in textes]
        for i, l in enumerate(lignes):
            l['cle'] = 'q-%d' % i
        return self.p.conflits_du_projet(self.d, self.metas0, questions=lignes, maintenant=self.maintenant)

    def test_the_question_about_a_case_marks_that_case_and_is_not_listed_twice(self):
        c = self.onglet2(QUESTION_USB)
        usb = next(x for x in c['ouverts'] if x['id'] == 'C1')
        self.assertEqual(usb['posee']['session'], CONFLITS)
        self.assertEqual(usb['posee']['session_titre'], 'Alpha · Conflits Studio')
        self.assertEqual(usb['posee']['depuis'], self.maintenant - 300)
        self.assertNotIn('posee', next(x for x in c['ouverts'] if x['id'] == 'C2'))
        self.assertEqual(c['questions_session'], [])
        self.assertEqual(c['en_cours'], c['questions_session'])

    def test_a_case_s_subject_inside_the_question_is_enough(self):
        c = self.onglet2('Plafond de remise : on garde laquelle des deux ?')
        self.assertEqual([x['id'] for x in c['ouverts'] if x.get('posee')], ['C2'])

    def test_three_shared_words_are_not_enough_four_are(self):
        # « poste », « distance », « uniquement » shared with C1: 3 words. A fourth (« trimestre ») makes the match.
        trois = 'Le poste de Sam passe à distance, uniquement par mail ?'
        self.assertEqual(self.onglet2(trois)['questions_session'][0]['question'], trois)
        quatre = trois + ' Pas de passage tous les trimestres ?'
        c = self.onglet2(quatre)
        self.assertEqual([x['id'] for x in c['ouverts'] if x.get('posee')], ['C1'])

    def test_the_words_every_question_carries_do_not_match(self):
        q = 'À trancher dans la session « Alpha · Conflits Studio » : ancienne valeur ou nouvelle valeur, Camille ?'
        c = self.onglet2(q)
        self.assertEqual([x for x in c['ouverts'] if x.get('posee')], [])
        self.assertEqual(len(c['questions_session']), 1)

    def test_two_questions_never_take_the_same_case(self):
        autre = 'Mise à jour du poste : clé USB ou à distance seulement, que répond Robin ?'
        c = self.onglet2(QUESTION_USB, autre)
        self.assertEqual([x['id'] for x in c['ouverts'] if x.get('posee')], ['C1'])
        self.assertEqual(len(c['questions_session']), 1)     # the one that did not take C1 stays a question
        self.assertEqual(c['ouverts'][0]['posee']['session'], CONFLITS)

    def test_the_best_score_takes_the_case(self):
        # The subject of C1 inside the 2nd question (score 1000+) beats the 4 shared words of the first.
        faible = 'Sam propose la mise à jour sur place par clé USB, Léo la mise à jour uniquement à distance'
        fort = 'Mise à jour du poste : clé USB ou à distance seulement ?'
        c = self.onglet2(faible, fort)
        self.assertEqual([x['question'] for x in c['questions_session']], [faible])

    def test_a_question_with_no_case_stays_unmatched_and_is_counted(self):
        c = self.onglet2('Couleur du bouton de la page d’accueil : bleu ou vert ?')
        self.assertEqual(len(c['questions_session']), 1)
        self.assertTrue(c['questions_session'][0]['compte'])
        self.assertEqual([x for x in c['ouverts'] if x.get('posee')], [])

    def test_a_numbered_steering_question_stays_apart_and_is_not_counted(self):
        c = self.onglet2('Q29 · Alpha · Conflits Studio : Lancer la passe conflits depuis le 10/11')
        self.assertEqual(len(c['questions_session']), 1)
        self.assertFalse(c['questions_session'][0]['compte'])


class Page(unittest.TestCase):
    A = T.Page.A
    run_page = T.Page.run_page
    SESSION = {'session': CONFLITS, 'session_titre': 'Alpha · Conflits Studio', 'depuis': 1}

    def cas(self, **k):
        c = {'id': 'C1', 'sujet': 'Mise à jour du poste : clé USB ou à distance seulement', 'nouveau': False,
             'ancienne': {'texte': 'mise à jour sur place par clé USB', 'source': 'regles', 'date': '02/09/2026'},
             'nouvelle': {'texte': 'mise à jour uniquement à distance', 'source': 'mail', 'date': '23/11/2026'},
             'communique': False, 'detecte': '23/11/2026', 'niveau': 'arbitrage'}
        c.update(k)
        return c

    def q(self, texte, compte=True):
        return {'question': texte, 'options': 'oui · non', 'session': CONFLITS, 'session_titre': 'Alpha · Conflits Studio',
                'depuis': 1, 'compte': compte}

    def test_the_case_a_session_asks_shows_once_marked_with_its_button(self):
        sortie = self.run_page(ouverts=[self.cas(posee=self.SESSION)], questions_session=[], en_cours=[])
        html = sortie['projetConflits']
        self.assertEqual(html.count('Mise à jour du poste'), 1)
        self.assertIn('<h3>À trancher</h3>', html)
        self.assertIn('posé maintenant', html)
        self.assertIn('data-sid="' + CONFLITS + '"', html)
        self.assertIn('Répondre dans « Alpha · Conflits Studio » ↗', html)
        self.assertNotIn('Questions de la session', html)
        for vieux in ('<h3>En cours</h3>', 'Dans le registre du Studio'):
            self.assertNotIn(vieux, html)
        self.assertIn('1 conflit à trancher', html)

    def test_a_case_nobody_asks_has_no_marker_and_no_button(self):
        html = self.run_page(ouverts=[self.cas()])['projetConflits']
        self.assertIn('<h3>À trancher</h3>', html)
        self.assertNotIn('posé maintenant', html)
        self.assertNotIn('Répondre dans', html)

    def test_the_unmatched_questions_come_after_under_their_own_heading(self):
        q29 = self.q('Q29 · Alpha · Conflits Studio : Lancer la passe conflits depuis le 10/11', compte=False)
        sortie = self.run_page(ouverts=[self.cas()], questions_session=[q29], en_cours=[q29])
        html = sortie['projetConflits']
        self.assertLess(html.index('<h3>À trancher</h3>'), html.index('<h3>Questions de la session</h3>'))
        self.assertIn('<strong>Q29 · Alpha · Conflits Studio : Lancer la passe conflits depuis le 10/11</strong>', html)
        self.assertIn('1 conflit à trancher · 1 question de la session', html)

    def test_a_steering_question_alone_is_shown_but_the_tab_counts_nothing(self):
        q29 = self.q('Q29 · Alpha · Conflits Studio : Lancer la passe', compte=False)
        sortie = self.run_page(questions_session=[q29], en_cours=[q29])
        self.assertIn('Questions de la session', sortie['projetConflits'])
        self.assertNotIn('conflit ouvert', json.dumps(sortie, ensure_ascii=False))

    def test_a_question_with_no_case_is_counted_with_the_cases(self):
        sortie = self.run_page(ouverts=[self.cas()], questions_session=[self.q('Couleur du bouton ?')])
        self.assertIn('2 conflits ouverts', json.dumps(sortie, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
