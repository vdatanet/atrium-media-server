---
feature: 006-images
title: Images
status: Draft
created: 2026-08-26
updated: 2026-08-26
depends_on: [004, 005]
---

# 006 — Images

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Serve the artwork that 004 located, at the size the client asked for, with cache behaviour that
makes a grid of two hundred posters load once rather than every time.

**Client behaviour unlocked:** a library that looks like anything at all. Posters are most of what
a user sees.

## 2. Scope

**In scope**

- `GET /Items/{itemId}/Images/{imageType}` and its indexed form.
- Which image an item advertises, and how a client knows.
- Resizing, format selection and quality.
- Cache behaviour: tags, conditional requests, and the on-disk cache.
- Delivery of existing chapter images.

**Out of scope**

- Uploading, deleting or reordering images over HTTP.
- Generating images: trickplay tiles, chapter extraction, splashscreens.
- User avatars as a separate route.
- `/Artists/{name}/Images/...` and other by-name image routes — no analysed client uses them, and
  by-name items carry their images through their item id.
- Locating artwork on disk or fetching it from a provider — that is 004.

## 3. Behaviour

### 3.1 How a client discovers an image

Items carry `ImageTags`, a map of image type to tag:

```json
"ImageTags": { "Primary": "ceec6133f1be9a00bb8b07cc59a26c99" },
"BackdropImageTags": [ "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7" ]
```

