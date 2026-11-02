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


class BudgetExceeded(RuntimeError):
    """The episode used up its LLM call budget."""


class LLMError(RuntimeError):
    """The LLM server failed (network, HTTP error, bad body)."""


@runtime_checkable
class LLM(Protocol):
    model: str

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str: ...


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

    def body(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> dict:
        b = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False,
             "options": {"temperature": float(temperature), "seed": int(seed), "num_ctx": self.num_ctx}}
        if format is not None:
            b["format"] = format
        return b

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str:
        data = json.dumps(self.body(prompt, format, temperature, seed)).encode("utf-8")
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

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str:
        from .planners import keyword
        self.n_calls += 1
        return keyword.answer(prompt, temperature=temperature, seed=seed)


def cache_key(model: str, prompt: str, format, temperature: float, seed: int) -> str:
    return hashlib.sha256(_dumps([model, prompt, format, float(temperature), int(seed)]).encode("utf-8")).hexdigest()


class CachedLLM:
    """JSONL cache in front of an LLM: lines ``{sha, model, prompt, format, temperature, seed, response}``."""

    def __init__(self, inner, path):
        self.inner = inner
        self.model = inner.model
        self.path = Path(path)
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

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str:
        k = cache_key(self.model, prompt, format, temperature, seed)
        if k in self._mem:
            self.hits += 1
            return self._mem[k]
        self.misses += 1
        resp = self.inner.chat(prompt, format=format, temperature=temperature, seed=seed)
        self._mem[k] = resp
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_dumps({"sha": k, "model": self.model, "prompt": prompt, "format": format,
                            "temperature": float(temperature), "seed": int(seed), "response": resp}) + "\n")
        return resp


class CountingLLM:
    """Counts calls; ``max_calls`` reached -> :class:`BudgetExceeded` before the call is made."""

    def __init__(self, inner, max_calls: Optional[int] = None):
        self.inner = inner
        self.model = inner.model
        self.max_calls = max_calls
        self.calls = 0

        self.failed: Optional[BaseException] = None     # the first LLMError (the runner aborts the run)

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(f"LLM budget of {self.max_calls} calls exhausted")
        self.calls += 1
        try:
            return self.inner.chat(prompt, format=format, temperature=temperature, seed=seed)
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
            llm = CachedLLM(llm, Path(cache_dir) / f"{safe}.jsonl")
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
