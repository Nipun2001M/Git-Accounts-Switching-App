# Setup

Install GitHub Switch, then add each GitHub account once. After that, switch with a keyword.

The pictures use `you@example.com` and `work@example.com` in place of real commit emails.

## 1. Install

From this project folder:

```bash
./scripts/install.sh
```

That does two things:

- Puts **GitHub Switch** in the Applications folder, so Spotlight can open it.
- Puts the `ghsw` command on your PATH.

Open it from Spotlight with Command-Space, then type **GitHub Switch**.

## 2. Add each account

In the app, click **Add Account**, or press Command-N.

![Add Account form](images/gui-add-account.png)

| Field | What to enter |
| --- | --- |
| Keyword | A short name you will type later, such as `personal` or `nr`. |
| GitHub username | The login on github.com. |
| Commit name | The author name Git writes on new commits. |
| Commit email | The address Git writes next to that name. GitHub uses it to attach the commit to the right account. |
| SSH private key | A secret file on this Mac for that account. Leave the suggested path, for example `~/.ssh/id_ed25519_personal`. |
| Generate the SSH key if it is missing | Leave this on. The app creates the key file when it is not there yet. It does not replace a key that already exists. |

Use a different keyword and a different key file for each account.

Click **Add**. The app shows the public key. Click **Copy Key**, then open [GitHub SSH keys](https://github.com/settings/keys) while logged into that same account and add the key.

The private key stays on this Mac. Only the public key goes on GitHub.

## 3. Log in to GitHub CLI once per account

```bash
gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key
```

Run that once for each account. The second time adds the other account. Tokens stay in the macOS keychain.

## 4. Choose a default, then switch

Select an account and click **Set Default**, or:

```bash
ghsw default personal
ghsw use personal
```

`ghsw use` with no keyword activates the default account.

Check what is active:

```bash
ghsw status
```

Switching changes the Git name and email, the `github.com` SSH key, and the active GitHub CLI login on this Mac. It does not create a repository.
