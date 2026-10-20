#!/usr/bin/env bash
# ssh-unlock-setup.sh -- key-only, LAN-only sshd for unlocking FileVault after a reboot.
#
#   sudo bash scripts/ssh-unlock-setup.sh --user <name> --lan <cidr> --pubkey <file>
#   bash scripts/ssh-unlock-setup.sh ... --root <dir>     (staging: writes under <dir>, no sudo)
#
# Card 1c58f629, Patrik's decision A (TG 3822): FileVault stays on; after a
# restart the data volume is unlocked over SSH from the LAN ("man fdesetup",
# REMOTE UNLOCKING VIA SSH, macOS 27.0.1). Viktor's review conditions (card
# #4902, S1-S7) shape every line here:
#
#   S1  a drop-in that sorts BEFORE 100-macos.conf (sshd uses the first value it
#       reads): key only, no root, one user from one LAN range, short grace,
#       no forwarding of any kind.
#   S2  authorized keys in a ROOT-owned file, /etc/ssh/authorized_keys/<user>.
#       ~/.ssh is writable by every agent (they all run as this uid), so a
#       prompt-injected agent could plant a key there and get a lasting shell.
#       Only the owner's public key goes in, restricted with from="<lan>".
#
# What this script does NOT do, on purpose:
#   - It does not turn Remote Login on. That is the owner's click in System
#     Settings > General > Sharing, where S5 is set too ("Allow full disk access
#     for remote users" OFF, "Only these users": this one user).
#   - It does not touch the router (S3: no port forwarding, no UPnP).
#   - It cannot configure the PREBOOT unlock prompt: before unlock the OpenSSH
#     configuration on the data volume is not available, and that phase takes
#     the account PASSWORD (man fdesetup; Viktor S4a). S4b/S4c (pinning the
#     preboot host key on the owner's device, a strong password) are steps of
#     the live test, not of this file.
#
# It validates with `sshd -t` before it keeps anything and rolls back on
# failure, then prints the effective settings (`sshd -T`) and the sha256 of
# both files for the review.

set -euo pipefail
# Every command resolves from the system dirs only. Under sudo the caller's PATH
# can survive, and /opt/homebrew/bin, ~/.local/bin and ~/.bun/bin are writable
# by every agent (same uid): a planted ssh-keygen there would run as root
# (Viktor 9534 P1). The same goes for the staging-only overrides further down.
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

