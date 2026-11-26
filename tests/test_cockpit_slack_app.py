"""Tests: a Slack message opens straight in the desktop app (PM, Q14, 2026-11-17):
python3 -m unittest discover -s tests

The page's « Slack ↗ » no longer follows the web address (browser, then Slack's go-between page): it calls the
connector's « ouvrir » with « slack », which reads the workspace id (T…) in the Slack app's state (read only) and hands
macOS a slack://channel link. Without the app or the workspace, the web address opens in the browser, as before; a page
without the connector keeps the plain link. The state file and the links are synthetic; `open` is never really run."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from test_cockpit_permission_hook import Base, load_connector

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
MSG = 'https://exemple.slack.com/archives/C0ABC1234/p1793900000000100'
REPLY = 'https://exemple.slack.com/archives/C0ABC1234/p1793900000000300?thread_ts=1793900000.000200&cid=C0ABC1234'


class SlackApp(Base):
    def setUp(self):
        super().setUp()
        self.m = load_connector(self.mon_studio, self.root / 'app', self.root / 'tr')
        self.addCleanup(self.m.AUTORISATIONS.arreter)
        self.etat = pathlib.Path(tempfile.mkdtemp()) / 'root-state.json'
        self.etat.write_text(json.dumps({'workspaces': {
            'T0EXEMPLE1': {'domain': 'exemple', 'url': 'https://exemple.slack.com/', 'id': 'T0EXEMPLE1'},
            'T0AUTRE001': {'domain': 'autre', 'id': 'T0AUTRE001'}}}), encoding='utf-8')
        p = mock.patch.dict(os.environ, {'MON_STUDIO_SLACK_ETAT': str(self.etat)})
        p.start()
        self.addCleanup(p.stop)
        self.appels = []

        class R:
            def __init__(self, rc):
                self.returncode = rc

        def faux_open(cmd, **kw):
            self.appels.append(cmd)
            return R(self.rc.pop(0) if self.rc else 0)
        self.rc = []
        p = mock.patch.object(self.m.subprocess, 'run', faux_open)
        p.start()
        self.addCleanup(p.stop)

    def test_a_message_opens_in_the_app(self):
        self.assertEqual(self.m.ouvrir({'slack': MSG}), {'ouvert': 'app'})
        self.assertEqual(self.appels, [['open', 'slack://channel?team=T0EXEMPLE1&id=C0ABC1234&message=1793900000.000100']])

    def test_a_reply_keeps_its_thread(self):
        self.m.ouvrir({'slack': REPLY})
        self.assertEqual(self.appels[0][1], 'slack://channel?team=T0EXEMPLE1&id=C0ABC1234'
                                            '&message=1793900000.000300&thread_ts=1793900000.000200')

    def test_unknown_workspace_opens_the_web_address(self):
        url = MSG.replace('exemple', 'inconnu')
        self.assertEqual(self.m.ouvrir({'slack': url}), {'ouvert': 'navigateur'})
        self.assertEqual(self.appels, [['open', url]])

    def test_no_slack_app_opens_the_web_address(self):
        self.etat.unlink()
        self.assertEqual(self.m.ouvrir({'slack': MSG}), {'ouvert': 'navigateur'})
        self.assertEqual(self.appels, [['open', MSG]])

    def test_app_refusing_falls_back_to_the_browser(self):
        self.rc = [1, 0]
        self.assertEqual(self.m.ouvrir({'slack': MSG}), {'ouvert': 'navigateur'})
        self.assertEqual(self.appels[1], ['open', MSG])

    def test_only_a_slack_message_address_is_accepted(self):
        for bad in ('slack://channel?team=T1&id=C1', 'https://evil.com/archives/C0ABC1234/p1793900000000100',
                    'https://exemple.slack.com.evil.com/archives/C0ABC1234/p1793900000000100',
                    'file:///etc/passwd', MSG + '\nopen -a Calculator', 12):
            with self.assertRaises(ValueError):
                self.m.ouvrir({'slack': bad})
        self.assertEqual(self.appels, [])

    def test_the_tool_declares_slack(self):
        props = {t['name']: t for t in self.m.OUTILS}['ouvrir']['inputSchema']['properties']
        self.assertIn('slack', props)


class Page(unittest.TestCase):
    def test_slack_buttons_go_through_the_connector(self):
        p = PAGE.read_text(encoding='utf-8')
        self.assertIn('data-slack=', p)
        self.assertIn('callTool(SERVEUR, "ouvrir", { slack: u }', p)
        self.assertNotIn('slack://', p.replace('slack:// link', ''))   # never a slack:// link in the page itself
        i = p.index('function boutonSource')
        self.assertIn('lienSlack(u, "Slack ↗"', p[i:i + 600])


if __name__ == '__main__':
    unittest.main()
