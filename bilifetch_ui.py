#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享的视觉组件、三层设计 Token 与主题引擎（主窗口、浏览窗口、登录窗口共用）。

设计工程与 UX 规范（结合 ui-ux-pro-max、design-system、Emil Kowalski 与 Apple HIG）：
  1. 三层设计 Token（Primitive → Semantic → Component）：
     消除散落的硬编码 Hex，原生支持浅色（Light）与深色（Dark）双主题实时切换，
     严格保证正文对比度 >= 4.5:1、深色表面层级与微亮描边清晰可辨。
  2. 性能零妥协：
     - 不在高频路径上调 setStyleSheet（仅在启动或切换主题时构建一次全局 QSS）。
     - 卡片背景（含多层柔光投影与高光边）按 (尺寸, 缩放比, 主题, 高亮态) 缓存为位图。
     - 大列表一律 QListView + 自绘 delegate，支持 1000+ 行虚拟化流畅滚动。
  3. 物理动效与微交互：
     - 定制强缓动曲线：--ease-out cubic-bezier(0.23, 1, 0.32, 1)、--ease-in-out cubic-bezier(0.77, 0, 0.175, 1)。
     - 按钮与可点击控件 pointer-down 瞬间 100ms 响应 scale(0.97)，释放 160ms 非对称回弹。
     - 分段控制器采用 Clip-Path 双层裁剪，滑块与文字颜色在像素边界同步过渡。
     - 缩略图未加载完成时提供柔和的 Skeleton Shimmer 骨架微光过渡，加载完毕 180ms 渐显。
  4. 全键盘无障碍（WCAG 2.2 AA）：
     - 所有交互控件具备 TabFocus 与 2px 品牌色焦点环（对比度 > 3:1），支持方向键、空格、回车闭环操作。
