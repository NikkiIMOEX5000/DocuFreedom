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
    """Small floppy-eared dog outline, drawn as a macOS template image."""
    pix = QPixmap(66, 66)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(3, 3)
    painter.setPen(QPen(Qt.black, 1.45, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)

    outline = QPainterPath(QPointF(7, 4.7))
    outline.cubicTo(8.4, 2.7, 13.6, 2.7, 15, 4.7)
    outline.cubicTo(16.5, 4.1, 18, 6.8, 19, 11.1)
    outline.cubicTo(20, 15.1, 18.8, 17.4, 16.9, 15.8)
    outline.lineTo(15.6, 14.4)
    outline.cubicTo(15.1, 17.4, 13.5, 18.8, 11, 18.8)
    outline.cubicTo(8.5, 18.8, 6.9, 17.4, 6.4, 14.4)
    outline.lineTo(5.1, 15.8)
    outline.cubicTo(3.2, 17.4, 2, 15.1, 3, 11.1)
    outline.cubicTo(4, 6.8, 5.5, 4.1, 7, 4.7)
    painter.drawPath(outline)

    ears = QPainterPath(QPointF(7, 4.7))
    ears.cubicTo(6.3, 7, 6.1, 11.3, 6.4, 14.4)
    ears.moveTo(15, 4.7)
    ears.cubicTo(15.7, 7, 15.9, 11.3, 15.6, 14.4)
    painter.drawPath(ears)

    # Tiny eyes and a nose keep the contour recognizable at 19 menu-bar points.
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.black)
    painter.drawEllipse(QPointF(8.6, 10.5), .65, .75)
    painter.drawEllipse(QPointF(13.4, 10.5), .65, .75)
    nose = QPainterPath(QPointF(9.7, 13.3))
    nose.cubicTo(9.7, 12.6, 12.3, 12.6, 12.3, 13.3)
    nose.cubicTo(12.3, 13.8, 11.4, 14.5, 11, 14.5)
    nose.cubicTo(10.6, 14.5, 9.7, 13.8, 9.7, 13.3)
    painter.drawPath(nose)
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
