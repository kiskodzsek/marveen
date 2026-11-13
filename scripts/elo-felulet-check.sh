#!/usr/bin/env bash
# elo-felulet-check.sh [--stamp <asset file>] <marabel-worktree> <app-preview file | Component> [...]
#
# Only a LIVE customer surface may appear in marketing material (film, Reel, post, landing image).
# /app-preview is notFound in production, so a component rendered there is not live just because it renders.
# For every given component (or every @/components import of an app-preview file) this checks on origin/main
# whether anything under src/app OUTSIDE app-preview uses it (<Component ...>). If not: NEM ÉLŐ, exit 1.
#
# --stamp <asset>: on a clean pass, write store/kep-kapu/<asset basename>.elo (the product-image-gate's ELO line
# "ELO: ok <Component,...>" needs it, max. 7 days old). Any other run (NEM ÉLŐ, usage, fetch or import-parse error)
# removes an older stamp of that asset.
# Imports: every form from @/components (multi-line, default, single quote); a namespace import or a count mismatch
# stops the check with exit 2 (Viktor 41284). "Customer route" = anything under src/app except src/app/app-preview.
# Scope (Viktor 41311 INFO 6): only the @/components layer is followed; @/app and local ./x-preview imports of an
# app-preview file are not, so name the components visible on the image as arguments too: that list is the cover.
#
# Why: 2026-11-13, Első éved r4-G Reel: the phone shot showed BabyTellHome ("Fotót adok hozzá"), not live since
# Marabel #563 (2026-10-20); Lex 41089 caught it before the ad launch ("Él-e vevőnek ez a képernyő prodon ma?").
# The same day the Short v3.9 J4 phone turned out to be the app-preview editor shell (Klodel 41172). Retro R4
# (card 686f1b5f): a machine check, not a note.
#
# Limit: it measures whether the component is wired into a customer route, not whether the configured state
# (sample data, query switch) occurs there. Only JSX use (<Component) counts. Compare the image with the live page.
# Exit: 0 = every component live; 1 = at least one NEM ÉLŐ; 2 = usage / git error.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KAPU="${ELO_KAPU_DIR:-${CLAUDE_PROJECT_DIR:-$HERE/..}/store/kep-kapu}"
STAMP=""
if [ "${1:-}" = "--stamp" ]; then
  [ $# -ge 2 ] || { echo "--stamp needs an asset file" >&2; exit 2; }
  STAMP="$(basename -- "$2")"; shift 2
  # the old stamp goes first: only a clean, complete run below writes it again (a usage, fetch or parse error too)
  rm -f -- "$KAPU/$STAMP.elo"
fi
R="${1:-}"; [ $# -ge 1 ] && shift
if [ -z "$R" ] || [ "$#" -lt 1 ]; then
  echo "usage: $0 [--stamp <asset>] <marabel-worktree> <src/app/app-preview/x.tsx | Component> [...]" >&2; exit 2
fi
# Viktor 41284 (5): a failed fetch would judge on a stale origin/main; the repo's origin goes into the stamp
git -C "$R" fetch -q origin main || { echo "git fetch origin main hibás ($R): elavult origin/main-en nem ítélek" >&2; exit 2; }
M=$(git -C "$R" rev-parse --short origin/main) || exit 2
URL=$(git -C "$R" remote get-url origin 2>/dev/null)
echo "origin/main $M ($URL)"
bad=0
comps=()
# Viktor 41284 (1): every import form from @/components counts (multi-line, default, single quote, combined); an
# import whose names cannot be read (namespace "* as X") stops the check (exit 2), so a partial read never stamps.
EXTRACT='
import re, sys
src = sys.stdin.read()
src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
src = re.sub(r"(?m)^\s*//.*$", " ", src)
names, bad = [], []
total = len(re.findall(r"""\bfrom\s*["\x27]@/components/""", src))
# Viktor 41311 INFO 5: a dynamic import() / require() of a component is not read below: it stops the check
# Viktor 41389 LOW 1: "*", not "+": a bare prefix literal ("@/components/" + name) stops the check too
for m in re.finditer(r"""\b(?:import|require)\s*\(\s*["\x27](@/components/[^"\x27]*)""", src):
    bad.append(f"{m.group(1)}: dinamikus import/require")
# Viktor 41371 LOW 1: a template-literal or non-literal argument cannot be read either: it stops the check too
# (a backtick literal without "@/components" and without ${...} is another module and passes)
for m in re.finditer(r"""(?<![.\w$])(?:import|require)\s*\(\s*([^\s"\x27])""", src):
    if m.group(1) == "`":
        lit = src[m.end(1):src.find("`", m.end(1))]
        if "@/components" not in lit and "${" not in lit:
            continue
    bad.append(f"{src[m.start():m.end()+40].splitlines()[0]}: dinamikus import/require nem olvasható argumentummal")
seen = 0
for m in re.finditer(r"""\bimport\s+(type\s+)?((?:(?!\bimport\b)[^;])*?)\s*from\s*["\x27](@/components/[^"\x27]+)["\x27]""", src, re.S):
    seen += 1
    if m.group(1):
        continue  # import type: no runtime component
    clause = m.group(2).strip()
    br = re.search(r"\{([^}]*)\}", clause, re.S)
    head = clause[:br.start()] if br else clause
    head = head.strip().rstrip(",").strip()
    if "*" in head:
        bad.append(f"{m.group(3)}: névtér-import ({head})")
        continue
    if head:
        names.append(head)
    if br:
        for part in br.group(1).split(","):
            part = part.strip()
            if not part or part.startswith("type "):
                continue
            names.append(re.split(r"\s+as\s+", part)[-1].strip())
if seen != total:
    bad.append(f"{total} @/components import van, {seen} olvasható")
for b in bad:
    print("OLVASHATATLAN " + b, file=sys.stderr)
print("\n".join(n for n in names if re.fullmatch(r"[A-Z][A-Za-z0-9]*", n)))
sys.exit(3 if bad else 0)
'
for a in "$@"; do
  if [[ "$a" == *.tsx || "$a" == *.ts ]]; then
    src="$(git -C "$R" show "origin/main:$a")" || { echo "nincs ilyen fájl az origin/main-en: $a" >&2; exit 2; }
    got="$(printf '%s\n' "$src" | python3 -I -c "$EXTRACT")" || { echo "az importok nem olvashatók teljesen ($a): nem ítélek" >&2; exit 2; }
    while IFS= read -r c; do [ -n "$c" ] && comps+=("$c"); done <<<"$got"
  else
    # Viktor 41284 (6): the name goes into a regex; only a plain component name is accepted
    [[ "$a" =~ ^[A-Z][A-Za-z0-9]*$ ]] || { echo "nem komponens-név: $a" >&2; exit 2; }
    comps+=("$a")
  fi
done
[ "${#comps[@]}" -gt 0 ] || { echo "nincs vizsgálható komponens" >&2; exit 2; }
out=()
for c in "${comps[@]}"; do
  users=$(git -C "$R" grep -l -E "<$c([[:space:]/>]|\$)" origin/main -- 'src/app' ':!src/app/app-preview' 2>/dev/null | sed 's#^origin/main:##')
  if [ -n "$users" ]; then
    line="ÉLŐ      $c <- $(echo "$users" | head -3 | tr '\n' ' ')"
  else
    line="NEM ÉLŐ  $c (csak az app-preview-ban vagy sehol; prodon nem látja vevő)"; bad=1
  fi
  echo "$line"; out+=("$line")
done
if [ -n "$STAMP" ]; then
  f="$KAPU/$STAMP.elo"
  if [ "$bad" -eq 0 ]; then
    mkdir -p "$KAPU" && {
      echo "EREDMENY: ELO"
      echo "ORIGIN_MAIN: $M"
      echo "ORIGIN_URL: $URL"
      echo "MERVE: $(date '+%Y-%m-%d %H:%M:%S')"
      printf '%s\n' "${out[@]}"
    } >"$f" && echo "bélyeg: $f"
  else
    echo "nincs bélyeg (NEM ÉLŐ komponens)" >&2
  fi
fi
exit $bad
