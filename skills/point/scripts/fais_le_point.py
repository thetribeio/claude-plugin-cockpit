#!/usr/bin/env python3
"""Read-only status of a Studio's Claude sessions over the last seven days (skill `point`, plugin `cockpit`).

    python3 fais_le_point.py [--dossier <path>] [--semaine] [--json]

Reads the app session records and the local transcripts. Writes nothing, sends nothing. Runs on macOS and Windows.
Env overrides: MON_STUDIO (Mon Studio data folder), MON_STUDIO_APP_SESSIONS (app session records),
MON_STUDIO_TRANSCRIPTS (local transcripts).
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import pathlib
import sys
import time

DAYS = 7
HEAVY = 150_000
MIN_ACTIVE_TO_FOLLOW = 2   # from two active topics on, the point points to the project view (a suggestion, not a gate)
SKIP_MARKERS = ('cross-session-message', 'agent-message', 'task-notification',
                'Another Claude session', 'This session is being continued')


def mon_studio_dir(env=None, home=None):
    """The Mon Studio data folder: the only place where its location is decided (MON_STUDIO wins)."""
    env = os.environ if env is None else env
    if env.get('MON_STUDIO'):
        return pathlib.Path(env['MON_STUDIO'])
    return pathlib.Path(home or pathlib.Path.home()) / 'Mon Studio'


def app_sessions_dir(env=None, platform=None, home=None):
    """Where the Claude app keeps its session records. MON_STUDIO_APP_SESSIONS wins on every OS."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    home = pathlib.Path(home or pathlib.Path.home())
    if env.get('MON_STUDIO_APP_SESSIONS'):
        return pathlib.Path(env['MON_STUDIO_APP_SESSIONS'])
    if platform.startswith('win'):
        appdata = env.get('APPDATA')
        base = pathlib.Path(appdata) if appdata else home / 'AppData' / 'Roaming'
        return base / 'Claude' / 'claude-code-sessions'
    if platform == 'darwin':
        return home / 'Library' / 'Application Support' / 'Claude' / 'claude-code-sessions'
    base = pathlib.Path(env['XDG_CONFIG_HOME']) if env.get('XDG_CONFIG_HOME') else home / '.config'
    return base / 'Claude' / 'claude-code-sessions'


def transcripts_dir(env=None, home=None):
    """Claude Code's local transcripts: MON_STUDIO_TRANSCRIPTS, then CLAUDE_CONFIG_DIR, then ~/.claude."""
    env = os.environ if env is None else env
    if env.get('MON_STUDIO_TRANSCRIPTS'):
        return pathlib.Path(env['MON_STUDIO_TRANSCRIPTS'])
    if env.get('CLAUDE_CONFIG_DIR'):
        return pathlib.Path(env['CLAUDE_CONFIG_DIR']) / 'projects'
    return pathlib.Path(home or pathlib.Path.home()) / '.claude' / 'projects'


def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def read_jsonl(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def inside(cwd, root):
    cwd, root = os.path.normcase(os.path.normpath(cwd or '')), os.path.normcase(os.path.normpath(root))
    return cwd == root or cwd.startswith(root + os.sep)


def read_records():
    out = []
    for p in glob.glob(str(app_sessions_dir() / '*' / '*' / 'local_*.json')):
        try:
            d = json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def load_sessions(root, records=None):
    out = []
    for d in read_records() if records is None else records:
        # A scheduled task's run is not a PM session: the app shows it under its routine.
        if d.get('isArchived') or d.get('scheduledTaskId') or not inside(d.get('cwd'), root):
            continue
        out.append(d)
    return out


def load_archived(root, records):
    """Archived sessions of the Studio (scheduled runs still excluded): only the week's cost reads them, the
    plugin archives finished sessions itself and their spending must not vanish from the total."""
    return [d for d in records if d.get('isArchived') and not d.get('scheduledTaskId') and inside(d.get('cwd'), root)]


def pm_text(entry):
    """Text typed by the PM, or None when the entry is not a PM message."""
    if entry.get('type') != 'user' or entry.get('isSidechain') or entry.get('isMeta'):
        return None
    c = (entry.get('message') or {}).get('content')
    if isinstance(c, list):
        c = '\n'.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
    if not isinstance(c, str) or not c.strip():
        return None
    if c.lstrip().startswith('<system-reminder>') or any(m in c for m in SKIP_MARKERS):
        return None
    return c


def usage_sum(u):
    return sum(int(u.get(k) or 0) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))


