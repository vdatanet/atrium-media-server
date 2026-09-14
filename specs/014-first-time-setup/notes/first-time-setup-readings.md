# 014 — what a Jellyfin answers before and just after its first-time setup

`[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`

The question was 014's five readings, OQ-4 to OQ-8, and the place they could be asked was fixed
before any of them was: **an operator's server has finished its setup and cannot be put back**, so
the state these operations exist for survives only on an instance that has just started. The probe
starts the pinned image with `InstanceSpec(configure=False)` — no first-time setup, no library, no
account — walks the window in the order 014 specifies it, and destroys the instance and its volumes,
including on failure.

**Five runs, and the reason there were five is the point of this note.** One could not look: the
pinned image failed to start and nothing was measured. After each of the other four, reading the
output closely moved a claim, so the script was extended and run again — and the spec cites only
what the script as committed reproduces. The last run's readings are below, with volatile values
elided.

## Readings

### The window, before any account

```
StartupWizardCompleted on a fresh instance      False
POST /Startup/User before any account exists    404 application/json; charset=utf-8
                                                {"type":"…rfc9110#section-15.5.5","title":"Not Found","status":404,"traceId":"…"}
GET /Startup/User (creates the account)         200 application/json; charset=utf-8  {"Name":"root"}
POST /Startup/User, empty password              400 application/json; charset=utf-8  "Password must not be empty"
POST /Startup/User, whitespace password         400 application/json; charset=utf-8  "Password must not be empty"
rename to an empty name                         400 text/plain  Error processing request.   (name stays root)
rename to "bad/name:here"                       400 text/plain  Error processing request.   (name stays root)
POST /Startup/User, valid                       204
```

### Libraries, during setup, with no token

```
POST /Library/Refresh, no token                 401  (no body, no Content-Type)
AddVirtualFolder, no token                      204
"Movies" twice, then "movies", then "Movies?"   204 204 204
  names afterwards                              ['Movies', 'Movies ', 'Movies2', 'movies']
AddVirtualFolder, empty name                    400 application/json  {"title":"One or more validation errors occurred.","errors":{"name":[…]}}
AddVirtualFolder, name of spaces                400 application/json  (the same validation refusal)
AddVirtualFolder, path that does not exist      400 text/plain  Error processing request.
collectionType = musicvideos, homevideos,
  boxsets, books, mixed                         204 each, stored with that type
collectionType omitted                          204, stored with no type
collectionType = photos (not declared)          204, stored with no type
every library row                               LibraryOptions: 37 properties; PrimaryImageItemId: none;
                                                RefreshStatus 'Idle', RefreshProgress none
```

### Closing the window

```
POST /Startup/Complete                          204
StartupWizardCompleted after it                 True
GET /Library/VirtualFolders, no token           401  (no body, no Content-Type)
second POST /Startup/Complete, no token         401
second POST /Startup/Complete, administrator    204
GET /Library/VirtualFolders, non-administrator  403  (no body, no Content-Type)
POST /Library/Refresh, non-administrator        403  (no body, no Content-Type)
rename to a name another account holds          400 text/plain  Error processing request.
/UserViews for the first account                200, the libraries
ServerName after a setup that skipped it        the container's host name
```

### Scans

```
films browsable before any refresh              17        (11 in two earlier runs)
POST /Library/Refresh                           204 after 0.00 s; films then 17, scan task Running
  as it changed                                 Running 17 row='Idle'/None -> Idle 17 row='Idle'/None
AddVirtualFolder "Shows", refreshLibrary=true   204 after 0.07 s; episodes then 0, scan task Running
  as it changed                                 Running 0 row='Active'/10.67 -> Idle 9 row='Idle'/None
```

## What moved, run by run

- **Run 1** passed every check the script made, and its output — read line by line rather than by
  its verdict — showed two claims 014 had made from the source to be wrong and one case nobody had
  predicted. The missing-path `400` body was `Error processing request.`, not the message the source
  builds; the empty-name `400` was request validation, not the library manager; and `photos`, a type
  the reference does not declare, answered `204`.
