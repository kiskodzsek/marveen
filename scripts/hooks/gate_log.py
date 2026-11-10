"""One line per block, for every reply / send gate: which gate stopped what, and how often (Klodel 35878).

Why: Patrik group TG 4521 (audit item 6, gate cleanup): a gate that caught nothing in two weeks is a candidate for
removal, but only half of the gates logged their blocks at all, each in its own format, so "caught nothing" could be
said of none of them (agents/kernel/reports/kapu-takaritas-1110.md). This module gives them one log.

Use, around the gate's entry point (one edit per gate, the gate's own logic is untouched):

    with gate_log.watch('claim-source'):
        sys.exit(main())

A SystemExit(2) leaving the block (exit 2 = PreToolUse block) is logged; everything else is not. The exception is
always re-raised: the gate's exit code and its stderr reach Claude Code as before. A gate may name the reason of the
block it is about to make with gate_log.reason('<short code>'): a fixed label from the gate's own vocabulary, never
text from the message.

The line (store/gate-blocks.jsonl, next to this file's scripts/ dir; GATE_LOG_PATH overrides it for tests):
    {"at": <unix>, "gate": "<name>", "agent": "<agent id or ?>", "code": "<reason or ''>"}
Never the message text, the chat id or a file name: they may hold personal data. The agent comes from the hook
payload's transcript_path (ledger_lib.agent_id_from_payload, session-stable); to read it the payload is taken off
stdin here and given back to the gate as an in-memory stdin.

Fail-open by design: no error in this module may change the gate's verdict. A broken import in a gate falls back to a
no-op (contextlib.nullcontext), a write error is swallowed.
"""
import contextlib
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'store', 'gate-blocks.jsonl')
_CODE = ''
_CODE_RE = None


def log_path():
    return os.environ.get('GATE_LOG_PATH') or DEFAULT_LOG


def reason(code):
    """Name the reason of the coming block: a short, fixed label ([a-z0-9-], at most 40 chars)."""
    global _CODE, _CODE_RE
    try:
        if _CODE_RE is None:
            import re
            _CODE_RE = re.compile(r'[^a-z0-9,\-]+')
        import unicodedata
        folded = ''.join(c for c in unicodedata.normalize('NFKD', str(code)) if not unicodedata.combining(c))
        _CODE = _CODE_RE.sub('-', folded.casefold())[:40].strip('-')
    except Exception:
        _CODE = ''


def _agent(raw):
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from ledger_lib import agent_id_from_payload
        return str(agent_id_from_payload(payload) or '?')[:40]
    except Exception:
        return os.environ.get('MARVEEN_AGENT_ID', '').strip()[:40] or '?'


def write(gate, agent, code, now=None):
    line = {'at': int(time.time() if now is None else now), 'gate': gate, 'agent': agent, 'code': code}
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
    except Exception:
        pass


@contextlib.contextmanager
def watch(gate):
    raw = ''
    try:
        raw = sys.stdin.read() if sys.stdin is not None else ''
    except Exception:
        raw = ''
    try:
        sys.stdin = io.StringIO(raw)
    except Exception:
        pass
    try:
        yield
    except SystemExit as e:
        if e.code == 2:
            write(gate, _agent(raw), _CODE)
        raise
