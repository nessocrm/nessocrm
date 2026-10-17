# Copyright (c) 2024-2026 Antonio Trento — https://antoniotrento.net
# All rights reserved. Use subject to the terms in the LICENSE file.

#!/usr/bin/env python3
"""GitHub Issues CLI for vibeissue — stdlib only (urllib), no gh CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agent_feedback import after_success, cmd_feedback  # noqa: E402
LABELS_FILE = ROOT / "tracker" / "labels.yml"
MANIFEST_FILE = ROOT / "tracker" / "import-manifest.json"
REPO_FILE = ROOT / "tracker" / "github_repo"
TOKEN_FILE = ROOT / ".secrets" / "github_token"
ENV_FILE = ROOT / ".env"
API_BASE = "https://api.github.com"
DEFAULT_REPO = "vibeissue/vibeissue"
_ssl_ready = False


def ensure_ssl() -> None:
    """Trust store Windows (optional truststore package)."""
    global _ssl_ready
    if _ssl_ready:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass
    _ssl_ready = True


def _value_from_dotenv(path: Path, key_name: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        if key.strip() == key_name:
            return val.strip().strip('"').strip("'")
    return ""


def _slug_from_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def repo_slug() -> str:
    """Repo owner/name: .env → GITHUB_REPO env → tracker/github_repo."""
    sources = (
        _value_from_dotenv(ENV_FILE, "GITHUB_REPO"),
        os.environ.get("GITHUB_REPO", "").strip(),
        _slug_from_file(REPO_FILE),
    )
    for slug in sources:
        if slug and "/" in slug:
            return slug
    return DEFAULT_REPO


def require_repo() -> str:
    slug = repo_slug()
    if not slug:
        print("ERRORE: repository GitHub non configurato.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Una sola configurazione (in ordine di lettura):", file=sys.stderr)
        print(f"  1. {ENV_FILE.relative_to(ROOT)}  →  GITHUB_REPO=owner/repo", file=sys.stderr)
        print("  2. Variabile GITHUB_REPO (sessione)", file=sys.stderr)
        print(f"  3. {REPO_FILE.relative_to(ROOT)}  →  owner/repo su una riga", file=sys.stderr)
        print("", file=sys.stderr)
        print("Oppure: python scripts/github_issue.py --repo owner/repo <comando>", file=sys.stderr)
        sys.exit(1)
    return slug


def _token_from_windows_user() -> str:
    """Legge GITHUB_TOKEN dalle variabili utente Windows (funziona anche in shell agent)."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, "GITHUB_TOKEN")
            return str(value).strip()
    except OSError:
        return ""


def _token_from_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def resolve_token() -> str:
    """Token GitHub: .env → env processo → .secrets/github_token → Windows User."""
    sources = (
        _value_from_dotenv(ENV_FILE, "GITHUB_TOKEN"),
        os.environ.get("GITHUB_TOKEN", "").strip(),
        _token_from_file(TOKEN_FILE),
        _token_from_windows_user(),
    )
    for token in sources:
        if token:
            return token
    return ""


def get_token() -> str:
    token = resolve_token()
    if not token:
        print("ERRORE: token GitHub non trovato.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Una sola configurazione (in ordine di lettura):", file=sys.stderr)
        print(f"  1. {ENV_FILE.relative_to(ROOT)}  →  GITHUB_TOKEN=...", file=sys.stderr)
        print("  2. Variabile GITHUB_TOKEN (env di sessione)", file=sys.stderr)
        print(f"  3. {TOKEN_FILE.relative_to(ROOT)}  →  token su una riga", file=sys.stderr)
        print("  4. Windows: variabile utente da registry (fallback)", file=sys.stderr)
        print("", file=sys.stderr)
        print("Il file in .secrets/ è gitignored — sicuro per uso locale.", file=sys.stderr)
        sys.exit(1)
    return token


def api_request(
    method: str,
    path: str,
    *,
    token: str,
    data: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    url = f"{API_BASE}{path}"
    body = None
    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "User-Agent": "vibeissue",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    ensure_ssl()
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"ERRORE HTTP {exc.code} {method} {path}", file=sys.stderr)
        print(detail, file=sys.stderr)
        sys.exit(1)


