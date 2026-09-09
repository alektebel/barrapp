/* The page reads traces. It does not decide anything.
 *
 * Every number rendered here was produced by the pipeline and written into a
 * trace entry or a payload: the amplitude lines, the thresholds, the fault
 * states. Where a value is missing the page says UNMEASURED rather than
 * filling it in - the evidence layer now keeps that distinction (measured /
 * unmeasured / view-blocked) and reports it beside the faults, and the page
 * shows all three states rather than quietly drawing a pass. */
'use strict';

const $ = (s) => document.querySelector(s);
const el = (t, cls, txt) => { const n = document.createElement(t);
  if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };
const j = async (u, o) => {
  const r = await fetch(u, o); const data = await r.json();
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
};
const fmt = (v) => typeof v === 'number'
  ? (Number.isInteger(v) ? String(v) : v.toLocaleString('en-US', {maximumSignificantDigits: 4}))
  : Array.isArray(v) ? (v.length > 8 ? `[${v.length} values]` : `[${v.map(fmt).join(', ')}]`)
  : v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);

const ST = {
  trace: null, payload: null, kp: null, spec: null, stage: null,
  clip: null, fps: 30, signal: null, reps: [], rejects: [], amp: null, poll: null,
  walkTimer: null, walking: false,
};

/* ---------------------------------------------------------------- boot ---- */
async function boot() {
  loadModel();                      // not awaited: the page is usable without it
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
  const traces = await refreshTraces();
  $('#run').onclick = () => run().catch(showError);
  $('#upload').onchange = () => uploadClip().catch(showError);
  $('#clip').onchange = () => chooseClip().catch(showError);
  $('#export').onclick = exportBundle;
  $('#cancel').onclick = () => j(`/api/runs/${ST.runId}/cancel`, {method:'POST'}).catch(showError);
  $('#previous-frame').onclick = () => stepFrame(-1);
  $('#next-frame').onclick = () => stepFrame(1);
  $('#speed').onchange = () => { $('#video').playbackRate = Number($('#speed').value); };
  $('#skeleton').onchange = draw;
  $('#review').oninput = () => {
    try { localStorage.setItem(reviewKey(), $('#review').value); $('#review-status').textContent = 'Saved locally · included in export'; }
    catch (_) { $('#review-status').textContent = 'Local storage unavailable. Export to keep your note.'; }
  };
  $('#video').addEventListener('error', () => { $('#media-status').textContent = 'Video unavailable or unsupported by this browser. The trace can still be inspected.'; });
  document.addEventListener('keydown', e => {
    if (/INPUT|TEXTAREA|SELECT|BUTTON/.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); stepFrame(e.key === 'ArrowLeft' ? -1 : 1); }
    // [ ] walk the pipeline treatments; same as the step buttons.
    if (e.key === '[') { e.preventDefault(); stepStage(-1); }
    if (e.key === ']') { e.preventDefault(); stepStage(1); }
  });
  const video = $('#video');
  if (video.requestVideoFrameCallback) {
    const tick = () => { draw(); video.requestVideoFrameCallback(tick); };
    video.requestVideoFrameCallback(tick);
  }
  $('#trace').onchange = () => loadTrace($('#trace').value).catch(showError);
  $('#diff').onclick = () => diff().catch(showError);
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
  // Open on the newest trace that has a payload, so the page does not arrive
  // blank: a debugger that starts on nothing asks you to first know which run
  // was wrong, which is precisely the thing you were using it to find out.
  const newest = traces.find((r) => r.traceId === $('#trace').value)
    || traces.find((r) => r.hasPayload)
    || traces[traces.length - 1];
  const linkedTrace = new URLSearchParams(location.search).get('trace');
  const linkedClip = new URLSearchParams(location.search).get('clip');
  if (linkedTrace) await loadTrace(linkedTrace);
  else if (linkedClip) { $('#clip').value = linkedClip; await chooseClip(); }
  else if (newest) { $('#trace').value = newest.traceId; await loadTrace(newest.traceId); }
  else if (c.clips.length) await chooseClip();
}

async function refreshTraces(select) {
  const t = await j('/api/traces');
  const sel = $('#trace');
  sel.innerHTML = '';
  sel.append(Object.assign(el('option', null, `traces (${t.traces.length})`), { value: '' }));
  ST.traces = t.traces;
  t.traces.forEach((r) => {
    const marks = (r.rejections ? ` ✗${r.rejections}` : '') + (r.errors ? ` !${r.errors}` : '');
    const o = el('option', null, `${r.traceId}  ${r.subject}${marks}`);
    o.value = r.traceId; sel.append(o);
  });
  if (select) sel.value = select;
  return t.traces;
}

