"""Tests for local account switching. They never touch the real Git config."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core
import ghsw


class SwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "accounts.json"
        self.ssh = self.root / "ssh_config"
        self.gitconfig = self.root / "gitconfig"
        self.env = os.environ.copy()
        self.env["GIT_CONFIG_GLOBAL"] = str(self.gitconfig)
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env["GIT_CONFIG_SYSTEM"] = str(self.root / "no-system-gitconfig")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add(self, keyword: str = "work") -> dict:
        key = self.root / f"id_{keyword}"
        key.write_text("not a real key\n")
        return core.add_account(
            self.config,
            keyword,
            username=f"{keyword}-user",
            name=f"{keyword.title()} Name",
            email=f"{keyword}@example.com",
            ssh_key=key,
            generate_key=False,
        )

    def test_add_list_default_and_reject_bad_keyword(self) -> None:
        self.add("work")
        self.add("personal")
        listed = core.list_accounts(self.config)
        self.assertEqual([row["keyword"] for row in listed["accounts"]], ["personal", "work"])
        core.set_default(self.config, "personal")
        listed = core.list_accounts(self.config)
        personal = next(row for row in listed["accounts"] if row["keyword"] == "personal")
        self.assertTrue(personal["is_default"])
        with self.assertRaises(core.GhswError):
            core.add_account(
                self.config,
                "Work",
                username="other",
                name="Other",
                email="other@example.com",
                ssh_key=self.root / "missing",
                generate_key=False,
            )
        with self.assertRaises(core.GhswError):
            core.normalize_keyword("1bad")

    def test_dry_run_writes_nothing(self) -> None:
        self.add()
        report = core.switch_account(
            self.config,
            self.ssh,
            "work",
            dry_run=True,
            env=self.env,
            gh_func=lambda username, env=None: (True, "unused"),
            ssh_func=lambda env, config_file: core.SSHCheck(True, "unused", "work-user"),
        )
        self.assertTrue(report.dry_run)
        self.assertFalse(self.ssh.exists())
        self.assertFalse(self.gitconfig.exists())
        self.assertIsNone(core.load_store(self.config)["active"])

    def test_switch_updates_git_ssh_and_keeps_other_hosts(self) -> None:
        self.add()
        self.ssh.write_text("Host gitlab.example\n  User git\n  IdentityFile /tmp/gitlab\n")
        calls: list[str] = []

        def gh_func(username: str, env=None):
            calls.append(username)
            return True, f"GitHub CLI is now using {username}."

        def ssh_func(env, config_file: Path):
            text = config_file.read_text()
            self.assertIn("IdentityFile", text)
            return core.SSHCheck(
                True,
                "Hi work-user! You've successfully authenticated, but GitHub does not provide shell access.",
                "work-user",
            )

        report = core.switch_account(
            self.config,
            self.ssh,
            "work",
            env=self.env,
            gh_func=gh_func,
            ssh_func=ssh_func,
        )
        self.assertEqual(report.warnings, [])
        self.assertEqual(calls, ["work-user"])
        name, email = core.read_git_identity(self.env)
        self.assertEqual(name, "Work Name")
        self.assertEqual(email, "work@example.com")
        text = self.ssh.read_text()
        self.assertTrue(text.startswith(core.MARKER_BEGIN))
        self.assertIn("Host gitlab.example", text)
        self.assertEqual(core.read_managed_key(self.ssh), str(self.root / "id_work"))
        self.assertEqual(core.load_store(self.config)["active"], "work")
        status = core.status(self.config, self.ssh, env=self.env)
        self.assertTrue(status["in_sync"])

    def test_ssh_username_mismatch_warns(self) -> None:
        self.add()

        def ssh_func(env, config_file: Path):
            return core.SSHCheck(True, "Hi someone-else! You've successfully authenticated.", "someone-else")

        report = core.switch_account(
            self.config,
            self.ssh,
            "work",
            switch_cli=False,
            env=self.env,
            ssh_func=ssh_func,
        )
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("someone-else", report.warnings[0])

    def test_use_without_keyword_uses_default(self) -> None:
        self.add("personal")
        core.set_default(self.config, "personal")
        report = core.switch_account(
            self.config,
            self.ssh,
            None,
            check=False,
            switch_cli=False,
            env=self.env,
        )
        self.assertEqual(report.keyword, "personal")
        store = core.load_store(self.config)
        store["default"] = None
        core.save_store(self.config, store)
        with self.assertRaises(core.GhswError):
            core.switch_account(
                self.config,
                self.ssh,
                None,
                dry_run=True,
                env=self.env,
            )

    def test_remove_active_falls_back_to_default(self) -> None:
        self.add("work")
        self.add("personal")
        core.set_default(self.config, "personal")
        core.switch_account(
            self.config,
            self.ssh,
            "work",
            check=False,
            switch_cli=False,
            env=self.env,
        )
        payload = core.remove_account(
            self.config,
            self.ssh,
            "work",
            env=self.env,
            gh_func=lambda username, env=None: (True, "switched"),
            switch_cli=True,
        )
        self.assertIn("personal", payload["notes"][0])
        store = core.load_store(self.config)
        self.assertNotIn("work", store["accounts"])
        self.assertEqual(store["active"], "personal")
        self.assertEqual(store["default"], "personal")
        name, email = core.read_git_identity(self.env)
        self.assertEqual(email, "personal@example.com")

    def test_remove_last_active_clears_ssh_block(self) -> None:
        self.add("work")
        core.switch_account(
            self.config,
            self.ssh,
            "work",
            check=False,
            switch_cli=False,
            env=self.env,
        )
        payload = core.remove_account(self.config, self.ssh, "work", env=self.env)
        self.assertIsNone(core.read_managed_key(self.ssh))
        self.assertTrue(any("Git name and email are unchanged" in note for note in payload["notes"]))

    def test_broken_markers_are_refused(self) -> None:
        self.ssh.write_text("# >>> ghsw >>>\nHost github.com\n")
        with self.assertRaises(core.GhswError):
            core.upsert_ssh_block(self.ssh, "/tmp/key")

    def test_generate_key_and_show_public_key(self) -> None:
        key = self.root / "keys" / "id_ed25519_personal"
        payload = core.add_account(
            self.config,
            "personal",
            username="octocat",
            name="Octo Cat",
            email="octo@example.com",
            ssh_key=key,
            generate_key=True,
        )
        self.assertTrue(key.exists())
        self.assertTrue(payload["public_key"].startswith("ssh-ed25519 "))
        shown = core.public_key_for(self.config, "personal")
        self.assertEqual(shown["public_key"], payload["public_key"])

    def test_gh_status_parser(self) -> None:
        text = """
