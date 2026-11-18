"""PreToolUse hook: a session or sub-agent launched without a model is refused once, with the price list.

The rule « a session Claude launches gets its model at creation » (regles/modele-effort.md) was only a text: measured
over a real week, 47 launches out of 73 left without a model, and the daughter then inherits the mother's (Opus). This
hook makes it a control:

- `mcp__ccd_session__start_session`: refused when `tool_input` carries a non-empty `prompt` and no `model`. An offer
  without a prompt (only a title) and a start by `proposal_id` alone pass.
- `Agent`: refused when there is no `model` and `subagent_type` is absent, "general-purpose" or "claude". Named agents
  take the model of their definition, and "fork" inherits the session's model (it ignores `model`): they pass.

The refusal is a PreToolUse `permissionDecision: deny` on stdout, exit 0; Claude relaunches the same call with `model`.
Off with `"controle_modele": false` in ~/Mon Studio/.parc/cockpit.json (or $MON_STUDIO/.parc/cockpit.json), set by
`install.py switch controle-modele off`. Only in a session of the desktop app (CLAUDE_CODE_HOST_SESSION_ID set, as
hooks/retirees.py reads it): a terminal session, a `claude -p` or a wake of the connector (whose environment drops the
CLAUDE_* variables) is never refused. A hook never breaks a session: any error, unreadable input or unknown tool is a
silent exit 0, the call goes through.
"""
import json
import os
import pathlib
import sys

SESSION_TOOL = 'mcp__ccd_session__start_session'
GENERIC_AGENTS = (None, '', 'general-purpose', 'claude')

REFUS = ('Lancement refusé : aucun modèle précisé. Relance le même appel avec `model`, selon le barème : '
         'Haiku pour lire, chercher, lister, vérifier ; '
         'Sonnet pour la rédaction courante, la mise à jour de fichiers, un petit script ; '
         'Opus pour un livrable client, un cadrage, un arbitrage, une analyse croisée.')


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def session_de_l_app():
    """True in a session of the desktop app: it sets CLAUDE_CODE_HOST_SESSION_ID; the terminal and `claude -p` do not."""
    return bool((os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or '').strip())


def controle_actif():
    try:
        etat = json.loads((mon_studio() / '.parc' / 'cockpit.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(etat, dict) and not etat.get('disabled') and etat.get('controle_modele') is not False


def sans_modele(outil, entree):
    if not isinstance(entree, dict) or entree.get('model'):
        return False
    if outil == SESSION_TOOL:
        prompt = entree.get('prompt')
        return isinstance(prompt, str) and bool(prompt.strip())
    if outil == 'Agent':
        return entree.get('subagent_type') in GENERIC_AGENTS
    return False


def main():
    if not session_de_l_app():
        return
    try:
        donnees = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return
    if not isinstance(donnees, dict) or not sans_modele(donnees.get('tool_name'), donnees.get('tool_input')):
        return
    if not controle_actif():
        return
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': REFUS}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:   # a hook never breaks a session
        pass
    sys.exit(0)
