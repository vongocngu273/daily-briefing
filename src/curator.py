"""Gemini curation with structured output + ID hydration (model never emits URLs)."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .config import CATEGORY_HINTS, LAYERS
from .news import Article

log = logging.getLogger(__name__)

SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "⚪"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# ---------- schemas sent to Gemini ----------

class CuratedItem(BaseModel):
    candidate_id: int = Field(description="cid của bài gốc trong danh sách ứng viên")
    category: str = Field(description="Mã chuyên mục được phép")
    severity: Literal["high", "medium", "low"]
    title: str = Field(description="Tiêu đề tiếng Việt, tối đa 12 chữ")
    summary: str = Field(description="Tóm tắt 1 câu tiếng Việt, tối đa 25 chữ")
    developments: str = Field(description="Diễn biến chính, 1-3 câu")
    context: str = Field(description="Bối cảnh, 1-2 câu")
    why_it_matters: str = Field(description="Vì sao quan trọng / ảnh hưởng tới Việt Nam, 1-2 câu")
    is_update: bool = Field(description="true nếu là diễn biến mới của tin đã đăng gần đây")


class LayerResult(BaseModel):
    items: list[CuratedItem]


class Takeaways(BaseModel):
    lines: list[str]


# ---------- output dataclass ----------

@dataclass
class NewsItem:
    cid: int
    category: str
    severity: str
    title: str
    summary: str
    developments: str
    context: str
    why_it_matters: str
    is_update: bool
    url: str
    source: str
    published: str
    ai: bool = True  # False = deterministic fallback, not recorded in history
    num: int = 0  # continuous display number across the page (01..N)

    @property
    def emoji(self) -> str:
        return SEVERITY_EMOJI.get(self.severity, "⚪")


def truncate_words(text: str, n: int) -> str:
    words = (text or "").split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]).rstrip(",;:") + "…"


# ---------- hydration ----------

def hydrate(result_items: list[CuratedItem], candidates: list[Article], layer: int,
            max_per_category: int = 5) -> dict[str, list[NewsItem]]:
    """Map candidate_id back to real URL/source. Drop invalid/duplicate cids."""
    by_cid = {a.cid: a for a in candidates}
    allowed = {k for k, _ in LAYERS[layer]}
    used: set[int] = set()
    out: dict[str, list[NewsItem]] = {k: [] for k in allowed}
    for it in result_items:
        art = by_cid.get(it.candidate_id)
        if art is None:
            log.warning("Lớp %d: bỏ cid không hợp lệ %s", layer, it.candidate_id)
            continue
        if it.candidate_id in used:
            continue
        if it.category not in allowed:
            log.warning("Lớp %d: bỏ chuyên mục lạ %r", layer, it.category)
            continue
        if len(out[it.category]) >= max_per_category:
            continue
        used.add(it.candidate_id)
        out[it.category].append(NewsItem(
            cid=art.cid,
            category=it.category,
            severity=it.severity if it.severity in SEVERITY_EMOJI else "low",
            title=truncate_words(it.title, 12),
            summary=truncate_words(it.summary, 25),
            developments=it.developments.strip(),
            context=it.context.strip(),
            why_it_matters=it.why_it_matters.strip(),
            is_update=bool(it.is_update),
            url=art.url,
            source=art.source,
            published=art.published.isoformat(),
        ))
    for k in out:
        out[k].sort(key=lambda n: SEVERITY_ORDER.get(n.severity, 3))
    return out


# ---------- Gemini ----------

SYSTEM = (
    "Bạn là biên tập viên trưởng một bản tin sáng cho độc giả Việt Nam. "
    "Chỉ dùng thông tin có trong danh sách ứng viên; không bịa chi tiết, số liệu hay URL. "
    "Viết tiếng Việt chuẩn, trung lập, súc tích."
)


def _layer_prompt(layer: int, candidates: list[Article], recent: list[str], max_per_cat: int) -> str:
    cats = "\n".join(f"- {k}: {label}" + (f" ({CATEGORY_HINTS[k]})" if k in CATEGORY_HINTS else "")
                     for k, label in LAYERS[layer])
    rows = [
        {"cid": a.cid, "source": a.source, "title": a.title, "snippet": a.summary[:220],
         "time_utc": a.published.strftime("%Y-%m-%d %H:%M")}
        for a in candidates
    ]
    return f"""Nhiệm vụ: chọn và biên tập tin quan trọng nhất cho các chuyên mục sau:
{cats}

