'use strict';
/* One live line, so the guide talks about the library in front of you rather
   than a hypothetical one. Everything else on this page is static on purpose:
   a debugging guide that cannot be read when the server is unhappy is not
   much of a debugging guide. */
(async () => {
  try {
    const clips = (await (await fetch('/api/gallery')).json()).clips || [];
    const files = clips.reduce((n, c) => n + c.copies.length, 0);
    const runs = clips.reduce((n, c) => n + c.runs, 0);
    const analysed = clips.filter((c) => c.summary).length;
    document.getElementById('live').textContent =
      `right now: ${clips.length} distinct videos from ${files} files on disk · ` +
      `${analysed} analysed · ${runs} runs on record`;
  } catch { /* the guide stands on its own */ }
})();
