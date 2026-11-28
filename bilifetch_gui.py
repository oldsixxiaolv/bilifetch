#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BiliFetch 图形界面（PyQt5）

和 bilifetch.py 共用同一套下载逻辑（bilifetch.py 里的 BiliClient / download_episode），
只是把命令行换成了窗口。

单独运行：python3 bilifetch_gui.py
压力测试：python3 bilifetch_gui.py --break-ui
打包后自检：BiliFetch --selftest <链接> <输出目录>

界面结构与 UX 升级（遵循 ui-ux-pro-max、design-system、Emil Kowalski 与 Apple HIG）：
  * 顶栏：Logo + 账号胶囊 + 主题切换（浅色/深色）+ 设置
  * 输入卡：链接输入（实时识别链接类型胶囊 + 行内错误校验与一键重试，告别弹窗打断）+ 解析；保存位置 + 画质
  * 队列卡：下载 / 日志 分段 + 状态筛选胶囊（全部 / 进行中 / 已完成 / 失败）；
            支持全键盘操作（↑/↓ 选行、Enter 打开/重试、Delete 取消/移除）与 2px 无障碍焦点环
  * 压力测试（Break UI）：支持 Ctrl+Shift+B 或 --break-ui 一键切换「常规 / 极端数据 / 空状态 / 单条 / 1000行压测」
"""

import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from PyQt5.QtCore import (QAbstractListModel, QByteArray, QEvent, QModelIndex,
                          QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                          QThread, QTimer, QVariantAnimation, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
                         QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QAction, QApplication, QDialog,
                             QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView,
                             QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                             QSizePolicy, QStackedWidget, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bilifetch as core          # noqa: E402
import bilifetch_collection as collection        # noqa: E402
import bilifetch_collection_gui as collection_gui     # noqa: E402
import bilifetch_login as login_mod                    # noqa: E402
from bilifetch_collection_gui import CollectionDialog   # noqa: E402
from bilifetch_login_gui import LoginDialog             # noqa: E402
from bilifetch_ui import (ACCENT, ACCENT_SOFT, BLUE, CARD, DUR_POPOVER, DUR_TOAST_IN,  # noqa: E402
                          DUR_TOAST_OUT, FIELD, GREEN, INK, INK_2, INK_3, LINE, ORANGE,
                          QSS, RED, STATE_COLORS, TRACK, AccountChip, Button, Card,
                          ComboBox, IconButton, LogoTile, Segmented, _ui_families,
                          animate_dialog_open, draw_focus_ring, draw_fox,
                          draw_scroll_edge_fade, ease_out, eval_ease_out, is_dark,
                          make_icon, mix, reduced_motion, set_theme, state_colors,
                          t_color, tabular_font, theme, ui_font)

HERE = os.path.dirname(os.path.abspath(__file__))

QUALITY_CHOICES = [
    ("最高画质", 0),
    ("4K", 120),
    ("1080P 60帧", 116),
    ("1080P 高码率", 112),
    ("1080P", 80),
    ("720P 60帧", 74),
    ("720P", 64),
    ("480P", 32),
    ("360P", 16),
]

# 识别剪贴板里的 B 站链接 / ID
LINK_RE = re.compile(r"(bilibili\.com/|b23\.tv/|^BV[0-9A-Za-z]{10}$|^av\d+$|^(ep|ss)\d+$)",
                     re.I)


def classify_link(text):
    """实时识别输入链接的类型，返回 (类型标签, 语义色key) 或 None。"""
    s = (text or "").strip()
    if not s:
        return None
    if re.search(r"(bangumi/play/(ep|ss)\d+|^(ep|ss)\d+$)", s, re.I):
        return ("番剧 / 剧集", "orange")
    if re.search(r"(favlist|fid=\d+)", s, re.I):
        return ("收藏夹", "blue")
    if re.search(r"(/lists/|seriesdetail|season_id=\d+|medialist)", s, re.I):
        return ("合集 / 列表", "blue")
    if re.search(r"b23\.tv/", s, re.I):
        return ("b23 短链", "accent")
    if re.search(r"(bilibili\.com/video/|^BV[0-9A-Za-z]{10}$|^av\d+$)", s, re.I):
        return ("视频", "green")
    if "bilibili.com" in s.lower():
        return ("B 站链接", "accent")
    return None


def load_app_icon():
    """窗口图标：优先用打包好的 .icns / .ico / .png；源码运行时现画一只矢量狐狸。"""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        os.path.join(exe_dir, "..", "Resources", "icon.icns"),
        os.path.join(exe_dir, "icon.ico"),
        os.path.join(exe_dir, "icon_1024.png"),
        os.path.join(HERE, "packaging", "app", "icon.ico"),
        os.path.join(HERE, "packaging", "app", "icon_1024.png"),
    ]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, os.path.join(sys._MEIPASS, "icon.ico"))
        candidates.insert(0, os.path.join(sys._MEIPASS, "icon_1024.png"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.exists(c):
            return QIcon(c)
    pm = QPixmap(128, 128)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_fox(p, 14, 14, 100)
    p.end()
    return QIcon(pm)


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.1f %s") % (n, unit)
        n /= 1024.0


def human_speed(bps):
    if bps >= 1024 * 1024:
        return "%.1f MB/s" % (bps / 1024.0 / 1024.0)
    return "%.0f KB/s" % (bps / 1024.0)


def reveal_label():
    if sys.platform == "darwin":
        return "在访达中显示"
    if sys.platform == "win32":
        return "在资源管理器中显示"
    return "在文件管理器中显示"


def reveal_in_file_manager(path):
    """在访达 / 资源管理器 / 文件管理器里显示并选中文件。"""
    if not path:
        return
    if sys.platform == "darwin":
        if os.path.isfile(path):
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["open", path])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
    else:
        norm = os.path.normpath(path)
        if os.path.isfile(norm):
            subprocess.Popen(["explorer.exe", "/select," + norm])
        else:
            os.startfile(norm if os.path.isdir(norm) else os.path.dirname(norm))


def open_path(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path])
    else:
        os.startfile(path)


# ---------------------------------------------------------------- 后台下载
class DownloadThread(QThread):
    """常驻的下载队列线程。"""

    log_line = pyqtSignal(str)
    job_started = pyqtSignal(int)
    job_title = pyqtSignal(int, str)
    job_part = pyqtSignal(int, int, int)            # id, 第几个分P(0起), 共几个
    job_stage = pyqtSignal(int, str)
    job_quality = pyqtSignal(int, str)              # id, 实际落盘画质名称
    job_progress = pyqtSignal(int, float, float)    # id, 已下字节, 总字节
    job_done = pyqtSignal(int, str)
    job_failed = pyqtSignal(int, str)
    job_cancelled = pyqtSignal(int)

    def __init__(self, cookie, proxy, threads=16, parent=None):
        super().__init__(parent)
        self.cookie = cookie
        self.proxy = proxy
        self.threads = threads
        self._jobs = collections.deque()
        self._lock = threading.Lock()
        self._closed = False
        self._cancel_all = False
        self._cancel_current = False
        self._skip = set()
        self._current = None
        self._client = None

    def add(self, jobs):
        """加任务。线程已经在收尾（不再接活）时返回 False。"""
        with self._lock:
            if self._closed or self._cancel_all:
                return False
            for j in jobs:
                self._skip.discard(j["id"])
                self._jobs.append(j)
            return True

    def cancel_job(self, job_id):
        with self._lock:
            self._skip.add(job_id)
            running = self._current == job_id
            if running:
                self._cancel_current = True
        if running:
            self._abort_network()

    def cancel_all(self):
        with self._lock:
            self._cancel_all = True
            self._jobs.clear()
        self._abort_network()

    def _abort_network(self):
        c = self._client
        if c is not None:
            try:
                c.cancel()
            except Exception:
                pass

    def _should_stop(self):
        return self._cancel_all or self._cancel_current

    def run(self):
        try:
            self._client = core.BiliClient(cookie=self.cookie, proxy=self.proxy or None)
        except Exception as e:
            self.log_line.emit("初始化失败：%s" % e)
            with self._lock:
                self._closed = True
                jobs = list(self._jobs)
                self._jobs.clear()
            for j in jobs:
                self.job_failed.emit(j["id"], str(e))
            return
        ffmpeg = core.find_executable("ffmpeg")
        while True:
            with self._lock:
                if self._cancel_all or not self._jobs:
                    self._closed = True
                    break
                job = self._jobs.popleft()
                if job["id"] in self._skip:
                    continue
                self._current = job["id"]
                self._cancel_current = False
            try:
                self._run_job(job, ffmpeg)
            except Exception as e:
                self.job_failed.emit(job["id"], str(e))
            with self._lock:
                self._current = None

    def _expand(self, job):
        client = self._client
        if job.get("url"):
            info = client.resolve(job["url"])
            self.job_title.emit(job["id"], info["title"])
            self.log_line.emit("解析：%s（UP主 %s）" % (info["title"], info["owner"]))
            return core.plan_jobs(client, info)
        title = job["title"]
        if job.get("cid"):
            return [(title, job["bvid"], job["cid"])]
        pages = client.pagelist(job["bvid"])
        if not pages:
            raise RuntimeError("没有取到分P信息")
        if len(pages) == 1:
            return [(title, job["bvid"], pages[0]["cid"])]
        out = []
        for i, p in enumerate(pages):
            part = p.get("part") or "P%d" % p.get("page")
            out.append((title if i == 0 else "%s - %s" % (title, part), job["bvid"], p["cid"]))
        return out

    def _run_job(self, job, ffmpeg):
        jid = job["id"]
        self.job_started.emit(jid)
        tag = job["title"][:24]
        if not ffmpeg:
            if sys.platform == "darwin":
                hint = "找不到 ffmpeg，请先安装（brew install ffmpeg）"
            elif sys.platform == "win32":
                hint = "找不到 ffmpeg，请运行 winget install Gyan.FFmpeg 或将 ffmpeg.exe 放到本程序目录"
            else:
                hint = "找不到 ffmpeg，请先安装（sudo apt install ffmpeg）"
            self.job_failed.emit(jid, hint)
            return
        try:
            parts = self._expand(job)
        except Exception as e:
            if self._should_stop():
                self.job_cancelled.emit(jid)
            else:
                self.job_failed.emit(jid, str(e))
            return
        n = len(parts)
        last_out, errors = "", []
        for k, (name, bvid, cid) in enumerate(parts):
            if self._should_stop():
                self.job_cancelled.emit(jid)
                return
            if n > 1:
                self.job_part.emit(jid, k, n)
            if cid is None:
                errors.append("拿不到 cid：%s" % name)
                continue
            try:
                last_out = core.download_episode(
                    self._client, bvid, cid, name, job["out_dir"],
                    quality=job["quality"], threads=self.threads,
                    audio_only=job["audio_only"], ffmpeg=ffmpeg,
                    on_log=lambda t: self.log_line.emit("[%s] %s" % (tag, t)),
                    on_progress=lambda d, t: self.job_progress.emit(jid, d, t),
                    on_stage=lambda s: self.job_stage.emit(jid, s),
                    on_quality=lambda q: self.job_quality.emit(jid, q),
                    should_stop=self._should_stop)
            except core.Cancelled:
                self.log_line.emit("[%s] 已取消" % tag)
                self.job_cancelled.emit(jid)
                return
            except Exception as e:
                if self._should_stop():
                    self.job_cancelled.emit(jid)
                    return
                self.log_line.emit("[%s] 失败：%s" % (tag, e))
                errors.append(str(e))
        if errors and len(errors) == n:
            self.job_failed.emit(jid, errors[0])
        elif errors:
            self.job_failed.emit(jid, "%d 个分P失败：%s" % (len(errors), errors[0]))
        else:
            self.job_done.emit(jid, last_out if n == 1 else job["out_dir"])


class LoginCheckThread(QThread):
    """后台查登录态。"""

    done = pyqtSignal(str, str)      # 状态(ok/invalid/error), 昵称

    def __init__(self, cookie, proxy, parent=None):
        super().__init__(parent)
        self.cookie = cookie
        self.proxy = proxy

    def run(self):
        try:
            state, name = login_mod.check_login_state(self.cookie, self.proxy)
        except Exception:
            state, name = "error", ""
        self.done.emit(state, name)


class PreviewThread(QThread):
    """后台读链接内容。"""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, url, cookie, proxy, parent=None):
        super().__init__(parent)
        self.url = url
        self.cookie = cookie
        self.proxy = proxy

    def run(self):
        try:
            client = core.BiliClient(cookie=self.cookie, proxy=self.proxy or None)
            collection_gui.collection_client = client
            self.done.emit(collection.fetch_preview(client, self.url))
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------- 行内链接识别徽章与错误提示条
class LinkBadge(QWidget):
    """实时显示识别到的链接类型方角徽章（取代胶丸，采用 radius/4）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = ""
        self._color_key = "accent"
        self._font = ui_font(12, QFont.DemiBold)
        self.setFixedHeight(24)
        self.hide()

    def setKind(self, info):
        if not info:
            self._label = ""
            self.hide()
            return
        label, color_key = info
        self._label = label
        self._color_key = color_key
        fm = QFontMetrics(self._font)
        self.setFixedWidth(fm.horizontalAdvance(label) + 16)
        self.show()
        self.update()

    def paintEvent(self, e):
        if not self._label:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        c = QColor(t_color(self._color_key))
        bg = QColor(c)
        bg.setAlpha(38 if is_dark() else 26)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 4.0, 4.0)
        p.setFont(self._font)
        p.setPen(c)
        p.drawText(r, Qt.AlignCenter, self._label)
        p.end()


