/**
 * Motion — Web app: prompt → job → video
 * Logs user interactions for learning.
 */

const API_BASE = '';

const form = document.getElementById('generate-form');
const promptInput = document.getElementById('prompt');
const durationSelect = document.getElementById('duration');
const submitBtn = document.getElementById('submit-btn');
const statusEl = document.getElementById('status');
const statusText = document.getElementById('status-text');
const progressBar = document.getElementById('progress-bar');
const resultEl = document.getElementById('result');
const videoPlayer = document.getElementById('video-player');
const downloadLink = document.getElementById('download-link');
const feedbackUp = document.getElementById('feedback-up');
const feedbackDown = document.getElementById('feedback-down');
const errorEl = document.getElementById('error');
const errorText = document.getElementById('error-text');

function logEvent(eventType, jobId = null, payload = {}) {
  const body = { event_type: eventType };
  if (jobId) body.job_id = jobId;
  if (Object.keys(payload).length) body.payload = payload;
  fetch(`${API_BASE}/api/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).catch(() => {});
}

function showError(msg) {
  errorText.textContent = msg;
  errorEl.hidden = false;
  statusEl.hidden = true;
  resultEl.hidden = true;
  logEvent('error', null, { message: msg });
}

function hideError() {
  errorEl.hidden = true;
}

function setStatus(text, showProgress = false) {
  hideError();
  statusText.textContent = text;
  statusEl.hidden = false;
  progressBar.hidden = !showProgress;
  resultEl.hidden = true;
}

let currentJobId = null;

function showResult(downloadUrl) {
  hideError();
  statusEl.hidden = true;
  videoPlayer.src = downloadUrl;
  downloadLink.href = downloadUrl;
  downloadLink.download = 'motion-video.mp4';
  resultEl.hidden = false;
  feedbackUp?.classList.remove('feedback-given');
  feedbackDown?.classList.remove('feedback-given');
  // Ensure video can play with sound (no muted attribute)
  if (videoPlayer) {
    videoPlayer.removeAttribute('muted');
    videoPlayer.muted = false;
  }
  logEvent('job_completed', currentJobId, { download_url: downloadUrl });
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  const duration = parseInt(durationSelect.value, 10);
  submitBtn.disabled = true;
  setStatus('Creating job...', false);

  try {
    const res = await fetch(`${API_BASE}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, duration_seconds: duration }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to create job');

    currentJobId = data.id;
    logEvent('prompt_submitted', currentJobId, { prompt, duration });

    setStatus('Generating your video... (this usually takes a few minutes)', true);
    await pollJob(currentJobId);
  } catch (err) {
    showError(err.message || 'Something went wrong');
  } finally {
    submitBtn.disabled = false;
  }
});

async function pollJob(jobId) {
  const maxAttempts = 300;
  const intervalMs = 1000;

  for (let i = 0; i < maxAttempts; i++) {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    const job = await res.json();
    if (!res.ok) throw new Error(job.error || 'Failed to fetch job');

    if (job.status === 'completed' && job.download_url) {
      const base = window.location.origin;
      const url = base + job.download_url;
      showResult(url);
      return;
    }

    if (job.status === 'failed') {
      throw new Error('Video generation failed');
    }

    await new Promise((r) => setTimeout(r, intervalMs));
  }

  throw new Error('Generation timed out. Your video may still be processing — try refreshing or check back later.');
}

videoPlayer.addEventListener('play', () => {
  logEvent('video_played', currentJobId);
}, { once: true });

downloadLink.addEventListener('click', () => {
  logEvent('download_clicked', currentJobId);
});

