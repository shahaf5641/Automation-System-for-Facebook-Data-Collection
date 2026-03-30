from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from facebook_scraper.config import Settings, SettingsError
from facebook_scraper.job_store import BaseJobStore, build_job_store
from facebook_scraper.run_history_store import BaseRunHistoryStore, build_run_history_store
from facebook_scraper.runner import DriverControl, configure_logging, run_scraper

APP_TITLE = "Facebook Data Extractor"
BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "web_outputs"
PROFILES_DIR = BASE_DIR / "web_profiles"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
logger = logging.getLogger("facebook_scraper.web")


class JobLogHandler(logging.Handler):
    def __init__(self, job: "ScrapeJob") -> None:
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("facebook_scraper"):
            return
        try:
            self.job.ingest_log(record.getMessage(), record.levelno)
            _sync_job(self.job)
        except Exception:
            self.handleError(record)


@dataclass
class ScrapeJob:
    job_id: str
    settings: Settings
    owner_client_id: str
    control: DriverControl = field(default_factory=DriverControl)
    status: str = "queued"
    message: str = "Waiting to start"
    output_file: str = ""
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    target_posts: int = 0
    captured_posts: int = 0
    progress_percent: int = 0
    progress_text: str = "Ready"
    current_group: int = 0
    total_groups: int = 0
    searching_groups_announced: bool = False
    queue_position: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append_log(self, line: str) -> None:
        with self.lock:
            self.logs.append(line)
            self.updated_at = time.time()

    def ingest_log(self, message: str, levelno: int) -> None:
        with self.lock:
            friendly = self._friendly_log_message(message, levelno)
            if not friendly:
                return
            self.logs.append(friendly)
            self.updated_at = time.time()

    def _friendly_log_message(self, message: str, levelno: int) -> str | None:
        if levelno >= logging.ERROR:
            self.progress_text = "Process failed"
            return "Something went wrong during processing."

        if "Waiting for manual Facebook login" in message:
            self.progress_percent = max(self.progress_percent, 10)
            self.progress_text = "Waiting for Facebook login"
            return "Waiting for facebook login"

        if "Already logged in" in message:
            self.progress_percent = max(self.progress_percent, 18)
            self.progress_text = "Login ready"
            return "Login succesfully"

        if "Manual login completed" in message:
            self.progress_percent = max(self.progress_percent, 18)
            self.progress_text = "Login ready"
            return "Login succesfully"

        if "Public groups toggle" in message:
            return None

        if "Search round found" in message:
            self.progress_percent = max(self.progress_percent, 28)
            self.progress_text = "Searching groups"
            if self.searching_groups_announced:
                return None
            self.searching_groups_announced = True
            return "Searching Groups..."

        groups_collected = re.search(r"Collected (\d+) group links\.", message)
        if groups_collected:
            self.progress_percent = max(self.progress_percent, 34)
            self.progress_text = "Groups list ready"
            return None

        opening_group = re.search(r"\[(\d+)/(\d+)\] Opening group:", message)
        if opening_group:
            self.current_group = int(opening_group.group(1))
            self.total_groups = int(opening_group.group(2))
            self.progress_percent = max(self.progress_percent, 40)
            self.progress_text = f"Scanning group {self.current_group}/{self.total_groups}"
            return f"Opening group {self.current_group}/{self.total_groups}..."

        captured_post = re.search(r"Captured post (\d+)/(\d+) from group (\d+):", message)
        if captured_post:
            self.captured_posts += 1
            if self.target_posts > 0:
                ratio = min(self.captured_posts / self.target_posts, 1.0)
                self.progress_percent = max(self.progress_percent, 40 + int(ratio * 55))
            self.progress_text = f"Collected {self.captured_posts}/{self.target_posts} posts"
            return f"Collected {self.captured_posts}/{self.target_posts} posts."

        finished_group = re.search(r"Finished group (\d+) with (\d+) posts\.", message)
        if finished_group:
            group_idx = int(finished_group.group(1))
            posts = int(finished_group.group(2))
            return f"Finished group {group_idx}. Added {posts} posts."

        if "Completed target posts by using" in message:
            return "Needed extra groups to complete your requested amount."

        low_posts = re.search(r"Only (\d+)/(\d+) posts were collected\.", message)
        if low_posts:
            got = int(low_posts.group(1))
            wanted = int(low_posts.group(2))
            return f"Completed with partial results: {got}/{wanted} posts."

        finished = re.search(r"Done\. Saved (\d+) records", message)
        if finished:
            total = int(finished.group(1))
            self.progress_percent = 100
            self.progress_text = "Completed"
            return f"Done. CSV is ready with {total} rows."

        if "Run stopped by user" in message:
            self.progress_text = "Stopped"
            return "Process stopped by user."

        if "Run was cancelled before start" in message:
            self.progress_text = "Stopped"
            return "Process was cancelled before start."

        return None

    def snapshot(self) -> dict:
        with self.lock:
            output_ready = bool(self.output_file and Path(self.output_file).exists())
            return {
                "job_id": self.job_id,
                "status": self.status,
                "message": self.message,
                "output_file": self.output_file,
                "output_ready": output_ready,
                "logs": list(self.logs),
                "progress_percent": self.progress_percent,
                "progress_text": self.progress_text,
                "captured_posts": self.captured_posts,
                "target_posts": self.target_posts,
                "owner_client_id": self.owner_client_id,
                "queue_position": self.queue_position,
                "search_word": self.settings.search_word,
                "group_links_number": self.settings.group_links_number,
                "posts_from_each_group": self.settings.posts_from_each_group,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "finished_at": self.finished_at,
            }

    def to_record(self) -> dict:
        with self.lock:
            return {
                "job_id": self.job_id,
                "settings": asdict(self.settings),
                "owner_client_id": self.owner_client_id,
                "status": self.status,
                "message": self.message,
                "output_file": self.output_file,
                "logs": list(self.logs),
                "target_posts": self.target_posts,
                "captured_posts": self.captured_posts,
                "progress_percent": self.progress_percent,
                "progress_text": self.progress_text,
                "current_group": self.current_group,
                "total_groups": self.total_groups,
                "searching_groups_announced": self.searching_groups_announced,
                "queue_position": self.queue_position,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "finished_at": self.finished_at,
            }

    @classmethod
    def from_record(cls, record: dict) -> "ScrapeJob":
        settings = Settings(**record["settings"])
        job = cls(
            job_id=record["job_id"],
            settings=settings,
            owner_client_id=record["owner_client_id"],
        )
        job.status = record.get("status", "queued")
        job.message = record.get("message", "Waiting to start")
        job.output_file = record.get("output_file", "")
        job.logs = deque(record.get("logs", []), maxlen=400)
        job.target_posts = int(record.get("target_posts", 0) or 0)
        job.captured_posts = int(record.get("captured_posts", 0) or 0)
        job.progress_percent = int(record.get("progress_percent", 0) or 0)
        job.progress_text = record.get("progress_text", "Ready")
        job.current_group = int(record.get("current_group", 0) or 0)
        job.total_groups = int(record.get("total_groups", 0) or 0)
        job.searching_groups_announced = bool(record.get("searching_groups_announced", False))
        job.queue_position = int(record.get("queue_position", 0) or 0)
        job.created_at = float(record.get("created_at", time.time()) or time.time())
        job.updated_at = float(record.get("updated_at", job.created_at) or job.created_at)
        job.finished_at = float(record.get("finished_at", 0.0) or 0.0)
        return job


