#!/usr/bin/env python3
"""Take every item out of Patrik's evening block and print them as JSON (card 7702bb13, Viktor 41840 LOW 2-3).

The 18:05 evening message (napi-eredmeny-este skill) calls this instead of reading the file and writing [] later:
the items are taken and the file emptied under the writers' lock, so nothing written meanwhile is lost and nothing
sent comes back. Parked items (<file>.hiba.jsonl, written when the block was not a JSON list) come back under
"parkolt"; "hibas_fajl": true means the block itself is broken and was left for a person to fix.

  python3 -I scripts/este-blokk-drain.py
  -> {"tetelek": [...], "parkolt": [...], "hibas_fajl": false, "olvashatatlan_sor": 0}

A copy of the last drain stays in <file>.utolso-drain.json. Exit 0; 1 on an error (the block is then unchanged).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
import este_blokk  # noqa: E402


def main():
    try:
        out = este_blokk.drain()
    except Exception as e:
        print(f'este-blokk-drain: {e.__class__.__name__}: {e}', file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
