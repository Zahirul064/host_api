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


class ChannelModeTests(unittest.TestCase):
    """--channel: চ্যানেলের আপলোড থেকে সূরা বদল (একই জায়গায়) ও নতুন যোগ।"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.meta, self.prog = self.tmp / "d.json", self.tmp / "m.json", self.tmp / "p.json"
        items = [{"itemType": "Other", "title": "x", "video_id": "OTHERvid001"},
                 {"itemType": "Quran_Recitation", "title": "সূরা ফাতিহা পুরনো", "video_id": "OLDfatiha01"},
                 {"itemType": "Quran_Recitation", "title": "হাতে বাছা", "video_id": "MANUALvid01"}]
        self.data.write_text(json.dumps({"itemType": items}, ensure_ascii=False), encoding="utf-8")
        self.meta.write_text(json.dumps({"OLDfatiha01": {"itemType": "Quran_Recitation", "surah": 1,
                                                         "source": "auto-surah"}}), encoding="utf-8")
        self.prog.write_text(json.dumps({"1": {"status": "done", "video_id": "OLDfatiha01"}}), encoding="utf-8")
        os.environ["YT_API_KEY"] = "k"
        self.orig = uv.api_get

    def tearDown(self):
        uv.api_get = self.orig

    def test_replaces_in_place_and_adds(self):
        vids = [video("NFfatiha001", "Surah Al-Fatihah | An Nafee", 500),
                video("NFfatiha002", "সূরা আল ফাতিহা সুন্দর তিলাওয়াত", 900),
                video("NFikhlas001", "Surah Al-Ikhlas recitation", 300),
                video("NFmulti0001", "Surah Al-Fatihah and Surah Al-Ikhlas", 9999),   # সংকলন → বাদ
                video("NFtafsir001", "Surah Al-Ikhlas tafsir", 9999)]                  # তাফসীর → বাদ
        byid = {v["id"]: v for v in vids}

        def fake(endpoint, params, key, quota, **kw):
            quota.spend(endpoint)
            if endpoint == "channels":
                return {"items": [{"id": "UCannafeeannafeeannafee1",
                                   "contentDetails": {"relatedPlaylists": {"uploads": "UUannafee"}}}]}
            if endpoint == "playlistItems":
                return {"items": [{"contentDetails": {"videoId": v["id"]}} for v in vids]}
            if endpoint == "videos":
                return {"items": [byid[i] for i in params["id"].split(",") if i in byid]}
            return {"items": []}
        uv.api_get = fake
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = us.main(["--channel", "@annafee_official", "--data", str(self.data), "--meta", str(self.meta),
                            "--progress", str(self.prog), "--summary-file", ""])
        self.assertEqual(code, 0, out.getvalue())
        ids = [i["video_id"] for i in json.loads(self.data.read_text(encoding="utf-8"))["itemType"]]
        self.assertEqual(ids, ["OTHERvid001", "NFikhlas001", "NFfatiha002", "MANUALvid01"])
        meta = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertNotIn("OLDfatiha01", meta)
        self.assertEqual(meta["NFfatiha002"]["surah"], 1)
        self.assertEqual(json.loads(self.prog.read_text())["112"]["video_id"], "NFikhlas001")


class ReplaceModeTests(unittest.TestCase):
    """--replace: খারাপ সূরা-ভিডিও একই জায়গায় ভালো তিলাওয়াতে বদল; শেখানো/সংকলন বাদ।"""

    def test_replace_in_place_with_recitation(self):
        tmp = Path(tempfile.mkdtemp())
        data, meta, prog = tmp / "d.json", tmp / "m.json", tmp / "p.json"
        items = [{"itemType": "Quran_Recitation", "title": "সূরা ফাতিহা (১) | Cara Membaca", "video_id": "BADfatiha01"},
                 {"itemType": "Quran_Recitation", "title": "সূরা ইখলাস", "video_id": "GOODikhlas1"}]
        data.write_text(json.dumps({"itemType": items}, ensure_ascii=False), encoding="utf-8")
        meta.write_text(json.dumps({"BADfatiha01": {"surah": 1, "source": "auto-surah", "itemType": "Quran_Recitation"},
                                    "GOODikhlas1": {"surah": 112, "source": "auto-surah", "itemType": "Quran_Recitation"}}),
                        encoding="utf-8")
        prog.write_text(json.dumps({"1": {"status": "done", "video_id": "BADfatiha01"},
                                    "112": {"status": "done", "video_id": "GOODikhlas1"}}), encoding="utf-8")
        vids = [video("RPteach0001", "Cara Membaca Surah Al-Fatihah", 99999),
                video("RPplain0001", "Surah Al-Fatihah", 50000),                       # তিলাওয়াত শব্দ নেই
                video("RPrecite001", "Surah Al-Fatihah beautiful recitation", 1000)]
        byid = {v["id"]: v for v in vids}

        def fake(endpoint, params, key, quota, **kw):
            quota.spend(endpoint)
            if endpoint == "search":
                return {"items": [{"id": {"videoId": v["id"]}} for v in vids]}
            if endpoint == "videos":
                return {"items": [byid[i] for i in params["id"].split(",") if i in byid]}
            return {"items": []}
        os.environ["YT_API_KEY"] = "k"
        orig, uv.api_get = uv.api_get, fake
        try:
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = us.main(["--replace", "1", "--data", str(data), "--meta", str(meta),
                                "--progress", str(prog), "--summary-file", ""])
        finally:
            uv.api_get = orig
        self.assertEqual(code, 0, out.getvalue())
        ids = [i["video_id"] for i in json.loads(data.read_text(encoding="utf-8"))["itemType"]]
        self.assertEqual(ids, ["RPrecite001", "GOODikhlas1"])
        m = json.loads(meta.read_text(encoding="utf-8"))
        self.assertNotIn("BADfatiha01", m)
        self.assertEqual(json.loads(prog.read_text())["1"]["video_id"], "RPrecite001")
