/* The page reads traces. It does not decide anything.
 *
 * Every number rendered here was produced by the pipeline and written into a
 * trace entry or a payload: the amplitude lines, the thresholds, the fault
 * states. Where a value is missing the page says UNMEASURED rather than
 * filling it in, because that distinction is the one the fault layer currently
 * loses (feedback.md, finding C2) and a debug tool that papered over it would
 * hide the thing worth seeing. */
'use strict';

const $ = (s) => document.querySelector(s);
const el = (t, cls, txt) => { const n = document.createElement(t);
  if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };
const j = (u, o) => fetch(u, o).then((r) => r.json());
const fmt = (v) => typeof v === 'number'
  ? (Number.isInteger(v) ? String(v) : v.toPrecision(4).replace(/\.?0+$/, ''))
  : Array.isArray(v) ? (v.length > 8 ? `[${v.length} values]` : `[${v.map(fmt).join(', ')}]`)
  : v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);

const ST = {
  trace: null, payload: null, kp: null, spec: null, stage: null,
  clip: null, fps: 30, signal: null, reps: [], rejects: [], amp: null, poll: null,
};

/* ---------------------------------------------------------------- boot ---- */
async function boot() {
  const c = await j('/api/clips');
  const clip = $('#clip');
  c.clips.forEach((f) => {
    const o = el('option', null, `${f.name}${f.cached ? '  ·cached' : ''}`);
    o.value = f.name; clip.append(o);
  });
  const be = $('#backend');
  be.append(Object.assign(el('option', null, 'backend: auto'), { value: '' }));
  (c.backends || []).forEach((b) => be.append(Object.assign(el('option', null, b), { value: b })));
  ST.spec = await j('/api/faultspec');
  await refreshTraces();
  $('#run').onclick = run;
  $('#trace').onchange = () => loadTrace($('#trace').value);
  $('#diff').onclick = diff;
  $('#video').addEventListener('timeupdate', draw);
  $('#video').addEventListener('seeked', draw);
  $('#video').addEventListener('loadeddata', () => { sizeCanvas(); draw(); });
  addEventListener('resize', () => { sizeCanvas(); draw(); drawChart(); });
  $('#chart').onclick = (e) => {
    if (!ST.dur) return;
    const r = e.target.getBoundingClientRect();
    $('#video').currentTime = ((e.clientX - r.left) / r.width) * ST.dur;
  };
  if (c.clips.length) $('#clip').value = c.clips[0].name;
}

async function refreshTraces(select) {
  const t = await j('/api/traces');
  const sel = $('#trace');
  sel.innerHTML = '';
  sel.append(Object.assign(el('option', null, `traces (${t.traces.length})`), { value: '' }));
  t.traces.forEach((r) => {
    const marks = (r.rejections ? ` ✗${r.rejections}` : '') + (r.errors ? ` !${r.errors}` : '');
    const o = el('option', null, `${r.traceId}  ${r.subject}${marks}`);
    o.value = r.traceId; sel.append(o);
  });
  if (select) sel.value = select;
  return t.traces;
}

/* ----------------------------------------------------------------- run ---- */
function status(text, cls) { const s = $('#status'); s.textContent = text; s.className = cls || ''; }

