#!/usr/bin/env python3
"""Close one inbound channel message as "not for me", silently, without a reply or a reaction.

Klodel 37860 (Balázs csoport TG 5277: "nem téged kérdeztelek vagy úgy érzed?"): when Patrik and Balázs write to
each other in the group, the agent does not answer (memory patrik-to-balazs-not-me, TG 3366), but the Stop-hook
reply guard, the live drain and the progress Stop hook kept demanding a reply. This command records the decision:

    python3 scripts/hooks/ledger-close.py <chat_id> <message_id> "nem nekem: <kinek szólt>"

The note must start with "nem nekem:" and name the addressee. Only an inbound that is in this agent's ledger can be
closed (agent id from the cwd, like the hooks). Written: store/.tg-closed-<agent>.json (read by the hooks) and one
line in store/.tg-closed-<agent>.log (append-only audit). Exit 0 = closed, 2 = refused (nothing written).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_lib  # noqa: E402


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[0] + '\nusage: ledger-close.py <chat_id> <message_id> "nem nekem: <kinek>"',
              file=sys.stderr)
        return 2
    chat_id, message_id, note = argv
    agent_id = ledger_lib.agent_id_from_cwd(os.getcwd())
    try:
        ledger_lib.close_inbound(agent_id, chat_id, message_id, note)
    except ValueError as e:
        print(f"ledger-close: refused: {e}", file=sys.stderr)
        return 2
    print(f"CLOSED agent={agent_id} chat_id={chat_id} message_id={message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