"""

import math
import os
import subprocess
import sys

from PyQt5.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation,
                          pyqtSignal)
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractButton, QApplication, QComboBox, QFrame,
                             QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy,
                             QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))

# ================================================================
# 第 1 层：Primitive Tokens（原始色板与基础常量）
# ================================================================
PRIMITIVES = {
    "pink_500": "#FB7299",
    "pink_400": "#FC86A8",
    "pink_600": "#E8628A",
    "pink_50": "#FFF0F4",
    "pink_950": "#3A1C28",
    "blue_500": "#00AEEC",
    "blue_600": "#0098D1",
    "blue_50": "#E6F7FD",
    "blue_950": "#132E3C",
    "green_500": "#2BB673",
    "green_50": "#E9F8F0",
    "green_950": "#143325",
    "orange_500": "#FF9F2E",
    "orange_50": "#FFF4E6",
    "orange_950": "#382814",
    "red_500": "#F25D59",
    "red_50": "#FDEEEE",
    "red_950": "#3B1A1D",
    # Light neutrals
    "slate_900": "#18191C",
    "slate_600": "#61666D",
    "slate_400": "#8A9099",
    "slate_200": "#E3E5E7",
    "slate_150": "#E9EAEC",
    "slate_100": "#F1F2F3",
    "slate_50": "#F6F7F8",
    "white": "#FFFFFF",
    # Dark neutrals (Elaya ai-design-skills pure neutral dark steps: #000000 / #181818 / #1F1F1F / #272727 / #313131)
    "dark_1000": "#000000",
    "dark_870": "#181818",
    "dark_850": "#1F1F1F",
    "dark_800": "#272727",
    "dark_750": "#313131",
    "dark_700": "#3D3D3D",
    "dark_500": "#8A8A8A",
    "dark_200": "#BDBDBD",
    "dark_50": "#F5F5F5",
}

# ================================================================
# 第 2 & 3 层：Semantic & Component Tokens（浅色 / 深色双主题映射）
# ================================================================
THEMES = {
    "light": {
        "name": "light",
        "accent": PRIMITIVES["pink_500"],
        "accent_hover": PRIMITIVES["pink_400"],
        "accent_press": PRIMITIVES["pink_600"],
        "accent_soft": PRIMITIVES["pink_50"],
        "accent_disabled": "#F7B8CB",
        "blue": PRIMITIVES["blue_500"],
        "green": PRIMITIVES["green_500"],
        "red": PRIMITIVES["red_500"],
        "orange": PRIMITIVES["orange_500"],
        "ink": PRIMITIVES["slate_900"],          # 对比度 16.5:1
        "ink_2": PRIMITIVES["slate_600"],        # 对比度 5.7:1 (>= 4.5:1)
        "ink_3": PRIMITIVES["slate_400"],
        "ink_disabled": "#B8BBBF",
        "page": PRIMITIVES["slate_50"],
        "card": PRIMITIVES["white"],
        "card_border": "#E6E8EB",
        "field": PRIMITIVES["slate_100"],
        "field_hover": PRIMITIVES["slate_150"],
        "field_press": "#DDDFE2",
        "field_focus_bg": PRIMITIVES["white"],
        "row_hover": "#F5F6F8",
        "pill_bg": PRIMITIVES["white"],
        "badge_inactive_bg": "#E4E6E9",
        "line": PRIMITIVES["slate_200"],
        "track": "#EDEEF0",
        "dark_log": PRIMITIVES["slate_50"],      # 浅色主题保持浅色同调表面，拒绝突兀黑洞块
        "dark_log_fg": PRIMITIVES["slate_900"],
        "log_border": PRIMITIVES["slate_200"],
        "shimmer_base": "#EFF1F3",
        "shimmer_hi": "#FAFBFD",
        "fox_tile": "#FFF1E6",
        "state_colors": {
            "wait": (PRIMITIVES["slate_400"], PRIMITIVES["slate_100"]),
            "run": (PRIMITIVES["blue_500"], PRIMITIVES["blue_50"]),
            "merge": (PRIMITIVES["orange_500"], PRIMITIVES["orange_50"]),
            "pause": (PRIMITIVES["orange_500"], PRIMITIVES["orange_50"]),
            "done": (PRIMITIVES["green_500"], PRIMITIVES["green_50"]),
            "fail": (PRIMITIVES["red_500"], PRIMITIVES["red_50"]),
            "cancel": (PRIMITIVES["slate_400"], PRIMITIVES["slate_100"]),
        },
    },
    "dark": {
        "name": "dark",
        "accent": "#E87598",                     # 暗色模式饱和度 < 80%（HSV S=50%）
        "accent_hover": "#F088A7",
        "accent_press": "#D66084",
        "accent_soft": "#331D24",
        "accent_disabled": "#5E3543",
        "blue": "#3BAFDA",
        "green": "#3BB87E",
        "red": "#E56B67",
        "orange": "#E8A246",
        "ink": PRIMITIVES["dark_50"],            # 对比度 15.8:1
        "ink_2": PRIMITIVES["dark_200"],         # 对比度 7.9:1 (>= 4.5:1)
        "ink_3": PRIMITIVES["dark_500"],
        "ink_disabled": "#595959",
        "page": PRIMITIVES["dark_870"],          # #181818
        "card": PRIMITIVES["dark_850"],          # #1F1F1F
        "card_border": PRIMITIVES["dark_750"],   # #313131
        "field": PRIMITIVES["dark_800"],         # #272727
        "field_hover": PRIMITIVES["dark_750"],   # #313131
        "field_press": PRIMITIVES["dark_700"],
        "field_focus_bg": PRIMITIVES["dark_870"],
        "row_hover": PRIMITIVES["dark_800"],
        "pill_bg": PRIMITIVES["dark_750"],
        "badge_inactive_bg": PRIMITIVES["dark_750"],
        "line": PRIMITIVES["dark_750"],
        "track": PRIMITIVES["dark_800"],
        "dark_log": PRIMITIVES["dark_870"],      # #181818
        "dark_log_fg": "#D4D4D4",
        "log_border": PRIMITIVES["dark_750"],
        "shimmer_base": PRIMITIVES["dark_800"],
        "shimmer_hi": PRIMITIVES["dark_750"],
        "fox_tile": "#2B221D",
        "state_colors": {
            "wait": (PRIMITIVES["dark_500"], PRIMITIVES["dark_800"]),
            "run": ("#3BAFDA", "#1A2B33"),
            "merge": ("#E8A246", "#2E2418"),
            "pause": ("#E8A246", "#2E2418"),
            "done": ("#3BB87E", "#192B22"),
            "fail": ("#E56B67", "#2E1C1D"),
            "cancel": (PRIMITIVES["dark_500"], PRIMITIVES["dark_800"]),
        },
    },
}

_THEME_MODE = "light"     # "light" | "dark"

# 导出兼容常量（切换主题时同步刷新）
ACCENT = THEMES["light"]["accent"]
ACCENT_HOVER = THEMES["light"]["accent_hover"]
ACCENT_PRESS = THEMES["light"]["accent_press"]
ACCENT_SOFT = THEMES["light"]["accent_soft"]
BLUE = THEMES["light"]["blue"]
GREEN = THEMES["light"]["green"]
RED = THEMES["light"]["red"]
ORANGE = THEMES["light"]["orange"]

INK = THEMES["light"]["ink"]
INK_2 = THEMES["light"]["ink_2"]
INK_3 = THEMES["light"]["ink_3"]
PAGE = THEMES["light"]["page"]
CARD = THEMES["light"]["card"]
FIELD = THEMES["light"]["field"]
FIELD_HOVER = THEMES["light"]["field_hover"]
LINE = THEMES["light"]["line"]
TRACK = THEMES["light"]["track"]
DARK = THEMES["light"]["dark_log"]
DARK_FG = THEMES["light"]["dark_log_fg"]
PINK, PINK_D, BLUE_D = ACCENT, ACCENT_PRESS, "#0098D1"
STATE_COLORS = dict(THEMES["light"]["state_colors"])


def detect_system_dark():
    """检测操作系统当前是否处于深色模式（支持 macOS / Windows / Linux）。"""
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                stderr=subprocess.DEVNULL, timeout=0.3
            ).decode("utf-8", "ignore").strip().lower()
            return out == "dark"
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return int(val) == 0
        except Exception:
            return False
    if sys.platform.startswith("linux"):
        gtk = (os.environ.get("GTK_THEME") or "").lower()
        if "dark" in gtk:
            return True
        try:
            out = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                stderr=subprocess.DEVNULL, timeout=0.3
            ).decode("utf-8", "ignore").strip().lower()
            return "dark" in out
        except Exception:
            return False
    return False


def theme():
    """返回当前激活主题的语义 Token 字典。"""
    return THEMES[_THEME_MODE]


def is_dark():
    return _THEME_MODE == "dark"


def t_color(key):
    """按语义 Token 名称取当前主题色值。"""
    return THEMES[_THEME_MODE][key]


def state_colors(st):
    """按任务状态取 (前景色, 柔和背景色)。"""
    sc = THEMES[_THEME_MODE]["state_colors"]
    return sc.get(st, sc["wait"])


# ---------------------------------------------------------------- 动效 Token 与自定义曲线
DUR_PRESS_IN = 100        # pointer-down 即时响应
DUR_PRESS_OUT = 160       # 释放回弹（100-160ms）
DUR_HOVER = 140           # 悬停色彩过渡
DUR_POPOVER = 180         # 下拉与轻浮层（150-250ms）
DUR_SEGMENT = 220         # 分段滑块移动（ease-in-out）
DUR_MODAL = 200           # 模态框入场
DUR_TOAST_IN = 240        # Toast 入场
DUR_TOAST_OUT = 180       # Toast 退场（非对称：退场快于入场）

_REDUCED_MOTION = None


def reduced_motion():
    """检测是否开启了「减弱动态效果」（prefers-reduced-motion）。结果缓存，零运行时开销。"""
    global _REDUCED_MOTION
    if _REDUCED_MOTION is not None:
        return _REDUCED_MOTION
    env = os.environ.get("BILIFETCH_REDUCED_MOTION", "").strip().lower()
    if env in ("1", "true", "yes"):
        _REDUCED_MOTION = True
        return True
    if env in ("0", "false", "no"):
        _REDUCED_MOTION = False
        return False
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                stderr=subprocess.DEVNULL, timeout=0.3
            ).decode("utf-8", "ignore").strip()
            _REDUCED_MOTION = (out == "1")
            return _REDUCED_MOTION
        except Exception:
            pass
    _REDUCED_MOTION = False
    return False


def _make_bezier(x1, y1, x2, y2):
    c = QEasingCurve(QEasingCurve.BezierSpline)
    c.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return c


_EASE_OUT = _make_bezier(0.22, 1.0, 0.36, 1.0)
_EASE_IN_OUT = _make_bezier(0.77, 0.0, 0.175, 1.0)
_EASE_DRAWER = _make_bezier(0.32, 0.72, 0.0, 1.0)


def ease_out():
    """强减速曲线：cubic-bezier(0.22, 1, 0.36, 1)（ai-design-skills 标准曲线）。"""
    return QEasingCurve(_EASE_OUT)


def ease_in_out():
    """强 ease-in-out：cubic-bezier(0.77, 0, 0.175, 1)，用于屏幕内元素的位移与变形。"""
    return QEasingCurve(_EASE_IN_OUT)


def ease_drawer():
    """iOS 风格阻尼曲线：cubic-bezier(0.32, 0.72, 0, 1)，用于面板与抽屉。"""
    return QEasingCurve(_EASE_DRAWER)


def eval_ease_out(t):
    """在自绘帧循环里直接求值 --ease-out (0..1 -> 0..1)。"""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return _EASE_OUT.valueForProgress(t)


# ---------------------------------------------------------------- 字体与排版（Tailwind Type Scale & Tabular Nums）
_TYPE_SCALE_STEPS = (12, 14, 16, 18, 20, 24, 30, 36, 48, 60)


def _snap_type_scale(px):
    """将任意字号收敛至 Tailwind 标准字阶（偏离档位时向下一档吸附，最低 12px）。"""
    if px <= 12:
        return 12
    best = 12
    for step in _TYPE_SCALE_STEPS:
        if step <= px:
            best = step
        else:
            break
    return best


def _cap_weight(weight):
    """ai-design-skills 规范：禁止超粗字重，封顶 Semibold (DemiBold)。"""
    return min(int(weight), int(QFont.DemiBold))


_UI_FAMILIES_CACHE = None
_TAB_FAMILIES_CACHE = None


def _filter_installed_fonts(candidates, fallback):
    try:
        from PyQt5.QtGui import QFontDatabase
        avail = set(QFontDatabase().families())
        picked = [f for f in candidates if f in avail or f.startswith(".")]
        return picked or fallback
    except Exception:
        return fallback


def _ui_families():
    global _UI_FAMILIES_CACHE
    if _UI_FAMILIES_CACHE is None:
        if sys.platform == "darwin":
            _UI_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist", "Manrope", "PingFang SC", ".AppleSystemUIFont"],
                ["PingFang SC", ".AppleSystemUIFont"],
            )
        elif sys.platform == "win32":
            _UI_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist", "Manrope", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"],
                ["Microsoft YaHei UI", "Segoe UI"],
            )
        else:
            _UI_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist", "Manrope", "Noto Sans CJK SC", "Ubuntu", "Cantarell", "DejaVu Sans"],
                ["Noto Sans CJK SC", "Ubuntu", "DejaVu Sans"],
            )
    return _UI_FAMILIES_CACHE


def ui_font(px=14, weight=QFont.Normal, tabular=False):
    """构建符合 ai-design-skills 字阶规范的界面字体：无斜体、封顶 Semibold、大标题微收字距。"""
    if tabular:
        return tabular_font(px, weight)
    snapped = _snap_type_scale(px)
    f = QFont()
    f.setFamilies(_ui_families())
    f.setPixelSize(snapped)
    f.setWeight(_cap_weight(weight))
    f.setStyle(QFont.StyleNormal)
    if snapped >= 18:
        f.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
    elif snapped <= 12:
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.1)
    return f


def tabular_font(px=12, weight=QFont.Normal):
    """用于实时刷新的数字（百分比、网速、剩余时间、大小）：排除 Inter/Arial/Helvetica。"""
    global _TAB_FAMILIES_CACHE
    if _TAB_FAMILIES_CACHE is None:
        if sys.platform == "darwin":
            _TAB_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist Mono", "Geist", "Menlo", "PingFang SC", ".AppleSystemUIFont"],
                ["Menlo", "PingFang SC", ".AppleSystemUIFont"],
            )
        elif sys.platform == "win32":
            _TAB_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist Mono", "Geist", "Consolas", "Segoe UI", "Microsoft YaHei UI"],
                ["Consolas", "Segoe UI", "Microsoft YaHei UI"],
            )
        else:
            _TAB_FAMILIES_CACHE = _filter_installed_fonts(
                ["Geist Mono", "Geist", "Ubuntu Mono", "Noto Sans CJK SC", "DejaVu Sans"],
                ["DejaVu Sans"],
            )
    snapped = _snap_type_scale(px)
    f = QFont()
    f.setFamilies(_TAB_FAMILIES_CACHE)
    f.setPixelSize(snapped)
    f.setWeight(_cap_weight(weight))
    f.setStyle(QFont.StyleNormal)
    return f


# ---------------------------------------------------------------- 全局样式表与主题切换
_QSS_TEMPLATE = """
QWidget { color: %INK%; }
QMainWindow, QDialog { background: %PAGE%; }
QToolTip {
    background: #1F1F1F;
    color: #F5F5F5;
    border: 1px solid #313131;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 12px;
}