class InlineNotice(QWidget):
    """输入框下方的行内错误与恢复引导条（遵循 ui-ux-pro-max Inline Validation & Error Recovery）。"""

    retryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(16, 16)
        lay.addWidget(self.icon_lbl)
        self.msg_lbl = QLabel()
        self.msg_lbl.setObjectName("err")
        self.msg_lbl.setWordWrap(True)
        lay.addWidget(self.msg_lbl, 1)
        self.btn_retry = Button("重试", "secondary", "retry", height=26)
        self.btn_retry.clicked.connect(self.retryRequested.emit)
        lay.addWidget(self.btn_retry)
        self.btn_dismiss = IconButton("close", "关闭提示", size=24)
        self.btn_dismiss.clicked.connect(self.clear_error)
        lay.addWidget(self.btn_dismiss)
        self.hide()

    def show_error(self, msg, can_retry=False):
        self.icon_lbl.setPixmap(make_icon("warning", t_color("red"), 16))
        self.msg_lbl.setText(str(msg or "解析失败"))
        self.btn_retry.setVisible(bool(can_retry))
        self.show()

    def clear_error(self):
        if self.isVisible():
            self.hide()


# ---------------------------------------------------------------- 队列模型
class QueueModel(QAbstractListModel):
    """下载队列的数据。每个任务是一个 dict，界面按 id 找行。"""

    JobRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs = []
        self._row = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.jobs)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        job = self.jobs[index.row()]
        if role == self.JobRole:
            return job
        if role == Qt.DisplayRole:
            return job["title"]
        if role == Qt.ToolTipRole:
            lines = [job.get("title") or ""]
            if job.get("error"):
                lines.append("原因：" + job["error"])
            elif job.get("path"):
                lines.append("位置：" + job["path"])
            return "\n".join(x for x in lines if x)
        return None

    def _reindex(self):
        self._row = {j["id"]: i for i, j in enumerate(self.jobs)}

    def set_all(self, jobs):
        self.beginResetModel()
        self.jobs = list(jobs)
        self._reindex()
        self.endResetModel()

    def add(self, jobs):
        if not jobs:
            return
        now = time.monotonic()
        for idx, j in enumerate(jobs):
            j["enter_t"] = now + min(idx, 5) * 0.035
        n = len(self.jobs)
        self.beginInsertRows(QModelIndex(), n, n + len(jobs) - 1)
        self.jobs.extend(jobs)
        self.endInsertRows()
        self._reindex()

    def remove_where(self, pred):
        keep = [j for j in self.jobs if not pred(j)]
        if len(keep) == len(self.jobs):
            return
        self.beginResetModel()
        self.jobs = keep
        self._reindex()
        self.endResetModel()

    def get(self, jid):
        r = self._row.get(jid)
        return self.jobs[r] if r is not None else None

    def row_of(self, jid):
        return self._row.get(jid)

    def touch(self, jid):
        r = self._row.get(jid)
        if r is not None:
            ix = self.index(r)
            self.dataChanged.emit(ix, ix)


class QueueDelegate(QStyledItemDelegate):
    ROW_H = 68
    ACTION_W = 64
    ACTION_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_title = ui_font(13, QFont.Medium)
        self.f_meta = ui_font(12)
        self.f_meta_tab = tabular_font(12, QFont.Normal)
        self.f_status_tab = tabular_font(12, QFont.Medium)
        self.f_num = tabular_font(11, QFont.DemiBold)
        self.f_action = ui_font(12, QFont.Medium)
        self.fm_title = QFontMetrics(self.f_title)
        self.fm_meta = QFontMetrics(self.f_meta)
        self.hover_row = -1
        self.focus_row = -1
        self.hover_action = False
        self.press_action = False

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    @staticmethod
    def action_spec(job):
        """返回当前行在悬停时可提供的快捷操作 (kind, icon, label)。"""
        if not job:
            return None
        st = job["state"]
        if st == "done" and job.get("path"):
            return ("reveal", "folder", "定位")
        if st == "pause":
            return ("retry", "play", "继续")
        if st in ("fail", "cancel"):
            return ("retry", "retry", "重试")
        if st in ("wait", "run"):
            return ("cancel", "pause", "暂停")
        return None

    def action_rect(self, option_rect):
        r = QRectF(option_rect).adjusted(8, 3, -8, -3)
        return QRectF(r.right() - self.ACTION_W - 12,
                      r.center().y() - self.ACTION_H / 2.0,
                      self.ACTION_W, self.ACTION_H)

    @staticmethod
    def status_text(job):
        st = job["state"]
        if st == "wait":
            return "等待中"
        if st == "run":
            return human_speed(job.get("speed", 0)) if job.get("speed") else (job.get("stage") or "准备中")
        if st == "merge":
            return "合并中"
        if st == "pause":
            return "已暂停"
        if st == "done":
            return "已完成"
        if st == "fail":
            return "失败"
        return "已取消"

    def meta_text(self, job):
        bits = []
        st = job["state"]
        rq = job.get("resolved_quality")
        if job.get("parts", 1) > 1:
            bits.append("P%d/%d" % (job.get("part", 0) + 1, job["parts"]))
        if rq and st in ("run", "pause", "done"):
            bits.append(rq)
        if st in ("run", "pause") and job.get("total"):
            bits.append("%s / %s" % (human_size(job.get("done_b", 0)), human_size(job["total"])))
            sp = job.get("speed") or 0
            remain = job["total"] - job.get("done_b", 0)
            if st == "run" and sp > 1024 and remain > 0:
                sec = int(remain / sp)
                bits.append("剩余 %d:%02d" % (sec // 60, sec % 60) if sec < 3600
                            else "剩余 %d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60))
        elif st == "fail":
            bits.append(job.get("error") or "下载失败")
        elif st == "done":
            if job.get("size"):
                bits.append(human_size(job["size"]))
            if job.get("path"):
                bits.append(os.path.basename(job["path"]) if os.path.isfile(job["path"])
                            else job["path"])
        elif st in ("wait", "pause"):
            if not rq:
                bits.append(job.get("quality_label", ""))
        if job.get("audio_only") and rq != "仅音频":
            bits.append("仅音频")
        return "  ·  ".join(b for b in bits if b)

    def paint(self, p, option, index):
        job = index.data(QueueModel.JobRole)
        if job is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        t = theme()

        now = time.monotonic()
        enter_t = job.get("enter_t")
        if enter_t is not None and not reduced_motion():
            dt = now - enter_t
            if dt < 0:
                p.restore()
                return
            if dt < 0.22:
                prog = eval_ease_out(dt / 0.22)
                p.setOpacity(prog)
                p.translate(0.0, (1.0 - prog) * 6.0)
            else:
                job.pop("enter_t", None)

        r = QRectF(option.rect).adjusted(8, 3, -8, -3)
        st = job["state"]
        fg, soft = state_colors(st)
        row = index.row()
        is_hover = (row == self.hover_row)
        is_focus = (row == self.focus_row and self.parent() and self.parent().hasFocus())

        if is_hover or is_focus:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["row_hover"]))
            p.drawRoundedRect(r, 8, 8)
        if is_focus:
            draw_focus_ring(p, r, 8)

        # 左侧状态圆
        c = QRectF(r.left() + 12, r.center().y() - 16, 32, 32)
        pct = job.get("shown", 0.0)
        if st in ("run", "merge") or (st == "pause" and pct > 0.5):
            p.setPen(QPen(QColor(t["track"]), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c.adjusted(2, 2, -2, -2))
            pen = QPen(QColor(t["orange"] if st in ("merge", "pause") else t["blue"]), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            if st == "merge":
                ang = job.get("merge_angle", 0.0)
                p.drawArc(c.adjusted(2, 2, -2, -2), int((90 - ang) * 16), int(-240 * 16))
            else:
                span = max(4.0, pct * 3.6)
                p.drawArc(c.adjusted(2, 2, -2, -2), 90 * 16, int(-span * 16))
            if st == "pause":
                p.drawPixmap(int(c.center().x() - 6), int(c.center().y() - 6),
                             make_icon("pause", t["orange"], 12))
            else:
                p.setPen(QColor(t["ink_2"]))
                p.setFont(self.f_num)
                p.drawText(c, Qt.AlignCenter, "%d" % int(pct) if st == "run" else "···")
        else:
            p.save()
            done_t = job.get("done_t")
            if st == "done" and done_t is not None and not reduced_motion():
                dt_done = now - done_t
                if 0.0 <= dt_done < 0.22:
                    sc = 0.86 + 0.14 * eval_ease_out(dt_done / 0.22)
                    p.translate(c.center())
                    p.scale(sc, sc)
                    p.translate(-c.center())
                else:
                    job.pop("done_t", None)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(soft))
            p.drawRoundedRect(c, 8, 8)
            icon = {"done": "check", "fail": "close", "cancel": "stop", "pause": "pause"}.get(st)
            if icon:
                p.drawPixmap(int(c.center().x() - 8), int(c.center().y() - 8),
                             make_icon(icon, fg, 16))
            else:
                p.setPen(QColor(t["ink_3"]))
                p.setFont(self.f_num)
                p.drawText(c, Qt.AlignCenter, "%d" % (row + 1))
            p.restore()

        # 右侧状态或悬停快捷操作胶囊
        spec = self.action_spec(job) if (is_hover or is_focus) else None
        right_w = 96
        x = c.right() + 14
        tw = max(40.0, r.right() - x - right_w - 14)
        top = r.center().y() - 19

        p.setFont(self.f_title)
        p.setPen(QColor(t["ink"] if st != "cancel" else t["ink_3"]))
        p.drawText(QRectF(x, top, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   self.fm_title.elidedText(job["title"], Qt.ElideRight, int(tw)))

        if spec is not None:
            act_r = self.action_rect(option.rect)
            p.save()
            if self.hover_action and self.press_action and not reduced_motion():
                p.translate(act_r.center())
                p.scale(0.95, 0.95)
                p.translate(-act_r.center())
            bg_c = QColor(t["field_press"]) if (self.hover_action and self.press_action) else (
                QColor(t["field_hover"]) if self.hover_action else QColor(t["card"]))
            p.setBrush(bg_c)
            p.setPen(QPen(QColor(t["line"]), 1))
            p.drawRoundedRect(act_r, 8, 8)
            ic_color = t["red"] if spec[0] == "cancel" else (t["accent"] if spec[0] == "retry" else t["ink"])
            p.drawPixmap(QPointF(act_r.left() + 10, act_r.center().y() - 6.5),
                         make_icon(spec[1], ic_color, 13))
            p.setFont(self.f_action)
            p.setPen(QColor(ic_color))
            p.drawText(QRectF(act_r.left() + 26, act_r.top(), act_r.width() - 30, act_r.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, spec[2])
            p.restore()
        else:
            status = self.status_text(job)
            p.setFont(self.f_status_tab if (st == "run" and job.get("speed")) else self.f_meta)
            p.setPen(QColor(fg if st != "wait" else t["ink_3"]))
            p.drawText(QRectF(r.right() - right_w - 14, top, right_w, 20),
                       Qt.AlignRight | Qt.AlignVCenter, status)

        meta = self.meta_text(job)
        meta_right_pad = (self.ACTION_W + 24) if spec is not None else 14
        meta_w = max(40.0, r.right() - x - meta_right_pad)
        if st in ("run", "merge") or (st == "pause" and pct > 0.5):
            bar = QRectF(x, top + 26, meta_w, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["track"]))
            p.drawRoundedRect(bar, 2, 2)
            w = bar.width() * (1.0 if st == "merge" else pct / 100.0)
            if w > 1:
                p.setBrush(QColor(t["orange"] if st in ("merge", "pause") else t["blue"]))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), w, bar.height()), 2, 2)
            p.setFont(self.f_meta_tab if st in ("run", "pause") else self.f_meta)
            p.setPen(QColor(t["ink_3"]))
            fm_m = QFontMetrics(p.font())
            p.drawText(QRectF(x, top + 33, meta_w, 16),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm_m.elidedText(meta, Qt.ElideRight, int(meta_w)))
        else:
            p.setFont(self.f_meta)
            p.setPen(QColor(t["red"] if st == "fail" else t["ink_3"]))
            p.drawText(QRectF(x, top + 22, meta_w, 18),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       self.fm_meta.elidedText(meta, Qt.ElideRight, int(meta_w)))
        p.restore()


