#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BiliFetch 图形界面（PyQt5）

和 bilifetch.py 共用同一套下载逻辑（bilifetch.py 里的 BiliClient / download_episode），
只是把命令行换成了窗口。

单独运行：python3 bilifetch_gui.py
打包后自检：BiliFetch --selftest <链接> <输出目录>

界面结构：
  顶栏      Logo + 账号 + 设置
  输入卡    链接输入 + 解析；保存位置 + 画质
  队列卡    下载 / 日志 两个分段；队列是 QListView + 自绘 delegate

流畅度与设计工程关键点（Emil Kowalski Design Engineering & Apple Fluid Interfaces）：
  * 下载是一个常驻的后台队列：下载过程中可以继续解析别的链接，新任务直接排到队尾，
    不用等上一批结束，也不再有"停止 -> 等线程 -> 再开始"的一串排队状态。
  * 进度信号只改数据，不直接重绘；由一个共享的 16ms 动画定时器把进度条平滑推到目标值，
    只在有行在动的时候运行，只重绘在动的那几行。
  * 速度每 0.5 秒统一算一次（指数平滑），配合等宽数字（tabular-nums）读数稳而不抖。
  * 列表悬停即显快捷操作胶囊（定位 / 重试 / 取消），上下滚动边缘带柔和渐隐遮罩。
  * 底部 Sonner 风格 Toast：带语义图标、底部滑入/滑出空间一致性、悬停暂停计时、点击即关。
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
                          QPointF, QRectF, QSize, Qt, QThread, QTimer, QVariantAnimation,
                          pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
                         QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QAction, QApplication, QDialog,
                             QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView,
                             QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                             QStackedWidget, QStyledItemDelegate, QVBoxLayout, QWidget)

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
                          ComboBox, IconButton, LogoTile, Segmented, animate_dialog_open,
                          draw_fox, draw_scroll_edge_fade, ease_out, eval_ease_out,
                          make_icon, mix, reduced_motion, tabular_font, ui_font)

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


def load_app_icon():
    """窗口图标：优先用打包好的 .icns；源码运行时现画一只矢量狐狸。"""
    for c in (os.path.join(os.path.dirname(sys.executable), "..", "Resources", "icon.icns"),
              os.path.join(HERE, "packaging", "app", "icon_1024.png")):
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


def reveal_in_file_manager(path):
    """在访达 / 文件管理器里显示文件。"""
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
        os.startfile(path if os.path.isdir(path) else os.path.dirname(path))


def open_path(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path])
    else:
        os.startfile(path)


