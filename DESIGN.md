# Design notes

Written for whoever picks this up next — human or Claude. `README.md` covers *how to
use* the app; this covers *how it works and why it is the way it is*.

Deployment update (October 2026): the active checkout is `~/todo-app` on A414.
`Todo.command` invokes `launch.py`: A414 hosts the app on localhost port 8765 and
Tailscale Serve HTTPS port 8443; other Macs open A414's shared URL. Task data is
local to the host and excluded from Git. The Dropbox deployment and SSH tunnel
notes below describe the previous setup; refer to README.md for current operation.

Built August 2026 for a single user (a network scientist) managing his own todo list.
Roughly 1,850 lines of HTML/CSS/JS plus a 217-line Python server. No dependencies, no
build step, no framework, no internet access at runtime.

---

## 1. Shape of the thing

    Todo.command  →  python3 todo.py  →  http://127.0.0.1:8765/
                                              │
                          app.html (whole UI) ─┤
                                              │
                                     data.json (everything)
                                     backups/  (5-min snapshots)

Two files do all the work:

- **`todo.py`** — a stdlib-only HTTP server. Serves `app.html`, owns every write to
  `data.json`, keeps rolling backups, and refuses stale writes. It has no model of
  tasks at all; it moves JSON to and from disk.
- **`app.html`** — one self-contained file: markup, CSS, and all application logic.
  It holds the entire list in memory, renders it, and PUTs the whole document back
  on change.

The split is deliberate: **the server is dumb so the client can be simple.** There is
no API surface to keep in sync with the UI, no partial-update protocol, no migrations
when a field is added. The cost is that every save ships the whole document — fine at
this scale (52 tasks ≈ 30 KB), and section 6 explains the one place that cost bites.

### Why a server at all

The obvious alternative is a plain `file://` page using the File System Access API.
That was rejected because FSA on `file://` origins can't persist its permission grant
across sessions in Chrome — you'd re-authorize the file every time you opened it. A
5-second `python3 todo.py` buys automatic, silent, atomic saves forever.

---

## 2. Data model

`data.json` is the only store. Everything lives here — tasks, projects, and the
prioritization comparison graph.

```json
{
  "version": 1,
  "updated": "a42cbd639df241799bd682d849f2db84",
  "projects": [ { "id": "p-research", "name": "Research", "color": "#a855f7" } ],
  "tasks":    [ { "id": "tfkrz1xe", "title": "Review IP License agreement",
                  "done": false, "project": "p-research", "parent": null,
                  "flagged": false, "tonight": false, "due": null,
                  "notes": "", "created": "2026-08-03", "completed": null } ],
  "priority": {
    "importance": [ { "w": "t041", "l": "t019" } ],
    "urgency":    [ { "w": "t010", "l": "t020" } ]
  }
}
```

Points that matter:

- **`tasks` is a flat array; order in the array *is* display order.** There's no
  `order` field to keep consistent. Reordering is `splice`. Nesting is `parent`
  pointing at another task's id, with children found by scanning in array order.
  Moving a subtree means splicing out the task plus all descendants and re-inserting
  — see `moveSubtree()`.
- **Fields are optional.** 50 of 52 tasks predate the `tonight` field and simply
  don't have it; the code reads `t.tonight` and lets `undefined` be falsy. Adding a
  boolean or nullable field needs no migration. Keep it that way.
- **`priority` stores raw comparisons, never scores.** Each entry is one answered
  question: `w` beat `l`. Ranks are recomputed from these edges on demand. The
  comparisons are the durable truth; the ranking is derived and disposable.
- **`updated` is the revision token** for the concurrency guard (section 6). The
  server rewrites it on every save.

---

## 3. Server (`todo.py`)

| Route | Method | Does |
|---|---|---|
| `/` | GET | serves `app.html` |
| `/api/data` | GET | the whole document |
| `/api/data` | PUT | replaces the whole document, guarded (section 6) |
| `/api/health` | GET | `{"app", "directory", "pid", "conflicts"}` — identity and conflict filenames |
| `/api/backups` | GET | recent snapshot filenames |

- **Writes are atomic**: write `data.json.tmp`, then `os.replace()`. A reader always
  sees a complete old or complete new file, never a half-written one. This matters
  more than usual because a sync client may be reading the file at any moment.
- **Backups** land in `backups/data-<timestamp>.json`, throttled to one per 5 minutes
  (`BACKUP_INTERVAL`), keeping the last 200 (`BACKUP_KEEP`). Throttling means the
  newest few minutes of work may exist only in `data.json` — acceptable, since
  `data.json` is itself durable.
- **`_lock` is an `RLock`**, not a `Lock`: the conflict check and the save it guards
  both take it, and they must be one atomic section.
- **Port 8765 is fixed.** Startup fails if occupied, keeping the Tailscale proxy
  deterministic. The launcher verifies `/api/health` identifies this app and folder
  before reusing an existing server. It never kills an unrelated listener.
- **Revision tokens are UUIDs**, so saves within the same second still have distinct
  revisions. `updated` is an opaque token; clients compare it for equality only.

