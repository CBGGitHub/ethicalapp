# EthicalApp

![EthicalApp icons](branding/preview.png)

**Free desktop apps for Windows that are actually free – no subscriptions, no watermarks, no accounts, no ads,
no tracking.** Made by [CraftingBenchGames](https://craftingbenchgames.com/).

**Download:** <https://ethicalapp.org> · **Free online tools** (run in your browser, nothing uploaded):
<https://ethicalapp.org/tools>

| App | What it does |
|-----|--------------|
| **EthicalApp** (launcher) | One window with all your installed apps; open or drop any file and it goes to the right app |
| **Ethical PDF Editor** | View, edit text, annotate, fill forms, sign, merge/split PDFs |
| **Ethical Document Editor** | Write documents; opens and saves Word `.docx` files |
| **Ethical Spreadsheet Editor** | Spreadsheets with 143 formulas & charts; opens and saves Excel `.xlsx` files |
| **Ethical Presentation Editor** | Slide decks & slideshows; opens and saves PowerPoint `.pptx` files |
| **Ethical Photo Editor** | Layer-based photo editor; opens and saves Photoshop `.psd` with layers, plus PNG/JPG/WebP… |
| **Ethical Converter** | Convert & compress audio, video, pictures, documents; trim videos; combine; zip/unzip |
| **Ethical Database** | Databases: tables, forms, queries, relationships, reports |
| **Ethical Sticky Notes** | Notes and to-do lists that stay on your desktop |
| **Ethical Snip** | Screenshots (area / window / full screen / free-form) you can mark up, pixelate, crop |
| **Ethical Planner** | Reminders and calendar events that pop up on time, with Done/Snooze |

**Languages:** English, Español, Português (Brasil), Français, Deutsch, Italiano, Nederlands, Polski, Türkçe,
Русский, Bahasa Indonesia, 日本語, 한국어, 简体中文 – the apps follow your Windows language, or pick one with the 🌐
button in the EthicalApp window. Translations live in `apps/locales/` (apps), `guide/i18n/` (guide) and
`installer/setup_i18n.py` (installer); corrections are welcome.

Press **F1** in any app for the searchable offline user guide. Optional: connect the apps to **Claude** (AI
assistant) so it can use them for you – the installer offers this.

## Install
Download the installer from <https://ethicalapp.org> – no admin password needed, choose which apps you want,
uninstall any time from Settings → Apps. Windows may show "Windows protected your PC" for a new program: click
**More info → Run anyway**. You can check the download is genuine with the SHA-256 fingerprint shown on the site.

## Build the installer from source
1. Install **Python 3.14** and **Inno Setup 6** (`winget install JRSoftware.InnoSetup`).
2. In this folder:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\python installer\build.py
   ```
3. The installer appears in `dist\EthicalApp-Setup-<version>.exe`.

GitHub Actions builds the same installer from this repository (`.github/workflows/build.yml`).

## Code signing policy
Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

- Only installers built by this repository's GitHub Actions workflow (`.github/workflows/build.yml`), from the
  source code published here, are signed. Nothing built anywhere else is signed.
- **Committers and reviewers:** [CraftingBenchGames (@CBGGitHub)](https://github.com/CBGGitHub)
- **Approvers:** [CraftingBenchGames (@CBGGitHub)](https://github.com/CBGGitHub) – every signing request is approved
  by hand before a release.

**Privacy:** EthicalApp will not transfer any information to other networked systems unless specifically requested by
the user or the person installing or operating it. Files are opened, edited and saved only on your own computer.
There is no telemetry, tracking or automatic update check. The optional connection to Claude (an AI assistant) is
off by default; when the user turns it on and asks Claude to work with a file, that content is handled by Claude
under Anthropic's privacy policy. See also <https://ethicalapp.org/privacy>.

## Licence
**AGPL-3.0** (`LICENSE`). EthicalApp is built on open-source components (Qt/PySide6, PyMuPDF, FFmpeg, python-docx,
openpyxl, python-pptx, Pillow and more) – their licences are in `licenses/` and listed in each installation's
`licenses` folder. Not affiliated with Microsoft or Adobe.