# ---------------------------------------------------------------- 后台下载
class DownloadThread(QThread):
    """常驻的下载队列线程。

    界面随时可以 add() 新任务；队列空了线程自己结束。
    add() 和"队列空 -> 结束"在同一把锁里判断，不会出现任务加进去却没人下的情况。
    """

    log_line = pyqtSignal(str)
    job_started = pyqtSignal(int)
    job_title = pyqtSignal(int, str)
    job_part = pyqtSignal(int, int, int)            # id, 第几个分P(0起), 共几个
    job_stage = pyqtSignal(int, str)
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

    # ---- 界面线程调用 ----
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
        # 光置标志不够：卡在 socket 读上的请求要等到超时才会看标志，
        # 直接把连接掐断，"停止"才会立刻生效。
        c = self._client
        if c is not None:
            try:
                c.cancel()
            except Exception:
                pass

    def _should_stop(self):
        return self._cancel_all or self._cancel_current

    # ---- 后台线程 ----
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
            except Exception as e:          # 兜底：一个任务出错不能把整个队列带崩
                self.job_failed.emit(job["id"], str(e))
            with self._lock:
                self._current = None

    def _expand(self, job):
        """把任务展开成具体的 [(文件名, bvid, cid)]。"""
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
            self.job_failed.emit(jid, "找不到 ffmpeg，请先安装（macOS: brew install ffmpeg）")
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
    """后台查登录态（以前在主线程查，开窗那一下整个界面是僵的）。"""

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
    """后台读链接内容（要打 B 站好几个接口，放界面线程里窗口会完全僵住）。"""

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
            # break-ui 规范：任何可能被截断的标题、路径或报错都在 Tooltip 中完整呈现
            lines = [job.get("title") or ""]
            if job.get("error"):
                lines.append("原因：" + job["error"])
            elif job.get("path"):
                lines.append("位置：" + job["path"])
            return "\n".join(x for x in lines if x)
        return None

    def _reindex(self):
        self._row = {j["id"]: i for i, j in enumerate(self.jobs)}

    def add(self, jobs):
        if not jobs:
            return
        now = time.monotonic()
        # Choreograph 规范：前 5 项做 35ms 微错峰入场，总延迟控制在 175ms 内，绝不阻塞长列表
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
        if st in ("fail", "cancel"):
            return ("retry", "retry", "重试")
        if st in ("wait", "run"):
            return ("cancel", "close", "取消")
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
        if st == "done":
            return "已完成"
        if st == "fail":
            return "失败"
        return "已取消"

    def meta_text(self, job):
        bits = []
        st = job["state"]
        if job.get("parts", 1) > 1:
            bits.append("P%d/%d" % (job.get("part", 0) + 1, job["parts"]))
        if st == "run" and job.get("total"):
            bits.append("%s / %s" % (human_size(job.get("done_b", 0)), human_size(job["total"])))
            sp = job.get("speed") or 0
            remain = job["total"] - job.get("done_b", 0)
            if sp > 1024 and remain > 0:
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
        elif st == "wait":
            bits.append(job.get("quality_label", ""))
        if job.get("audio_only"):
            bits.append("仅音频")
        return "  ·  ".join(b for b in bits if b)

    def paint(self, p, option, index):
        job = index.data(QueueModel.JobRole)
        if job is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

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
        fg, soft = STATE_COLORS.get(st, STATE_COLORS["wait"])
        is_hover = (index.row() == self.hover_row)

        if is_hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F6F7F8"))
            p.drawRoundedRect(r, 10, 10)

        # 左侧状态圆：运行中是环形进度，合并中是动态旋转环，完成打勾（带入场弹性），失败叉号
        c = QRectF(r.left() + 12, r.center().y() - 16, 32, 32)
        pct = job.get("shown", 0.0)
        if st in ("run", "merge"):
            p.setPen(QPen(QColor(TRACK), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c.adjusted(2, 2, -2, -2))
            pen = QPen(QColor(ORANGE if st == "merge" else BLUE), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            if st == "merge":
                ang = job.get("merge_angle", 0.0)
                p.drawArc(c.adjusted(2, 2, -2, -2), int((90 - ang) * 16), int(-240 * 16))
            else:
                span = max(4.0, pct * 3.6)
                p.drawArc(c.adjusted(2, 2, -2, -2), 90 * 16, int(-span * 16))
            p.setPen(QColor(INK_2))
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
            p.drawEllipse(c)
            icon = {"done": "check", "fail": "close", "cancel": "stop"}.get(st)
            if icon:
                p.drawPixmap(int(c.center().x() - 8), int(c.center().y() - 8),
                             make_icon(icon, fg, 16))
            else:
                p.setPen(QColor(INK_3))
                p.setFont(self.f_num)
                p.drawText(c, Qt.AlignCenter, "%d" % (index.row() + 1))
            p.restore()

        # 右侧状态或悬停快捷操作胶囊
        spec = self.action_spec(job) if is_hover else None
        right_w = 96
        x = c.right() + 14
        tw = r.right() - x - right_w - 14
        top = r.center().y() - 19

        p.setFont(self.f_title)
        p.setPen(QColor(INK if st != "cancel" else INK_3))
        p.drawText(QRectF(x, top, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   self.fm_title.elidedText(job["title"], Qt.ElideRight, int(tw)))

        if spec is not None:
            act_r = self.action_rect(option.rect)
            p.save()
            if self.hover_action and self.press_action and not reduced_motion():
                p.translate(act_r.center())
                p.scale(0.95, 0.95)
                p.translate(-act_r.center())
            bg_c = QColor("#E4E6E9") if (self.hover_action and self.press_action) else (
                QColor("#EAECEF") if self.hover_action else QColor("#FFFFFF"))
            p.setBrush(bg_c)
            p.setPen(QPen(QColor(LINE), 1))
            p.drawRoundedRect(act_r, 8, 8)
            ic_color = RED if spec[0] == "cancel" else (ACCENT if spec[0] == "retry" else INK)
            p.drawPixmap(QPointF(act_r.left() + 10, act_r.center().y() - 6.5),
                         make_icon(spec[1], ic_color, 13))
            p.setFont(self.f_action)
            p.setPen(QColor(ic_color))
            p.drawText(QRectF(act_r.left() + 26, act_r.top(), act_r.width() - 30, act_r.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, spec[2])
            p.restore()
        else:
            status = self.status_text(job)
            # 网速含数字时采用 tabular_font，防止数字变化造成右对齐抖动
            p.setFont(self.f_status_tab if (st == "run" and job.get("speed")) else self.f_meta)
            p.setPen(QColor(fg if st != "wait" else INK_3))
            p.drawText(QRectF(r.right() - right_w - 14, top, right_w, 20),
                       Qt.AlignRight | Qt.AlignVCenter, status)

        meta = self.meta_text(job)
        meta_right_pad = (self.ACTION_W + 24) if spec is not None else 14
        meta_w = max(40.0, r.right() - x - meta_right_pad)
        if st in ("run", "merge"):
            # 细进度条 + 下面一行明细（运行期数字采用等宽字体防抖）
            bar = QRectF(x, top + 26, meta_w, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(bar, 2, 2)
            w = bar.width() * (1.0 if st == "merge" else pct / 100.0)
            if w > 1:
                p.setBrush(QColor(ORANGE if st == "merge" else BLUE))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), w, bar.height()), 2, 2)
            p.setFont(self.f_meta_tab if st == "run" else self.f_meta)
            p.setPen(QColor(INK_3))
            fm_m = QFontMetrics(p.font())
            p.drawText(QRectF(x, top + 33, meta_w, 16),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm_m.elidedText(meta, Qt.ElideRight, int(meta_w)))
        else:
            p.setFont(self.f_meta)
            p.setPen(QColor(RED if st == "fail" else INK_3))
            p.drawText(QRectF(x, top + 22, meta_w, 18),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       self.fm_meta.elidedText(meta, Qt.ElideRight, int(meta_w)))
        p.restore()


class QueueView(QListView):
    actionTriggered = pyqtSignal(str, dict)     # action_kind, job

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

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
            if on_act:
                d = self.itemDelegate()
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
        draw_scroll_edge_fade(p, self.viewport().rect(), self.verticalScrollBar(), CARD, 16)
        p.end()


class EmptyState(QWidget):
    """队列为空时的提示（整块自绘，支持拖放悬停时的缩放与高亮反馈）。"""

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
        cx, cy = self.width() / 2.0, self.height() / 2.0 - 24

        p.save()
        if self._drag > 0.001:
            sc = 1.0 + 0.08 * self._drag
            p.translate(cx, cy)
            p.scale(sc, sc)
            p.translate(-cx, -cy)
        circle = QRectF(cx - 30, cy - 30, 60, 60)
        p.setPen(QPen(QColor(ACCENT), 1.5 * self._drag) if self._drag > 0.05 else Qt.NoPen)
        p.setBrush(mix("#FFF0F4", "#FFE0E9", self._drag))
        p.drawEllipse(circle)
        p.drawPixmap(int(cx - 13), int(cy - 13), make_icon("download", ACCENT, 26))
        p.restore()

        p.setPen(QColor(ACCENT if self._drag > 0.5 else INK))
        p.setFont(ui_font(15, QFont.DemiBold))
        title = "松开鼠标，立即解析链接" if self._drag > 0.5 else "粘贴链接，开始下载"
        p.drawText(QRectF(0, cy + 44, self.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter, title)
        p.setPen(QColor(INK_3))
        p.setFont(ui_font(12))
        p.drawText(QRectF(0, cy + 72, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   "支持视频、分P、番剧、合集、收藏夹和 b23.tv 短链")
        p.drawText(QRectF(0, cy + 92, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   "也可以直接把链接拖进窗口")
        p.end()


class Toast(QWidget):
    """底部居中的 Sonner 风格轻提示（遵循 Emil Kowalski 的 Sonner 设计原则）：

    1. 空间一致性：从底部 translateY(+14px) + scale(0.96) + opacity(0) 入场，
       退场沿原路径回到 translateY(+10px)，入场 240ms、退场 180ms（非对称时序）。
    2. 可打断性（Interruptible）：动画途中再次触发时，从当前实时位置与宽度平滑重定向。
    3. 边缘体验：鼠标悬停在 Toast 上时自动暂停倒计时，移开后恢复；点击即可立即关闭。
    4. 语义图标：根据消息内容自动匹配成功（绿勾）、警告（橙叹号）或提示（粉标）图标。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._text = ""
        self._kind = "info"
        self._progress = 0.0      # 0.0 = 隐藏, 1.0 = 完全展现
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
        # Sonner 原则：鼠标悬停时暂停自动消失计时
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

        # 柔和底部投影
        p.setPen(Qt.NoPen)
        for dy, alpha in ((3.0, 22), (1.5, 38)):
            p.setBrush(QColor(15, 20, 30, alpha))
            p.drawRoundedRect(r.adjusted(-1, dy, 1, dy + 1), 12, 12)

        # 深色磨砂质感底 + 顶部微亮高光边
        p.setBrush(QColor(24, 25, 28, 240))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawRoundedRect(r, 11, 11)

        ic_map = {
            "ok": ("check", GREEN),
            "warn": ("warning", ORANGE),
            "paste": ("paste", ACCENT),
            "info": ("info", ACCENT),
        }
        ic_name, ic_col = ic_map.get(self._kind, ("info", ACCENT))
        p.drawPixmap(QPointF(r.left() + 14, r.center().y() - 8), make_icon(ic_name, ic_col, 16))

        p.setFont(self._font)
        p.setPen(QColor("#F6F7F8"))
        fm = QFontMetrics(self._font)
        tx = r.left() + 38
        tw = r.right() - tx - 14
        p.drawText(QRectF(tx, r.top(), tw, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self._text, Qt.ElideRight, int(tw)))
        p.end()


class PathButton(Button):
    """显示保存目录的按钮：路径太长时中间省略（break-ui：文件名与路径保留首尾特征）。"""

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
        self.dl_thread = None          # 当前的下载队列线程
        self._old_threads = []         # 已经不接活、但还没退出的线程（不能提前析构）
        self._pending = []             # 旧线程收尾期间加进来的任务
        self._next_id = 1
        self._samples = {}             # 任务 id -> (时刻, 字节)，算速度用
        self._preview_thread = None
        self._login_thread = None
        self._last_clip = ""
        self._confirm_exit = True
        self._cookie = ""
        self._proxy = ""
        self._nickname = ""
        self._build_ui()
        self._load_settings()
        QTimer.singleShot(80, self._check_login)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(10)

        # ---- 顶栏 ----
        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 6, 0)
        head.setSpacing(10)
        head.addWidget(LogoTile(34))
        t = QLabel("BiliFetch")
        t.setObjectName("h1")
        head.addWidget(t)
        head.addStretch(1)
        self.account = AccountChip()
        self.account.clicked.connect(self._on_account)
        head.addWidget(self.account)
        self.btn_settings = IconButton("gear", "设置（代理 / Cookie）", size=34)
        self.btn_settings.clicked.connect(self.on_settings)
        head.addWidget(self.btn_settings)
        root.addLayout(head)

        # ---- 输入卡 ----
        self.input_card = Card(padding=(18, 18, 18, 16))
        card = self.input_card
        card.layout.setSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("bigInput")
        self.url_edit.setPlaceholderText("粘贴 B 站链接或 BV 号，回车解析")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.on_browse)
        paste = QAction(QIcon(make_icon("paste", INK_3, 16)), "粘贴", self.url_edit)
        paste.setToolTip("从剪贴板粘贴")
        paste.triggered.connect(self._paste_clipboard)
        self.url_edit.addAction(paste, QLineEdit.TrailingPosition)
        self.btn_start = Button("解析", "primary", "search", height=46)
        self.btn_start.setMinimumWidth(108)
        self.btn_start.setToolTip("读取链接内容，选好要下载的再开始")
        self.btn_start.clicked.connect(self.on_browse)
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.btn_start)
        card.layout.addLayout(row)

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
        opt.addStretch(1)
        lbl2 = QLabel("画质")
        lbl2.setObjectName("sub")
        opt.addWidget(lbl2)
        self.quality_box = ComboBox()
        for label, qid in QUALITY_CHOICES:
            self.quality_box.addItem(label, qid)
        self.quality_box.setToolTip("没有这个画质时自动选最接近的；未登录最高 480P")
        self.quality_box.setMinimumWidth(130)
        self.quality_box.currentIndexChanged.connect(lambda _i: self._save_settings())
        opt.addWidget(self.quality_box)
        card.layout.addLayout(opt)
        root.addWidget(card)

        # ---- 队列卡 ----
        qcard = Card(padding=(14, 14, 14, 10))
        qcard.layout.setSpacing(8)
        qhead = QHBoxLayout()
        qhead.setContentsMargins(4, 0, 0, 0)
        qhead.setSpacing(6)
        self.seg = Segmented(["下载", "日志"])
        self.seg.changed.connect(self._switch_tab)
        qhead.addWidget(self.seg)
        qhead.addSpacing(8)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setFont(tabular_font(12))
        qhead.addWidget(self.summary)
        qhead.addStretch(1)
        self.btn_clear = Button("清除已完成", "ghost", "trash", height=32)
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_stop = Button("全部停止", "secondary", "stop", height=32)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_copy = Button("复制", "ghost", "copy", height=32)
        self.btn_copy.clicked.connect(self.on_copy_log)
        self.btn_logclear = Button("清空", "ghost", "trash", height=32)
        self.btn_logclear.clicked.connect(self.on_clear_log)
        for b in (self.btn_clear, self.btn_stop, self.btn_copy, self.btn_logclear):
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

        self.setMinimumSize(760, 600)
        self.resize(920, 720)

        # 共享的进度动画定时器：只在有行在动时运行
        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.PreciseTimer)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_progress)
        # 速度统计：0.5 秒一次
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(500)
        self._speed_timer.timeout.connect(self._tick_speed)

        # 菜单（快捷键全部直接响应，遵循 Emil Kowalski "Never animate keyboard-initiated actions"）
        m = self.menuBar().addMenu("文件")
        a = m.addAction("解析剪贴板里的链接", self._paste_and_browse)
        a.setShortcut(QKeySequence("Ctrl+Shift+V"))
        a = m.addAction("打开下载文件夹", self.on_open_dir)
        a.setShortcut(QKeySequence("Ctrl+O"))
        a = m.addAction("设置…", self.on_settings)
        a.setShortcut(QKeySequence("Ctrl+,"))
        a.setMenuRole(QAction.PreferencesRole)
        m.addSeparator()
        m.addAction("退出", self.close).setMenuRole(QAction.QuitRole)
        m2 = self.menuBar().addMenu("帮助")
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

    def _switch_tab(self, i):
        self.stack.setCurrentIndex(i)
        q = i == 0
        self.btn_clear.setVisible(q)
        self.btn_stop.setVisible(q)
        self.summary.setVisible(q)
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
        self._save_settings()      # 立刻存盘，别等退出时才写

    def _check_login(self):
        """启动时在后台确认存的 Cookie 还能不能用（先按上次的昵称显示，不让用户干等）。"""
        if not self._cookie:
            self._set_login_state(None)
            return
        self._set_login_state(self._nickname or "已登录")
        self._login_thread = LoginCheckThread(self._cookie, self._proxy or None, self)
        self._login_thread.done.connect(self._on_login_checked)
        self._login_thread.start()

    def _on_login_checked(self, state, name):
        # 网络错误（error）不能当成登录失效 —— 否则用户每次开软件都要重新扫码
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
        # 必须是绝对路径：从 Dock 启动时 CWD 是 /，相对路径会存到奇怪的地方
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
        # Emil Kowalski 状态指示：复制按钮瞬时切换为对勾与「已复制」
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
            self.toast.show_message("先粘贴一个 B 站链接", kind="info")
            return
        if self._preview_thread is not None and self._preview_thread.isRunning():
            return
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
        QMessageBox.warning(self, "解析失败", msg)

    def _on_preview(self, info):
        self._reset_browse_button()
        if not info or not info.get("items"):
            QMessageBox.information(self, "提示", "这个链接里没有可下载的内容")
            return
        dlg = CollectionDialog(info, self._preview_url, self)
        if dlg.exec_() == QDialog.Accepted:
            items = dlg.selected_items()
            if items:
                self._start_download(self._preview_url, items=items, audio_only=dlg.audio_only)
                self.url_edit.clear()

    # ---------------- 下载队列 ----------------
    def _start_download(self, url, items=None, audio_only=False):
        """把要下载的内容加入队列。items 为空时按链接直接解析下载（自检用）。"""
        out_dir = self._ensure_out_dir()
        quality = self.quality_box.currentData()
        qlabel = self.quality_box.currentText()
        jobs = []
        for it in (items or [{"url": url, "title": url}]):
            job = {
                "id": self._next_id,
                "title": it.get("title") or it.get("bvid") or url,
                "bvid": it.get("bvid"), "cid": it.get("cid"), "url": it.get("url"),
                "out_dir": out_dir, "quality": quality, "quality_label": qlabel,
                "audio_only": audio_only,
                "state": "wait", "shown": 0.0, "target": 0.0,
                "parts": 1, "part": 0,
            }
            self._next_id += 1
            jobs.append(job)
        self.model.add(jobs)
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
            # 旧线程已经不接活了（正在收尾）：先记下，等它退出马上接着下
            self._pending.extend(jobs)
            return
        self._spawn(jobs)

    def _spawn(self, jobs):
        t = DownloadThread(self._cookie, self._proxy, threads=16)
        t.add(jobs)
        t.log_line.connect(self.append_log)
        t.job_started.connect(self._on_job_started)
        t.job_title.connect(self._on_job_title)
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
        if self._pending:
            jobs, self._pending = self._pending, []
            self._spawn(jobs)
        elif self.dl_thread is None:
            self._speed_timer.stop()
        self._refresh_summary()

    def _busy(self):
        return any(j["state"] in ("wait", "run", "merge") for j in self.model.jobs)

    # ---- 线程信号 ----
    def _on_job_started(self, jid):
        job = self.model.get(jid)
        if job:
            job.update(state="run", stage="准备中", shown=0.0, target=0.0, speed=0,
                       done_b=0, total=0)
            self._samples.pop(jid, None)
            self.model.touch(jid)
            self._refresh_summary()
            r = self.model.row_of(jid)
            if r is not None:
                self.list.scrollTo(self.model.index(r))

    def _on_job_title(self, jid, title):
        job = self.model.get(jid)
        if job and title:
            job["title"] = title
            self.model.touch(jid)

    def _on_job_part(self, jid, k, n):
        job = self.model.get(jid)
        if job:
            job.update(part=k, parts=n, state="run")
            self._samples.pop(jid, None)
            self.model.touch(jid)

    def _on_job_stage(self, jid, stage):
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
        job = self.model.get(jid)
        if not job or not total:
            return
        frac = max(0.0, min(1.0, done / total))
        n = job.get("parts", 1)
        pct = (job.get("part", 0) + frac) / n * 100.0
        # 视频流、音频流的总大小先后才知道，合起来的百分比可能往回跳一点：只进不退
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
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        self.append_log("完成：%s" % path)
        self._refresh_summary()
        self._maybe_all_done()

    def _on_job_failed(self, jid, msg):
        job = self.model.get(jid)
        if job:
            job.update(state="fail", error=msg.splitlines()[0][:200] if msg else "下载失败",
                       speed=0)
            self.model.touch(jid)
        self._refresh_summary()
        self._maybe_all_done()

    def _on_job_cancelled(self, jid):
        job = self.model.get(jid)
        if job:
            job.update(state="cancel", speed=0)
            self.model.touch(jid)
        self._refresh_summary()

    def _maybe_all_done(self):
        if self._busy():
            return
        jobs = self.model.jobs
        ok = sum(1 for j in jobs if j["state"] == "done")
        bad = sum(1 for j in jobs if j["state"] == "fail")
        if ok and not bad:
            self.toast.show_message("全部下载完成", kind="ok")
            QApplication.alert(self)      # 窗口在后台时让 Dock 图标跳一下
        elif bad:
            self.toast.show_message("%d 个失败，悬停或右键可重试" % bad, 3000, kind="warn")

    # ---- 动画 / 速度 ----
    def _tick_progress(self):
        moving = False
        now = time.monotonic()
        for job in self.model.jobs:
            row_dirty = False
            # 1. 新行入场错峰微动画
            if job.get("enter_t") is not None:
                if now - job["enter_t"] < 0.24:
                    moving = True
                    row_dirty = True
                else:
                    job.pop("enter_t", None)
                    row_dirty = True
            # 2. 完成态绿勾微弹入场
            if job.get("done_t") is not None:
                if now - job["done_t"] < 0.24:
                    moving = True
                    row_dirty = True
                else:
                    job.pop("done_t", None)
                    row_dirty = True
            # 3. 合并态动态旋转弧
            if job["state"] == "merge":
                job["merge_angle"] = (job.get("merge_angle", 0.0) + 7.5) % 360.0
                moving = True
                row_dirty = True
            # 4. 下载进度平滑插值
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
                if r is not None:
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
        if not jobs:
            self.summary.setText("")
            self.seg.setBadge(0, "")
            self.btn_stop.setEnabled(False)
            self.btn_clear.setEnabled(False)
            return
        n = len(jobs)
        done = sum(1 for j in jobs if j["state"] == "done")
        fail = sum(1 for j in jobs if j["state"] == "fail")
        active = sum(1 for j in jobs if j["state"] in ("wait", "run", "merge"))
        self.seg.setBadge(0, str(active if active else n))
        if active:
            if speed is None:
                speed = sum(j.get("speed") or 0 for j in jobs if j["state"] == "run")
            txt = "%d / %d" % (done, n)
            if speed:
                txt += "  ·  " + human_speed(speed)
        else:
            txt = "已完成 %d 个" % done
            if fail:
                txt += "，失败 %d 个" % fail
        if self.summary.text() != txt:
            self.summary.setText(txt)
        self.btn_stop.setEnabled(bool(active))
        self.btn_clear.setEnabled(any(j["state"] in ("done", "cancel") for j in jobs))

    # ---- 队列操作 ----
    def on_stop(self):
        for job in self.model.jobs:
            if job["state"] == "wait":
                job["state"] = "cancel"
        self._pending = [j for j in self._pending if j["state"] != "cancel"]
        if self.dl_thread is not None:
            self.dl_thread.cancel_all()
            if self.dl_thread not in self._old_threads:
                self._old_threads.append(self.dl_thread)
        self.list.viewport().update()
        self._refresh_summary()

    def on_clear(self):
        self.model.remove_where(lambda j: j["state"] in ("done", "cancel"))
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

    def _on_double_click(self, ix):
        job = ix.data(QueueModel.JobRole)
        if job and job["state"] == "done" and job.get("path"):
            reveal_in_file_manager(job["path"])
        elif job and job["state"] in ("fail", "cancel"):
            self._retry([job])

    def _on_context_menu(self, pos):
        ix = self.list.indexAt(pos)
        job = ix.data(QueueModel.JobRole) if ix.isValid() else None
        menu = QMenu(self)
        if job:
            st = job["state"]
            if st == "done" and job.get("path"):
                menu.addAction("在访达中显示", lambda: reveal_in_file_manager(job["path"]))
                if os.path.isfile(job["path"]):
                    menu.addAction("打开", lambda: open_path(job["path"]))
            if st in ("fail", "cancel"):
                menu.addAction("重试", lambda: self._retry([job]))
            if st in ("wait", "run", "merge"):
                menu.addAction("取消", lambda: self._cancel_job(job))
            if st not in ("run", "merge"):
                menu.addAction("从列表移除", lambda: self._remove_job(job))
            if st == "fail" and job.get("error"):
                menu.addAction("复制错误信息",
                               lambda: QApplication.clipboard().setText(job["error"]))
            menu.addSeparator()
        fails = [j for j in self.model.jobs if j["state"] in ("fail", "cancel")]
        if fails:
            menu.addAction("重试全部失败 / 取消的（%d）" % len(fails), lambda: self._retry(fails))
        if any(j["state"] in ("done", "cancel") for j in self.model.jobs):
            menu.addAction("清除已完成", self.on_clear)
        if not menu.isEmpty():
            menu.exec_(self.list.viewport().mapToGlobal(pos))

    def _retry(self, jobs):
        for job in jobs:
            job.update(state="wait", shown=0.0, target=0.0, error="", speed=0, part=0)
            self.model.touch(job["id"])
        self._submit(list(jobs))
        self._refresh_summary()

    def _cancel_job(self, job):
        if job["state"] == "wait":
            job["state"] = "cancel"
            self.model.touch(job["id"])
            self._pending = [j for j in self._pending if j["id"] != job["id"]]
        if self.dl_thread is not None:
            self.dl_thread.cancel_job(job["id"])
        self._refresh_summary()

    def _remove_job(self, job):
        if self.dl_thread is not None:
            self.dl_thread.cancel_job(job["id"])
        self.model.remove_where(lambda j: j["id"] == job["id"])
        if not self.model.jobs:
            self.page_q.setCurrentIndex(0)
        self._refresh_summary()

    # ---------------- 设置持久化 ----------------
    def _settings_path(self):
        base = os.path.expanduser("~")
        if sys.platform == "darwin":
            base = os.path.join(base, "Library", "Application Support")
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
                t.wait(3000)
        event.accept()

    def _stop_worker(self):
        """取消下载并等后台线程收尾。返回 True 表示已经干净停下。

        QThread 在运行中被销毁会让 Qt 直接 abort（SIGABRT，崩溃弹窗），
        所以这里必须等到线程真的结束。
        """
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
    """槽里抛了异常时的兜底：弹窗报错，别让程序直接消失。

    PyQt5 的默认行为是 qFatal() -> abort()：一个没接住的异常就会把整个 App 打死。
    """
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
    if sys.platform == "darwin":
        f.setFamily(".AppleSystemUIFont")
    f.setPixelSize(13)
    app.setFont(f)
    app.setStyleSheet(QSS)
    return app


def selftest_exit(url, out_dir, wait_ms=4000):
    """打包后的自检：开着界面下到一半就关窗口，看会不会 SIGABRT。"""
    app = _make_app()
    win = MainWindow()
    # 自检不能碰用户自己的设置
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
        win.close()                       # 走 closeEvent -> _stop_worker
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
    # 打包自检：--selftest <链接> <输出目录> / --selftest-collection <合集链接> <输出目录>
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/Downloads")
        sys.exit(selftest(sys.argv[2], out_dir))
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest-login":
        # 生成二维码存成 png：验证打包后 qrcode / PIL 都在（登录功能能不能用的关键）
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
    # 开窗之后再后台预热 requests（首次导入 170ms），用户还在看界面时它就加载好了
    QTimer.singleShot(250, lambda: threading.Thread(target=core.warm_up, daemon=True).start())

    def shutdown():
        # ⌘Q 退出不会触发窗口的 closeEvent，这里补上取消 + 等线程收尾
        win._save_settings()
        win._stop_worker()
        for t in (win._login_thread, win._preview_thread):
            if t is not None and t.isRunning():
                t.wait(3000)

    app.aboutToQuit.connect(shutdown)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
