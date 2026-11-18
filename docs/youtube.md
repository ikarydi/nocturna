# YouTube uploads

After a release is approved, Nocturna can upload it to YouTube on a fixed weekly schedule:

- a 1920x1080 video (the cover on night black with the delivery audio), and
- a 1080x1920 Short of up to 45 seconds taken from about a third of the way in.

Every upload is created **private** with a scheduled `publishAt`, so nothing goes public
before its slot and you can still pull it in YouTube Studio. Every upload sets
`status.containsSyntheticMedia = true`, YouTube's "altered or synthetic content" disclosure.
That flag cannot be turned off in Nocturna.

The description is built from the release: your description, catalog number and capture
time, BPM, key and lane, your credits plus the human-layer credits (CC BY attribution is
added automatically), and an AI disclosure line. The cover becomes the thumbnail, and the
video is added to a playlist named after the lane (created if missing).

## One-time setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project, enable
   **YouTube Data API v3**, configure the OAuth consent screen (External, add yourself as a
   test user), and create an **OAuth client ID** of type **Desktop app**. Download its JSON to
   `data/youtube-client-secret.json`.
2. Install the extra and sign in:

   ```bash
   pip install -e '.[youtube]'
   python -m nocturna.youtube auth
   ```

   It prints a Google sign-in URL. Open it in your Windows browser and pick the channel's
   account. WSL2 forwards `localhost:8765` back to the script. The token is saved to
   `data/youtube-token.json` (mode 600, git-ignored).
3. In `.env` set `YOUTUBE_ENABLED=true`. Set `YOUTUBE_AUTO_SCHEDULE=true` if approving a release
   should book its uploads straight away; otherwise use the dashboard's **Schedule** button.
4. Verify the channel with a phone number, otherwise custom thumbnails are refused (the upload
   itself still works and the failure is noted on the upload).

Make the first upload a test you delete afterwards. The current API reference says uploads
from unverified API projects are no longer forced to private, but check it on your project.

## Cadence

`YOUTUBE_LONG_SLOTS` and `YOUTUBE_SHORT_SLOTS` are weekly slots in `YOUTUBE_TIMEZONE`
(default: Tuesday and Friday 20:00 for videos, four Short slots). Each slot takes one upload,
so the channel grows at a steady human pace instead of bulk drops, which YouTube's
"inauthentic content" policy penalises. A slot is never closer than
`YOUTUBE_MIN_LEAD_HOURS` (default 12) so you have time to check the private upload.
Two releases with the same title are refused.

## Quota

Checked 2026-11-18 on the [quota calculator](https://developers.google.com/youtube/data/determine_quota_cost):
`videos.insert` costs 1 unit from a separate bucket of 100 uploads a day. `thumbnails.set`
and `playlistItems.insert` cost 50 units each from the default 10,000 daily units. The
default cadence uses a small fraction of that.

## When something fails

The upload row shows `failed` with the error, and the release history records it. Press
**Retry** in the dashboard while its slot is still in the future, or schedule the release
again.