`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Backdrops are a list**, not a map, because an item can have several and they are addressed by
index.

**A tag is a content hash.** It must change when the image changes, and **only** then. This is the
entire cache-invalidation mechanism: clients embed the tag in the URL, so a stable tag means an
image cached forever and a churning tag means every poster re-fetched on every scan. A tag derived
from a timestamp or a row id would look correct and quietly destroy client caching.

An item with no image of a type simply omits it. `ImageTags` is `{}` rather than absent when there
are none, so a client can distinguish "no images" from "field not requested".

Items also carry **inherited** tags so a list can render without a second request per item:
`AlbumPrimaryImageTag`, `SeriesPrimaryImageTag`, `SeriesThumbImageTag`,
`ParentThumbImageTag` with `ParentThumbItemId`, and `ParentBackdropImageTags`. An episode without
its own artwork is rendered with its season's or series' — and the client needs both the tag and
the id of the item that owns it.

### 3.2 `GET /Items/{itemId}/Images/{imageType}` — `GetItemImage`

**Consumers:** music-client, video-client.

`imageType` is one of `Primary`, `Backdrop`, `Thumb`, `Logo`, `Banner`, `Art`, `Disc`, `Chapter`.
`[spec: ImageType]` The indexed form `.../{imageIndex}` addresses one of several.

**Request parameters** v1 honours:

| Parameter | Effect |
|---|---|
| `maxWidth`, `maxHeight` | Fit inside the box, preserving aspect ratio |
| `width`, `height` | Exact dimension |
| `fillWidth`, `fillHeight` | Fill the box, cropping the overflow |
| `quality` | Compression quality, 0–100 |
| `format` | Requested output format |
| `tag` | The expected content tag; §3.4 |

Declared upstream but **not implemented in v1**: `percentPlayed`, `unplayedCount`, `blur`,
`backgroundColor`, `foregroundLayer`. These composite decorations onto the image server-side. No
analysed client uses them, and a client that sends one receives the undecorated image — a visible
difference, recorded here rather than discovered later.

**Authentication is required**, and in practice comes as `?api_key=` because these URLs are handed
to image loaders that do not set headers (002 §3.1). An image route that only accepted headers
would leave browsing working and every poster broken.

**Response — 200:** the image bytes, with the real `Content-Type`, a `Content-Length`, and
`Accept-Ranges: bytes`.

**Errors**

| Condition | Status |
|---|---|
| Unknown item, or one the user may not see | `404` |
| Item exists but has no image of that type | `404` |
| `imageIndex` out of range | `404` |
| Unparseable dimension or quality | `400` |

### 3.3 Resizing

**Never upscale.** A request for 600px from a 400px source returns 400px. Upscaling costs CPU and
bytes to deliver a blurrier image than the original.

**Aspect ratio is preserved** except under `fillWidth`/`fillHeight`, which crop centred.

**Format selection**, in order: an explicit `format` if supported; otherwise the source format,
except that a source with no transparency may be served as JPEG when that is materially smaller.
Transparency is never discarded — a logo served as JPEG acquires a white box, which is immediately
visible on any dark client theme.

**Resized results are cached on disk**, keyed by item, image type, index, tag and the full
parameter set. The cache is disposable: deleting it costs CPU, never correctness. It lives outside
the library root (004 §2).

### 3.4 Caching and conditional requests

The contract with the client:

| Mechanism | Behaviour |
|---|---|
| `ETag` | Sent on every image response, derived from the tag and the parameters |
| `If-None-Match` | Matching etag answers `304` with no body |
| `Cache-Control` | Long-lived and immutable when the request carried a `tag` |
| `Last-Modified` / `If-Modified-Since` | Honoured |

**The `tag` parameter makes a URL immutable.** A request carrying the tag it expects can be cached
indefinitely, because the URL changes when the image does. A request without one is still correct
but cannot be cached as aggressively.

**A stale `tag` is not an error.** A client asking for an image by a tag the item no longer has
receives the *current* image with a `200` — not a `404`. The client is behind, not wrong, and
failing here empties a user's grid during a refresh.

### 3.5 Chapter images

`imageType` of `Chapter` with an index addresses a chapter thumbnail, for the scrubbing UI of a
video client.

v1 **serves** chapter images that exist on disk. It does not **extract** them: generating them
means decoding a video at intervals and running a background job over the whole library, and that
job — trickplay and chapter-image generation — is out of v1 in its own right
([roadmap](../../docs/roadmap.md#out-of-scope-and-why)). The arrival of transcoding does not change
this; a decode on demand for one client is not a sweep over every item. An item whose chapters have
no images answers `404` per chapter, which is what a client already handles for a server that has
not finished generating them.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Image tags | `ImageTags` and friends in 005's responses | Until the underlying image changes |
| Resized-image cache | Response latency only | Disposable at any moment |

The images themselves belong to the user, on disk, and are owned by 004.

## 5. Acceptance criteria

1. An item with a poster advertises a `Primary` tag; one without advertises `ImageTags: {}`.
2. The tag is unchanged across a rescan when the image file is unchanged, and changes when the file
   changes.
3. `GET .../Images/Primary` returns the bytes with the right `Content-Type` and a `Content-Length`.
4. `maxWidth=300` on a 1000px-wide source returns a 300px-wide image with the aspect ratio
   preserved.
5. `maxWidth=2000` on a 400px-wide source returns 400px — no upscaling.
6. `fillWidth`/`fillHeight` return exactly those dimensions, cropped centred.
7. An image with transparency is never served in a format that discards it.
8. A second identical request is served from cache and is byte-identical to the first.
9. `If-None-Match` with the current etag answers `304` with an empty body.
10. A request carrying a **stale** `tag` answers `200` with the current image, not `404`.
11. An unknown item, an item with no such image, and an out-of-range index all answer `404`.
12. Authentication via `?api_key=` works on this route (shared with 002 AC-3).
13. Deleting the entire resize cache changes no response body.
14. An episode without its own artwork carries its series' tag **and** the id of the item that owns
    it.

## 6. Conformance

| Endpoint / behaviour | Level | How it is proven |
|---|---|---|
| `GET /Items/{itemId}/Images/{imageType}` | **L2** | Golden headers and byte-length assertions against fixture images |
| Indexed form | **L2** | Fixture with three backdrops |
| Resize matrix | **L2** | Table-driven over the parameter combinations of §3.2 |
| Cache and conditional requests | **L2** | Request pairs asserting `304` and cache-hit identity |
| Tag stability | **L2** | Rescan comparison (AC-2) |

Golden files here assert **headers and dimensions**, not image bytes: encoder output is not stable
across library versions, and a test that breaks when an encoder is upgraded teaches nothing.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | How the reference derives its image tags — content hash or something weaker | Nothing; a content hash is at least as good | `tools/probe_image_tags.py` |
| OQ-2 | Does the reference `404` or serve the current image for a stale `tag`? §3.4 assumes serve | AC-10, which may be a divergence | `tools/probe_image_tags.py` |
| OQ-3 | The reference's format-selection rule, especially transparency handling | §3.3, if a client compares bytes | `tools/probe_image_formats.py` |
| OQ-4 | Does any client send `percentPlayed`, `blur` or `foregroundLayer`? | The declared gap in §3.2 | Differential harness (010) |

## 8. References

- [docs/compatibility/api-surface-v1.md §7](../../docs/compatibility/api-surface-v1.md#7-images)
- [specs/004 §3.4](../004-metadata-resolution/spec.md) — which file becomes which image
- [specs/005 §3.2](../005-item-query-api/spec.md) — where tags are advertised
- `[spec: GetItemImage, GetItemImageByIndex, ImageType]`