async function run() {
  $('#run').disabled = true;
  status('starting…', 'run');
  const body = { clip: $('#clip').value, exercise: $('#exercise').value,
                 fresh: $('#fresh').checked, backend: $('#backend').value };
  const r = await j('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify(body) });
  if (!r.runId) { status(r.error || 'could not start', 'err'); $('#run').disabled = false; return; }
  clearInterval(ST.poll);
  ST.poll = setInterval(() => pollRun(r.runId), 400);
}

async function pollRun(id) {
  const s = await j('/api/runs/' + id);
  if (s.state === 'running') { status(`${s.stage}  ${s.elapsed}s`, 'run'); return; }
  clearInterval(ST.poll);
  $('#run').disabled = false;
  if (s.state === 'failed') {
    status(s.error || 'failed', 'err');
    $('#entries').innerHTML = '';
    $('#entries').append(el('div', 'kv', s.error || ''));
    (s.log || []).forEach((l) => $('#entries').append(el('div', 'kv', l)));
    if (s.traceId) { await refreshTraces(s.traceId); loadTrace(s.traceId); }
    return;
  }
  status(`${s.exercise} · ${s.reps} reps · ${s.rejections} rejections`
         + (s.poseSource === 'cache' ? ' · cached pose' : ` · ${s.poseSource}`), 'ok');
  await refreshTraces(s.traceId);
  loadTrace(s.traceId);
}

/* --------------------------------------------------------------- trace ---- */
async function loadTrace(id) {
  if (!id) return;
  ST.trace = await j('/api/traces/' + id);
  ST.payload = await j(`/api/traces/${id}/payload`).catch(() => null);
  if (ST.payload && ST.payload.error) ST.payload = null;
  ST.clip = ST.trace.subject || (ST.trace.context || {}).clip || '';
  const stem = ST.clip.replace(/\.[^.]+$/, '');
  $('#clip-title').textContent = `${ST.clip}  ·  ${id}`;
  $('#video').src = '/api/video/' + encodeURIComponent(ST.clip);
  ST.kp = await j('/api/keypoints/' + encodeURIComponent(stem)).catch(() => null);
  if (ST.kp && ST.kp.error) ST.kp = null;
  readSignal();
  renderRail();
  selectStage(defaultStage());
  await renderRight(id);
  drawChart();
}

/* Pull the chart's raw material out of the trace. Nothing is recomputed: the
 * signal, the amplitude lines and the rep windows are all entries the
 * segmenter wrote as it decided. */
function readSignal() {
  ST.signal = null; ST.amp = null; ST.reps = []; ST.rejects = []; ST.dur = 0;
  const es = (ST.trace && ST.trace.entries) || [];
  for (const e of es) {
    const d = e.data || {};
    if (e.message === 'keypoint timesteps' && Array.isArray(d.signal)) {
      ST.signal = d.signal; ST.fps = d.fps || 30;
    }
    if (e.message === 'amplitude') ST.amp = d;
    if (e.message === 'candidate turnarounds') ST.cands = d;
    // The relaxed pass writes its accepted reps under `rescue`, not `segment`.
    // Reading only `segment` left a rescued rep invisible on the chart while
    // the payload counted it - the chart would have been quietly lying.
    if ((e.stage === 'segment' || e.stage === 'rescue')
        && e.kind === 'decision' && Array.isArray(d.window_s)) {
      ST.reps.push({ w: d.window_s, turn: d.turnaround_s, label: d.outcome,
                     rescued: e.stage === 'rescue' });
    }
    if (e.kind === 'reject') ST.rejects.push(e);
    if (e.message === 'container' && d.duration_s) ST.dur = d.duration_s;
  }
  if (!ST.dur && ST.signal) ST.dur = ST.signal.length / ST.fps;
  if (ST.payload && ST.payload.duration_s) ST.dur = ST.payload.duration_s;
}

/* The stage worth opening first: whichever one has a rejection or an error,
 * else the last stage that ran. Never a stage this trace does not have - the
 * server pipeline ends at `quality`, the CLI's at `result`. */
function defaultStage() {
  const es = (ST.trace || {}).entries || [];
  const bad = es.find((e) => e.kind === 'error') || es.find((e) => e.kind === 'reject');
  if (bad) return bad.stage;
  return es.length ? es[es.length - 1].stage : null;
}

/* ---------------------------------------------------------------- rail ---- */
const ORDER = ['job', 'probe', 'pose', 'classify', 'segment', 'rescue', 'metrics',
               'quality', 'result'];

function renderRail() {
  const rail = $('#rail'); rail.innerHTML = '';
  const byStage = new Map();
  ((ST.trace || {}).entries || []).forEach((e) => {
    const c = byStage.get(e.stage) || { step: 0, decision: 0, reject: 0, note: 0, error: 0 };
    c[e.kind] = (c[e.kind] || 0) + 1; byStage.set(e.stage, c);
  });
  const stages = [...ORDER.filter((s) => byStage.has(s)),
                  ...[...byStage.keys()].filter((s) => !ORDER.includes(s))];
  stages.forEach((s) => {
    const c = byStage.get(s);
    const row = el('div', 'stage' + (s === ST.stage ? ' on' : ''));
    row.append(el('span', null, s));
    const n = el('span', 'n');
    if (c.decision) n.append(Object.assign(el('b'), { textContent: '→' + c.decision + ' ' }));
    if (c.reject) n.append(Object.assign(el('i'), { textContent: '✗' + c.reject + ' ' }));
    if (c.error) n.append(Object.assign(el('u'), { textContent: '!' + c.error + ' ' }));
    if (!c.decision && !c.reject && !c.error) n.textContent = String(c.step || 0);
    row.append(n);
    row.onclick = () => selectStage(s);
    rail.append(row);
  });
}

/* ------------------------------------------------------------- entries ---- */
function selectStage(s) {
  ST.stage = s; renderRail();
  const box = $('#entries'); box.innerHTML = '';
  $('#entries-title').textContent = `evidence · ${s}`;
  const es = ((ST.trace || {}).entries || []).filter((e) => e.stage === s);
  if (!es.length) { box.append(el('div', 'hint', 'no entries in this stage')); return; }
  es.forEach((e) => box.append(entryNode(e)));
}

function entryNode(e) {
  const d = e.data || {};
  const node = el('div', 'entry k-' + e.kind);
  const hd = el('div', 'hd');
  hd.append(el('span', 't', e.atMs + 'ms'));
  const mark = { decision: '→', reject: '✗', error: '!', note: '·', step: ' ' }[e.kind] || ' ';
  hd.append(el('span', 'm', `${mark} ${d.what ? d.what + ' — ' : ''}${e.message || ''}`
                            + (d.outcome ? `  (${d.outcome})` : '')));
  node.append(hd);

  const t = seconds(d);
  if (t != null) {
    node.classList.add('clickable');
    node.onclick = () => { $('#video').currentTime = t; };
  }
  Object.entries(d).forEach(([k, v]) => {
    if (k === 'outcome' || k === 'what') return;
    const line = el('div', 'kv');
    line.append(el('b', null, k)); line.append(document.createTextNode(' = ' + fmt(v)));
    node.append(line);
  });
  // A value beside the line it had to clear - the pair, which is what makes a
  // rejection debuggable at all (docs/DEBUGGING.md).
  const pair = thresholdPair(d);
  if (pair) node.append(bar(pair[0], pair[1]));
  return node;
}

const T_KEYS = [['wrist_travel', 'max_travel'], ['anchor_travel', 'max_travel'],
                ['value', 'threshold'], ['peak_above_hands', 'over_bar_threshold'],
                ['parked_frac', 'parked_max'], ['arm_articulation', 'articulation_min']];

function thresholdPair(d) {
  for (const [a, b] of T_KEYS) {
    if (typeof d[a] === 'number' && typeof d[b] === 'number') return [d[a], d[b]];
  }
  return null;
}

function bar(value, threshold) {
  const n = el('div', 'bar');
  const hi = Math.max(Math.abs(value), Math.abs(threshold)) * 1.25 || 1;
  const pos = (x) => Math.max(0, Math.min(100, (Math.abs(x) / hi) * 100));
  const v = el('i'); v.style.left = pos(value) + '%';
  const t = el('u'); t.style.left = pos(threshold) + '%';
  n.append(t, v);
  return n;
}

function seconds(d) {
  if (Array.isArray(d.window_s) && d.window_s.length) return d.window_s[0];
  if (typeof d.turnaround_s === 'number') return d.turnaround_s;
  if (Array.isArray(d.at_seconds) && typeof d.at_seconds[0] === 'number') return d.at_seconds[0];
  return null;
}

/* -------------------------------------------------------------- overlay --- */
function sizeCanvas() {
  const v = $('#video'), c = $('#overlay');
  c.width = v.clientWidth; c.height = v.clientHeight;
}

/* Draw the keypoints the pipeline measured, in the frame they were measured
 * in. Joints under the confidence floor are hollow - "tracked in 31% of the
 * clip" becomes something you watch rather than a number you take on faith. */
function draw() {
  const v = $('#video'), c = $('#overlay'), g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  drawCursor();
  if (!ST.kp || !v.videoWidth) return;
  const i = Math.min(ST.kp.frames - 1, Math.round(v.currentTime * ST.fps));
  const pts = ST.kp.kp[i];
  if (!pts) return;
  // letterbox: object-fit contain
  const s = Math.min(c.width / v.videoWidth, c.height / v.videoHeight);
  const ox = (c.width - v.videoWidth * s) / 2, oy = (c.height - v.videoHeight * s) / 2;
  const X = (p) => ox + p[0] * s, Y = (p) => oy + p[1] * s;
  const MIN_CONF = 0.5;

  g.lineWidth = 2;
  ST.kp.edges.forEach(([a, b]) => {
    const pa = pts[a], pb = pts[b];
    if (!pa || !pb) return;
    const weak = pa[2] < MIN_CONF || pb[2] < MIN_CONF;
    g.strokeStyle = weak ? 'rgba(224,163,62,.45)' : 'rgba(90,169,230,.9)';
    g.beginPath(); g.moveTo(X(pa), Y(pa)); g.lineTo(X(pb), Y(pb)); g.stroke();
  });
  ST.kp.analysis.forEach((k) => {
    const p = pts[k]; if (!p) return;
    g.beginPath(); g.arc(X(p), Y(p), 3.2, 0, 7);
    if (p[2] < MIN_CONF) { g.strokeStyle = '#e0a33e'; g.stroke(); }
    else { g.fillStyle = '#d7dee8'; g.fill(); }
  });
  g.fillStyle = 'rgba(125,136,153,.9)'; g.font = '11px monospace';
  g.fillText(`frame ${i}/${ST.kp.frames}  t=${v.currentTime.toFixed(2)}s`, 8, 14);
}

/* ---------------------------------------------------------------- chart --- */
function drawChart() {
  const c = $('#chart'), g = c.getContext('2d');
  c.width = c.clientWidth; c.height = 150;
  g.clearRect(0, 0, c.width, c.height);
  if (!ST.signal || !ST.signal.length) {
    g.fillStyle = '#55606f'; g.font = '12px monospace';
    g.fillText('no tracking signal in this trace', 10, 24);
    return;
  }
  const sig = ST.signal, dur = ST.dur || sig.length / ST.fps;
  const lo = Math.min(...sig), hi = Math.max(...sig);
  const pad = (hi - lo) * 0.12 || 1;
  const Y = (v) => c.height - 14 - ((v - lo + pad) / (hi - lo + 2 * pad)) * (c.height - 22);
  const X = (t) => (t / dur) * c.width;

  // accepted reps, from the segmenter's own decisions
  ST.reps.forEach((r) => {
    g.fillStyle = 'rgba(79,191,127,.13)';
    g.fillRect(X(r.w[0]), 0, X(r.w[1]) - X(r.w[0]), c.height);
    g.strokeStyle = 'rgba(79,191,127,.55)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(r.turn), 0); g.lineTo(X(r.turn), c.height); g.stroke();
    g.fillStyle = '#4fbf7f'; g.font = '10px monospace';
    g.fillText(r.label + (r.rescued ? ' (rescued)' : ''), X(r.w[0]) + 3, 11);
  });

  // the amplitude lines that decided which turnarounds counted. These are the
  // clip-wide percentiles finding C5 is about: seeing apex drawn above real
  // reps is the whole argument, in one picture.
  if (ST.amp) {
    const gate = ST.amp.rest_p15 + 0.6 * ST.amp.amplitude;
    [[ST.amp.apex_p97, '#8a6bd1', 'apex p97'], [ST.amp.rest_p15, '#8a6bd1', 'rest p15'],
     [gate, '#55606f', 'turnaround gate  rest+0.6·amp']].forEach(([v, col, label]) => {
      g.strokeStyle = col; g.setLineDash([4, 3]); g.lineWidth = 1;
      g.beginPath(); g.moveTo(0, Y(v)); g.lineTo(c.width, Y(v)); g.stroke();
      g.setLineDash([]);
      g.fillStyle = col; g.font = '10px monospace';
      g.fillText(`${label} ${fmt(v)}`, 4, Y(v) - 3);
    });
  }

  // the signal itself
  g.strokeStyle = '#5aa9e6'; g.lineWidth = 1.4; g.beginPath();
  sig.forEach((v, i) => {
    const x = X((i / (sig.length - 1)) * dur);
    i ? g.lineTo(x, Y(v)) : g.moveTo(x, Y(v));
  });
  g.stroke();

  // rejections, at the second they happened
  ST.rejects.forEach((e) => {
    const t = seconds(e.data || {});
    if (t == null) return;
    g.strokeStyle = '#e0a33e'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(t), 12); g.lineTo(X(t), c.height); g.stroke();
    g.fillStyle = '#e0a33e'; g.font = '10px monospace';
    g.fillText('✗ ' + ((e.data || {}).what || e.message || ''), X(t) + 3, c.height - 3);
  });

  drawCursor();
}

