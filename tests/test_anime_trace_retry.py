import asyncio
import unittest
from unittest import mock

from astrbot_plugin_collectimage.main import CollectImagePlugin


class _Cfg(dict):
    def __getattr__(self, k):
        return self.get(k)


class AnimeTraceRetryTest(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(CollectImagePlugin)
        self.plugin.config = _Cfg(anime_trace_delay=1, anime_trace_max_retries=2, anime_trace_cooldown=60)
        self.sleeps = []

        async def fake_sleep(s):
            self.sleeps.append(s)

        self.sleep_patch = mock.patch("astrbot_plugin_collectimage.main.asyncio.sleep", fake_sleep)
        self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()

    def _run(self, responses):
        calls = []

        async def fake_post(fields):
            calls.append(fields)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        self.plugin._anime_trace_post_once = fake_post
        result = asyncio.run(self.plugin.recognize_character(image_base64="AAAA"))
        return result, calls

    def test_retry_then_success(self):
        ok = ("ok", {"ai": "false", "data": [{"box_id": "1", "character": []}]}, 0.0)
        result, calls = self._run([("rate_limited", "HTTP 429", 0.0), ok])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["all_results"]), 1)

    def test_exhausted_rate_limit_enters_cooldown(self):
        result, calls = self._run([("rate_limited", "error box", 0.0)])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["ai_detect"], "限流")
        result2, calls2 = self._run([("ok", {"ai": "", "data": []}, 0.0)])
        self.assertEqual(len(calls2), 0)
        self.assertEqual(result2["ai_detect"], "冷却中")

    def test_fatal_does_not_retry(self):
        result, calls = self._run([("fatal", "HTTP 403", 0.0)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["all_results"], [])


if __name__ == "__main__":
    unittest.main()
