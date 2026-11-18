"""Tests: an answer to a session whose process is still there but whose turn is over goes at once (Q13, 2026-11-15):
python3 -m unittest discover -s tests

The connector stops the app's process (SIGTERM, as the app's governor does), then wakes the session with the answer
(`claude --resume <cli> -p`). It never stops a process whose turn goes on: « turn over » takes two witnesses, the
session's transcript (Claude's end_turn last, nothing queued, untouched for REPOS_S) and the app's main.log (a turn
end after the last message sent). Each test below breaks one witness and checks that the process lives on and the
answer waits. The « app process » is a real `sleep` the test starts; its line in the process table is made up."""
import json
import os
import subprocess
import threading
import time
import unittest

from test_cockpit_wake_answers import APP_CLAUDE, CLI, LOCAL, Setup, ps_line

SENT = f'2026-11-15 21:13:45 [info] Sending message to session {LOCAL}\n'
DONE = f'2026-11-15 21:20:26 [info] [Stop hook] Query completed for session {LOCAL}\n'
HEALTHY = f'2026-11-15 21:20:26 [info] [CCD CycleHealth] healthy cycle for {LOCAL} (401s, hadFirstResponse=true)\n'
IDLE = f'2026-11-15 21:17:50 [info] [WarmLifecycle:preview] Starting idle timeout for {LOCAL}: 1800s\n'


def assistant(stop, tool=False):
    content = [{'type': 'tool_use', 'name': 'Bash', 'input': {}}] if tool else [{'type': 'text', 'text': 'Fait.'}]
    return {'type': 'assistant', 'message': {'role': 'assistant', 'stop_reason': stop, 'content': content},
            'timestamp': '2026-11-15T20:20:00Z'}


