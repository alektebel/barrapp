'use strict';
/* The model card, rendered from /api/model. Nothing on this page is written
   here: every number, note and rule arrives from the server having been read
   out of the barra modules a moment ago, so a threshold that moves in the
   source moves on this page without anyone editing it. */

const $ = (s) => document.querySelector(s);
const el = (t, cls, txt) => { const n = document.createElement(t);
  if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };

let card = null;

const fmt = (v) => v === null ? '—'
  : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, '').replace(/\.$/, ''))
  : typeof v === 'boolean' ? (v ? 'yes' : 'no')
  : Array.isArray(v) ? v.join(', ')
  : String(v);

function section(title, lead) {
  const s = el('section', 'section');
  s.append(el('h2', null, title));
  if (lead) s.append(el('p', 'lead', lead));
  return s;
}

function constTable(rows) {
  const wrap = el('div', 'scroll-x inset');
  const table = el('table', 'table const-table');
  const head = el('tr');
  for (const h of ['Constant', 'Value', 'What it means', 'Defined in']) head.append(el('th', null, h));
  table.append(el('thead').appendChild(head).parentNode);
  const body = el('tbody');
  for (const r of rows) {
    const tr = el('tr');
    tr.dataset.hay = `${r.name} ${r.note} ${JSON.stringify(r.value)}`.toLowerCase();
    tr.append(el('td', 'name', r.name));
    const value = el('td', 'value');
    if (r.value && typeof r.value === 'object' && !Array.isArray(r.value)) {
      const nested = el('div', 'nested');
      for (const [k, v] of Object.entries(r.value)) {
        const line = el('div');
        line.append(el('span', null, k), el('b', null, fmt(v)));
        nested.append(line);
      }
      value.append(nested);
    } else value.textContent = fmt(r.value);
    tr.append(value, el('td', 'note', r.note || ''), el('td', 'src', r.source || ''));
    body.append(tr);
  }
  table.append(body);
  wrap.append(table);
  return wrap;
}

function renderPipeline() {
  const s = section('The prediction path, in order',
    'Ten stages. Each one names the module that owns it, what it decides, how it fails, ' +
    'and the first thing to look at when it is the suspect. Open a stage to see every ' +
    'constant that governs it.');
  card.pipeline.forEach((st, i) => {
    const row = el('article', 'stage');
    row.dataset.hay = JSON.stringify(st).toLowerCase();
    row.append(el('div').appendChild(el('span', 'step', String(i + 1))).parentNode);
    const main = el('div');
    main.append(el('h3', null, st.name),
                el('div', 'where', `${st.module} · ${st.fn}()`));
    const dl = el('dl');
    const add = (k, v, cls) => { dl.append(el('dt', null, k), el('dd', cls, v)); };
    add('Decides', st.decides);
    const emits = el('dd', null); emits.className = '';
    const chips = el('div', 'emits');
    for (const e of st.emits) chips.append(el('code', null, e));
    dl.append(el('dt', null, 'Emits'), el('dd').appendChild(chips).parentNode);
    add('How it fails', st.fails, 'fails');
    add('Look at first', st.look, 'look');
    main.append(dl);
    if (st.constants.length) {
      const d = el('details');
      d.append(el('summary', null,
        `${st.constants.length} constants govern this stage`));
      d.append(constTable(st.constants));
      main.append(d);
    }
    row.append(main);
    s.append(row);
  });
  return s;
}

function renderModules() {
  const s = section('Every constant, by module',
    'Read out of the source at request time, with the trailing comment that defines its ' +
    'meaning. This is the complete set — nothing in the prediction path reads a number ' +
    'that is not on this list.');
  for (const [name, rows] of Object.entries(card.modules)) {
    if (!rows.length) continue;
    const d = el('details', 'section');
    d.append(el('summary', null, `${name} — ${rows.length} constants`));
    d.append(constTable(rows));
    s.append(d);
  }
  return s;
}

function renderFaults() {
  const s = section('The technique rules',
    'Each rule fires when one measured primitive crosses one threshold, in one phase. ' +
    'A rule that cannot be measured from the clip’s viewpoint reports unobservable ' +
    'rather than absent.');
  for (const [track, rules] of Object.entries(card.faults)) {
    const d = el('details');
    d.append(el('summary', null, `${track.replaceAll('_', ' ')} — ${rules.length} rules`));
    const wrap = el('div', 'scroll-x inset');
    const t = el('table', 'table const-table');
    const head = el('tr');
    for (const h of ['Fault', 'Primitive', 'Fires when', 'Phase', 'Plane', 'Note'])
      head.append(el('th', null, h));
    t.append(el('thead').appendChild(head).parentNode);
    const body = el('tbody');
    for (const r of rules) {
      const tr = el('tr');
      tr.dataset.hay = JSON.stringify(r).toLowerCase();
      tr.append(el('td', 'name', r.fault.replaceAll('_', ' ')),
                el('td', 'name', r.key),
                el('td', 'value', `${r.op} ${fmt(r.threshold)}`),
                el('td', null, r.phase || 'any'),
                el('td', null, r.plane || '—'),
                el('td', 'note', r.note || (r.observable ? '' : 'viewpoint-dependent')));
      body.append(tr);
    }
    t.append(body); wrap.append(t); d.append(wrap);
    s.append(d);
  }
  return s;
}

