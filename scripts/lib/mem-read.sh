# mem-read.sh -- source me. One memory reader for the gate and the heavy-job lock.
#
#   mem_read   -> 0 and sets MEM_TOTAL_KB, MEM_AVAIL_KB, MEM_FREE_PCT, MEM_SOURCE
#              -> 1 when nothing could be read (callers decide fail-open/closed)
#
# Linux: /proc/meminfo MemTotal + MemAvailable (unchanged from the gate's v1).
# macOS: there is no /proc. Before this file the gate logged "cannot read
# /proc/meminfo -- fail-open (allow)" on every call (measured 2026-10-20 08:01),
# so on the Mac mini it limited nothing, and at the 07:02 panic it let 14
# agents run next to a 9.7 GB mflux job and a 6 GB VM. The Mac source is
# `sysctl kern.memorystatus_level`: the kernel's "free percentage", the same
# number `memory_pressure` prints as "System-wide memory free percentage"
# (both read 39 at 08:24 the same day). sysctl is used instead of
# memory_pressure on purpose: memory_pressure with a stray argument ALLOCATES
# memory until a target is hit, which is the last thing a memory gate should do.
#
# Test hooks: MEMGATE_PROC_MEMINFO (a meminfo file; when it is set, only that
# file is read, so a Linux-shaped test behaves the same on a Mac) and
# MEMGATE_SYSCTL (a sysctl stand-in, default /usr/sbin/sysctl).

mem_read() {
  MEM_TOTAL_KB=""; MEM_AVAIL_KB=""; MEM_FREE_PCT=""; MEM_SOURCE=""
  local meminfo="${MEMGATE_PROC_MEMINFO:-/proc/meminfo}" t a
  if [[ -r "$meminfo" ]]; then
    t="$(awk '/^MemTotal:/{print $2}' "$meminfo" 2>/dev/null)"
    a="$(awk '/^MemAvailable:/{print $2}' "$meminfo" 2>/dev/null)"
    if [[ "$t" =~ ^[0-9]+$ && "$a" =~ ^[0-9]+$ ]] && (( t > 0 )); then
      MEM_TOTAL_KB="$t"; MEM_AVAIL_KB="$a"
      MEM_FREE_PCT=$(( a * 100 / t )); MEM_SOURCE="meminfo"
      return 0
    fi
    return 1
  fi
  # An explicit meminfo that is missing is a test asking for "unreadable":
  # do not fall through to the real host.
  [[ -n "${MEMGATE_PROC_MEMINFO:-}" && -z "${MEMGATE_SYSCTL:-}" ]] && return 1
  local sysctl="${MEMGATE_SYSCTL:-/usr/sbin/sysctl}" bytes lvl
  [[ -x "$sysctl" ]] || return 1
  bytes="$("$sysctl" -n hw.memsize 2>/dev/null | tr -d ' \r\n')"
  lvl="$("$sysctl" -n kern.memorystatus_level 2>/dev/null | tr -d ' \r\n')"
  if [[ "$bytes" =~ ^[0-9]+$ && "$lvl" =~ ^[0-9]+$ ]] && (( bytes > 0 && lvl <= 100 )); then
    MEM_TOTAL_KB=$(( bytes / 1024 ))
    MEM_FREE_PCT="$lvl"
    MEM_AVAIL_KB=$(( MEM_TOTAL_KB * lvl / 100 ))
    MEM_SOURCE="memorystatus"
    return 0
  fi
  return 1
}
