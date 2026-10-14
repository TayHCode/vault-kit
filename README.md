# vault-kit

Build a private Obsidian vault from your Claude Code and Codex conversations and public GitHub repositories. Python 3.9 or newer is all you need; there are no packages to install.

## Quickstart

Clone this repository, then run this one command. It asks for your GitHub username (optional) and where to create the vault. You can instead pass `--transcripts FOLDER` to read a folder of JSONL transcripts.

    python3 vault_kit.py

By default it looks in `~/.claude/projects` and `~/.codex/sessions`. Public repositories are fetched by username without login; lookup failure or no network simply skips them.

For an offline example from the repository root:

    python3 vault_kit.py --username '' --transcripts examples/transcripts --output ./QuickstartVault

To skip every prompt, pass all three options: `--username NAME` (use `''` to skip GitHub), `--transcripts FOLDER` and `--output FOLDER`.

It creates `START-HERE.md`, an index, a project note for each repository or detected project, and linked notes for each transcript session. Transcript imports keep conversation text and skip tool outputs.

Search the vault from a terminal:

    python3 vault_kit.py search TERM --vault ./QuickstartVault

Existing notes are preserved; when a generated note's filename is already in use, vault-kit writes its copy with `(Vault Kit)` in the name and refreshes only notes marked as vault-kit managed. Links always point at the note vault-kit wrote, and running it again updates sessions whose transcripts have grown.

## Privacy

The vault contains your own conversations. Keep it private like the transcripts it comes from. The script writes only inside the output folder you choose.

## Limitations

Transcript formats can change, and public GitHub lookup requires an internet connection. Only public repositories are found; private repositories are not accessed.
