#!/usr/bin/env python3
"""
setup-slack-mcp.py — One-command Slack MCP setup for Claude Code

What this script does (automatically):
  1. Checks prerequisites (python3, podman)
  2. Creates a virtual environment and installs Playwright + Chromium
  3. Pulls the Slack MCP container image
  4. Opens a browser to extract your Slack session tokens
     (only manual step: log in to Slack when the browser opens)
  5. Prompts for a Slack channel ID to use for MCP server logs
  6. Writes a wrapper script that launches the MCP server
  7. Registers the MCP server in ~/.claude/settings.json

Usage:
  python3 setup-slack-mcp.py
  python3 setup-slack-mcp.py --refresh-tokens           # re-extract tokens
  python3 setup-slack-mcp.py --workspace https://myco.slack.com
  python3 setup-slack-mcp.py --logs-channel DXXXXXXXXX  # skip the prompt
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────────────

INSTALL_DIR    = Path.home() / ".local" / "share" / "slack-mcp"
VENV_DIR       = INSTALL_DIR / ".venv"
TOKENS_FILE    = INSTALL_DIR / "tokens.env"
WRAPPER_SCRIPT = INSTALL_DIR / "run-slack-mcp.sh"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

MCP_IMAGE       = "quay.io/redhat-ai-tools/slack-mcp"
MCP_SERVER_NAME = "slack"
PROFILE_DIR     = Path.home() / ".slack-token-extractor" / "browser-profile"

DEFAULT_WORKSPACE = "https://app.slack.com/client/"


# ── Helpers ──────────────────────────────────────────────────────────────────

def banner(msg: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {msg}")
    print(f"{'─' * width}")


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def venv_bin(name: str) -> Path:
    return VENV_DIR / "bin" / name


# ── Steps ────────────────────────────────────────────────────────────────────

def check_prerequisites() -> None:
    banner("Checking prerequisites")

    errors = []

    # podman (or docker as fallback)
    container_runtime = shutil.which("podman") or shutil.which("docker")
    if not container_runtime:
        errors.append("  ✗ Neither 'podman' nor 'docker' found — install one to continue.")
    else:
        runtime_name = Path(container_runtime).name
        print(f"  ✓ {runtime_name}: {container_runtime}")

    # python3 venv module
    result = subprocess.run(
        [sys.executable, "-m", "venv", "--help"],
        capture_output=True,
    )
    if result.returncode != 0:
        errors.append(f"  ✗ python3 venv module not available (try: sudo apt install python3-venv)")
    else:
        print(f"  ✓ python3: {sys.version.split()[0]}")

    if errors:
        print("\nPrerequisite check failed:")
        for e in errors:
            print(e)
        sys.exit(1)


def setup_venv() -> Path:
    """Create venv and install Playwright + Chromium. Returns path to venv python."""
    banner("Setting up Python environment")

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    if not VENV_DIR.exists():
        print(f"  Creating venv at {VENV_DIR} ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print(f"  ✓ Venv already exists")

    pip    = venv_bin("pip")
    python = venv_bin("python")

    # Install / upgrade playwright
    result = subprocess.run([str(pip), "show", "playwright"], capture_output=True)
    if result.returncode != 0:
        print("  Installing playwright ...")
        run([str(pip), "install", "--quiet", "playwright"])
    else:
        print("  ✓ playwright already installed")

    # Check if Chromium browser binary exists
    chromium_check = subprocess.run(
        [str(python), "-c",
         "from playwright.sync_api import sync_playwright; "
         "p = sync_playwright().start(); "
         "path = p.chromium.executable_path; "
         "p.stop(); "
         "import sys, pathlib; sys.exit(0 if pathlib.Path(path).exists() else 1)"],
        capture_output=True,
    )
    if chromium_check.returncode != 0:
        print("  Installing Chromium for Playwright (one-time download) ...")
        run([str(venv_bin("playwright")), "install", "chromium"])
    else:
        print("  ✓ Chromium already installed")

    return python


def pull_image() -> None:
    banner("Pulling Slack MCP container image")

    # Detect runtime
    runtime = "podman" if shutil.which("podman") else "docker"

    result = subprocess.run(
        [runtime, "image", "exists", MCP_IMAGE] if runtime == "podman"
        else [runtime, "image", "inspect", MCP_IMAGE],
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"  ✓ Image already present: {MCP_IMAGE}")
    else:
        print(f"  Pulling {MCP_IMAGE} ...")
        run([runtime, "pull", MCP_IMAGE])
        print(f"  ✓ Image ready")


def tokens_exist() -> bool:
    if not TOKENS_FILE.exists():
        return False
    text = TOKENS_FILE.read_text()
    return "SLACK_MCP_XOXC_TOKEN=xoxc-" in text and "SLACK_MCP_XOXD_TOKEN=" in text


# Inline extraction script — run inside the venv so Playwright is available.
_EXTRACT_SCRIPT = r'''
import json, os, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

workspace_url = sys.argv[1]
output_file   = sys.argv[2]
profile_dir   = Path(sys.argv[3])

profile_dir.mkdir(parents=True, exist_ok=True)

print("  Launching browser ...")
with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        str(profile_dir),
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        viewport={"width": 1280, "height": 800},
    )

    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(workspace_url)

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PWTimeout:
        pass  # continue anyway

    if any(x in page.url for x in ("signin", "sign_in", "ssb/signin")):
        print()
        print("  " + "=" * 56)
        print("  Log in to Slack in the browser window that just opened.")
        print("  Once you can see your workspace, come back here and")
        print("  press ENTER to continue.")
        print("  " + "=" * 56)
        input("  > ")
        try:
            page.wait_for_url("**/client/**", timeout=10000)
            page.wait_for_load_state("networkidle", timeout=30000)
        except PWTimeout:
            pass

    # Team ID
    m = re.search(r"/client/([A-Z0-9]+)", page.url)
    team_id = m.group(1) if m else page.evaluate("""() => {
        try {
            const c = JSON.parse(localStorage.localConfig_v2 || '{}');
            return Object.keys(c.teams || {})[0] || null;
        } catch { return null; }
    }""")

    if not team_id:
        print("  ERROR: Could not determine team ID. Is Slack fully loaded?")
        browser.close()
        sys.exit(1)

    print(f"  Found team ID: {team_id}")

    # XOXC token
    xoxc = page.evaluate("""(tid) => {
        try {
            const c = JSON.parse(localStorage.localConfig_v2 || '{}');
            if (c.teams?.[tid]?.token) return c.teams[tid].token;
            for (const d of Object.values(c.teams || {}))
                if (d.token?.startsWith('xoxc-')) return d.token;
        } catch {}
        return null;
    }""", team_id)

    if not xoxc:
        # Last-resort: scan page HTML
        xoxc = page.evaluate("""() => {
            const m = document.body.innerHTML.match(/"token":"(xoxc-[^"]+)"/);
            return m ? m[1] : null;
        }""")

    if not xoxc:
        print("  ERROR: Could not extract XOXC token.")
        browser.close()
        sys.exit(1)

    print(f"  Found XOXC token: {xoxc[:20]}...{xoxc[-8:]}")

    # XOXD cookie
    xoxd = next(
        (c["value"] for c in browser.cookies()
         if c["name"] == "d" and "slack.com" in c["domain"]),
        None,
    )

    if not xoxd:
        print("  ERROR: Could not extract XOXD token (cookie 'd' not found).")
        browser.close()
        sys.exit(1)

    print(f"  Found XOXD token: {xoxd[:20]}...{xoxd[-8:]}")
    browser.close()

with open(output_file, "w") as f:
    f.write(f"# Slack session tokens (auto-generated by setup-slack-mcp.py)\n")
    f.write(f"# Team ID: {team_id}\n\n")
    f.write(f"SLACK_MCP_XOXC_TOKEN={xoxc}\n")
    f.write(f"SLACK_MCP_XOXD_TOKEN={xoxd}\n")

os.chmod(output_file, 0o600)
print(f"  Tokens saved to: {output_file}")
'''


def extract_tokens(python: Path, workspace_url: str, refresh: bool) -> None:
    banner("Extracting Slack session tokens")

    if tokens_exist() and not refresh:
        print(f"  ✓ Tokens already exist at {TOKENS_FILE}")
        print("    Run with --refresh-tokens to re-extract.")
        return

    print("  A browser window will open. Log in to Slack, then return here.")

    extract_file = INSTALL_DIR / "_extract_tokens.py"
    extract_file.write_text(_EXTRACT_SCRIPT)

    try:
        run([
            str(python),
            str(extract_file),
            workspace_url,
            str(TOKENS_FILE),
            str(PROFILE_DIR),
        ])
    except subprocess.CalledProcessError:
        print("\n  Token extraction failed. See output above.")
        extract_file.unlink(missing_ok=True)
        sys.exit(1)
    finally:
        extract_file.unlink(missing_ok=True)


def write_wrapper(logs_channel: str) -> None:
    banner("Writing MCP wrapper script")

    runtime = "podman" if shutil.which("podman") else "docker"

    # Build env args as a list so there are no stray line-continuation issues
    env_lines = [
        '  -e SLACK_XOXC_TOKEN="${SLACK_MCP_XOXC_TOKEN}" \\',
        '  -e SLACK_XOXD_TOKEN="${SLACK_MCP_XOXD_TOKEN}" \\',
        "  -e MCP_TRANSPORT=stdio \\",
    ]
    if logs_channel:
        env_lines.append(f'  -e LOGS_CHANNEL_ID="{logs_channel}" \\')

    env_block = "\n".join(env_lines)

    content = f"""\