jobs: dict[str, ScrapeJob] = {}
jobs_lock = threading.Lock()
active_job_id: str | None = None
waiting_job_ids: deque[str] = deque()
job_store: BaseJobStore = build_job_store()
run_history_store: BaseRunHistoryStore = build_run_history_store()


def _sync_job(job: ScrapeJob) -> None:
    with job.lock:
        job.updated_at = time.time()
    record = job.to_record()
    job_store.save_job(job.job_id, record)
    run_history_store.upsert_job(record)


def _cleanup_stores() -> None:
    redis_retention_hours = float(os.getenv("REDIS_RETENTION_HOURS", "48") or 48)
    history_retention_days = float(os.getenv("RUN_HISTORY_RETENTION_DAYS", "30") or 30)
    now = time.time()
    redis_cutoff = now - (redis_retention_hours * 3600)
    history_cutoff = now - (history_retention_days * 86400)

    try:
        removed_jobs = job_store.cleanup_terminal_jobs(redis_cutoff)
        if removed_jobs:
            logger.info("Cleaned up %s old terminal jobs from %s store.", removed_jobs, job_store.backend_name)
    except Exception as exc:
        logger.warning("Could not clean up %s store: %s", job_store.backend_name, exc)

    try:
        removed_history = run_history_store.cleanup_old_runs(history_cutoff)
        if removed_history:
            logger.info(
                "Cleaned up %s old runs from %s history store.",
                removed_history,
                run_history_store.backend_name,
            )
    except Exception as exc:
        logger.warning("Could not clean up %s history store: %s", run_history_store.backend_name, exc)


