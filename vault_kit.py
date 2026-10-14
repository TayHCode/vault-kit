#!/usr/bin/env python3
"""Build a small Obsidian vault from local Claude Code and Codex conversations."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"


def conversation(record):
    """Return text from a known user/assistant message, excluding tool outputs."""
    kind = record.get("type")
    message = record.get("message")
    if kind == "response_item":
        message = record.get("payload", {})
        if message.get("type") != "message":
            return None
    elif kind == "event_msg":
        event = record.get("payload", {})
        if event.get("type") not in {"user_message", "agent_message"}:
            return None
        return event.get("message") if isinstance(event.get("message"), str) else None
    elif kind not in {"user", "assistant"}:
        return None
    if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"] for block in content
            if isinstance(block, dict)
            and block.get("type") in {"text", "input_text", "output_text"}
            and isinstance(block.get("text"), str)
        )
    return None


def transcript_info(path):
    lines, dates, project, named = [], [], path.parent.name, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        cwd = record.get("cwd") or (payload.get("cwd", "") if isinstance(payload, dict) else "")
        if cwd and not named:
            project, named = Path(cwd).name or project, True
        stamp = record.get("timestamp")
        if stamp:
            dates.append(str(stamp)[:10])
        text = conversation(record)
        if text and text.strip():
            lines.append(text.strip())
    if not lines:
        return None
    day = next((d for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)), "undated")
    return project, day, "\n\n".join(lines)


def github_repos(username):
    if not username:
        return []
    url = f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated"
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "vault-kit"})
    try:
        with urlopen(request, timeout=4) as response:
            repos = json.load(response)
        if not isinstance(repos, list):
            return []
        return [repo for repo in repos if isinstance(repo, dict) and repo.get("name")]
    except (OSError, URLError, ValueError) as error:
        print(f"GitHub lookup skipped: {error}", file=sys.stderr)
        return []


_NOTE_MARKER = "vault-kit-managed: true"


def _is_managed_note(path):
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return _NOTE_MARKER in path.read_text(encoding="utf-8").splitlines()[:3]
    except (OSError, UnicodeError):
        return False


def note_target(root, relative):
    base = root.resolve()
    target = root / relative
    if not target.is_symlink():
        resolved = target.resolve()
        if resolved != base and base not in resolved.parents:
            raise ValueError("A note path escaped the chosen vault folder")
    if target.exists() or target.is_symlink():
        if not _is_managed_note(target):
            original = target
            number = 1
            while (target.exists() or target.is_symlink()) and not _is_managed_note(target):
                suffix = " (Vault Kit)" if number == 1 else f" (Vault Kit {number})"
                target = original.with_name(f"{original.stem}{suffix}{original.suffix}")
                number += 1
    resolved = target.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("A note path escaped the chosen vault folder")
    return target


def write_note(root, relative, text):
    target = note_target(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\n{_NOTE_MARKER}\n---\n\n{text.rstrip()}\n", encoding="utf-8")
    return target.relative_to(root).as_posix()


def link(relative):
    return f"[[{relative.removesuffix('.md')}]]"


def build(transcript_dir, output, username=""):
    files = sorted(Path(transcript_dir).expanduser().rglob("*.jsonl"))
    build_from_files(files, output, username)


def main():
    if sys.argv[1:2] == ["search"]:
        finder = argparse.ArgumentParser(prog="vault_kit.py search", description="Search the notes in a vault.")
        finder.add_argument("term")
        finder.add_argument("--vault", required=True, help="Vault folder to search")
        args = finder.parse_args(sys.argv[2:])
        if not Path(args.vault).expanduser().is_dir():
            finder.error("vault folder not found")
        sys.exit(0 if search(args.vault, args.term) else 1)
    parser = argparse.ArgumentParser(description="Build an Obsidian vault from local Claude Code and Codex transcripts.")
    parser.add_argument("--username", help="GitHub username for a public repository lookup")
    parser.add_argument("--transcripts", help="Transcript folder (default: standard Claude and Codex folders)")
    parser.add_argument("--output", help="Vault folder (asked when omitted)")
    args = parser.parse_args()
    username = args.username if args.username is not None else input("GitHub username (optional): ").strip()
    output = args.output or input("Folder for your Obsidian vault: ").strip()
    if not output:
        parser.error("choose an output folder")
    if args.transcripts:
        source = Path(args.transcripts).expanduser()
    else:
        # Look in each tool's standard folder without copying or modifying it.
        roots = [Path.home() / ".claude" / "projects", Path.home() / ".codex" / "sessions"]
        files = [p for folder in roots if folder.is_dir() for p in folder.rglob("*.jsonl")]
        build_from_files(files, output, username)
        return
    build(source, output, username)


def build_from_files(files, output, username):
    # Reuse the same importer for Claude and Codex files without staging copies.
    root = Path(output).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    projects, sessions = {}, []
    for path in sorted(files):
        info = transcript_info(path)
        if info:
            project, day, text = info
            projects.setdefault(project, [])
            key = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]
            sessions.append((project, day, f"Sessions/{day}-{slug(project)}-{key}.md", text))
    _write_vault(root, projects, sessions, github_repos(username))
    print(f"Built vault at {root} ({len(projects)} projects, {len(sessions)} sessions)")


def _planned(root, relative):
    return note_target(root, relative).relative_to(root).as_posix()


def _write_vault(root, projects, sessions, repos):
    for repo in repos:
        projects.setdefault(repo["name"], [])
    names = sorted(projects, key=str.casefold)
    session_paths = {note: _planned(root, note) for _, _, note, _ in sessions}
    project_paths = {name: _planned(root, f"Projects/{slug(name)}.md") for name in names}
    index_path = _planned(root, "Index.md")
    start_path = _planned(root, "START-HERE.md")
    for project, day, note, text in sessions:
        write_note(root, session_paths[note], f"# {project} — {day}\n\nProject: {link(project_paths[project])}\n\n{text}")
    for name in names:
        repo = next((r for r in repos if r["name"] == name), None)
        body = f"# {name}\n\n"
        if repo:
            body += f"GitHub: [{repo['html_url']}]({repo['html_url']})\n\n{repo.get('description') or ''}\n\n"
        links = [f"- {link(session_paths[note])} ({day})" for project, day, note, _ in sessions if project == name]
        body += "## Sessions\n\n" + ("\n".join(links) if links else "No local sessions found.")
        write_note(root, project_paths[name], body)
    write_note(root, index_path, "# Vault index\n\n## Projects\n\n" + "\n".join(f"- {link(project_paths[name])}" for name in names))
    write_note(root, start_path, (
        f"# Start here\n\nOpen {link(index_path)} to browse projects and sessions.\n\n"
        "Each project note lists its conversation sessions; each session note holds the conversation text "
        "(tool outputs are not imported).\n\n"
        "Search the vault from a terminal:\n\n"
        "    python3 vault_kit.py search TERM --vault DIR\n"
    ))


def search(vault, term):
    root = Path(vault).expanduser()
    needle, found = term.casefold(), 0
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            if needle in line.casefold():
                print(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}")
                found += 1
    return found


if __name__ == "__main__":
    main()
