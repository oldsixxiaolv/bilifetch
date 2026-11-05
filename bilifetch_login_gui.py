#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站扫码登录对话框。

以前取二维码、轮询、查昵称全在界面线程里做：每 2 秒一次网络请求，
网络稍慢窗口就僵住（最长 15 秒）。现在全部放到后台线程，界面只收结果。

设计工程与动效升级（Emil Kowalski Design Engineering）：
  * 二维码加载完成时采用 scale(0.95) -> scale(1.0) + opacity(0 -> 1) 的 180ms --ease-out 入场。
  * 已扫码 / 二维码失效 / 登录成功时，二维码上方柔和浮现半透明磨砂遮罩与矢量状态徽章，
    让状态切换清晰直观，不再靠生硬清掉图片写纯文字。
"""

from PyQt5.QtCore import QPointF, QRectF, Qt, QThread, QTimer, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

import bilifetch_login as login_mod
from bilifetch_ui import (ACCENT, FIELD, GREEN, INK, INK_2, INK_3, LINE, Button, Card,
                          Spinner, animate_dialog_open, ease_out, make_icon,
                          reduced_motion, ui_font)

_orphans = []     # 对话框关了但线程还在等网络：先挂在这里，跑完再释放


class QrThread(QThread):
    """取二维码 -> 轮询，状态通过信号送回界面。"""

    qr_ready = pyqtSignal(bytes)
    state = pyqtSignal(str, str)          # 状态, 说明
    success = pyqtSignal(str, str)        # cookie, 昵称
    failed = pyqtSignal(str)

    def __init__(self, proxy=None, parent=None):
        super().__init__(parent)
        self.proxy = proxy
        self._stop = False

    def stop(self):
        self._stop = True

    def _sleep(self, sec):
        for _ in range(int(sec * 10)):
            if self._stop:
                return
            self.msleep(100)

    def run(self):
        try:
            login = login_mod.QrLogin(proxy=self.proxy)
            png, _key = login.make_qr_png()
        except Exception as e:
            if not self._stop:
                self.failed.emit("获取二维码失败：%s" % e)
            return
        if self._stop:
            return
        self.qr_ready.emit(png)
        errors = 0
        while not self._stop:
            self._sleep(1.5)
            if self._stop:
                return
            try:
                st, msg, cookie = login.poll()
                errors = 0
            except Exception as e:
                errors += 1
                if errors >= 3:
                    self.failed.emit("网络错误：%s" % e)
                    return
                continue
            if st == login_mod.DONE:
                name = login.whoami(cookie or "") or "已登录"
                self.success.emit(cookie or "", name)
                return
            if st == login_mod.EXPIRED:
                self.state.emit(st, msg)
                return
            self.state.emit(st, msg)


class QrBox(QWidget):
    """二维码展示框：支持 scale(0.95)->1.0 入场过渡与扫码/过期状态遮罩。"""

    def __init__(self, size=220, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pm = None
        self._enter_prog = 0.0
        self._overlay_mode = None      # None / "scanned" / "expired" / "done"
        self._overlay_prog = 0.0

        self._enter_anim = QVariantAnimation(self)
        self._enter_anim.setDuration(180)
        self._enter_anim.setEasingCurve(ease_out())
        self._enter_anim.valueChanged.connect(self._on_enter)

        self._ov_anim = QVariantAnimation(self)
        self._ov_anim.setDuration(180)
        self._ov_anim.setEasingCurve(ease_out())
        self._ov_anim.valueChanged.connect(self._on_ov)

    def _on_enter(self, v):
        self._enter_prog = float(v)
        self.update()

    def _on_ov(self, v):
        self._overlay_prog = float(v)
        self.update()

    def clear(self):
        self._pm = None
        self._overlay_mode = None
        self._enter_prog = 0.0
        self._overlay_prog = 0.0
        self.update()

    def setText(self, text):
        if "失效" in (text or ""):
            self.setOverlay("expired")

    def setPixmap(self, pm):
        self._pm = pm
        self._overlay_mode = None
        self._overlay_prog = 0.0
        if reduced_motion():
            self._enter_prog = 1.0
            self.update()
        else:
            self._enter_anim.stop()
            self._enter_anim.setStartValue(0.0)
            self._enter_anim.setEndValue(1.0)
            self._enter_anim.start()

    def setOverlay(self, mode):
        if self._overlay_mode == mode:
            return
        self._overlay_mode = mode
        if mode is None:
            self._overlay_prog = 0.0
            self.update()
            return
        if reduced_motion():
            self._overlay_prog = 1.0
            self.update()
        else:
            self._ov_anim.stop()
            self._ov_anim.setStartValue(0.0)
            self._ov_anim.setEndValue(1.0)
            self._ov_anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())

        p.setPen(QPen(QColor(LINE if self._pm else "transparent"), 1))
        p.setBrush(QColor("#FFFFFF" if self._pm else FIELD))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        if self._pm is not None:
            p.save()
            p.setOpacity(self._enter_prog)
            if not reduced_motion():
                sc = 0.95 + 0.05 * self._enter_prog
                p.translate(r.center())
                p.scale(sc, sc)
                p.translate(-r.center())
            side = self.width() - 16
            p.drawPixmap(QRectF(8, 8, side, side).toRect(), self._pm)
            p.restore()

        if self._overlay_mode and self._overlay_prog > 0.01:
            p.save()
            p.setOpacity(self._overlay_prog)
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(1, 1, -1, -1), 11, 11)
            p.fillPath(path, QColor(255, 255, 255, 228))

            cx, cy = r.center().x(), r.center().y() - 10
            if not reduced_motion():
                sc = 0.92 + 0.08 * self._overlay_prog
                p.translate(cx, cy)
                p.scale(sc, sc)
                p.translate(-cx, -cy)

            badge = QRectF(cx - 22, cy - 22, 44, 44)
            p.setPen(Qt.NoPen)
            if self._overlay_mode in ("scanned", "done"):
                p.setBrush(QColor("#E9F8F0"))
                p.drawEllipse(badge)
                p.drawPixmap(QPointF(cx - 11, cy - 11), make_icon("check", GREEN, 22))
                label = "登录成功" if self._overlay_mode == "done" else "已扫码，待手机确认"
                col = INK
            else:
                p.setBrush(QColor(FIELD))
                p.drawEllipse(badge)
                p.drawPixmap(QPointF(cx - 10, cy - 10), make_icon("retry", INK_2, 20))
                label = "二维码已失效"
                col = INK_2

            p.setPen(QColor(col))
            p.setFont(ui_font(13, QFont.DemiBold))
            p.drawText(QRectF(0, cy + 30, r.width(), 22), Qt.AlignCenter, label)
            p.restore()
        p.end()


class LoginDialog(QDialog):
    """显示二维码，轮询登录状态，成功后把 cookie 交给调用方。"""

    def __init__(self, parent=None, proxy=None):
        super().__init__(parent)
        self.setWindowTitle("登录 B 站")
        self.setFixedSize(380, 470)
        self.cookie = ""
        self.nickname = ""
        self.proxy = proxy
        self._thread = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        card = Card(padding=(22, 22, 22, 20))
        lay = card.layout
        lay.setSpacing(10)

        title = QLabel("扫码登录")
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        tip = QLabel("打开手机「哔哩哔哩」App，扫描下方二维码")
        tip.setObjectName("sub")
        tip.setAlignment(Qt.AlignCenter)
        lay.addWidget(tip)
        lay.addSpacing(6)

        self.qr = QrBox(220)
        self.spinner = Spinner(26, parent=self.qr)
        self.spinner.move((220 - 26) // 2, (220 - 26) // 2)
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        lay.addSpacing(4)

        self.status = QLabel("正在获取二维码…")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setObjectName("sub")
        lay.addWidget(self.status)

        self.btn_refresh = Button("刷新二维码", "secondary", "retry")
        self.btn_refresh.clicked.connect(self._new_qr)
        lay.addWidget(self.btn_refresh, 0, Qt.AlignHCenter)

        perk = QLabel("登录后可下载 1080P / 4K 等高清画质")
        perk.setObjectName("muted")
        perk.setAlignment(Qt.AlignCenter)
        lay.addWidget(perk)

        root.addWidget(card)
        animate_dialog_open(self)
        QTimer.singleShot(0, self._new_qr)

    def _new_qr(self):
        self._stop_thread()
        self.qr.clear()
        self.spinner.show()
        self.status.setText("正在获取二维码…")
        self.btn_refresh.setEnabled(False)
        t = QrThread(self.proxy, self)
        t.qr_ready.connect(self._on_qr)
        t.state.connect(self._on_state)
        t.success.connect(self._on_success)
        t.failed.connect(self._on_failed)
        self._thread = t
        t.start()

    def _on_qr(self, png):
        self.spinner.hide()
        pm = QPixmap()
        if not pm.loadFromData(png):
            self._on_failed("二维码图片解码失败")
            return
        # 二维码原图 400 多像素，不缩放的话 QLabel 会裁掉一截（手机扫不出来）。
        # 按 2x 缩到刚好填满，Retina 上也清晰。
        dpr = 2.0
        side = self.qr.width() - 16
        pm = pm.scaled(int(side * dpr), int(side * dpr), Qt.KeepAspectRatio,
                       Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.qr.setPixmap(pm)
        self.status.setText("等待扫码…")
        self.btn_refresh.setEnabled(True)

    def _on_state(self, st, msg):
        if st == login_mod.SCANNED:
            self.qr.setOverlay("scanned")
            self.status.setText("已扫码，请在手机上点「确认登录」")
        elif st == login_mod.WAITING:
            self.qr.setOverlay(None)
            self.status.setText("等待扫码…")
        elif st == login_mod.EXPIRED:
            self.qr.setOverlay("expired")
            self.status.setText("二维码已失效，点「刷新二维码」重试")
        else:
            self.status.setText(msg)

    def _on_success(self, cookie, name):
        self.cookie = cookie
        self.nickname = name
        self.qr.setOverlay("done")
        self.status.setText("登录成功：%s" % name)
        self.btn_refresh.setEnabled(False)
        QTimer.singleShot(550, self.accept)

    def _on_failed(self, msg):
        self.spinner.hide()
        self.status.setText(msg)
        self.btn_refresh.setEnabled(True)

    def _stop_thread(self):
        t = self._thread
        self._thread = None
        if t is None:
            return
        t.stop()
        for sig in (t.qr_ready, t.state, t.success, t.failed):
            try:
                sig.disconnect()
            except TypeError:
                pass
        if not t.wait(200):
            # 还卡在网络请求上：别在界面线程干等，摘出来让它自己跑完
            t.setParent(None)
            _orphans.append(t)
            t.finished.connect(lambda th=t: _release(th))

    def done(self, r):
        self._stop_thread()
        super().done(r)


def _release(t):
    t.wait()
    if t in _orphans:
        _orphans.remove(t)
