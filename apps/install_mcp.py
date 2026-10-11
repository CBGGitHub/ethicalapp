"""Connect the EthicalApp MCP server to Claude (Claude Code and/or Claude Desktop) — or disconnect it.

Interactive:      .venv\\Scripts\\python apps\\install_mcp.py              (asks which apps to enable)
Non-interactive:  .venv\\Scripts\\python apps\\install_mcp.py --apps pdf,document,spreadsheet --client all
Remove:           .venv\\Scripts\\python apps\\install_mcp.py --remove
Apps: pdf, document, spreadsheet, presentation, photo, converter, database (the guide tools are always on).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(HERE, "mcp_server.py")
NAME = "ethical-suite"
APPS = [("pdf", "Ethical PDF Editor"), ("document", "Ethical Document Editor"),
        ("spreadsheet", "Ethical Spreadsheet Editor"), ("presentation", "Ethical Presentation Editor"),
        ("photo", "Ethical Photo Editor"), ("converter", "Ethical Converter"), ("database", "Ethical Database"),
        ("stickynotes", "Ethical Sticky Notes"), ("snip", "Ethical Snip"),
        ("planner", "Ethical Planner")]
DESKTOP_CONFIG = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json")


def python_exe():
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"   # MCP talks over stdin/stdout, which pythonw doesn't have
    return exe


def claude_cli():
    return shutil.which("claude") or next((p for p in (os.path.expanduser(r"~\.local\bin\claude.exe"),)
                                           if os.path.exists(p)), None)


def install_code(apps):
    cli = claude_cli()
    if not cli:
        return "Claude Code: not found (skipped)."
    subprocess.run([cli, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, text=True)
    from suite_common import mcp_command
    r = subprocess.run([cli, "mcp", "add", NAME, "--scope", "user", "--", *mcp_command(apps)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return f"Claude Code: failed - {(r.stderr or r.stdout).strip()[:300]}"
    return "Claude Code: connected (all your projects)."


def remove_code():
    cli = claude_cli()
    if not cli:
        return "Claude Code: not found."
    r = subprocess.run([cli, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, text=True)
    return "Claude Code: removed." if r.returncode == 0 else "Claude Code: wasn't connected."


def install_desktop(apps, force=False):
    folder = os.path.dirname(DESKTOP_CONFIG)
    if not os.path.isdir(folder) and not force:
        return "Claude Desktop: not installed (skipped)."
    os.makedirs(folder, exist_ok=True)
    cfg = {}
    if os.path.exists(DESKTOP_CONFIG):
        try:
            cfg = json.load(open(DESKTOP_CONFIG, encoding="utf-8"))
            shutil.copy2(DESKTOP_CONFIG, DESKTOP_CONFIG + ".bak")
        except (OSError, json.JSONDecodeError):
            return "Claude Desktop: couldn't read its settings file (left unchanged)."
    from suite_common import mcp_command
    cmd = mcp_command(apps)
    cfg.setdefault("mcpServers", {})[NAME] = {"command": cmd[0], "args": cmd[1:]}
    with open(DESKTOP_CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return "Claude Desktop: connected - restart Claude Desktop to load it."


def remove_desktop():
    if not os.path.exists(DESKTOP_CONFIG):
        return "Claude Desktop: not installed."
    cfg = json.load(open(DESKTOP_CONFIG, encoding="utf-8"))
    if cfg.get("mcpServers", {}).pop(NAME, None) is None:
        return "Claude Desktop: wasn't connected."
    with open(DESKTOP_CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return "Claude Desktop: removed - restart Claude Desktop."


def ask_apps():
    print("Which apps should Claude be able to use?  (the user guide is always included)\n")
    for i, (key, name) in enumerate(APPS, 1):
        print(f"  {i}. {name}")
    ans = input("\nType numbers separated by commas, or just press Enter for all: ").strip()
    if not ans:
        return [k for k, _ in APPS]
    picked = []
    for part in ans.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= len(APPS):
            picked.append(APPS[int(part) - 1][0])
    return picked or [k for k, _ in APPS]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apps", help="comma list, e.g. pdf,document (default: ask, or all when --yes)")
    ap.add_argument("--client", choices=["code", "desktop", "all"], default="all")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--yes", action="store_true", help="don't ask anything (all apps unless --apps)")
    args = ap.parse_args()
    if args.remove:
        if args.client in ("code", "all"):
            print(remove_code())
        if args.client in ("desktop", "all"):
            print(remove_desktop())
        return
    if args.apps:
        apps = [a.strip() for a in args.apps.split(",") if a.strip() in dict(APPS)]
    elif args.yes or not sys.stdin.isatty():
        apps = [k for k, _ in APPS]
    else:
        apps = ask_apps()
    print(f"\nEnabling: {', '.join(dict(APPS)[a] for a in apps)} + the user guide\n")
    if args.client in ("code", "all"):
        print(install_code(apps))
    if args.client in ("desktop", "all"):
        print(install_desktop(apps, force=args.client == "desktop"))
    print("\nTry asking Claude: 'Use EthicalApp to turn my notes.md into a Word document' or "
          "'Make a 5-slide deck about our plan and open it'.")


if __name__ == "__main__":
    main()
