---
name: conflits
description: Utiliser quand le PM tape /cockpit:conflits. Remet un Studio d'équerre quand une source plus récente a changé une règle ou une décision que des documents présentent encore comme valable - rattrapage d'un Studio, liste des cas ouverts du registre projet/conflits.md, réponses du PM une décision à la fois, relecture de ce qui a changé depuis le dernier passage, correction en brouillon des tickets Jira ou Linear touchés par un conflit tranché. Coût annoncé avant chaque go ; rien n'est supprimé, rien ne part sans go explicite ni hors des heures ouvrées.
disable-model-invocation: true
---

<!-- conflits 0.3 (2026-11-15), plugin cockpit : trois niveaux, passe du lundi dans le point du matin, relance dans Mon Studio, tickets touchés, reprise des décisions tranchées à la main, aperçu préparé à la demande. Format du registre : celui de la méthode « Studio à jour », repris tel quel par /studio:auto-ingest. -->

# Conflits du Studio

Le PM a lu, dans un mail, une réunion ou un message, qu'une règle a changé ; un document du Studio la présente encore comme valable. Ce skill trouve ces écarts, marque à côté de l'ancien texte ce qui est sûr, et fait trancher le reste par le PM, une décision à la fois. Il écrit par script, sans modèle : un marquage ne coûte rien.

Sept usages, tous dans la même session :
1. **Rattrapage** d'un Studio, une fois : tout le Studio est relu. **Préparer** (`/cockpit:conflits préparer`, bouton « Préparer l'aperçu » de l'onglet Conflits) : le même relevé et le même jugement, sans la suite ; le PM valide plus tard.
2. **Les cas ouverts** : « où en sont les conflits ? », la liste du registre.
3. **Les réponses du PM**, en trois niveaux : les marquages sûrs d'un seul geste, les cas évidents d'un seul formulaire, les vraies décisions une par une.
4. **La relecture**, à la demande : seulement ce qui a changé depuis « Dernier passage ». Pour un Studio sans ingestion automatique, le **point du matin du lundi** la fait seul, sans question (plus bas).
5. **Les tickets touchés** par un conflit tranché « remplacer » : leur correction en brouillon, un seul go, poussée en heures ouvrées après relecture du ticket.
6. **La reprise** des décisions tranchées à la main avant l'outil : inscrites au registre comme tranchées, une fois.

Les trois niveaux (PM, 10/11) :
- **Marquage sûr** : posé par le script, d'un seul go groupé pour tout l'aperçu, suivi d'un récapitulatif par fichier.
- **Cas évident** : une décision du PM sans aucune des raisons ci-dessous. Elle est pré-répondue avec sa recommandation ; le PM lit la liste et répond par un seul formulaire.
- **Vraie décision** : au moins une raison, posée seule dans son formulaire : texte parti au client, argent ou contrat (prix, budget, devis, document signé, facturation), source seulement orale (réunion, appel, notes automatiques), savoir propre au PM. Le script les détermine ; une décision liée à une vraie décision en devient une.

Le script : `python3 "${CLAUDE_PLUGIN_ROOT}/skills/conflits/scripts/conflits.py"` (noté `conflits.py` plus bas). Si `${CLAUDE_PLUGIN_ROOT}` n'est pas remplacé, pars du dossier de ce skill (« Base directory for this skill ») : le script est dans `scripts/`. `<studio>` est le chemin absolu du Studio.

## Où ça tourne

0. **Avant tout autre geste, au premier niveau.** Quelle que soit la façon dont cette session a été lancée (par toi, par une session de kit, par une autre session), regarde si elle a une session mère : `get_session` sur elle-même ; si elle a un `parentSessionId` sans être `detached`, détache-la (`detach_session` sur elle-même) et dis-le en une ligne (« Session mise au premier niveau, avec son Studio. »). La session des conflits vit toujours au premier niveau, rangée avec son Studio, jamais sous la session qui l'a lancée. Si l'outil manque ou refuse, dis-le en une ligne et continue.

Tout se fait dans **une** session ouverte dans le dossier du Studio (son dossier de travail est le Studio, qui contient `.claude/.studio-manifest.json`), titrée « <Projet> · Conflits Studio », où <Projet> est le nom court du Studio (« Studio - Projet Alpha » donne « Projet Alpha »). Une session dont le titre commence ainsi (« Projet Alpha · Conflits Studio (rattrapage) ») compte : c'est la même.

