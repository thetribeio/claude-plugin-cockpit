"""The batches judged by the script itself (`conflits.py juger-lots`): one headless Sonnet call per batch, no tool, no
setting source, no MCP server, the judging brief as the system prompt; the same checks as a sub-agent's judgments, the
real usage of each call kept next to the plan, the in-session sub-agents as the fallback. No real call: the command is
replaced by a fake that answers like `claude -p --output-format json`. Synthetic Studio (tests/_studio_conflits.py).
python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import types
import unittest
import unittest.mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('conflits_lots', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)

BONS = {
    'S1': {'sujet': 'S1', 'classe': 'M', 'titre': 'Comité de pilotage le jeudi', 'passages': ['E1.1', 'E1.2']},
    'S2': {'sujet': 'S2', 'classe': 'PM', 'titre': 'Plafond de remise relevé', 'passages': ['E2.1'],
           'contexte': "Les règles de septembre limitaient la remise à 10 % ; au point du 3 novembre, elle passe à 15 %.",
           'recommande': 'remplacer', 'pourquoi': 'La règle écrite est plus récente.'},
    'S3': {'sujet': 'S3', 'classe': 'rien'},
}


def reponse(jugements, usd=0.05, code=0, erreur=False):
    sortie = {'type': 'result', 'is_error': erreur, 'result': json.dumps(jugements, ensure_ascii=False),
              'total_cost_usd': usd, 'duration_ms': 1000,
              'usage': {'input_tokens': 9000, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
                        'output_tokens': 1200}}
    return types.SimpleNamespace(returncode=code, stdout=json.dumps(sortie), stderr='')


class Faux:
    """Stands for `claude -p`: records each call, answers from `reponses` in turn (or the good judgments)."""
    def __init__(self, reponses=None):
        self.appels, self.reponses = [], list(reponses or [])

    def __call__(self, cmd, entree, cwd, env):
        self.appels.append({'cmd': cmd, 'entree': entree, 'cwd': cwd, 'env': env})
        if self.reponses:
            return self.reponses.pop(0)
        ids = [i for i in BONS if f'## {i} ·' in entree]
        return reponse([BONS[i] for i in ids])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = F.make(pathlib.Path(self.tmp.name) / 'Studio - Projet Alpha')
        env = unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-10',
                                                    'CONFLITS_CLAUDE': '/faux/claude'})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('CONFLITS_JUGEMENT', None)
        plan = conflits.releve(self.studio)
        self.chemin = pathlib.Path(self.tmp.name) / 'apercu.json'
        conflits.sauver_plan(self.chemin, plan)

    def cli(self, faux, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch.object(conflits, 'appel_tete', self._appel(faux)):
            code = conflits.main(['juger-lots', str(self.chemin), *args])
        return code, out.getvalue()

    @staticmethod
    def _appel(faux):
        vrai = Base._vrai_appel
        return lambda cli, texte, executer=None: vrai(cli, texte, faux)

    _vrai_appel = staticmethod(conflits.appel_tete)


class LaCommande(Base):
    def test_the_call_carries_nothing_but_the_brief_and_the_batch(self):
        faux = Faux()
        conflits.juger_les_lots(self.chemin, executer=faux)
        self.assertTrue(faux.appels)
        a = faux.appels[0]
        cmd = a['cmd']
        self.assertEqual(cmd[:2], ['/faux/claude', '-p'])
        self.assertEqual(cmd[cmd.index('--model') + 1], 'sonnet')
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')               # no tool schema
        self.assertEqual(cmd[cmd.index('--setting-sources') + 1], '')     # no CLAUDE.md, rules, hooks, plugins
        self.assertIn('--strict-mcp-config', cmd)                          # no MCP server
        self.assertIn('--no-session-persistence', cmd)
        self.assertEqual(cmd[cmd.index('--output-format') + 1], 'json')    # real usage per call
        self.assertIn('--max-budget-usd', cmd)
        brief = cmd[cmd.index('--system-prompt') + 1]
        self.assertIn('« Rien » est strict', brief)
        self.assertIn('donnés dans le message', brief)
        self.assertEqual(a['env'].get('DISABLE_PROMPT_CACHING'), '1')      # one call: a cache write saves nothing
        self.assertNotEqual(pathlib.Path(a['cwd']).resolve(), self.studio.resolve())   # no project file loaded
        self.assertIn('## S1 ·', a['entree'])

    def test_the_brief_is_the_monday_pass_brief(self):
        self.assertTrue(conflits.consigne_tete().startswith(
            conflits.CONSIGNE_JUGEMENT.split('donnés dans')[0]))
        self.assertIn(conflits.CONSIGNE_JUGEMENT.split('\n', 1)[1], conflits.consigne_tete())


class LeJugement(Base):
    def test_judgments_written_where_juger_reads_them_then_the_preview(self):
        code, out = self.cli(Faux())
        self.assertEqual(code, 0, out)
        self.assertTrue(conflits.chemin_jugements(self.chemin, 1).exists())
        self.assertIn('$ réels', out)
        plan = conflits.charger_plan(self.chemin)
        self.assertEqual(set(plan['jugements']), {'S1', 'S2', 'S3'})
        self.assertTrue(plan['marquages'])
        couts = json.loads(conflits.chemin_couts(self.chemin).read_text(encoding='utf-8'))
        self.assertEqual(couts[0]['entree'], 9000)
        self.assertEqual(couts[0]['sortie'], 1200)

    def test_a_title_with_a_code_is_asked_again_for_that_subject_only(self):
        mauvais = dict(BONS['S2'], titre='Remise PRJ-2 relevée')
        faux = Faux([reponse([BONS['S1'], mauvais, BONS['S3']]), reponse([BONS['S2']])])
        r = conflits.juger_les_lots(self.chemin, executer=faux)
        self.assertEqual(r['a_refaire'], [])
        self.assertEqual(len(faux.appels), 2)
        second = faux.appels[1]['entree']
        self.assertIn('## S2 ·', second)
        self.assertNotIn('## S1 ·', second)
        self.assertIn('code', second)
        self.assertAlmostEqual(r['usd'], 0.10)

    def test_a_subject_still_missing_sends_the_batch_to_the_fallback(self):
        faux = Faux([reponse([BONS['S1']]), reponse([])])
        code, out = self.cli(faux)
        self.assertEqual(code, 3)
        self.assertIn('repli', out)
        plan = conflits.charger_plan(self.chemin)
        self.assertEqual(plan['jugements'], {})                    # no preview from a half-judged plan

    def test_a_failed_call_costs_nothing_more_and_is_said(self):
        faux = Faux([reponse([], usd=0.0, code=1, erreur=True)] * 2)
        r = conflits.juger_les_lots(self.chemin, executer=faux)
        self.assertEqual(r['a_refaire'], [1])
        self.assertTrue(r['resultats'][0]['erreurs'])

    def test_a_judged_batch_is_not_paid_twice(self):
        conflits.juger_les_lots(self.chemin, executer=Faux())
        faux = Faux()
        r = conflits.juger_les_lots(self.chemin, executer=faux)
        self.assertEqual(faux.appels, [])
        self.assertEqual(r['a_refaire'], [])

    def test_without_the_command_line_the_sub_agents_judge(self):
        with unittest.mock.patch.dict(os.environ, {'CONFLITS_JUGEMENT': 'sous-agents'}):
            code, out = self.cli(Faux())
            self.assertEqual(conflits.mode_jugement(), 'sous-agents')
        self.assertEqual(code, 3)
        self.assertIn('sous-agents (repli)', out)

    def test_an_answer_wrapped_in_a_code_fence_is_read(self):
        self.assertEqual(conflits.liste_json('```json\n[{"sujet": "S1", "classe": "rien"}]\n```'),
                         [{'sujet': 'S1', 'classe': 'rien'}])
        with self.assertRaises(ValueError):
            conflits.liste_json('Je ne peux pas.')


if __name__ == '__main__':
    unittest.main()