/* ----------------------------------------------------------------- run ---- */
function status(text, cls) { const s = $('#status'); s.textContent = text; s.className = 'status ' + (cls || ''); }
function showError(e) { status(e.message || String(e), 'err'); $('#run').disabled = false; }

async function run() {
  $('#run').disabled = true;
  status('starting…', 'run');
  const body = { clip: $('#clip').value, exercise: $('#exercise').value,
                 fresh: $('#fresh').checked, backend: $('#backend').value };
  const r = await j('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify(body) });
  if (!r.runId) { status(r.error || 'could not start', 'err'); $('#run').disabled = false; return; }
  ST.runId = r.runId; $('#cancel').disabled = false;
  clearInterval(ST.poll);
  ST.poll = setTimeout(() => pollRun(r.runId).catch(showError), 400);
}

async function pollRun(id) {
  const s = await j('/api/runs/' + id);
  $('#run-log').textContent = (s.log || []).join('\n') || `${s.stage} · ${s.elapsed}s`;
  if (s.state === 'running') { status(`${s.stage}  ${s.elapsed}s`, 'run'); ST.poll = setTimeout(() => pollRun(id).catch(showError), 600); return; }
  clearInterval(ST.poll);
  $('#cancel').disabled = true;
  if (s.state === 'cancelled') { $('#run').disabled = false; status('Run stopped · previous results retained', 'ok'); return; }
  if (s.state === 'failed') {
    status(s.error || 'failed', 'err');
    $('#entries').innerHTML = '';
    $('#entries').append(el('div', 'kv', s.error || ''));
    (s.log || []).forEach((l) => $('#entries').append(el('div', 'kv', l)));
    if (s.traceId) { await refreshTraces(s.traceId); await loadTrace(s.traceId); }
    $('#run').disabled = false;
    return;
  }
  status(`${s.exercise} · ${s.reps} reps · ${s.rejections} rejections`
         + (s.poseSource === 'cache' ? ' · cached pose' : ` · ${s.poseSource}`), 'ok');
  await refreshTraces(s.traceId);
  await loadTrace(s.traceId);
  $('#run').disabled = false;
}

/* --------------------------------------------------------------- trace ---- */
async function loadTrace(id) {
  if (!id) return;
  stopWalk();
  const ticket = ST.loading = (ST.loading || 0) + 1;
  const [trace, payload] = await Promise.all([j('/api/traces/' + id), j(`/api/traces/${id}/payload`).catch(() => null)]);
  if (ticket !== ST.loading) return;
  ST.trace = trace;
  ST.payload = payload;
  if (ST.payload && ST.payload.error) ST.payload = null;
  ST.clip = ST.trace.subject || (ST.trace.context || {}).clip || '';
  const stem = ST.clip.replace(/\.[^.]+$/, '');
  const ex = (ST.payload && ST.payload.exercise) || 'auto';
  $('#clip-kicker').textContent = `${ST.trace.traceId || id}  ·  ${ex}`;
  $('#clip-name').textContent = ST.clip;
  renderChips();
  $('#clip').value = ST.clip;
  if (![...$('#trace').options].some(o => o.value === id)) { const o = el('option', null, id); o.value = id; $('#trace').append(o); }
  $('#trace').value = id;
  history.replaceState(null, '', '?trace=' + encodeURIComponent(id));
  $('#media-status').textContent = '';
  ST.selection = null;
  $('#video').src = '/api/video/' + encodeURIComponent(ST.clip);
  const kp = await j(`/api/traces/${id}/keypoints`).catch(() => null);
  if (ticket !== ST.loading) return;
  ST.kp = kp;
  if (ST.kp && ST.kp.error) ST.kp = null;
  readSignal();
  renderNavigation();
  refreshBaseline();
  restoreReview();
  $('#media-status').textContent = ST.kp ? (ST.kp.source === 'run' ? 'Overlay: exact keypoints saved with this run.' : 'Overlay: current clip cache; this older run has no saved pose snapshot.') : 'No cached pose available · video can be reviewed without the overlay.';
  renderRail();
  selectStage(defaultStage());
  await renderRight(id);
  drawChart();
}

/* Pull the chart's raw material out of the trace. Nothing is recomputed: the
 * signal, the amplitude lines and the rep windows are all entries the
 * segmenter wrote as it decided. */
function readSignal() {
  ST.signal = null; ST.amp = null; ST.cands = null; ST.reps = []; ST.rejects = []; ST.dur = 0; ST.fps = ST.payload?.fps || 30;
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

/* The clip head's mono pills: what this trace decided, at a glance. Values
 * come straight out of the payload — the page never computes a number. */
function renderChips() {
  const box = $('#clip-chips'); box.innerHTML = '';
  const p = ST.payload;
  if (!p) {
    box.append(chip('no payload', 'neu', ''));
    return;
  }
  const det = p.detected || {};
  const d = p.duration_s;
  const chips = [
    ['exercise', p.exercise, 'ok'],
    ['reps', p.n_reps, p.n_reps ? 'ok' : 'warn'],
    ['score', p.sessionScore == null ? 'unmeasured' : p.sessionScore, 'warn'],
    ['band', p.sessionBand, 'neu'],
    ['confidence', det.confidence != null ? Math.round(det.confidence * 100) + '%' : '—', 'neu'],
    ['duration', d != null ? d.toFixed(1) + 's' : '—', 'neu'],
  ];
  chips.forEach(([k, v, cls]) => box.append(chip(k, v, cls)));
}

function chip(k, v, cls) {
  const c = el('span', 'chip' + (cls ? ' ' + cls : ''));
  c.append(el('b', null, k + ' '));
  c.append(document.createTextNode(String(v)));
  return c;
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
const ORDER = ['job', 'probe', 'pose', 'classify', 'model', 'fusion', 'signal',
               'segment', 'rescue', 'metrics', 'quality', 'faults', 'vision', 'result'];

/* One Lucide-ish glyph per pipeline stage, so the rail reads as a strip of
 * nodes rather than a list. Fallback is a blank circle for stages a clip can
 * reach that the rail has no glyph for. */
const STAGE_ICON = {
  job: 'M4 6h16M4 12h16M4 18h10', probe: 'M9 3v6l4 8M9 3H5M15 3h5',
  pose: 'M12 3c4.97 0 9 3.58 9 8s-4.03 8-9 8a10 10 0 0 1-2.6-.34L5 21l1.2-3.6A7.6 7.6 0 0 1 3 11c0-4.42 4.03-8 9-8Z',
  classify: 'M3 6l3 3 4-5M9 6l3 3 4-5', signal: 'M4 14l3-4 3 6 3-8 3 4 4-2',
  model: 'M8 4h8M8 20h8M4 8v8M20 8v8M9 9h6v6H9z',
  fusion: 'M5 7h5a7 7 0 0 1 0 10H5M14 12h5M14 7h5M14 17h5',
  segment: 'M4 12h6l2-6 3 12 2-6h4',
  rescue: 'M12 3l2.5 5 5.5.8-4 3.9.9 5.5L12 16.5 7.1 18.2 8 12.7 4 8.8 9.5 8Z',
  metrics: 'M4 20V10M10 20V4M16 20v-6M22 20H2', quality: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01Z',
  faults: 'M12 8v5M12 17h.01M10.3 3.9h3.4L21 19.1H3L10.3 3.9Z',
  vision: 'M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  result: 'M5 4v16M11 4l8 8-8 8',
};
const STAGE_ICON_DEFAULT = 'M12 6a1 1 0 1 0 0 2M12 6a1 1 0 0 1 0-2M12 16a1 1 0 1 0 0 2M12 16a1 1 0 0 1 0 2';

function iconSvg(name) {
  const d = STAGE_ICON[name] || STAGE_ICON_DEFAULT;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '15'); svg.setAttribute('height', '15');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  svg.append(p);
  return svg;
}

function iconEl(d, size = 14) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size)); svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2.75');
  svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  svg.append(p);
  return svg;
}

