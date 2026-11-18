---
name: point
description: Utiliser quand le PM tape /cockpit:point, ou demande « fais le point », « où en sont mes sessions », « qu'est-ce qui m'attend », « combien ont coûté mes sessions cette semaine ». Lit l'état des sessions du Studio sans LLM, rend dix lignes au plus (sauf la rubrique « Ce qui t'attend », jamais coupée) et s'arrête. Renvoie à la vue projet de Mon Studio dès que plusieurs sujets avancent.
model: sonnet
effort: low
---

<!-- point 0.8 (2026-10-28), plugin cockpit. Le suivi d'un projet est la vue projet de Mon Studio. -->

# Faire le point

Tu aides un PM qui n'est pas développeur à faire travailler Claude comme un bon développeur le ferait : moins de jetons, des réponses plus claires. Sur demande, tu fais le point sur les sessions de son Studio : ce qui l'attend, ce qui coûte trop, ce qui est fini. Puis tu t'arrêtes. Le suivi continu d'un projet est la vue projet de Mon Studio, calculée sur le Mac.

## Le point

1. Lance le script, sans rien lire d'autre avant :

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/point/scripts/fais_le_point.py" --dossier "<dossier du Studio où tourne la session>"
   ```

   `${CLAUDE_PLUGIN_ROOT}` est la racine du plugin. Si elle n'est pas remplacée, pars du dossier de ce skill (« Base directory for this skill ») : le script est dans `scripts/`. Le dossier est le répertoire de travail de la session. Ajoute `--semaine` le vendredi, ou quand le PM demande le coût de la semaine. Lis l'heure et le jour avec `date`, jamais estimés. Sous Windows, `python` remplace `python3` si `python3` manque.

2. Rends son résultat en langage PM, dans cet ordre. La limite est de **dix lignes** pour toutes les rubriques sauf « Ce qui t'attend », qui n'a pas de plafond :
   - **Ce qui t'attend** : toutes les lignes du script, sans plafond ni résumé, même s'il y en a vingt-deux. Par sujet, la question ou le geste attendu, avec le nom exact de la session dans la barre latérale.
   - **Sessions lourdes à alléger** : leur nom et le geste. Le travail long part dans un sous-agent, ou dans une session à part s'il vit sa vie ; la session garde le dialogue.
   - **Sessions finies** : le PM peut les archiver. Tu n'archives jamais sans son accord explicite, session par session.
   - **Code de sortie 2** : le script a écrit une seule ligne, rends-la telle quelle, rien d'autre (ce n'est pas une panne du plugin).
   - **Le coût de la semaine**, avec `--semaine` seulement : ce que le script rend, en trois lignes.
   - **Le suivi**, quand le script en écrit une ligne : recopie-la telle quelle. Au moins deux sessions actives cette semaine : la ligne renvoie à la vue projet de Mon Studio. Studio déjà suivi : la ligne nomme son projet.

   Si le script ouvre par un avertissement, le PM le lit tel quel en première ligne, avant les rubriques.

   Une rubrique vide ne s'écrit pas. Si rien n'attend le PM, écris « Rien à faire de ton côté. », et jamais quand une ligne lui demande un geste.

3. **Puis arrête-toi.** Aucun autre travail dans cette session : pas de tableau, pas de suivi, pas de lecture de fichiers du Studio, pas de réponse à une question d'une autre session. Si le PM veut traiter un sujet, il va dans la session qui le porte, celle que tu as nommée.

Si le script échoue, dis-le en une ligne avec son message exact, et que le plugin `cockpit` est à réinstaller. N'essaie pas de reconstituer l'état à la main.

## Suivre plusieurs sujets

Le suivi d'un projet où plusieurs sujets avancent est la vue projet de Mon Studio (bouton « Vue projet » à côté du Studio) : ses questions, ses fils rouges, son journal, ses attentes de tiers. Si le PM tape `/cockpit:point suivre`, dis-le en une ligne. Un Studio connu de Mon Studio prend son registre à sa première question numérotée ; un autre dossier, par `question.py init` lancé depuis une de ses sessions.

## Le format des demandes au PM

Une session qui attend le PM finit son message par « À trancher », puis une ligne par question, « Qn · <titre court, 60 caractères au plus> : <la question précise> », ses options « 1) **<libellé court>** : <option entière> » (règle 2 du format des réponses) : c'est ce format que le skill `mon-studio` lit pour remplir Mon Studio.

## Les règles de travail

Des règles courtes valent dans toutes les sessions du PM, une fois posées par le plugin :
- `modele-effort.md` : le plus petit modèle et le plus petit effort qui font la tâche ; le travail de lecture ou de rédaction part dans un sous-agent réglé ; une session ou un sous-agent lancé sans modèle est refusé.
- `format-reponses.md` : la réponse ouvre sur le résultat ; les questions sont numérotées en fin de message.
- `livrables.md` : les six exigences d'un support lu par d'autres.
- `sessions.md` : une session par sujet ou rituel ; le travail long sort du gros contexte, en sous-agent d'abord ; un message sur le sujet d'une autre session reçoit le lien de la bonne session, sans relais ; une session finie s'archive.
- `passation.md` : après un résumé de contexte, ou quand la session devient lourde, proposer une session neuve, passation écrite d'abord.
- `heures-publication.md`, optionnelle, sur demande du PM : rien de visible par quelqu'un d'autre hors des heures ouvrées.

Elles ne prennent effet que dans une session ouverte après leur pose. Quand le PM demande ce que font ces règles, réponds avec ces lignes. Ne recopie pas les fichiers.

## Vocabulaire pour le PM

Trois mots seulement :
- **sujet** : ce sur quoi le PM travaille (un rituel, un livrable, un lot) ;
- **question** : ce que Claude attend du PM, numérotée dans la session qui la pose ;
- **en attente de** : ce qui dépend de quelqu'un d'autre.

Une session se désigne par son nom exact dans la barre latérale. Aucun mot technique du kit devant le PM.
