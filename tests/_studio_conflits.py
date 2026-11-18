"""A synthetic Studio for the conflicts tests: neutral, invented content (no client, no real ticket)."""
import os
import pathlib

import _isolation

DECISIONS = """# Journal des décisions

### 2026-10-20 : Comité de pilotage le jeudi

- **Statut :** actif
- **Décision :** le comité de pilotage se tient le jeudi, à partir de décembre.
- **Source :** `sources/2026-10-20-mail-atelier.md`
- **Remplace :** 2026-09-02 — Comité de pilotage le premier mardi

### 2026-10-25 : Export des commandes en format tableur

- **Statut :** actif
- **Décision :** les commandes du mois sont exportées chaque lundi dans un fichier tableur partagé avec la comptabilité.
- **Source :** `sources/2026-10-25-cr-point.md`

### 2026-09-02 : Comité de pilotage le premier mardi

- **Statut :** superseded
- **Remplacé par :** 2026-10-20 — Comité de pilotage le jeudi
- **Décision :** le comité de pilotage se tient le premier mardi du mois.
- **Source :** atelier de cadrage
"""

REGLES = """# Règles métier

### PRJ-1 : Plafond de remise

- **Statut :** superseded
- **Remplacée par :** PRJ-2
- **Règle :** remise limitée à 10 % des commandes.
- **Date :** 2026-09-15

### PRJ-2 : Remise relevée pour les grosses commandes

- **Statut :** actif
- **Règle :** remise portée à 15 % des commandes de plus de 50 pièces.
- **Source :** `sources/2026-11-03-cr-point.md`
- **Date :** 2026-11-03
"""

QUESTIONS = """# Questions ouvertes

### 2026-10-10 : Sous quel format exporter les commandes du mois pour la comptabilité ?

- **Contexte :** la comptabilité veut recevoir les commandes du mois chaque semaine ; le format de fichier reste à choisir.
"""

CDC = """# Cahier des charges

## Gouvernance

Le comité de pilotage se tient le premier mardi du mois, en visio.

## Remises

| Cas | Règle |
|---|---|
| Standard | La remise est limitée à 10 % des commandes. |
| Export | Aucune |
"""

PERIMETRE = """# Périmètre

- La remise est limitée à 10 % des commandes passées en ligne.
- Le catalogue compte trois gammes.
"""

ROADMAP = "# Roadmap\n\nLe comité de pilotage du premier mardi du mois valide chaque lot.\n"


def make(folder):
    s = pathlib.Path(folder)
    _isolation.make_studio(s)
    files = {'projet/decisions-log.md': DECISIONS, 'projet/regles-metier.md': REGLES,
             'projet/questions-ouvertes.md': QUESTIONS, 'projet/changelog.md':
             '# Historique des changements projet\n\n| Date | Changement | Source |\n|------|-----------|--------|\n',
             '0-commerce/cahier-des-charges.md': CDC, '2-cadrage/perimetre.md': PERIMETRE,
             '2-cadrage/roadmap.md': ROADMAP,
             'sources/2026-10-20-mail-atelier.md': 'Le comité passe au jeudi à partir de décembre.\n',
             'sources/2026-11-03-cr-point.md': 'Remise portée à 15 % au-delà de 50 pièces.\n'}
    for rel, text in files.items():
        p = s / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return s


def snapshot(folder):
    """Every file's bytes, by relative path (hidden plan folder excluded)."""
    out = {}
    for root, dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, folder)
            if rel.startswith(os.path.join('projet', '.conflits')):
                continue
            with open(p, 'rb') as h:
                out[rel] = h.read()
    return out


# The formats seen on real Studios (2026-11-10), with invented content: entries under `##` with an em dash, the status
# in back ticks, a replacement written in a bullet, an update on an entry still active, one-line rule bullets in a
# sub-folder store, a struck and ticked question, a value waiting for a decision.
DECISIONS_REELLES = """# Journal des décisions

> **Statuts :** `actif`, `superseded` (remplacée par une décision plus récente), `obsolète`.

## PRJ-1 — Hébergement chez le client

- **Statut** : `superseded`
- 🔴 **Remplacée le 2026-11-04** par **PRJ-7** et **PRJ-9** (hébergement mutualisé chez l'agence). Source : arbitrage PM.
- **Décision** : la plateforme est hébergée sur un serveur autonome chez le client.

## PRJ-2 — Application mobile native

- **Statut** : `actif`
- **Décision** : une application native Android et iOS pour les opérateurs.
- ➡️ **MAJ 2026-11-04** — La partie « Android et iOS » est remplacée par **PRJ-8** : web responsive, pas d'application native.

## PRJ-7 — Hébergement mutualisé

- **Statut** : `actif`
- **Décision** : hébergement mutualisé chez l'agence, en France.

## PRJ-9 — Version minimale du poste

- **Statut** : `actif`
- **Décision** : le poste local tourne sous Windows 10 et 11 ; les versions antérieures sont hors cible.
"""

REGLES_PUCES = """# Règles métier : produit B

## Score

- **PRJ-40** Le score affiche trois tranches 0-50, 50-75 et 75-100. ⚠️ *Superseded le 2026-10-15 par PRJ-41.*
- **PRJ-41** Le score affiche trois tranches 0-49, 50-74 et 75-100 (atelier du 2026-10-15).
"""

QUESTIONS_REELLES = """# Questions ouvertes

## ~~PRJ-60~~ — Quel hébergeur retenir ? — 🟢 Résolue (2026-11-04)

- **Réponse** : hébergement mutualisé chez l'agence (PRJ-7).

### PRJ-61 : ❓ Faut-il un mode hors ligne ?

- **Contexte** : à trancher avec l'équipe technique.
"""

STACK_REELLE = """# Stack

- Postes : jusqu'à Windows XP. Version minimale à fixer par l'équipe technique.
- Hébergement : serveur autonome chez le client (PRJ-1).
- Applications : Android et iOS natives pour les opérateurs.

| Sujet | Valeur |
|---|---|
| Hébergeur | Serveur autonome chez le client ⚠️ Remplacé le 2026-11-04 par PRJ-7, source `projet/decisions-log.md`. Rattrapage du 2026-11-10. |
"""

STORY_JSON = '{\n  "cartes": [\n    {"titre": "Héberger chez le client", "note": "PRJ-1 : serveur autonome"}\n  ]\n}\n'


def make_reel(folder):
    s = pathlib.Path(folder)
    _isolation.make_studio(s)
    files = {'projet/decisions-log.md': DECISIONS_REELLES, 'projet/produit-b/regles-metier.md': REGLES_PUCES,
             'projet/questions-ouvertes.md': QUESTIONS_REELLES, 'projet/technique/stack.md': STACK_REELLE,
             '2-cadrage/produit-b/story-mapping.md': '| Carte | Note |\n|---|---|\n| Voir son score | Tranches 0-50 / 50-75 / 75-100 (PRJ-40) |\n',
             '2-cadrage/story-mapping.json': STORY_JSON,
             'projet/pilotage/journal-kit.md': 'Hébergement : serveur autonome chez le client (PRJ-1).\n',
             'projet/rattrapage-2026-11-10/apercu.md': 'Hébergement : serveur autonome chez le client (PRJ-1).\n'}
    for rel, text in files.items():
        p = s / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return s
