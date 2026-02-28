import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class TargetModel(BaseModel):
    receiver_url: str
    printer_name: str


class JobRequest(BaseModel):
    kind: str = Field(pattern="^(receipt_pdf|bar_ticket)$")
    payload: dict[str, Any]
    target: TargetModel
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass
class QueueJob:
    id: str
    body: JobRequest
    created_at: float = field(default_factory=time.time)
    attempt_count: int = 0
    status: str = "pending"
    last_error: str = ""


app = FastAPI(title="Mozzart Print Bridge", version="1.0.0")
_jobs: dict[str, QueueJob] = {}
_queue: asyncio.Queue[str] = asyncio.Queue()
_worker_task: asyncio.Task | None = None


def _bridge_token() -> str:
    return str(os.getenv("PRINT_BRIDGE_API_TOKEN", "")).strip()


def _receiver_token() -> str:
    return str(os.getenv("PRINT_BRIDGE_RECEIVER_TOKEN", "")).strip()


def _require_auth(authorization: str | None = Header(default=None)):
    expected = _bridge_token()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid bearer token.")


def _retry_delays() -> list[int]:
    raw = str(os.getenv("PRINT_BRIDGE_RETRY_DELAYS", "5,15,60,300,900")).strip()
    delays: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value >= 0:
            delays.append(value)
    return delays or [5, 15, 60, 300, 900]


async def _worker_loop():
    delays = _retry_delays()
    timeout = float(os.getenv("PRINT_BRIDGE_RECEIVER_TIMEOUT", "10"))
    receiver_token = _receiver_token()

    while True:
        job_id = await _queue.get()
        job = _jobs.get(job_id)
        if not job:
            _queue.task_done()
            continue

        job.status = "sending"
        sent = False

        for delay in delays:
            headers = {"Content-Type": "application/json"}
            if receiver_token:
                headers["X-Bridge-Token"] = receiver_token

            try:
                response = requests.post(
                    job.body.target.receiver_url,
                    json={
                        "job_id": job.id,
                        "kind": job.body.kind,
                        "printer_name": job.body.target.printer_name,
                        "payload": job.body.payload,
                        "meta": job.body.meta,
                    },
                    headers=headers,
                    timeout=timeout,
                )
                if 200 <= response.status_code < 300:
                    job.status = "printed"
                    job.last_error = ""
                    sent = True
                    break
                job.last_error = f"receiver_status={response.status_code}"
            except Exception as exc:
                job.last_error = str(exc)

            job.attempt_count += 1
            if delay > 0:
                await asyncio.sleep(delay)

        if not sent:
            job.status = "failed"

        _queue.task_done()


@app.on_event("startup")
async def _startup():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(_worker_loop())


@app.on_event("shutdown")
async def _shutdown():
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        _worker_task = None


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "queued": _queue.qsize(),
        "jobs": len(_jobs),
    }


@app.post("/v1/jobs", dependencies=[Depends(_require_auth)])
async def create_job(req: JobRequest):
    job_id = str(uuid.uuid4())
    job = QueueJob(id=job_id, body=req)
    _jobs[job_id] = job
    await _queue.put(job_id)
    return {
        "job_id": job_id,
        "status": job.status,
    }


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_require_auth)])
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job.id,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "last_error": job.last_error,
        "created_at": job.created_at,
        "kind": job.body.kind,
    }
