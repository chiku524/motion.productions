/**
 * Opacity-plane + cross-axis coverage panel. One cached GET /api/coverage/axes, fetched lazily when the panel opens.
 */
(function () {
  const root = document.getElementById('axes-coverage');
  if (!root) return;
  const status = document.getElementById('axes-coverage-status');
  const body = document.getElementById('axes-coverage-body');
  let loaded = false;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const bar = (pct) => `<span style="display:inline-block;width:120px;height:8px;background:rgba(127,127,127,.25);vertical-align:middle"><span style="display:block;height:100%;width:${Math.min(100, pct)}%;background:currentColor"></span></span>`;
  async function load() {
    if (loaded) return;
    loaded = true;
    try {
      const r = await fetch('/api/coverage/axes');
      const d = await r.json();
      if (!d.available) { status.textContent = 'Not available yet.'; return; }
      const o = d.opacity;
      let h = `<h4>Opacity plane (${esc(o.space)}): ${o.covered.toLocaleString()} / ${o.size.toLocaleString()} cells (${o.pct}%)</h4><table class="explorer-table"><tr><th>Alpha</th><th>Cells</th><th></th></tr>`;
      for (const l of o.levels) {
        const pct = l.universe ? (100 * l.seen) / l.universe : 0;
        h += `<tr><td>${l.alpha_min}?${l.alpha_max}</td><td>${l.seen.toLocaleString()}</td><td>${bar(pct)} ${pct.toFixed(1)}%</td></tr>`;
      }
      h += '</table><h4>Cross-axis pairs</h4><table class="explorer-table"><tr><th>Pair</th><th>Seen</th><th>Possible</th><th></th></tr>';
      for (const p of [...d.cross_axis.pairs].sort((a, b) => a.pct - b.pct)) {
        h += `<tr><td>${esc(p.a)} ? ${esc(p.b)}</td><td>${p.seen}</td><td>${p.universe}</td><td>${bar(p.pct)} ${p.pct}%</td></tr>`;
      }
      body.innerHTML = h + '</table>';
      status.textContent = d.updated_at ? `Updated ${d.updated_at} UTC` : '';
    } catch (e) {
      loaded = false;
      status.textContent = 'Could not load coverage.';
    }
  }
  root.querySelector('details').addEventListener('toggle', (e) => { if (e.target.open) load(); });
})();
