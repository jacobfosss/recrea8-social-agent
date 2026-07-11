# Autonomous Social Agent (Instagram + TikTok)

This agent picks or generates content and posts it to Instagram and TikTok on a
schedule, running entirely on free infrastructure (GitHub Actions).

**Read this whole file before running anything.** The account-setup part
(Section 1) has to happen in your browser first — no code can do that part for you.

---

## 0. How it actually works (read this first)

- Both Instagram and TikTok's official APIs require your media (image/video) to
  live at a **public URL** before you can post it — you can't just upload a raw
  file from a script. This project solves that for free by committing media to
  a **public GitHub repo** and posting the raw.githubusercontent.com URL.
- **TikTok caveat:** until your TikTok developer app passes API audit for
  "Direct Post," posts land in the user's TikTok inbox as a **draft** they must
  tap "Post" on manually — TikTok does this deliberately to prevent spam bots.
  Full silent auto-publish only works after audit approval (free, but takes a
  few days and TikTok reviews your use case). I'll flag exactly where this
  matters below.
- **Instagram caveat:** while your Meta app is in "Development Mode" it can
  only post to Instagram accounts you've explicitly added as a Tester in the
  App Dashboard — which is fine if you're only posting to your own account,
  and means you never have to go through full App Review.
- Nothing here costs money: Meta Graph API, TikTok Content Posting API, GitHub,
  GitHub Actions, and Claude API (small usage) are all free at this scale.

---

## 1. Account & App Setup (one-time, do this in your browser)

### 1A. Facebook Page + Instagram linking
1. Create a Facebook Page (any name) at facebook.com/pages/create — required
   because Instagram's API is accessed *through* a linked Facebook Page.
2. Make sure your Instagram account is a **Business** or **Creator** account
   (Instagram app → Settings → Account type).
3. Link them: Instagram app → Settings → Business tools and controls →
   "Connect or create a Page."

### 1B. Meta Developer App (Instagram API access)
1. Go to https://developers.facebook.com/apps → Create App → type "Other" →
   "Business."
2. Add the **Instagram Graph API** product to the app.
3. In App Roles → Roles, add yourself (your Instagram/Facebook login) as an
   **Admin** or **Tester** — this is what lets Development Mode post to your
   own account without App Review.
4. Under Instagram Graph API → Generate a **User Access Token** with these
   permissions: `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`.
5. Exchange it for a **long-lived token** (60 days, renewable) — instructions:
   https://developers.facebook.com/docs/facebook-login/guides/access-tokens/long-lived
6. Get your Instagram Business Account ID:
   `GET https://graph.facebook.com/v21.0/me/accounts?access_token=TOKEN`
   → take the Page ID → then
   `GET https://graph.facebook.com/v21.0/PAGE_ID?fields=instagram_business_account&access_token=TOKEN`
7. Put both values in `.env` (see Section 3).

Full reference: https://developers.facebook.com/docs/instagram-platform/content-publishing

### 1C. TikTok Developer App
1. Go to https://developers.tiktok.com/ → Manage Apps → Create.
2. Add the **Content Posting API** product, scope `video.publish`.
3. Complete the "Direct Post" audit form (free) describing your use case —
   until it's approved, posts go to the user's inbox as drafts (see caveat
   above); this doesn't block you from testing the whole pipeline now.
4. Run the OAuth flow once to get a **user access token + refresh token** for
   your own TikTok account. TikTok's quickstart walks through this:
   https://developers.tiktok.com/doc/content-posting-api-get-started
5. Put the client key, client secret, and refresh token in `.env`.
6. In the developer portal, verify the `raw.githubusercontent.com` URL prefix
   for your repo under "URL properties" — TikTok's `PULL_FROM_URL` source
   requires the video's domain to be verified first, or the post call fails.

### 1D. Claude API key (for captions/content generation)
1. Get a key at https://console.anthropic.com (free credits available for new
   accounts; usage at this scale is a few cents a month).
