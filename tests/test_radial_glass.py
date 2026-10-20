"""Shift menu stays event driven and preserves the safe copy-only drop workflow."""
import os
import time
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, QMimeData, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dragshift import glass, radial


def wait_for(predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate()


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def menu(qt):
    widget = radial.RadialMenu(
        lambda paths: {"Convert": [radial.Item("PDF", key="convert:PDF"),
                                    radial.Item("PNG", key="convert:PNG")],
                       "Tools": [radial.Item("Edit", key="tool:edit")]},
        lambda paths: "Document",
    )
    yield widget
    widget.hide()
    widget.deleteLater()
    qt.processEvents()


def test_popup_does_not_capture_desktop_and_idle_animation_stops(menu, qt, monkeypatch):
    capture = Mock(side_effect=AssertionError("The menu must not capture the desktop"))
    monkeypatch.setattr(glass, "grab_screen", capture)
    menu.popup(QPoint(300, 300), ["document.pdf"])
    wait_for(lambda: menu.anim.state() == menu.anim.State.Stopped)
    assert not menu.frame.isActive()
    assert menu.anim.state() == menu.anim.State.Stopped
    menu._set_hover(0)
    assert menu.frame.isActive()
    wait_for(lambda: not menu.frame.isActive())
    assert menu.spring == [1.0, 0.0]
    assert not menu.frame.isActive()
    capture.assert_not_called()


def test_hide_cancels_hover_switch_and_discards_native_material(menu, qt):
    menu.popup(QPoint(300, 300), ["document.pdf"])
    menu._set_hover(0)
    menu._set_hover(-2)
    assert menu.hub_timer.isActive()
    material = Mock()
    menu._material = material
    menu.hide()
    assert not menu.frame.isActive()
    assert not menu.hub_timer.isActive()
    assert menu.anim.state() == menu.anim.State.Stopped
    assert menu.swap_anim.state() == menu.swap_anim.State.Stopped
    assert menu._material is None
    material.removeFromSuperview.assert_called_once()
    QTest.qWait(450)
    assert menu.ring_idx == 0


def test_drop_remains_copy_only_and_routes_original_paths(menu, qt):
    menu.popup(QPoint(300, 300), ["/tmp/document.pdf"])
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/document.pdf")])
    event = QDropEvent(QPointF(200, 90), Qt.CopyAction | Qt.MoveAction,
                       mime, Qt.LeftButton, Qt.ShiftModifier)
    received = []
    menu.activated.connect(lambda item, paths: received.append((item.key, paths)))
    menu.dropEvent(event)
    qt.processEvents()
    assert event.dropAction() == Qt.CopyAction
    assert event.isAccepted()
    assert received == [("convert:PDF", ["/tmp/document.pdf"])]
    assert not menu.isVisible()
    assert not menu.frame.isActive()


def test_native_material_rebuilds_only_for_changed_topology(menu, qt, monkeypatch):
    from dragshift import platform_mac
    monkeypatch.setattr(radial.sys, "platform", "darwin")
    monkeypatch.setattr(platform_mac, "native_app_available", lambda: True)
    materials = []
    masks = []

    def install(widget, mask, light):
        material = Mock()
        materials.append(material)
        masks.append(mask)
        return material

    monkeypatch.setattr(platform_mac, "install_shaped_material", install)
    menu.popup(QPoint(300, 300), ["document.pdf"])
    assert len(materials) == 1
    menu._set_hover(0)
    menu._tick()
    menu._sync_material()
    assert len(materials) == 1
    ratio = masks[0].devicePixelRatio()
    assert masks[0].pixelColor(round(200 * ratio), round(200 * ratio)).alpha() == 255
    assert masks[0].pixelColor(0, 0).alpha() == 0
    menu.next_ring()
    assert len(materials) == 2
    materials[0].removeFromSuperview.assert_called_once()
    menu.hide()
    materials[1].removeFromSuperview.assert_called_once()
