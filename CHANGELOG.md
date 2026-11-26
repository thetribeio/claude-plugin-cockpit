# Changelog

## 0.3.26 · 2026-11-26 · réglage du modèle et contrôle du barème pour tous les PM

Le barème modèle et effort passe d'un texte à deux hooks, pour tous les PM. Effet pour le PM : chaque session démarre au réglage qui convient à sa demande, et un sous-agent ou une session lancée ne part plus en Opus ou en Fable sans raison.

- Réglage d'ouverture (`hooks/reglage_ouverture.py`) : au premier message d'une session, la consigne de régler soi-même son modèle et son effort selon le barème (`set_session_model`, `set_session_effort`) et de l'annoncer en une ligne. Pour Fable et Opus high, la session propose et attend le oui du PM. La règle 6 de `regles/modele-effort.md` le dit ; le plafond des règles passe de 10 000 à 10 500 octets pour elle (10 369).
- Contrôle du barème (`hooks/bareme_modele.py`) : un sous-agent en Opus ou Fable est refusé sans « [modèle justifié] <raison> » dans son prompt ; une session lancée est refusée sans modèle, ou en Fable sans « [fable demandé] ». Un fork, une offre et un `proposal_id` passent. Une session sans modèle que le contrôle du modèle au lancement refuse déjà ne reçoit qu'un refus.
- Allumés par défaut ; `install.py switch reglage-ouverture off` et `switch controle-bareme off` les coupent (`reglage_ouverture`, `controle_bareme` dans cockpit.json), et le plan d'installation les annonce.
- Un PM qui a déjà sa propre copie de l'un de ces hooks dans `~/.claude/hooks/` (ou sous `$CLAUDE_CONFIG_DIR`) ne la reçoit pas deux fois : celui du plugin se tait tant que la copie est là, et la copie peut être retirée.
- Limites connues : le coût de la consigne d'ouverture (environ 250 tokens par session, relus ensuite) n'est pas mesuré ; aucun des deux hooks n'a encore été vu en session réelle sous le plugin, seulement dans leur version personnelle.

## 0.3.26 · 2026-11-26 · Mon Studio : le moteur ne devine plus ce que personne ne lui demande

Retrait de chemins de détection du texte libre, mesurés inutiles sur 4 806 fins de tour réelles des six dernières semaines. Effet pour le PM : les lignes affichées sur les sept derniers jours sont les mêmes, sauf deux lignes « Vérifier » qui citaient un geste à l'impératif (« Range cette session-ci. » devient « Ne dit pas si elle attend quelque chose de toi » ; une ancienne ligne disparaît). Une session dit ce qu'elle attend par ses questions numérotées ou par « Rien à faire de ton côté ».

- Plus de lecture des gestes dans le texte libre (impératif, « tu peux », « à coller », case à cocher, bloc à coller), des éléments d'une section « pour toi » ni des propositions de Claude : le tri ne garde que les feux verts, les décisions demandées et les questions.
- Plus de chemins qui ne se déclenchaient jamais : question « soldée » ou « sans objet », phrase qui parle d'une demande, demande annoncée pour plus tard, « tu peux » facultatif, « jamais à toi », partie « À trancher » qui se dit vide. Plus de lecture générale de « Rien n'est attendu de toi » : seule la formule du PM (« Rien à faire de ton côté ») et celles de son glossaire comptent.
- Plus de ligne de repli pour un rappel sans numéro (« Encore ouvert : l'étape 3, dans l'encadré »). La boîte restée ouverte reste lue pour le rangement, qui ne range pas une telle session.
- Retrait du code mort de la page : blocs couleur, grises, studios et silencieux du calcul de l'écran, listes `lignes` et `reste` des sessions.
- Gardés : le tri central, les questions numérotées, le glossaire, le type des lignes, et l'intitulé en gras « À faire de ton côté » lu comme un titre.
## 0.3.26 · 2026-11-26 · les règles de travail du PM ne valent que dans un Studio

