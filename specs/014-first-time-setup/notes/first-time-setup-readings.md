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
