# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Tareas largas en segundo plano con progreso y cancelación (la interfaz las consulta por id)."""
import threading
import time
import traceback
import uuid

from . import safety
from .util import log


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "running"
        self.progress = 0
        self.message = ""
        self.result = None
        self.error = None
        self.started = time.time()
        self._cancel = threading.Event()

    def update(self, progress=None, message=None):
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        if message is not None:
            self.message = message
        self.check()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "status": self.status, "progress": self.progress,
                "message": self.message, "result": self.result, "error": self.error,
                "elapsed": round(time.time() - self.started, 1)}


_jobs = {}
_lock = threading.Lock()


def start(kind, fn, *args, **kwargs):
    """Lanza fn(job, *args) en un hilo y devuelve el Job."""
    job = Job(kind)
    with _lock:
        _jobs[job.id] = job

    def runner():
        try:
            job.result = fn(job, *args, **kwargs)
            job.status = "done"
            job.progress = 100
        except Cancelled:
            job.status = "cancelled"
            job.message = "Cancelado por el usuario"
        except safety.Blocked as e:
            job.status = "error"
            job.error = f"Protección del sistema — {e}"
            log.warning("Tarea %s bloqueada por protección: %s", kind, e)
        except Exception as e:  # el error se muestra en la interfaz
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            log.error("Tarea %s falló:\n%s", kind, traceback.format_exc())

    threading.Thread(target=runner, daemon=True, name=f"job-{kind}").start()
    return job


def get(job_id):
    return _jobs.get(job_id)


def any_running():
    return any(j.status == "running" for j in _jobs.values())
