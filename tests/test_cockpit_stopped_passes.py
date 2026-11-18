"""Tests: a scheduled pass stopped on its way leads the board, in plain words (PM, 2026-11-17).

python3 -m unittest discover -s tests

On 17/11 the morning point stopped at 8:26 on a Slack search, wrote no matin.json, and the app's list of scheduled
tasks showed it « réussie ». The board showed « arrêtée sur une autorisation (mcp__749c…__slack_search_public_and_
private) », somewhere in its middle.
1. A tool's name is translated (« recherche Slack »), never `mcp__…`.
2. A stopped pass of a scheduled task leads « D'abord ».
3. The morning point not written today: one line at the head, that says why when its last pass says it."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import shutil
import unittest
from unittest import mock

import test_cockpit_scheduled_tasks as tasks
from test_cockpit_impact_effort import ligne, run_page

parc = tasks.parc
SLACK = 'mcp__749c036c-4b4b-49f3-bd3e-755af78aed3c__slack_search_public_and_private'
RETARD = "Point du matin pas passé aujourd'hui (dernier : 16/11)"


class ToolNames(unittest.TestCase):
    def test_known_tools(self):
        self.assertEqual(parc.nom_outil(SLACK), 'recherche Slack')
        self.assertEqual(parc.nom_outil('mcp__749c036c-4b4b-49f3-bd3e-755af78aed3c__slack_read_thread'), "lecture d'un fil Slack")
        self.assertEqual(parc.nom_outil('mcp__ccd_turn__update_plan'), 'liste des tâches de la session')
        self.assertEqual(parc.nom_outil('Bash'), 'commande du terminal')
        self.assertEqual(parc.nom_outil('mcp__b8e8556e-007a-42cb-a91b-55a4027514a8__list_events'), "lecture de l'agenda")
        self.assertEqual(parc.nom_outil('mcp__ccd_session_mgmt__list_events'), "lecture d'une session")

    def test_an_unknown_tool_never_shows_its_raw_name(self):
        for nom in ('mcp__pw-boond__browser_click', 'mcp__0c8228c5-d434-4a94-8c8a-e7d145535002__notion-query-meeting-notes',
                    'mcp__2d9cf542-7d06-4fb0-8cfe-16524152dac8__label_thread', 'mcp__srv__getJiraThing', 'mcp__solo'):
            vu = parc.nom_outil(nom)
            self.assertNotIn('mcp__', vu)
            self.assertNotRegex(vu, r'[0-9a-f]{8}-')
            self.assertTrue(vu.strip())
        self.assertEqual(parc.nom_outil('mcp__pw-boond__browser_click'), 'Boond : browser click')
        self.assertEqual(parc.nom_outil('mcp__2d9cf542-7d06-4fb0-8cfe-16524152dac8__label_thread'), 'outil « label thread »')

    def test_an_extract_keeps_its_detail(self):
        self.assertEqual(parc.extrait_lisible(SLACK + ' · in:#canal after:2026-11-16'), 'recherche Slack · in:#canal after:2026-11-16')
        self.assertEqual(parc.extrait_lisible('git push · rien'), 'git push · rien')
        self.assertEqual(parc.extrait_outil(SLACK, {'query': 'in:#canal'}), 'recherche Slack · in:#canal')


# The helpers of the scheduled-task tests, without running their tests twice
Helpers = type('Helpers', (unittest.TestCase,), {k: v for k, v in vars(tasks.Tasks).items() if not k.startswith('test_')})


class StoppedPass(Helpers):
    def stopped_on_slack(self, name='Point du matin'):
        return self.lines([tasks.prompt(3), tasks.tool(2.9, 'a', SLACK, {'query': 'in:#canal after:2026-11-16'}),
                           *tasks.refused(1, 'a')], name=name, title='Passage du matin' if name != 'Point du matin' else None)

    def test_the_line_says_the_tool_in_words_and_leads(self):
        lines, _ = self.stopped_on_slack(name='Ingestion auto')
        (l,) = lines
        self.assertEqual(l['suite'], 'Ingestion auto : arrêtée sur une autorisation (recherche Slack)')
        self.assertEqual(self.stopped_on_slack()[0][0]['suite'], 'Arrêtée sur une autorisation (recherche Slack)')
        self.assertIn('recherche Slack · in:#canal', l['detail'])
        self.assertTrue(l['en_tete'])
        self.assertEqual(l['impact'], 'fort')
        self.assertTrue(parc.rang_page(l)['en_tete'])
        for v in (l['suite'], l['detail']):
            self.assertNotIn('mcp__', v)

    def morning(self, entries, task_id='point-du-matin', retard=RETARD):
        autos, metas = self.automates(entries)
        for a in autos:
            a['id'] = task_id
        old = parc.CHANTIERS
        parc.CHANTIERS = self.root / 'chantiers'
        try:
            with mock.patch.object(parc, 'retard_du_matin', return_value=retard):
                fresh, aged = parc.lignes_et_anciennes([], metas, autos, 7, tasks.NOW, None)
        finally:
            parc.CHANTIERS = old
        return [l for l in fresh + aged if l.get('tache')]

    def test_the_morning_point_stopped_on_an_authorization(self):
        (l,) = self.morning([tasks.prompt(3), tasks.tool(2.9, 'a', SLACK, {'query': 'in:#canal'}), *tasks.refused(1, 'a')])
        heure = parc.heure_courte(dt.datetime.fromisoformat(tasks.at(1)).timestamp())
        self.assertEqual(l['suite'], f"{RETARD} : arrêté à {heure} sur une autorisation (recherche Slack)")
        self.assertLessEqual(len(l['suite']), parc.LIBELLE_MAX, 'the board cuts a longer line (17/11: « à … »)')
        self.assertIn(parc.RELANCER_MATIN, l['detail'])
        self.assertIn('recherche Slack · in:#canal', l['detail'])
        self.assertEqual((l['ouvrir'], l['verbe'], l['en_tete'], l['impact']), (tasks.PASS, 'Ouvrir', True, 'fort'))

    def test_the_morning_point_ended_without_its_file(self):
        (l,) = self.morning([tasks.prompt(3), tasks.final(2.5, 'b')])
        self.assertTrue(l['suite'].startswith(f"{RETARD} : son passage de "))
        self.assertTrue(l['suite'].endswith('a fini sans écrire le point'))
        self.assertEqual(l['detail'], parc.RELANCER_MATIN)
        self.assertEqual((l['ouvrir'], l['en_tete'], l['impact']), (tasks.PASS, True, 'fort'))

    def test_nothing_when_the_morning_point_is_written(self):
        self.assertEqual(self.morning([tasks.prompt(3), tasks.final(2.5, 'b')], retard=None), [])

    def test_another_task_is_not_the_morning_point(self):
        self.assertEqual(self.morning([tasks.prompt(3), tasks.final(2.5, 'b')], task_id='ingestion'), [])

    def test_an_extract_cached_by_an_older_version_is_translated(self):
        # 17/11 on the real board: cache.json kept « mcp__749c…__slack_search_public_and_private · … » from 0.2.23
        a = {'nom': 'Ingestion auto', 'id': 'x', 'lien': tasks.PASS, 'cwd': '/studios/Essai', 'ts': tasks.NOW - 3600,
             'arret': {'quoi': 'authorization', 'outil': SLACK, 'extrait': SLACK + ' · in:#canal', 'depuis': tasks.NOW - 3600}}
        (l,) = parc.ligne_de_tache(a, {}, {}, set(), 7, tasks.NOW)
        self.assertEqual(l['extrait'], 'recherche Slack · in:#canal')
        self.assertNotIn('mcp__', l['detail'])

    def test_heure_courte(self):
        self.assertEqual(parc.heure_courte(dt.datetime(2026, 11, 17, 8, 26).timestamp()), '8 h 26')
        self.assertEqual(parc.heure_courte(dt.datetime(2026, 11, 17, 7, 0).timestamp()), '7 h')


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def test_a_stopped_pass_leads_d_abord(self):
        out = run_page(lignes=[ligne('Go attendu', impact='fort', raison='client attend', effort='court'),
                               ligne(RETARD + ' : arrêté à 8 h 26 sur une autorisation (recherche Slack)',
                                     studio='Automates', impact='fort', en_tete=True)])
        t = out['tableau']
        self.assertLess(t.find("D'abord"), t.find('Point du matin pas passé'))
        self.assertLess(t.find('Point du matin pas passé'), t.find('Go attendu'))


if __name__ == '__main__':
    unittest.main()
