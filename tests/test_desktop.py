"""The desktop must never silently drop selected files or delete originals."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from dragshift import desktop
from dragshift.radial import Item
from dragshift.report import Result


class Controller:
    def __init__(self, qapp):
        self.qapp = qapp
        self.settings = self
        self.calls = []

    def get(self, key):
        return "next"

    def trigger_label(self):
        return "Shift ⇧"

    def open_dialog(self):
        pass

    open_settings = show_welcome = request_quit = open_dialog

    def build_rings(self, paths):
        return {"Convert": [Item("PNG", key="convert:PNG")],
                "Tools": [Item("Crop", key="tool:Crop"), Item("Resize", key="tool:Resize")]}

    def run_item(self, item, paths):
        self.calls.append((item.key, paths))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    controller = Controller(qapp)
    window = desktop.DesktopWindow(controller)
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


def source(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"test file")
    return path


def test_mixed_selection_requires_explicit_subset(window, tmp_path):
    image = source(tmp_path, "photo.png")
    pdf = source(tmp_path, "document.pdf")
    window.set_files([str(image), str(pdf)])
    assert not window.convert_button.isEnabled()
    assert "разные типы" in window.warning.text()
    window.file_list.item(0).setSelected(True)
    assert window.convert_button.isEnabled()
    window.convert_button.click()
    assert window.controller.calls == [("convert:PNG", [str(image)])]


def test_rejects_unsupported_paths_with_visible_reason(window, tmp_path):
    video = source(tmp_path, "movie.mov")
    window.set_files([str(video), str(tmp_path)])
    assert window.files == []
    assert "movie.mov" in window.banner_text.text()
    assert "поддерживаемые" in window.banner_text.text()


def test_accessibility_checked_state_changes_navigation(window):
    window.history_nav.setChecked(True)
    assert window.pages.currentIndex() == 1
    assert not window.workspace_nav.isChecked()
    window.workspace_nav.setChecked(True)
    assert window.pages.currentIndex() == 0
    assert not window.history_nav.isChecked()
    window.workspace_nav.click()
    assert window.workspace_nav.isChecked()
    assert window.pages.currentIndex() == 0


def test_view_menu_changes_page_and_sidebar_selection(window):
    menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "Вид")
    menu.actions()[1].trigger()
    assert window.pages.currentIndex() == 1
    assert window.history_nav.isChecked()
    menu.actions()[0].trigger()
    assert window.pages.currentIndex() == 0
    assert window.workspace_nav.isChecked()


def test_single_file_editors_and_busy_actions(window, tmp_path):
    first = source(tmp_path, "one.png")
    second = source(tmp_path, "two.png")
    window.set_files([str(first), str(second)])
    assert not window._tool_buttons[0].isEnabled()  # Crop processes one image.
    assert window._tool_buttons[1].isEnabled()  # Resize supports a batch.
    window.set_busy(True)
    window.convert_button.click()
    assert not window.convert_button.isEnabled()
    assert window.controller.calls == []
    window.set_busy(False)
    assert window.convert_button.isEnabled()


def test_failed_trash_never_deletes_result_or_original(window, tmp_path, monkeypatch):
    original = source(tmp_path, "original.png")
    output = source(tmp_path, "converted.png")
    attempts = []

    def failed_trash(path):
        attempts.append(path)
        return False, ""

    monkeypatch.setattr(desktop.QFile, "moveToTrash", failed_trash)
    window.record_result(Result("Converted", "", [original, output], [original]))
    card = window._results[0]
    undo = next(button for button in card.findChildren(QPushButton)
                if button.text() == "Отменить результат")
    undo.click()
    assert attempts == [str(output)]
    assert original.read_bytes() == b"test file"
    assert output.read_bytes() == b"test file"
    assert undo.isEnabled()  # A failed trash operation can be retried.
