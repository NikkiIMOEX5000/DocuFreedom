"""DocuFreedom by dna.apps: artwork and native macOS material helpers."""
from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QSettings
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

APP_NAME = "DocuFreedom"
PUBLISHER = "dna.apps"
DONATION_ADDRESS = "TNHazdSaijRvjL9YL3oy8widVkaNdf6SFw"
ICON_CHOICES = [("docufreedom", "DocuFreedom · собака"), ("apex", "Apex · угловой монограммный"),
                ("orbit", "Orbit · светлый круг"), ("ribbon", "Ribbon · треугольная лента")]


def icon_path(choice=None):
    choice = choice or QSettings("dna.apps", "DocuFreedom").value("icon_style", "docufreedom")
    if choice not in {key for key, _ in ICON_CHOICES}:
        choice = "docufreedom"
    return Path(__file__).with_name("assets") / "branding" / f"{choice}.png"


def app_icon(choice=None):
    return QIcon(str(icon_path(choice)))


def tray_icon():
    """Two overlapping sheets with a clean negative-space separation."""
    pix = QPixmap(66, 66)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(1.5, 1.5)
    painter.setPen(QPen(Qt.black, 3.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(6, 5, 25, 26), 5, 5)
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.black)
    painter.drawRoundedRect(QRectF(13, 12, 27, 28), 6, 6)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.setPen(QPen(Qt.black, 3.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(15, 14, 24, 25), 5, 5)
    painter.end()
    pix.setDevicePixelRatio(3)
    icon = QIcon(pix)
    icon.setIsMask(True)
    return icon


def install_native_material(widget, radius=20):
    """NSVisualEffectView blur, without reading or capturing the screen."""
    if sys.platform != "darwin":
        return None
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() != "cocoa":
        return None
    try:
        import AppKit
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        parent = view.superview()
        if parent is None:
            return None
        effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(view.frame())
        effect.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        effect.setMaterial_(AppKit.NSVisualEffectMaterialPopover)
        effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(AppKit.NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(radius)
        effect.layer().setMasksToBounds_(True)
        # QWidget paints its whole hierarchy into the content view's backing
        # layer. A native child sits above that layer and hides all controls;
        # the material must be a sibling behind the Qt content view instead.
        parent.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, view)
        window = view.window()
        if window:
            window.setOpaque_(False)
            window.setBackgroundColor_(AppKit.NSColor.clearColor())
            window.setHasShadow_(True)
        return effect
    except Exception:
        return None
