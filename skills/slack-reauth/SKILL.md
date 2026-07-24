---
name: slack-reauth
version: "1.0"
description: Refresh Slack MCP session tokens from the desktop app. Extracts xoxc/xoxd tokens automatically from the Slack app's on-disk storage — no DevTools, no copy-paste. Use when Slack MCP tools return auth errors, empty channel lists, or token expiry symptoms.
allowed-tools: Bash, Read, Write
user-invocable: true
---

# Slack Reauth

Refresh the Slack session tokens used by the Slack MCP server by extracting fresh tokens directly from the Slack desktop app's local storage.

## When to Use

Invoke when:
- `list_joined_channels` returns empty or false
- `refresh_channel_cache` returns false
- Slack MCP tools return auth errors or permission errors
- User says `/slack-reauth`, "refresh Slack tokens", "Slack MCP broken", "reauth Slack"

## Background

The Slack MCP server (`~/.config/slack-mcp/run-slack-mcp.sh`) authenticates using two browser session tokens:
- `xoxc-*` — Slack web API Bearer token
- `xoxd-*` — Slack session cookie (`d` cookie)

These are stored at `~/.config/slack-mcp/` as `xoxc-token` and `xoxd-token` files (600 perms) and injected as env vars into the container at startup. # nocheck Desktop app tokens rotate periodically — when expired, all Slack MCP calls fail silently or return empty results.

The refresh script (`~/DevSpace/slack-mcp/scripts/slack-refresh-tokens`) extracts fresh tokens from the Slack desktop app's on-disk storage without requiring browser DevTools.

## Requirements Check

Before running, verify:

```bash
# Script exists
ls ~/DevSpace/slack-mcp/scripts/slack-refresh-tokens

# Slack desktop app data present
ls ~/.config/Slack/Cookies

# Python deps
python3 -c "import secretstorage; from cryptography.hazmat.primitives.ciphers import Cipher" 2>&1

# secret-tool available (fallback if secretstorage not installed)
command -v secret-tool
```

If `~/.config/Slack/Cookies` is missing: Slack desktop app is not installed or not signed in. Tell the user — cannot extract tokens without it.

If `secretstorage` is missing: try `pip install --user secretstorage`. If that fails, check if `secret-tool` is available as fallback.

## Execution

### Step 1: Run the Refresh Script

```bash
~/DevSpace/slack-mcp/scripts/slack-refresh-tokens --validate
```

The script:
1. Reads the GNOME Keyring for Slack's encryption key (via `secretstorage` or `secret-tool`)
2. Decrypts `xoxd` from `~/.config/Slack/Cookies` (SQLite, AES-CBC)
3. Scans LevelDB (`~/.config/Slack/Local Storage/leveldb/`) for `xoxc`
4. Validates both tokens against `slack.com/api/auth.test`
5. Saves to `~/.local/share/slack-mcp/tokens.env`

**Success output looks like:**
```
Tokens saved to /home/<user>/.local/share/slack-mcp/tokens.env
  xoxc: <token-prefix>-...truncated...
  xoxd: <token-prefix>-...truncated...
Validated: tokens are working.
```

**If `--validate` fails:** tokens extracted but invalid. Slack app may be signed out — ask user to open Slack and sign in, then retry.

**If extraction fails entirely:** likely a keyring issue (locked keyring or wrong entry name). See Troubleshooting below.

### Step 2: Install Tokens

Read the saved tokens file and write each token to the config location:

```bash
# Read the tokens
source ~/.local/share/slack-mcp/tokens.env

# Write to config files (preserve 600 perms)
echo -n "$SLACK_MCP_XOXC_TOKEN" > ~/.config/slack-mcp/xoxc-token # nocheck
echo -n "$SLACK_MCP_XOXD_TOKEN" > ~/.config/slack-mcp/xoxd-token # nocheck
chmod 600 ~/.config/slack-mcp/xoxc-token ~/.config/slack-mcp/xoxd-token # nocheck
```

Verify the files are non-empty:
```bash
wc -c ~/.config/slack-mcp/xoxc-token ~/.config/slack-mcp/xoxd-token # nocheck
```

Both should be >100 characters.

### Step 3: Verify MCP Access

The MCP server reads token files at container startup (not live-reloaded). The Claude Code session picks up new tokens automatically on the next Slack MCP tool call — no restart needed because each call launches a fresh `podman run`.

Test with a quick search:
```
Use mcp__slack-mcp__whoami to confirm the new tokens work.
```

If `whoami` returns a valid user, reauth is complete.

### Step 4: Report Result

Tell the user:
- Old tokens replaced ✓
- Validation status (working / failed)
- Slack username confirmed (from whoami)
- When tokens will next expire (no fixed schedule — typically weeks to months)

## Troubleshooting

**`ERROR: No Slack encryption key in system keyring`**
- GNOME Keyring may be locked. Run `gnome-keyring-daemon --unlock` or open Passwords app.
- Slack Flatpak vs native: the keyring entry name differs. Check both:
  ```bash
  secret-tool lookup application Slack 2>/dev/null || \
  secret-tool lookup user "Slack Safe Storage" server "Slack Keys" 2>/dev/null
  ```

**`ERROR: No session cookie found in Slack Cookies DB`**
- Slack app not signed in. Open Slack desktop app, sign in, then retry.

**`ERROR: xoxc token not found in Slack Local Storage`**
- LevelDB files may be compacted. Open Slack (let it sync), close it cleanly, then retry.

**Flatpak Slack:**
- Data dir is `~/.var/app/com.slack.Slack/config/Slack/` instead of `~/.config/Slack/`
- Use `--slack-dir` override if the script auto-detection fails:
  ```bash
  ~/DevSpace/slack-mcp/scripts/slack-refresh-tokens \
    --slack-dir ~/.var/app/com.slack.Slack/config/Slack/ --validate
  ```

**Token installed but MCP still broken:**
- Confirm the wrapper script reads from the right path:
  ```bash
  cat ~/.config/slack-mcp/run-slack-mcp.sh
  ```
- Token files must be at `~/.config/slack-mcp/xoxc-token` and `~/.config/slack-mcp/xoxd-token`. # nocheck
