// Runs the pinned page (skills/mon-studio/assets/page-epinglee.html) in a fake browser, for
// tests/test_cockpit_authorizations.py. Usage: node tests/tester-epinglee.js <page.html> <payload.json>
// The payload holds `lignes` (what the tool « lignes » returns), and may hold `autorisations` (what the tool
// « autorisations » returns), `attentes` (what the tool « attentes » returns), `cliquer` (a list of [data attribute,
// value] to click in order), `deciderErreur` and `repondreErreur` (the error code the tool « decider » or « repondre »
// throws), `repondre` (what « repondre » returns, Q40: { mode, raison, texte, clic }), `anciennes` (the « Anciennes » lines of the board), `reclassement` (true: the switch of the reclassement button is on), `lire` (what the tool « lire » returns) and `lireErreur`. Prints a JSON of what the page shows and of the tool calls it made.
// The page as the app runs it (option B, Q13): the shell (page-epinglee.html) asks the connector's `gabarit` tool for
// the served code (page-servie.html), then runs it in a <script> filled by textContent. The file given is either one;
// the other is taken next to it, or from the plugin's assets. `gabaritErreur` (an error code) or `gabaritVide` (an
// empty answer) stand for a connector that does not serve the code.
const fs = require('fs'), vm = require('vm'), path = require('path');
const ASSETS = path.join(__dirname, '..', 'skills', 'mon-studio', 'assets');
const donne = fs.readFileSync(process.argv[2], 'utf8');
const entree = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const voisin = (nom) => [path.join(path.dirname(process.argv[2]), nom), path.join(ASSETS, nom)].find((f) => fs.existsSync(f));
const estCoquille = donne.includes('"gabarit"') && !donne.includes('var SERVEUR');
const coquille = estCoquille ? donne : fs.readFileSync(voisin('page-epinglee.html'), 'utf8');
const servi = estCoquille ? fs.readFileSync(voisin('page-servie.html'), 'utf8') : donne;
const BLOC_STYLE = /<style>\n?([\s\S]*?)<\/style>\n?/g, BLOC_SCRIPT = /<script>\n?([\s\S]*?)<\/script>\n?/g;
// The same cut as the connector's decouper_gabarit.
const gabarit = { version: 'essai', css: [...servi.matchAll(BLOC_STYLE)].map((m) => m[1]).join('\n'),
  js: [...servi.matchAll(BLOC_SCRIPT)].map((m) => m[1]).join('\n'),
  html: servi.replace(BLOC_STYLE, '').replace(BLOC_SCRIPT, '').trim() };
// The shell's scripts, in order; « projetFixe » fills its PROJET_FIXE as install.py copie-projet does.
let script = [...coquille.matchAll(BLOC_SCRIPT)].map((m) => m[1]).join('\n');
if (entree.projetFixe) script = script.replace('var PROJET_FIXE = "";', 'var PROJET_FIXE = ' + JSON.stringify(entree.projetFixe) + ';');
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: '', textContent: '', hidden: false, className: '', style: {}, attrs: {},
  classList: { add() {}, remove() {} }, setAttribute(a, v) { this.attrs[a] = String(v); },
  getAttribute(a) { return a in this.attrs ? this.attrs[a] : null; }, addEventListener() {},
  closest() { return null; }, scrollIntoView() {}, focus() {},
  querySelector() { return this.enfant || (this.enfant = el(this.id + ' >')); }, appendChild(x) { (this.enfants = this.enfants || []).push(x); } });
const ecoutes = {};
const injectes = [];
const doc = { getElementById: el, addEventListener(t, fn) { (ecoutes[t] = ecoutes[t] || []).push(fn); }, visibilityState: 'visible', title: 'Mon Studio',
  createElement: (tag) => ({ tagName: tag.toUpperCase(), textContent: '', className: '', appendChild() {} }),
  head: { appendChild(x) { injectes.push(x.tagName); } },
  // The loader's <script>: run where the page runs, as the browser does when it is appended.
  body: { appendChild(x) { injectes.push(x.tagName); if (x.tagName === 'SCRIPT') vm.runInContext(x.textContent, ctx); } } };
