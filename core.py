"""Local GitHub account switching for Git, SSH, and the GitHub CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MARKER_BEGIN = "# >>> ghsw >>>"
MARKER_END = "# <<< ghsw <<<"
KEYWORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GH_LOGIN_LINE = re.compile(
    r"(?:Logged in to|Failed to log in to) github\.com account (\S+)"
)

DEFAULT_CONFIG = Path.home() / ".config" / "ghsw" / "accounts.json"
DEFAULT_SSH_CONFIG = Path.home() / ".ssh" / "config"


class GhswError(Exception):
    """A problem the user can fix from the command or the app."""


@dataclass
class SSHCheck:
    ok: bool
    message: str
    username: str | None = None


@dataclass
class SwitchReport:
    ok: bool
    keyword: str
    dry_run: bool
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ssh_check: str | None = None
    gh_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "keyword": self.keyword,
            "dry_run": self.dry_run,
            "actions": self.actions,
            "warnings": self.warnings,
            "ssh_check": self.ssh_check,
            "gh_message": self.gh_message,
        }


GhFunc = Callable[[str, dict[str, str] | None], tuple[bool, str]]
SshFunc = Callable[[dict[str, str] | None, Path], SSHCheck]


def config_path() -> Path:
    override = os.environ.get("GHSW_CONFIG")
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG


def ssh_config_path() -> Path:
    override = os.environ.get("GHSW_SSH_CONFIG")
    if override:
        return Path(override).expanduser()
    return DEFAULT_SSH_CONFIG


def default_ssh_key(keyword: str) -> Path:
    return Path.home() / ".ssh" / f"id_ed25519_{keyword}"


def empty_store() -> dict[str, Any]:
    return {"version": 1, "default": None, "active": None, "accounts": {}}


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_store()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise GhswError(f"Account file is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise GhswError(f"Account file has an unexpected shape: {path}")
    data.setdefault("version", 1)
    data.setdefault("default", None)
    data.setdefault("active", None)
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        data["accounts"] = {}
    return data


def save_store(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(path, json.dumps(data, indent=2) + "\n", mode=0o600)


def normalize_keyword(keyword: str) -> str:
    cleaned = keyword.strip().lower()
    if not KEYWORD_RE.match(cleaned):
        raise GhswError(
            "Keyword must start with a letter and use only letters, numbers, hyphens, or underscores."
        )
    return cleaned


def validate_username(username: str) -> str:
    cleaned = username.strip()
    if not USERNAME_RE.match(cleaned):
        raise GhswError("Enter the GitHub username for this account.")
    return cleaned


def validate_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise GhswError("Enter the name that should appear on commits.")
    return cleaned


def validate_email(email: str) -> str:
    cleaned = email.strip()
    if not EMAIL_RE.match(cleaned):
        raise GhswError("Enter the email that should appear on commits.")
    return cleaned


def add_account(
    store_path: Path,
    keyword: str,
    username: str,
    name: str,
    email: str,
    ssh_key: str | Path,
    generate_key: bool,
) -> dict[str, Any]:
    keyword = normalize_keyword(keyword)
    username = validate_username(username)
    name = validate_name(name)
    email = validate_email(email)
    key_path = Path(ssh_key).expanduser()
    if not str(key_path):
        raise GhswError("Enter a path for the SSH private key.")

    store = load_store(store_path)
    if keyword in store["accounts"]:
        raise GhswError(
            f"Account '{keyword}' already exists. Remove it first if you want to replace it."
        )

    created = False
    if key_path.exists():
        reused = True
    elif generate_key:
        generate_ssh_key(key_path, email)
        created = True
        reused = False
    else:
        raise GhswError(
            f"SSH key not found at {key_path}. Pass --generate-key to create one."
        )

    store["accounts"][keyword] = {
        "username": username,
        "name": name,
        "email": email,
        "ssh_key": str(key_path),
    }
    save_store(store_path, store)
    public_key = read_public_key(key_path)
    public_path = public_key_path(key_path)
    if created:
        message = f"Added '{keyword}' and created a new SSH key."
    elif reused:
        message = f"Added '{keyword}' using the existing SSH key."
    else:
        message = f"Added '{keyword}'."
    return {
        "ok": True,
        "keyword": keyword,
        "username": username,
        "name": name,
        "email": email,
        "ssh_key": str(key_path),
        "public_key": public_key,
        "public_key_path": str(public_path) if public_path.exists() else None,
        "message": message,
    }


def generate_ssh_key(path: Path, comment: str) -> None:
    if path.exists():
        raise GhswError(f"SSH key already exists: {path}")
    directory = path.parent
    created_dir = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created_dir:
        os.chmod(directory, 0o700)
    result = run_command(
        ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(path), "-C", comment, "-N", ""],
        timeout=20,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GhswError(detail or "ssh-keygen failed.")
    os.chmod(path, 0o600)


def public_key_path(private_key: Path) -> Path:
    return private_key.with_name(private_key.name + ".pub")


def read_public_key(private_key: Path) -> str | None:
    path = public_key_path(private_key)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def public_key_for(store_path: Path, keyword: str) -> dict[str, Any]:
    keyword = normalize_keyword(keyword)
    store = load_store(store_path)
    account = store["accounts"].get(keyword)
    if not account:
        raise GhswError(f"No account named '{keyword}'.")
    key_path = Path(account["ssh_key"])
    public_key = read_public_key(key_path)
    if not public_key:
        raise GhswError(f"No public key file next to {key_path}.")
    return {
        "ok": True,
        "keyword": keyword,
        "username": account["username"],
        "public_key": public_key,
        "public_key_path": str(public_key_path(key_path)),
    }


def list_accounts(store_path: Path) -> dict[str, Any]:
    store = load_store(store_path)
    rows = []
    for keyword in sorted(store["accounts"]):
        account = store["accounts"][keyword]
        rows.append(
            {
                "keyword": keyword,
                "username": account["username"],
                "name": account["name"],
                "email": account["email"],
                "ssh_key": account["ssh_key"],
                "is_default": store.get("default") == keyword,
                "is_active": store.get("active") == keyword,
            }
        )
    return {
        "default": store.get("default"),
        "active": store.get("active"),
        "accounts": rows,
    }


def set_default(store_path: Path, keyword: str) -> dict[str, Any]:
    keyword = normalize_keyword(keyword)
    store = load_store(store_path)
    if keyword not in store["accounts"]:
        raise GhswError(f"No account named '{keyword}'.")
    store["default"] = keyword
    save_store(store_path, store)
    return {"ok": True, "keyword": keyword, "default": keyword}


def remove_account(
    store_path: Path,
    ssh_config: Path,
    keyword: str,
    env: dict[str, str] | None = None,
    gh_func: GhFunc | None = None,
    ssh_func: SshFunc | None = None,
    switch_cli: bool = True,
) -> dict[str, Any]:
    keyword = normalize_keyword(keyword)
    store = load_store(store_path)
    if keyword not in store["accounts"]:
        raise GhswError(f"No account named '{keyword}'.")

    was_active = store.get("active") == keyword
    was_default = store.get("default") == keyword
    fallback = store.get("default")
    if fallback == keyword:
        fallback = None

    notes: list[str] = []
    if was_active and fallback:
        switch_account(
            store_path,
            ssh_config,
            fallback,
            dry_run=False,
            check=False,
            switch_cli=switch_cli,
            env=env,
            gh_func=gh_func,
            ssh_func=ssh_func,
        )
        notes.append(f"Active account is now '{fallback}'.")
        store = load_store(store_path)

    del store["accounts"][keyword]
    if was_default:
        store["default"] = None
        notes.append("Cleared the default account.")
    if was_active and not fallback:
        store["active"] = None
        remove_managed_ssh_block(ssh_config)
        notes.append(
            "Removed the github.com SSH rule. Git name and email are unchanged. "
            "Run ghsw use with another keyword to pick an account."
        )
    save_store(store_path, store)
    return {"ok": True, "removed": keyword, "notes": notes}


def switch_account(
    store_path: Path,
    ssh_config: Path,
    keyword: str | None,
    dry_run: bool = False,
    check: bool = True,
    switch_cli: bool = True,
    env: dict[str, str] | None = None,
    gh_func: GhFunc | None = None,
    ssh_func: SshFunc | None = None,
) -> SwitchReport:
    store = load_store(store_path)
    if keyword:
        keyword = normalize_keyword(keyword)
    else:
        keyword = store.get("default") or ""
        if not keyword:
            raise GhswError("No keyword given and no default account is set.")
    account = store["accounts"].get(keyword)
    if not account:
        raise GhswError(f"No account named '{keyword}'.")

    key_path = Path(account["ssh_key"]).expanduser()
    if not key_path.exists():
        raise GhswError(f"SSH key for '{keyword}' was not found at {key_path}.")

    actions = [
        f"Set git user.name to {account['name']}",
        f"Set git user.email to {account['email']}",
        f"Point github.com SSH at {key_path}",
        f"Mark '{keyword}' as the active account",
    ]
    if switch_cli:
        actions.append(f"Switch GitHub CLI to {account['username']} when that login exists")
    else:
        actions.append("Leave the GitHub CLI login unchanged")
    if check:
        actions.append("Ask GitHub which account this SSH key belongs to")

    report = SwitchReport(ok=True, keyword=keyword, dry_run=dry_run, actions=actions)
    if dry_run:
        return report

    write_git_identity(account["name"], account["email"], env=env)
    upsert_ssh_block(ssh_config, str(key_path))
    store["active"] = keyword
    save_store(store_path, store)

    if switch_cli:
        gh = gh_func or switch_gh
        ok_gh, gh_message = gh(account["username"], env)
        report.gh_message = gh_message
        if not ok_gh:
            report.warnings.append(gh_message)

    if check:
        probe = ssh_func or check_ssh
        result = probe(env, ssh_config)
        report.ssh_check = result.message
        if not result.ok:
            report.warnings.append(result.message)
        elif result.username and result.username != account["username"]:
            warning = (
                f"GitHub authenticated as {result.username}, "
                f"which does not match {account['username']}."
            )
            report.warnings.append(warning)
    return report


def status(
    store_path: Path,
    ssh_config: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    store = load_store(store_path)
    git_name, git_email = read_git_identity(env)
    ssh_key = read_managed_key(ssh_config)
    gh_accounts, gh_error = read_gh_accounts(env)
    active_gh = next((item for item in gh_accounts if item.get("active")), None)
    active_keyword = store.get("active")
    account = store["accounts"].get(active_keyword) if active_keyword else None
    in_sync = False
    if account:
        in_sync = (
            account["name"] == git_name
            and account["email"] == git_email
            and ssh_key == str(Path(account["ssh_key"]).expanduser())
        )
    return {
        "active_keyword": active_keyword,
        "default_keyword": store.get("default"),
        "git_name": git_name,
        "git_email": git_email,
        "ssh_key": ssh_key,
        "gh_user": active_gh["username"] if active_gh else None,
        "gh_invalid": bool(active_gh and active_gh.get("invalid")),
        "gh_error": gh_error,
        "in_sync": in_sync,
    }


def command_env(env: dict[str, str] | None) -> dict[str, str]:
    merged = os.environ.copy() if env is None else env.copy()
    merged.setdefault("GIT_TERMINAL_PROMPT", "0")
    return merged


def run_command(
    args: list[str],
    env: dict[str, str] | None = None,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=command_env(env),
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


def read_git_identity(env: dict[str, str] | None = None) -> tuple[str, str]:
    name = run_command(["git", "config", "--global", "--get", "user.name"], env=env)
    email = run_command(["git", "config", "--global", "--get", "user.email"], env=env)
    return name.stdout.strip(), email.stdout.strip()


def write_git_identity(name: str, email: str, env: dict[str, str] | None = None) -> None:
    for key, value in (("user.name", name), ("user.email", email)):
        result = run_command(["git", "config", "--global", key, value], env=env)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GhswError(detail or f"Could not set git {key}.")


def format_identity_file(path: str) -> str:
    if any(character.isspace() for character in path):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return path


def render_block(ssh_key: str) -> str:
    identity = format_identity_file(str(Path(ssh_key).expanduser()))
    return (
        f"{MARKER_BEGIN}\n"
        "# Managed by GitHub Switch. Switching accounts rewrites this block.\n"
        "Host github.com\n"
        "  HostName github.com\n"
        "  User git\n"
        f"  IdentityFile {identity}\n"
        "  IdentitiesOnly yes\n"
        f"{MARKER_END}\n"
        "\n"
    )


def strip_managed_block(text: str) -> str:
    begin = text.find(MARKER_BEGIN)
    end = text.find(MARKER_END)
    if begin == -1 and end == -1:
        return text
    if begin == -1 or end == -1 or end < begin:
        raise GhswError(
            "The ghsw markers in the SSH config are incomplete. "
            "Keep both '# >>> ghsw >>>' and '# <<< ghsw <<<' lines."
        )
    end_index = end + len(MARKER_END)
    if end_index < len(text) and text[end_index] == "\n":
        end_index += 1
    return text[:begin] + text[end_index:]


def upsert_ssh_block(config_file: Path, ssh_key: str) -> None:
    existing = config_file.read_text() if config_file.exists() else ""
    stripped = strip_managed_block(existing).lstrip("\n")
    block = render_block(ssh_key)
    updated = block + stripped if stripped else block
    _write_config(config_file, updated)


def remove_managed_ssh_block(config_file: Path) -> None:
    if not config_file.exists():
        return
    stripped = strip_managed_block(config_file.read_text()).lstrip("\n")
    _write_config(config_file, stripped)


def read_managed_key(config_file: Path) -> str | None:
    if not config_file.exists():
        return None
    text = config_file.read_text()
    begin = text.find(MARKER_BEGIN)
    end = text.find(MARKER_END)
    if begin == -1 or end == -1 or end < begin:
        return None
    for line in text[begin:end].splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("identityfile "):
            value = stripped.split(None, 1)[1].strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            return str(Path(value).expanduser())
    return None


def _write_config(path: Path, text: str) -> None:
    mode = 0o600
    if path.exists():
        mode = path.stat().st_mode & 0o777
    directory = path.parent
    created_dir = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if created_dir:
        os.chmod(directory, 0o700)
    _write_private(path, text, mode=mode)


def _write_private(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (path.name + ".tmp")
    temporary.write_text(text)
    os.chmod(temporary, mode)
    temporary.replace(path)


def parse_gh_status(text: str) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        match = GH_LOGIN_LINE.search(line)
        if match:
            if current:
                accounts.append(current)
            current = {"username": match.group(1), "active": False, "invalid": False}
            if "Failed to log in" in line:
                current["invalid"] = True
            continue
        if current is None:
            continue
        if "Active account: true" in line:
            current["active"] = True
        if "token in keyring is invalid" in line.lower():
            current["invalid"] = True
    if current:
        accounts.append(current)
    return accounts


def read_gh_accounts(
    env: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    gh = shutil.which("gh", path=(env or os.environ).get("PATH"))
    if not gh:
        return [], "GitHub CLI (gh) is not installed."
    try:
        result = run_command(
            [gh, "auth", "status", "--hostname", "github.com"],
            env=env,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return [], "GitHub CLI status timed out."
    output = f"{result.stdout}\n{result.stderr}"
    return parse_gh_status(output), None


def switch_gh(username: str, env: dict[str, str] | None = None) -> tuple[bool, str]:
    gh = shutil.which("gh", path=(env or os.environ).get("PATH"))
    if not gh:
        return False, "GitHub CLI (gh) is not installed. Git name, email, and SSH key were still switched."
    accounts, error = read_gh_accounts(env)
    if error and not accounts:
        return False, f"{error} Git name, email, and SSH key were still switched."
    known = next((item for item in accounts if item["username"] == username), None)
    if known is None:
        return (
            False,
            f"GitHub CLI has no login for {username}. "
            "Git name, email, and SSH key were still switched. "
            f"Log in once with: gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key",
        )
    if known.get("invalid"):
        return (
            False,
            f"GitHub CLI is set to {username}, but the saved token is invalid. "
            "Log in again with: gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key",
        )
    if known.get("active"):
        return True, f"GitHub CLI is already using {username}."
    try:
        result = run_command(
            [gh, "auth", "switch", "--hostname", "github.com", "--user", username],
            env=env,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return False, f"gh auth switch timed out for {username}."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, detail or f"gh auth switch failed for {username}."
    return True, f"GitHub CLI is now using {username}."


def interpret_ssh_output(output: str) -> tuple[bool, str | None]:
    if "successfully authenticated" not in output.lower():
        return False, None
    match = re.search(r"Hi ([^!\r\n]+)!", output)
    username = match.group(1).strip() if match else None
    return True, username


def check_ssh(env: dict[str, str] | None, config_file: Path) -> SSHCheck:
    try:
        result = run_command(
            [
                "ssh",
                "-F",
                str(config_file),
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=10",
                "git@github.com",
            ],
            env=env,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return SSHCheck(False, "SSH check timed out reaching github.com.")
    output = (result.stderr or result.stdout).strip()
    ok, username = interpret_ssh_output(output)
    if ok:
        return SSHCheck(True, output or "SSH key authenticated.", username)
    if not output:
        return SSHCheck(False, "SSH check failed with no message from GitHub.")
    return SSHCheck(False, output, username)