---

## 4. Client architecture (`app.html`)

Deliberately old-fashioned: **one global `state`, one `render()`, re-render on
change.** No virtual DOM, no reactivity, no components. At 50–500 tasks a full
`innerHTML` rebuild is imperceptible, and it removes an entire class of
stale-view bugs.

    user action → mutate state → render() → save()  (debounced 450 ms)

- **`snapshot()` before every mutation** pushes a JSON deep copy onto an undo stack
  (max 60). That's why ⌘Z works across everything — edits, deletes, drags, even
  clearing the comparison graph — without any per-action undo logic.
- **`save()`** debounces 450 ms then PUTs. Also mirrors to `localStorage` under
  `todo-cache`, so a dead server degrades to a read-only cached view instead of a
  blank page.
- **Rendering is pure string building.** `rowHTML()` returns HTML; layouts assemble
  rows. Event handling is delegated from `document` on `data-*` attributes, so
  re-rendering never detaches a listener.
- **`localStorage` holds only preferences** — `todo-layout`, `todo-sidebar`,
  `todo-theme`, plus the `todo-cache` fallback and `todo-rejected` (section 6).
  No task data depends on it.

### Views vs. layouts — two independent axes

Easy to confuse; they compose.

- **View** = *which* tasks: `all`, `today`, `tonight`, `flagged`, `done`, or a
  project. Implemented in `matchesView()`.
- **Layout** = *how* they're drawn: `list`, `tiles`, `time`. Implemented in
  `groupedHTML()`, `tilesHTML()`, `timelineHTML()`.

`visibleSet()` bridges them and holds one subtlety: nesting layouts pull in a
matching task's **ancestors** so children have something to hang under, but the
timeline is flat and dates each row on its own, so pulling in an undated parent there
would just be noise. Hence the `layout !== "time"` branch. If you add a layout, decide
which side of that line it's on.

**Search deliberately ignores the active view.** Searching from "Today" scans
everything, including completed tasks. Scoping search to the current filter was the
original behavior and it was simply wrong — it hid real matches.

---

## 5. Prioritization (the interesting part)

The user is a co-author of SpringRank, so this had to be right.

### The maths

Ranks minimise the spring energy of the comparison network, with `A[i][j]` = number
of times *i* beat *j*:

    H(s) = ½ Σ_ij A_ij (s_i − s_j − 1)²

Every comparison is a spring of rest length 1 pulling the winner one unit above the
loser. Setting ∇H = 0 gives a linear system:

    [D_out + D_in − (A + Aᵀ)] s = d_out − d_in

That matrix is a graph Laplacian and therefore **singular** — adding a constant to
every rank costs nothing. Rather than pinning a gauge, we solve the regularised
system `(L + αI)s = b` with `α = 1e-6`, which selects the minimum-norm solution. That
choice does three useful things at once:

1. centres each connected component at zero,
2. leaves never-compared tasks at exactly 0 (their row is `α·s_i = 0`),
3. stays well-conditioned when the graph is in pieces — which it always is early on.

Solved by dense Gauss-Jordan with partial pivoting (`solveLinear`). O(n³) is nothing
at this size; correctness and legibility beat speed here.

**Verified against closed-form cases** — reproduce these if you touch `springRank()`:

| Input | Expected | Why |
|---|---|---|
| a beats b once | +0.5, −0.5 | one spring, rest length exactly satisfiable |
| a>b, b>c, a>c | +⅔, 0, −⅔ | springs can't all rest at once; least-squares shrinks |
| a>b>c>a | 0, 0, 0 | a pure cycle encodes no hierarchy |
| a>b and c>d | ±0.5 twice | components centre independently |
| isolated node | exactly 0 | regularisation, not an accident |

### Choosing the next pair

`proposePair()` runs three phases in order. Each returns a human-readable `phase`
string that the UI shows, so the user can tell what the algorithm is doing.

1. **Opening** — random pairs among tasks with zero comparisons. Cheap coverage.
2. **Runoff** — while the comparison graph has more than one component, pick a pair
   *spanning two components*, preferring similar win rates (winners meet winners,
   losers meet losers). This is first for a real reason: **SpringRank scores in
   disconnected components are not comparable**, since each is independently centred
   at zero. Refining before connecting would be refining noise.
3. **Refining** — the untested pair closest in current estimated rank. Maximum
   information per question.

Two invariants hold throughout: never repeat a pair, and never pair a task with its
own ancestor (that question has no meaningful answer).

**A newly added task** has no comparisons, so phase 1 catches it automatically; with
only one uncompared task it's matched against the *median-ranked* task and then
bisected into place by phase 3. Nothing special-cases "new".

Simulated against a hidden ground-truth ranking over the real 47-task list: 23
openings covered everything, 22 runoffs collapsed 24 components to 1, then refinement
— reaching Spearman ρ = 0.906 after 95 comparisons, with no repeated or ancestor
pairs. Worth re-running if you change the phase logic.

### The map, and why colour isn't the identity carrier

Urgency on x, importance on y, origin at the mean — an Eisenhower matrix that
emerges from the data instead of being asserted.