Les règles du PM et leurs contrôles ne s'appliquent plus à toutes les sessions du poste, seulement à celles ouvertes dans un Studio. Effet pour le PM : une session de développement, ou d'un autre plugin, ne reçoit plus le format « À trancher », la ligne de rappel, le rappel de session lourde ni la proposition de rangement, et ses sous-agents ne sont plus refusés faute de modèle. (Point d'audit soulevé par un développeur ; accord du PM.)

- Une session « de Studio » est une session dont le dossier est, ou est sous, un Studio de `projets.json`, un dossier avec `.claude/.studio-manifest.json`, ou `~/Mon Studio` ; la copie de travail de l'app compte comme son dépôt. Un petit fichier commun, `hooks/perimetre.py`, le décide, sans modèle (environ 45 ms), et sert aux règles au démarrage, à la ligne de rappel (gardée dans `hooks.json`), au rappel de session lourde, à la proposition de rangement et au refus de lancement sans modèle.
- Reste partout, car c'est de la mécanique : mise à jour du code copié, relais des autorisations, instantané des projets, brouillons, calcul de la liste à ranger, réponses en direct, lignes retirées.
- `regles_dossiers` (liste de dossiers en plus, vide par défaut) et `regles_partout: true` (revient à l'ancien comportement) dans `cockpit.json`. Au moindre doute, fichier illisible ou dossier inconnu, les règles restent posées.
- Mesuré sur 521 sessions des 30 derniers jours : 331 gardent les règles, 190 les perdent, dont 136 dans le dépôt du plugin cockpit lui-même ; à décider s'ils vont dans `regles_dossiers`. Rien n'y est ajouté ici.
- Reste à brancher après fusion : le contrôle de format des questions de fin de tour (`format_questions.py`).
## 0.3.26 · 2026-11-26 · fin de tour : la réponse finit toujours par « À trancher » ou « Rien à faire de ton côté »

Une réponse qui ne finit par aucun des deux est renvoyée une fois à sa session, qui ajoute l'un ou l'autre. Effet pour le PM : Mon Studio n'a plus à deviner ce qu'une session attend de lui. Mesure sur les fins de tour des 14 derniers jours : 3,5 % renvoyées (40 sur 1 132), dont 14 sur un échantillon de 20 sont de vrais oublis. (PM, 2026-11-26.)

- Le contrôle de format (`format_questions.py`) lit aussi les messages sans question : ni bloc « À trancher » / « To decide », ni question numérotée, ni « Encore ouvert », ni « Rien à faire de ton côté » / « Nothing to do on your side. » dans le dernier paragraphe (casse, ponctuation et point final tolérés).
- Jamais de boucle (rien après un renvoi, `stop_hook_active`), rien sur un message de moins de 200 caractères (point d'étape pendant qu'une session attend ses agents), ni sur un tour sans texte, une tâche planifiée ou une session lancée par une autre (sauf remontée au premier niveau). Chaque renvoi s'ajoute au journal, sans le texte, avec `sans_fin`.
- Interrupteur propre : `controle_fin_de_tour: false` dans cockpit.json (`install.py switch controle-fin-de-tour off`), allumé par défaut ; couper `controle_format` coupe les deux.
## 0.3.26 · 2026-11-26 · Mon Studio : les sessions ne peuvent plus répondre à ta place

Ce qui change : l'installation de Mon Studio refuse aux sessions les trois gestes de ta page, répondre à une question (`repondre`), autoriser ou refuser une demande d'outil (`decider`) et fermer une ligne (`clore`).
Pourquoi : un audit a relevé que rien n'empêchait une session de les appeler : elle pouvait répondre ou accorder une autorisation à la place du PM. Le garde-fou du connecteur ne s'appliquait pas aux sessions de l'app. (PM, accord du 2026-11-26.)
Effet pour le PM : sa page marche comme avant ; aucune session ne répond, n'autorise ni ne ferme plus rien à sa place.

- `install.py apply` (et `repair`) ajoute à `~/.claude/settings.json`, dans `permissions.deny`, les règles `mcp__mon-studio__repondre`, `mcp__mon-studio__decider` et `mcp__mon-studio__clore`, après une copie datée du fichier ; rien n'est écrasé, aucune règle n'est ajoutée en double. Cela fait partie de l'installation de base, sans interrupteur : c'est une protection, et elle n'autorise rien. Un fichier illisible n'est jamais écrit : l'installateur le dit.
- `plan` l'annonce avant le go ; `status` rend `actionsRefusees` (`present`, `missing`, `unreadable`) et `refusPoses`, et le `todo` `refuse_actions` quand il en manque.
- `disable` retire seulement les règles que l'installateur a posées lui-même (gardées dans `cockpit.json`, `refus_poses`) : une règle que le PM avait déjà reste.
- Les descriptions des trois outils du connecteur et son en-tête disent que les sessions en sont empêchées par cette règle. Le code du connecteur ne change pas.
- Jusqu'ici, seul `apply --autorisations` touchait aux réglages ; désormais `apply` et `repair` y ajoutent aussi ce refus, et seulement lui.
## 0.3.25 · 2026-11-26 · Mon Studio : un outil long n'est plus une autorisation

Ce qui change : une session qui fait tourner un outil long (une suite de tests de 10 minutes, un sous-agent) ne monte plus au tableau comme « Session arrêtée sur une autorisation : à rouvrir ». Le tableau ne parle d'autorisation que si une demande a vraiment été faite : chaque demande d'autorisation laisse une trace (l'heure et le nom de l'outil, rien de ce qu'il ferait) dans `~/Mon Studio/.parc/demandes-autorisation/`, que l'allumage des autorisations depuis la page soit actif ou non. Sans trace, la session travaille ; silencieuse plus de 30 minutes, elle est « arrêtée en plein travail », sans autorisation.
Pourquoi : le PM, 2026-11-26 : deux sessions en pleine suite de tests affichées comme arrêtées sur une autorisation. Au-delà de 3 minutes sans écrire, un outil sans résultat passait pour une autorisation en attente.

## 0.3.25 · 2026-11-26 · un seul tri, partout

« D'abord » ne se remplit plus de vieilles demandes de l'ingestion, et le même ordre vaut sur Mon Studio, dans la vue projet et dans le point du matin. Effet pour le PM : ce qui est tout en haut est ce qui presse, et la vue projet casse son gros bloc en bandes. (PM, Q5 à Q8, 2026-11-25/26)

- **« Prénom attend » dure 7 jours (Q5).** Une demande de l'ingestion qui commence par « Prénom attend/demande » est « fort » pendant 7 jours après son apparition ; ensuite elle passe dans « Ensuite », à son rang de récence, avec la mention « Prénom attend depuis N j ». Une demande retardée ou marquée urgente reste en haut, quel que soit son âge. Une session qui attend (« une session attend ») ne rend « fort » que pendant 24 h, comme son rang le faisait déjà.
- **Ordre de « D'abord » (Q6).** Les passages planifiés arrêtés d'abord ; puis les lignes en retard, l'échéance la plus ancienne d'abord ; puis les échéances, la plus proche d'abord ; puis les autres lignes fortes (blocages, « Prénom attend », mots clés), la plus récente d'abord. Une échéance sans origine connue compte, et la ligne dit « échéance JJ/MM · origine inconnue » (le kit d'ingestion n'écrit pas encore ce champ : mesuré le 2026-11-25, aucune des 6 échéances n'en avait).
- **Vue projet (Q7).** Mêmes titres de bande que le tableau (« D'abord · n », « Ensuite · n »), « Peut attendre » replié ; une bande vide n'a pas de titre, et « Ensuite » n'en a un que sous un « D'abord ».
- **Point du matin (Q8).** Les listes par projet suivent le tableau : échéance proche, puis la plus récente d'abord. Les projets sont classés par urgence, puis par récence de leur ligne la plus récente, plus par ordre alphabétique.
- **À savoir.** Une demande « Prénom attend » de plus de 7 jours ne va plus dans « Anciennes » tant qu'elle a moins de 21 jours : sans cela elle y serait tombée au même moment (« Anciennes » commence aussi à 7 jours), et la règle n'aurait rien changé. Au-delà de 21 jours, elle est ancienne comme les autres. Essayé sur les vraies données du 2026-11-26 : le tableau passe de 6 à 6 lignes en « D'abord » (aucune demande « Prénom attend » n'a encore 7 jours), l'ordre change, et « Dire à Léo … mode clair » descend sous les arrêts de session.
- Limites connues : l'âge « depuis N j » est celui du dernier calcul du Mac, il ne bouge pas page ouverte ; la limite de 7 jours n'a pu être essayée sur de vraies données que par un calcul rejoué (aucune demande réelle n'a encore passé 7 jours).

## 0.3.24 · 2026-11-26 · Mon Studio : boutons de réponse sous la question

Les boutons de réponse passent sous la question, côte à côte ; « Agir » garde « Ouvrir ↗ » et des icônes sur une ligne (nom au survol). Effet pour le PM : le tableau est 44 % moins haut (mesure sur 76 vraies lignes : 13 003 → 7 280 px). (PM, Q2, 2026-11-26)

## 0.3.24 · 2026-11-26 · Mon Studio : titre de question sans « : »

Une question écrite « Qn · Titre ? question » sans « : » garde un titre court sur sa ligne de Mon Studio, et la session est renvoyée pour la réécrire au format. Effet pour le PM : plus de ligne dont le titre court jusqu'à 278 caractères parce que la question collée au titre en faisait partie. (PM, 2026-11-26)

- Mon Studio coupe le titre au premier « ? » (gardé) quand il n'y a pas de « : » ; avec un « : », rien ne change. Le contrôle de fin de tour renvoie la session (`sans_deux_points`) : « Qn · <titre> : <question> ». Une ligne « Qn · Titre ? : question », ou un titre seul suivi de ses options, passe.
- Mesure sur les sessions du 20 au 25/11 (612 questions lues, 474 distinctes) : 11 questions distinctes sans « : » (13 fois dans les messages) ; leur titre faisait 60 caractères au plus pour 1 sur 11 avant, 10 sur 11 après (le plus long passe de 278 à 51 caractères). Fausses alertes sur les questions bien écrites : 0 sur 463. Les titres en gras fermé (« **Qn · Titre ?** question ») ne sont pas touchés : le gras fermant sépare déjà.

## 0.3.24 · 2026-11-26 · Mon Studio : une ligne « Relire » porte son document

Une ligne de relecture montre « Ouvrir le document ↗ » à côté de « C'est bon » et « Corrections ». Effet pour le PM : il lit le compte rendu, le mail ou l'artifact, puis répond sans ouvrir la session. (PM, Q1 du 2026-11-17, confirmée le 2026-11-25 ; point 1 de « À faire ensuite » de la 0.2.30.)

- Le lien est lu dans la question, sans modèle : « Pièce : <lien> », sinon le premier lien vers un document (artifact Claude, Google Docs ou Drive, Notion, wiki). Un lien d'autre nature n'est pas proposé. Un fichier du Studio se lit dans la page, comme avant. Mesure sur le tableau du 2026-11-25 : 0 ligne « Relire » sur 8 portait sa pièce avant, 1 sur 8 après (les sessions n'écrivaient pas le lien).
- La règle 2 demande « Pièce : <lien du document> » sur toute relecture ; le contrôle de fin de tour renvoie la session qui relit sans lien ni fichier (`relecture_sans_piece`).

## 0.3.23 · 2026-11-26 · Mon Studio : projets masqués

Ce qui change : une liste de projets que Mon Studio ne lit plus (`projets_masques` dans `~/Mon Studio/.parc/cockpit.json`, une liste de dossiers) : ni tableau, ni vue projet, ni liste des projets, ni brief du matin.
Pourquoi : un PM ne suit plus certains projets et ne veut plus les voir sur Mon Studio (avant une démo), sans archiver leurs sessions.
Effet : leurs sessions restent dans la barre latérale de l'app, rien n'est archivé ni modifié ; un dossier masque ses sous-dossiers et les copies de travail de son dépôt, jamais un dossier homonyme (« SEO » ne masque pas « SEO EF »).

## 0.3.22 · 2026-11-25 · rangement : sans demander, toutes les sessions vérifiées

L'essai du rangement sans demander a réussi : en mode auto, l'app a archivé la session visée, sans demande au PM, après une revérification. Effet pour le PM : avec `rangement_sans_demander` allumé, chaque jour toutes les sessions finies vérifiées sont rangées d'un coup, et une ligne « Rangé : … » le dit, au lieu d'une seule par jour. (PM, Q4, 2026-11-25)

- Restent exclues : les sessions qu'il a gardées quand on les lui a proposées (7 jours), celles qu'il a ouvertes lui-même, celles qui attendent une réponse, et les sessions de backlog dont l'epic n'est pas poussée dans Jira.

## 0.3.21 · 2026-11-25 · rangement : une session de backlog n'est jamais rangée avant le push Jira

Le rangement garde aussi une session d'écriture de backlog en pause pour relecture. Effet pour le PM : les fiches epic et les tickets écrits seulement dans le Studio ne sont ni proposés au rangement ni archivés, même par l'accord permanent, tant que leur epic n'est pas poussée dans Jira. (PM, 2026-11-25 : « elles, il ne faut pas y toucher »)

- Une session qui cite le dossier `fiche-epic` d'une epic est gardée comme celle qui cite son dossier `pret-a-dev`, tant que `pret-a-dev/05-jira/cles-jira.json` n'existe pas. Une session qui lit une epic déjà poussée comme modèle en écrivant une autre reste donc gardée.
- Une session qui a utilisé le plugin backlog (une commande `/backlog:…`, une compétence ou un agent `backlog:`) sans citer aucun dossier d'epic est gardée, avec la raison « écriture de backlog (plugin backlog) : rien de poussé dans Jira n'est connu ». Limite : elle reste gardée jusqu'à ce que le PM la range à la main.
- Une session proposée au PM et qu'il a gardée n'est jamais archivée sans lui demander pendant 7 jours, même avec `rangement_sans_demander` (PM, 2026-11-25 : « les autres garde-les pour l'instant »). La revérification ne porte que sur les sessions nommées par la proposition (`confirmer --ids`), et la session n'archive que celles que le PM accepte.

## 0.3.20 · 2026-11-25 · Mon Studio : les questions relayées restent dans leur session

Une session qui rappelle les questions d'une autre (« [autre session](lien) attend toujours tes réponses à ses questions Q40 à Q43 ») ne fait plus de lignes à son nom. Effet pour le PM : plus de lignes « Q40 · Une question t'attend dans cette session » avec « Question introuvable », dont le bouton « Ouvrir » menait à la mauvaise session ; ces questions restent sous la session qui les a posées. (PM, 2026-11-25, capture de Mon Studio.)

- Une phrase qui porte le lien d'une session n'est plus lue comme un rappel des questions de la session qui l'écrit. La même phrase sans lien (« J'attends toujours tes réponses à Q40 et Q43 ») reste lue comme avant.

## 0.3.19 · 2026-11-25 · rangement : la proposition revient dans ta session, une fois par jour

Une fois par jour, une de tes sessions te propose de ranger les sessions finies, à la fin de sa réponse. Effet pour le PM : il n'a plus à penser au bouton « Ranger » de Mon Studio ; il répond « 1 » et la session archive, ou « 2 » et rien ne bouge. (PM, Q7, 2026-11-25 : proposer d'abord, puis tester l'autonomie.)

- Au premier message du PM de la journée dans une session de premier niveau de l'app de bureau, le hook demande à la session de finir sa réponse par la question « Qn · Ranger N sessions finies ? », dont il donne le texte : les sessions ont été lancées par Claude ou par d'autres sessions, ne font plus rien depuis X jours, ce qu'elles ont produit est enregistré au Studio, aucune n'attend de réponse ; une ligne par session, son titre lié et sa raison en clair ; « 1) Les ranger (recommandé) », « 2) Les garder ». Le hook n'ordonne aucun archivage : c'est la réponse du PM qui vaut accord, comme le 2026-11-23 quand l'app a accepté l'archivage demandé par le PM dans sa session.
- Rien n'est proposé dans une session lancée par une autre, sur un message venu d'une autre session ou de l'app, dans une tâche programmée, hors de l'app de bureau, ni avec une liste calculée il y a plus de 24 h. Une session redevenue active ou déjà archivée sort de la liste ; la session où l'on travaille n'y est jamais.
- Sur le « 1 », la session lance `rangement.py confirmer` : il revérifie la liste (une session redevenue active en sort ; un worktree avec des fichiers non enregistrés ou des lignes jamais entrées dans main la garde, par `archive_check.py`, remis dans le plugin) et note les sessions confirmées dans `.parc/ranger.json`, comme le bouton, pour que « Rangées aujourd'hui » suive. Puis elle archive celles-là seulement.
- Interrupteurs : `rangement_propose` (allumé par défaut, `install.py switch rangement-propose on|off`) ; `rangement_auto: false` coupe aussi la proposition. `rangement_sans_demander` (coupé par défaut, `switch rangement-sans-demander on|off`) est l’essai d’un accord permanent : la session archive sans poser la question une session vérifiée par jour pendant l’essai, puis le dit en une ligne. `rangement.py proposer --apercu` montre la proposition du jour sans rien noter.

## 0.3.18 · 2026-11-24 · rangement : une session de tickets attend le push Jira

Le rangement garde une session de tickets prêts à dév tant que les tickets de son epic ne sont pas poussés dans Jira. Effet pour le PM : les micro-sessions d'une epic (une par ticket) restent toutes dans la liste jusqu'au push, au lieu d'être proposées au rangement dès qu'elles sont finies. (PM, 2026-11-24 : « je garde toutes ces micro-sessions par EPIC tant qu'elles ne sont pas poussées sur JIRA »)

- Une session est gardée, avec la raison « tickets de l'epic <dossier de l'epic> pas encore poussés dans Jira », quand ses appels d'outils citent un chemin `…/pret-a-dev/…` d'une epic du plugin backlog dont le fichier `pret-a-dev/05-jira/cles-jira.json` (écrit par le push) n'existe pas encore. Les chemins avec espaces et parenthèses (Drive partagé) et les chemins relatifs au dossier de la session sont lus.
- Un dossier d'epic qui n'existe plus ne garde rien ; un transcript illisible garde la session (au moindre doute, on garde). La lecture se fait sans modèle, seulement pour une session qui passe déjà toutes les autres conditions.
- Limite connue : la règle lit les chemins cités dans les appels d'outils ; une session qui a travaillé sur une epic sans jamais citer son dossier `pret-a-dev` n'est pas reconnue.

## 0.3.17 · 2026-11-24 · onglet Conflits : une seule liste « À trancher », passe complète tous les 30 jours

Mon Studio suggère une passe complète des conflits tous les 30 jours. Effet pour le PM : il est relancé quand l'ingestion, qui n'inscrit pas tout, a pu laisser passer des conflits.

- L'onglet « Conflits » liste chaque conflit une seule fois, sous « À trancher » : celui qu'une session pose en ce moment porte la mention « posé maintenant » et son bouton « Répondre dans … ». Les questions de la session qui ne portent sur aucun cas restent à part (« Questions de la session ») ; une question numérotée du message de la session (« Q29 · … ») s'y montre mais n'est pas comptée. Le rapprochement se fait sans LLM : le sujet du cas dans la question, ou au moins 4 mots significatifs communs avec son sujet et ses valeurs.
- Chaque passage de l'ingestion inscrit les nouveaux conflits au registre `projet/conflits.md` au fur et à mesure qu'il les trouve, sans les trouver tous. Mon Studio suggère donc une passe complète, comme à l'onboarding : une ligne « Refaire une passe complète des conflits » dans « Ce qui t'attend », et dans l'en-tête de l'onglet « Conflits » « Dernier passage complet il y a N jours : une nouvelle passe rattrape ce que l'ingestion n'a pas vu » avec le bouton « Refaire une passe complète ↗ » (`/cockpit:conflits rattrapage` copié). La suggestion vient 30 jours après « Dernier passage » ; la période se règle par Studio (`repasse_jours`, de 1 à 365, dans `projet/.conflits/reglages.json`). « Fait » la ferme jusqu'à la période suivante ; une nouvelle passe la remet à zéro. Un Studio jamais vérifié garde sa ligne « Vérifier les conflits du Studio, une fois ».

## 0.3.16 · 2026-11-24 · coût du premier relevé des conflits

Ce qui change : le jugement des lots du premier relevé des conflits est lancé par le script, un appel Sonnet sans outil par lot, au lieu de sous-agents de la session.
Pourquoi : chaque sous-agent portait environ 78 000 tokens de socle pour 16 000 tokens d'extraits, et la session Opus payait trois appels par lot, son contexte grossissant à chaque lot ; un PM a vu son estimation peser une grosse part de sa semaine.
Effet sur le coût : 64 sujets jugés pour 0,51 $ mesurés (1,76 $ annoncés avant) ; estimations 4,76 $ → 1,97 $ pour 64 sujets, 27,9 $ → 6,9 $ pour 307, 39,9 $ → 9,0 $ pour 393 ; 158 $ → 57 $ sur les 33 Studios clients, soit 2,5 à 4,5 fois moins pour un Studio de 60 sujets ou plus, 1,4 fois pour un petit Studio (la session reste).

- `conflits.py juger-lots <plan>` juge chaque lot par `claude -p` (Sonnet, effort medium, sans outil, sans règles ni CLAUDE.md, sans serveur MCP, sans cache), trois à la fois, avec la même consigne que la passe du lundi et les mêmes contrôles qu'un jugement de sous-agent ; un sujet refusé (un code dans son titre) ou manquant est redemandé une fois, seul. Il enchaîne `juger` et rend l'aperçu, précédé du coût réel ; chaque appel est noté dans `<plan>.couts.json`. La session le lance en arrière-plan : un appel au lieu de trois par lot.
- Rien ne change dans ce que le jugement décide ni dans ce qui est écrit : mêmes classes, mêmes règles de titre et de contexte, même registre, mêmes documents. Sur deux lots jugés des deux façons, 14 classements sur 16 identiques ; les deux autres posent la question au PM au lieu de « rien ».
- Repli : sans `claude` en ligne de commande, ou pour un lot qu'il n'a pas pu juger, il le dit (code 3) et la session reprend les sous-agents d'avant, pour ces lots seulement. L'estimation suit le mode qui jugera ; Mon Studio recalcule ses estimations gardées (barème 3).
- La taille des lots ne change pas (10 sujets, 45 Ko) : sans socle de 78 000 tokens, des lots plus gros n'économiseraient que la consigne (3 000 tokens par lot) et rendraient chaque jugement plus long.


La vue d'un projet et les réponses en direct ne font plus attendre la page. Effet pour le PM : un projet s'ouvre aussitôt sur sa dernière vue, mise à jour une ou deux secondes plus tard ; une question qui attend sa réponse, ou une demande d'autorisation, apparaît sans délai même pendant que le tableau se recalcule.

- Pourquoi : le 24/11 à 08:36, « attentes » a mis 11,89 s. Mesuré sur une copie des données réelles : pour nommer la session qui attend, le connecteur relisait les 1 046 fiches de l'app (734 Mo) au premier appel après un démarrage, 16 s ; ensuite, chaque appel faisait encore un accès disque par fiche, et chacun attendait le calcul du tableau en cours (0,03 s seul, 0,8 à 1,2 s pendant le calcul). « projet » (0,6 à 1,6 s) attendait en plus la fin du calcul du tableau (1,7 s de plus mesurés).
- « projet » est servi comme le tableau : la dernière vue du dossier tout de suite, recalculée en fond, un calcul à la fois par dossier ; un clic qui écrit la rend périmée et la vue suivante est recalculée avant de répondre. La page la relit toutes les 1,5 s jusqu'à la vue fraîche, sans redessiner une vue identique.
- « attentes » et « autorisations » restent en temps réel : elles lisent les sessions dans une table tenue à jour par chaque calcul du tableau, et ne relisent les fiches que pour une session encore inconnue (une nouvelle session est nommée dès sa première demande).
- Le journal du connecteur note la durée de chaque calcul en fond (« lignes en fond · 3.10 s », « projet en fond · Studio - X · 1.20 s »).

## 0.3.15 · 2026-11-24

L'onglet « Conflits » dit « les nouveautés sont jugées » quand un passage complet a eu lieu le jour même où le point du matin avait trouvé la relecture trop grosse (rattrapage de deux Studios réels le 24/11), au lieu de « Relecture pas faite ».

## 0.3.14 · 2026-11-23

Les conflits apportés par les ingestions arrivent chaque matin dans l'onglet « Conflits ». Effet pour le PM : plus aucune passe à lancer à la main ; un nouveau conflit d'une réunion, d'un mail ou d'une décision apparaît le lendemain matin, ou l'onglet dit « à jour » si rien n'est nouveau.

- Pourquoi rien n'arrivait depuis le 10/11 : la relecture « incrémentale » se fiait à la date de modification des fichiers, que le Drive réécrit par dossiers entiers (sur un Studio réel, 1 037 documents sur 1 175 « modifiés » depuis le dernier passage). Elle relisait donc tout : 480 sujets, 3,2 % de la semaine. La détection après ingestion, trop grosse, était sautée à chaque passage, et la passe du lundi sautait les Studios en ingestion.
- La relecture ne lit plus que les lignes que le dernier passage complet n'a pas lues (`projet/.conflits/lignes-lues.json`, gardé avec « Dernier passage ») ; sans ce fichier, les dates écrites dans le Studio. Un même passage copié dans plusieurs fichiers n'est lu qu'une fois ; une ligne de réunion rejoint une décision sur quatre mots de fond, sans les noms des personnes ni les lignes d'en-tête.
- La passe du point du matin tourne chaque jour, sur chaque Studio dont tu es PM, ingestion active ou non, réunions et mails compris. Elle inscrit au registre sans poser de question ; « Dernier passage » avance quand tout est jugé, ou quand rien n'est nouveau. Plafond : 200 000 caractères par matin ; mesuré sur deux Studios réels un lundi chargé, 47 sujets jugés pour 0,54 $ (0,04 % de la semaine).
- `conflits.py cacher <studio> C4 C8 … --raison … --pm …` retire des cas du journal de l'onglet (doublon marqué, bandeau posé, question close) ; ils restent au registre, qui n'est pas modifié.

## 0.3.13 · 2026-11-23

Mon Studio s'ouvre aussitôt et se recalcule en moins d'une seconde. Effet pour le PM : la page n'affiche plus « Mon Studio se charge… » pendant 4 à 8 s ; elle montre tout de suite le dernier tableau, puis le tableau frais quelques secondes après.

- Le connecteur rend aussitôt le dernier tableau qu'il a calculé, gardé en mémoire et dans `~/Mon Studio/.parc/lignes-derniere.json` (une app relancée l'a donc aussi), marqué `frais: false`, et le recalcule en fond, un calcul à la fois. La page le relit alors toutes les 1,5 s jusqu'au tableau frais ; elle ne redessine rien si rien n'a changé.
- Un clic qui change le tableau (Fait, Plus tard, Reçu, Annuler, une réponse, une autorisation…) n'est jamais caché par le tableau gardé : la lecture suivante recalcule avant de répondre, comme avant. Un calcul en fond qui échoue fait de même, pour que l'erreur s'affiche.
- Le calcul garde ce qui ne change pas d'une lecture à l'autre : le tri de chaque message (par son texte et le glossaire du PM), les tables de pastilles de l'app (par fichier, date et taille), le journal de chaque chantier, le nom git du PM, les modules voisins (matin.py, le registre des conflits), et, deux minutes, la recherche d'un Studio rangé dans le dossier d'un autre. Rien de ce qui dépend de l'heure n'est gardé.
- Mesuré sur une copie des données réelles du 2026-11-23, médianes de 5 lectures sur plusieurs séries : 5 à 6 s avant, 0,7 à 1,2 s après dans un connecteur déjà lancé (0,7 s quand une session vient de bouger) ; premier calcul d'un connecteur neuf 6,4 à 9 s avant, 2,4 à 3,3 s après ; première réponse à la page 0,01 s, tableau frais 3 à 4,5 s après une relance de l'app. Le tableau calculé est identique, octet pour octet, à celui de la 0.3.11 sur ces données (heure figée).
- Limites connues : pendant les quelques secondes du recalcul, la page peut montrer une ligne déjà partie (une session répondue ailleurs) ; un Studio créé dans le dossier d'un autre est vu jusqu'à deux minutes plus tard ; une session qui appelle l'outil `lignes` reçoit elle aussi le dernier tableau d'abord. Pas encore essayé dans la vraie page de l'app, seulement dans la page jouée par les tests.

## 0.3.12 · 2026-11-19

« Slack ↗ » ouvre le message directement dans l'app Slack de bureau, sans navigateur ni réglage (Q14). Effet pour le PM : un clic sur « Slack ↗ » (tableau, vue projet, dépli d'une ligne) amène sur le bon message dans l'app, au lieu de la page web de Slack.

- « Pour info » ne montre que des nouvelles fraîches : des faits de la veille ouvrée ou du jour, et rien de ce que tu as déjà vu un jour précédent. La date du fait se lit dans le texte de l'entrée (« Slack #canal (Alex, 19/11 18:05) », « Daily du 19/11 »), plus l'heure du passage de l'ingestion ; le connecteur note chaque visite de la page (~/Mon Studio/.parc/visites.json, 14 jours). Les visites du jour ne masquent rien, et après quelques jours d'absence tu ne vois jamais plus que la veille ouvrée et aujourd'hui.
- La page appelle l'outil « ouvrir » du connecteur avec l'adresse web du message ; le connecteur lit l'identifiant de l'espace dans le fichier d'état de l'app Slack (lecture seule) et confie à macOS un lien `slack://channel`. La page elle-même ne navigue jamais. Une réponse dans un fil garde son fil.
- Sans l'app Slack, sans l'espace dans son état, ou si macOS refuse le lien, l'adresse web s'ouvre dans le navigateur comme avant ; sans connecteur, le lien web reste un lien. Seule l'adresse d'un message Slack (`https://<espace>.slack.com/archives/…`) est acceptée.
- Limite connue : le lien `slack://` n'a pas été ouvert dans l'app par les tests (ils simulent `open`) ; ce qui a été vérifié, c'est le lien construit.
- Les trois en-têtes de bande du tableau (« D'abord », « Ensuite », « Peut attendre ») ont la même taille : les deux premiers étaient plus petits.
- Un titre n'est plus coupé par « … » : une demande de l'ingestion a pour titre le début de sa phrase jusqu'à une coupure naturelle (virgule, deux-points, parenthèse refermée), une ligne de session est coupée au même endroit ou sur un mot entier. Une demande déjà notée avec un titre en « … » retrouve son titre depuis son texte. Le dépli ne répète plus le titre : il montre seulement ce que le titre ne dit pas, et rien quand il dit tout.
- Chaque ligne de « D'abord » dit pourquoi elle y est, par une seule pastille : « échéance 20/11 », « en retard », « une session attend », « attend une autorisation », « arrêtée en plein travail », « sécurité », « Vincent attend »… La règle qui classait une échéance proche, une session qui attend ou une session arrêtée laissait la raison vide : elle donne désormais sa raison, et la page en déduit une quand elle n'en reçoit pas.
- « Sans réponse » (Today) ne montre plus une attente dont la session source est archivée : « Ouvrir » menait à une session archivée. Sur le Studio mesuré, 3 attentes devenaient 2 (la tâche personnelle d'une session archivée, notée « bloquée », partait).
- Le compteur de l'en-tête dit ce qu'il compte : « 10 à faire d'abord au tableau » (« dans ce projet » sur la page d'un projet), et la phrase de Today « 1 à traiter aujourd'hui », pour ne plus lire deux nombres différents comme un seul.
- Dans l'agenda de Today, « 26 questions ouvertes » à côté d'une réunion est un bouton : un clic ouvre le tableau filtré sur ce projet (le même filtre que le bouton du projet en haut du tableau), donc exactement les lignes comptées. Aucun appel au connecteur.
- Un fichier lu dans la page (« Lire ») n'affiche plus ses puces en gras sur une colonne étroite : une puce « **09:41, Ana** : texte » s'écrivait un caractère par ligne, parce que la règle de grille des lignes de la page s'appliquait aussi aux puces du fichier. Elles sont de simples lignes.
- Onglet Conflits d'un projet, « En cours » : une ligne de tâche montre son sujet (« Q29 · Projet · Conflits Studio : Lancer la passe… ») et non plus sa consigne (« Nouvelle session sur le dossier Studio, coller le prompt… »), qui était la phrase de détail de la ligne.
- Onglet Conflits d'un projet : une décision que le fichier des décisions du backlog note « pas tranchée » n'est plus rangée sous « Tranché » (le relevé prenait tout texte en gras pour un choix). Elle apparaît sous « Pas encore tranché », avec sa date, et n'entre plus dans le compte des tranchées.
- Le PM d'une fiche projet est aussi lu dans un bloc de lignes « clé: valeur » (`pm: Camille Durand (PM effectif…)`), pas seulement dans la ligne de tableau « | PM | … | ». Avant, un Studio dont la fiche était écrite ainsi comptait le PM comme simple membre : il n'avait ni la ligne « Vérifier les conflits du Studio, une fois » ni les relances de conflits. Un Studio sans manifeste (`.claude/.studio-manifest.json`) n'a toujours pas cette ligne : la commande des conflits ne peut pas y tourner.
- Sous le tableau, « Sessions finies à ranger » montre la demande d'archivage elle-même dans une boîte en lecture seule (un clic la sélectionne, Cmd+C la copie), avec ou sans le bouton « Ranger » : le presse-papiers de l'app peut refuser la copie. Si la copie par le connecteur échoue, la page ne dit plus « Copié » : elle dit de copier le texte à la main. Sur le Studio mesuré, le bloc n'apparaissait pas parce que la liste était vide : le rangement avait déjà archivé les dix sessions finies.

## 0.3.11 · 2026-11-19

Trois retouches de Mon Studio vues à l'usage. Effet pour le PM : un texte d'envoi ne recouvre plus le titre d'une question, une ligne Mail dit d'où vient son échéance, et un clic sur un projet filtre le tableau au lieu de sauter à un groupe.

- Sur une ligne qui vient d'être répondue depuis le tableau, « Envoi de « Q8 … » à la session… » (et « copié : colle-le… ») a sa propre rangée sous les boutons, passe à la ligne dans sa colonne et ne s'étale plus sur le titre. Essayé dans Chrome, à deux largeurs, avant et après.
- Une ligne Mail montre la date où le mail est arrivé (« reçu le 18/11 ») à côté de « avant le 23/11 ». Au dépli : « Reçu » et « Échéance », avec « lue dans le mail », « calculée : <règle> » ou « origine de l'échéance inconnue ». Le Mac lit ces dates sur la puce de l'ingestion : ` (reçu le AAAA-MM-JJ)` et ` (échéance AAAA-MM-JJ, lue dans le mail)` ou ` (échéance AAAA-MM-JJ, calculée : <règle>)`. Rien n'est inventé : sans date de réception, la ligne dit « noté le » (le jour du passage de l'ingestion), jamais « reçu le ».
- Un clic sur un projet, en haut du tableau, ne garde que ses lignes, dans toutes les bandes (D'abord, Ensuite, Peut attendre, Anciennes), demandes de l'ingestion comprises. Le projet choisi est marqué, « Tout afficher » (ou un second clic) remet tout. Tout se passe dans la page, sans appel au Mac. « Vue projet » reste le chemin vers la page du projet.
- Le tableau range toutes ses lignes de la même façon. Effet pour le PM : une ligne fraîche passe devant une vieille, quel que soit son dossier ou sa source. Les lignes d'un dossier qui n'est pas un Studio projet (dépôt de kit, dossier de travail) ne descendent plus en bas de « Ensuite » : elles gardent leur rang, urgence puis récence. Les demandes « À toi » de l'ingestion ne sont plus toutes en tête : elles rejoignent le bloc de leur Studio, sur le tableau comme dans la vue projet ; une demande forte (échéance, quelqu'un attend) monte toujours dans « D'abord ». Mesuré sur un vrai tableau : une ligne de 3 min passe de la 52e place de « Ensuite » à la 1re.
- Limites connues : le kit d'ingestion n'écrit pas encore ces deux mentions (reçu, origine de l'échéance) : tant qu'il ne le fait pas, les lignes Mail disent « noté le » et « origine de l'échéance inconnue » ; la bande « En un clic » n'est pas filtrée par le projet ; le filtre n'est pas gardé quand la page se recharge ; le clic sur un projet n'a pas été essayé dans la vraie page, seulement dans la page jouée par les tests.

## 0.3.10 · 2026-11-18

Les sessions finies se rangent depuis Mon Studio, par un bouton « Ranger », au lieu d'être confiées à une autre session. Effet pour le PM : plus d'ordre d'archivage glissé dans une session sans rapport, que l'app refusait en mode auto ; rien n'est archivé sans son message.

- La page montre sous le tableau « N sessions finies à ranger », avec leurs titres. « Ranger » copie la demande d'archivage, écrite par le Mac ; le PM la colle dans une nouvelle session (Cmd+N), et Claude les archive.
- Le hook du rangement ne confie plus aucune liste : il ne fait que la recalculer en arrière-plan, une heure au plus souvent.
- « Abandonner » met la session arrêtée dans la même liste, au lieu de la confier à la session suivante.
- Une session rangée par le bouton apparaît dans « Rangées aujourd'hui » dès que l'app la dit archivée.
- « Fait / Retirer du tableau » ne se perd plus. Le clic part aussitôt au Mac, et « Annuler » remet la ligne dans les 10 s : avant, une page rechargée dans ces 10 s perdait le clic. Un calcul du tableau qui avait lu l'état avant le clic ne remet plus la ligne : il relit l'état au moment d'écrire et garde la fermeture, comme un jugement Slack (mesuré le 2026-11-18 à 23 h 11). Même chose pour « C'est fait », « Reçu » et « Abandonner ».
- Une question posée à la fois dans la carte de fin de tour de l'app et en « Qn · » sous « À trancher » ne fait plus qu'une ligne : celle de la Qn, avec son titre, la question entière au dépli et ses boutons de réponse. Avant, l'intitulé « Encore ouvert : » seul sur sa ligne faisait monter la carte à part, sans boutons, avec un détail qui répétait le titre (mesuré le 2026-11-18). Une carte sans Qn correspondante a ses propres boutons, et son dépli montre sa question et l'état de la session. La règle de format demande que la carte reprenne le même « Qn · titre ».
- Une demande de l'ingestion sans lien, sans auteur ni canal n'affiche plus « Relevé par l'ingestion » (ce n'est pas un nom de session) : la colonne « session » nomme la session qui a fait ce passage sur ce Studio, trouvée par l'heure du passage et le dossier du Studio (titre d'ingestion : « ingest », 📬, ou tâche d'ingestion ; plusieurs sessions de même titre : la dernière lancée), avec « Ouvrir ↗ » vers elle. Au moindre doute (aucune session, ou deux titres différents), elle montre le fichier du Studio où l'ingestion a écrit la ligne, `projet/.ingestion-auto-state.json`. Même chose pour « Source » au dépli. (PM, Q9, 2026-11-19)
- Limites connues : que l'app accepte l'archivage sur la demande collée n'est pas encore vérifié dans l'app ; que « Ouvrir ↗ » ouvre bien une session d'ingestion déjà rangée (archivée) n'est pas vérifié non plus ; le même archivage, demandé par le PM en toutes lettres, est passé le 2026-11-18.

## 0.3.9 · 2026-11-18

La vérification du point du matin ne ferme plus une ligne Slack sur une promesse ou sur son propre lien, et revient à Haiku, à son vrai coût. Effet pour le PM : moins de lignes fermées à tort, et un coût annoncé qui est celui mesuré.

- Le connecteur refuse de fermer une ligne quand la preuve est la demande elle-même, son message parent ou un message plus ancien : la ligne reste ouverte et le refus est compté avec sa raison. Une suite ne se ferme plus avec le message qui l'a créée.
- La consigne de la tâche dit qu'une promesse, un report ou une attente n'est pas un geste fait, et que la preuve est le lien du message de réponse lui-même, plus tardif que la demande. La tâche planifiée est à mettre à jour (`/cockpit:mon-studio`).
- La vérification repasse sur Haiku par défaut ; Sonnet reste un choix possible, accepté par `status` sans rien redemander.
- Les coûts sont ceux mesurés le 2026-11-18 : 34 à 37 appels et 3,5 à 4 M tokens relus par passage pour 16 à 18 lignes Slack ouvertes, environ 0,44 $ par jour sur Haiku ; sur Sonnet, environ 7,7 $ par jour (estimation, non mesurée). Le total passe de 2,03 à 1,92 $ par jour ouvré.
- Limites connues : le premier relevé réel des fermetures (8 lignes, 3 à tort) remplace l'essai de 18 lignes.

## 0.3.8 · 2026-11-18

Le README se lit correctement sur GitHub. Effet pour le PM : les phrases de coûts ne s'affichent plus en formules.

- Là où un « $ » était suivi d'une ponctuation, le README écrit « dollars » : ni la protection de la 0.3.6 ni l'écriture de la 0.3.7 n'empêchaient GitHub d'y lire une formule.

## 0.3.7 · 2026-11-18

Le README se lit correctement sur GitHub, cette fois vérifié à l'écran. Effet pour le PM : les phrases de coûts ne s'affichent plus en formules.

- Les signes « $ » suivis d'une ponctuation s'écrivent `&#36;` dans le README : GitHub lisait encore la protection de la 0.3.6 comme une formule.

## 0.3.6 · 2026-11-18

Le README se lit correctement sur GitHub. Effet pour le PM : les deux phrases de coûts qui s'affichaient en formules redeviennent lisibles.

- Les signes « $ » suivis d'une ponctuation sont protégés : GitHub les prenait pour le début d'une formule.
- Limites connues : le contrôle du modèle se coupe par « coupe le contrôle du modèle », plus par le mainteneur.

## 0.3.5 · 2026-11-18

Les textes disent ce que le plugin fait vraiment, relus avant la première publication. Effet pour le PM : il sait ce que le plugin touche sur son Mac et dans ses Studios avant de dire go.

- Le README dit ce que le connecteur fait d'une session endormie quand tu réponds depuis le tableau : il lit la liste des processus et le journal de l'app, arrête le processus qui la tient quand son tour est fini, puis la relance ; en cours de tour, la réponse attend.
- Ce qui écrit dans un Studio est dit exactement : `/cockpit:conflits` après ton go, et la relecture du lundi du point du matin (registre et plan dans `projet/.conflits/`) quand elle tourne.
- L'annonce suit les chiffres du README (environ 7 $ pour une centaine de sujets, 10 $ pour 140) ; le refus d'un lancement sans modèle se dit sans « une fois ».
- Le contrôle du modèle et celui du format des questions se coupent chacun par un interrupteur (`switch controle-modele off`, `switch controle-format off`) et ne s'appliquent plus qu'aux sessions de l'app de bureau.
- Ton nom de PM se pose par `switch pm "Prénom Nom"` ; sans réglage ni git, le nom du compte Mac est utilisé : un PM sans git retrouve ses lignes « À toi ».
- Deux notes internes (publication, brouillon de PR du catalogue) quittent le dépôt ; libellés (« fils rouges », « Plus tard »), liste des hooks et des autorisations remis à jour.
- Le README ouvre sa section des coûts par un résumé : installation, premier relevé des conflits, part fixe et part variable de chaque jour.

## 0.3.4 · 2026-11-18

L'onglet « Conflits » dit vrai après un relevé, et son coût annoncé suit le coût mesuré. Effet pour le PM : il voit les cas dès qu'ils sont écrits, sait ce qu'un relevé va coûter, et n'a plus à demander la suite.

- L'onglet « Conflits » montre les cas dès que le relevé écrit au registre : `conflits.py` recopie le registre dans l'instantané de Mon Studio après chaque écriture, sans modèle ; si la session des conflits a travaillé depuis la dernière copie, l'onglet le dit au lieu de paraître vide.
- Le coût annoncé d'un relevé suit le premier relevé mesuré sur un vrai Studio (97 sujets : 5,2 $ mesurés, 6,1 $ estimés) : socle de 78 000 tokens par sous-agent, session des conflits à 100 000 tokens relus à chaque appel, marge x 1,15. Un Studio d'une centaine de sujets s'annonce vers 0,5 % de la semaine ; les estimations gardées de l'ancien barème ne s'affichent plus.
- Après l'écriture au registre, la session enchaîne tout de suite sur les décisions (évidents d'abord), sans attendre que le PM le demande, y compris après `--decisions-seules`.
- La session des conflits se met d'elle-même au premier niveau, avec son Studio, quand une autre session l'a lancée.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.3.3 · 2026-11-18

Une question tient sur une ligne, avec son titre court, et un clic montre la question précise ; ses boutons disent leurs mots. Effet pour le PM : il lit ce qu'il y a à décider sans relire deux fois la même phrase, répond d'un bouton qui dit son option, et ne voit plus les lignes qui n'attendent rien. Sur 103 lignes réelles, 75 dépliaient leur propre début.

- Règle 2 du format des réponses : « Qn · <titre court qui synthétise la décision, 60 caractères au plus> : <la question précise>. », options « 1) **<libellé de 4 mots au plus>** : <option entière> », la recommandée en premier, puis « Pourquoi : … Si tu ne fais rien : … », avec un exemple. L'étiquette d'impact ne compte pas dans les 60 caractères. Les règles passent à 9 741 octets (plafond 9 800).
- Nouveau hook de fin de tour (`format_questions.py`) : une question dont le titre dépasse 60 caractères, sans question précise après « : », ou dont les options n'ont pas de libellé court en gras renvoie la session, une fois, reposter seulement son bloc « À trancher » corrigé, mêmes numéros. Chaque message relu ajoute une ligne, sans son texte, à `~/Mon Studio/.parc/format-questions.jsonl`, pour mesurer.
- Au tableau, une question au nouveau format montre son titre seul ; une question plus ancienne, son titre et le début de la question, coupés sur un mot avec « … » : une ligne, jamais deux. Même règle pour les lignes sans numéro et pour une question posée en encadré.
- Toute ligne se déplie. Le dépli d'une question : la question précise (jamais le titre), les options entières, puis Recommandé, Pourquoi, Ce qu'on attend de toi, Si tu ne fais rien, Pièce, seulement celles que la question écrit.
- Un bouton par option : son libellé en gras, sinon l'option coupée sur un mot sous 28 caractères ; la recommandée en premier ; plus de « 1 », « 2 », « 3 » ni de bouton recommandé en double. La réponse envoyée reste le numéro (« Q8 1 »). Un bouton long ne déborde plus.
- Une ligne « Vérifier » qui n'attend rien du PM quitte le tableau et les pages projet ; elle reste dès qu'elle demande quelque chose.
- Un titre garde son étiquette d'impact : elle ne coupe plus le titre. Le cache de Mon Studio est refait au prochain passage (version 25).
- Le contrôle des lignes signale un dépli qui répète son titre, une ligne de plus de 90 caractères et une ligne d'information au tableau.
- La page servie, le calcul et un hook changent ; la page épinglée n'est pas à republier, l'app est à redémarrer.
- Rangement : une session confiée à ranger mais restée ouverte est reproposée six heures plus tard, trois fois au plus.

## 0.3.2 · 2026-11-18

Ce qui change : le README et le plan d'installation disent ce que le cockpit fait vraiment, avant le go du PM. Pourquoi : l'audit final avant partage (Q1, Q3) a trouvé trois promesses que le code ne tient pas et deux comportements non annoncés. Effet pour le PM : rien ne change sur sa page ; un nouveau PM lit des coûts et des limites justes.

- Le registre des conflits est dit tenu par `/cockpit:conflits` seul : aucune version publiée de l'ingestion automatique n'y écrit.
- La relecture du lundi est dite sautée au-delà de 90 000 caractères d'extraits, le cas normal aujourd'hui (350 sujets et plus par semaine sur les Studios mesurés) ; son coût de 0,04 $ par lundi ne vaut que pour une petite semaine. Une ligne de plus dans « Limites connues ».
- Le plan d'installation (`install.py plan`) et « Ce qu'il installe » annoncent le rangement automatique des sessions finies, allumé par défaut, et le refus d'un lancement sans modèle.

## 0.3.1 · 2026-11-17

Ce qui change : une question à laquelle le PM a répondu par son numéro quitte le tableau, même quand la réponse de la session la cite encore. Pourquoi : « Q14 ok » restait au tableau, parce que la session avait répondu « Audit final (Q14) : j'attends… », et cette simple citation était lue comme la question reposée (même cas pour une Q43 sur un autre Studio). Effet pour le PM : sur sa page du 17/11, 2 lignes déjà répondues partent, rien d'autre ne bouge.

- Seule une sortie qui repose la question (« À trancher », « Encore ouvert », un menu) la rouvre après la réponse du PM ; une phrase qui la cite rend compte de la réponse. Même règle pour les questions des tableaux de chantier.
- Les notes que l'app met devant les mots du PM (« Linked sessions now : q18-conflits = … ») ne comptent plus comme une citation de Q18.
- Le cache de Mon Studio est refait au prochain passage (version 24).
- Le README, le skill et la note de la tâche disent Sonnet pour la vérification du point du matin, comme le code depuis la 0.3.0.
- La ligne du point du matin arrêté tient sur sa ligne du tableau (120 signes), et les extraits gardés d'une version précédente montrent le nom d'outil traduit, plus `mcp__…`.

## 0.3.0 · 2026-11-17

Première version partagée : elle réunit tout ce qui précède et ajoute deux choses. Effet pour le PM : plus de lignes Slack réglées quittent le tableau, et il peut corriger lui-même l'ordre du tableau s'il allume l'interrupteur.

- La vérification du point du matin passe de Haiku à Sonnet (décision du PM, Q10). Essai sur les mêmes 18 lignes : Haiku en fermait de 4 à 7 selon le passage, Sonnet en ferme 7, avec 2 suites justes. Coût : 0,55 $ par jour ouvré au lieu de 0,03 $ ; point du matin complet 1,04 $ au lieu de 0,53 $ ; ensemble du cockpit 0,7 % de la semaine au lieu de 0,5 % (seuil 2 %). À l'installation, choisir Sonnet comme modèle de la tâche « Point du matin · vérification » dans « Planifiées ».
- Le PM peut corriger le classement du tableau (interrupteur `reclassement`, coupé par défaut : `install.py switch reclassement on|off`). Allumé, un seul bouton par ligne du tableau principal, « Pas si urgent » dans « D'abord », « À faire d'abord » ailleurs, un clic de plus annule ; son classement l'emporte sur le calcul tant que la ligne existe (« classé par toi »), et chaque clic est noté dans `~/Mon Studio/.parc/reclassements.jsonl`, qui ne quitte pas le Mac. Coupé, rien ne change.
- La page servie et le connecteur changent ; la page épinglée n'est pas à republier, l'app est à redémarrer.

## 0.2.30 · 2026-11-17

Ce qui change : tout le reste de la revue d'usage du 17/11, en une version. Pourquoi : des doublons, des boutons qui ne servaient à rien et un détail vide faisaient relire le tableau au lieu d'agir. Effet pour le PM : un bouton par geste, une fiche par question, des vieilles lignes rangées seules, et un Today qui sert de stand-up du matin.

- Un geste fait ailleurs n'a plus qu'un bouton, « C'est fait » : il répond à la session et retire la ligne (10 secondes pour annuler).
- Recommandation propre : « (recommandée) » reconnue, même placée avant son option ; jamais une adresse comme libellé ; plus de « : . » en tête de texte ; plus de « Oui (recommandé) » à côté de « Oui » ; un bouton de 28 caractères au plus.
- Le détail d'une question de session devient une fiche : Pourquoi · Ce qu'on attend de toi · Si tu ne fais rien · Recommandation · Pièce. Une rubrique vide ne s'affiche pas, une ligne qui n'ajoute rien au titre ne se déplie plus. La règle des questions demande « Pourquoi : … » et « Si tu ne fais rien : … » (9 338 octets de règles, sous le plafond).
- « Pas encore » devient « Plus tard » : la ligne est masquée jusqu'à demain, sur le tableau seulement, rien n'est envoyé à la session (une session qui attend dans son hook finit seule son attente, 10 minutes par défaut).
- Une ligne sans mouvement depuis 21 jours passe dans « Peut attendre ». « Peut attendre » et « Anciennes » se rangent par projet, avec « Tout retirer pour ce projet » et « Tout annuler ». Une session arrêtée depuis plus de 48 h propose « Abandonner » : la ligne part et la session est confiée au rangement pour archivage, à ton prochain message dans une session. Le compte des anciennes ne compte plus les lignes déjà retirées.
- Une question relayée (« réponds dans X », « (dans X) », « À répondre dans X ») est cachée quand la session X porte la même question ; dans le doute, elle reste avec « aussi dans X ». Sans modèle.
- Attentes de tiers : bouton « Reçu », et plus de doublon avec une ligne du tableau sur le même sujet.
- Today, le stand-up du matin : plus de renvoi vers les demandes du tableau ; plus d'entrée écrite par toi-même dans « Pour info » ; « Sans réponse » (ce que tu attends des autres depuis plus de 2 jours ouvrés : attentes de tiers des chantiers, et ce que le point du matin relève dans `sans_reponse`) ; à côté de chaque réunion de l'agenda, le nombre de questions ouvertes de son projet ; les réunions sans compte rendu, venues du bloc Projets.
- Petits retraits : « Fermé depuis hier » quitte le bloc Projets ; « Sans action » est replié et ne garde que les projets clients ; un seul style pour « Ouvrir ↗ ».
- La page servie change ; elle vient du connecteur, sans republication. Le connecteur change aussi (`clore` : `plus_tard`, `abandon`, clés « t… ») : `install.py repair`.

À faire ensuite, à ne pas oublier (décision Q1 du PM, 17/11) :
1. Après la publication : la pièce dans le détail des relectures (« C'est bon » / « Corrections »).
2. Puis mesurer sur une semaine les lignes sans réponse fermée ; au-delà d'une ligne sur cinq, une réponse en une phrase derrière un bouton « Autre ».
3. La tâche du point du matin peut écrire `sans_reponse` (mails du PM restés sans réponse) : sa consigne reste à compléter.

## 0.2.29 · 2026-11-17

Le détail d'une ligne ne répète plus son titre. Effet pour le PM : sur une question numérotée, le détail commence par le texte utile (propositions, contexte), puis la date d'apparition.

- Quand l'énoncé du détail est le titre de la ligne tel qu'affiché (à l'espace ou la ponctuation finale près), il n'est pas redit ; un titre coupé ou raccourci garde son énoncé complet.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.28 · 2026-11-17

Une page projet ne montre plus que son projet, et ses fils rouges redeviennent une vraie liste, réservée aux sessions où tu reviens discuter. Effet pour le PM : plus de sessions d'autres projets sur la page d'un projet ; sur un projet réel, 9 fils rouges au lieu de 23.

- Page projet (épinglée seule ou ouverte depuis le tableau) : plus de « Rangées aujourd'hui », de barre des Studios ni d'onglets Today et Conflits du tableau. Le compteur « N à faire d'abord » ne compte que les lignes du projet. Le tableau Mon Studio garde tout.
- « Fils rouges » : une ligne par session (point non lu, titre, dernière activité, « Ouvrir ↗ »), la plus récemment active en tête, dépliée par défaut, juste sous les questions. Plus de pastilles collées.
- Un fil rouge est une session de premier niveau (pas lancée par une autre session, ou remontée au premier niveau ensuite) où tu as écrit au moins 3 messages toi-même. La session d'ancrage du chantier, les piliers déclarés et ta liste `fils-rouges.json` restent ajoutés. Tes messages se comptent une fois par transcript, puis seulement sur ce qui s'ajoute.
- La page servie change ; elle vient du connecteur, sans republication.
- `/cockpit:point` : le coût de la semaine compte aussi les sessions archivées.
- README : les autorisations du point du matin sont six, avec les deux outils qui ferment les lignes Slack.

## 0.2.27 · 2026-11-17

Une ligne Slack n'a plus de bouton « Ouvrir ↗ » (décision du PM, Q11). Effet pour le PM : il ouvrait la session 📬 du Studio à son début et ne servait à rien ; restent « Slack ↗ » et « Fait / Retirer du tableau ».

- Une question qui écrit sa proposition (« Je propose : … ») se tranche depuis le tableau : le bouton « … (recommandé) » l'envoie à la session, et le détail montre la phrase envoyée.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.26 · 2026-11-17

Les sessions lancées par Claude prennent le bon modèle, et une session dit où parler. Effet pour le PM : moins de tokens dépensés en Opus par défaut et en relais entre sessions.

- Une session ou un sous-agent lancé sans modèle est refusé ; Claude relance avec le modèle du barème. Mesuré sur une semaine réelle : 47 lancements de session sur 73 partaient sans modèle. Se coupe par `"controle_modele": false` dans `cockpit.json`.
- Une action unique (un envoi, une vérification, un essai) se fait sur place ou en sous-agent, plus dans une session à part. Seule une tâche qui vit sa vie part dans une session, celle que l'app propose.
- Un message sur le sujet d'une autre session reçoit le lien de la bonne session, sans relais, sauf si le PM demande de transmettre.
- Un test plafonne ce que le plugin ajoute à chaque session (règles, descriptions des skills, ligne de rappel) : 9 400 octets de règles, dont la règle des questions à fort enjeu arrivée en 0.2.23.

Une ligne Slack tranchée par d'autres quitte aussi le tableau (décision du PM, Q9). Effet pour le PM : une décision prise dans le fil par les personnes concernées (« on part sur l'option B », « c'est en service ») ferme la ligne, même sans message de sa part, si plus rien ne lui est demandé.

- La vérification du point du matin ferme une ligne Slack quand le fil ou le canal montre la décision ou le geste pris après la demande, avec le lien de ce message pour preuve. Dans le doute, la ligne reste.


## 0.2.25 · 2026-11-17

Une tâche planifiée arrêtée en route se voit en tête du tableau, en mots simples. Effet pour le PM : un point du matin qui n'a pas écrit son fichier, ou un passage arrêté sur une autorisation, ne passe plus inaperçu parce que l'app le marque « réussi ».

- Le point du matin pas écrit à son heure fait une ligne en tête de « D'abord », qui dit pourquoi et ouvre le passage : « Point du matin pas passé aujourd'hui (dernier : 16/11) : arrêté à 8 h 26 sur une autorisation (recherche Slack), à relancer ». Sans arrêt lu : « son passage de 7 h 36 a fini sans écrire le point », ou « est encore en cours ».
- Tout passage d'une tâche planifiée arrêté (autorisation, erreur, tour coupé) passe en tête de « D'abord », avant les réponses courtes.
- Les noms d'outils sont traduits partout où le tableau les montre : « recherche Slack », « lecture d'un fil Slack », « lecture de l'agenda », « commande du terminal ». Un outil inconnu montre ses mots (« Boond : browser click »), jamais `mcp__…`. Le journal des autorisations garde le nom exact.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.24 · 2026-11-17

Les lignes Slack auxquelles tu as répondu dans le fil quittent le tableau d'elles-mêmes, et chaque ligne Slack tient en une phrase. Effet pour le PM : plus de question déjà tranchée qui reste des jours au tableau, et plus de message Slack à relire dans le tableau.

- La vérification du point du matin (11 h, 14 h, 17 h) lit le fil de chaque ligne Slack ouverte, puis cherche tes messages dans son canal, en lecture seule. Tu as répondu après la demande, dans le fil ou dans le canal : la ligne se ferme, avec ta réponse pour preuve, même si quelqu'un la conteste ensuite. Ta réponse annonce un geste de ta part (« je vais poser la question au client ») : ce geste devient une ligne, en une phrase. Sans réponse de ta part, la ligne reste. Elle passe même les jours sans point du matin.
- Le cockpit le fait lui-même, sans attendre le passage de l'ingestion : deux outils du connecteur, `slack_ouvertes` (lecture) et `slack_juger` (n'écrit que l'état des lignes du tableau), autorisés pour les tâches planifiées avec le go de l'installation.
- Chaque ligne Slack lue par la vérification prend un résumé court : ce qui est attendu de toi, et qui l'a écrit. Une ligne tirée de ton propre message le dit : « Tu t'es engagé le 12/11 à porter à Léo 5 questions client ».
- Le détail d'une ligne Slack ne recopie plus le message : qui l'a écrit, où, quand il a été relevé, et le lien « Ouvrir le message ↗ ». La page servie change ; elle vient du connecteur, sans republication.
- La tâche « Point du matin · vérification » est à reposer (nouvelle consigne) et ses deux nouvelles autorisations à ajouter : l'installation les propose, rien ne change sans ton go.

## 0.2.23 · 2026-11-17

Le tableau se trie par impact et par effort. Effet pour le PM : ce qui presse et se règle vite est en haut, avec sa raison ; le rangement est replié en bas.

- Trois bandes : « D'abord » (impact fort, toutes origines confondues, les réponses courtes en premier), « Ensuite » (le reste, dans l'ordre d'avant, les lignes hors Studio en dernier), « Peut attendre » (repliée sous le tableau). Aucune ligne n'est supprimée.
- Une ligne de « D'abord » dit pourquoi en quelques mots : « en retard », « sécurité », « bloqué », « Ana attend », « client attend ».
- Sans modèle. Celui qui écrit la ligne peut la qualifier dans son texte : « (impact fort : client attend) », « (impact faible) », « (effort court) », pour une demande de l'ingestion comme pour une question de session. « Fort » exige une raison de la liste (client attend, échéance, bloque l'équipe, argent ou contrat, sécurité). Sans étiquette, des règles simples : échéance proche ou dépassée, session qui attend ou arrêtée, « bloqué », « en clair », « sans délai », une personne qui demande ; « archiver cette session » est du rangement.
- Une demande en retard, ou qualifiée « fort » par sa source, ne part plus dans « Anciennes ».
- Le compteur du haut donne le nombre de lignes de « D'abord » (« 17 à faire d'abord », ou « Rien ne presse ») : un seul chiffre pour savoir par où commencer.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.22 · 2026-11-17

L'onglet Conflits ne dit plus « à jour » sans relecture derrière. Effet pour le PM : il voit la date du dernier passage complet et ce qu'est devenue la relecture depuis, avec sa raison.

- « Studio à jour depuis le JJ/MM » devient « Dernier passage complet le JJ/MM », suivi de l'état réel : pas relu depuis, relecture du lundi sautée (ingestion automatique active), pas faite (trop de sujets pour un point du matin), en échec, ou relu sans rien de nouveau. « Studio à jour » ne s'écrit qu'après une relecture qui n'a rien trouvé ou dont tout est jugé.
- Le point du matin du lundi note ce qu'il a fait de chaque Studio déjà vérifié (`~/Mon Studio/.parc/conflits-semaine.json`). Avant ce premier lundi, l'onglet donne la raison qu'il peut lire : l'ingestion automatique active.
- Rien d'autre ne change : ni la relecture elle-même, ni ses seuils, ni le tableau. La page servie change ; elle vient du connecteur, sans republication.

## 0.2.21 · 2026-11-17

Le tableau se lit plus vite et chaque bouton dit ce qu'il fait ; une ligne se retire à la main. Effet pour le PM : moins de texte par ligne, plus de clic qui part dans le mauvais sens, et plus de ligne qu'il ne peut pas faire partir.

- Le texte des lignes est nettoyé : plus de « une autre Qn vient de… » ni de « à traiter dans la session… », le numéro de la question une seule fois. Une demande de l'ingestion montre dans la colonne Session qui la fait et le canal (« Ana · #projet-client ») au lieu de « Message Slack ».
- Le bouton qui ouvre une session s'appelle « Ouvrir ↗ » partout. « Recommandé » dit son choix : « Automatique (recommandé) ».
- « En un clic » ne garde que ce qu'un clic règle, rien de plus de 48 h. Un geste à faire ailleurs a « C'est fait » (et « Y aller ↗ » quand son lien est connu), au tableau.
- « Fait / Retirer du tableau » sur toutes les lignes, questions des sessions comprises, avec 10 secondes pour annuler. La session concernée en est avertie à son tour suivant ; si elle repose la question plus tard, la ligne revient.
- Une question à laquelle tu as répondu en tapant dans la session part du tableau : l'app met ses propres notes devant tes messages, et Mon Studio ne les reconnaissait plus comme les tiens.
- Retirés : les fils rouges du tableau principal (repliés sur la page projet, à la place de « Sujets »), l'onglet Conflits quand il est vide, les boutons d'une question dont on peut garder plusieurs options (ils n'envoyaient qu'une option). Le compteur devient « N à trancher aujourd'hui » ; dans Today, « Pour info » a « Vu » au lieu de « Fait ».
- Mise à jour sans republier les pages ; le premier calcul relit tous les transcripts (quelques secondes).

## 0.2.20 · 2026-11-17

- Les sessions finies qui n'ont servi qu'à une action sont archivées sans toi : lancées par une autre session (ou marquées « [jetable] »), ton dernier message déjà traité, rien à trancher, 24 h sans activité. Une session que tu as ouverte toi-même ne l'est jamais.
- Le calcul se fait sans modèle ; l'archivage lui-même se fait dans ta prochaine session où tu écris, car l'app refuse d'archiver depuis une tâche planifiée. La page montre « Rangées aujourd'hui ».
- « Coupe le rangement » dans `/cockpit:mon-studio` l'arrête ; désactiver Mon Studio aussi.

## 0.2.19 · 2026-11-16

- Les pages Mon Studio (la page principale et les pages projet) chargent leur code depuis le connecteur à chaque ouverture : une mise à jour du plugin ne demande plus de les republier, et ne coûte plus de tokens pour elles.
- Une republication n'arrive plus que si la coquille de la page ou ses outils changent, ce qui est rare ; elle relit une page d'environ 4 Ko.
- Si le connecteur ne répond pas, la page le dit en une phrase et dit quoi faire.
- Cette version demande, une seule fois : quitter et rouvrir l'app, puis republier chaque page avec sa nouvelle coquille et l'outil `gabarit`.

## 0.2.18 · 2026-11-16

- Une session ouverte pour une seule action s'archive dès que son résultat est rendu, sans attendre l'accord du PM : la barre latérale ne garde plus les petites sessions finies.
- Une session de dialogue (fil rouge, sujet qui dure) ne s'archive toujours qu'avec l'accord du PM.
- Cette règle change pour toutes les sessions dès la mise à jour, sans go.

## 0.2.17 · 2026-11-16

- Une question du tableau se déplie sur elle-même : l'énoncé entier, les options, celle que la session recommande et les fichiers cités, qui se lisent dans la page. Plus besoin d'ouvrir la session pour décider ; « Ouvrir ↗ » dit qu'elle s'ouvre à son début.
- Une demande de l'ingestion a un titre court qui se lit en entier ; elle ne se déplie que si le détail apporte quelque chose (texte complet, commande à taper, fichier lié, lu dans la page), et sa colonne Session dit d'où elle vient sans rien ouvrir.
- Chaque demande ne s'affiche qu'une fois (plus de doublon dans le bloc Projets ni dans Today, dont la pastille ne compte plus deux fois), se ferme quand le point du matin la dit réglée au même lien, et au-delà de trois Studios les relevés de conflits tiennent en une ligne de « Mise en route ».

## 0.2.16 · 2026-11-16

- La page parle en mots simples : plus de termes techniques dans les messages d'erreur et les boutons.
- L'infobulle d'un bouton de réponse dit quand la session reçoit la réponse, et quand elle est copiée à la place.
- Le README dit ce qui est écrit dans `~/.claude/settings.json`, comment connecter le Claude du Terminal, et les limites connues.

## 0.2.15 · 2026-11-16

- `/cockpit:mon-studio` ne pose plus que le socle (dossier, connecteur, pages, règles) : une installation, un go, un redémarrage.
- Le point du matin, le premier relevé des conflits et la connexion du Terminal deviennent un bloc « Mise en route » en tête du tableau : une ligne par étape, son coût, son bouton, jusqu'à « fait » ou « Pas pour moi ».

## 0.2.14 · 2026-11-15

- Plus de tâche planifiée pour les conflits : le lundi, le point du matin relit ce qui est nouveau dans chaque Studio dont tu es PM.
- Chaque question « À trancher » arrive avec une proposition, même pour une date ou un chiffre à confirmer.

## 0.2.13 · 2026-11-15

- Une réponse donnée au tableau part tout de suite si le tour de la session est fini, sinon dès la fin du tour. La ligne dit « Envoyée » seulement quand la session a la réponse.

## 0.2.12 · 2026-11-15

- Mon Studio te reconnaît PM sur plus de fiches projet (remplacement noté, « (PM) » dans la ligne « Responsable »).

## 0.2.11 · 2026-11-15

- L'onglet « Conflits » tient le journal de ce qui a été tranché, avec la date du dernier passage complet ; un onglet vide dit pourquoi.
- `/cockpit:conflits` reprend les décisions déjà tranchées à la main, après ton go.
- Une ligne par Studio jamais vérifié dans « Ce qui t'attend », avec questions, temps et coût estimés.

## 0.2.10 · 2026-11-15

- Tes pages Mon Studio ne sont plus republiées quand une version ne change que des commentaires ou des espaces.

## 0.2.9 · 2026-11-14

- Vue projet plus rapide à lire : une pastille compte les lignes apparues depuis ta dernière visite, les plus urgentes anciennes remontent, « Sujets » et « Journal » sont repliés.

## 0.2.8 · 2026-11-12

- Quand tu tranches un conflit en « remplaçant » une valeur, `/cockpit:conflits` prépare en brouillon la correction des tickets Jira ou Linear qui la portent encore (description seulement, jamais de commentaire).
- Tous les brouillons se valident dans un seul formulaire ; rien ne part sans ton go ni hors des heures ouvrées.

## 0.2.7 · 2026-11-10

- Les conflits sont mieux trouvés et il y a moins de faux conflits : les archives ne sont plus relues, l'état du projet (questions, décisions, phase) est vérifié.
- Le rattrapage d'un Studio coûte deux fois moins.

## 0.2.6 · 2026-11-10

- Les conflits se traitent en trois niveaux : marquages sûrs en un go, cas évidents pré-répondus validés dans un formulaire, vraies décisions posées une par une.
- Un onglet « Conflits » dans la vue globale relance les Studios qui ont des conflits en attente.

## 0.2.5 · 2026-11-10

- Une session citée porte toujours un lien cliquable vers elle.
- Un bouton « Recommandé » apparaît sur les questions qui recommandent une réponse.
- Le point du matin ne vérifie que les brouillons à vérifier.

## 0.2.4 · 2026-11-10

- Nouveau `/cockpit:conflits` : il remet un Studio d'équerre quand une source plus récente change une règle ou une décision qu'un document présente encore comme valable.
- Une décision par encadré, en mots simples, sans aucun code ; rien n'est supprimé, seul un marquage est ajouté à côté de l'ancien texte.
- Le coût est dit avant chaque go.

## 0.2.3 · 2026-11-10

- Les tâches planifiées arrêtées sur une autorisation, une erreur ou une question apparaissent au tableau.
- Tes réglages Claude ne changent qu'avec ton go.
- « c fait » ferme la bonne question.

## 0.2.2 · 2026-11-09

- Les tâches du matin ne restent plus bloquées sur une autorisation ; un point du matin qui n'est pas passé se voit sur la page.
- Le coût est dit avant le go ; rien ne se pose sans l'accord du PM.
- Un registre de questions par Studio, sans rien installer ; deux « Q12 » ne se confondent plus.
- Mon Studio s'installe sur Mac seulement ; « Désactive Mon Studio » coupe tout.

## 0.2.1 · 2026-11-07

- Today : un bouton « Fait » sur chaque élément qui demande un geste.
- Un bouton de réponse répond à la session, même endormie (Claude doit être connecté dans le Terminal).
- Les brouillons Gmail ou Slack jamais envoyés apparaissent en bas de Today.

## 0.2.0 · 2026-11-06

- Une page « Mon Studio » épinglée dans l'app : ce que chaque session attend de toi, projet par projet, avec le bouton qui ouvre la bonne session.
- Une page par projet suivi, et un onglet Today rempli chaque jour ouvré à 7h30 (mails, Slack, agenda).
- `/cockpit:point` : le point sur les sessions d'un Studio en dix lignes.
- Des règles de travail dans toutes tes sessions, sans toucher à ton `CLAUDE.md`.

## 0.1.0 · 2026-10-29

- Premier plugin `cockpit` : Mon Studio, `/cockpit:point` et les règles de travail du PM, dans `~/Mon Studio`.
