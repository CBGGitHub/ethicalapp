"""Translations for every Ethical app.

Text in the code stays in English and is wrapped in tr():   tr("Open a file…")
Text with values uses named placeholders filled with .format():   tr("Saved {n} pages").format(n=n)
Text that must stay English where it is kept (file contents, keys) is marked N_("Title Slide") and shown with tr(name).
tr() looks the English text up in apps/locales/<language>.json ({"English text": "translation"}) and falls back to
the English text when there is no translation, so a missing entry never breaks anything.

The language is chosen in the launcher (🌐 menu) and shared by every app; "auto" follows the Windows display
language. A change applies the next time an app starts.

Translators / maintainers: run  .venv\\Scripts\\python apps\\locales\\i18n_tool.py  to collect every tr() text into
apps/locales/template.json and see which texts a language is missing. Keep {placeholders}, HTML tags, & accelerator
letters (one per text), "\\n" line breaks and file patterns like (*.pdf) intact in translations.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES = os.path.join(HERE, "locales")

# code -> name shown in the language menu (in its own language). English is the source language.
LANGUAGES = {
    "en": "English",
    "es": "Español",
    "pt_BR": "Português (Brasil)",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
    "ru": "Русский",
    "id": "Bahasa Indonesia",
    "ja": "日本語",
    "ko": "한국어",
    "zh_CN": "简体中文",
}

_SETTINGS_ORG = "Ethical Suite"     # = suite_common.SETTINGS_ORG (kept here so this module has no Qt-app imports)
_SETTINGS_APP = "Suite"
_catalog = None
_lang = None


def chosen_language():
    """The setting itself: "auto" or a language code."""
    from PySide6.QtCore import QSettings
    return str(QSettings(_SETTINGS_ORG, _SETTINGS_APP).value("language", "auto") or "auto")


def set_language(code):
    """Remember the language for every app ("auto" = follow Windows). Takes effect when an app (re)starts."""
    from PySide6.QtCore import QSettings
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue("language", code)


def _system_language():
    try:
        from PySide6.QtCore import QLocale
        names = QLocale.system().uiLanguages()
    except Exception:
        names = []
    for name in names:
        name = name.replace("-", "_")
        if name in LANGUAGES:
            return name
        if name.startswith("pt"):
            return "pt_BR"          # the only Portuguese we have
        if name.startswith("zh"):
            return "zh_CN"          # (simplified; better than English for traditional-Chinese readers too)
        base = name.split("_")[0]
        if base in LANGUAGES:
            return base
    return "en"


def language():
    """The language in use (a code from LANGUAGES)."""
    global _lang
    if _lang is None:
        code = os.environ.get("ETHICAL_LANGUAGE") or chosen_language()     # env var: for testing
        _lang = code if code in LANGUAGES else _system_language()
    return _lang


def _load():
    global _catalog
    _catalog = {}
    lang = language()
    if lang != "en":
        try:
            with open(os.path.join(LOCALES, lang + ".json"), encoding="utf-8") as fh:
                _catalog = {k: v for k, v in json.load(fh).items() if v}
        except (OSError, ValueError):
            pass
    return _catalog


def tr(text):
    """The text in the user's language (or the English text itself when there is no translation)."""
    cat = _catalog if _catalog is not None else _load()
    return cat.get(text, text)


def N_(text):
    """Marks text for translation without translating it here: for names that are stored in files or used as keys
    (e.g. slide layout names) and translated with tr(name) only where they are shown."""
    return text


def install_qt(app):
    """Called by make_app: Qt's own dialogs (file picker buttons, colour picker, OK/Cancel…) and number/date
    formats in the same language."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    lang = language()
    QLocale.setDefault(QLocale(lang))
    if lang == "en":
        return
    if lang in ("ja", "ko", "zh_CN"):
        _cjk_toolbar_fix(app)
    folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    for name in ("qtbase_" + lang, "qtbase_" + lang.split("_")[0]):
        t = QTranslator(app)
        if t.load(name, folder):
            app.installTranslator(t)
            break


def date_text(d, fmt="long"):
    """A date written the way the user's language does it (QDate/date/datetime)."""
    from PySide6.QtCore import QDate, QLocale
    if not isinstance(d, QDate):
        d = QDate(d.year, d.month, d.day)
    return QLocale().toString(d, QLocale.LongFormat if fmt == "long" else QLocale.ShortFormat)


def day_name(weekday, short=False):
    """Name of a weekday; weekday 0 = Monday (like Python's date.weekday())."""
    from PySide6.QtCore import QLocale
    return QLocale().dayName(weekday + 1, QLocale.ShortFormat if short else QLocale.LongFormat)


def month_name(month, short=False):
    """Name of a month 1-12."""
    from PySide6.QtCore import QLocale
    return QLocale().standaloneMonthName(month, QLocale.ShortFormat if short else QLocale.LongFormat)


def add_items(combo, items, current=None):
    """Fill a QComboBox with translated labels while keeping the English names as the item data: read the choice
    with combo.currentData(), never currentText() (which is translated)."""
    for item in items:
        combo.addItem(tr(item), item)
    if current is not None:
        combo.setCurrentIndex(max(0, combo.findData(current)))


_ACCEL_SUFFIX = None


def _cjk_toolbar_fix(app):
    """Chinese/Japanese/Korean menus write the shortcut letter as "保存(&S)". Toolbar buttons show the action text
    without the "&", which would leave "保存(S)" - so drop the "(S)" there (menus keep it)."""
    import re
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QToolBar
    pattern = re.compile(r"\s*\((?:&)?[A-Za-z0-9]\)(?=\s*(?:\.\.\.|…)?\s*$)")

    class Filter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show and isinstance(obj, QToolBar):
                for a in obj.actions():
                    t = a.iconText()
                    if pattern.search(t):
                        a.setIconText(pattern.sub("", t))
            return False

    global _ACCEL_SUFFIX
    _ACCEL_SUFFIX = Filter(app)
    app.installEventFilter(_ACCEL_SUFFIX)
