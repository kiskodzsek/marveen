#!/usr/bin/env python3
"""PostToolUse hook (telegram reply / edit_message): spend the reply marks the call held.

Why (Klodel 41147, mérve 2026-11-13 18:30-18:33 in the owner's group): patrik-reply-volume-gate.py spent a
KESZ-EREDMENY mark at its own exit 0 while another PreToolUse gate (claim-source-reply-gate.py) blocked the same
reply; the corrected reply then hit the volume gate again ("már válaszoltál"), and a second mark was needed.
Now a gate that passes on a mark only HOLDS it for its tool call (scripts/lib/reply_marks.py, spend_pending with
bind_call), and this hook spends what the call held. PostToolUse runs only when the tool ran, so a reply blocked by
any PreToolUse gate leaves the mark for the corrected reply.
Never blocks: always exit 0 (the message is already out).
Wiring: .claude/settings.json PostToolUse, matcher "mcp__plugin_telegram_telegram__reply|...__edit_message"
(main agent, as the gates that take marks). Tests: scripts/hooks/reply-marks-spend_test.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))


def main():
    try:
        payload = json.load(sys.stdin)
        import reply_marks
        if isinstance(payload, dict):
            reply_marks.spend_held(payload.get('tool_use_id'))
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
