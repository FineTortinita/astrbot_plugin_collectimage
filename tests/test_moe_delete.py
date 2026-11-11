import asyncio
import os
import shutil
import tempfile
import unittest

from PIL import Image as PILImage, ImageDraw

from astrbot.core.message.components import Image, Plain, Reply

from astrbot_plugin_collectimage.database import Database
from astrbot_plugin_collectimage.main import (
    CollectImagePlugin,
    _parse_image_ids,
    _parse_moe_args,
    _parse_moe_delete_args,
)


def _make_art(path, seed=0, size=(320, 320)):
    img = PILImage.new("RGB", size, ((seed * 70) % 256, 40, 200))
    draw = ImageDraw.Draw(img)
    for i in range(4 + seed):
        x = (i * 53 + seed * 31) % size[0]
        y = (i * 71 + seed * 17) % size[1]
        draw.rectangle([x, y, x + 60, y + 40], fill=((i * 60) % 256, (seed * 90) % 256, (i * 25) % 256))
    img.save(path, format="PNG")
    return path


class FakeEvent:
    def __init__(self, messages=None, admin=True):
        self._messages = messages or []
        self.role = "admin" if admin else "member"

    def is_admin(self):
        return self.role == "admin"

    def get_messages(self):
        return self._messages

    def stop_event(self):
        return None

    def plain_result(self, text):
        return _Result([Plain(text)])

    def chain_result(self, chain):
        return _Result(chain)


class _Result:
    def __init__(self, chain):
        self.chain = chain

    def stop_event(self):
        return self

    @property
    def text(self):
        return "".join(c.text for c in self.chain if isinstance(c, Plain))


class MoeDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.images_dir = os.path.join(self.tmp, "images")
        os.makedirs(self.images_dir)
        self.plugin = object.__new__(CollectImagePlugin)
        self.plugin.images_dir = self.images_dir
        self.plugin.config = {}
        self.plugin.db = Database(self.tmp)

    def tearDown(self):
        self.plugin.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, seed):
        path = _make_art(os.path.join(self.images_dir, f"img{seed}.png"), seed=seed)
        self.plugin.db.insert_image(
            file_hash=self.plugin._calculate_hash(path),
            file_path=path,
            file_name=os.path.basename(path),
            group_id="1",
            sender_id="2",
            timestamp=0,
            tags={},
            character="",
            description="",
            phash=self.plugin._calculate_phash(path),
        )
        return self.plugin.db.get_image_by_hash(self.plugin._calculate_hash(path))

    def _run(self, event, args):
        async def collect():
            return [r async for r in self.plugin.moe(event, args)]
        return asyncio.run(collect())

    def test_parse_delete_args(self):
        self.assertEqual(_parse_moe_delete_args("delete 12"), "12")
        self.assertEqual(_parse_moe_delete_args("/moe delete  12 34"), "12 34")
        self.assertEqual(_parse_moe_delete_args("delete"), "")
        self.assertIsNone(_parse_moe_delete_args("deleted"))
        self.assertIsNone(_parse_moe_delete_args("Summer Pockets 3"))
        # 普通搜索仍把末尾数字视为数量
        self.assertEqual(_parse_moe_args("delete 12"), ("delete", 10))
        self.assertEqual(_parse_image_ids("12, #34 12"), ([12, 34], []))
        self.assertEqual(_parse_image_ids("12 abc"), ([12], ["abc"]))

    def test_delete_by_id_removes_record_file_and_phash_cache(self):
        img = self._add(1)
        phash = img["phash"]
        self.assertIsNotNone(self.plugin.db.find_similar_phash(phash, threshold=0))

        results = self._run(FakeEvent(), "delete " + str(img["id"]))

        self.assertEqual(results[0].text, f"已删除 #{img['id']}")
        self.assertIsNone(self.plugin.db.get_image_by_id(img["id"]))
        self.assertFalse(os.path.exists(img["file_path"]))
        self.assertIsNone(self.plugin.db.find_similar_phash(phash, threshold=0))

    def test_delete_reports_missing_ids(self):
        img = self._add(2)
        results = self._run(FakeEvent(), f"delete {img['id']} 999")
        self.assertEqual(results[0].text, f"已删除 #{img['id']}；未找到 #999")

    def test_non_admin_rejected(self):
        img = self._add(3)
        results = self._run(FakeEvent(admin=False), f"delete {img['id']}")
        self.assertEqual(results[0].text, "仅管理员可删除图片")
        self.assertIsNotNone(self.plugin.db.get_image_by_id(img["id"]))

    def test_delete_without_reply_or_id_shows_usage(self):
        results = self._run(FakeEvent(), "delete")
        self.assertIn("用法", results[0].text)

    def test_delete_quoted_image_by_md5(self):
        keep = self._add(4)
        target = self._add(5)
        quoted_copy = os.path.join(self.tmp, "quoted.png")
        shutil.copy(target["file_path"], quoted_copy)
        reply = Reply(id="1", chain=[Image.fromFileSystem(quoted_copy)])

        results = self._run(FakeEvent([reply, Plain("/moe delete")]), "delete")

        self.assertEqual(results[0].text, f"已删除 #{target['id']}")
        self.assertIsNone(self.plugin.db.get_image_by_id(target["id"]))
        self.assertIsNotNone(self.plugin.db.get_image_by_id(keep["id"]))

    def test_delete_quoted_image_not_in_library(self):
        self._add(6)
        other = _make_art(os.path.join(self.tmp, "other.png"), seed=9, size=(200, 500))
        reply = Reply(id="1", chain=[Image.fromFileSystem(other)])
        results = self._run(FakeEvent([reply]), "delete")
        self.assertEqual(results[0].text, "被引用的图片不在图库中")

    def test_delete_quoted_bot_message_by_id_text(self):
        img = self._add(7)
        reply = Reply(id="1", chain=[Plain(f"#{img['id']}")], message_str=f"#{img['id']}")
        results = self._run(FakeEvent([reply]), "delete")
        self.assertEqual(results[0].text, f"已删除 #{img['id']}")

    def test_search_result_includes_id(self):
        img = self._add(8)
        results = self._run(FakeEvent(), "")
        self.assertEqual(results[0].chain[-1].text, f"#{img['id']}")


if __name__ == "__main__":
    unittest.main()
