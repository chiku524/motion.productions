/**
 * Mini-scenes gallery: recent short completed jobs for human review.
 * Thumbs up promotes the prompt into loop good_prompts (exploit pool).
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

function submitFeedback(jobId, rating, btn) {
  if (!jobId) return;
  const card = btn?.closest?.(".library-card");
  card?.querySelectorAll?.(".btn-feedback")?.forEach((b) => b.classList.add("feedback-given"));
  fetch(`${API_BASE}/api/jobs/${jobId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  }).catch(() => {});
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
        const id = escapeHtml(job.id);
        return `
        <article class="library-card" data-job-id="${id}">
          <video class="library-video" src="${url}" controls playsinline preload="metadata"></video>
          <div class="library-card-body">
            <span class="library-badge library-badge--main">${escapeHtml(label)}</span>
            <p class="library-prompt" title="${escapeHtml(fullPrompt)}">${escapeHtml(displayPrompt)}</p>
            <p class="library-meta">${formatDate(job.updated_at || job.created_at)}${job.duration_seconds ? ` · ${job.duration_seconds}s` : ""}</p>
            <div class="library-feedback">
              <button type="button" class="btn-feedback" data-rating="2" data-job="${id}" title="Good mini-scene — teach the loop" aria-label="Thumbs up">👍</button>
              <button type="button" class="btn-feedback" data-rating="1" data-job="${id}" title="Not useful" aria-label="Thumbs down">👎</button>
              <a href="${url}" class="library-download" download="motion-${id}.mp4">Download</a>
            </div>
          </div>
        </article>`;
      })
      .join("");

    listEl.querySelectorAll(".btn-feedback").forEach((btn) => {
      btn.addEventListener("click", () => {
        const jobId = btn.getAttribute("data-job");
        const rating = parseInt(btn.getAttribute("data-rating") || "0", 10);
        submitFeedback(jobId, rating, btn);
      });
    });
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