def parse_labels_yaml(path: Path) -> list[dict[str, str]]:
    """Minimal YAML parser for tracker/labels.yml (labels: - name/color/description)."""
    if not path.is_file():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    labels: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "labels:":
            continue
        if stripped.startswith("- "):
            if current:
                labels.append(current)
            current = {}
            rest = stripped[2:].strip()
            if rest:
                key, _, val = rest.partition(":")
                current[key.strip()] = val.strip().strip('"').strip("'")
            continue
        if current is not None and ":" in stripped:
            key, _, val = stripped.partition(":")
            current[key.strip()] = val.strip().strip('"').strip("'")

    if current:
        labels.append(current)

    for item in labels:
        if "name" not in item:
            print(f"ERRORE: voce label senza name in {path}", file=sys.stderr)
            sys.exit(1)
    return labels


def legacy_id_from_body(body: str) -> str | None:
    match = re.search(r"^\*\*Legacy ID:\*\*\s*`([^`]+)`", body, re.MULTILINE)
    return match.group(1) if match else None


def list_issues(token: str, *, state: str = "open", limit: int = 30) -> None:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    issues = api_request(
        "GET",
        f"/repos/{owner}/{name}/issues?state={state}&per_page={limit}&sort=updated",
        token=token,
    )
    if not isinstance(issues, list):
        print("Nessuna issue trovata.")
        return
    for issue in issues:
        if "pull_request" in issue:
            continue
        num = issue["number"]
        title = issue["title"]
        istate = issue["state"]
        labels = ", ".join(lb["name"] for lb in issue.get("labels", []))
        print(f"#{num} [{istate}] {title}")
        if labels:
            print(f"    labels: {labels}")