1. Le dossier de travail est un Studio, la session n'est ni une session de kit ni une tâche planifiée, et c'est la session des conflits (son titre commence par « <Projet> · Conflits Studio ») ou une session neuve ouverte pour ça (rien avant cette commande) : renomme-la « <Projet> · Conflits Studio » si son titre ne commence pas ainsi (`set_session_title` quand l'outil est là), puis continue ici.
2. Sinon (autre dossier, autre session du Studio qui a déjà son sujet, session de kit, routine), ne lis rien du Studio. C'est le cas quand le bouton de Mon Studio « Vérifier ce Studio » a ouvert la session la plus récente du Studio avec `/cockpit:conflits rattrapage` à coller : la session des conflits n'existe pas encore. Cherche la session par son titre (`list_sessions` de l'app, la plus récente si plusieurs) : si elle existe, dis au PM de la reprendre et donne son nom exact. Sinon, propose de la créer, et sur son accord : `start_session` (dossier du Studio, titre « <Projet> · Conflits Studio », avec un brief complet : le Studio, l'usage demandé, « lance /cockpit:conflits », les règles ci-dessous), puis `detach_session` pour la mettre au premier niveau de la barre latérale, sans groupe. Puis arrête-toi.
3. Une tâche planifiée ne pose jamais de question au PM et ne garde aucun travail à reprendre : ce qui a besoin du PM va dans le registre, en cas ouvert.

Le nom du PM, qui signe « tranché par » : son prénom tel que le Studio le connaît (fiche projet, « Responsable »), sinon `git config user.name`, sinon demande-le une fois, avec le go du coût.

## 1 et 4 · Rattrapage et relecture

0. **Un rattrapage déjà fait à la main ?** Si le Studio a un dossier `projet/rattrapage-AAAA-MM-JJ/` et que le registre n'a pas de « Dernier passage », commence par la reprise (usage 6) : le relevé ne reposera pas ce qui est tranché. **Un aperçu déjà préparé ?** Si `conflits.py attente <studio>` dit qu'un aperçu préparé d'avance attend (plus bas), saute aux étapes 4 et 5 avec ce plan : rien n'est à relire ni à payer de nouveau.
1. **Le coût d'abord.** `conflits.py estimer <studio>` (ajoute `--incremental` pour une relecture). Dis le coût en une ligne, en % de la semaine, puis demande le go (une question, rien d'autre). Au-delà de 0,5 % d'un lancement, propose de traiter un dossier à la fois (`--dossier <sous-dossier>`, la liste est dans la sortie), un go par dossier.
2. **Le relevé**, sur go : `conflits.py releve <studio>` (mêmes options). Sans modèle : le plan va dans `projet/.conflits/apercu-AAAA-MM-JJ.json`. Rien d'autre n'est écrit. Un document qui porte en tête son propre bandeau (« document d'étape », « périmé sur… ») est une archive : le relevé l'écarte ; sa page html jumelle sans bandeau devient un sujet à elle seule. Le relevé compte aussi l'état du projet : questions ouvertes et closes, décisions remplacées, taille de la story map, phase. Ne lis pas le plan toi-même.
3. **Le jugement**, par des sous-agents Sonnet, effort medium, un par lot (dix sujets au plus, moins de 45 000 caractères d'extraits), deux ou trois à la fois au plus. Chacun reçoit le brief de « Brief d'un sous-agent » plus bas, avec le chemin du plan et son numéro de lot. Il lit les extraits du lot, jamais un fichier entier, et écrit ses jugements dans le fichier que `lot` lui indique. Tu ne relis pas les extraits.
4. **L'aperçu** : `conflits.py juger <plan>`. Montre son tableau au PM tel quel (chaque conflit par son titre, ce qu'il y a à faire : marquage sûr, décision à prendre ou règle à ajouter, fichiers touchés, parti chez le client oui ou non, coût). Rien n'est encore écrit dans le Studio.
5. **Un seul go groupé** pour tous les marquages sûrs et les règles à ajouter. Sur go : `conflits.py ecrire <plan> --pm <prénom>`. Redis tel quel son récapitulatif (chaque fichier, les conflits marqués dedans) et sa dernière ligne (combien de cas évidents, combien de vraies décisions). Il revérifie chaque passage mot pour mot : un passage qui a bougé depuis l'aperçu devient une décision du PM, rien n'y est écrit. Il inscrit chaque décision du PM au registre (« ouvert »), une seule fois même si l'aperçu est refait ; il pose « Dernier passage » seulement après un passage complet (tous les lots jugés, tout le Studio, marquages écrits). Un fichier illisible n'est jamais réécrit : ses passages deviennent des décisions du PM. Pas de go : rien n'est écrit ; `--decisions-seules` inscrit les décisions sans marquer, si le PM le demande.
6. **Enchaîne tout de suite sur les décisions (usage 3)**, dans le même tour, sans attendre que le PM le demande et sans lui demander s'il veut continuer : les cas évidents d'abord (`evidents`, un seul formulaire), puis les vraies décisions une par une. Pareil après `--decisions-seules`. La dernière ligne de `ecrire` annonce cette suite : ce n'est pas une fin. Tu ne t'arrêtes que s'il n'y a aucune décision, ou si le PM dit d'arrêter.

## 2 · Les cas ouverts

`conflits.py attente <studio>` d'abord : les marquages sûrs que la passe du lundi a préparés (ils attendent ton go groupé : `conflits.py ecrire <plan de la passe> --pm <prénom>`), le nombre de cas évidents et de vraies décisions, et une ligne « Tickets : … » quand des corrections de tickets attendent (brouillons à valider, tickets validés à pousser, conflits tranchés dont les tickets restent à chercher) : enchaîne alors sur l'usage 5, en tête de la réponse si des tickets validés attendent les heures ouvrées. Puis, si le PM veut le détail, `conflits.py ouverts <studio>` : une ligne par conflit ouvert, par son titre, puis ceux qui ne se lisent pas. Ces commandes notent que le PM a vu les cas : la pastille « nouveaux » de Mon Studio s'éteint. Rends-les tels quels. Un conflit illisible ne bloque pas les autres : dis au PM lequel, par son titre.

## 3 · Les décisions du PM

**Les cas évidents, d'abord.** `conflits.py evidents <plan>` (sans aperçu : `<studio>/projet/.conflits/registre.json --studio <studio>`) rend la liste et un seul formulaire. Montre `texte` tel quel (une ligne par cas : son titre, la réponse pré-remplie, pourquoi), puis pose `formulaire` dans un seul encadré, ses options dans l'ordre. Le PM :
- valide : `conflits.py valider <plan> --pm <prénom>` ; tout s'écrit en une fois ; redis le point ;
- « les poser une par une » : `… --tous-sortir` ; ils rejoignent les vraies décisions ;
- répond en texte libre dans « Autre » : « sors le comité de pilotage » donne `--sortir '["comité de pilotage"]'` (le cas rejoint les vraies décisions) ; « le plafond de remise, garde tel quel » donne `--changer '[{"quoi": "plafond de remise", "choix": "simple discussion"}]'` ; les deux se combinent, en un seul appel. Si le script dit qu'aucun cas ou plusieurs répondent, rien n'est écrit : demande lequel, par son titre ;
- « Discuter d'abord » : explique, puis repose le même encadré.

**Les vraies décisions, ensuite.**

1. `conflits.py formulaires <plan>` une fois, au début : tous les formulaires des vraies décisions restantes (et des cas évidents sortis de la liste), prêts, y compris pour chaque cas ouvert du registre qu'aucun aperçu n'a préparé (écrit par `/studio:auto-ingest`) ; sans aperçu du tout : `conflits.py formulaires <studio>/projet/.conflits/registre.json --studio <studio>`. Chaque formulaire est prêt (le titre, le contexte, les options dans l'ordre, la recommandée en premier, et pour « Discuter d'abord » les extraits des deux sources avec leur date et leur place, ce qui en dépend, pourquoi la recommandation). Son champ `cas` sert à `repondre`, jamais au PM. Le plan d'un rattrapage est le plus récent de `projet/.conflits/`.
2. **Un encadré AskUserQuestion par décision, posé seul**, jamais deux décisions dans un encadré. Reprends du formulaire, sans les changer : `question` (sa première ligne est le titre du conflit en clair, la suivante son contexte : qui a dit quoi, et quand), `header`, et les `options` (leur `label` et leur `description`) dans leur ordre. Le libellé qui garde l'ancienne valeur est celui du formulaire ; le registre écrit toujours « simple discussion ».
3. **Fluidité** : entre deux encadrés, aucune lecture, aucune écriture, aucun appel d'outil. Toutes les huit réponses, et à la fin, un seul appel écrit le lot : `conflits.py repondre <plan> --pm <prénom> --reponses '[{"cas": "C7", "choix": "<label choisi>"}, …]'`. Il écrit la ligne État du registre, les marquages, « Règles remplacées » et le journal, puis rend un point d'une ligne (« 8 faites, 17 restent ») : redis-le tel quel.
4. **« Discuter d'abord »**, ou une réponse libre dans « Autre » qui est une question (un « ? », « pourquoi », « c'est quoi ») : jamais une décision. Explique en clair, en quelques lignes, à partir de la partie `discuter` du formulaire (les deux valeurs avec leur date et leur place, ce qui en dépend, pourquoi la recommandation), sans aucun code. Les codes et les chemins exacts (`references`) ne se donnent que si le PM les demande explicitement. Échange librement, puis repose le même encadré, mis à jour seulement si la recommandation change.
5. **Une décision qui en conditionne une autre** : la dépendante vient juste après (`depend_de`). Adapte sa question à la réponse donnée, sans rien écrire entre les deux.
6. **Une décision sautée** reste « ouvert » au registre. Le PM peut aussi répondre à la voix, par le titre (« le comité de pilotage, remplacer » : `conflits.py trancher <studio> "comité de pilotage" remplacer --pm <prénom>`, ou « rouvre le comité de pilotage » : `conflits.py rouvrir <studio> "comité de pilotage"`), ou par un numéro s'il le dit lui-même. N'exige jamais de numéro ; si plusieurs conflits répondent, le script les nomme : demande lequel.
7. **Reprise** : si la session s'est arrêtée au milieu d'un lot, retrouve dans la conversation les réponses pas encore écrites et écris-les d'abord (`repondre`, qui n'écrit jamais deux fois), puis relance `formulaires`.

