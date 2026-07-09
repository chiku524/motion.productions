/**
 * Registry browser — dedicated page with color swatches and sound samples.
 */
(function () {
  const API_BASE = window.location.origin;
  const S = window.RegistrySamples;

  const registriesLoading = document.getElementById('registries-loading');
  const registriesTables = document.getElementById('registries-tables');
  const registriesPrecision = document.getElementById('registries-precision');
  const registriesUpdated = document.getElementById('registries-updated');
  const registriesRefresh = document.getElementById('registries-refresh');
  const registriesExport = document.getElementById('registries-export');
  const registriesTabs = document.querySelectorAll('.registries-tab');
  const registriesContent = document.getElementById('registries-content');
  const registriesHealth = document.getElementById('registries-health');

  let lastRegistriesData = null;
  let lastProgressData = null;

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function cellHtml(c) {
    if (c && typeof c === 'object' && c.html != null) return c.html;
    return escapeHtml(String(c));
  }

  function registriesTable(headers, rows) {
    const th = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('');
    const trs = rows.map((r) => `<tr>${r.map((c) => `<td>${cellHtml(c)}</td>`).join('')}</tr>`).join('');
    return `<div class="registries-table-wrap"><table class="registries-table"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`;
  }

  function depthBreakdownStr(d, opts) {
    if (!d || typeof d !== 'object') return '—';
    const parts = Object.entries(d).map(([k, v]) => `${k}: ${Number(v).toFixed(0)}%`).filter(Boolean);
    let s = parts.length ? parts.join(', ') : '—';
    if (opts && opts.opacity_pct != null) s = (s !== '—' ? s + '; ' : '') + `opacity: ${Number(opts.opacity_pct).toFixed(0)}%`;
    if (opts && opts.theme_breakdown && typeof opts.theme_breakdown === 'object' && Object.keys(opts.theme_breakdown).length) {
      const t = Object.entries(opts.theme_breakdown).map(([k, v]) => `${k}: ${Number(v).toFixed(0)}%`).join(', ');
      s = (s !== '—' ? s + '; ' : '') + 'theme: ' + t;
    }
    return s || '—';
  }

  function renderColorPrimaryGrid(primaries, filter) {
    const q = (filter || '').trim().toLowerCase();
    const list = (primaries || []).filter((p) => {
      if (!q) return true;
      return String(p.name || '').toLowerCase().includes(q)
        || `${p.r},${p.g},${p.b}`.includes(q);
    });
    if (!list.length) return '<p class="registries-empty">No matching color primaries.</p>';
    return `<div class="registry-color-grid" id="registry-color-grid">${list.map((p) => S.colorPrimaryCard(p)).join('')}</div>`;
  }

  function renderHealth(health) {
    if (!registriesHealth || !health || !health.issues) return;
    const i = health.issues;
    const items = [
      { label: 'Pure sound mood leakage', count: i.pure_sound_semantic_keys, total: i.pure_sound_total },
      { label: 'Motion missing depth', count: i.blended_motion_missing_depth, total: i.blended_motion_total },
      { label: 'Lighting missing depth', count: i.blended_lighting_missing_depth, total: i.blended_lighting_total },
      { label: 'Gibberish names (est.)', count: i.gibberish_names_estimate },
      { label: 'Narrative name mismatches', count: i.narrative_name_mismatches },
    ].filter((x) => x.count > 0);
    if (!items.length && health.ok) {
      registriesHealth.innerHTML = '<p class="registries-health-ok">Registry health: all checks passed.</p>';
      registriesHealth.hidden = false;
      return;
    }
    const recs = (health.recommendations || []).map((r) => `<li>${escapeHtml(r)}</li>`).join('');
    registriesHealth.innerHTML = `
      <div class="registries-health-panel ${health.ok ? '' : 'registries-health-panel--warn'}">
        <strong>Registry health</strong>
        <ul class="registries-health-list">${items.map((x) => {
          const suffix = x.total != null ? ` / ${x.total}` : '';
          return `<li>${escapeHtml(x.label)}: <strong>${x.count}</strong>${suffix}</li>`;
        }).join('')}</ul>
        ${recs ? `<ul class="registries-health-recs">${recs}</ul>` : ''}
      </div>`;
    registriesHealth.hidden = false;
  }

  function soundKeyCell(s) {
    const key = s.key || '—';
    if (!s.key_leak) return key;
    const canon = s.canonical_key ? ` → ${s.canonical_key}` : '';
    return { html: `<span class="registry-key-leak" title="Semantic mood in Pure key${canon}">${escapeHtml(key)}</span>` };
  }

  function renderRegistries(data) {
    if (!data || !registriesTables || !S) return;
    const staticPrimitives = data.static_primitives || {};
    const dynamicCanonical = data.dynamic_canonical || {};
    const static_ = data.static || {};
    const dynamic = data.dynamic || {};
    const narrative = data.narrative || {};
    const interpretation = data.interpretation || [];
    const colorPrimaries = staticPrimitives.color_primaries || [];
    const soundPrimaries = staticPrimitives.sound_primaries || S.PRIMITIVES;

    const staticHtml = `
    <div class="registries-pane" data-pane="static">
      <p class="registries-primitives-desc">Pure primitives with <strong>visual color samples</strong> and <strong>playable sound samples</strong>. Discoveries show the same previews from stored RGB and depth breakdown.</p>
      <h3 class="registries-pane-title">Pure — Color primitives (origin)</h3>
      <p class="registries-hint">Click a swatch to see RGB. Search by name (e.g. mist, slate) or values.</p>
      <label class="registry-search-label" for="registry-color-search">Filter colors</label>
      <input type="search" id="registry-color-search" class="registry-search" placeholder="e.g. mist, ocean, 100,125,150" autocomplete="off">
      <div id="registry-color-grid-wrap">${renderColorPrimaryGrid(colorPrimaries, '')}</div>
      <h3 class="registries-pane-title">Pure — Colors (per-frame discoveries)</h3>
      ${static_.colors && static_.colors.length
        ? registriesTable(['Sample', 'Name', 'Key', 'Count', 'Depth %'], static_.colors.map((c) => {
            const breakdown = depthBreakdownStr(c.depth_breakdown, { opacity_pct: c.opacity_pct, theme_breakdown: c.theme_breakdown });
            return [
              S.colorSwatchCell(c, colorPrimaries),
              c.name,
              c.key,
              c.count,
              (breakdown && breakdown !== '—' ? breakdown : ''),
            ];
          }))
        : '<p class="registries-empty">No static colors yet.</p>'}
      <h3 class="registries-pane-title">Pure — Sound primitives (origin noises)</h3>
      <p class="registries-hint">Press ▶ to hear each origin noise. Blended discoveries mix primitives by depth %.</p>
      <div class="registry-sound-grid">${(soundPrimaries.length ? soundPrimaries : S.PRIMITIVES).map((p) => S.soundPrimaryCard(p)).join('')}</div>
      <h3 class="registries-pane-title">Pure — Sound (per-frame discoveries)</h3>
      ${static_.sound && static_.sound.length
        ? registriesTable(['Sample', 'Name', 'Key', 'Count', 'Strength %', 'Depth %'], static_.sound.map((s) => {
            const breakdown = depthBreakdownStr(s.depth_breakdown);
            const strength = s.strength_pct != null ? (Number(s.strength_pct) <= 1 ? (s.strength_pct * 100).toFixed(0) + '%' : Number(s.strength_pct).toFixed(0) + '%') : '—';
            return [S.soundPlayCell(s), s.name, soundKeyCell(s), s.count, strength, (breakdown && breakdown !== '—' ? breakdown : '')];
          }))
        : '<p class="registries-empty">No static sound yet.</p>'}
    </div>`;

    const dynamicHtml = `
    <div class="registries-pane" data-pane="dynamic">
      <p class="registries-primitives-desc">Blended elements. Learned colors include swatch previews.</p>
      <h3 class="registries-pane-title">Blended — Colors (learned)</h3>
      ${dynamic.colors_merged_from_blends ? `<p class="registries-hint">${dynamic.colors_merged_from_blends} blend-only colors merged into this table (deduped by RGB).</p>` : ''}
      ${dynamic.colors && dynamic.colors.length
        ? registriesTable(['Sample', 'Key', 'Name', 'Count', 'Depth %'], dynamic.colors.map((c) => {
            const b = depthBreakdownStr(c.depth_breakdown, { opacity_pct: c.opacity_pct, theme_breakdown: c.theme_breakdown });
            return [S.colorSwatchCell(c, colorPrimaries), c.key, c.name, c.count, (b && b !== '—' ? b : '')];
          }))
        : '<p class="registries-empty">No learned colors yet.</p>'}
      <h3 class="registries-pane-title">Blended — Gradient</h3>
      ${dynamic.gradient && dynamic.gradient.length
        ? registriesTable(['Name', 'Key', 'Depth %'], dynamic.gradient.map((g) => {
            const b = depthBreakdownStr(g.depth_breakdown);
            return [g.name, g.key, (b && b !== '—' ? b : '')];
          }))
        : '<p class="registries-empty">No gradient discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Camera</h3>
      ${dynamic.camera && dynamic.camera.length
        ? registriesTable(['Name', 'Key', 'Depth %'], dynamic.camera.map((c) => {
            const b = depthBreakdownStr(c.depth_breakdown);
            return [c.name, c.key, (b && b !== '—' ? b : '')];
          }))
        : '<p class="registries-empty">No camera discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Motion</h3>
      ${dynamic.motion && dynamic.motion.length
        ? registriesTable(['Key', 'Name', 'Trend', 'Count', 'Depth %'], dynamic.motion.map((m) => {
            const b = depthBreakdownStr(m.depth_breakdown);
            return [m.key, m.name, m.trend || '—', m.count, (b && b !== '—' ? b : (m.depth_pct != null ? `${m.depth_pct}%` : '—'))];
          }))
        : '<p class="registries-empty">No motion discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Entities</h3>
      ${dynamic.entities && dynamic.entities.length
        ? registriesTable(['Name', 'Kind', 'Trajectory', 'Bounce', 'Color', 'Count'], dynamic.entities.map((e) => [
            e.name || e.label || e.key || '—',
            e.kind || '—',
            e.trajectory || '—',
            e.bounce ? 'yes' : 'no',
            e.color_hint || '—',
            e.count ?? '—',
          ]))
        : '<p class="registries-empty">No entity discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Sound</h3>
      ${dynamic.sound && dynamic.sound.length
        ? registriesTable(['Sample', 'Name', 'Key', 'Depth %'], dynamic.sound.map((s) => {
            const b = depthBreakdownStr(s.depth_breakdown);
            const key = typeof s.key === 'string' ? s.key : (s.tempo || s.mood || s.presence || '—');
            return [S.soundPlayCell({ name: s.name, depth_breakdown: s.depth_breakdown, strength_pct: 0.5 }), s.name || '—', key, (b && b !== '—' ? b : '')];
          }))
        : '<p class="registries-empty">No sound discoveries yet.</p>'}
      ${(dynamic.lighting && dynamic.lighting.length) ? `<h3 class="registries-pane-title">Blended — Lighting</h3>
      ${registriesTable(['Name', 'Key', 'Depth %'], dynamic.lighting.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))}` : ''}
      ${(dynamic.composition && dynamic.composition.length) ? `<h3 class="registries-pane-title">Blended — Composition</h3>
      ${registriesTable(['Name', 'Key', 'Depth %'], dynamic.composition.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))}` : ''}
      ${(dynamic.graphics && dynamic.graphics.length) ? `<h3 class="registries-pane-title">Blended — Graphics</h3>
      ${registriesTable(['Name', 'Key', 'Depth %'], dynamic.graphics.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))}` : ''}
      ${(dynamic.temporal && dynamic.temporal.length) ? `<h3 class="registries-pane-title">Blended — Temporal</h3>
      ${registriesTable(['Name', 'Key', 'Depth %'], dynamic.temporal.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))}` : ''}
      ${(dynamic.technical && dynamic.technical.length) ? `<h3 class="registries-pane-title">Blended — Technical</h3>
      ${registriesTable(['Name', 'Key', 'Depth %'], dynamic.technical.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))}` : ''}
      <h3 class="registries-pane-title">Blended — Blends (other)</h3>
      ${dynamic.blends && dynamic.blends.length
        ? registriesTable(['Name', 'Domain', 'Key', 'Depth %'], dynamic.blends.map((b) => { const x = depthBreakdownStr(b.depth_breakdown); return [b.name, b.domain || '—', (b.key || '').slice(0, 40), (x && x !== '—' ? x : '')]; }))
        : '<p class="registries-empty">No other blends yet.</p>'}
    </div>`;

    const narrativeHtml = `
    <div class="registries-pane" data-pane="narrative">
      <p class="registries-primitives-desc">Semantic categories and named elements.</p>
      ${Object.keys(narrative).map((aspect) => {
        const entries = narrative[aspect] || [];
        return `
        <h3 class="registries-pane-title">Semantic — ${escapeHtml(aspect)}</h3>
        ${entries.length
          ? registriesTable(['Entry key', 'Value', 'Name', 'Count'], entries.map((e) => [e.entry_key, e.value, e.name, e.count]))
          : '<p class="registries-empty">No entries yet.</p>'}
        `;
      }).join('')}
    </div>`;

    const instructionSummary = (inst) => {
      if (!inst || typeof inst !== 'object') return '—';
      const parts = [];
      if (inst.palette) parts.push('palette');
      if (inst.motion) parts.push('motion');
      if (inst.gradient) parts.push('gradient');
      if (inst.camera) parts.push('camera');
      if (inst.mood) parts.push('mood');
      if (inst.audio_tempo) parts.push('tempo');
      const keys = Object.keys(inst).filter((k) => !parts.includes(k) && typeof inst[k] !== 'object');
      return [...parts, ...keys].slice(0, 6).join(', ') || '—';
    };

    const interpretationHtml = `
    <div class="registries-pane" data-pane="interpretation">
      <p class="registries-primitives-desc">Resolved user prompts (prompt → instruction).</p>
      ${interpretation && interpretation.length
        ? registriesTable(['Prompt', 'Instruction summary', 'Updated'], interpretation.map((i) => [
            (i.prompt || '').slice(0, 80) + (i.prompt && i.prompt.length > 80 ? '…' : ''),
            instructionSummary(i.instruction),
            i.updated_at ? new Date(i.updated_at).toLocaleString() : '—',
          ]))
        : '<p class="registries-empty">No resolved interpretations yet.</p>'}
    </div>`;

    registriesTables.innerHTML = staticHtml + dynamicHtml + narrativeHtml + interpretationHtml;
    registriesTables.hidden = false;
    if (registriesLoading) registriesLoading.hidden = true;

    const panes = registriesTables.querySelectorAll('.registries-pane');
    const activeTab = document.querySelector('.registries-tab.active');
    const activePane = activeTab ? activeTab.getAttribute('data-tab') : 'static';
    panes.forEach((p) => { p.hidden = p.getAttribute('data-pane') !== activePane; });

    S.bindSoundButtons(registriesTables);

    const searchEl = document.getElementById('registry-color-search');
    const gridWrap = document.getElementById('registry-color-grid-wrap');
    if (searchEl && gridWrap) {
      searchEl.addEventListener('input', () => {
        gridWrap.innerHTML = renderColorPrimaryGrid(colorPrimaries, searchEl.value);
      });
    }
  }

  function renderCoverageProgress(cov) {
    const host = document.getElementById('registries-coverage-progress');
    if (!host || !cov) return;
    const target = (cov.targets && cov.targets.target_pct) || 95;
    const soundNum = cov.static_sound_num_primitives || (cov.targets && cov.targets.static_sound_num_primitives) || 10;
    const soundPct = soundNum > 0
      ? Math.min(100, Math.round((100 * (cov.static_sound_primitive_count || 0)) / soundNum))
      : 0;
    const rows = [
      { label: 'Static colors (cell space)', pct: cov.static_colors_coverage_pct || 0, detail: `${cov.static_colors_count || 0} / ${cov.static_colors_estimated_cells || '—'}` },
      { label: 'Static sound primitives', pct: soundPct, detail: `${cov.static_sound_primitive_count || 0} / ${soundNum}` },
    ];
    const narrative = cov.narrative || {};
    const aspectLabel = (aspect) =>
      aspect === 'plots' ? 'Narrative · plots (tension_curve)' : `Narrative · ${aspect}`;
    for (const aspect of Object.keys(narrative).sort()) {
      const n = narrative[aspect];
      rows.push({
        label: aspectLabel(aspect),
        pct: n.coverage_pct || 0,
        detail: `${n.count || 0} / ${n.origin_size || '—'}`,
      });
    }
    const missingSound = cov.static_sound_primitives_missing || [];
    const missingHint = missingSound.length
      ? `<p class="registries-hint">Untouched sound primitives: ${missingSound.map(escapeHtml).join(', ')}</p>`
      : '';
    host.innerHTML = `
      <div class="registries-coverage-panel">
        <strong>Completion vs targets</strong>
        <p class="registries-hint">Target line at ${target}% (full NARRATIVE_ORIGINS / ${soundNum} sound primitives / ~28k color cells).</p>
        ${missingHint}
        <ul class="registries-coverage-list">${rows.map((r) => {
          const pct = Math.max(0, Math.min(100, Number(r.pct) || 0));
          const onTarget = pct >= target;
          return `<li>
            <div class="registries-coverage-row">
              <span>${escapeHtml(r.label)}</span>
              <span class="${onTarget ? 'on-target' : 'below-target'}">${pct.toFixed(1)}% · ${escapeHtml(r.detail)}</span>
            </div>
            <div class="registries-coverage-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
              <div class="registries-coverage-fill" style="width:${pct}%"></div>
              <div class="registries-coverage-target" style="left:${target}%"></div>
            </div>
          </li>`;
        }).join('')}</ul>
      </div>`;
    host.hidden = false;
  }

  async function fetchRegistriesSection(section, limit = 100) {
    const res = await fetch(`${API_BASE}/api/registries?section=${encodeURIComponent(section)}&limit=${limit}&offset=0`);
    const text = await res.text();
    if (text.trimStart().startsWith('<')) throw new Error('Registries API unavailable');
    let data;
    try { data = JSON.parse(text); } catch { throw new Error('Invalid registries response'); }
    if (!res.ok) throw new Error(data.error || data.details || 'Failed to load registries');
    return data;
  }

  /** Merge one section response into the cached registries payload. */
  function mergeSection(base, section, sec) {
    const next = { ...(base || {}) };
    if (sec.static_primitives) next.static_primitives = sec.static_primitives;
    if (sec.dynamic_canonical) next.dynamic_canonical = sec.dynamic_canonical;
    if (section === 'static' && sec.static) next.static = sec.static;
    if (section === 'dynamic' && sec.dynamic) next.dynamic = sec.dynamic;
    if (section === 'narrative' && sec.narrative) next.narrative = sec.narrative;
    if (section === 'interpretation') {
      next.interpretation = sec.interpretation || [];
      next.linguistic = sec.linguistic || next.linguistic || [];
    }
    if (section === 'linguistic') next.linguistic = sec.linguistic || [];
    next.truncated = !!(next.truncated || sec.truncated);
    next.totals = { ...(next.totals || {}), ...(sec.totals || {}) };
    return next;
  }

  const loadedSections = new Set();
  let activeTab = 'static';

  async function ensureSectionLoaded(section) {
    const map = {
      static: 'static',
      dynamic: 'dynamic',
      narrative: 'narrative',
      interpretation: 'interpretation',
    };
    const apiSection = map[section] || section;
    if (loadedSections.has(apiSection)) return lastRegistriesData;
    const sec = await fetchRegistriesSection(apiSection, 80);
    lastRegistriesData = mergeSection(lastRegistriesData, apiSection, sec);
    loadedSections.add(apiSection);
    return lastRegistriesData;
  }

  async function loadRegistries() {
    if (!registriesContent) return;
    const btnText = registriesRefresh ? registriesRefresh.textContent : '';
    if (registriesRefresh) {
      registriesRefresh.disabled = true;
      registriesRefresh.textContent = 'Loading…';
    }
    if (registriesLoading) {
      registriesLoading.textContent = 'Loading registries…';
      registriesLoading.hidden = false;
    }
    if (registriesTables) registriesTables.hidden = true;
    loadedSections.clear();
    try {
      // Light bootstrap first (meta is cheap; avoid 6× full D1 dumps in parallel).
      const [meta, covRes, progRes, healthRes] = await Promise.all([
        fetchRegistriesSection('meta', 50),
        fetch(`${API_BASE}/api/registries/coverage`),
        fetch(`${API_BASE}/api/loop/progress?last=20`),
        fetch(`${API_BASE}/api/registries/health`),
      ]);
      lastRegistriesData = {
        static_primitives: meta.static_primitives,
        dynamic_canonical: meta.dynamic_canonical,
        static: { colors: [], sound: [] },
        dynamic: {},
        narrative: {},
        interpretation: [],
        linguistic: [],
        totals: meta.totals || {},
        truncated: false,
      };
      loadedSections.add('meta');

      // Load only the active tab section (default: static).
      await ensureSectionLoaded(activeTab);
      const data = lastRegistriesData;
      const progText = await progRes.text();
      lastProgressData = null;
      try { lastProgressData = JSON.parse(progText); } catch { /* ignore */ }
      renderRegistries(data);
      showRegistriesTab(activeTab);
      try {
        const health = await healthRes.json();
        if (healthRes.ok) renderHealth(health);
      } catch { /* health endpoint optional */ }
      try {
        const cov = await covRes.json();
        if (covRes.ok) renderCoverageProgress(cov);
      } catch { /* coverage optional */ }
      if (registriesUpdated) {
        const truncNote = data.truncated ? ' · paginated (first page)' : '';
        registriesUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}${truncNote}`;
      }
      if (registriesPrecision && !progText.trimStart().startsWith('<')) {
        try {
          const prog = JSON.parse(progText);
          const pct = typeof prog.precision_pct === 'number' ? prog.precision_pct : 0;
          const target = typeof prog.target_pct === 'number' ? prog.target_pct : 95;
          registriesPrecision.textContent = `Precision: ${pct}% (target ${target}%)`;
          registriesPrecision.className = 'registries-precision ' + (pct >= target ? 'on-target' : 'below-target');
        } catch { registriesPrecision.textContent = 'Precision: —'; }
      }
    } catch (e) {
      if (registriesLoading) {
        registriesLoading.textContent = 'Could not load registries. ' + (e.message || '');
        registriesLoading.hidden = false;
      }
      if (registriesTables) registriesTables.hidden = true;
    } finally {
      if (registriesRefresh) {
        registriesRefresh.disabled = false;
        registriesRefresh.textContent = btnText || 'Refresh now';
      }
    }
  }

  function showRegistriesTab(tab) {
    activeTab = tab || 'static';
    registriesTabs.forEach((t) => t.classList.toggle('active', t.getAttribute('data-tab') === tab));
    if (registriesTables) {
      registriesTables.querySelectorAll('.registries-pane').forEach((p) => {
        p.hidden = p.getAttribute('data-pane') !== tab;
      });
    }
    // Lazy-load section data on first visit (avoids parallel full D1 dumps).
    ensureSectionLoaded(activeTab)
      .then((data) => {
        if (data) renderRegistries(data);
        if (registriesTables) {
          registriesTables.querySelectorAll('.registries-pane').forEach((p) => {
            p.hidden = p.getAttribute('data-pane') !== activeTab;
          });
        }
      })
      .catch((e) => {
        if (registriesLoading) {
          registriesLoading.textContent = 'Could not load tab. ' + (e.message || '');
          registriesLoading.hidden = false;
        }
      });
  }

  registriesTabs.forEach((t) => {
    t.addEventListener('click', () => showRegistriesTab(t.getAttribute('data-tab')));
  });
  if (registriesRefresh) {
    registriesRefresh.addEventListener('click', (e) => {
      e.preventDefault();
      loadRegistries();
    });
  }
  if (registriesExport) {
    registriesExport.addEventListener('click', () => {
      if (!lastRegistriesData) {
        loadRegistries().then(() => { if (lastRegistriesData) exportRegistries(); });
        return;
      }
      exportRegistries();
    });
  }

  function exportRegistries() {
    if (!lastRegistriesData) return;
    const payload = {
      exported_at: new Date().toISOString(),
      exported_schema_version: 2,
      registries: {
        pure_static: { primitives: lastRegistriesData.static_primitives, discoveries: lastRegistriesData.static },
        blended_dynamic: { canonical: lastRegistriesData.dynamic_canonical, discoveries: lastRegistriesData.dynamic },
        semantic_narrative: lastRegistriesData.narrative,
        interpretation: lastRegistriesData.interpretation,
        linguistic: lastRegistriesData.linguistic || [],
      },
      loop_progress: lastProgressData || null,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `motion-registries-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  loadRegistries();
})();