def _list_jobs_for_client(client_id: str) -> list[dict]:
    if not client_id:
        return []
    history_jobs = run_history_store.list_jobs_for_client(client_id)
    if history_jobs:
        return history_jobs
    matching: list[ScrapeJob] = []
    with jobs_lock:
        for job_id in job_store.load_all_jobs().keys():
            job = _load_job(job_id)
            if job is not None and job.owner_client_id == client_id:
                matching.append(job)
    matching.sort(key=lambda job: (job.created_at, job.job_id), reverse=True)
    return [job.snapshot() for job in matching]


def _delete_job_artifacts(output_file: str) -> None:
    path = Path(str(output_file or "").strip())
    if path.exists():
        try:
            path.unlink()
        except OSError:
            logger.warning("Could not delete output file: %s", path)


def _delete_job_for_owner(job_id: str, client_id: str) -> tuple[bool, str]:
    job = _load_job(job_id)
    if job is not None:
        if job.owner_client_id != client_id:
            return False, "Only the job owner can delete this run."
        if job.status in {"queued", "running"}:
            return False, "You can only delete completed, failed, or stopped runs."
        output_file = job.output_file
        with jobs_lock:
            jobs.pop(job_id, None)
            job_store.delete_job(job_id)
            _refresh_queue_positions_locked()
        run_history_store.delete_job(job_id)
        _delete_job_artifacts(output_file)
        return True, ""

    record = run_history_store.get_job(job_id)
    if record is None:
        return False, "Job not found."
    if str(record.get("owner_client_id", "")).strip() != client_id:
        return False, "Only the job owner can delete this run."
    status = str(record.get("status", "")).strip()
    if status in {"queued", "running"}:
        return False, "You can only delete completed, failed, or stopped runs."
    run_history_store.delete_job(job_id)
    job_store.delete_job(job_id)
    _delete_job_artifacts(str(record.get("output_file", "")).strip())
    return True, ""


def _delete_all_jobs_for_owner(client_id: str) -> int:
    removed = 0
    for job in _list_jobs_for_client(client_id):
        success, _ = _delete_job_for_owner(job["job_id"], client_id)
        if success:
            removed += 1
    return removed


def _load_job(job_id: str) -> ScrapeJob | None:
    job = jobs.get(job_id)
    if job is not None:
        return job
    record = job_store.get_job(job_id)
    if record is None:
        return None
    job = ScrapeJob.from_record(record)
    jobs[job_id] = job
    return job


def _bootstrap_jobs_from_store() -> None:
    global active_job_id, waiting_job_ids
    stored_jobs = job_store.load_all_jobs()
    for job_id, record in stored_jobs.items():
        jobs[job_id] = ScrapeJob.from_record(record)

    active_job_id = job_store.get_active_job_id()
    waiting_job_ids = deque(job_store.list_queue())

    # Running threads cannot survive process restart, so recover stale jobs cleanly.
    if active_job_id:
        stale_job = jobs.get(active_job_id)
        if stale_job is not None and stale_job.status == "running":
            stale_job.status = "failed"
            stale_job.message = "Server restarted before completion."
            stale_job.progress_text = "Failed"
            stale_job.append_log("The server restarted before this run could finish.")
            _sync_job(stale_job)
        active_job_id = None
        job_store.set_active_job_id(None)

    _refresh_queue_positions_locked()


def _set_active_job(job_id: str | None) -> None:
    global active_job_id
    with jobs_lock:
        active_job_id = job_id
        job_store.set_active_job_id(job_id)


