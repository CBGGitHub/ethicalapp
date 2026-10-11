@echo off
rem Connect the Ethical Suite apps to Claude (Claude Code / Claude Desktop) so Claude can use them.
cd /d "%~dp0"
".venv\Scripts\python.exe" apps\install_mcp.py %*
pause
