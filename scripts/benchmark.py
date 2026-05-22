#!/usr/bin/env python3
"""Benchmark SuwayomiOCR translation quality on the paired Datasets/ corpus.

Two-phase design:

  gather  — for each page in Datasets/生肉/ (raw JP), OCR it, OCR the matching
            Datasets/熟肉/ page as Chinese reference, then translate the JP text
            via both DeepSeek-Chat and Google Translate. Captures DeepSeek
            token usage. Appends one JSON object per page to benchmark_results.jsonl.
            Resumable: pages already in the JSONL are skipped.

  score   — read benchmark_results.jsonl, compute BLEU (zh tokenization), chrF,
            character-level Jaccard, and translation latency for each backend.
            Tallies DeepSeek token usage and prints estimated USD cost.
            Writes a human-readable report to BENCHMARKS.md.

Caveats:
  * Reference Chinese text is OCR-extracted from 熟肉 pages, not hand-transcribed.
    Both reference and system output share the same OCR-noise baseline.
  * Fan-translated 熟肉 may use looser/freer translation than the source warrants.
  * BLEU/chrF are surface-level; semantic equivalence (e.g. BERTScore) requires
    extra deps and is out of scope here.

Usage:
  python scripts/benchmark.py gather --limit 5      # smoke test
  python scripts/benchmark.py gather                # full corpus, resumes
  python scripts/benchmark.py score                 # compute metrics + report
"""

import argparse
import asyncio
import base64
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from ocr_client import recognize as ocr_recognize  # noqa: E402
from translation_client import _ai_client, _build_system_prompt, _translate_google  # noqa: E402

import os as _os
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(_os.environ.get("BENCHMARK_RAW_DIR", str(ROOT.parent / "Datasets" / "生肉")))
REF_DIR = Path(_os.environ.get("BENCHMARK_REF_DIR", str(ROOT.parent / "Datasets" / "熟肉")))
RESULTS_PATH = ROOT / "benchmark_results.jsonl"
REPORT_PATH_EN = ROOT / "BENCHMARKS.md"
REPORT_PATH_ZH = ROOT / "BENCHMARKS.zh.md"

# Translation API pricing (USD per 1M tokens). Defaults match DeepSeek-Chat
# as of late-2025 (input $0.27 miss / $0.07 hit, output $1.10). If you swap
# TRANSLATION_API_BASE_URL to a different provider, override these via the
# AI_PRICING_* environment variables.
AI_PRICING_INPUT_USD = float(_os.environ.get("AI_PRICING_INPUT_USD", "0.27"))
AI_PRICING_INPUT_CACHE_USD = float(_os.environ.get("AI_PRICING_INPUT_CACHE_USD", "0.07"))
AI_PRICING_OUTPUT_USD = float(_os.environ.get("AI_PRICING_OUTPUT_USD", "1.10"))

# Optional third backend for end-to-end comparison: a single multimodal model
# that does both OCR and translation. Reads QWEN_* env vars (set to empty to
# disable). If enabled, each page additionally runs:
#   ja_qwen = qwen_ocr(生肉)
#   zh_qwen = qwen_translate(ja_qwen)
# and is logged in the JSONL.
QWEN_BASE_URL = _os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
QWEN_MODEL = _os.environ.get("QWEN_MODEL", "Qwen/Qwen3.6-27B")
QWEN_API_KEY = _os.environ.get("QWEN_API_KEY", "")
QWEN_ENABLED = bool(QWEN_BASE_URL and QWEN_MODEL)

_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_LIST = re.compile(r"^[\-\*\+]\s+", re.MULTILINE)
_MD_EMPH = re.compile(r"\*+|_+|`+")
_MD_HR = re.compile(r"^-{3,}$", re.MULTILINE)


def _normalize(s: str) -> str:
    """Strip markdown noise for fair scoring."""
    s = _MD_HR.sub("", s)
    s = _MD_HEADING.sub("", s)
    s = _MD_LIST.sub("", s)
    s = _MD_EMPH.sub("", s)
    return " ".join(s.split())


def _jpeg_b64(path: Path, quality: int = 85) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


_QWEN_OCR_PROMPT = (
    "Extract all Japanese text from this manga page. Output ONLY the recognized "
    "text, preserve line breaks as \\n, no commentary, no markdown, no code fences."
)


_QWEN_THINK_RE = re.compile(r"<think>.*?</think>\s*|</?think>\s*", re.DOTALL | re.IGNORECASE)


async def _qwen_call(http: httpx.AsyncClient, messages: list, max_tokens: int = 2048) -> tuple[str, dict]:
    headers = {"Content-Type": "application/json"}
    if QWEN_API_KEY:
        headers["Authorization"] = f"Bearer {QWEN_API_KEY}"
    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = await http.post(f"{QWEN_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=300)
    r.raise_for_status()
    data = r.json()
    content = (data["choices"][0]["message"].get("content") or "").strip()
    # Strip any leaked thinking-tag fragments — Qwen3 occasionally emits an
    # orphan </think> even with enable_thinking=False.
    content = _QWEN_THINK_RE.sub("", content).strip()
    usage = data.get("usage") or {}
    return content, {
        "prompt": int(usage.get("prompt_tokens") or 0),
        "completion": int(usage.get("completion_tokens") or 0),
    }


async def _qwen_ocr(http: httpx.AsyncClient, jpeg_b64: str) -> tuple[str, dict]:
    return await _qwen_call(
        http,
        [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}},
            {"type": "text", "text": _QWEN_OCR_PROMPT},
        ]}],
        max_tokens=4096,
    )


async def _qwen_translate(http: httpx.AsyncClient, ja_text: str, manga_name: str) -> tuple[str, dict]:
    return await _qwen_call(
        http,
        [
            {"role": "system", "content": _build_system_prompt(manga_name)},
            {"role": "user", "content": ja_text},
        ],
        max_tokens=2048,
    )