def _refresh_queue_positions_locked() -> None:
    latest_queue = deque(job_store.list_queue())
    waiting_job_ids.clear()
    waiting_job_ids.extend(latest_queue)
    for position, queued_job_id in enumerate(waiting_job_ids, start=1):
        queued_job = _load_job(queued_job_id)
        if queued_job is not None and queued_job.status == "queued":
            queued_job.queue_position = position
            _sync_job(queued_job)


def _start_job_thread(job: ScrapeJob) -> None:
    thread = threading.Thread(target=_run_job, args=(job,), daemon=True)
    job.thread = thread
    thread.start()


def _promote_next_queued_job() -> None:
    global active_job_id
    next_job: ScrapeJob | None = None
    with jobs_lock:
        if active_job_id is not None:
            return
        while True:
            next_job_id = job_store.dequeue_next()
            if next_job_id is None:
                break
            candidate = _load_job(next_job_id)
            if candidate is None or candidate.status != "queued":
                continue
            active_job_id = next_job_id
            job_store.set_active_job_id(next_job_id)
            candidate.queue_position = 0
            candidate.status = "running"
            candidate.message = "Running"
            _sync_job(candidate)
            next_job = candidate
            break
        _refresh_queue_positions_locked()
    if next_job is not None:
        _start_job_thread(next_job)


def _get_active_job() -> ScrapeJob | None:
    with jobs_lock:
        if active_job_id is None:
            return None
        return _load_job(active_job_id)


_bootstrap_jobs_from_store()
_cleanup_stores()


def _create_settings_from_request(payload: dict) -> Settings:
    search_word = str(payload.get("search_word", "")).strip()
    if not search_word:
        raise SettingsError("Search term is required.")

    try:
        group_links_number = int(str(payload.get("group_links_number", "")).strip())
    except ValueError as exc:
        raise SettingsError("Group links number must be an integer.") from exc
    if group_links_number <= 0:
        raise SettingsError("Group links number must be greater than 0.")

    try:
        posts_from_each_group = int(str(payload.get("posts_from_each_group", "")).strip())
    except ValueError as exc:
        raise SettingsError("Posts from each group must be an integer.") from exc
    if posts_from_each_group <= 0:
        raise SettingsError("Posts from each group must be greater than 0.")

    job_id = uuid.uuid4().hex[:8]
    output_file = OUTPUTS_DIR / f"facebookposts-{job_id}.csv"
    chrome_profile_dir = PROFILES_DIR / "persistent-profile"

    return Settings(
        search_word=search_word,
        group_links_number=group_links_number,
        posts_from_each_group=posts_from_each_group,
        headless=False,
        output_file=str(output_file),
        chrome_profile_dir=str(chrome_profile_dir),
    )


def _run_job(job: ScrapeJob) -> None:
    handler = JobLogHandler(job)
    configure_logging(extra_handlers=[handler])

    with job.lock:
        job.status = "running"
        job.message = "Running"
        job.progress_percent = 5
        job.progress_text = "Starting browser"
    _sync_job(job)

    try:
        exit_code = run_scraper(job.settings, control=job.control)
    except Exception as exc:
        logger.exception("Job thread crashed unexpectedly: %s", exc)
        exit_code = 1
    finally:
        with job.lock:
            job.output_file = job.settings.output_file
            if exit_code == 0:
                job.status = "completed"
                job.message = "CSV file is ready."
                job.progress_percent = 100
                job.progress_text = "Completed"
                job.finished_at = time.time()
            elif exit_code == 2:
                job.status = "stopped"
                job.message = "Stopped."
                if job.progress_percent < 100:
                    job.progress_text = "Stopped"
                job.finished_at = time.time()
            else:
                job.status = "failed"
                job.message = "Finished with errors."
                if job.progress_percent < 100:
                    job.progress_text = "Failed"
                job.finished_at = time.time()
        _sync_job(job)
        global active_job_id
        with jobs_lock:
            if active_job_id == job.job_id:
                active_job_id = None
                job_store.set_active_job_id(None)
        _cleanup_stores()
        _promote_next_queued_job()


@app.get("/")
def index():
    return render_template("index.html", app_title=APP_TITLE)


@app.get("/api/active-job")
def get_active_job():
    job = _get_active_job()
    if job is None:
        return jsonify({"job": None})
    client_id = str(request.args.get("client_id", "")).strip()
    if client_id and client_id != job.owner_client_id:
        return jsonify({"job": None})
    return jsonify({"job": job.snapshot()})


