"""PreToolUse hook: the model scale holds for the sub-agents and the sessions Claude launches.

- `Agent`: Opus or Fable for a sub-agent is refused unless the prompt carries « [modèle justifié] » with a reason.
  No model given = CLAUDE_CODE_SUBAGENT_MODEL or the agent definition's model: it passes. A fork is left alone.
- `start_session` (any tool whose name ends so): a fresh session needs a model, and Fable is refused unless the prompt
  carries « [fable demandé] » (the PM asked for it in words). A fork (`context: fork`), a start by `proposal_id` and
  an offer (`initiation: offer`) are left alone.

A start_session without a model that hooks/modele_lancement.py already refuses (desktop app session, `controle_modele`
on, a prompt) is left to it: one refusal, not two. The refusal is a PreToolUse `permissionDecision: deny` on stdout,
exit 0; Claude relaunches the call with a fitting model, or with the marker and its reason.

Off with `"controle_bareme": false` in ~/Mon Studio/.parc/cockpit.json (or $MON_STUDIO/.parc/cockpit.json), set by
`install.py switch controle-bareme off`. Silent while the PM keeps a personal copy of the same hook,
<config>/hooks/bareme_modele.py (<config> = $CLAUDE_CONFIG_DIR, else ~/.claude): no double refusal, and the PM may
remove the copy at any time. Silent without Mon Studio, and never fails a tool call on its own error.
"""
import importlib.util
import json
import os
import pathlib
import sys

MARQUE_MODELE = '[modèle justifié]'
MARQUE_FABLE = '[fable demandé]'

REFUS_AGENT = ("Barème modèle et effort : sous-agent en Haiku (lire, chercher, extraire) ou Sonnet (rédiger, "
               "synthétiser, petit code), sans paramètre model (défaut Sonnet) ou model: haiku. Opus seulement pour "
               "un livrable client, un arbitrage ou après un échec constaté : ajoute alors « [modèle justifié] "
               "<raison> » au prompt.")
REFUS_SANS_MODELE = ("Barème modèle et effort : une session lancée reçoit son modèle. Passe model (claude-sonnet-5-5 "
                     "pour la rédaction courante et le code simple, claude-haiku-5-5 pour lire et vérifier, "
                     "claude-opus-5-5 pour un livrable client, un cadrage ou un kit) et effort (low ou medium).")
REFUS_FABLE = ("Barème modèle et effort : pas de Fable pour une session lancée (environ 3 fois Opus). Prends "
               "claude-opus-5-5 ; Fable seulement si le PM l'a demandé en toutes lettres : ajoute alors "
               "« [fable demandé] » au prompt.")


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def config_dir():
    """The PM's Claude config folder, as hooks/regles.py resolves it."""
    v = os.environ.get('CLAUDE_CONFIG_DIR')
    return pathlib.Path(v) if v else pathlib.Path.home() / '.claude'


def copie_personnelle():
    return (config_dir() / 'hooks' / 'bareme_modele.py').is_file()


def actif():
    try:
        etat = json.loads((mon_studio() / '.parc' / 'cockpit.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(etat, dict) and not etat.get('disabled') and etat.get('controle_bareme') is not False


def deja_refuse_sans_modele(outil, entree):
    """True when hooks/modele_lancement.py refuses this same call for its missing model."""
    try:
        spec = importlib.util.spec_from_file_location('modele_lancement', pathlib.Path(__file__).with_name('modele_lancement.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return outil == m.SESSION_TOOL and m.session_de_l_app() and m.sans_modele(outil, entree) and m.controle_actif()
    except Exception:
        return False


def raison(outil, t):
    """Why this call is refused, or None."""
    modele = str(t.get('model') or '').lower()
    prompt = str(t.get('prompt') or '')
    if outil == 'Agent':
        if t.get('subagent_type') == 'fork':
            return None
        if any(k in modele for k in ('opus', 'fable')) and MARQUE_MODELE not in prompt:
            return REFUS_AGENT
    elif outil.endswith('start_session'):
        if t.get('proposal_id') or t.get('context') == 'fork' or t.get('initiation') == 'offer':
            return None
        if not modele:
            return None if deja_refuse_sans_modele(outil, t) else REFUS_SANS_MODELE
        if 'fable' in modele and MARQUE_FABLE not in prompt:
            return REFUS_FABLE
    return None


def main():
    if not actif() or copie_personnelle():
        return
    e = json.loads(sys.stdin.read() or '{}')
    if not isinstance(e, dict):
        return
    outil, t = str(e.get('tool_name') or ''), e.get('tool_input')
    r = raison(outil, t) if isinstance(t, dict) else None
    if r:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                  'permissionDecisionReason': r}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:   # a hook never breaks a tool call
        pass
    sys.exit(0)