def analyse(session, since):
    cli_ids = list(session.get('priorCliSessionIds') or []) + ([session['cliSessionId']] if session.get('cliSessionId') else [])
    base = transcripts_dir()
    pm_msgs, last_ts, context, main_tokens, sub_tokens = 0, None, 0, 0, 0
    seen_calls = {}
    ctx_ts = -1
    for cid in cli_ids:
        for f in glob.glob(str(base / '*' / f'{cid}.jsonl')):
            for e in read_jsonl(f):
                ts = parse_ts(e.get('timestamp'))
                if ts is None:
                    continue
                last_ts = max(last_ts or 0, ts)
                if ts >= since and pm_text(e) is not None:
                    pm_msgs += 1
                if e.get('type') == 'assistant' and not e.get('isSidechain'):
                    u = (e.get('message') or {}).get('usage')
                    if u:
                        if ts >= ctx_ts:
                            ctx_ts, context = ts, usage_sum(u)
                        if ts >= since:
                            seen_calls[(e.get('message') or {}).get('id') or e.get('uuid') or id(e)] = usage_sum(u)
        main_tokens += sum(seen_calls.values())
        seen_calls = {}
        sub = {}
        for f in glob.glob(str(base / '*' / cid / 'subagents' / '*.jsonl')):
            for e in read_jsonl(f):
                ts = parse_ts(e.get('timestamp'))
                u = (e.get('message') or {}).get('usage') if e.get('type') == 'assistant' else None
                if u and ts is not None and ts >= since:
                    sub[(f, (e.get('message') or {}).get('id') or e.get('uuid') or id(e))] = usage_sum(u)
        sub_tokens += sum(sub.values())
    if last_ts is None and session.get('lastActivityAt'):
        try:
            last_ts = float(session['lastActivityAt']) / 1000
        except (TypeError, ValueError):
            pass
    return {'messages': pm_msgs, 'last': last_ts, 'context': context, 'tokens': main_tokens, 'sub_tokens': sub_tokens}


