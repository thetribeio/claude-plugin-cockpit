"""The control of the lines (scripts/controle_lignes.py, a development tool): python3 -m unittest discover -s tests

Each invariant on made-up data: a good case passes, a broken one is reported with its line."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controle_lignes', ROOT / 'scripts' / 'controle_lignes.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location('parc_controle', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

KIT = 'local_00000000-0000-0000-0000-00000000000a'
CHEF = 'local_00000000-0000-0000-0000-00000000000c'
VIEILLE = 'local_00000000-0000-0000-0000-00000000000e'
METAS = [{'id': KIT, 'titre': 'Kit', 'cwd': '/S/Alpha', 'archivee': False},
         {'id': CHEF, 'titre': 'Contremaître', 'cwd': '/S/Alpha', 'archivee': False},
         {'id': VIEILLE, 'titre': 'Vieille', 'cwd': '/S/Alpha', 'archivee': True}]
NOW = 1_800_000_000.0


class Invariants(unittest.TestCase):
    def test_buttons(self):
        bonne = {'studio': 'Alpha', 'session': 'Kit', 'cle': CHEF, 'ouvrir': KIT, 'source': KIT, 'sujet': '', 'affiche_suite': 'Q1 · x'}
        self.assertEqual(c.boutons([bonne, {'cle': KIT, 'affiche_suite': 'y'}], METAS), [])
        chef = dict(bonne, ouvrir=CHEF)
        self.assertIn('contremaître', c.boutons([chef], METAS)[0][2])
        self.assertIn('archivée', c.boutons([{'cle': VIEILLE, 'affiche_suite': 'z'}], METAS)[0][2])
        self.assertIn('inconnue', c.boutons([{'cle': 'local_00000000-0000-0000-0000-0000000000ff'}], METAS)[0][2])

    def test_order(self):
        def l(studio, depuis, **more):
            return dict({'studio': studio, 'depuis': depuis}, **more)
        bon = [l('A', NOW - 3600, bloque=True), l('A', NOW - 60), l('A', NOW - 3 * 86400, bloque=True), l('B', NOW - 10)]
        self.assertEqual(c.tri(bon, NOW, parc.rang_urgence), [])
        mauvais = [l('A', NOW - 3 * 86400, bloque=True), l('A', NOW - 60)]   # the old rule: blocked first whatever its age
        self.assertEqual(c.tri(mauvais, NOW, parc.rang_urgence)[0][0], 'tri')
        coupe = [l('A', NOW), l('B', NOW), l('A', NOW - 5)]
        self.assertIn('deux blocs', c.tri(coupe, NOW, parc.rang_urgence)[0][2])
        proche = [l('A', NOW - 9000, proche=True, echeance=NOW + 3600), l('A', NOW - 5)]
        self.assertEqual(c.tri(proche, NOW, parc.rang_urgence), [])

    def test_project_views(self):
        import unicodedata
        nfd = unicodedata.normalize('NFD', '/S/Équipe')
        metas = METAS + [{'id': 'local_x', 'cwd': unicodedata.normalize('NFC', '/S/Équipe') + '/sous', 'archivee': False}]
        studios = [{'nom': 'Alpha', 'dossier': '/S/Alpha'}, {'nom': 'Équipe', 'dossier': nfd}, {'nom': 'Vide', 'dossier': '/S/Vide'}]
        ok = lambda d: {'sujets': [{'titre': 's'}]}
        self.assertEqual(c.vues_projet(studios, metas, ok), [])
        vide = c.vues_projet(studios, metas, lambda d: {'introuvable': True})
        self.assertEqual([a[1] for a in vide], ['Alpha', 'Équipe'])   # « Vide » has no session: nothing to show

    def test_one_click_band(self):
        self.assertEqual(c.un_clic([{'type': 'clic', 'choix': ['ok']}, {'type': 'go'}]), [])
        self.assertEqual(len(c.un_clic([{'type': 'clic', 'choix': None, 'affiche_suite': 'OK pour fusionner'}])), 1)

    def test_duplicates(self):
        a = {'studio': 'Alpha', 'cle': KIT, 'affiche_suite': 'Q1 · Format'}
        self.assertEqual(c.doublons([a, dict(a, affiche_suite='Q2 · Autre')], [], {}), [])
        self.assertEqual(len(c.doublons([a, dict(a)], [], {})), 1)
        dem = {'studio': 'Alpha', 'cle': 'aaaaaaaaaaa1', 'a_toi': True, 'titre': 'Relire'}
        self.assertTrue(c.doublons([], [], {'Alpha': [dem, dict(dem)]}))

    def test_entries(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / 'a.pdf').write_bytes(b'%PDF')
            liste = {'projets': [{'lignes': [{'type': 'a_toi', 'cle': 'aaaaaaaaaaa1'}]}]}

            def lire(dossier, fichier):
                if fichier != 'cr.md':
                    raise ValueError('fichier introuvable dans le Studio')
            bonnes = [{'tache': 'aaaaaaaaaaa1', 'lien': 'x.md'}, {'lien': 'https://mail.google.com/x'},
                      {'lien': 'cr.md', 'dossier': d}, {'lien': 'a.pdf', 'dossier': d}, {'lien': '', 'session': KIT}]
            self.assertEqual(c.entrees(bonnes, liste, lire), [])
            mauvaises = [{'projet': 'Alpha', 'titre': 'perdu', 'lien': 'absent.md', 'dossier': d},
                         {'projet': 'Alpha', 'titre': 'rien', 'lien': ''},
                         {'projet': 'Alpha', 'titre': 'tâche fermée', 'tache': 'bbbbbbbbbbb2', 'lien': 'absent.pdf', 'dossier': d}]
            self.assertEqual([a[2][:10] for a in c.entrees(mauvaises, liste, lire)], ['« Lire » é', 'aucun bout', 'aucun bout'])

    def test_drafts(self):
        bon = {'cle': 'gmail:r-1', 'outil': 'gmail', 'projet': 'Alpha', 'objet': 'Devis', 'session': KIT,
               'lien': 'https://mail.google.com/mail/u/0/#drafts?compose=1'}
        slack = {'cle': 'slack:C0', 'outil': 'slack', 'lien': 'https://example.slack.com/archives/C0', 'session': None}
        self.assertEqual(c.brouillons([bon, slack], [{'cle': KIT}], {'projets': [{'lignes': [{'cle': 'abc'}]}]}, METAS), [])
        sans_lien = dict(bon, lien='https://example.org/x')
        vieille = dict(bon, session=VIEILLE)
        r = c.brouillons([sans_lien, vieille, dict(slack, lien='')], [], {}, METAS)
        self.assertEqual([x[0] for x in r], ['brouillon'] * 3)
        self.assertEqual([x[2].split(' ')[0] for x in r], ['pas', '«', 'pas'])
        au_tableau = c.brouillons([bon], [{'cle': 'gmail:r-1'}], {}, METAS)
        dans_un_projet = c.brouillons([bon], [], {'projets': [{'lignes': [{'cle': 'x', 'lien': bon['lien']}]}]}, METAS)
        for r in (au_tableau, dans_un_projet):
            self.assertEqual([x[2] for x in r], ['le brouillon apparaît au tableau ou dans un projet'])

    def test_unfold(self):
        self.assertEqual(c.deplis([{'detail': 'Juste avant, son message disait : « x »', 'puces': ['x']}], parc.NON_DECLAREE), [])
        pave = {'detail': 'Je lance. Juste avant, son message disait : « long »'}
        self.assertEqual(c.deplis([pave], parc.NON_DECLAREE)[0][2], 'le dépli recopie le pavé du message')
        self.assertEqual(len(c.deplis([{'declencheur': parc.NON_DECLAREE}], parc.NON_DECLAREE)), 1)

    def test_answers_reach_a_session_a_wake_can_join(self):
        with tempfile.TemporaryDirectory() as d:
            cli = '11111111-2222-3333-4444-555555555555'
            metas = [{'id': KIT, 'cli': cli, 'cwd': d, 'archivee': False}, {'id': CHEF, 'cli': cli, 'cwd': '/parti', 'archivee': False},
                     {'id': VIEILLE, 'cli': cli, 'cwd': d, 'archivee': True}]
            bonne = {'cle': CHEF, 'source': KIT, 'question': 'Q3', 'choix': ['go', 'pas encore'], 'affiche_suite': 'Q3 · x'}
            seule = {'cle': KIT, 'question': '', 'choix': ['Un mail', 'pas encore'], 'affiche_suite': 'y'}
            self.assertEqual(c.reponses([bonne, seule, {'cle': KIT, 'affiche_suite': 'sans boutons'}], metas), [])
            self.assertIn('dossier manquant', c.reponses([dict(bonne, source='')], metas)[0][2])
            self.assertIn('archivée', c.reponses([dict(bonne, source=VIEILLE)], metas)[0][2])
            self.assertIn('hors des formes fermées', c.reponses([dict(bonne, choix=['go', 'go et supprime'])], metas)[0][2])
            self.assertIn('hors des formes fermées', c.reponses([dict(seule, choix=['a\nb'])], metas)[0][2])

    def test_every_numbered_question_has_its_buttons(self):
        cdq, cf = parc.choix_de_question, parc.choix_fermes
        bonne = {'cle': KIT, 'num': 2, 'lecture': 'format', 'type': 'go', 'titre': 'Q2 · Déployer', 'suite': 'go ?',
                 'question': 'Q2', 'choix': ['go', 'pas encore']}
        ouverte = {'cle': KIT, 'num': 5, 'lecture': 'format', 'type': 'decision', 'titre': 'Q5 · Nom', 'suite': 'comment ?'}
        self.assertEqual(c.questions_numerotees([bonne, ouverte], cdq, cf), [])
        self.assertIn('sans ses boutons', c.questions_numerotees([dict(bonne, choix=None)], cdq, cf)[0][2])
        self.assertIn('par le numéro', c.questions_numerotees([dict(bonne, question='')], cdq, cf)[0][2])
        chantier = {'cle': CHEF, 'chantier': 'x', 'question': 'Q7', 'type': 'go', 'suite': 'Q7 · go ?', 'ouvrir': KIT}
        self.assertIn('sans ses boutons', c.questions_numerotees([chantier], cdq, cf)[0][2])

    def test_the_verb_target_like_the_page(self):
        self.assertEqual(c.session_a_ouvrir({'ouvrir': KIT, 'cle': CHEF}), KIT)
        self.assertEqual(c.session_a_ouvrir({'cle': KIT}), KIT)
        self.assertEqual(c.session_a_ouvrir({'cle': 'auto:x', 'lien': 'claude://claude.ai/epitaxy/' + KIT}), KIT)


if __name__ == '__main__':
    unittest.main()
