# Todo

A personal todo app with projects, subtasks, due dates, and pairwise priority
ranking. Plain HTML/JavaScript and a Python standard-library server; no build or
packages to install. Requires Python 3, macOS, and Tailscale.

## Open it

Double-click **`Todo.command`** in `~/todo-app`.

- **On A414:** checks the tailnet connection, starts the server if needed, exposes
  it privately through Tailscale Serve, and opens the shared URL.
- **On M5BP:** opens the same URL on A414 without starting a second server.

Bookmark **https://a414.tail5b7e55.ts.net:8443/** on either Mac. A414 must stay awake
and connected. Changes save after about half a second; other tabs refresh every
15 seconds or when focused, unless you are editing or have unsaved changes.

The server stays running after closing Terminal. After logout or reboot,
double-click the launcher again. Tailscale Serve may ask you to enable HTTPS on
first setup. Existing services on other ports are preserved; Todo uses HTTPS 8443
and forwards to `127.0.0.1:8765`. Access follows your tailnet rules.

```sh
./Todo.command --no-open  # start without opening a browser
./Todo.command --stop     # stop this folder's local server
```

Errors appear in Terminal; server logs are in `~/Library/Logs/todo-app.log`.
If port 8765 belongs to an old Dropbox instance, stop that instance first.
To choose a different host, set `TODO_HOST` to its Tailscale machine name on both
Macs (default: `a414`). A fresh clone on M5BP is enough to use the launcher.

## Data and backups

`data.json` contains all tasks, projects, and priority comparisons. The server
writes it atomically and keeps up to 200 snapshots in `backups/`, at most one per
five minutes of saving. Export downloads another copy.

**Task data and backups are excluded from Git.** GitHub distributes the app code;
both browsers use A414's data. This folder is outside Dropbox, so its live data
does not sync through Dropbox. Keep a separate backup of `data.json` and
`backups/`; these local snapshots do not protect against losing the host's disk.
The original Dropbox folder is an archive after this move; don't run it alongside
this copy. Offline edits are not reliably synced or merged.

## Use it

Add `Review report #research @friday !` to assign a project, due date, and flag.
`@tonight` adds a task to the rolling evening queue. Switch between List, Tiles,
and Timeline; Prioritize ranks tasks by importance and urgency. Use `⌘Z` to undo.

Saves reject stale revisions rather than merging simultaneous edits. A rejected
edit is retained in that browser's `localStorage` under `todo-rejected`.
Architecture and maintenance details are in [DESIGN.md](DESIGN.md).
