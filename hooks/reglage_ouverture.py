"""UserPromptSubmit hook: on the first message of a session, Claude sets its own model and effort, per the scale.

Rule 6 of regles/modele-effort.md was only a text; this hook gives it at the right moment. On the first message of a
session (the transcript holds no assistant line yet), it prints one instruction: choose the setting the request needs
(Haiku low, Sonnet medium, Opus medium, Opus high only for a really hard problem), change it without asking with
`set_session_model` / `set_session_effort`, and announce it in one line. Fable and Opus high are only proposed: the
session keeps its setting until the PM says yes. From the second message on, nothing.

Off with `"reglage_ouverture": false` in ~/Mon Studio/.parc/cockpit.json (or $MON_STUDIO/.parc/cockpit.json), set by
`install.py switch reglage-ouverture off`. Silent while the PM keeps a personal copy of the same hook,
<config>/hooks/reglage_ouverture.py (<config> = $CLAUDE_CONFIG_DIR, else ~/.claude): the instruction is not given
twice, and the PM may remove the copy at any time. Silent without Mon Studio, and never fails a prompt.

    echo '{"transcript_path": "/nonexistent"}' | python3 reglage_ouverture.py   # prints the instruction
"""
import json
import os
import pathlib
import sys

CONSIGNE = (
    "Réglage d'ouverture : c'est le premier message de cette session. Choisis le réglage selon le barème "
    "au vu de sa demande : Haiku low pour lire, chercher, vérifier ; Sonnet medium pour rédiger, synthétiser, "
    "petit code ; Opus medium pour un livrable client, un cadrage, un arbitrage, un chiffrage ou un kit ; "
    "Opus high seulement pour un problème réellement difficile. Change toi-même le modèle et l'effort, sans "
    "demander, avec les outils set_session_model et set_session_effort (ne change que ce qui diffère de ton "
    "réglage actuel), puis ouvre ta réponse par une ligne « Réglage : <modèle>, effort <niveau> — <raison en "
    "quelques mots> ». Si ton réglage actuel convient déjà, écris « Réglage : <modèle>, effort <niveau>, adapté. » "
    "Exception : pour Fable ou pour Opus high, ne change rien ; ouvre par « Réglage conseillé : <modèle>, effort "
    "<niveau> — <raison> (réglage actuel : <le tien>) », propose de basculer et attends le oui du PM. "
    "Puis traite sa demande normalement."
)


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def config_dir():
    """The PM's Claude config folder, as hooks/regles.py resolves it."""
    v = os.environ.get('CLAUDE_CONFIG_DIR')
    return pathlib.Path(v) if v else pathlib.Path.home() / '.claude'


def copie_personnelle():
    return (config_dir() / 'hooks' / 'reglage_ouverture.py').is_file()


def actif():
    try:
        etat = json.loads((mon_studio() / '.parc' / 'cockpit.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(etat, dict) and not etat.get('disabled') and etat.get('reglage_ouverture') is not False


def deja_repondu(chemin):
    """True once the transcript holds an assistant line: the session is past its first message."""
    try:
        with open(chemin, encoding='utf-8', errors='replace') as f:
            for ligne in f:
                if '"type":"assistant"' in ligne.replace(' ', ''):
                    return True
    except OSError:
        return False
    return False


def main():
    if not actif() or copie_personnelle():
        return
    e = json.loads(sys.stdin.read() or '{}')
    if not isinstance(e, dict) or deja_repondu(str(e.get('transcript_path') or '')):
        return
    print(CONSIGNE)


if __name__ == '__main__':
    try:
        main()
    except Exception:   # a hook never stops a prompt
        pass
    sys.exit(0)