class TurnOver(Setup):
    def setUp(self):
        super().setUp()
        self.proc = subprocess.Popen(['sleep', '60'])
        reaper = threading.Thread(target=self.proc.wait, daemon=True)   # no zombie: a stopped process really ends
        reaper.start()
        self.addCleanup(self.kill_proc)
        self.ps = ps_line(self.proc.pid, APP_CLAUDE + ' --output-format stream-json',
                          f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL} CLAUDE_CODE_SESSION_NAME=Essai')
        (self.transcripts / 'proj').mkdir()
        self.transcript = self.transcripts / 'proj' / f'{CLI}.jsonl'
        # The table as ps would show it: a process that ended is no longer there.
        self.m.lire_processus = lambda: '\n'.join(l for l in self.ps.splitlines() if self.m.pid_vivant(int(l.split()[0])))
        self.main_log = self.root / 'main.log'
        self.m.JOURNAL_APP = self.main_log
        self.at_rest()

    def kill_proc(self):
        if self.proc.poll() is None:
            self.proc.kill()

    def write_transcript(self, entries, age=60):
        self.transcript.write_text(''.join(json.dumps(e) + '\n' for e in entries))
        os.utime(self.transcript, (time.time() - age, time.time() - age))

    def at_rest(self):
        self.write_transcript([{'type': 'user', 'message': {'role': 'user', 'content': 'Q10 go'}}, assistant('end_turn')])
        self.main_log.write_text(SENT + DONE)

    def alive(self):
        time.sleep(0.3)
        return self.proc.poll() is None

    def assert_waits(self):
        r = self.answer()
        self.assertEqual(r['mode'], 'file')
        self.assertTrue(self.alive(), 'a process whose turn goes on was stopped')
        self.assertEqual(self.calls(timeout=0.3), [])
        self.m.tour_de_file()                                  # the watcher does not stop it either
        self.assertTrue(self.alive())
        self.assertEqual(self.calls(timeout=0.3), [])
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'en_file')

    # -- turn over: stop, then wake with the answer

    def test_turn_over_the_process_is_stopped_and_the_session_woken_with_the_answer(self):
        r = self.answer()
        self.assertEqual(r['mode'], 'reveil')
        self.assertFalse(self.alive())
        self.assertEqual(self.proc.returncode, -15)            # SIGTERM, as the app's governor
        self.assertEqual(self.calls()[0]['argv'][:4], ['--resume', CLI, '-p', 'Q11 go'])
        entry = self.queue()[f'{LOCAL}--Q11.json']
        self.assertEqual((entry['etat'], entry['arrets']), ('livree', 1))
        self.assertEqual([j['mode'] for j in self.journal()], ['arret', 'reveil'])
        self.assertTrue(self.journal()[1]['apres_arret'])

    def test_a_healthy_cycle_line_is_a_turn_end_too(self):
        self.main_log.write_text(SENT + HEALTHY)
        self.assertEqual(self.answer()['mode'], 'reveil')

    def test_the_watcher_delivers_a_queued_answer_once_the_turn_is_over(self):
        self.main_log.write_text(DONE + SENT)                  # a turn runs
        self.assertEqual(self.answer()['mode'], 'file')
        self.assertTrue(self.alive())
        self.main_log.write_text(DONE + SENT + DONE)           # it ended
        self.m.tour_de_file()
        self.assertFalse(self.alive())
        self.assertEqual(self.calls()[0]['argv'][:4], ['--resume', CLI, '-p', 'Q11 go'])

    # -- turn going on, or not proved over: never stopped

    def test_claude_is_running_a_tool(self):
        self.write_transcript([assistant('tool_use', tool=True)])
        self.assert_waits()

    def test_the_transcript_moved_in_the_last_seconds(self):
        self.write_transcript([assistant('end_turn')], age=2)
        self.assert_waits()

    def test_a_message_was_sent_after_the_last_turn_end(self):
        self.main_log.write_text(DONE + SENT)
        self.assert_waits()

    def test_an_idle_timeout_line_alone_is_not_a_turn_end(self):
        self.main_log.write_text(SENT + IDLE)                  # the app writes it in the middle of a turn
        self.assert_waits()

    def test_a_message_waits_in_the_session_queue(self):
        self.write_transcript([assistant('end_turn'), {'type': 'queue-operation', 'operation': 'enqueue',
                                                       'content': 'et aussi'}])
        self.assert_waits()

    def test_a_user_message_after_the_end_of_turn(self):
        self.write_transcript([assistant('end_turn'), {'type': 'user', 'message': {'role': 'user', 'content': 'suite'}}])
        self.assert_waits()

    def test_no_transcript_or_no_main_log(self):
        self.transcript.unlink()
        self.assert_waits()
        self.at_rest()
        self.main_log.unlink()
        self.assertEqual(self.answer()['mode'], 'file')
        self.assertTrue(self.alive())

    def test_a_process_the_app_does_not_hold_is_never_stopped(self):
        # A `claude --resume` the PM runs in a Terminal holds the same conversation.
        self.ps = ps_line(self.proc.pid, f'/Users/pm/.local/bin/claude --resume {CLI}')
        self.assert_waits()

    def test_a_process_the_app_starts_again_at_once_is_left_alone(self):
        stopped = []
        real = self.m.os.kill

        def kill(pid, sig):
            if sig:
                stopped.append(pid)
            return real(pid, sig)
        self.m.os.kill = kill
        self.addCleanup(setattr, self.m.os, 'kill', real)
        other = subprocess.Popen(['sleep', '60'])
        self.addCleanup(other.kill)
        threading.Thread(target=other.wait, daemon=True).start()
        # After the stop, the table shows a new process of the app on the session (it warmed it again).
        # Two readings before the stop (the liveness check, then the stop's own), the new process after it.
        tables = iter([self.ps, self.ps])
        self.ps_other = ps_line(other.pid, APP_CLAUDE + ' --x', f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL}')
        self.m.lire_processus = lambda: next(tables, self.ps_other)
        self.assertEqual(self.answer()['mode'], 'file')
        self.assertEqual(self.calls(timeout=0.3), [])          # never a wake beside the new process
        self.m.tour_de_file()
        self.assertEqual(stopped, [self.proc.pid])              # one stop per answer, never the new process
        self.assertIsNone(other.poll())

    # -- the line says « envoyée » only once the session has the answer

    def test_received_when_the_transcript_holds_the_answer(self):
        self.set_terminal(connecte=True, duree=1.5)
        self.answer()
        self.m.tour_de_file()
        self.assertFalse(self.m.file_pour_la_page()[0]['recue'])
        with self.transcript.open('a') as f:
            f.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'Q11 go'},
                                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}) + '\n')
        self.m.tour_de_file()
        self.assertTrue(self.m.file_pour_la_page()[0]['recue'])
        self.wait_end()
        self.m.tour_de_file()
        page = self.m.file_pour_la_page()[0]
        self.assertEqual(page['etat'], 'livree')
        self.assertTrue(page['fini'])


if __name__ == '__main__':
    unittest.main()