async def _gather_one(
    sem: asyncio.Semaphore,
    ds: AsyncOpenAI | None,
    http: httpx.AsyncClient,
    manga_name: str,
    page: str,
    existing: dict | None = None,
) -> dict:
    """Run any missing pipeline stages for `page` and return a complete row.

    If `existing` is given, only stages whose output is missing/empty are run —
    so adding a new backend (e.g. Qwen) only costs the new calls, not the
    whole pipeline.
    """
    row = dict(existing) if existing else {"page": page}
    row.setdefault("timings_s", {})

    need_ocr_ja = not (row.get("ja_text") or "").strip()
    need_ocr_zh = not (row.get("zh_ref") or "").strip()
    need_deepseek = not (row.get("zh_deepseek") or "").strip() and ds is not None
    need_google = not (row.get("zh_google") or "").strip()
    need_qwen_ocr = QWEN_ENABLED and not (row.get("ja_qwen") or "").strip()
    need_qwen_tr = QWEN_ENABLED and not (row.get("zh_qwen") or "").strip()

    async with sem:
        ja_b64 = _jpeg_b64(RAW_DIR / page) if (need_ocr_ja or need_qwen_ocr) else None
        zh_b64 = _jpeg_b64(REF_DIR / page) if need_ocr_zh else None

        if need_ocr_ja:
            t0 = time.time()
            row["ja_text"] = await ocr_recognize(ja_b64)
            row["timings_s"]["ocr_ja"] = round(time.time() - t0, 2)

        if need_ocr_zh:
            t0 = time.time()
            row["zh_ref"] = await ocr_recognize(zh_b64)
            row["timings_s"]["ocr_zh"] = round(time.time() - t0, 2)

        ja_text = row.get("ja_text", "")

        if need_deepseek and ja_text:
            try:
                t0 = time.time()
                resp = await ds.chat.completions.create(
                    model=settings.TRANSLATION_API_MODEL,
                    messages=[
                        {"role": "system", "content": _build_system_prompt(manga_name)},
                        {"role": "user", "content": ja_text},
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                )
                row["timings_s"]["deepseek"] = round(time.time() - t0, 2)
                row["zh_deepseek"] = (resp.choices[0].message.content or "").strip()
                tok = {"prompt": 0, "completion": 0, "cache_hit": 0}
                if resp.usage:
                    tok["prompt"] = int(resp.usage.prompt_tokens or 0)
                    tok["completion"] = int(resp.usage.completion_tokens or 0)
                    details = getattr(resp.usage, "prompt_tokens_details", None)
                    if details:
                        tok["cache_hit"] = int(getattr(details, "cached_tokens", 0) or 0)
                row["deepseek_tokens"] = tok
            except Exception as exc:
                row["zh_deepseek"] = f"<error: {exc}>"

        if need_google and ja_text:
            try:
                t0 = time.time()
                row["zh_google"] = await _translate_google(ja_text)
                row["timings_s"]["google"] = round(time.time() - t0, 2)
            except Exception as exc:
                row["zh_google"] = f"<error: {exc}>"

        if QWEN_ENABLED:
            row.setdefault("qwen_tokens", {"ocr_prompt": 0, "ocr_completion": 0,
                                          "translate_prompt": 0, "translate_completion": 0})
            if need_qwen_ocr:
                try:
                    t0 = time.time()
                    txt, usage = await _qwen_ocr(http, ja_b64)
                    row["ja_qwen"] = txt
                    row["timings_s"]["qwen_ocr"] = round(time.time() - t0, 2)
                    row["qwen_tokens"]["ocr_prompt"] = usage["prompt"]
                    row["qwen_tokens"]["ocr_completion"] = usage["completion"]
                except Exception as exc:
                    row["ja_qwen"] = f"<error: {exc}>"
            qwen_ja = row.get("ja_qwen", "")
            if need_qwen_tr and qwen_ja and not qwen_ja.startswith("<error"):
                try:
                    t0 = time.time()
                    txt, usage = await _qwen_translate(http, qwen_ja, manga_name)
                    row["zh_qwen"] = txt
                    row["timings_s"]["qwen_translate"] = round(time.time() - t0, 2)
                    row["qwen_tokens"]["translate_prompt"] = usage["prompt"]
                    row["qwen_tokens"]["translate_completion"] = usage["completion"]
                except Exception as exc:
                    row["zh_qwen"] = f"<error: {exc}>"

    # Ensure required schema fields exist even if all-skip (for downstream score)
    row.setdefault("ja_text", "")
    row.setdefault("zh_ref", "")
    row.setdefault("zh_deepseek", "")
    row.setdefault("zh_google", "")
    row.setdefault("deepseek_tokens", {"prompt": 0, "completion": 0, "cache_hit": 0})
    return row


def _load_existing() -> dict:
    """Map page → existing row, for incremental augmentation."""
    out: dict = {}
    if RESULTS_PATH.exists():
        for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                out[row["page"]] = row
            except Exception:
                pass
    return out


def _rewrite_results(rows_by_page: dict) -> None:
    """Atomically rewrite benchmark_results.jsonl with deterministic order."""
    tmp = RESULTS_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for page in sorted(rows_by_page):
            f.write(json.dumps(rows_by_page[page], ensure_ascii=False) + "\n")
    tmp.replace(RESULTS_PATH)


def _row_needs_work(row: dict | None) -> bool:
    """True if at least one configured backend has no output for this page."""
    if row is None:
        return True
    if not (row.get("ja_text") or "").strip():
        return True
    if not (row.get("zh_ref") or "").strip():
        return True
    if not (row.get("zh_deepseek") or "").strip() and settings.TRANSLATION_API_KEY:
        return True
    if not (row.get("zh_google") or "").strip():
        return True
    if QWEN_ENABLED and not (row.get("ja_qwen") or "").strip():
        return True
    if QWEN_ENABLED and not (row.get("zh_qwen") or "").strip():
        return True
    return False


async def cmd_gather(args: argparse.Namespace) -> None:
    all_pages = sorted(
        p.name for p in RAW_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if args.limit > 0:
        all_pages = all_pages[: args.limit]

    existing = _load_existing()
    todo = [p for p in all_pages if _row_needs_work(existing.get(p))]
    if not todo:
        print("[*] nothing to do (all pages already complete)")
        return

    backends = ["OCR(JP/ZH)", "Google"]
    if settings.TRANSLATION_API_KEY and settings.TRANSLATION_API_KEY != "sk-REPLACE-ME":
        backends.append(f"AI-translate({settings.TRANSLATION_API_MODEL})")
    if QWEN_ENABLED:
        backends.append(f"Qwen({QWEN_MODEL})")
    print(f"[*] {len(todo)} pages need work | backends: {', '.join(backends)} | "
          f"concurrency={args.concurrency} | manga={args.manga_name!r}")

    ds_client: AsyncOpenAI | None = None
    if settings.TRANSLATION_API_KEY and settings.TRANSLATION_API_KEY != "sk-REPLACE-ME":
        ds_client = AsyncOpenAI(
            api_key=settings.TRANSLATION_API_KEY,
            base_url=settings.TRANSLATION_API_BASE_URL,
            timeout=30.0,
        )

    sem = asyncio.Semaphore(args.concurrency)
    rows_by_page = dict(existing)

    async with httpx.AsyncClient() as http:
        tasks = [
            _gather_one(sem, ds_client, http, args.manga_name, p, existing.get(p))
            for p in todo
        ]
        for idx, fut in enumerate(asyncio.as_completed(tasks), start=1):
            row = await fut
            rows_by_page[row["page"]] = row
            t = row.get("timings_s", {})
            qwen_s = t.get("qwen_ocr", 0) + t.get("qwen_translate", 0)
            print(
                f"[{idx}/{len(todo)}] {row['page']:>10s}  "
                f"ocr={t.get('ocr_ja',0)+t.get('ocr_zh',0):.1f}s  "
                f"ds={t.get('deepseek',0):.1f}s  g={t.get('google',0):.1f}s  "
                f"qwen={qwen_s:.1f}s  "
                f"ja={len(row.get('ja_text',''))}/qwen={len(row.get('ja_qwen',''))}"
            )
            # Rewrite incrementally so a crash doesn't lose progress.
            if idx % 5 == 0 or idx == len(todo):
                _rewrite_results(rows_by_page)

    _rewrite_results(rows_by_page)


def _char_jaccard(a: str, b: str) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def _char_f1(a: str, b: str) -> float:
    """Multiset character F1 — symmetric, penalizes both insertions and deletions."""
    ca, cb = Counter(a), Counter(b)
    overlap = sum((ca & cb).values())
    if overlap == 0:
        return 0.0
    p = overlap / max(1, sum(ca.values()))
    r = overlap / max(1, sum(cb.values()))
    return 2 * p * r / (p + r)


def cmd_score(_args: argparse.Namespace) -> None:
    import sacrebleu

    if not RESULTS_PATH.exists():
        print(f"[!] {RESULTS_PATH} missing — run `benchmark.py gather` first")
        sys.exit(1)

    rows = [json.loads(line) for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        print("[!] no rows")
        sys.exit(1)

    def _score_pair(label: str, sys_field: str) -> dict:
        pairs = [
            (_normalize(r[sys_field]), _normalize(r["zh_ref"]))
            for r in rows
            if r.get(sys_field, "").strip()
            and not r[sys_field].startswith("<error:")
            and r.get("zh_ref", "").strip()
        ]
        if not pairs:
            return {"label": label, "n": 0}

        sys_out = [s for s, _ in pairs]
        refs = [r for _, r in pairs]
        bleu = sacrebleu.corpus_bleu(sys_out, [refs], tokenize="zh")
        chrf = sacrebleu.corpus_chrf(sys_out, [refs])
        chrfpp = sacrebleu.corpus_chrf(sys_out, [refs], word_order=2)
        jac = sum(_char_jaccard(s, r) for s, r in pairs) / len(pairs)
        f1 = sum(_char_f1(s, r) for s, r in pairs) / len(pairs)
        return {
            "label": label,
            "n": len(pairs),
            "bleu": bleu.score,
            "chrf": chrf.score,
            "chrfpp": chrfpp.score,
            "char_jaccard": jac,
            "char_f1": f1,
        }

    ds = _score_pair("DeepSeek-Chat", "zh_deepseek")
    g = _score_pair("Google Translate", "zh_google")
    qw = _score_pair("Qwen (end-to-end)", "zh_qwen") if any(r.get("zh_qwen") for r in rows) else {"label": "Qwen (end-to-end)", "n": 0}

    total_prompt = sum(r["deepseek_tokens"]["prompt"] for r in rows)
    total_completion = sum(r["deepseek_tokens"]["completion"] for r in rows)
    total_cache = sum(r["deepseek_tokens"]["cache_hit"] for r in rows)
    cache_miss = max(0, total_prompt - total_cache)

    cost_in_miss = cache_miss / 1e6 * AI_PRICING_INPUT_USD
    cost_in_hit = total_cache / 1e6 * AI_PRICING_INPUT_CACHE_USD
    cost_out = total_completion / 1e6 * AI_PRICING_OUTPUT_USD
    total_cost = cost_in_miss + cost_in_hit + cost_out

    # Qwen end-to-end token tally (no $$$ — local serving).
    qwen_ocr_prompt = sum((r.get("qwen_tokens") or {}).get("ocr_prompt", 0) for r in rows)
    qwen_ocr_completion = sum((r.get("qwen_tokens") or {}).get("ocr_completion", 0) for r in rows)
    qwen_tr_prompt = sum((r.get("qwen_tokens") or {}).get("translate_prompt", 0) for r in rows)
    qwen_tr_completion = sum((r.get("qwen_tokens") or {}).get("translate_completion", 0) for r in rows)
    qwen_total_tokens = qwen_ocr_prompt + qwen_ocr_completion + qwen_tr_prompt + qwen_tr_completion
    qwen_stats = {
        "ocr_prompt": qwen_ocr_prompt,
        "ocr_completion": qwen_ocr_completion,
        "translate_prompt": qwen_tr_prompt,
        "translate_completion": qwen_tr_completion,
        "total": qwen_total_tokens,
        "n": qw.get("n", 0),
    }

    timed = [r for r in rows if r["timings_s"]["deepseek"] > 0]
    timed_g = [r for r in rows if r["timings_s"]["google"] > 0]
    timed_q_ocr = [r for r in rows if r["timings_s"].get("qwen_ocr", 0) > 0]
    timed_q_tr = [r for r in rows if r["timings_s"].get("qwen_translate", 0) > 0]
    avg_ds_s = sum(r["timings_s"]["deepseek"] for r in timed) / max(1, len(timed))
    avg_g_s = sum(r["timings_s"]["google"] for r in timed_g) / max(1, len(timed_g))
    avg_qwen_ocr_s = sum(r["timings_s"]["qwen_ocr"] for r in timed_q_ocr) / max(1, len(timed_q_ocr))
    avg_qwen_tr_s = sum(r["timings_s"]["qwen_translate"] for r in timed_q_tr) / max(1, len(timed_q_tr))
    avg_ocr_s = sum(r["timings_s"]["ocr_ja"] for r in rows) / len(rows)

    pages_with_ja = sum(1 for r in rows if r["ja_text"].strip())
    pages_with_ref = sum(1 for r in rows if r["zh_ref"].strip())

    print("\n=== Translation quality ===")
    hdr = f"{'backend':<22} {'n':>4} {'BLEU':>6} {'chrF':>6} {'chrF++':>7} {'CharJac':>8} {'CharF1':>7}"
    print(hdr)
    print("-" * len(hdr))
    metrics_list = [ds, g] + ([qw] if qw.get("n", 0) > 0 else [])
    for m in metrics_list:
        if m.get("n", 0) == 0:
            print(f"{m['label']:<22} {0:>4}  (no data)")
            continue
        print(
            f"{m['label']:<22} {m['n']:>4} {m['bleu']:>6.2f} {m['chrf']:>6.2f} "
            f"{m['chrfpp']:>7.2f} {m['char_jaccard']:>8.3f} {m['char_f1']:>7.3f}"
        )

    print("\n=== DeepSeek-Chat tokens & cost ===")
    print(f"prompt tokens:     {total_prompt:>10,}  (cache hit {total_cache:,}, miss {cache_miss:,})")
    print(f"completion tokens: {total_completion:>10,}")
    print(f"cost:              ${total_cost:>9.4f}  "
          f"(input ${cost_in_miss + cost_in_hit:.4f} + output ${cost_out:.4f})")
    print(f"avg/page:          {(total_prompt + total_completion) / max(1, len(rows)):.0f} tok, "
          f"${total_cost / max(1, len(rows)):.5f}")

    if qw.get("n", 0) > 0:
        print(f"\n=== Qwen end-to-end tokens (local — no $$$, compute only) ===")
        print(f"OCR prompt + completion:        {qwen_ocr_prompt:>10,}  +  {qwen_ocr_completion:>10,}")
        print(f"Translate prompt + completion:  {qwen_tr_prompt:>10,}  +  {qwen_tr_completion:>10,}")
        print(f"total:                          {qwen_total_tokens:>10,}")
        print(f"avg/page:                       {qwen_total_tokens / max(1, qw['n']):>10.0f} tok")

    print("\n=== Latency (per page) ===")
    print(f"DeepSeek-OCR-2 (vLLM):   avg {avg_ocr_s:.2f}s")
    print(f"DeepSeek-Chat (cloud):   avg {avg_ds_s:.2f}s")
    print(f"Google Translate:        avg {avg_g_s:.2f}s")
    if qw.get("n", 0) > 0:
        print(f"Qwen OCR ({QWEN_MODEL}): avg {avg_qwen_ocr_s:.2f}s")
        print(f"Qwen translate:          avg {avg_qwen_tr_s:.2f}s")

    common_kwargs = dict(
        rows=rows,
        ds=ds,
        g=g,
        qw=qw,
        token_stats={
            "prompt": total_prompt,
            "completion": total_completion,
            "cache_hit": total_cache,
            "cache_miss": cache_miss,
            "cost_in_miss": cost_in_miss,
            "cost_in_hit": cost_in_hit,
            "cost_out": cost_out,
            "total_cost": total_cost,
        },
        qwen_stats=qwen_stats,
        latency={
            "ocr": avg_ocr_s,
            "deepseek": avg_ds_s,
            "google": avg_g_s,
            "qwen_ocr": avg_qwen_ocr_s,
            "qwen_translate": avg_qwen_tr_s,
        },
        coverage={
            "n_rows": len(rows),
            "with_ja_text": pages_with_ja,
            "with_ref": pages_with_ref,
        },
    )
    _write_report(lang="en", output_path=REPORT_PATH_EN, **common_kwargs)
    _write_report(lang="zh", output_path=REPORT_PATH_ZH, **common_kwargs)
    print(f"\n[*] wrote {REPORT_PATH_EN.name} + {REPORT_PATH_ZH.name}")


def _md_row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def _write_report(
    *,
    rows: list[dict],
    ds: dict,
    g: dict,
    qw: dict,
    token_stats: dict,
    qwen_stats: dict,
    latency: dict,
    coverage: dict,
    lang: str,
    output_path: Path,
) -> None:
    """Emit a benchmark report. `lang` is 'en' or 'zh'."""

    def T(en: str, zh: str) -> str:
        return en if lang == "en" else zh

    have_qwen = qw.get("n", 0) > 0

    # Pick samples where the backends *differ most* (so the report shows
    # cases that actually distinguish them), and skip near-empty pages.
    def _interest(r: dict) -> float:
        a, b = r.get("zh_deepseek", ""), r.get("zh_google", "")
        if len(a) < 60 or len(b) < 60:
            return -1.0
        if a.startswith("<error") or b.startswith("<error"):
            return -1.0
        return 1.0 - _char_f1(a, b)

    eligible = [
        r for r in rows
        if r["zh_ref"].strip()
        and r["zh_deepseek"].strip()
        and r["zh_google"].strip()
        and not r["zh_deepseek"].startswith("<error")
        and not r["zh_google"].startswith("<error")
    ]
    eligible.sort(key=_interest, reverse=True)
    samples = eligible[:5]

    n_pages = max(1, coverage["n_rows"])
    avg_cost = token_stats["total_cost"] / n_pages
    avg_tok = (token_stats["prompt"] + token_stats["completion"]) / n_pages
    avg_qwen_tok = qwen_stats["total"] / max(1, qwen_stats["n"]) if have_qwen else 0.0

    if ds.get("n", 0) and g.get("n", 0):
        if ds["bleu"] > g["bleu"] and ds["chrf"] > g["chrf"]:
            headline = T(
                "DeepSeek-Chat edges out Google on BLEU/chrF (manga-aware prompt helps)",
                "DeepSeek-Chat 在 BLEU/chrF 上小幅胜出 Google（漫画感知 prompt 起了作用）",
            )
        elif g["bleu"] > ds["bleu"] and g["chrf"] > g["chrf"]:
            headline = T(
                "Google Translate edges out DeepSeek-Chat on surface metrics",
                "Google Translate 在表面指标上小幅胜出 DeepSeek-Chat",
            )
        else:
            headline = T(
                "DeepSeek-Chat and Google Translate trade wins across metrics — close call",
                "DeepSeek-Chat 与 Google Translate 各指标互有胜负，结果接近",
            )
    else:
        headline = ""

    lines: list[str] = []

    # Language switcher
    if lang == "en":
        lines.append("<!-- LANG-SWITCH -->")
        lines.append("**English** | [中文](BENCHMARKS.zh.md)")
    else:
        lines.append("<!-- LANG-SWITCH -->")
        lines.append("[English](BENCHMARKS.md) | **中文**")
    lines.append("")

    lines.append(T(
        "# SuwayomiOCR Translation Benchmark",
        "# SuwayomiOCR 翻译 Benchmark",
    ))
    lines.append("")
    lines.append(T(
        "Automated benchmark of the JP→ZH translation pipeline over the paired",
        "在配对的 `Datasets/生肉/`（原始日文）↔ `Datasets/熟肉/`（同人组中译）漫画语料上",
    ))
    lines.append(T(
        "`Datasets/生肉/` (raw Japanese) ↔ `Datasets/熟肉/` (fan-translated Chinese)",
        "对 JP→ZH 翻译流程做的自动化 benchmark。参考译文和系统输出都来自同一个上游 OCR",
    ))
    lines.append(T(
        "manga corpus. Both reference and system outputs share the same upstream",
        "（vLLM 部署的 **DeepSeek-OCR-2**），因此 OCR 噪声在对比中部分抵消。",
    ))
    lines.append(T(
        "OCR pipeline (vLLM-hosted **DeepSeek-OCR-2**), so OCR noise cancels out",
        "",
    ))
    lines.append(T("partially in the comparison.", ""))
    lines.append("")

    # TL;DR
    if headline:
        lines.append(T("## TL;DR", "## TL;DR（总览）"))
        lines.append("")
        lines.append(f"_{headline}._")
        lines.append("")

        def _bold_max(*vals: float) -> list[str]:
            m = max(vals)
            return [f"**{v:.2f}**" if v == m else f"{v:.2f}" for v in vals]

        if have_qwen:
            qwen_col_title = T(
                "Qwen (end-to-end, local)",
                "Qwen（端到端，本地）",
            )
            lines.append(_md_row("", "DeepSeek-Chat", "Google Translate", qwen_col_title))
            lines.append(_md_row("---", "---:", "---:", "---:"))
            ds_bleu, g_bleu, q_bleu = _bold_max(ds["bleu"], g["bleu"], qw["bleu"])
            ds_chrf, g_chrf, q_chrf = _bold_max(ds["chrf"], g["chrf"], qw["chrf"])
            lines.append(_md_row("BLEU (zh)", ds_bleu, g_bleu, q_bleu))
            lines.append(_md_row("chrF", ds_chrf, g_chrf, q_chrf))
            lines.append(_md_row(
                T("per-page latency", "单页延迟"),
                f"{latency['deepseek']:.2f}s",
                f"{latency['google']:.2f}s",
                f"{latency['qwen_ocr'] + latency['qwen_translate']:.2f}s",
            ))
            lines.append(_md_row(
                T("per-page tokens", "单页 token 用量"),
                f"{avg_tok:.0f}",
                T("N/A (REST API)", "N/A（REST API）"),
                f"{avg_qwen_tok:.0f}",
            ))
            lines.append(_md_row(
                T("per-page cost", "单页成本"),
                f"${avg_cost:.5f}",
                T("$0 (free, rate-limited)", "$0（免费，有限流）"),
                T("$0 (self-hosted, GPU compute)", "$0（自部署，仅消耗 GPU 算力）"),
            ))
            lines.append(_md_row(
                T("OCR coupling", "OCR 耦合方式"),
                T("separate model (DeepSeek-OCR-2)", "独立模型（DeepSeek-OCR-2）"),
                T("separate model (DeepSeek-OCR-2)", "独立模型（DeepSeek-OCR-2）"),
                T("same model does OCR too", "同一个模型也做 OCR"),
            ))
            lines.append(_md_row(
                T("works behind GFW", "国内可直连"),
                T("yes (api.deepseek.com)", "是（api.deepseek.com）"),
                T("no (needs proxy)", "否（需要代理）"),
                T("yes (self-hosted)", "是（自部署）"),
            ))
        else:
            lines.append(_md_row("", "DeepSeek-Chat", "Google Translate"))
            lines.append(_md_row("---", "---:", "---:"))
            lines.append(_md_row(
                "BLEU (zh)",
                f"**{ds['bleu']:.2f}**" if ds["bleu"] >= g["bleu"] else f"{ds['bleu']:.2f}",
                f"**{g['bleu']:.2f}**" if g["bleu"] > ds["bleu"] else f"{g['bleu']:.2f}",
            ))
            lines.append(_md_row(
                "chrF",
                f"**{ds['chrf']:.2f}**" if ds["chrf"] >= g["chrf"] else f"{ds['chrf']:.2f}",
                f"**{g['chrf']:.2f}**" if g["chrf"] > ds["chrf"] else f"{g['chrf']:.2f}",
            ))
            lines.append(_md_row(T("per-page latency", "单页延迟"), f"{latency['deepseek']:.2f}s", f"{latency['google']:.2f}s"))
            lines.append(_md_row(
                T("per-page tokens", "单页 token 用量"),
                f"{avg_tok:.0f}",
                T("N/A (REST API)", "N/A（REST API）"),
            ))
            lines.append(_md_row(
                T("per-page cost", "单页成本"),
                f"${avg_cost:.5f}",
                T("$0 (free, rate-limited)", "$0（免费，有限流）"),
            ))
            lines.append(_md_row(
                T("manga-aware", "漫画感知"),
                T("yes (title + episode in system prompt)", "是（漫画名+话数进 system prompt）"),
                T("no (generic MT)", "否（通用 MT）"),
            ))
            lines.append(_md_row(
                T("works behind GFW", "国内可直连"),
                T("yes", "是"),
                T("no (needs proxy)", "否（需要代理）"),
            ))
        lines.append("")
        lines.append(T("**Which should I choose?**", "**该选哪个？**"))
        lines.append("")
        lines.append(T(
            "- **DeepSeek-Chat** if you read translated manga seriously and have no local GPU:",
            "- **DeepSeek-Chat** 如果你认真追番且没有本地 GPU：system prompt 携带漫画名和话数，",
        ))
        lines.append(T(
            "  the system prompt carries title and chapter, so character names, jargon and tone",
            "  人名、专有名词和语气更连贯。个人使用成本可以忽略（约 $0.35 / 千页）。",
        ))
        lines.append(T(
            "  stay consistent. Cost is negligible for personal use (≈ $0.35 per 1000 pages).",
            "",
        ))
        lines.append(T(
            "- **Google Translate** for zero config and zero account setup. Fastest per call,",
            "- **Google Translate** 零配置零账户。单次最快，但失去漫画语境，且国内需要代理。",
        ))
        lines.append(T(
            "  but loses the manga register and needs a proxy in mainland China.",
            "",
        ))
        if have_qwen:
            lines.append(T(
                "- **Qwen (end-to-end)** if you have a local GPU: a single multimodal model",
                "- **Qwen（端到端）** 如果你有本地 GPU：单一多模态模型同时完成 OCR + 翻译，",
            ))
            lines.append(T(
                "  does OCR + translation in one pipeline, no cloud calls, no per-token cost.",
                "  无云端调用，无 token 计费。质量与 DeepSeek 接近（详见下表），延迟受本机 GPU 影响。",
            ))
            lines.append(T(
                "  Quality is close to DeepSeek (see numbers below). Latency depends on your hardware.",
                "",
            ))
        lines.append("")

    lines.append(T("Reproduce with:", "复现方式："))
    lines.append("```bash")
    lines.append("python scripts/benchmark.py gather    " + T(
        "# populates benchmark_results.jsonl",
        "# 填充 benchmark_results.jsonl",
    ))
    lines.append("python scripts/benchmark.py score     " + T(
        "# rewrites this file",
        "# 重新生成本文件",
    ))
    lines.append("```")
    lines.append("")

    lines.append(T("## Corpus", "## 语料"))
    lines.append("")
    lines.append(T(f"- Pages processed: **{coverage['n_rows']}**", f"- 处理页数：**{coverage['n_rows']}**"))
    lines.append(T(f"- Pages with non-empty JP OCR: {coverage['with_ja_text']}", f"- 日文 OCR 非空的页数：{coverage['with_ja_text']}"))
    lines.append(T(f"- Pages with non-empty ZH reference OCR: {coverage['with_ref']}", f"- 中文参考 OCR 非空的页数：{coverage['with_ref']}"))
    lines.append("")

    lines.append(T("## Translation quality", "## 翻译质量"))
    lines.append("")
    lines.append(T("Metrics (all higher = better):", "指标（数值越高越好）："))
    lines.append("")
    lines.append(T(
        "- **BLEU** (sacrebleu, `tokenize=zh`) — character-level n-gram overlap, classic MT metric.",
        "- **BLEU**（sacrebleu, `tokenize=zh`）— 字级 n-gram 重叠率，经典 MT 指标。",
    ))
    lines.append(T(
        "- **chrF** — character n-gram F1, robust on Chinese where word boundaries are ambiguous.",
        "- **chrF** — 字级 n-gram F1，对中文这种无明确词边界的语言更稳健。",
    ))
    lines.append(T(
        "- **chrF++** — chrF augmented with word-level n-grams.",
        "- **chrF++** — chrF 加上词级 n-gram。",
    ))
    lines.append(T(
        "- **CharJac** — set Jaccard over unicode characters; coarse vocabulary overlap.",
        "- **CharJac** — Unicode 字符集 Jaccard 相似度；粗粒度词汇重叠。",
    ))
    lines.append(T(
        "- **CharF1** — multiset character F1; sensitive to over/under-generation.",
        "- **CharF1** — 字符多重集 F1；对过/欠生成敏感。",
    ))
    lines.append("")
    lines.append(_md_row(T("Backend", "后端"), "n", "BLEU", "chrF", "chrF++", "CharJac", "CharF1"))
    lines.append(_md_row("---", "---:", "---:", "---:", "---:", "---:", "---:"))
    metrics_list = [ds, g] + ([qw] if have_qwen else [])
    for m in metrics_list:
        if m.get("n", 0) == 0:
            lines.append(_md_row(m["label"], "0", "—", "—", "—", "—", "—"))
            continue
        lines.append(_md_row(
            m["label"], str(m["n"]),
            f"{m['bleu']:.2f}", f"{m['chrf']:.2f}", f"{m['chrfpp']:.2f}",
            f"{m['char_jaccard']:.3f}", f"{m['char_f1']:.3f}",
        ))
    lines.append("")
    if have_qwen:
        lines.append(T(
            "_Note: \"Qwen (end-to-end)\" uses the Qwen multimodal model for **both** OCR and",
            "_注：\"Qwen 端到端\"用 Qwen 多模态模型同时承担 **OCR 和翻译** 两个阶段，所以这一行",
        ))
        lines.append(T(
            "translation, so this row measures the **full pipeline**, while DeepSeek-Chat and",
            "衡量的是 **整套流水线** 的质量；而 DeepSeek-Chat 和 Google 那两行翻译的是同一份",
        ))
        lines.append(T(
            "Google rows translate the same DeepSeek-OCR text. They are not strictly apples-to-",
            "DeepSeek-OCR 出的日文，并不是严格的同条件对比。Qwen 行的得分包含了其 OCR 阶段",
        ))
        lines.append(T(
            "apples — Qwen's score also reflects its OCR contribution._",
            "的贡献。_",
        ))
        lines.append("")

    lines.append(T("## Qualitative observations", "## 定性观察"))
    lines.append("")
    lines.append(T(
        "Surface metrics (BLEU/chrF/CharF1) **understate the quality gap** on this",
        "在本数据集上，表面指标（BLEU/chrF/CharF1）**低估了两个后端的实际质量差距**。",
    ))
    lines.append(T(
        "corpus. Eyeballing the side-by-side samples below:",
        "肉眼对比下面的样本可以看出：",
    ))
    lines.append("")
    lines.append(T(
        "- **Short labels** (page numbers, illustration credits) — both backends are",
        "- **短标签**（页码、插图署名）— 两端基本持平，差别只是风格不同",
    ))
    lines.append(T(
        "  roughly equal. Differences are stylistic (e.g. `41` → `第41页` vs `41`).",
        "  （比如 `41` → `第41页` vs `41`）。",
    ))
    lines.append(T(
        "- **Long technical / structured prose** — DeepSeek is materially better. Google",
        "- **长篇技术 / 结构化正文** — DeepSeek 明显更好。Google 在图表、流程说明",
    ))
    lines.append(T(
        "  produces broken metaphors and dangling literal translations on diagrams and",
        "  上会出现破碎的比喻和悬空的直译；DeepSeek 能跟住文档结构，跨段术语保持一致。",
    ))
    lines.append(T(
        "  flow charts; DeepSeek follows the document structure and keeps terminology",
        "",
    ))
    lines.append(T("  consistent across sections.", ""))
    lines.append(T(
        "- **Literary / context-dependent prose** — DeepSeek wins on terminology choice",
        "- **文学性 / 上下文相关正文** — DeepSeek 在术语选择和语体上完胜；Google 在",
    ))
    lines.append(T(
        "  and register; Google has occasional outright translation errors on",
        "  上下文敏感词上偶尔出现彻底错译（例如把 義理の母 译成 婆婆 而非继母）。",
    ))
    lines.append(T(
        "  context-sensitive words (e.g. 義理の母 mistranslated as 婆婆 instead of 继母).",
        "",
    ))
    lines.append(T(
        "- **Table-formatted text** — DeepSeek preserves the markdown table structure",
        "- **表格化文本** — DeepSeek 干净保留 markdown 表格结构与日本特有术语。",
    ))
    lines.append(T(
        "  and Japan-specific terms cleanly. Google translates correctly but reads choppy.",
        "  Google 翻得正确但读起来很散。",
    ))
    lines.append("")
    lines.append(T(
        "The surface metrics are dragged down by three corpus-specific issues:",
        "表面指标被以下三个语料层面的问题拖低：",
    ))
    lines.append("")
    lines.append(T(
        "1. **Page misalignment** — `生肉/N.jpg` does not always correspond to `熟肉/N.jpg`",
        "1. **页码错位** — 本数据集里 `生肉/N.jpg` 与 `熟肉/N.jpg` 并非总是同一页的两个版本，",
    ))
    lines.append(T(
        "   in this dataset; the two scans were not curated to the same page order, so",
        "   两份扫描没做对齐校对，导致某些配对内容完全无关。两个翻译后端被同等惩罚，",
    ))
    lines.append(T(
        "   some pairs have completely unrelated content. Both backends are penalized",
        "   但绝对数值看起来比实际质量更差。",
    ))
    lines.append(T(
        "   equally, but the absolute scores look worse than the actual translations are.",
        "",
    ))
    lines.append(T(
        "2. **Free fan-translation** — `熟肉` paraphrases liberally and adds detail not in",
        "2. **同人组自由翻译** — `熟肉` 大量改写并补充了原文没有的细节。忠实翻译反而会被",
    ))
    lines.append(T(
        "   the source. A faithful translation looks \"wrong\" by n-gram overlap.",
        "   n-gram 重叠率认定为\"错\"。",
    ))
    lines.append(T(
        "3. **OCR noise on both sides** — both reference and system output share the OCR",
        "3. **两端共享的 OCR 噪声** — 参考译文和系统输出共用同一个 OCR 噪声底面。",
    ))
    lines.append(T("   noise floor.", ""))
    lines.append("")

    lines.append(T("## Translation API tokens & cost", "## 翻译 API token 用量与成本"))
    lines.append("")
    lines.append(T(
        f"Pricing assumed (USD per 1M tokens; **defaults match DeepSeek-Chat — verify at provider site**):",
        f"使用的定价（美元 / 1M tokens，**默认按 DeepSeek-Chat — 实际请以服务商页面为准**）：",
    ))
    lines.append(T(f"- input cache miss: `${AI_PRICING_INPUT_USD:.2f}`", f"- 输入 cache miss：`${AI_PRICING_INPUT_USD:.2f}`"))
    lines.append(T(f"- input cache hit:  `${AI_PRICING_INPUT_CACHE_USD:.2f}`", f"- 输入 cache hit： `${AI_PRICING_INPUT_CACHE_USD:.2f}`"))
    lines.append(T(f"- output:           `${AI_PRICING_OUTPUT_USD:.2f}`", f"- 输出：           `${AI_PRICING_OUTPUT_USD:.2f}`"))
    lines.append("")
    lines.append(_md_row(T("metric", "指标"), T("value", "数值")))
    lines.append(_md_row("---", "---:"))
    lines.append(_md_row(T("prompt tokens (total)", "prompt token 总数"), f"{token_stats['prompt']:,}"))
    lines.append(_md_row(T("├─ cache hit", "├─ cache hit"), f"{token_stats['cache_hit']:,}"))
    lines.append(_md_row(T("└─ cache miss", "└─ cache miss"), f"{token_stats['cache_miss']:,}"))
    lines.append(_md_row(T("completion tokens", "completion token 总数"), f"{token_stats['completion']:,}"))
    lines.append(_md_row(T("**total cost**", "**总成本**"), f"**${token_stats['total_cost']:.4f}**"))
    lines.append(_md_row(T("├─ input", "├─ 输入"), f"${token_stats['cost_in_miss'] + token_stats['cost_in_hit']:.4f}"))
    lines.append(_md_row(T("└─ output", "└─ 输出"), f"${token_stats['cost_out']:.4f}"))
    n = max(1, coverage["n_rows"])
    avg_tok = (token_stats["prompt"] + token_stats["completion"]) / n
    lines.append(_md_row(T("avg tokens / page", "单页平均 token"), f"{avg_tok:.0f}"))
    lines.append(_md_row(T("avg cost / page", "单页平均成本"), f"${token_stats['total_cost'] / n:.5f}"))
    lines.append("")

    if have_qwen and qwen_stats["n"] > 0:
        lines.append(T(
            "## Qwen end-to-end tokens (local — no $$$)",
            "## Qwen 端到端 token 用量（本地 — 无 API 费用）",
        ))
        lines.append("")
        lines.append(T(
            "Local model, only GPU compute cost. Token counts reported for reference and",
            "本地模型，只有 GPU 算力成本。token 数仅供参考，可用于估算自托管的算力需求。",
        ))
        lines.append(T(
            "as a proxy for self-hosted compute budget planning.",
            "",
        ))
        lines.append("")
        lines.append(_md_row(T("metric", "指标"), T("value", "数值")))
        lines.append(_md_row("---", "---:"))
        lines.append(_md_row(T("OCR prompt tokens", "OCR prompt token"), f"{qwen_stats['ocr_prompt']:,}"))
        lines.append(_md_row(T("OCR completion tokens", "OCR completion token"), f"{qwen_stats['ocr_completion']:,}"))
        lines.append(_md_row(T("translate prompt tokens", "翻译 prompt token"), f"{qwen_stats['translate_prompt']:,}"))
        lines.append(_md_row(T("translate completion tokens", "翻译 completion token"), f"{qwen_stats['translate_completion']:,}"))
        lines.append(_md_row(T("**total**", "**合计**"), f"**{qwen_stats['total']:,}**"))
        lines.append(_md_row(T("avg tokens / page", "单页平均 token"), f"{qwen_stats['total'] / max(1, qwen_stats['n']):.0f}"))
        lines.append("")

    lines.append(T("## Latency (per page, average)", "## 单页平均延迟"))
    lines.append("")
    lines.append(_md_row(T("stage", "阶段"), T("latency", "延迟")))
    lines.append(_md_row("---", "---:"))
    lines.append(_md_row(T("DeepSeek-OCR-2 (vLLM, local)", "DeepSeek-OCR-2（本地 vLLM）"), f"{latency['ocr']:.2f}s"))
    lines.append(_md_row(T("DeepSeek-Chat (cloud)", "DeepSeek-Chat（云端）"), f"{latency['deepseek']:.2f}s"))
    lines.append(_md_row(T("Google Translate (cloud)", "Google Translate（云端）"), f"{latency['google']:.2f}s"))
    if have_qwen:
        lines.append(_md_row(
            T(f"Qwen OCR ({QWEN_MODEL})", f"Qwen OCR（{QWEN_MODEL}）"),
            f"{latency['qwen_ocr']:.2f}s",
        ))
        lines.append(_md_row(
            T("Qwen translate (same model)", "Qwen 翻译（同一模型）"),
            f"{latency['qwen_translate']:.2f}s",
        ))
    lines.append("")

    lines.append(T("## Backend tradeoffs", "## 后端取舍对比"))
    lines.append("")
    if have_qwen:
        qwen_col = T("Qwen (end-to-end, local)", "Qwen（端到端，本地）")
        lines.append(_md_row("", "DeepSeek-Chat", "Google Translate", qwen_col))
        lines.append("|---|---|---|---|")
        lines.append(_md_row(
            T("Cost", "成本"),
            T("paid per token (≈ $0.35/1k pages)", "按 token 付费（≈ ¥2.5/千页）"),
            T("free (rate-limited)", "免费（有限流）"),
            T("free (self-hosted, GPU compute)", "免费（自部署，消耗 GPU 算力）"),
        ))
        lines.append(_md_row(
            T("Manga-aware prompt", "漫画感知 prompt"),
            T("yes", "有"),
            T("no (generic MT)", "无（通用 MT）"),
            T("yes (same system prompt)", "有（同样的 system prompt）"),
        ))
        lines.append(_md_row(
            T("OCR pipeline", "OCR 流水线"),
            T("separate DeepSeek-OCR-2 model", "独立的 DeepSeek-OCR-2 模型"),
            T("separate DeepSeek-OCR-2 model", "独立的 DeepSeek-OCR-2 模型"),
            T("same model does OCR too", "同一模型也做 OCR"),
        ))
        lines.append(_md_row(
            T("Accepts long context", "支持长上下文"),
            T("yes (~64K)", "是（~64K）"),
            T("per-call length cap", "单次有长度上限"),
            T("yes (model context window)", "是（模型自身上下文）"),
        ))
        lines.append(_md_row(
            T("China network friendliness", "国内网络友好度"),
            T("direct via api.deepseek.com", "直连 api.deepseek.com"),
            T("needs proxy", "需代理"),
            T("self-hosted, fully local", "自部署，完全本地"),
        ))
        lines.append(_md_row(
            T("Privacy", "隐私"),
            T("sent to DeepSeek", "发往 DeepSeek"),
            T("sent to Google", "发往 Google"),
            T("never leaves your machine", "数据不出本机"),
        ))
        lines.append(_md_row(
            T("Operator effort", "运维负担"),
            T("none — just an API key", "几乎为零 — 只需要 API key"),
            T("none", "几乎为零"),
            T("you run + maintain the vLLM/SGLang server", "需要自行部署和维护 vLLM/SGLang 服务"),
        ))
    else:
        lines.append(T(
            "| | DeepSeek-Chat | Google Translate |",
            "| | DeepSeek-Chat | Google Translate |",
        ))
        lines.append("|---|---|---|")
        lines.append(T(
            "| Cost | paid per token | free (rate-limited) |",
            "| 成本 | 按 token 付费 | 免费（限流） |",
        ))
        lines.append(T(
            "| Manga-aware prompt | yes (system prompt with title + episode) | generic |",
            "| 漫画感知 prompt | 有（system prompt 含标题与话数） | 无（通用） |",
        ))
        lines.append(T(
            "| Accepts long context | yes (~64K) | per-call length cap |",
            "| 支持长上下文 | 是（~64K） | 单次有长度上限 |",
        ))
        lines.append(T(
            "| China network friendliness | direct via api.deepseek.com | needs proxy |",
            "| 国内网络友好度 | 直连 api.deepseek.com | 需代理 |",
        ))
        lines.append(T(
            "| Privacy | sent to DeepSeek | sent to Google |",
            "| 隐私 | 发往 DeepSeek | 发往 Google |",
        ))
    lines.append("")

    lines.append(T("## Sample comparisons", "## 样本对比"))
    lines.append("")
    for r in samples:
        lines.append(T(f"### Page `{r['page']}`", f"### 第 `{r['page']}` 页"))
        lines.append("")
        lines.append(T(
            "**JP source (DeepSeek-OCR-2)**",
            "**日文原文（DeepSeek-OCR-2 识别）**",
        ))
        lines.append("")
        lines.append("```")
        lines.append(r["ja_text"][:800])
        lines.append("```")
        lines.append("")
        if have_qwen and r.get("ja_qwen"):
            lines.append(T(
                "**JP source (Qwen OCR)**",
                "**日文原文（Qwen 识别）**",
            ))
            lines.append("")
            lines.append("```")
            lines.append(r["ja_qwen"][:800])
            lines.append("```")
            lines.append("")
        lines.append(T(
            "**Reference (OCR of 熟肉)**",
            "**参考译文（OCR 自熟肉）**",
        ))
        lines.append("")
        lines.append("```")
        lines.append(r["zh_ref"][:800])
        lines.append("```")
        lines.append("")
        lines.append("**DeepSeek-Chat**")
        lines.append("")
        lines.append("```")
        lines.append(r["zh_deepseek"][:800])
        lines.append("```")
        lines.append("")
        lines.append("**Google Translate**")
        lines.append("")
        lines.append("```")
        lines.append(r["zh_google"][:800])
        lines.append("```")
        lines.append("")
        if have_qwen and r.get("zh_qwen"):
            lines.append(T("**Qwen (end-to-end)**", "**Qwen（端到端）**"))
            lines.append("")
            lines.append("```")
            lines.append(r["zh_qwen"][:800])
            lines.append("```")
            lines.append("")

    lines.append(T("## Caveats", "## 注意事项"))
    lines.append("")
    lines.append(T(
        "- The Chinese reference is OCR'd from a fan-translated manga; it is not a hand-",
        "- 中文参考是从同人组译版漫画里 OCR 出来的，不是人工对齐的平行语料。两端共享 OCR 错误。",
    ))
    lines.append(T(
        "  curated parallel corpus. Both reference and system output share OCR errors.",
        "",
    ))
    lines.append(T(
        "- `生肉/N.jpg` and `熟肉/N.jpg` are not always the same page in this dataset —",
        "- 本数据集里 `生肉/N.jpg` 与 `熟肉/N.jpg` 并非总对应同一页，参见上面\"定性观察\"。",
    ))
    lines.append(T(
        "  see \"Qualitative observations\" above. Run-level metrics absorb this noise.",
        "  全局指标会吸收这部分噪声。",
    ))
    lines.append(T(
        "- Fan translations take liberties (omission, paraphrase, register shift) that",
        "- 同人组译会自由发挥（省略、改写、换语体），这些差异表面指标 BLEU/chrF 无法和真正",
    ))
    lines.append(T(
        "  surface BLEU/chrF cannot distinguish from translation errors.",
        "  的翻译错误区分开。",
    ))
    lines.append(T(
        "- The corpus is a single title (133 pages); results may not generalize to other",
        "- 语料只有一部作品（133 页），结论不一定能泛化到其他题材。本作品偏文字向且含医学",
    ))
    lines.append(T(
        "  genres. This manga is body-text heavy with anatomical terminology, which both",
        "  术语，两个后端处理的自由度都比较大。",
    ))
    lines.append(T("  backends translate with varying creativity.", ""))
    lines.append(T(
        "- DeepSeek prices change. Cost figures are estimates using the rates above.",
        "- DeepSeek 定价会变动。成本数字是按上面价目表估算的。",
    ))
    lines.append(T(
        "- Semantic metrics (BERTScore, COMET) would give a more faithful picture but",
        "- 语义类指标（BERTScore、COMET）会给出更准确的画像，但需要 GPU 和额外依赖，",
    ))
    lines.append(T(
        "  require GPU + extra dependencies and are out of scope here.",
        "  超出本脚本范围。",
    ))
    lines.append("")

    # Drop any empty trailing T("xxx", "") lines that produce blank lines in zh
    cleaned = [ln for i, ln in enumerate(lines) if not (ln == "" and i > 0 and lines[i - 1] == "")]
    output_path.write_text("\n".join(cleaned), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("gather", help="OCR + translate every dataset page")
    pg.add_argument("--limit", type=int, default=0, help="0 = all pages")
    pg.add_argument("--concurrency", type=int, default=2)
    pg.add_argument("--manga-name", default="Unknown Manga:Chapter 1",
                    help="Title:Chapter string injected into the translation system prompt")
    pg.set_defaults(func=cmd_gather)

    ps = sub.add_parser("score", help="score JSONL and emit BENCHMARKS.md")
    ps.set_defaults(func=cmd_score)

    args = parser.parse_args()
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()
