"""১১৪ সূরা তিলাওয়াত আপডেটারের অফলাইন টেস্ট (আসল YouTube/quota লাগে না)।"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import update_surahs as us  # noqa: E402
import update_videos as uv  # noqa: E402

SURAHS = json.loads((Path(__file__).parent / "surahs.json").read_text(encoding="utf-8"))
BY_N = {s["n"]: s for s in SURAHS}


def vid_for(n, k=0):
    return f"S{n:03d}v{k}xxxxx"[:11]


def video(vid, title, views, dur="PT5M", embed=True):
    return {"id": vid,
            "snippet": {"title": title, "publishedAt": "2026-09-01T00:00:00Z", "channelTitle": "ch",
                        "channelId": "UC" + vid.ljust(22, "x")[:22], "liveBroadcastContent": "none"},
            "contentDetails": {"duration": dur},
            "status": {"privacyStatus": "public", "embeddable": embed, "uploadStatus": "processed"},
            "statistics": {"viewCount": str(views)}}


class FakeYT:
    """প্রতি সূরার সার্চে: একটি কম ভিউ, একটি বেশি ভিউ, একটি তাফসীর, একটি অন্য সূরার ভিডিও।"""

    def __init__(self, empty_recent=(), empty_always=()):
        self.videos, self.calls = {}, []
        self.empty_recent, self.empty_always = set(empty_recent), set(empty_always)

    def __call__(self, endpoint, params, key, quota, **kw):
        quota.spend(endpoint)
        if endpoint == "search":
            self.calls.append(params)
            en = params["q"].split("Surah ", 1)[1].rsplit(" beautiful", 1)[0]
            n = next(s["n"] for s in SURAHS if s["en"] == en)
            if n in self.empty_always or (n in self.empty_recent and "publishedAfter" in params):
                return {"items": []}
            other = 1 if n != 1 else 2
            vs = [video(vid_for(n, 0), f"Surah {en} recitation", 1000),
                  video(vid_for(n, 1), f"Surah {en} | Beautiful Quran Recitation", 50000),
                  video(vid_for(n, 2), f"Surah {en} tafsir", 900000),
                  video(vid_for(n, 3), f"Surah {BY_N[other]['en']} recitation", 800000)]
            for v in vs:
                self.videos[v["id"]] = v
            return {"items": [{"id": {"videoId": v["id"]}} for v in vs]}
        if endpoint == "videos":
            return {"items": [self.videos[i] for i in params["id"].split(",") if i in self.videos]}
        return {"items": []}


EXISTING = [
    {"itemType": "Amir_Hamza", "title": "a", "video_id": "AAAAAAAAAA1"},
    {"itemType": "Quran_Recitation", "title": "পুরনো তিলাওয়াত", "video_id": "QQQQQQQQQQ1"},
    {"itemType": "Quran_Recitation", "title": "পুরনো তিলাওয়াত ২", "video_id": "QQQQQQQQQQ2"},
    {"itemType": "Bangla_Gojol", "title": "g", "video_id": "GGGGGGGGGG1"},
]


class SurahTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.meta, self.prog = (self.tmp / "v.json", self.tmp / "m.json", self.tmp / "p.json")
        self.data.write_text(json.dumps({"itemType": EXISTING}, ensure_ascii=False), encoding="utf-8")
        os.environ["YT_API_KEY"] = "k"
        self.orig = uv.api_get

    def tearDown(self):
        uv.api_get = self.orig

    def run_main(self, fake, *extra):
        uv.api_get = fake
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", out):
            code = us.main(["--data", str(self.data), "--meta", str(self.meta), "--progress", str(self.prog),
                            "--summary-file", "", *extra])
        self.out = out.getvalue()
        return code

    def items(self):
        return json.loads(self.data.read_text(encoding="utf-8"))["itemType"]

    def test_surah_list_complete(self):
        self.assertEqual([s["n"] for s in SURAHS], list(range(1, 115)))
        for s in SURAHS:
            self.assertTrue(s["bn"] and s["en"] and s["ar"] and s["en_match"] and s["bn_match"], s["n"])

    def test_picks_most_viewed_valid_recitation(self):
        self.run_main(FakeYT(), "--only", "1", "2")
        recs = [i for i in self.items() if i["video_id"].startswith("S")]
        self.assertEqual([r["video_id"] for r in recs], [vid_for(1, 1), vid_for(2, 1)])  # তাফসীর/অন্য সূরা নয়
        self.assertTrue(recs[0]["title"].startswith("সূরা আল-ফাতিহা (১) | "))
        meta = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertEqual(meta[vid_for(1, 1)]["surah"], 1)
        self.assertEqual(meta[vid_for(1, 1)]["view_count"], 50000)

    def test_placement_and_schema(self):
        self.run_main(FakeYT(), "--only", "1", "2", "3")
        ids = [i["video_id"] for i in self.items()]
        self.assertEqual(ids, ["AAAAAAAAAA1", vid_for(1, 1), vid_for(2, 1), vid_for(3, 1),
                               "QQQQQQQQQQ1", "QQQQQQQQQQ2", "GGGGGGGGGG1"])
        doc = json.loads(self.data.read_text(encoding="utf-8"))
        self.assertEqual(list(doc), ["itemType"])
        for i in doc["itemType"]:
            self.assertEqual(set(i), {"itemType", "title", "video_id"})

    def test_batches_continue_in_order_across_days(self):
        # দিন ১: বাজেটে ৩টি সূরা (৩×১০১=৩০৩)
        self.run_main(FakeYT(), "--budget", "310")
        # দিন ২: পরের ৩টি
        self.run_main(FakeYT(), "--budget", "310")
        sur = [i["video_id"] for i in self.items() if i["video_id"].startswith("S")]
        self.assertEqual(sur, [vid_for(n, 1) for n in range(1, 7)])
        prog = json.loads(self.prog.read_text(encoding="utf-8"))
        self.assertEqual(sorted(int(k) for k, v in prog.items() if v["status"] == "done"), [1, 2, 3, 4, 5, 6])
        self.assertIn("6/114", self.out)

    def test_full_run_covers_114_in_two_days(self):
        fake = FakeYT()
        self.run_main(fake, "--budget", "6000")
        self.run_main(fake, "--budget", "6000")
        sur = [i for i in self.items() if i["video_id"].startswith("S")]
        self.assertEqual(len(sur), 114)
        self.assertEqual([i["video_id"] for i in sur], [vid_for(n, 1) for n in range(1, 115)])
        # তৃতীয় রান: কিছুই করার নেই, কোনো quota খরচ নয়
        calls_before = len(fake.calls)
        self.run_main(fake, "--budget", "6000")
        self.assertEqual(len(fake.calls), calls_before)

    def test_retry_all_time_then_not_found(self):
        fake = FakeYT(empty_recent={5}, empty_always={7})
        self.run_main(fake, "--only", "5", "7")
        prog = json.loads(self.prog.read_text(encoding="utf-8"))
        self.assertEqual(prog["5"]["status"], "retry")
        self.assertEqual(prog["7"]["status"], "retry")
        self.run_main(fake, "--only", "5", "7")
        prog = json.loads(self.prog.read_text(encoding="utf-8"))
        self.assertEqual(prog["5"]["status"], "done")          # সব সময়ের মধ্যে পাওয়া গেছে
        self.assertEqual(prog["7"]["status"], "not_found")
        self.assertNotIn("publishedAfter", fake.calls[-1])
        meta = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertEqual(meta[vid_for(5, 1)]["window"], "all-time")

    def test_dry_run_changes_nothing(self):
        before = self.data.read_text(encoding="utf-8")
        self.run_main(FakeYT(), "--only", "1", "--dry-run")
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))
        self.assertFalse(self.prog.exists())

    def test_invalid_key(self):
        before = self.data.read_text(encoding="utf-8")

        def bad(endpoint, params, key, quota, **kw):
            raise uv.InvalidKeyError("bad")
        self.assertEqual(self.run_main(bad, "--only", "1"), 3)
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))

    def test_matching_edge_cases(self):
        cases = [("Surah An-Nasr", 114, False), ("Surah An-Nas", 114, True), ("سورة الحجرات", 22, False),
                 ("سورة الحج", 22, True), ("Surah Ya-Sin", 36, True), ("سورة ص", 38, True),
                 ("سورة الصافات", 38, False), ("so sad recitation", 38, False), ("সূরা ইয়াসিন", 36, True),
                 ("সূরা নাসর", 114, False), ("Mizanur Rahman waz", 55, False), ("Surah Al-A'la", 87, True),
                 ("Surah Al-Alaq", 87, False), ("سُورَةُ الْبَقَرَة", 2, True)]
        for title, n, expected in cases:
            self.assertEqual(us.title_matches_surah(title, BY_N[n]), expected, (title, n))


if __name__ == "__main__":
    unittest.main()
