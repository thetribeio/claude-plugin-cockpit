#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conflicts of a Studio (/cockpit:conflits), without LLM: candidates, plan, writing, register. No dependency.

    conflits.py estimer   <studio> [--dossier D] [--incremental]          cost announced before the go (nothing written)
    conflits.py releve    <studio> [--dossier D] [--incremental] [--sortie PLAN.json]
                                                                          candidates and short extracts -> plan
    conflits.py lot       <plan> <k> [--sortie F]                         the extracts of batch k, for one sub-agent
    conflits.py juger-lots <plan> [--paralleles N]                        every batch judged by a headless Sonnet call
                                                                          (claude -p, no tool), then `juger`
    conflits.py juger     <plan> <jugements.json>...                      merges the sub-agents' judgments, prints the preview
    conflits.py apercu    <plan>                                          the preview table again
    conflits.py ecrire    <plan> --pm NOM [--decisions-seules]            after the go: safe markings, additions,
                                                                          PM decisions appended to the register
    conflits.py formulaires <plan>                                        every remaining decision form, prepared
    conflits.py repondre  <plan> --pm NOM --reponses JSON|fichier         one batch of the PM's answers, written
    conflits.py ouverts   <studio>                                        the register's open cases
    conflits.py trancher  <studio> <Cn> <choix> --pm NOM                  voice fallback (« C3 remplacer »)
    conflits.py rouvrir   <studio> <Cn>                                   « rouvre C3 »
    conflits.py reprendre <studio> [--entree F] [--extraction F [--sortie F | --ecrire --pm NOM]]
                                                                          decisions settled by hand before the tool,
                                                                          into the register as settled (reprise.py)

The judgment (is it a contradiction, which class) is made by Sonnet sub-agents on the extracts of `lot`, never on
whole files; everything else is here. What this script writes in a Studio is additive only: a marking line put next to
the old passage, a line at the end of a file, a register case appended, the register's `État` line, a row at the end
of `projet/changelog.md`. Nothing is removed and no existing byte changes. Before writing a marking, the passage is
checked again word for word: a passage that moved since the preview becomes a PM decision, nothing is written there.
A re-run never marks twice. Never Jira, Figma, ticketing nor the story map JSON from here; nothing is sent to anybody.
Ticket corrections of a settled conflict are drafts kept by tickets.py, pushed by the session only on the PM's go.

Code, names and messages to the session are in English or French as the repository does: what the PM reads is French.
"""
import argparse
import datetime as dt
import glob
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import sys
import unicodedata

ICI = pathlib.Path(__file__).resolve().parent
# registre.py next to this file; in ~/Mon Studio/.parc, where Mon Studio keeps copies, it is registre_conflits.py.
_spec = importlib.util.spec_from_file_location(
    'registre_conflits', ICI / 'registre.py' if (ICI / 'registre.py').exists() else ICI / 'registre_conflits.py')
registre = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registre)


def reprise_module():
    """reprise.py (decisions settled by hand before the tool), loaded only when needed."""
    spec = importlib.util.spec_from_file_location('reprise_conflits', ICI / 'reprise.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tickets_module():
    """tickets.py (ticket corrections of a settled conflict), loaded only when needed."""
    spec = importlib.util.spec_from_file_location('tickets_conflits', ICI / 'tickets.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# ---------- wording the PM reads (one place each)

# The PM has not validated this label yet (2026-11-10): the form shows it for « simple discussion », which the register
# always writes. Change it here only.
LIBELLE_GARDER = 'Garder tel quel'
DESCRIPTION_GARDER = "On ignore la nouvelle information ; l'ancienne valeur reste en vigueur. Le registre garde la trace."
LIBELLE_DISCUTER = "Discuter d'abord"
DESCRIPTION_DISCUTER = "Tu m'expliques, on en parle, puis tu me reposes la question."
RECOMMANDE = ' (Recommandé)'
LIBELLES = {'remplacer': 'Remplacer', 'à confirmer avec le client': 'À confirmer avec le client',
            'simple discussion': LIBELLE_GARDER}
DESCRIPTIONS = {'remplacer': "L'ancienne valeur passe dans « Règles remplacées », marquée partout où elle est écrite.",
                'à confirmer avec le client': "L'ancienne valeur reste ; la nouvelle est notée à côté, à confirmer avec le client.",
                'simple discussion': DESCRIPTION_GARDER}
# Three levels of treatment (PM, 2026-11-10, after a real run on a Studio: 32 decisions asked one by one, about 12
# were real ones). A PM decision is a real decision (« arbitrage », asked alone in its form) when at least one of these
# holds; otherwise it is obvious (« évident »): pre-answered with its recommendation, listed, validated by one form.
RAISON_CLIENT, RAISON_ARGENT, RAISON_ORAL, RAISON_SAVOIR = registre.RAISONS
ARGENT = re.compile(r'(?i)(€|\beuros?\b|\bk€|\bprix\b|budget|devis|contrat|contractu|factur|forfait|\bJH\b|'
                    r'jours?[- ]homme|tarif|paiement|avenant|\bsign[ée]e?s?\b|bon de commande|chiffrage|pénalit)')
ORAL = re.compile(r'(?i)(^|/)(reunions?|réunions?|transcripts?|comptes?-rendus|appels?|calls?)/|'
                  r'(transcri|verbatim|debrief|débrief|kick-?off|weekly|atelier|visio|appel|oral)')
CLASSES = {'M': 'marquage sûr', 'PM': 'décision à prendre', 'absence': 'règle à ajouter', 'rien': 'rien à faire'}
GENRES = {'remplace': 'Entrée remplacée', 'question': 'Question peut-être tranchée', 'maj': 'Entrée mise à jour',
          'attente': 'Passage encore en attente, peut-être tranché',
          'regles': 'Deux règles actives voisines', 'revirement': 'Revirement possible dans une source',
          'jumeau': 'Page HTML jumelle d’un document sous bandeau', 'compteur': 'Compteur peut-être périmé',
          'etat': 'Phase du projet peut-être périmée'}
LOT = 10                      # subjects per sub-agent at most
# A batch is read whole, once, by its sub-agent (one Read): it must stay well under the Read tool's limit, and every
# call of the sub-agent re-reads it from the cache. 2026-11-10: batches of up to 170 KB, read in pieces, cost twice the
# estimate. A batch now stops before this many characters of text.
LOT_CARACTERES = 45000
EXTRAITS_MAX = 6              # passages per subject, for a narrow search
# Passages per subject at most, and per file: 76 of 147 subjects of a real Studio hit the old 20, mostly the same value
# copied in a page and its twin; the best-ranked passages carry the subject, the rest only made the batch heavier.
EXTRAITS_SUJET = 8
EXTRAITS_PAR_FICHIER = 2
EXTRAITS_HTML = 2             # passages from html pages per subject (their text, tags removed)
CONTEXTE_LIGNES = 2           # lines around a passage
CONTEXTE_CARACTERES = 500     # a passage's context, at most
CONTEXTE_HTML = 300
ORDRE_ECRITURE = 8            # the session writes its answers every 8 decisions

# ---------- cost (README scale: list prices per million tokens, cache write = input x 1.25; 1 % of the week = 14.5 $)

PRIX = registre.PRIX   # input, output, cache read: the plugin's one price list, in registre.py
PASSE_MATIN_APPELS = 8        # the morning task's calls after `preparer`, which re-read the pass's subjects
POURCENT_USD = 14.5
PLAFOND_LANCEMENT = 0.5       # % of the week
CARACTERES_PAR_TOKEN = 3.5
# Measured on a real Studio's first relevé (2026-11-18, cockpit 0.3.1, the session's transcripts): 97 subjects, 11 batches
# of 10 to 44 KB, 11 Sonnet sub-agents, 3 or 4 calls each. Sub-agents: 638,000 tokens written to the cache, 2.58 million
# read from it, 33,000 output: 2.18 $. Each carried about 78,000 tokens before its batch (system prompt, the 42 tools'
# schemas, the CLAUDE.md and memory rules, the brief, the agent listing), 37,600 of them shared by all and read from the
# cache; its final context 84,000 to 103,000 tokens (1.03 million in all, the figure the app shows). The conflicts
# session (Opus) had 102,000 tokens of context at its first call and made 43 calls to launch and receive the 11
# batches: 181,000 written, 6.85 million read, 39,000 output: 3.05 $. The former model (41,000 tokens a sub-agent, a
# session of 45,000, x 1.5) gave the right total by two errors that cancelled out: sub-agents +48 %, session -49 %.
AGENT_SOCLE = 78000           # a sub-agent's context before its batch
AGENT_SOCLE_PARTAGE = 37600   # of it, shared by every sub-agent (system, tools): written to the cache once, then read
AGENT_APPELS = 3.6            # run `lot`, read the batch, write the judgments, hand back (3 or 4)
CARACTERES_PAR_TOKEN_LOT = 2.7  # a batch as the sub-agent reads it (line numbers, accents): measured
SORTIE_PAR_SUJET = 400
SESSION_BASE = 100000         # the conflicts session's context at its first call (Opus): system, tools, rules, skill
SESSION_PART_ECRITE = 0.55    # of it, written to the cache at the first call (the rest already cached)
SESSION_APPELS_FIXES = 10     # the relevé, `juger`, the preview, a few reads
SESSION_APPELS_PAR_LOT = 3    # launch a sub-agent, receive its hand-back, a check
SESSION_ECRITS_PAR_LOT = 11500
SESSION_CROISSANCE_PAR_LOT = 5000   # the context grows with each batch received
SESSION_SORTIE_FIXE, SESSION_SORTIE_PAR_LOT = 3000, 3250
# The batches judged by the script (`juger-lots`, the default when `claude` is on the PATH), measured on a copy of a
# real Studio (2026-11-23, 64 subjects, 7 batches of 15 to 43 KB, one headless Sonnet call each, two asked again for
# refused or missing subjects): 138,044 input tokens (no cache), 22,940 output: 0.51 $ in 1 min 42 s, against 1.76 $
# announced for the in-session sub-agents. Each call carries about 3,000 tokens besides its batch (the brief as the
# system prompt, under 1,000 of Claude Code's own); a batch's text is 2.15 characters a token, 2.27 on the estimate's
# count. The session (Opus) makes its fixed calls only: one launches `juger-lots` in the background, one reads its end.
TETE_SOCLE = 3000             # a headless call's tokens besides its batch
CARACTERES_PAR_TOKEN_TETE = 2.27
TETE_REPRISES = 1.10          # the subjects asked again (2 of 7 batches, +7 % of the cost, measured)
SESSION_ECRITS_TETE = 15000   # what `juger-lots` hands back to the session: its line and the preview table
PART_PM = 0.20                # fraction of subjects that become PM decisions (2026-11-10 replay: 34 of 171 on a real Studio)
TOKENS_PAR_DECISION = 900     # a prepared form, its answer, its discussion material
MARGE = 1.15                  # rounded up a little: the replay of 2026-11-18 gives +16 %, within 25 % of the measure

# ---------- what a Studio holds

JOURNAUX = {'decisions-log.md', 'changelog.md', 'conflits.md', 'verbatims.md', 'claude.md'}
MAGASINS = {'regles-metier.md', 'questions-ouvertes.md'}
DOSSIERS_SOURCES = {'sources', '1-sources', 'reunions', 'réunions', 'comptes-rendus', 'transcripts', 'archives',
                    'archive', 'node_modules'}
CLIENT = re.compile(r'(?i)(^|/)0-commerce/|(devis|offre|propale|proposition|contrat|cdc|cahier[-_ ]des[-_ ]charges)')
DATEE = re.compile(r'^\d{4}-\d{2}-\d{2}')
MARQUE = ('⚠️', 'ℹ️', '➕', '✅')
STOP = set('''alors aussi autre autres avant avec avoir cette ceux chaque comme dans depuis donc elle elles encore entre
était être faire leur leurs mais même moins notre nous parce pendant plus pour quand quel quelle quelles quels sans
selon sera sont sous tous tout toute toutes très vers votre vous était étaient après doit peut faut point fait faite
ainsi celle celles celui dont lorsque projet studio source décision règle statut actif superseded remplacé remplacée
contexte conséquences date valeur nouvelle ancienne'''.split())

CHAMP = re.compile(r'^\s*[-*]\s+\*\*([^*]+?)\s*:?\s*\*\*\s*:?\s*(.*)$')
TITRE3 = re.compile(r'^###\s+(.+?)\s*$')
TITRE_CODE = re.compile(r'^([A-Z]{1,5}-?\d{1,4})\s*[:·—–-]\s*(.+)$')
TITRE_DATE = re.compile(r'^(\d{4}-\d{2}-\d{2})\b[^:]*:\s*(.+)$')
NOMBRE = re.compile(r'(?<![\w.,])\d+(?:[.,]\d+)?\s*(?:%|€|k€|M€|jours?|j|h|heures?|semaines?|mois|ans?|JH|jh|pièces)?(?![\w])')
CITE = re.compile(r'`([^`]{2,60})`|«\s*([^»]{2,60}?)\s*»|"([^"]{2,60})"')
MAJ = re.compile(r'(?<=[a-zà-ÿ,;:] )([A-ZÀ-Ý][\wÀ-ÿ-]{3,})')

# Every code shown to the PM is followed by « · » and a short title (PM, 2026-11-10): one definition, in registre.py.
CODE = registre.CODE
SANS_TITRE = registre.SANS_TITRE
codes_nus = registre.codes_nus


def etiqueter(texte, titres, defaut=None):
    return registre.etiqueter(texte, titres, defaut)


def pour_le_pm(texte, titres):
    """A text the PM reads: no code at all, a code's title in its place when the Studio gives one (PM, 2026-11-10)."""
    return registre.sans_codes(texte, titres)


# ---------- small helpers

def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold()


def mots(texte):
    """Significant words, lower case, without accents, without a plural « s » or « x »."""
    return {w[:-1] if len(w) > 5 and w[-1] in 'sx' else w
            for w in re.findall(r'[a-z0-9]+', norm(texte)) if len(w) >= 5 and w not in STOP}


def une_ligne(s, n=None):
    s = ' '.join(str(s or '').split())
    return s if n is None or len(s) <= n else s[:n - 1].rstrip() + '…'


def iso_vers_jj(d):
    try:
        return dt.date.fromisoformat(d[:10]).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return None


def aujourdhui():
    return os.environ.get('CONFLITS_AUJOURDHUI') or dt.date.today().isoformat()