class QueueView(QListView):
    actionTriggered = pyqtSignal(str, dict)     # action_kind, job
    deleteRequested = pyqtSignal(dict)          # job

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self._empty_filter_text = ""

    def setEmptyFilterText(self, text):
        if self._empty_filter_text != text:
            self._empty_filter_text = text
            self.viewport().update()

    def _visible_rows(self):
        m = self.model()
        if not m:
            return []
        return [i for i in range(m.rowCount()) if not self.isRowHidden(i)]

    def focusInEvent(self, e):
        super().focusInEvent(e)
        d = self.itemDelegate()
        vis = self._visible_rows()
        if vis and d.focus_row not in vis:
            d.focus_row = vis[0]
        if d.focus_row >= 0:
            self.update(self.model().index(d.focus_row))

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        d = self.itemDelegate()
        if d.focus_row >= 0:
            self.update(self.model().index(d.focus_row))

    def keyPressEvent(self, e):
        vis = self._visible_rows()
        d = self.itemDelegate()
        key = e.key()
        if key in (Qt.Key_Down, Qt.Key_Up) and vis:
            cur = d.focus_row if d.focus_row in vis else vis[0]
            idx = vis.index(cur)
            nxt = vis[min(len(vis) - 1, idx + 1)] if key == Qt.Key_Down else vis[max(0, idx - 1)]
            old = d.focus_row
            d.focus_row = nxt
            for r in {old, nxt}:
                if r >= 0:
                    self.update(self.model().index(r))
            self.scrollTo(self.model().index(nxt))
            e.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and d.focus_row in vis:
            ix = self.model().index(d.focus_row)
            self.doubleClicked.emit(ix)
            e.accept()
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and d.focus_row in vis:
            job = self.model().index(d.focus_row).data(QueueModel.JobRole)
            if job:
                self.deleteRequested.emit(job)
            e.accept()
            return
        super().keyPressEvent(e)

    def _hit_action(self, pos):
        ix = self.indexAt(pos)
        if not ix.isValid():
            return ix, None, False
        job = ix.data(QueueModel.JobRole)
        d = self.itemDelegate()
        spec = d.action_spec(job)
        if spec is None:
            return ix, job, False
        rect = d.action_rect(self.visualRect(ix))
        return ix, job, rect.contains(QPointF(pos))

    def mouseMoveEvent(self, e):
        ix, _job, on_act = self._hit_action(e.pos())
        r = ix.row() if ix.isValid() else -1
        d = self.itemDelegate()
        if d.hover_row != r or d.hover_action != on_act:
            old = d.hover_row
            d.hover_row = r
            d.hover_action = on_act
            if not on_act:
                d.press_action = False
            self.setCursor(Qt.PointingHandCursor if on_act else Qt.ArrowCursor)
            for row in {old, r}:
                if row >= 0:
                    self.update(self.model().index(row))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            ix, _job, on_act = self._hit_action(e.pos())
            d = self.itemDelegate()
            if ix.isValid():
                old_f = d.focus_row
                d.focus_row = ix.row()
                if old_f >= 0:
                    self.update(self.model().index(old_f))
            if on_act:
                d.press_action = True
                self.update(ix)
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            d = self.itemDelegate()
            was_pressed = d.press_action
            d.press_action = False
            ix, job, on_act = self._hit_action(e.pos())
            if ix.isValid():
                self.update(ix)
            if was_pressed and on_act and job:
                spec = d.action_spec(job)
                if spec:
                    self.actionTriggered.emit(spec[0], job)
                return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        d = self.itemDelegate()
        if d.hover_row >= 0 or d.hover_action or d.press_action:
            old = d.hover_row
            d.hover_row = -1
            d.hover_action = False
            d.press_action = False
            self.setCursor(Qt.ArrowCursor)
            if old >= 0:
                self.update(self.model().index(old))
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        if self._empty_filter_text:
            vr = self.viewport().rect()
            cx, cy = vr.width() / 2.0, vr.height() / 2.0 - 8
            p.setPen(QColor(t_color("ink_2")))
            p.setFont(ui_font(13, QFont.Medium))
            p.drawText(QRectF(0, cy - 10, vr.width(), 22), Qt.AlignCenter, self._empty_filter_text)
        else:
            draw_scroll_edge_fade(p, self.viewport().rect(), self.verticalScrollBar(), t_color("card"), 28)
        p.end()


