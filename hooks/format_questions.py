"""Stop hook: the numbered questions of the turn's last message follow the short-title format (PM, 2026-11-18).

Rule 2 of regles/format-reponses.md: under « À trancher », each question is « Qn · <short title that says what to
decide, 60 characters at most> : <the precise question> », its options « 1) **<label of 4 words at most>** : <the whole
option> ». Mon Studio shows the title alone on its line and the label on the answer button; the click shows the rest.

The last message of the turn is read like the Stop hook of direct answers (reponse_directe.py: the transcript, the
PM's last message, Claude's final message after it) and its questions with the board's own parser (parc.a_trancher),
so the hook and the board read the same way. Violations, by kind:
- `titre_long`: the title is longer than 60 characters, its impact label « (impact fort : échéance) » not counted;
- `sans_question`: nothing after the title (no « : » and a precise question);
- `options_sans_libelle`: numbered options without a short bold label;
- `libelle_long`: a bold label longer than 28 characters.

With a violation, and unless the stop already follows a stop hook (`stop_hook_active`), it prints
`{"decision": "block", "reason": …}` once: which question, what is wrong, and to repost only the « À trancher » block,
corrected, with the same numbers. Otherwise it prints nothing.

Each message that holds at least one numbered question adds one line to ~/Mon Studio/.parc/format-questions.jsonl
(ts, session id, number of questions, violation kinds, whether it followed a block), never the message's text: to
measure how often sessions follow the rule. Silent on any error; the hooks.json guard keeps it silent once Mon Studio
is disabled.

Off with `"controle_format": false` in ~/Mon Studio/.parc/cockpit.json (`install.py switch controle-format off`): then
it reads, blocks and notes nothing. Only in a session of the desktop app (CLAUDE_CODE_HOST_SESSION_ID set): a terminal
session, a `claude -p`, and above all the connector's wake (`claude --resume <id> -p "<answer>"`, whose environment
drops every CLAUDE_* variable, mcp_mon_studio.env_terminal) end without a block.
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import reponse_directe  # noqa: E402  the same reading of the turn's last message

JOURNAL = reponse_directe.MON_STUDIO / '.parc' / 'format-questions.jsonl'
TITRE_MAX, LIBELLE_MAX = 60, 28
DIT = {'titre_long': 'titre de {n} caractères (60 au plus, hors étiquette d’impact)',
       'sans_question': 'pas de question précise après le titre (« Qn · <titre> : <la question> »)',
       'options_sans_libelle': 'options sans libellé court en gras (« 1) **<4 mots au plus>** : <option entière> »)',
       'libelle_long': 'libellé d’option de plus de 28 caractères'}


def ecarts(parc, item):
    """[(kind, length or None)] of one numbered question (an item of parc.a_trancher)."""
    sortie = []
    titre = re.sub(r'^Q\d+\s*·\s*', '', item.get('titre') or '')
    titre = ' '.join(parc.ETIQUETTE_TITRE.sub(' ', titre).split())
    if len(titre) > TITRE_MAX:
        sortie.append(('titre_long', len(titre)))
    q = parc.depli_de_question(item.get('titre') or '', item.get('suite') or '', item.get('brut') or '')
    if not q['question'].strip():
        sortie.append(('sans_question', None))
    options = parc.options_entieres(item.get('brut') or '')
    if options and not all(o['gras'] for o in options):
        sortie.append(('options_sans_libelle', None))
    if any(len(o['gras']) > LIBELLE_MAX for o in options):
        sortie.append(('libelle_long', None))
    return sortie


def raison(fautes):
    """The French reason of the block: each question and what is wrong, then what to do."""
    parties = []
    for num, ecs in fautes:
        parties.append(f"Q{num} : " + ' ; '.join(DIT[k].format(n=n) for k, n in ecs))
    return ("Mon Studio : le bloc « À trancher » ne suit pas le format des questions. " + ' · '.join(parties) + ". "
            "Reposte seulement le bloc « À trancher » corrigé, mêmes numéros, rien d'autre : « Qn · <titre court qui dit "
            "quoi décider, 60 caractères au plus> : <la question précise> », puis les options « 1) **<libellé de 4 mots au "
            "plus>** : <option entière> », la recommandée en premier avec « (recommandé) », puis « Pourquoi : … Si tu ne "
            "fais rien : … ».")


def noter(entree, n, kinds, relance):
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        ligne = {'ts': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                 'session': str(entree.get('session_id') or ''), 'questions': n, 'ecarts': kinds, 'relance': relance}
        with open(JOURNAL, 'a', encoding='utf-8') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    except OSError:
        pass


def actif():
    """In a session of the desktop app, and not cut by `controle_format: false` (absent or unreadable: on)."""
    if not (os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or '').strip():
        return False
    try:
        etat = json.loads((reponse_directe.MON_STUDIO / '.parc' / 'cockpit.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return True
    return not (isinstance(etat, dict) and etat.get('controle_format') is False)


def main():
    if not actif():
        return 0
    entree = json.loads(sys.stdin.read() or '{}')
    if not isinstance(entree, dict):
        return 0
    transcript = entree.get('transcript_path')
    if not transcript or not reponse_directe.PARC.exists():
        return 0
    parc = reponse_directe.charger_parc()
    texte = reponse_directe.dernier_message(parc, transcript, reponse_directe.debut_du_tour(transcript))
    if not texte or not re.search(r'Q\d', texte):
        return 0
    questions = [it for it in parc.a_trancher(texte)[0] if it.get('num')]
    if not questions:
        return 0
    fautes = [(it['num'], e) for it in questions for e in [ecarts(parc, it)] if e]
    relance = bool(entree.get('stop_hook_active'))
    noter(entree, len(questions), sorted({k for _, e in fautes for k, _ in e}), relance)
    if fautes and not relance:
        sys.stdout.write(json.dumps({'decision': 'block', 'reason': raison(fautes)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:  # never in the way of a normal stop
        sys.exit(0)
