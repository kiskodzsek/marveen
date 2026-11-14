#!/usr/bin/env python3
"""Add one item to Patrik's evening block from a script (card 7702bb13).

A script that revokes something Patrik may have given (a logout, a removed key or login) calls this right after
the revocation, so the 18:05 evening message tells him (retro 2026-11-13, Kernel c):

  python3 -I scripts/este-blokk-add.py --tipus visszavonas --agens kernel --forras higgsfield-gate \\
      --mi "Higgsfield MCP kijelentkeztetve (Dave configja)" --javaslat "újra-belépés a mini böngészőjében"

Ad-hoc commands typed in an agent's Bash (claude mcp logout, gh auth logout, ...) are noted by the PostToolUse hook
scripts/hooks/revocation-evening-note.py without this call. Prints added / duplicate / parked; exit 0, 2 on bad use.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
import este_blokk  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--tipus', default='visszavonas')
    ap.add_argument('--mi', required=True, help='what happened, one line, no secret')
    ap.add_argument('--forras', required=True, help='the script or card that did it')
    ap.add_argument('--agens', default=None)
    ap.add_argument('--javaslat', default=None)
    a = ap.parse_args(argv)
    if not a.mi.strip() or not a.forras.strip():
        print('este-blokk-add: --mi and --forras must not be empty', file=sys.stderr)
        return 2
    print(este_blokk.add_item(a.tipus, a.mi, a.forras, agens=a.agens, javaslat=a.javaslat))
    return 0


if __name__ == '__main__':
    sys.exit(main())
