"""Closing block of the turn (PM, 2026-11-26): python3 -m unittest discover -s tests

The Stop hook format_questions.py sends back once a last message that ends with neither a « À trancher » block nor
« Rien à faire de ton côté » (or « To decide » / « Nothing to do on your side. »). It lets through: a short status
line, a turn after a block (`stop_hook_active`), an empty turn, a scheduled task, a session launched by another
session, a session outside the desktop app. Its own switch: `controle_fin_de_tour: false`. Texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest

import test_cockpit_short_titles as base   # helpers only: transcript(), env_app(), HOST

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'format_questions.py'
spec = importlib.util.spec_from_file_location('format_questions_fin', HOOK)
fq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fq)
parc = base.parc

LONG = ("J'ai relu le plan et corrigé les trois écarts de dates entre la page de cadrage et le devis. Le chiffrage tient "
        "toujours dans le budget annoncé, et les deux scénarios restent comparables sur les mêmes hypothèses. ")
BLOC = LONG + "\n\n**À trancher**\n\nQ1 · Envoyer le plan ? : Tu l'envoies demain.\n1) **L'envoyer** (recommandé) : tel quel\n2) **Attendre** : lundi\n"


class SansFin(unittest.TestCase):
    def sf(self, t):
        return fq.sans_fin(parc, t)

    def test_missing_end_is_caught(self):
        self.assertTrue(self.sf(LONG))
        self.assertTrue(self.sf(LONG + "\n\nTu peux le relire quand tu veux."))

    def test_blocks_and_rien_pass_in_both_languages(self):
        self.assertFalse(self.sf(BLOC))
        self.assertFalse(self.sf(LONG.replace('J\'ai', 'I') + "\n\n**To decide**\n\nQ1 · Send? : yes\n"))
        for fin in ("Rien à faire de ton côté.", "rien à faire de ton côté", "**Rien à faire de ton côté**",
                    "Rien à faire de ton côté !", "Nothing to do on your side.", "NOTHING TO DO ON YOUR SIDE",
                    "Rien d'autre à trancher de ton côté."):
            self.assertFalse(self.sf(LONG + "\n\n" + fin), fin)

    def test_rien_in_the_middle_does_not_count(self):
        self.assertTrue(self.sf("Rien à faire de ton côté.\n\n" + LONG + "Je continue demain avec le reste du lot."))

    def test_empty_and_short_pass(self):
        self.assertFalse(self.sf(''))
        self.assertFalse(self.sf('   \n'))
        self.assertFalse(self.sf("Suite complète en cours, je reprends à son retour."))

    def test_code_block_does_not_fake_an_ending(self):
        self.assertTrue(self.sf(LONG + "\n\n```\nRien à faire de ton côté.\n```\n"))

    def test_encore_ouvert_counts(self):
        self.assertFalse(self.sf(LONG + "\n\nEncore ouvert : Q3 · Date de recette."))


class Hook(unittest.TestCase):
    def run_hook(self, texte, host=base.HOST, state=None, cartes=None, premier=None, **entree):
        with tempfile.TemporaryDirectory() as home:
            ms = pathlib.Path(home) / 'Mon Studio' / '.parc'
            ms.mkdir(parents=True)
            if state is not None:
                (ms / 'cockpit.json').write_text(json.dumps(state))
            t = base.transcript(home, texte)
            if premier:
                lignes = pathlib.Path(t).read_text().splitlines()
                o = json.loads(lignes[0])
                o['message']['content'] = premier
                pathlib.Path(t).write_text('\n'.join([json.dumps(o)] + lignes[1:]) + '\n')
            env = base.env_app(home, host)
            if cartes is not None:
                app = pathlib.Path(home) / 'app' / 'a' / 'b'
                app.mkdir(parents=True)
                (app / f'{base.HOST}.json').write_text(json.dumps(dict(cartes, sessionId=base.HOST, cliSessionId='abc')))
                env['MON_STUDIO_APP_SESSIONS'] = str(pathlib.Path(home) / 'app')
            entree = dict({'session_id': 'abc', 'transcript_path': t}, **entree)
            r = subprocess.run(['python3', str(HOOK)], input=json.dumps(entree), capture_output=True, text=True,
                               timeout=30, env=env)
            j = ms / 'format-questions.jsonl'
            return r.stdout, [json.loads(x) for x in j.read_text().splitlines()] if j.exists() else []

    def test_blocks_once_with_a_short_message(self):
        out, journal = self.run_hook(LONG)
        r = json.loads(out)
        self.assertEqual(r['decision'], 'block')
        self.assertIn('Rien à faire de ton côté', r['reason'])
        self.assertIn('À trancher', r['reason'])
        self.assertEqual(journal[0]['ecarts'], ['sans_fin'])
        self.assertNotIn('plan', json.dumps(journal))   # never the message's text

    def test_no_loop(self):
        out, journal = self.run_hook(LONG, stop_hook_active=True)
        self.assertEqual(out, '')
        self.assertTrue(journal[0]['relance'])

    def test_silent_on_a_closed_message(self):
        self.assertEqual(self.run_hook(LONG + "\n\nRien à faire de ton côté.")[0], '')
        self.assertEqual(self.run_hook(BLOC)[0], '')

    def test_own_switch_and_global_switch(self):
        self.assertEqual(self.run_hook(LONG, state={'controle_fin_de_tour': False}), ('', []))
        self.assertEqual(json.loads(self.run_hook(LONG, state={'controle_fin_de_tour': True})[0])['decision'], 'block')
        self.assertEqual(self.run_hook(LONG, state={'controle_format': False}), ('', []))
        # the format control stays on when only the closing control is off
        mauvais = base.Hook.MAUVAIS
        out, _ = self.run_hook(mauvais, state={'controle_fin_de_tour': False})
        self.assertIn('Q7', json.loads(out)['reason'])

    def test_silent_outside_the_desktop_app(self):
        self.assertEqual(self.run_hook(LONG, host=None), ('', []))

    def test_scheduled_task_and_launched_session_pass(self):
        self.assertEqual(self.run_hook(LONG, premier='<scheduled-task name="x">Lance</scheduled-task>')[0], '')
        self.assertEqual(self.run_hook(LONG, cartes={'scheduledTaskId': 't1'})[0], '')
        self.assertEqual(self.run_hook(LONG, cartes={'spawnedFrom': {'sessionId': 'local_x'}})[0], '')
        # moved up to the top level: read like any session
        out, _ = self.run_hook(LONG, cartes={'spawnedFrom': {'sessionId': 'local_x'}, 'lineageDetached': True})
        self.assertEqual(json.loads(out)['decision'], 'block')

    def test_empty_turn_passes(self):
        self.assertEqual(self.run_hook('')[0], '')

    def test_switch_documented(self):
        self.assertIn('controle-fin-de-tour', (ROOT / 'skills/mon-studio/SKILL.md').read_text(encoding='utf-8'))
        self.assertIn('controle_fin_de_tour', (ROOT / 'docs/a-fournir.md').read_text(encoding='utf-8'))
        self.assertIn('controle-fin-de-tour', (ROOT / 'skills/mon-studio/scripts/install.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
