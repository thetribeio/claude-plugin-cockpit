"""Tests of a reminder that relays another session's questions: python3 -m unittest discover -s tests

A session may tell the PM that another session, named by its link, still waits for answers to its questions
(« [Kit · publier](#local_…) attend toujours tes réponses à ses questions Q40 à Q43 »). Those numbers belong to the
other session, which has its own lines: the session that writes the sentence gets no line for them. Before the fix
(2026-11-25), Mon Studio showed Q40 and Q43 under the relaying session, as « Question introuvable », and « Ouvrir »
led to the wrong session. The same sentence without a link is still read as the session's own reminder."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

RELAYED = ("[Kit · publier la version](#local_0000aaaa-1111-2222-3333-444455556666) attend toujours tes réponses à "
           "ses questions Q40 à Q43, à lire et trancher dans cette session. La première porte sur l'installation.\n\n"
           "Encore ouvert : Q17 · Traiter les conflits cette semaine.")
OWN = "J'attends toujours tes réponses à Q40 et Q43, posées plus haut."


class RelayedReminder(unittest.TestCase):
    def test_linked_session_numbers_are_not_this_sessions(self):
        self.assertEqual(parc.rappels_en_phrase(RELAYED), {})

    def test_own_open_question_still_read(self):
        self.assertIn(17, parc.encore_ouvert(RELAYED))

    def test_unlinked_reminder_still_read(self):
        self.assertEqual(sorted(parc.rappels_en_phrase(OWN)), [40, 43])


if __name__ == '__main__':
    unittest.main()
