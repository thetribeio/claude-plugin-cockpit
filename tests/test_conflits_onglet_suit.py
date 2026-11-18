"""The « Conflits » tab follows the register as soon as the conflicts skill writes it: python3 -m unittest discover -s tests

The connector cannot read the Drive (macOS refuses it): it reads the register from Mon Studio's snapshot
(~/Mon Studio/.parc/projets-sources.json). That snapshot was refreshed by a hook at a session's start and turn's end,
five minutes at most often: right after the first relevé (2026-11-18) the tab showed no case while the register held 19.
Now conflits.py copies the register into the snapshot itself after every write, without an LLM; a later refresh read
before that copy never brings the old register back; and when the conflicts session worked after the copy the tab says
the copy may lag instead of looking empty. Synthetic Studio (tests/_studio_conflits.py)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('conflits_suit', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)
spec = importlib.util.spec_from_file_location('projets_suit', SCRIPTS / 'projets.py')
projets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projets)

JUGEMENTS = [
    {'sujet': 'S1', 'classe': 'M', 'titre': 'Comité de pilotage le jeudi', 'passages': ['E1.1', 'E1.2']},
    {'sujet': 'S2', 'classe': 'PM', 'titre': 'Plafond de remise relevé', 'passages': ['E2.1', 'E2.2'],
     'contexte': "Les règles de septembre limitaient la remise à 10 % ; au point du 3 novembre, elle passe à 15 %.",
     'recommande': 'remplacer', 'pourquoi': 'La règle PRJ-2 est plus récente que PRJ-1.'},
    {'sujet': 'S3', 'classe': 'M', 'titre': 'Format d’export des commandes', 'passages': ['E3.1']},
]


class Suit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.studio = F.make(base / 'Studio - Projet Alpha')
        self.d = str(self.studio)
        self.parc = base / 'Mon Studio' / '.parc'
        self.parc.mkdir(parents=True)
        for p in (unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-10', 'MON_STUDIO': str(base / 'Mon Studio')}),
                  unittest.mock.patch.object(projets.parc, 'INTERNE', self.parc)):
            p.start()
            self.addCleanup(p.stop)
        # The snapshot as the hook left it a few minutes before the relevé: the Studio known, its register empty.
        self.avant = time.time() - 120
        self.ecrire_snapshot({self.d: {'pm': None, 'passages': [], 'reglees': [], 'lu': self.avant, 'conflits': '',
                                       'conflits_vu': None, 'conflits_reglages': None}})
        self.plan = base / 'plan.json'

    def ecrire_snapshot(self, dossiers):
        (self.parc / 'projets-sources.json').write_text(json.dumps({'version': 1, 'ecrit': self.avant, 'dossiers': dossiers}),
                                                        encoding='utf-8')

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = conflits.main([str(a) for a in args])
        return code, out.getvalue()

    def onglet(self, metas=()):
        """The tab as the connector computes it: every read of the register on the Drive refused."""
        vrai = projets.lire_texte

        def lire(chemin):
            if str(chemin).endswith('conflits.md'):
                raise PermissionError()
            return vrai(chemin)
        with unittest.mock.patch.object(projets, 'lire_texte', side_effect=lire):
            return projets.conflits_du_projet(self.d, list(metas), instantane=projets.lire_instantane(), depuis_connecteur=True)

    def releve_juge(self):
        self.assertEqual(self.cli('releve', self.d, '--sortie', self.plan)[0], 0)
        j = self.plan.with_name('jugements.json')
        j.write_text(json.dumps(JUGEMENTS, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.cli('juger', self.plan, j)[0], 0)

    def test_the_tab_shows_the_cases_right_after_the_first_write(self):
        self.releve_juge()
        self.assertEqual(self.onglet()['ouverts'], [])          # before the go: nothing in the register yet
        code, out = self.cli('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules')
        self.assertEqual(code, 0, out)
        c = self.onglet()
        self.assertTrue(c['lu'])
        self.assertEqual(len(c['ouverts']), 1, out)
        self.assertEqual(c['ouverts'][0]['sujet'], 'Plafond de remise relevé')
        self.assertFalse(c['en_retard'])
        self.assertNotIn('Mon Studio', out)                     # the copy is silent when it works

    def test_a_settled_case_leaves_the_tab_at_once(self):
        self.releve_juge()
        self.cli('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules')
        cid = self.onglet()['ouverts'][0]['id']
        code, out = self.cli('trancher', self.d, cid, 'remplacer', '--pm', 'Camille')
        self.assertEqual(code, 0, out)
        c = self.onglet()
        self.assertEqual((c['ouverts'], c['tranches']), ([], 1))
        self.cli('rouvrir', self.d, cid)
        self.assertEqual(len(self.onglet()['ouverts']), 1)

    def test_every_writing_command_copies_the_register(self):
        appels = []
        with unittest.mock.patch.object(conflits.registre, 'copier_dans_mon_studio', side_effect=lambda s: appels.append(s) or True):
            self.releve_juge()
            self.assertEqual(appels, [])                        # the relevé and the judging write nothing in the Studio
            for args in (('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules'),
                         ('formulaires', self.plan), ('evidents', self.plan),
                         ('valider', self.plan, '--pm', 'Camille'),
                         ('repondre', self.plan, '--pm', 'Camille', '--reponses', '[]'),
                         ('ouverts', self.d), ('attente', self.d), ('regler', self.d, '--cas', '5'),
                         ('cloturer', self.plan)):
                del appels[:]
                self.cli(*args)
                self.assertEqual([os.path.realpath(a) for a in appels], [os.path.realpath(self.d)], args)

    def test_without_mon_studio_nothing_is_written_and_nothing_fails(self):
        shutil.rmtree(self.parc.parent)
        self.releve_juge()
        code, out = self.cli('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules')
        self.assertEqual(code, 0, out)
        self.assertFalse(self.parc.parent.exists())
        self.assertNotIn('Mon Studio', out)

    def test_a_failed_copy_is_said_in_the_session(self):
        self.releve_juge()
        with unittest.mock.patch.object(conflits.registre, 'copier_dans_mon_studio', return_value=False):
            code, out = self.cli('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules')
        self.assertEqual(code, 0)
        self.assertIn("L'onglet Conflits de Mon Studio suivra", out)

    def test_a_refresh_read_before_the_copy_never_brings_the_old_register_back(self):
        lu_avant = time.time() - 1                              # projets.py started reading before the write
        ancien = projets.lire_sources(self.d, lu_avant)
        self.releve_juge()
        self.cli('ecrire', self.plan, '--pm', 'Camille', '--decisions-seules')
        ancien['conflits'] = ''                                 # what it had read then
        projets.ecrire_instantane({self.d: ancien}, lu_avant)
        self.assertEqual(len(self.onglet()['ouverts']), 1)
        neuf = projets.lire_sources(self.d, time.time() + 1)    # a later full read wins again
        projets.ecrire_instantane({self.d: neuf}, time.time() + 1)
        self.assertEqual(len(self.onglet()['ouverts']), 1)
        self.assertNotIn('conflits_copie', projets.lire_instantane()[self.d])

    def test_the_tab_says_when_the_copy_may_lag(self):
        session = {'id': 'local_' + '1' * 36, 'cwd': self.d, 'titre': 'Projet Alpha · Conflits Studio',
                   'activite': time.time(), 'archivee': False}
        c = self.onglet([session])                              # the session worked after the hook's copy
        self.assertTrue(c['en_retard'])
        self.assertEqual(c['ouverts'], [])
        session['activite'] = self.avant - 600                  # nothing since the copy: no lag to say
        self.assertFalse(self.onglet([session])['en_retard'])


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def test_a_lagging_copy_is_said_instead_of_an_empty_tab(self):
        c = {'ouverts': [], 'illisibles': 0, 'session': None, 'titre_session': 'Projet Alpha · Conflits Studio',
             'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False, 'raison': '',
             'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': None, 'journal': [],
             'tranches': 0, 'verification': 'jamais', 'premiere': None, 'relecture': None, 'en_retard': True,
             'copie_le': '18/11 09:11', 'texte_premiere': "Le premier relevé des conflits n'est pas encore fait."}
        vue = {'dossier': self.A, 'nom': 'Projet Alpha', 'genere': 0, 'questions': [], 'anciennes': [], 'sujets': [],
               'tiers': [], 'journal': [], 'conflits': c}
        payload = {'lignes': [], 'projets': [{'studio': 'Projet Alpha', 'dossier': self.A, 'nom': 'Projet Alpha'}],
                   'projet': vue, 'cliquer': [['data-projet', self.A], ['data-vue-conflits', 'conflits']]}
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(ROOT / 'tests' / 'tester-epinglee.js'),
                                str(ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'), str(data)],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        texte = json.loads(r.stdout)['projetConflits']
        self.assertIn('copie du registre lue à 18/11 09:11', texte)
        self.assertNotIn("pas encore fait", texte)


if __name__ == '__main__':
    unittest.main()