Effet de chaque choix :
- **remplacer** : l'ancienne valeur est marquée là où elle est écrite, et l'ancienne règle passe dans « Règles remplacées » de son document vivant, avec sa date, sa source et « actée par <PM> le … ». Rien n'est supprimé. Si la fiche projet a un outil ticketing, ses tickets touchés sont cherchés ensuite (usage 5), après les décisions de la séance.
- **à confirmer avec le client** : l'ancienne valeur reste ; la nouvelle est notée à côté.
- **simple discussion** : rien ne change dans les documents ; le registre garde la trace.

## 5 · Les tickets touchés

Quand un conflit est tranché « remplacer », des tickets du projet décrivent peut-être encore l'ancienne valeur (le code PIN retenu, deux tickets qui parlent encore du code envoyé par e-mail). Le skill prépare leur correction en brouillon : la description seulement, jamais un commentaire. Il ne dépend d'aucun autre plugin. Le script : `python3 "${CLAUDE_PLUGIN_ROOT}/skills/conflits/scripts/tickets.py"` (noté `tickets.py`). Il ne parle jamais à Jira ni à Linear : c'est toi qui lis et pousses, avec l'outil ci-dessous ; lui dit quoi chercher, garde les brouillons et dit ce qui peut partir. Rien de ce que tu lis des tickets n'entre dans le Studio : tout va dans un dossier de travail hors du Studio (`tickets.py dossier`).