def pillar_ids():
    """Main threads the PM keeps for good (never offered for archiving): the pillars a followed project's mirror
    lists, and fils-rouges.json in the Mon Studio folder when it exists."""
    out, base = set(), mon_studio_dir()
    for f in glob.glob(str(base / 'chantiers' / '*.json')):
        try:
            m = json.loads(pathlib.Path(f).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue
        for x in m.get('piliers') or []:
            v = x.get('sessionId') if isinstance(x, dict) else x
            if isinstance(v, str):
                out.add(v)
        for l in m.get('lanes') or []:
            if isinstance(l, dict) and isinstance(l.get('pillarId'), str):
                out.add(l['pillarId'])
    try:
        fr = json.loads((base / 'fils-rouges.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        fr = None
    for v in (fr.values() if isinstance(fr, dict) else fr if isinstance(fr, list) else []):
        for x in (v if isinstance(v, list) else [v]):
            s = x.get('sessionId') if isinstance(x, dict) else x
            if isinstance(s, str):
                out.add(s)
    return out


def find_follow(root, records):
    """The follow-up already in place for this Studio, or None: a mirror in <Mon Studio>/chantiers/ whose folders
    (the folder of its own session, `dossier`, plus the extra folders in `dossiers`, as parc.py reads them) cover
    the Studio, its session not archived."""
    by_id = {r.get('sessionId'): r for r in records if r.get('sessionId')}
    for f in sorted(glob.glob(str(mon_studio_dir() / 'chantiers' / '*.json'))):
        if f.endswith('.pass.json'):
            continue
        try:
            m = json.loads(pathlib.Path(f).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue
        own = by_id.get(m.get('sessionId')) or {}
        if own.get('isArchived'):
            continue
        # `dossiers` adds folders to the follow-up's own Studio, it does not replace it.
        folders = [own.get('cwd'), m.get('dossier')] + (m.get('dossiers') if isinstance(m.get('dossiers'), list) else [])
        if any(isinstance(x, str) and x and inside(root, x) for x in folders):
            tableau = m.get('tableau') if isinstance(m.get('tableau'), str) and m.get('tableau') else None
            return {'chantier': m.get('chantier') or pathlib.Path(f).stem, 'tableau': tableau, 'session': m.get('session')}
    return None


def load_waiting(session_ids):
    """(rows, warnings). rows is None when parc.py is absent; warnings say when Mon Studio cannot be trusted."""
    parc = mon_studio_dir() / '.parc' / 'parc.py'
    if not parc.exists():
        return None, []
    try:
        spec = importlib.util.spec_from_file_location('parc_mon_studio', parc)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        res = mod.construire(7, 7, time.time(), mod.charger_cache())
    except Exception as e:
        return [], [f'Mon Studio est installé mais ne répond pas ({type(e).__name__}) : demandes en attente non listées.']
    rows = list(res.get('tableau') or []) + list(res.get('anciennes') or [])
    lecture = res.get('lecture_app') if isinstance(res.get('lecture_app'), dict) else {}
    rows = [r for r in rows if r.get('cle') in session_ids]
    warnings = []
    if lecture.get('etat') == 'hors_service':
        # Mon Studio says it cannot read the app any more: a leading warning, not an empty list read as « nothing waits ».
        warnings.append("Mon Studio ne lit plus l'app : " + str(lecture.get('raison') or 'raison inconnue')
                        + '. Les demandes en attente ne sont pas fiables.')
    return rows, warnings


def short(s, n=110):
    s = ' '.join(str(s or '').split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def fmt_tokens(n):
    return f'{n:,}'.replace(',', ' ')


def collect(root, semaine, records=None):
    now = time.time()
    since = now - DAYS * 86400
    records = read_records() if records is None else records
    has_transcripts = transcripts_dir().is_dir()
    sessions = load_sessions(root, records)
    ids = set()
    for s in sessions:
        ids.add(s.get('sessionId'))
        if s.get('cliSessionId'):
            ids.add(s['cliSessionId'])
    waiting, warnings = load_waiting(ids)
    failed = bool(warnings)  # Mon Studio's own warnings: an empty waiting list proves nothing
    if not has_transcripts:
        warnings.insert(0, f'Je ne lis pas les transcripts ({transcripts_dir()}) : sessions finies et sessions lourdes non évaluées.')
    waiting_keys = {r.get('cle') for r in waiting or []}
    pillars = pillar_ids()
    data = {'actives': [], 'en_attente': [], 'lourdes': [], 'a_archiver': [], 'attente_absente': waiting is None,
            'attente_indisponible': failed, 'transcripts_absents': not has_transcripts, 'avertissements': warnings}
    infos = []
    for s in sessions:
        a = analyse(s, since)
        title = s.get('title') or s.get('sessionId')
        has_wait = s.get('sessionId') in waiting_keys or s.get('cliSessionId') in waiting_keys
        infos.append((s, title, a))
        # Without transcripts, the app record's last activity is the only sign of life.
        if a['messages'] > 0 or (not has_transcripts and a['last'] and a['last'] >= since):
            data['actives'].append(title)
        if not has_transcripts:
            continue
        if a['context'] > HEAVY and a['last'] and a['last'] >= since:
            data['lourdes'].append({'titre': title, 'contexte': a['context']})
        if (a['last'] is None or a['last'] < since) and not has_wait and s.get('sessionId') not in pillars:
            data['a_archiver'].append(title)
    for r in waiting or []:
        data['en_attente'].append({'titre': r.get('session') or r.get('sujet'), 'texte': short(r.get('detail') or r.get('sujet'))})
    data['actives_n'] = len(data['actives'])
    data['suivi'] = find_follow(root, records)
    data['proposer_suivi'] = data['suivi'] is None and data['actives_n'] >= MIN_ACTIVE_TO_FOLLOW
    if semaine:
        cost = [(t, a, False) for _, t, a in infos]
        for s in load_archived(root, records):
            # The app's own date first: an archived session idle for more than a week is not read at all.
            try:
                if s.get('lastActivityAt') and float(s['lastActivityAt']) / 1000 < since:
                    continue
            except (TypeError, ValueError):
                pass
            a = analyse(s, since)
            if a['last'] and a['last'] >= since:
                cost.append((s.get('title') or s.get('sessionId'), a, True))
        main = sum(a['tokens'] for _, a, _ in cost)
        sub = sum(a['sub_tokens'] for _, a, _ in cost)
        costly = sorted(cost, key=lambda x: x[1]['tokens'] + x[1]['sub_tokens'], reverse=True)[:3]
        data['semaine'] = {
            'jetons_relus': main, 'jetons_sous_agents': sub,
            'part_sous_agents': round(100 * sub / (main + sub)) if main + sub else 0,
            'archivees_n': sum(1 for _, _, arch in cost if arch),
            'plus_cheres': [{'titre': t, 'jetons': a['tokens'] + a['sub_tokens'], 'archivee': arch}
                            for t, a, arch in costly if a['tokens'] + a['sub_tokens'] > 0],
        }
    return data


def render(d):
    out = list(d.get('avertissements') or [])
    if (not d['actives_n'] and not d.get('en_attente') and not d.get('lourdes') and not d.get('a_archiver')
            and not d.get('suivi') and not d.get('semaine')):
        # An empty point must not read as « all clear »: the point reads the app's sessions opened in this
        # Studio, not the Studio's files. Say what it reads and the one gesture that feeds it.
        out.append("Aucune session Claude ouverte dans ce Studio cette semaine : le point n'a rien à lire ici.")
        out.append("Il lit les sessions lancées depuis le dossier du Studio, pas ses fichiers. Pour l'état du projet "
                   "lui-même, demande un brief du Studio (/studio:brief).")
        return '\n'.join(out)
    out.append(f"Sessions actives cette semaine : {d['actives_n']}")
    if d['attente_absente']:
        out.append("Mon Studio n'est pas installé : les questions qui t'attendent ne sont pas listées "
                   "(Vue Mon Studio absente ; /cockpit:mon-studio pour l'installer).")
    elif d['en_attente']:
        out.append('En attente de toi :')
        out += [f"  - {r['titre']} : {r['texte']}" for r in d['en_attente']]
    elif d.get('attente_indisponible'):
        pass
    else:
        out.append('En attente de toi : rien')
    if d.get('transcripts_absents'):
        pass
    elif d['lourdes']:
        out.append('À alléger :')
        out += [f"  - {r['titre']} ({fmt_tokens(r['contexte'])} jetons de contexte)" for r in d['lourdes']]
    else:
        out.append('À alléger : rien')
    if d.get('transcripts_absents'):
        pass
    elif d['a_archiver']:
        out.append('Finies, à archiver si tu veux :')
        out += [f'  - {t}' for t in d['a_archiver']]
    else:
        out.append('Finies, à archiver si tu veux : rien')
    if d.get('suivi'):
        s = d['suivi']
        out.append(f"Ce Studio est déjà suivi : projet « {s['chantier']} », bouton « Vue projet » de Mon Studio.")
    elif d.get('proposer_suivi'):
        out.append(f"Tu as {d['actives_n']} sessions actives cette semaine : la vue projet de Mon Studio les montre ensemble "
                   f"(bouton « Vue projet »).")
    w = d.get('semaine')
    if w:
        out.append('Sur la semaine :')
        archived = f" (dont {w['archivees_n']} session{'s' if w['archivees_n'] > 1 else ''} archivée{'s' if w['archivees_n'] > 1 else ''})" if w.get('archivees_n') else ''
        out.append(f"  - contexte relu : {fmt_tokens(w['jetons_relus'])}{archived}")
        out.append(f"  - jetons des sous-agents : {fmt_tokens(w['jetons_sous_agents'])} ({w['part_sous_agents']} % du total)")
        if w['plus_cheres']:
            out.append('  - sessions les plus chères :')
            out += [f"    {r['titre']}{' (archivée)' if r.get('archivee') else ''} : {fmt_tokens(r['jetons'])}" for r in w['plus_cheres']]
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description='Point sur les sessions du Studio (lecture seule).')
    ap.add_argument('--dossier', default=os.getcwd())
    ap.add_argument('--semaine', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # Windows consoles default to a legacy code page
    except (AttributeError, ValueError):
        pass
    records = read_records()
    if not records:
        chemin = str(app_sessions_dir())
        msg = f"Je ne lis pas les sessions de l'app ({chemin}) : point impossible."
        print(json.dumps({'erreur': msg, 'chemin': chemin}, ensure_ascii=False, indent=2) if a.json else msg)
        return 2
    d = collect(os.path.abspath(a.dossier), a.semaine, records)
    print(json.dumps(d, ensure_ascii=False, indent=2) if a.json else render(d))
    return 0


if __name__ == '__main__':
    sys.exit(main())