#!/usr/bin/env bash
# Slack MCP wrapper — auto-generated by setup-slack-mcp.py
# Re-run setup-slack-mcp.py to regenerate or update this file.
set -euo pipefail

TOKENS="{TOKENS_FILE}"

if [[ ! -f "$TOKENS" ]]; then
  echo "Error: $TOKENS not found." >&2
  echo "Re-run: python3 setup-slack-mcp.py --refresh-tokens" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$TOKENS"

exec {runtime} run -i --rm \\
{env_block}
  {MCP_IMAGE}
"""
    WRAPPER_SCRIPT.write_text(content)
    WRAPPER_SCRIPT.chmod(0o755)
    print(f"  ✓ Written: {WRAPPER_SCRIPT}")


def register_mcp() -> None:
    banner("Registering MCP server in Claude Code settings")

    settings: dict = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except json.JSONDecodeError:
            print(f"  Warning: could not parse existing {CLAUDE_SETTINGS}, will overwrite.")

    settings.setdefault("mcpServers", {})[MCP_SERVER_NAME] = {
        "command": str(WRAPPER_SCRIPT),
        "args": [],
    }

    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  ✓ Registered '{MCP_SERVER_NAME}' in {CLAUDE_SETTINGS}")


def prompt_logs_channel() -> str:
    """Interactively guide the user to find and enter their Slack logs channel ID."""
    banner("Slack Logs Channel ID")

    print("""  The MCP server writes internal activity logs to a Slack channel.
  Any channel works — a self-DM or DM with Slackbot is easiest.

  How to find the channel ID:
    1. Open https://app.slack.com in a browser (not the desktop app)
    2. Navigate to the channel or DM you want to use
       - Self-DM: click your own name in the left sidebar
       - Slackbot: click "Slackbot" in the left sidebar
       - Channel:  click the channel name
    3. Copy the last segment of the URL, e.g.:
       https://app.slack.com/client/TXXXXXXXX/DXXXXXXXXX
                                               ^^^^^^^^^^^ this part
  IDs start with C (channel), D (direct message), or G (group DM).
