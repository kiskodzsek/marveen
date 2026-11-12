#!/usr/bin/env python3
"""The waiting clock and the free-machine guard (Klodel 35735, Patrik group TG 4453 -> 4454 "ok", 2026-11-10).

Why: on 2026-11-10 Patrik asked for a change of the baby film at 10:13 and got it at 10:35, after "na", "kurvalassu"
and "videok"; between 10:20 and 10:32 the MacBook rendered nothing while he waited ("macbookot használjátok?"). Nobody
was told in time. This runs every 5 minutes (a type='command' scheduled task: no LLM) and tells KLODEL (inter-agent,
never Patrik) when a request has waited too long, and Klodel + Dave when a render machine stands idle while he waits.

1. Waiting clock. A request is an inbound turn of the main agent's owner chats (Patrik / Balázs; conversation_log,
   store/projektek.json elo_uzenet privat + csoport, or MARVEEN_OWNER_CHATS) that is not an acknowledgement ("ok",
   "jó lesz a babás", an emoji) and not a one- or two-word nudge ("na", "videok"). It is open while it has no reply.
   The first reply after it decides: a RESULT (a file attached, a link, or a "Kész / Elkészült / Itt van ..." line)
   closes it; a PROMISE ("amint kész, küldöm", "átadtam Dave-nek", "indul", "Dave most rajzolja") keeps it open as
   promised work; anything else answered it (a question, a remark, a decision). Promised work closes on a later result
   that quotes it or the promise (Telegram reply_to), or names the same product (babás, papás, receptes, ...), or comes
   while it is the only promised work open; or by hand: patrik-varakozas.py close <message_id> [note].
   Measured on 2026-11-10 08:00-10:48 before choosing this: every non-ack message as a request gave 47 open ones (most
   of Patrik's messages are remarks), and Klodel promised in 38 replies, so neither alone tells waiting apart.
   Open for WAIT_S (15 min) -> one alert to Klodel listing every such request, its age and who is working (the tmux
   panes that are busy). At most one such message every WAIT_S; a request is named at most MAX_ALERTS times, and one
   older than MAX_AGE_S is no longer chased.
2. Free-machine guard. While a RENDER work request is open (render_related: the request or the promise names a film,
   video, image, render or one of the films' products; an inventory question, a purchase, a decision or an idea
   request is not), a render machine that has not rendered for IDLE_S (5 min) ->
   one alert to Klodel and Dave ("üres gép: <gép>, sorban: <ami vár>"), again every WAIT_S. The mini renders when a
   render.mjs export/frames, Blender or ffmpeg runs here; the MacBook when our ssh to its render gate (render-mac
   render|export) runs here (measured on this side: the gate itself has no status in the installed version).

State: store/patrik-varakozas.json (closed requests, alert times, the machines' last busy time). Reads the ledger DB
read-only. Messages go through scripts/agent-msg.sh on stdin (never through a shell string).
Usage: patrik-varakozas.py check [--dry] [--now TS] | list | close <message_id> [note]
Tests: scripts/__tests__/patrik-varakozas.test.py
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'hooks'))
from render_claim_lib import processes  # noqa: E402

ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or os.path.dirname(HERE)
STORE = os.path.join(ROOT, 'store')
STATE = os.path.join(STORE, 'patrik-varakozas.json')
DB = os.path.join(STORE, 'claudeclaw.db')
MAIN_AGENT = os.environ.get('MARVEEN_MAIN_AGENT', 'klodel')
SENDER = 'kernel'  # the tool's owner; the text says it is the waiting clock

WAIT_S = 15 * 60
IDLE_S = 5 * 60
MAX_ALERTS = 4
MAX_AGE_S = 4 * 3600

ACK_WORDS = {'ok', 'oke', 'okes', 'okse', 'jo', 'rendben', 'szuper', 'kiraly', 'top', 'koszi', 'koszonom', 'kosz',
             'mehet', 'igen', 'nem', 'ertem', 'persze', 'tok', 'tokeletes', 'hello', 'szia', 'helo'}
RESULT_START = ('kesz', 'elkeszult', 'itt van', 'itt a ', 'itt az ', 'kint van', 'feltoltve', 'elkuldve', 'megvan')
URL = re.compile(r'https?://\S+')
MACBOOK_SSH = re.compile(r'\bssh\b.*\brender-mac (?:render|export) [0-9a-f-]{8,36}')


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in text if not unicodedata.combining(c)).casefold()


def words(text):
    return re.findall(r'[a-z0-9]+', fold(text))


def is_ack(text):
    w = words(text)
    if not w:
        return True  # an emoji or a sticker
    if re.fullmatch(r'ne+m|i+gen|o+k+', w[0]) and len(w) <= 4:
        return True
    return len(w) <= 4 and w[0] in ACK_WORDS


def is_nudge(text):
    return '?' not in str(text) and len(words(text)) <= 2


def is_result(row):
    if row.get('attachment_kind') == 'file' or URL.search(str(row.get('text') or '')):
        return True
    plain = ' '.join(fold(row.get('text')).split()).lstrip('*_ ')
    return plain.startswith(RESULT_START)


# Klodel's reply promises work ("amint kész, küldöm", "átadtam Dave-nek", "indul", "Dave most rajzolja"): then the
# request stays open until a result. A reply without a promise answered it (a question, a remark, a decision).
PROMISE = re.compile(
    r'(kuldom|kuldjuk|amint (kesz|elkeszul|megvan)|atadtam|atadva|kiadtam|\bindul\b|^megy\b|^jon\b|utana jon'
    r'|\b(elsokent|eloszor|most) jon\b|most (irja|rajzolja|vagja|teszi|kiteszi|nezi|megkeresi|keszul|keszuln?ek'
    r'|rendereli|javitja|csinalja|kitalalja|osszerakja)|ma keszul|egybol osszerakja|szolok, amint)')
# A result belongs to the promise it names: the products and deliverables we talk about.
TOPICS = ('babas', 'papas', 'recept', 'aranyev', 'meseld', 'elso eved', 'marabello', 'koszonjuk', 'tiktok', 'chat',
          'messenger', 'whatsapp', 'aszf', 'terms', 'privacy', 'dns', 'logo', 'poszt', 'reel', 'landing', 'szamla',
          'billingo', 'konyvbemutato', 'hirdetes', 'banner', 'video', 'film')


# Free-machine guard (Klodel 35727 follow-up): a machine is "free while Patrik waits" only when what he waits for is
# render work. Measured 2026-11-10 11:00, the first live run: the three open requests (brand launch, market research,
# a team rule) and Klodel's promises named no film, image or render, yet four [SZABAD GÉP] messages went to Klodel and
# Dave. Folded text (no accents); a request counts when the request OR the promising reply names one of these.
RENDER_WORK = re.compile(
    r'\b(babas|papas|recept|aranyev|meseld|elso eved|koszonjuk|tiktok|reels?|shorts?|render|blender|3d|export'
    r'|kep|kepe[kt]?|kepeket|kepsor|illusztrac|animac|mintakep|boritokep)\b|film|video|felirat')


# A purchase, a payment or a decision is not render work, even when the promising reply talks about the images or the
# film it will lead to (Dave 38764, 2026-11-11: «ultrat be kell szerezni holnap» was answered with "indul az első
# AI-influenszer ... a képeket ...", and the free-machine alert went out twice). Then only the request's own words count.
# An idea, product or research request is not render work either (Klodel 39419, Patrik TG 18037, 2026-11-12: «akkor adj
# jobb ötleteket vagy termékeket ...» was research for Radar, yet [SZABAD GÉP] went out, 39417). "termek" is a whole word,
# so a product-image request ("termékképeket") is not caught here.
NON_RENDER = re.compile(
    r'(szerez|megve(sz|tt|nn)|\bvesz(ek|ed|unk|ik|em)?\b|\bveg(yem|yuk|yel|yek|ye|yetek)\b|vasarl|\bfizet|elofizet'
    r'|szamla|csomag|\bdont(es|s|sd|sek|sunk|ottam)?\b|valassz|valasszak|melyiket'
    r'|otlet|\btermek(ek|et|eket|eink|unk|ot)?\b|kutat|\bmi(nk|nek)? van meg\b)')
# An inventory question ("what do we have?") is not render work, whatever it names: it needs a list and an answer, no
# machine time (Klodel 39657, Dave 39655, Patrik TG 5603, 2026-11-12: «milyen hirdetéshez való anyagaink állnak
# rendelkezésre?» was answered "... képek, videók ... amint kész", and [SZABAD GÉP] went out, 39653/39654). Checked
# before the render words, so «milyen képeink állnak rendelkezésre?» is an inventory question too. Kept narrow: a status
# question ("hol tart a babás?") is not caught here, the render word still decides it. Only a short request: measured on
# the 14 days of the ledger before 2026-11-12, eight long render briefs (a campaign video, the character engine) carry
# "rendelkezésre" or "mi ... anyag" somewhere inside and would have been dropped.
INVENTORY = re.compile(r'rendelkezesre|leltar|\b(milyen|melyik|mely|hany|mi)\b.{0,80}\banyag')
INVENTORY_MAX = 200  # characters, folded


def render_related(q):
    text = ' '.join(fold(q.get('text') or '').split())
    if len(text) <= INVENTORY_MAX and INVENTORY.search(text):
        return False
    if RENDER_WORK.search(text):
        return True
    if NON_RENDER.search(text):
        return False
    return bool(RENDER_WORK.search(' '.join(fold(q.get('promise') or '').split())))


def is_promise(text):
    return bool(PROMISE.search(' '.join(fold(text).split())))


def topics(text):
    plain = ' '.join(fold(text).split())
    return {t for t in TOPICS if re.search(r'\b' + re.escape(t), plain)}


def open_requests(rows, closed, now):
    """rows: the turns of the owner chats, ascending: dicts chat, dir, mid, at, text, reply_to, attachment_kind.
    A request is open while it has no reply at all, and after a PROMISING reply until a result for it. -> the open
    requests [{chat, mid, at, text, promise}], oldest first ('promise' is the promising reply's text, or None)."""
    reqs = []
    for r in rows:
        if r['dir'] == 'in':
            text = r.get('text') or ''
            if now - r['at'] > MAX_AGE_S or is_ack(text) or is_nudge(text):
                continue
            # A request closed by hand was open until then: it still counts when a reply came before that.
            c = closed.get(str(r['mid']))
            closed_at = (c.get('at', 0) if isinstance(c, dict) else 0) if c is not None else None
            reqs.append({'chat': r['chat'], 'mid': str(r['mid']), 'at': r['at'], 'text': text, 'open': True,
                         'answered': False, 'promise': None, 'promise_mid': None, 'closed_at': closed_at})
            continue
        live = [q for q in reqs if q['open'] and q['chat'] == r['chat'] and q['at'] <= r['at']
                and (q['closed_at'] is None or r['at'] < q['closed_at'])]
        result = is_result(r)
        reply_to = str(r['reply_to']) if r.get('reply_to') else None
        # 1. The first reply after unanswered requests answers them (a quote names the one it answers).
        fresh = [q for q in live if not q['answered']]
        if reply_to and any(q['mid'] == reply_to for q in fresh):
            fresh = [q for q in fresh if q['mid'] == reply_to]
        for q in fresh:
            q['answered'] = True
            if result:
                q['open'] = False
            elif is_promise(r.get('text')):
                q['promise'], q['promise_mid'] = r.get('text') or '', str(r['mid'])
            else:
                q['open'] = False  # answered: a question, a remark, a decision
        if not result:
            continue
        # 2. A result closes the promised request it quotes, or names (a shared topic), or the only one open.
        promised = [q for q in live if q['answered'] and q['open'] and q['promise'] is not None]
        target = [q for q in promised if reply_to in (q['mid'], q['promise_mid'])]
        if not target:
            names = topics(r.get('text'))
            target = [q for q in promised if names & (topics(q['promise']) | topics(q['text']))]
        if not target and len(promised) == 1:
            target = promised
        for q in target:
            q['open'] = False
    return [q for q in reqs if q['open'] and q['closed_at'] is None]


def due_alerts(reqs, state, now):
    """The open requests to alert about now, in ONE message at most every WAIT_S: every request open for WAIT_S that
    has had fewer than MAX_ALERTS alerts. Updates state['alerted'] {mid: [last_ts, count]} and state['last_alert']."""
    if now - state.get('last_alert', 0) < WAIT_S:
        return []
    alerted = state.setdefault('alerted', {})
    due = [q for q in reqs if now - q['at'] >= WAIT_S and alerted.get(q['mid'], [0, 0])[1] < MAX_ALERTS]
    for q in due:
        alerted[q['mid']] = [now, alerted.get(q['mid'], [0, 0])[1] + 1]
    if due:
        state['last_alert'] = now
    return due


def machine_alerts(state, busy, waiting, now):
    """busy: {machine: bool}; waiting: any open work request. -> [(machine, idle_seconds)] to alert about now."""
    machines = state.setdefault('machines', {})
    out = []
    for m, is_busy in busy.items():
        rec = machines.setdefault(m, {'last_busy': now})
        if is_busy:
            rec['last_busy'] = now
            continue
        idle = now - rec.get('last_busy', now)
        if waiting and idle >= IDLE_S and now - rec.get('alerted', 0) >= WAIT_S:
            rec['alerted'] = now
            out.append((m, idle))
    return out


def machines_busy(procs):
    mini = mac = False
    for _pid, cmd in procs:
        args = cmd.split()
        if not args:
            continue
        if MACBOOK_SSH.search(cmd):
            mac = True
        elif 'render.mjs' in cmd and ('export' in args or 'frames' in args):
            mini = True
        elif args[0].endswith('/Blender') or (args[0].endswith('ffmpeg') and ' -i ' in cmd):
            mini = True
    return {'Mac mini': mini, 'MacBook': mac}


# --- I/O ----------------------------------------------------------------------------------------------------------

def owner_chats():
    env = os.environ.get('MARVEEN_OWNER_CHATS')
    if env:
        return {c.strip() for c in env.split(',') if c.strip()}
    try:
        with open(os.path.join(STORE, 'projektek.json'), encoding='utf-8') as f:
            elo = json.load(f).get('elo_uzenet')
    except Exception:
        return set()
    out = set()
    for key in ('privat', 'csoport'):
        v = elo.get(key) if isinstance(elo, dict) else None
        if isinstance(v, dict):
            v = v.get('chat_id')
        if v is not None and str(v).strip():
            out.add(str(v).strip())
    return out


def chat_label(chat):
    return 'csoport' if str(chat).startswith('-') else 'privát'


def read_rows(chats, now):
    if not chats:
        return []
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=5)
    try:
        q = ('SELECT chat_id, direction, message_id, created_at, text, reply_to_message_id, attachment_kind'
             ' FROM conversation_log WHERE agent_id=? AND created_at>=? AND chat_id IN (%s)'
             ' ORDER BY created_at, id' % ','.join('?' * len(chats)))
        rows = con.execute(q, (MAIN_AGENT, int(now - MAX_AGE_S - 3600), *sorted(chats))).fetchall()
    finally:
        con.close()
    return [{'chat': r[0], 'dir': r[1], 'mid': r[2], 'at': r[3], 'text': r[4], 'reply_to': r[5],
             'attachment_kind': r[6]} for r in rows]


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_state(s, now):
    # Keep it small: alerts and closes older than a day go.
    for key in ('alerted', 'closed'):
        d = s.get(key) or {}
        s[key] = {k: v for k, v in d.items() if now - (v[0] if isinstance(v, list) else v.get('at', 0)) < 86400}
    os.makedirs(STORE, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STORE, prefix='.varakozas-')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def panes():
    """'dolgozik: a, b; áll: c' from the tmux panes (idle-check.py's reading), or '' when tmux cannot be read."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('idle_check', os.path.join(HERE, 'idle-check.py'))
        ic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ic)
        names = subprocess.run(['tmux', 'ls', '-F', '#{session_name}'], capture_output=True, text=True,
                               timeout=5).stdout.split()
    except Exception:
        return ''
    busy, idle = [], []
    for n in sorted(names):
        if not n.startswith('agent-') or n == f'agent-{MAIN_AGENT}':
            continue
        a = n[len('agent-'):]
        (idle if ic.pane_idle(a) else busy).append(a)
    return f"dolgozik: {', '.join(busy) or '-'}; áll: {', '.join(idle) or '-'}"


def short(text, n=90):
    t = ' '.join(str(text or '').split())
    return t if len(t) <= n else t[:n - 1] + '…'


def send(to, text, dry):
    if dry:
        print(f'[{to}] {text}')
        return
    r = subprocess.run(['bash', os.path.join(HERE, 'agent-msg.sh'), SENDER, to, '-'], input=text, text=True,
                       capture_output=True, timeout=60)
    if r.returncode != 0 or 'OK id=' not in r.stdout:
        print(f'send to {to} failed: {r.stdout.strip()} {r.stderr.strip()}', file=sys.stderr)


def free_machine_text(free, waiting, now):
    """One message for one event (Klodel 35768): every idle machine in one line, or None when none is idle.
    11:00 on 2026-11-10 the mini and the MacBook went out as two messages to each recipient."""
    if not free:
        return None
    machines = ', '.join(f"{m} ({int(idle // 60)} perce nem renderel)" for m, idle in free)
    queue = '; '.join(f"«{short(q['text'], 60)}» ({int((now - q['at']) // 60)} p)" for q in waiting[:3])
    return (f"[SZABAD GÉP] üres gép: {machines}, miközben Patrik vár. "
            f"Sorban: {queue}. Blender-render a MacBookra mehet (render-gate).")


def check(dry, now):
    state = load_state()
    closed = state.get('closed') or {}
    reqs = open_requests(read_rows(owner_chats(), now), closed, now)
    due = due_alerts(reqs, state, now)
    if due:
        lines = [f"[VÁRAKOZÁS-ÓRA] {len(due)} kérés {WAIT_S // 60} perce vagy régebben áll eredmény nélkül:"]
        for q in due:
            lines.append(f"- {int((now - q['at']) // 60)} perce, {chat_label(q['chat'])}, msg {q['mid']}: «{short(q['text'])}»")
        p = panes()
        if p:
            lines.append(f'Panelek: {p}.')
        lines.append('Lezárás: eredmény reply_to-val a kérésre, vagy python3 -I scripts/patrik-varakozas.py close <msg> "<mi lett>".')
        send(MAIN_AGENT, '\n'.join(lines), dry)
    waiting = [q for q in reqs if q['promise'] is not None and render_related(q)]
    free = machine_alerts(state, machines_busy(processes()), bool(waiting), now)
    text = free_machine_text(free, waiting, now)
    if text:
        for to in (MAIN_AGENT, 'dave'):
            send(to, text, dry)
    if not dry:
        save_state(state, now)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'check'
    now = time.time()
    if '--now' in argv:
        now = float(argv[argv.index('--now') + 1])
    if cmd == 'check':
        return check('--dry' in argv, now)
    if cmd == 'list':
        state = load_state()
        for q in open_requests(read_rows(owner_chats(), now), state.get('closed') or {}, now):
            kind = 'vállalt' if q['promise'] is not None else 'válasz nélkül'
            print(f"{int((now - q['at']) // 60):4d} p  {chat_label(q['chat'])}  msg {q['mid']}  {kind}  «{short(q['text'])}»")
        return 0
    if cmd == 'close' and len(argv) > 2 and re.fullmatch(r'\d{1,12}', argv[2]):
        state = load_state()
        state.setdefault('closed', {})[argv[2]] = {'at': now, 'note': short(' '.join(argv[3:]), 200)}
        save_state(state, now)
        print(f'closed {argv[2]}')
        return 0
    print(__doc__.split('Usage: ')[1].split('\n')[0], file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
