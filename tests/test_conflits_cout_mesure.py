"""The cost announced before a relevé, against the first relevé measured on a real Studio: python3 -m unittest discover -s tests

2026-11-18, cockpit 0.3.1: 97 subjects in 11 batches, 11 Sonnet sub-agents. Announced before the go: 0.33 % of the week,
« about 92,000 tokens of extracts ». Measured in the session's transcripts (tokens, per kind): the sub-agents wrote
637,915 tokens to the cache (new input included), read 2,582,570 from it and wrote 32,779 output tokens; each carried
about 78,000 tokens before its batch. The conflicts session (Opus) launched and received them in 43 calls: 181,165
written, 6,847,719 read, 38,759 output. The replay of the estimate on the same figures must stay within 25 % of that,
component by component, and say the tokens a sub-agent really carries. Synthetic plan, no Studio read."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('conflits_cout', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)
spec = importlib.util.spec_from_file_location('projets_cout', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'projets.py')
projets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projets)

MESURE_SOUS_AGENTS = (637_915, 32_779, 2_582_570)     # written, output, read: Sonnet
MESURE_SESSION = (181_165, 38_759, 6_847_719)          # Opus, the relevé's calls (before the decisions)


def usd(modele, ecrits, sortie, relus):
    entree, out, cache = conflits.registre.PRIX[modele]
    return (ecrits * entree * 1.25 + sortie * out + relus * cache) / 1e6


def plan_de_l_essai():
    """97 subjects whose extracts weigh what the trial's did (92,306 tokens at 3.5 characters, as announced)."""
    sujet = {'extraits': [{'contexte': 'x' * 2978}], 'ancien': {'texte': 'a'}, 'nouveau': {'texte': 'b'}}
    ids = [f'S{i}' for i in range(1, 98)]
    return {'sujets': [dict(sujet, id=i) for i in ids], 'lots': [ids[k:k + 9] for k in range(0, 97, 9)][:10] + [ids[90:]]}


class Rejeu(unittest.TestCase):
    def setUp(self):
        self.c = conflits.estimer_cout(plan_de_l_essai())

    def test_the_replay_is_the_trial(self):
        self.assertEqual((self.c['sujets'], self.c['lots'], self.c['decisions_estimees']), (97, 11, 20))

    def test_each_part_within_25_percent_of_the_measure(self):
        agents, session = usd('sonnet', *MESURE_SOUS_AGENTS), usd('opus', *MESURE_SESSION)
        self.assertAlmostEqual(agents + session, 5.23, delta=0.01)
        for estime, mesure in ((self.c['usd_sous_agents'], agents), (self.c['usd_session_releve'], session),
                               (self.c['usd_sous_agents'] + self.c['usd_session_releve'], agents + session)):
            self.assertLess(abs(estime / mesure - 1), 0.25, (estime, mesure))
            self.assertGreaterEqual(estime, mesure * 0.95)          # a ceiling, not a floor

    def test_the_tokens_said_are_the_tokens_spent(self):
        self.assertLess(abs(self.c['tokens_sous_agents'] / sum(MESURE_SOUS_AGENTS) - 1), 0.25)
        self.assertTrue(84_000 <= self.c['tokens_par_sous_agent'] <= 103_000, self.c['tokens_par_sous_agent'])
        t = conflits.texte_cout(self.c)
        self.assertIn('dont 78 000 de socle fixe', t)
        self.assertIn("tokens de contexte chacun", t)
        self.assertNotIn("tokens d'extraits", t)                   # the figure that misled: 92,000 for 3.3 million
        self.assertIn('3,5 millions de tokens en tout', t)

    def test_preparing_counts_the_session_that_launches_the_sub_agents(self):
        p = conflits.cout_preparer(self.c)
        self.assertAlmostEqual(p['usd'], self.c['usd_sous_agents'] + self.c['usd_session_releve'], places=2)
        self.assertAlmostEqual(p['usd_session'], self.c['usd_session_decisions'], places=2)

    def test_tickets_use_the_same_sub_agent_model(self):
        spec = importlib.util.spec_from_file_location('tickets_cout', ROOT / 'skills' / 'conflits' / 'scripts' / 'tickets.py')
        tickets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tickets)
        with unittest.mock.patch.object(tickets, '_conflits', return_value=conflits):
            e = tickets.estimate(10)
        self.assertGreater(e['usd'], usd('sonnet', conflits.AGENT_SOCLE, 0, 0))


class EstimationGardee(unittest.TestCase):
    def test_an_estimate_of_the_former_model_is_never_shown(self):
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(projets.parc, 'INTERNE', pathlib.Path(d)):
            studio = str(pathlib.Path(d) / 'Studio - Projet Alpha')
            ancienne = {'t': time.time(), 'sujets': 97, 'decisions': 20, 'minutes': 22, 'pourcent': 0.33,
                        'pourcent_preparer': 0.25, 'au_dessus': False}
            (pathlib.Path(d) / 'conflits-estimations.json').write_text(json.dumps({studio: ancienne}), encoding='utf-8')
            self.assertIsNone(projets.estimation_premiere(studio))
            neuve = dict(ancienne, bareme=projets.ESTIMATION_BAREME, pourcent=0.5)
            (pathlib.Path(d) / 'conflits-estimations.json').write_text(json.dumps({studio: neuve}), encoding='utf-8')
            self.assertEqual(projets.estimation_premiere(studio)['pourcent'], 0.5)


if __name__ == '__main__':
    unittest.main()
