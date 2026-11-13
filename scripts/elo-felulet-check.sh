#!/usr/bin/env bash
# elo-felulet-check.sh [--stamp <asset file>] <marabel-worktree> <app-preview file | Component> [...]
#
# Only a LIVE customer surface may appear in marketing material (film, Reel, post, landing image).
# /app-preview is notFound in production, so a component rendered there is not live just because it renders.
# For every given component (or every @/components import of an app-preview file) this checks on origin/main
# whether anything under src/app OUTSIDE app-preview uses it (<Component ...>). If not: NEM ÉLŐ, exit 1.
#
# --stamp <asset>: on a clean pass, write store/kep-kapu/<asset basename>.elo (the product-image-gate's ELO line
# "ELO: ok" needs it, max. 7 days old). A failing run removes an older stamp of that asset.
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
fi
R="${1:-}"; [ $# -ge 1 ] && shift
if [ -z "$R" ] || [ "$#" -lt 1 ]; then
  echo "usage: $0 [--stamp <asset>] <marabel-worktree> <src/app/app-preview/x.tsx | Component> [...]" >&2; exit 2
fi
git -C "$R" fetch -q origin main 2>/dev/null
M=$(git -C "$R" rev-parse --short origin/main) || exit 2
echo "origin/main $M"
bad=0
comps=()
for a in "$@"; do
  if [[ "$a" == *.tsx || "$a" == *.ts ]]; then
    src="$(git -C "$R" show "origin/main:$a")" || { echo "nincs ilyen fájl az origin/main-en: $a" >&2; exit 2; }
    while IFS= read -r c; do [ -n "$c" ] && comps+=("$c"); done < <(
      printf '%s\n' "$src" | grep -E '^import \{[^}]+\} from "@/components/' |
        sed -E 's/^import \{([^}]+)\}.*/\1/' | tr ',' '\n' | sed -E '/^ *type /d; s/ as .*//; s/[[:space:]]//g' | grep -E '^[A-Z]')
  else
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
      echo "MERVE: $(date '+%Y-%m-%d %H:%M:%S')"
      printf '%s\n' "${out[@]}"
    } >"$f" && echo "bélyeg: $f"
  else
    rm -f -- "$f"
    echo "nincs bélyeg (NEM ÉLŐ komponens)" >&2
  fi
fi
exit $bad
