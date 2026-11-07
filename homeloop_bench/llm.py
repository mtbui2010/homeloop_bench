"""LLM clients for the planners (docs/planners.md).

* :class:`OllamaHTTP`: POST ``/api/chat`` of an Ollama server through ``urllib`` (no third-party HTTP).
* :class:`FakeLLM`: deterministic, rule-based (``planners/keyword.py``). For tests and CI only; its
  results are never reported as a planner's.
* :class:`CachedLLM`: wraps any LLM with a JSONL cache keyed by sha256(model, prompt, format, temperature,
  seed), so a rerun of a live experiment is reproducible without the server.
* :class:`CountingLLM`: counts calls and raises :class:`BudgetExceeded` past the episode's LLM budget.

Wall-clock latencies are written to stderr only, never into results.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

DEFAULT_MODEL = "qwen3-vl:8b-instruct"
SHARED_CACHE_ENV = "HOMELOOP_LLM_SHARED_CACHE"      # dir of a read-through prompt-sha cache shared by paired runs


class BudgetExceeded(RuntimeError):
    """The episode used up its LLM call budget."""


class LLMError(RuntimeError):
    """The LLM server failed (network, HTTP error, bad body)."""


@runtime_checkable
class LLM(Protocol):
    model: str

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str: ...


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class OllamaHTTP:
    """Ollama chat client. ``url`` is the server root, e.g. ``http://127.0.0.1:11536``."""

    def __init__(self, url: str, model: str = DEFAULT_MODEL, num_ctx: int = 8192, timeout_s: float = 300.0,
                 retries: Optional[int] = None, backoff_s: float = 2.0):
        self.url = url.rstrip("/")
        self.model = model
        self.num_ctx = int(num_ctx)
        self.timeout_s = float(timeout_s)
        # transient failures (connection, 5xx, timeouts) are retried with exponential backoff
        self.retries = int(os.environ.get("HOMELOOP_LLM_RETRIES", "3")) if retries is None else int(retries)
        self.backoff_s = float(backoff_s)
        self.n_calls = 0
        # Ollama's ``think`` switch, sent only when set (a thinking model such as qwen3.5 answers EMPTY when its reasoning uses
        # the whole token cap, so its role clients set False). Not part of any cache key: a model is used with one setting.
        self.think: Optional[bool] = None

    def body(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, messages=None,
             num_predict=None) -> dict:
        msgs = [dict(m) for m in messages] if messages is not None else [{"role": "user", "content": prompt}]
        b = {"model": self.model, "messages": msgs, "stream": False,
             "options": {"temperature": float(temperature), "seed": int(seed), "num_ctx": self.num_ctx}}
        if num_predict:                  # a cap on the answer's tokens (robot_agent's guarded understand call)
            b["options"]["num_predict"] = int(num_predict)
        if format is not None:
            b["format"] = format
        if self.think is not None:
            b["think"] = bool(self.think)
        return b

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        extra = {"num_predict": num_predict} if num_predict else {}
        return self.chat_messages(None, temperature, seed, format=format, prompt=prompt, **extra)

    def chat_messages(self, messages, temperature: float = 0.0, seed: int = 0, format=None, prompt: str = "",
                      num_predict=None) -> str:
        """A chat with a full message list (system / user / assistant turns), e.g. embodiplan's own calls.
        ``num_predict``: an optional cap on the answer's tokens, per call (not part of any cache key)."""
        data = json.dumps(self.body(prompt, format, temperature, seed, messages=messages,
                                    num_predict=num_predict)).encode("utf-8")
        req = urllib.request.Request(self.url + "/api/chat", data=data, headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    out = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt >= self.retries:
                    raise LLMError(f"HTTPError {e.code}: {e.reason}") from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                if isinstance(e, ValueError) or attempt >= self.retries:
                    raise LLMError(f"{type(e).__name__}: {e}") from e
            print(f"[llm] {self.url} attempt {attempt + 1} failed; retrying", file=sys.stderr)
            time.sleep(self.backoff_s * (2 ** attempt))
            attempt += 1
        self.n_calls += 1
        if os.environ.get("HOMELOOP_LLM_VERBOSE"):
            print(f"[llm] {self.model} {time.monotonic() - t0:.2f}s", file=sys.stderr)
        msg = (out.get("message") or {}).get("content")
        if msg is None:
            raise LLMError(f"no message in response: {str(out)[:200]}")
        return str(msg)


class FakeLLM:
    """Deterministic stand-in for an LLM: parses the prompt (task text, observation lines, the planner's
    MODE header) with the rule-based keyword brain and answers in the format that planner expects."""

    def __init__(self, model: str = "fake"):
        self.model = model
        self.n_calls = 0

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        from .planners import keyword
        self.n_calls += 1
        return keyword.answer(prompt, temperature=temperature, seed=seed)


def cache_key(model: str, prompt: str, format, temperature: float, seed: int) -> str:
    return hashlib.sha256(_dumps([model, prompt, format, float(temperature), int(seed)]).encode("utf-8")).hexdigest()


class CachedLLM:
    """JSONL cache in front of an LLM: lines ``{sha, model, prompt, format, temperature, seed, response}``.

    ``shared`` (a second JSONL path) makes it a read-through, write-through cache shared by paired runs (common random
    numbers): a prompt (by sha) that any run sharing the file has already answered is answered the same way, so two
    configurations whose code sends the same prompt get the same text and a cell that differs between them must come
    from a prompt the variant itself changed. The baseline fills the file first; a variant adds what is new. The run's
    own cache keeps every response it used, so the run stays replayable on its own. The shared file is read again on
    a miss (another run may have filled it since), under no lock: two runs that miss the same prompt at the same time
    both call the server, so run the baseline first."""

    # Process-wide tally of every CachedLLM (planner, translator and the user's intent classifier of the run): the runner
    # reads it before and after an episode and writes the difference to the record (``llm_cache``). "hits": own cache,
    # "shared": answered from the shared file (another configuration asked it first), "misses": went to the server.
    tally = {"hits": 0, "shared": 0, "misses": 0}

    @classmethod
    def tally_snapshot(cls) -> dict:
        return dict(cls.tally)

    def __init__(self, inner, path, shared=None):
        self.inner = inner
        self.model = inner.model
        self.path = Path(path)
        self.shared = Path(shared) if shared else None
        self._shared_pos = 0
        self._smem: dict = {}
        self._mem: dict = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        self._mem[rec["sha"]] = rec["response"]
        self.hits = 0
        self.misses = 0
        self.shared_hits = 0
        self._scan_shared()

    def _scan_shared(self) -> None:
        """Read the shared file's new complete lines into the shared memory."""
        if self.shared is None or not self.shared.exists():
            return
        mem = self._smem
        with self.shared.open("rb") as f:
            f.seek(self._shared_pos)
            data = f.read()
        end = data.rfind(b"\n") + 1                      # a line another run is still writing is left for later
        for line in data[:end].decode("utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                mem.setdefault(rec["sha"], rec["response"])
        self._shared_pos += end

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        # ``num_predict`` (a per-call cap on the answer's tokens) is passed on when given and is NOT part of the key: the
        # same prompt is the same cache entry with or without a cap
        extra = {"num_predict": num_predict} if num_predict else {}
        return self._cached(cache_key(self.model, prompt, format, temperature, seed),
                            lambda: self.inner.chat(prompt, format=format, temperature=temperature, seed=seed, **extra),
                            {"prompt": prompt, "format": format, "temperature": float(temperature), "seed": int(seed)})

    def chat_messages(self, messages, temperature: float = 0.0, seed: int = 0, format=None) -> str:
        msgs = [dict(m) for m in messages]
        k = cache_key(self.model, _dumps(msgs), format, temperature, seed) if len(msgs) != 1 or \
            msgs[0].get("role") != "user" else cache_key(self.model, msgs[0].get("content", ""), format, temperature, seed)
        return self._cached(k, lambda: self.inner.chat_messages(msgs, temperature, seed, format=format),
                            {"messages": msgs, "format": format, "temperature": float(temperature), "seed": int(seed)})

    def _cached(self, k: str, call, row: dict) -> str:
        if k in self._mem:
            self.hits += 1
            CachedLLM.tally["hits"] += 1
            return self._mem[k]
        if self.shared is not None:
            self._scan_shared()
            smem = self._smem
            if k in smem:
                self.shared_hits += 1
                CachedLLM.tally["shared"] += 1
                resp = smem[k]
                self._mem[k] = resp
                self._append(self.path, _dumps({"sha": k, "model": self.model, **row, "response": resp}) + "\n")
                return resp
        self.misses += 1
        CachedLLM.tally["misses"] += 1
        resp = call()
        self._mem[k] = resp
        line = _dumps({"sha": k, "model": self.model, **row, "response": resp}) + "\n"
        self._append(self.path, line)
        if self.shared is not None:
            self._append(self.shared, line)
        return resp

    @staticmethod
    def _append(path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            _lock(f)                     # parallel workers (run --workers N) share one cache file
            f.write(line)
            f.flush()


def _lock(f) -> None:
    """Exclusive advisory lock on an open file until it is closed (POSIX); a no-op elsewhere."""
    try:
        import fcntl
    except ImportError:              # pragma: no cover - non-POSIX
        return
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)


class CountingLLM:
    """Counts calls; ``max_calls`` reached -> :class:`BudgetExceeded` before the call is made."""

    def __init__(self, inner, max_calls: Optional[int] = None):
        self.inner = inner
        self.model = inner.model
        self.max_calls = max_calls
        self.calls = 0

        self.failed: Optional[BaseException] = None     # the first LLMError (the runner aborts the run)
        # calls refused because the budget was used up; a planner may catch BudgetExceeded and go on (robot_agent's
        # SAGE / AssistLoop do), so the episode reads this, not the exception (pilot round 1, hl-dev-000003 KO)
        self.refused = 0

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        extra = {"num_predict": num_predict} if num_predict else {}
        return self._count(lambda: self.inner.chat(prompt, format=format, temperature=temperature, seed=seed, **extra))

    def chat_messages(self, messages, temperature: float = 0.0, seed: int = 0, format=None) -> str:
        return self._count(lambda: self.inner.chat_messages(messages, temperature, seed, format=format))

    def _count(self, call) -> str:
        if self.max_calls is not None and self.calls >= self.max_calls:
            self.refused += 1
            raise BudgetExceeded(f"LLM budget of {self.max_calls} calls exhausted")
        self.calls += 1
        try:
            return call()
        except LLMError as e:
            if self.failed is None:
                self.failed = e
            raise


def llm_kind(spec: Optional[str]) -> Optional[str]:
    """"fake" | "url" | None, for summary.json (the URL itself is not written)."""
    if spec is None:
        return None
    return "fake" if spec == "fake" else "url"


def model_digest(url: str, model: Optional[str]) -> Optional[str]:
    """The digest of ``model`` on an Ollama server (``GET /api/tags``); None when the server does not list it."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=10) as r:
            tags = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e
    for m in tags.get("models") or []:
        if m.get("name") == (model or DEFAULT_MODEL) or m.get("model") == (model or DEFAULT_MODEL):
            return m.get("digest")
    return None


def shared_cache_path(model: str) -> Optional[Path]:
    """The shared (paired runs) cache file of ``model`` when HOMELOOP_LLM_SHARED_CACHE names a directory, else None."""
    d = os.environ.get(SHARED_CACHE_ENV)
    return Path(d) / (model.replace("/", "_").replace(":", "_") + ".jsonl") if d else None


def make_llm(spec: Optional[str], model: Optional[str] = None, cache_dir: Optional[str] = None):
    """``"fake"`` -> FakeLLM; ``"http://..."`` -> OllamaHTTP (cached under ``cache_dir`` when given);
    None -> None."""
    if spec is None or spec == "":
        return None
    if spec == "fake":
        return FakeLLM()
    if spec.startswith(("http://", "https://")):
        llm = OllamaHTTP(spec, model or DEFAULT_MODEL)
        if cache_dir:
            safe = (model or DEFAULT_MODEL).replace("/", "_").replace(":", "_")
            llm = CachedLLM(llm, Path(cache_dir) / f"{safe}.jsonl", shared=shared_cache_path(model or DEFAULT_MODEL))
        return llm
    raise ValueError(f"--llm must be a URL (http://host:port) or 'fake', got {spec!r}")


def parse_json(text: str):
    """Tolerant JSON parser for LLM answers: strips code fences / ``<think>`` blocks, takes the first
    balanced {...} or [...] value. Raises ValueError when nothing parses."""
    s = str(text or "")
    if "</think>" in s:
        s = s.split("</think>", 1)[1]
    s = s.replace("```json", "```").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = s.find(open_c)
        while start >= 0:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(s)):
                ch = s[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except ValueError:
                            break
            start = s.find(open_c, start + 1)
    raise ValueError(f"no JSON value in: {s[:120]!r}")
