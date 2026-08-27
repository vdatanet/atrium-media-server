# Recorded TMDB responses

**These are synthetic, not captured.** They are shaped after TMDB's documented API — the field
names, the nesting, the `append_to_response` sub-objects — and were written by hand, because this
repository has no TMDB key and its suite reaches no network.

That distinction matters for what they can prove, and 004 plan §8 already draws it:

| These fixtures pin | They do not pin |
|---|---|
| the **parser** — that a payload of this shape produces these fields, that the match rule keeps one candidate and refuses two, that artwork bounds hold | the **API** — that TMDB still answers in this shape |

The second is what plan §8's opt-in live test is for (`needs_reference`, T14): it replays one real
movie and diffs the parsed fields, so drift is caught by the thing that can see it rather than by
a fixture pretending to have been recorded.

The film is invented. `The Fixture (1999)` is nobody's work, and neither are the people in its
cast.