function renderMovements() {
  const s = section('Movement profiles',
    'The movement chosen by the classifier selects a reference frame and a tracked signal. ' +
    'Get this wrong and every number below it is plausible and meaningless.');
  const grid = el('div', 'grid');
  for (const m of card.movements) {
    const c = el('article', 'card mini');
    c.dataset.hay = JSON.stringify(m).toLowerCase();
    c.append(el('h3', null, m.name.replaceAll('_', ' ')));
    const dl = el('dl');
    for (const [k, v] of Object.entries(m)) {
      if (k === 'name') continue;
      dl.append(el('dt', null, k), el('dd', null, fmt(v) || '—'));
    }
    c.append(dl);
    grid.append(c);
  }
  s.append(grid);
  return s;
}

function renderMetrics() {
  const s = section('Per-rep metrics',
    'The robustness class is the honest part: INVARIANT survives any viewpoint, SCALED ' +
    'needs the athlete’s own reach as a yardstick, and PLANAR is only meaningful from ' +
    'the viewpoint it assumes.');
  const wrap = el('div', 'scroll-x inset');
  const t = el('table', 'table const-table');
  const head = el('tr');
  for (const h of ['Metric', 'Label', 'Unit', 'Robustness', 'Better when'])
    head.append(el('th', null, h));
  t.append(el('thead').appendChild(head).parentNode);
  const body = el('tbody');
  for (const m of card.metrics) {
    const tr = el('tr');
    tr.dataset.hay = JSON.stringify(m).toLowerCase();
    tr.append(el('td', 'name', m.key), el('td', null, m.label),
              el('td', 'value', m.unit),
              el('td').appendChild(el('span', 'tag tag-' +
                (m.robustness === 'PLANAR' ? 'accent' : m.robustness === 'SCALED' ? 'outline' : 'accent-2'),
                m.robustness)).parentNode,
              el('td', null, m.higherIsBetter === null ? 'neither' : m.higherIsBetter ? 'higher' : 'lower'));
    body.append(tr);
  }
  t.append(body); wrap.append(t); s.append(wrap);
  return s;
}

function renderProvenance() {
  const p = card.provenance || {};
  const s = section('Provenance — what produced these numbers',
    'Stamped on every payload. A score that moved without the athlete moving is answered ' +
    'here: a different commit, a different pose model file, or a changed measurement convention.');
  const grid = el('div', 'grid');
  const box = (title, entries) => {
    const c = el('article', 'card mini');
    c.dataset.hay = JSON.stringify(entries).toLowerCase();
    c.append(el('h3', null, title));
    const dl = el('dl');
    for (const [k, v] of entries) dl.append(el('dt', null, k), el('dd', null, fmt(v)));
    c.append(dl); return c;
  };
  grid.append(box('Build', [['barra', p.barra], ['commit', p.commit],
    ['python', p.python], ['platform', p.platform]]));
  const m = p.poseModel || {};
  grid.append(box('Pose model file', [['path', m.path], ['present', m.present],
    ['bytes', m.bytes], ['sha256', m.sha256_12]]));
  grid.append(box('Pose backends', [['registered', p.poseBackends],
    ['installed here', p.backendsInstalled]]));
  grid.append(box('Measurement conventions', Object.entries(p.measurement || {})));
  s.append(grid);
  return s;
}

function filter() {
  const term = $('#search').value.trim().toLowerCase();
  let hits = 0;
  for (const node of document.querySelectorAll('[data-hay]')) {
    const show = !term || node.dataset.hay.includes(term);
    node.classList.toggle('hidden', !show);
    if (show) hits += 1;
  }
  if (term) {
    // Open every container so a match cannot be hiding inside a closed one.
    for (const d of document.querySelectorAll('details')) d.open = true;
  }
  $('#status').textContent = term
    ? `${hits} rows match “${$('#search').value.trim()}”.`
    : summary();
}

function summary() {
  const c = card.counts;
  return `${c.constants} constants · ${c.faultRules} technique rules · ${c.metrics} metrics · ` +
         `${c.movements} movements · ${c.stages} stages. Read from the source on load.`;
}

async function boot() {
  try {
    const r = await fetch('/api/model');
    card = await r.json();
    if (!r.ok) throw Error(card.error || `HTTP ${r.status}`);
  } catch (e) {
    $('#status').className = 'status-line err';
    $('#status').textContent = e.message; return;
  }
  const c = card.counts;
  $('#stats').replaceChildren(...[
    ['Constants', c.constants, true], ['Technique rules', c.faultRules],
    ['Metrics', c.metrics], ['Movements', c.movements], ['Stages', c.stages],
  ].map(([k, v, lead]) => {
    const n = el('div', 'stat' + (lead ? ' lead' : ''));
    n.append(el('b', null, String(v)), el('span', null, k));
    return n;
  }));
  $('#body').replaceChildren(renderPipeline(), renderProvenance(), renderMovements(),
                             renderMetrics(), renderFaults(), renderModules());
  for (const w of card.warnings || []) {
    $('#body').prepend(el('p', 'status-line err', w));
  }
  $('#status').textContent = summary();
  $('#search').oninput = filter;
}

boot();
