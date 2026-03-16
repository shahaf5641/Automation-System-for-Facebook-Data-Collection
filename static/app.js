const form = document.getElementById("scrape-form");
const runBtn = document.getElementById("run-btn");
const stopBtn = document.getElementById("stop-btn");
const downloadBtn = document.getElementById("download-btn");
const clearLogsBtn = document.getElementById("clear-logs-btn");
const jobState = document.getElementById("job-state");
const jobMessage = document.getElementById("job-message");
const logOutput = document.getElementById("log-output");
const progressText = document.getElementById("progress-text");
const progressPercent = document.getElementById("progress-percent");
const progressFill = document.getElementById("progress-fill");
const themeToggle = document.getElementById("theme-toggle");
const themeLabel = document.getElementById("theme-label");
const themeIcon = document.getElementById("theme-icon");
const copyEmailBtn = document.getElementById("copy-email-btn");

const CLIENT_ID_KEY = "fb_scraper_client_id";
const THEME_KEY = "fb_scraper_theme";
let currentJobId = null;
let autoScrollLogs = true;

function getClientId() {
  const existing = localStorage.getItem(CLIENT_ID_KEY);
  if (existing) return existing;
  const next = (window.crypto && window.crypto.randomUUID)
    ? window.crypto.randomUUID()
    : `client-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  localStorage.setItem(CLIENT_ID_KEY, next);
  return next;
}

const clientId = getClientId();

function applyTheme(theme) {
  const normalized = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", normalized);
  if (themeLabel) {
    themeLabel.textContent = normalized === "dark" ? "Light Mode" : "Dark Mode";
  }
  if (themeIcon) {
    themeIcon.textContent = normalized === "dark" ? "☀️" : "🌙";
  }
}

function resolveInitialTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

applyTheme(resolveInitialTheme());

if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const current = document.body.getAttribute("data-theme") || "light";
    const next = current === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

if (copyEmailBtn) {
  copyEmailBtn.addEventListener("click", async () => {
    const email = copyEmailBtn.dataset.email || "shahaf564@gmail.com";
    let copied = false;
    try {
      await navigator.clipboard.writeText(email);
      copied = true;
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = email;
      helper.setAttribute("readonly", "");
      helper.style.position = "absolute";
      helper.style.left = "-9999px";
      document.body.appendChild(helper);
      helper.select();
      copied = document.execCommand("copy");
      document.body.removeChild(helper);
    }
    const original = copyEmailBtn.textContent;
    copyEmailBtn.textContent = copied ? "Copied!" : "Copy Failed";
    setTimeout(() => {
      copyEmailBtn.textContent = original || "Copy Email";
    }, 1400);
  });
}

logOutput.addEventListener("scroll", () => {
  const threshold = 20;
  autoScrollLogs =
    logOutput.scrollTop + logOutput.clientHeight >= logOutput.scrollHeight - threshold;
});

function setBadge(status) {
  jobState.textContent = status ? status[0].toUpperCase() + status.slice(1) : "Idle";
  jobState.className = `badge ${status || "idle"}`;
}

function setProgress(percent, text) {
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  progressFill.style.width = `${safePercent}%`;
  progressPercent.textContent = `${safePercent}%`;
  progressText.textContent = text || "Ready";
}

function setJobUi(job) {
  if (!job) {
    currentJobId = null;
    setBadge("idle");
    jobMessage.textContent = "No active job.";
    setProgress(0, "Ready");
    stopBtn.disabled = true;
    downloadBtn.classList.add("disabled");
    downloadBtn.setAttribute("aria-disabled", "true");
    downloadBtn.href = "#";
    return;
  }

  currentJobId = job.job_id;
  setBadge(job.status);
  const owner = job.owner_client_id === clientId;
  if (job.status === "queued" && Number(job.queue_position) > 0) {
    jobMessage.textContent = `Queued. Position ${job.queue_position}.`;
  } else {
    jobMessage.textContent = job.message || "Working...";
  }
  setProgress(job.progress_percent, job.progress_text);
  stopBtn.disabled = !owner || !(job.status === "queued" || job.status === "running");

  if (job.status === "completed") {
    downloadBtn.classList.remove("disabled");
    downloadBtn.classList.add("download-ready");
    downloadBtn.setAttribute("aria-disabled", "false");
    downloadBtn.href = `/api/jobs/${job.job_id}/download`;
  } else {
    downloadBtn.classList.add("disabled");
    downloadBtn.classList.remove("download-ready");
    downloadBtn.setAttribute("aria-disabled", "true");
    downloadBtn.href = "#";
  }

  if (job.logs && job.logs.length) {
    const wasAtBottom = autoScrollLogs;
    logOutput.textContent = job.logs.join("\n");
    if (wasAtBottom) {
      logOutput.scrollTop = logOutput.scrollHeight;
    }
  } else {
    logOutput.textContent = "Waiting for process logs...";
  }
}

async function refreshActiveJob() {
  if (currentJobId) {
    const ownJobResponse = await fetch(`/api/jobs/${currentJobId}`);
    if (ownJobResponse.ok) {
      const ownJobData = await ownJobResponse.json();
      setJobUi(ownJobData.job);
      return;
    }
    currentJobId = null;
  }

  const response = await fetch(`/api/active-job?client_id=${encodeURIComponent(clientId)}`);
  const data = await response.json();
  if (data.job) {
    setJobUi(data.job);
    return;
  }

  setJobUi(null);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const payload = {
    search_word: document.getElementById("search_word").value.trim(),
    group_links_number: document.getElementById("group_links_number").value.trim(),
    posts_from_each_group: document.getElementById("posts_from_each_group").value.trim(),
    client_id: clientId,
  };

  runBtn.disabled = true;
  jobMessage.textContent = "Starting...";

  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  if (!response.ok) {
    jobMessage.textContent = data.error || "Could not start job.";
    runBtn.disabled = false;
    return;
  }

  setJobUi(data.job);
  runBtn.disabled = false;
});

stopBtn.addEventListener("click", async () => {
  if (!currentJobId) return;
  stopBtn.disabled = true;
  const response = await fetch(`/api/jobs/${currentJobId}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    jobMessage.textContent = data.error || "Could not stop this job.";
  }
});

clearLogsBtn.addEventListener("click", () => {
  if (!currentJobId) {
    logOutput.textContent = "Logs cleared.";
    return;
  }

  fetch(`/api/jobs/${currentJobId}/clear-logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId }),
  })
    .then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not clear logs.");
      }
      logOutput.textContent = "Logs cleared.";
      autoScrollLogs = true;
    })
    .catch((error) => {
      jobMessage.textContent = error.message || "Could not clear logs.";
    });
});

setInterval(() => {
  refreshActiveJob().catch(() => {
    jobMessage.textContent = "Could not refresh job status.";
  });
}, 1500);

refreshActiveJob().catch(() => {
  jobMessage.textContent = "Could not load job status.";
});
