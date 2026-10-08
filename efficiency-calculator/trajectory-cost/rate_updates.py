"""Official Anthropic prices, refreshed by a detached worker, never by the caller."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_MARKDOWN_URL = PRICING_URL + ".md"
REFRESH_SECONDS = 24 * 60 * 60
RETRY_SECONDS = 15 * 60
DOWNLOAD_TIMEOUT = 15  # Worker only. The cost calculation never waits for this.
MAX_DOWNLOAD_BYTES = 2_000_000
PRICE_KEYS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")
_MODEL = re.compile(r"Claude\s+([A-Za-z][A-Za-z ]*?)\s+(\d+(?:\.\d+)*)\b")
_PRICE = re.compile(r"^\$\s*(\d+(?:\.\d+)?)\s*/\s*MTok(?:<sup>\d+</sup>)?$")


def default_cache_path() -> Path:
    configured = os.environ.get("TRAJECTORY_RATES_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(os.environ.get("LOCALAPPDATA") or
                os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "trajectory-cost" / "rates.json"


def _number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def validate_rates(rates: dict) -> None:
    if not isinstance(rates, dict) or not isinstance(rates.get("models"), dict) or not rates["models"]:
        raise ValueError("missing model prices")
    for model, spec in rates["models"].items():
        if not isinstance(model, str) or not isinstance(spec, dict):
            raise ValueError("invalid model price")
        variants = [spec]
        if "fast" in spec:
            variants.append(spec["fast"])
        previous = -1
        for tier in spec.get("tiers", []):
            threshold = tier.get("above_input_tokens") if isinstance(tier, dict) else None
            if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= previous:
                raise ValueError("invalid prompt-length price tier")
            previous = threshold
            variants.append(tier)
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError("invalid price variant")
            for key in PRICE_KEYS:
                if key in ("input", "output") or key in variant:
                    if not _number(variant.get(key)):
                        raise ValueError("invalid price: " + model + "/" + key)
    for key in ("write_5m", "write_1h", "read"):
        if not _number(rates.get("cache_multipliers", {}).get(key)):
            raise ValueError("invalid cache multiplier")
    for value in rates.get("server_tools_usd", {}).values():
        if not _number(value):
            raise ValueError("invalid server tool price")


def read_cached_rates(base: dict, cache: Path) -> dict:
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        validate_rates(saved)
        if saved.get("_pricing", {}).get("source") != PRICING_URL:
            return base
        checked_epoch(saved)
        # Classification settings belong to the caller's bundled table.
        merged = copy.deepcopy(base)
        merged["models"].update(saved["models"])
        merged["server_tools_usd"] = saved.get("server_tools_usd", base.get("server_tools_usd", {}))
        merged["_pricing"] = saved["_pricing"]
        return merged
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        return base


def checked_epoch(rates: dict) -> float:
    stamp = rates.get("_pricing", {}).get("checked_at")
    if not stamp:
        return 0.0
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _section(markdown: str, heading: str) -> str:
    found = re.search(r"^#{2,4}\s+" + re.escape(heading) + r"\s*$", markdown, re.MULTILINE)
    if not found:
        raise ValueError("missing official pricing section: " + heading)
    level = len(found.group().split()[0])
    tail = markdown[found.end():]
    end = re.search(r"^#{1," + str(level) + r"}\s+", tail, re.MULTILINE)
    return tail[:end.start()] if end else tail


def _table_rows(section: str):
    headers = None
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            headers = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r"[:\-\s]+", c) for c in cells):
            continue
        if headers is None:
            headers = [c.lower().replace("**", "") for c in cells]
            continue
        if len(cells) != len(headers):
            raise ValueError("incomplete pricing table row")
        yield dict(zip(headers, cells))


def _price(cell: str) -> float:
    match = _PRICE.fullmatch(cell.strip())
    if not match:
        raise ValueError("unsupported official price cell: " + cell)
    return float(match[1])


def _model_ids(label: str) -> list[str]:
    ids = ["claude-" + name.lower().replace(" ", "-") + "-" + version.replace(".", "-")
           for name, version in _MODEL.findall(label)]
    if not ids:
        raise ValueError("unsupported official model name: " + label)
    return ids


def parse_official_prices(markdown: str) -> dict:
    """Strictly parse base/cache, prompt-length tiers, fast mode and tool prices."""
    columns = {"input": "base input tokens", "output": "output tokens",
               "cache_write_5m": "5m cache writes", "cache_write_1h": "1h cache writes",
               "cache_read": "cache hits and refreshes"}
    models = {}
    tier_rows = {}
    tier_limits = {}
    for row in _table_rows(_section(markdown, "Model pricing")):
        if "model" not in row or not all(column in row for column in columns.values()):
            raise ValueError("unsupported official model pricing columns")
        label = row["model"]
        ids = _model_ids(label)
        if len(ids) != 1:
            raise ValueError("ambiguous model pricing row")
        model = ids[0]
        prices = {key: _price(row[column]) for key, column in columns.items()}
        tier = re.search(r"for prompts (up to|over) ([\d,]+) tokens", label, re.IGNORECASE)
        if tier:
            threshold = int(tier[2].replace(",", ""))
            if tier[1].lower() == "over":
                tier_rows.setdefault(model, []).append({"above_input_tokens": threshold, **prices})
                continue
            tier_limits[model] = threshold
        elif "for prompts" in label.lower():
            raise ValueError("unsupported prompt-length condition")
        if model in models:
            raise ValueError("duplicate base model price")
        models[model] = prices
    if not models:
        raise ValueError("empty official pricing table")
    for model, limit in tier_limits.items():
        tiers = tier_rows.get(model, [])
        if len(tiers) != 1 or tiers[0]["above_input_tokens"] != limit:
            raise ValueError("incomplete prompt-length price tiers")
        models[model]["tiers"] = tiers
    if tier_rows.keys() - tier_limits.keys():
        raise ValueError("missing base prompt-length tier")

    fast_section = _section(markdown, "Fast mode pricing")
    fast_count = 0
    for row in _table_rows(fast_section):
        if not all(k in row for k in ("model", "input", "output")):
            raise ValueError("unsupported fast mode pricing columns")
        for model in _model_ids(row["model"]):
            if model not in models or not models[model]["input"]:
                raise ValueError("missing fast mode base price")
            fast = {"input": _price(row["input"]), "output": _price(row["output"])}
            ratio = fast["input"] / models[model]["input"]
            for key in ("cache_write_5m", "cache_write_1h", "cache_read"):
                fast[key] = models[model][key] * ratio
            models[model]["fast"] = fast
            fast_count += 1
    if not fast_count or not re.search(r"[Pp]rompt caching.*apply", fast_section):
        raise ValueError("missing fast mode cache pricing rule")

    search = _section(markdown, "Web search tool")
    search_price = re.search(r"\$([\d.]+) per 1,000 searches", search)
    fetch = _section(markdown, "Web fetch tool")
    if not search_price or "no additional charges" not in fetch:
        raise ValueError("unsupported server tool pricing")
    return {"models": models, "server_tools_usd": {
        "web_search_per_1k": float(search_price[1]), "web_fetch_per_1k": 0.0}}


def _reserve_refresh(cache: Path, now: float) -> bool:
    """Nonblocking cross-process lock; failures are retried on a later calculation."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.with_suffix(".refresh").open("a+b") as fh:
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            fh.seek(0)
            try:
                last_attempt = float(fh.read() or b"0")
            except ValueError:
                last_attempt = 0.0
            if now - last_attempt < RETRY_SECONDS:
                return False
            fh.seek(0)
            fh.truncate()
            fh.write(str(now).encode("ascii"))
            fh.flush()
            return True
        except (OSError, ValueError):
            return False
        finally:
            if locked:
                if os.name == "nt":
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh, fcntl.LOCK_UN)