function submitFeedback(rating) {
  if (!currentJobId) return;
  feedbackUp?.classList.add('feedback-given');
  feedbackDown?.classList.add('feedback-given');
  fetch(`${API_BASE}/api/jobs/${currentJobId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating }),
  }).catch(() => {});
}

feedbackUp?.addEventListener('click', () => submitFeedback(2));
feedbackDown?.addEventListener('click', () => submitFeedback(1));

// Library: recent completed videos (successfully generated — see progress)
const libraryList = document.getElementById('library-list');
const libraryLoading = document.getElementById('library-loading');
const libraryRefresh = document.getElementById('library-refresh');

const LIBRARY_AUTO_REFRESH_MS = 45000; // 45s when tab visible

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const LIBRARY_DISPLAY_LIMIT = 6;

function workflowLabel(wt) {
  if (wt === 'explorer') return 'Explore';
  if (wt === 'exploiter') return 'Exploit';
  if (wt === 'web') return 'Web';
  if (wt === 'main') return 'Main';
  return 'Loop';
}

function workflowBadgeClass(wt) {
  if (wt === 'explorer' || wt === 'exploiter' || wt === 'web' || wt === 'main') return `library-badge-${wt}`;
  return 'library-badge-loop';
}

function shortenPrompt(promptText, maxLen = 42) {
  const s = (promptText || '').trim();
  if (!s) return '';
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen).trim() + '…';
}

async function loadLibrary() {
  if (!libraryList) return;
  try {
    const res = await fetch(`${API_BASE}/api/jobs?status=completed&limit=${LIBRARY_DISPLAY_LIMIT}`);
    const data = await res.json();
    libraryLoading?.remove();
    if (!res.ok || !Array.isArray(data.jobs)) {
      libraryList.innerHTML = '<p class="library-empty">No videos yet. Generate one above or wait for the loop.</p>';
      return;
    }
    if (data.jobs.length === 0) {
      libraryList.innerHTML = '<p class="library-empty">No videos yet. Generate one above or wait for the loop.</p>';
      return;
    }
    const base = window.location.origin;
    libraryList.innerHTML = data.jobs.map((job) => {
      const url = base + job.download_url;
      const fullPrompt = (job.prompt || '').trim();
      const displayPrompt = shortenPrompt(fullPrompt);
      const wt = job.workflow_type || null;
      const label = workflowLabel(wt);
      const badgeClass = workflowBadgeClass(wt);
      const badge = `<span class="library-badge ${badgeClass}">${escapeHtml(label)}</span>`;
      return `
        <article class="library-card">
          <video class="library-video" src="${url}" controls playsinline preload="metadata" data-has-audio="true"></video>
          <div class="library-card-body">
            ${badge}
            <p class="library-prompt" title="${escapeHtml(fullPrompt)}">${escapeHtml(displayPrompt)}</p>
            <p class="library-meta">${formatDate(job.updated_at || job.created_at)}${job.duration_seconds ? ` · ${job.duration_seconds}s` : ''}</p>
            <a href="${url}" class="library-download" download="motion-${job.id}.mp4">Download</a>
          </div>
        </article>`;
    }).join('');
  } catch {
    libraryLoading?.remove();
    libraryList.innerHTML = '<p class="library-empty">Could not load library. Refresh to try again.</p>';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

libraryRefresh?.addEventListener('click', () => {
  libraryList.innerHTML = '<div class="library-loading">Loading…</div>';
  loadLibrary();
});

// Auto-refresh library when tab is visible
let libraryRefreshTimer = null;
function scheduleLibraryRefresh() {
  if (document.visibilityState === 'visible' && libraryList) {
    libraryRefreshTimer = setTimeout(() => {
      loadLibrary();
      scheduleLibraryRefresh();
    }, LIBRARY_AUTO_REFRESH_MS);
  }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && libraryRefreshTimer) {
    clearTimeout(libraryRefreshTimer);
    libraryRefreshTimer = null;
  } else if (document.visibilityState === 'visible') {
    scheduleLibraryRefresh();
  }
});

loadLibrary();
scheduleLibraryRefresh();

// Loop: control automated Railway loop via API
const LOOP_POLL_MS = 20000;
let loopPollTimer = null;

const loopEnabled = document.getElementById('loop-enabled');
const loopStatusBadge = document.getElementById('loop-status-badge');
const loopDuration = document.getElementById('loop-duration');
const loopDelay = document.getElementById('loop-delay');
const loopExploit = document.getElementById('loop-exploit');
const loopExploitLabel = document.getElementById('loop-exploit-label');
const loopSave = document.getElementById('loop-save');
const loopRunCount = document.getElementById('loop-run-count');
const loopGoodCount = document.getElementById('loop-good-count');
const loopPrecision = document.getElementById('loop-precision');
const loopLastRun = document.getElementById('loop-last-run');
const loopLastPrompt = document.getElementById('loop-last-prompt');
const loopRecent = document.getElementById('loop-recent');

function formatLoopDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  if (diffMs < 60000) return 'Just now';
  if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function loadLoopStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/loop/status`);
    const text = await res.text();
    if (text.trimStart().startsWith('<')) throw new Error('API unavailable');
    let data;
    try { data = JSON.parse(text); } catch { throw new Error('Invalid response'); }
    if (!res.ok) throw new Error(data.error || 'Failed to load loop status');

    const cfg = data.config || {};
    loopEnabled.checked = cfg.enabled !== false;
    loopStatusBadge.textContent = cfg.enabled !== false ? 'Running' : 'Paused';
    loopStatusBadge.className = 'loop-badge ' + (cfg.enabled !== false ? 'running' : 'paused');

    const durationSec = typeof cfg.duration_seconds === 'number' ? Math.max(1, Math.min(60, cfg.duration_seconds)) : 1;
    if (loopDuration) {
      loopDuration.value = String(durationSec);
      if (![1,2,3,5,6,10,15,30].includes(durationSec)) loopDuration.value = '1';
    }
    loopDelay.value = typeof cfg.delay_seconds === 'number' ? cfg.delay_seconds : 30;
    const ratio = typeof cfg.exploit_ratio === 'number' ? cfg.exploit_ratio : 0.7;
    loopExploit.value = Math.round(ratio * 100);
    loopExploitLabel.textContent = `${Math.round(ratio * 100)}% exploit`;

    loopRunCount.textContent = `Runs: ${typeof data.run_count === 'number' ? data.run_count : 0}`;
    loopGoodCount.textContent = `Good prompts: ${typeof data.good_prompts_count === 'number' ? data.good_prompts_count : 0}`;
    loopLastRun.textContent = `Last run: ${formatLoopDate(data.last_run_at)}`;
    try {
      const progRes = await fetch(`${API_BASE}/api/loop/progress?last=20`);
      const progText = await progRes.text();
      if (!progText.trimStart().startsWith('<')) {
        const prog = JSON.parse(progText);
        const pct = typeof prog.precision_pct === 'number' ? prog.precision_pct : 0;
        const withL = typeof prog.runs_with_learning === 'number' ? prog.runs_with_learning : 0;
        const total = typeof prog.total_runs === 'number' ? prog.total_runs : 0;
        loopPrecision.textContent = `Precision: ${pct}% (${withL}/${total})`;
        loopPrecision.title = `Runs with learning in last ${total} completed jobs; target 95%`;
      } else loopPrecision.textContent = '—';
    } catch { loopPrecision.textContent = '—'; }

    if (data.last_prompt) {
      loopLastPrompt.textContent = `"${data.last_prompt}"`;
      loopLastPrompt.hidden = false;
    } else {
      loopLastPrompt.hidden = true;
    }

    const runs = data.recent_runs || [];
    const runLabel = (wt) => (wt === 'explorer' ? 'Explore' : wt === 'exploiter' ? 'Exploit' : wt === 'web' ? 'Web' : wt === 'main' ? 'Main' : 'Loop');
    const runBadgeClass = (wt) => (wt === 'explorer' || wt === 'exploiter' || wt === 'web' || wt === 'main' ? `loop-badge-${wt}` : 'loop-badge-loop');
    loopRecent.innerHTML = runs.length
      ? runs.map((r) => {
          const label = runLabel(r.workflow_type);
          const shortPrompt = shortenPrompt(r.prompt || r.id, 50);
          return `<li><span class="loop-badge ${runBadgeClass(r.workflow_type)}">${escapeHtml(label)}</span> <a href="${window.location.origin}/api/jobs/${r.id}/download" download title="${escapeHtml((r.prompt || '').trim())}">${escapeHtml(shortPrompt || r.id)}</a> · ${formatLoopDate(r.updated_at)}</li>`;
        }).join('')
      : '<li>No recent runs</li>';
  } catch (e) {
    loopStatusBadge.textContent = 'Error';
    loopStatusBadge.className = 'loop-badge error';
    loopRunCount.textContent = '—';
    loopGoodCount.textContent = '—';
    if (loopPrecision) loopPrecision.textContent = '—';
    loopLastRun.textContent = '—';
    loopLastPrompt.hidden = true;
    loopRecent.innerHTML = '<li>Could not load status</li>';
  }
}