Règles (PM, 11-12/11) :
- Un ticket reçoit par défaut un **ajout daté en tête** (« Mise à jour du 12/11/2026 : code PIN remplace code envoyé par e-mail. ») ; son texte d'origine ne change pas. Seul un ticket dans un statut que la fiche projet liste comme interne (« Statuts internes : À rédiger, Brouillon ») peut être réécrit.
- Un ticket terminé n'est jamais corrigé : il est seulement nommé dans le récapitulatif.
- Rien n'est poussé sans le go explicite du PM, ni hors des heures ouvrées (lundi à vendredi, 8 h à 20 h, heure de Paris, jours fériés exclus, lue par le script avec `date`). Hors de ces heures, le go vaut préparation : redis la ligne du script, et propose le push au passage suivant (`conflits.py attente` le rappelle).
- Juste avant chaque push, le ticket est relu dans l'outil. S'il a changé depuis le brouillon, il ne part pas, et le PM est prévenu.

**L'outil**, selon la fiche projet (« Outil ticketing », sinon la ligne « Jira » ou « Linear ») :
- Jira : acli d'abord (`command -v acli`, puis `acli jira auth status`) ; sinon le connecteur Atlassian (`searchJiraIssuesUsingJql`, `getJiraIssue`, `editJiraIssue`). La description se lit et s'écrit en ADF : avec le connecteur, demande l'ADF quand l'outil le propose et pousse avec `contentFormat: "adf"` ; une description revenue en texte est refusée par le script, dis-le au PM.
- Linear : le connecteur Linear (chercher, lire et mettre à jour un ticket) ; la description est en Markdown.
- Ni l'un ni l'autre : dis-le au PM en une ligne (« Je ne peux ni lire ni corriger les tickets : ni acli ni le connecteur Atlassian dans cette session. ») ; rien n'est poussé, les brouillons restent.