The project palette **fails colourblind validation** (pink vs. teal at ΔE 3.7 for
deuteranopia), and this isn't fixable: no categorical palette keeps nine series
separable in a scatter, where every pair can end up adjacent. So colour is a
*secondary* cue only. Identity is carried by up to 18 collision-avoided direct
labels, a hover tooltip with exact scores, and a **Table** toggle listing everything.
The project colours were kept because they're consistent with the rest of the app and
the user asked for that consistency. **If you add a chart here, don't let colour be
the only thing distinguishing two items.**

---

## 6. Multi-machine safety

The folder is meant to live in Dropbox and be used from more than one Mac.

The hazard isn't sync latency — it's that **a browser tab holds the whole document
and writes the whole document back**. A tab left open on a laptop yesterday will, on
the next keystroke, overwrite today's work with yesterday's, silently.

Three guards, all worth preserving:

1. **Optimistic concurrency.** Every PUT sends `X-Base-Updated:` — the `updated`
   value the tab last read. If the file on disk has since moved on, the server
   returns **409** with the current document. The client adopts it, stashes the
   rejected version in `localStorage["todo-rejected"]`, and tells the user. One edit
   is lost instead of a day's work. A PUT with no header is still accepted, so a
   stale client degrades rather than breaks.
2. **Re-sync on focus.** Poll every 15 s, *plus* on `focus` and `visibilitychange` —
   returning to a tab is exactly when a synced-in file is waiting. Polling never
   overwrites unsaved local edits (it bails if `dirty || editingId || notingId`).
3. **Conflicted-copy detection.** `/api/health` scans for Dropbox's
   `… (conflicted copy …)` files; the client shows a red banner naming them.
   Otherwise you'd drift onto a fork with no signal at all.

The rule these enforce: **one machine at a time.** They make violating it visible and
recoverable, not safe. The SSH tunnel in `README.md` avoids the problem entirely.

---

## 7. Smaller decisions, and why

- **`@tonight` is a rolling queue, not a due date.** It's for low-effort junk. Giving
  it `due = today` would turn the pile red tomorrow, which punishes exactly the
  behaviour it's meant to encourage. So it's its own flag, its own view, and its own
  timeline band between Today and Tomorrow, and it never ages into Overdue. A real
  due date that passes still wins.
- **Question marks are plain text.** An earlier build parsed `?` into a "maybe" flag.
  It was removed at the user's request — `? call the bank` and `worth doing?` now
  survive verbatim. Don't re-add magic punctuation.
- **A parent is never dated by its children.** In the timeline, only a task's own
  `due` places it, so a dated subtask appears on its own with a breadcrumb naming its
  parent. Inheritance was explicitly rejected.
- **Tiles use CSS columns, not grid.** Project sizes differ wildly (22 items vs. 2);
  a grid leaves dead space under short cards.
- **Row action buttons are an overlay inside tiles.** They're invisible until hover
  but were still reserving ~130 px of a 309 px row, squeezing text into 110 px.
  Absolute positioning gave the text 271 px back.
- **No `window.confirm()` / `alert()` anywhere in new code.** Browser modals block
  automation tooling. Destructive actions use inline confirmation that names exactly
  what will be deleted ("Delete all 109 importance comparisons?"). Note `prompt()`
  does survive in project rename/create — replace it if you touch that code.
- **Everything destructive is also undoable.** Confirmation *and* `⌘Z`.

---

## 8. Verifying changes

There's no test suite; the app is a single HTML file. What worked well, and caught
several real bugs:

- **Drive it in a real browser.** This found search being view-scoped, markdown links
  with title attributes rendering raw, and the tile-width problem — none visible by
  reading the code.
- **Test pure logic headlessly in Node** by extracting functions from `app.html` with
  a brace-matching grab and stubbing the few globals they need. This caught a
  double-space bug in autocomplete insertion without a browser at all.
- **Check the page parses**: extract the `<script>` and run `node --check`. A syntax
  error otherwise shows up as a silently blank page.
- **Verify maths against closed-form answers**, not plausibility (section 5).

A caveat for future sessions: this machine (`M5BP.local`) may not be the one running
the user's browser. `ERR_CONNECTION_REFUSED` in Chrome while `curl` succeeds locally
means the browser is on a different machine — no amount of extension re-pairing fixes
that, only the SSH tunnel.

---

## 9. Known limitations

- **Whole-document saves.** Fine to a few thousand tasks; past that, move to
  per-entity updates and the concurrency guard needs rethinking.
- **Comparisons reference task ids**, so deleting a task prunes its comparisons
  (`removeTask`). Editing a title keeps them — the identity is the id, not the text.
- **No recurring tasks, no reminders, no attachments.** Never asked for.
- **The comparison graph never forgets.** Old judgments carry equal weight to new
  ones; there's no decay. If priorities shift wholesale, Reset is the intended tool.
- **Autocomplete rendering was verified by logic, not by eye** — position, dark-mode
  contrast, and scrolling with many projects are unconfirmed visually.