""")

    while True:
        channel_id = input("  Enter channel ID (or press Enter to skip): ").strip()
        if not channel_id:
            print("  ⚠  No channel ID set. The server may log to stdout instead.")
            return ""
        if channel_id[0] in ("C", "D", "G") and len(channel_id) >= 9:
            return channel_id
        print(f"  That doesn't look like a valid Slack ID (expected C/D/G + digits). Try again.")


def verify() -> None:
    """Quick smoke-test: run the MCP server and send a JSON-RPC ping."""
    banner("Verifying MCP server")

    test_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }).encode()

    result = subprocess.run(
        [str(WRAPPER_SCRIPT)],
        input=test_payload,
        capture_output=True,
        timeout=30,
    )

    if result.returncode == 0 and b"tools" in result.stdout:
        print("  ✓ MCP server responded successfully")
    else:
        print("  ⚠  Could not verify MCP server. It may still work — check the tokens if you see issues.")
        if result.stderr:
            print(f"  stderr: {result.stderr.decode()[:300]}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up the Slack MCP plugin for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 setup-slack-mcp.py
  python3 setup-slack-mcp.py --refresh-tokens
  python3 setup-slack-mcp.py --workspace https://myco.slack.com
  python3 setup-slack-mcp.py --logs-channel C01234567
        """,
    )
    parser.add_argument(
        "--refresh-tokens",
        action="store_true",
        help="Re-extract Slack tokens even if they already exist",
    )
    parser.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE,
        metavar="URL",
        help=f"Slack workspace URL (default: {DEFAULT_WORKSPACE})",
    )
    parser.add_argument(
        "--logs-channel",
        default="",
        metavar="CHANNEL_ID",
        help="Slack channel ID for MCP server log output (prompted interactively if not set)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the smoke-test after setup",
    )
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       Slack MCP Setup for Claude Code                   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("  One manual step required: log in to Slack when the")
    print("  browser opens. Everything else is automatic.")

    check_prerequisites()
    python = setup_venv()
    pull_image()
    extract_tokens(python, args.workspace, refresh=args.refresh_tokens)
    logs_channel = args.logs_channel or prompt_logs_channel()
    write_wrapper(logs_channel)
    register_mcp()

    if not args.skip_verify:
        verify()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Setup complete!                                         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  MCP server name : {MCP_SERVER_NAME}")
    print(f"  Wrapper script  : {WRAPPER_SCRIPT}")
    print(f"  Tokens          : {TOKENS_FILE}")
    print(f"  Claude settings : {CLAUDE_SETTINGS}")
    print()
    print("  Start a new Claude Code session to activate the plugin.")
    print()
    print("  To refresh tokens when they expire:")
    print("    python3 setup-slack-mcp.py --refresh-tokens")
    print()


if __name__ == "__main__":
    main()
