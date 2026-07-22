/**
 * Public registry explorer — facet brackets, search, pagination via /api/registries/browse.
 */
(function () {
  const API_BASE = window.location.origin;
  const S = window.RegistrySamples;
  const PAGE = 48;

  const els = {
    tabs: document.querySelectorAll('.explorer-tab'),
    breadcrumb: document.getElementById('explorer-breadcrumb'),
    search: document.getElementById('explorer-search'),
    facets: document.getElementById('explorer-facets'),
    status: document.getElementById('explorer-status'),
    results: document.getElementById('explorer-results'),
    more: document.getElementById('explorer-more'),
    mission: document.getElementById('explorer-mission'),
    precision: document.getElementById('registries-precision'),
    updated: document.getElementById('registries-updated'),
    refresh: document.getElementById('registries-refresh'),
    exportBtn: document.getElementById('registries-export'),
    health: document.getElementById('registries-health'),
    coverage: document.getElementById('registries-coverage-progress'),
    opsSecret: document.getElementById('ops-api-secret'),
    opsDry: document.getElementById('ops-repair-dry'),
    opsApply: document.getElementById('ops-repair-apply'),
    opsResult: document.getElementById('ops-repair-result'),
  };

  /** @type {{ tab: string, family: string|null, shade: string|null, primitives: string[], aspect: string|null, q: string, offset: number, items: any[], total: number, truncated: boolean, facets: any }} */
  const state = {
    tab: 'colors',
    family: null,
    shade: null,
    primitives: [],
    aspect: null,
    q: '',
    offset: 0,
    items: [],
    total: 0,
    truncated: false,
    facets: null,
  };

  let searchTimer = null;
  let lastExportBundle = null;
  let syncingUrl = false;

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function kindForTab() {
    if (state.tab === 'colors') return 'static_colors';
    if (state.tab === 'sound') return 'static_sound';
    if (state.tab === 'narrative') return 'narrative';
    if (state.tab === 'interpretation') return 'interpretation';
    if (state.tab === 'linguistic') return 'linguistic';
    if (state.tab === 'blended') return state.aspect || 'dynamic';
    return 'static_colors';
  }

  function readUrlState() {
    const p = new URLSearchParams(window.location.search);
    const tab = p.get('tab');
    if (tab && ['colors', 'sound', 'blended', 'narrative', 'interpretation', 'linguistic'].includes(tab)) {
      state.tab = tab;
    }
    state.family = p.get('family') || null;
    state.shade = p.get('shade') || null;
    state.aspect = p.get('aspect') || null;
    const prims = p.get('primitive') || p.get('primitives') || '';
    state.primitives = prims ? prims.split(',').map((x) => x.trim()).filter(Boolean) : [];
    state.q = p.get('q') || '';
    if (els.search) els.search.value = state.q;
    els.tabs.forEach((t) => t.classList.toggle('active', t.getAttribute('data-tab') === state.tab));
  }

  function writeUrlState() {
    if (syncingUrl) return;
    const p = new URLSearchParams();
    p.set('tab', state.tab);
    if (state.family) p.set('family', state.family);
    if (state.shade) p.set('shade', state.shade);
    if (state.aspect) p.set('aspect', state.aspect);
    if (state.primitives.length) p.set('primitive', state.primitives.join(','));
    if (state.q) p.set('q', state.q);
    const next = `${window.location.pathname}?${p.toString()}`;
    const cur = `${window.location.pathname}${window.location.search}`;
    if (next !== cur) {
      history.replaceState(null, '', next);
    }
  }

  function buildBrowseUrl(offset) {
    const params = new URLSearchParams();
    params.set('kind', kindForTab());
    params.set('limit', String(PAGE));
    params.set('offset', String(offset));
    if (state.q) params.set('q', state.q);
    if (state.tab === 'colors') {
      if (state.family) params.set('family', state.family);
      if (state.shade) params.set('shade', state.shade);
      state.primitives.forEach((p) => params.append('primitive', p));
    } else if (state.tab === 'sound' || state.tab === 'narrative' || state.tab === 'linguistic') {
      if (state.family) params.set('family', state.family);
    } else if (state.tab === 'blended' && state.aspect) {
      params.set('aspect', state.aspect);
    }
    return `${API_BASE}/api/registries/browse?${params}`;
  }

  async function fetchBrowse(append) {
    const offset = append ? state.offset : 0;
    els.status.textContent = append ? 'Loading more…' : 'Loading…';
    els.status.hidden = false;
    try {
      const res = await fetch(buildBrowseUrl(offset));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.facets = data.facets || {};
      state.total = data.total || 0;
      state.truncated = !!data.truncated;
      state.offset = offset + (data.items || []).length;
      if (append) state.items = state.items.concat(data.items || []);
      else state.items = data.items || [];
      writeUrlState();
      renderAll();
      els.status.textContent = '';
      els.status.hidden = true;
    } catch (e) {
      els.status.textContent = `Failed to load: ${e.message || e}`;
      els.status.hidden = false;
    }
  }

  function renderBreadcrumb() {
    if (!els.breadcrumb) return;
    const crumbs = [];
    const rootLabel =
      state.tab === 'colors' ? 'All colors'
        : state.tab === 'sound' ? 'All sounds'
          : state.tab === 'blended' ? 'Blended'
            : state.tab === 'narrative' ? 'Semantic'
              : state.tab === 'linguistic' ? 'Linguistic'
                : 'Interpretations';

    crumbs.push({ label: rootLabel, action: 'root' });

    if (state.tab === 'blended' && state.aspect) {
      crumbs.push({
        label: state.aspect.replace(/^learned_/, '').replace(/_/g, ' '),
        action: 'aspect',
      });
    }
    if (state.family) {
      crumbs.push({ label: state.family, action: 'family' });
    }
    if (state.tab === 'colors' && state.shade) {
      crumbs.push({ label: state.shade, action: 'shade' });
    }
    if (state.tab === 'colors' && state.primitives.length) {
      crumbs.push({ label: state.primitives.join(' + '), action: 'prims' });
    }

    els.breadcrumb.innerHTML = crumbs.map((c, i) => {
      const last = i === crumbs.length - 1;
      if (last) return `<span class="explorer-crumb explorer-crumb--current">${escapeHtml(c.label)}</span>`;
      return `<button type="button" class="explorer-crumb" data-crumb="${escapeHtml(c.action)}">${escapeHtml(c.label)}</button>`;
    }).join('<span class="explorer-crumb-sep" aria-hidden="true">/</span>');

    els.breadcrumb.querySelectorAll('[data-crumb]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const a = btn.getAttribute('data-crumb');
        if (a === 'root') {
          state.family = null;
          state.shade = null;
          state.primitives = [];
          if (state.tab === 'blended') state.aspect = null;
        } else if (a === 'aspect') {
          state.family = null;
        } else if (a === 'family') {
          state.shade = null;
          state.primitives = [];
        } else if (a === 'shade') {
          state.primitives = [];
        }
        fetchBrowse(false);
      });
    });
  }

  function showFamilyBrackets() {
    if (state.tab === 'colors') return !state.family;
    if (state.tab === 'blended') return !state.aspect;
    if (state.tab === 'sound' || state.tab === 'narrative' || state.tab === 'linguistic') return !state.family;
    return false;
  }

  function showShadeBrackets() {
    return state.tab === 'colors' && state.family && !state.shade;
  }

  function renderFacets() {
    if (!els.facets) return;
    const facets = state.facets || {};
    let html = '';

    if (showFamilyBrackets()) {
      const families = facets.families || [];
      if (!families.length) {
        els.facets.hidden = true;
        els.facets.innerHTML = '';
        return;
      }
      const title =
        state.tab === 'blended' ? 'Choose an aspect'
          : state.tab === 'sound' ? 'Choose an origin sound'
            : state.tab === 'narrative' ? 'Choose a semantic aspect'
              : state.tab === 'linguistic' ? 'Choose a domain'
                : 'Choose a color family';
      html += `<div class="explorer-facet-block"><h2 class="explorer-facet-title">${title}</h2>`;
      html += `<div class="explorer-brackets">`;
      families.forEach((f) => {
        const rgb = f.sample_rgb;
        const swatch = rgb
          ? `<span class="explorer-bracket-swatch" style="background:rgb(${rgb[0]},${rgb[1]},${rgb[2]})"></span>`
          : `<span class="explorer-bracket-swatch explorer-bracket-swatch--neutral"></span>`;
        html += `<button type="button" class="explorer-bracket" data-family="${escapeHtml(f.id)}">
          ${swatch}
          <span class="explorer-bracket-label">${escapeHtml(f.label)}</span>
          <span class="explorer-bracket-count">${f.count}</span>
        </button>`;
      });
      html += `</div></div>`;
    }

    if (showShadeBrackets()) {
      const shades = facets.shades || [];
      html += `<div class="explorer-facet-block"><h2 class="explorer-facet-title">Shade</h2>`;
      html += `<div class="explorer-brackets explorer-brackets--shade">`;
      shades.forEach((s) => {
        html += `<button type="button" class="explorer-bracket" data-shade="${escapeHtml(s.id)}">
          <span class="explorer-bracket-label">${escapeHtml(s.label)}</span>
          <span class="explorer-bracket-count">${s.count}</span>
        </button>`;
      });
      html += `</div></div>`;
    }

    if (state.tab === 'colors' && state.family && state.shade) {
      const prims = facets.primitives || [];
      if (prims.length) {
        html += `<div class="explorer-facet-block"><h2 class="explorer-facet-title">Refine by primitive mix</h2>`;
        html += `<div class="explorer-chips">`;
        prims.forEach((p) => {
          const on = state.primitives.includes(p.id);
          html += `<button type="button" class="explorer-chip${on ? ' active' : ''}" data-primitive="${escapeHtml(p.id)}">${escapeHtml(p.label)} <span>${p.count}</span></button>`;
        });
        html += `</div></div>`;
      }
    }

    els.facets.innerHTML = html;
    els.facets.hidden = !html;

    els.facets.querySelectorAll('[data-family]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-family');
        if (state.tab === 'blended') {
          state.aspect = id;
          state.family = null;
        } else {
          state.family = id;
          state.shade = null;
          state.primitives = [];
        }
        fetchBrowse(false);
      });
    });
    els.facets.querySelectorAll('[data-shade]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.shade = btn.getAttribute('data-shade');
        state.primitives = [];
        fetchBrowse(false);
      });
    });
    els.facets.querySelectorAll('[data-primitive]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-primitive');
        if (state.primitives.includes(id)) {
          state.primitives = state.primitives.filter((x) => x !== id);
        } else {
          state.primitives = state.primitives.concat(id);
        }
        fetchBrowse(false);
      });
    });
  }

  function depthStr(d) {
    if (!d || typeof d !== 'object') return '';
    return Object.entries(d)
      .map(([k, v]) => `${k} ${Number(v).toFixed(0)}%`)
      .join(' · ');
  }

  function renderColorResults() {
    if (!state.items.length) {
      return '<p class="explorer-empty">No colors match these filters.</p>';
    }
    return `<div class="explorer-color-grid">${state.items.map((c) => {
      const rgb = { r: c.r, g: c.g, b: c.b };
      const swatch = S ? S.colorSwatchHtml(rgb, { large: true }) : '';
      const depth = depthStr(c.depth_breakdown);
      return `<article class="explorer-color-card">
        ${swatch}
        <div class="explorer-color-meta">
          <strong class="explorer-color-name">${escapeHtml(c.name)}</strong>
          <span class="explorer-color-rgb">${c.r}, ${c.g}, ${c.b}</span>
          ${depth ? `<span class="explorer-color-depth">${escapeHtml(depth)}</span>` : ''}
        </div>
      </article>`;
    }).join('')}</div>`;
  }

  function renderSoundResults() {
    if (!state.items.length) return '<p class="explorer-empty">No sounds match.</p>';
    return `<div class="explorer-card-list">${state.items.map((s) => {
      const play = S
        ? `<button type="button" class="btn btn-secondary btn-sm explorer-play" data-sound-key="${escapeHtml(s.key)}">▶</button>`
        : '';
      const depth = depthStr(s.depth_breakdown);
      return `<article class="explorer-list-card">
        <div class="explorer-list-card-main">
          <strong>${escapeHtml(s.name)}</strong>
          <span class="explorer-muted">${escapeHtml(s.key)}</span>
          ${depth ? `<span class="explorer-muted">${escapeHtml(depth)}</span>` : ''}
        </div>
        ${play}
      </article>`;
    }).join('')}</div>`;
  }

  function renderGenericList(emptyMsg) {
    if (!state.items.length) return `<p class="explorer-empty">${escapeHtml(emptyMsg)}</p>`;
    return `<div class="explorer-card-list">${state.items.map((item) => {
      const subtitle = item.value || item.key || item.prompt || item.canonical || '';
      const extra = item.aspect || item.domain || item.motion_type || item.gradient_type || item.role || '';
      let detail = '';
      if (item.prompt && item.instruction) {
        detail = `<pre class="explorer-instruction">${escapeHtml(JSON.stringify(item.instruction, null, 0).slice(0, 280))}</pre>`;
      }
      return `<article class="explorer-list-card">
        <div class="explorer-list-card-main">
          <strong>${escapeHtml(item.name || item.span || item.prompt || item.key)}</strong>
          ${subtitle && subtitle !== item.name ? `<span class="explorer-muted">${escapeHtml(String(subtitle).slice(0, 160))}</span>` : ''}
          ${extra ? `<span class="explorer-tag">${escapeHtml(String(extra))}</span>` : ''}
          ${item.count != null ? `<span class="explorer-muted">×${item.count}</span>` : ''}
          ${detail}
        </div>
      </article>`;
    }).join('')}</div>`;
  }

  function renderResults() {
    if (!els.results) return;
    const browsingLeaves =
      state.tab === 'interpretation' ||
      (state.tab === 'colors' && state.shade) ||
      (state.tab === 'sound' && state.family) ||
      (state.tab === 'narrative' && state.family) ||
      (state.tab === 'linguistic' && state.family) ||
      (state.tab === 'blended' && state.aspect) ||
      state.q;

    // At bracket-only level, still show a short preview of matches when family selected without shade (colors)
    if (state.tab === 'colors' && state.family && !state.shade && !state.q) {
      els.results.innerHTML = `<p class="explorer-hint">Pick a shade to browse ${state.total} color${state.total === 1 ? '' : 's'} in <strong>${escapeHtml(state.family)}</strong>.</p>`;
      if (els.more) els.more.hidden = true;
      return;
    }

    if (showFamilyBrackets() && !state.q) {
      els.results.innerHTML = `<p class="explorer-hint">Select a bracket above to drill in. ${state.total ? `${state.total} values in view.` : ''}</p>`;
      if (els.more) els.more.hidden = true;
      return;
    }

    let html = '';
    if (state.tab === 'colors') html = renderColorResults();
    else if (state.tab === 'sound') html = renderSoundResults();
    else if (state.tab === 'interpretation') html = renderGenericList('No interpretations yet.');
    else html = renderGenericList('No entries match.');

    const countLabel = browsingLeaves
      ? `<p class="explorer-count">Showing ${state.items.length} of ${state.total}</p>`
      : '';
    els.results.innerHTML = countLabel + html;

    if (els.more) {
      els.more.hidden = !state.truncated;
    }

    els.results.querySelectorAll('[data-sound-key]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.getAttribute('data-sound-key');
        const item = state.items.find((x) => x.key === key);
        if (!S || !item) return;
        const depth = item.depth_breakdown || {};
        if (typeof S.playSoundBlend === 'function' && Object.keys(depth).length) {
          S.playSoundBlend(depth, item.strength_pct != null ? item.strength_pct : 50);
        } else if (typeof S.playPrimitiveSound === 'function') {
          S.playPrimitiveSound(item.origin || Object.keys(depth)[0] || 'tone', item.strength_pct || 50);
        }
      });
    });
  }

  function renderAll() {
    renderBreadcrumb();
    renderFacets();
    renderResults();
  }

  els.tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      els.tabs.forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      state.tab = tab.getAttribute('data-tab');
      state.family = null;
      state.shade = null;
      state.primitives = [];
      state.aspect = null;
      state.q = '';
      if (els.search) els.search.value = '';
      if (els.search) {
        els.search.placeholder =
          state.tab === 'colors' ? 'Search name, key, RGB…'
            : state.tab === 'interpretation' ? 'Search prompts…'
              : 'Search…';
      }
      fetchBrowse(false);
    });
  });

  if (els.search) {
    els.search.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.q = (els.search.value || '').trim();
        fetchBrowse(false);
      }, 280);
    });
  }

  if (els.more) {
    els.more.addEventListener('click', () => fetchBrowse(true));
  }

  /* ——— Ops panel (coverage / health / export) ——— */
  function renderHealth(health) {
    if (!els.health || !health || !health.issues) return;
    const i = health.issues;
    const items = [
      { label: 'Pure sound mood leakage', count: i.pure_sound_semantic_keys, total: i.pure_sound_total },
      { label: 'Motion missing depth', count: i.blended_motion_missing_depth, total: i.blended_motion_total },
      { label: 'Lighting missing depth', count: i.blended_lighting_missing_depth, total: i.blended_lighting_total },
      { label: 'Gibberish names (est.)', count: i.gibberish_names_estimate },
      { label: 'Narrative name mismatches', count: i.narrative_name_mismatches },
    ].filter((x) => x.count > 0);
    if (!items.length && health.ok) {
      els.health.innerHTML = '<p class="registries-health-ok">Registry health: all checks passed.</p>';
      els.health.hidden = false;
      return;
    }
    const recs = (health.recommendations || []).map((r) => `<li>${escapeHtml(r)}</li>`).join('');
    els.health.innerHTML = `
      <div class="registries-health-panel ${health.ok ? '' : 'registries-health-panel--warn'}">
        <strong>Registry health</strong>
        <ul class="registries-health-list">${items.map((x) => {
          const suffix = x.total != null ? ` / ${x.total}` : '';
          return `<li>${escapeHtml(x.label)}: <strong>${x.count}</strong>${suffix}</li>`;
        }).join('')}</ul>
        ${recs ? `<ul class="registries-health-recs">${recs}</ul>` : ''}
      </div>`;
    els.health.hidden = false;
  }

  function renderCoverage(cov) {
    if (!els.coverage || !cov) return;
    const bars = [
      { label: 'Static colors', pct: cov.static_colors_coverage_pct, n: cov.static_colors_count },
      { label: 'Sound primitives', pct: cov.static_sound_coverage_pct, n: cov.static_sound_primitive_count },
    ].filter((b) => b.pct != null || b.n != null);
    if (!bars.length) {
      els.coverage.hidden = true;
      return;
    }
    els.coverage.innerHTML = `<div class="registries-coverage-bars">${bars.map((b) => {
      const pct = Math.max(0, Math.min(100, Number(b.pct) || 0));
      return `<div class="registries-coverage-row">
        <span>${escapeHtml(b.label)}${b.n != null ? ` (${b.n})` : ''}</span>
        <div class="registries-coverage-track"><div class="registries-coverage-fill" style="width:${pct}%"></div></div>
        <span>${pct.toFixed(0)}%</span>
      </div>`;
    }).join('')}</div>`;
    els.coverage.hidden = false;
  }

  async function loadMission() {
    if (!els.mission) return;
    try {
      const res = await fetch(`${API_BASE}/api/registries/mission`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const m = await res.json();
      const pct = m.findability_pct != null ? Number(m.findability_pct) : null;
      const cf = m.colors || {};
      const sf = m.sound || {};
      const nf = m.narrative || {};
      els.mission.textContent = pct != null
        ? `Findability ${pct}% · colors ${cf.families_filled || 0}/${cf.families_total || 12} families · sound ${sf.origins_filled || 0}/${sf.origins_total || 10} origins · narrative ${nf.aspects_filled || 0}/${nf.aspects_total || 7} aspects`
        : 'Findability: —';
      els.mission.title = m.hint || '';
      els.mission.classList.toggle('explorer-mission--good', pct != null && pct >= 80);
      els.mission.classList.toggle('explorer-mission--warn', pct != null && pct < 80);
    } catch {
      els.mission.textContent = 'Findability: —';
    }
  }

  async function loadOps() {
    try {
      const [progress, health, coverage, meta] = await Promise.all([
        fetch(`${API_BASE}/api/loop/progress?last=20`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch(`${API_BASE}/api/registries/health`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch(`${API_BASE}/api/registries/coverage`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch(`${API_BASE}/api/registries?section=meta`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      if (els.precision && progress) {
        const pct = progress.precision_pct ?? progress.learning_rate_pct;
        els.precision.textContent = pct != null ? `Precision: ${Number(pct).toFixed(0)}%` : 'Precision: —';
      }
      if (els.updated) {
        els.updated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      }
      if (health) renderHealth(health);
      if (coverage) renderCoverage(coverage);
      lastExportBundle = { progress, health, coverage, meta, browse_sample: { kind: kindForTab(), total: state.total } };
    } catch {
      /* ops optional */
    }
  }

  function opsAuthHeaders() {
    const secret = (els.opsSecret && els.opsSecret.value) || sessionStorage.getItem('motion_ops_secret') || '';
    if (els.opsSecret && els.opsSecret.value) {
      sessionStorage.setItem('motion_ops_secret', els.opsSecret.value);
    }
    return secret ? { Authorization: `Bearer ${secret}`, 'Content-Type': 'application/json' } : null;
  }

  async function runNameRepair(dryRun) {
    if (!els.opsResult) return;
    const headers = opsAuthHeaders();
    if (!headers) {
      els.opsResult.hidden = false;
      els.opsResult.textContent = 'Paste MOTION_API_SECRET first.';
      return;
    }
    els.opsResult.hidden = false;
    els.opsResult.textContent = dryRun ? 'Dry run…' : 'Applying…';
    try {
      const qs = dryRun ? '?dry_run=1&limit=200' : '?limit=200';
      const res = await fetch(`${API_BASE}/api/registries/backfill-names${qs}`, {
        method: 'POST',
        headers,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      els.opsResult.textContent = JSON.stringify(data, null, 2);
      if (!dryRun) {
        loadMission();
        loadOps();
        fetchBrowse(false);
      }
    } catch (e) {
      els.opsResult.textContent = `Failed: ${e.message || e}`;
    }
  }

  if (els.refresh) {
    els.refresh.addEventListener('click', () => {
      loadOps();
      loadMission();
      fetchBrowse(false);
    });
  }
  if (els.exportBtn) {
    els.exportBtn.addEventListener('click', async () => {
      await loadOps();
      const blob = new Blob([JSON.stringify(lastExportBundle || {}, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `motion-registries-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }
  if (els.opsSecret) {
    const saved = sessionStorage.getItem('motion_ops_secret');
    if (saved) els.opsSecret.value = saved;
  }
  if (els.opsDry) els.opsDry.addEventListener('click', () => runNameRepair(true));
  if (els.opsApply) els.opsApply.addEventListener('click', () => runNameRepair(false));

  // Deep-links: /registries/?tab=colors&family=blue&shade=light
  readUrlState();
  window.addEventListener('popstate', () => {
    syncingUrl = true;
    readUrlState();
    syncingUrl = false;
    fetchBrowse(false);
  });

  // Initial load
  fetchBrowse(false);
  loadMission();
  loadOps();
})();
/* explorer-v3 */
