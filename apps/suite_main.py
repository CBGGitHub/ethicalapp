"""Entry point of the installed EthicalApp (built into EthicalSuite.exe and EthicalSuiteCLI.exe).

EthicalSuite.exe <app> [file]      app = pdf, document, spreadsheet, presentation, photo, converter,
                                    database, stickynotes, snip, planner, guide, launcher   (no app: the launcher window with all apps)
EthicalSuiteCLI.exe mcp [--apps …]           run the MCP server for Claude
EthicalSuiteCLI.exe install-mcp [options]    connect/disconnect Claude
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run_app(key, rest):
    sys.argv = [sys.argv[0]] + rest
    if key == "pdf":
        import pdf_editor as m
    elif key == "document":
        import word_processor as m
    elif key == "spreadsheet":
        import sheets_app as m
    elif key == "presentation":
        import slides_app as m
    elif key == "photo":
        import photo_app as m
    elif key == "converter":
        import converter_app as m
    elif key == "database":
        import base_app as m
    elif key == "stickynotes":
        import sticky_notes as m
    elif key == "snip":
        import snip_app as m
    elif key == "planner":
        import planner_app as m
    else:
        raise SystemExit(f"Unknown app {key!r}")
    m.main()


def launcher(rest=()):
    """The EthicalApp window that shows all installed apps (apps/suite_launcher.py)."""
    sys.argv = [sys.argv[0], *rest]
    import suite_launcher
    suite_launcher.main()


def main():
    args = sys.argv[1:]
    if not args:
        launcher()
        return
    cmd, rest = args[0].lower(), args[1:]
    if cmd == "launcher":
        launcher(rest)
    elif cmd == "guide":
        from PySide6.QtWidgets import QApplication
        from suite_common import open_guide
        QApplication.instance() or QApplication(sys.argv)
        open_guide(rest[0] if rest else "")
    elif cmd == "mcp":
        sys.argv = [sys.argv[0]] + rest
        import mcp_server
        mcp_server.main()
    elif cmd == "install-mcp":
        sys.argv = [sys.argv[0]] + rest
        import install_mcp
        install_mcp.main()
    elif cmd in ("pdf", "document", "spreadsheet", "presentation", "photo", "converter", "database", "stickynotes", "snip", "planner"):
        run_app(cmd, rest)
    elif os.path.exists(args[0]):
        # a file was dropped on the exe: pick the app by extension
        from suite_common import EXT_APP
        key = EXT_APP.get(os.path.splitext(args[0])[1].lower())
        if key:
            run_app(key, args)
        else:
            run_app("converter", args)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
