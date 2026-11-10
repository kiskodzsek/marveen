// Office view ("Iroda"): the team as an org tree of desks, fed live from /api/iroda/snapshot.
//
// Data: GET /api/iroda/snapshot every POLL_MS (Bearer, same token as the main dashboard),
// monitor thumbnails from GET /api/iroda/thumb/<agent> (Bearer, fetched into blob URLs).
// The server already reduces everything (subjects only, scrubbed text, allowlisted media);
// this file only lays it out. Query flags: ?replay=1 replays the last 30 minutes in 30 s,
// ?t=<sec> freezes the replay at that second, ?open=<agent> opens that desk's drawer.
(() => {
  'use strict'
  const TOKEN_KEY = 'marveen-dashboard-token'
  const POLL_MS = 5000
  const FRESH_SEC = 30 * 60
  const LOOP = 30
  const SPEED = 520
  const qs = new URLSearchParams(location.search)

  // ---- token: same storage and ?token= handling as app.js ----
  let token = qs.get('token') || ''
  if (token) {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { /* storage blocked */ }
    qs.delete('token')
    history.replaceState({}, '', location.pathname + (qs.toString() ? '?' + qs : '') + location.hash)
  } else {
    try { token = localStorage.getItem(TOKEN_KEY) || '' } catch { token = '' }
  }
  const api = (path) => fetch(path, { headers: token ? { Authorization: 'Bearer ' + token } : {}, cache: 'no-store' })

  // ---- people: illustration colours only; names and roles come from the org ----
  const LOOK = {
    klodel: ['#3B2F2A', '#2F6F6A'], dave: ['#2A221E', '#4A6FA5'], pixel: ['#6B4B32', '#8C8F94'],
    pulzus: ['#1F1F1F', '#B5503C'], mira: ['#8A4B2E', '#C9853A'], viktor: ['#2C2C2C', '#3D4A5C'],
    lex: ['#5A3B2A', '#6E5A8A'], juro: ['#3A2D25', '#5E7D5A'], szigma: ['#262626', '#4F8A9A'],
    kernel: ['#33302D', '#55606B'],
  }
  const look = (id) => LOOK[id] || ['#3A3530', '#7A8590']

  const $ = (s) => document.querySelector(s)
  const $$ = (s) => [...document.querySelectorAll(s)]
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
  const ago = (sec) => sec < 60 ? 'most' : sec < 3600 ? Math.round(sec / 60) + ' p' : sec < 86400 ? Math.round(sec / 3600) + ' ó' : Math.round(sec / 86400) + ' n'
  const clock = (at) => new Date(at * 1000).toLocaleTimeString('hu-HU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Budapest' })

  // state -> pill class + label
  const ST = {
    working: ['work', 'dolgozik'], stalled: ['stall', 'elakadt?'], idle: ['idle', 'szabad'],
    stopped: ['off', 'alszik'], unreachable: ['off', 'nem elérhető'], unknown: ['idle', 'ismeretlen'],
  }
  const stOf = (a) => a ? (!a.running ? ST.stopped : ST[a.state] || ST.unknown) : ST.stopped
  const PRIO = { urgent: 'sürgős', high: 'magas', normal: 'normál', low: 'alacsony' }
  const STN = { in_progress: 'folyamatban', waiting: 'vár', planned: 'tervezett', testing: 'teszt' }

  let S = null // last snapshot
  let A = {} // agent id -> agent row
  let seats = {} // seat id -> seat (incl. lead)
  let orgKey = ''
  let openId = qs.get('open') || ''
  const deskCache = {} // id -> last rendered html
  const thumbs = {} // id -> { v, url, pending }

  // ---- projects + waiting ----
  // The top of the page stays short (Patrik csoport TG 4538: "sok a 100as kártya ott fent"): a project at 100%
  // leaves the grid for a folded "Kész (N)" row, and the grid shows the first PROJ_LIMIT open projects with a
  // "Mind a N" button. Both choices are the viewer's own and survive the 5 s re-render (localStorage).
  const PROJ_LIMIT = { wide: 8, narrow: 4 }
  const narrow = matchMedia('(max-width:760px)')
  const pref = (k, d) => { try { return localStorage.getItem(k) === null ? d : localStorage.getItem(k) === '1' } catch { return d } }
  const setPref = (k, v) => { try { localStorage.setItem(k, v ? '1' : '0') } catch { /* storage blocked */ } }
  let projAll = pref('iroda-proj-all', false)
  let projDone = pref('iroda-proj-done', false)
  let projList = []
  const progressOf = (p) => {
    const n = p.lepesek.length || 1, k = p.lepesek.filter((s) => s.kesz).length
    return { k, pct: Math.round(k / n * 100) }
  }
  function projCard(p) {
    const { k, pct } = progressOf(p)
    const next = (p.lepesek.find((s) => !s.kesz) || { nev: 'kész' }).nev, C = 2 * Math.PI * 26
    const due = p.hatarido ? p.hatarido.replace(/^\d{4}-/, '').replace('-', '.') + '.' : 'nincs határidő'
    return `<div class="proj"><div class="ring"><svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="26" fill="none" stroke="#ECE6DC" stroke-width="7"/><circle cx="32" cy="32" r="26" fill="none" stroke="${pct === 100 ? '#3E8E66' : '#2F6F6A'}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${C * pct / 100} ${C}"/></svg><div class="pct">${pct}%</div></div>
        <div style="min-width:0"><h3>${esc(p.cim)}</h3><div class="row"><span class="steps">${k}/${p.lepesek.length} lépés</span><span class="due ${p.hatarido ? '' : 'none'}">${esc(due)}</span></div>
        <div class="bars">${p.lepesek.map((s) => `<i class="${s.kesz ? 'on' : ''}"></i>`).join('')}</div>
        <div class="next"><b>Következő:</b> ${esc(next)}</div></div></div>`
  }
  function renderProjects(list) {
    projList = list
    const open = list.filter((p) => progressOf(p).pct < 100)
    const done = list.filter((p) => progressOf(p).pct === 100)
    const limit = narrow.matches ? PROJ_LIMIT.narrow : PROJ_LIMIT.wide
    const shown = projAll ? open : open.slice(0, limit)
    $('#projects').innerHTML = shown.length ? shown.map(projCard).join('')
      : `<div class="empty-note">${list.length ? 'Minden nagy feladat kész.' : 'Nincs nagy feladat a store/projektek.json-ban.'}</div>`
    const more = open.length > limit
      ? `<button type="button" class="proj-btn" data-act="all" aria-expanded="${projAll}">${projAll ? 'Kevesebb' : `Mind a ${open.length} mutatása`}</button>` : ''
    const doneRow = done.length
      ? `<button type="button" class="proj-btn done" data-act="done" aria-expanded="${projDone}"><span class="tick">✓</span> Kész (${done.length}) <span class="chev">${projDone ? '▴' : '▾'}</span></button>`
        + (projDone ? `<ul class="done-list">${done.map((p) => `<li><span class="tick">✓</span>${esc(p.cim)}</li>`).join('')}</ul>` : '')
      : ''
    $('#projFoot').innerHTML = more + doneRow
    $('#projFoot').hidden = !more && !doneRow
  }
  $('#projFoot').addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]')
    if (!b) return
    if (b.dataset.act === 'all') { projAll = !projAll; setPref('iroda-proj-all', projAll) }
    if (b.dataset.act === 'done') { projDone = !projDone; setPref('iroda-proj-done', projDone) }
    renderProjects(projList)
  })
  narrow.addEventListener('change', () => renderProjects(projList))
  function renderWaiting(cards, extra) {
    const items = cards.map((c) => `<li><span class="tag ${c.priority === 'urgent' || c.priority === 'high' ? '' : 'n'}">${esc(PRIO[c.priority] || c.priority)}</span><span>${esc(c.title)}</span></li>`)
      .concat(extra.map((t) => `<li><span class="tag n">teendő</span><span>${esc(t)}</span></li>`))
    $('#waitN').textContent = String(items.length)
    $('#waitList').innerHTML = items.join('') || '<li><span class="tag n">-</span><span>most nincs rád váró tétel</span></li>'
  }

  // ---- desk scene (from the approved mockup v2) ----
  function sceneSVG(id, placeholder, big) {
    const W = big ? 300 : 240, H = big ? 150 : 142, cx = W / 2
    const top = H * 0.66, y2 = top + 12, y3 = y2 + 9
    const x1 = W * 0.06, x2 = W * 0.94, inset = W * 0.05
    if (placeholder) return `<svg viewBox="0 0 ${W} ${H}"><ellipse cx="${cx}" cy="${H - 6}" rx="${W * 0.38}" ry="6" fill="rgba(30,42,51,.06)"/><path d="M${x1 + inset} ${top} L${x2 - inset} ${top} L${x2} ${y2} L${x1} ${y2} Z" fill="none" stroke="#C9C2B7" stroke-dasharray="4 4" stroke-width="1.4"/></svg>`
    const [hair, shirt] = look(id), px = W * 0.27, py = H * 0.80
    return `<svg viewBox="0 0 ${W} ${H}">
      <defs><linearGradient id="wt${W}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#EFE1CB"/><stop offset="1" stop-color="#E2CDAE"/></linearGradient></defs>
      <ellipse cx="${cx}" cy="${H - 4}" rx="${W * 0.44}" ry="7" fill="rgba(30,42,51,.10)"/>
      <rect x="${x1 + 8}" y="${y3}" width="4" height="${H - y3 - 6}" rx="1.5" fill="#B99B70"/><rect x="${x2 - 12}" y="${y3}" width="4" height="${H - y3 - 6}" rx="1.5" fill="#B99B70"/>
      <path d="M${x1 + inset} ${top} L${x2 - inset} ${top} L${x2} ${y2} L${x1} ${y2} Z" fill="url(#wt${W})"/>
      <path d="M${x1} ${y2} L${x2} ${y2} L${x2} ${y3} L${x1} ${y3} Z" fill="var(--wood-front)"/>
      <path d="M${x1} ${y3} L${x2} ${y3}" stroke="var(--wood-edge)" stroke-width="1"/>
      <rect x="${cx - 5}" y="${H * 0.59}" width="10" height="${top - H * 0.59 + 3}" fill="#2B333B"/>
      <ellipse cx="${cx}" cy="${top + 4}" rx="${W * 0.09}" ry="3.2" fill="#2B333B"/>
      <rect x="${cx + W * 0.06}" y="${top + 1}" width="${W * 0.16}" height="5" rx="1.5" fill="#F7F4EF" stroke="#D9D2C6" stroke-width=".6"/>
      <g transform="translate(${x2 - W * 0.11} ${top - 9})"><rect x="0" y="0" width="10" height="11" rx="2" fill="#FFFFFF" stroke="#D5CEC3" stroke-width=".7"/><path d="M10 3 q4 0 4 3 q0 3 -4 3" fill="none" stroke="#D5CEC3" stroke-width="1.2"/><path d="M3 -2 q1 -2 0 -4 M6 -2 q1 -2 0 -4" stroke="#CFC8BD" stroke-width=".8" fill="none"/></g>
      <g transform="translate(${px} ${py})">
        <rect x="-21" y="-12" width="42" height="34" rx="9" fill="#39434C"/>
        <path d="M-17 4 q17 -14 34 0 L17 18 L-17 18 Z" fill="${shirt}"/>
        <circle cx="0" cy="-10" r="9.5" fill="${hair}"/>
        <path d="M-9 -8 q9 6 18 0" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="2"/>
      </g>
    </svg>`
  }

  // What the monitor shows: media (fresh thumbnail) > document > tool call > idle.
  function screenOf(a) {
    if (!a) return { t: 'off', l1: 'nincs ágens' }
    if (!a.running) return { t: 'off', l1: 'alszik', l2: 'hívásra indul' }
    if (a.media && a.media.ageSec < FRESH_SEC) return { t: 'media', cap: a.media.caption, video: a.media.kind === 'video', v: a.media.v }
    const act = a.activity && a.activity.ageSec < FRESH_SEC ? a.activity : null
    if (act && act.file && /\.(md|pdf|docx?)$/i.test(act.file)) return { t: 'doc', title: act.file }
    if (act) return { t: 'code', l1: act.line, l2: a.work || '' } // activityLine already carries its own prefix
    return { t: 'idle', l1: a.activity ? 'utolsó jel ' + ago(a.activity.ageSec) : 'nincs friss jel', l2: a.work || '' }
  }
  function screenHTML(id, a, placeholder) {
    if (placeholder) return '<div class="mon empty"><div class="scr">üres hely<br>tervezett</div></div>'
    const s = screenOf(a), [cls] = stOf(a)
    const mcls = cls === 'work' ? 'work' : cls === 'stall' ? 'stall' : cls === 'off' ? 'off' : ''
    let inner
    if (s.t === 'code') inner = `<div class="scr"><div class="pad"><div class="l1">${esc(s.l1)}${cls === 'work' ? ' <i class="cur"></i>' : ''}</div><div class="l2">${esc(s.l2)}</div></div></div>`
    else if (s.t === 'media') {
      const th = thumbs[id]
      const img = th && th.v === s.v && th.url ? `<img src="${th.url}" alt="">` : ''
      inner = `<div class="scr ${cls === 'work' ? '' : 'dim'}">${img}${s.video ? '<div class="playbar"><i></i></div>' : ''}<div class="cap">${esc(s.cap)}</div></div>`
    } else if (s.t === 'doc') inner = `<div class="scr doc"><div class="page">${esc(s.title)}<i></i><i></i><i class="s"></i><i></i><i class="s"></i></div></div>`
    else if (s.t === 'idle') inner = `<div class="scr idle"><div class="pad"><div class="l1">${esc(s.l1)}</div><div class="l2">${esc(s.l2)}</div></div></div>`
    else inner = `<div class="scr off"><div class="pad">${esc(s.l1)}${s.l2 ? '<br>' + esc(s.l2) : ''}</div></div>`
    return `<div class="mon ${mcls}">${inner}</div>`
  }
  function deskHTML(id, big) {
    const seat = seats[id] || { id, name: id, role: '' }, a = A[id], ph = !!seat.placeholder
    const [cls, label] = ph ? ['none', 'üres hely'] : stOf(a)
    const q = a ? a.queue : { n: 0, oldestSec: 0 }
    const card = ph ? seat.role : (a && a.work) || (a && a.cards.top[0] && a.cards.top[0].title) || 'nincs nyitott kártya'
    return `<div class="desk ${big ? 'big' : ''} ${openId === id ? 'open' : ''}" data-id="${esc(id)}">
      <div class="scene">${sceneSVG(id, ph, big)}${screenHTML(id, a, ph)}</div>
      <div class="info"><span class="nm">${esc(seat.name)} <span class="pill ${cls}">${label}</span></span>
        ${ph ? '' : `<span class="q ${q.n >= 10 ? 'hot' : ''}">${q.n ? `sor ${q.n} · ${ago(q.oldestSec)}` : 'sor 0'}</span>`}
        <span class="card">${ph ? '' : esc(seat.role) + (seat.role ? ' · ' : '')}${esc(card)}</span></div></div>`
  }
  function wantThumb(id) {
    const a = A[id]
    if (!a || !a.running || !a.media || a.media.ageSec >= FRESH_SEC) return
    const th = thumbs[id]
    if (th && (th.v === a.media.v || th.pending)) return
    thumbs[id] = { v: a.media.v, url: th ? th.url : '', pending: true }
    api(`/api/iroda/thumb/${encodeURIComponent(id)}?v=${a.media.v}`)
      .then((r) => r.ok ? r.blob() : null)
      .then((b) => {
        const old = thumbs[id] && thumbs[id].url
        thumbs[id] = { v: a.media.v, url: b ? URL.createObjectURL(b) : '', pending: false }
        if (old && old !== thumbs[id].url) URL.revokeObjectURL(old)
        delete deskCache[id]
        renderDesks()
      })
      .catch(() => { thumbs[id] = { v: a.media.v, url: '', pending: false } })
  }

  function renderOrg(org) {
    $('#boss').innerHTML = `<div data-slot="${esc(org.lead.id)}" data-big="1"></div>`
    $('#depts').innerHTML = org.depts.map((d) => `<div class="room" data-dept="${esc(d.id)}"><div class="head"><h3>${esc(d.name)}</h3><div class="lead">${esc(d.lead)}</div><div class="stats" data-stats="${esc(d.id)}"></div></div>
      <div class="stack">${d.seats.map((s) => `<div data-slot="${esc(s.id)}"></div>`).join('')}</div></div>`).join('')
    for (const k of Object.keys(deskCache)) delete deskCache[k]
  }
  // Re-render only the desks whose html changed; returns true if anything did.
  function renderDesks() {
    let changed = false
    for (const slot of $$('[data-slot]')) {
      const id = slot.dataset.slot, html = deskHTML(id, slot.dataset.big === '1')
      if (deskCache[id] !== html) { slot.innerHTML = html; deskCache[id] = html; changed = true }
      wantThumb(id)
    }
    if (S) for (const d of S.org.depts) {
      const real = d.seats.filter((s) => !s.placeholder).map((s) => A[s.id]).filter(Boolean)
      const qn = real.reduce((n, a) => n + a.queue.n, 0), cnt = (k) => real.reduce((n, a) => n + (a.cards.counts[k] || 0), 0)
      const el = $(`[data-stats="${CSS.escape(d.id)}"]`)
      const html = real.length ? `<span class="chip ${qn >= 10 ? 'hot' : ''}">sor <b>${qn}</b></span><span class="chip">folyamatban <b>${cnt('in_progress')}</b></span><span class="chip">vár <b>${cnt('waiting')}</b></span>` : '<span class="chip">még nincs ágens</span>'
      if (el && el.innerHTML !== html) { el.innerHTML = html; changed = true }
    }
    if (changed) layout()
    return changed
  }

  // ---- geometry: one tree, every envelope travels on it (from mockup v2) ----
  const orgEl = $('#org')
  function rect(el) { const o = orgEl.getBoundingClientRect(), r = el.getBoundingClientRect(); return { x: r.left - o.left, y: r.top - o.top, w: r.width, h: r.height, r: r.right - o.left, b: r.bottom - o.top, cx: r.left - o.left + r.width / 2 } }
  let G = null
  function layout() {
    const lead = S && S.org.lead.id, kEl = lead && $(`.desk[data-id="${CSS.escape(lead)}"] .scene`), roomEls = $$('.room')
    if (!kEl || !roomEls.length) { G = null; return }
    const K = rect(kEl), rooms = roomEls.map(rect)
    const mobile = rooms.length > 1 && rooms[1].y > rooms[0].y + 5
    const trunkX = rooms[0].x - 12
    const kOut = [[K.cx, K.b + 2]]
    if (mobile) kOut.push([K.cx, K.b + 14], [trunkX, K.b + 14]); else kOut.push([K.cx, (K.b + rooms[0].y) / 2 + 6])
    const busY = mobile ? null : kOut[1][1]
    G = { lead, K: kOut, depts: {}, desks: {}, mobile, busY, trunkX }
    roomEls.forEach((el, i) => {
      const R = rooms[i], spineX = R.x + 19, entry = mobile ? [spineX, R.y + 22] : [spineX, R.y], hub = mobile ? [trunkX, R.y + 22] : [spineX, busY]
      const desks = [...el.querySelectorAll('.desk')].map((d) => { const s = rect(d.querySelector('.scene')); const y = s.y - 6; return { id: d.dataset.id, A: [spineX, y], B: [s.cx, y], C: [s.cx, s.y + 4] } })
      G.depts[el.dataset.dept] = { entry, hub, spineX, desks }
      desks.forEach((d) => { G.desks[d.id] = { dept: el.dataset.dept, ...d } })
    })
    let d = `M${G.K.map((p) => p.join(' ')).join(' L')}`
    const hubs = Object.values(G.depts).map((x) => x.hub)
    if (!mobile) { const xs = hubs.map((h) => h[0]).concat([G.K[1][0]]); d += ` M${Math.min(...xs)} ${busY} L${Math.max(...xs)} ${busY}` }
    else d += ` M${trunkX} ${G.K[2][1]} L${trunkX} ${hubs[hubs.length - 1][1]}`
    Object.values(G.depts).forEach((x) => {
      if (!x.desks.length) return
      const lastY = Math.max(...x.desks.map((k) => k.A[1]))
      d += ` M${x.hub.join(' ')} L${x.entry.join(' ')} L${x.spineX} ${lastY}`
      x.desks.forEach((k) => { d += ` M${k.A.join(' ')} L${k.B.join(' ')} L${k.C.join(' ')}` })
    })
    $('#static').innerHTML = `<path class="wire" d="${d}"/>`
  }
  const onTree = (id) => G && (id === G.lead || G.desks[id])
  function route(from, to) {
    const up = (id) => { if (id === G.lead) return G.K.slice().reverse(); const k = G.desks[id], x = G.depts[k.dept]; return [k.C, k.B, k.A, x.entry, x.hub] }
    let pts
    if (from !== G.lead && to !== G.lead && G.desks[from].dept === G.desks[to].dept) { const a = G.desks[from], b = G.desks[to]; pts = [a.C, a.B, a.A, b.A, b.B, b.C] }
    else pts = up(from).concat(up(to).reverse())
    return pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1])
  }
  function polyPath(pts, r = 10) {
    let d = `M${pts[0][0]} ${pts[0][1]}`
    for (let i = 1; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1]
      const l1 = Math.hypot(x1 - x0, y1 - y0), l2 = Math.hypot(x2 - x1, y2 - y1), rr = Math.min(r, l1 / 2, l2 / 2)
      if (!l1 || !l2) continue
      d += ` L${x1 - (x1 - x0) / l1 * rr} ${y1 - (y1 - y0) / l1 * rr} Q${x1} ${y1} ${x1 + (x2 - x1) / l2 * rr} ${y1 + (y2 - y1) / l2 * rr}`
    }
    const L = pts[pts.length - 1]; return d + ` L${L[0]} ${L[1]}`
  }

  // ---- envelopes ----
  const ENV = '<svg class="ic" viewBox="0 0 24 18"><rect x=".75" y=".75" width="22.5" height="16.5" rx="3" fill="#FFFDF8" stroke="#2F6F6A" stroke-width="1.3"/><path d="M2 2.5 L12 10 L22 2.5" fill="none" stroke="#2F6F6A" stroke-width="1.3" stroke-linejoin="round"/></svg>'
  const nameOf = (id) => (seats[id] && seats[id].name) || id
  let flights = []
  function makeFlight(m, start) {
    if (!onTree(m.from) || !onTree(m.to)) return null
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    p.setAttribute('d', polyPath(route(m.from, m.to))); p.setAttribute('class', 'trail'); p.style.opacity = 0
    $('#trails').appendChild(p)
    const L = p.getTotalLength(), dur = Math.min(3.2, Math.max(1.5, L / SPEED))
    p.style.strokeDasharray = `${L} ${L}`; p.style.strokeDashoffset = L
    const e = document.createElement('div'); e.className = 'env'; e.style.display = 'none'
    e.innerHTML = ENV + `<div class="lb">${esc(nameOf(m.from))} → ${esc(nameOf(m.to))}: ${esc(m.subject)}</div>`
    orgEl.appendChild(e)
    return { m, start, p, L, dur, e, fired: false, arrived: false }
  }
  function clearFlights() { $('#trails').innerHTML = ''; $$('.env').forEach((e) => e.remove()); flights = [] }
  const ease = (u) => u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2
  const monOf = (id) => $(`.desk[data-id="${CSS.escape(id)}"] .mon`)
  function drawFlights(now) {
    let lane = 0
    for (const f of flights) {
      const u = (now - f.start) / f.dur
      if (u >= 0 && u <= 1) {
        const pt = f.p.getPointAtLength(f.L * ease(u))
        f.e.style.display = 'block'; f.e.style.transform = `translate(${pt.x}px,${pt.y}px)`
        f.e.querySelector('.lb').style.transform = `translateY(${-lane * 30}px)`; lane++
        f.p.style.opacity = 0.9; f.p.style.strokeDashoffset = f.L * (1 - ease(u))
        if (!f.fired) { f.fired = true; const m = monOf(f.m.from); if (m) { m.classList.add('flash'); setTimeout(() => m.classList.remove('flash'), 900) } }
      } else {
        f.e.style.display = 'none'
        if (u > 1 && u < 1.6) {
          f.p.style.opacity = Math.max(0, 0.9 * (1 - (u - 1) / 0.6)); f.p.style.strokeDashoffset = 0
          if (!f.arrived) { f.arrived = true; const m = monOf(f.m.to); if (m) { m.classList.remove('ping'); void m.offsetWidth; m.classList.add('ping') } }
        } else f.p.style.opacity = 0
        if (u < 0) { f.fired = false; f.arrived = false }
      }
    }
  }

  // ---- log + drawer ----
  function renderLog(list) {
    $('#log').innerHTML = list.slice(0, 6).map((m) => `<li><span>${clock(m.at)}</span><span><b>${esc(nameOf(m.from))}</b> → <b>${esc(nameOf(m.to))}</b></span><span>${esc(m.subject)}</span></li>`).join('')
      || '<li><span></span><span></span><span>az elmúlt 30 percben nem ment üzenet</span></li>'
  }
  function renderDrawer() {
    const id = openId
    if (!id || !S) { $('#drawer').innerHTML = '<h3>Kattints egy asztalra</h3><div class="sub">a kártyái, a sora és az utolsó üzenetei</div>'; return }
    const seat = seats[id] || { name: id, role: '' }, a = A[id]
    const [cls, label] = seat.placeholder ? ['none', 'üres hely'] : stOf(a)
    const mine = S.messages.filter((m) => m.from === id || m.to === id).slice(0, 5)
    const c = a && a.cards
    $('#drawer').innerHTML = `<h3>${esc(seat.name)} <span class="pill ${cls}">${label}</span></h3>
      <div class="sub">${esc(seat.role)}${a ? ` · sor: ${a.queue.n}${a.queue.n ? `, a legrégebbi ${ago(a.queue.oldestSec)}` : ''} · kártyák: ${c.counts.in_progress || 0} folyamatban, ${c.counts.waiting || 0} vár, ${c.counts.planned || 0} tervezett` : ''}</div>
      ${a && a.work ? `<h4>Most</h4><ul><li>${esc(a.work)}${a.since != null ? ` · ${ago(a.since)} óta` : ''}</li></ul>` : ''}
      <h4>Kártyák</h4><ul>${c && c.top.length ? c.top.map((k) => `<li><span class="st ${esc(k.status)}">${esc(STN[k.status] || k.status)}</span>${esc(k.title)}</li>`).join('') : '<li>nincs</li>'}</ul>
      <h4>Utolsó 5 üzenet</h4><ul>${mine.length ? mine.map((m) => `<li>${clock(m.at)} · ${m.from === id ? '→ ' + esc(nameOf(m.to)) : '← ' + esc(nameOf(m.from))}: ${esc(m.subject)}</li>`).join('') : '<li>nincs az elmúlt 30 percben</li>'}</ul>`
  }
  orgEl.addEventListener('click', (ev) => {
    const d = ev.target.closest('.desk'); if (!d) return
    openId = d.dataset.id
    $$('.desk.open').forEach((x) => x.classList.remove('open')); d.classList.add('open')
    for (const k of Object.keys(deskCache)) delete deskCache[k] // the open class is part of the html
    renderDrawer()
  })

  // ---- live / replay ----
  const replay = qs.get('replay') === '1'
  const frozen = qs.get('t') !== null
  let rt = frozen ? parseFloat(qs.get('t')) || 0 : 0, playing = !frozen, lastTs = null
  let replayMsgs = []
  const seen = new Set()
  let firstLoad = true

  function apply(snap) {
    S = snap
    A = Object.fromEntries(snap.agents.map((a) => [a.id, a]))
    seats = Object.fromEntries([snap.org.lead, ...snap.org.depts.flatMap((d) => d.seats)].map((s) => [s.id, s]))
    const key = JSON.stringify(snap.org)
    if (key !== orgKey) { orgKey = key; renderOrg(snap.org); clearFlights() }
    renderProjects(snap.projects)
    renderWaiting(snap.waiting, snap.patrikraVar || [])
    renderDesks()
    if (!G) layout()
    renderDrawer()
    if (replay) {
      if (firstLoad) buildReplay()
    } else {
      renderLog(snap.messages)
      const now = performance.now() / 1000
      const fresh = snap.messages.filter((m) => !seen.has(m.id)).sort((x, y) => x.id - y.id)
      fresh.forEach((m) => seen.add(m.id))
      if (!firstLoad) fresh.forEach((m, i) => { const f = makeFlight(m, now + i * 0.6); if (f) flights.push(f) })
      flights = flights.filter((f) => { if (now - f.start > f.dur * 1.6 + 1) { f.p.remove(); f.e.remove(); return false } return true })
    }
    firstLoad = false
    const live = $('#live')
    live.classList.remove('stale')
    $('#liveText').textContent = (replay ? 'visszajátszás · ' : 'élő · ') + new Date(snap.at * 1000).toLocaleTimeString('hu-HU', { timeZone: 'Europe/Budapest' })
  }
  function buildReplay() {
    clearFlights()
    const list = S.messages.slice().sort((x, y) => x.at - y.at || x.id - y.id)
    if (!list.length) { renderLog([]); return }
    const t0 = list[0].at, span = Math.max(1, list[list.length - 1].at - t0)
    replayMsgs = list.map((m) => ({ ...m, rt: 1 + (m.at - t0) / span * (LOOP - 5) }))
    flights = replayMsgs.map((m) => makeFlight(m, m.rt)).filter(Boolean)
    $('#replayBox').hidden = false
  }
  function frame(ts) {
    if (replay) {
      if (lastTs !== null && playing) { rt += (ts - lastTs) / 1000; if (rt > LOOP) rt = 0 }
      lastTs = ts
      drawFlights(rt)
      const shown = replayMsgs.filter((m) => m.rt <= rt)
      renderLog(shown.slice().reverse())
      const cur = shown[shown.length - 1]
      $('#clock').textContent = cur ? clock(cur.at) : (replayMsgs[0] ? clock(replayMsgs[0].at) : '')
      $('#bar').style.width = (rt / LOOP * 100) + '%'
    } else drawFlights(ts / 1000)
    requestAnimationFrame(frame)
  }
  $('#play').onclick = () => { playing = !playing; $('#play').textContent = playing ? 'Szünet' : 'Lejátszás' }
  if (!playing) $('#play').textContent = 'Lejátszás'

  async function poll() {
    try {
      const r = await api('/api/iroda/snapshot')
      if (r.status === 401) { $('#live').classList.add('stale'); $('#liveText').innerHTML = 'nincs belépve: <a href="/dashboard">belépés a Dashboardon</a>'; return }
      if (!r.ok) throw new Error('http ' + r.status)
      apply(await r.json())
    } catch {
      $('#live').classList.add('stale'); $('#liveText').textContent = 'nincs kapcsolat, újrapróbálom'
    } finally {
      if (!replay || firstLoad) setTimeout(poll, POLL_MS)
    }
  }
  addEventListener('resize', () => { layout(); if (replay && S) buildReplay(); else clearFlights() })
  ;(document.fonts ? document.fonts.ready : Promise.resolve()).then(() => { poll(); requestAnimationFrame(frame) })
})()