/* Stages this trace actually produced, in pipeline order — the walk targets
 * these, not the full ORDER, so you never step into a treatment that never ran. */
function stageList() {
  const seen = new Set(((ST.trace || {}).entries || []).map((e) => e.stage));
  return [...ORDER.filter((s) => seen.has(s)),
          ...[...seen].filter((s) => !ORDER.includes(s))];
}

function stopWalk() {
  if (ST.walkTimer) clearInterval(ST.walkTimer);
  ST.walkTimer = null;
  ST.walking = false;
}

function stepStage(dir) {
  const stages = stageList();
  if (!stages.length) return;
  const i = Math.max(0, stages.indexOf(ST.stage));
  let n = i + dir;
  if (n >= stages.length) n = 0;
  if (n < 0) n = stages.length - 1;
  selectStage(stages[n]);
  // Evidence is below the fold on a tall clip — bring it into view so a step
  // actually shows the treatment you just landed on.
  $('#entries')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function toggleWalk() {
  if (ST.walking) { stopWalk(); renderRail(); return; }
  ST.walking = true;
  renderRail();
  ST.walkTimer = setInterval(() => {
    const stages = stageList();
    if (!stages.length) { stopWalk(); renderRail(); return; }
    const i = stages.indexOf(ST.stage);
    if (i >= stages.length - 1) { stopWalk(); renderRail(); return; }
    stepStage(1);
  }, 1600);
}

function renderWalkBar(stages) {
  const bar = el('div', 'walk-bar');
  const prev = el('button', 'btn btn-secondary walk-prev', null);
  prev.title = 'Previous treatment ([)';
  prev.append(iconEl('M15 18l-6-6 6-6', 15));
  prev.disabled = !stages.length;
  prev.onclick = () => { stopWalk(); stepStage(-1); };

  const next = el('button', 'btn btn-primary walk-next');
  next.append(iconEl('M5 4v16M11 4l8 8-8 8', 14));
  next.append(document.createTextNode('step into next stage'));
  next.disabled = !stages.length;
  next.onclick = () => { stopWalk(); stepStage(1); };

  const auto = el('button', 'btn btn-secondary walk-auto',
    ST.walking ? '⏸ walking' : '↻ walk it');
  auto.disabled = stages.length < 2;
  auto.onclick = toggleWalk;

  const i = stages.indexOf(ST.stage);
  const pos = el('div', 'walk-pos',
    !stages.length ? 'no treatments in this trace'
    : i < 0 ? `${stages.length} treatments · pick one`
    : `${ST.stage} · ${i + 1} of ${stages.length}`);

  bar.append(prev, next, auto, el('span', 'spacer'), pos);
  return bar;
}

function renderRail() {
  const rail = $('#rail'); rail.innerHTML = '';
  const byStage = new Map();
  const lastMs = new Map();
  ((ST.trace || {}).entries || []).forEach((e) => {
    const c = byStage.get(e.stage) || { step: 0, decision: 0, reject: 0, note: 0, error: 0 };
    c[e.kind] = (c[e.kind] || 0) + 1; byStage.set(e.stage, c);
    if (typeof e.atMs === 'number') lastMs.set(e.stage, e.atMs);
  });
  const stages = stageList();
  rail.append(renderWalkBar(stages));

  const group = el('div', 'stage-group');
  stages.forEach((s) => {
    const c = byStage.get(s) || {};
    const row = el('button', 'stage' + (s === ST.stage ? ' on' : ''));
    const icon = el('span', 'icon'); icon.append(iconSvg(s)); row.append(icon);

    const mid = el('div', 'mid');
    mid.append(el('div', 'name', s));
    mid.append(el('div', 'ms', lastMs.get(s) != null ? `${lastMs.get(s)}ms` : '—'));
    row.append(mid);

    let cls = 'neu', txt = String(c.step || c.decision || 0);
    if (c.error) { cls = 'bad'; txt = `!${c.error}`; }
    else if (c.reject) { cls = 'warn'; txt = `✗${c.reject}`; }
    else if (c.decision) { cls = 'ok'; txt = `→${c.decision}`; }
    row.append(el('span', 'tag ' + cls, txt));

    row.onclick = () => { stopWalk(); selectStage(s); };
    group.append(row);
  });
  rail.append(group);
}

/* -------------------------------------------------- the model, in place ---
 * A rejection is only checkable next to the constant it was compared against,
 * and until now that constant lived in a module nobody has open. The model
 * card (/api/model) is read once per page and the slice governing the selected
 * stage is shown above that stage's evidence — so "why 0.15" is answered where
 * the question is asked, with the source line that defines the number.
 *
 * The trace's stage names and the card's stage keys are different vocabularies
 * (the trace records where the code was; the card records what is decided), so
 * the map is written out rather than guessed by name. */
const STAGE_MODEL = {
  job: 'payload', probe: 'probe', pose: 'pose', classify: 'classify',
  model: 'model', fusion: 'fusion', signal: 'signal', segment: 'segment',
  rescue: 'segment', metrics: 'metrics',
  quality: 'score', faults: 'faults', vision: 'vision', result: 'payload',
};
let MODEL = null;

async function loadModel() {
  try { MODEL = await j('/api/model'); } catch { MODEL = null; }
}

function constValue(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(+v.toFixed(4));
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') {
    return Object.entries(v).map(([k, x]) => `${k} ${constValue(x)}`).join('  ');
  }
  return String(v);
}

