"""Offline tests, including a real detached worker with a deliberately blocked download."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import rate_updates as ru
import trajectory_cost as tc

PRICING = """## Model pricing
| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| --- | --- | --- | --- | --- | --- |
| Claude Opus 5 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |
| Claude Opus 4.8 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Fable 5.1 | $10 / MTok | $12.50 / MTok | $20 / MTok | $0.25 / MTok<sup>1</sup> | $50 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |

## Feature-specific pricing
### Fast mode pricing
| Model | Input | Output |
| --- | --- | --- |
| Claude Opus 5.5 | $8 / MTok | $40 / MTok |
| Claude Opus 5 / Claude Opus 4.8 | $10 / MTok | $50 / MTok |

* **Prompt caching** multipliers apply on top of fast mode pricing

### Specific tool pricing
#### Web search tool
Web search is available for $10 per 1,000 searches.
#### Web fetch tool
Web fetch usage has **no additional charges** beyond standard token costs.
"""
BASE = tc.load_rates(tc.RATES_PATH)


def _call(model, **tokens):
    return tc.Call("m", None, model, None, None, False, "standard", **tokens)


class RateUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cache = self.root / "cache" / "rates.json"

    def _refresh(self, text=PRICING):
        with patch.object(ru, "urlopen", return_value=io.BytesIO(text.encode())):
            return ru.refresh_rates(tc.RATES_PATH, self.cache)

    def test_parse_official_cache_fast_and_tiers(self):
        result = ru.parse_official_prices(PRICING)
        self.assertEqual(result["models"]["claude-fable-5-1"]["cache_read"], 0.25)
        self.assertEqual(result["models"]["claude-opus-5-5"]["fast"]["cache_read"], 0.4)
        self.assertEqual(result["models"]["claude-opus-4-8"]["fast"]["output"], 50)
        self.assertEqual(result["models"]["claude-haiku-5-5"]["tiers"][0]["above_input_tokens"], 100000)

    def test_success_keeps_old_models_and_policy(self):
        self.assertTrue(self._refresh())
        saved = ru.read_cached_rates(BASE, self.cache)
        self.assertIn("claude-sonnet-4-5", saved["models"])
        self.assertIn("claude-opus-5-5", saved["models"])
        self.assertEqual(saved["free_models"], BASE["free_models"])
        self.assertEqual(saved["_pricing"]["source"], ru.PRICING_URL)
        self.assertGreater(ru.checked_epoch(saved), time.time() - 10)
        self.assertEqual(list(self.cache.parent.glob("*.tmp")), [])

    def test_failure_and_changed_format_preserve_saved_file(self):
        self.assertTrue(self._refresh())
        original = self.cache.read_bytes()
        with patch.object(ru, "urlopen", side_effect=TimeoutError("offline")):
            self.assertFalse(ru.refresh_rates(tc.RATES_PATH, self.cache))
        bad_documents = ["<html>unavailable</html>",
                         PRICING.replace("$4 / MTok", "$4 / unknown-unit"),
                         PRICING.replace("| Base input tokens |", "| Unknown column |"),
                         PRICING.replace("for prompts over 100,000", "for prompts over 200,000"),
                         PRICING.replace("**Prompt caching** multipliers apply", "unknown cache rule")]
        for text in bad_documents:
            self.assertFalse(self._refresh(text))
            self.assertEqual(self.cache.read_bytes(), original)

    def test_invalid_cache_uses_bundled_prices(self):
        self.cache.parent.mkdir()
        self.cache.write_text("{broken", encoding="utf-8")
        self.assertIs(ru.read_cached_rates(BASE, self.cache), BASE)
        invalid = copy.deepcopy(BASE)
        invalid["models"]["claude-opus-5"]["input"] = -1
        self.cache.write_text(json.dumps(invalid), encoding="utf-8")
        self.assertIs(ru.read_cached_rates(BASE, self.cache), BASE)

    def test_atomic_publish_failure_keeps_previous_file(self):
        self.assertTrue(self._refresh())
        original = self.cache.read_bytes()
        with patch.object(ru.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(self._refresh())
        self.assertEqual(self.cache.read_bytes(), original)
        self.assertEqual(list(self.cache.parent.glob("*.tmp")), [])

    def test_load_returns_unchanged_snapshot_even_if_worker_finishes(self):
        def finish_refresh(*args):
            self.assertTrue(self._refresh())
        with patch.dict(os.environ, {"TRAJECTORY_RATES_CACHE": str(self.cache),
                                     "TRAJECTORY_RATES_AUTO_UPDATE": "1"}), \
                patch.object(tc, "schedule_refresh", side_effect=finish_refresh):
            snapshot = tc.load_rates()
            self.assertNotIn("claude-opus-5-5", snapshot["models"])
            following = tc.load_rates(auto_update=False)
            self.assertIn("claude-opus-5-5", following["models"])

    def test_custom_table_and_disabled_refresh_never_launch(self):
        with patch.dict(os.environ, {"TRAJECTORY_RATES_CACHE": str(self.cache),
                                     "TRAJECTORY_RATES_AUTO_UPDATE": "0"}), \
                patch.object(tc, "schedule_refresh") as launch:
            self.assertEqual(tc.load_rates(tc.RATES_PATH), BASE)
            tc.load_rates()
            tc.load_rates(auto_update=False)
            launch.assert_not_called()

    def test_scheduler_launches_once_without_http_or_wait(self):
        with patch.object(ru, "urlopen", side_effect=AssertionError("HTTP in caller")), \
                patch.object(ru.subprocess, "Popen") as launch:
            self.assertTrue(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))
            self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))
            launch.assert_called_once()
            launch.return_value.wait.assert_not_called()
            launch.return_value.communicate.assert_not_called()
            kwargs = launch.call_args.kwargs
            if os.name == "nt":
                self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
            else:
                self.assertTrue(kwargs["start_new_session"])

    def test_fresh_table_skips_refresh(self):
        current = copy.deepcopy(BASE)
        current["_pricing"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        with patch.object(ru.subprocess, "Popen") as launch:
            self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, current))
            launch.assert_not_called()
        self.assertFalse(self.cache.with_suffix(".refresh").exists())

    def test_retry_after_failure_and_unwritable_cache(self):
        with patch.object(ru.subprocess, "Popen", side_effect=OSError("launch failure")) as launch:
            self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))
            self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))
            self.assertEqual(launch.call_count, 1)
            later = time.time() + ru.RETRY_SECONDS + 1
            with patch.object(ru.time, "time", return_value=later):
                self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))
            self.assertEqual(launch.call_count, 2)
        with patch.object(ru, "_reserve_refresh", side_effect=PermissionError("read only")):
            self.assertFalse(ru.schedule_refresh(tc.RATES_PATH, self.cache, BASE))

    def test_prompt_length_threshold_counts_cached_input(self):
        rates = copy.deepcopy(BASE)
        rates["models"].update(ru.parse_official_prices(PRICING)["models"])
        at_limit = _call("claude-haiku-5-5", input_tokens=1, cache_read=99999, output_tokens=1000000)
        above_limit = _call("claude-haiku-5-5", input_tokens=1, cache_read=100000, output_tokens=1000000)
        self.assertAlmostEqual(tc.call_cost(at_limit, rates)[0], 0.5000001 + 0.00099999)
        self.assertAlmostEqual(tc.call_cost(above_limit, rates)[0], 2.5 + 0.0000005 + 0.005)

    def test_cli_exits_before_blocked_download_and_worker_survives(self):
        """Caller must exit while the real child is still waiting for our release file."""
        fixture = self.root / "pricing.md"
        fixture.write_text(PRICING, encoding="utf-8")
        started, release = self.root / "started", self.root / "release"
        session = self.root / "session.jsonl"
        session.write_text(json.dumps({"message": {"id": "m", "model": "claude-opus-5-5",
                                                    "usage": {"output_tokens": 1000000}}}), encoding="utf-8")
        worker = "\n".join([
            "import io, time", "from pathlib import Path", "import rate_updates as ru",
            "def blocked_download(*args, **kwargs):",
            f"    Path({str(started)!r}).touch()",
            "    deadline = time.monotonic() + 20",
            f"    while not Path({str(release)!r}).exists():",
            "        if time.monotonic() > deadline: raise TimeoutError('test not released')",
            "        time.sleep(0.01)",
            f"    return io.BytesIO(Path({str(fixture)!r}).read_bytes())",
            "ru.urlopen = blocked_download",
            f"raise SystemExit(0 if ru.refresh_rates(Path({str(tc.RATES_PATH)!r}), Path({str(self.cache)!r})) else 1)",
        ])
        caller = "\n".join([
            "import json, subprocess, sys", "import rate_updates as ru", "import trajectory_cost as tc",
            "launch = subprocess.Popen",
            f"ru.subprocess.Popen = lambda command, **options: launch([sys.executable, '-c', {worker!r}], **options)",
            f"tc.main([{str(session)!r}, '--json'])",
        ])
        env = {**os.environ, "TRAJECTORY_RATES_CACHE": str(self.cache), "TRAJECTORY_RATES_AUTO_UPDATE": "1"}
        try:
            result = subprocess.run([sys.executable, "-c", caller], cwd=tc.RATES_PATH.parent,
                                    env=env, capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["trajectory_cost_usd"], 0)
            self.assertFalse(release.exists())
            self.assertFalse(self.cache.exists())
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists(), "detached worker did not start")
        finally:
            release.touch()
        deadline = time.monotonic() + 5
        while not self.cache.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.cache.exists(), "worker was killed when the caller exited")
        with patch.dict(os.environ, env), patch.object(tc, "schedule_refresh"):
            self.assertEqual(tc.session_cost_usd(session), 20)


if __name__ == "__main__":
    unittest.main()