class EmptyState(QWidget):
    """队列为空时的提示（整块自绘，支持深浅色主题与拖放悬停反馈）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DUR_POPOVER)
        self._anim.setEasingCurve(ease_out())
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._drag = float(v)
        self.update()

    def setDragActive(self, active):
        target = 1.0 if active else 0.0
        if reduced_motion():
            self._drag = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._drag)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme()
        cx, cy = self.width() / 2.0, self.height() / 2.0 - 24

        p.save()
        if self._drag > 0.001:
            sc = 1.0 + 0.08 * self._drag
            p.translate(cx, cy)
            p.scale(sc, sc)
            p.translate(-cx, -cy)
        circle = QRectF(cx - 30, cy - 30, 60, 60)
        p.setPen(QPen(QColor(t["accent"]), 1.5 * self._drag) if self._drag > 0.05 else Qt.NoPen)
        hi_soft = "#4D2434" if is_dark() else "#FFE0E9"
        p.setBrush(mix(t["accent_soft"], hi_soft, self._drag))
        p.drawEllipse(circle)
        p.drawPixmap(int(cx - 13), int(cy - 13), make_icon("download", t["accent"], 26))
        p.restore()

        p.setPen(QColor(t["accent"] if self._drag > 0.5 else t["ink"]))
        p.setFont(ui_font(15, QFont.DemiBold))
        title = "松开鼠标，立即解析链接" if self._drag > 0.5 else "粘贴链接，开始下载"
        p.drawText(QRectF(0, cy + 44, self.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter, title)
        p.setPen(QColor(t["ink_3"]))
        p.setFont(ui_font(12))
        p.drawText(QRectF(0, cy + 72, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   "支持视频、分P、番剧、合集、收藏夹和 b23.tv 短链")
        p.drawText(QRectF(0, cy + 92, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   "也可以直接把链接拖进窗口")
        p.end()


class Toast(QWidget):
    """底部居中的 Sonner 风格轻提示。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._text = ""
        self._kind = "info"
        self._progress = 0.0
        self._closing = False
        self._remain_ms = 2200
        self._font = ui_font(13, QFont.Medium)

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(ease_out())
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_done)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_close)
        self.hide()

    @staticmethod
    def _infer_kind(text):
        if any(k in text for k in ("失败", "错误", "失效", "不可用")):
            return "warn"
        if any(k in text for k in ("完成", "成功", "已复制", "已加入")):
            return "ok"
        if "剪贴板" in text or "粘贴" in text:
            return "paste"
        return "info"

    def _on_anim(self, v):
        self._progress = float(v)
        self._reposition()
        self.update()

    def _on_anim_done(self):
        if self._closing and self._progress <= 0.01:
            self.hide()

    def _start_close(self):
        self._closing = True
        self._anim.stop()
        self._anim.setDuration(0 if reduced_motion() else DUR_TOAST_OUT)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def enterEvent(self, e):
        if self._hide_timer.isActive():
            self._remain_ms = max(800, self._hide_timer.remainingTime())
            self._hide_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._closing and self.isVisible():
            self._hide_timer.start(self._remain_ms)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._hide_timer.stop()
            self._start_close()

    def _reposition(self):
        par = self.parentWidget()
        if not par:
            return
        base_y = par.height() - self.height() - 22
        offset_y = 0 if reduced_motion() else int((1.0 - self._progress) * (10 if self._closing else 14))
        self.move((par.width() - self.width()) // 2, base_y + offset_y)

    def show_message(self, text, ms=2200, kind=None):
        self._text = str(text or "")
        self._kind = kind or self._infer_kind(self._text)
        self._remain_ms = ms
        self._closing = False
        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(self._text)
        w = min(520, max(140, tw + 16 + 8 + 34 + 12))
        self.setFixedSize(w, 46)
        self._reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(0 if reduced_motion() else DUR_TOAST_IN)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(ms)

    def paintEvent(self, e):
        if self._progress <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self._progress)))
        r = QRectF(self.rect()).adjusted(4, 3, -4, -5)

        if not reduced_motion():
            sc = 0.96 + 0.04 * self._progress
            p.translate(r.center())
            p.scale(sc, sc)
            p.translate(-r.center())

        p.setPen(Qt.NoPen)
        for dy, alpha in ((3.0, 22), (1.5, 38)):
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(r.adjusted(-1, dy, 1, dy + 1), 12, 12)

        p.setBrush(QColor("#1F1F1F"))
        p.setPen(QPen(QColor("#313131"), 1))
        p.drawRoundedRect(r, 12, 12)

        ic_map = {
            "ok": ("check", "#3BB87E"),
            "warn": ("warning", "#E8A246"),
            "paste": ("paste", "#E87598"),
            "info": ("info", "#E87598"),
        }
        ic_name, ic_col = ic_map.get(self._kind, ("info", "#E87598"))
        p.drawPixmap(QPointF(r.left() + 14, r.center().y() - 8), make_icon(ic_name, ic_col, 16))

        p.setFont(self._font)
        p.setPen(QColor("#F5F5F5"))
        fm = QFontMetrics(self._font)
        tx = r.left() + 38
        tw = r.right() - tx - 14
        p.drawText(QRectF(tx, r.top(), tw, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self._text, Qt.ElideRight, int(tw)))
        p.end()


# ---------------------------------------------------------------- Break-UI 压力测试浮动切换栏
class BreakUiBar(QWidget):
    """Emil Kowalski break-ui 技能：在界面底部提供 Demo / 极端数据 / 空状态 / 单条 / 1000行 实时切换器。"""

    modeChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        lbl = QLabel("Break UI 压测")
        lbl.setFont(ui_font(12, QFont.DemiBold))
        lay.addWidget(lbl)
        self.seg = Segmented(["还原", "常规示例", "极端数据", "空状态", "单条", "1000行"], compact=True)
        self.seg.changed.connect(self.modeChanged.emit)
        lay.addWidget(self.seg)
        self.adjustSize()
        self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor(t_color("card")))
        p.setPen(QPen(QColor(t_color("accent")), 1.5))
        # outer=12, gap=6 -> inner compact Segmented radius=6 (12 - 6 = 6)
        p.drawRoundedRect(r, 12, 12)
        p.end()


class PathButton(Button):
    """显示保存目录的按钮：路径太长时中间省略。"""

    MAX_W = 340

    def __init__(self, parent=None):
        super().__init__("", "secondary", "folder", parent)
        self._full = ""

    def setPath(self, path):
        self._full = path
        home = os.path.expanduser("~")
        shown = "~" + path[len(home):] if path.startswith(home) else path
        fm = QFontMetrics(self._font())
        self.setText(fm.elidedText(shown, Qt.ElideMiddle, self.MAX_W - 54))
        self.setToolTip(path)
        self.updateGeometry()

    def path(self):
        return self._full