function modelPanel(stage) {
  if (!MODEL) return null;
  const spec = MODEL.pipeline.find((p) => p.key === STAGE_MODEL[stage]);
  if (!spec) return null;
  const box = el('details', 'panel model-panel');
  box.append(el('summary', null, `what ${spec.name.toLowerCase()} decides · ${spec.constants.length} constants`));

  const facts = el('div', 'model-facts');
  const fact = (k, v, cls) => {
    const row = el('div', 'model-fact' + (cls ? ' ' + cls : ''));
    row.append(el('span', 'kicker', k), el('span', 'v', v));
    facts.append(row);
  };
  fact('module', `${spec.module} · ${spec.fn}()`, 'mono');
  fact('decides', spec.decides);
  fact('how it fails', spec.fails, 'fails');
  fact('look at first', spec.look, 'look');
  box.append(facts);

  if (spec.constants.length) {
    const table = el('table', 'model-consts');
    for (const c of spec.constants) {
      const tr = el('tr');
      tr.append(el('td', 'k', c.name), el('td', 'v', constValue(c.value)),
                el('td', 'n', c.note || ''));
      table.append(tr);
    }
    box.append(table);
    box.append(el('div', 'hint', 'read out of ' +
      [...new Set(spec.constants.map((c) => c.source))].join(', ') +
      ' when this page loaded · full card at /models'));
  }
  return box;
}

