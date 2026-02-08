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

async function loadLibrary() {
  if (!libraryList) return;
  try {
    const res = await fetch(`${API_BASE}/api/jobs?status=completed&limit=24`);
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
      const prompt = (job.prompt || '').slice(0, 80) + (job.prompt && job.prompt.length > 80 ? '…' : '');
      return `
        <article class="library-card">
          <video class="library-video" src="${url}" controls playsinline preload="metadata"></video>
          <div class="library-card-body">
            <p class="library-prompt">${escapeHtml(prompt)}</p>
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
