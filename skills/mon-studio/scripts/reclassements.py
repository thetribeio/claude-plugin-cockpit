#!/usr/bin/env python3
"""What the PM corrected in the board's order: a summary of ~/Mon Studio/.parc/reclassements.jsonl, without a model.

The board's button (switch « reclassement », PM 2026-11-17, for him alone at first) notes one JSON line per click:
the date, the line's key, its origin (session or ingestion), its Studio and text, what the rules computed (impact,
raison, effort, regle: « étiquette » or the rule) and what the PM chose (`pm`: dabord, ensuite or annuler). This
script reads it, read-only, and says how many corrections, in which direction, by computed reason and rule, by
origin, and the ten latest. It serves, after a week or two, to correct the rules of parc.priorite by hand.

    python3 reclassements.py               the summary, in French, for the PM
    python3 reclassements.py --json        the same figures as JSON
    python3 reclassements.py --fichier F   another journal (a copy, a test)

Nothing leaves the Mac: no network, no model, nothing written."""
import collections
import json
import os
import pathlib
import sys

MON_STUDIO = pathlib.Path(os.environ.get('MON_STUDIO') or pathlib.Path.home() / 'Mon Studio')
JOURNAL = MON_STUDIO / '.parc' / 'reclassements.jsonl'
SENS = {'dabord': "vers « D'abord »", 'ensuite': 'hors de « D\'abord »', 'annuler': 'annulées'}
DERNIERES = 10


def lire(chemin):
    """The journal's entries, oldest first; a line that is not a JSON object is skipped."""
    try:
        lignes = pathlib.Path(chemin).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for l in lignes:
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get('pm') in SENS:
            out.append(x)
    return out


def finales(entrees):
    """The order the PM left on each line: his last click on it, or nothing when that click undid the one before."""
    par_cle = {}
    for x in entrees:
        par_cle[x.get('cle')] = x
    return [x for x in par_cle.values() if x['pm'] != 'annuler']


def raison_calculee(x):
    c = x.get('calcul') or {}
    impact = c.get('impact') or '?'
    return f"{impact}" + (f" · {c['raison']}" if c.get('raison') else '')


def resumer(entrees):
    gardees = finales(entrees)
    return {
        'clics': len(entrees),
        'sens': dict(collections.Counter(x['pm'] for x in entrees)),
        'corrections_gardees': len(gardees),
        'par_raison': collections.Counter(f"{SENS[x['pm']]} · calculé {raison_calculee(x)}" for x in gardees).most_common(),
        'par_regle': collections.Counter(f"{SENS[x['pm']]} · {(x.get('calcul') or {}).get('regle') or '?'}"
                                         for x in gardees).most_common(),
        'par_origine': collections.Counter(f"{x.get('origine') or '?'} · {SENS[x['pm']]}" for x in gardees).most_common(),
        'dernieres': [{k: x.get(k) for k in ('date', 'origine', 'studio', 'texte', 'pm')} | {'calcule': raison_calculee(x)}
                      for x in reversed(entrees[-DERNIERES:])],
    }


def en_francais(r):
    if not r['clics']:
        return 'Aucune correction notée pour l\'instant (le journal est vide ou absent).'
    s = r['sens']
    out = [f"{r['clics']} clics : {s.get('dabord', 0)} {SENS['dabord']}, {s.get('ensuite', 0)} {SENS['ensuite']}, "
           f"{s.get('annuler', 0)} {SENS['annuler']}. {r['corrections_gardees']} lignes gardent ton classement.", '']
    for titre, cle in (('Par classement calculé', 'par_raison'), ('Par règle', 'par_regle'), ('Par origine', 'par_origine')):
        if r[cle]:
            out.append(f'{titre} :')
            out += [f'  {n} · {k}' for k, n in r[cle]]
            out.append('')
    out.append('Les dix plus récentes :')
    for x in r['dernieres']:
        texte = ' '.join(str(x.get('texte') or '').split())
        texte = texte if len(texte) <= 90 else texte[:89] + '…'
        out.append(f"  {str(x.get('date') or '')[:16].replace('T', ' ')} · {SENS[x['pm']]} (calculé {x['calcule']}) · "
                   f"{x.get('origine') or '?'} · {x.get('studio') or '?'} · {texte}")
    return '\n'.join(out)


def main(argv):
    chemin = JOURNAL
    if '--fichier' in argv:
        i = argv.index('--fichier')
        if i + 1 >= len(argv):
            print(__doc__.strip())
            return 2
        chemin = pathlib.Path(argv[i + 1]).expanduser()
    r = resumer(lire(chemin))
    print(json.dumps(r, ensure_ascii=False, indent=1) if '--json' in argv else en_francais(r))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