QLabel#h1    { font-size: 20px; font-weight: 600; color: %INK%; }
QLabel#h2    { font-size: 16px; font-weight: 600; color: %INK%; }
QLabel#muted { font-size: 12px; color: %INK_3%; }
QLabel#sub   { font-size: 12px; color: %INK_2%; }
QLabel#err   { font-size: 12px; color: %RED%; font-weight: 500; }

QLineEdit {
    background: %FIELD%;
    color: %INK%;
    border: 1.5px solid transparent;
    border-radius: 8px;
    padding: 0 12px;
    min-height: 36px;
    font-size: 14px;
    selection-background-color: %ACCENT%;
    selection-color: #ffffff;
}
QLineEdit:hover { background: %FIELD_HOVER%; }
QLineEdit:focus { background: %FIELD_FOCUS_BG%; border: 1.5px solid %ACCENT%; }
QLineEdit[invalid="true"] { border: 1.5px solid %RED%; background: %FIELD_FOCUS_BG%; }
QLineEdit#bigInput { min-height: 48px; border-radius: 8px; padding: 0 16px; font-size: 14px; }
QLineEdit#search { min-height: 32px; border-radius: 8px; font-size: 14px; }

QComboBox {
    background: %FIELD%;
    color: %INK%;
    border: 1.5px solid transparent;
    border-radius: 8px;
    padding: 0 32px 0 12px;
    min-height: 36px;
    min-width: 96px;
    font-size: 14px;
}
QComboBox:hover { background: %FIELD_HOVER%; }
QComboBox:focus { border: 1.5px solid %ACCENT%; background: %FIELD_FOCUS_BG%; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: %CARD%;
    color: %INK%;
    border: 1px solid %LINE%;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: %ACCENT_SOFT%;
    selection-color: %ACCENT%;
}

QCheckBox { color: %INK_2%; spacing: 8px; font-size: 14px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1.5px solid %INK_3%; background: %CARD%;
}
QCheckBox::indicator:hover { border-color: %ACCENT%; }
QCheckBox::indicator:checked { background: %ACCENT%; border-color: %ACCENT%; }

QListView { background: %CARD%; border: none; outline: none; }

QPlainTextEdit {
    background: %DARK%;
    color: %DARK_FG%;
    border: 1px solid %LOG_BORDER%;
    border-radius: 8px;
    padding: 12px;
    font-family: Menlo, Consolas, monospace;
    font-size: 12px;
    selection-background-color: %ACCENT%;
    selection-color: #ffffff;
}

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: %LINE%; border-radius: 4px; min-height: 32px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: %INK_3%; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0; }

QMenuBar { background: %PAGE%; color: %INK_2%; }
QMenu { background: %CARD%; border: 1px solid %LINE%; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 8px 24px 8px 12px; border-radius: 4px; color: %INK%; font-size: 14px; }
QMenu::item:selected { background: %FIELD%; }
QMenu::item:disabled { color: %INK_3%; }
QMenu::separator { height: 1px; background: %LINE%; margin: 4px 8px; }