function drawCursor() {
  const c = $('#chart');
  if (!c || !ST.dur) return;
  const g = c.getContext('2d'), t = $('#video').currentTime;
  g.strokeStyle = 'rgba(215,222,232,.75)'; g.lineWidth = 1;
  g.beginPath(); g.moveTo((t / ST.dur) * c.width, 0);
  g.lineTo((t / ST.dur) * c.width, c.height); g.stroke();
}

/* ----------------------------------------------------------------- reps --- */
async function renderRight(id) {
  const box = $('#right'); box.innerHTML = '';
  if (!ST.payload) {
    box.append(el('div', 'hint',
      'no payload stored beside this trace — run the clip here to get one'));
    return;
  }
  const p = ST.payload;
  const head = el('div', 'card');
  head.append(el('h3', null, 'result'));
  const b = el('div', 'body');
  [['exercise', p.exercise], ['detected', (p.detected || {}).label],
   ['confidence', (p.detected || {}).confidence], ['reps', p.n_reps],
   ['candidates', p.n_candidates], ['session', p.sessionScore + ' ' + p.sessionBand],
   ['countedBy', p.countedBy], ['failures', JSON.stringify(p.failures || {})]]
    .forEach(([k, v]) => {
      const line = el('div', 'kv'); line.append(el('b', null, k));
      line.append(document.createTextNode(' = ' + fmt(v))); b.append(line);
    });
  (p.blockers || []).forEach((x) => b.append(el('div', 'kv', '✗ ' + x)));
  head.append(b); box.append(head);

  const evidence = faultEvidence();
  (p.reps || []).forEach((rep, i) =>
    box.append(repCard(rep, evidence[i], p.track, evidence.length > 0)));

  const par = await j('/api/parity/' + id).catch(() => null);
  if (par && !par.error) box.append(parityCard(par));
}