const appels = [], veilles = {}, srv0 = 'host:mon-studio';
const now = Date.now();
const mcp = {
  watchTool(srv, outil, args, cb) { if ((entree.refuserVeille || []).includes(outil)) throw new Error('not_in_manifest'); veilles[outil] = cb; },
  async callTool(srv, outil, args) {
    if (outil === 'gabarit') {   // the shell's call, kept out of `appels`
      if (entree.gabaritErreur) { const e = new Error('outil absent'); e.code = entree.gabaritErreur; throw e; }
      return { payload: entree.gabaritVide ? {} : gabarit };
    }
    appels.push([outil, args]);
    if (outil === 'decider' && entree.deciderErreur) { const e = new Error('refusé'); e.code = entree.deciderErreur; throw e; }
    if (outil === 'repondre' && entree.repondreErreur) { const e = new Error('session partie'); e.code = entree.repondreErreur; throw e; }
    if (outil === 'attentes') return { payload: entree.attentes || { actif: false, attentes: [] } };
    if (outil === 'repondre' && entree.repondre) return { payload: entree.repondre };
    if (outil === 'projet') return { payload: entree.projet || { introuvable: true } };
    if (outil === 'lire' && entree.lireErreur) { const e = new Error('illisible'); e.code = entree.lireErreur; throw e; }
    if (outil === 'lire') return { payload: entree.lire || { texte: '' } };
    if (outil === 'autorisations') return { payload: entree.autorisations || { demandes: [], decisions: [], actif: false } };
    return { payload: { decide: true } };
  },
  async invalidate() { return {}; },
  async listTools() { return { servers: [{ server: srv0, tools: (entree.outils || []).map((name) => ({ name, description: '' })) }] }; },
};
// Une horloge que le test avance (avancerMs) : la page relit Date.now().
let decalage = 0;
class Horloge extends Date { static now() { return Date.now() + decalage; } }
const minuteurs = [];
// « stockage »: the browser's localStorage (key → value) when the test gives one; absent, any access throws, as in a
// private window. « stockageLu » in the output: what the page left in it.
const stockage = entree.stockage ? Object.assign({}, entree.stockage) : null;
const ctx = { document: doc, claude: { use: async () => mcp }, navigator: {}, setTimeout(fn, ms) { minuteurs.push(ms); return 0; }, clearTimeout() {},
  setInterval() { return 0; }, requestAnimationFrame() { return 0; }, cancelAnimationFrame() {}, console, Date: Horloge, Promise,
  Object, Array, String, Number, Math, JSON, RegExp, isNaN, parseInt, Error };
