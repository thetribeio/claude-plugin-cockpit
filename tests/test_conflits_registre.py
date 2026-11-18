"""Tests of the conflict register reader and writer (skills/conflits/scripts/registre.py):
python3 -m unittest discover -s tests

The format is the shared one of `projet/conflits.md` (read later by /studio:auto-ingest as it is): one level-3 heading
per case, fixed field lines, ids never reused, append only, only the État line changes, an unreadable case reported
without blocking the others, DD/MM/YYYY dates. Synthetic, neutral data."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import os
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('registre_conflits', ROOT / 'skills' / 'conflits' / 'scripts' / 'registre.py')
registre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registre)

EXEMPLE = """# Registre des conflits

### C1 · Jour du comité de pilotage
- **Détecté le** : 12/11/2026
- **Ancienne valeur** : comité de pilotage le premier mardi du mois (source : projet/regles.md, 02/09/2026)
- **Nouvelle valeur** : comité de pilotage le jeudi, à partir de décembre (source : sources/2026-11-10-mail.md, 10/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : ouvert

### C2 · Plafond de remises
- **Détecté le** : 04/11/2026
- **Ancienne valeur** : remise limitée à 10 % (source : projet/regles.md, 15/09/2026)
- **Nouvelle valeur** : remise portée à 15 % (source : sources/2026-11-03-cr.md, 03/11/2026)
- **Déjà communiqué au client** : oui
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : tranché le 06/11/2026 par Camille : remplacer
"""
ANCIENNE = {'texte': 'livraison le lundi', 'source': 'projet/regles-metier.md', 'date': '01/09/2026'}
NOUVELLE = {'texte': 'livraison le mercredi', 'source': 'sources/2026-11-02-cr.md', 'date': '02/11/2026'}


class Lire(unittest.TestCase):
    def test_reads_the_format_example(self):
        r = registre.lire(EXEMPLE)
        self.assertEqual([c['id'] for c in r['cas']], ['C1', 'C2'])
        self.assertEqual(r['illisibles'], [])
        c1, c2 = r['cas']
        self.assertEqual(c1['ancienne'], {'texte': 'comité de pilotage le premier mardi du mois',
                                          'source': 'projet/regles.md', 'date': '02/09/2026'})
        self.assertFalse(c1['communique'])
        self.assertEqual(c1['etat'], 'ouvert')
        self.assertEqual(c2['tranche'], {'date': '06/11/2026', 'par': 'Camille', 'choix': 'remplacer'})

    def test_an_unreadable_case_does_not_block_the_others(self):
        texte = EXEMPLE.replace('- **Déjà communiqué au client** : non', '- **Déjà communiqué au client** : peut-être')
        r = registre.lire(texte)
        self.assertEqual([c['id'] for c in r['cas']], ['C2'])
        self.assertEqual(r['illisibles'][0]['id'], 'C1')
        self.assertIn('hors format', r['illisibles'][0]['erreurs'][0])

    def test_a_missing_field_is_unreadable(self):
        texte = EXEMPLE.replace('- **Détecté le** : 04/11/2026\n', '')
        r = registre.lire(texte)
        self.assertEqual(r['illisibles'][0]['id'], 'C2')
        self.assertIn('absent', ' '.join(r['illisibles'][0]['erreurs']))

    def test_unknown_field_and_outside_text_are_ignored(self):
        texte = EXEMPLE.replace('# Registre des conflits\n', '# Registre des conflits\n\nUn mot.\nDernier passage : 09/11/2026\n')
        texte = texte.replace('- **Options** : remplacer', '- **Autre** : rien\n- **Options** : remplacer', 1)
        r = registre.lire(texte)
        self.assertEqual(len(r['cas']), 2)
        self.assertEqual(r['dernier_passage'], '09/11/2026')

    def test_absent_file_has_no_case(self):
        r = registre.lire_fichier(pathlib.Path(tempfile.mkdtemp()) / 'absent.md')
        self.assertEqual((r['cas'], r['illisibles']), ([], []))

    def test_iso_conversion(self):
        self.assertEqual(registre.iso('06/11/2026'), '2026-11-06')
        self.assertIsNone(registre.iso('2026-11-06'))


class Ecrire(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.chemin = self.dir / 'projet' / 'conflits.md'

    def test_first_case_creates_the_file_as_c1(self):
        cid = registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False, '10/11/2026')
        self.assertEqual(cid, 'C1')
        texte = self.chemin.read_text(encoding='utf-8')
        self.assertTrue(texte.startswith('# Registre des conflits\n'))
        self.assertIn('### C1 · Jour de livraison\n- **Détecté le** : 10/11/2026\n', texte)
        self.assertIn('- **Options** : remplacer · à confirmer avec le client · simple discussion\n- **État** : ouvert\n', texte)
        self.assertEqual(registre.lire(texte)['cas'][0]['nouvelle'], NOUVELLE)

    def test_append_only_and_ids_never_reused(self):
        self.chemin.parent.mkdir(parents=True)
        # C2 unreadable, C1 gone (deleted by hand): the next id still follows the largest one found.
        texte = EXEMPLE.replace('### C1 ·', '### C5 ·').replace('- **Détecté le** : 04/11/2026\n', '')
        self.chemin.write_text(texte, encoding='utf-8')
        cid = registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, True, '10/11/2026')
        self.assertEqual(cid, 'C6')
        apres = self.chemin.read_text(encoding='utf-8')
        self.assertTrue(apres.startswith(texte))             # nothing before changed
        self.assertTrue(apres.rstrip().endswith('- **État** : ouvert'))

    def test_the_same_case_is_never_registered_twice(self):
        a = registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False)
        b = registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False)
        self.assertEqual(a, b)
        self.assertEqual(len(registre.lire_fichier(self.chemin)['cas']), 1)

    def test_a_multiline_value_is_written_on_one_line(self):
        registre.ajouter(self.chemin, 'Sujet\nsur deux lignes', dict(ANCIENNE, texte='a\nb'), NOUVELLE, False)
        r = registre.lire_fichier(self.chemin)
        self.assertEqual(r['cas'][0]['sujet'], 'Sujet sur deux lignes')
        self.assertEqual(r['cas'][0]['ancienne']['texte'], 'a b')

    def test_only_the_state_line_changes(self):
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_text(EXEMPLE, encoding='utf-8')
        registre.changer_etat(self.chemin, 'C1', 'simple discussion', 'Camille', '2026-11-10')
        apres = self.chemin.read_text(encoding='utf-8')
        avant_l, apres_l = EXEMPLE.splitlines(), apres.splitlines()
        diff = [(a, b) for a, b in zip(avant_l, apres_l) if a != b]
        self.assertEqual(diff, [('- **État** : ouvert', '- **État** : tranché le 10/11/2026 par Camille : simple discussion')])
        c1 = registre.lire(apres)['cas'][0]
        self.assertEqual(c1['tranche']['choix'], 'simple discussion')

    def test_reopen_and_unknown_choice(self):
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_text(EXEMPLE, encoding='utf-8')
        registre.changer_etat(self.chemin, 'C2')
        self.assertEqual(registre.lire_fichier(self.chemin)['cas'][1]['etat'], 'ouvert')
        with self.assertRaises(ValueError):
            registre.changer_etat(self.chemin, 'C1', 'Garder tel quel', 'Camille')
        with self.assertRaises(KeyError):
            registre.changer_etat(self.chemin, 'C9', 'remplacer', 'Camille')

    def test_crlf_file_keeps_its_line_ends(self):
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_bytes(EXEMPLE.replace('\n', '\r\n').encode('utf-8'))
        registre.changer_etat(self.chemin, 'C1', 'remplacer', 'Camille', '2026-11-10')
        registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False)
        brut = self.chemin.read_bytes().decode('utf-8')
        self.assertNotIn('\n', brut.replace('\r\n', ''))
        self.assertEqual(len(registre.lire(brut)['cas']), 3)

    def test_last_pass_line_sits_outside_any_case(self):
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_text(EXEMPLE, encoding='utf-8')
        registre.poser_dernier_passage(self.chemin, '2026-11-09')
        registre.poser_dernier_passage(self.chemin, '2026-11-10')
        texte = self.chemin.read_text(encoding='utf-8')
        self.assertEqual(texte.count('Dernier passage'), 1)
        self.assertTrue(texte.startswith('# Registre des conflits\n\nDernier passage : 10/11/2026\n'))
        r = registre.lire(texte)
        self.assertEqual(r['dernier_passage'], '10/11/2026')
        self.assertEqual(len(r['cas']), 2)
        self.assertEqual(r['illisibles'], [])
        # Removing that line gives back the file byte for byte.
        self.assertEqual(texte.replace('Dernier passage : 10/11/2026\n\n', ''), EXEMPLE)

    def test_last_pass_on_an_absent_register(self):
        registre.poser_dernier_passage(self.chemin, '2026-11-10')
        self.assertEqual(registre.lire_fichier(self.chemin)['dernier_passage'], '10/11/2026')
        self.assertEqual(registre.ajouter(self.chemin, 'Sujet', ANCIENNE, NOUVELLE, False), 'C1')



class Concurrence(unittest.TestCase):
    """Review of 2026-11-10: the night ingestion may append a case while the session writes; the Drive keeps a file's
    identity; a file that cannot be read is never rewritten."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.chemin = self.dir / 'projet' / 'conflits.md'
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_text(EXEMPLE, encoding='utf-8')

    def test_a_case_is_appended_without_rewriting_the_file(self):
        inode = os.stat(self.chemin).st_ino
        registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False)
        registre.changer_etat(self.chemin, 'C3', 'remplacer', 'Camille', '2026-11-10')
        self.assertEqual(os.stat(self.chemin).st_ino, inode)

    def test_a_held_lock_makes_the_writer_wait_then_give_up(self):
        lock = self.chemin.with_name('.conflits.md.lock')
        lock.write_text('')
        with unittest.mock.patch.object(registre, 'VERROU_S', 0.3):
            with self.assertRaises(registre.Change):
                registre.changer_etat(self.chemin, 'C1', 'remplacer', 'Camille')
        self.assertEqual(self.chemin.read_text(encoding='utf-8'), EXEMPLE)

    def test_a_dead_lock_is_taken_over(self):
        lock = self.chemin.with_name('.conflits.md.lock')
        lock.write_text('')
        os.utime(lock, (1, 1))
        registre.changer_etat(self.chemin, 'C1', 'remplacer', 'Camille')
        self.assertFalse(lock.exists())

    def test_a_change_between_read_and_write_writes_nothing(self):
        def autre(texte):
            with open(self.chemin, 'a', encoding='utf-8') as f:
                f.write('\n### C9 · Ajouté par la nuit\n')
            return texte + 'x'
        with self.assertRaises(registre.Change):
            registre.modifier(self.chemin, autre)
        self.assertTrue(self.chemin.read_text(encoding='utf-8').endswith('### C9 · Ajouté par la nuit\n'))

    def test_an_unreadable_register_is_never_written(self):
        self.chemin.write_bytes('# Registre des conflits\n\nr\xe9sum\xe9 en latin-1\n'.encode('latin-1'))
        avant = self.chemin.read_bytes()
        with self.assertRaises(registre.Illisible):
            registre.ajouter(self.chemin, 'Jour de livraison', ANCIENNE, NOUVELLE, False)
        with self.assertRaises(registre.Illisible):
            registre.poser_dernier_passage(self.chemin, '2026-11-10')
        self.assertEqual(self.chemin.read_bytes(), avant)

    def test_a_leftover_tmp_is_removed(self):
        tmp = self.chemin.with_name('.conflits.md.tmp')
        tmp.write_text('reste')
        registre.poser_dernier_passage(self.chemin, '2026-11-10')
        self.assertFalse(tmp.exists())


if __name__ == '__main__':
    unittest.main()