2. Put it in `.env` as `ANTHROPIC_API_KEY`.

### 1E. GitHub (free hosting for both the code and the media files)
1. Create a **public** GitHub repo, push this whole folder to it.
2. Public repo = your media files get a working raw URL automatically. (Keep
   `.env` out of the repo — it's already in `.gitignore`.)
3. In the repo, go to Settings → Secrets and variables → Actions, and add each
   value from your `.env` as a Repository Secret (same names). GitHub Actions
   reads them from there, not from the `.env` file.

---

## 2. What goes in the repo

```
social-agent/
├── content/library/       ← drop your own images/videos here to be posted as-is
├── data/posted_log.json   ← tracks what's already been posted (auto-created)
├── src/
│   ├── content_selector.py   ← decides: pick from library, or generate new
│   ├── content_generator.py  ← Claude writes captions; Pillow makes graphic posts
│   ├── media_host.py         ← commits new media to repo, returns public URL
│   ├── instagram_poster.py   ← posts via Instagram Graph API
│   ├── tiktok_poster.py      ← posts via TikTok Content Posting API
│   └── main.py                ← orchestrator — run this
├── config.yaml             ← posting frequency, brand voice, topics
├── .env.example             ← copy to .env locally for testing
└── .github/workflows/post_schedule.yml  ← the free 24/7 scheduler
```

---

## 3. Local setup (to test before trusting the schedule)

```bash
cp .env.example .env       # fill in every value
pip install -r requirements.txt
python src/main.py --dry-run     # generates/selects content, shows what WOULD post, posts nothing
python src/main.py               # actually posts once
```

Edit `config.yaml` to set:
- `post_times` — how often the agent should post
- `brand_voice` — a short description Claude uses when writing captions
- `topics` — subjects to draw on when generating new content
- `platforms` — turn Instagram/TikTok on or off independently

---

## 4. Turning on full autonomy

Once local testing works and secrets are set in GitHub:
1. Confirm `.github/workflows/post_schedule.yml`'s `cron` schedule matches how
   often you want it to post (it's set to twice a day by default).
2. Push to GitHub. Actions will now run on schedule automatically, for free,
   forever, with no computer of yours needing to stay on.
3. Watch the "Actions" tab on GitHub the first few runs to confirm it's
   working and check for errors.

---

## 5. Costs — actually free at this scale
| Piece | Cost |
|---|---|
| Instagram Graph API | Free |
| TikTok Content Posting API | Free |
| GitHub public repo + Actions | Free (2,000 min/month free tier, this uses ~1 min/run) |
| Claude API (captions) | Free credits initially, then fractions of a cent per post using Haiku |

---

## 6. Self-improvement loop (engagement-based learning)

The agent now learns from how past posts perform, not just what it's told:

- Every post gets logged to `data/post_history.json` (topic, caption length,
  media type, source) at post time.
- A separate scheduled workflow (`metrics_pull.yml`, once daily) pulls
  likes/comments/reach/saves/shares for posts old enough to have accumulated
  engagement, and writes `data/performance_insights.json` — a plain-language
  summary of what's working ("video posts outperform images 3:1," "posts
  about X get double the engagement," etc.).
- That summary feeds into the Claude prompt for future captions, and topic
  choice is weighted (not forced) toward better-performing topics — untested
  topics still get tried occasionally so the agent doesn't lock onto one idea
  forever.
- This needs roughly 3+ measured posts before it has enough data to draw any
  pattern; before that it behaves exactly like before.
- **TikTok metrics only populate once your app is past the Direct Post audit**
  — until then, TikTok's contribution to the learning loop is inactive
  (harmless no-op), while Instagram's works immediately since likes/comments
  need no extra approval.

You can inspect what it's learned any time: `data/performance_insights.json`,
or run `python -m src.performance_analyzer` locally to print the summary.

---

## 7. Style inspiration, voiceovers, and research-backed content

### Style inspiration (not scraping)
Automated scraping of other creators' Instagram/TikTok posts is against both
platforms' Terms of Service, and reusing their images/video/voiceovers would
be a copyright problem regardless of good intent — so this project doesn't do
that. Instead: **you** save screenshots of accounts/posts whose aesthetic you
want to channel into `content/style_references/`, then run the style-guide
workflow (Actions tab → "Rebuild style guide" → Run workflow, or locally with
`python -m src.style_analyzer`). Claude looks at each image and describes the
*transferable style qualities* — color palette, layout, typography, mood —
never the specific subject matter, and synthesizes them into
`data/style_guide.json`, which then quietly informs every generated post's
look and tone. Re-run it any time you add new references.

### Voiceovers and narrated videos
Voiceovers use **Piper**, a free, fully offline, open-source neural TTS engine
(no API key, no per-use cost, GPL-3.0 licensed tool — doesn't affect your
content's rights). `src/video_builder.py` turns a short script into a
narrated vertical video: each line becomes a text-card scene with matching
narration, stitched together with moviepy. Set
`content_generation.educational_as_video: true` in `config.yaml` to make
research-based posts narrated videos instead of static cards — slower to
generate but more scroll-stopping. Drop a royalty-free track (e.g. from
Pixabay, which explicitly licenses for commercial use) into
`content/music/background.mp3` and it's mixed in quietly under narration;
this project won't auto-download music for you, since that would mean
scraping rather than using a real licensing agreement.

### Research-backed educational content
`src/research_agent.py` queries **PubMed's E-utilities** — NIH's official,
free, keyless API — for real, recent studies on the topics in
`config.yaml`'s `research.topics` (ultra-processed foods, inflammation,
artificial sweeteners, etc.), then has Claude translate each abstract into a
short, honest, plain-language post in your brand voice: paraphrased (never
quoted) and explicitly instructed to stay measured about what a study does
and doesn't show — no exaggerated health claims. Results queue into
`data/research_queue.json`; `content_selector.py` treats this as one of three
content types it rotates between (`content_mix` in `config.yaml` controls the
ratio: library / educational / lifestyle). A weekly scheduled workflow
(`research_pull.yml`) keeps the queue topped up automatically.

**Worth knowing:** an AI-simplified summary of a study is not medical advice
and shouldn't be presented as more definitive than the underlying research —
Claude's prompt is written to stay measured, but you should spot-check the
first several posts against the actual abstracts before trusting it fully.

---

## 8. Engagement — what's automated and what isn't (and why)

Automated commenting/liking on **other accounts'** posts violates both
Instagram's and TikTok's platform policies as "inauthentic behavior" — the
realistic outcome is API revocation or a shadowbanned account, not more
reach. This project intentionally draws the line here:

- **Auto-reply to comments on your own posts** (`comment_reply.py`, runs
  every 3 hours) — sanctioned by Meta; this is what the
  `instagram_manage_comments` permission exists for. Requires adding that
  scope when you generate your access token in Section 1B.
- **Engagement digest** (`engagement_assist.py`, runs weekly) — uses
  Instagram's official Business Discovery endpoint to surface recent posts
  from accounts you list in `config.yaml`'s `engagement.accounts_to_monitor`,
  and drafts a suggested comment for each. It writes to
  `data/engagement_digest.md` for **you** to review and post yourself — a
  few minutes of genuine engagement a day, informed by AI-drafted starting
  points, is both more effective and account-safe than automation.

## 9. Posting frequency

Short answer: **3–5 posts a week per platform**, not daily, at least to
start. This is grounded in current industry data, not a guess:

- Buffer's analysis of 11M+ TikTok posts found the biggest efficiency gain is
  going from 1x/week to 2–5x/week — each additional post beyond that keeps
  helping, but with steadily diminishing returns, and low-quality high-volume
  posting can actually suppress an account's average reach.
- The convergent 2026 guidance across Instagram, TikTok, and small-business
  benchmarks lands the same place: **Instagram feed 3–5x/week**, **TikTok
  2–5x/week** (TikTok tolerates and rewards somewhat higher volume since each
  video is evaluated independently, but "post 4x/day" advice is aimed at
  full-time creators, not a brand running one content pipeline).
- Consistency matters more than the exact number — algorithms read regular
  posting as a signal of account health, and most sources recommend
  committing to a cadence for at least 6–8 weeks before judging results or
  changing frequency.

**My recommendation for you specifically:** start at **every other day (≈4x/week)
per platform** rather than every 3 days — it's inside the proven sweet spot
and gives the performance-learning loop more data points faster, while still
being very sustainable at zero marginal cost (no human has to shoot content).
Once you've added real photography/video (Part 1 of the audit) and are
comfortable with output quality, you can push toward daily on TikTok
specifically, since that platform tolerates volume best. I'd hold Instagram
feed at 3–5x/week even later — that platform punishes quality drops harder
than TikTok does. Instagram **Stories** (once built) can run more often, even
daily, since they carry a lower quality bar.

Change `.github/workflows/post_schedule.yml`'s `cron` entries to match
whatever cadence you land on — it's currently set to 2x/day, which I'd
dial back to match the above.

---

## 10. Visual quality upgrades, content calendar, and approval mode (launch-readiness pass)

### Real photography instead of flat-color cards
Get a free key at pexels.com/api and set `PEXELS_API_KEY`. Once set, every
generated post pulls a real, commercially-licensed stock photo matching the
topic as its background (with a gradient overlay for text legibility),
instead of a flat color. Without the key, it still works — just falls back
to the solid-color version, so nothing breaks if you skip this.

### Your logo and font
Drop `content/branding/logo.png` (transparent background recommended) and
`content/branding/font.ttf` into the repo. Every generated image and video
caption will then use your actual font and watermark your logo in the corner
automatically. Without these, it uses a clean system font and no watermark.

### Better video: motion + synced captions + real music
Videos now use a subtle Ken Burns zoom (not a static slideshow) and animated
word-by-word captions timed to the voiceover — the current dominant format
for short-form video. Set `JAMENDO_CLIENT_ID` (free at devportal.jamendo.com)
for automatic royalty-free background music via real Creative Commons
licensing, or drop your own track at `content/music/background.mp3` — either
works, and it's silent (not broken) if neither is set up.

### Instagram Stories
`instagram_poster.post_story()` is ready to use — not yet wired into the main
scheduled run since Stories work best posted more frequently/casually than
feed content. Ask me to wire in a separate Stories-specific workflow once
you're ready (e.g. quick polls, behind-the-scenes, repurposed feed content).

### Content calendar (themed pillars)
`config.yaml`'s `content_calendar` now lets you assign a theme to specific
weekdays (defaults: Mythbusting Monday = educational, Ingredient Spotlight
Wednesday = lifestyle, Weekend Ready Friday = library). This gives the feed
intentional structure instead of pure randomness — edit or remove freely.

### Approval mode (on by default — recommended for launch)
`posting.require_approval: true` in `config.yaml` means **nothing posts
automatically yet**. Instead, every piece of content opens a GitHub issue
with the image/video preview and caption; comment `approve` on it and a
follow-up workflow (`approval_check.yml`, checks every 30 min) publishes it
for real. This is the safety net I'd genuinely recommend keeping on for the
first few weeks — flip it to `false` once you trust the output quality and
the health-claim accuracy of the research pipeline.

---

## 11. What I still need from you
- Confirm once you've completed Section 1 and have all 6 values for `.env`.
- Drop a few sample images/videos into `content/library/` if you want the
  "pick existing content" mode to have something to work with.
- Tell me your brand voice / niche so I can fill in `config.yaml` properly —
  right now it has placeholder values.
