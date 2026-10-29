# GitHub Switch

Switch the GitHub account this Mac uses for commits, SSH, and the GitHub CLI. Each account gets a short keyword such as `personal` or `nr`. One account can be the default.

Switching does not create a repository.

## Guides

- [Setup](docs/setup.md) — install, add accounts, SSH keys, and GitHub CLI
- [Command line](docs/cli.md) — `ghsw` with pictures
- [App](docs/gui.md) — the GitHub Switch window, buttons, and shortcuts

## Commands

```bash
ghsw add personal
ghsw default personal
ghsw use personal
ghsw use
ghsw status
ghsw list
ghsw key personal
ghsw use nr --dry-run
```

`ghsw use` with no keyword activates the default account. `--dry-run` prints the change and writes nothing.

Your account list is stored at `~/.config/ghsw/accounts.json`. SSH private keys stay in `~/.ssh`. Tokens stay in the macOS keychain through `gh`.

## Rebuild the app shortcut

```bash
./scripts/install.sh
```
