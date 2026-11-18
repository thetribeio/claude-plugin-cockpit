"""Tests: Slack lines the PM answered in their thread leave the board (PM, Q6 and Q8, 2026-11-17):
python3 -m unittest discover -s tests

The ingestion kit closes a request only at its « Réglé sur preuve » step, which did not close answered Slack questions.
The midday check of the morning point now reads each open Slack line's thread and gives its judgment:
  - slack_ouvertes lists the open « À toi » lines that link to Slack, with the thread to read (channel, parent ts);
  - slack_juger « reglee » closes a line (par: slack, the PM's reply as proof); « ouverte » keeps it; a `suite` the
    reply announces becomes a line of its own; a summary replaces the message on the board (never the message itself);
  - an invalid judgment is set aside, the others go through; a line that is not an open Slack line is never touched;
  - the verification task's instructions carry the step, read-only on Slack, and its two tools are allowed.

Studios and links are synthetic; the real ~/Mon Studio is never read."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_cockpit_projets import Base, MONDAY, FRIDAY   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSIGNE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin-verif.md'
INSTALL = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py'
CONNECTOR = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'

ASK1 = 'https://exemple.slack.com/archives/C0ABC123/p1793900000000100'
ASK2 = 'https://exemple.slack.com/archives/C0ABC123/p1793900000000300?thread_ts=1793900000.000200&cid=C0ABC123'
REPLY = 'https://exemple.slack.com/archives/C0ABC123/p1793990000000100'
REPORT = ("📬 Alpha · 2 actions pour toi\nÀ toi de jouer :\n"
          f"- Ana te demande si on exporte aussi en CSV ([Message Slack]({ASK1}))\n"
          f"- Ana te demande de confirmer le type de pose ([Message Slack]({ASK2}))\n"
          "- Valider le **devis** avant jeudi.\n")


class SlackAnswered(Base):
    def setUp(self):
        super().setUp()
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute(MONDAY)

    def a_toi(self, when=MONDAY):
        b = self.block(self.compute(when))
        return [l for l in (b['lignes'] if b else []) if l['type'] == 'a_toi']

    def open_slack(self):
        return {x['demande'][:40]: x for x in self.p.slack_ouvertes()}

    def test_lists_open_slack_lines_with_the_thread_to_read(self):
        o = self.p.slack_ouvertes()
        self.assertEqual(len(o), 2, 'the request without a Slack link is not listed')
        first = next(x for x in o if x['lien'] == ASK1)
        self.assertEqual((first['channel_id'], first['message_ts'], first['demande_ts']),
                         ('C0ABC123', '1793900000.000100', '1793900000.000100'))
        reply_in_thread = next(x for x in o if x['lien'] == ASK2)
        self.assertEqual(reply_in_thread['message_ts'], '1793900000.000200', 'the parent of the thread is read')
        self.assertEqual(reply_in_thread['demande_ts'], '1793900000.000300')
        self.assertEqual(first['projet'], 'Alpha')

    def test_answered_line_closes_unanswered_stays(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        r = self.p.slack_juger([
            {'cle': o[ASK1], 'verdict': 'reglee', 'reponse': REPLY, 'resume': 'Dire à Ana si on exporte aussi en CSV', 'qui': 'Ana'},
            {'cle': o[ASK2], 'verdict': 'ouverte', 'resume': 'Confirmer à Ana le type de pose', 'qui': 'Ana'}],
            maintenant=MONDAY + 60)
        self.assertEqual((r['fermees'], r['suites'], r['ecartes']), (1, 0, []))
        titles = [l['titre'] for l in self.a_toi(MONDAY + 120)]
        self.assertNotIn('Dire à Ana si on exporte aussi en CSV', titles)
        self.assertTrue(all('CSV' not in t for t in titles), titles)
        self.assertIn('Confirmer à Ana le type de pose', titles)
        etat = self.p.lire_etat()[o[ASK1]]
        self.assertEqual((etat['par'], etat['preuve']), ('slack', REPLY))
        self.assertEqual([x['lien'] for x in self.p.slack_ouvertes()], [ASK2])

    def test_summary_replaces_the_message_on_the_board(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        self.p.slack_juger([{'cle': o[ASK2], 'verdict': 'ouverte', 'resume': 'Confirmer à Ana le type de pose', 'qui': 'Ana'}])
        line = next(l for l in self.a_toi(MONDAY + 120) if l['cle'] == o[ASK2])
        self.assertEqual((line['titre'], line['texte'], line['auteur']), ('Confirmer à Ana le type de pose',) * 2 + ('Ana',))

    def test_a_suite_becomes_its_own_line(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        r = self.p.slack_juger([{'cle': o[ASK1], 'verdict': 'reglee', 'reponse': REPLY,
                                 'suite': 'Poser au client la question du format CSV'}], maintenant=MONDAY + 60)
        self.assertEqual((r['fermees'], r['suites']), (1, 1))
        lines = self.a_toi(MONDAY + 120)
        suite = next(l for l in lines if l['titre'] == 'Poser au client la question du format CSV')
        self.assertEqual((suite['lien'], suite['auteur']), (REPLY, 'Toi'))
        self.assertIn(REPLY, [x['lien'] for x in self.p.slack_ouvertes()], 'the suite is checked in its turn')

    def test_a_suite_is_not_closed_by_the_message_that_created_it(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        self.p.slack_juger([{'cle': o[ASK1], 'verdict': 'reglee', 'reponse': REPLY,
                             'suite': 'Poser au client la question du format CSV'}], maintenant=MONDAY + 60)
        suite = next(x['cle'] for x in self.p.slack_ouvertes() if x['lien'] == REPLY)
        r = self.p.slack_juger([{'cle': suite, 'verdict': 'reglee', 'reponse': REPLY}], maintenant=MONDAY + 120)
        self.assertEqual((r['fermees'], [e['cle'] for e in r['ecartes']]), (0, [suite]))
        self.assertIn(REPLY, [x['lien'] for x in self.p.slack_ouvertes()], 'the suite stays open')
        later = 'https://exemple.slack.com/archives/C0ABC123/p1793995000000100'
        r = self.p.slack_juger([{'cle': suite, 'verdict': 'reglee', 'reponse': later}], maintenant=MONDAY + 180)
        self.assertEqual(r['fermees'], 1, 'a later message of the PM still closes it')

    def test_the_instructions_keep_a_promise_open(self):
        text = CONSIGNE.read_text(encoding='utf-8')
        self.assertIn("Une promesse, un report ou une attente", text)
        self.assertIn("n'est pas un geste fait : elle ne ferme jamais une ligne seule", text)
        self.assertIn("ce n'est jamais le `lien` de la ligne ni son message parent", text)

    def test_invalid_judgments_are_set_aside(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        devis = next(l['cle'] for l in self.a_toi() if 'devis' in l['titre'])
        r = self.p.slack_juger([{'cle': devis, 'verdict': 'reglee', 'reponse': REPLY},
                                {'cle': o[ASK1], 'verdict': 'reglee'},
                                {'cle': o[ASK2], 'verdict': 'peut-etre'},
                                {'cle': 'zz', 'verdict': 'reglee', 'reponse': REPLY}, 'pas un objet'])
        self.assertEqual(r['fermees'], 0)
        self.assertEqual(len(r['ecartes']), 5)
        self.assertEqual(len(self.p.slack_ouvertes()), 2)
        self.assertIn(devis, [l['cle'] for l in self.a_toi()], 'a line without a Slack link is never closed here')
        with self.assertRaises(ValueError):
            self.p.slack_juger('pas une liste')

    def test_closed_line_is_not_judged_twice(self):
        o = {x['lien']: x['cle'] for x in self.p.slack_ouvertes()}
        self.p.slack_juger([{'cle': o[ASK1], 'verdict': 'reglee', 'reponse': REPLY}])
        r = self.p.slack_juger([{'cle': o[ASK1], 'verdict': 'reglee', 'reponse': REPLY}])
        self.assertEqual((r['fermees'], len(r['ecartes'])), (0, 1))

    def test_fil_slack_rejects_other_links(self):
        for lien in ('', 'https://mail.google.com/x', 'https://exemple.slack.com/archives/C0ABC/p1', None):
            self.assertIsNone(self.p.fil_slack(lien))


class Wiring(unittest.TestCase):
    def test_check_task_closes_slack_lines_read_only(self):
        c = CONSIGNE.read_text(encoding='utf-8')
        for word in ('`slack_ouvertes`', '`slack_read_thread`', '`slack_search_public_and_private`', '`slack_juger`', '`reglee`', '`ouverte`', '`suite`',
                     'Tu t\'es engagé le 12/11', 'sans recopier le message ni le fil', 'sans message du PM', 'même s\'il n\'y a pas de point'):
            self.assertIn(word, c)
        self.assertIn("Tu n'envoies rien", c)
        self.assertNotIn('slack_send', c)

    def test_tools_declared_dispatched_and_allowed(self):
        m = CONNECTOR.read_text(encoding='utf-8')
        for name in ('slack_ouvertes', 'slack_juger'):
            self.assertIn(f"'name': '{name}'", m)
            self.assertIn(f"nom == '{name}'", m)
            self.assertIn(f"'mcp__mon-studio__{name}'", INSTALL.read_text(encoding='utf-8'))

    def test_page_never_copies_a_slack_message_in_the_detail(self):
        p = PAGE.read_text(encoding='utf-8')
        i = p.index('function detailAToi')
        body = p[i:p.index('function detail(', i)]
        slack = body[body.index('slack\\.com'):body.index('if (l.texte')]
        self.assertNotIn('l.texte', slack)
        self.assertIn('Ouvrir le message', slack)

    def test_a_slack_request_has_no_open_session_button(self):
        # PM, Q11, 2026-11-17: « Ouvrir ↗ » opened the 📬 session at its start, useless; « Slack ↗ » stays.
        p = PAGE.read_text(encoding='utf-8')
        i = p.index('function demandes(')
        row = p[i:p.index('a_toi: true', i)]
        self.assertRegex(row, r'ouvrir: !l\.repli && l\.session && !/\^https:.*slack.*\.test\(l\.lien')


if __name__ == '__main__':
    unittest.main()