- **Run 2** could not look. The instance did not answer within 180 s and was already gone when its
  logs were asked for, so what killed it is not known; it is consistent with the pinned image's
  start failure counted at four of eight starts on 2026-09-02. Nothing was measured and nothing was
  left behind, and the retry was taken on that exit code alone — a run reporting a contradiction is
  never retried.
- **Run 3** added the three readings run 1 lacked: a name of spaces (the same validation `400`),
  the stored type of `photos` (none, as if omitted), and film counts on either side of each `204`
  instead of polling a status field. It showed the `204` does not wait, and that a library added
  with `refreshLibrary=false` had been scanned anyway.
- **Run 4** read the library row **during** each scan, because the spec's claim that the row never
  shows a scan rested on run 1's version of the script, which the committed one no longer
  reproduced. The row read `Active` while a newly added library scanned — so the claim was wrong,
  and the true one is narrower: the row shows the scan adding a library starts, and not the one
  `POST /Library/Refresh` starts.
- **Run 5** measured the one row still unverified — the `403` on `POST /Library/Refresh`, whose
  policy differs from the setup operations' — and reproduced run 4's `Active`, once only in a
  one-second sample before, now twice. It also read 17 films before any refresh where runs 3 and 4
  read 11, which is why the spec states that number as a range and not as 11.

## What these readings do not say

- **What started the scan of a library added with `refreshLibrary=false`.** Something scanned it
  before any refresh was asked for, every time; the probe did not isolate what.
- **Whether a running scan is restarted or left to finish** when `POST /Library/Refresh` arrives.
  The task read `Cancelling` when one was running and `Running` when none was, and the library
  reached all its films either way.
- **Whether a client's interface accepts a server whose setup skipped `POST /Startup/Configuration`.**
  The probe signed in and listed views; it rendered nothing.

---

## The second walk — T1's four readings, 2026-09-14

`[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`

014's task list opens with the four readings its plan could not take from a desk (plan §9, rows two
to four, and the order §6.4 inferred). They are asked **on the same instance, after the first walk
has finished**: the window is closed by then, so every request is the administrator's the first
walk set up, and every library is added over a directory of `FirstTimeSetup/` — one film per
directory, written into the fixture tree by `tests/fixtures/reference_tree.py` through the 003
generator, and reached by no library of the first walk.

**Five runs of the extended script, and two of them could not look.** Run 1 read all four and its
output moved the script twice: a `PrimaryImageItemId` on three rows, the same value on two of them,
and no word on what a scan then made of the path cases — so run 2 compared that value with each
row's `ItemId` and refreshed after the path cases. Run 2 found `Movies` and `movies` sharing an
`ItemId`, so run 3 added which of the two views that id is; **the instance stopped answering midway
through run 3's path cases** (`RemoteDisconnected`, the container already gone) and **run 4's never
answered within 180 s** — the pinned image's start failure again. Both were retried on that exit
alone; neither reported anything. Run 5 is the one below, and it reproduced every reading runs 1
and 2 had taken, the volatile values aside.

### 1. `/UserViews` over the types this server does not scan

One library per case over one film, `POST /Library/Refresh`, and the reading once the scan task
was idle (films 17 → 20).

```
case          /UserViews row                CollectionType there   ChildCount, read twice   what the scan put under its ItemId
musicvideos   present, CollectionFolder     'musicvideos'          two numbers, 1..9        a MusicVideo
homevideos    present, CollectionFolder     'homevideos'           two numbers, 1..9        a Video
boxsets       present, CollectionFolder     'boxsets'              two numbers, 1..9        nothing
books         present, CollectionFolder     'books'                two numbers, 1..9        nothing
mixed         present, CollectionFolder     absent                 two numbers, 1..9        a Movie
omitted       present, CollectionFolder     absent                 two numbers, 1..9        a Movie
photos        present, CollectionFolder     absent                 two numbers, 1..9        a Movie
```

The seven `type-*` libraries the first walk added over `Empty` are views too, with the same
`CollectionType` split. `ChildCount` is behaviours §3.25's random number: the two readings differed
on six rows of seven in run 5 (`4 then 7`, `2 then 1`, …) and are elided. Every library also has one
`Folder` under it, the directory its path names, which the last column leaves out.

### 2. The raw key set of every `GET /Library/VirtualFolders` row

