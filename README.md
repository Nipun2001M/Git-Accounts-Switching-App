# GitHub Switch

Switch the GitHub account this Mac uses for commits, SSH, and the GitHub CLI. Each account gets a short keyword such as `work` or `personal`. One account can be the default.

The project stays in this folder. It does not create a GitHub repository.

## Open the app

Spotlight: press Command-Space and type **GitHub Switch**.

The same app is in the Applications folder. Inside the window:

| Action | Shortcut |
| --- | --- |
| Add an account | Command-N |
| Refresh | Command-R |
| Use the selected account | Command-Return |
| Set the selected account as the default | Command-D |
| Remove the selected account | Command-Delete |

## Terminal

```bash
ghsw add work
ghsw add personal
ghsw default personal
ghsw use work
ghsw use
ghsw status
ghsw list
ghsw key work
ghsw use work --dry-run
ghsw remove work
```

`ghsw use` with no keyword activates the default account. `--dry-run` prints the change and writes nothing.

## What a switch changes

- Global Git `user.name` and `user.email`
- The `github.com` block in `~/.ssh/config` between the `# >>> ghsw >>>` markers
- The active GitHub CLI login, when that username is already logged in

Your account list is stored at `~/.config/ghsw/accounts.json`. SSH private keys stay in `~/.ssh`. Tokens stay in the macOS keychain through `gh`.

## First-time setup for each account

1. Add the account in the app, or with `ghsw add <keyword>`.
2. Copy the public key into that GitHub account at [SSH keys](https://github.com/settings/keys).
3. Log that account into GitHub CLI once:

```bash
gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key
```

4. Run `ghsw use <keyword>` before you commit or push as that person.

If you already had a `Host github.com` entry, it stays below the managed block. The block at the top is the one GitHub Switch rewrites.

## Rebuild the app shortcut

```bash
/Users/nipunmadhushan/personalProj/ghsw/scripts/install.sh
```
