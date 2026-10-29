"""অফলাইন টেস্ট — আসল YouTube API বা quota ছাড়াই পুরো পাইপলাইন যাচাই করে।
চালাতে:  python3 -m unittest discover -s scripts -p "test_*.py" -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import update_videos as uv  # noqa: E402

REPO_JSON = Path(__file__).resolve().parent.parent / "video_studio.json"
REPO_ICONS = Path(__file__).resolve().parent.parent / "waz_icone.json"


# ── Flutter মডেলের হুবহু অনুকরণ (lib/models/video_item.dart, providers) ──────
def dart_video_item_from_json(j):
    return {"itemType": str(j.get("itemType") or ""), "title": str(j.get("title") or "Untitled"),
            "videoId": str(j.get("video_id") or "")}


def dart_parse_global(body, voice_item_type):
    """VideoProvider._parseGlobalJson-এর আচরণ।"""
    decoded = json.loads(body)
    items, seen, out = decoded["itemType"] or [], set(), []
    for i in items:
        vid, it = str(i.get("video_id") or "").strip(), str(i.get("itemType") or "")
        if not vid or it == "Home_Page" or vid in seen:
            continue
        seen.add(vid)
        if voice_item_type in it:
            out.append(dart_video_item_from_json(i))
    return out


def dart_video_counts(body):
    """ScholarIconProvider._mergeVideoTypes-এর আচরণ।"""
    c = {}
    for i in json.loads(body)["itemType"]:
        t, v = str(i.get("itemType") or "").strip(), str(i.get("video_id") or "").strip()
        if t and t != "Home_Page" and v:
            c[t] = c.get(t, 0) + 1
    return c


# ── fake YouTube ────────────────────────────────────────────────────────
def video(vid, title, dur="PT40M", public=True, embed=True, pub="2026-10-20T10:00:00Z", live="none", ch="UCaaaaaaaaaaaaaaaaaaaaaa"):
    return {"id": vid,
            "snippet": {"title": title, "publishedAt": pub, "channelTitle": "চ্যানেল", "channelId": ch,
                        "liveBroadcastContent": live},
            "contentDetails": {"duration": dur},
            "status": {"privacyStatus": "public" if public else "private", "embeddable": embed,
                       "uploadStatus": "processed"}}


class FakeYouTube:
    def __init__(self, search_results, videos, fail=None):
        self.search_results = search_results   # query -> [ids]  or Exception
        self.videos = {v["id"]: v for v in videos}
        self.fail = fail or {}
        self.calls = []

    def __call__(self, endpoint, params, key, quota, **kw):
        quota.spend(endpoint)
        self.calls.append((endpoint, params.get("q") or params.get("id")))
        if endpoint in self.fail:
            exc = self.fail[endpoint]
            raise exc() if isinstance(exc, type) else exc
        if endpoint == "search":
            r = self.search_results.get(params["q"], [])
            if isinstance(r, Exception):
                raise r
            return {"items": [{"id": {"videoId": i}} for i in r]}
        if endpoint == "videos":
            return {"items": [self.videos[i] for i in params["id"].split(",") if i in self.videos]}
        return {"items": []}


EXISTING = [
    {"itemType": "Noman_Ali_Khan", "title": "পুরনো ১", "video_id": "rLKhbUCH2-A"},
    {"itemType": "Amir_Hamza", "title": "পুরনো ২", "video_id": "OLDvideo001"},
    {"itemType": "Tarik_Monwar", "title": "পুরনো ৩", "video_id": "sfng9s4zkDY"},
    {"itemType": "Amir_Hamza", "title": "পুরনো ৪", "video_id": "OLDvideo002"},
    {"itemType": "Noman_Ali_Khan", "title": "পুরনো ১ ডুপ্লিকেট", "video_id": "rLKhbUCH2-A"},
]

CONFIG = {
    "defaults": {"lookback_days": 14, "search_max_results": 25, "min_duration_sec": 600,
                 "max_new_per_category": 5, "region_code": "BD", "relevance_language": "bn",
                 "quota_budget": 5000},
    "blocked_title_words": ["#shorts", "shorts", "troll"],
    "blocked_channel_ids": ["UCbbbbbbbbbbbbbbbbbbbbbb"],
    "scholars": [
        {"key": "Amir_Hamza", "auto": True, "queries": ["আমির হামজা ওয়াজ", "Amir Hamza waz"],
         "must_match": ["আমির হামজা", "amir hamza"]},
        {"key": "Tarik_Monwar", "auto": True, "queries": ["তারেক মনোয়ার"],
         "must_match": ["তারেক মনোয়ার", "tarek monowar"]},
        {"key": "Bangla_Gojol", "auto": False},
    ],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "video_studio.json"
        self.meta = self.tmp / "video_meta.json"
        self.conf = self.tmp / "config.json"
        self.data.write_text(json.dumps({"itemType": EXISTING}, ensure_ascii=False, indent=4), encoding="utf-8")
        self.conf.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        os.environ["YT_API_KEY"] = "test-key"
        self.orig_api = uv.api_get

    def tearDown(self):
        uv.api_get = self.orig_api

    def run_main(self, fake, *extra):
        uv.api_get = fake
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", out):
            code = uv.main(["--config", str(self.conf), "--data", str(self.data), "--meta", str(self.meta),
                            "--summary-file", "", *extra])
        self.output = out.getvalue()
        return code

    def items(self):
        return json.loads(self.data.read_text(encoding="utf-8"))["itemType"]


class PipelineTests(Base):
    def standard_fake(self):
        return FakeYouTube(
            {"আমির হামজা ওয়াজ": ["NEWvideo001", "NEWvideo002", "NEWvideo003", "OLDvideo001"],
             "Amir Hamza waz": ["NEWvideo001", "NEWvideo004", "NEWvideo005"],
             "তারেক মনোয়ার": ["NEWtarik001"]},
            [video("NEWvideo001", "নতুন ওয়াজ | আমির হামজা", pub="2026-10-25T00:00:00Z"),
             video("NEWvideo002", "Amir Hamza #shorts", dur="PT40S"),
             video("NEWvideo003", "অন্য বক্তার ওয়াজ"),
             video("NEWvideo004", "amir hamza new waz 2026", pub="2026-10-26T00:00:00Z", embed=False),
             video("NEWvideo005", "AMIR HAMZA tafsir", pub="2026-10-24T00:00:00Z"),
             video("NEWtarik001", "আল্লামা তারেক মনোয়ার নতুন ওয়াজ")])

    def test_adds_valid_records_and_preserves_existing_order(self):
        self.assertEqual(self.run_main(self.standard_fake()), 0)
        items = self.items()
        ids = [i["video_id"] for i in items]
        # নতুনগুলো ক্যাটাগরির প্রথম পুরনো রেকর্ডের আগে, নতুনতম আগে
        self.assertEqual(ids, ["rLKhbUCH2-A", "NEWvideo001", "NEWvideo005", "OLDvideo001",
                               "NEWtarik001", "sfng9s4zkDY", "OLDvideo002", "rLKhbUCH2-A"])
        # পুরনো ৫টি রেকর্ড হুবহু, একই ক্রমে
        self.assertEqual([i for i in items if not i["video_id"].startswith("NEW")], EXISTING)

    def test_schema_unchanged(self):
        self.run_main(self.standard_fake())
        doc = json.loads(self.data.read_text(encoding="utf-8"))
        self.assertEqual(list(doc.keys()), ["itemType"])
        for i in doc["itemType"]:
            self.assertEqual(set(i), {"itemType", "title", "video_id"})

    def test_metadata_goes_to_sidecar(self):
        self.run_main(self.standard_fake())
        meta = json.loads(self.meta.read_text(encoding="utf-8"))
        self.assertEqual(set(meta), {"NEWvideo001", "NEWvideo005", "NEWtarik001"})
        m = meta["NEWvideo001"]
        self.assertEqual(m["url"], "https://www.youtube.com/watch?v=NEWvideo001")
        self.assertTrue(uv.valid_iso_date(m["published_at"]))
        self.assertEqual(m["source"], "auto")

    def test_flutter_parsers_accept_output(self):
        self.run_main(self.standard_fake())
        body = self.data.read_text(encoding="utf-8")
        amir = dart_parse_global(body, "Amir_Hamza")
        self.assertEqual([v["videoId"] for v in amir], ["NEWvideo001", "NEWvideo005", "OLDvideo001", "OLDvideo002"])
        self.assertEqual(dart_video_counts(body)["Tarik_Monwar"], 2)

    def test_existing_duplicates_reported_not_deleted(self):
        self.run_main(self.standard_fake())
        self.assertIn("rLKhbUCH2-A", self.output)
        self.assertEqual(sum(1 for i in self.items() if i["video_id"] == "rLKhbUCH2-A"), 2)

    def test_idempotent_second_run(self):
        self.run_main(self.standard_fake())
        first = self.data.read_text(encoding="utf-8")
        self.assertEqual(self.run_main(self.standard_fake()), 0)
        self.assertEqual(first, self.data.read_text(encoding="utf-8"))
        self.assertIn("কোনো পরিবর্তন নেই", self.output)

    def test_five_per_category_limit(self):
        ids = [f"LIMITvid{n:03d}" for n in range(9)]
        fake = FakeYouTube({"আমির হামজা ওয়াজ": ids},
                           [video(i, f"আমির হামজা ওয়াজ {n}", pub=f"2026-10-{10 + n:02d}T00:00:00Z")
                            for n, i in enumerate(ids)])
        self.run_main(fake)
        added = [i["video_id"] for i in self.items() if i["video_id"].startswith("LIMIT")]
        self.assertEqual(added, ids[::-1][:5])  # নতুনতম ৫টি

    def test_max_new_flag(self):
        self.run_main(self.standard_fake(), "--max-new", "1")
        self.assertEqual([i["video_id"] for i in self.items() if i["itemType"] == "Amir_Hamza"][:1], ["NEWvideo001"])
        self.assertNotIn("NEWvideo005", [i["video_id"] for i in self.items()])

    def test_empty_search_results(self):
        before = self.data.read_text(encoding="utf-8")
        self.assertEqual(self.run_main(FakeYouTube({}, [])), 0)
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))
        self.assertFalse(self.meta.exists())

    def test_malformed_api_items_are_skipped(self):
        class Weird(FakeYouTube):
            def __call__(self, endpoint, params, key, quota, **kw):
                quota.spend(endpoint)
                if endpoint == "search":
                    return {"items": [None, {}, {"id": None}, {"id": {"videoId": 123}},
                                      {"id": {"videoId": "bad id!"}}, {"id": {"videoId": "GOODvid0001"}}]}
                return {"items": [None, {"id": "GOODvid0001"},  # snippet নেই
                                  video("GOODvid0001", "আমির হামজা ওয়াজ")]}
        self.assertEqual(self.run_main(Weird({}, [])), 0)
        self.assertIn("GOODvid0001", [i["video_id"] for i in self.items()])

    def test_one_search_failure_does_not_stop_others(self):
        fake = self.standard_fake()
        fake.search_results["আমির হামজা ওয়াজ"] = uv.ApiError("search HTTP 500")
        self.assertEqual(self.run_main(fake), 0)
        ids = [i["video_id"] for i in self.items()]
        self.assertIn("NEWtarik001", ids)
        self.assertIn("NEWvideo005", ids)
        self.assertIn("HTTP 500", self.output)

    def test_all_searches_failing_returns_5_and_keeps_file(self):
        before = self.data.read_text(encoding="utf-8")
        fake = FakeYouTube({q: uv.ApiError("down") for q in
                            ["আমির হামজা ওয়াজ", "Amir Hamza waz", "তারেক মনোয়ার"]}, [])
        self.assertEqual(self.run_main(fake), 5)
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))

    def test_invalid_key_aborts_without_changes(self):
        before = self.data.read_text(encoding="utf-8")
        self.assertEqual(self.run_main(FakeYouTube({}, [], fail={"search": uv.InvalidKeyError("bad")})), 3)
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))

    def test_quota_exhaustion_keeps_partial_valid_results(self):
        fake = self.standard_fake()
        CONFIG2 = json.loads(json.dumps(CONFIG))
        CONFIG2["defaults"]["quota_budget"] = 202   # ২টি সার্চ + ২টি videos.list, তারপর শেষ
        self.conf.write_text(json.dumps(CONFIG2, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.run_main(fake), 0)
        ids = [i["video_id"] for i in self.items()]
        self.assertIn("NEWvideo001", ids)
        self.assertNotIn("NEWtarik001", ids)
        self.assertIn("quota", self.output)

    def test_missing_key_env(self):
        os.environ["YT_API_KEY"] = ""
        self.assertEqual(self.run_main(FakeYouTube({}, [])), 2)

    def test_corrupt_existing_file_is_not_touched(self):
        self.data.write_text('{"videos": []}', encoding="utf-8")
        self.assertEqual(self.run_main(self.standard_fake()), 4)
        self.assertEqual(self.data.read_text(encoding="utf-8"), '{"videos": []}')

    def test_validation_failure_keeps_original(self):
        before = self.data.read_text(encoding="utf-8")
        with mock.patch.object(uv, "merge", lambda items, new: new.get("Amir_Hamza", [])):  # পুরনো হারানোর বাগ
            self.assertEqual(self.run_main(self.standard_fake()), 4)
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.suffix == ".tmp"], [])

    def test_dry_run_writes_nothing(self):
        before = self.data.read_text(encoding="utf-8")
        self.run_main(self.standard_fake(), "--dry-run")
        self.assertEqual(before, self.data.read_text(encoding="utf-8"))

    def test_blocked_channel(self):
        fake = FakeYouTube({"তারেক মনোয়ার": ["BLOCKvid001"]},
                           [video("BLOCKvid001", "তারেক মনোয়ার ওয়াজ", ch="UCbbbbbbbbbbbbbbbbbbbbbb")])
        self.run_main(fake)
        self.assertNotIn("BLOCKvid001", [i["video_id"] for i in self.items()])

    def test_bangla_unicode_variants_match(self):
        # য় দুইভাবে লেখা যায়: U+09DF অথবা য + ় — দুটোই মিলতে হবে
        decomposed = "তারেক মনোয়ার"
        precomposed = "তারেক মনোয়ার"
        self.assertTrue(uv.title_matches(decomposed + " ওয়াজ", [precomposed]))
        self.assertTrue(uv.title_matches(precomposed, [decomposed]))

    def test_prune_requires_flag_and_has_guard(self):
        fake = FakeYouTube({}, [video("OLDvideo001", "x"), video("OLDvideo002", "x"),
                                video("sfng9s4zkDY", "x")])  # rLKhbUCH2-A মৃত
        self.run_main(fake)
        self.assertEqual(len(self.items()), 5)      # --prune ছাড়া কিছুই মোছে না
        self.run_main(fake, "--prune")
        self.assertNotIn("rLKhbUCH2-A", [i["video_id"] for i in self.items()])

    def test_config_validation(self):
        bad = json.loads(json.dumps(CONFIG))
        bad["scholars"].append({"key": "Amir_Hamza", "auto": False})
        self.conf.write_text(json.dumps(bad), encoding="utf-8")
        self.assertEqual(self.run_main(FakeYouTube({}, [])), 2)


class ApiLayerTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.p_sleep = mock.patch.object(uv, "SLEEP", self.sleeps.append)
        self.p_sleep.start()

    def tearDown(self):
        self.p_sleep.stop()

    def http_error(self, code, reason=""):
        body = json.dumps({"error": {"errors": [{"reason": reason}],
                                     "message": "API key not valid" if reason == "keyInvalid" else ""}})
        return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body.encode()))

    def test_retry_with_backoff_then_success(self):
        seq = [urllib.error.URLError("dns"), self.http_error(503), {"items": []}]

        def fake(url, timeout):
            r = seq.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(uv, "_http_get", fake):
            self.assertEqual(uv.api_get("videos", {}, "k", uv.QuotaGuard(100)), {"items": []})
        self.assertEqual(self.sleeps, [1, 2])

    def test_gives_up_after_retries(self):
        with mock.patch.object(uv, "_http_get", side_effect=TimeoutError()):
            with self.assertRaises(uv.ApiError):
                uv.api_get("videos", {}, "k", uv.QuotaGuard(100))
        self.assertEqual(self.sleeps, [1, 2, 4])

    def test_invalid_key_not_retried(self):
        with mock.patch.object(uv, "_http_get", side_effect=self.http_error(400, "keyInvalid")):
            with self.assertRaises(uv.InvalidKeyError):
                uv.api_get("search", {}, "k", uv.QuotaGuard(1000))
        self.assertEqual(self.sleeps, [])

    def test_quota_exceeded_detected(self):
        with mock.patch.object(uv, "_http_get", side_effect=self.http_error(403, "quotaExceeded")):
            with self.assertRaises(uv.QuotaError):
                uv.api_get("search", {}, "k", uv.QuotaGuard(1000))

    def test_error_messages_never_contain_key(self):
        secret = "AIzaSECRETKEY123"
        with mock.patch.object(uv, "_http_get", side_effect=self.http_error(404, "notFound")):
            try:
                uv.api_get("videos", {}, secret, uv.QuotaGuard(100))
            except uv.ApiError as e:
                self.assertNotIn(secret, str(e))

    def test_malformed_response(self):
        with mock.patch.object(uv, "_http_get", return_value=["not", "a", "dict"]):
            with self.assertRaises(uv.ApiError):
                uv.api_get("videos", {}, "k", uv.QuotaGuard(100), retries=0)

    def test_local_quota_guard(self):
        q = uv.QuotaGuard(150)
        q.spend("search")
        with self.assertRaises(uv.QuotaError):
            q.spend("search")

    def test_helpers(self):
        self.assertEqual(uv.iso_duration_seconds("PT1H2M3S"), 3723)
        self.assertEqual(uv.iso_duration_seconds("PT45S"), 45)
        self.assertEqual(uv.iso_duration_seconds("P1D"), 86400)
        self.assertEqual(uv.iso_duration_seconds("garbage"), 0)
        self.assertTrue(uv.title_blocked("Amir Hamza #shorts", ["#shorts"]))
        self.assertFalse(uv.title_blocked("shortsighted people", ["shorts"]))
        self.assertEqual(uv.clean_title("র\u200d্যাব"), "র\u200d্যাব")   # বাংলা ZWJ অক্ষত
        self.assertEqual(uv.clean_title("  a​\nb \t c "), "a b c")


@unittest.skipUnless(REPO_JSON.exists(), "repo video_studio.json not present")
class RealRepoFileTests(unittest.TestCase):
    """রিপোর আসল video_studio.json অ্যাপের পার্সারের সাথে মিলছে কি না।"""

    def test_real_file_structure(self):
        doc = json.loads(REPO_JSON.read_text(encoding="utf-8"))
        self.assertEqual(uv.validate_document(doc, strict_ids=True), [])

    def test_config_keys_exist_or_are_new(self):
        conf = uv.load_config(Path(__file__).parent / "scholars_config.json")
        body = REPO_JSON.read_text(encoding="utf-8")
        existing = set(dart_video_counts(body))
        for s in conf["scholars"]:
            self.assertRegex(s["key"], r"^[A-Za-z0-9_]+$")
        missing = {s["key"] for s in conf["scholars"]} - existing
        self.assertEqual(missing, set(), f"config keys not in JSON (typo?): {missing}")

    def test_no_duplicate_video_ids(self):
        ids = [i["video_id"] for i in json.loads(REPO_JSON.read_text(encoding="utf-8"))["itemType"]]
        dups = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dups, [], f"duplicate video ids: {dups}")

    @unittest.skipUnless(REPO_ICONS.exists(), "waz_icone.json not present")
    def test_icons_keys_are_single_source(self):
        """waz_icone.json: প্রতিটির স্পষ্ট key, কোনো ডুপ্লিকেট নেই, সব ক্যাটাগরি কভার।"""
        icons = json.loads(REPO_ICONS.read_text(encoding="utf-8"))
        keys = [i.get("key", "") for i in icons]
        for k in keys:
            self.assertRegex(k, r"^[A-Za-z0-9_]+$")
        self.assertEqual(len(keys), len(set(keys)), "duplicate key in waz_icone.json")
        types = set(dart_video_counts(REPO_JSON.read_text(encoding="utf-8")))
        self.assertEqual(types - set(keys), set(), "categories missing from waz_icone.json")
        self.assertEqual(set(keys) - types, set(), "waz_icone.json key not found in video_studio.json")
        for i in icons:
            for f in ("imageUrl", "cat_title", "cat_subtitle", "serverUrl"):
                self.assertIsInstance(i.get(f), str, f"{i.get('key')}: {f}")


if __name__ == "__main__":
    unittest.main()