**Chercher**, après les décisions du PM, ou quand `attente` dit que des conflits tranchés attendent :
1. `tickets.py recherche <studio>` : pour chaque conflit tranché « remplacer » pas encore cherché, les requêtes, et le coût en une ligne. Redis cette ligne et demande le go (une question, rien d'autre). S'il manque la clé du projet Jira ou l'outil, redis son message et arrête-toi là.
2. Sur go : `tickets.py dossier`, puis pour chaque conflit, deux recherches, la sortie dans un fichier du dossier, jamais lue par toi :
   - acli : `acli jira workitem search --jql '<jql_ouverts>' --fields key,summary,status,description --limit <ouverts_par_conflit> --json > "<dossier>/<cas>.json"`, puis `acli jira workitem search --jql '<jql_termines>' --fields key,summary,status --limit <termines_par_conflit> --json > "<dossier>/<cas>-termines.json"` ;
   - connecteur : les mêmes requêtes, mêmes champs et mêmes limites ; écris le résultat tel quel dans ces deux fichiers ;
   - Linear : la recherche du connecteur avec `requete`, dans l'équipe de la fiche, 15 tickets au plus, dans `<dossier>/<cas>.json` (le script met de côté les terminés).
3. `tickets.py lot <studio> <dossier> 1 --sortie "<dossier>/lot-1.txt"` donne le nombre de lots ; un sous-agent Sonnet, effort medium, par lot, deux à la fois au plus, avec le brief « Brief du sous-agent des tickets » plus bas.
4. `tickets.py preparer <studio> <dossier>` : les brouillons. Les conflits du dossier sont notés « cherchés » : ils ne sont plus recherchés.

**Le go du PM, en un seul formulaire.** `tickets.py brouillons <studio>` : montre `texte` tel quel (les brouillons groupés par conflit, chaque ticket par son titre, avant et après, puis les tickets terminés non corrigés), puis pose `formulaire` dans un seul encadré, ses options dans l'ordre. Aucun code de ticket devant le PM. Le PM :
- valide : `tickets.py valider <studio> --pm <prénom>`, redis son point ;
- répond en texte libre dans « Autre » : « écarte mot de passe oublié » donne `--ecarter '["mot de passe oublié"]'` ; « pour la connexion, écris : la connexion se fait par code PIN » donne `--changer '[{"quoi": "connexion", "texte": "la connexion se fait par code PIN"}]'` (pour un ajout, le texte devient l'ajout daté ; pour une réécriture, toute la description) ; les deux se combinent, en un seul appel. Si le script dit qu'aucun ticket ou plusieurs répondent, rien n'est écrit : demande lequel, par son titre ;
- « Tout écarter » : `--tout-ecarter` ; « Discuter d'abord » : explique, puis repose le même encadré.

**Pousser**, seulement après ce go : `tickets.py pousser <studio>`. Hors des heures ouvrées, il ne rend rien à pousser : redis son message et arrête-toi. Sinon, `tickets.py dossier` (un dossier de travail neuf, même au passage suivant), puis pour chaque ticket, l'un après l'autre :
1. relis-le dans l'outil, dans `<dossier>/actuel-<id>.json` (acli : `acli jira workitem view <cle> --fields summary,status,description --json > …`) ;
2. `tickets.py verifier <studio> <id> --actuel "<dossier>/actuel-<id>.json" --sortie "<dossier>/pousser-<id>.json"` ; s'il dit qu'il ne faut pas pousser (ticket changé, terminé, sorti d'un statut interne, ou pas relu), redis son message au PM et passe au suivant. Si le PM veut un nouveau brouillon d'un ticket changé : `tickets.py recherche <studio> --cas <cas rendu par verifier>`, puis les mêmes étapes que « Chercher » ; un ticket déjà corrigé pour ce conflit n'en reçoit jamais un second ;
3. pousse le fichier de sortie comme description, rien d'autre : acli `acli jira workitem edit --key <cle> --description-file "<dossier>/pousser-<id>.json" --yes` ; connecteur Atlassian `editJiraIssue` avec `contentFormat: "adf"` et ce contenu dans `fields.description` ; Linear, la mise à jour du ticket avec ce Markdown comme description ;
4. relis-le dans `<dossier>/relu-<id>.json`, puis `tickets.py pousse <studio> <id> --relu "<dossier>/relu-<id>.json"` (en cas d'erreur de l'outil : `--echec "<le message>"`, le ticket reste validé).

À la fin, un récapitulatif en quelques lignes : les tickets corrigés, par leur titre ; ceux qui n'ont pas pu partir, et pourquoi.

### Brief du sous-agent des tickets

Lance-le en Sonnet, effort medium, avec ce texte (remplace `<dossier>` et `<k>`) :

> Tu juges si des tickets décrivent encore une valeur remplacée. Lance `python3 "<chemin de tickets.py>" lot "<studio>" "<dossier>" <k> --sortie "<dossier>/lot-<k>.txt"`, puis lis ce fichier en entier, en une seule lecture, rien d'autre. Pour chaque conflit, la nouvelle valeur fait foi. Pour chaque ticket, `touche` est vrai seulement si sa description présente encore l'ancienne valeur comme valable aujourd'hui ; faux si elle ne la porte pas, porte déjà la nouvelle, ou la raconte au passé. Pour un ticket touché marqué « réécriture permise » seulement, écris `apres` : toute la description corrigée, en Markdown simple (titres, listes, gras), identique à l'original sauf ce que la nouvelle valeur change. Écris le fichier de jugements que donne la dernière ligne du lot, d'un seul coup avec l'outil d'écriture de fichier : une liste JSON, un objet par ticket, `{"cas": "C1", "cle": "PRJ-12", "touche": true}` (avec `"apres"` seulement dans le cas ci-dessus). Réponds seulement « lot <k> écrit, n tickets ».

## 6 · La reprise des décisions tranchées à la main

Un Studio rattrapé à la main avant l'outil garde un dossier `projet/rattrapage-AAAA-MM-JJ/` (questions, réponses du PM, journal de ce qui a été posé) et un registre vide : Mon Studio le dit « pas encore vérifié », et un relevé reposerait ce que le PM a déjà tranché. La reprise inscrit ces décisions au registre, comme tranchées, avec leur date, qui les a tranchées et où, puis pose « Dernier passage » à la date du rattrapage. Elle se fait une fois, avant tout rattrapage par l'outil ; la commande la propose d'elle-même quand un tel dossier existe et que le registre n'a pas de « Dernier passage ».

1. `conflits.py reprendre <studio> --entree "<dossier du plan>/reprise-entree.txt"` : les fichiers lus, le coût en une ligne (quelques centièmes de % de la semaine). Redis-la et demande le go (une question, rien d'autre). Sans dossier de rattrapage, rien à reprendre : enchaîne sur le rattrapage (usage 1).
2. Sur go : un sous-agent Sonnet, effort medium, avec le brief « Brief du sous-agent de la reprise » plus bas. Il écrit `projet/.conflits/reprise.json`.
3. `conflits.py reprendre <studio> --extraction <studio>/projet/.conflits/reprise.json --pm <prénom>` : l'aperçu, sans code (chaque décision par son titre, sa réponse, sa date, qui ; ce qui reste à faire d'après le rattrapage, qui n'entre pas au registre ; la date « Studio à jour depuis »). Montre-le tel quel, puis un seul encadré : inscrire au registre (recommandé), corriger une réponse, ne rien inscrire. En texte libre, « pages publiques, à confirmer avec le client » donne `--changer '[{"quoi": "pages publiques", "choix": "à confirmer avec le client"}]'`. Si le PM dit que le rattrapage à la main n'était pas complet, `--dernier-passage aucun` : les décisions entrent au registre, le Studio reste « pas encore vérifié ».
4. Sur go : la même commande avec `--ecrire`. Redis sa ligne. Rien d'autre n'est écrit que le registre (ajout seul, jamais deux fois) et une ligne du journal du Studio.

Pour montrer ce qui serait inscrit sans rien écrire dans le Studio : `--sortie <fichier hors du Studio>` (l'aperçu et les lignes exactes du registre).

### Brief du sous-agent de la reprise

Lance-le en Sonnet, effort medium, avec ce texte (remplace `<entrée>` et `<extraction>`) :

> Tu reprends les décisions de conflits qu'un PM a tranchées à la main dans un Studio, avant l'outil. Lis en entier, en une seule lecture, le fichier `<entrée>`, rien d'autre : il rassemble les fichiers d'un rattrapage fait à la main (questions posées au PM, ses réponses, journal de ce qui a été posé), chacun sous une ligne « ===== <chemin> (rattrapage du <date>) ===== ». Une décision est une question que le PM a tranchée ; ni un marquage posé sans lui, ni une question restée sans réponse. Plusieurs cas regroupés sous une même question font une seule décision.
> Pour chaque décision, un objet JSON : `{"titre": "<3 à 8 mots en clair>", "ancienne": {"texte": "<ce que le Studio présentait, une ligne>", "source": "<le chemin du Studio où c'était écrit, tel que le fichier le donne ; sinon le chemin du fichier du rattrapage>", "date": "JJ/MM/AAAA ou null"}, "nouvelle": {"texte": "<la valeur plus récente, une ligne>", "source": "…", "date": "…"}, "communique": <true seulement si l'ancienne valeur est dans un document parti chez le client>, "choix": "remplacer | à confirmer avec le client | simple discussion", "reponse": "<la réponse du PM, en ses mots, une phrase>", "tranche_le": "JJ/MM/AAAA", "par": "<son prénom, tel que le fichier l'écrit>", "tranche_dans": "<le chemin, sous « ===== », du fichier où la réponse est écrite>", "reste": "<ce qui n'est pas fait d'après les fichiers (brouillon pas envoyé, marquage pas posé, question à poser au client), sinon chaîne vide>"}`.
> `reste` ne dit que ce qui attend quelqu'un ou quelque chose hors du Studio : un brouillon pas envoyé, une réponse du client ou d'un collègue, une vérification promise. Jamais un marquage ou une réécriture du Studio : le rattrapage ne voit pas ce qui a été posé après lui.
> Le choix : `remplacer` quand la nouvelle valeur est retenue (ancien texte marqué remplacé, règle réécrite, question close dans le sens nouveau, ajout ou complément, bandeau posé) ; `à confirmer avec le client` quand la décision attend le client ; `simple discussion` quand l'ancienne valeur reste en vigueur ou que rien ne change dans les documents (« laisser », « reste ouvert », « ne rien toucher »).
> Une date : seulement celle que le fichier écrit, jamais devinée ; une année absente se lit dans la date du rattrapage. `tranche_le` est la date écrite avec la réponse (sur sa ligne ou dans le titre de sa section), sinon la date du rattrapage. Une valeur sans date : `null`.
> Le titre, la réponse et ce qui reste sont lus par le PM : aucun code dedans (ni numéro de décision, de règle, de question, d'US, de cas, de ticket, ni lettre seule), seulement des mots ; « le PM », la personne, est permis. Un titre avec un code est refusé.
> Écris dans `<extraction>`, d'un seul coup avec l'outil d'écriture de fichier, sans script ni relecture, une liste JSON, un objet par décision. Réponds seulement « n décisions ».

## La passe du lundi (dans le point du matin)

Aucune tâche planifiée par Studio : ne crée jamais de tâche pour les conflits. Le premier point du matin de la semaine (la tâche « Point du matin » de Mon Studio, le lundi) relit, pour chaque Studio dont le PM est responsable, déjà vérifié une fois (« Dernier passage » au registre) et sans ingestion automatique active, seulement ce qui est nouveau depuis « Dernier passage ». Il ne pose aucune question et ne marque rien dans les documents : il inscrit les décisions au registre (avec leur niveau, leur recommandation, leur contexte) et prépare les marquages sûrs, qui attendent le go groupé du PM ici (`conflits.py attente`). Un Studio dont l'ingestion automatique est active est sauté : aucune version publiée de l'ingestion n'inscrit ses cas au registre, c'est une limite connue ; la relecture se fait ici, à la demande. Une semaine trop chargée (plus de 90 000 caractères d'extraits pour tous les Studios) laisse les Studios en trop pour le lundi suivant, qui relit depuis le même « Dernier passage » ; une relecture ici les rattrape plus tôt.

Son coût est dans celui du point du matin, annoncé à l'installation de Mon Studio ; `conflits.py passe <studio> --estimer` le dit pour ce Studio, si le PM le demande. Rien à créer ni à régler ici.

## Préparer l'aperçu, à la demande

Le PM clique « Préparer l'aperçu » dans l'onglet Conflits : la session s'ouvre avec `/cockpit:conflits préparer`. Pour qu'il n'ait plus qu'à valider en revenant :
1. `conflits.py estimer <studio> --preparer` : dis le coût en une ligne, puis demande le go (une question, rien d'autre). Au-dessus du plafond d'un lancement, un dossier à la fois.
2. Sur go : les étapes 2 à 4 du rattrapage (relevé, sous-agents, `juger`), sans montrer l'aperçu ni rien écrire dans les documents. `juger` garde un résumé (`projet/.conflits/pret.json`) : Mon Studio dit alors le compte exact et le temps.
3. Dis en une ligne ce qui attend (le résumé de `conflits.py attente`) et que `/cockpit:conflits rattrapage`, ici, reprend aux étapes 4 et 5 avec ce plan. Arrête-toi. Le résumé s'efface quand le plan est écrit.

## La relance dans Mon Studio

L'onglet « Conflits » de Mon Studio (vue globale et vue projet) montre une pastille pour les cas nouveaux, pas encore montrés au PM ici, et le bouton vers cette session. « Ce qui t'attend » porte une ligne de relance à partir de 10 cas non traités ou de 14 jours sans traitement. Le PM règle ces seuils pour ce Studio : « relance à 5 cas » donne `conflits.py regler <studio> --cas 5`, « à 7 jours » donne `--jours 7`. Ni Slack ni mail.

## Les mots devant le PM

Aucun code devant le PM : ni numéro de décision, de règle, de question, d'US, de ticket ou d'ADR, ni numéro de conflit du registre, ni identifiant interne de sujet ou d'extrait, ni lettre de classe ou de cause. Chaque conflit se dit par son titre en clair, puis son contexte en mots simples : qui a dit quoi, et quand (« Le contrat signé du 6 novembre fixe… ; au kick-off du 9 novembre, le client a dit… »). Ce qu'il y a à faire se dit en mots : « marquage sûr », « décision à prendre », « règle à ajouter ». Les scripts l'écrivent déjà ainsi : recopie-les. Les codes restent dans le registre et dans les marquages du Studio ; tu ne les donnes que si le PM les demande.

## Garde-fous

- Rien n'est supprimé. Un marquage est une ligne ajoutée à côté de l'ancien texte : « ⚠️ Remplacé le {date} par {décision}, source {fichier} — rattrapage du {date} ». Aucun octet existant ne change.
- Un document parti chez le client (devis, offre, cahier des charges remis, tout `0-commerce/`) est seulement marqué : jamais d'ajout ni de « Règles remplacées » dedans.
- Le script n'écrit que dans le Studio, dans un .md ou un .txt : jamais le registre hors de ses lignes, un journal de changements, une source datée, une page html ni la story map JSON (lus seulement : ce qu'ils portent va au PM).
- Rien n'est envoyé à personne. Rien dans Figma ni le JSON de la story map. Dans le ticketing, seulement la description des tickets touchés par un conflit tranché, par l'usage 5 : après le go explicite du PM, en heures ouvrées, après relecture du ticket ; jamais un commentaire, une transition, une assignation ni un nouveau ticket. Le PM décide seul de prévenir le client.
- Les écritures passent par le script, jamais par Edit ou Write : c'est lui qui revérifie le passage et ne marque jamais deux fois.
- Les questions au client restent dans `questions-ouvertes.md` ; le registre ne contient que les conflits.

## Brief d'un sous-agent

Lance-le en Sonnet, effort medium, avec ce texte (remplace `<plan>` et `<k>`) :

> Tu juges le lot <k> des conflits d'un Studio. Lance `python3 "<chemin de conflits.py>" lot "<plan>" <k> --sortie "<dossier du plan>/lot-<k>.txt"`, puis lis ce fichier en entier, en une seule lecture (il fait moins de 50 Ko), rien d'autre : jamais un fichier du Studio. Pour chaque sujet, applique la règle de lecture commune ci-dessous et classe-le :
> - `M` (marquage sûr) : l'ancien terme ET le sujet sont dans le même passage, et la nouvelle source est écrite et pèse au moins autant que l'ancienne. Donne les extraits à marquer.
> - `PM` (décision du PM) : un doute, une source orale ou plus faible, un document signé contredit, deux règles actives qui se contredisent, un revirement dans une source, une page html qui garde l'ancienne valeur. Donne la réponse recommandée (`remplacer`, `à confirmer avec le client` ou `simple discussion`) et pourquoi, en une ou deux phrases.
> - `absence` (à ajouter) : la nouvelle valeur manque là où elle devrait figurer ; donne le fichier (pris dans les extraits) et le texte à ajouter, une ligne.
> - `rien` : aucun extrait ne présente l'ancienne valeur comme valable aujourd'hui.
> « Rien » est strict. Un passage d'un document vivant (README, statut, fiche, roadmap, prérequis, stack, glossaire, story map, page html) qui écrit encore l'ancienne valeur au présent n'est jamais « rien », même s'il est court, même si la nouvelle valeur le nuance seulement, même si un autre document est déjà à jour : `M` si c'est sûr, sinon `PM`. « Rien » seulement quand l'extrait ne porte pas l'ancienne valeur, porte déjà la nouvelle ou la nuance explicitement, ou raconte le passé (une ligne datée d'historique, une question déjà résolue dans sa propre ligne, un compte rendu).
> Genres particuliers : une « page html jumelle d'un document sous bandeau » est `PM` (recommandé `remplacer` : y mettre le même bandeau), sauf si l'extrait montre déjà un bandeau ; un « compteur peut-être périmé » ou une « phase du projet » qui ne correspond plus au compte donné est `M` quand la ligne dit bien la même chose que le compte (même périmètre), sinon `rien`.
> Une décision tirée d'un résumé automatique seul : `resume_seul: true` (elle reste « à confirmer »). Une nouvelle valeur seulement dite à l'oral (réunion, appel), sans écrit qui la reprenne : `source_orale: true`. Une décision que seul le PM peut prendre, parce qu'elle dépend de ce qu'il sait hors du Studio (un échange, une intention, un engagement) : `savoir_pm: true`.
> Règle de lecture commune : <colle ici, telle quelle, la section « Règle de lecture commune » de ce skill>.
> Écris le fichier que donne la dernière ligne de `lot`, d'un seul coup avec l'outil d'écriture de fichier, sans script ni relecture : une liste JSON, un objet par sujet. Pour `rien`, seulement `{"sujet": "S12", "classe": "rien"}`. Sinon : `{"sujet": "<son identifiant dans le lot>", "classe": "M|PM|absence", "titre": "<3 à 8 mots en clair>", "contexte": "<qui a dit quoi, et quand, en une ou deux phrases simples>", "passages": ["<identifiants des extraits>"], "recommande": "…", "pourquoi": "…", "depend_de": "<identifiant d'un autre sujet>" ou null, "absence": {"fichier": "…", "texte": "…"} ou null, "resume_seul": false, "source_orale": false, "savoir_pm": false}` ; `ancienne` et `nouvelle` (`{"texte": "…"}`) seulement pour reformuler une valeur peu claire.
> Le titre et le contexte sont lus par le PM : aucun code dedans (« le PM », la personne, est permis) (ni numéro de décision, de règle, de question, d'US, de ticket, ni lettre), seulement des mots. Exemple de contexte : « Le contrat signé du 6 novembre fixe l'hébergement en France ; au kick-off du 9 novembre, le client a demandé un hébergement chez lui. » Un titre ou un contexte qui contient un code est refusé et le sujet t'est rendu. Réponds seulement « lot <k> écrit, n sujets ».

## Règle de lecture commune

# Règle de lecture commune d'un Studio

But : qu'aucun outil ne présente comme vraie une donnée qu'une source plus récente du Studio a changée.

## Règle 1 · La dernière source datée fait foi

Sur un sujet, la dernière source datée fait foi. Un document vivant qui la contredit est en retard, et non incomplet.

Un document signé ne cède qu'à une source écrite qui pèse au moins autant : document signé, puis échange écrit, puis oral.

Une décision tirée d'un résumé automatique seul reste « à confirmer ».

## Règle 2 · Donnée figée

Avant d'annoncer une donnée figée (agenda, fiche, règle, horaire d'un rituel), la rapprocher des échanges récents du Studio.

S'ils divergent, le dire et donner les deux valeurs avec leurs dates. Ne jamais trancher seul.

## Règle 3 · Action déjà faite

Avant d'annoncer une action « à faire », chercher la preuve qu'elle est faite : compte rendu coché, ticket, commit ou branche.

Si elle l'est, dire « déjà fait le {date} » au lieu de la reporter.