github.com
  X Failed to log in to github.com account nipun-m145 (keyring)
  - Active account: true
  - The token in keyring is invalid.

  Logged in to github.com account octocat (keyring)
  - Active account: false
"""
        accounts = core.parse_gh_status(text)
        self.assertEqual(accounts[0]["username"], "nipun-m145")
        self.assertTrue(accounts[0]["active"])
        self.assertTrue(accounts[0]["invalid"])
        self.assertEqual(accounts[1]["username"], "octocat")
        self.assertFalse(accounts[1]["active"])

    def test_ssh_output_parser(self) -> None:
        ok, username = core.interpret_ssh_output(
            "Hi octocat! You've successfully authenticated, but GitHub does not provide shell access."
        )
        self.assertTrue(ok)
        self.assertEqual(username, "octocat")
        ok, username = core.interpret_ssh_output("git@github.com: Permission denied (publickey).")
        self.assertFalse(ok)
        self.assertIsNone(username)

    def test_cli_round_trip_uses_temp_config(self) -> None:
        key = self.root / "id_cli"
        env = {
            "GHSW_CONFIG": str(self.config),
            "GHSW_SSH_CONFIG": str(self.ssh),
            "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ghsw.main(
                    [
                        "add",
                        "work",
                        "--username",
                        "work-user",
                        "--name",
                        "Work Name",
                        "--email",
                        "work@example.com",
                        "--ssh-key",
                        str(key),
                        "--generate-key",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            added = json.loads(stdout.getvalue())
            self.assertTrue(added["ok"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ghsw.main(["use", "--dry-run", "--json"])
            self.assertEqual(code, 1)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ghsw.main(["default", "work", "--json"])
            self.assertEqual(code, 0)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ghsw.main(["use", "--dry-run", "--json"])
            self.assertEqual(code, 0)
            preview = json.loads(stdout.getvalue())
            self.assertTrue(preview["dry_run"])
            self.assertEqual(preview["keyword"], "work")
            self.assertFalse(self.gitconfig.exists())

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ghsw.main(["use", "work", "--no-gh", "--no-check", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(core.read_git_identity(self.env)[1], "work@example.com")

            stderr = io.StringIO()
            with mock.patch.object(sys.stdin, "isatty", return_value=False):
                with redirect_stderr(stderr):
                    code = ghsw.main(["remove", "work"])
            self.assertEqual(code, 1)
            self.assertIn("--yes", stderr.getvalue())


class RealConfigUntouched(unittest.TestCase):
    def test_user_global_gitconfig_is_not_required(self) -> None:
        home = Path.home() / ".gitconfig"
        before = home.stat().st_mtime if home.exists() else None
        result = subprocess.run(
            ["git", "config", "--global", "--get", "user.email"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/tmp/ghsw-test-does-not-write",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        after = home.stat().st_mtime if home.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
