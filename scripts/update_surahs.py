#!/usr/bin/env python3
"""
কুরআনের ১১৪টি সূরার তিলাওয়াত — Quran_Recitation ক্যাটাগরিতে অটো-আপডেট
=====================================================================
প্রতি সূরার জন্য গত ১৮০ দিনের সবচেয়ে বেশি দেখা সুমধুর তিলাওয়াত (একটি ভিডিও)।
YouTube দৈনিক কোটার কারণে কয়েক দিনে ভাগ করে চলে (দিনে ~৬০টি সূরা);
অগ্রগতি থাকে scripts/surah_progress.json-এ।

নিয়ম:
  * শিরোনামে সেই সূরার নাম থাকতে হবে — ইংরেজি ("Surah Al-Baqarah"),
    আরবি ("سورة البقرة") বা বাংলা ("সূরা আল-বাকারা")। "সূরা/Surah/سورة" শব্দের
    ঠিক পরে নাম থাকতে হবে, তাই "নাস" আর "নাসর", "حج" আর "حجرات" গুলিয়ে যায় না।
  * তাফসীর/ওয়াজ/লেকচার/Shorts/LIVE বাদ; public + embeddable + লাইভ নয় + ≥৬০ সেকেন্ড।
  * আগে থেকে ফাইলে আছে এমন ভিডিও বা একই শিরোনাম বাদ।
  * ১৮০ দিনে কিছু না পেলে পরের রানে সময়সীমা ছাড়া (সব সময়ের) খোঁজে;
    তাতেও না পেলে "not_found" — আর কোটা খরচ করে না।
  * মূল ফাইলের গঠন অপরিবর্তিত; পুরনো রেকর্ড মোছে না/সরায় না। নতুন সূরাগুলো
    Quran_Recitation-এর শুরুতে ১→১১৪ ক্রমে বসে (পরের দিনের ব্যাচ আগের ব্যাচের পরে)।
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_videos as uv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CATEGORY = "Quran_Recitation"

SURAH_WORDS_EN = {"surah", "surat", "sura", "surah", "soorah", "suratul", "surahs", "sourate", "surate"}
EN_PREFIXES = {"al", "an", "ar", "as", "at", "ad", "az", "ash", "adh", "ath", "aal", "e", "i", "el", "ul"}
BN_SURAH = r"(?:সূরা|সুরা|ছুরা|সূরাহ|সুরাহ)"
BN_PREFIX = r"(?:(?:আল|আন|আর|আত|আস|আদ|আয|আশ|আলে|আয্‌)[\s\-‐–]*)?"
AR_DIACRITICS = re.compile(r"[ً-ْٰـ]")

# ইংরেজি: পুরো শব্দ মিললে; বাংলা/চিহ্ন: শব্দের অংশ হলেও (বিভক্তিসহ)
BLOCKED_WORDS = ["tafsir", "tafseer", "waz", "lecture", "explanation", "#shorts", "shorts", "reaction"]
BLOCKED_SUBSTR = ["তাফসীর", "তাফসির", "ওয়াজ", "লেকচার", "ব্যাখ্যা", "🔴", "লাইভ", "تفسير"]
BLOCKED_CS = ["LIVE"]


# ── matching ─────────────────────────────────────────────────────────────
def norm_ar(s: str) -> str:
    s = AR_DIACRITICS.sub("", s or "")
    return (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
             .replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي"))


def en_tokens(title: str) -> list[str]:
    t = uv.nfc(title).casefold().replace("'", "").replace("’", "").replace("`", "")
    return [w for w in re.split(r"[^a-z]+", t) if w]


def matches_en(title: str, cores: list[str]) -> bool:
    toks = en_tokens(title)
    for i, w in enumerate(toks):
        if w not in SURAH_WORDS_EN:
            continue
        rest = [x for x in toks[i + 1:i + 6] if x not in EN_PREFIXES][:2]
        if not rest:
            continue
        cand = {rest[0], "".join(rest[:2])}
        if any(c in cand for c in cores):
            return True
    return False


def matches_ar(title: str, core: str) -> bool:
    t, c = norm_ar(uv.nfc(title)), norm_ar(core)
    return re.search(r"سوره\s*(?:ال)?" + re.escape(c) + r"(?![ء-ي])", t) is not None


def matches_bn(title: str, cores: list[str]) -> bool:
    t = uv.nfc(title)
    for c in cores:
        if re.search(BN_SURAH + r"[\s\-:]*" + BN_PREFIX + re.escape(uv.nfc(c)) + r"(?![ঀ-৿])", t):
            return True
    return False


def title_matches_surah(title: str, s: dict) -> bool:
    return (matches_en(title, s["en_match"]) or matches_ar(title, s["ar"])
            or matches_bn(title, s["bn_match"]))


def bn_digits(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def display_title(s: dict, yt_title: str) -> str:
    return f"সূরা {s['bn']} ({bn_digits(s['n'])}) | {yt_title}"


# ── main ─────────────────────────────────────────────────────────────────
def run(args) -> int:
    surahs = json.loads(Path(args.surahs).read_text(encoding="utf-8"))
    assert [s["n"] for s in surahs] == list(range(1, 115)), "surahs.json must list 1..114"
    data_path, meta_path, prog_path = Path(args.data), Path(args.meta), Path(args.progress)

    doc = json.loads(data_path.read_text(encoding="utf-8"))
    errs = uv.validate_document(doc, strict_ids=False)
    if errs:
        print("ERROR: unexpected structure — nothing changed:\n  " + "\n  ".join(errs[:10]), file=sys.stderr)
        return 4
    items = doc["itemType"]
    original_keys = list(doc.keys())
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    progress = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {}

    key = os.environ.get("YT_API_KEY", "").strip()
    if not key:
        print("ERROR: YT_API_KEY environment variable is not set", file=sys.stderr)
        return 2

    seen_ids = {it["video_id"] for it in items}
    seen_titles = {uv.title_key(it["title"]) for it in items}
    quota = uv.QuotaGuard(args.budget)
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=args.lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    todo = [s for s in surahs
            if progress.get(str(s["n"]), {}).get("status") not in ("done", "not_found")]
    if args.only:
        todo = [s for s in todo if s["n"] in args.only]
    added: list[tuple[dict, dict, dict]] = []   # (surah, record, meta)
    report = {"added": [], "retry": [], "not_found": [], "failed": [], "stopped": ""}

    for s in todo:
        n = str(s["n"])
        st = progress.get(n, {"status": "pending", "tries": 0})
        all_time = st.get("tries", 0) >= 1          # দ্বিতীয় চেষ্টা: সময়সীমা ছাড়া
        if quota.used + uv.COST["search"] + 2 > quota.budget:
            report["stopped"] = "quota budget for this run used — continues next run"
            break
        params = {"part": "id", "type": "video", "order": "viewCount",
                  "q": f"Surah {s['en']} beautiful recitation",
                  "maxResults": 25, "videoEmbeddable": "true", "safeSearch": "strict"}
        if not all_time:
            params["publishedAfter"] = since
        try:
            data = uv.api_get("search", params, key, quota)
            ids = [((it or {}).get("id") or {}).get("videoId") for it in data.get("items") or []]
            ids = [i for i in dict.fromkeys(ids) if isinstance(i, str) and uv.ID_RE.match(i) and i not in seen_ids]
            details = uv.fetch_details(ids, key, quota) if ids else {}
        except uv.InvalidKeyError as e:
            print(f"ERROR: {e} — nothing changed", file=sys.stderr)
            return 3
        except uv.QuotaError as e:
            report["stopped"] = str(e)
            break
        except uv.ApiError as e:
            report["failed"].append((s["n"], str(e)))
            continue

        best = None
        for vid in ids:
            v = details.get(vid)
            if not v or not uv.is_playable(v):
                continue
            title = uv.clean_title((v.get("snippet") or {}).get("title", ""))
            if not title or not title_matches_surah(title, s):
                continue
            if uv.title_blocked(title, BLOCKED_WORDS, BLOCKED_SUBSTR, BLOCKED_CS):
                continue
            if uv.iso_duration_seconds((v.get("contentDetails") or {}).get("duration", "")) < args.min_duration:
                continue
            if uv.title_key(title) in seen_titles:
                continue
            vc = uv._view_count(v)
            if best is None or vc > best[1]:
                best = (v, vc, title)

        st["tries"] = st.get("tries", 0) + 1
        if best is None:
            st["status"] = "not_found" if all_time else "retry"
            report["not_found" if all_time else "retry"].append(s["n"])
            progress[n] = st
            continue
        v, vc, title = best
        sn = v.get("snippet") or {}
        rec = {"itemType": CATEGORY, "title": display_title(s, title), "video_id": v["id"]}
        m = {"itemType": CATEGORY, "surah": s["n"], "published_at": sn.get("publishedAt", ""),
             "channel": uv.clean_title(sn.get("channelTitle", ""))[:120], "channel_id": sn.get("channelId", ""),
             "url": f"https://www.youtube.com/watch?v={v['id']}", "view_count": vc, "source": "auto-surah",
             "window": "all-time" if all_time else f"{args.lookback_days}d",
             "added_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        seen_ids.add(v["id"])
        seen_titles.add(uv.title_key(rec["title"]))
        seen_titles.add(uv.title_key(title))
        st.update({"status": "done", "video_id": v["id"]})
        progress[n] = st
        added.append((s, rec, m))
        report["added"].append({"surah": s["n"], "video_id": v["id"], "views": vc, "title": title})

    # ── সারাংশ ──
    done = sum(1 for p in progress.values() if p.get("status") == "done")
    lines = ["## কুরআন তিলাওয়াত (১১৪ সূরা) আপডেট", "",
             f"- এই রানে যোগ: **{len(added)}** | মোট সম্পন্ন: **{done}/114** | quota: {quota.used}"]
    if report["retry"]:
        lines.append(f"- ১৮০ দিনে পাওয়া যায়নি, পরের রানে সব সময়ের মধ্যে খুঁজবে: {report['retry']}")
    if report["not_found"]:
        lines.append(f"- পাওয়া যায়নি: {report['not_found']}")
    if report["failed"]:
        lines.append(f"- ফেল: {report['failed']}")
    if report["stopped"]:
        lines.append(f"- থেমেছে: {report['stopped']}")
    if added:
        lines += ["", "| সূরা | ভিউ | ভিডিও |", "|---|---|---|"]
        for s, rec, m in added:
            lines.append(f"| {s['n']}. {s['bn']} | {m['view_count']:,} | "
                         f"[{rec['video_id']}](https://youtu.be/{rec['video_id']}) {rec['title'][:70].replace('|', '/')} |")
    summary = "\n".join(lines) + "\n"
    print(summary)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as f:
            f.write(summary)
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        print("(dry-run — ফাইল লেখা হয়নি)")
        return 0
    if not added and not report["retry"] and not report["not_found"]:
        print("কোনো পরিবর্তন নেই।")
        return 0

    # ── মার্জ: আগের সূরা-রেকর্ডগুলোর ঠিক পরে (না থাকলে ক্যাটাগরির শুরুতে), ১→১১৪ ক্রমে ──
    new_recs = [rec for _, rec, _ in sorted(added, key=lambda x: x[0]["n"])]
    if new_recs:
        prev_ids = {p["video_id"] for p in progress.values() if p.get("status") == "done"} - {r["video_id"] for r in new_recs}
        last_prev = max((i for i, it in enumerate(items) if it["video_id"] in prev_ids), default=None)
        if last_prev is not None:
            pos = last_prev + 1
        else:
            pos = next((i for i, it in enumerate(items) if it["itemType"] == CATEGORY), len(items))
        merged = items[:pos] + new_recs + items[pos:]
    else:
        merged = items
    out_doc = {k: (merged if k == "itemType" else doc[k]) for k in original_keys}
    old_ids = [it["video_id"] for it in items]

    def validate(d):
        e = uv.validate_document(d, strict_ids=False)
        if list(d) != original_keys:
            e.append("top-level keys changed")
        new_set = {r["video_id"] for r in new_recs}
        if [it["video_id"] for it in d["itemType"] if it["video_id"] not in new_set] != old_ids:
            e.append("existing records lost or reordered")
        for r in new_recs:
            if set(r) != set(uv.REQUIRED_FIELDS) or not uv.ID_RE.match(r["video_id"]):
                e.append(f"bad record {r}")
        if e:
            raise uv.ValidationError("; ".join(e[:10]))

    try:
        uv.atomic_write_json(data_path, out_doc, validate)
    except uv.ValidationError as e:
        print(f"ERROR: validation failed — original kept: {e}", file=sys.stderr)
        return 4
    for _, rec, m in added:
        meta[rec["video_id"]] = m
    uv.atomic_write_json(meta_path, dict(sorted(meta.items())))
    uv.atomic_write_json(prog_path, dict(sorted(progress.items(), key=lambda kv: int(kv[0]))))
    print(f"লেখা হয়েছে: {len(new_recs)} নতুন সূরা-ভিডিও")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--surahs", default=str(ROOT / "scripts" / "surahs.json"))
    p.add_argument("--data", default=str(ROOT / "video_studio.json"))
    p.add_argument("--meta", default=str(ROOT / "video_meta.json"))
    p.add_argument("--progress", default=str(ROOT / "scripts" / "surah_progress.json"))
    p.add_argument("--budget", type=int, default=6000, help="এই রানের quota সীমা (প্রতি সূরা ~১০১)")
    p.add_argument("--lookback-days", type=int, default=180)
    p.add_argument("--min-duration", type=int, default=60)
    p.add_argument("--only", type=int, nargs="*", help="শুধু এই সূরা নম্বরগুলো")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    p.add_argument("--report-json", default="")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
