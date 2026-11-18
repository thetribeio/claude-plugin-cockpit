"""Tests: the proof of a Slack closure must be a message later than the request (2026-11-18):
python3 -m unittest discover -s tests

Measured on real data: 3 closures out of 8 were wrong, the proof being the request itself, and a « suite » line was
closed with the very message that created it. slack_juger now sets aside a « reglee » judgment whose proof is the
request, the parent of its thread, or an earlier message: the line stays open, with the reason in `ecartes`.

Studios and links are synthetic; the real ~/Mon Studio is never read."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_cockpit_projets import Base, MONDAY, FRIDAY   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSIGNE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin-verif.md'

ASK1 = 'https://exemple.slack.com/archives/C0TEST/p1794000000000100'
ASK2 = 'https://exemple.slack.com/archives/C0TEST/p1794000000000300?thread_ts=1794000000.000200&cid=C0TEST'
PARENT = 'https://exemple.slack.com/archives/C0TEST/p1794000000000200'
EARLIER = 'https://exemple.slack.com/archives/C0TEST/p1793999999000100'
LATER = 'https://exemple.slack.com/archives/C0TEST/p1794000900000100'
LATER_IN_THREAD = 'https://exemple.slack.com/archives/C0TEST/p1794000900000200?thread_ts=1794000000.000200'
REPORT = ("📬 Alpha · 2 actions pour toi\nÀ toi de jouer :\n"
          f"- Ana te demande si on exporte aussi en CSV ([Message Slack]({ASK1}))\n"
          f"- Léo te demande de confirmer le type de pose ([Message Slack]({ASK2}))\n")


class SlackPreuve(Base):
    def setUp(self):
        super().setUp()
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute(MONDAY)
        self.cles = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}

    def juger(self, lien, reponse, **kw):
        return self.p.slack_juger([{'cle': self.cles[lien], 'verdict': 'reglee', 'reponse': reponse, **kw}], maintenant=MONDAY + 60)

    def assert_refused(self, r, lien, raison):
        self.assertEqual((r['fermees'], r['suites']), (0, 0))
        self.assertEqual(r['ecartes'], [{'cle': self.cles[lien], 'raison': raison}])
        ligne = self.p.lire_etat()[self.cles[lien]]
        self.assertIsNone(ligne['fermee'])
        self.assertNotIn('preuve', ligne)
        self.assertIn(lien, [x['lien'] for x in self.p.slack_ouvertes()])

    def test_proof_equal_to_the_request_is_set_aside(self):
        self.assert_refused(self.juger(ASK1, ASK1, suite='Poser la question au client'), ASK1, 'preuve = la demande elle-même')
        self.assertFalse([k for k, l in self.p.lire_etat().items() if l.get('suite_de')], 'no suite is created')

    def test_proof_equal_to_the_request_in_another_form_is_set_aside(self):
        autre_forme = 'https://exemple.slack.com/archives/C0TEST/p1794000000000300'
        self.assert_refused(self.juger(ASK2, autre_forme), ASK2, 'preuve = la demande elle-même')

    def test_proof_equal_to_the_thread_parent_is_set_aside(self):
        self.assert_refused(self.juger(ASK2, PARENT), ASK2, 'preuve = le message parent du fil')

    def test_proof_earlier_than_the_request_is_set_aside(self):
        self.assert_refused(self.juger(ASK1, EARLIER), ASK1, 'preuve antérieure à la demande')
        self.assert_refused(self.juger(ASK2, EARLIER), ASK2, 'preuve antérieure à la demande')

    def test_refused_judgment_still_writes_summary_and_who(self):
        r = self.juger(ASK1, ASK1, resume='Dire à Ana si on exporte en CSV', qui='Ana')
        self.assertEqual((r['fermees'], r['resumes'], len(r['ecartes'])), (0, 1, 1))
        ligne = self.p.lire_etat()[self.cles[ASK1]]
        self.assertEqual((ligne['resume'], ligne['qui']), ('Dire à Ana si on exporte en CSV', 'Ana'))

    def test_suite_cannot_be_closed_by_the_message_that_created_it(self):
        r = self.juger(ASK1, LATER, suite='Poser au client la question du format CSV')
        self.assertEqual((r['fermees'], r['suites']), (1, 1))
        suite = next(x for x in self.p.slack_ouvertes() if x['lien'] == LATER)
        r2 = self.p.slack_juger([{'cle': suite['cle'], 'verdict': 'reglee', 'reponse': LATER}], maintenant=MONDAY + 120)
        self.assertEqual((r2['fermees'], r2['ecartes']), (0, [{'cle': suite['cle'], 'raison': 'preuve = la demande elle-même'}]))
        self.assertIsNone(self.p.lire_etat()[suite['cle']]['fermee'])

    def test_later_message_still_closes_the_suite(self):
        self.juger(ASK1, LATER, suite='Poser au client la question du format CSV')
        suite = next(x for x in self.p.slack_ouvertes() if x['lien'] == LATER)
        encore_apres = 'https://exemple.slack.com/archives/C0TEST/p1794001000000100'
        r = self.p.slack_juger([{'cle': suite['cle'], 'verdict': 'reglee', 'reponse': encore_apres}], maintenant=MONDAY + 120)
        self.assertEqual((r['fermees'], r['ecartes']), (1, []))

    def test_normal_case_unchanged(self):
        r = self.juger(ASK2, LATER, suite='Confirmer le type de pose à Léo')
        self.assertEqual((r['fermees'], r['suites'], r['ecartes']), (1, 1, []))
        ligne = self.p.lire_etat()[self.cles[ASK2]]
        self.assertEqual((ligne['par'], ligne['preuve']), ('slack', LATER))
        r = self.juger(ASK1, LATER)
        self.assertEqual((r['fermees'], r['suites'], r['ecartes']), (1, 0, []))

    def test_reply_in_thread_proof_link_closes_the_line(self):
        r = self.juger(ASK2, LATER_IN_THREAD)
        self.assertEqual((r['fermees'], r['ecartes']), (1, []))
        self.assertEqual(self.p.lire_etat()[self.cles[ASK2]]['preuve'], LATER_IN_THREAD)


class Instructions(unittest.TestCase):
    def test_consigne_asks_for_the_reply_own_link_and_no_promise_closure(self):
        c = CONSIGNE.read_text(encoding='utf-8')
        for word in ('?thread_ts=<message_ts>', 'jamais le `lien` de la ligne', "n'est pas un geste fait", "ne ferme qu'avec sa `suite`"):
            self.assertIn(word, c)
        self.assertNotIn('le lien de la recherche ou du fil tel quel', c)


if __name__ == '__main__':
    unittest.main()