/* ------------------------------------------------------------- entries ---- */
function selectStage(s) {
  ST.stage = s; renderRail();
  const box = $('#entries'); box.innerHTML = '';
  const stages = stageList();
  const i = stages.indexOf(s);
  $('#entries-title').textContent = i < 0
    ? `evidence · ${s || '—'}`
    : `evidence · ${s} · treatment ${i + 1} of ${stages.length}`;
  const model = modelPanel(s);
  if (model) box.append(model);
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
  $('#playhead').textContent = `${v.currentTime.toFixed(3)}s · frame ${Math.floor(v.currentTime * ST.fps)}`;
  if ($('#loop').checked && ST.selection && !v.paused && v.currentTime >= ST.selection[1]) v.currentTime = ST.selection[0];
  drawChart();
  if (!$('#skeleton').checked || !ST.kp || !v.videoWidth) return;
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
    g.strokeStyle = weak ? 'rgba(198,113,57,.5)' : 'rgba(122,138,94,.9)';
    g.beginPath(); g.moveTo(X(pa), Y(pa)); g.lineTo(X(pb), Y(pb)); g.stroke();
  });
  ST.kp.analysis.forEach((k) => {
    const p = pts[k]; if (!p) return;
    g.beginPath(); g.arc(X(p), Y(p), 3.2, 0, 7);
    if (p[2] < MIN_CONF) { g.strokeStyle = '#c67139'; g.stroke(); }
    else { g.fillStyle = '#f9f4ed'; g.fill(); }
  });
  g.fillStyle = 'rgba(72,66,56,.92)'; g.font = '11px monospace';
  g.fillText(`frame ${i}/${ST.kp.frames}  t=${v.currentTime.toFixed(2)}s`, 8, 14);
}