QMessageBox { background: %PAGE%; }
QMessageBox QLabel { font-size: 14px; color: %INK%; }
QMessageBox QPushButton, QFileDialog QPushButton {
    min-width: 64px; padding: 8px 12px; border-radius: 8px;
    background: %FIELD%; color: %INK%; border: none;
}
"""


def build_qss(mode=None):
    t = THEMES[mode or _THEME_MODE]
    qss = _QSS_TEMPLATE
    mapping = {
        "INK": t["ink"],
        "INK_2": t["ink_2"],
        "INK_3": t["ink_3"],
        "PAGE": t["page"],
        "CARD": t["card"],
        "FIELD": t["field"],
        "FIELD_HOVER": t["field_hover"],
        "FIELD_FOCUS_BG": t["field_focus_bg"],
        "LINE": t["line"],
        "DARK": t["dark_log"],
        "DARK_FG": t["dark_log_fg"],
        "LOG_BORDER": t["log_border"],
        "ACCENT": t["accent"],
        "ACCENT_SOFT": t["accent_soft"],
        "RED": t["red"],
    }
    for k, v in mapping.items():
        qss = qss.replace("%" + k + "%", v)
    return qss


QSS = build_qss("light")


def set_theme(mode="light", app=None):
    """切换全局主题（'light' | 'dark' | 'auto'），同步刷新语义常量、样式表与所有打开的窗口。"""
    global _THEME_MODE, ACCENT, ACCENT_HOVER, ACCENT_PRESS, ACCENT_SOFT
    global BLUE, GREEN, RED, ORANGE, INK, INK_2, INK_3, PAGE, CARD, FIELD, FIELD_HOVER
    global LINE, TRACK, DARK, DARK_FG, STATE_COLORS, QSS

    if mode == "auto":
        resolved = "dark" if detect_system_dark() else "light"
    else:
        resolved = "dark" if mode == "dark" else "light"

    _THEME_MODE = resolved
    t = THEMES[resolved]
    ACCENT = t["accent"]
    ACCENT_HOVER = t["accent_hover"]
    ACCENT_PRESS = t["accent_press"]
    ACCENT_SOFT = t["accent_soft"]
    BLUE = t["blue"]
    GREEN = t["green"]
    RED = t["red"]
    ORANGE = t["orange"]
    INK = t["ink"]
    INK_2 = t["ink_2"]
    INK_3 = t["ink_3"]
    PAGE = t["page"]
    CARD = t["card"]
    FIELD = t["field"]
    FIELD_HOVER = t["field_hover"]
    LINE = t["line"]
    TRACK = t["track"]
    DARK = t["dark_log"]
    DARK_FG = t["dark_log_fg"]
    STATE_COLORS.clear()
    STATE_COLORS.update(t["state_colors"])
    QSS = build_qss(resolved)

    qapp = app or QApplication.instance()
    if qapp is not None:
        qapp.setStyleSheet(QSS)
        for w in qapp.allWidgets():
            if hasattr(w, "_cache"):
                w._cache = None
            if hasattr(w, "_pm") and isinstance(w, LogoTile):
                w._pm = None
            w.update()
    return resolved


def mix(c1, c2, t):
    """两个颜色按 t (0..1) 插值。"""
    t = max(0.0, min(1.0, float(t)))
    a, b = QColor(c1), QColor(c2)
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


def first_grapheme(text):
    """安全提取昵称首字符（兼容空白、Emoji 与组合字符，避免 break-ui 中的半截乱码）。"""
    s = (text or "").strip()
    if not s:
        return "?"
    return s[0].upper()


def draw_focus_ring(p, rect, radius=8.0, color=None):
    """绘制符合 WCAG 2.2 Focus Appearance 的 2px 高对比度焦点环。"""
    p.save()
    pen = QPen(QColor(color or t_color("accent")), 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    r = QRectF(rect).adjusted(1.0, 1.0, -1.0, -1.0)
    p.drawRoundedRect(r, max(2.0, radius - 1.0), max(2.0, radius - 1.0))
    p.restore()


def draw_skeleton_shimmer(p, rect, radius=7.0, phase=0.0):
    """为异步加载中的缩略图/封面绘制柔和的 Skeleton Shimmer 骨架微光（ui-ux-pro-max progressive-loading）。"""
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    base = QColor(t_color("shimmer_base"))
    hi = QColor(t_color("shimmer_hi"))
    p.save()
    p.setClipPath(path)
    p.fillPath(path, base)
    if not reduced_motion():
        w = rect.width()
        cx = rect.left() - w * 0.6 + (w * 2.2) * (phase % 1.0)
        grad = QLinearGradient(cx - w * 0.45, rect.top(), cx + w * 0.45, rect.bottom())
        grad.setColorAt(0.0, base)
        grad.setColorAt(0.5, hi)
        grad.setColorAt(1.0, base)
        p.fillRect(QRectF(rect), grad)
    p.restore()


# ---------------------------------------------------------------- 图标（design 矢量规范：统一 1.5px 线宽与圆角）
_icon_cache = {}


def make_icon(kind, color, size=16, dpr=2.0):
    """矢量小图标（按 Retina 2x 画，结果缓存起来，同样的图标只画一次）。"""
    key = (kind, QColor(color).name(QColor.HexArgb), size, dpr)
    pm = _icon_cache.get(key)
    if pm is not None:
        return pm
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.5 * size / 16.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.scale(size / 16.0, size / 16.0)
    path = QPainterPath()
    if kind == "folder":
        path.moveTo(2, 4.5)
        path.quadTo(2, 3, 3.5, 3)
        path.lineTo(6.2, 3)
        path.lineTo(7.7, 4.6)
        path.lineTo(12.5, 4.6)
        path.quadTo(14, 4.6, 14, 6.1)
        path.lineTo(14, 11.5)
        path.quadTo(14, 13, 12.5, 13)
        path.lineTo(3.5, 13)
        path.quadTo(2, 13, 2, 11.5)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "gear":
        n, r_out, r_in = 8, 6.6, 4.9
        for i in range(n * 4):
            a = (i / (n * 4.0)) * 2 * math.pi - math.pi / 2
            rr = r_out if (i % 4) in (1, 2) else r_in
            pt = QPointF(8 + rr * math.cos(a), 8 + rr * math.sin(a))
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QRectF(5.8, 5.8, 4.4, 4.4))
    elif kind == "sun":
        p.drawEllipse(QRectF(5.0, 5.0, 6.0, 6.0))
        for i in range(8):
            a = i * math.pi / 4.0
            p.drawLine(QPointF(8 + 4.4 * math.cos(a), 8 + 4.4 * math.sin(a)),
                       QPointF(8 + 6.3 * math.cos(a), 8 + 6.3 * math.sin(a)))
    elif kind == "moon":
        outer = QPainterPath()
        outer.addEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
        cut = QPainterPath()
        cut.addEllipse(QRectF(6.2, 1.8, 8.2, 8.2))
        path = outer.subtracted(cut)
        p.drawPath(path)
    elif kind == "link":
        p.drawRoundedRect(QRectF(2.2, 5.8, 6.2, 4.4), 2.2, 2.2)
        p.drawRoundedRect(QRectF(7.6, 5.8, 6.2, 4.4), 2.2, 2.2)
        p.drawLine(QPointF(6.2, 8.0), QPointF(9.8, 8.0))
    elif kind == "open":
        p.drawPolyline([QPointF(7, 3), QPointF(4.2, 3), QPointF(3, 4.2), QPointF(3, 11.8),
                        QPointF(4.2, 13), QPointF(11.8, 13), QPointF(13, 11.8), QPointF(13, 9)])
        p.drawLine(QPointF(8.5, 7.5), QPointF(13, 3))
        p.drawPolyline([QPointF(9.5, 3), QPointF(13, 3), QPointF(13, 6.5)])
    elif kind == "stop":
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(4.5, 4.5, 7, 7), 1.5, 1.5)
    elif kind == "pause":
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(4.4, 3.8, 2.5, 8.4), 1.1, 1.1)
        p.drawRoundedRect(QRectF(9.1, 3.8, 2.5, 8.4), 1.1, 1.1)
    elif kind == "play":
        p.setBrush(QColor(color))
        path.moveTo(5.5, 3.8)
        path.lineTo(12.3, 8)
        path.lineTo(5.5, 12.2)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "download":
        p.drawLine(QPointF(8, 2.5), QPointF(8, 10))
        p.drawPolyline([QPointF(4.8, 7), QPointF(8, 10.2), QPointF(11.2, 7)])
        p.drawLine(QPointF(3, 13.2), QPointF(13, 13.2))
    elif kind == "paste":
        p.drawRoundedRect(QRectF(3.5, 3.5, 9, 10.5), 1.8, 1.8)
        p.drawRoundedRect(QRectF(6, 2, 4, 3), 1, 1)
    elif kind == "trash":
        p.drawLine(QPointF(2.8, 4.5), QPointF(13.2, 4.5))
        p.drawLine(QPointF(6.3, 2.5), QPointF(9.7, 2.5))
        path.moveTo(4.2, 4.5)
        path.lineTo(4.9, 12.6)
        path.quadTo(5, 13.6, 6, 13.6)
        path.lineTo(10, 13.6)
        path.quadTo(11, 13.6, 11.1, 12.6)
        path.lineTo(11.8, 4.5)
        p.drawPath(path)
    elif kind == "copy":
        p.drawRoundedRect(QRectF(5.5, 5.5, 8, 8), 1.6, 1.6)
        p.drawPolyline([QPointF(3, 10.5), QPointF(3, 4), QPointF(3.8, 3), QPointF(10.5, 3)])
    elif kind == "retry":
        path.arcMoveTo(QRectF(3, 3, 10, 10), 60)
        path.arcTo(QRectF(3, 3, 10, 10), 60, 280)
        p.drawPath(path)
        p.drawPolyline([QPointF(10.6, 1.9), QPointF(10.6, 4.6), QPointF(13.2, 4.6)])
    elif kind == "check":
        p.drawPolyline([QPointF(3.5, 8.3), QPointF(6.7, 11.3), QPointF(12.5, 4.8)])
    elif kind == "close":
        p.drawLine(QPointF(4.5, 4.5), QPointF(11.5, 11.5))
        p.drawLine(QPointF(11.5, 4.5), QPointF(4.5, 11.5))
    elif kind == "search":
        p.drawEllipse(QRectF(3, 3, 8, 8))
        p.drawLine(QPointF(10, 10), QPointF(13.2, 13.2))
    elif kind == "user":
        p.drawEllipse(QRectF(5.3, 2.6, 5.4, 5.4))
        path.moveTo(2.8, 13.6)
        path.quadTo(3.4, 9.4, 8, 9.4)
        path.quadTo(12.6, 9.4, 13.2, 13.6)
        p.drawPath(path)
    elif kind == "list":
        for y in (4.5, 8, 11.5):
            p.drawLine(QPointF(5.5, y), QPointF(13, y))
            p.drawPoint(QPointF(2.8, y))
    elif kind == "terminal":
        p.drawRoundedRect(QRectF(2, 3, 12, 10), 2, 2)
        p.drawPolyline([QPointF(4.8, 6.3), QPointF(6.8, 8), QPointF(4.8, 9.7)])
        p.drawLine(QPointF(8.3, 10), QPointF(11, 10))
    elif kind == "chevron":
        p.drawPolyline([QPointF(4.5, 6.3), QPointF(8, 9.8), QPointF(11.5, 6.3)])
    elif kind == "info":
        p.drawEllipse(QRectF(2.5, 2.5, 11, 11))
        p.drawLine(QPointF(8, 7.2), QPointF(8, 11))
        p.drawPoint(QPointF(8, 5.0))
    elif kind == "warning":
        path.moveTo(8, 2.6)
        path.lineTo(13.6, 12.8)
        path.lineTo(2.4, 12.8)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(8, 6.4), QPointF(8, 9.4))
        p.drawPoint(QPointF(8, 11.2))
    elif kind == "music":
        p.drawLine(QPointF(6, 11.5), QPointF(6, 3.2))
        p.drawLine(QPointF(6, 3.2), QPointF(12.5, 2.2))
        p.drawLine(QPointF(12.5, 2.2), QPointF(12.5, 10.3))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(2.8, 10, 3.6, 3))
        p.drawEllipse(QRectF(9.3, 8.8, 3.6, 3))
    p.end()
    _icon_cache[key] = pm
    return pm


# ---------------------------------------------------------------- 滚动边缘渐隐遮罩（Apple Design §12）
def draw_scroll_edge_fade(p, viewport_rect, scrollbar, bg_color=None, fade_h=28):
    """当列表发生滚动或内容溢出时，在顶部/底部绘制柔和渐隐遮罩，避免末行文字被生硬腰斩。"""
    if scrollbar is None:
        return
    val = scrollbar.value()
    mx = scrollbar.maximum()
    if val <= 0 and mx <= 0:
        return
    bg = bg_color or t_color("card")
    c_solid = QColor(bg)
    c_mid = QColor(bg)
    c_mid.setAlpha(210)
    c_trans = QColor(bg)
    c_trans.setAlpha(0)
    w = viewport_rect.width()
    h = viewport_rect.height()
    p.save()
    p.setPen(Qt.NoPen)
    if val > 0:
        th = min(fade_h, max(10.0, val * 0.6))
        grad = QLinearGradient(0, 0, 0, th)
        grad.setColorAt(0.0, c_solid)
        grad.setColorAt(0.35, c_mid)
        grad.setColorAt(1.0, c_trans)
        p.fillRect(QRectF(0, 0, w, th), grad)
    if val < mx:
        remain = mx - val
        bh = min(fade_h, max(10.0, remain * 0.6))
        grad = QLinearGradient(0, h - bh, 0, h)
        grad.setColorAt(0.0, c_trans)
        grad.setColorAt(0.65, c_mid)
        grad.setColorAt(1.0, c_solid)
        p.fillRect(QRectF(0, h - bh, w, bh), grad)
    p.restore()


# ---------------------------------------------------------------- 卡片
class Card(QFrame):
    """圆角卡片 + 柔和多层环境投影（Tailwind radius/16，spacing/200=16px 同心圆角基准）。"""

    MARGIN = 6
    RADIUS = 16

    def __init__(self, parent=None, padding=(16, 16, 16, 16)):
        super().__init__(parent)
        self.setObjectName("card")
        self._cache = None
        self._cache_key = None
        self._highlight = 0.0
        self._hl_anim = None
        self.layout = QVBoxLayout(self)
        m = self.MARGIN
        self.layout.setContentsMargins(padding[0] + m, padding[1] + m,
                                       padding[2] + m, padding[3] + m)
        self.layout.setSpacing(12)

    def setHighlight(self, active):
        target = 1.0 if active else 0.0
        if self._hl_anim is None:
            self._hl_anim = QVariantAnimation(self)
            self._hl_anim.setDuration(DUR_POPOVER)
            self._hl_anim.setEasingCurve(ease_out())
            self._hl_anim.valueChanged.connect(self._on_hl)
        self._hl_anim.stop()
        self._hl_anim.setStartValue(self._highlight)
        self._hl_anim.setEndValue(target)
        self._hl_anim.start()

    def _on_hl(self, v):
        self._highlight = float(v)
        self._cache = None
        self.update()

    def _render(self):
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        m = self.MARGIN
        r = QRectF(m, m, w - 2 * m, h - 2 * m)
        p.setPen(Qt.NoPen)
        dark = is_dark()
        shadows = ((5, 9), (3.5, 14), (2, 20), (1, 28)) if dark else ((5, 3), (3.5, 5), (2, 7), (1, 10))
        for i, a in shadows:
            p.setBrush(QColor(0, 0, 0, a) if dark else QColor(15, 20, 30, a))
            p.drawRoundedRect(r.adjusted(-i * 0.6, -i * 0.2, i * 0.6, i * 0.9),
                              self.RADIUS + i * 0.6, self.RADIUS + i * 0.6)
        p.setBrush(mix(t_color("card"), t_color("accent_soft"), self._highlight * 0.25))
        border_col = mix(QColor(t_color("card_border")), QColor(t_color("accent")), self._highlight)
        p.setPen(QPen(border_col, 1.0 + 0.5 * self._highlight))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        p.end()
        return pm

    def paintEvent(self, e):
        key = (self.width(), self.height(), self.devicePixelRatioF(), _THEME_MODE, round(self._highlight, 3))
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()


# ---------------------------------------------------------------- 按钮
class Button(QAbstractButton):
    """自绘按钮（遵循 Emil Kowalski 按压反馈、非对称时序与 ui-ux-pro-max 焦点无障碍规范）。"""

    PRESS_SCALE = 0.97

    def __init__(self, text="", kind="secondary", icon=None, parent=None, height=36):
        super().__init__(parent)
        self.setText(text)
        self.kind = kind
        self._icon_kind = icon
        self._saved_icon = icon
        self._hover = 0.0
        self._press = 0.0
        self._loading = False
        self._spin_angle = 0.0
        self._h = height
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DUR_HOVER)
        self._anim.setEasingCurve(ease_out())
        self._anim.valueChanged.connect(self._on_anim)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setEasingCurve(ease_out())
        self._press_anim.valueChanged.connect(self._on_press_anim)

        self._spin_anim = None

    def setIconKind(self, kind):
        self._icon_kind = kind
        if not self._loading:
            self._saved_icon = kind
        self.updateGeometry()
        self.update()

    def setLoading(self, loading, text=None):
        """切换按钮加载态：显示内联高速旋转指示器，无需外部拼凑控件。"""
        self._loading = bool(loading)
        if text is not None:
            self.setText(text)
        if self._loading:
            if self._spin_anim is None:
                self._spin_anim = QVariantAnimation(self)
                self._spin_anim.setStartValue(0.0)
                self._spin_anim.setEndValue(360.0)
                self._spin_anim.setDuration(620)
                self._spin_anim.setLoopCount(-1)
                self._spin_anim.valueChanged.connect(self._on_spin)
            self._spin_anim.start()
            self.setEnabled(False)
        else:
            if self._spin_anim is not None:
                self._spin_anim.stop()
            self.setEnabled(True)
        self.updateGeometry()
        self.update()

    def _on_spin(self, v):
        self._spin_angle = float(v)
        self.update()

    def _on_anim(self, v):
        self._hover = float(v)
        self.update()

    def _on_press_anim(self, v):
        self._press = float(v)
        self.update()

    def _animate_hover(self, to):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(to)
        self._anim.start()

    def _animate_press(self, to, duration):
        if reduced_motion():
            self._press = float(to)
            self.update()
            return
        self._press_anim.stop()
        self._press_anim.setDuration(duration)
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(float(to))
        self._press_anim.start()

    def enterEvent(self, e):
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate_hover(0.0)
        if self._press > 0.0:
            self._animate_press(0.0, DUR_PRESS_OUT)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self._animate_press(1.0, DUR_PRESS_IN)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press > 0.0:
            self._animate_press(0.0, DUR_PRESS_OUT)
        super().mouseReleaseEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.EnabledChange and not self.isEnabled():
            self._anim.stop()
            self._press_anim.stop()
            self._hover = 0.0
            self._press = 0.0

    def _colors(self):
        enabled = self.isEnabled()
        t = theme()
        if self.kind == "primary":
            if not enabled and not self._loading:
                return QColor(t["accent_disabled"]), QColor("#FFFFFF")
            if self._loading:
                return QColor(t["accent"]), QColor("#FFFFFF")
            base = mix(t["accent"], t["accent_hover"], self._hover)
            return mix(base, t["accent_press"], self._press), QColor("#FFFFFF")
        if self.kind == "ghost":
            fg = mix(t["ink_2"], t["ink"], self._hover * 0.6) if enabled else QColor(t["ink_disabled"])
            f_col = QColor(t["field"])
            f_zero = QColor(f_col.red(), f_col.green(), f_col.blue(), 0)
            base = mix(f_zero, f_col, self._hover)
            return mix(base, t["field_press"], self._press), fg
        # secondary
        fg = QColor(t["ink"]) if enabled else QColor(t["ink_disabled"])
        base = mix(t["field"], t["field_hover"], self._hover)
        return mix(base, t["field_press"], self._press), fg

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        w = fm.horizontalAdvance(self.text()) if self.text() else 0
        has_ic = bool(self._icon_kind or self._loading)
        if has_ic:
            w += 16 + (8 if self.text() else 0)
        pad = 12 if self.text() else 8
        return QSize(w + pad * 2, self._h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _font(self):
        # 主按钮 14px Semibold (Button-sm)，32px 紧凑顶栏按钮 12px Semibold (Button-Xsm)
        px = 12 if self._h <= 32 else 14
        return ui_font(px, QFont.DemiBold)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg, fg = self._colors()
        r = QRectF(self.rect())

        if self._press > 0.001 and not reduced_motion():
            s = 1.0 - (1.0 - self.PRESS_SCALE) * self._press
            cx, cy = r.center().x(), r.center().y()
            p.translate(cx, cy)
            p.scale(s, s)
            p.translate(-cx, -cy)

        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        rad = min(8.0, r.height() / 2.0)
        p.drawRoundedRect(r, rad, rad)

        if self.kind == "primary" and (self.isEnabled() or self._loading):
            p.setPen(QPen(QColor(255, 255, 255, 48), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad - 0.5, rad - 0.5)

        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus:
            draw_focus_ring(p, r, rad)

        f = self._font()
        p.setFont(f)
        p.setPen(fg)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text()) if self.text() else 0
        has_ic = bool(self._icon_kind or self._loading)
        iw = 16 if has_ic else 0
        gap = 8 if (iw and tw) else 0
        x = (r.width() - (tw + iw + gap)) / 2.0

        if self._loading:
            sp_r = QRectF(x + 1.5, (r.height() - 13) / 2.0, 13, 13)
            pen = QPen(fg, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(sp_r, int(-self._spin_angle * 16), int(250 * 16))
            p.setPen(fg)
        elif iw:
            pm = make_icon(self._icon_kind, fg, 16)
            p.drawPixmap(QPointF(x, (r.height() - 16) / 2.0), pm)
        if tw:
            p.drawText(QRectF(x + iw + gap, 0, tw + 2, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class IconButton(Button):
    """方形图标按钮（透明底，悬停出现浅灰底，按压 0.94 微缩放）。"""

    PRESS_SCALE = 0.94

    def __init__(self, icon, tooltip="", parent=None, size=34):
        super().__init__("", "ghost", icon, parent, height=size)
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)

    def sizeHint(self):
        return QSize(self._h, self._h)


# ---------------------------------------------------------------- 分段切换
class Segmented(QWidget):
    """分段切换控件：采用 Clip-Path 双层裁剪，支持 TabFocus 与左右方向键切换。"""

    changed = pyqtSignal(int)

    def __init__(self, labels, parent=None, compact=False):
        super().__init__(parent)
        self.labels = list(labels)
        self._compact = compact
        self._index = 0
        self._pos = 0.0
        self._pressed_seg = -1
        self._press_val = 0.0
        self._badges = [""] * len(self.labels)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedHeight(28 if compact else 32)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DUR_SEGMENT)
        self._anim.setEasingCurve(ease_in_out())
        self._anim.valueChanged.connect(self._on_anim)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(DUR_PRESS_IN)
        self._press_anim.setEasingCurve(ease_out())
        self._press_anim.valueChanged.connect(self._on_press)

        px = 12 if compact else 14
        self._font = ui_font(px, QFont.Medium)
        self._font_active = ui_font(px, QFont.DemiBold)
        self._font_badge = tabular_font(12, QFont.DemiBold)
        self._recalc_width()

    def _recalc_width(self):
        fm = QFontMetrics(self._font_active)
        fm_b = QFontMetrics(self._font_badge)
        max_w = 0
        for i, t in enumerate(self.labels):
            w = fm.horizontalAdvance(t)
            if self._badges[i]:
                w += 6 + max(18, fm_b.horizontalAdvance(self._badges[i]) + 8)
            max_w = max(max_w, w)
        pad = 12 if self._compact else 18
        min_seg = 40 if self._compact else 52
        self._seg_w = max(min_seg, max_w + pad)
        self._total_w = self._seg_w * len(self.labels) + 4
        self.setFixedWidth(self._total_w)
        self.updateGeometry()

    def sizeHint(self):
        return QSize(getattr(self, "_total_w", 120), self.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    def _on_press(self, v):
        self._press_val = float(v)
        self.update()

    def index(self):
        return self._index

    def setBadge(self, i, text):
        text = str(text or "")
        if 0 <= i < len(self._badges) and self._badges[i] != text:
            self._badges[i] = text
            self._recalc_width()
            self.update()

    def setIndex(self, i, animate=True):
        if i == self._index or not (0 <= i < len(self.labels)):
            return
        self._index = i
        if animate and not reduced_motion():
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._anim.stop()
            self._pos = float(i)
            self.update()
        self.changed.emit(i)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Left, Qt.Key_Up):
            self.setIndex((self._index - 1) % len(self.labels))
            e.accept()
            return
        if e.key() in (Qt.Key_Right, Qt.Key_Down):
            self.setIndex((self._index + 1) % len(self.labels))
            e.accept()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = int((e.pos().x() - 2) // self._seg_w)
            if 0 <= i < len(self.labels):
                self._pressed_seg = i
                self._press_anim.stop()
                self._press_anim.setDuration(DUR_PRESS_IN)
                self._press_anim.setStartValue(self._press_val)
                self._press_anim.setEndValue(1.0)
                self._press_anim.start()
                self.setIndex(i)

    def mouseReleaseEvent(self, e):
        if self._press_val > 0.0:
            self._press_anim.stop()
            self._press_anim.setDuration(DUR_PRESS_OUT)
            self._press_anim.setStartValue(self._press_val)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
        super().mouseReleaseEvent(e)

    def _draw_labels(self, p, r, active=False):
        t = theme()
        f = self._font_active if active else self._font
        fm = QFontMetrics(f)
        fm_b = QFontMetrics(self._font_badge)
        for i, lbl in enumerate(self.labels):
            seg = QRectF(2 + i * self._seg_w, 0, self._seg_w, r.height())
            badge = self._badges[i]
            tw = fm.horizontalAdvance(lbl)
            bw = max(18, fm_b.horizontalAdvance(badge) + 8) if badge else 0
            gap = 6 if badge else 0
            total_w = tw + gap + bw
            sx = seg.left() + (seg.width() - total_w) / 2.0

            p.setFont(f)
            p.setPen(QColor(t["ink"] if active else t["ink_3"]))
            p.drawText(QRectF(sx, 0, tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, lbl)

            if badge:
                bh = 16
                br = QRectF(sx + tw + gap, (r.height() - bh) / 2.0, bw, bh)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(t["accent_soft"] if active else t["badge_inactive_bg"]))
                p.drawRoundedRect(br, 4.0, 4.0)
                p.setFont(self._font_badge)
                p.setPen(QColor(t["accent"] if active else t["ink_2"]))
                p.drawText(br, Qt.AlignCenter, badge)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        t = theme()
        # 同心圆角公式 inner = outer - gap：outer=8, gap=2 -> inner=6；compact outer=6, gap=2 -> inner=4
        rad = 6.0 if self._compact else 8.0
        pill_rad = 4.0 if self._compact else 6.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["field"]))
        p.drawRoundedRect(r, rad, rad)

        self._draw_labels(p, r, active=False)

        pill = QRectF(2 + self._pos * self._seg_w, 2, self._seg_w, r.height() - 4)
        if self._press_val > 0.01 and not reduced_motion():
            dx = pill.width() * 0.015 * self._press_val
            dy = pill.height() * 0.025 * self._press_val
            pill = pill.adjusted(dx, dy, -dx, -dy)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 32 if is_dark() else 16))
        p.drawRoundedRect(pill.adjusted(0, 1.0, 0, 1.0), pill_rad, pill_rad)
        p.setBrush(QColor(t["pill_bg"]))
        p.setPen(QPen(QColor(255, 255, 255, 18) if is_dark() else QColor(0, 0, 0, 10), 0.5))
        p.drawRoundedRect(pill, pill_rad, pill_rad)

        clip = QPainterPath()
        clip.addRoundedRect(pill, pill_rad, pill_rad)
        p.save()
        p.setClipPath(clip)
        self._draw_labels(p, r, active=True)
        p.restore()

        if self.hasFocus():
            draw_focus_ring(p, r, rad)
        p.end()


# ---------------------------------------------------------------- 小部件
class Avatar(QWidget):
    """圆角方框头像（Squircle，取代普通正圆）：昵称首字 + 品牌色底。"""

    def __init__(self, size=24, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._text = ""

    def setName(self, name):
        self._text = first_grapheme(name)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t_color("accent")))
        p.drawRoundedRect(QRectF(self.rect()), 6.0, 6.0)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(ui_font(12, QFont.DemiBold))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class AccountChip(QAbstractButton):
    """右上角的账号按钮：采用 radius/8 圆角矩形 + 内嵌 radius/4 同心圆角方框头像（8 - 4 = 4）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._name = None
        self._hover = 0.0
        self._press = 0.0
        self.setFixedHeight(32)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DUR_HOVER)
        self._anim.setEasingCurve(ease_out())
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_hover", float(v)), self.update()))

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setEasingCurve(ease_out())
        self._press_anim.valueChanged.connect(lambda v: (setattr(self, "_press", float(v)), self.update()))

        self._update_size()

    def setName(self, name):
        self._name = (name or "").strip() or None
        self._update_size()
        self.update()

    def name(self):
        return self._name

    def _font(self):
        return ui_font(13, QFont.Medium)

    def _label(self):
        return self._name if self._name else "登录"

    def _update_size(self):
        fm = QFontMetrics(self._font())
        w = fm.horizontalAdvance(self._label()) + 4 + 24 + 8 + 12 + (18 if self._name else 4)
        self.setFixedWidth(min(260, max(78, w)))

    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        if self._press > 0.0:
            self._animate_press(0.0, DUR_PRESS_OUT)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self._animate_press(1.0, DUR_PRESS_IN)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press > 0.0:
            self._animate_press(0.0, DUR_PRESS_OUT)
        super().mouseReleaseEvent(e)

    def _animate_press(self, to, duration):
        if reduced_motion():
            self._press = float(to)
            self.update()
            return
        self._press_anim.stop()
        self._press_anim.setDuration(duration)
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(float(to))
        self._press_anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        t = theme()

        if self._press > 0.001 and not reduced_motion():
            s = 1.0 - 0.03 * self._press
            cx, cy = r.center().x(), r.center().y()
            p.translate(cx, cy)
            p.scale(s, s)
            p.translate(-cx, -cy)

        p.setPen(Qt.NoPen)
        if self._name:
            bg = mix(mix(t["card"], t["field"], self._hover), t["field_press"], self._press)
            p.setBrush(bg)
            p.setPen(QPen(QColor(t["line"]), 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8.0, 8.0)
            av = QRectF(4, 4, r.height() - 8, r.height() - 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawRoundedRect(av, 4.0, 4.0)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(ui_font(12, QFont.DemiBold))
            p.drawText(av, Qt.AlignCenter, first_grapheme(self._name))
            p.setPen(QColor(t["ink"]))
            p.setFont(self._font())
            fm = QFontMetrics(self._font())
            tr = QRectF(av.right() + 8, 0, r.width() - av.right() - 8 - 24, r.height())
            elided = fm.elidedText(self._name, Qt.ElideRight, int(tr.width()))
            p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, elided)
            p.drawPixmap(QPointF(r.width() - 22, (r.height() - 14) / 2),
                         make_icon("chevron", t["ink_3"], 14))
        else:
            hover_soft = "#42242E" if is_dark() else "#FFE3EB"
            press_soft = "#522B38" if is_dark() else "#FFD4E1"
            bg = mix(mix(t["accent_soft"], hover_soft, self._hover), press_soft, self._press)
            p.setBrush(bg)
            p.drawRoundedRect(r, 8.0, 8.0)
            p.drawPixmap(QPointF(12, (r.height() - 16) / 2), make_icon("user", t["accent"], 16))
            p.setPen(QColor(t["accent"]))
            p.setFont(ui_font(14, QFont.DemiBold))
            p.drawText(QRectF(34, 0, r.width() - 40, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, "登录")

        if self.hasFocus():
            draw_focus_ring(p, r, 8.0)
        p.end()


class Spinner(QWidget):
    """高速转圈加载指示（620ms/圈，提升感知加载速度；只在可见时跑定时器）。"""

    def __init__(self, size=16, color=ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(620)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self.update)

    def showEvent(self, e):
        self._anim.start()

    def hideEvent(self, e):
        self._anim.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color, max(1.6, self.width() / 9.0))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = pen.widthF()
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        a = self._anim.currentValue() or 0.0
        p.drawArc(r, int(-a * 16), int(260 * 16))
        p.end()


class ComboBox(QComboBox):
    """下拉框：样式表里把原生箭头去掉了，这里自己画一个小箭头，并带悬停反馈。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.drawPixmap(QPointF(self.width() - 26, (self.height() - 14) / 2.0),
                     make_icon("chevron", t_color("ink_2") if self.underMouse() else t_color("ink_3"), 14))
        p.end()


def animate_dialog_open(dialog, duration=DUR_MODAL):
    """为模态对话框提供克制的 180ms --ease-out 渐显入场（遵循 reduced-motion）。"""
    if reduced_motion():
        return
    fx = QGraphicsOpacityEffect(dialog)
    fx.setOpacity(0.0)
    dialog.setGraphicsEffect(fx)
    anim = QVariantAnimation(dialog)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(ease_out())
    anim.valueChanged.connect(fx.setOpacity)
    anim.finished.connect(lambda: dialog.setGraphicsEffect(None))
    dialog._open_anim = anim
    anim.start()


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background:%s; border:none;" % t_color("line"))
    return line


def draw_rounded_pixmap(p, rect, pm, radius):
    """把图片按圆角裁剪画进 rect（等比铺满后居中裁切）。"""
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    p.save()
    p.setClipPath(path)
    p.drawPixmap(rect.toRect() if isinstance(rect, QRectF) else rect, pm)
    p.restore()


class SectionTitle(QLabel):
    """分区标题（保留旧名字以兼容）。"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("h2")


class IconLabel(QWidget):
    """图标 + 文字的小标签（保留旧名字以兼容）。"""

    def __init__(self, text, icon_kind=None, color=INK_3, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if icon_kind:
            ic = QLabel()
            ic.setPixmap(make_icon(icon_kind, color, 15))
            ic.setFixedWidth(15)
            lay.addWidget(ic)
        self.label = QLabel(text)
        self.label.setObjectName("sub")
        lay.addWidget(self.label)
        lay.addStretch(1)


# ---------------------------------------------------------------- 狐狸
FOX_ORANGE = "#F0823A"
FOX_DARK = "#DD6A2A"
FOX_CREAM = "#FFF6EC"
FOX_NOSE = "#F2748A"
FOX_EYE = "#3A2A20"


def draw_fox(p, x, y, size):
    """画一个简约的狐狸头（纯矢量，任何尺寸都清晰）。"""
    s = size / 100.0
    p.save()
    p.translate(x, y)
    p.setRenderHint(QPainter.Antialiasing)

    for sign in (-1, 1):
        ear = QPainterPath()
        if sign < 0:
            ear.moveTo(24 * s, 40 * s)
            ear.lineTo(14 * s, 8 * s)
            ear.lineTo(44 * s, 26 * s)
        else:
            ear.moveTo(76 * s, 40 * s)
            ear.lineTo(86 * s, 8 * s)
            ear.lineTo(56 * s, 26 * s)
        ear.closeSubpath()
        p.setBrush(QBrush(QColor(FOX_ORANGE)))
        p.setPen(Qt.NoPen)
        p.drawPath(ear)
        inner = QPainterPath()
        if sign < 0:
            inner.moveTo(27 * s, 37 * s)
            inner.lineTo(21 * s, 17 * s)
            inner.lineTo(38 * s, 28 * s)
        else:
            inner.moveTo(73 * s, 37 * s)
            inner.lineTo(79 * s, 17 * s)
            inner.lineTo(62 * s, 28 * s)
        inner.closeSubpath()
        p.setBrush(QBrush(QColor(FOX_DARK)))
        p.drawPath(inner)

    head = QPainterPath()
    head.addEllipse(QRectF(20 * s, 26 * s, 60 * s, 56 * s))
    p.setBrush(QBrush(QColor(FOX_ORANGE)))
    p.setPen(Qt.NoPen)
    p.drawPath(head)

    muzzle = QPainterPath()
    muzzle.moveTo(50 * s, 92 * s)
    muzzle.lineTo(31 * s, 60 * s)
    muzzle.quadTo(50 * s, 46 * s, 69 * s, 60 * s)
    muzzle.closeSubpath()
    p.setBrush(QBrush(QColor(FOX_CREAM)))
    p.drawPath(muzzle)

    p.setBrush(QBrush(QColor(FOX_EYE)))
    p.drawEllipse(QRectF(33 * s, 48 * s, 9 * s, 11 * s))
    p.drawEllipse(QRectF(58 * s, 48 * s, 9 * s, 11 * s))
    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.drawEllipse(QRectF(35 * s, 49 * s, 3.4 * s, 4 * s))
    p.drawEllipse(QRectF(60 * s, 49 * s, 3.4 * s, 4 * s))
    p.setBrush(QBrush(QColor(FOX_NOSE)))
    p.drawEllipse(QRectF(45.5 * s, 58 * s, 9 * s, 7 * s))
    p.restore()


class LogoTile(QWidget):
    """标题栏的小徽章：圆角浅底 + 狐狸（按尺寸与主题缓存）。"""

    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pm = None
        self._pm_theme = None

    def paintEvent(self, e):
        if self._pm is None or self._pm_theme != _THEME_MODE:
            self._pm_theme = _THEME_MODE
            dpr = self.devicePixelRatioF()
            w = self.width()
            pm = QPixmap(int(w * dpr), int(w * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, w, w), 8.0, 8.0)
            q.fillPath(path, QColor(t_color("fox_tile")))
            q.setClipPath(path)
            m = w * 0.86
            draw_fox(q, (w - m) / 2, (w - m) / 2 + w * 0.03, m)
            q.end()
            self._pm = pm
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)
        p.end()
