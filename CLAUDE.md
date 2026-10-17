# Claude Code — Vibeissue

Claude Code (VS Code extension, terminal, or desktop) can use **vibeissue** like any other agent: run the Python CLI and keep GitHub Issues as the source of truth.

## What to read

1. **[AGENTS.md](AGENTS.md)** — canonical rules (commands, labels, workflow, documentation). Every product change updates `docs/` in the same change. The site is MkDocs: `py -3 -m mkdocs build --strict` must pass.
2. **[Documentation](https://vibeissue.github.io/docs/)** — MkDocs (EN/IT), including [platforms](https://vibeissue.github.io/docs/platforms/overview/)

## Claude Code setup

1. Adopt or clone vibeissue into your project (`python scripts/adopt.py --target ../my-repo --repo myorg/my-app`).
2. Keep **`CLAUDE.md`** (this file) and **`AGENTS.md`** at the repository root — Claude Code loads them automatically.
3. Configure `GITHUB_TOKEN` and `tracker/github_repo` — see [token guide](https://vibeissue.github.io/docs/getting-started/token/) (Windows, macOS, Linux).
4. Ask in chat: *"Open a GitHub issue for the Safari login bug"* — Claude should run `python scripts/github_issue.py create ...` directly.

## VS Code + Claude Code

- Open the **project folder** (repo root), not a parent directory, so paths like `scripts/github_issue.py` resolve correctly.
- Use the integrated terminal; restart the IDE after setting `GITHUB_TOKEN` in your shell profile or system environment.
- On **Windows**, the CLI can also read user env vars from the registry if the IDE shell does not inherit them.
- If Claude asks you to run commands manually, remind it to follow **AGENTS.md**: execute the script when the token is configured.

## Optional: project memory

You can add a short note in Claude project settings:

> For bugs and tasks, use `python scripts/github_issue.py` per AGENTS.md. GitHub Issues is the source of truth.

## Not Claude-specific

The CLI, labels, templates, and token handling are **identical** across platforms. Only the instruction file name changes (Cursor uses `.cursor/rules/`, Copilot uses `.github/copilot-instructions.md`, etc.).
