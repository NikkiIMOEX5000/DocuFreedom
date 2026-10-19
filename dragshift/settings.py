"""Persistent settings + the Settings and Welcome windows."""
from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSlider, QVBoxLayout)

from . import __version__
from .util import CONFIG
from . import theme
from .window import GlassWindow

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
APP = "DocuFreedom"
ORGANIZATION = "dna.apps"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULTS = {
    "output": "next",
    "jpg_quality": 90,
    "pdf_dpi": 200,
    "trigger": "shift",
    "welcomed": False,
    "last_result": "",
    "icon_style": "docufreedom",
    "theme": "system",
    "favorite_tools": [],
}


class Settings:
    def __init__(self, store=None, legacy_store=None):
        self.q = store if store is not None else QSettings(ORGANIZATION, APP)
        # Keep old preferences readable without rewriting them or losing a user's
        # configuration. New choices belong to the new publisher/app namespace.
        self.legacy = legacy_store if legacy_store is not None else (QSettings("DragShift", "DragShift") if store is None else None)

    def get(self, key):
        default = DEFAULTS[key]
        if self.q.contains(key):
            value = self.q.value(key, default)
        elif self.legacy is not None and self.legacy.contains(key):
            value = self.legacy.value(key, default)
            if key == "icon_style" and value == "ribbon":
                value = DEFAULTS["icon_style"]
        else:
            value = default
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, list):
            if isinstance(value, str):
                import json
                try:
                    value = json.loads(value) if value.startswith("[") else [value]
                except (ValueError, TypeError):
                    value = []
            if not isinstance(value, (list, tuple)):
                return list(default)
            return list(dict.fromkeys(item for item in value if isinstance(item, str)))
        if key == "theme":
            return value if value in {key for key, _ in theme.THEMES} else "system"
        return value

    def set(self, key, value):
        if key == "theme" and value not in {mode for mode, _ in theme.THEMES}:
            value = "system"
        if key == "favorite_tools":
            value = list(dict.fromkeys(str(item) for item in value))
        self.q.setValue(key, value)
        self.apply()

    def apply(self):
        for key in ("output", "jpg_quality", "pdf_dpi"):
            CONFIG[key] = self.get(key)
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            theme.apply_theme(self.get("theme"))


# ---------------------------------------------------------------- autostart (Windows)
def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --quiet'
    return f'"{sys.executable}" -m dragshift --quiet'


def autostart_enabled() -> bool:
    if IS_MAC:
        from . import platform_mac
        return platform_mac.autostart_enabled()
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    if IS_MAC:
        from . import platform_mac
        platform_mac.set_autostart(on)
        return
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


TRIGGERS = ([("shift", "Shift ⇧"), ("ctrl", "Control ⌃"), ("alt", "Option ⌥")] if IS_MAC
            else [("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")])
OUTPUTS = [("next", "Рядом с исходным файлом"), ("folder", "В подпапке «DocuFreedom»")]
DPIS = [(150, "150 dpi · небольшой размер"), (200, "200 dpi · оптимально"), (300, "300 dpi · для печати")]


def _autostart_error(parent, error: Exception):
    QMessageBox.warning(parent, "Не удалось изменить автозапуск",
                        "Настройка входа в систему не была сохранена.\n"
                        "Вы можете повторить попытку в настройках DocuFreedom.\n\n"
                        f"Подробности: {error}")


