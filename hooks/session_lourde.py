"""UserPromptSubmit hook: a session whose context grew past a threshold is told, once, to propose a fresh session.

The PM chose a threshold of 300 000 tokens (2026-11-03); this hook works without an LLM, in the session itself:

- the size of the context is read from the transcript (`transcript_path`): the last assistant message's usage,
  input_tokens + cache_read_input_tokens + cache_creation_input_tokens;
- past the threshold (`decoupe_seuil_tokens` in ~/Mon Studio/.parc/cockpit.json, 300 000 by default), the instruction
  is given once when it is crossed, then a reminder every 100 000 tokens more, never at every message. The last step
  told is kept per session in ~/Mon Studio/.parc/sessions-lourdes.json; a session that shrinks below the threshold
  (a context summary) starts again from zero.

Silent without Mon Studio (no cockpit.json) and in a session opened outside any Studio (perimetre.py), and never
fails a prompt.
"""
import json
import os
import pathlib
import sys

PAS = 100000
SEUIL_DEFAUT = 300000
FIN = 4 * 1024 * 1024   # the end of the transcript where the last usage is


def mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def lire_json(chemin, defaut=None):
    try:
        return json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaut


def taille_du_contexte(transcript):
    """Tokens of the context at the last assistant message of the main conversation, or None."""
    try:
        with open(transcript, 'rb') as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - FIN))
            lignes = f.read().split(b'\n')
    except OSError:
        return None
    for ligne in reversed(lignes):
        if b'"usage"' not in ligne:
            continue
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        if o.get('type') != 'assistant' or o.get('isSidechain'):
            continue
        u = (o.get('message') or {}).get('usage')
        if isinstance(u, dict):
            return sum(int(u.get(k) or 0) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    return None


def seuil(etat):
    v = etat.get('decoupe_seuil_tokens') if isinstance(etat, dict) else None
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else SEUIL_DEFAUT


def consigne(tokens):
    n = f'{round(tokens, -4):,}'.replace(',', ' ')
    return (f'Cette session pèse environ {n} tokens. Si la demande ouvre un sujet distinct, propose une session neuve par '
            f'l\'outil natif (start_session en offre, ou hand_off_to_session si une tâche est en cours) ; sinon, '
            f'propose-le à la fin de la tâche en cours. Avant, écris la passation dans les fichiers du projet (décisions, '
            f'préférences, état) et annonce-la en une ligne. Une session qui doit rester au premier niveau de la barre '
            f'(fil rouge, kit) : lance-la après le go du PM, puis remonte-la par detach_session ; le prompt complet à '
            f'coller seulement si l\'outil manque ou refuse.')


def main():
    base = mon_studio() / '.parc'
    etat = lire_json(base / 'cockpit.json')
    if not isinstance(etat, dict):
        return
    try:
        entree = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return
    sid, transcript = entree.get('session_id'), entree.get('transcript_path')
    if not sid or not transcript:
        return
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import perimetre
    if not perimetre.session_de_studio(entree.get('cwd')):
        return   # only the sessions opened in a Studio are told
    tokens = taille_du_contexte(transcript)
    if tokens is None:
        return
    s = seuil(etat)
    registre_chemin = base / 'sessions-lourdes.json'
    registre = lire_json(registre_chemin, {})
    registre = registre if isinstance(registre, dict) else {}
    palier = (tokens - s) // PAS if tokens >= s else -1
    dit = registre.get(sid, -1)
    if palier < 0:
        if sid in registre:   # shrank below the threshold (a summary): the next crossing is told again
            registre.pop(sid)
            ecrire(registre_chemin, registre)
        return
    if isinstance(dit, int) and palier <= dit:
        return
    registre[sid] = palier
    ecrire(registre_chemin, registre)
    print(consigne(tokens))


def ecrire(chemin, registre):
    tmp = chemin.with_name(f'.{chemin.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(registre, indent=1), encoding='utf-8')
    os.replace(tmp, chemin)


if __name__ == '__main__':
    try:
        main()
    except Exception:   # a hook never stops a prompt
        pass
    sys.exit(0)
