'use strict';
/* The shelf. One card per row in the library, and the library is keyed on
   content — so "don't show the same video twice" is not a filter here, it is
   the shape of the data this page receives. What this page does add is the
   provenance: a card whose bytes exist at more than one path says so. */

const $ = (s) => document.querySelector(s);
const el = (t, cls, txt) => { const n = document.createElement(t);
  if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };

let clips = [];

async function api(url, options) {
  const r = await fetch(url, options);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(data.error || `HTTP ${r.status}`);
  return data;
}

const attention = (c) => Boolean(
  c.trace?.errors || c.summary?.blockers.length ||
  Object.values(c.summary?.failures || {}).some((n) => n > 0));

const secs = (v) => Number.isFinite(v) ? `${v.toFixed(1)}s` : null;

function statusOf(c) {
  if (c.trace?.errors) return ['attention', 'Run failed'];
  if (!c.trace) return ['', 'Never analysed'];
  if (!c.summary) return ['attention', 'No result'];
  return attention(c) ? ['attention', 'Needs inspection'] : ['clean', 'Analysed'];
}

function stats() {
  const analysed = clips.filter((c) => c.summary).length;
  const copies = clips.reduce((n, c) => n + c.extraCopies, 0);
  const runs = clips.reduce((n, c) => n + c.runs, 0);
  const rows = [
    ['Distinct videos', clips.length, true],
    ['Analysed', analysed],
    ['Pipeline runs', runs],
    ['Duplicate files collapsed', copies],
  ];
  $('#stats').replaceChildren(...rows.map(([k, v, lead]) => {
    const n = el('div', 'stat' + (lead ? ' lead' : ''));
    n.append(el('b', null, String(v)), el('span', null, k));
    return n;
  }));
}

/* The chips are rebuilt rather than re-rendered: saving a tag must not
   destroy the form that reports the save. */
function fillChips(node, c) {
  node.replaceChildren();
  if (c.extraCopies) node.append(el('span', 'tag tag-accent-2', `${c.extraCopies + 1} files, one video`));
  if (c.cached) node.append(el('span', 'tag tag-outline', 'pose cached'));
  for (const t of (c.tags || '').split(',').map((s) => s.trim()).filter(Boolean)) {
    node.append(el('span', 'tag', t));
  }
}

function meta(c, refresh) {
  const box = el('details', 'meta');
  box.append(el('summary', null, 'Details, notes and files'));
  const form = el('form');
  const field = (name, label, value, tag = 'input') => {
    const wrap = el('label');
    wrap.append(el('span', 'kicker', label));
    const input = el(tag);
    if (tag === 'textarea') input.rows = 2; else input.type = 'text';
    input.name = name; input.value = value || '';
    wrap.append(input);
    return wrap;
  };
  const row = el('div', 'row');
  row.append(field('title', 'Title', c.title),
             field('movement', 'Declared movement', c.movement));
  form.append(row, field('tags', 'Tags', c.tags),
              field('notes', 'Notes', c.notes, 'textarea'));

  const facts = el('ul', 'paths');
  const line = (t) => facts.append(el('li', null, t));
  line(`library id ${c.id} · sha256 ${c.sha256.slice(0, 16)}…`);
  line(`${(c.bytes / 1048576).toFixed(1)} MiB` +
       (c.frames ? ` · ${c.frames} frames @ ${c.fps?.toFixed(2)} fps · ${c.width}×${c.height}` : '') +
       (c.probeNote ? ` · could not probe: ${c.probeNote}` : ''));
  for (const p of c.copies) line(p === c.path ? `${p}  ← served from here` : p);
  if (c.extraCopies) {
    line(`${c.extraCopies} extra file${c.extraCopies > 1 ? 's' : ''} hold identical bytes; ` +
         'they share this one card and this one history.');
  }
  form.append(facts);

  const actions = el('div', 'actions');
  const save = el('button', 'btn btn-secondary', 'Save details');
  save.type = 'submit';
  const said = el('span', 'saved');
  actions.append(save, said);
  form.append(actions);

  form.onsubmit = async (e) => {
    e.preventDefault();
    save.disabled = true; said.textContent = 'Saving…';
    try {
      const body = Object.fromEntries(new FormData(form).entries());
      const updated = await api(`/api/videos/${encodeURIComponent(c.id)}`,
        { method: 'POST', body: JSON.stringify(body) });
      Object.assign(c, { title: updated.title, movement: updated.movement,
                         tags: updated.tags, notes: updated.notes });
      said.textContent = 'Saved.';
      refresh();
    } catch (err) { said.textContent = err.message; }
    finally { save.disabled = false; }
  };
  box.append(form);
  return box;
}

