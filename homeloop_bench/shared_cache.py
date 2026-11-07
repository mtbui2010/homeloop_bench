"""Race-safe shared prompt cache for paired runs (common random numbers).

The problem: configurations that run in parallel on a COLD shared cache can miss the same prompt at the same time. Both call the
server, the answers differ (sampling, batching), both are appended, and a later run reads the first-written one: the two
configurations were not paired. Two ways out:

* sequential per replicate (the DEFAULT and the safe one): one configuration at a time on a replicate's cache; the baseline first.
  ``run`` and ``aa-check`` REFUSE to start next to another live run on the same shared cache directory unless lock mode is on.
* lock mode (``--cache-lock`` or ``HOMELOOP_CACHE_LOCK=1``): the first run to miss a key takes an exclusive lock on the key, calls the
  server, appends the answer, and only then releases the lock; a run that misses the same key meanwhile waits, re-reads the
  shared file and uses the first answer. Write-once per key: the first completed answer wins and nobody else calls the server
  for that key. The locks are POSIX advisory ``flock`` files, one per key bucket (the first 3 hex digits of the sha), so they work
  between processes (separate ``run`` commands, ``--workers`` processes) and threads.

Registration: a run that uses a shared cache directory holds an ``flock`` on ``DIR/.runs/<id>.run`` for its lifetime. A new run
looks at the files whose lock is still held (live runs); a file whose lock is free belongs to a dead process and is removed.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import uuid
from pathlib import Path

LOCK_ENV = "HOMELOOP_CACHE_LOCK"          # "1": lock mode (write-once per key)
RUNS_DIR = ".runs"
LOCK_DIR_SUFFIX = ".locks"


class SharedCacheError(RuntimeError):
    """A run would share a cache with another live run without lock mode."""


def lock_mode() -> bool:
    return os.environ.get(LOCK_ENV, "") == "1"


def _flock(f, flags) -> bool:
    try:
        import fcntl
    except ImportError:              # pragma: no cover - non-POSIX
        return True
    try:
        fcntl.flock(f.fileno(), flags)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def key_lock(shared: Path, key: str):
    """Exclusive lock on the bucket of ``key`` next to the shared file ``shared`` (blocks until it is free)."""
    d = Path(str(shared) + LOCK_DIR_SUFFIX)
    d.mkdir(parents=True, exist_ok=True)
    with (d / key[:3]).open("a+") as f:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def live_runs(cache_dir) -> list:
    """The registrations of the other live runs on ``cache_dir`` (dicts with pid, lock, label); stale files are removed."""
    import fcntl
    out = []
    d = Path(cache_dir) / RUNS_DIR
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.run")):
        try:
            f = p.open("a+")
        except OSError:
            continue
        with f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:                       # held: the run is alive
                f.seek(0)
                try:
                    out.append(json.loads(f.read() or "{}"))
                except ValueError:
                    out.append({})
                continue
            try:                                  # free: a dead run
                p.unlink()
            except OSError:
                pass
    return out


_HELD: list = []


def register_run(cache_dir, lock: bool, label: str = "") -> None:
    """Refuse (SharedCacheError) when another live run is on ``cache_dir`` and either side is not in lock mode; else register this
    process as a run for its lifetime."""
    d = Path(cache_dir) / RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    rid = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    p = d / f"{rid}.run"
    f = p.open("a+")
    import fcntl
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)        # alive from now on
    f.seek(0)
    f.truncate()
    f.write(json.dumps({"id": rid, "pid": os.getpid(), "lock": bool(lock), "label": label}, sort_keys=True))
    f.flush()
    mine = (f, p)
    _HELD.append(mine)
    atexit.register(release_runs)
    others = [r for r in live_runs(cache_dir) if r.get("id") != rid]
    if others and not (lock and all(r.get("lock") for r in others)):
        _HELD.remove(mine)
        _drop(mine)
        who = ", ".join(f"pid {r.get('pid', '?')}" + (f" ({r['label']})" if r.get("label") else "") for r in others)
        raise SharedCacheError(
            f"another run is live on the shared cache {cache_dir} ({who}). Configurations that miss the same prompt at the same "
            "time get different answers and are then not paired. Run the configurations of a replicate one after the other "
            "(the default), or start every one of them with --cache-lock (write-once per key, docs/runner.md).")


def release_runs() -> None:
    while _HELD:
        _drop(_HELD.pop())


def _drop(held) -> None:
    f, p = held
    try:
        p.unlink()
    except OSError:
        pass
    try:
        f.close()
    except OSError:
        pass
