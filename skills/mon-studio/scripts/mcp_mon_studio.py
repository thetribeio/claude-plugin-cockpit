#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Connecteur local « mon-studio » : le tableau de Mon Studio pour une page publiée ouverte dans l'app Claude.

Serveur MCP minimal (stdio, JSON-RPC une ligne par message, sans dépendance). La page épinglée l'appelle
comme serveur hôte (`host:mon-studio`) : elle parle au serveur, jamais à Claude, donc rien ne coûte de
tokens. Les outils :

    lignes         le tableau calculé par parc.py, avec les conflits de chaque Studio (champ `conflits` : ses cas ouverts,
                   ses nouveaux non lus, sa relance, la session qui les traite ; null si leur lecture échoue), les fils rouges de chaque Studio et la liste par projet de
                   projets.py (champ `liste_projets`) et le point du matin de matin.py (champ `matin`), chacun null si son calcul échoue (lecture seule, annoté comme tel : l'app ne
                   demande rien)
    projet         la vue d'un seul projet (parc.vue_projet_pour_la_page), plus `conflits` : les cas ouverts du registre
                   des conflits du Studio et la session « <Projet> · Conflits Studio » (projets.conflits_du_projet), null
                   si leur lecture échoue (lecture seule)
    ouvrir         ouvre une session dans l'app (`open claude://…`) ; pas en lecture seule (il lance `open` et peut
                   écrire le presse-papiers) ; avec `copier`, met d'abord
                   le numéro de la question (« Q10 »), ou une réponse fermée (« Q10 go »), dans le presse-papiers, à coller.
                   Avec `dossier` et `fichier` au lieu de `id`, ouvre un document d'un Studio connu de ce Mac dans son
                   application (`open`), pour le bouton « Fichier » du point du matin : extensions de documents
                   seulement (EXTENSIONS_DOCUMENT), jamais un lien symbolique qui sort du Studio
    autorisations  les demandes d'autorisation en attente que le hook PermissionRequest (hooks/autorisation.py) a
                   confiées au connecteur, et les cinq dernières décisions (lecture seule)
    decider        autorise cette fois, ou refuse, une de ces demandes : libère le hook qui l'attend (pas en lecture
                   seule). Seul un clic du PM sur la page l'appelle.
    attentes       les sessions qui attendent la réponse du PM à la question numérotée qu'elles viennent de poser,
                   confiées par le hook Stop (hooks/reponse_directe.py), avec leurs réponses fermées (lecture seule)
    repondre       donne une de ces réponses fermées (« go », « oui », « pas encore », « 1 »…) à la session qui attend : libère le
                   hook, et la session reprend avec ce mot (pas en lecture seule). Sans `id`, avec `session` et `question` :
                   la session n'attend pas sur la page ; si son tour est fini, elle reprend avec la réponse par le
                   Claude du Terminal (son processus au repos est d'abord arrêté) ; en plein tour, la réponse attend dans
                   ~/Mon Studio/.parc/reponses-en-file/ la fin du tour (24 h au plus).
                   Seul un clic du PM sur la page l'appelle.
    lire           le texte d'un fichier d'un Studio connu de ce Mac (md, txt, csv seulement, 200 Ko au plus, tronqué
                   au-delà), pour « Lire » de « Ce qui est entré au Studio » : mêmes règles que `ouvrir` avec un fichier
                   (chemin relatif sans `..`, liens résolus dans le Studio), lu par le calcul hors de l'app quand le Drive
                   refuse la lecture au connecteur (lecture seule)
    clore          ferme à la main une ligne de la liste par projet (« Fait / plus d'actu » au tableau, « Fait » dans
                   Today), par sa clé : ce qu'aucune source ne voit ; avec `matin: true`, marque « Fait », pour de bon,
                   un élément « à traiter » ou « préparer demain » du point du matin, ou un brouillon pas envoyé (pas en
                   lecture seule). Seul un clic du PM sur la page l'appelle.
    matin_ecrire   pour les deux tâches planifiées du point du matin : remplace ~/Mon Studio/matin.json par l'objet
                   `contenu`, après la vérification de `matin.py ecrire` (objet JSON, `genere_le` lisible), et rien
                   d'autre (pas en lecture seule). Autorisé par la règle `mcp__mon-studio__matin_ecrire`, que seul
                   `install.py apply --autorisations` pose, après le go du PM (2026-11-10).
    conflits_juger pour la tâche du point du matin, le lundi : les jugements de la passe des conflits d'un Studio
                   (`plan`, donné par `matin.py preparer`), inscrits au registre du Studio par `conflits.py`
                   (`cloturer`) ; rien n'est marqué dans les documents (pas en lecture seule). Seulement un plan de
                   passe, d'un Studio de projets.json, pas encore jugé. Autorisé par la règle
                   `mcp__mon-studio__conflits_juger`, posée de même (PM, Q18, 2026-11-15).

`decider`, `repondre` et `clore` sont faits pour la page : leur description dit à une session de ne pas les appeler,
rien ne l'en empêche. Le protocole n'identifie pas l'appelant. Seule une instance lancée avec CLAUDE_PROJECT_DIR posé
limite `lire` et `ouvrir` d'un fichier au Studio de ce dossier et refuse `decider` et `repondre` ; les instances que
l'app lance, celles que la page et les sessions de l'app appellent, ne portent pas cette variable : ce garde-fou ne
s'y applique pas.

Les demandes arrivent par une socket Unix locale, une par instance de ce serveur :
~/Mon Studio/.parc/autorisations-<pid>.sock (dossier en 700, socket en 600), tenue par un fil. L'app de bureau lance
deux instances, une par client (« claude-ai » et « local-agent-mode ») ; le hook envoie la même demande à toutes, et
chacune la montre à la page de son client. La première qui reçoit `decider` répond au hook, qui ferme alors les
autres connexions : la demande quitte aussi les autres instances. Au démarrage, une instance retire les sockets
mortes (connexion refusée, ou pid disparu) et l'ancienne autorisations.sock si elle est morte ; elle retire la sienne
en s'arrêtant. Les demandes restent en mémoire, 30 minutes au plus, jamais sur le disque ; chaque décision ajoute
une ligne JSON à ~/Mon Studio/.parc/autorisations.log, écrite par la seule instance qui a reçu `decider`. Si le
serveur s'arrête, ses connexions se ferment ; quand plus aucune ne reste, le hook sort et la fenêtre normale de l'app
reste. Sous Windows, rien de tout cela ne tourne.

Les mêmes sockets reçoivent aussi les attentes du hook Stop (`type: "attente"`), gardées en mémoire
de la même façon, jusqu'à la limite que le hook donne (30 minutes au plus). Une attente ne prend qu'une réponse de sa
liste fermée `choix` : aucun texte libre. Chaque réponse ajoute une ligne JSON à
~/Mon Studio/.parc/reponses-directes.log (date, numéro, choix, session). Interrupteur : `reponses_directes`.

Lancé par l'app depuis la copie hors du Drive (~/Mon Studio/.parc/), à côté de parc.py et projets.py qu'il importe.
Chaque appel est noté dans ~/Mon Studio/.parc/connecteur.log (outil, client, durée), jamais son contenu.
"""
import atexit
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import os
import re
import secrets
import select
import signal
import socket
import subprocess
import sys
import threading
import time

ICI = pathlib.Path(__file__).resolve().parent
VERSION = '0.9'
CLIENT = {}
_charge = {'mtime': None}
_charge_projets = {'mtime': None, 'module': None}


def charger_parc():
    """parc.py, rechargé quand install.py en pose une nouvelle copie : l'app garde ce serveur allumé tant
    qu'elle tourne, une mise à jour du calcul ne doit pas demander de la relancer."""
    global parc
    mtime = (ICI / 'parc.py').stat().st_mtime
    if mtime != _charge['mtime']:
        spec = importlib.util.spec_from_file_location('parc', ICI / 'parc.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parc, _charge['mtime'] = module, mtime
    return parc


parc = charger_parc()


def charger_projets():
    """projets.py, rechargé comme parc.py quand sa copie change ; il calcule avec le parc du connecteur."""
    mtime = (ICI / 'projets.py').stat().st_mtime
    if mtime != _charge_projets['mtime']:
        spec = importlib.util.spec_from_file_location('projets', ICI / 'projets.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _charge_projets.update(mtime=mtime, module=module)
    module = _charge_projets['module']
    module.parc = parc
    return module
JOURNAL = parc.INTERNE / 'connecteur.log'

# What « ouvrir » may put in the clipboard: a question number (« Q10 »), or a closed answer to it (« Q10 go », « Q10 pas
# encore », « Q10 ok », « Q10 2 ») when the session does not wait on the page. Never free text.
# A question without a number, or a chantier line whose number is the foreman's: the answer
# alone (« go », « pas encore », « 1 », or an option's label, 80 characters at most, one line).
# Same characters as parc.LIBELLE_PERMIS (written for JavaScript too: no \\w, which is ASCII only there).
LETTRES = 'A-Za-z0-9À-ÖØ-öø-ÿŒœ'
LIBELLE_MOTIF = "(?!Q\\d)[" + LETTRES + "](?:[" + LETTRES + "’'«»,.:()/+?!%€-]| (?! )){0,79}"
# « Recommandé » (PM, 2026-11-10): the answer the question recommends in its own words, « Q44 recommandé : … ».
RECOMMANDE_MOTIF = 'recommandé : ' + LIBELLE_MOTIF
# « /cockpit:conflits rattrapage »: the first check of a Studio, pasted in its most recent session (PM, Q14, 2026-11-15);
# « /cockpit:conflits préparer »: its preview prepared on demand, validated later (PM, Q18, 2026-11-15).
COPIE_MOTIF = (r'^(?:Q\d{1,4}(?: (?:go|oui|pas encore|ok|[1-9]\d?|' + RECOMMANDE_MOTIF + '))?|' + LIBELLE_MOTIF
               + r'|/cockpit:conflits (?:rattrapage|préparer)|/cockpit:mon-studio (?:point du matin|terminal))$')

OUTILS = [
    {'name': 'lignes',
     'description': "Le tableau de Mon Studio : une ligne par question ou action qui attend le PM, dans tous ses "
                    "Studios et ses chantiers, plus la liste des tableaux de chantier et la liste par projet. Lecture seule, sans LLM.",
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'Tableau de Mon Studio', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'projet',
     'description': "La vue d'un seul projet (clé : un dossier, champ « dossier » d'un projet de « lignes ») : ses "
                    "questions et actions, ses sujets (session pilier et sessions filles, état = dernier compte rendu de "
                    "fin de tour), ses attentes de tiers, son journal et les cas ouverts de son registre des conflits "
                    "(projet/conflits.md) avec la session « <Projet> · Conflits Studio ». Jamais deux projets mêlés. "
                    "Lecture seule, sans LLM.",
     'inputSchema': {'type': 'object', 'properties': {'dossier': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
                     'required': ['dossier'], 'additionalProperties': False},
     'annotations': {'title': "Vue d'un projet", 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'ouvrir',
     'description': "Ouvre une session dans l'app Claude (identifiant local_…). Avec « copier », met d'abord le "
                    "numéro de la question (Q10), ou une réponse fermée (« Q10 go », « Q10 1 »), dans le presse-papiers ; "
                    "sans « id », seulement la commande d'une étape de la mise en route, copiée. "
                    "Avec « dossier » (un Studio de ce Mac) et « fichier » (un chemin relatif à ce Studio) au lieu de "
                    "« id », ouvre ce document (md, pdf, docx, xlsx, image…) dans son application ; tout autre type est refusé. "
                    "Ne modifie rien d'autre.",
     'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'string', 'pattern': r'^local_[0-9a-f-]{36}$'},
                                                      'copier': {'type': 'string', 'pattern': COPIE_MOTIF},
                                                      'dossier': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
                                                      'fichier': {'type': 'string', 'minLength': 1, 'maxLength': 500}},
                     'additionalProperties': False},
     'annotations': {'title': 'Ouvrir une session', 'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                     'openWorldHint': False}},
    {'name': 'autorisations',
     'description': "Les demandes d'autorisation d'outil en attente dans les sessions, confiées par le hook de Mon "
                    "Studio quand l'interrupteur est allumé, et les cinq dernières décisions. Lecture seule.",
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'Autorisations en attente', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'decider',
     'description': "Autorise cette fois (allow) ou refuse (deny) une demande d'autorisation en attente, par son "
                    "identifiant : la session reçoit la réponse pour cet appel seulement, sans règle permanente. "
                    "Réservé à la page : appelé sur un clic du PM, jamais par une session.",
     'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'string', 'pattern': r'^[0-9a-f]{32}$'},
                                                      'decision': {'type': 'string', 'enum': ['allow', 'deny']}},
                     'required': ['id', 'decision'], 'additionalProperties': False},
     'annotations': {'title': "Répondre à une autorisation", 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': False}},
    {'name': 'attentes',
     'description': "Les sessions qui attendent la réponse du PM à la question numérotée qu'elles viennent de poser, "
                    "confiées par le hook de Mon Studio quand l'interrupteur est allumé, avec leurs réponses possibles. "
                    "Lecture seule.",
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'Réponses attendues', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'repondre',
     'description': "Donne à une session une des réponses de sa liste fermée (go, oui, pas encore, 1, 2…, ou le libellé d'une option). "
                    "Avec « id » : la session attend sur la page, elle reprend aussitôt avec ce mot. Avec « session » et "
                    "« question » (Q11, ou vide pour une question sans numéro) : la session ne l'attend pas ; son tour fini, "
                    "elle reprend avec cette réponse ; en plein tour, la réponse lui est donnée dès la fin du tour "
                    "(24 h au plus). Rend « mode » : directe, reveil, file, ou copie (à copier dans la session). "
                    "Aucun texte libre. Réservé à la page : appelé sur un clic du PM, jamais par une session.",
     'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'string', 'pattern': r'^[0-9a-f]{32}$'},
                                                      'session': {'type': 'string', 'pattern': r'^local_[0-9a-f-]{36}$'},
                                                      'question': {'type': 'string', 'pattern': r'^(?:Q\d{1,4})?$'},
                                                      'choix': {'type': 'string', 'maxLength': 80}},
                     'required': ['choix'], 'additionalProperties': False},
     'annotations': {'title': 'Répondre à une question', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': False}},
    {'name': 'lire',
     'description': "Le texte d'un fichier d'un Studio de ce Mac (« dossier », et « fichier » relatif à ce Studio) : md, "
                    "txt ou csv seulement, 200 Ko au plus (tronqué au-delà, champ « tronque »). Tout autre type, un chemin "
                    "qui sort du Studio ou un Studio inconnu est refusé. Lecture seule, ne modifie rien.",
     'inputSchema': {'type': 'object', 'properties': {'dossier': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
                                                      'fichier': {'type': 'string', 'minLength': 1, 'maxLength': 500}},
                     'required': ['dossier', 'fichier'], 'additionalProperties': False},
     'annotations': {'title': 'Lire un fichier du Studio', 'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'clore',
     'description': "Ferme à la main une ligne de la liste par projet (« Fait »), par sa clé : pour ce "
                    "qu'aucune source ne voit, un coup de fil par exemple. Une clé « r… » retire du tableau une ligne "
                    "de session (« Fait / Retirer du tableau ») ; la session en est avertie à son tour suivant. "
                    "Avec « matin », marque fait, pour de bon, un "
                    "élément « à traiter » ou « préparer demain » du point du matin, ou un brouillon pas envoyé. Avec une "
                    "clé « etape-… », écarte une étape de la mise en route (« Pas pour moi »). Une clé « t… » "
                    "marque reçue une attente de tiers (« Reçu »). Avec « plus_tard », masque la ligne jusqu'à demain, "
                    "sur le tableau seulement, sans rien envoyer à la session. Avec « abandon » (clé « r… » d'une "
                    "session arrêtée), retire la ligne et propose la session à l'archivage. Avec « reclasser » (dabord, "
                    "ensuite, annuler), ne ferme rien : met la ligne dans « D'abord » ou hors de « D'abord » au tableau, "
                    "ou annule, quand l'interrupteur « reclassement » est allumé. Réservé "
                    "à la page : appelé sur un clic du PM, jamais par une session.",
     'inputSchema': {'type': 'object', 'properties': {'cle': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                                                      'matin': {'type': 'boolean'}, 'plus_tard': {'type': 'boolean'},
                                                      'abandon': {'type': 'boolean'},
                                                      'reclasser': {'type': 'string', 'enum': ['dabord', 'ensuite', 'annuler']}},
                     'required': ['cle'], 'additionalProperties': False},
     'annotations': {'title': 'Fermer une ligne de projet', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': False}},
    {'name': 'gabarit',
     'description': "Le code de la page Mon Studio de la version installée (styles, gabarit, script), que la page "
                    "épinglée exécute à chaque ouverture : une mise à jour du plugin ne la republie donc pas. Lu dans "
                    "~/Mon Studio/.parc (copie posée par l'installation) ou dans le dossier du plugin. Lecture seule, sans LLM.",
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'Code de la page', 'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'matin_ecrire',
     'description': "Écrit le point du matin du PM : « contenu » est l'objet JSON complet, avec un « genere_le » lisible. "
                    "Il remplace ~/Mon Studio/matin.json, et rien d'autre ; refusé, l'ancien fichier reste. Réservé aux "
                    "deux tâches planifiées du point du matin.",
     'inputSchema': {'type': 'object', 'properties': {'contenu': {'type': 'object'}},
                     'required': ['contenu'], 'additionalProperties': False},
     'annotations': {'title': 'Écrire le point du matin', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'conflits_juger',
     'description': "Inscrit au registre des conflits d'un Studio les jugements de sa passe du lundi : « plan » est le "
                    "chemin donné par `matin.py preparer` (champ `conflits`), « jugements » la liste JSON, un objet par "
                    "sujet. Rien n'est marqué dans les documents. Réservé à la tâche planifiée du point du matin.",
     'inputSchema': {'type': 'object', 'properties': {'plan': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
                                                      'jugements': {'type': 'array', 'items': {'type': 'object'}}},
                     'required': ['plan', 'jugements'], 'additionalProperties': False},
     'annotations': {'title': 'Inscrire la passe des conflits', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': False}},    {'name': 'slack_ouvertes',
     'description': "Le nom du PM (`pm`) et ses demandes « À toi » de l'ingestion encore ouvertes qui pointent vers un message Slack (`lignes`) : clé, "
                    "projet, demande, lien, fil à lire (channel_id, message_ts du parent), heure de la demande, résumé "
                    "déjà écrit. Lecture seule. Pour la vérification du point du matin.",
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'Lignes Slack ouvertes', 'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': False}},
    {'name': 'slack_juger',
     'description': "Rend le jugement de la vérification sur des lignes Slack ouvertes, un objet par ligne : « cle », "
                    "« verdict » (« reglee » : le PM a répondu dans le fil après la demande ; « ouverte »), « resume » "
                    "(une phrase courte, jamais le message recopié), « qui » (l'auteur de la demande, « Toi » pour un "
                    "message du PM), « reponse » (lien Slack de la réponse du PM, requis pour « reglee »), « suite » "
                    "(facultatif : ce que la réponse annonce, en une phrase, qui devient une ligne). N'écrit que l'état "
                    "des lignes de Mon Studio. Réservé à la tâche planifiée de vérification du point du matin.",
     'inputSchema': {'type': 'object', 'properties': {'jugements': {'type': 'array', 'maxItems': 200, 'items': {'type': 'object'}}},
                     'required': ['jugements'], 'additionalProperties': False},
     'annotations': {'title': 'Fermer les lignes Slack réglées', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': False}},
]


# Served page code (option B, PM Q13, 2026-11-16): the pinned pages are a small shell that runs the code this tool
# returns, so a template change no longer republishes them. Read from the copy install.py puts next to the connector
# (~/Mon Studio/.parc), or from the plugin's assets when the connector runs from the plugin. Never from ~/Documents nor
# the Drive: the connector the app starts has no access there (macOS TCC, Q13).
GABARIT_FICHIER = 'page-servie.html'
_BLOC_STYLE = re.compile(r'<style>\n?(.*?)</style>\n?', re.S)
_BLOC_SCRIPT = re.compile(r'<script>\n?(.*?)</script>\n?', re.S)


def source_du_gabarit():
    for chemin in (ICI / GABARIT_FICHIER, ICI.parent / 'assets' / GABARIT_FICHIER):
        if chemin.is_file():
            return chemin
    return None


def version_installee():
    plugin = ICI.parent.parent.parent / '.claude-plugin' / 'plugin.json'
    for chemin, cle in ((plugin, 'version'), (ICI / 'cockpit.json', 'version')):
        try:
            v = json.loads(chemin.read_text(encoding='utf-8')).get(cle)
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(v, str) and v:
            return v
    return ''


def decouper_gabarit(texte):
    """{css, html, js}: the <style> blocks, the markup left, the <script> blocks, in their order."""
    css = '\n'.join(m.group(1) for m in _BLOC_STYLE.finditer(texte))
    js = '\n'.join(m.group(1) for m in _BLOC_SCRIPT.finditer(texte))
    html = _BLOC_SCRIPT.sub('', _BLOC_STYLE.sub('', texte)).strip()
    return {'css': css, 'html': html, 'js': js}


def gabarit():
    chemin = source_du_gabarit()
    if not chemin:
        raise RuntimeError(f"code de la page absent ({ICI / GABARIT_FICHIER}) : relancer l'installation de Mon Studio")
    texte = chemin.read_text(encoding='utf-8')
    return dict(decouper_gabarit(texte), version=version_installee(),
                empreinte=hashlib.sha256(texte.encode('utf-8')).hexdigest()[:12])


def matin_ecrire(arguments):
    """The morning tasks give the whole point here, never through a file tool nor a shell heredoc (2026-11-10: a file
    outside the task's folder and a JSON in a heredoc each wait on a prompt nobody answers). Same check as
    `matin.py ecrire`; only ~/Mon Studio/matin.json is written."""
    contenu = (arguments or {}).get('contenu')
    if not isinstance(contenu, dict):
        raise ValueError("« contenu » doit être l'objet JSON du point du matin")
    ok, texte = charger_projets()._charger_matin().ecrire(json.dumps(contenu, ensure_ascii=False))
    if not ok:
        raise ValueError(f'Refusé : {texte}.')
    return {'ecrit': True, 'compte_rendu': texte}


def conflits_juger(arguments):
    """The Monday pass of one Studio, judged by the morning task (PM, Q18, 2026-11-15): only a pass plan
    (`projet/.conflits/passe-<date>.json`) of a Studio listed in projets.json, not judged yet. `conflits.py cloturer`
    writes the decisions to the register; nothing is marked in the documents."""
    arguments = arguments or {}
    chemin, jugements = arguments.get('plan'), arguments.get('jugements')
    if not isinstance(chemin, str) or not isinstance(jugements, list):
        raise ValueError("« plan » (chemin) et « jugements » (liste) sont requis")
    p = charger_projets()
    c = p._charger_releve()
    if c is None:
        raise ValueError('Refusé : conflits.py introuvable.')
    plan_chemin = pathlib.Path(chemin).expanduser().resolve()
    studio = plan_chemin.parent.parent.parent
    studios = {str(pathlib.Path(s['dossier']).expanduser().resolve()) for s in (p.parc.lire_json(
        p.parc.SORTIE / 'projets.json', {}) or {}).get('studios') or [] if isinstance(s, dict) and isinstance(s.get('dossier'), str)}
    if not (c.nom_du_plan_de_passe(plan_chemin) and plan_chemin.parent.name == '.conflits'
            and plan_chemin.parent.parent.name == 'projet' and str(studio) in studios and c.est_un_studio(studio)
            and plan_chemin.is_file()):
        raise ValueError("Refusé : ce n'est pas un plan de passe d'un Studio de Mon Studio.")
    plan = c.charger_plan(str(plan_chemin))
    if plan.get('mode') != 'passe' or pathlib.Path(plan.get('studio') or '').expanduser().resolve() != studio:
        raise ValueError("Refusé : ce plan n'est pas une passe de ce Studio.")
    if plan.get('jugements'):
        raise ValueError('Refusé : cette passe est déjà jugée.')
    return {'inscrit': True, 'compte_rendu': c.cloturer(str(plan_chemin), jugements)}


def noter(texte):
    try:
        with JOURNAL.open('a', encoding='utf-8') as f:
            f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {texte}\n")
    except OSError:
        pass


def lignes():
    with CALCUL:
        return _lignes()


def _lignes():
    charger_parc()
    maintenant = time.time()
    cache = parc.charger_cache()
    e = parc.construire(int(parc.os.environ.get('MON_STUDIO_JOURS', 7)), 7, maintenant, cache)
    parc.ecrire_atomique(parc.INTERNE / 'cache.json', json.dumps(cache, ensure_ascii=False))
    # La liste par projet : un échec de son calcul ne coûte que son bloc, le tableau reste.
    try:
        projets = charger_projets().calculer(e=e, maintenant=maintenant, metas=parc.fiches(cache), depuis_connecteur=True)
    except Exception as exc:
        noter(f"projets · échec : {exc!r}")
        projets = None
    # Le point du matin : même règle, un échec de sa lecture ne coûte que son bloc. Sa partie ingestion (entrées, nouvelles
    # demandes) vient de la liste par projet qu'on vient de calculer, lue en direct.
    try:
        matin = charger_projets().matin_pour_la_page(maintenant, parc.fiches(cache), projets)
    except Exception as exc:
        noter(f"matin · échec : {exc!r}")
        matin = None
    # The global « Conflits » tab: one row per Studio with open cases, its new ones, its reminder. A failure costs only
    # that tab (null).
    try:
        conflits = charger_projets().conflits_global((projets or {}).get('studios'), parc.fiches(cache),
                                                    charger_projets().lire_instantane())
    except Exception as exc:
        noter(f"conflits global · échec : {exc!r}")
        conflits = None
    # Le contenu est composé par parc.py, rechargé à chaud : le tableau évolue sans arrêter ce serveur.
    page = parc.pour_la_page(e)
    # The lines a click on an answer is checked against (repondre_session): only their closed choices go to a session.
    _lignes_vues.update(t=maintenant, lignes=[l for l in page['lignes'] + page.get('anciennes', []) if l.get('choix')])
    # The lines « Fait / Retirer du tableau » may take off (retirer): what the session that asked will be told.
    _retirables.update(t=maintenant, lignes={l['retrait']: a_prevenir(l) for l in page['lignes'] + page.get('anciennes', [])
                                             if l.get('retrait')})
    # Switch « reclassement » on (PM, 2026-11-17): the lines his button may move, as the Mac computed them; the page
    # learns the switch is on by `reclassement`. Off: neither, the payload of 0.2.23.
    plus = {}
    if parc.reclassement_actif():
        _reclassables.update(t=maintenant, lignes=a_reclasser(e, projets))
        plus['reclassement'] = True
    # The « Mise en route » block (2026-11-15): the setup steps not done yet, from the first day. Same rule.
    try:
        mise_en_route = charger_projets().mise_en_route(maintenant)
    except Exception as exc:
        noter(f"mise en route · échec : {exc!r}")
        mise_en_route = None
    # « Sans réponse » of the morning stand-up: the third-party waits older than two working days, then what the
    # morning point read itself (mails of the PM without an answer), when it writes some.
    if isinstance(matin, dict):
        try:
            matin['sans_reponse'] = parc.sans_reponse(e, maintenant) + [dict(x, matin=True) for x in matin.get('sans_reponse') or []
                                                                      if isinstance(x, dict) and x.get('titre')]
        except Exception as exc:
            noter(f"sans réponse · échec : {exc!r}")
    return dict(page, liste_projets=projets, matin=matin, conflits=conflits, mise_en_route=mise_en_route,
                plus_tard=plus_tard_actifs(maintenant), version=VERSION, **plus)


def a_reclasser(e, projets):
    """{key: what the journal keeps of the line}: the lines of sessions (key « r… ») and the requests of the ingestion
    (their own key), with the order the rules gave (`calcul`) and the PM's, if any (`reclassee`)."""
    out = {}
    for l in (e.get('tableau') or []) + (e.get('anciennes') or []):
        if l.get('retrait'):
            texte = ' '.join(str(l.get('complet') or l.get('affiche_suite') or '').split())
            out[l['retrait']] = {'origine': 'session', 'studio': l.get('studio') or '', 'texte': texte[:300],
                                 'calcul': l.get('calcul') or {}, 'reclassee': l.get('reclassee') or ''}
    for p in (projets or {}).get('projets') or []:
        for l in p.get('lignes') or []:
            if l.get('type') == 'a_toi' and re.fullmatch(r'[0-9a-f]{12}', str(l.get('cle') or '')):
                texte = ' '.join(str(l.get('texte') or l.get('titre') or '').split())
                out[l['cle']] = {'origine': 'ingestion', 'studio': p.get('nom') or '', 'texte': texte[:300],
                                 'calcul': l.get('calcul') or {}, 'reclassee': l.get('reclassee') or ''}
    return out


def clore(arguments):
    arguments = arguments or {}
    cle = arguments.get('cle') or ''
    if 'reclasser' in arguments:
        return reclasser(cle, arguments.get('reclasser'))
    if arguments.get('matin') is True:
        if not isinstance(cle, str) or not 1 <= len(cle) <= 80:
            raise ValueError('clé du point du matin invalide')
        return charger_projets().fait_matin(cle)
    if isinstance(cle, str) and cle.startswith('etape-'):
        return charger_projets().ecarter_etape(cle)
    if arguments.get('plus_tard') is True:
        return plus_tard(cle)
    if isinstance(cle, str) and re.fullmatch(r't[0-9a-f]{12}', cle):
        return tiers_recu(cle)
    if isinstance(cle, str) and re.fullmatch(r'r[0-9a-f]{12}', cle):
        return retirer(cle, abandon=arguments.get('abandon') is True)
    if not re.fullmatch(r'[0-9a-f]{12}', cle):
        raise ValueError('clé de ligne invalide')
    return charger_projets().fermer(cle)


PLUS_TARD = 'plus-tard.json'   # in ~/Mon Studio/.parc: {key: until (ms)}, the lines hidden until tomorrow
ABANDONNEES = 'abandonnees.json'   # in ~/Mon Studio/.parc: the stopped sessions the PM gave up, for the rangement


def demain_minuit(maintenant=None):
    d = dt.datetime.fromtimestamp(maintenant or time.time()).date() + dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time()).timestamp()


def plus_tard_actifs(maintenant=None):
    """{key: until in ms} of the lines hidden by « Plus tard » that are still hidden; the others are forgotten."""
    maintenant = maintenant or time.time()
    r = parc.lire_json(parc.INTERNE / PLUS_TARD, {})
    return {k: v for k, v in (r if isinstance(r, dict) else {}).items()
            if isinstance(k, str) and isinstance(v, (int, float)) and v > maintenant * 1000}


def plus_tard(cle):
    """« Plus tard » (PM, 2026-11-17): the line is hidden until tomorrow midnight, on the board only. Nothing is sent to
    the session; one waiting in its Stop hook ends its own wait (reponses_directes_minutes)."""
    charger_parc()
    if not isinstance(cle, str) or not re.fullmatch(r'[rt]?[0-9a-f]{12}', cle):
        raise ValueError('clé de ligne invalide')
    r = plus_tard_actifs()
    r[cle] = int(demain_minuit() * 1000)
    parc.ecrire_atomique(parc.INTERNE / PLUS_TARD, json.dumps(r, ensure_ascii=False, indent=1))
    noter(f"ligne masquée jusqu'à demain : {cle}")
    return {'plus_tard': cle, 'jusqua': r[cle]}


def tiers_recu(cle):
    """« Reçu » on a third-party wait (PM, 2026-11-17): it leaves the project page and « Sans réponse » for good."""
    charger_parc()
    chemin = parc.INTERNE / parc.TIERS_RECUS
    r = parc.tiers_recus()
    r[cle] = time.time()
    parc.ecrire_atomique(chemin, json.dumps(r, ensure_ascii=False, indent=1))
    noter(f"attente de tiers reçue : {cle}")
    return {'recu': cle}


def retirer(cle, abandon=False):
    """« Fait / Retirer du tableau » on a line of a session (PM, 2026-11-17): the line leaves the board for good, and
    the session that asked is told once at its next turn (hooks/retirees.py). The line is looked up among those the
    board shows (read at most two minutes ago, else computed again): its session, number and title come from the Mac's
    own reading, never from the page."""
    with CALCUL:
        l = _retirables['lignes'].get(cle) if time.time() - _retirables['t'] <= LIGNES_FRAICHES_S else None
        if l is None:
            lignes()
            l = _retirables['lignes'].get(cle)
    if l is None:
        raise ValueError('ligne déjà partie du tableau')
    chemin = parc.INTERNE / parc.RETIREES
    r = parc.lire_json(chemin, {})
    r = r if isinstance(r, dict) else {}
    maintenant = time.time()
    limite = maintenant - parc.RETIREES_JOURS * 86400
    r = {k: v for k, v in r.items() if isinstance(v, dict) and (v.get('quand') or 0) >= limite}
    # An abandoned session is not told (it is stopped): it is proposed for archiving instead (hooks/rangement.py).
    r[cle] = dict(l, quand=maintenant, prevenue=bool(abandon))
    parc.ecrire_atomique(chemin, json.dumps(r, ensure_ascii=False, indent=1))
    if abandon and l.get('session'):
        a = parc.lire_json(parc.INTERNE / ABANDONNEES, {})
        a = a if isinstance(a, dict) else {}
        a[l['session']] = {'titre': l.get('session_titre') or l.get('titre') or '', 'quand': maintenant}
        parc.ecrire_atomique(parc.INTERNE / ABANDONNEES, json.dumps(a, ensure_ascii=False, indent=1))
    noter(f"ligne {'abandonnée' if abandon else 'retirée du tableau'} : {cle}")
    return {'retiree': cle, 'abandon': bool(abandon)}


def reclasser(cle, vers):
    """« Pas si urgent » (vers « ensuite ») or « À faire d'abord » (vers « dabord ») on a line of the board, or
    « annuler » (one more click): the PM's order is kept in reclassees.json and holds over the computed one while the
    line is there (parc.classements_du_pm). The line is looked up among those the board shows, as for « retirer »; its
    text and computed order come from the Mac's own reading. Each click is one line of reclassements.jsonl, which never
    leaves the Mac."""
    if not parc.reclassement_actif():
        raise ValueError("le reclassement du tableau est coupé (cockpit.json, reclassement_tableau)")
    if vers not in ('dabord', 'ensuite', 'annuler'):
        raise ValueError('classement invalide')
    if not isinstance(cle, str) or not re.fullmatch(r'r?[0-9a-f]{12}', cle):
        raise ValueError('clé de ligne invalide')
    with CALCUL:
        l = _reclassables['lignes'].get(cle) if time.time() - _reclassables['t'] <= LIGNES_FRAICHES_S else None
        if l is None:
            lignes()
            l = _reclassables['lignes'].get(cle)
        if l is None:
            raise ValueError('ligne déjà partie du tableau')
        chemin = parc.INTERNE / parc.RECLASSEES
        r = parc.lire_json(chemin, {})
        r = r if isinstance(r, dict) else {}
        maintenant = time.time()
        limite = maintenant - parc.RECLASSEES_JOURS * 86400
        r = {k: v for k, v in r.items() if isinstance(v, dict) and (v.get('quand') or 0) >= limite}
        avant = (r.get(cle) or {}).get('vers') or ''
        if vers == 'annuler':
            r.pop(cle, None)
        else:
            r[cle] = {'vers': vers, 'quand': maintenant}
        parc.ecrire_atomique(chemin, json.dumps(r, ensure_ascii=False, indent=1))
        _reclassables['t'] = 0.0   # the next click reads the board again
    calcul = l.get('calcul') or {}
    entree = {'date': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'cle': cle, 'origine': l['origine'],
              'studio': l.get('studio') or '', 'texte': l.get('texte') or '',
              'calcul': {k: calcul.get(k) or '' for k in ('impact', 'raison', 'effort', 'regle')},
              'pm': vers, 'avant': avant}
    try:
        with (parc.INTERNE / parc.RECLASSEMENTS).open('a', encoding='utf-8') as f:
            f.write(json.dumps(entree, ensure_ascii=False) + '\n')
    except OSError:
        pass
    noter(f"ligne reclassée : {cle} → {vers}")
    return {'cle': cle, 'reclassee': '' if vers == 'annuler' else vers}


def a_prevenir(l):
    """What retirees.json keeps of a board line: the session to tell (the one that asked), its number, its title."""
    sid = l.get('source') if SESSION_LOCALE.match(str(l.get('source') or '')) else l.get('cle')
    return {'session': sid if SESSION_LOCALE.match(str(sid or '')) else '',
            'question': l.get('question') if NUMERO_QUESTION.match(str(l.get('question') or '')) and l.get('question') else '',
            'titre': ' '.join(str(l.get('affiche_titre') or l.get('affiche_suite') or '').split())[:120],
            'session_titre': ' '.join(str(l.get('session') or '').split())[:120]}


def projet(arguments):
    dossier = str((arguments or {}).get('dossier') or '')
    if not dossier or len(dossier) > 1000:
        raise ValueError('dossier de projet invalide')
    charger_parc()
    maintenant = time.time()
    cache = parc.charger_cache()
    e = parc.construire(int(parc.os.environ.get('MON_STUDIO_JOURS', 7)), 7, maintenant, cache)
    parc.ecrire_atomique(parc.INTERNE / 'cache.json', json.dumps(cache, ensure_ascii=False))
    vue = parc.vue_projet_pour_la_page(e, dossier)
    # The « Conflits » tab: the open cases of the Studio's register, read-only. A failure costs only that tab.
    try:
        vue['conflits'] = charger_projets().conflits_du_projet(dossier, parc.fiches(cache), depuis_connecteur=True)
    except Exception as exc:
        noter(f"conflits · échec : {exc!r}")
        vue['conflits'] = None
    return dict(vue, version=VERSION)


# What « ouvrir » opens in a Studio: documents only. `open` also launches an executable, a .command, a .app or a
# .terminal: anything outside this closed list is refused.
EXTENSIONS_DOCUMENT = frozenset({'md', 'txt', 'pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'csv', 'png', 'jpg',
                                 'jpeg', 'gif', 'odt', 'ods', 'odp', 'rtf', 'html'})


def document_autorise(chemin):
    """Vrai si le nom finit par une extension de la liste fermée des documents (sans tenir compte de la casse)."""
    nom = os.path.basename(chemin)
    return '.' in nom.strip('.') and nom.rsplit('.', 1)[1].lower() in EXTENSIONS_DOCUMENT


def ouvrir_fichier(dossier, fichier):
    """Un document d'un Studio connu, ouvert dans son application. Le chemin est validé comme dans matin.json (relatif,
    sans `..`), son extension doit être celle d'un document (EXTENSIONS_DOCUMENT), et le chemin résolu (liens symboliques
    suivis) doit rester dans le dossier du Studio et finir lui aussi par une extension de document : c'est lui qu'`open`
    reçoit. Son existence n'est pas vérifiée ici, le Drive peut refuser la lecture au connecteur : `open` le dit. Un
    dossier (un .app est un dossier) est refusé."""
    p = charger_projets()
    chemin = p._charger_matin()._chemin(fichier)
    if not chemin:
        raise ValueError('chemin de fichier invalide')
    if not document_autorise(chemin):
        raise ValueError("ce type de fichier ne s'ouvre pas depuis la page (documents seulement)")
    d = p.dossier_du_matin(dossier)
    base = os.path.realpath(d)
    reel = os.path.realpath(os.path.join(d, chemin))
    if not reel.startswith(base.rstrip(os.sep) + os.sep) or not document_autorise(reel):
        raise ValueError('le fichier sort du dossier du Studio')
    if os.path.isdir(reel):
        raise ValueError("ce chemin est un dossier, pas un document")
    r = subprocess.run(['open', reel], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("le fichier n'a pas pu s'ouvrir")
    return {'ouvert': chemin}


def dossier_de_la_session():
    """CLAUDE_PROJECT_DIR when this instance was launched with it, or None. The guard built on it applies only when the
    variable is present: the instances the desktop app launches (the ones the page and the app's sessions call) never
    carry it, so there it refuses nothing. The protocol has no caller identity; the tool descriptions tell a session not
    to call decider, repondre and clore."""
    d = os.environ.get('CLAUDE_PROJECT_DIR')
    return os.path.normpath(d) if d else None


def refuser_hors_de_la_page(outil):
    if dossier_de_la_session():
        raise ValueError(f"« {outil} » n'est réservé qu'à la page de Mon Studio : une session ne l'appelle pas")


def lire(arguments):
    arguments = arguments or {}
    dossier, fichier = arguments.get('dossier'), arguments.get('fichier')
    if not isinstance(dossier, str) or not isinstance(fichier, str):
        raise ValueError('dossier et fichier attendus')
    session = dossier_de_la_session()
    if session and charger_projets().dossier_normal(dossier) != charger_projets().dossier_normal(session):
        raise ValueError('une session ne lit que les fichiers de son propre Studio')
    return charger_projets().lire_fichier(dossier, fichier)


def ouvrir(arguments):
    arguments = arguments or {}
    if 'fichier' in arguments or 'dossier' in arguments:
        session = dossier_de_la_session()
        if session and charger_projets().dossier_normal(str(arguments.get('dossier') or '')) != charger_projets().dossier_normal(session):
            raise ValueError("une session n'ouvre que les fichiers de son propre Studio")
        return ouvrir_fichier(arguments.get('dossier'), arguments.get('fichier'))
    sid = arguments.get('id') or ''
    copie = arguments.get('copier') or ''
    # A setup step's button (« Mise en route »): only its command to the clipboard, to paste in a new session; the
    # page cannot open one.
    if not sid and re.fullmatch(r'/cockpit:mon-studio (?:point du matin|terminal)', copie):
        subprocess.run(['pbcopy'], input=copie.encode(), capture_output=True)
        return {'copie': copie}
    if not re.fullmatch(r'local_[0-9a-f-]{36}', sid):
        raise ValueError('identifiant de session invalide')
    # Le numéro de la question, prêt à coller (Cmd+V) dans la session qui s'ouvre : un lien claude:// ne
    # transporte aucun texte, il ne reste que le presse-papiers. Seul un numéro « Q10 » est accepté.
    if copie and re.fullmatch(COPIE_MOTIF[1:-1], copie):
        subprocess.run(['pbcopy'], input=copie.encode(), capture_output=True)
    r = subprocess.run(['open', parc.lien_app(sid)], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("l'app n'a pas pu ouvrir la session")
    return {'ouvert': sid}


# ---------- Les autorisations confiées par le hook PermissionRequest

MOTIF_SOCKET = re.compile(r'autorisations-(\d+)\.sock')
ANCIENNE_SOCKET = parc.INTERNE / 'autorisations.sock'   # one socket for every instance, before 2026-10-30
JOURNAL_DECISIONS = parc.INTERNE / 'autorisations.log'
JOURNAL_REPONSES = parc.INTERNE / 'reponses-directes.log'
CHOIX_POSSIBLE = re.compile(r'^(?:go|oui|pas encore|ok|[1-9]\d?|' + RECOMMANDE_MOTIF + ')$')
# An option's label, for a question without a number: one line, 80 characters at most.
LIBELLE_POSSIBLE = re.compile('^' + LIBELLE_MOTIF + '$')
NUMERO_QUESTION = re.compile(r'^(?:Q\d{1,4})?$')
SESSION_LOCALE = re.compile(r'^local_[0-9a-f-]{36}$')
LIMITE_S = 1800          # une demande plus vieille est oubliée : le hook a abandonné, la fenêtre normale reste
AILLEURS_S = 5           # transcript écrit plus tard que la demande : la session a été répondue dans l'app
DECISIONS_MONTREES = 5
POSSIBLE = os.name != 'nt' and hasattr(socket, 'AF_UNIX')


class Demande:
    def __init__(self, conn, d):
        self.conn, self.id = conn, d['id']
        self.session, self.cwd = str(d.get('session_id') or '')[:100], str(d.get('cwd') or '')[:500]
        self.outil, self.extrait = str(d.get('tool_name') or '')[:200], str(d.get('extrait') or '')[:300]
        self.depuis = time.time()
        self.reponse = None            # 'allow' | 'deny', posée par decider
        self.fini = threading.Event()  # la connexion est rendue (réponse envoyée, expirée ou fermée par le hook)


class Attente:
    """A session waiting for the PM's closed answer to the question it just asked (hooks/reponse_directe.py)."""

    def __init__(self, conn, d):
        self.conn, self.id = conn, d['id']
        self.session = str(d.get('session_id') or '')[:100]
        sid = str(d.get('sessionId') or '')
        self.sessionId = sid if SESSION_LOCALE.match(sid) else None
        self.numero, self.kind = d['numero'], d['kind']
        self.titre, self.choix = str(d.get('titre') or '')[:300], list(d['choix'])
        limite = d.get('limite')
        self.limite = min(LIMITE_S, float(limite)) if isinstance(limite, (int, float)) and not isinstance(limite, bool) \
            and limite > 0 else LIMITE_S
        self.depuis = time.time()
        self.reponse = None
        self.fini = threading.Event()


def attente_valide(d):
    """An « attente » message as the hook sends it: anything else is dropped, so the page never shows free text."""
    choix = d.get('choix')
    return (d.get('kind') in ('go', 'decision', 'clic') and isinstance(d.get('numero'), str)
            and bool(NUMERO_QUESTION.match(d['numero'])) and isinstance(choix, list)
            and (1 if d.get('kind') == 'clic' else 2) <= len(choix) <= 12
            and all(isinstance(c, str) and (CHOIX_POSSIBLE.match(c) or (not d['numero'] and LIBELLE_POSSIBLE.match(c)))
                    for c in choix)
            and len(set(choix)) == len(choix))


def pid_vivant(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True    # it exists, under another account
    return True


def socket_vivante(chemin):
    """True when something accepts a connection on this socket."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as essai:
            essai.settimeout(1)
            essai.connect(str(chemin))
        return True
    except OSError:
        return False


def nettoyer_sockets(dossier, garder=None):
    """Remove the dead sockets of stopped instances: connection refused, or a pid that no longer exists. The old
    single autorisations.sock goes too when nothing answers on it. A live socket is never touched."""
    for chemin in sorted(dossier.glob('autorisations-*.sock')) + [dossier / ANCIENNE_SOCKET.name]:
        if chemin == garder or not chemin.is_socket():
            continue
        m = MOTIF_SOCKET.fullmatch(chemin.name)
        mort = (m is not None and not pid_vivant(int(m.group(1)))) or not socket_vivante(chemin)
        if mort:
            try:
                chemin.unlink()
            except OSError:
                pass


class Autorisations:
    """La socket de cette instance et les demandes qu'elle a reçues, en mémoire seulement."""

    def __init__(self, chemin=None):
        self.chemin = pathlib.Path(chemin or parc.INTERNE / f'autorisations-{os.getpid()}.sock')
        self.demandes, self.attentes, self.verrou = {}, {}, threading.Lock()
        self.serveur, self.raison = None, ''

    def demarrer(self):
        if not POSSIBLE:
            self.raison = 'ce système ne le permet pas (Mac seulement)'
            return False
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.chemin.parent, 0o700)
            nettoyer_sockets(self.chemin.parent, garder=self.chemin)
            if self.chemin.exists() or self.chemin.is_socket():
                if socket_vivante(self.chemin):  # a dead one, left under a reused pid, is replaced
                    self.raison = 'une autre copie de Mon Studio répond déjà à la page'
                    return False
                self.chemin.unlink()
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ancien = os.umask(0o177)
            try:
                s.bind(str(self.chemin))
            finally:
                os.umask(ancien)
            os.chmod(self.chemin, 0o600)
            s.listen(16)
        except OSError as exc:
            self.raison = f'le lien avec la page ne s\'ouvre pas ({exc})'
            return False
        self.serveur, self.raison = s, ''
        threading.Thread(target=self._accepter, daemon=True).start()
        return True

    def arreter(self):
        s, self.serveur = self.serveur, None
        if s:
            s.close()
            try:
                self.chemin.unlink()
            except OSError:
                pass
        with self.verrou:
            for d in list(self.demandes.values()) + list(self.attentes.values()):
                d.fini.set()

    def _accepter(self):
        while self.serveur:
            try:
                conn, _ = self.serveur.accept()
            except OSError:
                return
            threading.Thread(target=self._servir, args=(conn,), daemon=True).start()

    def _servir(self, conn):
        try:
            conn.settimeout(5)
            recu = b''
            while b'\n' not in recu and len(recu) < 65536:
                bout = conn.recv(4096)
                if not bout:
                    return
                recu += bout
            d = json.loads(recu.split(b'\n', 1)[0])
            if not (isinstance(d, dict) and re.fullmatch(r'[0-9a-f]{32}', str(d.get('id')))):
                return
            if d.get('type') == 'demande':
                dem, registre, limite = Demande(conn, d), self.demandes, LIMITE_S
            elif d.get('type') == 'attente' and attente_valide(d):
                dem = Attente(conn, d)
                registre, limite = self.attentes, dem.limite
            else:
                return
            with self.verrou:
                registre[dem.id] = dem
            while not dem.fini.is_set():
                if time.time() - dem.depuis > limite:
                    break
                lisible, _, _ = select.select([conn], [], [], 0.5)
                if lisible and not dem.fini.is_set():
                    try:
                        if not conn.recv(1, socket.MSG_PEEK):
                            break  # le hook est parti (l'app l'a arrêté, ou la session a été répondue)
                    except OSError:
                        break
        except (OSError, ValueError):
            pass
        finally:
            with self.verrou:
                for registre in (self.demandes, self.attentes):
                    for k, v in list(registre.items()):
                        if v.conn is conn and v.reponse is None:
                            del registre[k]
            conn.close()

    def oublier_expirees(self):
        with self.verrou:
            for k, v in list(self.demandes.items()):
                if time.time() - v.depuis > LIMITE_S:
                    del self.demandes[k]
                    v.fini.set()
            for k, v in list(self.attentes.items()):
                if time.time() - v.depuis > v.limite:
                    del self.attentes[k]
                    v.fini.set()

    def en_attente_de_reponse(self):
        self.oublier_expirees()
        with self.verrou:
            return sorted(self.attentes.values(), key=lambda a: a.depuis)

    def repondre(self, ident, choix):
        """Hands the PM's closed answer to the waiting hook. Refuses an unknown or expired wait, an answer outside its
        list, and a session that no longer waits."""
        self.oublier_expirees()
        with self.verrou:
            att = self.attentes.get(str(ident))
            if att is None:
                raise ValueError("attente inconnue ou expirée : la session s'est arrêtée, réponds dans la session")
            if not isinstance(choix, str) or choix not in att.choix:
                raise ValueError(f"réponse hors liste : seules {', '.join('« ' + c + ' »' for c in att.choix)} sont acceptées")
            if att.fini.is_set():
                self.attentes.pop(att.id, None)
                raise ValueError("la session n'attend plus : réponds dans la session")
            del self.attentes[att.id]
        att.reponse = choix
        try:
            att.conn.sendall((json.dumps({'id': att.id, 'choix': choix}, ensure_ascii=False) + '\n').encode())
        except OSError:
            att.fini.set()
            raise ValueError("la session n'attend plus : réponds dans la session")
        att.fini.set()
        return att

    def en_attente(self):
        self.oublier_expirees()
        with self.verrou:
            return sorted(self.demandes.values(), key=lambda d: d.depuis)

    def lacher(self, dem):
        """La session a été répondue ailleurs : la demande part, le hook se termine sans rien rendre."""
        with self.verrou:
            self.demandes.pop(dem.id, None)
        dem.fini.set()
        try:
            dem.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def decider(self, ident, decision):
        if decision not in ('allow', 'deny'):
            raise ValueError('décision attendue : allow ou deny')
        self.oublier_expirees()
        with self.verrou:
            dem = self.demandes.pop(str(ident), None)
        if dem is None:
            raise ValueError("demande inconnue ou expirée : réponds dans la session, sa fenêtre d'autorisation reste")
        dem.reponse = decision
        try:
            dem.conn.sendall((json.dumps({'id': dem.id, 'decision': decision}) + '\n').encode())
        except OSError:
            dem.fini.set()
            raise ValueError("la session n'attend plus cette demande : réponds dans la session")
        dem.fini.set()
        return dem


AUTORISATIONS = Autorisations()
_fiches = {'fiches': {}}


def interrupteur():
    etat = parc.lire_json(parc.INTERNE / 'cockpit.json', {}) or {}
    return isinstance(etat, dict) and etat.get('autorisations_tableau') is True


def interrupteur_reponses():
    etat = parc.lire_json(parc.INTERNE / 'cockpit.json', {}) or {}
    return isinstance(etat, dict) and etat.get('reponses_directes') is True

def sessions_connues():
    """{identifiant CLI: (local_…, titre)} d'après les fiches de l'app, relues seulement quand elles bougent."""
    charger_parc()
    return {m['cli']: (m['id'], m['titre']) for m in parc.fiches(_fiches) if m.get('cli')}


def repondue_ailleurs(dem, index):
    """Vrai quand le transcript de la session a été écrit après la demande : l'app a eu sa réponse, par sa fenêtre."""
    chemin = index.get(dem.session)
    try:
        return bool(chemin) and os.stat(chemin).st_mtime > dem.depuis + AILLEURS_S
    except OSError:
        return False


def dernieres_decisions(n=DECISIONS_MONTREES):
    try:
        lignes = JOURNAL_DECISIONS.read_text(encoding='utf-8').splitlines()[-n:]
    except OSError:
        return []
    sortie = []
    for l in reversed(lignes):
        try:
            sortie.append(json.loads(l))
        except ValueError:
            continue
    return sortie


def autorisations():
    allume, tenue = interrupteur(), AUTORISATIONS.serveur is not None
    actif = allume and tenue
    if not allume:
        raison = 'interrupteur coupé (cockpit.json, autorisations_tableau)'
    elif not tenue:
        raison = AUTORISATIONS.raison or "le lien entre la page et ton Mac ne répond pas"
    else:
        raison = ''
    demandes = []
    if actif:
        attente = AUTORISATIONS.en_attente()
        if attente:
            connues, index = sessions_connues(), parc.index_transcripts()
            for d in attente:
                if repondue_ailleurs(d, index):
                    AUTORISATIONS.lacher(d)
                    continue
                sid, titre = connues.get(d.session, (None, None))
                demandes.append({'id': d.id, 'session': d.session, 'sessionId': sid, 'titre': titre,
                                 'outil': parc.nom_outil(d.outil), 'extrait': parc.extrait_lisible(d.extrait),
                                 'cwd': d.cwd, 'depuis': int(d.depuis * 1000)})
    return {'actif': actif, 'interrupteur': allume, 'raison': raison, 'demandes': demandes,
            'decisions': dernieres_decisions() if actif else []}


def decider(arguments):
    arguments = arguments or {}
    refuser_hors_de_la_page('decider')
    if not interrupteur():
        raise ValueError("les autorisations depuis Mon Studio sont coupées (cockpit.json, autorisations_tableau)")
    dem = AUTORISATIONS.decider(arguments.get('id') or '', arguments.get('decision'))
    titre = sessions_connues().get(dem.session, (None, None))[1]
    ligne = {'date': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'decision': dem.reponse,
             'outil': dem.outil, 'extrait': dem.extrait, 'session': dem.session, 'titre': titre}
    try:
        with JOURNAL_DECISIONS.open('a', encoding='utf-8') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    except OSError:
        pass
    return {'id': dem.id, 'decision': dem.reponse, 'envoye': True}


def attentes():
    allume, tenue = interrupteur_reponses(), AUTORISATIONS.serveur is not None
    actif = allume and tenue
    if not allume:
        raison = 'interrupteur coupé (cockpit.json, reponses_directes)'
    elif not tenue:
        raison = AUTORISATIONS.raison or "le lien entre la page et ton Mac ne répond pas"
    else:
        raison = ''
    sortie = []
    if actif:
        liste = AUTORISATIONS.en_attente_de_reponse()
        connues = sessions_connues() if liste else {}
        for a in liste:
            sid, titre = connues.get(a.session, (None, None))
            sortie.append({'id': a.id, 'session': a.session, 'sessionId': a.sessionId or sid, 'titre_session': titre,
                           'numero': a.numero, 'titre': a.titre, 'kind': a.kind, 'choix': list(a.choix),
                           'depuis': int(a.depuis * 1000),
                           # la fin de l'attente : la page change la ligne à cette heure (essai de la réponse en direct du 02/11)
                           'jusqua': int((a.depuis + a.limite) * 1000)})
    # The answers given to sessions that did not wait (Q40), whatever the switch: the page says on each line what
    # became of its answer.
    return {'actif': actif, 'interrupteur': allume, 'raison': raison, 'attentes': sortie, 'en_file': file_pour_la_page()}

def repondre_attente(arguments):
    arguments = arguments or {}
    refuser_hors_de_la_page('repondre')
    if not interrupteur_reponses():
        raise ValueError("les réponses depuis Mon Studio sont coupées (cockpit.json, reponses_directes)")
    att = AUTORISATIONS.repondre(arguments.get('id') or '', arguments.get('choix'))
    titre = sessions_connues().get(att.session, (None, None))[1]
    ligne = {'date': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'numero': att.numero,
             'choix': att.reponse, 'session': titre or att.sessionId or att.session}
    try:
        with JOURNAL_REPONSES.open('a', encoding='utf-8') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    except OSError:
        pass
    return {'id': att.id, 'choix': att.reponse, 'envoye': True}


# ---------- An answer to a session that does not wait on the page (Q40, 2026-11-09)
#
# The PM clicks a closed answer (« Go », « Oui », an option, « Pas encore ») on a line whose session does not wait in
# its Stop hook. `repondre` with `session`, `question` and `choix` (no `id`) decides, for everyone and at any time:
#   a) the session waits in its hook after all (a wait arrived since the page last read): the hook gets the answer;
#   b) the session is asleep (no Claude process holds it): it is woken in the background with the Terminal's Claude,
#      `claude --resume <cliSessionId> -p "<answer>"`, in its folder, with its model, effort and permission mode
#      (never a more permissive one), detached, its output in .parc/reveils/; the turn shows in the app afterwards;
#   c) a Claude process of the app still holds the session. Never a second process on it, the conversation would fork.
#      - Its turn is over (Q13, 2026-11-15: tried on a throwaway session, answer in 20 s, whole conversation kept, the
#        app shows no error, main.log notes « exited with code 143 »): the process is stopped (SIGTERM, as the app's own
#        governor does under memory pressure) and the session is woken as in b), right away. At most once per answer.
#      - Its turn goes on, or nothing proves it is over: the answer waits in .parc/reponses-en-file/ and the watcher
#        thread (`surveiller_file`) delivers it as above once the turn is over. It expires after 24 h. One answer per
#        question: a new click replaces the one not delivered yet.
#      « Turn over » takes both witnesses (`au_repos`), each checked again right before the stop:
#        1. the session's transcript: its last user, assistant or queue entry is Claude's answer that ends the turn
#           (stop_reason end_turn), no message waits in its queue, and the file has not moved for REPOS_S seconds;
#        2. the app's main.log: after the last « Sending message to session <id> », a turn end for that session
#           (« [Stop hook] Query completed for session <id> » or « healthy cycle for <id> »). « Starting idle
#           timeout » is not one: the app writes it in the middle of a turn too (seen on 2026-11-15, 21:17:50).
#        A tool that runs for minutes leaves Claude's last entry a tool call (no end_turn); a message typed meanwhile
#        is an enqueue or a user entry after it; a Stop hook still running (case a) has no « Query completed » yet.
#        A process the app does not hold (a `claude --resume` in a Terminal, or a wake from here) is never stopped.
#   A wake that ends on an error before the session received the answer puts the answer back in the queue once; the
#   second failure says « Pas envoyée » on the line. The line says « envoyée » only once the session's transcript holds
#   the answer, or the wake ended without an error.
# Otherwise (not a Mac, the Terminal's Claude missing or not logged in, a session unknown, archived or without its
# folder) `mode: "copie"`: the page copies the answer and opens the session, as before.
#
# Liveness (checked on the real data of 2026-11-09): `ps -axww -E` lists each process's command and environment. A
# process of the app's Claude carries CLAUDE_CODE_HOST_SESSION_ID=local_… ; a resumed one also has --resume=<cli>, and
# a wake from here, or a `claude --resume` in a Terminal, has --resume <cli>. Only the Claude CLI's own lines count
# (« …/claude --… »): its children (shells, MCP servers, browsers) inherit the variable and outlive it. main.log is not
# used: « Pausing session » is reliable but a « Warming session » often has no end, and an idle timeout does not
# always stop the process (25 sessions « started » there had no process, one « stopped » still had one).
# ps unreadable: the session counts as alive (the answer waits, nothing forks).

import contextlib
try:
    import fcntl
except ImportError:          # Windows: no wake, the page copies the answer
    fcntl = None

REVEIL_POSSIBLE = sys.platform == 'darwin' and fcntl is not None
FILE = parc.INTERNE / 'reponses-en-file'
REVEILS = parc.INTERNE / 'reveils'
TERMINAL = parc.INTERNE / 'terminal.json'
FILE_S = 24 * 3600          # an answer that waits longer expires; the PM sees it on the line
GARDE_S = 48 * 3600         # an entry is forgotten after that (delivered, expired or failed)
TOUR_S = 15                 # the watcher's period
LIGNES_FRAICHES_S = 120     # the lines a click is checked against are at most that old
AUTH_S = 300                # `claude auth status`, asked again after that
NON_CONNECTE_S = 600        # a wake that found the Terminal logged out: no other wake for that long
REPOS_S = 15                # a transcript untouched that long, ending on Claude's end of turn: the turn is over
ARRET_S = 10                # how long a stopped process may take to end; still there: the answer waits
ARRETS_MAX = 1              # stops per answer: a process the app starts again at once is left alone
ESSAIS_MAX = 2              # wakes per answer: one more after a wake that ended on an error
JOURNAL_APP = pathlib.Path(os.environ.get('MON_STUDIO_JOURNAL_APP')
                           or pathlib.Path.home() / 'Library' / 'Logs' / 'Claude' / 'main.log')
JOURNAL_APP_FIN = 3 * 1024 * 1024   # the end of main.log read for a session's last turn
TRANSCRIPT_FIN = 512 * 1024
CLI_PROCESSUS = re.compile(r'/claude --')
HOTE = re.compile(r'\bCLAUDE_CODE_HOST_SESSION_ID=(local_[0-9a-f-]{36})')
REPRISE = re.compile(r'--resume[= ]([0-9a-f-]{36})\b')
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
MODELE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.\-_\[\]]{1,60}$')
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
# The session's permission mode, as the Terminal's Claude takes it: the same, or less permissive. Never
# bypassPermissions from here: auto at most. Unknown: default (anything that would ask is refused, nobody watches).
MODES = {'plan': 'plan', 'default': 'default', 'manual': 'default', 'dontAsk': 'dontAsk', 'acceptEdits': 'acceptEdits',
         'auto': 'auto', 'bypassPermissions': 'auto'}
# What the Terminal's Claude says when it has no usable login (essai du 2026-11-06), at the start of a line.
DECONNECTE = re.compile(r'^(?:Not logged in|OAuth session expired|OAuth token has expired|Invalid API key|Please run /login)',
                        re.I | re.M)
CALCUL = threading.RLock()  # one board computation at a time: the page's call and the watcher's use the same cache
_lignes_vues = {'t': 0.0, 'lignes': []}
_retirables = {'t': 0.0, 'lignes': {}}
_reclassables = {'t': 0.0, 'lignes': {}}   # the lines « Pas si urgent » / « À faire d'abord » may move, by their key
_auth = {'t': 0.0, 'ok': None}
_lances = {}                # pid → Popen of the wakes this instance started, reaped by the watcher


def claude_terminal():
    """The Terminal's Claude (native installer: ~/.local/bin/claude), never the app's own copy, which has no login
    usable outside the app. MON_STUDIO_CLAUDE replaces it (tests)."""
    chemin = os.environ.get('MON_STUDIO_CLAUDE') or str(pathlib.Path.home() / '.local' / 'bin' / 'claude')
    return chemin if os.path.isfile(chemin) and os.access(chemin, os.X_OK) else None


def env_terminal():
    """The connector's environment for the Terminal's Claude, without the variables of a running Claude or of the app
    (CLAUDE_CODE_*, CLAUDE_EFFORT, CLAUDE_PID…: the wake is not a session of the app, and takes its effort from the
    card), CLAUDE_CONFIG_DIR kept, with the usual folders on PATH (the app starts this server with a short one)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE') or k == 'CLAUDE_CONFIG_DIR'}
    chemins = [p for p in env.get('PATH', '').split(os.pathsep) if p]
    for p in (str(pathlib.Path.home() / '.local' / 'bin'), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin',
              '/usr/sbin', '/sbin'):
        if p not in chemins:
            chemins.append(p)
    env['PATH'] = os.pathsep.join(chemins)
    return env


def noter_terminal(connecte, par):
    try:
        parc.ecrire_atomique(TERMINAL, json.dumps({'connecte': bool(connecte), 't': time.time(), 'par': par}))
    except OSError:
        pass


def terminal_connecte(maintenant=None):
    """True when the Terminal's Claude can wake a session: present, `claude auth status` says logged in, and no wake
    found it logged out in the last 10 minutes. Asked again every 5 minutes, never through a model call."""
    maintenant = maintenant or time.time()
    exe = claude_terminal()
    if not exe:
        return False
    note = parc.lire_json(TERMINAL, {}) or {}
    if isinstance(note, dict) and note.get('connecte') is False and note.get('par') == 'reveil' \
            and maintenant - float(note.get('t') or 0) < NON_CONNECTE_S:
        return False
    if _auth['ok'] is not None and maintenant - _auth['t'] < AUTH_S:
        return _auth['ok']
    try:
        r = subprocess.run([exe, 'auth', 'status'], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL, env=env_terminal(), errors='replace')
        try:
            ok = json.loads(r.stdout or '').get('loggedIn') is True
        except (ValueError, AttributeError):
            ok = r.returncode == 0 and not DECONNECTE.search(r.stdout + r.stderr)
    except (OSError, subprocess.SubprocessError):
        ok = False
    _auth.update(t=maintenant, ok=ok)
    return ok


def lire_processus():
    """The process table with each process's environment (`ps -E` shows it for the PM's own processes), or None."""
    try:
        r = subprocess.run(['ps', '-axww', '-E', '-o', 'pid=,command='], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL, errors='replace')
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def sessions_vivantes(texte=None):
    """({local_…}, {cliSessionId}) of the sessions a Claude process holds, or None when ps cannot be read."""
    texte = lire_processus() if texte is None else texte
    if texte is None:
        return None
    hotes, reprises = set(), set()
    for ligne in texte.splitlines():
        if CLI_PROCESSUS.search(ligne):
            hotes.update(HOTE.findall(ligne))
            reprises.update(REPRISE.findall(ligne))
    return hotes, reprises


def session_vivante(sid, cli, vivantes):
    """A Claude process holds the session, or ps could not tell (then it counts as alive: nothing forks)."""
    return vivantes is None or sid in vivantes[0] or bool(cli and cli in vivantes[1])


def processus_de_l_app(sid, cli, texte):
    """(pids of the app's Claude CLI holding `sid`, True when another Claude process holds it: a Terminal's
    `claude --resume`, or a wake from here). Only the CLI's own lines count, as in sessions_vivantes."""
    pids, autre = [], False
    for ligne in (texte or '').splitlines():
        if not CLI_PROCESSUS.search(ligne):
            continue
        if sid in HOTE.findall(ligne):
            try:
                pids.append(int(ligne.split(None, 1)[0]))
            except (ValueError, IndexError):
                autre = True
        elif cli and cli in REPRISE.findall(ligne):
            autre = True
    return pids, autre


def transcript_de(cli):
    if not UUID.match(str(cli or '')):
        return None
    for chemin in parc.TRANSCRIPTS.glob(f'*/{cli}.jsonl'):
        return chemin
    return None


def fin_du_transcript(chemin):
    """The user, assistant and queue entries of the main conversation, from the end of the transcript."""
    with open(chemin, 'rb') as f:
        f.seek(0, 2)
        n = f.tell()
        f.seek(max(0, n - TRANSCRIPT_FIN))
        brut = f.read()
    lignes = brut.split(b'\n')[1 if n > TRANSCRIPT_FIN else 0:]
    sortie = []
    for ligne in lignes:
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get('type') in ('user', 'assistant', 'queue-operation') and not o.get('isSidechain'):
            sortie.append(o)
    return sortie


def transcript_au_repos(cli, maintenant=None):
    """Witness 1: the transcript ends on Claude's end of turn, nothing waits in the queue, unchanged for REPOS_S."""
    chemin = transcript_de(cli)
    if chemin is None:
        return False
    try:
        if (maintenant or time.time()) - os.stat(chemin).st_mtime < REPOS_S:
            return False
        entrees = fin_du_transcript(chemin)
    except OSError:
        return False
    if not entrees:
        return False
    dernier = entrees[-1]
    return dernier.get('type') == 'assistant' and (dernier.get('message') or {}).get('stop_reason') == 'end_turn'


def journal_app_au_repos(sid):
    """Witness 2: in the app's main.log, a turn end of this session after the last message sent to it."""
    try:
        with open(JOURNAL_APP, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - JOURNAL_APP_FIN))
            texte = f.read().decode('utf-8', 'replace')
    except OSError:
        return False
    debut = texte.rfind(f'Sending message to session {sid}')
    fin = max(texte.rfind(f'[Stop hook] Query completed for session {sid}'), texte.rfind(f'healthy cycle for {sid} '))
    return fin >= 0 and fin > debut


def au_repos(sid, fiche, maintenant=None):
    """The process holding the session has finished its turn: both witnesses agree."""
    return transcript_au_repos((fiche or {}).get('cliSessionId'), maintenant) and journal_app_au_repos(sid)


def arreter_au_repos(e, fiche, maintenant):
    """Case c, turn over: stops the app's process that holds the session, so that it can be woken with the answer.
    True when no process holds it anymore. Never a process whose turn goes on, never one the app does not hold."""
    if int(e.get('arrets') or 0) >= ARRETS_MAX:
        return False
    sid = e['session']
    texte = lire_processus()
    if texte is None:
        return False
    pids, autre = processus_de_l_app(sid, fiche.get('cliSessionId'), texte)
    if autre or not pids or not au_repos(sid, fiche):
        return False
    e['arrets'] = int(e.get('arrets') or 0) + 1
    e['arret'] = maintenant
    ecrire_entree(e)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            noter(f"file · arrêt {pid} : {exc!r}")
            return False
    fin = time.time() + ARRET_S
    while time.time() < fin and any(pid_vivant(p) for p in pids):
        time.sleep(0.2)
    restants = [p for p in pids if pid_vivant(p)]
    journal_reponse(e, 'arret', pids=pids, restants=restants)
    return not restants


def recue_par_la_session(e):
    """The session's transcript holds the answer, written after the click: it reached the session."""
    fiche = fiche_session(e['session']) or {}
    chemin = transcript_de(fiche.get('cliSessionId'))
    if chemin is None:
        return False
    try:
        entrees = fin_du_transcript(chemin)
    except OSError:
        return False
    clic = float(e.get('clic') or 0)
    for o in reversed(entrees):
        if o.get('type') != 'user':
            continue
        quand = parc.horodatage(o)
        if quand is not None and quand < clic - 5:
            break
        if parc.texte_de((o.get('message') or {}).get('content')).strip() == e.get('texte'):
            return True
    return False


def fiche_session(sid):
    """The app's card of a session (local_….json), or None."""
    if not SESSION_LOCALE.match(sid or ''):
        return None
    for dossier in parc.dossiers_app():
        o = parc.lire_json(dossier / f'{sid}.json')
        if isinstance(o, dict) and o.get('sessionId') == sid:
            return o
    return None


def joignable(fiche):
    """The card has what a wake needs: a CLI session id, an existing folder, and the session is not archived."""
    return (isinstance(fiche, dict) and not fiche.get('isArchived') and UUID.match(str(fiche.get('cliSessionId') or ''))
            and os.path.isdir(str(fiche.get('cwd') or '')))


def commande_reveil(exe, fiche, texte):
    """The wake: the session's own conversation, its model and effort, its permission mode or a less permissive one."""
    cmd = [exe, '--resume', fiche['cliSessionId'], '-p', texte,
           '--permission-mode', MODES.get(str(fiche.get('permissionMode') or ''), 'default')]
    modele = str(fiche.get('model') or '')
    if modele and modele != 'default' and MODELE.match(modele):
        cmd += ['--model', modele]
    if fiche.get('effort') in EFFORTS:
        cmd += ['--effort', fiche['effort']]
    return cmd


def lancer_reveil(fiche, texte, maintenant=None):
    """Starts the wake, detached (its own process group, no stdin, output in .parc/reveils/), without waiting: the
    session takes its time. Returns (pid, journal)."""
    exe = claude_terminal()
    if not exe:
        raise OSError("le Claude du Terminal est introuvable")
    REVEILS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromtimestamp(maintenant or time.time()).strftime('%Y%m%d-%H%M%S')
    journal = REVEILS / f"{stamp}-{fiche['sessionId']}.log"
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        p = subprocess.Popen(commande_reveil(exe, fiche, texte), cwd=fiche['cwd'], stdin=subprocess.DEVNULL, stdout=fd,
                             stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, env=env_terminal())
    finally:
        os.close(fd)
    _lances[p.pid] = p
    return p.pid, journal


def cle_file(sid, question):
    return f"{sid}--{question or 'seule'}"


@contextlib.contextmanager
def verrou_file():
    """The queue is shared by the app's two instances of this server: one at a time reads and writes it."""
    FILE.mkdir(parents=True, exist_ok=True)
    os.chmod(FILE, 0o700)
    fd = os.open(FILE / '.verrou', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def entrees_file():
    sortie = []
    for chemin in sorted(FILE.glob('local_*.json')) if FILE.is_dir() else []:
        e = parc.lire_json(chemin)
        if isinstance(e, dict) and SESSION_LOCALE.match(str(e.get('session') or '')):
            sortie.append(e)
    return sortie


def ecrire_entree(e):
    parc.ecrire_atomique(FILE / f"{cle_file(e['session'], e.get('question'))}.json", json.dumps(e, ensure_ascii=False))


def retirer_entree(e):
    try:
        (FILE / f"{cle_file(e['session'], e.get('question'))}.json").unlink()
    except OSError:
        pass


def journal_reponse(e, mode, **plus):
    """One JSON line per delivery (and per answer that failed or expired) in reponses-directes.log."""
    ligne = dict({'date': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'numero': e.get('question') or '',
                  'choix': e.get('choix'), 'session': e.get('titre') or e.get('session'), 'mode': mode}, **plus)
    try:
        with JOURNAL_REPONSES.open('a', encoding='utf-8') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    except OSError:
        pass


def session_de_la_reponse(l):
    """The session an answer of this line goes to, as the page computes it (sessionDeLaReponse): the one that asked
    (`source` of a chantier line), else the one the line opens."""
    if SESSION_LOCALE.match(str(l.get('source') or '')):
        return l['source']
    if l.get('ouvrir'):
        return l['ouvrir']
    if SESSION_LOCALE.match(str(l.get('cle') or '')):
        return l['cle']
    m = re.search(r'(local_[0-9a-f-]{36})$', str(l.get('lien') or ''))
    return m.group(1) if m else ''


def texte_de_la_reponse(l, choix):
    """What the session receives, word for word what the PM would paste: « Q11 go », or the answer alone for a
    question without a number, or a chantier line whose number is not the session's own (copie_numero)."""
    q = l.get('question') or ''
    return f'{q} {choix}' if q and l.get('copie_numero') is not False else choix


def lignes_vues(age_max=LIGNES_FRAICHES_S):
    """The board's lines with answer buttons, from the page's last reading, or computed again when older."""
    with CALCUL:
        if time.time() - _lignes_vues['t'] > age_max:
            lignes()
        return list(_lignes_vues['lignes'])


def ligne_de_la_reponse(sid, question, choix, liste):
    """The open line this answer belongs to: same session, same question, and the answer is one of its closed choices."""
    for l in liste:
        if session_de_la_reponse(l) == sid and (l.get('question') or '') == question \
                and isinstance(l.get('choix'), list) and choix in l['choix']:
            return l
    return None


def attente_pour(sid, question):
    """The wait of a session in its Stop hook on this question, if the hook holds one."""
    connues = None
    for a in AUTORISATIONS.en_attente_de_reponse():
        if a.numero != question:
            continue
        s = a.sessionId
        if not s:
            connues = sessions_connues() if connues is None else connues
            s = connues.get(a.session, (None, None))[0]
        if s == sid and not a.fini.is_set():
            return a
    return None


def livrer(e, maintenant, vivantes=None):
    """Under the queue's lock: delivers `e` now when its session is asleep, else leaves it waiting. Returns the mode:
    'reveil' (woken), 'file' (waits), or 'echec' (the session cannot be joined; `e` says why)."""
    fiche = fiche_session(e['session'])
    if not joignable(fiche):
        e.update(etat='echec', raison='session', fin=maintenant)
        ecrire_entree(e)
        journal_reponse(e, 'echec', raison='session')
        return 'echec'
    vivantes = sessions_vivantes() if vivantes is None else vivantes
    if session_vivante(e['session'], fiche.get('cliSessionId'), vivantes):
        # Case c: only a process whose turn is over is stopped; then nobody may hold the session again before the wake.
        if not arreter_au_repos(e, fiche, maintenant):
            return 'file'
        if session_vivante(e['session'], fiche.get('cliSessionId'), sessions_vivantes()):
            return 'file'
        if vivantes is not None:
            vivantes[0].discard(e['session'])
    try:
        pid, journal = lancer_reveil(fiche, e['texte'], maintenant)
    except OSError as exc:
        e.update(etat='echec', raison='lancement', fin=maintenant)
        ecrire_entree(e)
        journal_reponse(e, 'echec', raison=f'lancement : {exc}')
        return 'echec'
    if vivantes is not None:
        vivantes[0].add(e['session'])   # another answer to this session waits for this wake to end: never two at once
    e.update(etat='livree', livree=maintenant, pid=pid, journal=journal.name, essais=int(e.get('essais') or 0) + 1,
             autorisation=MODES.get(str(fiche.get('permissionMode') or ''), 'default'))
    ecrire_entree(e)
    journal_reponse(e, 'reveil', attendue_depuis=int(maintenant - e['clic']), journal=journal.name,
                    apres_arret=bool(e.get('arret')))
    return 'reveil'


def repondre_session(arguments):
    """`repondre` without `id`: the click on a line whose session does not wait on the page (cases a, b, c above)."""
    sid, question, choix = arguments.get('session') or '', arguments.get('question') or '', arguments.get('choix')
    if not SESSION_LOCALE.match(sid):
        raise ValueError('identifiant de session invalide')
    if not isinstance(question, str) or not NUMERO_QUESTION.match(question):
        raise ValueError('numéro de question invalide')
    if not isinstance(choix, str) or not (CHOIX_POSSIBLE.match(choix) or (not question and LIBELLE_POSSIBLE.match(choix))):
        raise ValueError('réponse hors liste : seules les réponses fermées de la ligne sont acceptées')
    ligne = ligne_de_la_reponse(sid, question, choix, lignes_vues())
    if ligne is None:
        raise ValueError("réponse hors des choix de la ligne, ou question déjà réglée : réponds dans la session")
    texte = texte_de_la_reponse(ligne, choix)
    maintenant = time.time()
    att = attente_pour(sid, question) if interrupteur_reponses() else None
    if att is not None and choix in att.choix:
        repondre_attente({'id': att.id, 'choix': choix})
        return {'mode': 'directe', 'texte': texte, 'clic': int(maintenant * 1000)}
    if not REVEIL_POSSIBLE:
        return {'mode': 'copie', 'raison': 'systeme', 'texte': texte}
    if not terminal_connecte(maintenant):
        return {'mode': 'copie', 'raison': 'terminal', 'texte': texte}
    fiche = fiche_session(sid)
    if not joignable(fiche):
        return {'mode': 'copie', 'raison': 'session', 'texte': texte}
    e = {'session': sid, 'question': question, 'choix': choix, 'texte': texte, 'etat': 'en_file', 'clic': maintenant,
         'titre': str(fiche.get('title') or '')[:120]}
    with verrou_file():
        ecrire_entree(e)    # replaces an answer to the same question that was not delivered yet
        mode = livrer(e, maintenant)
    if mode == 'echec':
        with verrou_file():
            retirer_entree(e)
        return {'mode': 'copie', 'raison': e.get('raison') or 'session', 'texte': texte}
    return {'mode': mode, 'texte': texte, 'clic': int(maintenant * 1000)}


def recolter():
    """Reaps the wakes this instance started; returns {pid: exit code} of those that ended."""
    fins = {}
    for pid, p in list(_lances.items()):
        code = p.poll()
        if code is not None:
            fins[pid] = code
            del _lances[pid]
    return fins


def journal_deconnecte(nom):
    """True when a wake's output says the Terminal's Claude is not logged in."""
    try:
        with open(REVEILS / nom, 'rb') as f:
            texte = f.read(8192).decode('utf-8', 'replace')
    except OSError:
        return False
    return bool(DECONNECTE.search(texte))


def tour_de_file(maintenant=None, vivantes=None):
    """One pass of the watcher: expires, delivers what a sleeping session can take, and notes how each wake ended."""
    if not REVEIL_POSSIBLE or not FILE.is_dir():
        return
    maintenant = maintenant or time.time()
    fins = recolter()
    if not entrees_file():
        return
    with verrou_file():
        for e in entrees_file():
            age = maintenant - float(e.get('clic') or 0)
            if age > GARDE_S:
                retirer_entree(e)
            elif e.get('etat') == 'en_file':
                if age > FILE_S:
                    e.update(etat='expiree', fin=maintenant)
                    ecrire_entree(e)
                    journal_reponse(e, 'expiree')
                    continue
                att = attente_pour(e['session'], e.get('question') or '') if interrupteur_reponses() else None
                if att is not None and e['choix'] in att.choix:
                    try:
                        repondre_attente({'id': att.id, 'choix': e['choix']})
                        e.update(etat='livree', livree=maintenant, fini=True, par='attente')
                        ecrire_entree(e)
                    except ValueError:
                        pass
                    continue
                if vivantes is None:
                    vivantes = sessions_vivantes()
                fiche = fiche_session(e['session'])
                if joignable(fiche) and session_vivante(e['session'], fiche.get('cliSessionId'), vivantes) and not (
                        int(e.get('arrets') or 0) < ARRETS_MAX and au_repos(e['session'], fiche, maintenant)):
                    continue   # its turn goes on: the answer waits
                # The session is asleep: deliver only an answer whose question is still open (the PM may have
                # answered in the session meanwhile) and while the Terminal is logged in.
                try:
                    ouverte = ligne_de_la_reponse(e['session'], e.get('question') or '', e['choix'], lignes_vues(0))
                except Exception as exc:   # the board could not be computed: try again at the next pass
                    noter(f"file · lignes : {exc!r}")
                    continue
                if ouverte is None:
                    e.update(etat='sans_objet', fin=maintenant)
                    ecrire_entree(e)
                    journal_reponse(e, 'sans_objet')
                elif not terminal_connecte(maintenant):
                    e.update(etat='echec', raison='terminal', fin=maintenant)
                    ecrire_entree(e)
                    journal_reponse(e, 'echec', raison='terminal')
                else:
                    livrer(e, maintenant, vivantes)
            elif e.get('etat') == 'livree' and not e.get('fini'):
                pid = e.get('pid')
                if not e.get('recue') and recue_par_la_session(e):
                    e['recue'] = maintenant
                    ecrire_entree(e)
                if isinstance(pid, int) and pid not in fins and (pid in _lances or pid_vivant(pid)):
                    continue
                e['fini'] = maintenant
                if pid in fins:
                    e['code'] = fins[pid]
                if e.get('recue'):
                    pass   # the session has the answer, whatever happened to its turn afterwards
                elif e.get('journal') and journal_deconnecte(e['journal']):
                    e.update(etat='echec', raison='terminal')
                    noter_terminal(False, 'reveil')
                    _auth.update(t=0.0, ok=None)
                    journal_reponse(e, 'echec', raison='terminal')
                elif e.get('code') not in (None, 0) and int(e.get('essais') or 1) < ESSAIS_MAX:
                    # The wake ended on an error before the session got the answer: back in the queue, once.
                    journal_reponse(e, 'echec', raison='reveil', code=e['code'], encore=True)
                    for k in ('pid', 'livree', 'fini', 'journal'):
                        e.pop(k, None)
                    e['etat'] = 'en_file'
                elif e.get('code') not in (None, 0):
                    # Again (session deleted, model refused, crash): the answer did not reach the session, and the
                    # page must not say it was sent.
                    e.update(etat='echec', raison='reveil')
                    journal_reponse(e, 'echec', raison='reveil', code=e['code'])
                ecrire_entree(e)


def surveiller_file():
    while True:
        time.sleep(TOUR_S)
        try:
            tour_de_file()
        except Exception as exc:   # the watcher never stops the server
            noter(f"file · échec : {exc!r}")


def file_pour_la_page():
    """The answers given to sessions that did not wait, for the page's lines (field `en_file` of `attentes`)."""
    if not REVEIL_POSSIBLE:
        return []
    sortie = []
    for e in entrees_file():
        ms = lambda t: int(float(t) * 1000) if t else None
        sortie.append({'session': e['session'], 'question': e.get('question') or '', 'choix': e.get('choix'),
                       'texte': e.get('texte'), 'etat': e.get('etat'), 'raison': e.get('raison') or '',
                       'clic': ms(e.get('clic')), 'livree': ms(e.get('livree')), 'fini': bool(e.get('fini')),
                       'recue': ms(e.get('recue'))})
    return sortie


def repondre(msg_id, resultat=None, erreur=None):
    sortie = {'jsonrpc': '2.0', 'id': msg_id}
    if erreur:
        sortie['error'] = erreur
    else:
        sortie['result'] = resultat
    sys.stdout.write(json.dumps(sortie, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def traiter(msg):
    methode, msg_id, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
    if msg_id is None:
        return  # notification (initialized, cancelled…) : rien à répondre
    if methode == 'initialize':
        CLIENT.update(params.get('clientInfo') or {})
        noter(f"démarrage · client {CLIENT.get('name', '?')} {CLIENT.get('version', '')}")
        repondre(msg_id, {'protocolVersion': params.get('protocolVersion') or '2025-06-18',
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'mon-studio', 'version': VERSION}})
    elif methode == 'ping':
        repondre(msg_id, {})
    elif methode == 'tools/list':
        repondre(msg_id, {'tools': OUTILS})
    elif methode == 'tools/call':
        nom, debut = params.get('name'), time.time()
        try:
            if nom == 'lignes':
                donnees = lignes()
            elif nom == 'ouvrir':
                donnees = ouvrir(params.get('arguments'))
            elif nom == 'projet':
                donnees = projet(params.get('arguments'))
            elif nom == 'autorisations':
                donnees = autorisations()
            elif nom == 'decider':
                donnees = decider(params.get('arguments'))
            elif nom == 'attentes':
                donnees = attentes()
            elif nom == 'repondre':
                arguments = params.get('arguments') or {}
                donnees = repondre_attente(arguments) if arguments.get('id') else repondre_session(arguments)
            elif nom == 'clore':
                donnees = clore(params.get('arguments'))
            elif nom == 'lire':
                donnees = lire(params.get('arguments'))
            elif nom == 'gabarit':
                donnees = gabarit()
            elif nom == 'matin_ecrire':
                donnees = matin_ecrire(params.get('arguments'))
            elif nom == 'conflits_juger':
                donnees = conflits_juger(params.get('arguments'))
            elif nom == 'slack_ouvertes':
                p = charger_projets()
                donnees = {'pm': p.identite() or '', 'lignes': p.slack_ouvertes()}
            elif nom == 'slack_juger':
                with CALCUL:
                    donnees = charger_projets().slack_juger((params.get('arguments') or {}).get('jugements'))
            else:
                repondre(msg_id, erreur={'code': -32602, 'message': f'outil inconnu : {nom}'})
                return
            noter(f"{nom} · client {CLIENT.get('name', '?')} · {time.time() - debut:.2f} s")
            repondre(msg_id, {'content': [{'type': 'text', 'text': json.dumps(donnees, ensure_ascii=False)}]})
        except Exception as exc:  # l'outil répond en échec, le serveur reste debout
            noter(f"{nom} · échec : {exc!r}")
            repondre(msg_id, {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})
    else:
        repondre(msg_id, erreur={'code': -32601, 'message': f'méthode inconnue : {methode}'})


def main():
    if AUTORISATIONS.demarrer():
        atexit.register(AUTORISATIONS.arreter)
    if REVEIL_POSSIBLE:
        threading.Thread(target=surveiller_file, daemon=True).start()
    for ligne in sys.stdin:
        if not ligne.strip():
            continue
        try:
            msg = json.loads(ligne)
        except ValueError:
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            if isinstance(m, dict):
                traiter(m)
    AUTORISATIONS.arreter()


if __name__ == '__main__':
    main()
