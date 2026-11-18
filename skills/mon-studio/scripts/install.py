#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installs, checks and repairs Mon Studio on the PM's Mac, without an LLM.

    python3 install.py status                  # JSON: what is in place and what is left to do (read only)
    python3 install.py plan                    # what `apply --connector` would do, in plain words (read only)
    python3 install.py apply [--connector] [--autorisations]
                                               # installs or updates; --connector also declares it in the app;
                                               # --autorisations adds the morning tasks' rules to ~/.claude/settings.json
    python3 install.py repair                  # copies the screen's code again, even when it is up to date
    python3 install.py page <address>          # records the published page, so it is never published twice
    python3 install.py pinned                  # the noted page is pinned again, after a reactivation
    python3 install.py copie-projet <folder> <file> [<name>]
                                               # a copy of the page that opens on this project only (PROJET_FIXE)
    python3 install.py page-projet <folder> <address>
                                               # records the published page of one project, one page per project
    python3 install.py page-projet --retirer <folder>
                                               # forgets that project's page (unpinned by Claude, never deleted)
    python3 install.py disable                 # removes what the skill put on the Mac (relay marker included), silences its hook
    python3 install.py switch <name> <value>   # sets one switch of cockpit.json, on the PM's request (see below)
    python3 install.py brouillons-rattrapage   # notes the drafts sessions left in the last 30 days (todo drafts_catch_up)
    python3 install.py etape matin|terminal    # one step of « Mise en route »: what it lays and costs (matin), or the
                                               # Terminal's login checked (terminal); writes nothing but terminal.json

The installation lays only the base (folder, connector, Mon Studio page, project pages, rules; 2026-11-15, review Q4
and Q8). The morning point (two tasks, their permissions, their models), the first check of each Studio's conflicts and
the Terminal's login are steps of the « Mise en route » block at the head of the board (projets.mise_en_route), each
with its cost and its button, until done or « Pas pour moi » (~/Mon Studio/.parc/mise-en-route.json). `status` asks
for none of them before the PM started the step: the morning tasks' items (allow_scripts, set_task_models, …) once one
task exists, terminal_login once terminal.json exists.

