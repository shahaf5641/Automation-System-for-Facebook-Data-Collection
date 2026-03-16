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

let currentJobId = null;

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
  jobMessage.textContent = job.message || "Working...";
  setProgress(job.progress_percent, job.progress_text);
  stopBtn.disabled = !(job.status === "queued" || job.status === "running");

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
    logOutput.textContent = job.logs.join("\n");
    logOutput.scrollTop = logOutput.scrollHeight;
  } else {
    logOutput.textContent = "Waiting for process logs...";
  }
}

async function refreshActiveJob() {
  const response = await fetch("/api/active-job");
  const data = await response.json();
  if (data.job) {
    setJobUi(data.job);
    return;
  }

  if (currentJobId) {
    const finishedResponse = await fetch(`/api/jobs/${currentJobId}`);
    if (finishedResponse.ok) {
      const finishedData = await finishedResponse.json();
      setJobUi(finishedData.job);
      return;
    }
  }

  setJobUi(null);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const payload = {
    search_word: document.getElementById("search_word").value.trim(),
    group_links_number: document.getElementById("group_links_number").value.trim(),
    posts_from_each_group: document.getElementById("posts_from_each_group").value.trim(),
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
  await fetch(`/api/jobs/${currentJobId}/stop`, { method: "POST" });
});

clearLogsBtn.addEventListener("click", () => {
  if (!currentJobId) {
    logOutput.textContent = "Logs cleared.";
    return;
  }

  fetch(`/api/jobs/${currentJobId}/clear-logs`, { method: "POST" })
    .then(() => {
      logOutput.textContent = "Logs cleared.";
    })
    .catch(() => {
      jobMessage.textContent = "Could not clear logs.";
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