/* The evidence the taxonomy read, per rep, straight out of the trace step the
 * fault layer now writes. */
function faultEvidence() {
  const out = [];
  ((ST.trace || {}).entries || []).forEach((e) => {
    if ((e.message || '').startsWith('failure classification')) out.push(e.data || {});
  });
  return out;
}

function repCard(rep, ev, track, traced) {
  const card = el('div', 'card rep');
  const hd = el('div', 'hd');
  hd.append(el('span', null, `${rep.label}  ${rep.startS}–${rep.endS}s`));
  hd.append(el('span', 'sc', rep.score == null ? '— unmeasured' : `${rep.score} ${rep.band}`));
  card.append(hd);

  const rows = ((ST.spec || {}).spec || {})[track] || [];
  const table = el('table', 'f');
  const fired = new Set(rep.failures || []);
  const values = (ev || {}).evidence || {};
  rows.forEach((r) => {
    const tr = el('tr');
    const v = values[r.key];
    const has = v !== null && v !== undefined && Number.isFinite(Number(v));
    // Without the evidence step there is nothing to be three-valued about, so
    // the panel says it has no evidence rather than inventing "absent".
    const state = fired.has(r.fault) ? 'fired' : !traced ? 'clear' : has ? 'clear' : 'unmeas';
    const td = el('td');
    td.append(el('span', 'st ' + state,
                 state === 'unmeas' ? 'UNMEASURED' : state.toUpperCase()));
    td.append(el('span', 'fn', ' ' + r.fault));
    tr.append(td);
    tr.append(el('td', null,
      has ? `${fmt(Number(v))} ${r.op} ${fmt(r.threshold)}`
          : !traced ? `${r.key} — not traced (older run)`
          : `${r.key} absent`));
    table.append(tr);
  });
  if (!rows.length) {
    card.append(el('div', 'hint',
      `classify_failures() has no rules for ${track}, so the server names no `
      + 'faults for this rep at all — while the two regex consumers below read '
      + 'the why-strings and name several. That gap is what the parity panel '
      + 'is measuring.'));
  }
  card.append(table);
  if (traced && rows.some((r) => { const v = values[r.key];
        return !(v !== null && v !== undefined && Number.isFinite(Number(v))); })) {
    card.append(el('div', 'hint',
      'UNMEASURED is not clean: faults_taxonomy._f() defaults an absent '
      + 'measurement to healthy, so these rows are indistinguishable from a '
      + 'passing rep in what the phone receives (feedback.md C2).'));
  }
  if ((ST.spec || {}).inherits_bar_rules && ST.spec.inherits_bar_rules.includes(track)) {
    card.append(el('div', 'hint',
      `${track} is classified by muscle_up()'s bar rules — measured about the `
      + 'hips, judged about the bar (feedback.md C1).'));
  }
  return card;
}

