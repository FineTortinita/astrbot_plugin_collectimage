import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from astrbot_plugin_collectimage.database import Database
from astrbot_plugin_collectimage.main import CollectImagePlugin


def _make_art(path, seed=0, size=(640, 640), format="PNG", **save_kwargs):
    """Generate a structured (gradient + shapes) image so dHash is stable."""
    img = Image.new("RGB", size)
    px = img.load()
    w, h = size
    for y in range(h):
        for x in range(w):
            r = (x * 255 // w + seed * 40) % 256
            g = (y * 255 // h + seed * 80) % 256
            b = ((x + y) * 255 // (w + h) + seed * 120) % 256
            px[x, y] = (r, g, b)
    draw = ImageDraw.Draw(img)
    for i in range(5 + seed):
        cx = (w // 6) * (i + 1) % w
        cy = (h // 5) * (i + 1) % h
        rr = 30 + (i * 17 + seed * 23) % 90
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                     fill=((i * 55 + seed * 30) % 256, (i * 90) % 256, (i * 33) % 256))
    img.save(path, format=format, **save_kwargs)
    return path


def _hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class PhashDedupTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(CollectImagePlugin)

    def test_phash_signature_format(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_art(os.path.join(d, "a.png"), seed=1)
            sig = self.plugin._calculate_phash(p)
            self.assertEqual(len(sig), 80)
            int(sig, 16)  # 合法 hex
            self.assertIsNotNone(Database._split_phash(sig))

    def test_recompressed_and_resized_is_near_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            base = _make_art(os.path.join(d, "base.png"), seed=2)
            jpg = os.path.join(d, "recompressed.jpg")
            Image.open(base).convert("RGB").save(jpg, format="JPEG", quality=55)
            small = os.path.join(d, "small.png")
            im = Image.open(base).convert("RGB")
            im.resize((im.width // 2, im.height // 2)).save(small, format="PNG")

            sig_base = self.plugin._calculate_phash(base)
            sig_jpg = self.plugin._calculate_phash(jpg)
            sig_small = self.plugin._calculate_phash(small)

            self.assertLessEqual(_hamming(sig_base[16:], sig_jpg[16:]), 24)
            self.assertLessEqual(_hamming(sig_base[16:], sig_small[16:]), 24)

    def test_different_images_are_not_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_art(os.path.join(d, "a.png"), seed=3)
            b = _make_art(os.path.join(d, "b.png"), seed=11)
            sig_a = self.plugin._calculate_phash(a)
            sig_b = self.plugin._calculate_phash(b)
            self.assertGreater(_hamming(sig_a, sig_b), 24)

    def test_database_find_similar_phash(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            try:
                sig = self.plugin._calculate_phash(_make_art(os.path.join(d, "x.png"), seed=5))
                self.assertTrue(db.insert_image(
                    file_hash="h1", file_path=os.path.join(d, "x.png"),
                    file_name="x.png", group_id="g", sender_id="s",
                    timestamp=1, phash=sig,
                ))
                hit = db.find_similar_phash(sig, threshold=24)
                self.assertIsNotNone(hit)
                self.assertEqual(hit["file_hash"], "h1")

                other = self.plugin._calculate_phash(_make_art(os.path.join(d, "y.png"), seed=17))
                self.assertIsNone(db.find_similar_phash(other, threshold=24))
            finally:
                db.close()

    def test_duplicate_groups_cluster(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            try:
                base = _make_art(os.path.join(d, "b0.png"), seed=7)
                sig0 = self.plugin._calculate_phash(base)
                jpg = os.path.join(d, "b0.jpg")
                Image.open(base).convert("RGB").save(jpg, format="JPEG", quality=50)
                sig1 = self.plugin._calculate_phash(jpg)
                db.insert_image("h0", base, "b0.png", "g", "s", 1, phash=sig0)
                db.insert_image("h1", jpg, "b0.jpg", "g", "s", 2, phash=sig1)

                groups = db.find_duplicate_groups(threshold=24)
                self.assertEqual(len(groups), 1)
                self.assertEqual(len(groups[0]), 2)
            finally:
                db.close()

    def test_legacy_short_phash_is_recomputed(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            try:
                db.insert_image("h0", "/nope.png", "n.png", "g", "s", 1, phash="0123456789abcdef")
                self.assertEqual(db.count_images_without_valid_phash(), 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
