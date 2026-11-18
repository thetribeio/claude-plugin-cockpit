"""Tests of hooks/rangement.py: only a finished one-action session is archived, never a dialogue, never on a doubt.
python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = charger('rangement', ROOT / 'hooks' / 'rangement.py')
parc = charger('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')

NOW = 2_000_000_000.0
H = 24


def finie(**kw):
    """The facts of a session that passes every guard."""
    f = {'id': 'local_aaaa', 'titre': 'Alpha · Vérifier un lien', 'parent': 'local_mere', 'parent_titre': 'Alpha · Suivi',
         'jetable': False, 'detachee': False, 'epinglee': False, 'exemptee': False, 'humains': 0, 'repondu': True,
         'etat': 'attend',
         'texte': 'Le lien est vérifié : il ouvre la bonne page.\n\nRien à faire de ton côté.', 'prio': None,
         'carte': False, 'encadre': False, 'besoin': False, 'au_tableau': False, 'activite': NOW - 30 * 3600,
         'dossier_sale': False, 'dossier_partage': False, 'filles_en_route': False}
    f.update(kw)
    return f


class Verdict(unittest.TestCase):
    def juge(self, **kw):
        return rg.juger(finie(**kw), H, NOW, parc)

    def test_finished_daughter_is_archived_with_its_reason(self):
        ok, why = self.juge()
        self.assertTrue(ok)
        self.assertIn('Alpha · Suivi', why)

    def test_marked_session_without_mother_is_archived(self):
        self.assertTrue(self.juge(parent=None, parent_titre=None, jetable=True)[0])

    def test_never_a_dialogue_session(self):
        ok, why = self.juge(parent=None, parent_titre=None, jetable=False)
        self.assertFalse(ok)
        self.assertIn('dialogue', why)

    def test_daughter_where_claude_answered_the_pm_last_is_archived(self):
        self.assertTrue(self.juge(humains=3, repondu=True)[0])

    def test_never_when_the_pm_last_message_is_unanswered(self):
        ok, why = self.juge(humains=1, repondu=False)
        self.assertFalse(ok)
        self.assertIn('attend la réponse', why)

    def test_daughter_answered_still_needs_every_other_guard(self):
        for kw in ({'texte': 'Fait.\n\nJe l’envoie ?'}, {'activite': NOW - 3600}, {'au_tableau': True},
                   {'dossier_sale': True}, {'filles_en_route': True}, {'epinglee': True}, {'detachee': True},
                   {'titre': '📬 Alpha'}, {'texte': 'Encore à faire : relire.'}, {'etat': 'main'}):
            self.assertFalse(self.juge(humains=2, repondu=True, **kw)[0], kw)

    def test_never_a_marked_session_the_pm_wrote_in(self):
        ok, why = self.juge(parent=None, parent_titre=None, jetable=True, humains=1, repondu=True)
        self.assertFalse(ok)
        self.assertIn('dialogue', why)

    def test_never_a_session_the_pm_opened_even_answered(self):
        ok, why = self.juge(parent=None, parent_titre=None, humains=4, repondu=True)
        self.assertFalse(ok)
        self.assertIn('dialogue', why)

    def test_never_a_mailbox_title(self):
        self.assertFalse(self.juge(titre='📬 Alpha · Boîte')[0])

    def test_never_pinned(self):
        self.assertFalse(self.juge(epinglee=True)[0])

    def test_never_exempted_in_the_app(self):
        self.assertFalse(self.juge(exemptee=True)[0])

    def test_never_moved_to_the_top_level(self):
        self.assertFalse(self.juge(detachee=True)[0])

    def test_never_while_working_or_stuck(self):
        for etat in ('travaille', 'suspens', 'erreur', 'main', None):
            self.assertFalse(self.juge(etat=etat)[0], etat)

    def test_never_with_a_numbered_question(self):
        self.assertFalse(self.juge(texte='Fait.\n\n**À trancher**\n\nQ3 · Envoi : je propose lundi.')[0])

    def test_never_with_still_open(self):
        self.assertFalse(self.juge(texte='Fait.\n\nEncore ouvert : Q3 · Envoi (lundi ou mardi).')[0])

    def test_never_with_a_final_question_mark(self):
        self.assertFalse(self.juge(texte='Le lien est vérifié.\n\nJe l’envoie à l’équipe ?')[0])

    def test_never_with_an_app_card_question_or_menu(self):
        self.assertFalse(self.juge(carte=True)[0])
        self.assertFalse(self.juge(encadre=True)[0])
        self.assertFalse(self.juge(besoin=True)[0])

    def test_never_when_an_action_is_awaited(self):
        self.assertFalse(self.juge(prio=2)[0])

    def test_never_when_gestures_are_handed_to_the_pm(self):
        self.assertFalse(self.juge(texte='Pilote poussé.\n\n**Tes gestes**\n- Faire relire les tickets par le lead dev.')[0])
        self.assertFalse(self.juge(texte='Brouillon prêt. À toi de jouer : l’envoyer lundi.')[0])

    def test_never_when_work_is_said_left(self):
        self.assertFalse(self.juge(texte='Vague faite. Encore à faire : réindexer 3 pages.')[0])

    def test_never_with_a_line_on_the_board(self):
        self.assertFalse(self.juge(au_tableau=True)[0])

    def test_never_before_the_quiet_hours(self):
        ok, why = self.juge(activite=NOW - 3 * 3600)
        self.assertFalse(ok)
        self.assertIn('seuil', why)

    def test_never_with_unsaved_files_or_an_unreadable_folder(self):
        self.assertFalse(self.juge(dossier_sale=True)[0])
        self.assertFalse(self.juge(dossier_sale=None)[0])

    def test_never_with_a_shared_folder(self):
        self.assertFalse(self.juge(dossier_partage=True)[0])

    def test_never_with_a_daughter_under_way(self):
        self.assertFalse(self.juge(filles_en_route=True)[0])

    def test_never_with_an_unreadable_transcript(self):
        self.assertFalse(self.juge(humains=None)[0])


def ligne(kind=None, texte='', meta=False, tool=False):
    contenu = [{'type': 'tool_result', 'content': 'x'}] if tool else texte
    o = {'type': 'user', 'message': {'role': 'user', 'content': contenu}}
    if kind:
        o['origin'] = {'kind': kind}
    if meta:
        o['isMeta'] = True
    return json.dumps(o)


def reponse(texte):
    contenu = [{'type': 'text', 'text': texte}] if texte else [{'type': 'tool_use', 'name': 'Bash', 'input': {}}]
    return json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'model': 'm', 'content': contenu}})


class Transcript(unittest.TestCase):
    def ecrire(self, lignes):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        p = os.path.join(d, 't.jsonl')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lignes) + '\n')
        return p

    def test_brief_from_a_session_is_not_the_pm(self):
        p = self.ecrire([ligne(None, 'Background (from the session that started this one): vérifier'),
                         ligne(tool=True), ligne('peer', 'Another Claude session sent a message'),
                         ligne(None, 'skill', meta=True)])
        self.assertEqual(rg.humains_et_marqueur(p, parc), (0, False, True))

    def test_pm_message_counts_and_waits_for_claude(self):
        p = self.ecrire([ligne(None, 'Background: vérifier'), reponse('Vérifié.'), ligne('human', 'Et le second lien ?')])
        self.assertEqual(rg.humains_et_marqueur(p, parc), (1, False, False))

    def test_pm_message_answered_after_it(self):
        p = self.ecrire([ligne(None, 'Background: vérifier'), ligne('human', 'Et le second lien ?'),
                         reponse('Le second aussi.'), ligne('peer', 'Another Claude session sent a message')])
        self.assertEqual(rg.humains_et_marqueur(p, parc), (1, False, True))

    def test_tool_call_without_text_is_not_an_answer(self):
        p = self.ecrire([ligne(None, 'Background: vérifier'), ligne('human', 'Et le second ?'), reponse('')])
        self.assertEqual(rg.humains_et_marqueur(p, parc), (1, False, False))

    def test_pasted_brief_with_the_marker_is_not_a_dialogue(self):
        p = self.ecrire([ligne('human', '[jetable] Vérifie ce lien et rends le résultat.')])
        self.assertEqual(rg.humains_et_marqueur(p, parc), (0, True, True))

    def test_unreadable_transcript_is_a_doubt(self):
        self.assertEqual(rg.humains_et_marqueur('/nonexistent/t.jsonl', parc), (None, False, False))


class Folder(unittest.TestCase):
    def test_no_folder_is_clean(self):
        self.assertFalse(rg.dossier_sale(None))
        self.assertFalse(rg.dossier_sale('/nonexistent/folder'))

    def test_uncommitted_file_is_unsaved(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        subprocess.run(['git', 'init', '-q', d], check=True)
        self.assertFalse(rg.dossier_sale(d))
        pathlib.Path(d, 'notes.md').write_text('x')
        self.assertTrue(rg.dossier_sale(d))

    def test_folder_that_is_not_a_repository_is_a_doubt(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        self.assertIsNone(rg.dossier_sale(d))


class Hook(unittest.TestCase):
    def setUp(self):
        self.ms = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ms)
        (self.ms / '.parc').mkdir()
        self.anciens = {k: getattr(rg, k) for k in ('MON_STUDIO', 'INTERNAL', 'STATE', 'OUT', 'LOCK',
                                                    'lancer_calcul_detache')}
        rg.MON_STUDIO, rg.INTERNAL = self.ms, self.ms / '.parc'
        rg.STATE, rg.OUT, rg.LOCK = rg.INTERNAL / 'cockpit.json', rg.INTERNAL / 'rangement.json', rg.INTERNAL / 'r.lock'
        self.lancements = []
        rg.lancer_calcul_detache = lambda: self.lancements.append(1)
        self.etat({})
        cartes = {'a': {'cli': 'cli-pm', 'id': 'local_pm', 'parent': None, 'tache': None, 'archivee': False},
                  'b': {'cli': 'cli-fille', 'id': 'local_fille', 'parent': 'local_pm', 'tache': None, 'archivee': False},
                  'c': {'cli': 'cli-tache', 'id': 'local_tache', 'parent': None, 'tache': 'point-du-matin',
                        'archivee': False}}
        (rg.INTERNAL / 'cache.json').write_text(json.dumps({'fiches': {k: {'meta': v} for k, v in cartes.items()}}))
        self.liste([{'id': 'local_x', 'titre': 'Alpha · Essai', 'raison': 'r'},
                    {'id': 'local_pm', 'titre': 'Alpha · Fil', 'raison': 'r'}])

    def tearDown(self):
        for k, v in self.anciens.items():
            setattr(rg, k, v)

    def etat(self, d):
        rg.STATE.write_text(json.dumps(d))

    def liste(self, a_ranger, **kw):
        rg.OUT.write_text(json.dumps(dict({'calcule': NOW, 'a_ranger': a_ranger, 'confiees': {}, 'rangees': []}, **kw)))

    def test_hands_the_list_once_to_a_pm_session_never_itself(self):
        texte = rg.hook({'session_id': 'cli-pm'}, NOW)
        self.assertIn('local_x', texte)
        self.assertNotIn('local_pm', texte)
        self.assertIn('archive_session', texte)
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW + 60), '')
        self.assertIn('local_x', json.loads(rg.OUT.read_text())['confiees'])

    def test_a_session_handed_but_still_open_is_handed_again_after_six_hours(self):
        self.assertIn('local_x', rg.hook({'session_id': 'cli-pm'}, NOW))
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW + 5 * 3600), '')
        texte = rg.hook({'session_id': 'cli-pm'}, NOW + 7 * 3600)
        self.assertIn('local_x', texte)
        self.assertEqual(json.loads(rg.OUT.read_text())['confiees']['local_x']['essais'], 2)

    def test_after_three_tries_it_is_no_longer_handed(self):
        rg.hook({'session_id': 'cli-pm'}, NOW)
        rg.hook({'session_id': 'cli-pm'}, NOW + 7 * 3600)
        self.assertIn('local_x', rg.hook({'session_id': 'cli-pm'}, NOW + 14 * 3600))
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW + 21 * 3600), '')

    def test_a_hand_off_from_before_the_tries_counter_counts_as_one(self):
        self.liste([{'id': 'local_x', 'titre': 'Alpha · Essai', 'raison': 'r'}],
                   confiees={'local_x': {'quand': NOW - 8 * 3600, 'titre': 'Alpha · Essai'}})
        self.assertIn('local_x', rg.hook({'session_id': 'cli-pm'}, NOW))
        self.assertEqual(json.loads(rg.OUT.read_text())['confiees']['local_x']['essais'], 2)

    def test_not_to_a_daughter_a_scheduled_run_or_an_unknown_session(self):
        for cli in ('cli-fille', 'cli-tache', 'cli-inconnue', None):
            self.assertEqual(rg.hook({'session_id': cli}, NOW), '', cli)

    def test_switch_off_and_disabled_say_nothing(self):
        self.etat({'rangement_auto': False})
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW), '')
        self.etat({'disabled': True})
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW), '')
        self.assertEqual(self.lancements, [])

    def test_not_installed_says_nothing(self):
        rg.STATE.unlink()
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW), '')

    def test_stale_list_starts_a_background_computation(self):
        self.liste([], calcule=NOW - 2 * 3600)
        self.assertEqual(rg.hook({'session_id': 'cli-pm'}, NOW), '')
        self.assertEqual(self.lancements, [1])

    def test_quiet_hours_threshold_is_a_setting(self):
        self.etat({'rangement_heures': 6})
        self.assertEqual(rg.reglages(), (True, 6))
        self.etat({})
        self.assertEqual(rg.reglages(), (True, 24))


class Trace(unittest.TestCase):
    def test_today_archived_sessions_reach_the_page(self):
        ms = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ms)
        (ms / '.parc').mkdir()
        ancien = parc.INTERNE
        parc.INTERNE = ms / '.parc'
        self.addCleanup(setattr, parc, 'INTERNE', ancien)
        maintenant = time.time()
        (ms / '.parc' / 'rangement.json').write_text(json.dumps({'rangees': [
            {'id': 'local_a', 'titre': 'Alpha · Essai', 'quand': maintenant - 60},
            {'id': 'local_b', 'titre': 'Alpha · Vieux', 'quand': maintenant - 3 * 86400}]}))
        r = parc.rangees_du_jour(maintenant)
        self.assertEqual([x['id'] for x in r], ['local_a'])
        self.assertEqual(r[0]['titre'], 'Alpha · Essai')

    def test_page_has_the_block(self):
        page = (ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html').read_text(encoding='utf-8')
        self.assertIn('id="bloc-rangees"', page)
        self.assertIn('d.rangees', page)


class Wiring(unittest.TestCase):
    def test_hook_is_declared_and_silent_once_disabled(self):
        hooks = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))
        cmds = [h['command'] for g in hooks['hooks']['UserPromptSubmit'] for h in g['hooks']]
        cmd = next(c for c in cmds if 'rangement.py' in c)
        self.assertIn('"disabled": true', cmd)

    def test_switch_is_known(self):
        install = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py').read_text(encoding='utf-8')
        self.assertIn("'rangement': 'rangement_auto'", install)

    def test_never_writes_claude_settings(self):
        src = (ROOT / 'hooks' / 'rangement.py').read_text(encoding='utf-8')
        self.assertNotIn("'settings.json'", src)
        self.assertNotIn('CLAUDE_SETTINGS', src)


if __name__ == '__main__':
    unittest.main()
