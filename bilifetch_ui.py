#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享的视觉组件与配色（主窗口、浏览窗口、登录窗口共用，保证风格一致）。

单独拆一个模块是为了避开循环导入：
bilifetch_gui 依赖 bilifetch_collection_gui，反过来就不行了。

设计工程与性能原则（遵循 Emil Kowalski Design Engineering & Apple Fluid Interface 规范）：
  1. 不在高频路径上调 setStyleSheet —— 每调一次 Qt 都要重新解析、重新 polish 整棵子树。
  2. 不给每个小控件配一个常驻 QTimer —— 几十行就是几十个定时器一起唤醒主线程。
  3. 卡片背景（含阴影与高光）按尺寸缓存成位图，重绘时只贴图，不再每帧画多层抗锯齿圆角。
  4. 大列表一律用 QListView + 自绘 delegate，不用 setItemWidget 堆控件。
  5. 动效克制且具物理感：
     - 使用定制强曲线（--ease-out: cubic-bezier(0.23, 1, 0.32, 1)，--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)）。
     - 按钮与可点击控件在 pointer-down 瞬间响应 scale(0.97) 按压反馈（按下 100ms、释放 160ms 非对称时序）。
     - 分段控制器采用 clip-path 双层裁剪技术，让滑块与文字颜色在像素级边界同步过渡。
     - 高频数字（进度、速度、计数）统一使用等宽数字（tabular-nums），消除跳字抖动。
     - 尊重系统/环境变量的减弱动态效果（prefers-reduced-motion）。
"""

import math
import os
import subprocess
import sys

from PyQt5.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation,
                          pyqtSignal)
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractButton, QComboBox, QFrame, QGraphicsOpacityEffect,
                             QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 配色
# 取 B 站官方 Web 端的中性灰阶 + 品牌粉，只保留一个强调色，不再到处用粉蓝渐变。
ACCENT = "#FB7299"        # 品牌粉：主按钮、选中态
ACCENT_HOVER = "#FC86A8"
ACCENT_PRESS = "#E8628A"
ACCENT_SOFT = "#FFF0F4"   # 粉色浅底
BLUE = "#00AEEC"          # 进度条
GREEN = "#2BB673"
RED = "#F25D59"
ORANGE = "#FF9F2E"

INK = "#18191C"           # 主文字
INK_2 = "#61666D"         # 次文字
INK_3 = "#9499A0"         # 弱文字
PAGE = "#F6F7F8"          # 窗口底色
CARD = "#FFFFFF"
FIELD = "#F1F2F3"         # 输入框底色
FIELD_HOVER = "#E9EAEC"
LINE = "#E3E5E7"
TRACK = "#EDEEF0"
DARK = "#16181D"          # 日志面板
DARK_FG = "#B4BAC4"

# 兼容旧名字（别的模块/脚本可能还在引用）
PINK, PINK_D, BLUE_D = ACCENT, ACCENT_PRESS, "#0098D1"

STATE_COLORS = {
    "wait": (INK_3, "#F1F2F3"),
    "run": (BLUE, "#E6F7FD"),
    "merge": (ORANGE, "#FFF4E6"),
    "done": (GREEN, "#E9F8F0"),
    "fail": (RED, "#FDEEEE"),
    "cancel": (INK_3, "#F1F2F3"),
}

# ---------------------------------------------------------------- 动效 Token 与自定义曲线
# 严格对齐 Emil Kowalski 的曲线与时长预算（UI 动效控制在 300ms 以内）
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


_EASE_OUT = _make_bezier(0.23, 1.0, 0.32, 1.0)
_EASE_IN_OUT = _make_bezier(0.77, 0.0, 0.175, 1.0)
_EASE_DRAWER = _make_bezier(0.32, 0.72, 0.0, 1.0)


def ease_out():
    """强 ease-out：cubic-bezier(0.23, 1, 0.32, 1)，用于入场、按压反馈、弹层。"""
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


# ---------------------------------------------------------------- 字体与排版（Optical Sizing & Tabular Nums）
def ui_font(px=13, weight=QFont.Normal, tabular=False):
    """构建符合 Apple Typography 规范的界面字体：按字号微调字距（tracking）。"""
    f = QFont()
    if tabular:
        if sys.platform == "darwin":
            f.setFamily("SF Pro Text")
        f.setStyleHint(QFont.Monospace)
        f.setFixedPitch(False)
    f.setPixelSize(px)
    f.setWeight(weight)
    # 大字号收紧字距，极小字号微放宽字距，正文字距保持自然
    if px >= 18:
        f.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
    elif px <= 11:
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.15)
    return f


def tabular_font(px=12, weight=QFont.Normal):
    """用于实时刷新的数字（百分比、网速、剩余时间、大小）：采用等宽数字的无衬线 UI 字体，既与界面融合又彻底消除跳字抖动。"""
    f = QFont()
    if sys.platform == "darwin":
        f.setFamilies(["Helvetica Neue", "PingFang SC", ".AppleSystemUIFont"])
    else:
        f.setFamilies(["Inter", "Liberation Sans", "DejaVu Sans", "Arial", "sans-serif"])
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


# ---------------------------------------------------------------- 全局样式表
# 只在启动时 setStyleSheet 一次。动态状态一律靠自绘或 property，不再反复设样式。
QSS = """
QWidget { color: %INK%; }
QMainWindow, QDialog { background: %PAGE%; }
QToolTip {
    background: rgba(24, 25, 28, 242);
    color: #F6F7F8;
    border: 1px solid rgba(255, 255, 255, 22);
    padding: 5px 9px;
    border-radius: 7px;
    font-size: 12px;
}

