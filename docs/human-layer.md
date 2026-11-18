# The human layer

Every release needs at least one human-made sound before it can be approved. Since mid-2026
Tidal pays no royalties on fully AI-generated tracks, Deezer keeps them out of
recommendations, and Bandcamp bans them. A real recording mixed into the track keeps
Nocturna releases AI-assisted rather than fully AI, and it makes them sound like Nocturna.

Add one from the release's **Human layer** box. Accepted sources:

| Source | Licence Nocturna accepts | What you must give |
|---|---|---|
| Own recording (field recording, a part you played) | owned | nothing else |
| Freesound | CC0, or CC BY (credited automatically) | author and link (filled in on import) |
| Public-domain recording | public domain | the source page as evidence |
| Royalty-free sample pack | the pack's royalty-free licence | the pack or vendor |
| Session player | work for hire | the player's name |

Licences that forbid commercial use or changes (CC BY-NC, ND, Sampling+, "personal use")
are refused. Sound recordings published more than 70 years ago are generally public domain
in the EU, but a modern remaster can carry new rights, so keep the source page. Popular
sample-pack loops can trigger Content ID claims; chop and process them.

## Freesound

Set `FREESOUND_API_KEY` (free at https://freesound.org/apiv2/apply) and the dashboard shows a
search box. Only CC0 and CC BY results get a **Use** button. Import stores Freesound's
high-quality MP3 preview with its licence, author and link. Download the original from
Freesound for a final mix if the preview is not good enough.

## Credits

Every human layer that needs credit appears in the release's human credits, in
`metadata.json`, in the provenance card and in the YouTube description.

Your own recordings remain the safest human layer: whether stock sounds count as "not
fully AI" is up to each platform's detector.
