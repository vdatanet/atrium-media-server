# Recorded MusicBrainz responses

**Synthetic, not captured** — the same distinction as the TMDB fixtures beside them, and for the
same reason: this repository's suite reaches no network. They are shaped after MusicBrainz's
documented `ws/2` JSON, and they pin the **parser** rather than the **API**. Plan §8's opt-in live
test (`needs_reference`, T13/T14) is what would notice the service changing shape.

The album, the artist and everything in them are invented.

The three search fixtures exist for the three outcomes the exactly-one rule has: one survivor,
none, and two.
