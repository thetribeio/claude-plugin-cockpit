"""Tests: nothing forgotten, nothing invented in Mon Studio: python3 -m unittest discover -s tests

The PM, 2026-10-26 (Q33, Q37): a « Go » line « Ingestion auto : un passage automatique attend ton autorisation…
Ouvre ce passage » stayed on the screen of the session « COPIL · init » hours after the pass had resumed and closed:
Mon Studio guessed the ask in the free text of the last message and could not know it was settled elsewhere. And,
the PM added: once a PM trusts the screen, he no longer opens each session, so nothing may be forgotten either.
So:

  - a waiting session's numbered questions make its lines; « Rien à faire de ton côté » makes none; a 📬 thread brings
    news; a probable ask without a number makes one line with the neutral verb « Vérifier », never a guessed « Go »;
    a message with no probable ask makes a « Vérifier » line while the PM has not read it (Q40: a blocking check at
    the end of every answer would have sent back 64 % of the answers of a week, each turn re-reading its session);
  - a short reminder at each of the PM's messages (UserPromptSubmit hook) asks sessions to end with numbered questions
    or « Rien à faire de ton côté »;
  - the English forms count too (« To decide », « Still open », « Nothing to do on your side. »).

Transcripts and cards are synthetic; the COPIL · init message is the real one, its links and names changed."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

NOW = time.time()
OTHER = '/studios/Studio-Autre'

RELAYED = ("Pas un retour : le dernier message enregistré était le compte rendu du dépôt des scripts.\n\n"
           "**Ingestion auto : un passage automatique attend ton autorisation depuis le 22/10 et bloque les suivants.** "
           "Ouvre [ce passage](#local_00000000-0000-0000-0000-000000000000) et choisis « Toujours autoriser » sur la carte. "
           "Je ne relance rien tant qu'il est bloqué.")
NUMBERED = "Le plan est prêt.\n\n## À trancher\n\n**Q2 · Format du CR** : court ou long ? Je recommande court."
NOTHING = "Les scripts sont déposés dans le Studio pilote.\n\nRien à faire de ton côté."
INFO = "Oui, tu peux l'utiliser. Elle n'a pas bougé depuis ma passe du 9 octobre."
THREAD = "📬 Nouveautés du Studio\n\nDeux emails du client sont entrés au Studio."
EN_NOTHING = "The deck is updated with the new figures.\n\nNothing to do on your side."
EN_NUMBERED = "Two options.\n\n## To decide\n\n**Q1 · Hosting**: theirs or ours? I recommend ours."


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def final(hours_ago, text, mid='m1'):
    return {'type': 'assistant', 'timestamp': at(hours_ago),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(hours_ago, text):
    return {'type': 'user', 'timestamp': at(hours_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def card(sid, title, cwd=OTHER):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


class Screen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def session(self, sid, text, unread=False):
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(json.dumps(pm(3, 'Où en est-on ?')) + '\n' + json.dumps(final(2, text)) + '\n', encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, 'Session ' + sid), chemin=str(path), derniere=r['depuis'], non_lue=unread, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def lines(self, unread=(), **texts):
        sessions = [self.session(sid, text, sid in unread) for sid, text in texts.items()]
        metas = [card(s['id'], s['titre']) for s in sessions]
        out = {}
        for l in parc.tableau(sessions, metas, [], 3650, NOW, {}):
            out.setdefault(l['cle'], []).append(l)
        return sessions, out

    def test_the_relayed_authorization_is_no_longer_a_go(self):
        _, out = self.lines(local_copil=RELAYED)
        (l,) = out['local_copil']
        self.assertEqual((l['type'], l['verbe'], l['lecture']), ('check', 'Vérifier', 'a_verifier'))
        self.assertIn('Ingestion auto : un passage automatique attend ton autorisation', l['suite'])
        self.assertIn('Rien à faire de ton côté', l['declencheur'])

    def test_every_waiting_session_is_on_the_screen_unless_it_said_nothing_or_was_read_with_nothing_asked(self):
        sessions, out = self.lines(unread=('local_info_unread',), local_numbered=NUMBERED, local_nothing=NOTHING,
                                   local_info=INFO, local_info_unread=INFO, local_relayed=RELAYED, local_thread=THREAD,
                                   local_en_nothing=EN_NOTHING, local_en_numbered=EN_NUMBERED)
        for s in sessions:
            self.assertEqual(s['etat'], 'attend', s['id'])
        shown = {sid for sid in out}
        self.assertEqual(shown, {'local_numbered', 'local_info_unread', 'local_relayed', 'local_en_numbered'})
        self.assertEqual([l['lecture'] for l in out['local_numbered']], ['format'])
        self.assertEqual([l['lecture'] for l in out['local_en_numbered']], ['format'])
        self.assertEqual([(l['lecture'], l['suite']) for l in out['local_info_unread']],
                         [('a_verifier', parc.A_VERIFIER_SUITE)])

    def test_a_probable_ask_stays_even_once_read(self):
        _, out = self.lines(local_relayed=RELAYED, local_question="Il reste la clé de l'API : sert-elle ailleurs ?")
        self.assertEqual(sorted(out), ['local_question', 'local_relayed'])

    def test_no_line_is_a_guessed_go_any_more(self):
        _, out = self.lines(local_a=RELAYED, local_b=INFO, local_c="Dis-moi si le plan te va.",
                            local_d="Je propose de garder court. Je l'applique ?")
        for sid, ls in out.items():
            for l in ls:
                self.assertEqual(l['type'], 'check', (sid, l['suite']))


class Reminder(unittest.TestCase):
    """The reminder at each of the PM's messages: one line, only where Mon Studio is installed."""

    def command(self):
        hooks = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']
        # No blocking check on the answer's form: it would cost a turn for most answers. The only Stop hooks are the
        # direct answer (Q11), off by default, which never blocks without the PM's click (test_cockpit_direct_answers),
        # and the snapshot of the Studios, launched in the background, silent (test_cockpit_projets_snapshot).
        stops = [h['command'] for g in hooks.get('Stop', []) for h in g['hooks']]
        self.assertTrue(all('hooks/reponse_directe.py' in c or 'hooks/projets_instantane.py' in c
                            or 'hooks/format_questions.py' in c for c in stops), stops)
        (cmd,) = [h['command'] for g in hooks['UserPromptSubmit'] for h in g['hooks'] if 'Mon Studio :' in h['command']]
        return cmd

    def run_command(self, home):
        # The reminder is guarded by perimetre.py (real plugin root); the session sits in Mon Studio.
        root = pathlib.Path(__file__).resolve().parent.parent
        return subprocess.run(['/bin/sh', '-c', self.command()], capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, HOME=str(home), CLAUDE_PLUGIN_ROOT=str(root)),
                              input='{}', cwd=str(pathlib.Path(home) / 'Mon Studio') if (pathlib.Path(home) / 'Mon Studio').is_dir() else None)

    def test_it_reminds_where_mon_studio_is_installed(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / 'Mon Studio' / '.parc').mkdir(parents=True)
            (pathlib.Path(d) / 'Mon Studio' / '.parc' / 'cockpit.json').write_text('{}')
            r = self.run_command(d)
        self.assertEqual(r.returncode, 0)
        self.assertIn('« Rien à faire de ton côté. »', r.stdout)
        self.assertIn('« Nothing to do on your side. »', r.stdout)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)

    def test_silent_elsewhere(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_command(d)
        self.assertEqual((r.returncode, r.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
