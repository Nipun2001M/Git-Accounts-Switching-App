#!/usr/bin/env python3
"""Switch the GitHub account used by Git and SSH on this Mac."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import core


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghsw",
        description="Switch the GitHub account used by Git, SSH, and the GitHub CLI on this Mac.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Save a GitHub account under a keyword")
    add.add_argument("keyword")
    add.add_argument("--username")
    add.add_argument("--name", help="Name to put on commits")
    add.add_argument("--email", help="Email to put on commits")
    add.add_argument("--ssh-key", help="Path to the private SSH key")
    add.add_argument(
        "--generate-key",
        action="store_true",
        help="Create an ed25519 key when the file does not exist",
    )
    add.add_argument("--json", action="store_true")

    listing = sub.add_parser("list", help="Show saved accounts")
    listing.add_argument("--json", action="store_true")

    use = sub.add_parser("use", help="Make an account active")
    use.add_argument("keyword", nargs="?", help="Keyword. Omit to use the default account")
    use.add_argument("--dry-run", action="store_true", help="Show what would change")
    use.add_argument("--no-check", action="store_true", help="Skip the GitHub SSH check")
    use.add_argument("--no-gh", action="store_true", help="Leave the GitHub CLI login unchanged")
    use.add_argument("--json", action="store_true")

    default = sub.add_parser("default", help="Choose the account used by ghsw use")
    default.add_argument("keyword")
    default.add_argument("--json", action="store_true")

    remove = sub.add_parser("remove", help="Forget an account keyword")
    remove.add_argument("keyword")
    remove.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    remove.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="Show the active Git identity")
    status.add_argument("--json", action="store_true")

    key = sub.add_parser("key", help="Print an account's public SSH key")
    key.add_argument("keyword")
    key.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(getattr(args, "json", False))
    try:
        dispatch(args)
    except core.GhswError as exc:
        emit_error(str(exc), json_mode)
        return 1
    except subprocess.TimeoutExpired:
        emit_error("A Git or GitHub command timed out.", json_mode)
        return 1
    return 0


def dispatch(args: argparse.Namespace) -> None:
    if args.command == "add":
        payload = add_account(args)
        emit(payload, args.json, lambda item: print_added(item))
        return
    if args.command == "list":
        payload = core.list_accounts(core.config_path())
        emit(payload, args.json, print_list)
        return
    if args.command == "use":
        report = core.switch_account(
            core.config_path(),
            core.ssh_config_path(),
            args.keyword,
            dry_run=args.dry_run,
            check=not args.no_check,
            switch_cli=not args.no_gh,
        )
        payload = report.as_dict()
        emit(payload, args.json, lambda item: print_switch(item, args.keyword))
        return
    if args.command == "default":
        payload = core.set_default(core.config_path(), args.keyword)
        emit(payload, args.json, lambda item: print(f"Default account: {item['keyword']}"))
        return
    if args.command == "remove":
        confirm_remove(args)
        payload = core.remove_account(core.config_path(), core.ssh_config_path(), args.keyword)
        emit(payload, args.json, print_removed)
        return
    if args.command == "status":
        payload = core.status(core.config_path(), core.ssh_config_path())
        emit(payload, args.json, print_status)
        return
    if args.command == "key":
        payload = core.public_key_for(core.config_path(), args.keyword)
        emit(payload, args.json, lambda item: print(item["public_key"]))
        return
    raise core.GhswError(f"Unknown command: {args.command}")


def add_account(args: argparse.Namespace) -> dict:
    keyword = args.keyword
    username = args.username
    name = args.name
    email = args.email
    ssh_key = args.ssh_key
    generate_key = args.generate_key
    interactive = sys.stdin.isatty() and not args.json

    if interactive:
        username = username or ask("GitHub username")
        name = name or ask("Commit name")
        email = email or ask("Commit email")
        suggested = str(core.default_ssh_key(core.normalize_keyword(keyword)))
        ssh_key = ssh_key or ask("SSH private key", suggested)
        if not generate_key:
            answer = ask("Generate the SSH key if it is missing? [Y/n]", "Y")
            generate_key = not answer.lower().startswith("n")
    else:
        missing = [
            flag
            for flag, value in (
                ("--username", username),
                ("--name", name),
                ("--email", email),
            )
            if not value
        ]
        if missing:
            raise core.GhswError(f"Missing {' '.join(missing)}.")
        if not ssh_key:
            ssh_key = str(core.default_ssh_key(core.normalize_keyword(keyword)))

    return core.add_account(
        core.config_path(),
        keyword,
        username or "",
        name or "",
        email or "",
        ssh_key or "",
        generate_key,
    )


def confirm_remove(args: argparse.Namespace) -> None:
    if args.yes or args.json or not sys.stdin.isatty():
        if args.yes or args.json:
            return
        raise core.GhswError("Refusing to remove an account without --yes.")
    answer = ask(f"Remove '{args.keyword}' from GitHub Switch? [y/N]", "N")
    if not answer.lower().startswith("y"):
        raise core.GhswError("Left the account in place.")


def ask(label: str, current: str | None = None) -> str:
    shown = f" [{current}]" if current else ""
    entered = input(f"{label}{shown}: ").strip()
    if entered:
        return entered
    return current or ""


def emit(payload: dict, as_json: bool, human) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    human(payload)


def emit_error(message: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        return
    print(f"ghsw: {message}", file=sys.stderr)


def print_added(payload: dict) -> None:
    print(payload["message"])
    if payload.get("public_key"):
        print()
        print(f"Public key ({payload['public_key_path']}):")
        print(payload["public_key"])
        print()
        print(f"Add that key to the GitHub account '{payload['username']}':")
        print("https://github.com/settings/keys")
        print()
        print("Then log that account into GitHub CLI once:")
        print("gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key")


def print_list(payload: dict) -> None:
    accounts = payload["accounts"]
    if not accounts:
        print("No accounts yet. Add one with: ghsw add <keyword>")
        print("Or open GitHub Switch from the Applications folder.")
        return
    headers = ("KEYWORD", "GITHUB", "EMAIL", "FLAGS")
    rows = []
    for account in accounts:
        flags = []
        if account["is_active"]:
            flags.append("active")
        if account["is_default"]:
            flags.append("default")
        rows.append(
            (
                account["keyword"],
                account["username"],
                account["email"],
                ", ".join(flags),
            )
        )
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: tuple[str, str, str, str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    print(format_row(headers))
    for row in rows:
        print(format_row(row))


def print_switch(payload: dict, requested: str | None) -> None:
    if payload["dry_run"]:
        print(f"Would switch to {payload['keyword']}:")
        for action in payload["actions"]:
            print(f"  - {action}")
        return
    store = core.load_store(core.config_path())
    account = store["accounts"].get(payload["keyword"], {})
    print(f"Active account: {payload['keyword']}")
    if account:
        print(f"Git: {account['name']} <{account['email']}>")
        print(f"SSH key: {account['ssh_key']}")
    gh_message = payload.get("gh_message")
    ssh_check = payload.get("ssh_check")
    warnings = payload.get("warnings") or []
    if gh_message and gh_message not in warnings:
        print(gh_message)
    if ssh_check and ssh_check not in warnings:
        print(ssh_check)
    for warning in warnings:
        print(f"Warning: {warning}")
    if requested is None and payload["keyword"]:
        return


def print_removed(payload: dict) -> None:
    print(f"Removed '{payload['removed']}'.")
    for note in payload["notes"]:
        print(note)


def print_status(payload: dict) -> None:
    print(f"Active keyword: {payload['active_keyword'] or 'none'}")
    print(f"Default keyword: {payload['default_keyword'] or 'none'}")
    print(f"Git name: {payload['git_name'] or 'not set'}")
    print(f"Git email: {payload['git_email'] or 'not set'}")
    print(f"SSH key: {payload['ssh_key'] or 'not set'}")
    if payload.get("gh_user") and payload.get("gh_invalid"):
        print(f"GitHub CLI: {payload['gh_user']} (saved token is invalid)")
    else:
        print(f"GitHub CLI: {payload['gh_user'] or 'not logged in'}")
    if payload.get("gh_error"):
        print(f"GitHub CLI note: {payload['gh_error']}")
    if payload["active_keyword"]:
        print(f"Matches saved account: {'yes' if payload['in_sync'] else 'no'}")


if __name__ == "__main__":
    sys.exit(main())
