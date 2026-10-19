# GitHub token for issues

This guide is for when it is needed. Until then vibeissue is installed and the repo `nessocrm/nessocrm` is already named in `tracker/github_repo`. Only the token is missing.

The token is not pasted into chat, not put in an issue, and not committed.

## Create the token

1. On GitHub, top right: **Settings**.
2. At the bottom of the side menu: **Developer settings**.
3. **Personal access tokens**, then **Fine-grained tokens**, then **Generate new token**.
4. Repository access: only `nessocrm/nessocrm`.
5. Permissions, **Issues**: Read and write. No other permission.
6. Generate and copy the value. GitHub shows it once. It has the form `github_pat_...`.

## Where to put it

Either path is enough. The project file takes precedence over the Windows variable.

### Local file

Open `.secrets/github_token` in the repo root and write the token on one line, without quotes. The `.secrets/` folder is already in `.gitignore`.

### Windows user variable

1. Search for "Environment variables" and open the user ones.
2. New variable. Name: `GITHUB_TOKEN`. Value: the token.
3. Confirm every window.
4. Close and reopen Cursor. A terminal that is already open does not see the new variable.

## Check

From this folder, in a new terminal:

```
python scripts/github_issue.py list
```

A list, even an empty one, means the connection works. Then, once:

```
python scripts/github_issue.py labels --apply
```

That creates the labels on the repo. From then on, a chat request such as "open an issue for…" uses these issues.
