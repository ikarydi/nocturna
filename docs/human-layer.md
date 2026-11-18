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

## Mixing it in

Once a release has a take and at least one human layer, the Human layer box shows
**Mix into track**. It lays every human layer under the take and saves the result as a new
take; the original is kept.

- **Level** is set by loudness, not raw volume: *Balanced* puts the layer 10 LU under the
  track, *Subtle* 16, *Upfront* 6. A quiet field recording and a loud loop end up equally
  present.
- **Loop if shorter** repeats a short sound across the whole track. Every layer fades in and
  out, and a limiter keeps the mix below -0.5 dBFS.
- **Mix again** always starts from the original take, so layers are never stacked twice.
- Export master + delivery again after mixing. Approval is refused while the delivery is
  older than the newest take.

For anything more musical (placing a phrase at a drop, EQ, reverb), mix in Audacity or a DAW
and upload the result as a new take instead.

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