/* ---------------------------------------------------------------- chart --- */
function drawChart() {
  const c = $('#chart'), g = c.getContext('2d');
  c.width = c.clientWidth; c.height = 150;
  g.clearRect(0, 0, c.width, c.height);
  if (!ST.signal || !ST.signal.length) {
    g.fillStyle = '#82796a'; g.font = '12px monospace';
    g.fillText('no tracking signal in this trace', 10, 24);
    return;
  }
  const sig = ST.signal, dur = ST.dur || sig.length / ST.fps;
  const valid = sig.filter(Number.isFinite);
  if (!valid.length) return;
  const lo = valid.reduce((a,b) => Math.min(a,b)), hi = valid.reduce((a,b) => Math.max(a,b));
  const pad = (hi - lo) * 0.12 || 1;
  const Y = (v) => c.height - 14 - ((v - lo + pad) / (hi - lo + 2 * pad)) * (c.height - 22);
  const X = (t) => (t / dur) * c.width;

  // accepted reps, from the segmenter's own decisions
  ST.reps.forEach((r) => {
    g.fillStyle = 'rgba(122,138,94,.18)';
    g.fillRect(X(r.w[0]), 0, X(r.w[1]) - X(r.w[0]), c.height);
    g.strokeStyle = 'rgba(122,138,94,.5)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(r.turn), 0); g.lineTo(X(r.turn), c.height); g.stroke();
    g.fillStyle = '#7a8a5e'; g.font = '10px monospace';
    g.fillText(r.label + (r.rescued ? ' (rescued)' : ''), X(r.w[0]) + 3, 11);
  });

  // the amplitude lines that decided which turnarounds counted. These are the
  // clip-wide percentiles finding C5 is about: seeing apex drawn above real
  // reps is the whole argument, in one picture.
  if (ST.amp) {
    [[ST.amp.apex_p97, '#8a6bd1', 'clip apex p97'], [ST.amp.rest_p15, '#8a6bd1', 'clip rest p15']].forEach(([v, col, label]) => {
      if (!Number.isFinite(v)) return;
      g.strokeStyle = col; g.setLineDash([4, 3]); g.lineWidth = 1;
      g.beginPath(); g.moveTo(0, Y(v)); g.lineTo(c.width, Y(v)); g.stroke();
      g.setLineDash([]); g.fillStyle = col; g.font = '10px monospace';
      g.fillText(`${label} ${fmt(v)}`, 4, Y(v) - 3);
    });
  }

  // the signal itself
  g.strokeStyle = '#c08a55'; g.lineWidth = 1.4; g.beginPath();
  let connected = false;
  sig.forEach((v, i) => {
    if (!Number.isFinite(v)) { connected = false; return; }
    const x = X((i / (sig.length - 1)) * dur);
    connected ? g.lineTo(x, Y(v)) : g.moveTo(x, Y(v)); connected = true;
  });
  g.stroke();

  // rejections, at the second they happened
  ST.rejects.forEach((e) => {
    const t = seconds(e.data || {});
    if (t == null) return;
    g.strokeStyle = '#c67139'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(t), 12); g.lineTo(X(t), c.height); g.stroke();
    g.fillStyle = '#c67139'; g.font = '10px monospace';
    g.fillText('✗ ' + ((e.data || {}).what || e.message || ''), X(t) + 3, c.height - 3);
  });

  drawCursor();
}