/* Only the movement NAME is title-cased — `text-transform: capitalize` on the
   whole line turned "open to run the pipeline on it" into a headline. */
const human = (name) => name ? name.replaceAll('_', ' ').replace(/^./, (m) => m.toUpperCase()) : '';

function movementLine(c) {
  if (c.summary) return `${human(c.summary.exercise || 'unknown')} · ${c.summary.reps ?? '—'} reps`;
  return c.movement ? `${human(c.movement)} · declared, not yet measured`
                    : 'Open to run the pipeline on it';
}

function card(c) {
  const wrap = el('article', 'video-card');
  const link = el('a', 'open');
  link.href = c.trace ? `/inspect?trace=${encodeURIComponent(c.trace.traceId)}`
                      : `/inspect?clip=${encodeURIComponent(c.name)}`;

  const preview = el('div', 'preview');
  const spine = el('div', 'spine');
  for (let i = 0; i < 7; i++) spine.append(el('span'));
  preview.append(spine);
  const img = el('img');
  img.alt = `First frames of ${c.name}`; img.loading = 'lazy';
  img.src = `/api/poster/${encodeURIComponent(c.name)}?v=${c.mtime}`;
  img.onerror = () => { img.remove();
    preview.append(el('span', 'unavailable', 'No preview — decoder missing for this container')); };
  preview.append(img);
  const [cls, label] = statusOf(c);
  preview.append(el('span', 'badge ' + cls, label));
  const d = secs(c.durationS ?? c.summary?.durationS);
  if (d) preview.append(el('span', 'duration', d));
  link.append(preview);

  const info = el('div', 'info');
  info.append(el('h2', null, c.title || c.name));
  const p = c.summary;
  info.append(el('p', 'movement', movementLine(c)));

  const faults = Object.entries(p?.failures || {}).filter(([, n]) => n > 0);
  info.append(el('p', 'summary',
    !p ? (c.trace ? 'A run exists but produced no result — open the trace to see where it stopped.'
                  : 'Ready for its first analysis.')
    : p.blockers.length ? p.blockers.slice(0, 2).join(' · ')
    : faults.length ? faults.slice(0, 2).map(([n, k]) => `${human(n)} ×${k}`).join(' · ')
        + (faults.length > 2 ? ` · +${faults.length - 2} more` : '')
    : 'No technique faults fired. Open it to check what was measurable.'));

  if (p && p.score != null) {
    const bar = el('div', 'score-bar');
    const track = el('div', 'track');
    const fill = el('div', 'fill' + (p.score < 50 ? ' warn' : ''));
    fill.style.width = `${Math.max(0, Math.min(100, Number(p.score)))}%`;
    track.append(fill);
    bar.append(track, el('span', 'lbl', String(p.score)));
    info.append(bar);
  }

  const chips = el('div', 'chips');
  fillChips(chips, c);
  info.append(chips);
  link.append(info);
  wrap.append(link);

  const foot = el('div', 'card-footer');
  foot.append(el('span', 'id', c.id));
  foot.append(el('span', null, c.runs ? `${c.runs} run${c.runs > 1 ? 's' : ''}` : 'no runs'));
  if (p && p.score != null) foot.append(el('span', null, `score ${p.score}`));
  foot.append(el('span', 'spacer'));
  const open = el('a', 'btn btn-secondary', 'Debug this →');
  open.href = link.href;
  foot.append(open);
  wrap.append(foot, meta(c, () => {
    // In place: the editor stays open and keeps showing what it just did.
    wrap.querySelector('h2').textContent = c.title || c.name;
    wrap.querySelector('.movement').textContent = movementLine(c);
    fillChips(chips, c);
  }));
  return wrap;
}

