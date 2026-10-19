"""Theme changes and pinned tools are persistent UI behavior, not static CSS checks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from dragshift import theme
from dragshift.settings import Settings, SettingsWindow
from dragshift.pdf_workspace import PdfWorkspace, PdfEditor, ToolDialog, TOOLS
from dragshift.convert import fitz


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    theme.apply_theme("system")


@pytest.fixture
def settings(tmp_path):
    return Settings(store=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))


class Controller:
    def __init__(self, settings):
        self.settings = settings
        self.windows = []
        self.jobs = []
    def open_window(self, window):
        self.windows.append(window)
    def submit(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def tool(key):
    return next(item for item in TOOLS if item.key == key)


def test_settings_preserve_legacy_read_only_and_new_identity(tmp_path, qapp):
    legacy = QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat)
    store = QSettings(str(tmp_path / "new.ini"), QSettings.IniFormat)
    legacy.setValue("jpg_quality", 82)
    legacy.setValue("icon_style", "ribbon")
    legacy.sync()
    before = Path(legacy.fileName()).read_bytes()
    prefs = Settings(store, legacy)
    assert prefs.get("jpg_quality") == 82
    assert prefs.get("icon_style") == "docufreedom"
    prefs.set("theme", "dark")
    prefs.set("favorite_tools", ["merge", "compress", "merge"])
    store.sync()
    reopened = Settings(QSettings(store.fileName(), QSettings.IniFormat), legacy)
    assert reopened.get("theme") == "dark"
    assert reopened.get("favorite_tools") == ["merge", "compress"]
    assert Path(legacy.fileName()).read_bytes() == before


def test_live_theme_updates_existing_main_dialog_editor_and_system(qapp, settings, tmp_path, monkeypatch):
    source = tmp_path / "Document.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((30, 30), "Unchanged paper")
        document.save(source)
    controller = Controller(settings)
    main = QMainWindow()
    theme.register_window(main)
    dialog = ToolDialog(tool("compress"), [str(source)], controller)
    editor = PdfEditor(str(source), controller)
    try:
        settings.set("theme", "dark")
        qapp.processEvents()
        for window in (main, dialog, editor):
            assert window.property("docuFreedomTheme") == "dark"
            assert theme.tokens("dark")["surface"] in window.styleSheet()
        assert qapp.palette().color(QPalette.Window).name() == theme.tokens("dark")["window"].lower()
        assert editor.canvas.styleSheet() == "background: white;", "PDF paper must stay white"
        settings.set("theme", "light")
        assert all(w.property("docuFreedomTheme") == "light" for w in (main, dialog, editor))
        monkeypatch.setattr(theme, "_system_theme", lambda: "dark")
        settings.set("theme", "system")
        assert main.property("docuFreedomTheme") == "dark"
        monkeypatch.setattr(theme, "_system_theme", lambda: "light")
        theme.manager()._system_changed(Qt.ColorScheme.Light)
        assert editor.property("docuFreedomTheme") == "light"
        settings.set("theme", "dark")
        theme.manager()._system_changed(Qt.ColorScheme.Light)
        assert main.property("docuFreedomTheme") == "dark", "explicit choice must ignore OS changes"
    finally:
        editor.dirty = False
        editor.close()
        main.close()
        dialog.close()
        editor.deleteLater()
        main.deleteLater()
        dialog.deleteLater()
        qapp.processEvents()


def test_theme_selector_applies_immediately(qapp, settings, monkeypatch):
    import dragshift.settings as module
    monkeypatch.setattr(module, "autostart_enabled", lambda: False)
    window = SettingsWindow(settings)
    try:
        window.theme.setCurrentIndex(window.theme.findData("dark"))
        assert settings.get("theme") == "dark"
        assert window.property("docuFreedomTheme") == "dark"
        settings.set("theme", "light")
        assert window.theme.currentData() == "light"
        settings.set("theme", "system")
        assert window.theme.currentData() == "system"
        assert "DocuFreedom" in window.windowTitle()
    finally:
        window.close()
        qapp.processEvents()


def test_favorites_buttons_persist_order_without_launching_tool(qapp, settings):
    controller = Controller(settings)
    workspace = PdfWorkspace(controller, lambda: [])
    workspace.resize(1100, 800)
    workspace.show()
    qapp.processEvents()
    try:
        pin = workspace.favorite_buttons["compress"]
        QTest.mouseClick(pin, Qt.LeftButton)
        qapp.processEvents()
        assert settings.get("favorite_tools") == ["compress"]
        assert pin.isChecked() and pin.text() == "★"
        assert "Убрать" in pin.accessibleName()
        assert not controller.jobs and not controller.windows and not workspace.dialogs
        workspace.toggle_favorite("merge")
        ordered = [workspace.grid.itemAt(i).widget() for i in range(workspace.grid.count())]
        by_key = {item.key: card for item, card in workspace.cards}
        assert ordered[:3] == [by_key["editor"], by_key["compress"], by_key["merge"]]
        assert workspace.grid.getItemPosition(0)[3] == 3, "editor is a featured full-width card"
        restored = PdfWorkspace(Controller(settings), lambda: [])
        try:
            assert restored.favorites == ["compress", "merge"]
            assert [item.key for item in restored.favorite_tools()] == ["compress", "merge"]
        finally:
            restored.close()
            restored.deleteLater()
        workspace.toggle_favorite("compress")
        assert settings.get("favorite_tools") == ["merge"]
        assert not pin.isChecked()
        pin.setFocus()
        QTest.keyClick(pin, Qt.Key_Space)
        assert settings.get("favorite_tools") == ["merge", "compress"]
        assert not controller.jobs and not workspace.dialogs
    finally:
        workspace.close()
        workspace.deleteLater()
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_search_words_case_punctuation_favorites_and_no_results(qapp, settings):
    settings.set("favorite_tools", ["not-a-tool", "compress", "merge"])
    workspace = PdfWorkspace(Controller(settings), lambda: [])
    try:
        assert workspace.favorites == ["compress", "merge"]
        workspace.search.setText("  PDF: СЖАТЬ  ")
        assert [spec.key for spec, card in workspace.cards if not card.isHidden()] == ["compress"]
        workspace.search.setText("MERGE pdf")
        assert [spec.key for spec, card in workspace.cards if not card.isHidden()] == ["merge"]
        workspace.search.clear()
        workspace.group.setCurrentText("Избранное")
        assert {spec.key for spec, card in workspace.cards if not card.isHidden()} == {"compress", "merge"}
        workspace.search.setText("несуществующий инструмент 995")
        assert all(card.isHidden() for _, card in workspace.cards)
        assert not workspace.empty_hint.isHidden()
        assert workspace.result_count.text() == "Инструментов: 0"
        workspace.search.clear()
        workspace.group.setCurrentText("Все инструменты")
        assert workspace.empty_hint.isHidden()
        workspace.set_busy(True)
        assert all(not pin.isEnabled() for pin in workspace.favorite_buttons.values())
    finally:
        workspace.close()
        workspace.deleteLater()
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