if (stockage) ctx.localStorage = { getItem: (k) => (k in stockage ? stockage[k] : null), setItem: (k, v) => { stockage[k] = String(v); } };
vm.createContext(ctx);
vm.runInContext(script, ctx);
const tick = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };
(async () => {
  await tick();
  const lignes = entree.lignes.map((l) => Object.assign({}, l, { depuis: l.depuis || now - 3600000 }));
  const page = { genere: now, pastilles_lues: true, lignes, anciennes: [], fils_rouges: entree.fils_rouges || [], projets: entree.projets || [],
    liste_projets: entree.liste_projets || null, matin: entree.matin || null, lecture_app: entree.lecture_app || undefined,
    mise_en_route: entree.mise_en_route || undefined, conflits: entree.conflits, rangees: entree.rangees || [], a_ranger: entree.a_ranger || [], ranger_texte: entree.ranger_texte || '',
    sans_action: entree.sans_action || [], plus_tard: entree.plus_tard || {}, reclassement: entree.reclassement || undefined };
  if (veilles.lignes) veilles.lignes({ type: 'data', result: { payload: page } });   // none when the code was not served
  if (veilles.autorisations && entree.autorisations) veilles.autorisations({ type: 'data', result: { payload: entree.autorisations } });
  if (veilles.attentes && entree.attentes) veilles.attentes({ type: 'data', result: { payload: entree.attentes } });
  if (veilles.attentes && entree.attentesErreur) veilles.attentes({ type: 'error', error: { code: entree.attentesErreur } });
  // Des lignes « Anciennes » (champ `anciennes` du payload) : le tableau relu les porte.
  if (entree.anciennes && veilles.lignes) veilles.lignes({ type: 'data', result: { payload: Object.assign({}, page, { anciennes: entree.anciennes.map((l) => Object.assign({}, l, { depuis: l.depuis || now - 9 * 86400000 })) }) } });
  await tick();
  const premier = (els.boite || {}).innerHTML || '';
  if (entree.avancerMs) decalage = entree.avancerMs;
  if (veilles.attentes && entree.attentesApres) veilles.attentes({ type: 'data', result: { payload: entree.attentesApres } });
  else if (entree.avancerMs && veilles.attentes && entree.attentes) veilles.attentes({ type: 'data', result: { payload: entree.attentes } });
  await tick();
  const avant = (els.autorisations || {}).innerHTML || '';
  const tableauAvant = (els.boite || {}).innerHTML || '';
  const projetsAvant = (els.projets || {}).innerHTML || '';
  const matinAvant = (els.matin || {}).innerHTML || '';
  for (const [attr, valeur] of entree.cliquer || []) {
    const bouton = { tagName: 'BUTTON', disabled: false, innerHTML: '', textContent: '',
      getAttribute: (a) => (a === attr ? valeur : (entree.attributs || {})[a] || null), closest: () => null,
      matches: () => false };
    const ev = { target: { closest: (sel) => (sel.includes(attr) ? bouton : null) }, preventDefault() {}, stopPropagation() {} };
    for (const fn of ecoutes.click || []) fn(ev);
    await tick();
  }
  const g = (id) => els[id] || {};
  console.log(JSON.stringify({
    blocHidden: !!g('bloc-autorisations').hidden, blocTitre: g('autorisations-titre').textContent || '',
    compte: g('compte').textContent || '', ongletConflitsGlobalHidden: !!g('onglet-conflits').hidden, sans: g('sans').innerHTML || '',
    clics: g('clics').innerHTML || '', anciennes: g('anciennes').innerHTML || '', anciennesRepliees: (g('anciennes').style || {}).display === 'none',
    anciennesHidden: !!g('bloc-anciennes').hidden,
    attendre: g('attendre').innerHTML || '', attendreHidden: !!g('bloc-attendre').hidden, attendreReplie: (g('attendre').style || {}).display === 'none',
    bloc: g('autorisations').innerHTML || '', blocAvant: avant, decisions: g('decisions').innerHTML || '',
    decisionsHidden: g('decisions').hidden !== false, noteAttentes: g('note-attentes').hidden === false ? g('note-attentes').textContent : '', tableau: g('boite').innerHTML || '', tableauAvant, alerte: g('alerte-texte').textContent || '',
    appels, veilles: Object.keys(veilles), premier, minuteurs,
    studios: g('studios').innerHTML || '', projetCache: g('bloc-projet').hidden !== false, projetNom: g('projet-nom').textContent || '',
    projetQuestions: g('projet-questions').innerHTML || '', projetSujets: g('projet-sujets').innerHTML || '',
    projetTiers: g('projet-bloc-tiers').hidden === false ? g('projet-tiers').innerHTML : '', projetJournal: g('projet-journal').innerHTML || '',
    projetConflits: g('projet-conflits').hidden === false ? g('projet-conflits').innerHTML : '', projetConflitsBrut: g('projet-conflits').innerHTML || '',
    projetLigneConflits: g('projet-ligne-conflits').hidden === false ? g('projet-ligne-conflits').innerHTML : '',
    ongletConflits: g('projet-onglet-conflits').innerHTML || '', projetPrincipalHidden: !!g('projet-principal').hidden,
    boiteCachee: (g('boite').style || {}).display === 'none',
    projets: g('projets').innerHTML || '', projetsAvant, projetsHidden: !!g('bloc-projets').hidden,
    matin: g('matin').innerHTML || '', matinAvant, matinHidden: !!g('bloc-matin').hidden,
    ongletsHidden: !!g('onglets').hidden, ongletMatin: g('onglet-matin').innerHTML || '',
    ongletMatinLabel: (g('onglet-matin').attrs || {})['aria-label'] || '',
    ongletMatinSelected: (g('onglet-matin').attrs || {})['aria-selected'] || '',
    ongletTableauSelected: (g('onglet-tableau').attrs || {})['aria-selected'] || '',
    vueTableauHidden: !!g('vue-tableau').hidden,
    titreDocument: doc.title, titrePage: g('titre-page').textContent || '', tousProjetsHidden: !!g('tous-projets').hidden,
    studiosHidden: !!g('studios').hidden,
    rangeesVisibles: !g('bloc-rangees').hidden && (g('bloc-rangees').style || {}).display !== 'none',
    aRanger: g('a-ranger').innerHTML || '', aRangerHidden: !!g('bloc-a-ranger').hidden, aRangerTitre: g('a-ranger-titre').textContent || '',
    ongletProjet: g('projet-onglet-projet').innerHTML || '', ongletProjetLabel: (g('projet-onglet-projet').attrs || {})['aria-label'] || '',
    sujetsReplies: (g('projet-sujets').style || {}).display === 'none', journalReplie: (g('projet-journal').style || {}).display === 'none',
    sujetsOuvert: (g('projet-sujets-bascule').attrs || {})['aria-expanded'] || '', stockageLu: stockage,
    miseEnRoute: g('mise-en-route').innerHTML || '', miseEnRouteHidden: !!g('bloc-mise-en-route').hidden,
    appels, veilles: Object.keys(veilles),
    coquille: g('mon-studio').innerHTML || '', coquillePanne: g('mon-studio >').textContent || '', injectes,
  }));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
