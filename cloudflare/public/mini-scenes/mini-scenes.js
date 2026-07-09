/**
 * Mini-scenes gallery: recent short completed jobs for human review.
 */
const API_BASE = "";
const LIMIT = 24;
const MAX_DURATION = 6;

const listEl = document.getElementById("mini-scenes-list");
const loadingEl = document.getElementById("mini-scenes-loading");
const refreshBtn = document.getElementById("mini-scenes-refresh");

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function shortenPrompt(s, maxLen = 90) {
  if (!s) return "";
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen).trim() + "…";
}

function workflowLabel(wt) {
  if (!wt) return "main";
  return String(wt).replace(/_/g, " ");
}

async function loadMiniScenes() {
  if (!listEl) return;
  try {
    const res = await fetch(
      `${API_BASE}/api/jobs?status=completed&limit=${LIMIT}&min_duration=4&max_duration=${MAX_DURATION}`
    );
    const data = await res.json();
    loadingEl?.remove();
    if (!res.ok || !Array.isArray(data.jobs)) {
      listEl.innerHTML = '<p class="library-empty">Could not load mini-scenes.</p>';
      return;
    }
    if (data.jobs.length === 0) {
      listEl.innerHTML =
        '<p class="library-empty">No short clips yet. The balanced loop posts 5s mini-scenes as they complete.</p>';
      return;
    }
    const base = window.location.origin;
    listEl.innerHTML = data.jobs
      .map((job) => {
        const url = base + (job.download_url || `/api/jobs/${job.id}/download`);
        const fullPrompt = (job.prompt || "").trim();
        const displayPrompt = shortenPrompt(fullPrompt);
        const label = workflowLabel(job.workflow_type);
        return `
        <article class="library-card">
          <video class="library-video" src="${url}" controls playsinline preload="metadata"></video>
          <div class="library-card-body">
            <span class="library-badge library-badge--main">${escapeHtml(label)}</span>
            <p class="library-prompt" title="${escapeHtml(fullPrompt)}">${escapeHtml(displayPrompt)}</p>
            <p class="library-meta">${formatDate(job.updated_at || job.created_at)}${job.duration_seconds ? ` · ${job.duration_seconds}s` : ""}</p>
            <a href="${url}" class="library-download" download="motion-${job.id}.mp4">Download</a>
          </div>
        </article>`;
      })
      .join("");
  } catch {
    loadingEl?.remove();
    listEl.innerHTML = '<p class="library-empty">Could not load mini-scenes. Refresh to try again.</p>';
  }
}

refreshBtn?.addEventListener("click", () => {
  listEl.innerHTML = '<div class="library-loading">Loading…</div>';
  loadMiniScenes();
});

loadMiniScenes();
setInterval(() => {
  if (document.visibilityState === "visible") loadMiniScenes();
}, 60000);
