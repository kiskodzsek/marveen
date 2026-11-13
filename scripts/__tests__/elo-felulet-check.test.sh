#!/usr/bin/env bash
# scripts/elo-felulet-check.sh (retro R4, card 686f1b5f; Viktor 41284): every import form of an app-preview file is read,
# an unreadable import stops the check, and the stamp is written only by a clean, complete run.
# A throw-away Marabel-like repo: a bare "origin" and a clone, nothing touches a real repo or the real store.
#
# Run:  bash scripts/__tests__/elo-felulet-check.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHK="$ROOT/scripts/elo-felulet-check.sh"
[ -e "$CHK" ] || { echo "FATAL: missing $CHK" >&2; exit 2; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/elofel.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
git init -q --bare -b main "$SB/origin.git"
git clone -q "$SB/origin.git" "$SB/wt" 2>/dev/null
W="$SB/wt"
mkdir -p "$W/src/app/app-preview" "$W/src/app/shop" "$W/src/components"
# customer route: uses LiveCard and LiveDefault only
cat > "$W/src/app/shop/page.tsx" <<'EOF'
import { LiveCard } from "@/components/live-card";
import LiveDefault from "@/components/live-default";
export default function P() { return <main><LiveCard /><LiveDefault title="x" /></main>; }
EOF
# app-preview views: all four import forms, each with one dead component
cat > "$W/src/app/app-preview/forms.tsx" <<'EOF'
import { LiveCard } from "@/components/live-card";
import {
  DeadOne,
  DeadTwo as DeadTwoAlias,
} from "@/components/dead";
import DeadDefault from "@/components/dead-default";
import { DeadSingleQuote } from '@/components/dead-single';
import type { SomeType } from "@/components/types";
export default function V() { return <div />; }
EOF
cat > "$W/src/app/app-preview/live.tsx" <<'EOF'
import LiveDefault, { LiveCard } from "@/components/live-card";
import type { T } from "@/components/types";
EOF
cat > "$W/src/app/app-preview/ns.tsx" <<'EOF'
import { LiveCard } from "@/components/live-card";
import * as Dead from "@/components/dead";
EOF
# Viktor 41311 INFO 5: no semicolons (the clause must not swallow the next import) and a dynamic import
printf '%s\n' 'import { useState } from "react"' 'import { DeadNoSemi } from "@/components/dead-nosemi"' \
  'import { LiveCard } from "@/components/live-card"' > "$W/src/app/app-preview/nosemi.tsx"
printf '%s\n' 'import { LiveCard } from "@/components/live-card";' \
  'const D = dynamic(() => import("@/components/dead-dyn"));' > "$W/src/app/app-preview/dyn.tsx"
# Viktor 41371 LOW 1: a template literal or a variable as the argument; a plain other-module template literal passes
printf '%s\n' 'import { LiveCard } from "@/components/live-card";' \
  'const D = dynamic(() => import(`@/components/dead-tpl`));' > "$W/src/app/app-preview/dyntpl.tsx"
printf '%s\n' 'import { LiveCard } from "@/components/live-card";' 'const p = "@/components/dead-var";' \
  'const D = dynamic(() => import(p));' > "$W/src/app/app-preview/dynvar.tsx"
printf '%s\n' 'import { LiveCard } from "@/components/live-card";' \
  'const D = dynamic(() => import("@/components/" + name));' > "$W/src/app/app-preview/dynprefix.tsx"
printf '%s\n' 'import { LiveCard } from "@/components/live-card";' \
  'const L = await import(`lodash`); const v = cfg.import(x);' > "$W/src/app/app-preview/dynother.tsx"
git -C "$W" add -A && git -C "$W" commit -qm init && git -C "$W" push -q origin main 2>/dev/null

run() { OUT="$(env ELO_KAPU_DIR="$SB/kapu" bash "$CHK" "$@" 2>&1)"; RC=$?; }

run "$W" src/app/app-preview/forms.tsx
check "multi-line, aliased, default and single-quote imports are all read (exit 1)" "$(ok "$RC" = 1)" "rc=$RC $OUT"
for c in DeadOne DeadTwoAlias DeadDefault DeadSingleQuote; do
  check "  NEM ÉLŐ $c" "$(ok -n "$(printf '%s\n' "$OUT" | grep "^NEM ÉLŐ  $c ")")" "$OUT"
done
check "  ÉLŐ LiveCard <- the shop page" "$(ok -n "$(printf '%s\n' "$OUT" | grep '^ÉLŐ      LiveCard <- src/app/shop/page.tsx')")" "$OUT"
check "  import type is not a component" "$(ok -z "$(printf '%s\n' "$OUT" | grep SomeType)")" "$OUT"

run --stamp reel.mp4 "$W" src/app/app-preview/live.tsx
check "default + named in one import, all live: exit 0" "$(ok "$RC" = 0)" "rc=$RC $OUT"
check "  the stamp is written, with EREDMENY, ORIGIN_MAIN, ORIGIN_URL" "$(ok -n "$(grep -l 'EREDMENY: ELO' "$SB/kapu/reel.mp4.elo" 2>/dev/null)" -a -n "$(grep '^ORIGIN_URL: .*origin.git' "$SB/kapu/reel.mp4.elo" 2>/dev/null)")" "$(cat "$SB/kapu/reel.mp4.elo" 2>/dev/null)"
check "  both components are ÉLŐ lines" "$(ok "$(grep -c '^ÉLŐ ' "$SB/kapu/reel.mp4.elo" 2>/dev/null)" = 2)"

run --stamp reel.mp4 "$W" src/app/app-preview/ns.tsx
check "a namespace import stops the check (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"
check "  and removes the earlier stamp" "$(ok ! -e "$SB/kapu/reel.mp4.elo")"

run --stamp reel.mp4 "$W" LiveCard
run --stamp reel.mp4 "$W" src/app/app-preview/forms.tsx
check "a NEM ÉLŐ run removes the earlier stamp" "$(ok "$RC" = 1 -a ! -e "$SB/kapu/reel.mp4.elo")" "rc=$RC"

run "$W" 'Dead.*'
check "a regex-shaped component argument is refused (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"

run --stamp reel.mp4 "$W" LiveCard
git -C "$W" remote set-url origin "$SB/no-such-origin.git"
run --stamp reel.mp4 "$W" LiveCard
check "a failed fetch stops the check (exit 2) and removes the stamp" "$(ok "$RC" = 2 -a ! -e "$SB/kapu/reel.mp4.elo")" "rc=$RC $OUT"

git -C "$W" remote set-url origin "$SB/origin.git"
run "$W" src/app/app-preview/nosemi.tsx
check "an import without a semicolon after another import is read (NEM ÉLŐ DeadNoSemi)" "$(ok "$RC" = 1 -a -n "$(printf '%s\n' "$OUT" | grep '^NEM ÉLŐ  DeadNoSemi ')")" "rc=$RC $OUT"
run "$W" src/app/app-preview/dyn.tsx
check "a dynamic import() of a component stops the check (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"
run "$W" src/app/app-preview/dyntpl.tsx
check "a template-literal import() of a component stops the check (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"
run "$W" src/app/app-preview/dynvar.tsx
check "an import() of a variable stops the check (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"
run "$W" src/app/app-preview/dynprefix.tsx
check "a prefix-literal import() (\"@/components/\" + name) stops the check (exit 2)" "$(ok "$RC" = 2)" "rc=$RC $OUT"
run "$W" src/app/app-preview/dynother.tsx
check "an other-module template literal and a method named import pass (exit 0, LiveCard)" "$(ok "$RC" = 0)" "rc=$RC $OUT"

echo "$((DONE-FAILS))/$DONE pass"
[ "$FAILS" -eq 0 ]