class SettingsWindow(GlassWindow):
    changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__("Настройки DocuFreedom", size=(680, 580))
        self.setMinimumSize(620, 520)
        self.s = settings
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        r = 0

        def combo(options, current):
            c = QComboBox()
            c.setMinimumWidth(270)
            for v, label in options:
                c.addItem(label, v)
            idx = max(0, [v for v, _ in options].index(current) if current in [v for v, _ in options] else 0)
            c.setCurrentIndex(idx)
            return c

        grid.addWidget(QLabel("Оформление"), r, 0)
        self.theme = combo(theme.THEMES, self.s.get("theme"))
        self.theme.setAccessibleName("Оформление приложения: системное, светлое или тёмное")
        self.theme.currentIndexChanged.connect(lambda _: self._save("theme", self.theme.currentData()))
        grid.addWidget(self.theme, r, 1)
        r += 1

        grid.addWidget(QLabel("Клавиша быстрого меню"), r, 0)
        self.trigger = combo(TRIGGERS, self.s.get("trigger"))
        self.trigger.currentIndexChanged.connect(lambda _: self._save("trigger", self.trigger.currentData()))
        grid.addWidget(self.trigger, r, 1)
        r += 1
        hint = QLabel("Нажмите при перетаскивании файла в Finder" if IS_MAC
                      else "Нажмите при перетаскивании файла")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        grid.addWidget(hint, r, 1)
        r += 1

        grid.addWidget(QLabel("Сохранять результат"), r, 0)
        self.output = combo(OUTPUTS, self.s.get("output"))
        self.output.currentIndexChanged.connect(lambda _: self._save("output", self.output.currentData()))
        grid.addWidget(self.output, r, 1)
        r += 1

        grid.addWidget(QLabel("Качество JPG / WebP"), r, 0)
        row = QHBoxLayout()
        self.q = QSlider(Qt.Horizontal)
        self.q.setRange(60, 100)
        self.q.setValue(self.s.get("jpg_quality"))
        self.qv = QLabel(str(self.q.value()))
        self.qv.setObjectName("dim")
        self.qv.setFixedWidth(30)
        self.q.valueChanged.connect(lambda v: (self.qv.setText(str(v)), self._save("jpg_quality", v)))
        row.addWidget(self.q)
        row.addWidget(self.qv)
        grid.addLayout(row, r, 1)
        r += 1

        grid.addWidget(QLabel("PDF → изображение"), r, 0)
        self.dpi = combo(DPIS, self.s.get("pdf_dpi"))
        self.dpi.currentIndexChanged.connect(lambda _: self._save("pdf_dpi", self.dpi.currentData()))
        grid.addWidget(self.dpi, r, 1)
        r += 1

        from .branding import ICON_CHOICES
        grid.addWidget(QLabel("Иконка интерфейса"), r, 0)
        self.icon_style = combo(ICON_CHOICES, self.s.get('icon_style'))
        self.icon_style.currentIndexChanged.connect(lambda _: self._save('icon_style', self.icon_style.currentData()))
        grid.addWidget(self.icon_style, r, 1)
        r += 1

        if IS_WIN or IS_MAC:
            self.auto = QCheckBox("Запускать при входе в систему")
            self.auto.setChecked(autostart_enabled())
            self.auto.toggled.connect(self._set_autostart)
            grid.addWidget(self.auto, r, 1)
            r += 1
        self.body.addLayout(grid)
        self.body.addStretch(1)
        about = QLabel(f"DocuFreedom {__version__}  ·  dna.apps\nПриложение работает в строке меню")
        about.setObjectName("dim")
        foot = QHBoxLayout()
        foot.addWidget(about)
        foot.addStretch(1)
        done = QPushButton("Готово")
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        foot.addWidget(done)
        self.body.addLayout(foot)
        theme.manager().changed.connect(self._sync_theme)

    def _sync_theme(self, *_):
        index = self.theme.findData(self.s.get("theme"))
        if index >= 0 and index != self.theme.currentIndex():
            self.theme.blockSignals(True)
            self.theme.setCurrentIndex(index)
            self.theme.blockSignals(False)

    def _save(self, key, value):
        self.s.set(key, value)
        self.changed.emit()

    def _set_autostart(self, enabled: bool):
        try:
            set_autostart(enabled)
        except Exception as error:
            self.auto.blockSignals(True)
            self.auto.setChecked(autostart_enabled())
            self.auto.blockSignals(False)
            _autostart_error(self, error)


class WelcomeWindow(GlassWindow):
    def __init__(self, settings: Settings, trigger_label: str = "Shift"):
        super().__init__("Добро пожаловать в DocuFreedom", size=(650, 400))
        self.setMinimumSize(610, 350)
        self.s = settings
        steps = [
            ("1", "Откройте DocuFreedom из строки меню", "Значок с двумя квадратами → «Открыть полное приложение»"),
            ("2", "Добавьте файлы или откройте PDF-студию", "Изображения, документы, OCR, страницы, подписи и преобразование"),
            ("3", "Откройте готовый результат", "Новый файл сохраняется рядом с исходным. Оригинал не меняется"),
            ("⇧", f"Быстрое меню: перетаскивание + {trigger_label}",
             "Перетащите файл на нужный сектор. Нажмите клавишу ещё раз, чтобы сменить раздел"),
        ]
        for n, head, sub in steps:
            row = QHBoxLayout()
            badge = QLabel(n)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(34, 34)
            badge.setObjectName("welcomeBadge")
            row.addWidget(badge)
            col = QVBoxLayout()
            col.setSpacing(0)
            h = QLabel(head)
            h.setStyleSheet("font-size: 12pt; font-weight: 600;")
            d = QLabel(sub)
            d.setObjectName("dim")
            d.setWordWrap(True)
            h.setWordWrap(True)
            col.addWidget(h)
            col.addWidget(d)
            row.addSpacing(8)
            row.addLayout(col, 1)
            self.body.addLayout(row)
        self.body.addStretch(1)
        foot = QHBoxLayout()
        if IS_WIN or IS_MAC:
            self.auto = QCheckBox("Запускать при входе в систему")
            self.auto.setChecked(autostart_enabled())
            foot.addWidget(self.auto)
        foot.addStretch(1)
        ok = QPushButton("Начать работу")
        ok.setObjectName("primary")
        ok.clicked.connect(self._done)
        foot.addWidget(ok)
        self.body.addLayout(foot)

    def _done(self):
        if IS_WIN or IS_MAC:
            try:
                if self.auto.isChecked() != autostart_enabled():
                    set_autostart(self.auto.isChecked())
            except Exception as error:
                self.auto.setChecked(autostart_enabled())
                _autostart_error(self, error)
                return
        self.s.set("welcomed", True)
        self.close()
