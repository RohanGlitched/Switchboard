/* Switchboard console. Vanilla JS, no build step — one less thing to break
   between a judge cloning the repo and seeing it work. */

const $ = (id) => document.getElementById(id);

const state = {
  cards: new Map(),      // card_id -> card
  rows: new Map(),       // message_id -> DOM row
  handled: 0,
  escalated: 0,
  policy: [],
  started: null,
  running: false,
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

/* tally */

function renderTally() {
  const open = [...state.cards.values()].filter((c) => c.status === 'open').length;
  const num = $('tally-num');
  const word = $('tally-word');
  const sub = $('tally-sub');

  num.textContent = open;
  num.classList.toggle('zero', open === 0);

  if (open === 0) {
    word.textContent = state.handled ? 'You’re clear.' : 'Nothing needs you.';
    sub.textContent = state.handled
      ? `${state.handled} handled without you this week.`
      : 'The week hasn’t started yet.';
  } else {
    word.textContent = open === 1 ? 'One decision needs you.' : `${open} decisions need you.`;
    sub.textContent = `${state.handled} others were handled without you.`;
  }

  $('c-handled').textContent = state.handled;
  $('c-desk').textContent = state.escalated;
}

/* decision cards */

function cardHTML(c) {
  const never = c.tier === 'never';
  const opts = (c.options || []).map((o) =>
    `<li><b>${esc(o.label)}</b> — ${esc(o.detail)}</li>`).join('');

  return `
    <div class="card-top">
      <span class="chip ${never ? 'never' : ''}">${esc(c.class_label)}</span>
      ${never ? '<span class="chip never">never automatic</span>' : ''}
      <span class="card-when">${esc(c.sender)} · ${esc(c.sim_time)}</span>
    </div>

    <h3 class="card-head">${esc(c.headline)}</h3>

    <p class="quote"><span class="who">${esc(c.sender)}:</span> ${esc(c.body)}</p>

    <div class="why"><strong>Why you’re seeing this.</strong> ${esc(c.why_escalated)}</div>

    <div class="rec-label">What Switchboard would do</div>
    <p class="rec">${esc(c.recommendation)}</p>

    ${c.draft_reply ? `
      <div class="draft" id="draft-${c.id}" contenteditable="false">${esc(c.draft_reply)}</div>
      <div class="draft-note" id="note-${c.id}" hidden>Edited replies don’t count toward autonomy.</div>` : ''}

    ${opts ? `<ul class="options">${opts}</ul>` : ''}
    ${(c.citations || []).length ? `<div class="cites">${esc(c.citations.join(' · '))}</div>` : ''}

    <div class="actions" id="acts-${c.id}">
      <button class="btn btn-yes"  data-act="approve" data-card="${c.id}">Approve and send</button>
      ${c.draft_reply ? `<button class="btn btn-edit" data-act="edit" data-card="${c.id}">Edit first</button>` : ''}
      <button class="btn btn-no"   data-act="deny"    data-card="${c.id}">I'll handle it</button>
    </div>`;
}

function upsertCard(c) {
  state.cards.set(c.id, c);
  let el = document.querySelector(`[data-cardroot="${c.id}"]`);
  if (!el) {
    const empty = $('cards').querySelector('.empty');
    if (empty) empty.remove();
    el = document.createElement('article');
    el.className = 'card' + (c.tier === 'never' ? ' tier-never' : '');
    el.dataset.cardroot = c.id;
    $('cards').prepend(el);
  }
  el.innerHTML = cardHTML(c);
  renderTally();
}

function resolveCardUI(c, modified) {
  const el = document.querySelector(`[data-cardroot="${c.id}"]`);
  state.cards.set(c.id, c);
  if (el) {
    el.classList.add('resolved');
    const acts = el.querySelector('.actions');
    if (acts) {
      const label = c.status === 'approved'
        ? (modified ? 'Edited and sent' : 'Approved and sent')
        : 'You took this one';
      acts.innerHTML = `<span class="verdict ${c.status === 'denied' ? 'denied' : ''}">${label}</span>`;
    }
  }
  renderTally();
  if (![...state.cards.values()].some((x) => x.status === 'open')) {
    setTimeout(showClearState, 420);
  }
}

function showClearState() {
  if ([...state.cards.values()].some((c) => c.status === 'open')) return;
  const box = document.createElement('div');
  box.className = 'empty';
  box.innerHTML = `
    <h3>Desk clear.</h3>
    <p>${state.handled} messages handled without you, ${state.escalated} brought to you.
       Everything it did is on the record on the right.</p>`;
  $('cards').appendChild(box);
}

/* activity stream */

function streamRow(msg) {
  const row = document.createElement('div');
  row.className = 'stream-row';
  row.innerHTML = `
    <div class="stream-top">
      <span class="stream-who">${esc(msg.sender)}</span>
      <span class="stream-when">${esc(msg.sim_time)}</span>
    </div>
    <div class="stream-body">${esc(msg.body)}</div>
    <div class="thinking"><span class="dots"><span></span><span></span><span></span></span>reading</div>
    <div class="tools"></div>`;
  $('stream').prepend(row);
  state.rows.set(msg.id, row);
  return row;
}

function setThinking(mid, text) {
  const row = state.rows.get(mid);
  if (!row) return;
  const t = row.querySelector('.thinking');
  if (t) t.lastChild.textContent = text;
}

function addTool(mid, tool) {
  const row = state.rows.get(mid);
  if (!row) return;
  const box = row.querySelector('.tools');
  if (!box || box.querySelector(`[data-t="${tool}"]`)) return;
  const s = document.createElement('span');
  s.className = 'tool';
  s.dataset.t = tool;
  s.textContent = tool.replace(/_/g, ' ');
  box.appendChild(s);
}

function finishRow(mid, kind, label, detail) {
  const row = state.rows.get(mid);
  if (!row) return;
  const t = row.querySelector('.thinking');
  if (t) t.remove();
  const v = document.createElement('div');
  v.className = 'stream-verdict';
  v.innerHTML = kind === 'handled'
    ? `<span class="tick">✓</span><span>${esc(label)}</span>`
    : `<span class="arrow">→</span><span>${esc(label)}</span>`;
  row.appendChild(v);
  if (detail) {
    const d = document.createElement('div');
    d.className = 'stream-body';
    d.style.marginTop = '5px';
    d.style.color = 'var(--ink-3)';
    d.textContent = detail;
    row.appendChild(d);
  }
}

/* autonomy dial */

function renderDial(classes) {
  state.policy = classes;
  const order = { auto: 0, ask: 1, never: 2 };
  const sorted = [...classes].sort((a, b) =>
    (order[a.tier] - order[b.tier]) || a.label.localeCompare(b.label));

  $('dial').innerHTML = sorted.map((c) => {
    if (c.tier === 'auto') {
      return `<span class="dchip auto" title="${esc(c.rationale)}">${esc(c.label)}
        <button data-demote="${esc(c.key)}" title="Return this to the Desk">×</button></span>`;
    }
    if (c.tier === 'never') {
      return `<span class="dchip never" title="${esc(c.rationale)}">${esc(c.label)}</span>`;
    }
    return `<span class="dchip" title="${esc(c.rationale)}">${esc(c.label)}
      <span class="prog">${c.approvals}/${c.threshold}</span></span>`;
  }).join('');
}

/* promotion moment */

function showPromotion(p) {
  $('promo-root').innerHTML = `
    <div class="promo-wrap">
      <div class="promo" role="dialog" aria-modal="true" aria-label="Switchboard is asking for autonomy">
        <div class="promo-from"><span class="pulse live"></span>Switchboard is asking</div>
        <q>${esc(p.message)}</q>
        <div class="promo-why">${esc(p.rationale)}</div>
        <div class="promo-acts">
          <button class="btn btn-yes"  data-promo="yes">Yes, handle these</button>
          <button class="btn btn-edit" data-promo="no">Keep asking me</button>
        </div>
      </div>
    </div>`;
  const btn = document.querySelector('[data-promo="yes"]');
  if (btn) btn.focus();
}

async function decidePromotion(accept) {
  $('promo-root').innerHTML = '';
  await post('/api/promotion', { accept });
}

/* events */

function onEvent(ev) {
  switch (ev.kind) {
    case 'hello':
      $('engine-text').innerHTML =
        `<b>${esc(ev.provider)}</b> · ${esc(String(ev.model).replace(/^us\./, ''))}`;
      $('pulse').classList.add('live');
      break;

    case 'week_start':
      state.started = Date.now();
      break;

    case 'message_in':
      streamRow(ev.message);
      break;

    case 'trace':
      if (!ev.message_id) break;
      if (ev.phase === 'tool_call' && ev.tool) addTool(ev.message_id, ev.tool);
      else if (ev.phase === 'thinking' && ev.node) setThinking(ev.message_id, nodeWord(ev.node));
      break;

    case 'triaged':
      setThinking(ev.message_id, `${ev.class_label.toLowerCase()} — deciding`);
      break;

    case 'handled':
      state.handled += 1;
      finishRow(ev.message_id, 'handled',
        `Handled alone — ${ev.class_label.toLowerCase()}`, ev.reply);
      renderTally();
      break;

    case 'escalated':
      state.escalated += 1;
      upsertCard(ev.card);
      finishRow(ev.card.message_id, 'escalated', 'Sent to your desk');
      break;

    case 'message_failed':
      finishRow(ev.message_id, 'escalated', 'Could not process — ' + ev.error);
      break;

    case 'card_resolved':
      resolveCardUI(ev.card, ev.modified);
      break;

    case 'policy':
      renderDial(ev.classes);
      break;

    case 'promotion_proposed':
      // On a reload the bus replays history. A promotion the Coordinator already
      // answered must not come back; the live state hydration below is the only
      // thing allowed to restore a still-pending one.
      if (!ev.replay) showPromotion(ev);
      break;

    case 'week_done':
      state.running = false;
      $('run').disabled = false;
      $('run').textContent = 'Run the week again';
      $('reset').disabled = false;
      $('c-time').textContent = `${ev.elapsed}s`;
      renderTally();
      break;
  }
}

function nodeWord(node) {
  return { triage: 'reading', resolver: 'acting', escalator: 'writing it up for you' }[node]
    || 'thinking';
}

/* wiring */

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return r.json().catch(() => ({}));
}