@app.get("/api/jobs")
def list_jobs():
    client_id = str(request.args.get("client_id", "")).strip()
    return jsonify({"jobs": _list_jobs_for_client(client_id)})


@app.delete("/api/jobs")
def delete_all_jobs():
    payload = request.get_json(silent=True) or request.form.to_dict()
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        return jsonify({"error": "client_id is required."}), 400
    removed = _delete_all_jobs_for_owner(client_id)
    return jsonify({"ok": True, "deleted": removed})


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or request.form.to_dict()
    client_id = str(payload.get("client_id", "")).strip() or uuid.uuid4().hex

    try:
        settings = _create_settings_from_request(payload)
    except SettingsError as exc:
        return jsonify({"error": str(exc)}), 400

    job = ScrapeJob(
        job_id=Path(settings.output_file).stem.replace("facebookposts-", ""),
        settings=settings,
        owner_client_id=client_id,
    )
    job.target_posts = settings.expected_table_size
    job.total_groups = settings.group_links_number
    job.append_log("Note: this run executes on the host computer.")
    job.append_log("Preparing run...")
    start_now = False
    with jobs_lock:
        jobs[job.job_id] = job
        _sync_job(job)
        global active_job_id
        if active_job_id is None:
            active_job_id = job.job_id
            job_store.set_active_job_id(job.job_id)
            start_now = True
        else:
            job.message = "Queued. Waiting for current run."
            job.progress_text = "Queued"
            job_store.enqueue(job.job_id)
            job.append_log("Queued. Waiting for current run to finish.")
            _sync_job(job)
        _refresh_queue_positions_locked()

    if start_now:
        _start_job_thread(job)

    return jsonify({"job": job.snapshot()}), 201


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = _load_job(job_id)
    if job is not None:
        return jsonify({"job": job.snapshot()})
    record = run_history_store.get_job(job_id)
    if record is None:
        return jsonify({"error": "Job not found."}), 404
    return jsonify({"job": ScrapeJob.from_record(record).snapshot()})


@app.post("/api/jobs/<job_id>/stop")
def stop_job(job_id: str):
    job = _load_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    client_id = str(payload.get("client_id", "")).strip()
    if client_id != job.owner_client_id:
        return jsonify({"error": "Only the job owner can stop this run."}), 403

    if job.status == "queued":
        with jobs_lock:
            job_store.remove_from_queue(job.job_id)
            _refresh_queue_positions_locked()
        with job.lock:
            job.status = "stopped"
            job.message = "Stopped."
            job.progress_text = "Stopped"
            job.finished_at = time.time()
            job.logs.append("Process was cancelled before start.")
        _sync_job(job)
        return jsonify({"ok": True})

    job.control.request_stop()
    with job.lock:
        if job.status == "running":
            job.message = "Stopping..."
    _sync_job(job)
    return jsonify({"ok": True})


@app.post("/api/jobs/<job_id>/clear-logs")
def clear_job_logs(job_id: str):
    job = _load_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    client_id = str(payload.get("client_id", "")).strip()
    if client_id != job.owner_client_id:
        return jsonify({"error": "Only the job owner can clear logs."}), 403

    with job.lock:
        job.logs.clear()
    _sync_job(job)
    return jsonify({"ok": True})


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id: str):
    payload = request.get_json(silent=True) or request.form.to_dict()
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        return jsonify({"error": "client_id is required."}), 400
    success, error = _delete_job_for_owner(job_id, client_id)
    if not success:
        status_code = 404 if error == "Job not found." else 403 if "owner" in error else 400
        return jsonify({"error": error}), status_code
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>/download")
def download_job_output(job_id: str):
    job = _load_job(job_id)
    if job is not None:
        output_path = Path(job.settings.output_file)
    else:
        record = run_history_store.get_job(job_id)
        if record is None:
            return jsonify({"error": "Job not found."}), 404
        output_path = Path(str(record.get("output_file", "")).strip())
    if not output_path.exists():
        return jsonify({"error": "Output file is not ready yet."}), 404

    return send_file(output_path, as_attachment=True, download_name="facebookposts.csv")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
