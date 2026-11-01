#!/usr/bin/env python3
"""
video_studio.json অটো-আপডেটার (v2)
===================================
YouTube Data API v3 দিয়ে প্রতিটি বক্তার নতুন ওয়াজ খুঁজে video_studio.json-এ যোগ করে।

নিরাপত্তা নীতি (master prompt অনুযায়ী):
  * স্কিমা অপরিবর্তিত: মূল ফাইলে টপ-লেভেলে শুধু "itemType", প্রতিটি রেকর্ডে শুধু
    itemType / title / video_id। অতিরিক্ত তথ্য (তারিখ, চ্যানেল, URL) আলাদা
    video_meta.json-এ যায়।
  * পুরনো কোনো রেকর্ড মোছা বা সরানো হয় না, ক্রমও বদলায় না। নতুন রেকর্ড সেই
    ক্যাটাগরির প্রথম পুরনো রেকর্ডের ঠিক আগে বসে, তাই অ্যাপে সবার উপরে দেখায়।
  * প্রতি রানে প্রতি ক্যাটাগরিতে সর্বোচ্চ ৫টি নতুন ভিডিও (কনফিগে বদলানো যায়)।
  * অস্থায়ী ফাইলে লেখা হয় → পুরোটা যাচাই হয় → পাস করলে তবেই আসল ফাইল বদলায়।
  * সাময়িক নেটওয়ার্ক বা সার্ভার এরর হলে exponential backoff দিয়ে আবার চেষ্টা করে।
    API key ভুল হলে পুরো রান থামে; quota শেষ হলে যা পাওয়া গেছে তা নিরাপদে রেখে থামে।
  * ডুপ্লিকেট রেকর্ড শুধু রিপোর্ট করে (মোছে না)। মৃত ভিডিও শুধু --prune দিলে মোছে।
  * শুধু Python standard library — কোনো pip install লাগে না।

এক্সিট কোড: 0 = ঠিক আছে (কিছু সার্চ ফেল হলেও), 2 = কনফিগ/ইনপুট সমস্যা,
            3 = API key ভুল, 4 = যাচাই ফেল (আসল ফাইল অক্ষত), 5 = সব সার্চ ফেল
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/"
ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")
REQUIRED_FIELDS = ("itemType", "title", "video_id")
COST = {"search": 100, "videos": 1, "playlistItems": 1}


# ── errors ────────────────────────────────────────────────────────────────
class ApiError(RuntimeError):
    pass


class InvalidKeyError(ApiError):
    pass


class QuotaError(ApiError):
    pass


class ValidationError(RuntimeError):
    pass


# ── quota / API ───────────────────────────────────────────────────────────
class QuotaGuard:
    def __init__(self, budget: int):
        self.budget, self.used = budget, 0

    def spend(self, endpoint: str) -> None:
        cost = COST.get(endpoint, 1)
        if self.used + cost > self.budget:
            raise QuotaError(f"local quota budget {self.budget} reached")
        self.used += cost


SLEEP = time.sleep  # টেস্টে বদলানো যায়


def _http_get(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def api_get(endpoint: str, params: dict, key: str, quota: QuotaGuard,
            retries: int = 3, timeout: int = 30) -> dict:
    """একটি YouTube API কল — retry, backoff, key/quota শনাক্তকরণসহ।
    এরর মেসেজে কখনো API key থাকে না।"""
    quota.spend(endpoint)
    url = API + endpoint + "?" + urllib.parse.urlencode({**params, "key": key})
    last = ""
    for attempt in range(retries + 1):
        try:
            data = _http_get(url, timeout)
            if not isinstance(data, dict):
                raise ApiError(f"{endpoint}: malformed response (not an object)")
            return data
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            reason = _error_reason(body)
            if e.code == 400 and ("keyInvalid" in body or "API key not valid" in body):
                raise InvalidKeyError("YouTube API key is invalid") from None
            if e.code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                raise QuotaError(f"YouTube quota: {reason}") from None
            if e.code == 403 and reason in ("accessNotConfigured", "forbidden", "ipRefererBlocked"):
                raise InvalidKeyError(f"API key not allowed: {reason}") from None
            if e.code in (429, 500, 502, 503, 504):
                last = f"HTTP {e.code}"
            else:
                raise ApiError(f"{endpoint} HTTP {e.code} ({reason or 'unknown'})") from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            last = type(e).__name__
        except json.JSONDecodeError:
            last = "invalid JSON"
        if attempt < retries:
            SLEEP(2 ** attempt)  # 1s, 2s, 4s
    raise ApiError(f"{endpoint} failed after {retries + 1} attempts ({last})")


def _error_reason(body: str) -> str:
    try:
        errs = json.loads(body).get("error", {}).get("errors", [])
        return errs[0].get("reason", "") if errs else ""
    except (ValueError, AttributeError):
        return ""


# ── text helpers ─────────────────────────────────────────────────────────
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", nfc(s).casefold()).strip()


def clean_title(s: str) -> str:
    """কন্ট্রোল ক্যারেক্টার বাদ। বাংলার যুক্তাক্ষরে লাগা ZWJ/ZWNJ (U+200C/D) রাখা হয়।"""
    s = re.sub(r"\s+", " ", nfc(s))
    s = "".join(ch for ch in s
                if ch in "‌‍" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs", "Cn"))
    return re.sub(r" +", " ", s).strip()


def title_matches(title: str, must: list[str]) -> bool:
    t = norm(title)
    return not must or any(norm(w) in t for w in must)


def title_blocked(title: str, blocked: list[str], substrings: list[str] = (),
                  case_sensitive: list[str] = ()) -> bool:
    """blocked: পুরো শব্দ মিললে (ইংরেজি)। substrings: শব্দের অংশ হলেও (বাংলা
    বিভক্তির জন্য, যেমন "জোট" → "জোটের")। case_sensitive: হুবহু বড়-ছোট হাতের
    অক্ষরে (যেমন "LIVE" — যাতে "how to live" বাদ না পড়ে)।"""
    t = f" {norm(title)} "
    if any(f" {norm(w)} " in t or (norm(w).startswith("#") and norm(w) in t) for w in blocked):
        return True
    if any(norm(w) and norm(w) in t for w in substrings):
        return True
    raw = nfc(title)
    return any(re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", raw) for w in case_sensitive)


def title_key(title: str) -> str:
    """একই ভিডিওর কপি চেনার জন্য শিরোনামের সারাংশ: ছোট হাতের অক্ষর, ব্র্যাকেটের
    অংশ (যেমন "(Portrait)") বাদ, যতিচিহ্ন/ইমোজি বাদ। সংখ্যা রাখা হয় (পর্ব ১ ≠ পর্ব ২,
    "(২)" ≠ "")।"""
    t = norm(title)
    # ব্র্যাকেটে শুধু লেবেল (Portrait/Full/HD) থাকলে বাদ; সংখ্যা থাকলে (পর্ব "(২)") রাখা
    t = re.sub(r"\(([^)]*)\)|\[([^\]]*)\]",
               lambda m: f" {m.group(0)} " if re.search(r"\d", m.group(0)) else " ", t)
    t = "".join(ch if (ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc")) else " " for ch in t)
    return re.sub(r"\s+", " ", t).strip()


def iso_duration_seconds(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s or "")
    if not m or s in ("P", "PT"):
        return 0
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def valid_iso_date(s: str) -> bool:
    try:
        dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except (TypeError, ValueError):
        return False


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ── schema validation (Flutter মডেলের সাথে মিল) ─────────────────────────
def validate_document(doc, *, strict_ids: bool) -> list[str]:
    """VideoItem.fromJson / ScholarIconProvider._mergeVideoTypes যা আশা করে তা যাচাই।"""
    errs: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("itemType"), list):
        return ["top level must be an object with an 'itemType' array"]
    for i, it in enumerate(doc["itemType"]):
        if not isinstance(it, dict):
            errs.append(f"record {i}: not an object")
            continue
        for f in REQUIRED_FIELDS:
            if not isinstance(it.get(f), str):
                errs.append(f"record {i}: '{f}' missing or not a string")
        if strict_ids and isinstance(it.get("video_id"), str) and not ID_RE.match(it["video_id"]):
            errs.append(f"record {i}: invalid video_id {it['video_id']!r}")
    return errs


# ── result tracking ──────────────────────────────────────────────────────
@dataclass
class Report:
    added: dict = field(default_factory=dict)          # key -> [records]
    skipped: dict = field(default_factory=dict)        # reason -> count
    failed: list = field(default_factory=list)         # (key, message)
    existing_duplicates: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    stopped_reason: str = ""
    quota_used: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    @property
    def total_added(self) -> int:
        return sum(len(v) for v in self.added.values())

    def markdown(self) -> str:
        L = ["## ওয়াজ ভিডিও আপডেট রিপোর্ট", "",
             f"- নতুন যোগ: **{self.total_added}**",
             f"- quota ব্যবহার: {self.quota_used} ইউনিট",
             f"- ফেল হওয়া সার্চ: {len(self.failed)}"]
        if self.stopped_reason:
            L.append(f"- ⚠️ আগেই থেমেছে: {self.stopped_reason}")
        if self.existing_duplicates:
            L.append(f"- ⚠️ ফাইলে আগে থেকে ডুপ্লিকেট (মোছা হয়নি): {', '.join(self.existing_duplicates)}")
        if self.pruned:
            L.append(f"- মৃত ভিডিও বাদ: {', '.join(self.pruned)}")
        if self.added:
            L += ["", "| ক্যাটাগরি | নতুন | শিরোনাম |", "|---|---|---|"]
            for k, recs in self.added.items():
                for r in recs:
                    L.append(f"| {k} | [{r['video_id']}](https://youtu.be/{r['video_id']}) | {r['title'].replace('|', '/')} |")
        if self.skipped:
            L += ["", "**বাদ পড়েছে:** " + ", ".join(f"{k}: {v}" for k, v in sorted(self.skipped.items()))]
        if self.failed:
            L += ["", "**ফেল:**"] + [f"- {k}: {m}" for k, m in self.failed]
        return "\n".join(L) + "\n"


# ── discovery ────────────────────────────────────────────────────────────
def fetch_details(ids, key, quota) -> dict:
    out = {}
    for part in chunks(list(ids), 50):
        data = api_get("videos", {"part": "snippet,contentDetails,status,statistics",
                                  "id": ",".join(part), "maxResults": 50}, key, quota)
        for v in data.get("items") or []:
            if isinstance(v, dict) and isinstance(v.get("id"), str):
                out[v["id"]] = v
    return out


def is_playable(v: dict) -> bool:
    st, sn = v.get("status") or {}, v.get("snippet") or {}
    return (st.get("privacyStatus") == "public" and st.get("embeddable") is True
            and st.get("uploadStatus", "processed") == "processed"
            and sn.get("liveBroadcastContent", "none") == "none")


def discover(sch: dict, cfg: dict, key: str, quota: QuotaGuard, since: str, rep: Report,
             from_playlist: set | None = None) -> list[str]:
    """প্রার্থী ভিডিও আইডি। from_playlist দিলে প্লেলিস্ট থেকে পাওয়া আইডিগুলো সেখানে জমা হয়।"""
    ids: list[str] = []
    for ch in sch.get("channel_ids", []):
        if not (isinstance(ch, str) and ch.startswith("UC") and len(ch) == 24):
            rep.failed.append((sch["key"], f"bad channel id {ch!r}"))
            continue
        try:
            data = api_get("playlistItems", {"part": "contentDetails", "playlistId": "UU" + ch[2:],
                                             "maxResults": 50}, key, quota)
            for it in data.get("items") or []:
                cd = (it or {}).get("contentDetails") or {}
                if cd.get("videoId") and (cd.get("videoPublishedAt") or "") >= since:
                    ids.append(cd["videoId"])
        except (InvalidKeyError, QuotaError):
            raise
        except ApiError as e:
            rep.failed.append((sch["key"], f"channel {ch}: {e}"))
    # বক্তার নির্দিষ্ট প্লেলিস্ট (ব্যবহারকারীর বেছে দেওয়া) — সব ভিডিও প্রার্থী, তারিখ সীমা নেই;
    # প্রতি পাতায় ৫০টি, সর্বোচ্চ ৪ পাতা (প্রতি পাতা ১ ইউনিট)
    for pl in sch.get("playlist_ids", []):
        if not (isinstance(pl, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,64}", pl)):
            rep.failed.append((sch["key"], f"bad playlist id {pl!r}"))
            continue
        token = ""
        try:
            for _ in range(4):
                params = {"part": "contentDetails", "playlistId": pl, "maxResults": 50}
                if token:
                    params["pageToken"] = token
                data = api_get("playlistItems", params, key, quota)
                for it in data.get("items") or []:
                    cd = (it or {}).get("contentDetails") or {}
                    if isinstance(cd.get("videoId"), str):
                        ids.append(cd["videoId"])
                        if from_playlist is not None:
                            from_playlist.add(cd["videoId"])
                token = data.get("nextPageToken") or ""
                if not token:
                    break
        except (InvalidKeyError, QuotaError):
            raise
        except ApiError as e:
            rep.failed.append((sch["key"], f"playlist {pl}: {e}"))
    for q in sch.get("queries", []):
        try:
            data = api_get("search", {
                "part": "id", "type": "video", "q": q,
                "order": "viewCount" if cfg.get("sort_by") == "viewCount" else "date",
                "publishedAfter": since, "maxResults": cfg["search_max_results"],
                "regionCode": cfg["region_code"], "relevanceLanguage": cfg["relevance_language"],
                "videoEmbeddable": "true", "safeSearch": "strict",
            }, key, quota)
            for it in data.get("items") or []:
                vid = ((it or {}).get("id") or {}).get("videoId")
                if isinstance(vid, str):
                    ids.append(vid)
        except (InvalidKeyError, QuotaError):
            raise
        except ApiError as e:
            rep.failed.append((sch["key"], f"search {q!r}: {e}"))
    good = []
    for i in dict.fromkeys(ids):
        if ID_RE.match(i):
            good.append(i)
        else:
            rep.skip("invalid id")
    return good


def _view_count(v: dict) -> int:
    """videos.list → statistics.viewCount (স্ট্রিং আসে; না থাকলে/লুকানো থাকলে 0)।"""
    try:
        return int((v.get("statistics") or {}).get("viewCount") or 0)
    except (TypeError, ValueError):
        return 0


def build_record(k: str, v: dict, sch: dict, cfg: dict, blocked_words, blocked_ch, rep: Report,
                 blocked_subs=(), blocked_cs=(), trusted=False):
    """trusted=True: ব্যবহারকারীর বেছে দেওয়া প্লেলিস্টের ভিডিও — নাম মেলানো ও বাংলা-শিরোনাম শর্ত লাগে না
    (বাকি সব ফিল্টার — LIVE, রাজনৈতিক শব্দ, দৈর্ঘ্য, embed — আগের মতোই)।"""
    if not is_playable(v):
        rep.skip("not public/embeddable/live")
        return None
    sn, cd = v.get("snippet") or {}, v.get("contentDetails") or {}
    title = clean_title(sn.get("title", ""))
    if not title or len(title) > 300:
        rep.skip("bad title")
        return None
    if sn.get("channelId") in blocked_ch:
        rep.skip("blocked channel")
        return None
    if title_blocked(title, blocked_words, blocked_subs, blocked_cs):
        rep.skip("blocked word")
        return None
    if not trusted and not title_matches(title, sch.get("must_match", [])):
        rep.skip("speaker name not in title")
        return None
    # বাংলা অনুবাদ/সাবটাইটেলের ভিডিওই চাই (যেমন উর্দু বক্তা) — শিরোনামে বাংলা অক্ষর থাকতে হবে
    if not trusted and sch.get("require_bangla_title") and not re.search(r"[\u0980-\u09FF]", title):
        rep.skip("title not in Bangla")
        return None
    min_d = sch.get("min_duration_sec", cfg["min_duration_sec"])
    if iso_duration_seconds(cd.get("duration", "")) < min_d:
        rep.skip("too short")
        return None
    # গজল/সংগীতের মতো বিভাগে খুব লম্বা সংকলন বাদ (max_duration_sec না থাকলে সীমা নেই)
    max_d = sch.get("max_duration_sec")
    if max_d and iso_duration_seconds(cd.get("duration", "")) > max_d:
        rep.skip("too long")
        return None
    pub = sn.get("publishedAt", "")
    if not valid_iso_date(pub):
        rep.skip("bad publish date")
        return None
    return ({"itemType": k, "title": title, "video_id": v["id"]},
            {"published_at": pub, "channel": clean_title(sn.get("channelTitle", ""))[:120],
             "channel_id": sn.get("channelId", ""), "url": f"https://www.youtube.com/watch?v={v['id']}",
             "source": "auto", "view_count": _view_count(v)})


# ── merge + atomic write ─────────────────────────────────────────────────
def merge(items: list[dict], new_by_key: dict[str, list[dict]]) -> list[dict]:
    """পুরনো ক্রম অক্ষত; নতুনগুলো ক্যাটাগরির প্রথম পুরনো রেকর্ডের আগে, না থাকলে শেষে।"""
    out, placed = [], set()
    for it in items:
        k = it.get("itemType")
        if k in new_by_key and k not in placed:
            out += new_by_key[k]
            placed.add(k)
        out.append(it)
    for k, recs in new_by_key.items():
        if k not in placed:
            out += recs
    return out


def atomic_write_json(path: Path, obj, validate=None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        reloaded = json.loads(Path(tmp).read_text(encoding="utf-8"))
        if validate:
            validate(reloaded)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── main ─────────────────────────────────────────────────────────────────
def load_config(path: Path) -> dict:
    conf = json.loads(path.read_text(encoding="utf-8"))
    keys = set()
    for s in conf.get("scholars", []):
        k = s.get("key", "")
        if not KEY_RE.match(k) or k in keys:
            raise ValidationError(f"config: bad or duplicate key {k!r}")
        keys.add(k)
        if s.get("auto") and not (s.get("queries") or s.get("channel_ids") or s.get("playlist_ids")):
            raise ValidationError(f"config: {k} is auto but has no queries/channel_ids/playlist_ids")
    return conf


def run(args) -> int:
    rep = Report()
    try:
        conf = load_config(Path(args.config))
    except (ValueError, ValidationError, OSError) as e:
        print(f"ERROR config: {e}", file=sys.stderr)
        return 2
    cfg = dict(conf["defaults"])
    if args.lookback_days:
        cfg["lookback_days"] = args.lookback_days
    if args.max_new:
        cfg["max_new_per_category"] = args.max_new
    blocked_words = conf.get("blocked_title_words", [])
    blocked_subs = conf.get("blocked_title_substrings", [])
    blocked_cs = conf.get("blocked_title_words_case_sensitive", [])
    blocked_ch = set(conf.get("blocked_channel_ids", []))
    per_channel = int(cfg.get("max_per_channel_per_run", 0) or 0)   # 0 = সীমা নেই

    data_path, meta_path = Path(args.data), Path(args.meta)
    # ১-২. লোড ও বর্তমান কাঠামো যাচাই
    try:
        original_text = data_path.read_text(encoding="utf-8")
        doc = json.loads(original_text)
    except (OSError, ValueError) as e:
        print(f"ERROR: cannot read {data_path}: {e}", file=sys.stderr)
        return 2
    errs = validate_document(doc, strict_ids=False)
    if errs:
        print("ERROR: existing file has unexpected structure — nothing changed:\n  " + "\n  ".join(errs[:20]),
              file=sys.stderr)
        return 4
    items: list[dict] = doc["itemType"]
    original_keys = list(doc.keys())
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            print("WARN: video_meta.json unreadable — starting fresh", file=sys.stderr)

    seen, dups = set(), []
    for it in items:
        vid = it["video_id"].strip()
        if vid in seen:
            dups.append(vid)
        seen.add(vid)
    rep.existing_duplicates = sorted(set(dups))
    seen_titles = {title_key(it["title"]) for it in items}
    # হাতে সরানো ভিডিও (ভুল বক্তা/অপ্রাসঙ্গিক) — পরের রানে আবার যেন না আসে
    blocked_ids = set(conf.get("blocked_video_ids", []))
    channel_count: dict[str, int] = {}

    key = os.environ.get("YT_API_KEY", "").strip()
    if not key:
        print("ERROR: YT_API_KEY environment variable is not set", file=sys.stderr)
        return 2
    quota = QuotaGuard(cfg["quota_budget"])
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg["lookback_days"])
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    limit = cfg["max_new_per_category"]

    # ৩-৬. খোঁজা, যাচাই, ডুপ্লিকেট বাদ, ৫টির সীমা
    new_by_key: dict[str, list[dict]] = {}
    new_meta: dict[str, dict] = {}
    attempted = 0
    exit_code = 0
    for sch in conf["scholars"]:
        k = sch["key"]
        if not sch.get("auto") or (args.only and k not in args.only):
            continue
        attempted += 1
        try:
            from_pl: set = set()
            cand = discover(sch, cfg, key, quota, since, rep, from_pl)
            fresh = [c for c in cand if c not in seen and c not in blocked_ids]
            rep.skipped["already in file"] = rep.skipped.get("already in file", 0) + len(cand) - len(fresh)
            details = fetch_details(fresh, key, quota) if fresh else {}
        except InvalidKeyError as e:
            print(f"ERROR: {e} — nothing changed", file=sys.stderr)
            return 3
        except QuotaError as e:
            rep.stopped_reason = str(e)
            rep.failed.append((k, str(e)))
            break
        except ApiError as e:
            rep.failed.append((k, str(e)))
            continue
        recs = []
        for vid in fresh:
            v = details.get(vid)
            if v is None:
                rep.skip("no details returned")
                continue
            built = build_record(k, v, sch, cfg, blocked_words, blocked_ch, rep, blocked_subs, blocked_cs,
                                 trusted=vid in from_pl)
            if built:
                recs.append(built)
        # sort_by = "viewCount": সবচেয়ে বেশি দেখা আগে; নইলে নতুনতম আগে
        if cfg.get("sort_by") == "viewCount":
            recs.sort(key=lambda r: (r[1].get("view_count", 0), r[1]["published_at"]), reverse=True)
        else:
            recs.sort(key=lambda r: r[1]["published_at"], reverse=True)
        chosen = []
        for r, m in recs:
            tk = title_key(r["title"])
            ch = m.get("channel_id") or m.get("channel", "")
            if tk in seen_titles:
                rep.skip("same title already present")
                continue
            if per_channel and channel_count.get(ch, 0) >= per_channel:
                rep.skip("channel limit per run")
                continue
            if len(chosen) >= limit:
                rep.skip("over per-run limit")
                continue
            chosen.append((r, m))
            seen_titles.add(tk)
            channel_count[ch] = channel_count.get(ch, 0) + 1
        recs = chosen
        if recs:
            new_by_key[k] = [r for r, _ in recs]
            rep.added[k] = new_by_key[k]
            for r, m in recs:
                seen.add(r["video_id"])
                new_meta[r["video_id"]] = {**m, "itemType": k,
                                           "added_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    failed_keys = {k for k, _ in rep.failed}
    if attempted and not rep.stopped_reason and len(failed_keys) >= attempted:
        exit_code = 5

    # ঐচ্ছিক: মৃত ভিডিও ছাঁটাই — শুধু স্পষ্ট --prune দিলে
    if args.prune and items and not rep.stopped_reason:
        try:
            ids = list(dict.fromkeys(it["video_id"] for it in items if ID_RE.match(it["video_id"])))
            alive = fetch_details(ids, key, quota)
            dead = [i for i in ids if i not in alive or not is_playable(alive[i])]
            if len(dead) > max(10, 0.2 * len(ids)):
                rep.failed.append(("prune", f"refused: {len(dead)} removals looks wrong"))
            else:
                rep.pruned = dead
                items = [it for it in items if it["video_id"] not in set(dead)]
        except ApiError as e:
            rep.failed.append(("prune", str(e)))

    rep.quota_used = quota.used
    summary = rep.markdown()
    print(summary)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as f:
            f.write(summary)
    if args.report_json:
        Path(args.report_json).write_text(json.dumps({
            "added": rep.added, "skipped": rep.skipped, "failed": rep.failed,
            "existing_duplicates": rep.existing_duplicates, "pruned": rep.pruned,
            "stopped_reason": rep.stopped_reason, "quota_used": rep.quota_used,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    if not rep.total_added and not rep.pruned:
        print("কোনো পরিবর্তন নেই — ফাইল অক্ষত।")
        return exit_code
    if args.dry_run:
        print("(dry-run — ফাইল লেখা হয়নি)")
        return exit_code

    # ৭-১০. মার্জ → সম্পূর্ণ যাচাই → অস্থায়ী ফাইল → প্রতিস্থাপন
    merged = merge(items, new_by_key)
    out_doc = {k: (merged if k == "itemType" else doc[k]) for k in original_keys}
    old_ids = [it["video_id"] for it in items]

    def validate_out(d):
        e = validate_document(d, strict_ids=False)
        if list(d.keys()) != original_keys:
            e.append("top-level keys changed")
        new_items = [r for recs in new_by_key.values() for r in recs]
        for r in new_items:
            if set(r) != set(REQUIRED_FIELDS) or not ID_RE.match(r["video_id"]):
                e.append(f"bad new record {r}")
        got_old = [it["video_id"] for it in d["itemType"] if it not in new_items]
        if got_old != old_ids:
            e.append("existing records lost or reordered")
        if len(d["itemType"]) != len(items) + len(new_items):
            e.append("record count mismatch")
        if e:
            raise ValidationError("; ".join(e[:10]))

    try:
        atomic_write_json(data_path, out_doc, validate_out)
    except ValidationError as e:
        print(f"ERROR: validation failed — original file kept: {e}", file=sys.stderr)
        return 4
    meta.update(new_meta)
    atomic_write_json(meta_path, dict(sorted(meta.items())))
    print(f"লেখা হয়েছে: {data_path.name} ({len(merged)} রেকর্ড), {meta_path.name}")
    return exit_code


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(ROOT / "scripts" / "scholars_config.json"))
    p.add_argument("--data", default=str(ROOT / "video_studio.json"))
    p.add_argument("--meta", default=str(ROOT / "video_meta.json"))
    p.add_argument("--lookback-days", type=int, default=0)
    p.add_argument("--max-new", type=int, default=0, help="প্রতি ক্যাটাগরিতে সর্বোচ্চ নতুন (ডিফল্ট কনফিগ থেকে)")
    p.add_argument("--only", nargs="*", help="শুধু এই key-গুলো")
    p.add_argument("--prune", action="store_true", help="ডিলিট/প্রাইভেট ভিডিও বাদ দাও (সতর্কতা: রেকর্ড মোছে)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    p.add_argument("--report-json", default="")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