class SettingsDialog(QDialog):
    """高级设置：Cookie / 代理（不常用，不占主界面）。"""

    def __init__(self, cookie, proxy, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        card = Card(padding=(20, 18, 20, 18))
        lay = card.layout
        lay.setSpacing(8)

        t = QLabel("网络代理")
        t.setObjectName("h2")
        lay.addWidget(t)
        self.proxy = QLineEdit(proxy)
        self.proxy.setPlaceholderText("例如 http://127.0.0.1:7890，留空则直连")
        lay.addWidget(self.proxy)
        h = QLabel("默认不走系统代理（部分 TUN 代理会重置 B 站 CDN 连接）。")
        h.setObjectName("muted")
        h.setWordWrap(True)
        lay.addWidget(h)
        lay.addSpacing(8)

        t2 = QLabel("Cookie")
        t2.setObjectName("h2")
        lay.addWidget(t2)
        self.cookie = QLineEdit(cookie)
        self.cookie.setPlaceholderText("一般用扫码登录即可；也可以粘贴浏览器里复制的整段 Cookie")
        lay.addWidget(self.cookie)
        root.addWidget(card)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = Button("取消", "secondary")
        cancel.clicked.connect(self.reject)
        ok = Button("保存", "primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)
        animate_dialog_open(self)


# ---------------------------------------------------------------- 主窗口
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BiliFetch")
        self.setWindowIcon(load_app_icon())
        self.setAcceptDrops(True)
        self.dl_thread = None
        self._old_threads = []
        self._pending = []
        self._next_id = 1
        self._samples = {}
        self._preview_thread = None
        self._login_thread = None
        self._last_clip = ""
        self._confirm_exit = True
        self._cookie = ""
        self._proxy = ""
        self._nickname = ""
        self._theme_mode = "light"
        self._saved_real_jobs = None
        self._build_ui()
        self._load_settings()
        QTimer.singleShot(80, self._check_login)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        # ---- 顶栏（严格 8px 间距网格，32x32 统一热区与 radius/8 方角）----
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        head.setSpacing(8)
        head.addWidget(LogoTile(32))
        t = QLabel("BiliFetch")
        t.setObjectName("h1")
        head.addWidget(t)
        head.addStretch(1)
        self.account = AccountChip()
        self.account.clicked.connect(self._on_account)
        head.addWidget(self.account)
        self.btn_theme = IconButton("moon", "切换深色 / 浅色外观（⌘T）", size=32)
        self.btn_theme.clicked.connect(self.toggle_theme)
        head.addWidget(self.btn_theme)
        self.btn_settings = IconButton("gear", "设置（代理 / Cookie）", size=32)
        self.btn_settings.clicked.connect(self.on_settings)
        head.addWidget(self.btn_settings)
        root.addLayout(head)

        # ---- 输入卡（outer radius=16, padding=16, inner radius=8）----
        self.input_card = Card(padding=(16, 16, 16, 16))
        card = self.input_card
        card.layout.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("bigInput")
        self.url_edit.setPlaceholderText("粘贴 B 站链接或 BV 号，回车解析")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.on_browse)
        self.url_edit.textChanged.connect(self._on_url_text_changed)
        paste = QAction(QIcon(make_icon("paste", INK_3, 16)), "粘贴", self.url_edit)
        paste.setToolTip("从剪贴板粘贴")
        paste.triggered.connect(self._paste_clipboard)
        self.url_edit.addAction(paste, QLineEdit.TrailingPosition)
        self.btn_start = Button("解析", "primary", "search", height=48)
        self.btn_start.setMinimumWidth(104)
        self.btn_start.setToolTip("读取链接内容，选好要下载的再开始")
        self.btn_start.clicked.connect(self.on_browse)
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.btn_start)
        card.layout.addLayout(row)

        # 行内错误校验提示条（默认隐藏，出错时就近出现在输入框正下方）
        self.inline_notice = InlineNotice()
        self.inline_notice.retryRequested.connect(self.on_browse)
        card.layout.addWidget(self.inline_notice)

        opt = QHBoxLayout()
        opt.setSpacing(8)
        lbl = QLabel("保存到")
        lbl.setObjectName("sub")
        opt.addWidget(lbl)
        self.btn_pick = PathButton()
        self.btn_pick.clicked.connect(self.on_pick_dir)
        opt.addWidget(self.btn_pick)
        self.btn_open = IconButton("open", "打开下载文件夹", size=36)
        self.btn_open.clicked.connect(self.on_open_dir)
        opt.addWidget(self.btn_open)
        opt.addSpacing(4)
        self.link_badge = LinkBadge()
        opt.addWidget(self.link_badge)
        opt.addStretch(1)
        lbl2 = QLabel("画质")
        lbl2.setObjectName("sub")
        opt.addWidget(lbl2)
        self.quality_box = ComboBox()
        for label, qid in QUALITY_CHOICES:
            self.quality_box.addItem(label, qid)
        self.quality_box.setToolTip("没有这个画质时自动选最接近的；未登录最高 480P")
        self.quality_box.setMinimumWidth(128)
        self.quality_box.currentIndexChanged.connect(lambda _i: self._save_settings())
        opt.addWidget(self.quality_box)
        card.layout.addLayout(opt)
        root.addWidget(card)

        # ---- 队列卡（padding 16/12，spacing 8）----
        qcard = Card(padding=(16, 16, 16, 12))
        qcard.layout.setSpacing(8)
        qhead = QHBoxLayout()
        qhead.setContentsMargins(4, 0, 0, 0)
        qhead.setSpacing(8)
        self.seg = Segmented(["下载", "日志"])
        self.seg.changed.connect(self._switch_tab)
        qhead.addWidget(self.seg)
        self.filter_seg = Segmented(["全部", "进行中", "已完成", "失败"], compact=True)
        self.filter_seg.changed.connect(lambda _i: self._apply_queue_filter())
        self.filter_seg.hide()
        qhead.addWidget(self.filter_seg)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setFont(tabular_font(12))
        self.summary.setContentsMargins(8, 0, 4, 0)
        qhead.addWidget(self.summary)
        qhead.addStretch(1)
        self.btn_clear = Button("清理", "ghost", "trash", height=32)
        self.btn_clear.setToolTip("清除已完成或已暂停的任务")
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_start_all = Button("全部开始", "primary", "play", height=32)
        self.btn_start_all.setToolTip("继续所有已暂停或失败的下载任务")
        self.btn_start_all.clicked.connect(self.on_start_all)
        self.btn_stop = Button("全部暂停", "secondary", "pause", height=32)
        self.btn_stop.setToolTip("立即暂停所有正在进行的下载任务（保留已下载分片）")
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_copy = Button("复制", "ghost", "copy", height=32)
        self.btn_copy.clicked.connect(self.on_copy_log)
        self.btn_logclear = Button("清空", "ghost", "trash", height=32)
        self.btn_logclear.clicked.connect(self.on_clear_log)
        for b in (self.btn_clear, self.btn_start_all, self.btn_stop, self.btn_copy, self.btn_logclear):
            qhead.addWidget(b)
        qcard.layout.addLayout(qhead)

        self.stack = QStackedWidget()
        page_q = QStackedWidget()        # 0 = 空状态, 1 = 列表
        self.empty = EmptyState()
        page_q.addWidget(self.empty)
        self.model = QueueModel(self)
        self.list = QueueView()
        self.delegate = QueueDelegate(self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setModel(self.model)
        self.list.doubleClicked.connect(self._on_double_click)
        self.list.actionTriggered.connect(self._on_row_action)
        self.list.deleteRequested.connect(self._on_key_delete_job)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        page_q.addWidget(self.list)
        self.page_q = page_q
        self.stack.addWidget(page_q)

        page_l = QWidget()
        ll = QVBoxLayout(page_l)
        ll.setContentsMargins(4, 4, 4, 4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        ll.addWidget(self.log_view)
        self.stack.addWidget(page_l)
        qcard.layout.addWidget(self.stack, 1)
        root.addWidget(qcard, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)
        self.break_bar = BreakUiBar(central)
        self.break_bar.modeChanged.connect(self._apply_break_ui_mode)

        self.setMinimumSize(760, 600)
        self.resize(920, 720)

        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.PreciseTimer)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_progress)
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(500)
        self._speed_timer.timeout.connect(self._tick_speed)

        # 菜单（快捷键全部 0ms 瞬时响应）
        m = self.menuBar().addMenu("文件")
        a = m.addAction("解析剪贴板里的链接", self._paste_and_browse)
        a.setShortcut(QKeySequence("Ctrl+Shift+V"))
        a = m.addAction("打开下载文件夹", self.on_open_dir)
        a.setShortcut(QKeySequence("Ctrl+O"))
        a = m.addAction("切换深色 / 浅色外观", self.toggle_theme)
        a.setShortcut(QKeySequence("Ctrl+T"))
        a = m.addAction("设置…", self.on_settings)
        a.setShortcut(QKeySequence("Ctrl+,"))
        a.setMenuRole(QAction.PreferencesRole)
        m.addSeparator()
        m.addAction("退出", self.close).setMenuRole(QAction.QuitRole)
        m2 = self.menuBar().addMenu("帮助")
        a_break = m2.addAction("界面压力测试（Break UI）", self.toggle_break_ui_bar)
        a_break.setShortcut(QKeySequence("Ctrl+Shift+B"))
        m2.addSeparator()
        m2.addAction("关于 BiliFetch", self.on_about).setMenuRole(QAction.AboutRole)
        focus = QAction(self)
        focus.setShortcut(QKeySequence("Ctrl+L"))
        focus.triggered.connect(lambda: (self.url_edit.setFocus(), self.url_edit.selectAll()))
        self.addAction(focus)

        self._switch_tab(0)
        self._refresh_summary()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast._reposition()
        if self.break_bar.isVisible():
            self._reposition_break_bar()

    def _reposition_break_bar(self):
        par = self.centralWidget()
        if par:
            self.break_bar.adjustSize()
            self.break_bar.move((par.width() - self.break_bar.width()) // 2,
                                par.height() - self.break_bar.height() - 14)
            self.break_bar.raise_()

    # ---------------- 主题切换 ----------------
    def toggle_theme(self):
        nxt = "light" if is_dark() else "dark"
        self.apply_theme(nxt, save=True)
        self.toast.show_message("已切换为%s外观" % ("深色" if nxt == "dark" else "浅色"), kind="info")

    def apply_theme(self, mode, save=False):
        resolved = set_theme(mode)
        self._theme_mode = resolved
        self.btn_theme.setIconKind("sun" if resolved == "dark" else "moon")
        self.btn_theme.setToolTip("切换为%s外观（⌘T）" % ("浅色" if resolved == "dark" else "深色"))
        if save:
            self._save_settings()

    # ---------------- 链接识别与行内校验 ----------------
    def _on_url_text_changed(self, text):
        if self.url_edit.property("invalid") == "true":
            self.url_edit.setProperty("invalid", "false")
            self.url_edit.style().unpolish(self.url_edit)
            self.url_edit.style().polish(self.url_edit)
        self.inline_notice.clear_error()
        self.link_badge.setKind(classify_link(text))

    def _set_input_error(self, msg, can_retry=False):
        self.url_edit.setProperty("invalid", "true")
        self.url_edit.style().unpolish(self.url_edit)
        self.url_edit.style().polish(self.url_edit)
        self.inline_notice.show_error(msg, can_retry=can_retry)
        if not reduced_motion():
            # 水平微震提示（±5px, 180ms）
            pos0 = self.url_edit.pos()
            anim = QVariantAnimation(self.url_edit)
            anim.setDuration(180)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.valueChanged.connect(
                lambda v: self.url_edit.move(
                    pos0.x() + int(round(5.0 * (1.0 - float(v)) * (-1 if int(float(v) * 6) % 2 else 1))),
                    pos0.y()
                )
            )
            anim.finished.connect(lambda: self.url_edit.move(pos0))
            self._shake_anim = anim
            anim.start()

    def _switch_tab(self, i):
        self.stack.setCurrentIndex(i)
        q = i == 0
        self.btn_clear.setVisible(q)
        self.btn_start_all.setVisible(q)
        self.btn_stop.setVisible(q)
        self.summary.setVisible(q)
        self.filter_seg.setVisible(q and len(self.model.jobs) > 0)
        self.btn_copy.setVisible(not q)
        self.btn_logclear.setVisible(not q)
        if not q:
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ---------------- 剪贴板 / 拖放 ----------------
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._sniff_clipboard)

    def _sniff_clipboard(self):
        """切回窗口时，如果剪贴板里是新的 B 站链接，就帮忙填进输入框（不自动解析）。"""
        text = (QApplication.clipboard().text() or "").strip()
        if not text or len(text) > 500 or text == self._last_clip:
            return
        self._last_clip = text
        if not LINK_RE.search(text):
            return
        cur = self.url_edit.text().strip()
        if cur == text or (cur and not self.url_edit.property("autofilled")):
            return
        self.url_edit.setText(text)
        self.url_edit.setProperty("autofilled", True)
        self.url_edit.setFocus()
        self.url_edit.selectAll()
        self.toast.show_message("已识别剪贴板里的链接，回车即可解析", kind="paste")

    def _paste_clipboard(self):
        text = (QApplication.clipboard().text() or "").strip()
        if text:
            self.url_edit.setText(text)
            self.url_edit.setProperty("autofilled", False)
            self.url_edit.setFocus()

    def _paste_and_browse(self):
        self._paste_clipboard()
        self.on_browse()

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.input_card.setHighlight(True)
            self.empty.setDragActive(True)

    def dragLeaveEvent(self, e):
        self.input_card.setHighlight(False)
        self.empty.setDragActive(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.input_card.setHighlight(False)
        self.empty.setDragActive(False)
        md = e.mimeData()
        text = md.urls()[0].toString() if md.hasUrls() else md.text()
        text = (text or "").strip()
        if text:
            self.url_edit.setText(text)
            self.on_browse()

    # ---------------- 账号 ----------------
    def _set_login_state(self, nickname):
        self._nickname = nickname or ""
        self.account.setName(nickname or None)
        self.account.setToolTip(("已登录：%s（点击管理账号）" % nickname) if nickname
                                else "扫码登录，解锁 1080P 及以上画质")

    def _on_account(self):
        if not self.account.name():
            self.on_login()
            return
        menu = QMenu(self)
        a = menu.addAction("已登录：%s" % self.account.name())
        a.setEnabled(False)
        menu.addSeparator()
        menu.addAction("重新扫码登录", self.on_login)
        menu.addAction("退出登录", self.on_logout)
        menu.exec_(self.account.mapToGlobal(self.account.rect().bottomLeft()))

    def on_logout(self):
        if QMessageBox.question(self, "退出登录", "要退出当前账号吗？",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._cookie = ""
        self._set_login_state(None)
        self.append_log("已退出登录")
        self.toast.show_message("已退出登录", kind="info")
        self._save_settings()

    def on_login(self):
        dlg = LoginDialog(self, proxy=self._proxy or None)
        dlg.exec_()
        if not dlg.cookie:
            return
        self._cookie = dlg.cookie
        self._set_login_state(dlg.nickname or "已登录")
        self.append_log("登录成功：%s（高清画质已解锁）" % (dlg.nickname or ""))
        self.toast.show_message("登录成功，已解锁高清画质", kind="ok")
        self._save_settings()

    def _check_login(self):
        if not self._cookie:
            self._set_login_state(None)
            return
        self._set_login_state(self._nickname or "已登录")
        self._login_thread = LoginCheckThread(self._cookie, self._proxy or None, self)
        self._login_thread.done.connect(self._on_login_checked)
        self._login_thread.start()

    def _on_login_checked(self, state, name):
        if state == "ok":
            self._set_login_state(name)
            self._save_settings()
        elif state == "invalid":
            self._cookie = ""
            self._set_login_state(None)
            self.toast.show_message("登录已失效，请重新扫码登录", 3500, kind="warn")
            self._save_settings()

    def on_settings(self):
        dlg = SettingsDialog(self._cookie, self._proxy, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cookie = dlg.cookie.text().strip()
        self._proxy = dlg.proxy.text().strip()
        if cookie != self._cookie:
            self._cookie = cookie
            self._nickname = ""
            self._check_login()
        self._save_settings()

    # ---------------- 目录 ----------------
    def on_pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.btn_pick.path())
        if d:
            self.btn_pick.setPath(d)
            self._save_settings()

    def on_open_dir(self):
        path = self.btn_pick.path()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        if not os.path.isdir(path):
            QMessageBox.warning(self, "目录不存在", path)
            return
        open_path(path)

    def _ensure_out_dir(self):
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads", "BiliFetch")
        out_dir = os.path.abspath(os.path.expanduser(self.btn_pick.path() or default_dir))
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "保存目录不可用",
                                "没法用这个目录：\n%s\n\n(%s)\n\n已经改用 %s" % (out_dir, e, default_dir))
            out_dir = default_dir
            os.makedirs(out_dir, exist_ok=True)
        self.btn_pick.setPath(out_dir)
        return out_dir

    # ---------------- 日志 ----------------
    def append_log(self, text):
        self.log_view.appendPlainText(time.strftime("%H:%M:%S  ") + text)

    def on_copy_log(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.btn_copy.setIconKind("check")
        self.btn_copy.setText("已复制")
        QTimer.singleShot(1400, lambda: (self.btn_copy.setIconKind("copy"),
                                         self.btn_copy.setText("复制")))
        self.toast.show_message("日志已复制", kind="ok")

    def on_clear_log(self):
        self.log_view.clear()

    def on_about(self):
        QMessageBox.about(
            self, "关于 BiliFetch",
            "BiliFetch %s\n\n"
            "支持普通视频、分P、番剧、合集、收藏夹和 b23.tv 短链。\n\n"
            "仅供学习研究，请遵守 B 站用户协议。" % core.VERSION)

    # ---------------- 解析 ----------------
    def on_browse(self):
        url = self.url_edit.text().strip()
        if not url:
            self.url_edit.setFocus()
            self._set_input_error("请先粘贴一个 B 站视频 / 番剧 / 合集链接或 BV 号", can_retry=False)
            return
        if self._preview_thread is not None and self._preview_thread.isRunning():
            return
        self.inline_notice.clear_error()
        self.btn_start.setLoading(True, "解析中")
        self._preview_url = url
        t = PreviewThread(url, self._cookie, self._proxy, self)
        t.done.connect(self._on_preview)
        t.failed.connect(self._on_preview_failed)
        self._preview_thread = t
        t.start()

    def _reset_browse_button(self):
        self.btn_start.setLoading(False, "解析")
        self.btn_start.setIconKind("search")

    def _on_preview_failed(self, msg):
        self._reset_browse_button()
        self.append_log("解析失败：%s" % msg)
        self._set_input_error("解析失败：%s" % (msg.splitlines()[0] if msg else "无法识别该链接"),
                              can_retry=True)
        self.url_edit.setFocus()

    def _on_preview(self, info):
        self._reset_browse_button()
        if not info or not info.get("items"):
            self._set_input_error("这个链接里没有找到可下载的视频内容", can_retry=False)
            return
        dlg = CollectionDialog(info, self._preview_url, self)
        if dlg.exec_() == QDialog.Accepted:
            items = dlg.selected_items()
            if items:
                self._start_download(self._preview_url, items=items, audio_only=dlg.audio_only)
                self.url_edit.clear()

    # ---------------- 下载队列与筛选 ----------------
    def _apply_queue_filter(self):
        f_idx = self.filter_seg.index()
        # 0 = 全部, 1 = 进行中(含已暂停), 2 = 已完成, 3 = 失败/取消
        v = self.list
        v.setUpdatesEnabled(False)
        vis_count = 0
        try:
            for i, job in enumerate(self.model.jobs):
                st = job["state"]
                if f_idx == 1:
                    hide = st not in ("wait", "run", "merge", "pause")
                elif f_idx == 2:
                    hide = st != "done"
                elif f_idx == 3:
                    hide = st not in ("fail", "cancel")
                else:
                    hide = False
                if v.isRowHidden(i) != hide:
                    v.setRowHidden(i, hide)
                if not hide:
                    vis_count += 1
        finally:
            v.setUpdatesEnabled(True)
        labels = ["", "当前没有正在进行的下载任务", "还没有已完成的下载任务", "没有失败或取消的任务"]
        v.setEmptyFilterText(labels[f_idx] if (self.model.jobs and vis_count == 0) else "")

    def _start_download(self, url, items=None, audio_only=False):
        """把要下载的内容加入队列。items 为空时按链接直接解析下载（自检用）。"""
        out_dir = self._ensure_out_dir()
        quality = self.quality_box.currentData()
        qlabel = self.quality_box.currentText()
        used_names = {
            core.sanitize(j["title"]).lower()
            for j in self.model.jobs
            if j.get("out_dir") == out_dir and j.get("title")
        }
        jobs = []
        for it in (items or [{"url": url, "title": url}]):
            raw_title = it.get("title") or it.get("bvid") or url
            key = core.sanitize(raw_title).lower()
            if key in used_names:
                bvid = it.get("bvid")
                cand = "%s (%s)" % (raw_title, bvid) if bvid else None
                if cand and core.sanitize(cand).lower() not in used_names:
                    raw_title = cand
                else:
                    seq = 2
                    while True:
                        cand = "%s (#%d)" % (raw_title, seq)
                        if core.sanitize(cand).lower() not in used_names:
                            raw_title = cand
                            break
                        seq += 1
            used_names.add(core.sanitize(raw_title).lower())
            job = {
                "id": self._next_id,
                "title": raw_title,
                "bvid": it.get("bvid"), "cid": it.get("cid"), "url": it.get("url"),
                "out_dir": out_dir, "quality": quality, "quality_label": qlabel,
                "audio_only": audio_only,
                "state": "wait", "shown": 0.0, "target": 0.0,
                "parts": 1, "part": 0,
            }
            self._next_id += 1
            jobs.append(job)
        self.model.add(jobs)
        self._apply_queue_filter()
        self.page_q.setCurrentIndex(1)
        if self.seg.index() != 0:
            self.seg.setIndex(0)
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self._submit(jobs)
        self._refresh_summary()
        if len(jobs) > 1 or self.dl_thread is not None:
            self.toast.show_message("已加入下载队列：%d 个" % len(jobs), kind="ok")

    def _submit(self, jobs):
        t = self.dl_thread
        if t is not None and t.add(jobs):
            return
        if t is not None and t.isRunning():
            self._pending.extend(jobs)
            return
        self._spawn(jobs)

    def _spawn(self, jobs):
        t = DownloadThread(self._cookie, self._proxy, threads=16)
        t.add(jobs)
        t.log_line.connect(self.append_log)
        t.job_started.connect(self._on_job_started)
        t.job_title.connect(self._on_job_title)
        t.job_quality.connect(self._on_job_quality)
        t.job_part.connect(self._on_job_part)
        t.job_stage.connect(self._on_job_stage)
        t.job_progress.connect(self._on_job_progress)
        t.job_done.connect(self._on_job_done)
        t.job_failed.connect(self._on_job_failed)
        t.job_cancelled.connect(self._on_job_cancelled)
        t.finished.connect(lambda th=t: self._on_thread_finished(th))
        self.dl_thread = t
        t.start()
        self._speed_timer.start()

    def _on_thread_finished(self, t):
        if t in self._old_threads:
            self._old_threads.remove(t)
        if t is self.dl_thread:
            self.dl_thread = None
        t.deleteLater()
        if self.dl_thread is None and self._pending:
            jobs, self._pending = self._pending, []
            self._spawn(jobs)
        elif self.dl_thread is None:
            self._speed_timer.stop()
        self._refresh_summary()

    def _busy(self):
        return any(j["state"] in ("wait", "run", "merge") for j in self.model.jobs)

    # ---- 线程信号 ----
    def _on_job_started(self, jid):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if job:
            resuming = job.pop("resuming", False)
            shown = job.get("shown", 0.0) if resuming else 0.0
            target = job.get("target", 0.0) if resuming else 0.0
            job.update(state="run", stage="准备中", shown=shown, target=target, speed=0,
                       done_b=job.get("done_b", 0) if resuming else 0,
                       total=job.get("total", 0) if resuming else 0)
            self._samples.pop(jid, None)
            self.model.touch(jid)
            self._apply_queue_filter()
            self._refresh_summary()
            r = self.model.row_of(jid)
            if r is not None and not self.list.isRowHidden(r):
                self.list.scrollTo(self.model.index(r))

    def _on_job_title(self, jid, title):
        job = self.model.get(jid)
        if job and title:
            job["title"] = title
            self.model.touch(jid)

    def _on_job_quality(self, jid, qlabel):
        job = self.model.get(jid)
        if job and qlabel:
            job["resolved_quality"] = qlabel
            self.model.touch(jid)

    def _on_job_part(self, jid, k, n):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if job:
            job.update(part=k, parts=n, state="run")
            self._samples.pop(jid, None)
            self.model.touch(jid)

    def _on_job_stage(self, jid, stage):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if not job:
            return
        if stage in ("合并", "转封装"):
            job["state"] = "merge"
            job["speed"] = 0
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            job["stage"] = "连接中"
        self.model.touch(jid)

    def _on_job_progress(self, jid, done, total):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if not job or not total:
            return
        frac = max(0.0, min(1.0, done / total))
        n = job.get("parts", 1)
        pct = (job.get("part", 0) + frac) / n * 100.0
        job["target"] = max(job.get("target", 0.0), pct)
        job["done_b"], job["total"] = done, total
        if job["state"] != "run":
            job["state"] = "run"
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _on_job_done(self, jid, path):
        job = self.model.get(jid)
        if job:
            size = 0
            try:
                if os.path.isfile(path):
                    size = os.path.getsize(path)
            except OSError:
                pass
            job.update(state="done", path=path, size=size, shown=100.0, target=100.0,
                       speed=0, done_t=time.monotonic())
            self.model.touch(jid)
            self._apply_queue_filter()
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        self.append_log("完成：%s" % path)
        self._refresh_summary()
        self._maybe_all_done()

    def _on_job_failed(self, jid, msg):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if job:
            job.update(state="fail", error=msg.splitlines()[0][:200] if msg else "下载失败",
                       speed=0)
            self.model.touch(jid)
            self._apply_queue_filter()
        self._refresh_summary()
        self._maybe_all_done()

    def _on_job_cancelled(self, jid):
        if self.sender() is not None and self.sender() is not self.dl_thread:
            return
        job = self.model.get(jid)
        if job and job["state"] not in ("wait", "run", "done"):
            job.update(state="pause", speed=0)
            self.model.touch(jid)
            self._apply_queue_filter()
        self._refresh_summary()

    def _maybe_all_done(self):
        if self._busy():
            return
        jobs = self.model.jobs
        ok = sum(1 for j in jobs if j["state"] == "done")
        bad = sum(1 for j in jobs if j["state"] == "fail")
        if ok and not bad:
            self.toast.show_message("全部下载完成", kind="ok")
            QApplication.alert(self)
        elif bad:
            self.toast.show_message("%d 个失败，悬停或右键可重试" % bad, 3000, kind="warn")

    # ---- 动画 / 速度 ----
    def _tick_progress(self):
        moving = False
        now = time.monotonic()
        for job in self.model.jobs:
            row_dirty = False
            if job.get("enter_t") is not None:
                if now - job["enter_t"] < 0.24:
                    moving = True
                    row_dirty = True
                else:
                    job.pop("enter_t", None)
                    row_dirty = True
            if job.get("done_t") is not None:
                if now - job["done_t"] < 0.24:
                    moving = True
                    row_dirty = True
                else:
                    job.pop("done_t", None)
                    row_dirty = True
            if job["state"] == "merge":
                job["merge_angle"] = (job.get("merge_angle", 0.0) + 7.5) % 360.0
                moving = True
                row_dirty = True
            elif job["state"] == "run":
                tgt, cur = job.get("target", 0.0), job.get("shown", 0.0)
                if abs(tgt - cur) >= 0.05:
                    nxt = cur + (tgt - cur) * 0.18
                    if abs(tgt - nxt) < 0.05:
                        nxt = tgt
                    job["shown"] = nxt
                    moving = True
                    row_dirty = True
            if row_dirty:
                r = self.model.row_of(job["id"])
                if r is not None and not self.list.isRowHidden(r):
                    self.list.update(self.model.index(r))
        if not moving:
            self._anim_timer.stop()

    def _tick_speed(self):
        now = time.monotonic()
        total_speed = 0.0
        for job in self.model.jobs:
            if job["state"] != "run":
                continue
            jid = job["id"]
            done = job.get("done_b", 0)
            prev = self._samples.get(jid)
            self._samples[jid] = (now, done)
            if prev is None or done < prev[1]:
                continue
            sp = (done - prev[1]) / max(now - prev[0], 1e-3)
            old = job.get("speed") or 0
            job["speed"] = sp if not old else old * 0.6 + sp * 0.4
            total_speed += job["speed"]
            self.model.touch(jid)
        self._refresh_summary(total_speed)

    def _refresh_summary(self, speed=None):
        jobs = self.model.jobs
        self.filter_seg.setVisible(self.seg.index() == 0 and len(jobs) > 0)
        if not jobs:
            self.summary.setText("")
            self.seg.setBadge(0, "")
            self.setWindowTitle("BiliFetch")
            self.btn_start_all.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_clear.setEnabled(False)
            return
        n = len(jobs)
        done = sum(1 for j in jobs if j["state"] == "done")
        fail = sum(1 for j in jobs if j["state"] == "fail")
        paused = sum(1 for j in jobs if j["state"] in ("pause", "cancel"))
        active = sum(1 for j in jobs if j["state"] in ("wait", "run", "merge"))
        self.seg.setBadge(0, str(active if active else n))
        if active:
            if speed is None:
                speed = sum(j.get("speed") or 0 for j in jobs if j["state"] == "run")
            txt = "%d / %d" % (done, n)
            if speed:
                txt += "  ·  " + human_speed(speed)
            self.setWindowTitle("BiliFetch (%d/%d)" % (done, n))
        else:
            txt = "已完成 %d 个" % done
            if paused:
                txt += "，已暂停 %d 个" % paused
            if fail:
                txt += "，失败 %d 个" % fail
            self.setWindowTitle("BiliFetch")
        if self.summary.text() != txt:
            self.summary.setText(txt)
        self.btn_start_all.setEnabled(any(j["state"] in ("pause", "cancel", "fail") for j in jobs))
        self.btn_stop.setEnabled(bool(active))
        self.btn_clear.setEnabled(any(j["state"] in ("done", "cancel", "pause") for j in jobs))

    # ---- 队列操作（0ms 瞬时状态机与后台线程解耦）----
    def on_stop(self):
        paused_count = 0
        for job in self.model.jobs:
            if job["state"] in ("wait", "run", "merge"):
                job["state"] = "pause"
                job["speed"] = 0
                paused_count += 1
        self._pending = []
        if self.dl_thread is not None:
            t = self.dl_thread
            self.dl_thread = None
            t.cancel_all()
            if t not in self._old_threads:
                self._old_threads.append(t)
        self._speed_timer.stop()
        self._apply_queue_filter()
        self.list.viewport().update()
        self._refresh_summary()
        if paused_count:
            self.toast.show_message("已全部暂停（点击「全部开始」可立即续传）", kind="info")

    def on_start_all(self):
        resumable = [j for j in self.model.jobs if j["state"] in ("pause", "cancel", "fail")]
        if not resumable:
            return
        self._retry(resumable)
        self.toast.show_message("已开始 %d 个任务" % len(resumable), kind="ok")

    def on_clear(self):
        self.model.remove_where(lambda j: j["state"] in ("done", "cancel", "pause"))
        self._apply_queue_filter()
        if not self.model.jobs:
            self.page_q.setCurrentIndex(0)
        self._refresh_summary()

    def _on_row_action(self, kind, job):
        if kind == "reveal" and job.get("path"):
            reveal_in_file_manager(job["path"])
        elif kind == "retry":
            self._retry([job])
        elif kind == "cancel":
            self._cancel_job(job)

    def _on_key_delete_job(self, job):
        if job["state"] in ("wait", "run", "merge"):
            self._cancel_job(job)
        else:
            self._remove_job(job)

    def _on_double_click(self, ix):
        job = ix.data(QueueModel.JobRole)
        if job and job["state"] == "done" and job.get("path"):
            reveal_in_file_manager(job["path"])
        elif job and job["state"] in ("fail", "cancel", "pause"):
            self._retry([job])

    def _on_context_menu(self, pos):
        ix = self.list.indexAt(pos)
        job = ix.data(QueueModel.JobRole) if ix.isValid() else None
        menu = QMenu(self)
        if job:
            st = job["state"]
            if st == "done" and job.get("path"):
                menu.addAction(reveal_label(), lambda: reveal_in_file_manager(job["path"]))
                if os.path.isfile(job["path"]):
                    menu.addAction("打开", lambda: open_path(job["path"]))
            if st in ("pause", "cancel"):
                menu.addAction("继续下载", lambda: self._retry([job]))
            if st == "fail":
                menu.addAction("重试", lambda: self._retry([job]))
            if st in ("wait", "run", "merge"):
                menu.addAction("暂停", lambda: self._cancel_job(job))
            if st not in ("run", "merge"):
                menu.addAction("从列表移除", lambda: self._remove_job(job))
            if st == "fail" and job.get("error"):
                menu.addAction("复制错误信息",
                               lambda: QApplication.clipboard().setText(job["error"]))
            menu.addSeparator()
        resumable = [j for j in self.model.jobs if j["state"] in ("pause", "fail", "cancel")]
        if resumable:
            menu.addAction("全部开始 / 重试（%d）" % len(resumable), self.on_start_all)
        if any(j["state"] in ("wait", "run", "merge") for j in self.model.jobs):
            menu.addAction("全部暂停", self.on_stop)
        if any(j["state"] in ("done", "cancel", "pause") for j in self.model.jobs):
            menu.addAction("清除已完成", self.on_clear)
        if not menu.isEmpty():
            menu.exec_(self.list.viewport().mapToGlobal(pos))

    def _retry(self, jobs):
        for job in jobs:
            was_paused = (job["state"] == "pause" and job.get("shown", 0.0) > 0)
            if was_paused:
                job.update(state="wait", error="", speed=0, resuming=True)
            else:
                job.update(state="wait", shown=0.0, target=0.0, error="", speed=0,
                           part=0, resuming=False)
            self.model.touch(job["id"])
        self._apply_queue_filter()
        self.list.viewport().update()
        self._submit(list(jobs))
        self._refresh_summary()

    def _cancel_job(self, job):
        jid = job["id"]
        job["state"] = "pause"
        job["speed"] = 0
        self.model.touch(jid)
        self._pending = [j for j in self._pending if j["id"] != jid]
        if self.dl_thread is not None:
            if self.dl_thread._current == jid:
                t = self.dl_thread
                self.dl_thread = None
                t.cancel_job(jid)
                if t not in self._old_threads:
                    self._old_threads.append(t)
                waiting = [j for j in self.model.jobs if j["state"] == "wait"]
                if waiting:
                    self._spawn(waiting)
            else:
                self.dl_thread.cancel_job(jid)
        self._apply_queue_filter()
        self.list.viewport().update()
        self._refresh_summary()

    def _remove_job(self, job):
        if self.dl_thread is not None:
            self.dl_thread.cancel_job(job["id"])
        self.model.remove_where(lambda j: j["id"] == job["id"])
        self._apply_queue_filter()
        if not self.model.jobs:
            self.page_q.setCurrentIndex(0)
        self._refresh_summary()

    # ---------------- Break-UI 压力测试（Emil Kowalski break-ui 技能）----------------
    def toggle_break_ui_bar(self):
        if self.break_bar.isVisible():
            self._apply_break_ui_mode(0)
            self.break_bar.hide()
        else:
            if self._saved_real_jobs is None:
                self._saved_real_jobs = list(self.model.jobs)
            self.break_bar.show()
            self._reposition_break_bar()
            self.break_bar.seg.setIndex(2)    # 默认直接展示「极端数据」

    def _apply_break_ui_mode(self, mode_idx):
        # 0=还原, 1=常规示例, 2=极端数据, 3=空状态, 4=单条, 5=1000行
        if self._saved_real_jobs is None:
            self._saved_real_jobs = list(self.model.jobs)
        if mode_idx == 0:
            real = self._saved_real_jobs or []
            self._saved_real_jobs = None
            self.model.set_all(real)
            self.page_q.setCurrentIndex(1 if real else 0)
            self._apply_queue_filter()
            self._refresh_summary()
            return
        if mode_idx == 1:
            jobs = [
                {"id": 9001, "title": "第01集 末世桃源", "state": "done", "shown": 100.0, "target": 100.0, "size": 536870912, "path": "/tmp/第01集 末世桃源.mp4", "resolved_quality": "4K 超清", "parts": 1, "part": 0},
                {"id": 9002, "title": "第02集 波澜初起", "state": "done", "shown": 100.0, "target": 100.0, "size": 536870912, "path": "/tmp/第02集 波澜初起.mp4", "resolved_quality": "4K 超清", "parts": 1, "part": 0},
                {"id": 9003, "title": "第03集 长夜（4K 修复版）", "state": "run", "shown": 63.0, "target": 63.0, "speed": 8808038, "done_b": 327155712, "total": 522190848, "resolved_quality": "4K 超清", "parts": 3, "part": 1},
                {"id": 9004, "title": "第04集 雷云", "state": "merge", "shown": 100.0, "target": 100.0, "merge_angle": 45.0, "resolved_quality": "1080P 高码率", "parts": 1, "part": 0},
                {"id": 9005, "title": "第05集 天光", "state": "pause", "shown": 42.0, "target": 42.0, "done_b": 176160768, "total": 419430400, "resolved_quality": "1080P 高清", "parts": 1, "part": 0},
                {"id": 9006, "title": "第06集 余烬", "state": "fail", "shown": 0.0, "target": 0.0, "error": "HTTP 403: 没有权限（可能需要大会员）", "parts": 1, "part": 0},
            ]
        elif mode_idx == 2:
            # break-ui 极端但真实的数据集（超长多语言标题、Emoji 前缀、无空格长 URL 错误、极端大文件与分P）
            self._set_login_state("🦊 Aleksandra Wiśniewska-Kowalczyk · 超级无敌长昵称测试账号")
            jobs = [
                {"id": 9101, "title": "【4K HDR 120FPS 杜比视界】《灵笼 第二季 · 终章》全集高码率收藏版 — Supercalifragilisticexpialidocious_2026_Remastered_Edition_Final_v12", "state": "run", "shown": 98.4, "target": 98.4, "speed": 134217728, "done_b": 19864223744, "total": 20186346291, "resolved_quality": "4K 超清", "parts": 128, "part": 126, "audio_only": True},
                {"id": 9102, "title": "A", "state": "done", "shown": 100.0, "target": 100.0, "size": 999, "path": "/Volumes/ExternalDrive/Media/Archive/2026/Bilibili/极其深层的目录结构测试/子目录A/子目录B/最终输出文件_v99_final.mp4", "parts": 1, "part": 0},
                {"id": 9103, "title": "🎉🔥 表情包开头与阿拉伯语/泰语混排测试：اللغة العربية ภาษาไทย Tiếng Việt — 测试行高与基线裁剪", "state": "fail", "shown": 0.0, "target": 0.0, "error": "HTTPSConnectionPool(host='upos-sz-mirrorcoso1.bilivideo.com', port=443): Read timed out (read timeout=20.0) — 请检查代理或切换直连重试", "parts": 1, "part": 0},
                {"id": 9104, "title": "正在转封装无损杜比全景声多音轨 MKV 容器测试", "state": "merge", "shown": 100.0, "target": 100.0, "merge_angle": 120.0, "parts": 24, "part": 23},
                {"id": 9105, "title": "已暂停断点续传任务与超长画质标签仅音频混合项测试", "state": "pause", "shown": 57.6, "target": 57.6, "done_b": 301989888, "total": 524288000, "resolved_quality": "1080P 60帧", "audio_only": True, "parts": 1, "part": 0},
            ]
        elif mode_idx == 3:
            jobs = []
        elif mode_idx == 4:
            jobs = [
                {"id": 9201, "title": "单条任务边界测试（1 / 1 计数与单行滚动表现）", "state": "done", "shown": 100.0, "target": 100.0, "size": 104857600, "path": "/tmp/single.mp4", "parts": 1, "part": 0}
            ]
        else:
            # 1000 行虚拟化列表滚动压测
            states = ("done", "run", "pause", "wait", "fail")
            jobs = [
                {"id": 10000 + i, "title": "第 %04d 集 · 大规模 1000 行队列虚拟化流畅度压力测试（行号 #%d）" % (i + 1, i + 1),
                 "state": states[i % len(states)], "shown": float((i * 17) % 100), "target": float((i * 17) % 100),
                 "speed": 4194304 if states[i % len(states)] == "run" else 0,
                 "done_b": 20971520, "total": 41943040, "size": 41943040,
                 "error": "模拟网络波动超时" if states[i % len(states)] == "fail" else "",
                 "quality_label": "1080P", "parts": 1, "part": 0}
                for i in range(1000)
            ]
        self.model.set_all(jobs)
        self.page_q.setCurrentIndex(1 if jobs else 0)
        self._apply_queue_filter()
        self._refresh_summary()

    # ---------------- 设置持久化 ----------------
    def _settings_path(self):
        base = os.path.expanduser("~")
        if sys.platform == "darwin":
            base = os.path.join(base, "Library", "Application Support")
        elif sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.join(base, "AppData", "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(base, ".config")
        d = os.path.join(base, "BiliFetch")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "settings.json")

    def _legacy_settings_path(self):
        return os.path.join(os.path.expanduser("~"), "BiliFetch", "settings.json")

    def _load_settings(self):
        default = os.path.join(os.path.expanduser("~"), "Downloads", "BiliFetch")
        s = {}
        for path in (self._settings_path(), self._legacy_settings_path()):
            try:
                with open(path, encoding="utf-8") as fp:
                    s = json.load(fp)
                break
            except Exception:
                continue
        self.btn_pick.setPath(s.get("out_dir") or default)
        self._cookie = s.get("cookie", "")
        self._proxy = s.get("proxy", "")
        self._nickname = s.get("nickname", "")
        theme_pref = s.get("theme") or "light"
        self.apply_theme(theme_pref, save=False)
        q = s.get("quality")
        if q is not None:
            i = self.quality_box.findData(q)
            if i >= 0:
                self.quality_box.blockSignals(True)
                self.quality_box.setCurrentIndex(i)
                self.quality_box.blockSignals(False)
        geo = s.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass

    def _save_settings(self):
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as fp:
                json.dump({"out_dir": self.btn_pick.path(),
                           "cookie": self._cookie,
                           "proxy": self._proxy,
                           "nickname": self._nickname,
                           "theme": self._theme_mode,
                           "quality": self.quality_box.currentData(),
                           "geometry": bytes(self.saveGeometry().toBase64()).decode()},
                          fp, ensure_ascii=False)
        except Exception:
            pass

    # ---------------- 退出 ----------------
    def closeEvent(self, event):
        if self._confirm_exit and self._busy():
            r = QMessageBox.question(
                self, "正在下载",
                "还有任务没下完，确定要退出吗？\n未完成的部分下次重新下载时会接着续传。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                event.ignore()
                return
        self._save_settings()
        if not self._stop_worker():
            QMessageBox.information(self, "正在退出", "下载线程还没停下来，请稍后再关一次。")
            event.ignore()
            return
        for t in (self._login_thread, self._preview_thread):
            if t is not None and t.isRunning():
                if not t.wait(500):
                    t.setParent(None)
                    self._old_threads.append(t)
        event.accept()

    def _stop_worker(self):
        self._pending = []
        threads = list(self._old_threads)
        if self.dl_thread is not None:
            self.dl_thread.cancel_all()
            threads.append(self.dl_thread)
        for t in threads:
            if t.isRunning() and not t.wait(15000):
                return False
        return True


SELFTEST_RESULT = os.path.join(tempfile.gettempdir(), "bilifetch_selftest.txt")


def gui_excepthook(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    sys.stderr.write(text)
    try:
        QMessageBox.critical(None, "出错了",
                             "这一步没能完成：\n%s\n\n（完整信息见终端输出，程序还在运行）"
                             % value)
    except Exception:
        pass


def _make_app():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("BiliFetch")
    app.setStyle("Fusion")
    f = app.font()
    f.setFamilies(_ui_families())
    f.setPixelSize(14)
    app.setFont(f)
    app.setStyleSheet(QSS)
    return app


def selftest_exit(url, out_dir, wait_ms=4000):
    """打包后的自检：开着界面下到一半就关窗口，看会不会 SIGABRT。"""
    app = _make_app()
    win = MainWindow()
    win._settings_path = lambda: os.path.join(
        tempfile.gettempdir(), "bilifetch_selftest_settings.json")
    win._confirm_exit = False
    win.btn_pick.setPath(out_dir)
    win.show()
    QMessageBox.information = staticmethod(lambda *a, **k: None)

    QTimer.singleShot(1200, lambda: win._start_download(url))

    state = {"running": True, "downloading": False}

    def bye():
        state["downloading"] = bool(win.dl_thread and win.dl_thread.isRunning())
        t = win.dl_thread
        win.close()
        state["running"] = bool(t and t.isRunning())

    QTimer.singleShot(wait_ms, bye)
    QTimer.singleShot(wait_ms + 30000, app.quit)
    app.exec_()

    ok = state["downloading"] and not state["running"]
    if not state["downloading"]:
        text = "FAIL 下载根本没开始，这条自检不算数\n"
    elif state["running"]:
        text = "FAIL 退出时线程还在跑\n"
    else:
        text = "OK 下载中关窗口，线程干净收尾\n"
    try:
        with open(SELFTEST_RESULT, "w", encoding="utf-8") as fp:
            fp.write(text)
    except OSError:
        pass
    print(text.strip())
    return 0 if ok else 1


def selftest(url, out_dir):
    """打包后的自检：不开界面，真下一次，把结果写到文件里。"""
    try:
        client = core.BiliClient()
        info = client.resolve(url)
        jobs = core.plan_jobs(client, info)
        name, bvid, cid = jobs[0]
        out = core.download_episode(client, bvid, cid, name, out_dir,
                                     ffmpeg=core.find_executable("ffmpeg"))
        with open(SELFTEST_RESULT, "w", encoding="utf-8") as fp:
            fp.write("OK\n%s\n" % out)
        return 0
    except Exception as e:
        with open(SELFTEST_RESULT, "w", encoding="utf-8") as fp:
            fp.write("FAIL\n%s\n" % e)
        return 1


def selftest_collection(url, out_dir):
    """打包自检：读合集 -> 取第一个视频 -> 真下载一次。"""
    try:
        client = core.BiliClient()
        info = collection.fetch_collection(client, url)
        if not info or not info.get("items"):
            raise RuntimeError("合集里没有视频")
        it = info["items"][0]
        pages = client.pagelist(it["bvid"])
        out = core.download_episode(client, it["bvid"], pages[0]["cid"],
                                     it["title"], out_dir,
                                     ffmpeg=core.find_executable("ffmpeg"))
        with open(SELFTEST_RESULT, "w", encoding="utf-8") as fp:
            fp.write("OK\n%s %s\n%s\n" % (info["title"], len(info["items"]), out))
        return 0
    except Exception as e:
        with open(SELFTEST_RESULT, "w", encoding="utf-8") as fp:
            fp.write("FAIL\n%s\n" % e)
        return 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/Downloads")
        sys.exit(selftest(sys.argv[2], out_dir))
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest-login":
        try:
            png, key = login_mod.QrLogin().make_qr_png()
            out = os.path.join(tempfile.gettempdir(), "bilifetch_qr.png")
            with open(out, "wb") as fp:
                fp.write(png)
            print("OK %s %d bytes" % (key, len(png)))
            sys.exit(0)
        except Exception as e:
            print("FAIL %s" % e)
            sys.exit(1)
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest-collection":
        out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/Downloads")
        sys.exit(selftest_collection(sys.argv[2], out_dir))
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest-exit":
        out_dir = sys.argv[3] if len(sys.argv) > 3 else tempfile.gettempdir()
        sys.exit(selftest_exit(sys.argv[2], out_dir))

    app = _make_app()
    sys.excepthook = gui_excepthook
    win = MainWindow()
    win.show()
    if "--break-ui" in sys.argv:
        QTimer.singleShot(50, win.toggle_break_ui_bar)
    QTimer.singleShot(250, lambda: threading.Thread(target=core.warm_up, daemon=True).start())

    def shutdown():
        win._save_settings()
        win._stop_worker()
        for t in (win._login_thread, win._preview_thread):
            if t is not None and t.isRunning():
                if not t.wait(500):
                    t.setParent(None)
                    win._old_threads.append(t)

    app.aboutToQuit.connect(shutdown)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
