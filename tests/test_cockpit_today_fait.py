"""Tests: Today evolves by hand (PM, 2026-11-09): python3 -m unittest discover -s tests

- Q42: a Slack draft shows in Today 3 working days (Monday to Friday) at most after it was written, then goes by itself,
  « Fait » or not; a Gmail draft stays until it is sent or marked « Fait ». Filtered by matin.py, without an LLM.
- Every item of a Today rubric that asks for a gesture (à traiter, entrées au Studio, préparer
  demain, brouillons) has one button, « Fait », the same word everywhere in Today except the entries that came into the Studio (« Pour info »), whose button is « Vu »; one click, the item leaves at once
  and for good: neither the next computation nor the next morning task brings it back. The agenda and « Réglé » only
  inform; « Tout vu » stays on each group of entries. The main board keeps its own label.
- scripts/controle_lignes.py checks it on real data: every actionable item of Today has its closing button.

Studios, drafts and pages here are synthetic; every file lives in a temporary folder."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import pathlib
import re
import shutil
import tempfile
import unittest

import test_cockpit_drafts as td
import test_cockpit_matin as tm
from test_cockpit_matin import MatinBase, item, iso
from test_cockpit_projets import FRIDAY, MONDAY, REPORT, local

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPT = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin.md'
spec = importlib.util.spec_from_file_location('controle_lignes_today', ROOT / 'scripts' / 'controle_lignes.py')
controle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controle)

WEDNESDAY_4 = dt.date(2026, 11, 4)
MONDAY_9 = local(2026, 11, 9)       # Wednesday 4 + Thursday, Friday, (weekend), Monday: the third working day
TUESDAY_10 = local(2026, 11, 10)    # the fourth: gone
BUTTON = re.compile(r'<button type="button" class="fait" ([a-z-]+)="([^"]*)"[^>]*>([^<]*)</button>')


def slack(i='s', **extra):
    return td.draft(i, **dict({'outil': 'slack', 'cle': f'slack:C{i}', 'destinataire': '#projet',
                               'lien': f'https://example.slack.com/archives/C{i}', 'depuis': WEDNESDAY_4.isoformat()},
                              **extra))


class SlackDrafts(MatinBase):
    def keys(self, when):
        return [x['cle'] for x in self.m.pour_la_page(when)['brouillons']]

    def test_working_days_are_monday_to_friday(self):
        n = self.m.jours_ouvres_apres
        self.assertEqual(n(WEDNESDAY_4, WEDNESDAY_4), 0)
        self.assertEqual(n(dt.date(2026, 11, 6), dt.date(2026, 11, 9)), 1, 'Friday to Monday: one working day')
        self.assertEqual(n(WEDNESDAY_4, dt.date(2026, 11, 9)), 3)
        self.assertEqual(n(WEDNESDAY_4, dt.date(2026, 11, 10)), 4)
        self.assertEqual(n(WEDNESDAY_4, dt.date(2027, 3, 1)), 117, 'far away: counted roughly, always more than 3')

    def test_a_slack_draft_shows_three_working_days_with_a_weekend_in_between_then_goes(self):
        gmail = td.draft(1, depuis=WEDNESDAY_4.isoformat())
        for when in (local(2026, 11, 5), local(2026, 11, 6), MONDAY_9):
            self.write(genere_le=iso(when), brouillons=[slack(), gmail])
            self.assertEqual(self.keys(when), ['slack:Cs', 'gmail:r-1'], dt.date.fromtimestamp(when))
        self.write(genere_le=iso(TUESDAY_10), brouillons=[slack(), gmail])
        self.assertEqual(self.keys(TUESDAY_10), ['gmail:r-1'], 'gone by itself, without « Fait »; Gmail stays')
        with self.assertRaises(ValueError):
            self.m.fait('slack:Cs', TUESDAY_10)

    def test_without_depuis_the_noted_creation_counts_and_without_any_date_it_goes(self):
        notes = [{'cle': 'slack:Cn', 'outil': 'slack', 'cree_le': '2026-11-06T10:00:00+01:00'}]
        (self.mon_studio / '.parc' / 'brouillons.json').write_text(json.dumps({'brouillons': notes}), encoding='utf-8')
        self.write(genere_le=iso(MONDAY_9), brouillons=[slack('n', depuis=''), slack('x', depuis='')])
        self.assertEqual(self.keys(MONDAY_9), ['slack:Cn'])

    def test_an_expired_slack_draft_does_not_take_a_place(self):
        self.write(genere_le=iso(TUESDAY_10), brouillons=[slack()] + [td.draft(i) for i in range(10)])
        self.assertEqual(len(self.keys(TUESDAY_10)), self.m.PLAFOND_BROUILLONS)
        self.assertNotIn('slack:Cs', self.keys(TUESDAY_10))

    def test_the_prompt_says_it_in_one_line(self):
        c = PROMPT.read_text(encoding='utf-8')
        # 2026-11-10: matin.py preparer keeps a Slack draft inside its 3 working days; the prompt no longer counts.
        self.assertEqual(len([l for l in c.splitlines() if '3 jours ouvrés' in l]), 0)
        self.assertNotIn('—', c)


class DurableFait(MatinBase):
    POINT = {'a_traiter': [item(1)], 'preparer_demain': [{'cle': 'demain:ev1', 'titre': 'Relire le devis', 'phrase': '', 'lien': ''},
                                                         {'titre': 'Préparer la démo', 'phrase': '', 'lien': 'https://drive.google.com/d'}],
             'brouillons': [td.draft(1)]}

    def open_keys(self, when):
        p = self.m.pour_la_page(when)
        return {b: [x['cle'] for x in p[b]] for b in ('a_traiter', 'preparer_demain', 'brouillons')}

    def test_preparer_demain_has_a_stable_key(self):
        self.write(**self.POINT)
        first = self.m.pour_la_page(MONDAY)['preparer_demain']
        self.assertEqual(first[0]['cle'], 'demain:ev1')
        self.assertRegex(first[1]['cle'], r'^demain:[0-9a-f]{12}$')
        self.write(genere_le=iso(MONDAY + 3600), **self.POINT)
        self.assertEqual(self.m.pour_la_page(MONDAY + 3600)['preparer_demain'][1]['cle'], first[1]['cle'])

    def test_every_item_of_the_point_is_closed_for_good(self):
        self.write(**self.POINT)
        derived = self.m.pour_la_page(MONDAY)['preparer_demain'][1]['cle']
        for cle in ('k1', 'demain:ev1', derived, 'gmail:r-1'):
            self.assertEqual(self.m.fait(cle, MONDAY), {'fait': cle})
        empty = {'a_traiter': [], 'preparer_demain': [], 'brouillons': []}
        self.assertEqual(self.open_keys(MONDAY + 60), empty, 'at once, and at the next computation')
        # The verification task rewrites the file during the day, the morning task the next day: nothing comes back.
        self.write(genere_le=iso(MONDAY + 3 * 3600), **self.POINT)
        self.assertEqual(self.open_keys(MONDAY + 3 * 3600), empty)
        tuesday = MONDAY + 86400
        self.write(genere_le=iso(tuesday), **dict(self.POINT, a_traiter=[item(1), item(2)]))
        self.assertEqual(self.open_keys(tuesday), dict(empty, a_traiter=['k2']))

    def test_same_key_same_title_stays_hidden_a_new_title_comes_back(self):
        # PM, 2026-11-09: « Fait » hides that item only, never a new request written later under the same key.
        self.write(a_traiter=[item(1, titre='Valider le devis')], brouillons=[td.draft(1)], preparer_demain=self.POINT['preparer_demain'][:1])
        for cle in ('k1', 'gmail:r-1', 'demain:ev1'):
            self.m.fait(cle, MONDAY)
        tuesday = MONDAY + 86400
        self.write(genere_le=iso(tuesday), a_traiter=[item(1, titre='  valider LE devis ', phrase='Autre phrase.')],
                   brouillons=[td.draft(1)], preparer_demain=self.POINT['preparer_demain'][:1])
        self.assertEqual(self.open_keys(tuesday), {'a_traiter': [], 'preparer_demain': [], 'brouillons': []},
                         'same key, same title (case, spaces and phrase aside): still hidden')
        wednesday = tuesday + 86400
        self.write(genere_le=iso(wednesday), a_traiter=[item(1, titre='Signer le bon de commande')],
                   brouillons=[td.draft(1, objet='Nouvel objet')],
                   preparer_demain=[dict(self.POINT['preparer_demain'][0], titre='Relire le planning')])
        self.assertEqual(self.open_keys(wednesday), {'a_traiter': ['k1'], 'preparer_demain': ['demain:ev1'], 'brouillons': ['gmail:r-1']},
                         'same key, new title: it comes back')
        self.assertEqual(self.m.fait('k1', wednesday), {'fait': 'k1'}, 'and it can be closed again')
        self.assertEqual(self.open_keys(wednesday)['a_traiter'], [])

    def test_the_older_state_is_still_read(self):
        self.state_file().write_text(json.dumps({'version': 1, 'jours': {'2026-10-30': ['k1']}, 'brouillons_vus': ['gmail:r-1']}),
                                     encoding='utf-8')
        self.write(**dict(self.POINT, a_traiter=[item(1), item(2)]))
        self.assertEqual(self.open_keys(MONDAY)['a_traiter'], ['k2'])
        self.assertEqual(self.open_keys(MONDAY)['brouillons'], [])
        self.m.fait('k2', MONDAY)
        state = json.loads(self.state_file().read_text(encoding='utf-8'))
        self.assertEqual(sorted(state['fermes']), ['gmail:r-1', 'k1', 'k2'])

    def test_the_state_keeps_the_most_recent_closings(self):
        self.write(**self.POINT)
        saved = self.m.FERMES_MAX
        self.m.FERMES_MAX = 2
        try:
            self.state_file().write_text(json.dumps({'version': 2, 'fermes': {'a': '2026-10-01', 'b': '2026-10-20'}}), encoding='utf-8')
            self.m.fait('k1', MONDAY)
        finally:
            self.m.FERMES_MAX = saved
        self.assertEqual(sorted(json.loads(self.state_file().read_text(encoding='utf-8'))['fermes']), ['b', 'k1'])

    def test_the_ingestion_items_closed_by_hand_hold_across_computations_and_mornings(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        m = self.p.matin_pour_la_page(MONDAY, self.metas, self.compute())
        demande, entree = m['demandes'][0]['cle'], m['entre_studio'][0]['cle']
        self.p.fermer(demande, MONDAY + 60)
        self.p.fermer(entree, MONDAY + 60)
        # The same report read again by a later run, and a new morning point: neither comes back.
        self.runs(self.alpha, (FRIDAY, REPORT), (MONDAY + 1800, REPORT))
        self.write(genere_le=iso(MONDAY + 3600), a_traiter=[item(1)])
        m = self.p.matin_pour_la_page(MONDAY + 3600, self.metas, self.compute(MONDAY + 3600))
        self.assertNotIn(demande, [x['cle'] for x in m['demandes']])
        self.assertNotIn(entree, [x['cle'] for x in m['entre_studio']])


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    run_page = tm.Page.run_page
    LISTE = {'projets': [{'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm', 'lignes': [
        {'cle': 'aaaaaaaaaaa1', 'type': 'a_toi', 'titre': 'Valider le devis', 'detail': '', 'depuis': 0, 'session': None},
        {'cle': 'bbbbbbbbbbb1', 'type': 'reunion', 'titre': 'Atelier', 'detail': '2026-11-06', 'depuis': 0, 'session': None},
        {'cle': 'eeeeeeeeeee1', 'type': 'entree', 'titre': 'CR rangé', 'detail': '', 'depuis': 0, 'session': None}]}]}
    MATIN = dict(tm.Page.MATIN,
                 preparer_demain=[{'cle': 'demain:ev1', 'titre': 'Relire le devis', 'phrase': 'Avant la réunion.', 'lien': ''}],
                 brouillons=[td.draft(1)],
                 demandes=[{'cle': 'aaaaaaaaaaa1', 'titre': 'Valider le devis', 'projet': 'Alpha', 'echeance': None, 'lien': '',
                            'dossier': '/S/Alpha', 'depuis': 0}],
                 entre_studio=[{'cle': 'eeeeeeeeeee1', 'projet': 'Alpha', 'titre': 'CR rangé', 'phrase': 'CR rangé',
                                'lien': 'https://docs.google.com/x', 'dossier': '/S/Alpha'}])
    ACTIONNABLES = {'data-matin-fait': ['k1', 'k2', 'k3', 'demain:ev1', 'gmail:r-1'],
                    'data-clore': ['eeeeeeeeeee1']}   # a new request is closed on the board (0.2.17)

    def buttons(self, h):
        return BUTTON.findall(h)

    def test_every_actionable_rubric_has_its_fait_button(self):
        h = self.run_page(matin=self.MATIN, liste_projets=self.LISTE, outils=['lignes', 'clore'])['matin']
        for attr, cles in self.ACTIONNABLES.items():
            for cle in cles:
                mot = 'Vu' if attr == 'data-clore' else 'Fait'   # « Pour info » entries are seen, not done
                self.assertIn((attr, cle, mot), self.buttons(h), cle)
        agenda = h.split('<ol class="frise"', 1)[1].split('</ol>', 1)[0]
        self.assertNotIn('class="fait"', agenda, 'the agenda only informs')
        h = self.run_page(matin=self.MATIN, liste_projets=self.LISTE, outils=['lignes', 'clore'],
                          cliquer=[['regle-bascule', '1']])['matin']
        regle = h.split('<ul class="liste regle">', 1)[1].split('</ul>', 1)[0]
        self.assertIn('devis envoyé', regle)
        self.assertNotIn('class="fait"', regle, '« Réglé » only informs')

    def test_one_word_everywhere_in_today_and_the_board_keeps_its_own(self):
        out = self.run_page(matin=self.MATIN, liste_projets=self.LISTE, outils=['lignes', 'clore'])
        mots = self.buttons(out['matin'])
        self.assertEqual({mot for _, _, mot in mots} | {'Tout vu'}, {'Fait', 'Vu', 'Tout vu'})
        self.assertEqual([(a, c) for a, c, mot in mots if mot == 'Vu'], [('data-clore', 'eeeeeeeeeee1')], '« Vu » on the entries only')
        self.assertIn('data-tout-vu="Alpha"', out['matin'])
        self.assertNotIn("plus d'actu", out['matin'])
        self.assertNotIn('Fait / Retirer du tableau', out['matin'], 'the board keeps its own label, Today « Fait »')

    def test_one_click_and_the_item_leaves_at_once(self):
        for attr, cle, call in (('data-matin-fait', 'demain:ev1', {'cle': 'demain:ev1', 'matin': True}),
                                ('data-matin-fait', 'gmail:r-1', {'cle': 'gmail:r-1', 'matin': True}),
                                ('data-clore', 'eeeeeeeeeee1', {'cle': 'eeeeeeeeeee1'})):
            out = self.run_page(matin=self.MATIN, liste_projets=self.LISTE, outils=['lignes', 'clore'], cliquer=[[attr, cle]])
            self.assertIn(['clore', call], out['appels'])
            self.assertIn(f'{attr}="{cle}"', out['matinAvant'])
            self.assertNotIn(f'{attr}="{cle}"', out['matin'])

    def test_without_the_clore_tool_no_button(self):
        h = self.run_page(matin=self.MATIN, liste_projets=self.LISTE, outils=['lignes'])['matin']
        self.assertEqual(self.buttons(h), [])


class Control(unittest.TestCase):
    LISTE = Page.LISTE
    MATIN = Page.MATIN

    def test_items_with_a_key_clore_takes_pass(self):
        self.assertEqual(controle.fermeture_today(self.MATIN, self.LISTE), [])
        self.assertEqual(controle.fermeture_today({'etat': 'pas_passe', 'demandes': [], 'entre_studio': []}, None), [])

    def test_a_missing_or_unknown_key_is_reported(self):
        matin = dict(self.MATIN, preparer_demain=[{'titre': 'Sans clé'}],
                     demandes=[dict(self.MATIN['demandes'][0], cle='ccccccccccc1')])
        found = controle.fermeture_today(matin, self.LISTE)
        self.assertEqual(sorted(a[1].split(' · ')[1] for a in found), ['preparer_demain'])
        self.assertTrue(all(a[0] == 'fermeture' for a in found))

    def test_a_missing_button_or_another_word_is_reported(self):
        html = ''.join(f'<button type="button" class="fait" {attr}="{controle.esc(c)}" title="x">Fait</button>'
                       for attr, cles in Page.ACTIONNABLES.items() for c in cles)
        self.assertEqual(controle.fermeture_today(self.MATIN, self.LISTE, html), [])
        sans = html.replace('data-matin-fait="demain:ev1"', '')
        self.assertIn('pas de bouton « Fait »', controle.fermeture_today(self.MATIN, self.LISTE, sans)[0][2])
        autre = html + '<button type="button" class="fait" data-clore="eeeeeeeeeee1" title="x">Fermer</button>'
        self.assertIn('« Fermer »', controle.fermeture_today(self.MATIN, self.LISTE, autre)[0][2])

    @unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
    def test_the_rendered_tab_passes(self):
        with tempfile.TemporaryDirectory() as d:
            html = controle.rendre_today(self.MATIN, self.LISTE, d)
        self.assertIn('data-matin-fait="k1"', html)
        self.assertEqual(controle.fermeture_today(self.MATIN, self.LISTE, html), [])


if __name__ == '__main__':
    unittest.main()