const ORDERS = {
  added: (a, b) => b.addedAt - a.addedAt,
  name: (a, b) => (a.title || a.name).localeCompare(b.title || b.name),
  runs: (a, b) => b.runs - a.runs,
  duration: (a, b) => (b.durationS || 0) - (a.durationS || 0),
};

function render() {
  const term = $('#search').value.trim().toLowerCase();
  const filter = $('#filter').value;
  const shown = clips.filter((c) => {
    const hay = `${c.name} ${c.title} ${c.movement} ${c.tags} ${c.id} ${c.summary?.exercise || ''}`.toLowerCase();
    if (term && !hay.includes(term)) return false;
    return filter === 'all'
      || (filter === 'analyzed' && c.summary)
      || (filter === 'new' && !c.trace)
      || (filter === 'attention' && attention(c))
      || (filter === 'copies' && c.extraCopies > 0);
  }).sort(ORDERS[$('#sort').value]);

  stats();
  $('#gallery').replaceChildren(...shown.map(card));
  $('#status').className = 'status-line';
  $('#status').textContent = !clips.length
    ? 'The library is empty. Add a video, or drop files into data/videos and press Rescan disk.'
    : !shown.length ? 'No videos match that search or filter.'
    : `${shown.length} of ${clips.length} videos · summaries come from each video's most recent run`;
}

function fail(e) { $('#status').className = 'status-line err'; $('#status').textContent = e.message; }

async function refresh() { clips = (await api('/api/gallery')).clips; render(); }

$('#search').oninput = render;
$('#filter').onchange = render;
$('#sort').onchange = render;

$('#rescan').onclick = async () => {
  $('#rescan').disabled = true;
  $('#status').textContent = 'Indexing the video folders…';
  try {
    const r = await api('/api/videos/scan', { method: 'POST' });
    await refresh();
    $('#status').textContent = `Scan: ${r.added.length} new · ` +
      `${r.alreadyKnown.length} already in the library under another name · ` +
      `${r.unchanged} unchanged · ${r.total} distinct videos.`;
  } catch (e) { fail(e); }
  finally { $('#rescan').disabled = false; }
};

$('#upload').onchange = async () => {
  const files = [...$('#upload').files];
  if (!files.length) return;
  $('#upload').disabled = true;
  const added = [], dupes = [];
  try {
    for (const [i, f] of files.entries()) {
      if (f.size > 512 * 1024 * 1024) throw Error(`${f.name} is over 512 MiB.`);
      $('#status').className = 'status-line';
      $('#status').textContent = `Adding ${f.name} (${i + 1} of ${files.length})…`;
      const r = await api(`/api/videos?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
      (r.isNew ? added : dupes).push(r);
    }
    $('#search').value = ''; $('#filter').value = 'all';
    await refresh();
    $('#status').textContent = [
      added.length ? `Added ${added.length} video${added.length > 1 ? 's' : ''}.` : '',
      dupes.length ? `${dupes.length} already in the library — ${dupes.map((d) => d.id).join(', ')} ` +
        'hold those exact frames, so no second card was made.' : '',
    ].filter(Boolean).join(' ');
  } catch (e) { fail(e); }
  finally { $('#upload').disabled = false; $('#upload').value = ''; }
};

refresh().catch(fail);