USER_NAME=""; LAN=""; PUBKEY=""; ROOT=""
usage() { echo "usage: sudo bash $0 --user <name> --lan <cidr> --pubkey <file.pub> [--root <staging-dir>]" >&2; exit 64; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)   [[ $# -ge 2 ]] || usage; USER_NAME="$2"; shift 2 ;;
    --lan)    [[ $# -ge 2 ]] || usage; LAN="$2"; shift 2 ;;
    --pubkey) [[ $# -ge 2 ]] || usage; PUBKEY="$2"; shift 2 ;;
    --root)   [[ $# -ge 2 ]] || usage; ROOT="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$USER_NAME" && -n "$LAN" && -n "$PUBKEY" ]] || usage

die() { echo "ssh-unlock-setup: $*" >&2; exit 1; }

[[ "$USER_NAME" =~ ^[a-z_][a-z0-9._-]{0,31}$ ]] || die "not a plain user name: $USER_NAME"
[[ "$USER_NAME" != "root" ]] || die "root is never allowed (S1)"
# A private IPv4 range only: this sshd must never be meant for the internet (S3).
[[ "$LAN" =~ ^(10|172|192)\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/(1[6-9]|2[0-9]|3[0-2])$ ]] || die "--lan must be a private IPv4 CIDR like 192.168.0.0/24"
case "$LAN" in
  10.*|192.168.*) ;;
  172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;;
  *) die "--lan is not an RFC 1918 range: $LAN" ;;
esac

[[ -f "$PUBKEY" ]] || die "no public key file: $PUBKEY"
grep -q "PRIVATE KEY" "$PUBKEY" && die "that is a PRIVATE key. The private key never comes to this machine (S2)."
[[ "$(grep -cv '^[[:space:]]*$' "$PUBKEY")" == "1" ]] || die "the key file must hold exactly one key"
key_line="$(grep -v '^[[:space:]]*$' "$PUBKEY")"
[[ "$key_line" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || die "only a plain ssh-ed25519 public key is accepted (no options, S2)"

if [[ -z "$ROOT" ]]; then
  [[ "$(id -u)" == "0" ]] || die "run with sudo (or --root <dir> to stage)"
  id "$USER_NAME" >/dev/null 2>&1 || die "no such user on this machine: $USER_NAME"
fi

# The fixed binaries and the live config. The overrides exist for the test's
# staging run only and are ignored in live mode.
SSHD=/usr/sbin/sshd; DROPIN_SRC=/etc/ssh/sshd_config.d; MAIN_CFG=/etc/ssh/sshd_config
if [[ -n "$ROOT" ]]; then
  SSHD="${SSHD_BIN:-$SSHD}"; DROPIN_SRC="${SSHD_DROPIN_DIR:-$DROPIN_SRC}"; MAIN_CFG="${SSHD_MAIN_CONFIG:-$MAIN_CFG}"
fi

# Backups and scratch live in a fresh 700 dir. Live, that dir is root's under
# /private/var/tmp, not the caller's TMPDIR: a rollback copies the backup back
# into /etc/ssh, so a user-writable backup would be a way in.
if [[ -z "$ROOT" ]]; then WORK="$(mktemp -d /private/var/tmp/ssh-unlock.XXXXXX)"; else WORK="$(mktemp -d "${TMPDIR:-/tmp}/ssh-unlock.XXXXXX")"; fi
trap 'rm -rf "$WORK"' EXIT

# Validate exactly the line that will be written, not the caller's file again.
printf '%s\n' "$key_line" > "$WORK/key.pub"
ssh-keygen -l -f "$WORK/key.pub" >/dev/null 2>&1 || die "ssh-keygen cannot read the key"

ETC="${ROOT}/etc/ssh"
DROPIN="$ETC/sshd_config.d/010-marveen.conf"
KEYDIR="$ETC/authorized_keys"
KEYFILE="$KEYDIR/$USER_NAME"
mkdir -p "$ETC/sshd_config.d"

backup=""
if [[ -f "$DROPIN" ]]; then backup="$WORK/010-marveen.conf.bak"; cp -p "$DROPIN" "$backup"; fi
key_backup=""
if [[ -f "$KEYFILE" ]]; then key_backup="$WORK/authkeys.bak"; cp -p "$KEYFILE" "$key_backup"; fi

cat > "$DROPIN.new" <<EOF
# Managed by marveen scripts/ssh-unlock-setup.sh (card 1c58f629, Viktor S1/S2).
# Sorted before 100-macos.conf: sshd keeps the FIRST value it reads.
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers ${USER_NAME}@${LAN}
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
MaxAuthTries 3
LoginGraceTime 20
AllowAgentForwarding no
AllowTcpForwarding no
AllowStreamLocalForwarding no
X11Forwarding no
PermitTunnel no
PermitUserRC no
EOF

mkdir -p "$KEYDIR"
printf 'from="%s" %s\n' "$LAN" "$key_line" > "$KEYFILE.new"

if [[ -z "$ROOT" ]]; then
  chown root:wheel "$DROPIN.new" "$KEYFILE.new" "$KEYDIR"
fi
chmod 644 "$DROPIN.new" "$KEYFILE.new"; chmod 755 "$KEYDIR"
mv -f "$DROPIN.new" "$DROPIN"; mv -f "$KEYFILE.new" "$KEYFILE"

rollback() {
  if [[ -n "$backup" ]]; then mv -f "$backup" "$DROPIN"; else rm -f "$DROPIN"; fi
  if [[ -n "$key_backup" ]]; then mv -f "$key_backup" "$KEYFILE"; else rm -f "$KEYFILE"; fi
}

# Validation. Live: the real sshd and its real config. Staging: a copy of the
# main config pointed at the staged drop-in dir and a throwaway host key, so the
# check runs without root and measures the same parser.
if [[ -z "$ROOT" ]]; then
  if ! "$SSHD" -t; then rollback; die "sshd -t rejected the config -- rolled back, nothing changed"; fi
  T_ARGS=()
else
  # Mirror the live drop-ins (100-macos.conf brings UsePAM yes) so the staged
  # view is the live one plus ours, not ours alone.
  for f in "$DROPIN_SRC"/*; do
    [[ -f "$f" && "$(basename "$f")" != "010-marveen.conf" ]] && cp "$f" "$ETC/sshd_config.d/"
  done
  main="$ROOT/sshd_config.main"
  sed "s#^Include /etc/ssh/sshd_config.d/\*#Include $ETC/sshd_config.d/*#" "$MAIN_CFG" > "$main"
  [[ -f "$ROOT/hostkey" ]] || ssh-keygen -q -t ed25519 -N '' -f "$ROOT/hostkey" >/dev/null
  T_ARGS=(-f "$main" -h "$ROOT/hostkey")
  if ! "$SSHD" -t "${T_ARGS[@]}"; then rollback; die "sshd -t rejected the staged config -- rolled back"; fi
fi

# A LAN address inside the range, for the effective-config view.
probe_addr="$(echo "$LAN" | cut -d/ -f1 | awk -F. '{print $1"."$2"."$3"."($4+10)}')"
echo "== sshd -T (user=$USER_NAME, addr=$probe_addr)"
"$SSHD" -T "${T_ARGS[@]}" -C "user=$USER_NAME,host=probe,addr=$probe_addr" 2>/dev/null \
  | grep -E '^(passwordauthentication|kbdinteractiveauthentication|authenticationmethods|pubkeyauthentication|permitrootlogin|allowusers|authorizedkeysfile|maxauthtries|logingracetime|allowagentforwarding|allowtcpforwarding|allowstreamlocalforwarding|x11forwarding|permittunnel|permituserrc|usepam) '
echo "== sha256"
shasum -a 256 "$DROPIN" "$KEYFILE"
echo "== key"
ssh-keygen -l -f "$KEYFILE"
echo "OK. Remote Login itself is still OFF until it is switched on in System Settings (S5)."
