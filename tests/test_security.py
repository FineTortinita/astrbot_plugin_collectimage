import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_collectimage.main import (
    CollectImagePlugin,
    _is_public_ip,
    _normalize_allowed_groups,
)
from astrbot_plugin_collectimage.web_server import WebServer


class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_count = 0

    def save_config(self):
        self.save_count += 1


class JsonRequest:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


class FakeResolver:
    def __init__(self, addresses):
        self.addresses = addresses

    async def resolve(self, host, port=0, family=0):
        return [{"host": address} for address in self.addresses]

    async def close(self):
        return None


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(CollectImagePlugin)

    def test_empty_group_allowlist_denies_all(self):
        self.assertEqual(_normalize_allowed_groups([]), set())
        self.assertEqual(_normalize_allowed_groups(["", "  "]), set())
        self.assertEqual(_normalize_allowed_groups([123, "456"]), {"123", "456"})

    def test_remote_url_literal_address_filter(self):
        self.assertTrue(_is_public_ip("8.8.8.8"))
        self.assertFalse(_is_public_ip("127.0.0.1"))
        self.assertFalse(_is_public_ip("169.254.169.254"))
        self.assertTrue(self.plugin._is_safe_url("https://example.com/image.png"))
        self.assertFalse(self.plugin._is_safe_url("http://127.0.0.1/image.png"))
        self.assertFalse(self.plugin._is_safe_url("http://user:pass@example.com/image.png"))
        self.assertFalse(self.plugin._is_safe_url("file:///etc/passwd"))

    def test_dns_answers_with_private_ip_are_rejected(self):
        async def resolve(addresses):
            from astrbot_plugin_collectimage.main import PublicOnlyResolver

            resolver = PublicOnlyResolver(FakeResolver(addresses))
            try:
                return await resolver.resolve("example.com", 443)
            finally:
                await resolver.close()

        public_records = asyncio.run(resolve(["8.8.8.8"]))
        self.assertEqual(public_records[0]["host"], "8.8.8.8")
        with self.assertRaises(OSError):
            asyncio.run(resolve(["8.8.8.8", "127.0.0.1"]))

    def test_default_resolver_lifecycle_inside_event_loop(self):
        async def lifecycle():
            from astrbot_plugin_collectimage.main import PublicOnlyResolver

            resolver = PublicOnlyResolver()
            await resolver.close()

        asyncio.run(lifecycle())

    def test_image_filenames_are_unique_and_safe(self):
        names = {self.plugin._make_image_filename(".png") for _ in range(100)}
        self.assertEqual(len(names), 100)
        self.assertTrue(all(name.endswith(".png") for name in names))
        self.assertTrue(self.plugin._make_image_filename(".html").endswith(".jpg"))

    def test_image_copy_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            destination = Path(directory) / "destination.jpg"
            source.write_bytes(b"new")
            destination.write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                self.plugin._copy_image_exclusive(str(source), str(destination))
            self.assertEqual(destination.read_bytes(), b"existing")

    def test_model_tags_are_restricted_to_library(self):
        self.plugin.tags_library = {
            "hair": [{"name": "long_hair", "cn": "长发"}],
        }
        tags = self.plugin._sanitize_tags({
            "hair": ["长发", "<img src=x onerror=alert(1)>", "长发"],
            "unknown": ["value"],
        })
        self.assertEqual(tags, {"hair": ["长发"]})

    def test_config_update_is_saved_and_password_invalidates_sessions(self):
        config = SavingConfig({
            "webui_enabled": True,
            "webui_password": "existing-password",
            "max_api_images": 50,
        })
        server = object.__new__(WebServer)
        server.plugin = type("Plugin", (), {"config": config})()
        server._sessions = {"old-session": 1.0}

        response = asyncio.run(server.handle_update_config(JsonRequest({
            "webui_password": "new-password-123",
            "max_api_images": 25,
        })))
        body = json.loads(response.text)

        self.assertTrue(body["success"])
        self.assertEqual(config.save_count, 1)
        self.assertEqual(config["max_api_images"], 25)
        self.assertEqual(server._sessions, {})

    def test_negative_pagination_values_are_rejected_by_clamp(self):
        limit, offset = WebServer._bounded_pagination(-1, -100, 50)
        self.assertEqual(limit, 1)
        self.assertEqual(offset, 0)

    def test_untrusted_values_are_not_interpolated_into_inner_html(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        dangerous_fragments = (
            "${characterText}",
            "${tagsText",
            "${alias.original_name}",
            "${alias.alias}",
            'value="${name',
            'value="${work',
        )
        for fragment in dangerous_fragments:
            self.assertNotIn(fragment, script)


if __name__ == "__main__":
    unittest.main()
