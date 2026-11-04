#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合集预览与选择对话框。

用户粘的是合集/列表链接时，先弹这个窗口让他预览清单、勾选要下的视频。

列表用 QListView + 自绘 delegate：以前每行是一个 QWidget（勾选框 + 两个 QLabel + 缩略图），
一百多集就是七八百个控件，打开窗口、滚动、全选时都明显发涩；现在每行只是模型里的一条数据，
画在屏幕上的那几行才会被绘制。
"""

import threading

from PyQt5.QtCore import (QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListView, QStyledItemDelegate, QVBoxLayout)

import bilifetch_collection as col
from bilifetch_ui import (ACCENT, ACCENT_SOFT, FIELD, INK, INK_3, Button, Card,
                          make_icon, ui_font)

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

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.checked = [bool(it.get("checked", True)) for it in self.items]
        self.thumbs = [None] * len(self.items)
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
        if role == Qt.ToolTipRole:
            return self.items[i].get("title")
        return None

    def set_checked(self, rows, value):
        rows = list(rows)
        if not rows:
            return
        for r in rows:
            self.checked[r] = value
        self.dataChanged.emit(self.index(min(rows)), self.index(max(rows)), [self.CheckRole])

    def toggle(self, r):
        self.checked[r] = not self.checked[r]
        ix = self.index(r)
        self.dataChanged.emit(ix, ix, [self.CheckRole])

    def set_thumb(self, r, pm):
        if 0 <= r < len(self.thumbs):
            self.thumbs[r] = pm
            ix = self.index(r)
            self.dataChanged.emit(ix, ix, [self.ThumbRole])


class ItemDelegate(QStyledItemDelegate):
    """一行：勾选框 + 缩略图 + 标题 + 时长/播放量。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_title = ui_font(13, QFont.Medium)
        self.f_meta = ui_font(12)
        self.f_badge = ui_font(10, QFont.DemiBold)
        self.hover_row = -1

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect)
        checked = index.data(ItemModel.CheckRole)
        item = index.data(ItemModel.ItemRole) or {}
        row = index.row()

        # 背景：悬停浅灰，选中浅粉
        card = r.adjusted(6, 3, -6, -3)
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT_SOFT))
            p.drawRoundedRect(card, 10, 10)
        elif row == self.hover_row:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F6F7F8"))
            p.drawRoundedRect(card, 10, 10)

        # 勾选框
        cb = QRectF(card.left() + 12, card.center().y() - 9, 18, 18)
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(cb, 5, 5)
            p.drawPixmap(cb.adjusted(1, 1, -1, -1).toRect(), make_icon("check", "#FFFFFF", 16))
        else:
            p.setPen(QPen(QColor("#C9CCD0"), 1.5))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(cb.adjusted(0.75, 0.75, -0.75, -0.75), 5, 5)

        # 缩略图
        th = QRectF(cb.right() + 14, card.center().y() - THUMB_H / 2.0, THUMB_W, THUMB_H)
        path = QPainterPath()
        path.addRoundedRect(th, 7, 7)
        pm = index.data(ItemModel.ThumbRole)
        if pm is not None:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(th.toRect(), pm)
            p.restore()
        else:
            p.fillPath(path, QColor(FIELD))
            p.drawPixmap(int(th.center().x() - 9), int(th.center().y() - 9),
                         make_icon("play", "#C9CCD0", 18))
        if item.get("duration"):
            txt = col.format_duration(item["duration"])
            p.setFont(self.f_badge)
            fm = QFontMetrics(self.f_badge)
            bw = fm.horizontalAdvance(txt) + 10
            br = QRectF(th.right() - bw - 4, th.bottom() - 18, bw, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
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
    """点击整行切换勾选；按住 Shift 点击可以连选一段。"""

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

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        ix = self.indexAt(e.pos())
        if not ix.isValid():
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
        if d.hover_row >= 0:
            old = d.hover_row
            d.hover_row = -1
            self.update(self.model().index(old))
        super().leaveEvent(e)


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
        t = QLabel(self.info.get("title") or "合集")
        t.setObjectName("h1")
        t.setWordWrap(True)
        t.setMaximumHeight(56)
        tbox.addWidget(t)
        owner = self.info.get("owner") or ""
        bits = [self.info.get("kind_label", "合集"),
                "共 %d 个" % sum(1 for it in items if not it.get("extra"))]
        if owner:
            bits.append(owner)
        sub = QLabel("  ·  ".join(bits))
        sub.setObjectName("sub")
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
        b_inv = Button("反选", "secondary", height=32)
        b_inv.clicked.connect(self._invert)
        tools.addWidget(b_inv)
        root.addLayout(tools)

        # ---- 清单 ----
        card = Card(padding=(4, 6, 4, 6))
        self.model = ItemModel(items, self)
        self.view = ItemView()
        self.view.setItemDelegate(ItemDelegate(self.view))
        self.view.setModel(self.model)
        self.view.toggled.connect(self._update_count)
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

        self._update_count()
        self.view.setFocus()          # 别让搜索框一打开就抢焦点（会亮起粉色边框）
        QTimer.singleShot(0, self._load_covers)

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
        self._update_count()

    def _invert(self):
        vis = self._visible()
        on = [i for i in vis if not self.model.checked[i]]
        off = [i for i in vis if self.model.checked[i]]
        self.model.set_checked(on, True)
        self.model.set_checked(off, False)
        self._update_count()

    def _update_count(self):
        vis = self._visible()
        n = sum(1 for i in vis if self.model.checked[i])
        self.counter.setText("已选 %d / %d" % (n, len(vis)))
        self.btn_all.setText("全不选" if vis and n == len(vis) else "全选")
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
        self._stop_threads()
        super().done(r)


def _icon_action(parent):
    from PyQt5.QtWidgets import QAction
    from PyQt5.QtGui import QIcon
    return QAction(QIcon(make_icon("search", INK_3, 16)), "", parent)