function scheduleLoopPoll() {
  if (document.visibilityState !== 'visible') return;
  loopPollTimer = setTimeout(() => {
    loadLoopStatus();
    scheduleLoopPoll();
  }, LOOP_POLL_MS);
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && loopPollTimer) {
    clearTimeout(loopPollTimer);
    loopPollTimer = null;
  } else if (document.visibilityState === 'visible') {
    loadLoopStatus();
    scheduleLoopPoll();
  }
});

loopExploit?.addEventListener('input', () => {
  const v = parseInt(loopExploit.value, 10);
  loopExploitLabel.textContent = `${v}% exploit`;
});

loopSave?.addEventListener('click', async () => {
  const enabled = loopEnabled.checked;
  const duration_seconds = Math.max(1, Math.min(60, parseInt(loopDuration?.value || '1', 10) || 1));
  const delay_seconds = Math.max(0, Math.min(600, parseInt(loopDelay.value, 10) || 30));
  const exploit_ratio = Math.max(0, Math.min(1, parseInt(loopExploit.value, 10) / 100));

  const originalText = loopSave.textContent;
  loopSave.disabled = true;
  loopSave.textContent = '';
  loopSave.classList.add('btn-saving');
  const spinner = document.createElement('span');
  spinner.className = 'btn-spinner';
  spinner.setAttribute('aria-hidden', 'true');
  loopSave.appendChild(spinner);

  try {
    const res = await fetch(`${API_BASE}/api/loop/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, duration_seconds, delay_seconds, exploit_ratio }),
    });
    const text = await res.text();
    if (text.trimStart().startsWith('<')) throw new Error('Server returned a page instead of data. The API may be misconfigured or the loop config endpoint is not available.');
    let data;
    try { data = JSON.parse(text); } catch { throw new Error('Invalid response from server. Try again or check the API.'); }
    if (!res.ok) throw new Error(data.details ? `${data.error || 'Failed to save config'}: ${data.details}` : (data.error || 'Failed to save config'));
    loopSave.textContent = 'Saved';
    loopSave.classList.remove('btn-saving');
    loopSave.classList.add('btn-saved');
    loadLoopStatus();
    setTimeout(() => {
      loopSave.textContent = originalText;
      loopSave.classList.remove('btn-saved');
      loopSave.disabled = false;
    }, 1500);
  } catch (e) {
    loopSave.removeChild(spinner);
    loopSave.textContent = originalText;
    loopSave.classList.remove('btn-saving');
    loopSave.disabled = false;
    alert(e.message || 'Could not save loop settings');
  }
});

loopEnabled?.addEventListener('change', async () => {
  const enabled = loopEnabled.checked;
  try {
    const res = await fetch(`${API_BASE}/api/loop/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    const text = await res.text();
    if (text.trimStart().startsWith('<')) throw new Error('Server returned a page instead of data. The API may be misconfigured.');
    let data;
    try { data = JSON.parse(text); } catch { throw new Error('Invalid response from server.'); }
    if (!res.ok) throw new Error(data.error || 'Failed to update');
    loopStatusBadge.textContent = enabled ? 'Running' : 'Paused';
    loopStatusBadge.className = 'loop-badge ' + (enabled ? 'running' : 'paused');
  } catch (e) {
    loopEnabled.checked = !enabled;
    alert(e.message || 'Could not update loop');
  }
});

if (loopEnabled) {
  loadLoopStatus();
  scheduleLoopPoll();
}

// ——— Registries (manual refresh only) ———
const registriesLoading = document.getElementById('registries-loading');
const registriesTables = document.getElementById('registries-tables');
const registriesPrecision = document.getElementById('registries-precision');
const registriesUpdated = document.getElementById('registries-updated');
const registriesRefresh = document.getElementById('registries-refresh');
const registriesTabs = document.querySelectorAll('.registries-tab');
const registriesContent = document.getElementById('registries-content');

function registriesTable(headers, rows) {
  const th = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('');
  const trs = rows.map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(String(c))}</td>`).join('')}</tr>`).join('');
  return `<table class="registries-table"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
}

function depthBreakdownStr(d) {
  if (!d || typeof d !== 'object') return '—';
  const parts = Object.entries(d).map(([k, v]) => `${k}: ${Number(v).toFixed(0)}%`).filter(Boolean);
  return parts.length ? parts.join(', ') : '—';
}

function renderRegistries(data) {
  if (!data || !registriesTables) return;
  const staticPrimitives = data.static_primitives || {};
  const dynamicCanonical = data.dynamic_canonical || {};
  const static_ = data.static || {};
  const dynamic = data.dynamic || {};
  const narrative = data.narrative || {};
  const interpretation = data.interpretation || [];

  const colorPrimaries = (staticPrimitives.color_primaries || []).map((p) => `${p.name} (${p.r},${p.g},${p.b})`).join(' · ') || '—';
  const soundPrimaries = (staticPrimitives.sound_primaries || []).join(' · ') || '—';
  const staticSoundHeaders = ['Key', 'Name', 'Count'].concat(static_.sound && static_.sound.some((s) => s.strength_pct != null) ? ['Strength %'] : []);
  const staticSoundRows = static_.sound && static_.sound.length
    ? static_.sound.map((s) => {
        const row = [s.key, s.name, s.count];
        if (static_.sound.some((x) => x.strength_pct != null))
          row.push(s.strength_pct != null ? (s.strength_pct * 100).toFixed(0) + '%' : '—');
        return row;
      })
    : [];
  const staticHtml = `
    <div class="registries-pane" data-pane="static">
      <p class="registries-primitives-desc">Pure primitives (single frame/pixel or single sample). Color depth % = luminance vs black/white. Sound primitives = actual noises (silence, rumble, tone, hiss); strength % recorded per discovery.</p>
      <h3 class="registries-pane-title">Pure — Color primitives (origin)</h3>
      <p class="registries-primitives">${escapeHtml(colorPrimaries)}</p>
      <h3 class="registries-pane-title">Pure — Colors (per-frame discoveries)</h3>
      ${static_.colors && static_.colors.length
        ? registriesTable(['Key', 'Name', 'Count', 'RGB', 'Depth %', 'Depth (B/W)'], static_.colors.map((c) => [
            c.key, c.name, c.count, `(${c.r},${c.g},${c.b})`,
            c.depth_pct != null ? c.depth_pct.toFixed(1) + '%' : '—',
            depthBreakdownStr(c.depth_breakdown),
          ]))
        : '<p class="registries-empty">No static colors yet.</p>'}
      <h3 class="registries-pane-title">Pure — Sound primitives (origin noises)</h3>
      <p class="registries-primitives">${escapeHtml(soundPrimaries)}</p>
      <h3 class="registries-pane-title">Pure — Sound (per-frame discoveries)</h3>
      ${static_.sound && static_.sound.length
        ? registriesTable(staticSoundHeaders, staticSoundRows)
        : '<p class="registries-empty">No static sound yet.</p>'}
    </div>`;

  const dynamicHtml = `
    <div class="registries-pane" data-pane="dynamic">
      <p class="registries-primitives-desc">Blended: categories (gradient, motion, camera, sound, etc.) and elements (named discoveries). Time and/or distance; kick, snare, bass, etc. live here.</p>
      <h3 class="registries-pane-title">Blended — Gradient (canonical → discoveries)</h3>
      <p class="registries-primitives">Canonical: ${escapeHtml((dynamicCanonical.gradient_type || []).join(', ') || '—')}</p>
      ${dynamic.gradient && dynamic.gradient.length
        ? registriesTable(['Name', 'Key', 'Depth %', 'Depth vs primitives'], dynamic.gradient.map((g) => [g.name, g.key, (g.depth_pct != null ? g.depth_pct.toFixed(1) : '') + '%', depthBreakdownStr(g.depth_breakdown)]))
        : '<p class="registries-empty">No gradient discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Camera</h3>
      <p class="registries-primitives">Canonical: ${escapeHtml((dynamicCanonical.camera_motion || []).join(', ') || '—')}</p>
      ${dynamic.camera && dynamic.camera.length
        ? registriesTable(['Name', 'Key', 'Depth %', 'Depth vs primitives'], dynamic.camera.map((c) => [c.name, c.key, (c.depth_pct != null ? c.depth_pct.toFixed(1) : '') + '%', depthBreakdownStr(c.depth_breakdown)]))
        : '<p class="registries-empty">No camera discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Motion</h3>
      <p class="registries-primitives">Canonical: ${escapeHtml((dynamicCanonical.motion || []).join(', ') || '—')}</p>
      ${dynamic.motion && dynamic.motion.length
        ? registriesTable(['Key', 'Name', 'Trend', 'Count'], dynamic.motion.map((m) => [m.key, m.name, m.trend || '—', m.count]))
        : '<p class="registries-empty">No motion discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Sound</h3>
      <p class="registries-primitives">Canonical: ${escapeHtml((dynamicCanonical.sound || []).join(', ') || '—')}</p>
      ${dynamic.sound && dynamic.sound.length
        ? registriesTable(['Name', 'Key', 'Depth %', 'Depth vs primitives'], dynamic.sound.map((s) => [
            s.name || '—',
            typeof s.key === 'string' ? s.key : (s.tempo || s.mood || s.presence || '—'),
            (s.depth_pct != null ? s.depth_pct.toFixed(1) : '') + '%',
            depthBreakdownStr(s.depth_breakdown),
          ]))
        : '<p class="registries-empty">No sound discoveries yet.</p>'}
      <h3 class="registries-pane-title">Blended — Colors (learned)</h3>
      ${dynamic.colors && dynamic.colors.length
        ? registriesTable(['Key', 'Name', 'Count', 'Depth %', 'Depth vs primitives'], dynamic.colors.map((c) => [c.key, c.name, c.count, (c.depth_pct != null ? c.depth_pct.toFixed(1) : '') + '%', depthBreakdownStr(c.depth_breakdown)]))
        : '<p class="registries-empty">No learned colors yet.</p>'}
      <h3 class="registries-pane-title">Blended — Blends (other)</h3>
      ${dynamic.blends && dynamic.blends.length
        ? registriesTable(['Name', 'Domain', 'Key', 'Depth %', 'Depth vs primitives'], dynamic.blends.map((b) => [b.name, b.domain || '—', (b.key || '').slice(0, 40), (b.depth_pct != null ? b.depth_pct.toFixed(1) : '') + '%', depthBreakdownStr(b.depth_breakdown)]))
        : '<p class="registries-empty">No other blends yet.</p>'}
    </div>`;

  const narrativeHtml = `
    <div class="registries-pane" data-pane="narrative">
      <p class="registries-primitives-desc">Semantic: blends in categories (plot, setting, dialogue, genre, mood, style). Elements are named entries with depth where applicable.</p>
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
      <p class="registries-primitives-desc">Interpretation: resolved user prompts (prompt → instruction). The system prepares for everything until the user sends input; this registry stores what was interpreted.</p>
      <h3 class="registries-pane-title">Interpretation — Resolved prompts</h3>
      ${interpretation && interpretation.length
        ? registriesTable(['Prompt', 'Instruction summary', 'Updated'], interpretation.map((i) => [
            (i.prompt || '').slice(0, 60) + (i.prompt && i.prompt.length > 60 ? '…' : ''),
            instructionSummary(i.instruction),
            i.updated_at ? new Date(i.updated_at).toLocaleString() : '—',
          ]))
        : '<p class="registries-empty">No resolved interpretations yet.</p>'}
    </div>`;

  registriesTables.innerHTML = staticHtml + dynamicHtml + narrativeHtml + interpretationHtml;
  registriesTables.hidden = false;
  if (registriesLoading) registriesLoading.hidden = true;
  registriesTables.querySelectorAll('.registries-pane').forEach((p, i) => {
    p.hidden = i !== 0;
  });
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
  try {
    const [regRes, progRes] = await Promise.all([
      fetch(`${API_BASE}/api/registries?limit=200`),
      fetch(`${API_BASE}/api/loop/progress?last=20`),
    ]);
    const regText = await regRes.text();
    const progText = await progRes.text();
    if (regText.trimStart().startsWith('<')) throw new Error('Registries API unavailable');
    let data;
    try { data = JSON.parse(regText); } catch { throw new Error('Invalid registries response'); }
    if (!regRes.ok) throw new Error(data.error || 'Failed to load registries');
    renderRegistries(data);
    registriesUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
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
  registriesTabs.forEach((t) => t.classList.toggle('active', t.getAttribute('data-tab') === tab));
  registriesTables.querySelectorAll('.registries-pane').forEach((p) => {
    p.hidden = p.getAttribute('data-pane') !== tab;
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
loadRegistries();

// Match right column height to left so registries-content doesn't exceed
function syncColumnHeights() {
  if (window.innerWidth < 768) return;
  const left = document.querySelector('.main-grid .grid-left');
  const right = document.querySelector('.main-grid .dashboard-right');
  if (!left || !right) return;
  const h = left.offsetHeight;
  right.style.maxHeight = h + 'px';
}
syncColumnHeights();
window.addEventListener('resize', syncColumnHeights);
// Re-sync after registries load (content may affect left height)
const ob = new ResizeObserver(syncColumnHeights);
const gridLeft = document.querySelector('.main-grid .grid-left');
if (gridLeft) ob.observe(gridLeft);