QLabel#h1    { font-size: 20px; font-weight: 700; color: %INK%; }
QLabel#h2    { font-size: 15px; font-weight: 600; color: %INK%; }
QLabel#muted { font-size: 12px; color: %INK_3%; }
QLabel#sub   { font-size: 12px; color: %INK_2%; }

QLineEdit {
    background: %FIELD%;
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 0 12px;
    min-height: 36px;
    font-size: 13px;
    selection-background-color: %ACCENT%;
    selection-color: #ffffff;
}
QLineEdit:hover { background: %FIELD_HOVER%; }
QLineEdit:focus { background: #ffffff; border: 1.5px solid %ACCENT%; }
QLineEdit#bigInput { min-height: 46px; border-radius: 12px; padding: 0 16px; font-size: 14px; }
QLineEdit#search { min-height: 32px; border-radius: 9px; }

QComboBox {
    background: %FIELD%;
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 0 30px 0 12px;
    min-height: 36px;
    min-width: 96px;
    font-size: 13px;
}
QComboBox:hover { background: %FIELD_HOVER%; }
QComboBox:focus { border: 1.5px solid %ACCENT%; background: #ffffff; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid %LINE%;
    border-radius: 10px;
    padding: 4px;
    outline: none;
    selection-background-color: %ACCENT_SOFT%;
    selection-color: %ACCENT%;
}

QCheckBox { color: %INK_2%; spacing: 7px; font-size: 13px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1.5px solid #C9CCD0; background: #ffffff;
}
QCheckBox::indicator:hover { border-color: %ACCENT%; }
QCheckBox::indicator:checked { background: %ACCENT%; border-color: %ACCENT%; }

QListView { background: #ffffff; border: none; outline: none; }

QPlainTextEdit {
    background: %DARK%;
    color: %DARK_FG%;
    border: none;
    border-radius: 10px;
    padding: 10px 12px;
    font-family: Menlo, Consolas, monospace;
    font-size: 12px;
    selection-background-color: %ACCENT%;
    selection-color: #ffffff;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D3D5D8; border-radius: 3px; min-height: 32px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: #B9BCC0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0; }

QMenuBar { background: %PAGE%; color: %INK_2%; }
QMenu { background: #ffffff; border: 1px solid %LINE%; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: %INK%; font-size: 13px; }
QMenu::item:selected { background: %FIELD%; }
QMenu::item:disabled { color: %INK_3%; }
QMenu::separator { height: 1px; background: %LINE%; margin: 4px 8px; }

QMessageBox QLabel { font-size: 13px; }
QMessageBox QPushButton, QFileDialog QPushButton {
    min-width: 64px; padding: 5px 14px; border-radius: 7px;
    background: %FIELD%; border: none;
}
"""
for _k, _v in {"INK": INK, "INK_2": INK_2, "INK_3": INK_3, "PAGE": PAGE, "FIELD": FIELD,
               "FIELD_HOVER": FIELD_HOVER, "LINE": LINE, "DARK": DARK, "DARK_FG": DARK_FG,
               "ACCENT": ACCENT, "ACCENT_SOFT": ACCENT_SOFT}.items():
    QSS = QSS.replace("%" + _k + "%", _v)


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


# ---------------------------------------------------------------- 图标
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
        # 齿轮：外圈 8 个齿的闭合轮廓 + 中心圆孔
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
    elif kind == "open":
        # 打开文件夹：方框 + 右上斜箭头
        p.drawPolyline([QPointF(7, 3), QPointF(4.2, 3), QPointF(3, 4.2), QPointF(3, 11.8),
                        QPointF(4.2, 13), QPointF(11.8, 13), QPointF(13, 11.8), QPointF(13, 9)])
        p.drawLine(QPointF(8.5, 7.5), QPointF(13, 3))
        p.drawPolyline([QPointF(9.5, 3), QPointF(13, 3), QPointF(13, 6.5)])
    elif kind == "stop":
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(4.5, 4.5, 7, 7), 1.5, 1.5)
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
def draw_scroll_edge_fade(p, viewport_rect, scrollbar, bg_color=CARD, fade_h=28):
    """当列表发生滚动或内容溢出时，在顶部/底部绘制柔和渐隐遮罩，避免末行文字被生硬腰斩。"""
    if scrollbar is None:
        return
    val = scrollbar.value()
    mx = scrollbar.maximum()
    if val <= 0 and mx <= 0:
        return
    c_solid = QColor(bg_color)
    c_mid = QColor(bg_color)
    c_mid.setAlpha(210)
    c_trans = QColor(bg_color)
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
    """白色圆角卡片 + 柔和多层环境投影。

    背景（含投影）按尺寸缓存成一张位图：卡片里的子控件每次刷新时，
    父级只需要贴一次图，而不是重新画多层抗锯齿半透明圆角。
    支持 drop_active 高亮态（拖放链接悬停在窗口上时提供平滑的视觉引导）。
    """

    MARGIN = 6       # 给投影留的边
    RADIUS = 14

    def __init__(self, parent=None, padding=(18, 16, 18, 16)):
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
        # 投影：多层极淡圆角叠出的自然柔边，只在缓存时画一次
        for i, a in ((5, 3), (3.5, 5), (2, 7), (1, 10)):
            p.setBrush(QColor(15, 20, 30, a))
            p.drawRoundedRect(r.adjusted(-i * 0.6, -i * 0.2, i * 0.6, i * 0.9),
                              self.RADIUS + i * 0.6, self.RADIUS + i * 0.6)
        p.setBrush(mix(CARD, ACCENT_SOFT, self._highlight * 0.25))
        border_col = mix(QColor(232, 234, 237), QColor(ACCENT), self._highlight)
        p.setPen(QPen(border_col, 1.0 + 0.5 * self._highlight))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        p.end()
        return pm

    def paintEvent(self, e):
        key = (self.width(), self.height(), self.devicePixelRatioF(), round(self._highlight, 3))
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()


# ---------------------------------------------------------------- 按钮
class Button(QAbstractButton):
    """自绘按钮（遵循 Emil Kowalski 按压反馈与非对称动画时序）。

    kind: primary（品牌粉实心）/ secondary（浅灰底）/ ghost（透明，悬停才有底）
    * 悬停：140ms --ease-out 颜色平滑过渡。
    * 按压（:active）：pointer-down 瞬间 100ms 缩放到 scale(0.97)，松手 160ms --ease-out 回弹。
      QPainter 整体缩放让背景、图标、文字等比联动，触感真实自然。
    * 加载态（setLoading）：内置 620ms 高转速内联弧形转圈，提升感知性能。
    """

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
                self._spin_anim.setDuration(620)   # 快速旋转提升感知响应速度
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
        if self.kind == "primary":
            if not enabled and not self._loading:
                return QColor("#F7B8CB"), QColor("#FFFFFF")
            if self._loading:
                return QColor(ACCENT), QColor("#FFFFFF")
            base = mix(ACCENT, ACCENT_HOVER, self._hover)
            return mix(base, ACCENT_PRESS, self._press), QColor("#FFFFFF")
        if self.kind == "ghost":
            fg = mix(INK_2, INK, self._hover * 0.6) if enabled else QColor("#C4C7CB")
            base = mix(QColor(241, 242, 243, 0), FIELD, self._hover)
            return mix(base, "#E3E5E7", self._press), fg
        # secondary
        fg = QColor(INK) if enabled else QColor("#B8BBBF")
        base = mix(FIELD, "#E6E7E9", self._hover)
        return mix(base, "#DDDFE2", self._press), fg

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        w = fm.horizontalAdvance(self.text()) if self.text() else 0
        has_ic = bool(self._icon_kind or self._loading)
        if has_ic:
            w += 16 + (6 if self.text() else 0)
        pad = 16 if self.text() else 10
        return QSize(w + pad * 2, self._h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _font(self):
        return ui_font(13, QFont.DemiBold if self.kind == "primary" else QFont.Medium)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg, fg = self._colors()
        r = QRectF(self.rect())

        # 按压微缩放（scale(0.97)）：文字与图标随容器一同自然内缩
        if self._press > 0.001 and not reduced_motion():
            s = 1.0 - (1.0 - self.PRESS_SCALE) * self._press
            cx, cy = r.center().x(), r.center().y()
            p.translate(cx, cy)
            p.scale(s, s)
            p.translate(-cx, -cy)

        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        rad = min(10.0, r.height() / 2.0)
        p.drawRoundedRect(r, rad, rad)

        # 主按钮顶部细微高光边（Apple 材质层次感）
        if self.kind == "primary" and (self.isEnabled() or self._loading):
            p.setPen(QPen(QColor(255, 255, 255, 48), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad - 0.5, rad - 0.5)

        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus:
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)

        f = self._font()
        p.setFont(f)
        p.setPen(fg)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text()) if self.text() else 0
        has_ic = bool(self._icon_kind or self._loading)
        iw = 16 if has_ic else 0
        gap = 6 if (iw and tw) else 0
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

    def __init__(self, icon, tooltip="", parent=None, size=32):
        super().__init__("", "ghost", icon, parent, height=size)
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)

    def sizeHint(self):
        return QSize(self._h, self._h)


# ---------------------------------------------------------------- 分段切换
class Segmented(QWidget):
    """分段切换控件：采用 Emil Kowalski 的 Clip-Path 双层绘制技术。

    底层绘制未选中态（INK_3），上层在白色药丸滑块的裁剪路径（QPainter.setClipPath）内
    绘制选中态（INK + 品牌粉微章）。滑块滑过文字时，字色在滑块边缘像素级同步切换，
    彻底消除颜色插值带来的中间态发灰问题。
    """

    changed = pyqtSignal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.labels = list(labels)
        self._index = 0
        self._pos = 0.0
        self._pressed_seg = -1
        self._press_val = 0.0
        self._badges = [""] * len(self.labels)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DUR_SEGMENT)
        self._anim.setEasingCurve(ease_in_out())
        self._anim.valueChanged.connect(self._on_anim)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(DUR_PRESS_IN)
        self._press_anim.setEasingCurve(ease_out())
        self._press_anim.valueChanged.connect(self._on_press)

        self._font = ui_font(13, QFont.Medium)
        self._font_active = ui_font(13, QFont.DemiBold)
        self._font_badge = tabular_font(11, QFont.DemiBold)
        self._recalc_width()

    def _recalc_width(self):
        fm = QFontMetrics(self._font_active)
        fm_b = QFontMetrics(self._font_badge)
        max_w = 0
        for i, t in enumerate(self.labels):
            w = fm.horizontalAdvance(t)
            if self._badges[i]:
                w += 6 + max(18, fm_b.horizontalAdvance(self._badges[i]) + 10)
            max_w = max(max_w, w)
        self._seg_w = max(72, max_w + 34)
        self.setFixedWidth(self._seg_w * len(self.labels) + 6)

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

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = int((e.pos().x() - 3) // self._seg_w)
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
        f = self._font_active if active else self._font
        fm = QFontMetrics(f)
        fm_b = QFontMetrics(self._font_badge)
        for i, t in enumerate(self.labels):
            seg = QRectF(3 + i * self._seg_w, 0, self._seg_w, r.height())
            badge = self._badges[i]
            tw = fm.horizontalAdvance(t)
            bw = max(18, fm_b.horizontalAdvance(badge) + 10) if badge else 0
            gap = 5 if badge else 0
            total_w = tw + gap + bw
            sx = seg.left() + (seg.width() - total_w) / 2.0

            p.setFont(f)
            p.setPen(QColor(INK if active else INK_3))
            p.drawText(QRectF(sx, 0, tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, t)

            if badge:
                br = QRectF(sx + tw + gap, (r.height() - 16) / 2.0, bw, 16)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(ACCENT_SOFT if active else "#E4E6E9"))
                p.drawRoundedRect(br, 8, 8)
                p.setFont(self._font_badge)
                p.setPen(QColor(ACCENT if active else INK_2))
                p.drawText(br, Qt.AlignCenter, badge)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(FIELD))
        p.drawRoundedRect(r, 9, 9)

        # 1. 底层：绘制全部未激活标签
        self._draw_labels(p, r, active=False)

        # 2. 白色药丸滑块（支持按压时轻微内缩反馈）
        pill = QRectF(3 + self._pos * self._seg_w, 3, self._seg_w, r.height() - 6)
        if self._press_val > 0.01 and not reduced_motion():
            dx = pill.width() * 0.015 * self._press_val
            dy = pill.height() * 0.025 * self._press_val
            pill = pill.adjusted(dx, dy, -dx, -dy)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 20, 30, 16))
        p.drawRoundedRect(pill.adjusted(0, 1.0, 0, 1.0), 7, 7)
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QPen(QColor(0, 0, 0, 10), 0.5))
        p.drawRoundedRect(pill, 7, 7)

        # 3. 顶层：Clip-Path 裁剪在滑块区域内，绘制激活态标签
        clip = QPainterPath()
        clip.addRoundedRect(pill, 7, 7)
        p.save()
        p.setClipPath(clip)
        self._draw_labels(p, r, active=True)
        p.restore()
        p.end()


# ---------------------------------------------------------------- 小部件
class Avatar(QWidget):
    """圆形头像：昵称首字 + 品牌色底。"""

    def __init__(self, size=26, parent=None):
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
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(QRectF(self.rect()))
        p.setPen(QColor("#FFFFFF"))
        p.setFont(ui_font(int(self.height() * 0.46), QFont.DemiBold))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class AccountChip(QAbstractButton):
    """右上角的账号胶囊：已登录显示头像 + 昵称；未登录显示「登录」。

    支持 --ease-out 悬停与 pointer-down scale(0.97) 按压反馈；
    超长昵称自动省略并附带完整昵称 Tooltip（break-ui 规范）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._name = None
        self._hover = 0.0
        self._press = 0.0
        self.setFixedHeight(34)

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

        if self._press > 0.001 and not reduced_motion():
            s = 1.0 - 0.03 * self._press
            cx, cy = r.center().x(), r.center().y()
            p.translate(cx, cy)
            p.scale(s, s)
            p.translate(-cx, -cy)

        p.setPen(Qt.NoPen)
        if self._name:
            bg = mix(mix("#FFFFFF", FIELD, self._hover), "#E4E6E9", self._press)
            p.setBrush(bg)
            p.setPen(QPen(QColor(LINE), 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), r.height() / 2, r.height() / 2)
            av = QRectF(5, 5, r.height() - 10, r.height() - 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(av)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(ui_font(12, QFont.DemiBold))
            p.drawText(av, Qt.AlignCenter, first_grapheme(self._name))
            p.setPen(QColor(INK))
            p.setFont(self._font())
            fm = QFontMetrics(self._font())
            tr = QRectF(av.right() + 8, 0, r.width() - av.right() - 8 - 26, r.height())
            elided = fm.elidedText(self._name, Qt.ElideRight, int(tr.width()))
            p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, elided)
            p.drawPixmap(QPointF(r.width() - 24, (r.height() - 14) / 2),
                         make_icon("chevron", INK_3, 14))
        else:
            bg = mix(mix(ACCENT_SOFT, "#FFE3EB", self._hover), "#FFD4E1", self._press)
            p.setBrush(bg)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.drawPixmap(QPointF(12, (r.height() - 16) / 2), make_icon("user", ACCENT, 16))
            p.setPen(QColor(ACCENT))
            p.setFont(ui_font(13, QFont.DemiBold))
            p.drawText(QRectF(34, 0, r.width() - 40, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, "登录")
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
                     make_icon("chevron", INK_2 if self.underMouse() else INK_3, 14))
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
    line.setStyleSheet("background:%s; border:none;" % LINE)
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
    """画一个简约的狐狸头（纯矢量，任何尺寸都清晰）。

    和 App 图标是同一只狐狸。p 是已开启抗锯齿的 QPainter。
    """
    s = size / 100.0
    p.save()
    p.translate(x, y)
    p.setRenderHint(QPainter.Antialiasing)

    # 耳朵（两个三角）
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

    # 脸
    head = QPainterPath()
    head.addEllipse(QRectF(20 * s, 26 * s, 60 * s, 56 * s))
    p.setBrush(QBrush(QColor(FOX_ORANGE)))
    p.setPen(Qt.NoPen)
    p.drawPath(head)

    # 口鼻（白）
    muzzle = QPainterPath()
    muzzle.moveTo(50 * s, 92 * s)
    muzzle.lineTo(31 * s, 60 * s)
    muzzle.quadTo(50 * s, 46 * s, 69 * s, 60 * s)
    muzzle.closeSubpath()
    p.setBrush(QBrush(QColor(FOX_CREAM)))
    p.drawPath(muzzle)

    # 眼睛
    p.setBrush(QBrush(QColor(FOX_EYE)))
    p.drawEllipse(QRectF(33 * s, 48 * s, 9 * s, 11 * s))
    p.drawEllipse(QRectF(58 * s, 48 * s, 9 * s, 11 * s))
    # 高光
    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.drawEllipse(QRectF(35 * s, 49 * s, 3.4 * s, 4 * s))
    p.drawEllipse(QRectF(60 * s, 49 * s, 3.4 * s, 4 * s))
    # 鼻子
    p.setBrush(QBrush(QColor(FOX_NOSE)))
    p.drawEllipse(QRectF(45.5 * s, 58 * s, 9 * s, 7 * s))
    p.restore()


class LogoTile(QWidget):
    """标题栏的小徽章：圆角浅底 + 狐狸（按尺寸缓存）。"""

    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pm = None

    def paintEvent(self, e):
        if self._pm is None:
            dpr = self.devicePixelRatioF()
            w = self.width()
            pm = QPixmap(int(w * dpr), int(w * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, w, w), w * 0.28, w * 0.28)
            q.fillPath(path, QColor("#FFF1E6"))
            q.setClipPath(path)
            m = w * 0.86
            draw_fox(q, (w - m) / 2, (w - m) / 2 + w * 0.03, m)
            q.end()
            self._pm = pm
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)
        p.end()