function drawCursor() {
  const c = $('#chart');
  if (!c || !ST.dur) return;
  const g = c.getContext('2d'), t = $('#video').currentTime;
  g.strokeStyle = 'rgba(114,104,90,.6)'; g.lineWidth = 1;
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
  head.append(el('div', 'card-kicker', 'result'));
  head.append(el('h3', null, `${p.exercise || 'unmeasured'} · ${p.n_reps ?? '—'} rep${p.n_reps === 1 ? '' : 's'}`));
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
    box.append(Array.isArray(rep.assessments) ? assessmentCard(rep) : repCard(rep, evidence[i], p.track, evidence.length > 0)));

  const par = await j('/api/parity/' + id).catch(() => null);
  if (par && !par.error && ST.trace?.traceId === id) box.append(parityCard(par));
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
  const shipped = Array.isArray(rep.faults) ? rep.faults.map((f) => f.name) : [];
  const fired = new Set(shipped.length ? shipped : (rep.failures || []));
  const values = (ev || {}).evidence || {};
  rows.forEach((r) => {
    const tr = el('tr');
    const v = values[r.key];
    const has = v !== null && v !== undefined && Number.isFinite(Number(v));
    // The trace step writes view_blocked; the payload row writes viewBlocked.
    const blocked = (((ev || {}).view_blocked) || ((ev || {}).viewBlocked) || [])
      .includes(r.key);
    // Fired comes from the server's own array. A row that did not fire and has
    // no measured value is UNMEASURED, never CLEAR - a fault whose evidence is
    // missing did not fire, and did not pass either.
    const state = fired.has(r.fault) ? 'fired'
      : blocked ? 'unmeas' : !traced ? 'unmeas' : has ? 'clear' : 'unmeas';
    const td = el('td');
    td.append(el('span', 'st ' + state,
                 state === 'unmeas' ? 'UNMEASURED' : state.toUpperCase()));
    td.append(el('span', 'fn', ' ' + r.fault));
    tr.append(td);
    tr.append(el('td', null,
      has ? `${fmt(Number(v))} ${r.op} ${fmt(r.threshold)}${r.plane ? '  ·' + r.plane : ''}`
          : !traced ? `${r.key} — not traced (older run)`
          : blocked ? `${r.key} — view-blocked (${r.plane})`
          : `${r.key} absent`));
    table.append(tr);
  });
  if (!rows.length) {
    card.append(el('div', 'hint',
      `classify_failures() has no rules for ${track}, so no fault was named `
      + 'for this rep at all.'));
  }
  card.append(table);
  if (traced && rows.some((r) => { const v = values[r.key];
        return !(v !== null && v !== undefined && Number.isFinite(Number(v))); })) {
    card.append(el('div', 'hint',
      'UNMEASURED is not clean: the evidence layer records what this rep '
      + 'could not produce (or what the camera angle cannot support) beside '
      + 'the faults, rather than folding it into them.'));
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
  ['rep', 'server (taxonomy)', 'harness (barra/faults)', 'phone (Cues.kt port)']
    .forEach((h) => head.append(el('td', null, h)));
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
  const rows = ST.traces || [];
  const cur = $('#trace').value;
  const prev = rows.find(r => r.traceId === $('#baseline').value && r.subject === ST.clip);
  if (!prev) { status('no earlier trace to diff against', 'err'); return; }
  const [d, baselinePayload] = await Promise.all([
    j(`/api/diff?a=${prev.traceId}&b=${cur}`),
    j(`/api/traces/${prev.traceId}/payload`).catch(() => null)
  ]);
  const box = $('#entries'); box.innerHTML = '';
  $('#entries-title').textContent = `diff · ${d.a} → ${d.b}`;
  if (baselinePayload && ST.payload) {
    const table = el('table', 'f');
    const header = el('tr'); ['Result', 'Baseline', 'Selected run'].forEach(x => header.append(el('th', null, x))); table.append(header);
    for (const key of ['exercise', 'n_reps', 'n_candidates', 'sessionScore', 'failures']) {
      const row = el('tr'); [key, fmt(baselinePayload[key] ?? null), fmt(ST.payload[key] ?? null)].forEach(x => row.append(el('td', null, x))); table.append(row);
    }
    box.append(table);
  }
  const pre = el('pre', 'diff');
  (d.diff.length ? d.diff : ['(identical)']).forEach((l) => {
    const s = el('span', l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : null, l + '\n');
    pre.append(s);
  });
  box.append(pre);
}

boot().catch(showError);

