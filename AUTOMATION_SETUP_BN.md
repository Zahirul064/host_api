> ✅ ধাপ ৩ (ফাইল আপলোড) করা হয়ে গেছে। বাকি শুধু ধাপ ১, ২ ও ৪ (API key, Secret, Actions অনুমতি), তারপর ধাপ ৫।

# video_studio.json অটো-আপডেট: সেটআপ গাইড (v2)

এই ফোল্ডারের ফাইলগুলো আপনার GitHub রিপো **Zahirul064/host_api**-এ এভাবে যাবে:

```
host_api/
├── .github/workflows/update-videos.yml   ← এই ফোল্ডারের update-videos.yml
├── scripts/update_videos.py              ← YouTube থেকে ভিডিও খোঁজে
├── scripts/scholars_config.json          ← কোন বক্তার জন্য কী খুঁজবে
├── scripts/test_update_videos.py         ← অফলাইন টেস্ট (৩৪টি)
├── waz_icone.json                        ← নতুন: ২৪টি ক্যাটাগরি, প্রতিটিতে "key", serverUrl খালি
├── video_studio.json                     ← নতুন: ৩টি ডুপ্লিকেট বাদ (৫৬১ → ৫৫৮); এরপর বট আপডেট করবে
└── video_meta.json                       ← বট নিজে তৈরি করবে (তারিখ, চ্যানেল, URL)
```

`video_studio.json`-এর গঠন **একটুও বদলায় না**। প্রতিটা রেকর্ডে আগের মতোই শুধু `itemType`, `title`, `video_id` থাকে, তাই অ্যাপে কোনো পরিবর্তন লাগবে না।

## ধাপ ১: YouTube API Key নিন (বিনামূল্যে, প্রায় ৫ মিনিট)
1. https://console.cloud.google.com এ যান → নতুন প্রজেক্ট খুলুন (নাম: `waz-bot`)
2. **APIs & Services → Library** → "YouTube Data API v3" খুঁজে **Enable** করুন
3. **APIs & Services → Credentials → Create credentials → API key**
4. Key-টি **Restrict** করুন: *API restrictions* → শুধু "YouTube Data API v3" রাখুন
5. দৈনিক ফ্রি কোটা ১০,০০০ ইউনিট; এই স্ক্রিপ্ট দিনে প্রায় ৩,০০০ ইউনিট খরচ করে

## ধাপ ২: Key-টি GitHub Secret হিসেবে রাখুন
রিপো → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `YT_API_KEY`
- Value: (আপনার key)

> ⚠️ Key কখনো কোডে, JSON-এ বা অ্যাপে লিখবেন না। রিপোটা public, তাই কোডে রাখলে key চুরি হয়ে যাবে।

## ধাপ ৩: ফাইলগুলো রিপোতে দিন
1. GitHub ওয়েবসাইটে **Add file → Upload files** → `scripts` ফোল্ডারটা (তিনটি ফাইলসহ), `waz_icone.json` আর `video_studio.json` **একসাথে** টেনে আনুন → Commit
   - এই চারটা একসাথেই দিতে হবে, কারণ টেস্ট দেখে যে JSON-এ ডুপ্লিকেট নেই আর প্রতিটা ক্যাটাগরির key আছে। পুরনো JSON রেখে শুধু scripts দিলে workflow-এর টেস্ট ফেল করবে।
2. **Add file → Create new file** → নামের ঘরে লিখুন `.github/workflows/update-videos.yml` → এই ফোল্ডারের `update-videos.yml` ফাইলের সব লেখা কপি করে পেস্ট করুন → Commit

## ধাপ ৪: Actions-কে লেখার অনুমতি দিন
**Settings → Actions → General → Workflow permissions → "Read and write permissions"** → Save

## ধাপ ৫: প্রথমে "শুকনো" রান, তারপর আসল রান
1. **Actions → Update waz videos → Run workflow**
   - `dry_run` ✅ টিক দিন, `lookback_days` = **180**
   - রান শেষ হলে **Summary** খুলে দেখুন কোন কোন ভিডিও যোগ হতো। ভুল বক্তার ভিডিও থাকলে আমাকে জানান।
