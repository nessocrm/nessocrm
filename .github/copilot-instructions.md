# GitHub Copilot — workspace instructions

When the user reports a bug, requests a task, or asks to track work:

1. Read **[AGENTS.md](../AGENTS.md)** at the repository root. Every product change updates `docs/` in the same change, and `py -3 -m mkdocs build --strict` must pass.
2. Run **`python scripts/github_issue.py`** from the repo root — do not ask the user to paste commands if `GITHUB_TOKEN` is configured.
3. Use GitHub Issues as the **source of truth** for open/closed work.

Platform guide: [vibeissue.github.io/docs/platforms/overview/](https://vibeissue.github.io/docs/platforms/overview/)