function action(text, fn, cls = 'btn btn-secondary') {
  const b = el('button', cls, text); b.type = 'button'; b.onclick = fn; return b;
}
function seekWindow(window) {
  if (!Array.isArray(window) || window.length !== 2 || !window.every(Number.isFinite)) return;
  ST.selection = window; $('#video').pause(); $('#video').currentTime = window[0];
  $('#media-status').textContent = `Selected ${window[0].toFixed(2)}–${window[1].toFixed(2)}s · enable Loop selection and play to repeat.`;
}
function stepFrame(delta) {
  const v = $('#video'); v.pause();
  v.currentTime = Math.max(0, Math.min(v.duration || Infinity, (Math.round(v.currentTime * ST.fps) + delta) / ST.fps));
}
function renderNavigation() {
  const nav = $('#rep-nav'); nav.replaceChildren();
  for (const rep of ST.payload?.reps || []) {
    nav.append(action(`${rep.label} · ${rep.startS.toFixed(1)}s`, () => {
      seekWindow([rep.startS, rep.endS]);
      document.getElementById('rep-' + rep.label)?.scrollIntoView({block:'nearest', behavior:'smooth'});
    }));
  }
  if (!nav.children.length) nav.append(el('span', 'hint', 'No accepted reps. Inspect segmentation rejections and record missed intervals below.'));
}
function assessmentCard(rep) {
  const card = el('section', 'card rep'); card.id = 'rep-' + rep.label;
  card.append(el('h3', null, `${rep.label} · ${rep.startS}–${rep.endS}s`));
  card.append(el('div', 'hint', rep.score == null ? 'Score unmeasured' : `Score ${rep.score} · ${rep.band || ''}`));
  const phases = el('div', 'controls phases');
  phases.append(action('Whole rep', () => seekWindow([rep.startS, rep.endS])));
  Object.entries(rep.phases || {}).forEach(([name, window]) => {
    if (Array.isArray(window)) phases.append(action(name, () => seekWindow(window)));
  });
  card.append(phases);
  if (!rep.assessments.length) card.append(el('p', 'hint', 'No error assessments were produced for this rep.'));
  for (const a of rep.assessments) {
    const row = el('div', 'assessment ' + a.status);
    row.append(el('strong', null, a.name || a.errorId));
    row.append(el('span', 'st ' + (a.status === 'observed' ? 'fired' : a.status === 'not_observed' ? 'clear' : 'unmeas'), a.status.replaceAll('_', ' ').toUpperCase()));
    row.append(el('div', 'hint', `${a.errorId} · ${a.phase} · ${a.source || 'pipeline'}`));
    const e = a.evidence || {};
    row.append(el('div', 'measurement', e.value == null ? 'No usable measurement' : `${e.primitive}: ${fmt(e.value)} ${e.unit || ''} ${e.comparison || ''} ${fmt(e.threshold)} (threshold)`));
    const availability = a.availability || {};
    if (availability.reason || availability.detail) row.append(el('div', 'hint', [availability.reason, availability.detail].filter(Boolean).join(' · ')));
    if (a.variantDependent) row.append(el('div', 'hint', 'Depends on the intended technique variant.'));
    const window = a.intervalS || rep.phases?.[a.phase];
    if (Array.isArray(window)) row.append(action('Inspect evidence phase', () => seekWindow(window)));
    const details = el('details'); details.append(el('summary', null, 'Raw assessment'));
    details.append(el('pre', null, JSON.stringify(a, null, 2))); row.append(details); card.append(row);
  }
  return card;
}
function refreshBaseline() {
  const select = $('#baseline'); select.replaceChildren(el('option', null, 'Choose baseline (same video)'));
  select.firstChild.value = '';
  const rows = (ST.traces || []).filter(r => r.subject === ST.clip && r.traceId !== ST.trace?.traceId);
  rows.forEach(r => { const o = el('option', null, r.traceId); o.value = r.traceId; select.append(o); });
  if (rows.length) select.value = rows[0].traceId;
  $('#diff').disabled = !rows.length;
}
function reviewKey() { return 'barrapp-review:' + (ST.trace?.traceId || ST.clip); }
function restoreReview() {
  try { $('#review').value = localStorage.getItem(reviewKey()) || ''; } catch (_) { $('#review').value = ''; }
  $('#review-status').textContent = '';
}
function exportBundle() {
  const bundle = {version: 1, exportedAt: new Date().toISOString(), clip: ST.clip,
    trace: ST.trace, payload: ST.payload, review: $('#review').value,
    selectedWindowS: ST.selection || null, playheadS: $('#video').currentTime,
    overlaySource: ST.kp?.source || 'unavailable'};
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], {type: 'application/json'}));
  const a = el('a'); a.href = url; a.download = (ST.trace?.traceId || 'video') + '-debug.json'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function chooseClip() {
  const clip = $('#clip').value;
  const rows = await refreshTraces();
  const latest = rows.find(r => r.subject === clip && r.hasPayload);
  if (latest) { await loadTrace(latest.traceId); return; }
  ST.loading = (ST.loading || 0) + 1;
  stopWalk();
  history.replaceState(null, '', location.pathname);
  ST.clip = clip; ST.trace = null; ST.payload = null; ST.kp = null; ST.selection = null; ST.stage = null;
  $('#video').src = '/api/video/' + encodeURIComponent(clip);
  $('#clip-name').textContent = clip; $('#clip-kicker').textContent = 'Ready to analyze';
  $('#media-status').textContent = 'No run yet. Choose the movement or leave Auto, then Run.';
  $('#entries').replaceChildren(); $('#right').replaceChildren();
  renderRail();
  readSignal(); renderChips(); renderNavigation(); refreshBaseline(); restoreReview(); drawChart();
}
async function uploadClip() {
  const f = $('#upload').files[0]; if (!f) return;
  if (f.size > 512 * 1024 * 1024) throw new Error('Choose a video up to 512 MiB.');
  status('Importing video…', 'run'); $('#run').disabled = true;
  const result = await j('/api/clips?name=' + encodeURIComponent(f.name), {method: 'POST', body: f});
  const c = await j('/api/clips'); $('#clip').replaceChildren();
  c.clips.forEach(f => { const o = el('option', null, f.name + (f.cached ? ' ·cached' : '')); o.value = f.name; $('#clip').append(o); });
  $('#clip').value = result.name; $('#upload').value = ''; await chooseClip();
  $('#run').disabled = false; status('Video imported · ready to run', 'ok');
}
