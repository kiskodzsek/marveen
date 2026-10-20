#!/usr/bin/env bash
# SSHUNLOCK1020 -- scripts/ssh-unlock-setup.sh in staging mode (--root), with
# the real /usr/sbin/sshd as the parser and throwaway keys generated here.
# Nothing is written outside the sandbox and no sshd is started.
#
# Run:  bash scripts/__tests__/ssh-unlock-setup.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SETUP="$ROOT/scripts/ssh-unlock-setup.sh"
[ -f "$SETUP" ] || { echo "FATAL: missing $SETUP" >&2; exit 2; }
[ -x /usr/sbin/sshd ] || { echo "SKIP: no /usr/sbin/sshd on this host"; exit 0; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }
ok() { [ "$@" ] && echo 0 || echo 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/sshunlock.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
ssh-keygen -q -t ed25519 -N '' -C test-only -f "$SB/k" >/dev/null
ssh-keygen -q -t ed25519 -N '' -C test-two -f "$SB/k2" >/dev/null
ssh-keygen -q -t rsa -b 2048 -N '' -C test-rsa -f "$SB/rsa" >/dev/null
run() { OUT="$(bash "$SETUP" "$@" 2>&1)"; RC=$?; }
st() { run --user tester --lan 192.168.0.0/24 --root "$SB/r$1" "${@:2}"; }

echo "== accepted"
st 1 --pubkey "$SB/k.pub"
check "a plain ed25519 key in staging -> rc 0" "$(ok "$RC" = 0)" "$OUT"
eff() { echo "$OUT" | grep -qx "$1"; }
for want in "passwordauthentication no" "kbdinteractiveauthentication no" "authenticationmethods publickey" \
            "permitrootlogin no" "allowusers tester@192.168.0.0/24" "authorizedkeysfile /etc/ssh/authorized_keys/%u" \
            "maxauthtries 3" "logingracetime 20" "allowagentforwarding no" "allowtcpforwarding no" \
            "x11forwarding no" "permittunnel no"; do
  check "sshd -T: $want" "$(eff "$want"; echo $?)"
done
check "the live drop-ins are mirrored (usepam yes from 100-macos.conf)" "$(eff "usepam yes"; echo $?)" "$OUT"
KF="$SB/r1/etc/ssh/authorized_keys/tester"
check "the key line is restricted with from=\"<lan>\"" "$(ok -n "$(grep '^from="192.168.0.0/24" ssh-ed25519 ' "$KF")")" "$(cat "$KF")"
check "key file 644, key dir 755, drop-in 644" "$(ok "$(stat -f %Lp "$KF")" = 644 -a "$(stat -f %Lp "$SB/r1/etc/ssh/authorized_keys")" = 755 -a "$(stat -f %Lp "$SB/r1/etc/ssh/sshd_config.d/010-marveen.conf")" = 644)"
check "the drop-in sorts before 100-macos.conf" "$(ok "$(ls "$SB/r1/etc/ssh/sshd_config.d" | head -1)" = 010-marveen.conf)"
check "prints sha256 of both files" "$(ok "$(echo "$OUT" | grep -cE '^[0-9a-f]{64}  ')" = 2)"
check "says Remote Login is still off" "$(ok -n "$(echo "$OUT" | grep 'Remote Login itself is still OFF')")"

echo "== refused"
st 2 --pubkey "$SB/k";                check "a PRIVATE key is refused" "$(ok "$RC" != 0 -a ! -e "$SB/r2/etc/ssh/authorized_keys/tester")" "$OUT"
st 3 --pubkey "$SB/rsa.pub";          check "an RSA key is refused (ed25519 only)" "$(ok "$RC" != 0)" "$OUT"
printf 'command="/bin/sh" %s\n' "$(cat "$SB/k.pub")" > "$SB/opt.pub"
st 4 --pubkey "$SB/opt.pub";          check "a key with options is refused" "$(ok "$RC" != 0)" "$OUT"
cat "$SB/k.pub" "$SB/k2.pub" > "$SB/two.pub"
st 5 --pubkey "$SB/two.pub";          check "two keys in one file are refused" "$(ok "$RC" != 0)" "$OUT"
run --user tester --lan 8.8.8.0/24 --pubkey "$SB/k.pub" --root "$SB/r6"; check "a public range is refused" "$(ok "$RC" != 0)" "$OUT"
run --user tester --lan 172.40.0.0/16 --pubkey "$SB/k.pub" --root "$SB/r7"; check "a non-RFC1918 172.x range is refused" "$(ok "$RC" != 0)" "$OUT"
run --user tester --lan 192.168.0.0/8 --pubkey "$SB/k.pub" --root "$SB/r8"; check "a /8 mask is refused (too wide)" "$(ok "$RC" != 0)" "$OUT"
run --user root --lan 192.168.0.0/24 --pubkey "$SB/k.pub" --root "$SB/r9"; check "user root is refused" "$(ok "$RC" != 0)" "$OUT"
if [ "$(id -u)" != 0 ]; then
  run --user tester --lan 192.168.0.0/24 --pubkey "$SB/k.pub"
  check "live mode without sudo refuses and writes nothing" "$(ok "$RC" != 0 -a -n "$(echo "$OUT" | grep 'run with sudo')")" "$OUT"
fi
run --user tester;                    check "missing arguments -> usage (64)" "$(ok "$RC" = 64)"

echo "== PATH and overrides (Viktor 9534 P1)"
# Shadow every command the script calls with a fake that leaves a mark. Under
# sudo the caller's PATH can survive, and these dirs are agent-writable.
mkdir -p "$SB/shadow"
for c in ssh-keygen shasum sed cp mv chmod chown mkdir mktemp grep awk cut basename id rm cat ls printf; do
  printf '#!/bin/sh\necho "%s" >> "%s/shadow.hit"\nexit 0\n' "$c" "$SB" > "$SB/shadow/$c"; chmod +x "$SB/shadow/$c"
done
OUT="$(PATH="$SB/shadow:$PATH" bash "$SETUP" --user tester --lan 192.168.0.0/24 --pubkey "$SB/k.pub" --root "$SB/r10" 2>&1)"; RC=$?
check "a shadowing PATH runs none of the fakes, and staging still works" "$(ok "$RC" = 0 -a ! -e "$SB/shadow.hit")" "rc=$RC hits=$(sort -u "$SB/shadow.hit" 2>/dev/null | tr '\n' ' ') $OUT"
# SSHD_BIN, SSHD_DROPIN_DIR and SSHD_MAIN_CONFIG are read only inside the
# staging-only block (between `if [[ -n "$ROOT" ]]; then` and its `fi`).
BAD="$(awk '/^if \[\[ -n "\$ROOT" \]\]; then$/{inb=1; next} inb && /^fi$/{inb=0; next}
  !/^[[:space:]]*#/ && /SSHD_BIN|SSHD_DROPIN_DIR|SSHD_MAIN_CONFIG/ && !inb {print NR": "$0}' "$SETUP")"
check "the sshd/config overrides are read only in staging mode" "$(ok -z "$BAD" -a -n "$(grep -c 'SSHD_BIN' "$SETUP")")" "$BAD"

echo
echo "$((DONE-FAILS))/$DONE passed"
[ "$FAILS" = "0" ] || exit 1