def schedule_refresh(base_path: Path, cache: Path, current: dict) -> bool:
    """Launch and return. No HTTP, subprocess wait, thread join or retry in caller."""
    try:
        now = time.time()
        if now - checked_epoch(current) < REFRESH_SECONDS or not _reserve_refresh(cache, now):
            return False
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                   "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                          "--base", str(base_path.resolve()), "--cache", str(cache.resolve())], **options)
        return True
    except (OSError, ValueError, TypeError):
        return False


def refresh_rates(base_path: Path, cache: Path) -> bool:
    """Worker entry point. Publish only fully downloaded and validated prices."""
    temporary = None
    try:
        base = json.loads(base_path.read_text(encoding="utf-8"))
        rates = copy.deepcopy(read_cached_rates(base, cache))
        request = Request(PRICING_MARKDOWN_URL, headers={"User-Agent": "trajectory-cost/1.0"})
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise ValueError("official pricing document too large")
        update = parse_official_prices(payload.decode("utf-8"))
        rates["models"].update(update["models"])
        rates["server_tools_usd"] = update["server_tools_usd"]
        rates["_pricing"] = {"source": PRICING_URL,
                             "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        validate_rates(rates)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache.parent,
                                         prefix="rates-", suffix=".tmp", delete=False) as fh:
            temporary = Path(fh.name)
            json.dump(rates, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temporary, cache)
        temporary = None
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Detached official pricing refresh worker")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if refresh_rates(args.base, args.cache) else 1)