/* ------------------------------------------------------------- parity ----- */
function parityCard(par) {
  const card = el('div', 'card');
  card.append(el('h3', null,
    `fault parity · ${par.disagreements} of ${par.reps.length} reps disagree`));
  const t = el('table', 'f par');
  const head = el('tr');
  ['rep', 'server', 'harness (regex)', 'phone (regex)'].forEach((h) => head.append(el('td', null, h)));
  t.append(head);
  par.reps.forEach((r) => {
    const tr = el('tr', r.agree ? 'yes' : 'no');
    tr.append(el('td', null, r.label));
    [r.server, r.harness, r.phone].forEach((s) =>
      tr.append(el('td', r.agree ? 'yes' : 'no', s.length ? s.join(', ') : '—')));
    t.append(tr);
  });
  card.append(t);
  card.append(el('div', 'hint', par.note));
  return card;
}

/* --------------------------------------------------------------- diff ----- */
async function diff() {
  const rows = await refreshTraces($('#trace').value);
  const cur = $('#trace').value || (rows[0] || {}).traceId;
  const i = rows.findIndex((r) => r.traceId === cur);
  const prev = rows[i + 1];
  if (!prev) { status('no earlier trace to diff against', 'err'); return; }
  const d = await j(`/api/diff?a=${prev.traceId}&b=${cur}`);
  const box = $('#entries'); box.innerHTML = '';
  $('#entries-title').textContent = `diff · ${d.a} → ${d.b}`;
  const pre = el('pre', 'diff');
  (d.diff.length ? d.diff : ['(identical)']).forEach((l) => {
    const s = el('span', l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : null, l + '\n');
    pre.append(s);
  });
  box.append(pre);
}

boot();