def lire_texte(chemin):
    try:
        with open(chemin, encoding='utf-8', newline='') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def ecrire_texte(chemin, texte):
    chemin = pathlib.Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name('.' + chemin.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(texte)
    os.replace(tmp, chemin)


def est_client(rel):
    return bool(CLIENT.search(rel.replace(os.sep, '/')))


def code_libelle(e):
    return f"{e['code']} · {e['libelle']}" if e.get('code') else e.get('libelle') or e.get('titre') or ''


# ---------- reading the Studio's stores
#
# Studios are not homogeneous (seen on real ones, 2026-11-10): entries under `##`, `###` or `####`; « PRJ-1 — Titre »,
# « PRJ-1 : Titre », « 2026-09-30 — Titre », « ~~PRJ-1~~ — … — 🟢 Résolue » ; a status in back ticks; a replacement
# written in a bullet (« 🔴 **Remplacée le 2026-11-04** par **PRJ-51** … », « ➡️ **MAJ 2026-11-04** — … remplacée par
# **PRJ-23** »), partial, or on an entry still active. No list of phrasings decides anything here: whatever may have
# changed a value becomes a candidate, and the Sonnet judgment settles it.

TITRE_ENTREE = re.compile(r'^(#{2,4})\s+(.*\S)\s*$')
CODE_STUDIO = re.compile(r'(?<![\w-])([A-Z]{1,6}-\d{1,4})(?![\w-])')
DATE_ISO = re.compile(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)')
SEPARATEURS = ' \t:·—–-|*_~`'
CLOS = re.compile(r'(?i)✅|🟢|☑|\b(r[ée]solue?s?|tranch[ée]e?s?|clos[e]?|ferm[ée]e?s?|r[ée]pondue?s?|caduque?s?|abandonn[ée]e?s?)\b')
# « solution technique non tranchée », « pas encore résolue »: a heading that says the question is still open.
NON_CLOS = re.compile(r'(?i)\b(?:non|pas(?: encore)?|jamais)\s+(?:tranch|r[ée]solu|clos|ferm|r[ée]pondu)')
REMPLACE = re.compile(r'(?i)superseded|obsol[eè]te|remplac[ée]e?s?|caduque?s?|annul[ée]e?s?')
# The plain fields of an entry: never an update, even when they hold a date and « remplace ».
CHAMPS_FIXES = {'date', 'source', 'sources', 'statut', 'etat', 'contexte', 'decision', 'regle', 'question', 'consequences',
                'remplace par', 'remplacee par', 'validee par', 'valide par', 'a trancher par', 'impact',
                'description', 'enonce', 'origine', 'reference', 'references', 'piste documentee', 'a verifier'}
POINTEURS = {'remplace', 'remplace par', 'remplacee par', 'source', 'sources'}
PUCE_ENTREE = re.compile(r'^[-*+]\s+\*\*~*([A-Z]{1,6}-\d{1,4})~*\*\*\s*[:·—–-]?\s*(.+)$')
BULLE = re.compile(r'^\s*(?:[-*+>]|\d+[.)])\s')
CHANGE = re.compile(r'(?i)\bMAJ\b|mise à jour|superseded|obsol[eè]te|remplac|caduc|tranch|r[ée]solu|\bclos|pr[ée]cis|abandonn|annul|confirm|'
                    r'devient|passe (?:à|de)|n.est plus|ne vaut plus|revu|modifi')
EN_ATTENTE = re.compile(r"(?i)\bà (?:valider|fixer|pr[ée]ciser|arr[êe]ter|trancher|confirmer|planifier|d[ée]finir|d[ée]cider|"
                        r"chiffrer|[ée]crire|compl[ée]ter|choisir|v[ée]rifier|arbitrer|caler)\b|\bnon (?:tranch|arbitr|d[ée]cid|"
                        r"d[ée]fini|fix|valid)|\ben attente\b|\ben cours\b|\bpas encore\b|\bTBD\b|\bTODO\b|- \[ \]|\?\s*(?:\||$)")
# A line a catch-up already touched: a marking by hand (« ⚠️ Remplacé le … source `…`. Rattrapage du 2026-11-10. »,
# « *Remplacé le … — rattrapage du 2026-11-09* », « ⚠️ Non retenu le … Rattrapage du … », often in a table cell) or by
# this script (« — rattrapage du 10/11/2026 »), or an update written during a catch-up.
LIGNE_MARQUEE = re.compile(r'(?i)\b(rattrapage|relecture) du \d')
LECTURE_SEULE = ('.html', '.htm', '.json')     # read for candidates, never written: what they hold goes to the PM
DOSSIERS_HORS = DOSSIERS_SOURCES | {'pilotage', 'node_modules', '.git'}
# A document under a banner (« > ⚠️ **Document d'étape du 02/10/2026**, périmé sur : … ») says itself that it is an
# archive: its old values are meant to be there. Seen on a real Studio: 11 false positives of 19 came from such
# documents and closed questions. Looked for in the first lines only.
# The banner speaks of the document itself, not of an archive it mentions (« > Voir aussi la page archivée »).
BANDEAU = re.compile(r"(?i)document d['’]étape|périm[ée]e? sur\b|ne fait plus foi|n['’]est plus à jour|"
                     r"(?:ce|cette) (?:document|page|fichier|version) (?:est )?(?:archiv[ée]e?|obsol[eè]te|périm[ée]e?|remplac[ée]e?)|"
                     r"^[>\s⚠️*_]*(?:document|page|version) (?:archiv[ée]e?|obsol[eè]te|périm[ée]e?)\b")
BANDEAU_LIGNES = 15


HTML_RETIRE = re.compile(r'(?is)<!--.*?-->|<(script|style)\b.*?</\1\s*>|<[^>]*>')
ENTITES = (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&#39;', "'"), ('&quot;', '"'),
           ('&rsquo;', '’'), ('&laquo;', '«'), ('&raquo;', '»'), ('&eacute;', 'é'), ('&egrave;', 'è'),
           ('&agrave;', 'à'), ('&ccedil;', 'ç'), ('&euro;', '€'))


def texte_html(lignes):
    """The text of an html page, line by line (same line numbers): tags, comments, script and style blocks removed
    over the whole page (a tag or a comment may span lines), entities of everyday French put back. A page's markup
    made most of a batch and matched words for nothing."""
    texte = HTML_RETIRE.sub(lambda m: ' ' + '\n' * m.group(0).count('\n'), '\n'.join(lignes))
    for a, b in ENTITES:
        texte = texte.replace(a, b)
    return [' '.join(l.split()) for l in texte.split('\n')]


def est_html(rel):
    return rel.lower().endswith(('.html', '.htm'))


def bandeau(texte):
    """The banner line of a document that says it is an archive, or None: a warning in its first lines, not a marking
    of a catch-up (« ⚠️ Remplacé le … — rattrapage du … » marks one passage, not the whole document)."""
    vues = 0
    for l in (texte or '').splitlines():
        if not l.strip():
            continue
        vues += 1
        if vues > BANDEAU_LIGNES:
            break
        t = l.strip()
        if ('⚠' in t or t.startswith('>')) and BANDEAU.search(t) and not LIGNE_MARQUEE.search(t):
            return t
    return None


def nettoyer_titre(t):
    """A heading without its strike-through, emphasis and status marks."""
    t = re.sub(r'~~', '', t)
    t = re.sub(r'[✅❓🟢🔴🟠🟡⚠️➡️☑❌✔️]+', ' ', t)
    return ' '.join(t.replace('**', '').split())


def entrees(texte, fichier):
    """The entries of a journal or a store: every heading (level 2 to 4) that holds a code or a date, with its bold
    fields, its update bullets and its state (`actif`, `remplace`, `clos`)."""
    sortie, courante = [], None
    for i, ligne in enumerate((texte or '').splitlines(), 1):
        ligne = ligne.rstrip('\r')
        m = TITRE_ENTREE.match(ligne)
        if m or ligne.startswith('# '):
            courante = None
            if not m:
                continue
            brut = m.group(2)
            propre = nettoyer_titre(brut)
            mc = CODE_STUDIO.search(propre[:40])
            md = DATE_ISO.search(propre[:40])
            if not mc and not md:
                continue                      # a section heading, not an entry
            libelle = propre
            if mc and mc.start() <= 3:
                libelle = propre[mc.end():]
            elif md and md.start() <= 3:
                libelle = propre[md.end():]
                libelle = re.sub(r'^\s*\([^)]*\)', '', libelle)
            libelle = libelle.strip(SEPARATEURS) or propre
            courante = {'titre': propre, 'ligne': i, 'fin': i, 'brute': ligne, 'fichier': fichier, 'champs': {},
                        'code': mc.group(1) if mc and mc.start() <= 3 else None, 'libelle': libelle,
                        'date': md.group(1) if md else None, 'corps': [], 'majs': [],
                        'barre': '~~' in brut, 'marque_clos': bool(CLOS.search(brut)) and not NON_CLOS.search(brut)}
            sortie.append(courante)
            continue
        mb = PUCE_ENTREE.match(ligne)
        if mb and (courante is None or courante.get('puce') or not courante['champs']):
            # A one-line entry: « - **PRJ-4** Progression … ⚠️ *Superseded le 2026-11-06 par PRJ-98.* »
            texte = mb.group(2)
            courante = {'titre': mb.group(1) + ' ' + une_ligne(texte, 80), 'ligne': i, 'fin': i, 'brute': ligne,
                        'fichier': fichier, 'champs': {}, 'code': mb.group(1), 'libelle': une_ligne(re.sub(r'[*_`]', '', texte), 80),
                        'date': None, 'corps': [], 'majs': [], 'barre': '~~' in ligne[:20],
                        'marque_clos': False, 'puce': True}
            sortie.append(courante)
            if CHANGE.search(texte) and DATE_ISO.search(texte):
                courante['majs'].append({'date': DATE_ISO.search(texte).group(1), 'ligne': i,
                                         'texte': une_ligne(re.sub(r'\*\*|`|\*', '', texte), 600),
                                         'codes': [c for c in CODE_STUDIO.findall(texte) if c != mb.group(1)]})
            courante['corps'].append(texte)
            continue
        if courante is None:
            continue
        if courante.get('puce') and not ligne.startswith((' ', '\t')):
            courante = None
            continue
        courante['corps'].append(ligne)
        courante['fin'] = i
        f = CHAMP.match(ligne)
        if f:
            cle = norm(f.group(1)).strip()
            courante['champs'].setdefault(cle, f.group(2).strip().strip('`*_ '))
        if BULLE.match(ligne) and CHANGE.search(ligne) and DATE_ISO.search(ligne) and not (f and norm(f.group(1)).strip() in CHAMPS_FIXES):
            d = DATE_ISO.search(ligne).group(1)
            sortie[-1]['majs'].append({'date': d, 'ligne': i, 'texte': une_ligne(re.sub(r'\*\*|`', '', ligne).lstrip('-*+> '), 600),
                                       'codes': [c for c in CODE_STUDIO.findall(ligne) if c != courante['code']]})
    for e in sortie:
        c = e['champs']
        if not e['date']:
            d = DATE_ISO.search(c.get('date', '') or c.get('source', '') or ' '.join(e['corps'][:6]))
            e['date'] = d.group(1) if d else None
        statut = norm(c.get('statut', '') or c.get('etat', '') or c.get('état', ''))
        e['statut'] = statut
        remplace_bulle = any(re.search(r'(?i)(remplac[ée]e?s?|superseded|obsol[eè]te) (le|par|depuis)', m['texte'][:60] if not e.get('puce') else m['texte'])
                             for m in e['majs'])
        e['remplace_par'] = c.get('remplace par') or c.get('remplacee par') or ''
        if REMPLACE.search(statut) or (e['barre'] and 'question' not in fichier) or e['remplace_par'] or remplace_bulle:
            e['etat'] = 'remplace'
        elif e['marque_clos'] or e['barre'] or re.search(r'resolu|tranch|clos|repondu|ferme', statut):
            e['etat'] = 'clos'
        else:
            e['etat'] = 'actif'
        corps = [l for l in e['corps'] if l.strip() and not CHAMP.match(l) and not l.lstrip().startswith(('>', '|'))]
        e['texte'] = une_ligne(c.get('decision') or c.get('regle') or c.get('question') or c.get('description')
                               or c.get('enonce') or (corps[0].lstrip('-*+ ') if corps else '') or e['libelle'], 600)
        e['source'] = c.get('source', '')
    return sortie


def remplacante(pointeur, candidates):
    """The entry a « Remplacé par » pointer names: by its code, or by its title found in the pointer."""
    p = norm(pointeur)
    for code in CODE_STUDIO.findall(pointeur or ''):
        for e in candidates:
            if e.get('code') == code:
                return e
    meilleure, score = None, 0
    for e in candidates:
        lib = norm(e['libelle'])
        if len(lib) >= 8 and lib in p and len(lib) > score:
            meilleure, score = e, len(lib)
    return meilleure


def source_chemin(texte, studio):
    """The first Studio path cited by a « Source » field, else ''."""
    for m in re.finditer(r'`([^`]+\.[a-z0-9]{1,5})`|([\w./-]+/[\w.-]+\.[a-z0-9]{1,5})', texte or ''):
        chemin = (m.group(1) or m.group(2)).strip()
        if (pathlib.Path(studio) / chemin).exists():
            return chemin
    return ''


def _parcourir(base, racine):
    for chemin, sous, fichiers in os.walk(base):
        sous[:] = sorted(d for d in sous if not d.startswith('.') and norm(d) not in DOSSIERS_HORS
                         and not norm(d).startswith('rattrapage'))
        for f in sorted(fichiers):
            yield os.path.relpath(os.path.join(chemin, f), racine), f


def magasins_du_studio(studio):
    """The journals of decisions, the rules and the open questions: projet/decisions-log.md and its siblings in the
    sub-folders of projet/ (a Studio that holds several products keeps one set per product)."""
    racine = pathlib.Path(studio) / 'projet'
    sortie = {'decisions': [], 'regles': [], 'questions': []}
    if not racine.is_dir():
        return sortie
    for rel, f in _parcourir(racine, pathlib.Path(studio)):
        bas = norm(f)
        for cle, debut in (('decisions', 'decisions-log'), ('regles', 'regles-metier'), ('questions', 'questions-ouvertes')):
            if bas.startswith(debut) and bas.endswith('.md'):
                sortie[cle].append(rel)
    for v in sortie.values():
        v.sort(key=lambda r: (r.count(os.sep), r))
    return sortie


def documents_vivants(studio, dossier=None):
    """Every document a stale value may sit in, as relative paths: md and txt (written to), html and json (read only);
    the stores of decisions, rules and questions too. Not a journal of changes, not a dated source, not under a source,
    hidden, `pilotage` or `rattrapage…` folder. `dossier` limits them to one sub-folder."""
    racine = pathlib.Path(studio)
    sortie = []
    if dossier and any(norm(p) in DOSSIERS_HORS or p.startswith('.') for p in pathlib.Path(dossier).parts):
        return sortie
    for rel, f in _parcourir(racine / dossier if dossier else racine, racine):
        bas = f.lower()
        if f.startswith('.') or not bas.endswith(('.md', '.txt') + LECTURE_SEULE) or not os.path.isfile(racine / rel):
            continue                          # a broken link is not a document
        if bas in JOURNAUX or norm(f).startswith(('decisions-log', 'regles-metier', 'questions-ouvertes', 'changelog',
                                                   'verbatims')) or DATEE.match(f):
            continue
        if bas.endswith('.json') and os.path.getsize(racine / rel) > 3 * 1024 * 1024:
            continue
        sortie.append(rel)
    return sortie


def sources_du_studio(studio):
    """{rel: size} of every dated source (a file whose name starts with a date, or under a source folder)."""
    racine = pathlib.Path(studio)
    sortie = {}
    for chemin, sous, fichiers in os.walk(racine):
        sous[:] = sorted(d for d in sous if not d.startswith('.'))
        dans_sources = any(norm(p) in DOSSIERS_SOURCES for p in pathlib.Path(chemin).relative_to(racine).parts)
        for f in sorted(fichiers):
            if f.lower().endswith(('.md', '.txt')) and (DATEE.match(f) or dans_sources):
                p = os.path.join(chemin, f)
                try:
                    sortie[os.path.relpath(p, racine)] = os.path.getsize(p)
                except OSError:
                    continue
    return sortie


# A source line meets an entry on its substance: four words in common, never a header line (« **Présents :** … »,
# « **Source :** … ») nor a person's name (2026-11-23: three words, names included, gave 24 « revirements » for one day
# of one Studio, most of them a list of attendees or a summary line).
REVIREMENT_MOTS = 4
PUCE = re.compile(r'^\s*(?:[-*+>]|\d+[.)])\s+')
EN_TETE = re.compile(r'(?i)^[*_]*\s*(?:présents?|absents?|participants?|invités?|sources?|date|durée|lieu|résumé|'
                     r'ordre du jour|animateur|rédacteur|destinataires?|de|à|cc|objet|from|to|subject)\s*[*_]*\s*:')
NOM_PROPRE = re.compile(r'(?<![.!?:]\s)(?<!^)\b[A-ZÀ-Ý][a-zà-ÿ]+')


def mots_de_fond(ligne):
    t = PUCE.sub('', ligne.strip())
    if EN_TETE.match(t):
        return set()
    noms = {norm(n) for n in NOM_PROPRE.findall(t)}
    return mots(t) - noms


# ---------- what the last complete pass read (2026-11-23)
# The re-read starts from what the last complete pass read, line by line, never from a file's modification date: the
# Drive rewrites the dates of whole folders (one real Studio, 23/11: 1,037 of 1,175 documents « changed » since the
# 09/11 pass, 500 of them on 19/11), and the « incremental » re-read read the whole Studio again. `lignes-lues.json`, next to the
# register: a 10-hex fingerprint of every line read, and the size of every source; written only with « Dernier
# passage ». Without it (a Studio checked before this file existed), the dates written in the Studio decide: an entry
# dated since « Dernier passage », a source whose name starts with such a date.
LONGUEUR_EMPREINTE = 10


def empreinte(ligne):
    t = ' '.join((ligne or '').split()).lower()
    return hashlib.sha1(t.encode('utf-8')).hexdigest()[:LONGUEUR_EMPREINTE] if t else None


def chemin_lignes_lues(studio):
    return chemin_conflits(studio) / 'lignes-lues.json'


def lire_lignes_lues(studio):
    """{'lignes': set of fingerprints, 'sources': {rel: size}, 'le'} or None when the Studio has none."""
    x = registre._lire_json(chemin_lignes_lues(studio))
    if not isinstance(x, dict) or not isinstance(x.get('lignes'), str) or not isinstance(x.get('sources'), dict):
        return None
    s, n = x['lignes'], LONGUEUR_EMPREINTE
    return {'lignes': {s[k:k + n] for k in range(0, len(s), n)}, 'sources': x['sources'], 'le': x.get('le')}


def ecrire_lignes_lues(plan):
    """After a complete pass: what it read, added to what the passes before it read. False when the plan carries
    nothing or the file could not be written (the Drive refused): « Dernier passage » then stays where it was."""
    lu = plan.get('lu')
    if not isinstance(lu, dict):
        return False
    avant = lire_lignes_lues(plan['studio']) or {'lignes': set(), 'sources': {}}
    n = LONGUEUR_EMPREINTE
    lignes = avant['lignes'] | {lu['lignes'][k:k + n] for k in range(0, len(lu['lignes']) - n + 1, n)}
    try:
        _ecrire_lignes_lues(plan, avant, lignes, lu)
    except OSError:
        return False
    return True


def _ecrire_lignes_lues(plan, avant, lignes, lu):
    ecrire_texte(chemin_lignes_lues(plan['studio']), json.dumps(
        {'version': 1, 'le': plan['date'], 'lignes': ''.join(sorted(lignes)), 'sources': {**avant['sources'], **lu['sources']}},
        ensure_ascii=False))


# ---------- the candidates

def termes_distinctifs(ancien, nouveau):
    """What the old value says that the new one does not: numbers with their unit, quoted terms, proper names, words."""
    n_nouveau = norm(nouveau)
    termes = set()
    for m in NOMBRE.finditer(ancien or ''):
        t = m.group(0).strip()
        if norm(t) not in n_nouveau and not re.fullmatch(r'\d{1,2}', t) and not re.fullmatch(r'(19|20)\d{2}', t):
            termes.add(t)
    for m in CITE.finditer(ancien or ''):
        t = next(g for g in m.groups() if g).strip()
        if norm(t) not in n_nouveau and not CODE_STUDIO.fullmatch(t):
            termes.add(t)
    for m in MAJ.finditer(ancien or ''):
        if norm(m.group(1)) not in n_nouveau:
            termes.add(m.group(1))
    # Plain words the old value has and the new one has not (« mardi » against « jeudi »).
    termes |= mots(ancien) - mots(nouveau)
    return sorted(termes, key=len, reverse=True)


def deja_marque(lignes, i, cle=None, titres=None):
    """True when line i is already marked, by hand or by this script: a marking in the line itself (a table cell,
    « *Remplacé le … — rattrapage du … * »), or on the marking lines right under it, attached to it and to nothing else.
    A table row: a marking under its table that names that row. `cle` makes a marking of this script count even
    without « rattrapage du »."""
    brute = lignes[i].rstrip('\r\n')
    if LIGNE_MARQUEE.search(brute):
        return True
    n = norm(cle) if cle else None
    if brute.lstrip().startswith('|'):
        fin = fin_de_table(lignes, i)
        k = fin + 1
        if k < len(lignes) and not lignes[k].strip():
            k += 1
        nom = norm(f"Rangée « {libelle_rangee(brute, titres)} »")
        rangee = mots(brute)
        while k < len(lignes) and lignes[k].strip() and est_marquage(lignes[k]):
            if nom in norm(lignes[k]):
                return True
            # A catch-up marking by hand under the table names no row: it marks the rows with words in common
            # (seen: « ⚠️ Remplacé … par <décision> (jalons et dates butoirs du contrat …) » under a table of dates).
            if LIGNE_MARQUEE.search(lignes[k]) and 'rangee «' not in norm(lignes[k]) \
                    and len(rangee & mots(lignes[k])) >= 2:
                return True
            k += 1
        return False
    k = i + 1
    while k < len(lignes) and lignes[k].strip() and est_marquage(lignes[k]):
        if LIGNE_MARQUEE.search(lignes[k]) or (n and n in norm(lignes[k])):
            return True
        k += 1
    return False


def est_marquage(ligne):
    t = ligne.strip().lstrip('-*>_ ').lstrip()
    return t.startswith(MARQUE) or bool(LIGNE_MARQUEE.match(t.lstrip('⚠️ℹ️➕✅ *_')))


def extrait(rel, i, brute, lignes):
    a, b = max(0, i - CONTEXTE_LIGNES), min(len(lignes), i + CONTEXTE_LIGNES + 1)
    html = est_html(rel)
    largeur = CONTEXTE_HTML if html else CONTEXTE_CARACTERES
    contexte = '\n'.join(l.rstrip('\r')[:largeur] for l in lignes[a:b] if not html or l.strip())
    lecture_seule = rel.lower().endswith(LECTURE_SEULE)
    return {'fichier': rel, 'ligne': i + 1, 'passage': brute if not lecture_seule else brute[:300],
            'contexte': contexte[:largeur], 'client': est_client(rel), 'lecture_seule': lecture_seule}


def valeur(e, studio, defaut):
    return {'texte': une_ligne(e['texte'], 400), 'source': source_chemin(e['source'], studio) or defaut,
            'date': iso_vers_jj(e['date']) if e.get('date') else None, 'code': e.get('code'),
            'libelle': e['libelle'], 'entree': une_ligne(e['brute']), 'document': e['fichier']}


class Lignes:
    """Every line of the documents, read once, with an index by word and by code."""

    def __init__(self, studio, docs):
        self.studio, self.lignes, self.par_mot, self.par_code, self.textes = studio, [], {}, {}, {}
        for rel in docs:
            texte = lire_texte(pathlib.Path(studio) / rel)
            if texte is None:
                continue
            ls = texte.splitlines()
            if est_html(rel):
                ls = texte_html(ls)
            self.textes[rel] = ls
            for i, brute in enumerate(ls):
                brute = brute.rstrip('\r')
                if not brute.strip() or len(brute.strip()) < 12 or est_marquage(brute) or deja_marque(ls, i):
                    continue
                f = CHAMP.match(brute)
                if f and norm(f.group(1)).strip() in POINTEURS:
                    continue                  # « Remplace : … », « Source : … » point at the old value on purpose
                k = len(self.lignes)
                coupe = brute[:2000]
                m = mots(coupe)
                self.lignes.append((rel, i, brute, m, norm(coupe), set(CODE_STUDIO.findall(coupe))))
                for w in m:
                    self.par_mot.setdefault(w, []).append(k)
                for c in self.lignes[k][5]:
                    self.par_code.setdefault(c, []).append(k)

    def chercher(self, termes, sujet_mots, codes, exclues, n=None):
        """Lines holding a code of `codes`, or a distinctive term with the subject; best first."""
        n = n or EXTRAITS_MAX
        candidats = set()
        for c in codes:
            candidats.update(self.par_code.get(c, ()))
        mots_termes = [norm(t) for t in termes if re.fullmatch(r'[a-z0-9]+', norm(t))]
        autres = [norm(t) for t in termes if not re.fullmatch(r'[a-z0-9]+', norm(t)) and norm(t)]
        for w in mots_termes:
            candidats.update(self.par_mot.get(w, ()))
        if autres:
            for w in sujet_mots:
                for k in self.par_mot.get(w, ()):
                    if any(a in self.lignes[k][4] for a in autres):
                        candidats.add(k)
        trouves = []
        for k in candidats:
            rel, i, brute, m, low, cs = self.lignes[k]
            if (rel, i) in exclues:
                continue
            a_code = bool(cs & set(codes))
            touche = sum(1 for w in mots_termes if w in m) + sum(1 for a in autres if a in low)
            communs = len(sujet_mots & m)
            if not (a_code or (touche and communs >= 2) or (touche >= 2 and communs >= 1)):
                continue
            trouves.append((4 * a_code + 2 * touche + communs, rel, i, brute))
        trouves.sort(key=lambda x: (-x[0], x[1], x[2]))
        return [(rel, i, brute, self.textes[rel]) for _, rel, i, brute in plafonner(trouves, n)]


def plafonner(trouves, n):
    """The best `n` passages, at most EXTRAITS_PAR_FICHIER from one file and EXTRAITS_HTML from html pages: the same
    value copied down a page, or in a page and its twin, says nothing more to the judge."""
    garde, par_fichier, html = [], {}, 0
    for t in trouves:
        rel = t[1]
        if par_fichier.get(rel, 0) >= EXTRAITS_PAR_FICHIER or (est_html(rel) and html >= EXTRAITS_HTML):
            continue
        garde.append(t)
        par_fichier[rel] = par_fichier.get(rel, 0) + 1
        html += est_html(rel)
        if len(garde) >= n:
            break
    return garde


HISTORIQUE = re.compile(r'^\s*(?:[-*+|]\s*)?\**\(?\d{4}-\d{2}-\d{2}')     # a dated line of a history: a past fact
NB_OUVERTES = re.compile(r'(?i)(?<![\w-])(\d+)\s+(?:questions?\s+)?ouvertes?\b')
NB_CLOSES = re.compile(r'(?i)(?<![\w-])(\d+)\s+(?:questions?\s+)?(?:closes?|ferm[ée]es?|r[ée]solues?|tranch[ée]es?)\b')
NB_REMPLACEES = re.compile(r'(?i)(?<![\w-])(\d+)\s+(?:d[ée]cisions?\s+)?(?:remplac[ée]es?|superseded)\b')
NB_CARTE = re.compile(r'(?i)(?<![\w-])(\d+)\**\s+\**(th[èe]mes?|initiatives?|epics?|fonctionnalit[ée]s?)\b')
CARTE_CLES = {'theme': 'themes', 'initiative': 'initiatives', 'epic': 'epics', 'fonctionnalite': 'fonctionnalites'}
CARTE_MOTS = {'themes': 'thèmes', 'initiatives': 'initiatives', 'epics': 'epics', 'fonctionnalites': 'fonctionnalités'}
PHASE_DEPUIS = re.compile(r'(?i)\bphase\s*(\d)\b[^|\n]{0,80}?depuis le (\d{4}-\d{2}-\d{2})')
PHASE_PASSAGE = re.compile(r'(?i)\b(?:passage|passe|bascule|entr[ée]e?)\s+en\s+phase\s*(\d)\b')
PHASE_DITE = re.compile(r"(?i)\bphase(?:\s+(?:actuelle|en cours|courante|du projet))?\s*\**\s*[:|]\s*\**\s*(?:phase\s*)?(\d)\b|"
                        r"\b(?:actuellement|aujourd['’]hui|projet|sommes)\s+en\s+phase\s*(\d)\b")


def carte_du_studio(studio):
    """The story map JSON (/studio:story-map): the most recent `story-mapping*.json`, outside archives, with its counts."""
    meilleur = None
    for rel, f in _parcourir(pathlib.Path(studio), pathlib.Path(studio)):
        if norm(f).startswith('story-mapping') and f.lower().endswith('.json'):
            try:
                t = os.path.getmtime(pathlib.Path(studio) / rel)
            except OSError:
                continue
            if meilleur is None or (f == 'story-mapping.json', t) > (os.path.basename(meilleur[0]) == 'story-mapping.json', meilleur[1]):
                meilleur = (rel, t)
    if not meilleur:
        return None, {}
    try:
        with open(pathlib.Path(studio) / meilleur[0], encoding='utf-8') as h:
            d = json.load(h)
    except (OSError, ValueError):
        return None, {}
    return meilleur[0], {k: len(d[k]) for k in CARTE_MOTS if isinstance(d, dict) and isinstance(d.get(k), list) and d[k]}


def etat_du_projet(studio, magasins, questions, decisions, index):
    """(genre, title, expected value, source, lines) for each count or phase a living line states and the Studio
    contradicts: open and closed questions, replaced decisions (counted in the stores), story map items (counted in its
    JSON), the project's phase (the latest « Phase N … depuis le … » or « passage en Phase N »). A dated history line
    tells a past fact and is never one of them."""
    sortie = []
    vivantes = [(rel, i, brute) for rel, i, brute, m, low, cs in index.lignes if not HISTORIQUE.match(brute)]
    # A Studio with several products keeps one journal per product: a line may count one of them or all of them.
    par_journal = lambda es, f: {sum(1 for e in es if f(e) and e['fichier'] == j) for j in {e['fichier'] for e in es}} | \
        {sum(1 for e in es if f(e))}
    if questions and magasins['questions']:
        ouvertes = sum(1 for q in questions if q['etat'] == 'actif')
        closes = len(questions) - ouvertes
        admis_o = par_journal(questions, lambda q: q['etat'] == 'actif')
        admis_c = par_journal(questions, lambda q: q['etat'] != 'actif')
        lignes_ = [(rel, i, brute, index.textes[rel]) for rel, i, brute in vivantes if 'question' in norm(brute)
                   and any(int(m.group(1)) not in admis for rx, admis in ((NB_OUVERTES, admis_o), (NB_CLOSES, admis_c))
                           for m in rx.finditer(brute))]
        if lignes_:
            sortie.append(('compteur', 'Nombre de questions ouvertes et closes',
                           f"{ouvertes} questions ouvertes et {closes} closes, compte du relevé dans {magasins['questions'][0]}",
                           magasins['questions'][0], plafonner([(0,) + t for t in lignes_], EXTRAITS_SUJET)))
    if decisions and magasins['decisions']:
        remplacees = sum(1 for d in decisions if d['etat'] == 'remplace')
        admis = par_journal(decisions, lambda d: d['etat'] == 'remplace')
        lignes_ = [(rel, i, brute, index.textes[rel]) for rel, i, brute in vivantes if 'decision' in norm(brute)
                   and any(int(m.group(1)) not in admis for m in NB_REMPLACEES.finditer(brute))]
        if lignes_:
            sortie.append(('compteur', 'Nombre de décisions remplacées',
                           f"{remplacees} décisions remplacées, compte du relevé dans {magasins['decisions'][0]}",
                           magasins['decisions'][0], plafonner([(0,) + t for t in lignes_], EXTRAITS_SUJET)))
    carte, comptes = carte_du_studio(studio)
    if comptes:
        lignes_ = []
        for rel, i, brute in vivantes:
            if rel == carte or re.search(r'(?i)\blot\s*\d', brute):
                continue            # a batch's own count is not the map's
            trouves = [(CARTE_CLES[re.sub(r's$', '', norm(m.group(2)))], int(m.group(1))) for m in NB_CARTE.finditer(brute)]
            trouves = [(k, n) for k, n in trouves if k in comptes]
            if trouves and ('story' in norm(brute) or len(trouves) >= 2) and any(comptes[k] != n for k, n in trouves):
                lignes_.append((rel, i, brute, index.textes[rel]))
        if lignes_:
            attendu = ', '.join(f'{n} {CARTE_MOTS[k]}' for k, n in comptes.items())
            sortie.append(('compteur', 'Taille de la story map', f'{attendu}, compte du relevé dans {carte}', carte,
                           plafonner([(0,) + t for t in lignes_], EXTRAITS_SUJET)))
    phase = None
    # The phase is said where the Studio keeps its state, whatever folder is read: these files are always looked at.
    etat = [(rel, brute) for rel, i, brute, m, low, cs in index.lignes]
    for rel in ('README.md', 'projet/status.md', 'projet/fiche-projet.md', 'projet/changelog.md'):
        if rel not in index.textes:
            etat += [(rel, l) for l in (lire_texte(pathlib.Path(studio) / rel) or '').splitlines()]
    for rel, brute in etat:
        for rx in (PHASE_DEPUIS, PHASE_PASSAGE):
            for x in rx.finditer(brute):
                d = DATE_ISO.search(brute)
                cle = (int(x.group(1)), d.group(1) if d else '')
                if d and d.group(1) <= aujourdhui() and (phase is None or cle > phase[0]):   # « passage prévu le … »: not yet
                    phase = (cle, rel, une_ligne(brute, 200))
    if phase:
        (n, date), source, texte = phase
        lignes_ = []
        for rel, i, brute in vivantes:
            dites = [int(g) for x in PHASE_DITE.finditer(brute) for g in x.groups() if g]
            if dites and max(dites) < n:
                lignes_.append((rel, i, brute, index.textes[rel]))
        if lignes_:
            sortie.append(('etat', 'Phase du projet', f'Phase {n} depuis le {iso_vers_jj(date)} : {texte}', source,
                           plafonner([(0,) + t for t in lignes_], EXTRAITS_SUJET)))
    return [(g, t, a, s, [x[1:] for x in l]) for g, t, a, s, l in sortie]


def releve(studio, dossier=None, incremental=False):
    """The plan of a preview: subjects with their short extracts. Writes nothing."""
    studio = str(pathlib.Path(studio).resolve())
    reg = registre.lire_fichier(registre.chemin_du_studio(studio))
    depuis = registre.iso(reg['dernier_passage']) if incremental else None
    neuf = lambda d: not depuis or (d or '') >= depuis
    lire = lambda rel: entrees(lire_texte(pathlib.Path(studio) / rel) or '', rel)
    magasins = magasins_du_studio(studio)
    decisions = [e for rel in magasins['decisions'] for e in lire(rel)]
    regles = [e for rel in magasins['regles'] for e in lire(rel)]
    questions = [e for rel in magasins['questions'] for e in lire(rel)]
    tout = decisions + regles + questions
    docs = documents_vivants(studio, dossier)
    for rel in sum(magasins.values(), []):
        if rel not in docs and not dossier:
            docs.append(rel)
    # A document under its own banner is an archive, left out whole; its html twin without a banner is one subject of
    # its own (« jumeau »), not one extract per stale value: the PM puts the banner on it or not.
    sous_bandeau, jumeaux = {}, {}
    for rel in docs:
        texte = lire_texte(pathlib.Path(studio) / rel)
        b = bandeau('\n'.join(texte_html(texte.splitlines())) if est_html(rel) and texte else texte)
        if b:
            sous_bandeau[rel] = b
    for rel in docs:
        if est_html(rel) and rel not in sous_bandeau:
            md = os.path.splitext(rel)[0] + '.md'
            if md in sous_bandeau:
                jumeaux[rel] = md
    docs = [d for d in docs if d not in sous_bandeau and d not in jumeaux]
    index = Lignes(studio, docs)
    # What is new since the last complete pass: a line it did not read (`lignes-lues.json`), else, for a Studio checked
    # before that file, an entry dated since « Dernier passage ». Never a file's modification date.
    lues = lire_lignes_lues(studio) if depuis else None
    sources = sources_du_studio(studio) if not dossier else {}
    sources_lues = {}

    def lire_source(rel, taille):
        """A source's lines, kept as read with its size (the next pass reads it again only if its size changed)."""
        lignes = (lire_texte(pathlib.Path(studio) / rel) or '').splitlines()
        lu.update(empreinte(l) for l in lignes)
        sources_lues[rel] = taille
        return lignes
    deja_lues = lues['lignes'] if lues else set()
    lu = set()

    def ligne_neuve(brute):
        h = empreinte(brute)
        return lues is not None and h is not None and h not in deja_lues

    def lignes_de(e):
        ls = index.textes.get(e['fichier'])
        if ls is None:
            ls = (lire_texte(pathlib.Path(studio) / e['fichier']) or '').splitlines()
        return ls[e['ligne'] - 1:e['fin']]

    neuves_memo = {}

    def entree_neuve(e):
        if not depuis:
            return True
        if id(e) not in neuves_memo:
            if lues is not None:
                neuves_memo[id(e)] = any(ligne_neuve(l) for l in lignes_de(e))
            else:
                neuves_memo[id(e)] = neuf(e.get('date')) or any(neuf(m.get('date')) for m in e.get('majs') or [])
        return neuves_memo[id(e)]
    titres = {e['code']: une_ligne(e['libelle'], 80) for e in tout if e.get('code')}
    par_code = {e['code']: e for e in tout if e.get('code')}
    # The lines of a replaced entry, or of a closed question, are an archive: its old value is meant to be there.
    des_questions = {id(q) for q in questions}
    archives = {(e['fichier'], k - 1) for e in tout
                if e['etat'] == 'remplace' or (e['etat'] == 'clos' and id(e) in des_questions)
                for k in range(e['ligne'], e['fin'] + 1)}
    sujets, vus = [], set()
    mode = 'relecture' if depuis else 'rattrapage'
    # A case already in the register (its identity: sources and dates of both values) is decided there, not again.
    # A value the register had to date (« date inconnue, celle du fichier / du relevé ») has no date in the Studio:
    # it is known by its source alone, so a weekly pass does not judge and pay for it again.
    sans_date = lambda v: None if re.search(r'\(date inconnue, celle du (fichier|relevé)\)$', v['texte'].strip()) else v['date']
    au_registre = {(c['ancienne']['source'], sans_date(c['ancienne']), c['nouvelle']['source'], sans_date(c['nouvelle']))
                   for c in reg['cas']}

    def ajouter(genre, ancien, nouveau, trouves, titre):
        jj = lambda d: registre.jjmmaaaa(d) if d else None
        if (ancien.get('source'), jj(ancien.get('date')), nouveau.get('source'), jj(nouveau.get('date'))) in au_registre \
                or (ancien.get('source'), ancien.get('date'), nouveau.get('source'), nouveau.get('date')) in au_registre:
            return
        extraits, memes = [], set()
        for rel, i, brute, ls in trouves:
            # The same passage copied in several files (a ticket exported to five folders) is read once (2026-11-23:
            # one ticket in five export folders, five extracts of one line). An html page stays apart: its own subject.
            cle = (empreinte(brute), est_html(rel))
            if cle in memes:
                vus.add((rel, i))
                continue
            memes.add(cle)
            extraits.append(extrait(rel, i, brute, ls))
        if not extraits:
            return
        sid = f'S{len(sujets) + 1}'
        for k, x in enumerate(extraits, 1):
            x['id'] = f'E{len(sujets) + 1}.{k}'
            vus.add((x['fichier'], x['ligne'] - 1))
        sujets.append({'id': sid, 'genre': genre, 'titre': une_ligne(titre, 90), 'ancien': ancien, 'nouveau': nouveau,
                       'extraits': extraits, 'client': any(x['client'] for x in extraits)})

    def a_garder(trouves, nouvelle_neuve):
        """A subject is new when its new value is, or when one of its passages is a line the last pass did not read."""
        if not depuis or nouvelle_neuve:
            return trouves
        return [t for t in trouves if ligne_neuve(t[2])]

    def propres(e):
        return {(e['fichier'], k - 1) for k in range(e['ligne'], e['fin'] + 1)}

    def chercher_et_ajouter(e, genre, ancien, nv, ancien_texte, codes, nouvelle_neuve):
        termes = termes_distinctifs(ancien_texte, nv['texte'])
        sujet_mots = mots(e['libelle']) | (mots(ancien_texte) & mots(nv['texte'])) or mots(ancien_texte)
        trouves = index.chercher(termes, sujet_mots, codes, propres(e) | archives, n=EXTRAITS_SUJET)
        trouves = a_garder(trouves, nouvelle_neuve)
        ajouter(genre, ancien, nv, trouves, e['libelle'])

    # (a) an entry replaced (status, strike-through, « Remplacée le … par … ») and (b) an entry an update changed:
    # the old value, its code and its distinctive words in the documents.
    for e in tout:
        store, nouvelle = e['fichier'], None
        if e['etat'] == 'remplace':
            nouvelle = remplacante(e['remplace_par'] or ' '.join(m['texte'] for m in e['majs']),
                                   [x for x in tout if x is not e])
            maj = (e['majs'] or [None])[-1]
            if nouvelle:
                nv = valeur(nouvelle, studio, nouvelle['fichier'])
            elif maj:
                nv = {'texte': maj['texte'], 'source': source_chemin(maj['texte'], studio) or store,
                      'date': iso_vers_jj(maj['date']), 'code': None, 'libelle': une_ligne(maj['texte'], 60), 'entree': ''}
            elif e['remplace_par']:
                nv = {'texte': e['remplace_par'], 'source': store, 'date': None, 'code': None,
                      'libelle': une_ligne(e['remplace_par'], 60), 'entree': ''}
            else:
                continue
            genre = 'remplace'
        elif e['etat'] == 'actif' and 'question' not in store and [
                m for m in e['majs'] if not (remplacante(m['texte'], [x for x in tout if x is not e and x['etat'] == 'remplace']))]:
            # An update that only points at an entry it replaced is that entry's subject (a), not a change of this one.
            maj = [m for m in e['majs'] if not remplacante(m['texte'], [x for x in tout if x is not e and x['etat'] == 'remplace'])][-1]
            nv = {'texte': maj['texte'], 'source': source_chemin(maj['texte'], studio) or store,
                  'date': iso_vers_jj(maj['date']), 'code': e.get('code'), 'libelle': e['libelle'],
                  'entree': une_ligne(e['brute'])}
            genre = 'maj'
        elif e['etat'] == 'clos':
            maj = (e['majs'] or [None])[-1]
            nv = {'texte': maj['texte'] if maj else e['titre'], 'source': store,
                  'date': iso_vers_jj(maj['date']) if maj else iso_vers_jj(e['date']), 'code': e.get('code'),
                  'libelle': e['libelle'], 'entree': une_ligne(e['brute'])}
            genre = 'question'
        else:
            continue
        ancien_texte = e['texte'] + ' ' + e['libelle']
        if lues is not None:
            nouvelle_neuve = entree_neuve(e) or (nouvelle is not None and entree_neuve(nouvelle))
        else:
            nouvelle_neuve = neuf(registre.iso(nv['date']) if nv.get('date') else None)
        chercher_et_ajouter(e, genre, valeur(e, studio, store), nv, ancien_texte, [e['code']] if e.get('code') else [],
                            nouvelle_neuve)

    # (a') an active entry that says what it replaces without that being an entry (« Remplace : les valeurs de la V1 »).
    for e in tout:
        quoi = e['champs'].get('remplace') or ''
        if e['etat'] != 'actif' or len(quoi) < 12 or remplacante(quoi, [x for x in tout if x is not e]):
            continue
        ancien = {'texte': une_ligne(quoi, 400), 'source': e['fichier'], 'date': None, 'code': None,
                  'libelle': une_ligne(quoi, 60), 'entree': ''}
        codes = [c for c in CODE_STUDIO.findall(quoi) if c in par_code]
        chercher_et_ajouter(e, 'remplace', ancien, valeur(e, studio, e['fichier']), quoi, codes, entree_neuve(e))

    if True:  # noqa
        # (c) a line still waiting (« à valider », « non tranché », « - [ ] », « ? ») on a subject a decision, an update
        # or a closed question has settled since: paired with the closest one.
        reponses = []
        for e in tout:
            if e['etat'] == 'remplace':
                continue
            if e['etat'] == 'clos' or 'question' not in e['fichier']:
                textes = [(e['texte'] + ' ' + e['libelle'], e['date'], None)] + [(m['texte'], m['date'], m) for m in e['majs']]
                for t, d, m in textes:
                    reponses.append((e, mots(t), d, m))
        # An open question's own lines wait by nature: (d) pairs them with the decision that may answer them.
        questions_ouvertes = {(q['fichier'], k - 1) for q in questions if q['etat'] == 'actif'
                              for k in range(q['ligne'], q['fin'] + 1)}
        groupes = {}
        for k, (rel, i, brute, m, low, cs) in enumerate(index.lignes):
            if (rel, i) in vus or (rel, i) in archives or (rel, i) in questions_ouvertes or not EN_ATTENTE.search(brute):
                continue
            meilleur, score = None, 0
            for e, me, d, maj in reponses:
                if e['fichier'] == rel and e['ligne'] - 1 <= i <= e['fin'] - 1:
                    continue
                communs = len(m & me)
                if communs >= 3 and communs > score:
                    meilleur, score = (e, maj), communs
            if meilleur:
                groupes.setdefault(id(meilleur[0]), [meilleur[0], meilleur[1], []])[2].append((score, rel, i, brute))
        for e, maj, lignes_ in groupes.values():
            lignes_.sort(key=lambda x: (-x[0], x[1], x[2]))
            trouves = [(rel, i, brute, index.textes[rel]) for _, rel, i, brute in plafonner(lignes_, EXTRAITS_SUJET)]
            nv = {'texte': (maj or {}).get('texte') or e['texte'], 'source': e['fichier'],
                  'date': iso_vers_jj((maj or {}).get('date') or e['date']), 'code': e.get('code'),
                  'libelle': e['libelle'], 'entree': une_ligne(e['brute'])}
            trouves = a_garder(trouves, entree_neuve(e) if lues is not None else neuf((maj or {}).get('date') or e['date']))
            ajouter('attente', {'texte': 'en attente, à décider', 'source': trouves[0][0] if trouves else e['fichier'],
                                'date': None, 'code': None, 'libelle': 'Passage encore en attente', 'entree': ''},
                    nv, trouves, e['libelle'])

    if not dossier:
        actives = [d for d in decisions if d['etat'] == 'actif']
        # (d) an open question a later decision may answer.
        for q in questions:
            if q['etat'] != 'actif' or any('tranch' in norm(l) for l in q['corps']):
                continue
            if (q['fichier'], q['ligne'] - 1) in vus:
                continue
            mq = mots(q['libelle'] + ' ' + q['champs'].get('contexte', ''))
            for d in actives:
                if q.get('date') and d.get('date') and d['date'] < q['date']:
                    continue
                if not (entree_neuve(d) or (lues is not None and entree_neuve(q))):
                    continue
                md_ = mots(d['texte'] + ' ' + d['libelle'])
                communs = mq & md_
                if len(communs) >= 3 and len(communs) / max(1, len(mq | md_)) >= 0.12:
                    i = q['ligne'] - 1
                    texte_q = index.textes.get(q['fichier']) or []
                    if not texte_q or deja_marque(texte_q, i, f'par {code_libelle(d)}'):
                        continue
                    ajouter('question', valeur(q, studio, q['fichier']), valeur(d, studio, d['fichier']),
                            [(q['fichier'], i, q['brute'], texte_q)], q['libelle'])
                    break
        # (e) two active rules side by side on the same subject.
        actives_r = [r for r in regles if r['etat'] == 'actif']
        for i, r1 in enumerate(actives_r):
            for r2 in actives_r[i + 1:]:
                if not (entree_neuve(r1) or entree_neuve(r2)):
                    continue
                if r1['fichier'] != r2['fichier']:
                    continue
                m1, m2 = mots(r1['texte']), mots(r2['texte'])
                communs = m1 & m2
                if len(communs) >= 3 and len(communs) / max(1, len(m1 | m2)) >= 0.3:
                    vieux, jeune = sorted((r1, r2), key=lambda r: r.get('date') or '')
                    texte_r = index.textes.get(vieux['fichier']) or []
                    if not texte_r or deja_marque(texte_r, vieux['ligne'] - 1, 'En conflit avec'):
                        continue
                    ajouter('regles', valeur(vieux, studio, vieux['fichier']), valeur(jeune, studio, jeune['fichier']),
                            [(vieux['fichier'], r['ligne'] - 1, r['brute'], texte_r) for r in (vieux, jeune)],
                            vieux['libelle'])
        # (f) re-read only: a new line of a source (meeting, mail, Slack) that meets an active rule or decision. A
        # source is read again only when it is new or its size changed since the last complete pass; without
        # `lignes-lues.json`, the sources whose name starts with a date since « Dernier passage ».
        if depuis:
            for rel, taille in sorted(sources.items()):
                if lues is not None and lues['sources'].get(rel) == taille:
                    continue
                lignes = lire_source(rel, taille)
                if lues is None:
                    date = re.match(r'\d{4}-\d{2}-\d{2}', os.path.basename(rel))
                    if not date or date.group(0) < depuis:
                        continue            # read and kept as read, never compared: older than the last pass
                neuves = [(i, mots_de_fond(lignes[i])) for i, l in enumerate(lignes) if lues is None or ligne_neuve(l)]
                n = 0
                for e in actives + actives_r:
                    if source_chemin(e['source'], studio) == rel:
                        continue            # the source this entry was written from
                    me = mots(e['texte'])
                    for i, fond in neuves:
                        l = lignes[i]
                        if len(me & fond) >= REVIREMENT_MOTS:
                            date = re.match(r'\d{4}-\d{2}-\d{2}', os.path.basename(rel))
                            ajouter('revirement', valeur(e, studio, 'projet/regles-metier.md'),
                                    {'texte': une_ligne(l, 400), 'source': rel,
                                     'date': iso_vers_jj(date.group(0)) if date else registre.jjmmaaaa(
                                         dt.date.fromtimestamp(os.path.getmtime(pathlib.Path(studio) / rel))),
                                     'code': None, 'libelle': os.path.basename(rel), 'entree': ''},
                                    [(rel, i, l.rstrip('\r'), lignes)], e['libelle'])
                            n += 1
                            break
                    if n >= 3:
                        break

    # (g) an html page whose markdown twin is under a banner, without one itself: one subject per page.
    for rel, md in sorted(jumeaux.items()):
        ls = texte_html((lire_texte(pathlib.Path(studio) / rel) or '').splitlines())
        lu.update(empreinte(l) for l in ls)
        if depuis and lues is not None and not any(ligne_neuve(l) for l in ls + (index.textes.get(md) or [])):
            continue
        i = next((k for k, l in enumerate(ls) if len(l) >= 12), 0)
        date = registre.jjmmaaaa(dt.date.fromtimestamp(os.path.getmtime(pathlib.Path(studio) / md)))
        ajouter('jumeau', {'texte': f'page sans bandeau, présentée comme à jour : {une_ligne(ls[i] if ls else rel, 200)}',
                           'source': rel, 'date': None, 'code': None, 'libelle': os.path.basename(rel), 'entree': ''},
                {'texte': une_ligne(sous_bandeau[md], 400), 'source': md, 'date': date, 'code': None,
                 'libelle': f'bandeau de {os.path.basename(md)}', 'entree': ''},
                [(rel, i, ls[i] if ls else '', ls)], f'{os.path.basename(rel)} sans le bandeau de son jumeau')

    # (h) the project's state: a count of questions, replaced decisions or story map items, and the phase, that the
    # Studio itself contradicts. Counted by the script, the judge only says whether the line means the same thing.
    for genre, titre, attendu, source, lignes_ in etat_du_projet(studio, magasins, questions, decisions, index):
        # A count read in the Studio is new when the count itself changed since the last pass, not only its lines.
        lu.add(empreinte(attendu))
        source_neuve = lues is None or ligne_neuve(attendu) or any(ligne_neuve(l) for l in index.textes.get(source) or [])
        trouves = lignes_ if not depuis or source_neuve else [t for t in lignes_ if ligne_neuve(t[2])]
        ajouter(genre, {'texte': une_ligne(trouves[0][2], 300) if trouves else '', 'source': trouves[0][0] if trouves else '',
                        'date': None, 'code': None, 'libelle': titre, 'entree': ''},
                {'texte': attendu, 'source': source, 'date': registre.jjmmaaaa(
                    dt.date.fromtimestamp(os.path.getmtime(pathlib.Path(studio) / source))),
                 'code': None, 'libelle': titre, 'entree': ''}, trouves, titre)

    for s in sujets:
        for v in (s['ancien'], s['nouveau']):
            if v.get('code'):
                titres.setdefault(v['code'], une_ligne(v['libelle'], 80))
        for x in s['extraits']:
            for c in CODE_STUDIO.findall(x['contexte']):
                if c in par_code:
                    titres.setdefault(c, une_ligne(par_code[c]['libelle'], 80))
    plan = {'version': 2, 'studio': studio, 'nom': nom_court(studio), 'date': aujourdhui(), 'mode': mode,
            'dossier': dossier, 'depuis': reg['dernier_passage'] if depuis else None, 'sujets': sujets,
            'titres': titres, 'jugements': {}, 'marquages': [], 'decisions': [], 'absences': [], 'ecrit': False,
            'sous_bandeau': sorted(sous_bandeau)}
    if not dossier:
        # What this pass read, kept with « Dernier passage » when the pass is complete (ecrire_lignes_lues).
        for ls in index.textes.values():
            lu.update(empreinte(l) for l in ls)
        if not depuis:
            for rel, taille in sources.items():     # a whole-Studio pass keeps every source as read
                lire_source(rel, taille)
        lu.discard(None)
        plan['lu'] = {'lignes': ''.join(sorted(lu)), 'sources': sources_lues}
    plan['lots'] = repartir(plan)
    plan['cout'] = estimer_cout(plan)
    return plan


def texte_sujet(plan, s):
    """One subject as its sub-agent reads it: its two values and its short extracts."""
    t = plan['titres']
    sortie = [f"## {s['id']} · {s['titre']} ({GENRES[s['genre']]})"]
    for nom, v in (('Ancienne', s['ancien']), ('Nouvelle', s['nouveau'])):
        entete = code_libelle(v) if v.get('code') else v['libelle']
        sortie.append(f"- {nom} : {etiqueter(v['texte'], t)} (source : {v['source']}, {v['date'] or 'sans date'}) "
                      f"[{etiqueter(entete, t)}]")
    for x in s['extraits']:
        sortie.append(f"- Extrait {x['id']} · {x['fichier']} ligne {x['ligne']}"
                      f"{' · parti chez le client' if x['client'] else ''}{' · page html, jamais écrite' if est_html(x['fichier']) else ''}")
        sortie.append('```')
        sortie.append(etiqueter(x['contexte'], t))
        sortie.append('```')
    sortie.append('')
    return '\n'.join(sortie)


def repartir(plan):
    """The batches, in subject order: a batch closes at LOT subjects or before LOT_CARACTERES of text, so that its
    sub-agent reads it whole, once."""
    lots, courant, taille = [], [], 0
    for s in plan['sujets']:
        n = len(texte_sujet(plan, s))
        if courant and (len(courant) >= LOT or taille + n > LOT_CARACTERES):
            lots.append(courant)
            courant, taille = [], 0
        courant.append(s['id'])
        taille += n
    if courant:
        lots.append(courant)
    return lots


def lots_du_plan(plan):
    """The batches of a plan; a plan made before batches by size is cut by ten."""
    if plan.get('lots') is not None:
        return plan['lots']
    ids = [s['id'] for s in plan['sujets']]
    return [ids[k:k + LOT] for k in range(0, len(ids), LOT)]


def nom_court(studio):
    """The Studio's short name, as Mon Studio shows it: « Studio - Projet Alpha » -> « Projet Alpha »."""
    nom = os.path.basename(os.path.normpath(studio))
    court = re.sub(r"(?i)^studio\s*[-–]\s*|\s*[-–]\s*studio$", '', nom).strip()
    if ' ' not in court and '-' in court:
        court = court.replace('-', ' ')
    return court or nom


# ---------- cost

def cout_usd(modele, ecrits, sortie, relus):
    entree, out, cache = PRIX[modele]
    return (ecrits * entree * 1.25 + sortie * out + relus * cache) / 1e6


def cout_sous_agents(lots, tok, sortie):
    """Sonnet sub-agents, one per batch: (usd, tokens written, tokens read). The shared part of their base is written
    to the cache once; each later call re-reads the base and, from the third, the batch."""
    if not lots:
        return 0.0, 0, 0
    ecrits = AGENT_SOCLE_PARTAGE + lots * (AGENT_SOCLE - AGENT_SOCLE_PARTAGE) + tok + sortie
    relus = lots * (AGENT_SOCLE_PARTAGE + (AGENT_APPELS - 1) * AGENT_SOCLE) + (AGENT_APPELS - 2) * tok
    return cout_usd('sonnet', ecrits, sortie, relus), ecrits, relus


def cout_tete(lots, tok_car, sortie):
    """The batches judged headless (`juger-lots`): one Sonnet call per batch, no cache: (usd, tokens read)."""
    if not lots:
        return 0.0, 0
    entree = lots * TETE_SOCLE + tok_car * CARACTERES_PAR_TOKEN_LOT / CARACTERES_PAR_TOKEN_TETE
    prix_entree, prix_sortie, _ = PRIX['sonnet']
    return (entree * prix_entree + sortie * prix_sortie) / 1e6 * TETE_REPRISES, int(entree * TETE_REPRISES)


def cout_session_releve(lots, mode='sous-agents'):
    """The conflicts session's own calls during a relevé (Opus). With the sub-agents, launching and receiving each
    batch, its context growing with each; with `juger-lots`, its fixed calls only."""
    if mode == 'tete':
        ecrits = SESSION_BASE * SESSION_PART_ECRITE + SESSION_ECRITS_TETE
        relus = SESSION_APPELS_FIXES * (SESSION_BASE + SESSION_ECRITS_TETE)
        return cout_usd('opus', ecrits, SESSION_SORTIE_FIXE, relus), ecrits + relus
    appels = SESSION_APPELS_FIXES + SESSION_APPELS_PAR_LOT * lots
    ecrits = SESSION_BASE * SESSION_PART_ECRITE + lots * SESSION_ECRITS_PAR_LOT
    relus = appels * (SESSION_BASE + lots * SESSION_CROISSANCE_PAR_LOT)
    return cout_usd('opus', ecrits, SESSION_SORTIE_FIXE + lots * SESSION_SORTIE_PAR_LOT, relus), ecrits + relus


def cout_session_decisions(lots, decisions, mode='sous-agents'):
    """Then the decisions asked one by one, in the same session whose context has grown with the relevé."""
    if not decisions:
        return 0.0
    appels = decisions + math.ceil(decisions / ORDRE_ECRITURE) + 2
    ecrits = decisions * TOKENS_PAR_DECISION
    croissance = SESSION_ECRITS_TETE if mode == 'tete' else lots * SESSION_CROISSANCE_PAR_LOT
    contexte = SESSION_BASE + croissance + ecrits / 2
    return cout_usd('opus', ecrits, decisions * 150, appels * contexte)


def estimer_cout(plan, mode=None):
    """A ceiling for one launch: the batches judged by Sonnet on the extracts (headless calls of `juger-lots`, or
    in-session sub-agents when `claude` is not on the PATH), and the conflicts session (Opus) that launches them, shows
    the preview and asks the decisions. Markings and register lines are written by the script: no model."""
    mode = mode or mode_jugement()
    n = len(plan['sujets'])
    lots = len(plan['lots']) if plan.get('lots') is not None else (math.ceil(n / LOT) if n else 0)
    car = sum(len(x['contexte']) + 200 for s in plan['sujets'] for x in s['extraits']) + \
        sum(len(s['ancien']['texte']) + len(s['nouveau']['texte']) + 150 for s in plan['sujets'])
    tok = car / CARACTERES_PAR_TOKEN_LOT
    sortie = n * SORTIE_PAR_SUJET
    if mode == 'tete':
        agents, a_lus = cout_tete(lots, tok, sortie)
        par_agent, a_tokens = (int(a_lus / lots) if lots else 0), int(a_lus + sortie)
    else:
        agents, a_ecrits, a_relus = cout_sous_agents(lots, tok, sortie)
        par_agent = int(AGENT_SOCLE + (tok + sortie) / lots) if lots else 0
        a_tokens = int(a_ecrits + a_relus + sortie)
    decisions = math.ceil(n * PART_PM)
    releve, s_tokens = cout_session_releve(lots, mode) if n else (0.0, 0)
    questions = cout_session_decisions(lots, decisions, mode)
    total = (agents + releve + questions) * MARGE
    return {'sujets': n, 'lots': lots, 'mode': mode, 'decisions_estimees': decisions, 'tokens_extraits': int(tok),
            'tokens_par_sous_agent': par_agent, 'tokens_sous_agents': a_tokens, 'tokens_session_releve': int(s_tokens),
            'usd_sous_agents': round(agents * MARGE, 2), 'usd_session_releve': round(releve * MARGE, 2),
            'usd_session_decisions': round(questions * MARGE, 2), 'usd_session': round((releve + questions) * MARGE, 2),
            'usd': round(total, 2), 'pourcent_semaine': round(total / POURCENT_USD, 2),
            'au_dessus_du_plafond': total / POURCENT_USD > PLAFOND_LANCEMENT}


def estimer_passe(plan):
    """A ceiling for one daily pass inside the morning point (Sonnet, the task already running: only what the pass adds
    is counted): the subjects and the judging instructions written to the task's context, its judgments, and that
    context re-read by the task's remaining calls. With nothing new, nothing is added: 0 $."""
    n = len(plan['sujets'])
    lots = len(plan['lots']) if plan.get('lots') is not None else (math.ceil(n / LOT) if n else 0)
    if not n:
        return {'sujets': 0, 'lots': 0, 'usd': 0.0, 'pourcent_semaine': 0.0, 'usd_rien_de_nouveau': 0.0,
                'pourcent_rien_de_nouveau': 0.0}
    car = sum(len(x['contexte']) + 200 for s in plan['sujets'] for x in s['extraits']) + \
        sum(len(s['ancien']['texte']) + len(s['nouveau']['texte']) + 150 for s in plan['sujets'])
    tok = car / CARACTERES_PAR_TOKEN + len(CONSIGNE_JUGEMENT) / CARACTERES_PAR_TOKEN
    sortie = n * SORTIE_PAR_SUJET
    usd = cout_usd('sonnet', tok + sortie, sortie, PASSE_MATIN_APPELS * (tok + sortie)) * MARGE
    return {'sujets': n, 'lots': lots, 'usd': round(usd, 2), 'pourcent_semaine': round(usd / POURCENT_USD, 2),
            'usd_rien_de_nouveau': 0.0, 'pourcent_rien_de_nouveau': 0.0}


def cout_des_tickets(plan):
    """With a ticketing tool on the project sheet: what finding the tickets of the expected « remplacer » decisions
    (and of the settled ones not searched yet) would cost, said again before the search (PM, Q17, 2026-11-12)."""
    t = tickets_module()
    if not t.project_ref(plan['studio'])['outil']:
        return ''
    deja = len(t.search(plan['studio'])['conflits'])
    n = max(1, plan['cout'].get('decisions_estimees', 0) + deja)
    return t.cost_line(t.estimate(n)) + " Coût redit avant la recherche, qui ne se lance qu'après tes décisions."


def texte_cout_passe(c, depuis):
    quoi = (f"{c['sujets']} sujet{'s' if c['sujets'] > 1 else ''} nouveau{'x' if c['sujets'] > 1 else ''} depuis le "
            f"{registre.jjmmaaaa(depuis)}" if depuis else f"{c['sujets']} sujets (aucun passage complet encore : tout le Studio)")
    return (f"Passe du matin, chaque jour : environ {fr(float(c['pourcent_semaine']))} % de ta semaine "
            f"({fr(float(c['usd']))} $) pour ce qu'il y a aujourd'hui ({quoi}) ; rien un jour sans rien de nouveau. "
            "Aucune question, rien n'est marqué dans les documents : elle inscrit les décisions au registre et prépare "
            "les marquages sûrs pour ton prochain go.")


def fr(x):
    """A number as the PM reads it: decimal comma."""
    return f'{x:.2f}'.replace('.', ',') if isinstance(x, float) else str(x)


def millions(n):
    return f"{n / 1e6:.1f} million{'s' if n >= 1.95e6 else ''}".replace('.', ',') if n >= 1e6 else f"{round(n, -3):,.0f}".replace(',', ' ')


def texte_cout(c, dossiers=None):
    pl = lambda n, mot: f"{n} {mot}{'s' if n > 1 else ''}"
    lignes = [f"Coût estimé : {fr(float(c['pourcent_semaine']))} % de ta semaine ({fr(float(c['usd']))} $), plafond d'un lancement 0,5 %."]
    if c.get('lots') and c.get('mode') == 'tete':
        lignes.append(
            f"- {pl(c['sujets'], 'sujet')} en {pl(c['lots'], 'lot')}, jugés par Sonnet sur extraits seulement, un appel sans "
            f"outil par lot lancé par le script : environ {millions(c.get('tokens_par_sous_agent', 0))} tokens chacun, dont "
            f"{millions(TETE_SOCLE)} de consigne ; {millions(c.get('tokens_sous_agents', 0))}"
            f"{' de' if c.get('tokens_sous_agents', 0) >= 1e6 else ''} tokens en tout : {fr(float(c['usd_sous_agents']))} $")
        lignes.append(
            f"- la session des conflits (Opus, environ {millions(SESSION_BASE)} tokens de contexte relus à chaque appel) : "
            f"lancer le jugement et lire l'aperçu, {fr(float(c.get('usd_session_releve', c['usd_session'])))} $ ; puis environ "
            f"{pl(c['decisions_estimees'], 'décision')} posées une par une, {fr(float(c.get('usd_session_decisions', 0.0)))} $")
    elif c.get('lots'):
        lignes.append(
            f"- {pl(c['sujets'], 'sujet')} en {pl(c['lots'], 'lot')}, jugés par des sous-agents Sonnet sur extraits seulement : "
            f"environ {millions(c.get('tokens_par_sous_agent', 0))} tokens de contexte chacun, dont {millions(AGENT_SOCLE)} "
            f"de socle fixe (consigne système, outils, règles) ; {millions(c.get('tokens_sous_agents', 0))}"
            f"{' de' if c.get('tokens_sous_agents', 0) >= 1e6 else ''} tokens en tout, presque tous relus en cache : {fr(float(c['usd_sous_agents']))} $")
        lignes.append(
            f"- la session des conflits (Opus, environ {millions(SESSION_BASE)} tokens de contexte relus à chaque appel) : "
            f"lancer et recevoir les lots, {fr(float(c.get('usd_session_releve', c['usd_session'])))} $ ; puis environ "
            f"{pl(c['decisions_estimees'], 'décision')} posées une par une, {fr(float(c.get('usd_session_decisions', 0.0)))} $")
    lignes.append("- les marquages et le registre : écrits par script, sans modèle, 0 $")
    if c['au_dessus_du_plafond']:
        lignes.append('Au-dessus du plafond : traiter par dossier (`--dossier <sous-dossier>`), un lancement chacun.'
                      + (f" Dossiers : {', '.join(dossiers)}." if dossiers else ''))
    return '\n'.join(lignes)


def dossiers_de_premier_niveau(studio):
    return sorted(d for d in os.listdir(studio) if (pathlib.Path(studio) / d).is_dir() and not d.startswith('.')
                  and norm(d) not in DOSSIERS_HORS)


# ---------- batches for the sub-agents, and their judgments

def texte_lot(plan, k):
    """What one sub-agent reads: about ten subjects, each with its two values and its short extracts."""
    lots = lots_du_plan(plan)
    if not 1 <= k <= len(lots):
        raise SystemExit(f'lot {k} vide : {len(lots)} lot(s) dans ce plan')
    par_id = {s['id']: s for s in plan['sujets']}
    lot = [par_id[i] for i in lots[k - 1]]
    sortie = [f"Lot {k} · {len(lot)} sujets du Studio « {plan['nom']} » (aperçu du {plan['date']})", '']
    return '\n'.join(sortie + [texte_sujet(plan, s) for s in lot])


def chemin_jugements(plan_chemin, k):
    p = pathlib.Path(plan_chemin)
    return p.with_name(f'{p.stem}.jugements-{k}.json')


CHOIX_VALIDES = set(registre.CHOIX)


def valider_jugement(plan, j):
    """One sub-agent judgment, checked and completed. Raises ValueError on what cannot be used."""
    par_id = {s['id']: s for s in plan['sujets']}
    s = par_id.get(j.get('sujet'))
    if not s:
        raise ValueError(f"sujet inconnu : {j.get('sujet')!r}")
    classe = j.get('classe')
    if classe not in CLASSES:
        raise ValueError(f"{s['id']} : classe inconnue {classe!r}")
    ids = {x['id'] for x in s['extraits']}
    passages = [p for p in (j.get('passages') or []) if p in ids]
    notes = []
    if classe == 'M' and s['genre'] in ('regles', 'revirement'):
        classe = 'PM'
        notes.append('revirement ou règles voisines : jamais un marquage seul')
    if classe == 'M' and (s['genre'] in ('jumeau', 'etat')
                          or (s['genre'] == 'compteur' and not s['nouveau']['source'].endswith('.json'))):
        # An html page is never written; a count of questions or decisions is the relevé's, close but not certain;
        # a line about the phase may tell a past one (« Phase : 2, terminée le … »).
        classe = 'PM'
        notes.append('page html ou compte du relevé : jamais un marquage seul')
    if classe == 'M' and j.get('resume_seul'):
        classe = 'PM'
        notes.append('résumé automatique seul : à confirmer')
    if classe == 'M' and not passages:
        classe = 'rien'
    recommande = j.get('recommande')
    if j.get('resume_seul'):
        recommande = 'à confirmer avec le client'
    if recommande not in CHOIX_VALIDES:
        recommande = 'à confirmer avec le client'

    def v(cle, defaut):
        # The text may be the sub-agent's (clearer); the source and the date stay the Studio's: they make the case's
        # identity in the register, and a date is never made up.
        x = dict(defaut)
        donne = j.get(cle) or {}
        if donne.get('texte'):
            x['texte'] = une_ligne(donne['texte'], 400)
        if not x.get('source') and donne.get('source'):
            x['source'] = une_ligne(donne['source'], 200)
        if not x.get('date') and isinstance(donne.get('date'), str) and registre.DATE.match(donne['date']):
            x['date'] = donne['date']
        return x
    # The title and the context are what the PM reads: in plain words, no code (PM, 2026-11-10). One that carries a
    # code is refused, the sub-agent writes it again; one that is missing is made from the Studio, codes removed.
    # « pourquoi » is shown with its codes removed (pour_le_pm), not refused: it often names the rule it relies on.
    for cle in ('titre', 'contexte'):
        if registre.codes_pour_le_pm(j.get(cle) or ''):
            raise ValueError(f"{s['id']} : le {cle} contient un code ({', '.join(registre.codes_pour_le_pm(j[cle]))}) : "
                             "à écrire en mots simples")
    titre = une_ligne(j.get('titre') or pour_le_pm(s['titre'], plan['titres']), 90)
    absence = j.get('absence') or None
    if classe == 'absence':
        if not absence or not absence.get('fichier') or not absence.get('texte'):
            raise ValueError(f"{s['id']} : une absence donne « fichier » et « texte »")
        absence = {'fichier': str(absence['fichier']).lstrip('/'), 'texte': une_ligne(absence['texte'], 400)}
    ancienne, nouvelle = v('ancienne', s['ancien']), v('nouvelle', s['nouveau'])
    contexte = une_ligne(j.get('contexte') or '', 500) or contexte_par_defaut(plan, ancienne, nouvelle)
    return {'sujet': s['id'], 'classe': classe, 'titre': titre, 'contexte': contexte, 'ancienne': ancienne,
            'nouvelle': nouvelle, 'decision': une_ligne(j.get('decision') or '', 120),
            'passages': passages, 'recommande': recommande, 'pourquoi': une_ligne(j.get('pourquoi') or '', 500),
            'depend_de': j.get('depend_de') if j.get('depend_de') in par_id else None, 'absence': absence,
            'resume_seul': bool(j.get('resume_seul')), 'notes': notes,
            'source_orale': j.get('source_orale') is True, 'savoir_pm': j.get('savoir_pm') is True,
            'titres': {k: une_ligne(t, 80) for k, t in (j.get('titres') or {}).items()
                       if isinstance(k, str) and isinstance(t, str) and CODE.fullmatch(k)}}


def contexte_par_defaut(plan, a, n):
    """Who said what, and when, in plain words, when the sub-agent gave no context: from the Studio, codes removed."""
    e = lambda x: pour_le_pm(x, plan['titres'])
    quand = lambda v: f"le {v['date']}" if v.get('date') else 'à une date inconnue'
    return (f"Écrit {quand(a)} dans {registre.chemin_lisible(a['source'])} : {e(une_ligne(a['texte'], 160))}. "
            f"Puis {quand(n)}, {registre.chemin_lisible(n['source'])} : {e(une_ligne(n['texte'], 160))}.")


def nom_decision(plan, s, j=None):
    """How a marking names the new value, from the Studio only (never the sub-agent's wording, which changes from one
    run to the next): its code and title, else its entry's title."""
    v = s['nouveau']
    if v.get('code'):
        return f"{v['code']} · {plan['titres'].get(v['code'], v['libelle'])}"
    return une_ligne(v['libelle'], 80)


def texte_marquage(plan, s, j=None):
    v = s['nouveau']
    quoi = 'Tranchée' if s['genre'] == 'question' else 'Remplacé'
    signe = '✅' if s['genre'] == 'question' else '⚠️'
    date = v.get('date') or 'date inconnue'
    return f"{signe} {quoi} le {date} par {nom_decision(plan, s)}, source {v['source']} — {plan['mode']} du " \
           f"{registre.jjmmaaaa(plan['date'])}"


def cle_marquage(plan, s, j=None):
    """What makes a marking the same on a re-run (whatever the day and the sub-agent): the new value's name and source,
    as the Studio writes them."""
    return f"par {nom_decision(plan, s)}, source {s['nouveau']['source']}"


def construire(plan):
    """From the judgments: the safe markings, the PM decisions (dependents right after what they depend on), the
    additions. A safe marking or an addition in a document gone to the client stays a marking; an addition there
    becomes a PM decision."""
    par_id = {s['id']: s for s in plan['sujets']}
    marquages, decisions, absences = [], [], []
    for sid, j in plan['jugements'].items():
        s = par_id[sid]
        if j['classe'] == 'M':
            for x in s['extraits']:
                if x['id'] in j['passages']:
                    marquages.append({'id': f'M{len(marquages) + 1}', 'sujet': sid, 'titre': j['titre'],
                                      'fichier': x['fichier'], 'ligne': x['ligne'], 'passage': x['passage'],
                                      'texte': texte_marquage(plan, s, j), 'cle': cle_marquage(plan, s, j),
                                      'client': x['client'], 'etat': None})
        elif j['classe'] == 'absence' and not est_client(j['absence']['fichier']) \
                and not cible_refusee(plan['studio'], j['absence']['fichier'], ajout=True):
            absences.append({'id': f'A{len(absences) + 1}', 'sujet': sid, 'titre': j['titre'],
                             'fichier': j['absence']['fichier'], 'texte': j['absence']['texte'],
                             'source': f"{j['nouvelle']['source']}, {j['nouvelle']['date']}", 'etat': None})
        elif j['classe'] in ('PM', 'absence'):
            decisions.append(nouvelle_decision(plan, s, j))
    ordre = []
    restantes = sorted(decisions, key=lambda d: int(d['sujet'][1:]))
    par_sujet = {d['sujet']: d for d in restantes}

    def placer(d):
        if d in ordre:
            return
        dep = par_sujet.get(d['depend_de'] or '')
        if dep and dep not in ordre and dep is not d:
            placer(dep)
        if d in ordre:
            return
        ordre.append(d)
        for e in restantes:
            if e['depend_de'] == d['sujet'] and e not in ordre:
                placer(e)
    for d in restantes:
        placer(d)
    # A decision and the one it conditions are asked together: if either is a real decision, both are.
    change = True
    while change:                    # along a whole chain of « depend_de », until nothing moves
        change = False
        for d in ordre:
            dep = par_sujet.get(d['depend_de'] or '')
            if dep and 'arbitrage' in (d['niveau'], dep['niveau']):
                for x in (d, dep):
                    if x['niveau'] != 'arbitrage':
                        x['niveau'], x['raisons'], change = 'arbitrage', x['raisons'] or ['liée à une autre décision'], True
    for k, d in enumerate(ordre, 1):
        d['id'] = f'D{k}'
    plan.update(marquages=marquages, decisions=ordre, absences=absences)
    return plan


def niveau_de(plan, s, j, extraits=None):
    """('arbitrage' | 'evident', [reasons in words]) of a PM decision. A reason only ever makes it a real decision:
    - text gone to the client: the subject touches a document gone to the client, or was already said to him;
    - money or contract: a price, a budget, a quote, a signed document, a billing, in either value or the passages;
    - a source only oral: the new value comes from a meeting, a call or its automatic notes (or the sub-agent says so),
      or the decision rests on an automatic summary alone;
    - the PM's own knowledge: the sub-agent says only the PM knows (a talk, an intention, a context not in the Studio)."""
    extraits = s['extraits'] if extraits is None else extraits
    a, n = j['ancienne'], j['nouvelle']
    raisons = []
    # The passages the decision touches (all of the subject's when the sub-agent named none): a document gone to the
    # client among the others the subject merely quotes does not make every decision a client one.
    if any(x.get('client') for x in extraits):
        raisons.append(RAISON_CLIENT)
    if ARGENT.search(' '.join([a.get('texte') or '', n.get('texte') or '', j.get('titre') or '', j.get('contexte') or '']
                              + [x.get('passage') or '' for x in extraits])):
        raisons.append(RAISON_ARGENT)
    if j.get('source_orale') or j.get('resume_seul') or ORAL.search(n.get('source') or ''):
        raisons.append(RAISON_ORAL)
    if j.get('savoir_pm'):
        raisons.append(RAISON_SAVOIR)
    return ('arbitrage' if raisons else 'evident'), raisons


def nouvelle_decision(plan, s, j, raison=None):
    niveau, raisons = niveau_de(plan, s, j, [x for x in s['extraits'] if x['id'] in j['passages']] or s['extraits'])
    return {'niveau': niveau, 'raisons': raisons, 'sorti': False, 'id': None, 'sujet': s['id'], 'titre': pour_le_pm(j['titre'], plan['titres']),
            'contexte': j.get('contexte') or contexte_par_defaut(plan, j['ancienne'], j['nouvelle']), 'ancienne': j['ancienne'], 'nouvelle': j['nouvelle'],
            'communique': s['client'], 'extraits': [x for x in s['extraits'] if x['id'] in j['passages']] or s['extraits'],
            'recommande': j['recommande'], 'pourquoi': raison or j['pourquoi'], 'depend_de': j['depend_de'],
            'nom': nom_decision(plan, s, j), 'cle': cle_marquage(plan, s, j), 'marquage': texte_marquage(plan, s, j),
            'cas': None, 'reponse': None, 'ecrit': False}


def juger(plan, jugements):
    erreurs = []
    for j in jugements:
        try:
            v = valider_jugement(plan, j)
        except ValueError as exc:
            erreurs.append(str(exc))
            continue
        for k, t in v.pop('titres').items():
            plan['titres'].setdefault(k, t)
        plan['jugements'][v['sujet']] = v
    construire(plan)
    return erreurs


def juger_le_plan(chemin_plan, fichiers=None):
    """Every judgment file next to the plan (or `fichiers`) merged into it; the plan saved, the prepared preview
    noted. Returns (preview text, errors)."""
    plan = charger_plan(chemin_plan)
    p = pathlib.Path(chemin_plan)
    fichiers = fichiers or sorted(glob.glob(str(p.with_name(p.stem + '.jugements-*.json'))))
    jugements = []
    for f in fichiers:
        with open(f, encoding='utf-8') as h:
            x = json.load(h)
        jugements += x if isinstance(x, list) else x.get('jugements', [])
    erreurs = juger(plan, jugements)
    sauver_plan(chemin_plan, plan)
    noter_pret(plan, chemin_plan)
    return apercu(plan), erreurs


# ---------- the batches judged by the script itself: one headless Sonnet call per batch (`juger-lots`)
# Measured 2026-11-18: an in-session sub-agent carries about 78,000 tokens before its batch (system prompt, the tools'
# schemas, the rules, the agent listing) for 16,000 tokens of extracts, and the Opus session pays about three calls
# per batch to launch and receive it, its context growing with each. A `claude -p` call with no tool, no setting
# source, no MCP server and the judging brief as its system prompt carries under 1,000 tokens besides the brief, and
# the session makes one call for all the batches. Same brief as the Monday pass (CONSIGNE_JUGEMENT), same checks
# (valider_jugement): the judgment and what is written do not change, only who carries it.

TETE_MODELE = 'sonnet'
TETE_EFFORT = 'medium'
TETE_PARALLELES = 3           # calls at a time
TETE_BUDGET_APPEL = 1.0       # $ ceiling of one call (--max-budget-usd): a batch costs about 0.1 $
TETE_DELAI = 900              # seconds for one call
TETE_ESSAIS = 2               # a batch whose answer has refused or missing subjects is asked again once, for them only


def consigne_tete():
    """The Monday pass's brief, the subjects given as the message, the answer the JSON list alone."""
    return CONSIGNE_JUGEMENT.replace("donnés dans `texte` : tu ne lis aucun fichier",
                                     "donnés dans le message : tu ne lis aucun fichier") + (
        "\nRéponds seulement par la liste JSON `jugements`, un objet par sujet du message, sans texte autour ni bloc "
        "de code.")


def claude_cli():
    """The Claude Code command line, or None: then the batches are judged by in-session sub-agents (the fallback).
    CONFLITS_JUGEMENT=sous-agents forces the fallback; CONFLITS_CLAUDE names another command."""
    if os.environ.get('CONFLITS_JUGEMENT') == 'sous-agents':
        return None
    if os.environ.get('CONFLITS_CLAUDE'):
        return os.environ['CONFLITS_CLAUDE']
    import shutil
    # Mon Studio's page computes the estimate without the shell's PATH: the installer's usual places too.
    for x in [shutil.which('claude')] + [os.path.expanduser(c) for c in CLAUDE_EMPLACEMENTS]:
        if x and os.path.isfile(x) and os.access(x, os.X_OK):
            return x
    return None


CLAUDE_EMPLACEMENTS = ('~/.local/bin/claude', '~/.claude/local/claude', '/opt/homebrew/bin/claude',
                       '/usr/local/bin/claude')


def mode_jugement():
    return 'tete' if claude_cli() else 'sous-agents'


def commande_tete(cli):
    return [cli, '-p', '--model', TETE_MODELE, '--effort', TETE_EFFORT, '--tools', '', '--system-prompt',
            consigne_tete(), '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
            '--disable-slash-commands', '--output-format', 'json', '--max-budget-usd', str(TETE_BUDGET_APPEL)]


def liste_json(texte):
    """The JSON list in a model's answer (code fences or a sentence around it tolerated). Raises ValueError."""
    t = (texte or '').strip()
    debut, fin = t.find('['), t.rfind(']')
    if debut < 0 or fin < debut:
        raise ValueError('pas de liste JSON dans la réponse')
    x = json.loads(t[debut:fin + 1])
    if not isinstance(x, list):
        raise ValueError("la réponse n'est pas une liste")
    return [j for j in x if isinstance(j, dict)]


def appel_tete(cli, texte, executer=None):
    """One headless call: (judgments, usage record). Prompt caching is off: each call is single, and a cache write
    costs twice the input it saves nothing on (measured: 946 tokens, 0.0038 $ cached, 0.0019 $ not). Runs in an empty
    temporary folder, so that no project file (CLAUDE.md) is loaded. Raises RuntimeError(message, usage) on a failure."""
    import subprocess
    import tempfile
    env = dict(os.environ, DISABLE_PROMPT_CACHING='1')
    with tempfile.TemporaryDirectory(prefix='conflits-lot-') as vide:
        try:
            r = (executer or (lambda cmd, entree, cwd, env: subprocess.run(
                cmd, input=entree, capture_output=True, text=True, cwd=cwd, env=env, timeout=TETE_DELAI)))(
                commande_tete(cli), texte, vide, env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f'appel impossible : {exc}', None)
    try:
        sortie = json.loads(r.stdout)
    except (ValueError, TypeError):
        raise RuntimeError(f"réponse illisible (code {r.returncode}) : {une_ligne((r.stderr or r.stdout or '')[:300])}",
                           None)
    u = sortie.get('usage') or {}
    trace = {'usd': float(sortie.get('total_cost_usd') or 0.0), 'entree': int(u.get('input_tokens') or 0),
             'cache_ecrit': int(u.get('cache_creation_input_tokens') or 0),
             'cache_lu': int(u.get('cache_read_input_tokens') or 0), 'sortie': int(u.get('output_tokens') or 0),
             'secondes': round((sortie.get('duration_ms') or 0) / 1000)}
    if sortie.get('is_error') or r.returncode:
        raise RuntimeError(f"échec (code {r.returncode}) : {une_ligne(str(sortie.get('result') or r.stderr)[:300])}",
                           trace)
    try:
        return liste_json(sortie.get('result')), trace
    except ValueError as exc:
        raise RuntimeError(str(exc), trace)


def juger_un_lot(plan, chemin_plan, k, cli, executer=None):
    """Batch k judged headless, its judgments written where `juger` reads them. Returns
    {'lot', 'ok', 'jugements', 'manquants', 'erreurs', 'appels': [usage records]}."""
    lot = lots_du_plan(plan)[k - 1]
    par_id = {s['id']: s for s in plan['sujets']}
    texte = texte_lot(plan, k)
    bons, erreurs, appels = {}, [], []
    for _ in range(TETE_ESSAIS):
        try:
            jugements, trace = appel_tete(cli, texte, executer)
        except RuntimeError as exc:
            if exc.args[1]:
                appels.append(exc.args[1])
            erreurs = [str(exc.args[0])]
            continue
        appels.append(trace)
        erreurs = []
        for j in jugements:
            if j.get('sujet') not in lot:
                continue
            try:
                valider_jugement(plan, j)
            except ValueError as e:
                erreurs.append(str(e))
                continue
            bons[j['sujet']] = j
        reste = [i for i in lot if i not in bons]
        if not reste:
            break
        # Asked again for the refused or missing subjects only, with why they were refused.
        texte = (f"Lot {k} · {len(reste)} sujet(s) à juger de nouveau"
                 + (f" ; refusés : {' ; '.join(erreurs)}" if erreurs else '') + '\n\n'
                 + '\n'.join(texte_sujet(plan, par_id[i]) for i in reste))
    if bons:
        ecrire_texte(chemin_jugements(chemin_plan, k),
                     json.dumps([bons[i] for i in lot if i in bons], ensure_ascii=False, indent=1))
    manquants = [i for i in lot if i not in bons]
    return {'lot': k, 'ok': not manquants, 'jugements': len(bons), 'manquants': manquants, 'erreurs': erreurs,
            'appels': appels}


def lot_deja_juge(plan, chemin_plan, k):
    """A batch whose judgment file covers all its subjects (a run stopped midway starts again after it)."""
    try:
        with open(chemin_jugements(chemin_plan, k), encoding='utf-8') as h:
            x = json.load(h)
    except (OSError, ValueError):
        return False
    x = x if isinstance(x, list) else x.get('jugements', [])
    return set(lots_du_plan(plan)[k - 1]) <= {j.get('sujet') for j in x if isinstance(j, dict)}


def chemin_couts(chemin_plan):
    p = pathlib.Path(chemin_plan)
    return p.with_name(f'{p.stem}.couts.json')


def juger_les_lots(chemin_plan, paralleles=TETE_PARALLELES, executer=None):
    """Every batch not judged yet, judged headless, `paralleles` at a time; each call's real usage appended to
    `<plan>.couts.json`. Returns {'mode', 'lots', 'faits', 'a_refaire', 'usd', 'tokens', 'resultats'}."""
    from concurrent.futures import ThreadPoolExecutor
    plan = charger_plan(chemin_plan)
    n = len(lots_du_plan(plan))
    a_faire = [k for k in range(1, n + 1) if not lot_deja_juge(plan, chemin_plan, k)]
    cli = claude_cli()
    if not cli:
        return {'mode': 'sous-agents', 'lots': n, 'faits': [], 'a_refaire': a_faire, 'usd': 0.0, 'tokens': {},
                'resultats': []}
    with ThreadPoolExecutor(max_workers=max(1, paralleles)) as ex:
        resultats = list(ex.map(lambda k: juger_un_lot(plan, chemin_plan, k, cli, executer), a_faire))
    traces = [dict(t, lot=r['lot']) for r in resultats for t in r['appels']]
    deja = registre._lire_json(chemin_couts(chemin_plan))
    ecrire_texte(chemin_couts(chemin_plan),
                 json.dumps((deja if isinstance(deja, list) else []) + traces, ensure_ascii=False, indent=1))
    tokens = {c: sum(t[c] for t in traces) for c in ('entree', 'cache_ecrit', 'cache_lu', 'sortie')}
    return {'mode': 'tete', 'lots': n, 'faits': [r['lot'] for r in resultats if r['ok']],
            'a_refaire': [r['lot'] for r in resultats if not r['ok']], 'usd': round(sum(t['usd'] for t in traces), 4),
            'tokens': tokens, 'resultats': resultats}


# ---------- the preview

def fichiers_pour_le_pm(fichiers, n=3):
    noms = [registre.chemin_lisible(f) for f in fichiers]
    return ', '.join(noms[:n]) + (f' et {len(noms) - n} autres' if len(noms) > n else '')


def apercu(plan):
    """The preview the PM reads: no code, no id, no class letter; each conflict by its title, what to do in words."""
    t = plan['titres']
    e = lambda x: pour_le_pm(x, t)
    jug = plan['jugements']
    manquent = [s for s in plan['sujets'] if s['id'] not in jug]
    lignes = [f"Aperçu des conflits · {plan['nom']} · {plan['mode']} du {registre.jjmmaaaa(plan['date'])}"
              + (f" (dossier {registre.chemin_lisible(plan['dossier'])})" if plan.get('dossier') else '')
              + ' · rien n\'est écrit', '',
              '| Conflit | À faire | Avant → maintenant | Fichiers touchés | Parti chez le client |',
              '|---|---|---|---|---|']
    for s in plan['sujets']:
        j = jug.get(s['id'])
        if not j or j['classe'] == 'rien':
            continue
        if j['classe'] == 'absence':
            fichiers = [j['absence']['fichier']]
        else:
            fichiers = sorted({x['fichier'] for x in s['extraits'] if x['id'] in j['passages']} or
                              {x['fichier'] for x in s['extraits']})
        classe = j['classe'] if j['classe'] != 'absence' or not est_client(j['absence']['fichier']) else 'PM'
        lignes.append(f"| {e(j['titre'])} | {CLASSES[classe]} | "
                      f"{e(une_ligne(j['ancienne']['texte'], 70))} → {e(une_ligne(j['nouvelle']['texte'], 70))} "
                      f"({j['nouvelle'].get('date') or 'date inconnue'}) | {fichiers_pour_le_pm(fichiers)} | "
                      f"{'oui' if s['client'] else 'non'} |")
    fichiers_m = {m['fichier'] for m in plan['marquages']}
    rien = sum(1 for j in jug.values() if j['classe'] == 'rien')
    lignes += ['', f"Marquages sûrs : {len(plan['marquages'])} dans {len(fichiers_m)} fichiers "
               f"({sum(1 for m in plan['marquages'] if m['client'])} dans un document parti chez le client, seulement marqués).",
               f"Décisions à prendre : {len(plan['decisions'])}, posées une par une après le go.",
               f"Règles à ajouter : {len(plan['absences'])}.",
               f"Écartés à la lecture : {rien}."]
    if manquent:
        lignes.append(f"Pas encore lus : {len(manquent)} sujets ({', '.join(e(s['titre']) for s in manquent[:5])}"
                      f"{'…' if len(manquent) > 5 else ''}).")
    lignes += ['', texte_cout(plan['cout'])]
    return '\n'.join(lignes)


# ---------- writing in the Studio

INTERDITS = {'conflits.md', 'changelog.md', 'verbatims.md', 'claude.md'}


def cible_refusee(studio, rel, ajout=False):
    """Why a write to `rel` is refused, or None: it must resolve inside the Studio (no « .. », no absolute path, no
    link out), be a .md or .txt, never the register nor a journal of changes, never a hidden, source or dated file.
    An addition (`ajout`) goes neither to the journal of decisions nor to the open questions either."""
    if not isinstance(rel, str) or not rel.strip():
        return 'aucun fichier'
    p = pathlib.PurePosixPath(rel.replace(os.sep, '/'))
    if p.is_absolute() or '..' in p.parts or re.match(r'^[A-Za-z]:', rel):
        return 'chemin hors du Studio'
    base = os.path.realpath(studio)
    reel = os.path.realpath(os.path.join(studio, rel))
    if not reel.startswith(base.rstrip(os.sep) + os.sep):
        return 'chemin hors du Studio'
    nom = p.name.lower()
    if not nom.endswith(('.md', '.txt')):
        return 'ni .md ni .txt'
    if nom in INTERDITS or DATEE.match(p.name):
        return 'registre, journal ou source datée'
    if any(x.startswith('.') or norm(x) in DOSSIERS_SOURCES for x in p.parts[:-1]):
        return 'dossier caché ou de sources'
    if ajout and norm(nom).startswith(('decisions-log', 'questions-ouvertes')):
        return 'journal des décisions ou questions ouvertes'
    return None


def _ecrit(fonction, *args, **kwargs):
    """A document write, its refusals named: 'illisible' (the file exists and cannot be read: never written),
    'change' (it changed during the write, or another writer holds it)."""
    try:
        return fonction(*args, **kwargs)
    except registre.Illisible:
        return 'illisible'
    except registre.Change:
        return 'change'


def libelle_rangee(ligne, titres=None):
    """The first non-empty cell of a table row, to name it under the table: « Rangée « PRJ-37 · Se connecter » »."""
    cellules = [c.strip().strip('*`_ ') for c in ligne.strip().strip('|').split('|')]
    premiere = next((c for c in cellules if c), '')
    return etiqueter(une_ligne(premiere, 50), titres or {})


def poser(studio, rel, passage, ligne, texte, cle, titres=None):
    """Puts the marking `texte` on its own line next to `passage` (checked word for word), without changing a byte of
    the file. Under a table, after one blank line (so that it is not read as a row), naming the row it is for.
    'pose', 'deja' (already marked: nothing written), 'bouge' (the passage is not there any more), 'hors' (a file this
    script never writes), 'illisible' or 'change'."""
    if cible_refusee(studio, rel):
        return 'hors'
    resultat = {}

    def inserer(contenu):
        if contenu is None:
            resultat['r'] = 'bouge'
            return None
        lignes = contenu.splitlines(keepends=True)
        brutes = [l.rstrip('\r\n') for l in lignes]
        trouves = [i for i, l in enumerate(brutes) if l == passage]
        if not trouves:
            resultat['r'] = 'bouge'
            return None
        i = min(trouves, key=lambda k: abs(k - (ligne - 1)))
        if deja_marque(brutes, i, cle, titres):
            resultat['r'] = 'deja'
            return None
        nl = '\r\n' if lignes[i].endswith('\r\n') else '\n'
        if brutes[i].lstrip().startswith('|'):
            fin = fin_de_table(brutes, i)
            signe = next((m for m in MARQUE if texte.startswith(m)), '⚠️')
            marque = f"{signe} Rangée « {libelle_rangee(brutes[i], titres)} » : {texte[len(signe):].strip() if texte.startswith(signe) else texte}"
            k = fin + 1
            if k + 1 < len(brutes) and not brutes[k].strip() and est_marquage(brutes[k + 1]):
                k += 1
                while k + 1 < len(brutes) and brutes[k + 1].strip() and est_marquage(brutes[k + 1]):
                    k += 1
                nouvelles = [marque + nl]
                position = k + 1
            else:
                nouvelles = [nl, marque + nl]
                position = fin + 1
            if position == len(lignes) and lignes and not lignes[-1].endswith(('\n', '\r')):
                lignes[-1] += nl
            lignes[position:position] = nouvelles
        else:
            retrait = re.match(r'\s*', brutes[i]).group(0)
            if re.match(r'\s*(?:[-*+]|\d+[.)])\s', brutes[i]):
                retrait += '  '
            if i == len(lignes) - 1 and not lignes[i].endswith(('\n', '\r')):
                lignes[i] += nl
            lignes.insert(i + 1, retrait + texte + nl)
        resultat['r'] = 'pose'
        return ''.join(lignes)
    r = _ecrit(registre.modifier, pathlib.Path(studio) / rel, inserer)
    return r if r in ('illisible', 'change') else resultat.get('r', 'bouge')


def fin_de_table(brutes, i):
    fin = i
    while fin + 1 < len(brutes) and brutes[fin + 1].lstrip().startswith('|'):
        fin += 1
    return fin


def ajouter_en_fin(studio, rel, ligne, cle=None, ajout=True):
    """Appends `ligne` at the end of a file (created when absent), in append mode. Nothing when `cle` (or the line) is
    already there. 'pose', 'deja', 'hors', 'illisible' or 'change'."""
    if cible_refusee(studio, rel, ajout=ajout):
        return 'hors'

    def suite(contenu):
        if contenu is not None and norm(cle or ligne) in norm(contenu):
            return None
        contenu = contenu or ''
        nl = '\r\n' if '\r\n' in contenu else '\n'
        return ('' if not contenu or contenu.endswith(('\n', '\r')) else nl) + ligne + nl
    r = _ecrit(registre.ajouter_fin, pathlib.Path(studio) / rel, suite)
    return r if r in ('illisible', 'change') else ('pose' if r else 'deja')


def journal(studio, texte):
    """A row at the end of the Studio's journal of changes (`projet/changelog.md`), never a rewrite; created with its
    header when absent, never written when it cannot be read. 'pose', 'deja', 'illisible' or 'change'."""
    chemin = pathlib.Path(studio) / 'projet' / 'changelog.md'
    rangee = f"| {aujourdhui()} | {texte.replace('|', '/')} | /cockpit:conflits |"

    def suite(contenu):
        if contenu is None:
            return '# Historique des changements projet\n\n| Date | Changement | Source |\n|------|-----------|--------|\n' + rangee + '\n'
        if rangee in contenu:
            return None
        nl = '\r\n' if '\r\n' in contenu else '\n'
        return ('' if contenu.endswith(('\n', '\r')) else nl) + rangee + nl
    r = _ecrit(registre.ajouter_fin, chemin, suite)
    return r if r in ('illisible', 'change') else ('pose' if r else 'deja')


def regles_remplacees(studio, rel, entree, cle):
    """The old rule in the « Règles remplacées » section of the living document that carries it (its store of rules
    or decisions, or the living document it was written in), at the end of that section (created at the end of the
    file). Never a raw source, a client document nor a file this script does not write. Nothing is removed.
    'pose', 'deja', 'hors' (no such document: the PM is told), 'illisible' or 'change'."""
    if not rel or est_client(rel) or cible_refusee(studio, rel) or not rel.lower().endswith('.md'):
        return 'hors'
    if not (pathlib.Path(studio) / rel).is_file():
        return 'hors'
    resultat = {}

    def ranger(contenu):
        if contenu is None:
            resultat['r'] = 'hors'
            return None
        if norm(cle) in norm(contenu):
            resultat['r'] = 'deja'
            return None
        resultat['r'] = 'pose'
        nl = '\r\n' if '\r\n' in contenu else '\n'
        lignes = contenu.splitlines(keepends=True)
        debut = next((i for i, l in enumerate(lignes) if re.match(r'^#{2,3}\s+Règles remplacées\s*$', l.rstrip('\r\n'))), None)
        if debut is None:
            if contenu and not contenu.endswith(('\n', '\r')):
                contenu += nl
            return contenu + nl + '## Règles remplacées' + nl + nl + entree + nl
        fin = len(lignes)
        for k in range(debut + 1, len(lignes)):
            if re.match(r'^#{1,3}\s', lignes[k]):
                fin = k
                break
        while fin > debut + 1 and not lignes[fin - 1].strip():
            fin -= 1
        if fin == len(lignes) and lignes and not lignes[-1].endswith(('\n', '\r')):
            lignes[-1] += nl
        lignes.insert(fin, entree + nl)
        return ''.join(lignes)
    r = _ecrit(registre.modifier, pathlib.Path(studio) / rel, ranger)
    return r if r in ('illisible', 'change') else resultat.get('r', 'hors')


def chemin_registre(plan):
    return registre.chemin_du_studio(plan['studio'])


def date_connue(plan, v):
    """A value for the register, whose format requires a date: its own date, else the date of the document it is
    written in (the last time that file changed), said in the text (« date inconnue, celle du fichier »). Never
    today's date passed off as the source's."""
    v = dict(v)
    if v.get('date') and registre.DATE.match(v['date']):
        return v
    base = os.path.realpath(plan['studio'])
    for rel in (v.get('document'), v.get('source')):
        if not rel:
            continue
        p = pathlib.Path(os.path.realpath(os.path.join(plan['studio'], rel)))
        if str(p).startswith(base + os.sep) and p.is_file():
            v['date'] = registre.jjmmaaaa(dt.date.fromtimestamp(p.stat().st_mtime))
            v['texte'] = f"{v['texte']} (date inconnue, celle du fichier)"
            return v
    v['date'] = registre.jjmmaaaa(plan['date'])
    v['texte'] = f"{v['texte']} (date inconnue, celle du relevé)"
    return v


def enregistrer_decision(plan, d):
    """The case of decision `d` in the register: the one already there (same sources and dates, whatever the
    wording), else a new one appended."""
    if d.get('cas'):
        return d['cas']
    a, n = date_connue(plan, d['ancienne']), date_connue(plan, d['nouvelle'])
    t = plan['titres']
    # The register keeps the Studio's codes (traceability), each with its title.
    a, n = dict(a, texte=etiqueter(a['texte'], t)), dict(n, texte=etiqueter(n['texte'], t))
    e = lambda x: pour_le_pm(x or '', t)
    file = {'niveau': d.get('niveau') or 'arbitrage', 'recommande': d.get('recommande'), 'pourquoi': e(d.get('pourquoi')),
            'contexte': e(d.get('contexte')), 'raisons': [r for r in d.get('raisons') or [] if r in registre.RAISONS],
            'ajoute_par': AJOUTE_PAR.get(plan.get('mode'), 'rattrapage')}
    d['cas'] = registre.ajouter(chemin_registre(plan), d['titre'], a, n, d['communique'], plan['date'],
                                par_sources=True, file=file)
    return d['cas']


AJOUTE_PAR = {'rattrapage': 'rattrapage', 'relecture': 'relecture', 'passe': 'passe hebdomadaire'}


def ecrire(plan, pm, decisions_seules=False, passe=False):
    """After the PM's go: the safe markings (a passage that moved becomes a PM decision), the additions, every PM
    decision appended to the register (open), « Dernier passage », one journal row."""
    if plan['sujets'] and not plan['jugements']:
        raise SystemExit("rien de jugé dans ce plan : lance d'abord les sous-agents puis `juger`")
    studio = plan['studio']
    # The weekly pass (`passe`): no question and nothing marked in the documents; the decisions go to the register
    # (the queue), the safe markings wait in the plan for the PM's grouped go.
    decisions_seules = decisions_seules or passe
    if passe:
        plan['mode'] = 'passe'
    compte = {'pose': 0, 'deja': 0, 'bouge': 0, 'hors': 0, 'illisible': 0, 'change': 0}
    par_id = {s['id']: s for s in plan['sujets']}
    bouges = set()
    if not decisions_seules:
        for m in plan['marquages']:
            if m['etat'] in ('pose', 'deja'):
                continue
            m['etat'] = poser(studio, m['fichier'], m['passage'], m['ligne'], m['texte'], m['cle'], plan['titres'])
            compte[m['etat']] += 1
            if m['etat'] not in ('pose', 'deja'):
                bouges.add(m['sujet'])         # moved, unreadable, refused: the PM decides, nothing written there
        for sid in sorted(bouges, key=lambda x: int(x[1:])):
            if any(d['sujet'] == sid for d in plan['decisions']):
                continue
            j = dict(plan['jugements'][sid], recommande='remplacer')
            d = nouvelle_decision(plan, par_id[sid], j, "Un passage a bougé depuis l'aperçu, ou son fichier ne se lit pas : "
                                                         "rien n'y a été écrit.")
            d['id'] = f"D{len(plan['decisions']) + 1}"
            d['niveau'], d['raisons'] = 'arbitrage', d['raisons'] or ['passage qui a bougé']   # the PM sees it
            plan['decisions'].append(d)
        for a in plan['absences']:
            if a['etat'] in ('pose', 'deja'):
                continue
            a['etat'] = ajouter_en_fin(studio, a['fichier'], f"➕ Ajouté le {registre.jjmmaaaa(plan['date'])} : {a['texte']} "
                                       f"(source : {a['source']}) — {plan['mode']} du {registre.jjmmaaaa(plan['date'])}",
                                       cle=a['texte'])
            if a['etat'] not in ('pose', 'deja'):
                compte['hors'] += 1
    for d in plan['decisions']:
        enregistrer_decision(plan, d)
    # « Dernier passage » only after a complete pass: every subject judged, the whole Studio, the markings written.
    # Otherwise the previous date stays, and the next re-read takes those subjects again.
    complet = (not decisions_seules or passe) and not plan.get('dossier') \
        and all(s['id'] in plan['jugements'] for s in plan['sujets'])
    if complet:
        avant = registre.lire_fichier(chemin_registre(plan))['dernier_passage']
        # Never back in time: a pass's markings written later must not make the next re-read start earlier.
        if not avant or registre.iso(avant) <= plan['date']:
            # What it read first: « Dernier passage » never moves past lines that were not kept as read.
            if ecrire_lignes_lues(plan) or 'lu' not in plan:
                registre.poser_dernier_passage(chemin_registre(plan), plan['date'])
            else:
                complet = False
    plan['dernier_passage_pose'] = complet
    fichiers = {m['fichier'] for m in plan['marquages'] if m['etat'] == 'pose'}
    ajouts = sum(1 for a in plan['absences'] if a['etat'] == 'pose')
    journal(studio, f"Conflits, {plan['mode']} : {compte['pose']} marquages dans {len(fichiers)} fichiers, {ajouts} "
                    f"ajouts, {len(plan['decisions'])} décisions du PM au registre (projet/conflits.md)"
            + (f", {len(plan['marquages'])} marquages sûrs en attente du go du PM" if passe and plan['marquages'] else ''))
    plan['ecrit'] = not passe or not (plan['marquages'] or plan['absences'])
    plan['ecrit_par'] = pm
    # The recap of the grouped go (PM, 2026-11-10): each file, and the conflicts marked in it, by their titles.
    recap = {}
    for m in plan['marquages']:
        if m['etat'] == 'pose':
            recap.setdefault(m['fichier'], [])
            titre = pour_le_pm(m['titre'], plan['titres'])
            if titre not in recap[m['fichier']]:
                recap[m['fichier']].append(titre)
    for a in plan['absences']:
        if a['etat'] == 'pose':
            recap.setdefault(a['fichier'], []).append(f"ajout : {pour_le_pm(a['titre'], plan['titres'])}")
    return {'marquages': compte, 'fichiers': len(fichiers), 'ajouts': ajouts, 'decisions': len(plan['decisions']),
            'devenus_decisions': sorted(bouges),
            'recap': [f"{registre.chemin_lisible(f)} : {' ; '.join(ts)}" for f, ts in sorted(recap.items())],
            'evidents': sum(1 for d in plan['decisions'] if est_evident(d)),
            'arbitrages': sum(1 for d in plan['decisions'] if not est_evident(d))}


# ---------- the decision forms

def choix_du_libelle(texte):
    """A form's answer back to the register's choice: « Garder tel quel » is written « simple discussion »."""
    t = (texte or '').replace(RECOMMANDE, '').strip()
    for choix, lib in LIBELLES.items():
        if norm(t) in (norm(choix), norm(lib)):
            return choix
    return None


def formulaire(plan, d, rang, total):
    """One AskUserQuestion form, prepared in full and without any code: the conflict's title in plain words, then its
    context (who said what, and when); the substantive options, recommended first, then « Discuter d'abord ». And what
    « Discuter d'abord » needs, codes removed too; the codes and paths, for the PM who asks for them, in `references`.
    `cas` is for the script only (repondre), never shown."""
    t = plan['titres']
    e = lambda x: pour_le_pm(x, t)
    a, n = d['ancienne'], d['nouvelle']
    question = f"{e(d['titre'])}\n{e(d.get('contexte') or contexte_par_defaut(plan, a, n))}"
    ordre = [d['recommande']] + [c for c in registre.CHOIX if c != d['recommande']]
    options = [{'label': LIBELLES[c] + (RECOMMANDE if c == d['recommande'] else ''), 'description': DESCRIPTIONS[c]}
               for c in ordre]
    options.append({'label': LIBELLE_DISCUTER, 'description': DESCRIPTION_DISCUTER})
    dependantes = [e(x['titre']) for x in plan['decisions'] if x['depend_de'] and x['depend_de'] == d['sujet']]
    codes = sorted({c for x in [a['texte'], n['texte'], d['titre']] + [y['contexte'] for y in d['extraits']]
                    for c in CODE_STUDIO.findall(x)} | ({d['cas']} if d.get('cas') else set())
                   | {v.get('code') for v in (a, n) if v.get('code')})
    return {'cas': d['cas'], 'decision': d['id'], 'rang': rang, 'total': total,
            'header': f'Cas {rang}/{total}'[:12], 'question': question, 'options': options, 'multiSelect': False,
            'discuter': {'ancienne': {'texte': e(a['texte']), 'ou': registre.chemin_lisible(a['source']), 'date': a.get('date')},
                         'nouvelle': {'texte': e(n['texte']), 'ou': registre.chemin_lisible(n['source']), 'date': n.get('date')},
                         'extraits': [{'ou': registre.chemin_lisible(x['fichier']), 'client': x['client'],
                                       'texte': e(x['contexte'])} for x in d['extraits'][:3]],
                         'en_depend': dependantes, 'pourquoi': e(d['pourquoi']),
                         'recommande': LIBELLES[d['recommande']]},
            'references': {'codes': {c: t.get(c, '') for c in codes},
                           'fichiers': sorted({a['source'], n['source']} | {x['fichier'] for x in d['extraits'][:3]})},
            'depend_de': next((e(x['titre']) for x in plan['decisions']
                               if d['depend_de'] and x['sujet'] == d['depend_de']), None)}


def decision_du_registre(plan, c, index=None):
    """A decision for a register case no plan holds (written by /studio:auto-ingest, or by an earlier plan): its
    values from the register, its passages found again by the relevé's search, with the same safeguards."""
    studio = plan['studio']
    a, n = dict(c['ancienne']), dict(c['nouvelle'])
    a['document'] = a['source'] if not cible_refusee(studio, a['source']) and not est_client(a['source']) else None
    if index is None:
        index = Lignes(studio, documents_vivants(studio))
    codes = [x for x in CODE_STUDIO.findall(a['texte']) if x in plan.get('titres', {})]
    sujet_mots = mots(c['sujet']) | (mots(a['texte']) & mots(n['texte'])) or mots(a['texte'])
    trouves = index.chercher(termes_distinctifs(a['texte'], n['texte']), sujet_mots, codes, set(), n=EXTRAITS_SUJET)
    extraits = [extrait(rel, i, brute, ls) for rel, i, brute, ls in trouves]
    for k, x in enumerate(extraits, 1):
        x['id'] = f"{c['id']}.{k}"
    nom = f"{c['id']} · {c['sujet']}"
    f = c.get('file') or registre.lire_file({})
    recommande = f['recommande'] or 'à confirmer avec le client'
    pourquoi = f['pourquoi'] or ("Cas inscrit au registre sans aperçu de ce relevé : pas de recommandation, à confirmer "
                                 "par défaut." if not f['recommande'] else '')
    raisons = list(f['raisons'])
    if f['niveau'] == 'evident' and not f['recommande']:
        raisons.append(RAISON_SAVOIR)            # never pre-answered without an opinion
    # The level written in the register is the one every view reads (the plan, `attente`, Mon Studio): trusted as
    # written. A case without one is a real decision anyway.
    niveau = 'arbitrage' if raisons or f['niveau'] != 'evident' else 'evident'
    return {'niveau': niveau, 'raisons': raisons, 'sorti': False, 'contexte': f['contexte'] or None,
            'id': f"R{c['id']}", 'sujet': None, 'titre': c['sujet'], 'ancienne': a, 'nouvelle': n,
            'communique': c['communique'], 'extraits': extraits, 'recommande': recommande, 'pourquoi': pourquoi,
            'depend_de': None, 'nom': nom, 'cle': f"par {nom}, source {n['source']}",
            'marquage': f"⚠️ Remplacé le {n['date']} par {nom}, source {n['source']} — {plan['mode']} du "
                        f"{registre.jjmmaaaa(plan['date'])}", 'cas': c['id'], 'reponse': None, 'ecrit': False}


def plan_vide(studio):
    """A plan without a preview, for the register's cases alone (voice answer, or cases from the ingestion)."""
    studio = str(pathlib.Path(studio).resolve())
    return {'version': 2, 'studio': studio, 'nom': nom_court(studio), 'date': aujourdhui(), 'mode': 'relecture',
            'dossier': None, 'depuis': None, 'sujets': [], 'titres': registre.titres_du_studio(studio), 'jugements': {},
            'marquages': [], 'decisions': [], 'absences': [], 'ecrit': True}


def completer_du_registre(plan):
    """Adds to the plan every open case of the register it does not hold yet. Returns how many."""
    connus = {d.get('cas') for d in plan['decisions']}
    manquants = [c for c in registre.lire_fichier(chemin_registre(plan))['cas'] if c['etat'] == 'ouvert' and c['id'] not in connus]
    if not manquants:
        return 0
    for k, v in registre.titres_du_studio(plan['studio']).items():
        plan.setdefault('titres', {}).setdefault(k, v)
    index = Lignes(plan['studio'], documents_vivants(plan['studio']))
    for c in manquants:
        plan['decisions'].append(decision_du_registre(plan, c, index))
    return len(manquants)


def _restantes(plan):
    """The decisions of the plan still open in the register."""
    reg = {c['id']: c for c in registre.lire_fichier(chemin_registre(plan))['cas']}
    return [d for d in plan['decisions'] if d.get('cas') and d['reponse'] is None
            and reg.get(d['cas'], {}).get('etat') == 'ouvert']


def est_evident(d):
    return d.get('niveau') == 'evident' and not d.get('sorti')


def _sortis_chemin(studio):
    return pathlib.Path(studio) / registre.DIR_CONFLITS / 'sortis.json'


def appliquer_sortis(plan):
    """The cases the PM took out of the obvious list stay out, whatever plan the session reads next (a weekly pass,
    the register alone): kept by case id in projet/.conflits/sortis.json, never in the register."""
    x = registre._lire_json(_sortis_chemin(plan['studio'])) or {}
    sortis = set(c for c in x.get('cas') or [] if isinstance(c, str))
    for d in plan['decisions']:
        if d.get('cas') in sortis:
            d['sorti'] = True
    return sortis


def noter_sortis(plan, cas):
    deja = appliquer_sortis(plan)
    if set(cas) - deja:
        ecrire_texte(_sortis_chemin(plan['studio']), json.dumps({'cas': sorted(deja | set(cas))}) + '\n')


def formulaires(plan):
    """The forms of the real decisions only (and of the obvious cases the PM took out of the list), one per decision.
    The obvious cases go through `evidents` first."""
    completer_du_registre(plan)
    appliquer_sortis(plan)
    restantes = [d for d in _restantes(plan) if not est_evident(d)]
    return [formulaire(plan, d, k, len(restantes)) for k, d in enumerate(restantes, 1)]


# ---------- the obvious cases: one list, one form (PM, 2026-11-10)

LIBELLE_VALIDER = 'Valider ces réponses'
LIBELLE_UNE_PAR_UNE = 'Les poser une par une'


def evidents(plan):
    """The obvious cases, pre-answered: the list the PM reads (each by its title, the answer in words, why in one
    line, no code) and the one form that validates them. Empty when there is none."""
    completer_du_registre(plan)
    appliquer_sortis(plan)
    t = plan.get('titres') or {}
    e = lambda x: pour_le_pm(x or '', t)
    liste = [d for d in _restantes(plan) if est_evident(d)]
    if not liste:
        return {'liste': [], 'texte': '', 'formulaire': None}
    lignes = [f"- « {e(d['titre'])} » : {LIBELLES[d['recommande']].lower()}"
              + (f" ({une_ligne(e(d['pourquoi']), 160)})" if d.get('pourquoi') else '') for d in liste]
    n = len(liste)
    question = (f"{n} cas évident{'s' if n > 1 else ''}, pré-répondu{'s' if n > 1 else ''} ci-dessus.\n"
                "Tu peux les valider d'un coup, en sortir (« sors le … » : il rejoint les vraies questions) ou en "
                "changer une réponse, dans « Autre ».")
    options = [{'label': LIBELLE_VALIDER + RECOMMANDE, 'description': "Chaque cas prend la réponse indiquée ; tout s'écrit en une fois."},
               {'label': LIBELLE_UNE_PAR_UNE, 'description': 'Chaque cas devient une question à part, posée seule.'},
               {'label': LIBELLE_DISCUTER, 'description': DESCRIPTION_DISCUTER}]
    return {'liste': [{'titre': e(d['titre']), 'reponse': LIBELLES[d['recommande']]} for d in liste],
            'texte': '\n'.join(lignes),
            'formulaire': {'header': 'Cas évidents', 'question': question, 'options': options, 'multiSelect': False}}


def _designer(liste, quoi):
    """The decisions of `liste` the PM's words point at (« le comité de pilotage »): exact title, else every word."""
    voulus = mots(quoi) or {w for w in re.findall(r'[a-z0-9]+', norm(quoi)) if len(w) >= 3}
    if not voulus:
        return []
    exacts = [d for d in liste if norm(d['titre']).strip() == norm(quoi).strip()]
    return exacts or [d for d in liste if voulus <= mots(d['titre']) | set(re.findall(r'[a-z0-9]+', norm(d['titre'])))]


def valider_evidents(plan, pm, sortir=(), changer=(), tous_sortir=False):
    """The PM's one answer on the obvious cases: those he takes out become real decisions (asked one by one), those
    he changes take his answer, all the others their pre-answer; written in one go. A word that points at no case or
    at several: nothing is written, the cases are named."""
    completer_du_registre(plan)
    appliquer_sortis(plan)
    t = plan.get('titres') or {}
    liste = [d for d in _restantes(plan) if est_evident(d)]
    erreurs, sortis, changes = [], [], {}
    for quoi in sortir:
        trouves = _designer(liste, quoi)
        if len(trouves) != 1:
            erreurs.append(_ambigu(quoi, trouves, t))
        else:
            sortis.append(trouves[0])
    for c in changer:
        trouves = _designer(liste, c.get('quoi') or '')
        choix = choix_du_libelle(c.get('choix')) or (c.get('choix') if c.get('choix') in registre.CHOIX else None)
        if len(trouves) != 1:
            erreurs.append(_ambigu(c.get('quoi') or '', trouves, t))
        elif not choix:
            erreurs.append(f"réponse inconnue pour « {pour_le_pm(trouves[0]['titre'], t)} » : {c.get('choix')!r}")
        else:
            changes[trouves[0]['cas']] = choix
    if erreurs:
        return {'ecrites': 0, 'erreurs': erreurs, 'sortis': [], 'point': 'Rien écrit.'}
    if tous_sortir:
        sortis = list(liste)
    for d in sortis:
        d['sorti'] = True
        changes.pop(d['cas'], None)
    if sortis:
        noter_sortis(plan, [d['cas'] for d in sortis])
    reponses = [{'cas': d['cas'], 'choix': changes.get(d['cas'], d['recommande'])} for d in liste if d not in sortis]
    r = repondre(plan, reponses, pm)
    r['sortis'] = [pour_le_pm(d['titre'], t) for d in sortis]
    return r


def _ambigu(quoi, trouves, t):
    if not trouves:
        return f"aucun cas évident ne répond à « {pour_le_pm(quoi, t)} »"
    return "plusieurs cas répondent à « " + pour_le_pm(quoi, t) + " » : " + ' ; '.join(
        f"« {pour_le_pm(d['titre'], t)} »" for d in trouves) + '. Lequel ?'


def appliquer_reponse(plan, d, choix, pm):
    """One answer, written: the register's État line, then its effect in the documents, then a journal row. What could
    not be written (passage moved, file unreadable or refused, no living document for « Règles remplacées ») is said."""
    studio, t = plan['studio'], plan.get('titres') or {}
    enregistrer_decision(plan, d)
    registre.changer_etat(chemin_registre(plan), d['cas'], choix, pm, plan_jour())
    effets = {'pose': 0, 'deja': 0, 'a_la_main': []}
    jour = registre.jjmmaaaa(plan_jour())

    def marquer(texte, cle):
        for x in d['extraits']:
            if x.get('lecture_seule'):
                effets['a_la_main'].append(f"{registre.chemin_lisible(x['fichier'])} (lecture seule)")
                continue
            r = poser(studio, x['fichier'], x['passage'], x['ligne'], texte, cle, t)
            if r in ('pose', 'deja'):
                effets[r] += 1
            else:
                effets['a_la_main'].append(f"{registre.chemin_lisible(x['fichier'])} ({ETATS_ECRITURE.get(r, r)})")
    if choix == 'remplacer':
        marquer(d['marquage'], d['cle'])
        a, n = d['ancienne'], d['nouvelle']
        entree = (f"- {etiqueter(a['texte'], t)} (source : {a['source']}, {a['date']}) — remplacée le {n['date']} par "
                  f"{etiqueter(n['texte'], t)}, source {n['source']}, actée par {pm} le {jour} ({d['cas']} · {d['titre']})")
        r = regles_remplacees(studio, a.get('document'), entree, f"({d['cas']} · ")
        effets['regles_remplacees'] = r
        if r not in ('pose', 'deja'):
            effets['a_la_main'].append("« Règles remplacées » : aucun document vivant ne porte l'ancienne règle "
                                       f"({ETATS_ECRITURE.get(r, r)}), à ranger à la main")
    elif choix == 'à confirmer avec le client':
        note = (f"ℹ️ À confirmer avec le client depuis le {jour} : {etiqueter(d['nouvelle']['texte'], t)}, source "
                f"{d['nouvelle']['source']} ({d['nouvelle']['date']}) — {plan['mode']} du {jour}")
        marquer(note, f"À confirmer avec le client depuis le {jour}")
    j = journal(studio, f"Conflit {d['cas']} · {d['titre']} : tranché par {pm}, {choix}")
    if j in ('illisible', 'change'):
        effets['a_la_main'].append(f"le journal du Studio ({ETATS_ECRITURE[j]}) : sa ligne n'est pas écrite")
    d['reponse'], d['ecrit'] = choix, True
    return effets


ETATS_ECRITURE = {'bouge': 'passage introuvable', 'hors': 'fichier jamais écrit par ce script',
                  'illisible': 'fichier illisible, jamais réécrit', 'change': 'fichier en cours d\'écriture ailleurs'}


def plan_jour():
    return aujourdhui()


def repondre(plan, reponses, pm):
    """A batch of answers ([{"cas": "C7", "choix": "remplacer"}…]), each written once; then « n faites, m restent »."""
    par_cas = {d['cas']: d for d in plan['decisions'] if d.get('cas')}
    faits, erreurs, details = 0, [], []
    for r in reponses:
        d = par_cas.get(r.get('cas'))
        choix = choix_du_libelle(r.get('choix')) or (r.get('choix') if r.get('choix') in registre.CHOIX else None)
        if not d or not choix:
            erreurs.append(f"une réponse n'a pas été comprise ({r.get('choix')!r}) : rien n'est écrit pour elle")
            continue
        if d['reponse'] == choix and d['ecrit']:
            continue
        effets = appliquer_reponse(plan, d, choix, pm)
        faits += 1
        if effets['a_la_main']:
            details.append(f"« {pour_le_pm(d['titre'], plan.get('titres') or {})} » : à reprendre à la main : "
                           f"{', '.join(effets['a_la_main'])}")
    total = len([d for d in plan['decisions'] if d.get('cas')])
    faites = len([d for d in plan['decisions'] if d['reponse']])
    return {'ecrites': faits, 'faites': faites, 'restent': total - faites, 'erreurs': erreurs, 'details': details,
            'point': f"{faites} faites, {total - faites} restent"}


# ---------- what the PM has seen, the reminder's thresholds, what waits (PM, 2026-11-10)

def chemin_conflits(studio):
    return pathlib.Path(studio) / registre.DIR_CONFLITS


def est_un_studio(studio):
    return (pathlib.Path(studio) / '.claude' / '.studio-manifest.json').exists()


def noter_vu(studio):
    """The PM has just been shown the register: every case up to its largest id is seen (Mon Studio's dot goes).
    Nothing is written outside a Studio."""
    if not est_un_studio(studio):
        return 0
    r = registre.lire_fichier(registre.chemin_du_studio(studio))
    n = max([r['max_id']] + [registre.lire_vu(studio)])
    try:
        ecrire_texte(chemin_conflits(studio) / 'vu.json', json.dumps({'vu': n, 'le': aujourdhui()}) + '\n')
    except OSError:
        pass
    return n


def regler(studio, cas=None, jours=None):
    """The reminder's thresholds of this Studio (Mon Studio, « Ce qui t'attend »): from `cas` open cases, or `jours`
    days without a treatment. Each from 1 to 365."""
    if not est_un_studio(studio):
        raise ValueError(f"« {studio} » n'est pas un Studio (pas de .claude/.studio-manifest.json) : rien n'est écrit")
    r = registre.lire_reglages(studio)
    for cle, v in (('relance_cas', cas), ('relance_jours', jours)):
        if v is None:
            continue
        if not isinstance(v, int) or not 1 <= v <= 365:
            raise ValueError(f'{v!r} : un nombre de 1 à 365')
        r[cle] = v
    ecrire_texte(chemin_conflits(studio) / 'reglages.json', json.dumps(r) + '\n')
    return r


def attente(studio):
    """What waits for the PM, in words: safe markings prepared by a pass (per plan), obvious cases, real decisions."""
    reg = registre.ouverts(studio)
    en_attente = []
    for chemin in plans_du_studio(studio):
        try:
            plan = charger_plan(chemin)
        except (OSError, ValueError):
            continue
        # Only what was never tried: a marking that moved was turned into a decision by the go.
        reste = [m for m in plan.get('marquages') or [] if m.get('etat') is None]
        reste_a = [a for a in plan.get('absences') or [] if a.get('etat') is None]
        if plan.get('jugements') and (reste or reste_a) and plan.get('mode') == 'passe' and not plan.get('ecrit'):
            en_attente.append({'plan': chemin, 'date': plan['date'], 'marquages': len(reste), 'ajouts': len(reste_a)})
    ouverts = reg['ouverts']
    return {'marquages_en_attente': en_attente, 'pret': lire_pret(studio),
            'evidents': sum(1 for c in ouverts if c['file']['niveau'] == 'evident'),
            'arbitrages': sum(1 for c in ouverts if c['file']['niveau'] != 'evident'),
            'illisibles': len(reg['illisibles'])}


# ---------- the Monday pass, inside the morning point (PM, Q18, 2026-11-15)
# No scheduled task per Studio: on the first morning point of the week, `matin.py preparer` opens the pass of every
# Studio the PM leads that had a complete pass and has no automatic ingestion, and gives the morning task the subjects
# to judge with CONSIGNE_JUGEMENT; the task hands its judgments to the connector's tool `conflits_juger`, which calls
# `cloturer`. Nothing is marked in the documents: the decisions go to the register, the safe markings wait in the plan
# for the PM's grouped go in the conflicts session.

# Subjects' text handed to the morning task in one day, all Studios together. Measured on 2026-11-23 on two real
# Studios, one heavy day (Friday to Monday): 47 subjects, 133,000 characters, judged by Sonnet for 0.54 $ (0.04 % of
# the week); 200,000 characters stay under 0.1 % a morning, so a busy Studio is never left waiting for days.
PASSE_MATIN_CARACTERES = 200000
INGESTION_ACTIVE_S = 8 * 86400   # an automatic ingestion that passed within 8 days writes its own cases to the register


def nom_du_plan_de_passe(chemin):
    return re.fullmatch(r'passe-\d{4}-\d{2}-\d{2}\.json', pathlib.Path(chemin).name) is not None


def ingestion_active(studio, maintenant=None):
    """True when /studio:auto-ingest passed on this Studio within INGESTION_ACTIVE_S: it writes its cases itself."""
    maintenant = dt.datetime.now().timestamp() if maintenant is None else maintenant
    etat = registre._lire_json(pathlib.Path(studio) / 'projet' / '.ingestion-auto-state.json')
    if not isinstance(etat, dict):
        return False
    for n in etat.get('nouvelles') or []:
        try:
            t = dt.datetime.fromisoformat(str(n.get('ts')).replace('Z', '+00:00')).timestamp()
        except (AttributeError, TypeError, ValueError):
            continue
        if maintenant - t <= INGESTION_ACTIVE_S:
            return True
    return False


def ouvrir_passe(studio, plan=None):
    """The daily pass: only what is new since « Dernier passage », written as a plan `passe-<date>.json` next to the
    register. {'etat': 'jamais' | 'rien' | 'ouverte', 'texte', 'chemin', 'plan'}. `plan`: a re-read already made."""
    plan = plan or releve(studio, None, True)
    if not plan.get('depuis'):
        # Without « Dernier passage » the pass would read the whole Studio every week, at a cost no go covered.
        return {'etat': 'jamais', 'chemin': None, 'plan': plan,
                'texte': "Pas encore de passage complet sur ce Studio : la passe hebdomadaire ne relit pas tout. Rien "
                         "n'est fait ; le rattrapage se fait dans la session des conflits."}
    if not plan['sujets']:
        return {'etat': 'rien', 'chemin': None, 'plan': plan,
                'texte': 'Rien de nouveau depuis le dernier passage : rien à juger.'}
    sortie = chemin_conflits(plan['studio']) / f"passe-{plan['date']}.json"
    plan['mode'] = 'passe'
    # A pass run again the same day renumbers its subjects: the judgments of the earlier run are set aside, never
    # applied to other subjects (renamed, nothing deleted).
    for f in glob.glob(str(sortie.with_name(sortie.stem + '.jugements-*.json'))):
        os.replace(f, f + '.ancien')
    sauver_plan(sortie, plan)
    return {'etat': 'ouverte', 'chemin': str(sortie), 'plan': plan,
            'texte': f"Plan : {sortie}\n{len(plan['sujets'])} sujet(s), {plan['cout']['lots']} lot(s). Rien n'est écrit "
                     "dans le Studio hors de ce plan."}


def passe_du_matin(studio, reste):
    """For the morning point: the pass of one Studio, its subjects as one text for the morning task. None when there is
    nothing to judge; {'trop': True} when the subjects' text is over `reste` characters (no plan is kept: the next
    Monday re-reads from the same « Dernier passage »); else {'plan', 'sujets', 'texte'}."""
    plan = releve(studio, None, True)
    if not plan.get('depuis'):
        return None
    if not plan['sujets']:
        # Nothing new to judge is a complete pass: « Dernier passage » moves to today with what it read, so the tab
        # says « à jour » and tomorrow re-reads only tomorrow's lines.
        cloturer_sans_sujet(plan)
        return None
    texte = '\n'.join(texte_lot(plan, k) for k in range(1, len(lots_du_plan(plan)) + 1))
    if len(texte) > reste:
        return {'trop': True, 'sujets': len(plan['sujets'])}
    r = ouvrir_passe(studio, plan)
    if r['etat'] != 'ouverte':
        return None
    texte = '\n'.join(texte_lot(r['plan'], k) for k in range(1, len(lots_du_plan(r['plan'])) + 1))
    return {'plan': r['chemin'], 'sujets': len(r['plan']['sujets']), 'texte': texte}


def cloturer_sans_sujet(plan):
    """A re-read that found no subject: « Dernier passage » set to the plan's day (never back in time), and what it read."""
    avant = registre.lire_fichier(chemin_registre(plan))['dernier_passage']
    if plan['sujets'] or plan.get('dossier') or (avant and registre.iso(avant) > plan['date']):
        return False
    if not ecrire_lignes_lues(plan):
        return False
    registre.poser_dernier_passage(chemin_registre(plan), plan['date'])
    return True


def cloturer(chemin_plan, jugements=None):
    """The end of a pass: the judgments (the files next to the plan, plus `jugements` given by the morning task, kept in
    `<plan>.jugements-matin.json`) merged, the decisions written to the register, nothing marked. Returns the report."""
    p = pathlib.Path(chemin_plan)
    plan = charger_plan(chemin_plan)
    if jugements is not None:
        ecrire_texte(p.with_name(p.stem + '.jugements-matin.json'), json.dumps(jugements, ensure_ascii=False, indent=1))
    tous = []
    for f in sorted(glob.glob(str(p.with_name(p.stem + '.jugements-*.json')))):
        with open(f, encoding='utf-8') as h:
            x = json.load(h)
        tous += x if isinstance(x, list) else x.get('jugements', [])
    erreurs = juger(plan, tous)
    r = ecrire(plan, 'passe hebdomadaire', passe=True)
    sauver_plan(chemin_plan, plan)
    lignes = [f"{r['decisions']} décisions au registre ({r['evidents']} évidentes, {r['arbitrages']} à trancher une par une), "
              f"{len(plan['marquages'])} marquages sûrs en attente du go du PM."
              + ('' if plan.get('dernier_passage_pose') else ' Dernier passage inchangé : des sujets restent à juger.')]
    lignes += [f"Jugement écarté : {e}" for e in erreurs]
    return '\n'.join(lignes)


# What the morning task applies to the subjects of a pass: the sub-agent's brief of the conflicts skill, without its
# file gestures (the task reads no file and writes through the connector). Kept in step with SKILL.md by a test.
CONSIGNE_JUGEMENT = """Tu juges les sujets des conflits d'un Studio, donnés dans `texte` : tu ne lis aucun fichier. Pour chaque sujet, applique la règle de lecture commune ci-dessous et classe-le :
- `M` (marquage sûr) : l'ancien terme ET le sujet sont dans le même passage, et la nouvelle source est écrite et pèse au moins autant que l'ancienne. Donne les extraits à marquer.
- `PM` (décision du PM) : un doute, une source orale ou plus faible, un document signé contredit, deux règles actives qui se contredisent, un revirement dans une source, une page html qui garde l'ancienne valeur. Donne la réponse recommandée (`remplacer`, `à confirmer avec le client` ou `simple discussion`) et pourquoi, en une ou deux phrases.
- `absence` (à ajouter) : la nouvelle valeur manque là où elle devrait figurer ; donne le fichier (pris dans les extraits) et le texte à ajouter, une ligne.
- `rien` : aucun extrait ne présente l'ancienne valeur comme valable aujourd'hui.
« Rien » est strict. Un passage d'un document vivant (README, statut, fiche, roadmap, prérequis, stack, glossaire, story map, page html) qui écrit encore l'ancienne valeur au présent n'est jamais « rien », même s'il est court, même si la nouvelle valeur le nuance seulement, même si un autre document est déjà à jour : `M` si c'est sûr, sinon `PM`. « Rien » seulement quand l'extrait ne porte pas l'ancienne valeur, porte déjà la nouvelle ou la nuance explicitement, ou raconte le passé (une ligne datée d'historique, une question déjà résolue dans sa propre ligne, un compte rendu).
Genres particuliers : une « page html jumelle d'un document sous bandeau » est `PM` (recommandé `remplacer` : y mettre le même bandeau), sauf si l'extrait montre déjà un bandeau ; un « compteur peut-être périmé » ou une « phase du projet » qui ne correspond plus au compte donné est `M` quand la ligne dit bien la même chose que le compte (même périmètre), sinon `rien`.
Une décision tirée d'un résumé automatique seul : `resume_seul: true` (elle reste « à confirmer »). Une nouvelle valeur seulement dite à l'oral (réunion, appel), sans écrit qui la reprenne : `source_orale: true`. Une décision que seul le PM peut prendre, parce qu'elle dépend de ce qu'il sait hors du Studio (un échange, une intention, un engagement) : `savoir_pm: true`.
Règle de lecture commune, pour qu'aucun outil ne présente comme vraie une donnée qu'une source plus récente du Studio a changée :
1. La dernière source datée fait foi. Un document vivant qui la contredit est en retard, et non incomplet. Un document signé ne cède qu'à une source écrite qui pèse au moins autant : document signé, puis échange écrit, puis oral. Une décision tirée d'un résumé automatique seul reste « à confirmer ».
2. Donnée figée (agenda, fiche, règle, horaire d'un rituel) : la rapprocher des échanges récents du Studio. S'ils divergent, donner les deux valeurs avec leurs dates. Ne jamais trancher seul.
3. Action déjà faite : avant d'annoncer une action « à faire », chercher la preuve qu'elle est faite (compte rendu coché, ticket, commit ou branche) ; si elle l'est, « déjà fait le {date} ».
`jugements` est une liste JSON, un objet par sujet. Pour `rien`, seulement `{"sujet": "S12", "classe": "rien"}`. Sinon : `{"sujet": "<son identifiant>", "classe": "M|PM|absence", "titre": "<3 à 8 mots en clair>", "contexte": "<qui a dit quoi, et quand, en une ou deux phrases simples>", "passages": ["<identifiants des extraits>"], "recommande": "…", "pourquoi": "…", "depend_de": "<identifiant d'un autre sujet>" ou null, "absence": {"fichier": "…", "texte": "…"} ou null, "resume_seul": false, "source_orale": false, "savoir_pm": false}`.
Le titre et le contexte sont lus par le PM : aucun code dedans (ni numéro de décision, de règle, de question, d'US, de ticket, ni lettre seule), seulement des mots ; « le PM », la personne, est permis."""


# ---------- a preview prepared on demand (PM, 2026-11-15; from the board, Q18): the PM only validates later

# The PM's time, said with the count of questions (an estimate, not a measure): a minute per real decision, asked
# alone and answered by voice; a quarter of a minute per obvious case, read in a list; two minutes for the preview and
# the grouped go.
MINUTES_BASE, MINUTES_PAR_DECISION, MINUTES_PAR_EVIDENT = 2, 1.0, 0.25


def minutes_pm(evidents, arbitrages):
    return max(1, math.ceil(MINUTES_BASE + arbitrages * MINUTES_PAR_DECISION + evidents * MINUTES_PAR_EVIDENT))


def chemin_pret(studio):
    return pathlib.Path(studio) / registre.DIR_CONFLITS / 'pret.json'


def noter_pret(plan, chemin_plan):
    """A whole-Studio catch-up judged and not written yet: a small summary next to the register, which Mon Studio
    reads without opening the plan (« 12 questions t'attendent, environ 20 min »). Not for the weekly pass (its
    markings wait in `attente`), nor a folder alone. Returns the summary, or None."""
    if plan.get('mode') == 'passe' or plan.get('dossier') or plan.get('ecrit') or not plan.get('sujets') \
            or not all(s['id'] in plan['jugements'] for s in plan['sujets']):
        return None
    # A plan kept outside the Studio (`releve --sortie`, a dry run) never leaves anything in it.
    dossier_plans = (pathlib.Path(plan['studio']) / registre.DIR_CONFLITS).resolve()
    if pathlib.Path(chemin_plan).resolve().parent != dossier_plans:
        return None
    evidents = sum(1 for d in plan['decisions'] if est_evident(d))
    arbitrages = len(plan['decisions']) - evidents
    x = {'plan': str(chemin_plan), 'date': plan['date'], 'marquages': len(plan['marquages']),
         'ajouts': len(plan['absences']), 'evidents': evidents, 'arbitrages': arbitrages,
         'minutes': minutes_pm(evidents, arbitrages)}
    try:
        ecrire_texte(chemin_pret(plan['studio']), json.dumps(x, ensure_ascii=False, indent=1) + '\n')
    except OSError:
        return None
    return x


def lire_pret(studio):
    """The prepared preview still waiting (its plan there, not written), or None."""
    x = registre._lire_json(chemin_pret(studio))
    if not x or not x.get('plan') or not os.path.exists(x['plan']):
        return None
    # A complete pass written since (another plan, a folder at a time): this preview is out of date.
    dernier = registre.iso(registre.lire_fichier(registre.chemin_du_studio(studio))['dernier_passage'])
    if dernier and str(x.get('date') or '') <= dernier:
        return None
    try:
        if charger_plan(x['plan']).get('ecrit'):
            return None
    except (OSError, ValueError):
        return None
    return x


def oublier_pret(studio, chemin_plan, tout=False):
    """The prepared preview has been written, or a complete pass (`tout`) made it out of date: the summary goes (it
    is the tool's own file, never the PM's)."""
    x = registre._lire_json(chemin_pret(studio))
    if x and (tout or os.path.abspath(str(x.get('plan') or '')) == os.path.abspath(str(chemin_plan))):
        try:
            os.unlink(chemin_pret(studio))
        except OSError:
            pass


def cout_preparer(c):
    """What preparing the preview on demand costs (PM, Q18: a gesture from the board, no scheduled task): the Sonnet
    sub-agents on the extracts and the session's calls that launch and receive them; then what stays for the session
    when the PM comes back: the decisions asked."""
    usd = c['usd_sous_agents'] + c.get('usd_session_releve', 0.0)
    ensuite = c.get('usd_session_decisions', c['usd_session'])
    return {'usd': round(usd, 2), 'pourcent_semaine': round(usd / POURCENT_USD, 2), 'usd_session': round(ensuite, 2),
            'pourcent_session': round(ensuite / POURCENT_USD, 2),
            'au_dessus_du_plafond': usd / POURCENT_USD > PLAFOND_LANCEMENT}


def texte_preparer(c):
    x = cout_preparer(c)
    return (f"Aperçu préparé maintenant, sans rien te demander d'autre : environ {fr(float(x['pourcent_semaine']))} % "
            f"de ta semaine ({fr(float(x['usd']))} $) pour {c['sujets']} sujets, sous-agents Sonnet sur extraits. "
            f"Ensuite, quand tu reviens : environ {fr(float(x['pourcent_session']))} % ({fr(float(x['usd_session']))} $) "
            f"pour les {c['decisions_estimees']} décisions estimées."
            + (" Au-dessus du plafond d'un lancement : un dossier à la fois." if x['au_dessus_du_plafond'] else ''))


def texte_pret(x):
    pl = lambda n, un, plusieurs: f"{n} {un if n == 1 else plusieurs}"
    return (f"Aperçu préparé le {registre.jjmmaaaa(x['date'])} : {pl(x['marquages'], 'marquage sûr', 'marquages sûrs')} "
            f"d'un seul go, {pl(x['evidents'], 'cas évident', 'cas évidents')} en liste, "
            f"{pl(x['arbitrages'], 'vraie question', 'vraies questions')} ; environ {x['minutes']} min de ton temps. "
            f"Plan : {x['plan']}")


# ---------- command line

def trouver_cas(cas, quoi):
    """The register cases a PM's words point at: its id if he says it (« C3 »), else the cases whose title holds all
    his words (« le comité de pilotage »). Never requires an id."""
    quoi = (quoi or '').strip()
    if re.fullmatch(r'C[1-9]\d*', quoi):
        return [c for c in cas if c['id'] == quoi]
    voulus = mots(quoi) or {w for w in re.findall(r'[a-z0-9]+', norm(quoi)) if len(w) >= 3}
    if not voulus:
        return []
    exacts = [c for c in cas if norm(c['sujet']).strip() == norm(quoi).strip()]
    return exacts or [c for c in cas if voulus <= mots(c['sujet']) | {w for w in re.findall(r'[a-z0-9]+', norm(c['sujet']))}]


def charger_plan(chemin):
    with open(chemin, encoding='utf-8') as f:
        plan = json.load(f)
    if isinstance(plan, dict) and 'lu' not in plan:
        try:
            with open(chemin_lu_du_plan(chemin), encoding='utf-8') as f:
                plan['lu'] = json.load(f)
        except (OSError, ValueError):
            pass
    return plan


def chemin_lu_du_plan(chemin):
    """What a pass read (about a megabyte on a large Studio) lives next to its plan, never inside it."""
    p = pathlib.Path(chemin)
    return p.with_name(p.stem + '.lu.json')


def sauver_plan(chemin, plan):
    plan = dict(plan)
    lu = plan.pop('lu', None)
    if isinstance(lu, dict):
        ecrire_texte(chemin_lu_du_plan(chemin), json.dumps(lu, ensure_ascii=False))
    ecrire_texte(chemin, json.dumps(plan, ensure_ascii=False, indent=1) + '\n')


def chemin_plan_defaut(studio):
    return pathlib.Path(studio) / 'projet' / '.conflits' / f'apercu-{aujourdhui()}.json'


def plans_du_studio(studio):
    d = pathlib.Path(studio) / 'projet' / '.conflits'
    # The previews of a catch-up or a re-read, and the weekly passes; never a sub-agent's judgments file.
    return sorted((f for motif in ('apercu-*.json', 'passe-*.json', 'registre.json') for f in glob.glob(str(d / motif))
                   if '.jugements-' not in f and not f.endswith('.lu.json')), key=os.path.getmtime, reverse=True)


def chemin_extraction(studio):
    return pathlib.Path(studio) / registre.DIR_CONFLITS / 'reprise.json'


def commande_reprendre(a):
    """The reprise of decisions settled by hand (PM, Q12, 2026-11-15). Without --extraction: what the sub-agent reads
    and what it costs. With it: the preview (--sortie: in that file, nothing written in the Studio), or, with --ecrire
    after the PM's go, the register."""
    r = reprise_module()
    if not est_un_studio(a.studio):
        print(f"« {a.studio} » n'est pas un Studio (pas de .claude/.studio-manifest.json).")
        return 2
    if not a.extraction:
        c = r.estimer(a.studio, registre, cout_usd, POURCENT_USD, a.dossier)
        if not c['fichiers']:
            print("Aucun rattrapage fait à la main dans ce Studio (pas de dossier projet/rattrapage-AAAA-MM-JJ) : rien à reprendre.")
            return 0
        print(f"Reprise des décisions tranchées à la main : {len(c['fichiers'])} fichier(s), "
              f"{c['caracteres'] // 1000} Ko, lus une fois par un sous-agent Sonnet : environ "
              f"{fr(float(c['pourcent_semaine']))} % de ta semaine ({fr(float(c['usd']))} $).")
        for rel, jour, taille in c['fichiers']:
            print(f"- {rel} (rattrapage du {registre.jjmmaaaa(jour)}, {taille // 1000} Ko)")
        if c['trop_gros']:
            print("Trop gros pour une lecture : un dossier à la fois (--dossier rattrapage-AAAA-MM-JJ).")
        if a.entree:
            ecrire_texte(a.entree, r.texte_entree(a.studio, a.dossier) + '\n')
            print(f"Entrée du sous-agent : {a.entree}")
        print(f"Extraction attendue dans : {chemin_extraction(a.studio)}")
        return 0
    if a.sortie and a.ecrire:
        print('--sortie (essai à blanc) et --ecrire ne vont pas ensemble.')
        return 2
    if a.sortie:
        try:
            dans = pathlib.Path(a.sortie).resolve().is_relative_to(pathlib.Path(a.studio).resolve())
        except (OSError, ValueError):
            dans = True
        if dans:
            print("--sortie : un fichier hors du Studio, pour que rien n'y soit écrit.")
            return 2
    decisions, refus = r.verifier(a.studio, r.charger(a.extraction), registre, a.pm)
    erreurs = r.changer(decisions, json.loads(a.changer or '[]'))
    if erreurs:
        print('Rien changé, rien écrit : ' + ' ; '.join(erreurs) + '. Lequel ?')
        return 2
    for d in decisions:
        if d['choix'] not in registre.CHOIX:
            print(f"Choix inconnu pour « {d['titre']} » : {d['choix']}. Rien écrit.")
            return 2
    if a.dernier_passage in ('aucun', 'non', 'none'):
        dernier = None
    elif a.dernier_passage:
        try:
            dernier = registre.jjmmaaaa(a.dernier_passage)
        except ValueError:
            dernier = None
        dernier = dernier if registre.iso(dernier) else None
        if not dernier:
            print(f"Date illisible : {a.dernier_passage} (JJ/MM/AAAA).")
            return 2
    else:
        dernier = r.dernier_passage_propose(a.studio, registre, a.dossier)
    texte, nouvelles = r.apercu(a.studio, decisions, refus, registre, dernier)
    if a.ecrire:
        if not a.pm:
            print('--pm manque : le prénom du PM, pour une décision sans auteur.')
            return 2
        x = r.ecrire(a.studio, decisions, registre, dernier, journal)
        pl = lambda n, un, plusieurs: f"{n} {un if n == 1 else plusieurs}"
        print(f"{pl(x['inscrites'], 'décision inscrite', 'décisions inscrites')} au registre comme tranchée"
              f"{'' if x['inscrites'] == 1 else 's'}, {x['deja']} déjà là."
              + (f" Dernier passage : {x['dernier_passage']}." if x['dernier_passage'] else ''))
        if refus:
            print(f"{len(refus)} écartées, rien écrit pour elles : " + ' ; '.join(n for n, _ in refus) + '.')
        if x['echecs']:
            print(f"Pas écrites : {len(x['echecs'])} ({' ; '.join(f'{n} : {e}' for n, e in x['echecs'])}). "
                  "Dernier passage pas posé : relance la même commande, rien n'est écrit deux fois.")
            return 1
        return 0
    print(texte)
    if a.sortie:
        ecrire_texte(a.sortie, texte + '\n\n----- Lignes ajoutées à projet/conflits.md -----\n\n'
                     + r.texte_registre(a.studio, nouvelles, registre, dernier) + '\n')
        print(f"\nAperçu et lignes du registre : {a.sortie}. Rien n'est écrit dans le Studio.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='conflits.py', description='Conflits d\'un Studio, sans LLM.')
    sp = p.add_subparsers(dest='cmd', required=True)
    for nom in ('estimer', 'releve'):
        x = sp.add_parser(nom)
        x.add_argument('studio')
        x.add_argument('--dossier')
        x.add_argument('--incremental', action='store_true')
        if nom == 'estimer':
            x.add_argument('--preparer', action='store_true', help="le coût d'un aperçu préparé à la demande, validé plus tard")
        if nom == 'releve':
            x.add_argument('--sortie')
    x = sp.add_parser('lot'); x.add_argument('plan'); x.add_argument('k', type=int)
    x.add_argument('--sortie', help='écrit le lot dans ce fichier, à lire en une fois')
    x = sp.add_parser('juger'); x.add_argument('plan'); x.add_argument('jugements', nargs='*')
    x = sp.add_parser('juger-lots'); x.add_argument('plan')
    x.add_argument('--paralleles', type=int, default=TETE_PARALLELES)
    x = sp.add_parser('apercu'); x.add_argument('plan')
    x = sp.add_parser('ecrire'); x.add_argument('plan'); x.add_argument('--pm', required=True)
    x.add_argument('--decisions-seules', action='store_true')
    x = sp.add_parser('formulaires'); x.add_argument('plan'); x.add_argument('--studio')
    x = sp.add_parser('repondre'); x.add_argument('plan'); x.add_argument('--pm', required=True)
    x.add_argument('--reponses', required=True)
    x = sp.add_parser('ouverts'); x.add_argument('studio')
    x = sp.add_parser('trancher'); x.add_argument('studio'); x.add_argument('cas', help='C3, ou des mots de son titre')
    x.add_argument('choix')
    x.add_argument('--pm', required=True)
    x = sp.add_parser('rouvrir'); x.add_argument('studio'); x.add_argument('cas', help='C3, ou des mots de son titre')
    x = sp.add_parser('evidents'); x.add_argument('plan'); x.add_argument('--studio')
    x = sp.add_parser('valider'); x.add_argument('plan'); x.add_argument('--studio')
    x.add_argument('--pm', required=True)
    x.add_argument('--sortir', default='[]', help='JSON : les mots des titres que le PM sort de la liste')
    x.add_argument('--changer', default='[]', help='JSON : [{"quoi": "<mots du titre>", "choix": "<réponse>"}]')
    x.add_argument('--tous-sortir', action='store_true', help='« Les poser une par une »')
    x = sp.add_parser('passe'); x.add_argument('studio'); x.add_argument('--estimer', action='store_true')
    x = sp.add_parser('cloturer'); x.add_argument('plan')
    x = sp.add_parser('attente'); x.add_argument('studio')
    x = sp.add_parser('cacher')  # cases kept in the register, never shown as conflicts in the tab's journal
    x.add_argument('studio'); x.add_argument('cas', nargs='+', help='C4 C8 …')
    x.add_argument('--raison', required=True); x.add_argument('--pm', required=True)
    x = sp.add_parser('regler'); x.add_argument('studio'); x.add_argument('--cas', type=int)
    x.add_argument('--jours', type=int)
    x = sp.add_parser('reprendre'); x.add_argument('studio')
    x.add_argument('--dossier', help='un seul dossier rattrapage-AAAA-MM-JJ')
    x.add_argument('--entree', help="écrit ici ce que le sous-agent lit, en une fois")
    x.add_argument('--extraction', help='le JSON écrit par le sous-agent')
    x.add_argument('--sortie', help="aperçu et lignes du registre dans ce fichier ; rien n'est écrit dans le Studio")
    x.add_argument('--ecrire', action='store_true')
    x.add_argument('--pm')
    x.add_argument('--dernier-passage', help="JJ/MM/AAAA, ou « aucun » ; par défaut la date du dernier rattrapage")
    x.add_argument('--changer', default='[]', help='JSON : [{"quoi": "<mots du titre>", "choix": "<réponse>"}]')
    a = p.parse_args(argv)
    code = commande(a)
    if a.cmd in COPIENT:
        studio = studio_de_la_commande(a)
        if studio and est_un_studio(studio) and not registre.copier_dans_mon_studio(studio):
            print("L'onglet Conflits de Mon Studio suivra d'ici quelques minutes (copie du registre impossible pour "
                  "l'instant).")
    return code


# The commands that write the register, or what the PM has seen of it (vu.json, reglages.json): Mon Studio's tab
# follows them at once (registre.copier_dans_mon_studio). `reprendre` copies only when it writes (--ecrire).
COPIENT = {'ecrire', 'valider', 'repondre', 'trancher', 'rouvrir', 'cloturer', 'reprendre', 'regler', 'formulaires',
           'evidents', 'attente', 'ouverts', 'cacher'}


def studio_de_la_commande(a):
    if a.cmd == 'reprendre' and not a.ecrire:
        return None
    if getattr(a, 'studio', None):
        return a.studio
    try:
        return charger_plan(a.plan)['studio']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def commande(a):
    if a.cmd == 'cacher':
        try:
            ajoutes = registre.mettre_hors_journal(a.studio, a.cas, a.raison, a.pm)
        except ValueError as e:
            print(str(e))
            return 1
        print(f"Hors du journal de l'onglet : {', '.join(ajoutes) or 'rien de nouveau'}. Le registre est inchangé.")
        return 0
    if a.cmd in ('estimer', 'releve'):
        if not (pathlib.Path(a.studio) / '.claude' / '.studio-manifest.json').exists():
            print(f"« {a.studio} » n'est pas un Studio (pas de .claude/.studio-manifest.json).")
            return 2
        plan = releve(a.studio, a.dossier, a.incremental)
        if a.cmd == 'estimer' and a.preparer:
            print(texte_preparer(plan['cout']))
            return 0
        if a.cmd == 'estimer':
            print(texte_cout(plan['cout'], dossiers_de_premier_niveau(plan['studio'])))
            ligne = cout_des_tickets(plan)
            if ligne:
                print(ligne)
            return 0
        sortie = pathlib.Path(a.sortie) if a.sortie else chemin_plan_defaut(plan['studio'])
        sauver_plan(sortie, plan)
        print(f"Plan : {sortie}")
        print(f"{len(plan['sujets'])} sujet(s), {plan['cout']['lots']} lot(s) de {LOT} sujets au plus "
              f"({plan['mode']}{', depuis le ' + plan['depuis'] if plan['depuis'] else ''}). Rien n'est écrit dans le Studio"
              + (' hors de ce plan.' if not a.sortie else '.'))
        print(texte_cout(plan['cout'], dossiers_de_premier_niveau(plan['studio'])))
        return 0
    if a.cmd == 'lot':
        texte = texte_lot(charger_plan(a.plan), a.k)
        if a.sortie:
            ecrire_texte(a.sortie, texte + '\n')
            print(f"Lot {a.k} écrit dans {a.sortie} ({len(texte) // 1000} Ko) : lis-le en une fois.")
        else:
            print(texte)
        print(f"\nRéponse attendue dans : {chemin_jugements(a.plan, a.k)}")
        return 0
    if a.cmd == 'juger':
        texte, erreurs = juger_le_plan(a.plan, a.jugements)
        print(texte)
        for e in erreurs:
            print(f"Jugement écarté : {e}")
        return 0
    if a.cmd == 'juger-lots':
        r = juger_les_lots(a.plan, a.paralleles)
        if r['mode'] == 'sous-agents':
            print("Pas de `claude` en ligne de commande ici : les lots se jugent par sous-agents (repli), lots "
                  + ', '.join(map(str, r['a_refaire'])) + '.')
            return 3
        t = r['tokens']
        if r['resultats']:
            nb = lambda n: f'{n:,}'.replace(',', ' ')
            print(f"{len(r['faits'])} lot(s) jugé(s) sur {len(r['resultats'])} lancé(s) ({r['lots']} au plan), Sonnet sans "
                  f"outil : {fr(float(r['usd']))} $ réels ({nb(t['entree'] + t['cache_ecrit'] + t['cache_lu'])} tokens lus, "
                  f"{nb(t['sortie'])} écrits).")
        for x in r['resultats']:
            if not x['ok']:
                print(f"Lot {x['lot']} : {len(x['manquants'])} sujet(s) sans jugement ({'; '.join(x['erreurs'])[:300]}).")
        if r['a_refaire']:
            print("À juger par sous-agents (repli, « Brief d'un sous-agent »), lots "
                  + ', '.join(map(str, r['a_refaire'])) + f", puis : conflits.py juger {a.plan}")
            return 3
        texte, erreurs = juger_le_plan(a.plan)
        print(texte)
        for e in erreurs:
            print(f"Jugement écarté : {e}")
        return 0
    if a.cmd == 'apercu':
        print(apercu(charger_plan(a.plan)))
        return 0
    if a.cmd == 'ecrire':
        plan = charger_plan(a.plan)
        r = ecrire(plan, a.pm, a.decisions_seules)
        sauver_plan(a.plan, plan)
        if plan.get('ecrit'):
            oublier_pret(plan['studio'], a.plan, tout=plan.get('dernier_passage_pose'))
        m = r['marquages']
        print(f"{m['pose']} marquages posés dans {r['fichiers']} fichiers, {m['deja']} déjà là, {r['ajouts']} ajouts, "
              f"{r['decisions']} décisions au registre.")
        if r['devenus_decisions']:
            print(f"Passages qui ont bougé, devenus décisions du PM : {len(r['devenus_decisions'])}.")
        if r['recap']:
            print('Récapitulatif :')
            for x in r['recap']:
                print(f'- {x}')
        # Not an end (PM, 2026-11-18: « il n'aurait pas fallu que j'ai à te le demander ») : the session goes on at once.
        if r['evidents'] or r['arbitrages']:
            print(f"Suite, tout de suite, sans attendre que le PM le demande : {r['evidents']} cas évidents à valider d'un coup, "
                  f"puis {r['arbitrages']} vraies décisions une par une. On enchaîne (usage 3).")
        else:
            print("Aucune décision n'attend le PM.")
        return 0
    if a.cmd == 'formulaires':
        if not os.path.exists(a.plan):
            if not a.studio:
                print(f"Plan introuvable : {a.plan}. Pour les seuls cas du registre : --studio <studio>.")
                return 2
            plan = plan_vide(a.studio)
        else:
            plan = charger_plan(a.plan)
        fs = formulaires(plan)
        sauver_plan(a.plan, plan)
        noter_vu(plan['studio'])
        attendent = sum(1 for d in _restantes(plan) if est_evident(d))
        print(json.dumps({'formulaires': fs, 'ecrire_tous_les': ORDRE_ECRITURE, 'evidents_en_attente': attendent,
                          'libelle_garder': LIBELLE_GARDER}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == 'repondre':
        plan = charger_plan(a.plan)
        brut = a.reponses
        if os.path.exists(brut):
            with open(brut, encoding='utf-8') as f:
                brut = f.read()
        r = repondre(plan, json.loads(brut), a.pm)
        sauver_plan(a.plan, plan)
        print(r['point'] + '.')
        for x in r['details'] + r['erreurs']:
            print(x)
        return 0
    if a.cmd in ('evidents', 'valider'):
        if not os.path.exists(a.plan):
            if not a.studio:
                print(f"Plan introuvable : {a.plan}. Pour les seuls cas du registre : --studio <studio>.")
                return 2
            plan = plan_vide(a.studio)
        else:
            plan = charger_plan(a.plan)
        if a.cmd == 'evidents':
            r = evidents(plan)
            sauver_plan(a.plan, plan)
            noter_vu(plan['studio'])
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 0
        r = valider_evidents(plan, a.pm, json.loads(a.sortir), json.loads(a.changer), a.tous_sortir)
        sauver_plan(a.plan, plan)
        print(r['point'] + '.')
        if r.get('sortis'):
            print('Sortis de la liste, posés à part : ' + ' ; '.join(f'« {x} »' for x in r['sortis']) + '.')
        for x in r.get('details', []) + r['erreurs']:
            print(x)
        return 0 if not r['erreurs'] else 2
    if a.cmd == 'passe':
        if not est_un_studio(a.studio):
            print(f"« {a.studio} » n'est pas un Studio (pas de .claude/.studio-manifest.json).")
            return 2
        if a.estimer:
            plan = releve(a.studio, None, True)
            print(texte_cout_passe(estimer_passe(plan), plan.get('depuis')))
            return 0
        r = ouvrir_passe(a.studio)
        print(r['texte'])
        return 2 if r['etat'] == 'jamais' else 0
    if a.cmd == 'cloturer':
        print(cloturer(a.plan))
        return 0
    if a.cmd in ('attente', 'ouverts', 'regler', 'trancher', 'rouvrir') and not est_un_studio(a.studio):
        print(f"« {a.studio} » n'est pas un Studio (pas de .claude/.studio-manifest.json).")
        return 2
    if a.cmd == 'attente':
        r = attente(a.studio)
        noter_vu(a.studio)
        if r['pret']:
            print(texte_pret(r['pret']))
        for x in r['marquages_en_attente']:
            print(f"Passe du {registre.jjmmaaaa(x['date'])} : {x['marquages']} marquages sûrs et {x['ajouts']} ajouts "
                  "attendent ton go.")
        print(f"Cas évidents à valider d'un coup : {r['evidents']}. Vraies décisions, une par une : {r['arbitrages']}."
              + (f" Cas illisibles : {r['illisibles']}." if r['illisibles'] else ''))
        t = tickets_module().status(a.studio)['texte']
        if t:
            print('Tickets : ' + t)
        return 0
    if a.cmd == 'reprendre':
        return commande_reprendre(a)
    if a.cmd == 'regler':
        try:
            r = regler(a.studio, a.cas, a.jours)
        except ValueError as exc:
            print(str(exc))
            return 2
        print(f"Relance dans Mon Studio à partir de {r['relance_cas']} conflits non traités ou de {r['relance_jours']} "
              "jours sans traitement.")
        return 0
    if a.cmd == 'ouverts':
        noter_vu(a.studio)
        r = registre.ouverts(a.studio)
        if not r['ouverts'] and not r['illisibles']:
            print('Aucun conflit ouvert.')
        t = registre.titres_du_studio(a.studio)
        e = lambda x: pour_le_pm(x, t)
        for c in r['ouverts']:
            print(f"« {e(c['sujet'])} » : avant, {e(c['ancienne']['texte'])} ({registre.chemin_lisible(c['ancienne']['source'])}, "
                  f"{c['ancienne']['date']}) ; maintenant, {e(c['nouvelle']['texte'])} "
                  f"({registre.chemin_lisible(c['nouvelle']['source'])}, {c['nouvelle']['date']}) · déjà dit au client : "
                  f"{'oui' if c['communique'] else 'non'}")
        for c in r['illisibles']:
            print(f"Un conflit du registre ne se lit pas, ligne {c['ligne']} : « {e(c['sujet'])} » ({'; '.join(c['erreurs'])})")
        return 0
    if a.cmd in ('trancher', 'rouvrir'):
        tous = registre.lire_fichier(registre.chemin_du_studio(a.studio))['cas']
        cherches = [c for c in tous if (c['etat'] == 'ouvert') == (a.cmd == 'trancher')] or tous
        trouves = trouver_cas(cherches, a.cas)
        if len(trouves) != 1:
            t = registre.titres_du_studio(a.studio)
            if not trouves:
                print(f"Aucun conflit ne répond à « {pour_le_pm(a.cas, t)} ».")
            else:
                print("Plusieurs conflits répondent : " + ' ; '.join(f"« {pour_le_pm(c['sujet'], t)} »" for c in trouves)
                      + '. Lequel ?')
            return 2
        cas = trouves[0]
    if a.cmd == 'trancher':
        choix = choix_du_libelle(a.choix) or (a.choix if a.choix in registre.CHOIX else None)
        if not choix:
            print(f"Choix inconnu : {a.choix} (remplacer, à confirmer avec le client, {LIBELLE_GARDER.lower()}).")
            return 2
        for chemin in plans_du_studio(a.studio):
            plan = charger_plan(chemin)
            if any(d.get('cas') == cas['id'] for d in plan['decisions']):
                r = repondre(plan, [{'cas': cas['id'], 'choix': choix}], a.pm)
                sauver_plan(chemin, plan)
                print(r['point'] + '.')
                for x in r['details'] + r['erreurs']:
                    print(x)
                return 0
        # A case no plan holds (written by the ingestion): the same effect, its passages found again by the relevé.
        plan = plan_vide(a.studio)
        plan['decisions'].append(decision_du_registre(plan, cas))
        r = repondre(plan, [{'cas': cas['id'], 'choix': choix}], a.pm)
        print(r['point'] + '.')
        for x in r['details'] + r['erreurs']:
            print(x)
        return 0
    if a.cmd == 'rouvrir':
        registre.changer_etat(registre.chemin_du_studio(a.studio), cas['id'])
        journal(a.studio, f"Conflit {cas['id']} · {cas['sujet']} : rouvert")
        for chemin in plans_du_studio(a.studio):
            plan = charger_plan(chemin)
            for d in plan['decisions']:
                if d.get('cas') == cas['id']:
                    d['reponse'], d['ecrit'] = None, False
                    sauver_plan(chemin, plan)
        print(f"« {pour_le_pm(cas['sujet'], registre.titres_du_studio(a.studio))} » : rouvert.")
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