Nothing the PM already has is overwritten: the files of ~/Mon Studio are written only when missing, and an
existing `mon-studio` entry in the app's configuration is kept as is. Only the screen's code (parc.py and
the connector, the page's served code and the question tools) is replaced, in ~/Mon Studio/.parc/: the plugin's folder changes with
every version, so the app always runs these copies, never the plugin's files.

Mon Studio has no local server any more: the pinned page and its connector are the only screen.
`apply` and `repair` take away what an older installation put on the Mac for that server: the launchd agent
io.thetribe.mon-studio (stopped, its plist deleted), ~/Mon Studio/.claude/launch.json and settings.json, the two
pages it served and its journal. A file the PM may have changed is compared with what the installer wrote: when it
differs, it stays and the output says so. `status` lists these leftovers and asks for `remove_server`.

`disable` takes away the same leftovers, the connector's entry (only when it is ours) and the copy of the
connector, and marks Mon Studio disabled in cockpit.json: the session-start hook then copies nothing, even when
the plugin's version moves, and `status` proposes nothing. The files of ~/Mon Studio stay, and so do the
question tools and parc.py, which they load, while ~/Mon Studio/chantiers exists. `apply` lifts the mark: the PM
reactivates Mon Studio by installing it again.

Answering an authorization from the page is off by default, and nothing here turns it on by itself: `apply`,
`repair` and `disable` keep whatever cockpit.json says. The PM asks (« allume les réponses directes ») and the skill runs
`switch`, never a hand edit of the JSON (adoption test of 2026-11-02):

    switch autorisations on|off            autorisations_tableau
    switch reponses-directes on|off        reponses_directes
    switch reponses-directes-minutes <n>   reponses_directes_minutes (1 to 30)
    switch reponses-directes-sessions toutes   ends the trial: drops reponses_directes_sessions, every session answers
    switch decoupe-seuil <tokens>          decoupe_seuil_tokens, the heavy-session hook's threshold (300000 by default)
    switch regle <name> on|off             an optional rule of regles/optionnelles (heures-publication)
    switch rangement on|off                rangement_auto: finished one-action sessions archived (on by default)
    switch rangement-heures <n>            rangement_heures: hours without activity before archiving (24 by default)
    switch reclassement on|off             reclassement_tableau: the board's « Pas si urgent » / « À faire d'abord » button
    switch controle-modele on|off          controle_modele: a session or sub-agent launched without a model is refused
                                           once (hooks/modele_lancement.py; on by default, desktop app sessions only)
    switch controle-format on|off          controle_format: a malformed « À trancher » block is sent back once
                                           (hooks/format_questions.py; on by default, desktop app sessions only)
    switch pm "<Prénom Nom>"               pm: the PM's name as the project sheets write it, which makes a project
                                           « à toi »; an empty name ("") removes it (then git's user.name, then the
                                           Mac account's full name)

The keys:

    "autorisations_tableau": true          the PermissionRequest hook (hooks/autorisation.py) hands each request to
                                           the connector, and the page shows « Autoriser cette fois » / « Refuser »
    "autorisations_sessions": ["…"]        optional: only these sessions (CLI session id or local_… id), for a trial
    "reclassement_tableau": true           the board's lines get one button that moves them in or out of « D'abord »;
                                           the PM's choice holds over the computed one (.parc/reclassees.json) and each
                                           click is noted in .parc/reclassements.jsonl, read by reclassements.py (PM,
                                           2026-11-17: for him alone at first, to learn from his corrections)

Answering a numbered question from the page is off by default too, and follows the same rule:

    "reponses_directes": true              the Stop hook (hooks/reponse_directe.py) keeps a session that just asked a
                                           go or a decision waiting for the PM's click, and the page shows its answers
    "reponses_directes_sessions": ["…"]    optional: only these sessions, for a trial
    "reponses_directes_minutes": 10        optional: how long a session waits, 30 at most

`status` reports them (autorisationsTableau, autorisationsSessions, reponsesDirectes, reponsesDirectesSessions,
reponsesDirectesMinutes). The page declares the connector's page tools (PAGE_TOOLS);
`page` records which ones (pageTools), and `status` asks for `republish_page` with `pageToolsCurrent: false` while the
published page was declared with fewer: it is then republished with its whole `capabilities` declaration.

Drafts not sent (Q39, 2026-11-07): the PostToolUse hook hooks/brouillons.py notes in ~/Mon Studio/.parc/brouillons.json
each Gmail or Slack draft a session leaves; the morning task checks which are still drafts. `status` asks for
`drafts_catch_up` while that file does not exist: `brouillons-rattrapage` reads the transcripts of the last 30 days
(read only) and writes it, even empty.

Answers to a session that does not wait on the page (Q40, 2026-11-09): the connector wakes a sleeping session with the
Terminal's Claude (~/.local/bin/claude, `claude --resume <id> -p "<answer>"`), which needs its own login. `status`
gives `terminalLogin`: "ok", "absent" (no ~/.local/bin/claude) or "deconnecte" (it answers « Not logged in » or « OAuth
session expired »), and asks for `terminal_login` unless "ok". The check is `claude auth status`, then one short
`claude -p` (model haiku, nothing kept) when it says logged in; a positive result is kept 6 hours in
~/Mon Studio/.parc/terminal.json, which the connector also writes when a wake finds the Terminal logged out.

Served page (option B, PM Q13, 2026-11-16): a published page is only a shell, assets/page-epinglee.html (PROJET_FIXE,
title, first paint, a loader). The loader asks the connector's `gabarit` tool for the page's code, assets/page-servie.html
(styles, markup, script), copied into ~/Mon Studio/.parc with the connector, and runs it. A change of the served code
alone republishes nothing: `republish_page` and `republish_project_pages` follow the shell's fingerprint and the tools
declaration only.

Project pages (« épingle-moi le projet X », 2026-11-05): one template, assets/page-epinglee.html (the shell). A project page is a
copy whose `var PROJET_FIXE = "";` holds the Studio's folder (`copie-projet` writes it into Claude's scratchpad copy;
the folder is never written in the repository): it opens on that project only, without « Tous les projets » nor the
tabs, titled with the project's name. cockpit.json keeps `pages_projet` {folder: address} and, per folder, the
template's hash and the tools it was published with (`pages_projet_etat`); `status` gives `projectPages` and the todo
`republish_project_pages` when the template changed since a page was published, as `republish_page` does.

Project pages are pinned by default (PM, 2026-11-06): one per Studio of ~/Mon Studio/projets.json (`studios`), without
asking; the PM unpins what he no longer follows. `status` lists the Studios without a page in `missingProjectPages`
[{dossier, nom}] and asks for `publish_project_pages`. `page-projet --retirer` keeps the folder in
`pages_projet_retirees`, so it never comes back; `page-projet <folder> <address>` takes it out of that list.

The morning tasks' commands (2026-11-10): `apply --autorisations`, run only after the PM's go, adds to ~/.claude/settings.json `permissions.allow` the six rules of
SCRIPT_RULES (matin.py preparer and verifier, written exactly as the tasks' instructions run them, the connector's
tools `slack_ouvertes` and `slack_juger` (the board's Slack lines), its tool `matin_ecrire`, which writes ~/Mon Studio/matin.json only, and its tool `conflits_juger`, which writes the Monday
pass's decisions to a Studio's conflicts register only), only the missing ones, and removes the plugin's former
rule (FORMER_RULES), after a dated copy of the file; nothing else of the file changes, and an unreadable file is left alone.
`apply` without the flag (the hook's update at each version, `update`, `remove_server`) and `repair` never touch the
file: a rule the PM removed is never written back without his go. `plan` announces it in one line, `disable` removes exactly these rules, and `status` gives `scriptRules`
("present", "missing", "unreadable") and asks for `allow_scripts` when they are missing on an installed Mac.
`status` also gives `morningBlocked` and asks for `morning_blocked` when the latest run of « Point du matin » started
today or on the last working day and ~/Mon Studio/matin.json was not written since (the app shows such a run
« succeeded »).
"""
import unicodedata
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
PLUGIN_ROOT = SKILL.parent.parent
PARC_SOURCE = SCRIPTS / 'parc.py'
CONNECTOR_SOURCE = SCRIPTS / 'mcp_mon_studio.py'
# The list by project (projets.py): read by the connector next to parc.py, and run by the morning brief.
PROJETS_SOURCE = SCRIPTS / 'projets.py'
# The morning brief's reader (matin.py): loaded by projets.py, which the connector loads.
MATIN_SOURCE = SCRIPTS / 'matin.py'
# The conflicts register reader of the conflicts skill: loaded by projets.py for the project view's « Conflits » tab.
REGISTRE_SOURCE = PLUGIN_ROOT / 'skills' / 'conflits' / 'scripts' / 'registre.py'
# The conflicts survey, for the cost of a first check said on the board (PM, Q14, 2026-11-15): run without LLM.
CONFLITS_SOURCE = PLUGIN_ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py'
# The pinned pages are a shell (page-epinglee.html: PROJET_FIXE, title, first paint, loader); the page's code
# (page-servie.html: styles, markup, script) is served by the connector's `gabarit` tool from its copy in .parc (Q13).
PAGE_SOURCE = SKILL / 'assets' / 'page-epinglee.html'
PAGE_CODE_SOURCE = SKILL / 'assets' / 'page-servie.html'
MORNING_PROMPT = SKILL / 'assets' / 'consigne-point-du-matin.md'
# The check during the day (11h, 14h, 17h): moves to `regle` what got its answer, nothing else.
MORNING_CHECK_PROMPT = SKILL / 'assets' / 'consigne-point-du-matin-verif.md'
# The drafts' hook and catch-up, run from the plugin's folder (never copied).
DRAFTS_SCRIPT = PLUGIN_ROOT / 'hooks' / 'brouillons.py'
# The question tools: a session of a project calls them from ~/Mon Studio/.parc to number a question to the PM
# (question.py) and to read its project's raw lines (lignes-brutes.py); see SKILL.md.
PROJECT_TOOLS = ('lignes-brutes.py', 'question.py')

HOME = pathlib.Path.home()
MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO', str(HOME / 'Mon Studio')))
INTERNAL = MON_STUDIO / '.parc'
STATE = INTERNAL / 'cockpit.json'
PARC_COPY = INTERNAL / 'parc.py'
CONNECTOR_COPY = INTERNAL / 'mcp_mon_studio.py'
PROJETS_COPY = INTERNAL / 'projets.py'
# The list by project's output: its `studios` are the Studios of this Mac, each with its folder and name.
PROJETS_JSON = MON_STUDIO / 'projets.json'
MATIN_COPY = INTERNAL / 'matin.py'
REGISTRE_COPY = INTERNAL / 'registre_conflits.py'
CONFLITS_COPY = INTERNAL / 'conflits.py'
PAGE_CODE_COPY = INTERNAL / 'page-servie.html'
# The marker the ingestion kit reads: present = Mon Studio is active and relays the kit's news,
# so the kit stops inviting the PM to type « news ». Posed by apply/repair (and `page`) once the page is published,
# removed by `disable`.
RELAY_MARKER = INTERNAL / 'nouvelles-relayees.json'
MORNING_TASK = HOME / '.claude' / 'scheduled-tasks' / 'point-du-matin' / 'SKILL.md'
MORNING_CHECK_TASK = HOME / '.claude' / 'scheduled-tasks' / 'point-du-matin-verif' / 'SKILL.md'
APP_SUPPORT = HOME / 'Library' / 'Application Support' / 'Claude'
# The user's Claude Code settings: scheduled tasks honour its `permissions.allow` rules (docs, « Permissions for
# scheduled tasks »: https://code.claude.com/docs/en/desktop-scheduled-tasks). A run in mode « default » that meets a
# permission prompt waits for an answer nobody gives (2026-11-10: 1 h 46 then cut, nothing written, shown « succeeded »).
# `apply` allows the plugin's own commands the two morning tasks run, exactly as their instructions write them (a Bash
# rule matches the command text Claude writes: https://code.claude.com/docs/en/permissions), nothing broader; `disable`
# removes exactly these rules.
CLAUDE_SETTINGS = HOME / '.claude' / 'settings.json'
# The tasks use no file tool (2026-11-10): preparer and verifier give what they would read, and the point is written by
# the connector's tool `matin_ecrire`, never a shell heredoc (a JSON in a heredoc meets Claude Code's own checks, «
# brace with quote character », before any rule; checked with `claude -p --permission-mode default`). A file tool
# outside the task's folder waited on a prompt (10h56, a Write), and the app grants folder access only by hand.
# The Monday pass of the conflicts (PM, Q18, 2026-11-15) runs inside the morning point: its judgments go to the
# Studios' registers through the connector's tool `conflits_juger`, allowed the same way.
# The midday check closes the Slack lines the PM answered in their thread (PM, Q6, 2026-11-17): it reads them with
# `slack_ouvertes` and writes its judgments with `slack_juger`, which writes the board lines' state only.
SCRIPT_RULES = [f'Bash(python3 ~/Mon\\ Studio/.parc/matin.py {cmd})' for cmd in ('preparer', 'verifier')] \
    + ['mcp__mon-studio__matin_ecrire', 'mcp__mon-studio__conflits_juger',
       'mcp__mon-studio__slack_ouvertes', 'mcp__mon-studio__slack_juger']
# The plugin's own rule of an earlier version (`matin.py ecrire` from matin.json.tmp): `apply --autorisations` and
# `disable` remove it, exactly.
FORMER_RULES = ['Bash(python3 ~/Mon\\ Studio/.parc/matin.py ecrire)']
APP_CONFIG = APP_SUPPORT / 'claude_desktop_config.json'
APP_SESSIONS = APP_SUPPORT / 'claude-code-sessions'
CHANTIERS = MON_STUDIO / 'chantiers'
CONNECTOR_NAME = 'mon-studio'
# The connector's tools the page declares (capabilities.mcp): a page declared with fewer is republished with all.
PAGE_TOOLS = ['lignes', 'projet', 'ouvrir', 'autorisations', 'decider', 'attentes', 'repondre', 'clore', 'lire', 'gabarit']
CONNECTOR_PYTHON = '/usr/bin/python3'
# The Terminal's Claude, which wakes a sleeping session (Q40); the app's own copy has no login usable outside the app.
TERMINAL_CLAUDE = HOME / '.local' / 'bin' / 'claude'
TERMINAL_NOTE = INTERNAL / 'terminal.json'
TERMINAL_OK_S = 6 * 3600
LOGGED_OUT = re.compile(r'^(?:Not logged in|OAuth session expired|OAuth token has expired|Invalid API key|Please run /login)',
                        re.I | re.M)
PAGE_ADDRESS = re.compile(r'^https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+$')

CLAUDE_MD = """# Mon Studio

Ce dossier n'est ni un Studio ni un projet. Il tient Mon Studio, l'écran de toutes tes sessions, posé par `/cockpit:mon-studio` : la page « Mon Studio » épinglée dans l'app, que remplit le connecteur local `mon-studio` (copie dans `.parc/`).

Si on t'écrit ici : ne lis aucun fichier, n'écris rien, n'ouvre ni ne modifie aucune session. Pour toute question sur l'écran, ou si la page est vide : `/cockpit:mon-studio`.
"""

# The CLAUDE.md written while Mon Studio was the `cockpit` skill of the product-kits plugin: it named the old command.
# Replaced by the current one only when the PM left it as it was.
PREVIOUS_CLAUDE_MD = """# Mon Studio

Ce dossier n'est ni un Studio ni un projet. Il tient Mon Studio, l'écran de toutes tes sessions, posé par `/product-kits:cockpit` : la page « Mon Studio » épinglée dans l'app, que remplit le connecteur local `mon-studio` (copie dans `.parc/`).

Si on t'écrit ici : ne lis aucun fichier, n'écris rien, n'ouvre ni ne modifie aucune session. Pour toute question sur l'écran, ou si la page est vide : `/product-kits:cockpit`.
"""

# Written only when missing.
LOCAL_FILES = {
    MON_STUDIO / 'CLAUDE.md': lambda: CLAUDE_MD,
}

# The PM's way of working (three framing answers), kept in ~/Mon Studio. An older kit kept it in ~/.claude/foreman-pm:
# copied once when it is there and missing here, never overwritten.
WAY_OF_WORKING = MON_STUDIO / 'facon-de-travailler.md'
WAY_OF_WORKING_BEFORE = HOME / '.claude' / 'foreman-pm' / 'facon-de-travailler.md'

# --- what an older installation put on the Mac for the local server (since removed) ----------

LEGACY_LABEL = 'io.thetribe.mon-studio'
LEGACY_AGENT = HOME / 'Library' / 'LaunchAgents' / f'{LEGACY_LABEL}.plist'
LEGACY_LAUNCH = MON_STUDIO / '.claude' / 'launch.json'
LEGACY_SETTINGS = MON_STUDIO / '.claude' / 'settings.json'
# The pages the server served, and the journal launchd wrote: produced by parc.py, never by the PM.
LEGACY_PAGES = (MON_STUDIO / 'mon-studio.html', MON_STUDIO / 'mon-studio-ancien.html')
LEGACY_PAGE_MARK = b'<!-- mon-studio:tableau-'
LEGACY_JOURNAL = INTERNAL / 'parc.log'
# The CLAUDE.md the installer wrote when the local screen existed: it told a session here to open that screen.
# Replaced by the current one only when the PM left it as it was.
LEGACY_CLAUDE_MD = """# Mon Studio

Ce dossier n'est ni un Studio ni un projet. Il tient Mon Studio, l'écran de toutes tes sessions, posé par `/product-kits:cockpit`. L'écran du quotidien est la page « Mon Studio » épinglée dans l'app. En secours, l'écran local s'ouvre sans Claude : bouton ▷ de la pastille « Mon Studio » dans le panneau navigateur (configuration de `.claude/launch.json`, qui lance `.parc/parc.py --lanceur`).

Si on t'écrit ici, ta seule tâche : ouvrir l'écran local avec preview_start et le nom « Mon Studio », puis ne rien écrire. Ne recopie jamais l'écran, ne lis aucun fichier, n'écris rien, n'ouvre ni ne modifie aucune session.

Si l'ouverture échoue, ou pour une question sur l'écran : `/product-kits:cockpit`.
"""


def legacy_launch():
    """The launch.json the installer wrote for the app's ▷ button."""
    return {'version': '0.0.1', 'configurations': [{
        'name': 'Mon Studio', 'runtimeExecutable': '/usr/bin/python3', 'runtimeArgs': [str(PARC_COPY), '--lanceur'],
        'port': 47475, 'autoPort': True}]}


def legacy_settings():
    """The settings.json the installer wrote, so that the local session opened its screen without asking."""
    return {'permissions': {'allow': ['mcp__Claude_Browser__preview_start']}}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


# Fingerprint of the pinned page (PM, Q21, 2026-11-15): the pinned pages are republished only when the page really changes.
# The template is read without its comments (HTML <!-- -->, CSS /* */, JS // and /* */ outside strings, regular
# expressions and template literals) and without extra whitespace; any other change (text, style, script) changes it.
# The « v2: » prefix tells it from the raw sha noted before: an old value counts as « to republish » once.
_JS_WORD = re.compile(r'[\w$]')
_WORD_RUN = re.compile(r'[\w$]+')
_SPACE_RUN = re.compile(r'\s+')
_JS_REGEX_AFTER = set('(,=:[!&|?{;+-*%<>~^')
_JS_REGEX_KEYWORDS = {'return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'new', 'delete', 'void', 'throw',
                      'instanceof', 'yield', 'await'}
_CSS_TIGHT = set('{};,')


def _code_separator(prev, nxt, newline, js):
    """What a run of whitespace (or a comment) between two tokens becomes: nothing where it cannot matter."""
    if not js:
        return '' if prev in _CSS_TIGHT or nxt in _CSS_TIGHT else ' '
    if newline:
        return '\n'   # automatic semicolon insertion: a line break can change the meaning
    if _JS_WORD.match(prev) and _JS_WORD.match(nxt):
        return ' '
    if prev.isdigit() and nxt == '.':
        return ' '    # « 1 .toString() » is not « 1.toString() »
    return ' ' if prev == nxt and prev in '+-/' else ''


def _quoted_end(src, i, quote):
    """Index just past the string or template literal opened at i (escapes skipped). A quoted string stops at the end
    of its line, as in JS and CSS; unterminated template: end of text."""
    j, n = i + 1, len(src)
    while j < n:
        if src[j] == '\\':
            j += 2
            continue
        if src[j] == quote:
            return j + 1
        if src[j] == '\n' and quote != '`':
            return j
        if quote == '`' and src.startswith('${', j):
            j = _strip_code(src, j + 2, True, [], nested=True)
            continue
        j += 1
    return n


def _regex_end(src, i):
    """Index just past the regular expression literal opened at i, or None when it is not one (line ends first)."""
    j, n, in_class = i + 1, len(src), False
    while j < n:
        c = src[j]
        if c == '\n':
            return None
        if c == '\\':
            j += 2
            continue
        if c == '[':
            in_class = True
        elif c == ']':
            in_class = False
        elif c == '/' and not in_class:
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            return j
        j += 1
    return None


def _strip_code(src, i, js, out, nested=False):
    """Appends to out the CSS or JS of src from i without comments or extra whitespace; returns where it stopped (the
    end, or just past the « } » closing a template literal's ${ when nested). Where a JS « / » could open a regular
    expression or divide, nothing after it on its line is touched (to the end of the script if a « ` » follows)."""
    n, gap, last, depth = len(src), None, None, 0

    def emit(tok):
        nonlocal gap
        if gap is not None and out:
            out.append(_code_separator(out[-1][-1], tok[0], '\n' in gap, js))
        gap = None
        out.append(tok)

    while i < n:
        c = src[i]
        if c.isspace():
            j = _SPACE_RUN.match(src, i).end()
            gap = (gap or '') + src[i:j]
            i = j
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            # A CSS comment separates nothing; a JS comment holding a line break counts as one.
            if js:
                gap = (gap or '') + ('\n' if '\n' in src[i:j] else ' ')
            i = j
        elif js and src.startswith('//', i):
            j = src.find('\n', i)
            i = n if j < 0 else j
        elif c in '"\'' or (js and c == '`'):
            j = _quoted_end(src, i, c)
            emit(src[i:j])
            last, i = ')', j   # a value: a « / » after it divides
        elif js and c == '/' and (last is None or last in _JS_REGEX_AFTER or last in _JS_REGEX_KEYWORDS):
            j = _regex_end(src, i)
            if j is None:
                emit(c)
                last, i = c, i + 1
            else:
                emit(src[i:j])
                last, i = ')', j
        elif js and c == '/':
            # After « ) », « ] », « } » or a name, « / » usually divides but may open a regular expression: when the
            # rest of the line holds anything a wrong guess could misread, it is kept as it is.
            eol = src.find('\n', i)
            eol = n if eol < 0 else eol
            rest = src[i:eol]
            if '`' in rest:
                eol, rest = n, src[i:]
            if any(s in rest[1:] for s in ('//', '/*', '"', "'", '`')):
                emit(rest)
                last, i = ')', eol
            else:
                emit(c)
                last, i = c, i + 1
        elif (c.isalnum() or c in '_$') and _WORD_RUN.match(src, i):
            j = _WORD_RUN.match(src, i).end()
            emit(src[i:j])
            last, i = src[i:j], j
        else:
            if nested and c == '}' and depth == 0:
                return i + 1
            depth += (c == '{') - (c == '}')
            emit(c)
            last, i = c, i + 1
    return i


_PAGE_BLOCK = re.compile(r'(<(script|style)\b[^>]*>)(.*?)(</\2\s*>)', re.I | re.S)
_HTML_PIECE = re.compile(r'<!--.*?(?:-->|$)|<[A-Za-z/!](?:[^>"\']|"[^"]*"|\'[^\']*\')*>?', re.S)
_TAG_PIECE = re.compile(r'"[^"]*"|\'[^\']*\'|\s+|[^"\'\s]+')


def _strip_tag(tag):
    """A tag with its whitespace reduced outside quoted values, none before « > » or « /> »."""
    out = ''.join(' ' if p.isspace() else p for p in _TAG_PIECE.findall(tag))
    return re.sub(r' (/?>)$', r'\1', out)


def _strip_html(text):
    """HTML without comments; text whitespace reduced to one space as a browser shows it (kept as it is when the
    segment has a <pre> or a <textarea>), attribute values untouched."""
    keep = re.search(r'<(pre|textarea)\b', text, re.I) is not None
    out, words, at = [], [], 0

    def flush():
        joined = ''.join(words)
        out.append(joined if keep else re.sub(r'\s+', ' ', joined))
        words.clear()

    for m in _HTML_PIECE.finditer(text):
        words.append(text[at:m.start()])
        if not m.group().startswith('<!--'):   # a comment drops out; the text around it joins up
            flush()
            out.append(_strip_tag(m.group()))
        at = m.end()
    words.append(text[at:])
    flush()
    return ''.join(out)


def page_essence(html):
    """The page as a reader or a browser gets it: comments out, whitespace reduced."""
    parts, at = [], 0
    for m in _PAGE_BLOCK.finditer(html):
        parts.append(_strip_html(html[at:m.start()]))
        body = []
        _strip_code(m.group(3), 0, m.group(2).lower() == 'script', body)
        parts += [_strip_tag(m.group(1)), ''.join(body), _strip_tag(m.group(4))]
        at = m.end()
    parts.append(_strip_html(html[at:]))
    return ''.join(parts).strip()


def page_sha():
    if not PAGE_SOURCE.exists():
        return None
    return 'v2:' + hashlib.sha256(page_essence(PAGE_SOURCE.read_text(encoding='utf-8')).encode('utf-8')).hexdigest()


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def plugin_version():
    manifest = read_json(PLUGIN_ROOT / '.claude-plugin' / 'plugin.json', {}) or {}
    return manifest.get('version') or 'inconnue'


def copy_state(copy, source):
    if not copy.exists():
        return 'absent'
    return 'current' if sha(copy) == sha(source) else 'different'


def copies_to_install(force=False):
    """Why the screen's code must be copied again into ~/Mon Studio/.parc, or None to keep it.

    A copy that differs from the plugin's is kept once Mon Studio is installed at the plugin's version: it was
    put there by hand, to try a change before it ships. It gives way at the plugin's next version.
    """
    if force:
        return 'réinstallation demandée'
    if not PARC_COPY.exists() or not CONNECTOR_COPY.exists():
        return 'premier passage'
    if not PROJETS_COPY.exists():
        return 'liste par projet absente'
    if not MATIN_COPY.exists():
        return 'point du matin absent'
    if not REGISTRE_COPY.exists():
        return 'registre des conflits absent'
    if not CONFLITS_COPY.exists():
        return 'relevé des conflits absent'
    if not PAGE_CODE_COPY.exists():
        return 'code de la page absent'
    state = read_json(STATE, None)
    if not isinstance(state, dict):
        current = copy_state(PARC_COPY, PARC_SOURCE) == 'current' and copy_state(CONNECTOR_COPY, CONNECTOR_SOURCE) == 'current'
        if not current:
            return 'copie précédente remplacée par celle du plugin'
    elif state.get('version') != plugin_version():
        return f"version {state.get('version')} → {plugin_version()}"
    return None


def same_json(path, expected):
    return read_json(path, None) == expected


def legacy_pages():
    found = []
    for page in LEGACY_PAGES:
        try:
            with page.open('rb') as f:
                f.seek(max(0, page.stat().st_size - 200))
                if LEGACY_PAGE_MARK in f.read():
                    found.append(page)
        except OSError:
            continue
    return found


def server_leftovers():
    """What an older installation left on the Mac for the local server and `apply` would take away, as paths.
    A launch.json or settings.json the PM changed is not listed: it stays."""
    found = [LEGACY_AGENT] if LEGACY_AGENT.exists() else []
    found += [p for p, expected in ((LEGACY_LAUNCH, legacy_launch()), (LEGACY_SETTINGS, legacy_settings()))
              if p.exists() and same_json(p, expected)]
    found += legacy_pages()
    if LEGACY_JOURNAL.exists():
        found.append(LEGACY_JOURNAL)
    claude_md = MON_STUDIO / 'CLAUDE.md'
    if claude_md.exists() and claude_md.read_text(encoding='utf-8', errors='replace') == LEGACY_CLAUDE_MD:
        found.append(claude_md)
    return found


def connector_entry():
    return {'command': CONNECTOR_PYTHON, 'args': [str(CONNECTOR_COPY)]}


def connector_declared():
    """absent, ours (points to the copy in ~/Mon Studio/.parc) or other (an entry we must not touch)."""
    config = read_json(APP_CONFIG, None)
    if not isinstance(config, dict):
        return 'absent'
    entry = (config.get('mcpServers') or {}).get(CONNECTOR_NAME)
    if not entry:
        return 'absent'
    return 'ours' if str(CONNECTOR_COPY) in (entry.get('args') or []) else 'other'


def connector_last_call():
    log = INTERNAL / 'connecteur.log'
    try:
        lines = log.read_text(encoding='utf-8', errors='replace').strip().splitlines()
    except OSError:
        return None
    return lines[-1][:19] if lines else None


def task_body(text):
    """A scheduled task's prompt: what follows its frontmatter (the block between two `---` lines), trailing blanks ignored."""
    text = text.replace('\r\n', '\n')
    if text.startswith('---\n'):
        end = text.find('\n---', 3)
        if end != -1:
            nl = text.find('\n', end + 1)
            text = text[nl + 1:] if nl != -1 else ''
    return text.strip()


# The conflicts' own scheduled tasks of earlier versions (a weekly pass and a prepared preview per Studio), replaced by
# the Monday pass of the morning point and a gesture from the board (PM, Q18, 2026-11-15): found by their prompts' first
# words, never by a title the PM may have changed.
FORMER_CONFLICTS_TASKS = ('Passe hebdomadaire des conflits du Studio', "Préparation de l'aperçu des conflits du Studio")


def former_conflicts_tasks():
    """The taskIds of the conflicts' scheduled tasks of earlier versions still in ~/.claude/scheduled-tasks."""
    found = []
    for path in sorted((HOME / '.claude' / 'scheduled-tasks').glob('*/SKILL.md')):
        try:
            body = task_body(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError):
            continue
        if body.lstrip().startswith(FORMER_CONFLICTS_TASKS):
            found.append(path.parent.name)
    return found


def morning_task_state(task=None, prompt=None):
    """'absent' (no task file), 'current' (its prompt is the plugin's) or 'outdated'. Read only: this script never
    creates nor changes the task, Claude does with the app's own tool (SKILL.md, step 3). Defaults: the morning task;
    the check during the day passes its own files."""
    task, prompt = task or MORNING_TASK, prompt or MORNING_PROMPT
    try:
        text = task.read_text(encoding='utf-8')
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'outdated'
    try:
        wanted = prompt.read_text(encoding='utf-8')
    except OSError:
        return 'current'
    return 'current' if task_body(text) == task_body(wanted) else 'outdated'


def terminal_env():
    return {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE') or k == 'CLAUDE_CONFIG_DIR'}


def terminal_login(now=None):
    """« ok », « absent » or « deconnecte »: can the Terminal's Claude wake a session? `claude auth status` first;
    when it says logged in, one short `claude -p` proves it (an expired login only shows there). A positive answer is
    kept 6 hours (terminal.json); a negative one is asked again each time, so the todo leaves as soon as the PM logs in."""
    now = now or time.time()
    exe = os.environ.get('MON_STUDIO_CLAUDE') or str(TERMINAL_CLAUDE)
    if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
        return 'absent'
    note = read_json(TERMINAL_NOTE, {}) or {}
    if isinstance(note, dict) and note.get('connecte') is True and now - float(note.get('t') or 0) < TERMINAL_OK_S:
        return 'ok'
    env, run = terminal_env(), dict(capture_output=True, text=True, stdin=subprocess.DEVNULL, errors='replace')
    try:
        r = subprocess.run([exe, 'auth', 'status'], timeout=30, env=env, **run)
        try:
            logged = json.loads(r.stdout or '').get('loggedIn') is True
        except (ValueError, AttributeError):
            logged = r.returncode == 0 and not LOGGED_OUT.search(r.stdout + r.stderr)
        if logged:
            r = subprocess.run([exe, '-p', 'Réponds seulement : ok', '--model', 'haiku', '--no-session-persistence',
                                '--permission-mode', 'plan'], timeout=120, cwd=str(HOME), env=env, **run)
            logged = r.returncode == 0 and not LOGGED_OUT.search(r.stdout + r.stderr)
    except (OSError, subprocess.SubprocessError):
        return 'deconnecte'
    try:
        write_atomic(TERMINAL_NOTE, json.dumps({'connecte': logged, 't': now, 'par': 'install'}))
    except OSError:
        pass
    return 'ok' if logged else 'deconnecte'


# The model each morning task should run on, fixed at its creation (2026-11-09, measured cost: in Opus medium for lack
# of a fixed model, the two tasks cost 2.45 $ a day). The app's tool cannot set it: the PM picks it in the task, and
# `status` reads the model of the task's latest run in the app's session records. The PM sets the model in the task's
# Edit form (« Modifier »); a scheduled task's effort cannot be set (no form field, no key, no tool parameter): it runs at
# the app's default effort, so only the model is compared.
# The check is back on Haiku (0.3.9, measured 2026-11-18): a pass makes 34 to 37 model calls and reads 3.5 to 4 million
# tokens from the cache for 16 to 18 open Slack lines (the cost follows the number of open lines), not the 3 to 5 calls
# the Sonnet choice of 0.3.0 assumed; the same volumes on Sonnet cost about 17 times more (see COSTS). Sonnet stays an
# option the PM may choose (Q10, 2026-11-17: on the same 18 lines it closed more consistently), at its real cost: a
# last run on an ALSO_MODELS model does not ask for set_task_models.
TASK_MODELS = {'point-du-matin': 'sonnet', 'point-du-matin-verif': 'haiku'}
ALSO_MODELS = {'point-du-matin-verif': ['sonnet']}
RUN_RECORDS_DAYS = 8


def latest_runs():
    """{task id: session record} of the latest run of each morning task in the app's session records of the last
    RUN_RECORDS_DAYS days; a task with no run is absent. Read only."""
    latest, since = {}, time.time() - RUN_RECORDS_DAYS * 86400
    for path in APP_SESSIONS.glob('*/*/local_*.json'):
        try:
            if path.stat().st_mtime < since:
                continue
            text = path.read_text(encoding='utf-8')
            if '"scheduledTaskId"' not in text:
                continue
            record = json.loads(text)
        except (OSError, ValueError):
            continue
        task = record.get('scheduledTaskId') if isinstance(record, dict) else None
        if task in TASK_MODELS and (task not in latest or (record.get('createdAt') or 0) > (latest[task].get('createdAt') or 0)):
            latest[task] = record
    return latest


def task_models(runs=None):
    """{task id: {'model', 'effort'}} of the latest run of each morning task (latest_runs)."""
    runs = latest_runs() if runs is None else runs
    return {task: {'model': r.get('model'), 'effort': r.get('effort')} for task, r in runs.items()}


# A run still going is not blocked: the morning task is judged MORNING_RUN_MIN minutes after it started.
MORNING_RUN_MIN = 30


def epoch_s(value):
    """A record's createdAt in seconds (the app writes milliseconds), 0 when unreadable."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    return v / 1000 if v > 1e11 else v


def last_working_day(day):
    day -= datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def morning_blocked(run, now=None):
    """True when the latest run of « Point du matin » started today or on the last working day, more than
    MORNING_RUN_MIN minutes ago, and ~/Mon Studio/matin.json was not written since, nor holds that day's point (a replay
    that found the point already written stops without writing). The run then waited on a prompt nobody answered or
    failed: the app still shows it « succeeded » (2026-11-10)."""
    now = time.time() if now is None else now
    start = epoch_s((run or {}).get('createdAt'))
    if not start or now - start < MORNING_RUN_MIN * 60:
        return False
    today = datetime.date.fromtimestamp(now)
    run_day = datetime.date.fromtimestamp(start)
    if run_day not in (today, last_working_day(today)):
        return False
    matin = MON_STUDIO / 'matin.json'
    try:
        if matin.stat().st_mtime >= start:
            return False
    except OSError:
        return True
    written = read_json(matin, None)
    try:
        day = datetime.datetime.fromisoformat(str(written.get('genere_le'))).date()
    except (AttributeError, TypeError, ValueError):
        return True
    return day != run_day


def model_is(run, wanted, also=()):
    """True when a run's model is the wanted family (« haiku » in claude-haiku-…) or one of the also-accepted ones. The
    effort is not compared: a scheduled task cannot choose it."""
    model = str(run.get('model') or '')
    return any(family in model for family in (wanted, *also))


SETUP_STEPS_FILE = INTERNAL / 'mise-en-route.json'
SETUP_STEPS = ('matin', 'terminal')


def setup_steps_state():
    """The steps of « Mise en route »: {'ecartees': [steps the PM set aside], 'matin': 'fait' | 'a_faire' | 'ecarte'}.
    The block itself is computed by projets.mise_en_route for the page; this is what the skill needs. Read only."""
    data = read_json(SETUP_STEPS_FILE, {}) or {}
    aside = data.get('ecartees') if isinstance(data, dict) and isinstance(data.get('ecartees'), dict) else {}
    aside = sorted(k for k in aside if k in SETUP_STEPS)
    done = MORNING_TASK.exists() and MORNING_CHECK_TASK.exists()
    return {'ecartees': aside, 'matin': 'ecarte' if 'matin' in aside else 'fait' if done else 'a_faire'}


def morning_step_items():
    """The COSTS items of the morning step: the task, its check and the Monday pass of the conflicts it carries."""
    return [c for c in COSTS if 'Point du matin' in c[0]]


def setup_step_costs():
    """The cost line of each step, recorded in cockpit.json (`etapes`) for the block (projets.py cannot read COSTS)."""
    usd = sum(cost_usd(c) for c in morning_step_items())
    return {'matin': f'environ {fr(usd, 2)} $ par jour ouvré, {fr(pct_week(usd) * ACTIVE_DAYS, 2)} % de ta semaine '
                     'chaque semaine (« Point du matin » sur Sonnet, estimation à remesurer ; sa vérification sur Haiku, mesurée)',
            'terminal': "moins d'un centime pour la vérification ; ensuite, une réponse par bouton coûte le même tour de "
                        'la session que si tu répondais dedans'}


def step(name):
    """`etape matin`: what the morning step lays and costs, for the PM's go (nothing written). `etape terminal`: the
    Terminal's login, checked now (terminal.json written, as `status` would)."""
    if name == 'terminal':
        return [json.dumps({'terminalLogin': terminal_login()}, ensure_ascii=False)]
    if name != 'matin':
        raise SystemExit('étape inconnue : matin ou terminal')
    lines = ['créerait, avec ton go, la tâche planifiée « Point du matin » (lundi au vendredi, 7h30, Sonnet) : elle lit '
             'tes mails, Slack et ton agenda pour l\'onglet « Today » et, le lundi, relit les conflits nouveaux des Studios '
             'dont tu es PM, déjà vérifiés et sans ingestion automatique',
             'créerait sa vérification, « Point du matin · vérification » (lundi au vendredi, 11h, 14h et 17h au plus, '
             'Haiku ; Sonnet possible, bien plus cher) : elle range dans « réglé » ce qui a eu sa réponse et ferme au tableau les lignes Slack auxquelles tu as répondu dans le fil']
    rules = script_rules_state()
    if rules == 'missing':
        allow = ((read_json(CLAUDE_SETTINGS, {}) or {}).get('permissions') or {}).get('allow') or [] \
            if CLAUDE_SETTINGS.exists() else []
        n = len([r for r in SCRIPT_RULES if r not in allow])
        lines.append(f'ajouterait {n} autorisation{"s" if n > 1 else ""} pour ces tâches dans tes réglages Claude '
                     f'({CLAUDE_SETTINGS}, copie gardée avant), sur les six dont elles ont besoin : les deux seules '
                     'commandes qu\'elles lancent, toutes du plugin, l\'outil « matin_ecrire » du connecteur mon-studio, '
                     'qui n\'écrit que ~/Mon Studio/matin.json, son outil « conflits_juger », qui n\'écrit que le '
                     'registre des conflits d\'un Studio, le lundi, et ses outils « slack_ouvertes » et « slack_juger », '
                     'qui ferment au tableau les lignes Slack auxquelles tu as répondu dans le fil')
    elif rules == 'unreadable':
        lines.append(f'laisserait {CLAUDE_SETTINGS}, illisible : les tâches demanderont leurs autorisations à leur '
                     'première exécution')
    lines.append('te demanderait ensuite un geste par tâche dans « Planifiées » : choisir son modèle (Sonnet pour « Point du '
                 'matin », Haiku pour sa vérification), puis « Exécuter '
                 'maintenant » et « Toujours autoriser » à chaque demande de l\'agenda, de Gmail et de Slack')
    out = [PASTE_START, f'Ce que ça coûte par jour ouvré (« Point du matin » : estimation du {COSTS_DATE} ; sa vérification : '
                        'mesurée le 2026-11-18 ; prix catalogue) :']
    for c in morning_step_items():
        tokens = sum(c[2:5])
        out.append(f'- {c[0]} : {tokens_fr(tokens)} tokens (dont {tokens_fr(c[4])} relus en cache), {fr(cost_usd(c), 2)} $, '
                   f'{fr(pct_week(cost_usd(c)) * ACTIVE_DAYS, 2)} % de la semaine par semaine')
    usd = sum(cost_usd(c) for c in morning_step_items())
    out.append(f'- Total de l\'étape : {fr(usd, 2)} $ par jour, {fr(pct_week(usd) * ACTIVE_DAYS, 2)} % de la semaine par semaine')
    out.append(f'- {verif_sonnet_option()}')
    out.append(PASTE_END)
    return lines + out


def status():
    state = read_json(STATE, None)
    installed = isinstance(state, dict)
    state = state if installed else {}
    runs = latest_runs()
    s = {
        'macos': sys.platform == 'darwin',
        'app': APP_SESSIONS.exists(),
        'pluginVersion': plugin_version(),
        'installed': installed,
        'installedVersion': state.get('version'),
        'disabled': bool(state.get('disabled')),
        'disabledAt': state.get('disabledAt'),
        'files': {str(p.relative_to(MON_STUDIO)): p.exists() for p in LOCAL_FILES},
        'parcCopy': copy_state(PARC_COPY, PARC_SOURCE),
        'connectorCopy': copy_state(CONNECTOR_COPY, CONNECTOR_SOURCE),
        'projetsCopy': copy_state(PROJETS_COPY, PROJETS_SOURCE),
        'matinCopy': copy_state(MATIN_COPY, MATIN_SOURCE),
        'registreCopy': copy_state(REGISTRE_COPY, REGISTRE_SOURCE),
        'conflitsCopy': copy_state(CONFLITS_COPY, CONFLITS_SOURCE),
        'pageCodeCopy': copy_state(PAGE_CODE_COPY, PAGE_CODE_SOURCE),
        'morningTask': morning_task_state(),
        'morningTaskPrompt': str(MORNING_PROMPT),
        'morningCheckTask': morning_task_state(MORNING_CHECK_TASK, MORNING_CHECK_PROMPT),
        'morningCheckTaskPrompt': str(MORNING_CHECK_PROMPT),
        'taskModels': {task: {'wanted': {'model': TASK_MODELS[task]}, 'also': ALSO_MODELS.get(task, []), 'lastRun': run}
                       for task, run in task_models(runs).items()},
        'morningBlocked': morning_blocked(runs.get('point-du-matin')),
        'projectTools': {name: copy_state(INTERNAL / name, SCRIPTS / name) for name in PROJECT_TOOLS},
        'serverLeftovers': [str(p) for p in server_leftovers()],
        'connector': connector_declared(),
        'connectorLastCall': connector_last_call(),
        'page': state.get('page'),
        'newsRelayed': RELAY_MARKER.exists(),
        'pageCurrent': bool(state.get('page')) and state.get('pageSha') == page_sha(),
        'pageToolsCurrent': state.get('pageTools') == PAGE_TOOLS,
        'projectPages': project_pages_state(state),
        'missingProjectPages': missing_project_pages(state),
        'autorisationsTableau': state.get('autorisations_tableau') is True,
        'autorisationsSessions': state.get('autorisations_sessions'),
        'reponsesDirectes': state.get('reponses_directes') is True,
        'reponsesDirectesSessions': state.get('reponses_directes_sessions'),
        'reponsesDirectesMinutes': state.get('reponses_directes_minutes'),
        'rangementAuto': state.get('rangement_auto') is not False,
        'reclassementTableau': state.get('reclassement_tableau') is True,
        'controleModele': state.get('controle_modele') is not False,
        'controleFormat': state.get('controle_format') is not False,
        'rangementHeures': state.get('rangement_heures') or 24,
        'decoupeSeuilTokens': state.get('decoupe_seuil_tokens'),
        'reglesOptionnelles': state.get('regles_optionnelles') or [],
        'draftsNoted': (INTERNAL / 'brouillons.json').exists(),
        'scriptRules': script_rules_state(),
        'formerConflictsTasks': former_conflicts_tasks(),
    }
    s['pmName'], s['pmNameSource'] = pm_name()
    # Asked only where Mon Studio runs: a Mac with the app, installed and not disabled. Never before the PM's go
    # (`installed`): the check runs the Terminal's Claude once (tokens) and writes terminal.json in ~/Mon Studio/.parc.
    # Since 2026-11-15, only once the PM did the Terminal step (terminal.json exists) and did not set it aside.
    steps = setup_steps_state()
    s['miseEnRoute'] = steps
    s['terminalLogin'] = terminal_login() if s['macos'] and s['app'] and installed and not s['disabled'] \
        and TERMINAL_NOTE.exists() and 'terminal' not in steps['ecartees'] else None
    # The morning tasks still in the app: `disable` cannot delete them (only the app's tool can), so a disabled Mon
    # Studio says which ones remain until Claude deletes them.
    s['morningTasksLeft'] = [task for task, path in (('point-du-matin', MORNING_TASK), ('point-du-matin-verif', MORNING_CHECK_TASK))
                             if path.exists()]
    todo = []
    if not s['macos']:
        todo.append('unsupported')
    elif not s['app']:
        todo.append('no_app')
    elif s['disabled']:
        todo.append('disabled')
        if s['morningTasksLeft']:
            todo.append('delete_morning_tasks')
    else:
        if not installed or s['parcCopy'] == 'absent' or s['connectorCopy'] == 'absent':
            todo.append('install')
        elif s['installedVersion'] != s['pluginVersion'] or s['pageCodeCopy'] == 'absent':
            todo.append('update')
        if s['serverLeftovers']:
            todo.append('remove_server')
        if s['connector'] == 'absent':
            todo.append('connector')
        elif s['connector'] == 'other':
            todo.append('connector_other')
        elif not s['connectorLastCall']:
            todo.append('restart_app')
        if not s['page']:
            todo.append('publish_page')
        elif not s['pageCurrent'] or not s['pageToolsCurrent']:
            todo.append('republish_page')
        if any(not p['current'] for p in s['projectPages']):
            todo.append('republish_project_pages')
        if s['missingProjectPages']:
            todo.append('publish_project_pages')
        if (s['page'] or s['projectPages']) and state.get('pageUnpinned'):
            todo.append('pin_page')
        # The morning point is a step of « Mise en route » (2026-11-15): nothing asked before one of its tasks exists.
        morning_started = s['morningTask'] != 'absent' or s['morningCheckTask'] != 'absent'
        if s['morningTask'] == 'absent' and morning_started:
            todo.append('create_morning_task')
        elif s['morningTask'] == 'outdated':
            todo.append('update_morning_task')
        if s['morningCheckTask'] == 'absent' and morning_started:
            todo.append('create_morning_check_task')
        elif s['morningCheckTask'] == 'outdated':
            todo.append('update_morning_check_task')
        if not s['draftsNoted']:
            todo.append('drafts_catch_up')
        if s['scriptRules'] == 'missing' and morning_started and 'install' not in todo and 'update' not in todo:
            todo.append('allow_scripts')
        if s['terminalLogin'] in ('absent', 'deconnecte'):
            todo.append('terminal_login')
        if any(not model_is(t['lastRun'], TASK_MODELS[task], t['also']) for task, t in s['taskModels'].items()):
            todo.append('set_task_models')
        if s['morningBlocked'] and s['morningTask'] != 'absent':
            todo.append('morning_blocked')
        if s['formerConflictsTasks']:
            todo.append('delete_conflicts_tasks')
    s['todo'] = todo
    return s


def pm_name():
    """(name, source) of the PM as projets.identite_et_source finds it: the `pm` setting, git, the Mac account.
    ('', 'aucun') when none, or when projets.py cannot be loaded."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location('projets_nom', PROJETS_SOURCE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        nom, source = mod.identite_et_source()
        return nom or '', source
    except Exception:
        return '', 'aucun'


def studios_found():
    """The names of the Studios a first installation would give a pinned page to, before projets.json exists: the
    working folders of the app's session records that are Studios, as projets.py lists them. Read only, [] on any
    failure. The PM's go must have seen each page named (SKILL.md, « Règles »)."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location('projets_plan', PROJETS_SOURCE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return [os.path.basename(d.rstrip(os.sep)) for d in mod.studios(mod.parc.fiches({'fiches': {}}))]
    except Exception:
        return []


def plan():
    s = status()
    if 'unsupported' in s['todo']:
        return [MAC_ONLY]
    if 'no_app' in s['todo']:
        return [f"Fiches de session de l'app introuvables ({APP_SESSIONS}) : l'app Claude est-elle installée ?"]
    lines = []
    for path in LOCAL_FILES:
        lines.append(f'{"garderait" if path.exists() else "poserait "}  {path}')
    if WAY_OF_WORKING_BEFORE.is_file() and not WAY_OF_WORKING.exists():
        lines.append(f'recopierait {WAY_OF_WORKING_BEFORE} vers {WAY_OF_WORKING}')
    reason = copies_to_install()
    if reason:
        lines.append(f'poserait   le calcul, le connecteur et les outils des projets dans {INTERNAL} : {reason}')
    else:
        lines.append('garderait  le calcul et le connecteur' + kept_copy_note())
    for path in s['serverLeftovers']:
        lines.append(f'retirerait {path} (ancien écran local)')
    for path in changed_legacy_files():
        lines.append(f'laisserait {path} : modifié depuis son installation (ancien écran local, à retirer à la main)')
    if s['connector'] == 'absent':
        lines.append(f"déclarerait le connecteur « {CONNECTOR_NAME} » dans {APP_CONFIG} (une entrée ajoutée, rien d'autre)")
    elif s['connector'] == 'ours':
        lines.append(f'garderait  le connecteur « {CONNECTOR_NAME} », déjà déclaré dans l\'app')
    else:
        lines.append(f'laisserait l\'entrée « {CONNECTOR_NAME} » existante, qui pointe ailleurs que {CONNECTOR_COPY}')
    pages = [m['nom'] for m in s['missingProjectPages']] if PROJETS_JSON.exists() else studios_found()
    if pages:
        lines.append(f'publierait une page épinglée par projet, {len(pages)} en tout, après la page « Mon Studio » : '
                     + ', '.join(pages) + ' (dis celles que tu ne veux pas avant ton go)')
    lines.append('ne poserait pas : le point du matin (deux tâches planifiées et leurs autorisations), le premier relevé '
                 'des conflits de chaque Studio, la connexion du Claude du Terminal. Ce sont les étapes du bloc « Mise en '
                 'route », en tête du tableau dès le premier jour, chacune avec son coût et son bouton, à faire quand tu '
                 'veux ou à écarter (« Pas pour moi »)')
    # Ce qui arrive dans chaque session avec ce go (test d'adoption du 2026-11-02 : rien sans être annoncé).
    try:
        given, skipped = rules_announced()
    except Exception:
        given, skipped = [], []
    if given:
        lines.append('donnerait  ces règles de travail au démarrage de chaque session : ' + ', '.join(given))
    if skipped:
        lines.append('laisserait les règles que ton CLAUDE.md importe déjà : ' + ', '.join(skipped))
    optional = sorted(p.stem for p in OPTIONAL_RULES.glob('*.md'))
    if optional:
        lines.append('ne donnerait pas, sauf demande : ' + ', '.join(optional) + ' (règle optionnelle, `switch regle <nom> on`)')
    lines.append('ajouterait dans chaque session : la consigne de numéroter les questions au PM (dans un projet suivi), '
                 'le rappel de finir par « À trancher » ou « Rien à faire de ton côté », et l\'alerte de session lourde '
                 '(au-delà de 300 000 tokens)')
    # Two things that act without the PM, announced before the go (final review, Q3, 2026-11-18).
    state = read_json(STATE, {}) or {}
    if s['rangementAuto']:
        lines.append(f"rangerait sans toi les sessions finies d'une seule action (lancées par une autre session ou "
                     f"marquées « [jetable] », rien à trancher, inactives depuis {s['rangementHeures']} h) : archivées "
                     "dans la prochaine session où tu écris, rouvrables depuis « Archivées » ; « coupe le rangement » "
                     "l'arrête")
    if state.get('controle_modele') is not False:
        lines.append('refuserait un lancement de session ou de sous-agent sans modèle choisi, jusqu\'à ce que Claude '
                     'le relance avec le modèle du barème (sessions de l\'app seulement ; « coupe le contrôle du modèle » '
                     'l\'arrête)')
    if state.get('controle_format') is not False:
        lines.append('renverrait une fois la session reposter un bloc « À trancher » mal formé (sessions de l\'app '
                     'seulement ; « coupe le contrôle du format » l\'arrête)')
    lines.extend(cost_lines())
    lines.extend(paste_block())
    return lines


# What each item costs a day, shown to the PM before the go (plan). Measured on the author's seat from 2026-10-26 to
# 2026-11-09 (long sessions: 87 messages and 8.4 sessions a day, median context 335,000 tokens), so the rules, the
# reminder line and the question register will cost a PM less. 1 % of the week = 14.5 $ on that seat, a Team seat whose
# budget was raised, which any PM may ask for; a week = 5 active days.
# Each item gives its tokens a day in three parts, so that its $ is recomputed from them at list prices: written (new
# input, written to the cache at x1.25), output, and read again from the cache on every later call of the session.
# A text a hook injects costs mostly in those re-reads. Injected texts are priced at Opus, the morning tasks at the
# model the PM sets for them; the volumes were measured with them on Opus medium. The morning tasks run at the app's
# default effort, high (seen on 2026-11-10, not low as first assumed). « Point du matin » is still an estimate, to
# measure again after the first real run that is not blocked on a permission prompt; its check is measured (2026-11-18).
# (item, basis, written, output, read from cache, model), tokens a day
COSTS_DATE = '2026-11-09'
WEEK_USD = 14.5 * 100
ACTIVE_DAYS = 5


def _prices():
    """$ per million tokens (input, output, cache read), from the plugin's one price list in the conflicts registre."""
    spec = importlib.util.spec_from_file_location('registre_prix', REGISTRE_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PRIX


PRICES = _prices()
CACHE_WRITE = 1.25
COSTS = [
    ('la page Mon Studio et le connecteur', 'scripts locaux, sans Claude', 0, 0, 0, 'opus'),
    ('les règles, au démarrage de chaque session', 'environ 2 400 tokens x 8,4 sessions, relus à chaque appel suivant',
     20_200, 0, 2_650_000, 'opus'),
    ('la ligne de rappel, à chaque message', '60 tokens x 87 messages, relus jusqu\'à la fin de la session',
     5_200, 0, 455_000, 'opus'),
    ('la tâche « Point du matin » (Sonnet, effort par défaut de l\'app (élevé))',
     'estimation à remesurer après la première exécution réelle débloquée : 1 exécution de 7 à 13 appels', 100_000, 9_000, 1_100_000,
     'sonnet'),
    # Measured on 2026-11-18, two real passes on Haiku: 34 and 37 calls, 0.38 M tokens written, 0.14 M and 0.11 M output,
    # 3.49 M and 3.98 M read from the cache, for 16 and 18 open Slack lines. A day is three passes of the average.
    ('« Point du matin · vérification » (Haiku, effort par défaut de l\'app (élevé))',
     'mesuré le 2026-11-18, deux passages réels : 34 à 37 appels et 3,5 à 4 M tokens relus par passage pour 16 à 18 '
     'lignes Slack ouvertes ; le coût suit le nombre de lignes Slack ouvertes ; 3 passages au plus par jour',
     1_140_000, 375_000, 11_205_000, 'haiku'),
    # The Monday pass of the conflicts (PM, Q18, 2026-11-15), in the same run: only what it adds, a fifth of it a day.
    # Not measured: a week of about 20 new subjects (about 12,000 tokens of extracts and the judging instructions, 400
    # output tokens a subject), re-read by the task's 8 calls after `preparer`, x1.5 as conflits.estimer_passe.
    ('la passe des conflits du lundi, dans « Point du matin » (Sonnet)',
     'estimation pour une petite semaine, environ 20 sujets nouveaux dans les Studios dont tu es PM sans ingestion '
     'automatique ; rien une semaine sans rien de nouveau, ni quand la passe est sautée (au-delà de 90 000 caractères '
     'd\'extraits, le cas aujourd\'hui sur les Studios mesurés, 350 sujets et plus par semaine) ; un lundi sur cinq jours', 6_000, 2_400, 48_000, 'sonnet'),
    ('/cockpit:point, une fois par jour', 'skill 1 600 tokens, sortie 250 à 1 250, réponse 500, 3 appels',
     2_850, 500, 285_000, 'sonnet'),
    ('le registre des questions, au démarrage', '700 tokens x 4,8 sessions d\'un Studio', 3_400, 0, 240_000, 'opus'),
    ('le registre des questions, par question', '1 100 tokens x 13 questions, new et settle', 14_300, 0, 320_000, 'opus'),
]
# Items that cost tokens but were not measured on the author's seat (introduced after the measure, or too rare to
# measure): the plan names them without a figure rather than an invented one. (item, what it costs)
UNMEASURED = [
    ('la reprise d\'une session par un bouton de réponse',
     'un tour de la session (`claude --resume -p`) avec la relecture de son contexte, au modèle de la session ; '
     'le même tour que si tu répondais dans la session'),
    ('la lecture des brouillons par « Point du matin »',
     'un appel Gmail par brouillon noté, 10 au plus, au prix de la tâche'),
    ('la vérification de la connexion du Claude du Terminal',
     'un `claude -p` court sur Haiku après l\'installation, gardé 6 h'),
    ('le chargement d\'un skill du cockpit, à chaque appel',
     'environ 11 000 tokens pour /cockpit:mon-studio, 11 000 pour /cockpit:conflits, relus à chaque appel suivant de '
     'la session qui l\'a appelé'),
    ('la publication des pages, à l\'installation puis à chaque version du plugin qui change la page',
     'la session qui publie relit chaque page : environ 63 000 tokens par page sur Sonnet, relevé le 2026-11-15, '
     'soit environ 0,04 % de la semaine pour la page Mon Studio et trois pages projet'),
]
# The register's high bound: each question costs one more round trip of a session whose 335,000-token context is read
# again, twice (new and settle).
QUESTIONS_HIGH_READ = 2 * 335_000 * 13
# The same volumes of the check at Sonnet's price, per measured pass (written, output, read): the PM may choose Sonnet
# for it. An estimate, not measured: no real pass has run on Sonnet.
VERIF_PASSES = [(380_000, 140_000, 3_490_000), (380_000, 110_000, 3_980_000)]
COSTS_THRESHOLDS = (0.5, 2.0)   # % of the week: one launch, normal use in a week (the maintainer's provisional thresholds)
# The first relevé of a Studio's conflicts, once per Studio (a « Mise en route » step, each Studio with its own estimate
# on its line): measured on a real Studio on 2026-11-18, 97 subjects, in the session's transcripts. Sub-agents (Sonnet),
# then the conflicts session's calls that launched and received them (Opus): (item, written, output, read, model).
FIRST_SURVEY_DATE = '2026-11-18'
FIRST_SURVEY = [('les 11 sous-agents', 637_915, 32_779, 2_582_570, 'sonnet'),
                ('la session des conflits', 181_165, 38_759, 6_847_719, 'opus')]


def usd_of(written, output, read, model):
    entree, sortie, relu = PRICES[model]
    return (written * entree * CACHE_WRITE + output * sortie + read * relu) / 1e6


def cost_usd(c):
    return usd_of(*c[2:])


def pct_week(usd):
    return 100 * usd / WEEK_USD


def fr(x, digits):
    return f'{x:.{digits}f}'.replace('.', ',')


def tokens_fr(n):
    return f'{n / 1e6:.2f} M'.replace('.', ',') if n >= 1e6 else f'{n:,}'.replace(',', ' ')


def cost_lines():
    """The cost lines of plan(): one per item, a day, in tokens and as a part of the week, then the total and the
    thresholds."""
    lines = [f'coûterait, mesuré le {COSTS_DATE} sur la place de l\'auteur, sauf « Point du matin », estimation, et sa '
             f'vérification, mesurée le 2026-11-18 (sessions longues : règles, rappel et registre '
             'coûteront moins à un PM ; prix catalogue par million de tokens, entrée / sortie / relu en cache : Opus 4 / 20 '
             '/ 0,20 $, Sonnet 2 / 10 / 0,10 $, Haiku 0,10 / 0,50 / 0,01 $, écriture en cache au prix d\'entrée x 1,25 ; '
             '1 % de la semaine = 14,5 $ sur la place de l\'auteur, une place Team au budget relevé que tout PM peut demander ; '
             'sur une offre plus petite, les mêmes dollars pèsent plus ; semaine de 5 jours) :']
    for c in COSTS:
        item, basis, written, output, read, model = c
        day = pct_week(cost_usd(c))
        lines.append(f'  {item} : {tokens_fr(written)} tokens écrits, {tokens_fr(output)} en sortie et {tokens_fr(read)} '
                     f'relus en cache par jour, {fr(cost_usd(c), 2)} $, {fr(day, 3)} % de la semaine par jour, '
                     f'{fr(day * ACTIVE_DAYS, 2)} % par semaine ({basis})')
        if '· vérification' in item:
            lines.append(f'  {verif_sonnet_option()}')
    usd = sum(cost_usd(c) for c in COSTS)
    launch = next(c for c in COSTS if 'Point du matin »' in c[0] and c[5] == 'sonnet')   # one run, not a day's total
    q = COSTS[-1]
    high = usd - cost_usd(q) + usd_of(q[2], q[3], q[4] + QUESTIONS_HIGH_READ, q[5])
    lines.append(f'  total : {fr(usd, 2)} $ par jour, {fr(pct_week(usd), 2)} % de la semaine par jour, '
                 f'{fr(pct_week(usd) * ACTIVE_DAYS, 1)} % par semaine (seuil : {fr(COSTS_THRESHOLDS[1], 0)} %) ; '
                 f'le lancement quotidien le plus cher, une exécution du point du matin, {fr(pct_week(cost_usd(launch)), 2)} % '
                 f'(seuil : {fr(COSTS_THRESHOLDS[0], 1)} %)')
    lines.append(f'  au plus, si chaque question coûte un aller-retour de plus à sa session : {fr(high, 2)} $ par jour, '
                 f'{fr(pct_week(high) * ACTIVE_DAYS, 1)} % par semaine')
    lines.append(first_survey_line('  '))
    for item, basis in UNMEASURED:
        lines.append(f'  {item} : non mesuré ({basis})')
    return lines


def verif_sonnet_option():
    """The check on Sonnet at its real order of magnitude (estimate, not measured): per pass, a day of three passes, its
    part of the week, and whether it passes the weekly threshold on its own."""
    check = next(c for c in COSTS if '· vérification' in c[0])
    passes = [usd_of(*p, 'sonnet') for p in VERIF_PASSES]
    usd = usd_of(*check[2:5], 'sonnet')
    week = pct_week(usd) * ACTIVE_DAYS
    over = f', au-dessus à elle seule du seuil de {fr(COSTS_THRESHOLDS[1], 0)} %' if week > COSTS_THRESHOLDS[1] else ''
    return (f'option Sonnet pour la vérification (estimation, non mesurée : aucun passage réel sur Sonnet) : mêmes volumes '
            f'au prix Sonnet, environ {fr(min(passes), 1)} à {fr(max(passes), 1)} $ par passage, {fr(usd, 1)} $ par jour '
            f'pour trois passages, {fr(pct_week(usd), 2)} % de la semaine par jour, {fr(week, 1)} % par semaine{over}')


def first_survey_line(prefix):
    """Once per Studio, outside the daily total: the first relevé of its conflicts, as measured."""
    usd = sum(usd_of(*x[1:]) for x in FIRST_SURVEY)
    tokens = sum(sum(x[1:4]) for x in FIRST_SURVEY)
    read = sum(x[3] for x in FIRST_SURVEY)
    return (f'{prefix}une fois par Studio, le premier relevé des conflits (sa ligne « Vérifier les conflits », si tu la fais) : '
            f'mesuré le {FIRST_SURVEY_DATE} sur 97 sujets, {tokens_fr(tokens)} tokens (dont {tokens_fr(read)} relus en cache), '
            f'{fr(usd, 2)} $, {fr(pct_week(usd), 2)} % de la semaine, plus environ 1 $ pour une vingtaine de décisions ; '
            'chaque Studio a son estimation sur sa ligne')


# The cost block Claude pastes unchanged before the go (eval installation-plan, 2026-11-10: presented in Claude's own
# words, the plan lost its token figures and kept only $ and %). Short, one line per item, between two markers.
PASTE_START = '--- à coller tel quel dans ta réponse, sans rien changer ---'
PASTE_END = '--- fin du bloc à coller ---'


def paste_block():
    """The ready-to-paste cost block: per item, tokens a day, $ a day and % of the week a week; then the total."""
    out = [PASTE_START, f'Ce que ça coûte par jour ouvré (mesuré le {COSTS_DATE} sur la place de l\'auteur, prix catalogue ; '
                         '« Point du matin » est une estimation, sa vérification est mesurée le 2026-11-18) :']
    for c in COSTS:
        item, _, written, output, read, _ = c
        tokens = written + output + read
        step_item = ' (étape de mise en route, seulement si tu la fais)' if c in morning_step_items() else ''
        option = f' ; {verif_sonnet_option()}' if '· vérification' in item else ''
        out.append(f'- {item} : {tokens_fr(tokens)} tokens (dont {tokens_fr(read)} relus en cache), {fr(cost_usd(c), 2)} $, '
                   f'{fr(pct_week(cost_usd(c)) * ACTIVE_DAYS, 2)} % de la semaine par semaine{step_item}{option}' if tokens else
                   f'- {item} : 0 token, 0 $')
    usd = sum(cost_usd(c) for c in COSTS)
    tokens = sum(sum(c[2:5]) for c in COSTS)
    base = usd - sum(cost_usd(c) for c in morning_step_items())
    out.append(f'- Total : {tokens_fr(tokens)} tokens, {fr(usd, 2)} $ par jour, {fr(pct_week(usd) * ACTIVE_DAYS, 1)} % de '
               f'la semaine par semaine (seuil : {fr(COSTS_THRESHOLDS[1], 0)} %) ; sans le point du matin : {fr(base, 2)} $ '
               f'par jour, {fr(pct_week(base) * ACTIVE_DAYS, 1)} % de la semaine par semaine')
    out.append(first_survey_line('- ').replace('- une fois', '- Une fois', 1))
    out.append(f'- 1 % de la semaine = {fr(WEEK_USD / 100, 1)} $ sur une place Team au budget relevé, que tout PM peut '
               'demander ; sur une offre plus petite, les mêmes dollars pèsent plus')
    out.append(PASTE_END)
    return out


def install_local_files(lines):
    for path, content in LOCAL_FILES.items():
        if path.exists():
            if path == MON_STUDIO / 'CLAUDE.md' and path.read_text(encoding='utf-8', errors='replace') == PREVIOUS_CLAUDE_MD:
                write_atomic(path, CLAUDE_MD)
                lines.append(f"remplacé   {path} (il nommait l'ancienne commande, /product-kits:cockpit)")
                continue
            lines.append(f'gardé      {path} (déjà là, jamais écrasé)')
            continue
        write_atomic(path, content())
        lines.append(f'posé       {path}')
    if WAY_OF_WORKING_BEFORE.is_file() and not WAY_OF_WORKING.exists():
        write_atomic(WAY_OF_WORKING, WAY_OF_WORKING_BEFORE.read_text(encoding='utf-8'))
        lines.append(f'recopié    {WAY_OF_WORKING} (depuis {WAY_OF_WORKING_BEFORE}, laissé en place)')


def kept_copy_note():
    if copy_state(PARC_COPY, PARC_SOURCE) == 'current' and copy_state(CONNECTOR_COPY, CONNECTOR_SOURCE) == 'current':
        return ', à jour'
    return ' (copie locale différente du plugin, gardée jusqu\'à sa prochaine version)'


def install_project_tools(lines, replace):
    for name in PROJECT_TOOLS:
        target = INTERNAL / name
        if target.exists() and not replace:
            continue
        write_atomic(target, (SCRIPTS / name).read_text(encoding='utf-8'))
        lines.append(f'posé       {target} (outil des projets)')


def copy_atomic(source, target):
    """A copy that keeps the source's date: the connector reloads parc.py when its date changes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    shutil.copy2(source, tmp)
    os.replace(tmp, target)


def install_copies(lines, force=False):
    """Copies parc.py, the connector and the question tools into ~/Mon Studio/.parc when they are missing or
    the plugin's version moved. True when the copies are in place."""
    reason = copies_to_install(force)
    if not reason:
        lines.append('ok         calcul et connecteur' + kept_copy_note())
        install_project_tools(lines, replace=False)
        return True
    connector_changed = copy_state(CONNECTOR_COPY, CONNECTOR_SOURCE) == 'different'
    try:
        copy_atomic(PARC_SOURCE, PARC_COPY)
        copy_atomic(CONNECTOR_SOURCE, CONNECTOR_COPY)
        copy_atomic(PROJETS_SOURCE, PROJETS_COPY)
        copy_atomic(MATIN_SOURCE, MATIN_COPY)
        copy_atomic(REGISTRE_SOURCE, REGISTRE_COPY)
        copy_atomic(CONFLITS_SOURCE, CONFLITS_COPY)
        copy_atomic(PAGE_CODE_SOURCE, PAGE_CODE_COPY)
    except OSError as exc:
        lines.append(f'ÉCHEC      calcul et connecteur dans {INTERNAL} : {exc}')
        return False
    lines.append(f'posé       calcul et connecteur dans {INTERNAL} ({reason})')
    install_project_tools(lines, replace=True)
    if connector_changed:
        lines.append("note       nouveau connecteur copié : l'app le prend au prochain démarrage")
    return True


def changed_legacy_files():
    """launch.json and settings.json of the old local screen that the PM changed: they stay."""
    return [p for p, expected in ((LEGACY_LAUNCH, legacy_launch()), (LEGACY_SETTINGS, legacy_settings()))
            if p.exists() and not same_json(p, expected)]


def launchctl(*args):
    try:
        return subprocess.run(['launchctl', *args], capture_output=True).returncode
    except OSError:
        return None


def remove_server(lines):
    """Takes away what an older installation put on the Mac for the local server. A launch.json or settings.json
    the PM changed stays, and the output says so; the CLAUDE.md of that time is replaced only when unchanged."""
    target = f'gui/{os.getuid()}/{LEGACY_LABEL}' if hasattr(os, 'getuid') else None
    removed = False
    if target and launchctl('print', target) == 0:
        launchctl('bootout', target)
        lines.append(f'arrêté     ancien serveur local ({LEGACY_LABEL})')
        removed = True
    leftovers = server_leftovers()
    claude_md = MON_STUDIO / 'CLAUDE.md'
    for path in leftovers:
        try:
            if path == claude_md:
                write_atomic(path, CLAUDE_MD)
                lines.append(f"remplacé   {path} (il renvoyait à l'ancien écran local)")
            else:
                path.unlink()
                lines.append(f'retiré     {path} (ancien écran local)')
        except OSError as exc:
            lines.append(f'ÉCHEC      {path} (ancien écran local) : {exc}')
        removed = True
    for path in changed_legacy_files():
        lines.append(f"gardé      {path} : modifié depuis son installation, il ne sert plus (ancien écran local) ; "
                     "à retirer à la main si tu n'en veux plus")
    folder = MON_STUDIO / '.claude'
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    return removed


def declare_connector(lines):
    current = connector_declared()
    if current == 'ours':
        lines.append(f'gardé      connecteur « {CONNECTOR_NAME} », déjà déclaré dans l\'app')
        return True
    if current == 'other':
        lines.append(f'gardé      entrée « {CONNECTOR_NAME} » existante, qui pointe ailleurs : non modifiée '
                     f'(attendu : {CONNECTOR_PYTHON} {CONNECTOR_COPY})')
        return False
    if APP_CONFIG.exists():
        config = read_json(APP_CONFIG, None)
        if not isinstance(config, dict):
            lines.append(f"ÉCHEC      configuration de l'app illisible ({APP_CONFIG}) : rien n'est modifié")
            return False
        backup = INTERNAL / 'claude_desktop_config.before-cockpit.json'
        if not backup.exists():
            write_atomic(backup, APP_CONFIG.read_text(encoding='utf-8'))
    else:
        config = {}
    if not isinstance(config.get('mcpServers'), dict):
        config['mcpServers'] = {}
    config['mcpServers'][CONNECTOR_NAME] = connector_entry()
    write_atomic(APP_CONFIG, json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    lines.append(f"déclaré    connecteur « {CONNECTOR_NAME} » dans la configuration de l'app : "
                 "quitter et rouvrir l'app pour qu'elle le lance")
    return True


def record_state(drop=(), **fields):
    state = read_json(STATE, {}) or {}
    state.update(fields)
    for key in drop:
        state.pop(key, None)
    write_atomic(STATE, json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def script_rules_state():
    """'present' when every rule of SCRIPT_RULES is in ~/.claude/settings.json `permissions.allow`, 'missing'
    otherwise, 'unreadable' when the file exists but is not a JSON object (then it is never written)."""
    if not CLAUDE_SETTINGS.exists():
        return 'missing'
    settings = read_json(CLAUDE_SETTINGS, None)
    if not isinstance(settings, dict) or not isinstance(settings.get('permissions', {}), dict) \
            or not isinstance(settings.get('permissions', {}).get('allow', []), list):
        return 'unreadable'
    allow = settings.get('permissions', {}).get('allow', [])
    return 'present' if all(r in allow for r in SCRIPT_RULES) else 'missing'


def backup_settings():
    """A dated copy of ~/.claude/settings.json next to it, before any change."""
    if CLAUDE_SETTINGS.exists():
        backup = CLAUDE_SETTINGS.with_name(f'settings.json.avant-mon-studio-{time.strftime("%Y%m%d-%H%M%S")}')
        shutil.copy2(CLAUDE_SETTINGS, backup)
        return backup
    return None


def write_settings(settings):
    write_atomic(CLAUDE_SETTINGS, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')


def allow_script_rules(lines):
    """Adds the missing SCRIPT_RULES to `permissions.allow`, the rest of the file kept as it is."""
    state = script_rules_state()
    if state == 'present':
        return
    if state == 'unreadable':
        lines.append(f'laissé     {CLAUDE_SETTINGS} : illisible, les autorisations des scripts du plugin restent à donner '
                     'à la main (« Toujours autoriser » à la première exécution de chaque tâche du matin)')
        return
    settings = read_json(CLAUDE_SETTINGS, {}) if CLAUDE_SETTINGS.exists() else {}
    allow = settings.setdefault('permissions', {}).setdefault('allow', [])
    added = [r for r in SCRIPT_RULES if r not in allow]
    backup = backup_settings()
    allow[:] = [r for r in allow if r not in FORMER_RULES] + added
    write_settings(settings)
    lines.append(f'autorisé   {len(added)} {"geste" if len(added) == 1 else "gestes"} du point du matin dans {CLAUDE_SETTINGS}'
                 + (f' (copie avant changement : {backup.name})' if backup else ''))


def remove_script_rules(lines):
    """Removes exactly SCRIPT_RULES from `permissions.allow`, nothing else."""
    settings = read_json(CLAUDE_SETTINGS, None) if CLAUDE_SETTINGS.exists() else None
    if not isinstance(settings, dict) or not isinstance(settings.get('permissions'), dict):
        return
    allow = settings['permissions'].get('allow')
    ours = SCRIPT_RULES + FORMER_RULES
    if not isinstance(allow, list) or not any(r in allow for r in ours):
        return
    backup = backup_settings()
    settings['permissions']['allow'] = [r for r in allow if r not in ours]
    write_settings(settings)
    lines.append(f'retiré     les autorisations des tâches du point du matin de {CLAUDE_SETTINGS} '
                 f'(copie avant changement : {backup.name})')


# Every path the installer writes is a macOS one (~/Library/Application Support/Claude, launchd, /usr/bin/python3):
# under Windows or Linux, apply and disable stop before touching anything (2026-11-09, point 7 of the review).
MAC_ONLY = ("Mon Studio s'installe sur Mac seulement : ses chemins (le dossier de l'app dans ~/Library, launchd) sont "
            "ceux de macOS. Rien n'est posé ni retiré.")


def apply(with_connector=False, force=False, script_rules=False):
    """Only `apply --autorisations`, after the PM's go on `plan` or on `allow_scripts`, touches ~/.claude/settings.json
    (2026-11-10, Q17: `repair` had added the rules without a go, and the hook's update ran `apply` at every version)."""
    if sys.platform != 'darwin':
        print(MAC_ONLY)
        return 2
    s = status()
    if 'unsupported' in s['todo'] or 'no_app' in s['todo']:
        print('\n'.join(plan()))
        return 2
    lines = []
    INTERNAL.mkdir(parents=True, exist_ok=True)
    remove_server(lines)
    install_local_files(lines)
    ok = install_copies(lines, force=force)
    if script_rules:
        allow_script_rules(lines)
    if with_connector:
        declare_connector(lines)
    if s['disabled']:
        # The PM installs again: Mon Studio is back, and the hook follows the plugin's versions again.
        record_state(drop=('disabled', 'disabledAt'))
        lines.append('réactivé   Mon Studio : le hook de démarrage suit de nouveau les versions du plugin')
    if ok:
        record_state(version=plugin_version(), installedAt=time.strftime('%Y-%m-%dT%H:%M:%S'), etapes=setup_step_costs())
        if s['page']:
            pose_relay_marker(lines)
        build_projets(lines)
    print('\n'.join(lines))
    return 0 if ok else 1


def build_projets(lines):
    """On a fresh install projets.json does not exist yet: build it once, so that `status` names the project pages
    (`publish_project_pages`) in the same go. Never rebuilt here when it exists: the connector keeps it current."""
    if PROJETS_JSON.exists():
        return
    try:
        r = subprocess.run([sys.executable, str(PROJETS_COPY)], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, HOME=str(HOME), MON_STUDIO=str(MON_STUDIO)))
    except (OSError, subprocess.SubprocessError) as exc:
        lines.append(f'ÉCHEC      liste par projet ({PROJETS_JSON}) : {exc}')
        return
    if r.returncode == 0 and PROJETS_JSON.exists():
        lines.append(f'calculé    {PROJETS_JSON} (liste par projet)')
    else:
        last = (r.stderr or r.stdout or '').strip().splitlines()[-1:] or ['sans message']
        lines.append(f'ÉCHEC      liste par projet ({PROJETS_JSON}) : {last[0]}')


def pose_relay_marker(lines=None):
    """~/Mon Studio/.parc/nouvelles-relayees.json : {"par": "cockpit", "depuis": <ISO date>}. Its `depuis` is kept when the
    marker is already there."""
    old = read_json(RELAY_MARKER, None)
    if isinstance(old, dict) and old.get('par') == 'cockpit' and old.get('depuis'):
        return
    write_atomic(RELAY_MARKER, json.dumps({'par': 'cockpit', 'depuis': time.strftime('%Y-%m-%dT%H:%M:%S')}, indent=2) + '\n')
    if lines is not None:
        lines.append(f'posé       {RELAY_MARKER} : le kit d\'ingestion sait que Mon Studio relaie ses nouvelles')


def remove_relay_marker(lines):
    try:
        RELAY_MARKER.unlink()
    except FileNotFoundError:
        return
    lines.append(f'retiré     {RELAY_MARKER} : le kit d\'ingestion reprend ses invitations à taper « news »')


def record_page(address):
    if not PAGE_ADDRESS.match(address or ''):
        print(f'Adresse de page refusée : {address!r} (attendu : https://claude.ai/artifact/…)')
        return 1
    if not STATE.exists():
        print("Mon Studio n'est pas encore installé : lancer d'abord `install.py apply`.")
        return 1
    record_state(page=address, pageSha=page_sha(), pageTools=PAGE_TOOLS, pageAt=time.strftime('%Y-%m-%dT%H:%M:%S'))
    lines = [f'noté       page {address}']
    if not (read_json(STATE, {}) or {}).get('disabled'):
        pose_relay_marker(lines)
    print('\n'.join(lines))
    return 0


PROJECT_MARK = 'var PROJET_FIXE = "";'


def project_folder(folder):
    """The Studio's folder as a project page names it: absolute, normalized, no control character; None otherwise."""
    if not isinstance(folder, str) or not folder or len(folder) > 1000 or any(ord(c) < 32 for c in folder):
        return None
    folder = os.path.normpath(os.path.expanduser(folder))
    return folder if os.path.isabs(folder) and folder != os.sep else None


def project_pages(state=None):
    """{folder: address} of the project pages noted in cockpit.json."""
    state = read_json(STATE, {}) if state is None else state
    pages = (state or {}).get('pages_projet') if isinstance(state, dict) else None
    return {k: v for k, v in pages.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(pages, dict) else {}


def project_page_html(folder, name=None):
    """The template with PROJET_FIXE filled: a JSON string, with « </ » escaped so the folder can never close the
    script; the <title> is the project's name."""
    html = PAGE_SOURCE.read_text(encoding='utf-8')
    if html.count(PROJECT_MARK) != 1:
        raise ValueError("point d'injection PROJET_FIXE introuvable dans la page")
    value = json.dumps(folder, ensure_ascii=False).replace('</', '<\\/')
    name = (name or os.path.basename(folder.rstrip(os.sep)) or 'Projet').strip()
    title = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    html = html.replace(PROJECT_MARK, f'var PROJET_FIXE = {value};')
    return html.replace('<title>Mon Studio</title>', f'<title>{title}</title>', 1)


def copy_project_page(folder, target, name=None):
    d = project_folder(folder)
    if not d:
        print(f'Dossier de projet refusé : {folder!r} (attendu : le chemin absolu du Studio)')
        return 1
    if os.path.abspath(target).startswith(str(SKILL) + os.sep):
        print('La copie se fait hors du dépôt (scratchpad) : le dossier du Studio ne s\'écrit jamais dans le plugin.')
        return 1
    write_atomic(pathlib.Path(target), project_page_html(d, name))
    print(f'copié      page du projet {d} -> {target}')
    return 0


def nfc(folder):
    return unicodedata.normalize('NFC', folder or '')


def removed_project_pages(state):
    """The folders whose page the PM took away (`page-projet --retirer`): never proposed again."""
    removed = state.get('pages_projet_retirees') if isinstance(state, dict) else None
    return [d for d in removed if isinstance(d, str)] if isinstance(removed, list) else []


def missing_project_pages(state):
    """[{dossier, nom}] of the Studios of projets.json without a project page, except the ones the PM took away.
    Folders compare in NFC: the Drive and the app may spell an accented folder in either form."""
    data = read_json(PROJETS_JSON, {}) or {}
    studios = data.get('studios') if isinstance(data, dict) else None
    if not isinstance(studios, list):
        return []
    have = {nfc(d) for d in project_pages(state)} | {nfc(d) for d in removed_project_pages(state)}
    out, seen = [], set()
    for s in studios:
        d = project_folder(s.get('dossier')) if isinstance(s, dict) else None
        if not d or nfc(d) in have or nfc(d) in seen:
            continue
        seen.add(nfc(d))
        out.append({'dossier': d, 'nom': str(s.get('nom') or os.path.basename(d))})
    return out


def record_project_page(folder, address):
    d = project_folder(folder)
    if not d:
        print(f'Dossier de projet refusé : {folder!r} (attendu : le chemin absolu du Studio)')
        return 1
    if not PAGE_ADDRESS.match(address or ''):
        print(f'Adresse de page refusée : {address!r} (attendu : https://claude.ai/artifact/…)')
        return 1
    state = read_json(STATE, None)
    if not isinstance(state, dict):
        print("Mon Studio n'est pas encore installé : lancer d'abord `install.py apply`.")
        return 1
    pages, current = project_pages(state), state.get('pages_projet_etat')
    current = dict(current) if isinstance(current, dict) else {}
    if d in pages and pages[d] != address:
        print(f'Ce projet a déjà sa page ({pages[d]}) : une seule page par projet. Republie-la à son adresse.')
        return 1
    pages[d] = address
    current[d] = {'sha': page_sha(), 'tools': PAGE_TOOLS, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    removed = [x for x in removed_project_pages(state) if nfc(x) != nfc(d)]   # asked again: it comes back
    record_state(pages_projet=pages, pages_projet_etat=current, pages_projet_retirees=removed)
    print(f'noté       page du projet {d} : {address}')
    return 0


def forget_project_page(folder):
    d = project_folder(folder)
    state = read_json(STATE, None)
    if not d or not isinstance(state, dict):
        print(f'Aucune page notée pour ce projet : {folder!r}')
        return 1
    pages = project_pages(state)
    noted = next((k for k in pages if nfc(k) == nfc(d)), None)
    address = pages.pop(noted) if noted else None
    current = state.get('pages_projet_etat') if isinstance(state.get('pages_projet_etat'), dict) else {}
    current = {k: v for k, v in current.items() if k != noted}
    removed = removed_project_pages(state)
    if all(nfc(x) != nfc(d) for x in removed):
        removed.append(d)   # never proposed again at installation (publish_project_pages)
    record_state(pages_projet=pages, pages_projet_etat=current, pages_projet_retirees=removed)
    if address:
        print(f'retiré     page du projet {d} ({address}) : à désépingler, sans la supprimer ; plus proposée')
    else:
        print(f'noté       projet {d} : pas de page, et plus proposée à l\'installation')
    return 0


def project_pages_state(state):
    """[{dossier, page, current}]: current is false when the template or its tools changed since its publication."""
    current = state.get('pages_projet_etat') if isinstance(state.get('pages_projet_etat'), dict) else {}
    template = page_sha()
    out = []
    for d, address in sorted(project_pages(state).items()):
        e = current.get(d) if isinstance(current.get(d), dict) else {}
        out.append({'dossier': d, 'page': address, 'current': e.get('sha') == template and e.get('tools') == PAGE_TOOLS})
    return out


def record_pinned():
    state = read_json(STATE, {}) or {}
    if not state.get('page') and not project_pages(state):
        print('Aucune page notée.')
        return 1
    record_state(drop=('pageUnpinned',))
    print('noté       page épinglée')
    return 0


def remove_connector(lines):
    """Takes our `mon-studio` entry out of the app's configuration, and nothing else. True when it did."""
    current = connector_declared()
    if current == 'absent':
        lines.append(f"absent     connecteur « {CONNECTOR_NAME} » dans la configuration de l'app")
        return False
    if current == 'other':
        lines.append(f'gardé      entrée « {CONNECTOR_NAME} » existante, qui pointe ailleurs : non modifiée')
        return False
    config = read_json(APP_CONFIG, None)
    # The same backup as declare_connector, taken just before this write.
    backup = INTERNAL / 'claude_desktop_config.before-disable.json'
    write_atomic(backup, APP_CONFIG.read_text(encoding='utf-8'))
    del config['mcpServers'][CONNECTOR_NAME]
    write_atomic(APP_CONFIG, json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    lines.append(f"retiré     connecteur « {CONNECTOR_NAME} » de la configuration de l'app, cette entrée seule "
                 f'(sauvegarde : {backup})')
    return True


def remove_copies(lines):
    # The question tools serve the projects' registers, and lignes-brutes.py loads parc.py: they stay while
    # ~/Mon Studio/chantiers exists, and the question hook with them.
    copies = [CONNECTOR_COPY, PROJETS_COPY, MATIN_COPY, REGISTRE_COPY, CONFLITS_COPY, PAGE_CODE_COPY]
    if CHANTIERS.exists():
        lines.append(f'gardé      outils des projets et calcul dans {INTERNAL} ({CHANTIERS} existe)')
    else:
        copies += [PARC_COPY] + [INTERNAL / name for name in PROJECT_TOOLS]
    for path in copies:
        if path.exists():
            path.unlink()
            lines.append(f'retiré     {path}')


def disable():
    if sys.platform != 'darwin':
        print(MAC_ONLY)
        return 2
    state = read_json(STATE, None)
    if (not isinstance(state, dict) and not server_leftovers() and connector_declared() != 'ours'
            and not PARC_COPY.exists() and not CONNECTOR_COPY.exists()):
        print("rien       Mon Studio n'est pas installé sur ce Mac : rien à retirer")
        return 0
    state = state if isinstance(state, dict) else {}
    lines = []
    # The mark first: every hook reads it, so they fall silent even if a later removal fails.
    fields = {'disabled': True}
    if not state.get('disabled'):
        fields['disabledAt'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    if state.get('page') or project_pages(state):
        fields['pageUnpinned'] = True
    record_state(**fields)
    remove_server(lines)
    connector_removed = remove_connector(lines)
    remove_copies(lines)
    remove_relay_marker(lines)
    remove_script_rules(lines)
    lines.append('désactivé  Mon Studio : le hook de démarrage ne recopie plus rien, même à une nouvelle version du plugin')
    lines.append(f'gardé      les fichiers de {MON_STUDIO} (CLAUDE.md, chantiers/, fils-rouges.json…)')
    if state.get('page'):
        lines.append(f"à faire    désépingler la page {state['page']}, sans la supprimer")
    for d, address in sorted(project_pages(state).items()):
        lines.append(f'à faire    désépingler la page du projet {os.path.basename(d)} {address}, sans la supprimer')
    for task, path in (('point-du-matin', MORNING_TASK), ('point-du-matin-verif', MORNING_CHECK_TASK)):
        if path.exists():
            lines.append(f'à faire    supprimer la tâche planifiée « {task} » dans l\'app (delete_scheduled_task) : '
                         'sinon elle tourne encore chaque jour ouvré'
                         + (', avec la passe des conflits du lundi' if task == 'point-du-matin' else ''))
    for task in former_conflicts_tasks():
        lines.append(f'à faire    supprimer l\'ancienne tâche des conflits « {task} » dans l\'app (delete_scheduled_task)')
    if connector_removed:
        lines.append("à faire    quitter et rouvrir l'app : elle arrête le connecteur à son démarrage")
    print('\n'.join(lines))
    return 0


BOOLEAN_SWITCHES = {'autorisations': 'autorisations_tableau', 'reponses-directes': 'reponses_directes',
                    'rangement': 'rangement_auto', 'reclassement': 'reclassement_tableau',
                    'controle-modele': 'controle_modele', 'controle-format': 'controle_format'}
OPTIONAL_RULES = PLUGIN_ROOT / 'regles' / 'optionnelles'
SEUIL_MIN = 50000


def rules_announced():
    """(given, skipped): the rules the session-start hook would give in every session, as hooks/regles.py decides."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('regles', PLUGIN_ROOT / 'hooks' / 'regles.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    todo, skipped = mod.rules_to_print({'MON_STUDIO': str(MON_STUDIO)})
    return [r.stem for r in todo], [r.stem for r in skipped]


def switch(name, value):
    """One switch of cockpit.json, in words the PM said; never on Claude's own initiative."""
    if not STATE.is_file():
        print('Mon Studio n\'est pas installé (pas de cockpit.json) : installe-le d\'abord.')
        return 3
    state = read_json(STATE, {}) or {}
    on = {'on': True, 'off': False}
    if name in BOOLEAN_SWITCHES and value in on:
        record_state(**{BOOLEAN_SWITCHES[name]: on[value]})
        print(f'{BOOLEAN_SWITCHES[name]} : {"allumé" if on[value] else "coupé"}.')
        return 0
    if name == 'reponses-directes-sessions' and value == 'toutes':
        record_state(drop=('reponses_directes_sessions',))
        print('reponses_directes_sessions : retiré, toutes les sessions peuvent recevoir une réponse de la page.')
        return 0
    if name == 'reponses-directes-minutes' and value.isdigit() and 1 <= int(value) <= 30:
        record_state(reponses_directes_minutes=int(value))
        print(f'reponses_directes_minutes : {int(value)}.')
        return 0
    if name == 'decoupe-seuil' and value.isdigit() and int(value) >= SEUIL_MIN:
        record_state(decoupe_seuil_tokens=int(value))
        print(f'decoupe_seuil_tokens : {int(value)}.')
        return 0
    if name == 'rangement-heures' and value.isdigit() and 1 <= int(value) <= 24 * 30:
        record_state(rangement_heures=int(value))
        print(f'rangement_heures : {int(value)}.')
        return 0
    if name == 'pm':
        nom = ' '.join(value.split())
        if nom:
            record_state(pm=nom)
            print(f'pm : {nom}. Les projets dont la fiche porte ce nom en PM sont à toi.')
        else:
            record_state(drop=('pm',))
            print('pm : retiré, le nom vient de git (user.name), sinon du compte du Mac.')
        return 0
    if name == 'regle' and ' ' in value:
        rule, _, onoff = value.partition(' ')
        if (OPTIONAL_RULES / f'{rule}.md').is_file() and onoff in on:
            wanted = [r for r in state.get('regles_optionnelles') or [] if r != rule] + ([rule] if on[onoff] else [])
            record_state(regles_optionnelles=wanted)
            print(f'Règle {rule} : {"donnée dans les sessions ouvertes désormais" if on[onoff] else "retirée"}.')
            return 0
    print('Interrupteur inconnu ou valeur invalide. ' + __doc__[__doc__.index('    switch autorisations'):__doc__.index('The keys:')].strip())
    return 2


def drafts_catch_up():
    """The catch-up of hooks/brouillons.py, on this Mon Studio."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('brouillons', DRAFTS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = os.environ.get('MON_STUDIO')
    os.environ['MON_STUDIO'] = str(MON_STUDIO)
    try:
        return mod.main(['rattrapage'])
    except Exception as exc:
        print(f'Rattrapage des brouillons impossible : {exc}')
        return 1
    finally:
        if old is None:
            os.environ.pop('MON_STUDIO', None)
        else:
            os.environ['MON_STUDIO'] = old


def main(argv):
    command = argv[0] if argv else 'status'
    if command == 'status':
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if command == 'plan':
        print('Simulation, rien n\'est modifié.\n' + '\n'.join(plan()))
        return 0
    if command == 'apply':
        return apply(with_connector='--connector' in argv[1:], script_rules='--autorisations' in argv[1:])
    if command == 'repair':
        return apply(with_connector='--connector' in argv[1:], force=True)
    if command == 'page' and len(argv) == 2:
        return record_page(argv[1])
    if command == 'pinned':
        return record_pinned()
    if command == 'copie-projet' and len(argv) in (3, 4):
        return copy_project_page(argv[1], argv[2], argv[3] if len(argv) == 4 else None)
    if command == 'page-projet' and len(argv) == 3 and argv[1] == '--retirer':
        return forget_project_page(argv[2])
    if command == 'page-projet' and len(argv) == 3:
        return record_project_page(argv[1], argv[2])
    if command == 'disable':
        return disable()
    if command == 'brouillons-rattrapage':
        return drafts_catch_up()
    if command == 'etape' and len(argv) == 2 and argv[1] in SETUP_STEPS:
        print('\n'.join(step(argv[1])))
        return 0
    if command == 'switch' and len(argv) == 3:
        return switch(argv[1], argv[2])
    if command == 'switch' and len(argv) == 4 and argv[1] == 'regle':
        return switch('regle', f'{argv[2]} {argv[3]}')
    print(__doc__.strip())
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
