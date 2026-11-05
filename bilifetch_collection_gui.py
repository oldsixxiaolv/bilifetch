#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合集预览与选择对话框。

用户粘的是合集/列表链接时，先弹这个窗口让他预览清单、勾选要下的视频。

设计工程与流畅度优化（遵循 Emil Kowalski Design Engineering & Apple Fluid Interfaces）：
  1. 列表用 QListView + 自绘 delegate：一百多集只绘制视口内可见的几行。
  2. 缩略图异步到达时做 180ms --ease-out 柔和渐显（不再一帧生硬跳出）。
  3. 勾选框与整行支持 pointer-down scale(0.992) 按压反馈，对勾采用左->右 clip-path 扫入动效。
  4. 视口上下边缘带滚动渐隐遮罩（draw_scroll_edge_fade），消除末行被卡片边框生硬截断的问题。
  5. 极端数据防御（break-ui）：超长标题双行省略+Tooltip、超长 UP 主名自动省略、搜索无结果空状态提示、等宽数字时长与计数。
"""

import threading
import time

from PyQt5.QtCore import (QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath,
                         QPen, QPixmap, QTextLayout)
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListView, QSizePolicy, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

import bilifetch_collection as col
from bilifetch_ui import (ACCENT, ACCENT_SOFT, CARD, FIELD, INK, INK_2, INK_3, Button, Card,
                          animate_dialog_open, draw_scroll_edge_fade, eval_ease_out,
                          make_icon, mix, reduced_motion, tabular_font, ui_font)

THUMB_W, THUMB_H = 112, 63
ROW_H = 80
COVER_W, COVER_H = 136, 77

# 还没停干净的抓图线程先挂在这里：对话框销毁时不能把它们一起带走
# （运行中的 QThread 被析构 → Qt abort），等它们自己结束再删。
_live_threads = []


def _release_thread(t):
    """线程自己跑完了：撤掉引用并删除。"""
    t.wait()
    if t in _live_threads:
        _live_threads.remove(t)
    try:
        t.deleteLater()
    except RuntimeError:
        pass


# 读取合集用的客户端，由主窗口在打开对话框前设置（这样能用上 Cookie / 代理）
collection_client = None


class ElidedTitleLabel(QWidget):
    """最多显示两行的标题控件（单行时紧凑贴合，双行时自动增高，超出第 2 行末尾优雅省略并附带完整 Tooltip）。"""

    def __init__(self, text="", max_lines=2, font=None, color=INK, parent=None):
        super().__init__(parent)
        self._text = str(text or "")
        self._max_lines = max_lines
        self._font = font or ui_font(20, QFont.Bold)
        self._color = QColor(color)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fm = QFontMetrics(self._font)
        self._line_h = fm.lineSpacing() + 2
        self._lines = []
        self.setToolTip(self._text if len(self._text) > 24 else "")
        self._relayout(560)

    def _relayout(self, w):
        w = max(80, w)
        layout = QTextLayout(self._text, self._font)
        layout.beginLayout()
        lines = []
        while len(lines) < self._max_lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(w)
            lines.append((line.textStart(), line.textLength()))
        layout.endLayout()
        self._lines = lines or [(0, len(self._text))]
        target_h = self._line_h * len(self._lines) + 2
        if self.height() != target_h:
            self.setFixedHeight(target_h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout(self.width())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font)
        p.setPen(self._color)
        fm = QFontMetrics(self._font)
        w = max(40, self.width())
        if not self._lines:
            self._relayout(w)

        y = 0
        for idx, (start, length) in enumerate(self._lines):
            seg = self._text[start:start + length]
            if idx == self._max_lines - 1 and start + length < len(self._text):
                seg = fm.elidedText(self._text[start:], Qt.ElideRight, w)
            p.drawText(QRectF(0, y, w, self._line_h), Qt.AlignLeft | Qt.AlignVCenter, seg)
            y += self._line_h
        p.end()


class CoverThread(QThread):
    """后台批量抓缩略图。

    用线程池并发抓（一张图 ~200ms，串行抓 91 张要等十几秒）；
    每个工作线程复用自己的 Session（以前每张图新建一个 Session，连接都没法复用）。
    缩放也在后台做好，按 2x 出图，Retina 上不糊；QPixmap 必须在界面线程建，所以传 QImage。
    """

    WORKERS = 8

    ready = pyqtSignal(int, QImage)

    def __init__(self, urls, parent=None, size=(THUMB_W, THUMB_H), dpr=2.0):
        super().__init__(parent)
        self.urls = urls          # [(index, url)]
        self.size = size
        self.dpr = dpr
        self._stop = False
        self._local = threading.local()

    def stop(self):
        self._stop = True

    def _session(self):
        s = getattr(self._local, "s", None)
        if s is None:
            import requests
            s = requests.Session()
            s.trust_env = False
            s.headers.update({"User-Agent": "Mozilla/5.0",
                              "Referer": "https://www.bilibili.com/"})
            self._local.s = s
        return s

    def _fetch(self, url):
        if self._stop:
            return None
        w0, h0 = int(self.size[0] * self.dpr), int(self.size[1] * self.dpr)
        # B 站图床支持按尺寸出缩略图，省掉下载 1080P 原图（几百 KB → 十几 KB）
        if "hdslb.com" in url and "@" not in url:
            url = url.replace("http://", "https://") + "@%dw_%dh_1c.jpg" % (w0, h0)
        r = self._session().get(url, timeout=10)
        img = QImage()
        if not img.loadFromData(r.content):
            return None
        scaled = img.scaled(w0, h0, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        w, h = scaled.width(), scaled.height()
        return scaled.copy((w - w0) // 2, (h - h0) // 2, w0, h0)

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if not self.urls:
            return
        pool = ThreadPoolExecutor(max_workers=self.WORKERS)
        try:
            futures = {pool.submit(self._fetch, url): idx for idx, url in self.urls}
            for fut in as_completed(futures):
                if self._stop:
                    break
                try:
                    img = fut.result()
                except Exception:
                    img = None
                if img is not None:
                    self.ready.emit(futures[fut], img)
        finally:
            # 不用 with：with 退出时会等所有在途请求跑完，对话框关了还得等半天
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:          # 老版本 Python 没有 cancel_futures
                pool.shutdown(wait=False)


# ---------------------------------------------------------------- 模型
class ItemModel(QAbstractListModel):
    CheckRole = Qt.UserRole + 1
    ThumbRole = Qt.UserRole + 2
    ItemRole = Qt.UserRole + 3
    CheckTimeRole = Qt.UserRole + 4
    ThumbTimeRole = Qt.UserRole + 5

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.checked = [bool(it.get("checked", True)) for it in self.items]
        self.thumbs = [None] * len(self.items)
        self.check_t = [0.0] * len(self.items)
        self.thumb_t = [0.0] * len(self.items)
        self.meta = [self._meta_text(it) for it in self.items]

    @staticmethod
    def _meta_text(item):
        bits = []
        if item.get("no"):
            bits.append("第%s集" % item["no"])
        if item.get("duration"):
            bits.append(col.format_duration(item.get("duration")))
        if item.get("view"):
            bits.append("%s 播放" % col.format_views(item.get("view")))
        group = item.get("group") or ""
        if group and group != "正片":
            bits.append(group)
        return "  ·  ".join(bits)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        i = index.row()
        if role == Qt.DisplayRole:
            it = self.items[i]
            return it.get("title") or it.get("bvid") or ""
        if role == self.CheckRole:
            return self.checked[i]
        if role == self.ThumbRole:
            return self.thumbs[i]
        if role == self.ItemRole:
            return self.items[i]
        if role == self.CheckTimeRole:
            return self.check_t[i]
        if role == self.ThumbTimeRole:
            return self.thumb_t[i]
        if role == Qt.ToolTipRole:
            t = self.items[i].get("title") or ""
            m = self.meta[i]
            return (t + ("\n" + m if m else "")) if t else None
        return None

    def set_checked(self, rows, value):
        rows = list(rows)
        if not rows:
            return
        now = time.monotonic()
        changed_rows = []
        for r in rows:
            if self.checked[r] != value:
                self.checked[r] = value
                self.check_t[r] = now
                changed_rows.append(r)
        if changed_rows:
            self.dataChanged.emit(self.index(min(changed_rows)),
                                  self.index(max(changed_rows)), [self.CheckRole])

    def toggle(self, r):
        self.checked[r] = not self.checked[r]
        self.check_t[r] = time.monotonic()
        ix = self.index(r)
        self.dataChanged.emit(ix, ix, [self.CheckRole])

    def set_thumb(self, r, pm):
        if 0 <= r < len(self.thumbs):
            self.thumbs[r] = pm
            self.thumb_t[r] = time.monotonic()
            ix = self.index(r)
            self.dataChanged.emit(ix, ix, [self.ThumbRole])


class ItemDelegate(QStyledItemDelegate):
    """一行：勾选框（带 clip-path 扫入动效）+ 缩略图（带渐显）+ 标题 + 时长/播放量。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_title = ui_font(13, QFont.Medium)
        self.f_meta = ui_font(12)
        self.f_badge = tabular_font(10, QFont.DemiBold)
        self.hover_row = -1
        self.press_row = -1

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect)
        checked = index.data(ItemModel.CheckRole)
        item = index.data(ItemModel.ItemRole) or {}
        row = index.row()
        now = time.monotonic()

        card = r.adjusted(6, 3, -6, -3)

        # 按压微缩放反馈（pointer-down scale(0.992)）
        if row == self.press_row and not reduced_motion():
            p.translate(card.center())
            p.scale(0.992, 0.992)
            p.translate(-card.center())

        check_t = index.data(ItemModel.CheckTimeRole) or 0.0
        dt_chk = now - check_t
        chk_prog = eval_ease_out(dt_chk / 0.16) if (0.0 <= dt_chk < 0.16 and not reduced_motion()) else 1.0

        # 背景：悬停浅灰，选中浅粉（带柔和色彩过渡）
        if checked or chk_prog < 1.0:
            t_bg = chk_prog if checked else (1.0 - chk_prog)
            base_bg = "#F6F7F8" if row == self.hover_row else "#FFFFFF"
            p.setPen(Qt.NoPen)
            p.setBrush(mix(base_bg, ACCENT_SOFT, t_bg))
            p.drawRoundedRect(card, 10, 10)
        elif row == self.hover_row:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F6F7F8"))
            p.drawRoundedRect(card, 10, 10)

        # 勾选框（按压内缩 + 对勾从左至右 clip-path 绘制）
        cb = QRectF(card.left() + 12, card.center().y() - 9, 18, 18)
        p.save()
        if row == self.press_row and not reduced_motion():
            p.translate(cb.center())
            p.scale(0.90, 0.90)
            p.translate(-cb.center())
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(mix("#FFFFFF", ACCENT, chk_prog))
            p.drawRoundedRect(cb, 5, 5)
            # Choreograph 规范：方框落定同时对勾由左向右扫出
            ic_rect = cb.adjusted(1, 1, -1, -1)
            if chk_prog < 1.0:
                p.setClipRect(QRectF(ic_rect.left(), ic_rect.top(),
                                     ic_rect.width() * chk_prog, ic_rect.height()))
            p.drawPixmap(ic_rect.toRect(), make_icon("check", "#FFFFFF", 16))
        else:
            border_c = ACCENT if row == self.hover_row else "#C9CCD0"
            p.setPen(QPen(QColor(border_c), 1.5))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(cb.adjusted(0.75, 0.75, -0.75, -0.75), 5, 5)
        p.restore()

        # 缩略图（异步加载完成时 180ms 渐显）
        th = QRectF(cb.right() + 14, card.center().y() - THUMB_H / 2.0, THUMB_W, THUMB_H)
        path = QPainterPath()
        path.addRoundedRect(th, 7, 7)
        pm = index.data(ItemModel.ThumbRole)
        thumb_t = index.data(ItemModel.ThumbTimeRole) or 0.0
        dt_th = now - thumb_t
        th_prog = eval_ease_out(dt_th / 0.18) if (pm is not None and 0.0 <= dt_th < 0.18 and not reduced_motion()) else 1.0

        if pm is None or th_prog < 1.0:
            p.fillPath(path, QColor(FIELD))
            p.drawPixmap(int(th.center().x() - 9), int(th.center().y() - 9),
                         make_icon("play", "#C9CCD0", 18))
        if pm is not None:
            p.save()
            p.setClipPath(path)
            if th_prog < 1.0:
                p.setOpacity(th_prog)
            p.drawPixmap(th.toRect(), pm)
            p.restore()

        if item.get("duration"):
            txt = col.format_duration(item["duration"])
            p.setFont(self.f_badge)
            fm = QFontMetrics(self.f_badge)
            bw = fm.horizontalAdvance(txt) + 10
            br = QRectF(th.right() - bw - 4, th.bottom() - 18, bw, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(15, 20, 30, 165))
            p.drawRoundedRect(br, 4, 4)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(br, Qt.AlignCenter, txt)

        # 文字
        tx = th.right() + 14
        tw = card.right() - tx - 14
        title = index.data(Qt.DisplayRole) or ""
        p.setFont(self.f_title)
        fm = QFontMetrics(self.f_title)
        p.setPen(QColor(INK))
        meta = index.model().meta[row] if hasattr(index.model(), "meta") else ""
        if item.get("current"):
            meta = ("当前  ·  " + meta) if meta else "当前"
        lines_h = fm.height() + 6 + QFontMetrics(self.f_meta).height()
        ty = card.center().y() - lines_h / 2.0
        p.drawText(QRectF(tx, ty, tw, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(title, Qt.ElideRight, int(tw)))
        p.setFont(self.f_meta)
        p.setPen(QColor(ACCENT if item.get("current") else INK_3))
        fm2 = QFontMetrics(self.f_meta)
        p.drawText(QRectF(tx, ty + fm.height() + 6, tw, fm2.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(meta, Qt.ElideRight, int(tw)))
        p.restore()


class ItemView(QListView):
    """点击整行切换勾选；按住 Shift 点击可以连选一段；支持空搜索提示与滚动边缘渐隐。"""

    toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._anchor = None
        self._empty_filtered = False

    def setEmptyFiltered(self, empty):
        if self._empty_filtered != bool(empty):
            self._empty_filtered = bool(empty)
            self.viewport().update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        ix = self.indexAt(e.pos())
        if not ix.isValid():
            return
        d = self.itemDelegate()
        d.press_row = ix.row()
        self.update(ix)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)
        d = self.itemDelegate()
        pressed = d.press_row
        d.press_row = -1
        if pressed >= 0:
            self.update(self.model().index(pressed))
        ix = self.indexAt(e.pos())
        if not ix.isValid() or ix.row() != pressed:
            return
        m = self.model()
        r = ix.row()
        if e.modifiers() & Qt.ShiftModifier and self._anchor is not None:
            value = m.checked[self._anchor]
            lo, hi = sorted((self._anchor, r))
            m.set_checked([i for i in range(lo, hi + 1) if not self.isRowHidden(i)], value)
        else:
            m.toggle(r)
            self._anchor = r
        self.toggled.emit()

    def mouseDoubleClickEvent(self, e):
        self.mousePressEvent(e)     # 双击当两次单击处理，别吞掉

    def mouseMoveEvent(self, e):
        ix = self.indexAt(e.pos())
        r = ix.row() if ix.isValid() else -1
        d = self.itemDelegate()
        if d.hover_row != r:
            old = d.hover_row
            d.hover_row = r
            for row in (old, r):
                if row >= 0:
                    self.update(self.model().index(row))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        d = self.itemDelegate()
        if d.hover_row >= 0 or d.press_row >= 0:
            old_h, old_p = d.hover_row, d.press_row
            d.hover_row = -1
            d.press_row = -1
            for row in {old_h, old_p}:
                if row >= 0:
                    self.update(self.model().index(row))
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        if self._empty_filtered:
            # break-ui 空结果态：搜索无匹配时给出清晰引导
            vr = self.viewport().rect()
            cx, cy = vr.width() / 2.0, vr.height() / 2.0 - 12
            p.drawPixmap(int(cx - 12), int(cy - 28), make_icon("search", INK_3, 24))
            p.setPen(QColor(INK_2))
            p.setFont(ui_font(14, QFont.Medium))
            p.drawText(QRectF(0, cy + 4, vr.width(), 22), Qt.AlignCenter, "没有找到匹配的剧集")
            p.setPen(QColor(INK_3))
            p.setFont(ui_font(12))
            p.drawText(QRectF(0, cy + 28, vr.width(), 18), Qt.AlignCenter, "试试其他关键词，或清空搜索框")
        else:
            draw_scroll_edge_fade(p, self.viewport().rect(), self.verticalScrollBar(), CARD, 28)
        p.end()


# ---------------------------------------------------------------- 对话框
class CollectionDialog(QDialog):
    """浏览 / 预览窗口：读出清单 -> 勾选 -> 确认下载。

    合集/列表/收藏夹会列出全部视频；单个视频会列出它的各个分 P。
    """

    def __init__(self, info=None, url="", parent=None):
        super().__init__(parent)
        self.info = info or {}
        self.url = url
        items = self.info.get("items") or []
        self.setWindowTitle("选择要下载的内容")
        self.setMinimumSize(720, 560)
        self.resize(820, 680)
        self._threads = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 18)
        root.setSpacing(14)

        # ---- 头部：封面 + 名称（横排）----
        head = QHBoxLayout()
        head.setSpacing(16)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setStyleSheet("background:%s; border-radius:10px;" % FIELD)
        head.addWidget(self.cover, 0, Qt.AlignTop)
        tbox = QVBoxLayout()
        tbox.setSpacing(6)
        title_str = self.info.get("title") or "合集"
        t = ElidedTitleLabel(title_str, max_lines=2, font=ui_font(19, QFont.Bold), color=INK)
        tbox.addWidget(t)
        owner = self.info.get("owner") or ""
        bits = [self.info.get("kind_label", "合集"),
                "共 %d 个" % sum(1 for it in items if not it.get("extra"))]
        if owner:
            bits.append(owner)
        sub_full = "  ·  ".join(bits)
        sub_fm = QFontMetrics(ui_font(12))
        sub = QLabel(sub_fm.elidedText(sub_full, Qt.ElideRight, 580))
        sub.setObjectName("sub")
        if len(sub_full) > 40:
            sub.setToolTip(sub_full)
        tbox.addWidget(sub)
        tbox.addStretch(1)
        head.addLayout(tbox, 1)
        root.addLayout(head)

        # ---- 工具条 ----
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("搜索标题")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(_icon_action(self.search), QLineEdit.LeadingPosition)
        self.search.setFixedWidth(240)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)          # 打字时别每个键都重排一遍
        self._filter_timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda _t: self._filter_timer.start())
        tools.addWidget(self.search)
        tools.addStretch(1)
        self.chk_extra = QCheckBox("显示花絮 / PV")
        self.chk_extra.setToolTip("番剧除了正片，还有 PV、花絮、二创解析等分区")
        self.chk_extra.toggled.connect(self._toggle_extra)
        self.chk_extra.setVisible(any(it.get("extra") for it in items))
        tools.addWidget(self.chk_extra)
        tools.addSpacing(6)
        self.btn_all = Button("全选", "secondary", height=32)
        self.btn_all.clicked.connect(self._toggle_all)
        tools.addWidget(self.btn_all)
        self.btn_inv = Button("反选", "secondary", height=32)
        self.btn_inv.clicked.connect(self._invert)
        tools.addWidget(self.btn_inv)
        root.addLayout(tools)

        # ---- 清单 ----
        card = Card(padding=(4, 6, 4, 6))
        self.model = ItemModel(items, self)
        self.view = ItemView()
        self.view.setItemDelegate(ItemDelegate(self.view))
        self.view.setModel(self.model)
        self.view.toggled.connect(self._on_user_toggled)
        card.layout.addWidget(self.view)
        root.addWidget(card, 1)
        self._apply_visibility()
        # 打开时滚到「当前这一集」
        for i, it in enumerate(items):
            if it.get("current"):
                QTimer.singleShot(0, lambda i=i: self.view.scrollTo(
                    self.model.index(i), QAbstractItemView.PositionAtCenter))
                break

        # ---- 底部 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.chk_audio = QCheckBox("只下载音频")
        self.chk_audio.setToolTip("只保存音频（m4a），适合音乐、播客类视频")
        bottom.addWidget(self.chk_audio)
        bottom.addSpacing(10)
        self.counter = QLabel()
        self.counter.setObjectName("muted")
        self.counter.setFont(tabular_font(12))
        bottom.addWidget(self.counter)
        bottom.addStretch(1)
        cancel = Button("取消", "secondary")
        cancel.clicked.connect(self.reject)
        self.ok = Button("下载", "primary", "download")
        self.ok.setMinimumWidth(128)
        self.ok.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(self.ok)
        root.addLayout(bottom)

        # 共享动效定时器：用于驱动勾选与缩略图渐显，无动画时自动休眠
        self._fx_timer = QTimer(self)
        self._fx_timer.setInterval(16)
        self._fx_timer.timeout.connect(self._tick_fx)

        self._update_count()
        self.view.setFocus()          # 别让搜索框一打开就抢焦点（会亮起粉色边框）
        animate_dialog_open(self)
        QTimer.singleShot(0, self._load_covers)

    def _start_fx(self):
        if not reduced_motion() and not self._fx_timer.isActive():
            self._fx_timer.start()

    def _tick_fx(self):
        now = time.monotonic()
        active = False
        for i in range(len(self.model.items)):
            if self.view.isRowHidden(i):
                continue
            ct = self.model.check_t[i]
            tt = self.model.thumb_t[i]
            if (ct and now - ct < 0.18) or (tt and now - tt < 0.20):
                active = True
                self.view.update(self.model.index(i))
        if not active:
            self._fx_timer.stop()

    def _on_user_toggled(self):
        self._start_fx()
        self._update_count()

    # ---------- 可见性 / 过滤 ----------
    def _apply_visibility(self):
        kw = self.search.text().strip().lower()
        show_extra = self.chk_extra.isChecked()
        v = self.view
        v.setUpdatesEnabled(False)
        try:
            for i, it in enumerate(self.model.items):
                hidden = bool(it.get("extra")) and not show_extra
                if not hidden and kw:
                    hidden = kw not in (it.get("title") or "").lower() and \
                        kw not in (it.get("bvid") or "").lower()
                if v.isRowHidden(i) != hidden:
                    v.setRowHidden(i, hidden)
        finally:
            v.setUpdatesEnabled(True)
        self.view.setEmptyFiltered(len(self._visible()) == 0 and len(self.model.items) > 0)

    def _visible(self):
        return [i for i in range(len(self.model.items)) if not self.view.isRowHidden(i)]

    def _filter(self):
        self._apply_visibility()
        self._update_count()

    def _toggle_extra(self, on):
        self._apply_visibility()
        if on:
            self._load_covers(extra=True)
        self._update_count()

    # ---------- 选择 ----------
    def _toggle_all(self):
        vis = self._visible()
        all_on = vis and all(self.model.checked[i] for i in vis)
        self.model.set_checked(vis, not all_on)
        self._start_fx()
        self._update_count()

    def _invert(self):
        vis = self._visible()
        on = [i for i in vis if not self.model.checked[i]]
        off = [i for i in vis if self.model.checked[i]]
        self.model.set_checked(on, True)
        self.model.set_checked(off, False)
        self._start_fx()
        self._update_count()

    def _update_count(self):
        vis = self._visible()
        n = sum(1 for i in vis if self.model.checked[i])
        self.counter.setText("已选 %d / %d" % (n, len(vis)))
        self.btn_all.setText("全不选" if vis and n == len(vis) else "全选")
        self.btn_all.setEnabled(bool(vis))
        self.btn_inv.setEnabled(bool(vis))
        self.btn_all.updateGeometry()
        self.ok.setText("下载 %d 个" % n if n else "请先选择")
        self.ok.setEnabled(n > 0)

    # ---------- 封面 ----------
    def _start_thread(self, urls, size, slot):
        t = CoverThread(urls, self, size=size, dpr=max(2.0, self.devicePixelRatioF()))
        t.ready.connect(slot)
        self._threads.append(t)
        t.start()

    def _load_covers(self, extra=False):
        items = self.model.items
        if not extra:
            cover = self.info.get("cover") or (items[0].get("pic") if items else "")
            if cover:
                self._start_thread([(-1, cover)], (COVER_W, COVER_H), self._on_cover)
        urls = [(i, it.get("pic")) for i, it in enumerate(items)
                if it.get("pic") and bool(it.get("extra")) == extra
                and self.model.thumbs[i] is None]
        # 同一张图（单视频的多个分 P 共用封面）只抓一次
        seen = {}
        uniq = []
        for i, u in urls:
            seen.setdefault(u, []).append(i)
            if len(seen[u]) == 1:
                uniq.append((i, u))
        self._dup = getattr(self, "_dup", {})
        for u, idxs in seen.items():
            self._dup[idxs[0]] = idxs
        if uniq:
            self._start_thread(uniq[:400], (THUMB_W, THUMB_H), self._on_thumb)

    def _on_cover(self, _idx, img):
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(img.width() / float(COVER_W))
        # 圆角
        out = QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, COVER_W, COVER_H), 10, 10)
        p.setClipPath(path)
        p.drawPixmap(0, 0, pm)
        p.end()
        self.cover.setStyleSheet("")
        self.cover.setPixmap(out)

    def _on_thumb(self, idx, img):
        pm = QPixmap.fromImage(img)
        for i in self._dup.get(idx, [idx]):
            self.model.set_thumb(i, pm)
        self._start_fx()

    # ---------- 结果 ----------
    def selected_items(self):
        return [self.model.items[i] for i in self._visible() if self.model.checked[i]]

    @property
    def audio_only(self):
        """只下音频（在浏览窗口里勾）。"""
        return self.chk_audio.isChecked()

    def _stop_threads(self):
        """停掉后台抓图线程。

        抓图线程可能正卡在网络请求上，**运行中的 QThread 被析构会让 Qt 直接 abort**，
        所以等不干净时要把它从父子关系里摘出来、Python 侧继续持有引用，等它自己跑完再删。
        """
        for t in self._threads:
            t.stop()
            try:
                t.ready.disconnect()
            except TypeError:
                pass
            if t.wait(100):
                t.deleteLater()
            else:
                t.setParent(None)
                _live_threads.append(t)
                t.finished.connect(lambda th=t: _release_thread(th))
        self._threads = []

    def done(self, r):
        self._fx_timer.stop()
        self._stop_threads()
        super().done(r)


def _icon_action(parent):
    from PyQt5.QtWidgets import QAction
    from PyQt5.QtGui import QIcon
    return QAction(QIcon(make_icon("search", INK_3, 16)), "", parent)