Quy tắc:
1. Mỗi chuyên mục tối đa {max_per_cat} tin, ưu tiên tầm ảnh hưởng lớn và tác động tới Việt Nam. Có thể ít hơn nếu thiếu tin xứng đáng.
2. candidate_id PHẢI là một cid có trong danh sách. Mỗi cid dùng tối đa một lần. Không trả URL.
3. Gộp các bài cùng một sự kiện: chỉ chọn 1 cid đại diện (ưu tiên nguồn uy tín, chi tiết hơn).
4. So với "Tiêu đề đã đăng gần đây": nếu cùng sự kiện mà không có gì mới thì BỎ; nếu có diễn biến mới đáng kể thì chọn và đặt is_update=true.
5. severity: high = khẩn cấp/tác động lớn; medium = đáng chú ý; low = tham khảo.
6. title ≤ 12 chữ; summary đúng 1 câu ≤ 25 chữ; developments, context, why_it_matters mỗi phần 1–2 câu, chỉ dựa trên tiêu đề/snippet, không suy diễn số liệu.
7. category phải là một trong các mã: {", ".join(k for k, _ in LAYERS[layer])}.

Tiêu đề đã đăng gần đây:
{json.dumps(recent, ensure_ascii=False)}

Danh sách ứng viên (JSON):
{json.dumps(rows, ensure_ascii=False)}
"""


def is_key_problem(err: Exception) -> bool:
    """Errors where another API key may succeed: quota (429), auth (401/403), invalid key (400)."""
    code = getattr(err, "code", None)
    msg = str(err).lower()
    return code in (401, 403, 429) or (code == 400 and "api key" in msg)


def is_retryable(err: Exception) -> bool:
    """429 / 5xx / network & parse errors are retryable; other 4xx are permanent."""
    code = getattr(err, "code", None)
    if isinstance(code, int):
        return code == 429 or code >= 500
    return True


class Curator:
    def __init__(self, api_keys: str | list[str], model: str = "gemini-3.8-flash", max_retries: int = 4,
                 temperature: float = 0.3, fallback_models: list[str] | None = None,
                 thinking_level: str | None = None, request_timeout_s: int = 300):
        from google import genai

        keys = [api_keys] if isinstance(api_keys, str) else list(api_keys)
        keys = [k for k in dict.fromkeys(keys) if k]
        if not keys:
            raise ValueError("Cần ít nhất 1 Gemini API key")
        # Key 1 lỗi quota/auth -> tự chuyển sang key 2 (không bao giờ log giá trị key)
        from google.genai import types as _t

        http = _t.HttpOptions(timeout=request_timeout_s * 1000)  # ms; stop hung requests
        self.clients = [genai.Client(api_key=k, http_options=http) for k in keys]
        self.key_idx = 0
        self.thinking_level = (thinking_level or "").upper() or None
        self._lock = threading.Lock()
        # De-duplicated model chain; first one that is not 404 sticks for the run.
        self.models = list(dict.fromkeys([model, *(fallback_models or [])]))
        self.max_retries = max_retries
        self.temperature = temperature

    @property
    def model(self) -> str:
        return self.models[0]

    def _next_model(self, failed: str) -> bool:
        """Drop an exhausted model from the chain (shared across threads)."""
        with self._lock:
            if self.models and self.models[0] == failed and len(self.models) > 1:
                self.models.pop(0)
                log.warning("Model %s lỗi liên tục, chuyển sang %s", failed, self.models[0])
            return bool(self.models) and self.models[0] != failed

    def _switch_key(self, failed_idx: int) -> bool:
        """Move to the next API key. True if a different key is now active."""
        with self._lock:
            if self.key_idx == failed_idx and failed_idx + 1 < len(self.clients):
                self.key_idx = failed_idx + 1
                log.warning("Gemini API key #%d lỗi, chuyển sang key dự phòng #%d", failed_idx + 1, self.key_idx + 1)
            return self.key_idx != failed_idx

    def _generate(self, prompt: str, schema):
        from google.genai import types

        last_err: Exception | None = None
        attempt = 0
        while attempt < self.max_retries and self.models:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=self.temperature,
                thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level)
                if self.thinking_level else None,
            )
            current = self.model
            key_idx = self.key_idx
            try:
                resp = self.clients[key_idx].models.generate_content(model=current, contents=prompt, config=config)
                parsed = resp.parsed
                if parsed is None and resp.text:
                    parsed = schema.model_validate_json(resp.text)
                if parsed is None:
                    raise ValueError("empty response")
                return parsed
            except Exception as e:  # noqa: BLE001
                last_err = e
                code = getattr(e, "code", None)
                if code == 404 and self._next_model(current):
                    continue
                if code == 400 and self.thinking_level and "thinking" in str(e).lower():
                    log.warning("Model %s không hỗ trợ thinking_level, bỏ tham số này", self.model)
                    self.thinking_level = None
                    continue
                if is_key_problem(e) and self._switch_key(key_idx):
                    attempt = 0
                    continue
                if not is_retryable(e):
                    log.error("Gemini lỗi không thể retry (%s): %s", code, str(e)[:160])
                    break
                attempt += 1
                wait = min(60, 2 ** attempt * 3) + random.uniform(0, 1.5)
                log.warning("Gemini lỗi (lần %d/%d, %s): %s – chờ %.1fs", attempt, self.max_retries,
                            self.model, str(e)[:160], wait)
                if attempt < self.max_retries:
                    time.sleep(wait)
                elif self._next_model(current):  # model overloaded for every retry -> next model
                    attempt = 0
                elif self._switch_key(key_idx):  # last model too -> try backup key
                    attempt = 0
        raise RuntimeError(f"Gemini thất bại: {str(last_err)[:300]}")

    def curate_layer(self, layer: int, candidates: list[Article], recent: list[str],
                     max_per_cat: int = 5) -> dict[str, list[NewsItem]]:
        if not candidates:
            return {k: [] for k, _ in LAYERS[layer]}
        result: LayerResult = self._generate(_layer_prompt(layer, candidates, recent, max_per_cat), LayerResult)
        hydrated = hydrate(result.items, candidates, layer, max_per_cat)
        log.info("Lớp %d: %d ứng viên -> %d tin", layer, len(candidates), sum(len(v) for v in hydrated.values()))
        return hydrated

    def takeaways(self, items: list[NewsItem]) -> list[str]:
        if not items:
            return []
        top = sorted(items, key=lambda n: SEVERITY_ORDER.get(n.severity, 3))[:20]
        bullet = "\n".join(f"- {n.title}: {n.summary}" for n in top)
        prompt = (
            "Từ các tin dưới đây, viết đúng 3 dòng \"3 điều cần nhớ hôm nay\" cho người đọc Việt Nam. "
            "Mỗi dòng tối đa 15 chữ, không đánh số, không bịa thông tin ngoài danh sách.\n\n" + bullet
        )
        res: Takeaways = self._generate(prompt, Takeaways)
        return [truncate_words(l.strip().lstrip("-•0123456789. "), 15) for l in res.lines if l.strip()][:3]


def fallback_layer(layer: int, candidates: list[Article], max_per_cat: int = 5) -> dict[str, list[NewsItem]]:
    """Deterministic fallback when Gemini is unavailable: newest headlines, first category only."""
    out = {k: [] for k, _ in LAYERS[layer]}
    first = LAYERS[layer][0][0]
    for a in candidates[:max_per_cat]:
        out[first].append(NewsItem(
            cid=a.cid, category=first, severity="low", title=a.title,
            summary=truncate_words(a.summary, 25) or a.title, developments="", context="",
            why_it_matters="", is_update=False, url=a.url, source=a.source,
            published=a.published.isoformat(), ai=False,
        ))
    return out
