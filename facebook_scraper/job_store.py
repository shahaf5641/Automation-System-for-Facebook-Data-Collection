from __future__ import annotations

import json
import logging
import os
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


class BaseJobStore:
    backend_name = "memory"

    def save_job(self, job_id: str, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def load_all_jobs(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def set_active_job_id(self, job_id: str | None) -> None:
        raise NotImplementedError

    def get_active_job_id(self) -> str | None:
        raise NotImplementedError

    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    def dequeue_next(self) -> str | None:
        raise NotImplementedError

    def remove_from_queue(self, job_id: str) -> None:
        raise NotImplementedError

    def list_queue(self) -> list[str]:
        raise NotImplementedError


class MemoryJobStore(BaseJobStore):
    backend_name = "memory"

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_job_id: str | None = None
        self.queue: deque[str] = deque()

    def save_job(self, job_id: str, record: dict[str, Any]) -> None:
        self.jobs[job_id] = json.loads(json.dumps(record))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        record = self.jobs.get(job_id)
        if record is None:
            return None
        return json.loads(json.dumps(record))

    def load_all_jobs(self) -> dict[str, dict[str, Any]]:
        return {job_id: json.loads(json.dumps(record)) for job_id, record in self.jobs.items()}

    def set_active_job_id(self, job_id: str | None) -> None:
        self.active_job_id = job_id

    def get_active_job_id(self) -> str | None:
        return self.active_job_id

    def enqueue(self, job_id: str) -> None:
        if job_id not in self.queue:
            self.queue.append(job_id)

    def dequeue_next(self) -> str | None:
        while self.queue:
            return self.queue.popleft()
        return None

    def remove_from_queue(self, job_id: str) -> None:
        try:
            self.queue.remove(job_id)
        except ValueError:
            return

    def list_queue(self) -> list[str]:
        return list(self.queue)


class RedisJobStore(BaseJobStore):
    backend_name = "redis"

    def __init__(self, client, prefix: str) -> None:
        self.client = client
        self.prefix = prefix

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}:{suffix}"

    def save_job(self, job_id: str, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=True)
        self.client.hset(self._key("jobs"), job_id, payload)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        payload = self.client.hget(self._key("jobs"), job_id)
        if payload is None:
            return None
        return json.loads(payload)

    def load_all_jobs(self) -> dict[str, dict[str, Any]]:
        raw = self.client.hgetall(self._key("jobs"))
        return {job_id: json.loads(payload) for job_id, payload in raw.items()}

    def set_active_job_id(self, job_id: str | None) -> None:
        key = self._key("active_job_id")
        if job_id:
            self.client.set(key, job_id)
        else:
            self.client.delete(key)

    def get_active_job_id(self) -> str | None:
        value = self.client.get(self._key("active_job_id"))
        return value or None

    def enqueue(self, job_id: str) -> None:
        queue_key = self._key("queue")
        if self.client.lpos(queue_key, job_id) is None:
            self.client.rpush(queue_key, job_id)

    def dequeue_next(self) -> str | None:
        value = self.client.lpop(self._key("queue"))
        return value or None

    def remove_from_queue(self, job_id: str) -> None:
        self.client.lrem(self._key("queue"), 0, job_id)

    def list_queue(self) -> list[str]:
        values = self.client.lrange(self._key("queue"), 0, -1)
        return list(values)


def build_job_store() -> BaseJobStore:
    redis_url = os.getenv("REDIS_URL", "").strip()
    redis_prefix = os.getenv("REDIS_PREFIX", "facebook_scraper")

    if not redis_url:
        logger.info("Redis is not configured. Falling back to in-memory job store.")
        return MemoryJobStore()

    if redis is None:
        logger.warning("REDIS_URL is set but redis package is not installed. Using in-memory job store.")
        return MemoryJobStore()

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        logger.info("Connected to Redis job store at %s", redis_url)
        return RedisJobStore(client=client, prefix=redis_prefix)
    except Exception as exc:
        logger.warning("Could not connect to Redis (%s). Using in-memory job store.", exc)
        return MemoryJobStore()