2. সব ঠিক থাকলে আবার Run করুন, এবার `dry_run` টিক ছাড়া, `lookback_days` = 180।
3. এরপর প্রতিদিন বাংলাদেশ সময় সকাল ৬:১৭-র দিকে নিজে থেকে চলবে। গত ১৮০ দিনের ভিডিওর মধ্যে সবচেয়ে বেশি দেখা হয়েছে এমন, এখনো তালিকায় নেই এমন ভিডিও থেকে প্রতি বক্তার সর্বোচ্চ ৫টি যোগ হবে। (`scripts/scholars_config.json`-এ `"sort_by": "date"` দিলে নতুনতম ভিডিও আগে আসবে।)

## কী কী সুরক্ষা আছে
- আপনার পুরনো কোনো রেকর্ড মোছে না বা সরায় না; নতুন ভিডিও সেই বক্তার তালিকার উপরে বসে
- আগে অস্থায়ী ফাইলে লেখে, পুরোটা যাচাই করে, তারপর আসল ফাইল বদলায়
- ভিডিও শুধু তখনই নেয় যখন সেটা public, এমবেড-অনুমোদিত, লাইভ নয়, কমপক্ষে ১০ মিনিট লম্বা, আর টাইটেলে বক্তার নাম আছে
- নেট সমস্যায় ৩ বার চেষ্টা করে; key ভুল হলে কিছু না বদলে থামে; quota শেষ হলে যা পেয়েছে তা রেখে থামে
- কিছু ফেল করলে Actions-এ লাল ✗ দেখায়, GitHub আপনাকে ইমেইল পাঠায়
- ডিলিট বা প্রাইভেট হয়ে যাওয়া ভিডিও মোছে **শুধু** আপনি `prune` টিক দিয়ে চালালে

## নতুন বক্তা যোগ করতে
নতুন বক্তা তিন জায়গায় যোগ করতে হবে:
1. `scripts/scholars_config.json`: খোঁজার নিয়ম
2. `waz_icone.json`: অ্যাপে নাম আর ছবি দেখানোর জন্য। একই `key` দিন; প্রতিটি `imageUrl` আলাদা হতে হবে।
3. প্রথম রানে বট নিজেই `video_studio.json`-এ সেই key দিয়ে ভিডিও যোগ করবে।

টেস্ট নিজে থেকেই ধরে ফেলে যদি কোনো key এক ফাইলে থাকে আর অন্য ফাইলে না থাকে।

`scripts/scholars_config.json`-এ একটি লাইন যোগ করুন:
```json
{"key": "Bokta_Name_Ekhane", "auto": true,
 "queries": ["বক্তার বাংলা নাম ওয়াজ", "Bokta English Name waz"],
 "must_match": ["বক্তার বাংলা নাম", "bokta english name"]}
```
- **key**: অ্যাপে যে itemType দেখাবে (শুধু ইংরেজি অক্ষর, সংখ্যা আর `_`)
- **queries**: YouTube-এ যা লিখে সার্চ করবে। প্রতিটি কোয়েরিতে ১০০ ইউনিট খরচ হয়, তাই ১-২টি রাখুন।
- **must_match**: টাইটেলে এগুলোর অন্তত একটি না থাকলে ভিডিও নেবে না। এটা ভুল বক্তার ভিডিও আটকায়, নামের সব প্রচলিত বানান দিন।
- **min_duration_sec** (ঐচ্ছিক): ছোট ক্লিপ নিতে চাইলে, যেমন `180`
- **channel_ids** (ঐচ্ছিক): বক্তার অফিসিয়াল চ্যানেল আইডি (`UC...`)। এটা সবচেয়ে নির্ভুল আর সস্তা (১ ইউনিট)।

কোনো চ্যানেল বারবার ভুল ভিডিও দিলে তার আইডি `blocked_channel_ids`-এ যোগ করুন।

## লোকাল টেস্ট (Mac Terminal)
```bash
cd host_api
python3 -m unittest discover -s scripts -p "test_*.py" -v
YT_API_KEY=xxxx python3 scripts/update_videos.py --only Amir_Hamza --dry-run
```