```
rows   keys
  3    CollectionType ItemId LibraryOptions Locations Name PrimaryImageItemId RefreshStatus
 12    CollectionType ItemId LibraryOptions Locations Name RefreshStatus
  4    ItemId LibraryOptions Locations Name RefreshStatus
```

- **No key is ever `null`.** `CollectionType` is absent on the four rows stored with no type
  (`type-omitted`, `type-photos`, `one-film-omitted`, `one-film-photos`) and reads `mixed` on the
  two added as `mixed`; `RefreshProgress` is absent on every idle row.
- **`PrimaryImageItemId` is the row's own `ItemId`** on the three rows over `/fixture/Movies` —
  `Movies`, `Movies2`, `movies` — and absent everywhere else. The first walk read it on the same
  rows before any scan had finished, and read none.
- **`Movies` and `movies` share one `ItemId`.** The listing names `movies`'s view for both rows,
  and `Movies`'s own view has another id — so a client browsing `Movies` by the id the listing
  gives it is browsing `movies`.

### 3. The paths `POST /Library/VirtualFolders` is given

`collectionType=movies`, `refreshLibrary=false`, the body carrying no `PathInfos` except where said.

```
paths                                           status                          the listing then holds
fixture/FirstTimeSetup/relative  (a dir from /) 204                             Locations ['fixture/FirstTimeSetup/relative']
FirstTimeSetup/relative  (a dir from nowhere)   400 text/plain Error processing request.   no row
/…/outer,/…/outer/inner                         204                             Locations [outer, outer/inner]
/…/twice,/…/twice                               204                             Locations [twice, twice]
none, and none in the body                      204                             Locations []
none, one in the body's PathInfos               204                             Locations ['/fixture/FirstTimeSetup/body']
```

A refresh afterwards (films 20 → 24): the relative-path library and the pathless one hold nothing;
the nested library holds `The Outer Film` and a `Movie` named `inner` — **the inner film once, not
twice**; the doubled path holds its film once; the body-only library holds its film.

### 4. A refused rename, and the password it carried

```
POST /Startup/User {Name: "bad/name:here", Password: <new>}   400 text/plain Error processing request.
  the account's name after it                                  unchanged
AuthenticateByName with the old password                       200
AuthenticateByName with the new password                       401
```

### What the second walk moved

- **Plan §6.4's inference held**: a rename refused `400` leaves the password, so AC-3's test can
  assert it. Nothing amended.
- **Plan §6.5 and §9's `/UserViews` question is answered, and the spec gains it**: every library is
  a view, and `mixed` is a type of the listing and not of the view. Spec §3.6.1 and AC-7 amended,
  and §3.6.1's *"what the reference's scan puts in a library of no type was not read"* replaced by
  the reading.
- **Spec §3.5's `PrimaryImageItemId` row was wrong as worded.** *"None of which had artwork"* was a
  reading taken before any scan had finished; a scanned library whose films have images carries its
  own id, because the reference generates the library folder a collage
  `[source: Emby.Server.Implementations/Images/CollectionFolderImageProvider.cs:21-40 @ v10.11.11]`.
  The row is amended with the reading; what this server answers is put to the operator.
- **Plan §6.6's path refusals are contradicted by every case but one.** Nested paths, a doubled
  path, a relative path that resolves and no `paths` at all are `204` on the reference, where §6.6
  refused them on 003's grounds; and with no `paths` the body's `PathInfos` becomes the library's
  paths, where spec §3.6 and OQ-13 say nothing in the body is applied. **Neither is amended: both
  are put to the operator**, and plan §6.6 says so beside the steps.
- **A listing `ItemId` two libraries share**, found by reading the key set rather than asked for:
  the listing finds a library's folder by its path compared ignoring case
  `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1319 @ v10.11.11]`, so `Movies`
  beside `movies` is listed with `movies`'s. Spec §3.5's `ItemId` row records it; whether this server
  reproduces it is put to the operator.

### What the second walk does not say

- **What a client makes of a library whose `CollectionType` is absent in its view but `mixed` in
  the listing.** The probe reads the wire.
- **Whether the reference's process working directory is `/`.** The relative path that was accepted
  names a directory from `/`, and the image declares no working directory; the one that names a
  directory from nowhere was refused. That is consistent with resolving against `/` and proves no
  more.
