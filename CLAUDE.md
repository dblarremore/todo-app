# Todo app — orientation

**Read `DESIGN.md` before changing anything.** It explains the architecture, the
SpringRank prioritization, the multi-machine safety guards, and why the non-obvious
choices are the way they are. `README.md` is the user-facing manual.

## Current deployment

The active checkout is `~/todo-app` on A414, outside Dropbox. `Todo.command` runs
`launch.py`, which starts localhost port 8765 and Tailscale Serve HTTPS port 8443
on A414; other Macs only open that host. See README.md for current operation.
The Dropbox and SSH references in older design notes describe the previous setup.
`updated` is now an opaque UUID revision token. Keep personal data out of Git.

## What this is

A local todo app: `todo.py` (stdlib-only server) serves `app.html` (the
entire UI, ~1,850 lines, no dependencies) and owns all writes to `data.json`.

    python3 todo.py     # → http://127.0.0.1:8765/

## Ground rules

- **`data.json` is the only store** — tasks, projects, and the pairwise comparison
  graph. There is no database and no markdown mirror; don't reintroduce one.
- **Don't hand-edit `data.json` while the server is running.** The app will overwrite
  it. Stop the server first, or go through the UI.
- **Preserve the concurrency guard.** Saves send `X-Base-Updated`; the server answers
  409 if the file changed underneath. This is what makes the folder safe in Dropbox.
  Don't remove it when touching save logic.
- **No `alert()` / `confirm()`** in new code — browser modals freeze automation.
  Destructive actions get inline confirmation *and* remain ⌘Z-undoable.
- **Schema fields are optional.** Most tasks predate `tonight`; code treats missing
  as falsy. Add nullable fields freely, never write a migration.

## Verifying a change

    python3 -c "s=open('app.html').read(); \
      open('/tmp/pg.js','w').write(s[s.index('<script>')+8:s.rindex('</script>')])" \
      && node --check /tmp/pg.js

A JS syntax error renders as a silently blank page, so always check. For logic, pull
functions out of `app.html` in Node and stub the DOM (see DESIGN.md §8); for anything
visual, actually drive the browser — several real bugs here were invisible in review.

If Chrome reports `ERR_CONNECTION_REFUSED` while `curl` succeeds, the user's browser
is on a different machine than this shell. Re-pairing the extension won't help; the
SSH tunnel in `README.md` is the fix.