document.addEventListener('click', async (e) => {
  const promo = e.target.closest('[data-promo]');
  if (promo) return decidePromotion(promo.dataset.promo === 'yes');

  const dem = e.target.closest('[data-demote]');
  if (dem) return void post('/api/demote', { decision_class: dem.dataset.demote });

  const btn = e.target.closest('[data-act]');
  if (!btn) return;

  const id = btn.dataset.card;
  const draft = $(`draft-${id}`);

  if (btn.dataset.act === 'edit') {
    if (!draft) return;
    draft.contentEditable = 'true';
    draft.focus();
    const note = $(`note-${id}`);
    if (note) note.hidden = false;
    btn.textContent = 'Editing';
    btn.disabled = true;
    return;
  }

  btn.closest('.actions').querySelectorAll('button').forEach((b) => (b.disabled = true));
  await post(`/api/cards/${id}/resolve`, {
    action: btn.dataset.act,
    edited_reply: draft ? draft.textContent : null,
  });
});

$('run').addEventListener('click', async () => {
  state.running = true;
  $('run').disabled = true;
  $('run').textContent = 'Working…';
  $('reset').disabled = true;
  const res = await post('/api/run');
  if (res.detail) {
    // Usually a missing credential. Put the reason where the person is looking.
    state.running = false;
    $('run').disabled = false;
    $('run').textContent = 'Run the week';
    $('reset').disabled = false;
    $('engine-text').textContent = res.detail;
    $('pulse').classList.remove('live');
  }
});

$('reset').addEventListener('click', async () => {
  await post('/api/reset');
  location.reload();
});

function connect() {
  const src = new EventSource('/api/stream');
  src.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)); } catch (_) { /* ignore malformed frame */ }
  };
  src.onerror = () => {
    $('pulse').classList.remove('live');
    $('engine-text').textContent = 'reconnecting…';
  };
}

(async function init() {
  try {
    const s = await (await fetch('/api/state')).json();
    renderDial(s.policy);
    if (s.provider) {
      $('engine-text').innerHTML =
        `<b>${esc(s.provider.name)}</b> · ${esc(String(s.provider.model).replace(/^us\./, ''))}`;
      $('pulse').classList.add('live');
    }
    if (s.pending_promotion) showPromotion(s.pending_promotion);
  } catch (_) {
    $('engine-text').textContent = 'server unreachable';
  }
  connect();
  renderTally();
})();
