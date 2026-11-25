"""Tests of the switches set on the PM's request, and of the install plan that announces the rules:
python3 -m unittest discover -s tests

Adoption test of 2026-11-02: the switches (authorizations, direct answers) are set by `/cockpit:mon-studio` when the
PM asks, through `install.py switch`, never by hand in cockpit.json; the rules a session gets are announced in the
install plan, so the one go covers them; the publication hours become an optional rule. Fake HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_cockpit_disable import load  # noqa: E402


class Switches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name) / 'home'
        (self.home / '.claude').mkdir(parents=True)
        env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin'}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop('MON_STUDIO', None)
        self.i = load('install', env)
        self.i.INTERNAL.mkdir(parents=True)
        self.i.record_state(version='0.1.0', reponses_directes=False)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.i.main(list(argv))
        return code, out.getvalue()

    def state(self):
        return json.loads(self.i.STATE.read_text())

    def test_boolean_switches(self):
        self.assertEqual(self.run_main('switch', 'reponses-directes', 'on')[0], 0)
        self.assertIs(self.state()['reponses_directes'], True)
        self.run_main('switch', 'autorisations', 'on')
        self.run_main('switch', 'autorisations', 'off')
        self.assertIs(self.state()['autorisations_tableau'], False)
        self.assertEqual(self.run_main('switch', 'tableau-publie', 'off')[0], 2)   # retired with the foreman
        self.assertEqual(self.state()['version'], '0.1.0')   # nothing else touched

    def test_reclassement_is_off_until_asked(self):
        self.assertFalse(self.i.status()['reclassementTableau'])   # off by default: the board of 0.2.23
        self.assertEqual(self.run_main('switch', 'reclassement', 'on')[0], 0)
        self.assertIs(self.state()['reclassement_tableau'], True)
        self.assertTrue(self.i.status()['reclassementTableau'])
        self.run_main('switch', 'reclassement', 'off')
        self.assertIs(self.state()['reclassement_tableau'], False)
        self.assertIn('switch reclassement on|off', self.run_main('switch', 'tout', 'on')[1])

    def test_the_two_blocking_checks_have_a_switch(self):
        st = self.i.status()
        self.assertTrue(st['controleModele'])   # on by default, as before 0.3.5
        self.assertTrue(st['controleFormat'])
        for nom, cle, champ in (('controle-modele', 'controle_modele', 'controleModele'),
                                ('controle-format', 'controle_format', 'controleFormat')):
            code, out = self.run_main('switch', nom, 'off')
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), f'{cle} : coupé.')
            self.assertIs(self.state()[cle], False)
            self.assertFalse(self.i.status()[champ])
            self.assertEqual(self.run_main('switch', nom, 'on')[1].strip(), f'{cle} : allumé.')
            self.assertIs(self.state()[cle], True)
        usage = self.run_main('switch', 'tout', 'on')[1]
        self.assertIn('switch controle-modele on|off', usage)
        self.assertIn('switch controle-format on|off', usage)
        self.assertEqual(self.state()['version'], '0.1.0')   # nothing else touched

    def test_the_two_hooks_of_the_scale_have_a_switch(self):
        st = self.i.status()
        self.assertTrue(st['reglageOuverture'])   # on by default
        self.assertTrue(st['controleBareme'])
        for nom, cle, champ in (('reglage-ouverture', 'reglage_ouverture', 'reglageOuverture'),
                                ('controle-bareme', 'controle_bareme', 'controleBareme')):
            code, out = self.run_main('switch', nom, 'off')
            self.assertEqual((code, out.strip()), (0, f'{cle} : coupé.'))
            self.assertIs(self.state()[cle], False)
            self.assertFalse(self.i.status()[champ])
            self.assertEqual(self.run_main('switch', nom, 'on')[1].strip(), f'{cle} : allumé.')
        usage = self.run_main('switch', 'tout', 'on')[1]
        self.assertIn('switch reglage-ouverture on|off', usage)
        self.assertIn('switch controle-bareme on|off', usage)
        self.assertEqual(self.state()['version'], '0.1.0')   # nothing else touched

    def test_the_pm_name_is_set_by_a_switch(self):
        self.assertEqual((self.i.status()['pmName'], self.i.status()['pmNameSource']), ('', 'aucun'))
        code, out = self.run_main('switch', 'pm', '  Camille   Exemple ')
        self.assertEqual(code, 0)
        self.assertIn('pm : Camille Exemple.', out)
        self.assertEqual(self.state()['pm'], 'Camille Exemple')
        st = self.i.status()
        self.assertEqual((st['pmName'], st['pmNameSource']), ('Camille Exemple', 'reglage'))
        self.assertEqual(self.run_main('switch', 'pm', '')[0], 0)   # removed: back to git, then the Mac account
        self.assertNotIn('pm', self.state())
        self.assertIn('switch pm "<Prénom Nom>"', self.run_main('switch', 'tout', 'on')[1])
        self.assertEqual(self.state()['version'], '0.1.0')

    def test_the_direct_answers_trial_ends_for_every_session(self):
        state = self.state()
        state['reponses_directes_sessions'] = ['local_essai']
        (self.home / 'Mon Studio' / '.parc' / 'cockpit.json').write_text(json.dumps(state))
        self.assertEqual(self.run_main('switch', 'reponses-directes-sessions', 'toutes')[0], 0)
        self.assertNotIn('reponses_directes_sessions', self.state())
        self.assertEqual(self.run_main('switch', 'reponses-directes-sessions', 'une')[0], 2)

    def test_numbers_are_bounded(self):
        self.assertEqual(self.run_main('switch', 'reponses-directes-minutes', '20')[0], 0)
        self.assertEqual(self.state()['reponses_directes_minutes'], 20)
        self.assertEqual(self.run_main('switch', 'reponses-directes-minutes', '45')[0], 2)
        self.assertEqual(self.run_main('switch', 'decoupe-seuil', '400000')[0], 0)
        self.assertEqual(self.state()['decoupe_seuil_tokens'], 400000)
        self.assertEqual(self.run_main('switch', 'decoupe-seuil', '1000')[0], 2)

    def test_optional_rule(self):
        self.assertEqual(self.run_main('switch', 'regle', 'heures-publication', 'on')[0], 0)
        self.assertEqual(self.state()['regles_optionnelles'], ['heures-publication'])
        self.run_main('switch', 'regle', 'heures-publication', 'on')
        self.assertEqual(self.state()['regles_optionnelles'], ['heures-publication'])   # once
        self.run_main('switch', 'regle', 'heures-publication', 'off')
        self.assertEqual(self.state()['regles_optionnelles'], [])
        self.assertEqual(self.run_main('switch', 'regle', 'inconnue', 'on')[0], 2)

    def test_unknown_switch_lists_the_known_ones(self):
        code, out = self.run_main('switch', 'tout', 'on')
        self.assertEqual(code, 2)
        self.assertIn('switch reponses-directes on|off', out)

    def test_not_installed(self):
        self.i.STATE.unlink()
        self.assertEqual(self.run_main('switch', 'autorisations', 'on')[0], 3)
        self.assertFalse(self.i.STATE.exists())

    def test_status_reports_the_new_switches(self):
        self.run_main('switch', 'regle', 'heures-publication', 'on')
        s = self.i.status()
        self.assertEqual(s['reglesOptionnelles'], ['heures-publication'])

    def test_plan_announces_the_rules(self):
        self.i.APP_SESSIONS.mkdir(parents=True)
        (self.home / '.claude' / 'CLAUDE.md').write_text('@livrables.md\n')
        with mock.patch.object(self.i.sys, 'platform', 'darwin'):
            lines = '\n'.join(self.i.plan())
        self.assertIn('règles de travail au démarrage de chaque session : format-reponses', lines)
        self.assertIn('passation', lines)
        self.assertIn('déjà : livrables', lines)
        self.assertIn('ne donnerait pas, sauf demande : heures-publication', lines)
        self.assertIn('session lourde', lines)


if __name__ == '__main__':
    unittest.main()
