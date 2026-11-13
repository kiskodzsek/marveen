#!/usr/bin/env python3
"""reply-mark.py -- write a gate mark right before a Telegram reply, instead of a marker line in the text.

  python3 -I scripts/reply-mark.py <KIND> --chat <chat_id | privat | csoport> "<value>"

KIND: PRIVAT-OK (why private) | KESZ-EREDMENY (what finished result) | BALAZS-KERES (TG <message id>) |
BELSO-UT-MERVE (msg_id of the internal route measured). One mark = one message, 3 minutes, this agent and chat only
(scripts/lib/reply_marks.py). Klodel 40845: the owner never sees these markers; Viktor 40894.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))
sys.path.insert(0, os.path.join(HERE, 'hooks'))
import reply_marks  # noqa: E402
import owner_chat  # noqa: E402

ALIASES = {'PRIVÁT-OK': 'PRIVAT-OK', 'KÉSZ-EREDMÉNY': 'KESZ-EREDMENY', 'BALÁZS-KÉRÉS': 'BALAZS-KERES',
           'BELSŐ-ÚT-MÉRVE': 'BELSO-UT-MERVE'}


def agent_id():
    import ledger_lib
    return (ledger_lib._agent_id_from_config_path(os.environ.get('CLAUDE_CONFIG_DIR'))
            or os.environ.get('MARVEEN_AGENT_ID', '').strip() or ledger_lib.main_agent_id())


def resolve_chat(v):
    install = os.path.dirname(HERE)
    if v == 'privat':
        c = (os.environ.get('MARVEEN_OWNER_PRIVATE_CHAT') or '').strip() or str(
            owner_chat.resolve_owner_chat_id(os.path.join(install, '.env')) or '')
    elif v == 'csoport':
        c = (os.environ.get('MARVEEN_OWNER_GROUP_CHAT') or '').strip()
        if not c:
            import importlib.util
            spec = importlib.util.spec_from_file_location('pig', os.path.join(HERE, 'hooks', 'product-image-gate.py'))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            c = m.owner_group_chat()
    else:
        c = v
    # Viktor 40894 (5): an unknown owner chat is refused, never "" == "".
    if not reply_marks.norm_chat(c):
        raise ValueError(f'the {v} chat id is unknown')
    return c


def main(argv):
    if len(argv) != 4 or argv[1] != '--chat':
        sys.stderr.write(__doc__)
        return 2
    kind = ALIASES.get(argv[0], argv[0])
    try:
        chat = resolve_chat(argv[2])
        reply_marks.add(kind, chat, agent_id(), argv[3])
    except (ValueError, OSError) as e:
        sys.stderr.write(f'reply-mark: {e}\n')
        return 2
    print(f'OK {kind} -> {argv[2]}, one message, {reply_marks.TTL_S // 60} minutes')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