def create_issue(
    token: str,
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return api_request("POST", f"/repos/{owner}/{name}/issues", token=token, data=payload)


def cmd_create(args: argparse.Namespace, token: str) -> None:
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    labels = [s.strip() for s in args.labels.split(",") if s.strip()] if args.labels else None
    issue = create_issue(token, title=args.title, body=body, labels=labels)
    print(f"Creato #{issue['number']}: {issue['html_url']}")


def parse_label_list(raw: str | None) -> list[str] | None:
    """Comma-separated labels → list, or None if flag omitted."""
    if raw is None:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_edit(args: argparse.Namespace, token: str) -> None:
    """PATCH title / body / labels on an existing issue (labels replaces the full set)."""
    payload: dict[str, Any] = {}
    changed: list[str] = []

    if args.title is not None:
        title = args.title.strip()
        if not title:
            print("ERRORE: --title non può essere vuoto.", file=sys.stderr)
            sys.exit(1)
        payload["title"] = title
        changed.append("title")

    body: str | None = None
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif args.body is not None:
        body = args.body
    if body is not None:
        payload["body"] = body
        changed.append("body")

    labels = parse_label_list(args.labels)
    if labels is not None:
        payload["labels"] = labels
        changed.append("labels")

    if not payload:
        print(
            "ERRORE: specifica almeno uno tra --title, --body / --body-file, --labels.",
            file=sys.stderr,
        )
        sys.exit(1)

    repo = require_repo()
    owner, name = repo.split("/", 1)
    issue = api_request(
        "PATCH",
        f"/repos/{owner}/{name}/issues/{args.number}",
        token=token,
        data=payload,
    )
    label_names = ", ".join(lb["name"] for lb in issue.get("labels", [])) or "(nessuna)"
    print(f"Aggiornata #{issue['number']}: {issue['html_url']}")
    print(f"  campi: {', '.join(changed)}")
    print(f"  title: {issue['title']}")
    print(f"  labels: {label_names}")


def cmd_comment(args: argparse.Namespace, token: str) -> None:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    api_request(
        "POST",
        f"/repos/{owner}/{name}/issues/{args.number}/comments",
        token=token,
        data={"body": body},
    )
    print(f"Commento aggiunto a #{args.number}")


def cmd_close(args: argparse.Namespace, token: str) -> None:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    if getattr(args, "reason", None):
        api_request(
            "POST",
            f"/repos/{owner}/{name}/issues/{args.number}/comments",
            token=token,
            data={"body": args.reason},
        )
    api_request(
        "PATCH",
        f"/repos/{owner}/{name}/issues/{args.number}",
        token=token,
        data={"state": "closed"},
    )
    print(f"Chiusa #{args.number}")


def cmd_close_batch(args: argparse.Namespace, token: str) -> None:
    reason = args.reason or "Chiusa: ridondante o backlog non prioritario."
    for number in args.numbers:
        close_args = argparse.Namespace(number=number, reason=reason)
        cmd_close(close_args, token)
    print(f"\nChiuse {len(args.numbers)} issue.")


def fetch_repo_labels(token: str) -> dict[str, dict[str, Any]]:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    existing = api_request("GET", f"/repos/{owner}/{name}/labels?per_page=100", token=token)
    if not isinstance(existing, list):
        return {}
    return {item["name"]: item for item in existing}


def cmd_labels(args: argparse.Namespace, token: str) -> None:
    desired = parse_labels_yaml(LABELS_FILE)
    if not args.apply:
        print(f"Labels in {LABELS_FILE} ({len(desired)}):")
        for item in desired:
            desc = item.get("description", "")
            color = item.get("color", "")
            print(f"  - {item['name']} #{color}  {desc}")
        print("\nUsa --apply per crearle/aggiornarle su GitHub.")
        return

    repo = require_repo()
    owner, name = repo.split("/", 1)
    existing = fetch_repo_labels(token)
    created = updated = 0
    for item in desired:
        name_label = item["name"]
        payload = {
            "name": name_label,
            "color": item.get("color", "ededed").lstrip("#"),
            "description": item.get("description", ""),
        }
        if name_label in existing:
            api_request(
                "PATCH",
                f"/repos/{owner}/{name}/labels/{quote(name_label, safe='')}",
                token=token,
                data=payload,
            )
            updated += 1
        else:
            api_request("POST", f"/repos/{owner}/{name}/labels", token=token, data=payload)
            created += 1
    print(f"Labels: {created} create, {updated} aggiornate su {require_repo()}")


def search_issue_by_legacy_id(token: str, legacy_id: str) -> dict[str, Any] | None:
    repo = require_repo()
    owner, name = repo.split("/", 1)
    query = quote(f'repo:{owner}/{name} is:issue "{legacy_id}" in:body', safe="")
    result = api_request("GET", f"/search/issues?q={query}&per_page=5", token=token)
    if not isinstance(result, dict):
        return None
    for item in result.get("items", []):
        if legacy_id in item.get("body", ""):
            return item
    return None


def cmd_import(args: argparse.Namespace, token: str) -> None:
    manifest_path = Path(args.manifest) if args.manifest else MANIFEST_FILE
    if not manifest_path.is_file():
        print(f"ERRORE: manifest non trovato: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        print("ERRORE: import-manifest.json deve essere un array JSON.", file=sys.stderr)
        sys.exit(1)

    dry_run = not args.apply
    created = skipped = 0

    for entry in items:
        title = entry["title"]
        body = entry["body"]
        labels = entry.get("labels", [])
        legacy_id = legacy_id_from_body(body) or entry.get("legacy_id")

        if legacy_id:
            found = search_issue_by_legacy_id(token, legacy_id)
            if found:
                print(f"SALTATA (esiste #{found['number']}): {legacy_id} — {title}")
                skipped += 1
                continue

        if dry_run:
            print(f"[dry-run] CREEREBBE: {title}")
            print(f"          labels: {', '.join(labels)}")
            if legacy_id:
                print(f"          legacy: {legacy_id}")
            created += 1
            continue

        issue = create_issue(token, title=title, body=body, labels=labels)
        print(f"CREATA #{issue['number']}: {title}")
        print(f"         {issue['html_url']}")
        created += 1

    action = "simulati" if dry_run else "creati"
    print(f"\nImport: {created} {action}, {skipped} saltati (duplicati).")
    if dry_run:
        print("Usa --apply per creare le issue su GitHub.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub Issues CLI (stdlib, GITHUB_TOKEN + GITHUB_REPO richiesti).",
    )
    parser.add_argument(
        "--repo",
        help="Override repo owner/name (default: GITHUB_REPO env, .env, tracker/github_repo, or vibeissue/vibeissue)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Elenca issue aperte (default) o chiuse")
    p_list.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p_list.add_argument("--limit", type=int, default=30)

    p_create = sub.add_parser("create", help="Crea una nuova issue")
    p_create.add_argument("title")
    p_create.add_argument("--body", default="")
    p_create.add_argument("--body-file")
    p_create.add_argument("--labels", help="Comma-separated label names")

    p_edit = sub.add_parser(
        "edit",
        help="Modifica titolo, corpo e/o label di un'issue esistente",
    )
    p_edit.add_argument("number", type=int, help="Numero issue")
    p_edit.add_argument("--title", default=None, help="Nuovo titolo")
    p_edit.add_argument(
        "--body",
        default=None,
        help="Nuovo corpo (sostituisce interamente il body)",
    )
    p_edit.add_argument("--body-file", help="Leggi il nuovo corpo da file")
    p_edit.add_argument(
        "--labels",
        default=None,
        help="Sostituisce TUTTE le label (lista comma-separated; stringa vuota = nessuna)",
    )

    p_comment = sub.add_parser("comment", help="Aggiunge un commento a un'issue")
    p_comment.add_argument("number", type=int)
    p_comment.add_argument("--body", default="")
    p_comment.add_argument("--body-file")

    p_close = sub.add_parser("close", help="Chiude un'issue")
    p_close.add_argument("number", type=int)
    p_close.add_argument("--reason", help="Commento prima della chiusura")

    p_close_batch = sub.add_parser("close-batch", help="Chiude più issue (numeri separati da spazio)")
    p_close_batch.add_argument("numbers", type=int, nargs="+")
    p_close_batch.add_argument(
        "--reason",
        default="Chiusa: sub-task duplicata, backlog bassa priorità o import di test.",
    )

    p_labels = sub.add_parser("labels", help="Mostra o applica label da tracker/labels.yml")
    p_labels.add_argument("--apply", action="store_true", help="Crea/aggiorna label su GitHub")

    p_import = sub.add_parser("import", help="Importa issue da tracker/import-manifest.json")
    p_import.add_argument("--manifest", help="Path alternativo al manifest JSON")
    p_import.add_argument("--dry-run", action="store_true", help="Solo anteprima (default)")
    p_import.add_argument("--apply", action="store_true", help="Crea le issue su GitHub")

    p_feedback = sub.add_parser(
        "feedback",
        help="Optional maintainer feedback or email signup (not GitHub Issues)",
    )
    p_feedback.add_argument("message", nargs="?", default="")
    p_feedback.add_argument("--email", default="")
    p_feedback.add_argument(
        "--subscribe",
        action="store_true",
        help="Email signup only (requires --email)",
    )
    p_feedback.add_argument(
        "--decline",
        action="store_true",
        help="User declined; silence prompts for 90 days",
    )
    p_feedback.add_argument("--locale", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.repo:
        os.environ["GITHUB_REPO"] = args.repo

    if args.command == "feedback":
        return cmd_feedback(args)

    token = get_token()

    if args.command == "list":
        list_issues(token, state=args.state, limit=args.limit)
    elif args.command == "create":
        cmd_create(args, token)
    elif args.command == "edit":
        cmd_edit(args, token)
    elif args.command == "comment":
        cmd_comment(args, token)
    elif args.command == "close":
        cmd_close(args, token)
    elif args.command == "close-batch":
        cmd_close_batch(args, token)
    elif args.command == "labels":
        cmd_labels(args, token)
    elif args.command == "import":
        if not args.apply:
            args.dry_run = True
        cmd_import(args, token)
    else:
        parser.print_help()
        return 1

    after_success(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
