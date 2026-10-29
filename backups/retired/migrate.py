#!/usr/bin/env python3
"""One-time importer: _TODO.md -> data.json

Kept around so you can re-import a markdown list later if you ever want to.
Usage: python3 migrate.py [source.md] [dest.json]
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

PALETTE = [
    "#6366f1", "#0ea5e9", "#10b981", "#f59e0b",
    "#ef4444", "#a855f7", "#14b8a6", "#ec4899", "#84cc16",
]

TASK_RE = re.compile(r"^(?P<indent>[\t ]*)- \[(?P<mark>[ xX])\]\s*(?P<text>.*)$")
HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<name>.*?)\s*$")
DATE_RE = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)\s*$")
DUE_RE = re.compile(r"\s*\(due (\d{4}-\d{2}-\d{2})\)\s*$")


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "project"


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse(md_text):
    projects = []
    tasks = []
    by_slug = {}
    counter = [0]

    def add_project(name):
        name = re.sub(r"^\[\[(.*)\]\]$", r"\1", name.strip())
        slug = slugify(name)
        if slug in by_slug:
            return by_slug[slug]
        pid = "p-" + slug
        projects.append({
            "id": pid,
            "name": name,
            "color": PALETTE[len(projects) % len(PALETTE)],
        })
        by_slug[slug] = pid
        return pid

    current = add_project("Inbox")
    # stack of (indent_width, task_id) for nesting
    stack = []

    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("---"):
            continue

        h = HEADER_RE.match(line)
        if h:
            current = add_project(h.group("name"))
            stack = []
            continue

        m = TASK_RE.match(line)
        if not m:
            continue

        indent = m.group("indent").replace("    ", "\t")
        depth = len(indent.replace(" ", ""))
        text = m.group("text").strip()
        done = m.group("mark").lower() == "x"

        # markers this script's own markdown mirror writes, so a re-import round-trips
        due = None
        m_due = DUE_RE.search(text)
        if m_due:
            due = m_due.group(1)
            text = DUE_RE.sub("", text).strip()
        tonight = bool(re.search(r"\s*@tonight\s*$", text, re.I))
        if tonight:
            text = re.sub(r"\s*@tonight\s*$", "", text, flags=re.I).strip()

        flagged = text.startswith("! ")
        if flagged:
            text = text[2:].strip()

        created = None
        d = DATE_RE.search(text)
        if d:
            created = d.group(1)
            text = DATE_RE.sub("", text).strip()

        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else None

        counter[0] += 1
        tid = f"t{counter[0]:03d}"
        tasks.append({
            "id": tid,
            "title": text,
            "done": done,
            "project": current,
            "parent": parent,
            "flagged": flagged,
            "tonight": tonight,
            "due": due,
            "notes": "",
            "created": created or now()[:10],
            "completed": now()[:10] if done else None,
        })
        stack.append((depth, tid))

    return {"version": 1, "updated": now(), "projects": projects, "tasks": tasks}


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "_TODO.md"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "data.json"
    data = parse(src.read_text(encoding="utf-8"))
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['tasks'])} tasks in {len(data['projects'])} projects -> {dest}")


if __name__ == "__main__":
    main()
