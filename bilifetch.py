#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bilifetch —— B 站视频下载器（macOS / Linux / Windows 通用）

参考 nICEnnnnnnnLee/BilibiliDown 的 API 调用流程重写的命令行版本：

    1. 解析链接      ep / ss / av / bv / b23.tv
    2. 查分 P 列表   x/player/pagelist          -> cid
    3. 查播放地址    x/player/playurl           -> DASH 音视频分离流
                    pgc/player/web/playurl     -> 番剧专用
    4. 下载 + ffmpeg 合并成 mp4

依赖：requests、ffmpeg
用法：python3 bilifetch.py "https://www.bilibili.com/bangumi/play/ep1633643"
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse, urlunparse


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

API = "https://api.bilibili.com"

VERSION = "1.1.0"

# 画质 id -> 名称（B 站官方编码）
QN_NAME = {
    127: "8K", 126: "杜比", 125: "HDR", 120: "4K", 116: "1080P60",
    112: "1080P+", 80: "1080P", 74: "720P60", 64: "720P", 32: "480P", 16: "360P",
}

# 视频编码优先级（照搬上游 Global.videoCodecPriority）：7=AVC/H.264, 12=HEVC, 13=AV1
VIDEO_CODEC_PRIORITY = [7, 12, 13]
# 音频码率优先级（照搬上游 Global.audioQualityPriority）：192K / 132K / 64K
AUDIO_PRIORITY = [30280, 30232, 30216, -1]

# B 站 CDN 各镜像速度差异极大（同一个文件实测：mirrorcoso1 只有 0.1 MB/s，
# mirrorhw / estghw 有 4 MB/s），所以下载前先探速，挑最快的镜像。
# 前排的是实测较快的。
CDN_MIRRORS = [
    "upos-sz-estghw.bilivideo.com",
    "upos-sz-mirrorhw.bilivideo.com",
    "upos-sz-mirrorali.bilivideo.com",
    "upos-sz-mirrorcoso1.bilivideo.com",
    "upos-sz-mirrorcos.bilivideo.com",
    "upos-sz-mirrorcosb.bilivideo.com",
]

# 单个分段的大小。CDN 对长时间的单连接会直接 reset，分段要够小。
CHUNK_SIZE = 4 * 1024 * 1024

# 从访达双击启动的 App，PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，
# 不含 Homebrew / MacPorts 的 bin 目录 ⇒ ffmpeg 这类工具要手动翻这些位置。
EXTRA_BIN_DIRS = [
    "/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
    "/opt/homebrew/sbin", "/usr/local/sbin", "/opt/miniconda3/bin",
]


def find_executable(name):
    """在 PATH 和常见安装目录里找可执行文件，返回绝对路径；找不到返回 None。"""
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_BIN_DIRS:
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None

# WBI 混淆表（照搬上游 API.MixinArray）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]


class Cancelled(Exception):
    """用户中途取消。"""


def log(msg):
    print(msg, flush=True)


def sanitize(name, maxlen=80):
    """把标题里的非法文件名字符换掉，并截断长度。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().strip(".")
    return (name[:maxlen] or "untitled")


_requests = None


def req():
    """拿到 requests 模块（第一次用到时才导入）。

    `import requests` 要 170ms，而图形界面开窗时压根用不到它 ——
    推迟到真正联网时，开窗能快三分之一。后面会在后台线程里预热。
    """
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests


def warm_up():
    """后台预热：把 requests 先加载好，别让它在用户点按钮时才卡一下。"""
    try:
        req()
    except Exception:
        pass


class BiliClient:
    """Bilibili API 客户端。"""

    def __init__(self, cookie="", proxy=None):
        self.session = req().Session()
        # 默认不读系统代理：ClashX 之类的 TUN 代理会重置 CDN 连接
        self.session.trust_env = False
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if cookie:
            # 放进 cookie jar（domain=.bilibili.com）：
            # 一是 requests 不会用 jar 里的 cookie 覆盖我们设的 header，
            # 二是 CDN（*.bilivideo.com）拿不到 B 站 cookie，不至于泄漏出去。
            for part in cookie.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    if k:
                        self.session.cookies.set(k.strip(), v.strip(),
                                                domain=".bilibili.com", path="/")
        self._wbi_img = None
        self._pgc_cache = {}
        # 正在读数据的响应：取消时直接掐断它们
        self._active = set()
        self._active_lock = threading.Lock()
        # 探速结果缓存（按域名）：视频流探过的，音频流直接复用
        self._probe_cache = {}

    # ---------- 取消 ----------
    def cancel(self):
        """立刻打断正在进行的网络读取。

        光置取消标志不够：请求正卡在 socket 读取上时，要等到读超时（最长 60 秒）
        才会去看标志 —— 表现就是"点了停止半天停不下来"。
        这里直接把连接关掉，阻塞的读会立刻抛错，然后重试逻辑就会看到取消标志。

        关连接的动作放到后台线程：close() 可能和正在读的线程抢锁，
        放在界面线程里做会把界面卡住。
        """
        with self._active_lock:
            resp_list = list(self._active)
        if not resp_list:
            return
        threading.Thread(target=self._close_all, args=(resp_list,),
                         name="cancel-conns", daemon=True).start()

    @staticmethod
    def _close_all(resp_list):
        for r in resp_list:
            try:
                r.close()
            except Exception:
                pass

    def _track(self, resp):
        with self._active_lock:
            self._active.add(resp)
        return resp

    def _untrack(self, resp):
        with self._active_lock:
            self._active.discard(resp)

    # ---------- 基础请求 ----------

    def get_json(self, url, params=None, referer=None):
        """请求 API，返回解析后的 json；失败抛 RuntimeError。"""
        headers = {"Referer": referer} if referer else None
        resp = self.session.get(url, params=params, headers=headers, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError("接口报错 code=%s message=%s" % (data.get("code"), data.get("message")))
        return data

    # ---------- WBI 签名（照搬上游 API.encWbi）----------

    def _mixin_key(self):
        if self._wbi_img is None:
            nav = self.get_json(API + "/x/web-interface/nav")
            img = nav["data"]["wbi_img"]
            stem = lambda u: os.path.splitext(os.path.basename(u))[0]
            self._wbi_img = stem(img["img_url"]) + stem(img["sub_url"])
        return "".join(self._wbi_img[i] for i in MIXIN_KEY_ENC_TAB[:32])

    def sign(self, params):
        """给参数加上 w_rid / wts，返回排序后的 query 字符串。"""
        mixin_key = self._mixin_key()
        params = dict(params)
        params["wts"] = str(int(time.time()))
        items = []
        for key in sorted(params):
            value = re.sub(r"[!'()*]", "", str(params[key]))
            items.append((quote(key, safe=""), quote(value, safe="")))
        query = "&".join("%s=%s" % kv for kv in items)
        params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
        return "&".join("%s=%s" % (quote(k, safe=""), quote(str(v), safe=""))
                        for k, v in sorted(params.items()))

    def get_json_signed(self, path, params):
        """带 WBI 签名地请求接口（部分接口未签名会返回 -403）。"""
        url = API + path + "?" + self.sign(params)
        return self.get_json(url)

    # ---------- 链接解析 ----------

    @property
    def has_login(self):
        """有没有带上 SESSDATA（即是否已登录）。"""
        return bool(self.session.cookies.get("SESSDATA", domain=".bilibili.com")
                    or self.session.cookies.get("SESSDATA"))

    def resolve(self, text):
        """把用户输入解析成 {'bvid','cid','title','episodes','is_pgc'}。"""
        text = text.strip()
        # 短链先跟随跳转
        if "b23.tv" in text:
            resp = self.session.get(text if text.startswith("http") else "https://" + text,
                                    allow_redirects=True, timeout=(10, 30))
            text = resp.url

        if re.fullmatch(r"av\d+", text, re.I):
            return self._from_av(text.lower())
        if re.fullmatch(r"bv[0-9A-Za-z]{10}", text, re.I):
            return self._from_bvid(text)

        m = re.search(r"/bangumi/play/(ep|ss)(\d+)", text)
        if m:
            return self._from_ep(m.group(1), m.group(2))
        m = re.search(r"\b(ep|ss)(\d+)\b", text)
        if m:
            return self._from_ep(m.group(1), m.group(2))
        m = re.search(r"/video/(av\d+|bv[0-9A-Za-z]{10})", text, re.I)
        if m:
            return self._from_av(m.group(1)) if m.group(1).lower().startswith("av") \
                else self._from_bvid(m.group(1))
        raise ValueError("无法识别的链接或 ID：%s" % text)

    def _from_av(self, aid):
        aid = re.sub(r"(?i)^av", "", aid)
        view = self.get_json(API + "/x/web-interface/view", {"aid": aid})["data"]
        return self._pack(view, prefer_cid=None)

    def _from_bvid(self, bvid):
        view = self.get_json(API + "/x/web-interface/view", {"bvid": bvid})["data"]
        return self._pack(view, prefer_cid=None)

    def _from_ep(self, kind, num):
        """番剧：ep_id / season_id -> season 接口 -> bvid + cid。"""
        key = "ep_id" if kind == "ep" else "season_id"
        season = self.get_json(API + "/pgc/view/web/season", {key: num})["result"]
        episodes = season.get("episodes") or []
        if not episodes:
            raise RuntimeError("season_id=%s 没有取到任何分集" % num)
        target = None
        if kind == "ep":
            for ep in episodes:
                if str(ep.get("id")) == str(num):
                    target = ep
                    break
            if target is None:
                raise RuntimeError("该番剧里找不到 ep%s" % num)
        else:
            target = episodes[0]
        view = self.get_json(API + "/x/web-interface/view", {"bvid": target["bvid"]})["data"]
        info = self._pack(view, prefer_cid=target.get("cid"))
        info["season_title"] = season.get("season_title") or ""
        # episodes 里同一集会出现两次（短版切片 + 正片），按集号分组留最长的那条
        best = {}
        for ep in episodes:
            key = ep.get("title") or str(ep.get("id"))
            old = best.get(key)
            if old is None or (ep.get("duration") or 0) > (old.get("duration") or 0):
                best[key] = ep
        info["episodes"] = [{"cid": ep.get("cid"), "bvid": ep.get("bvid"),
                             "title": ep.get("title") or "",
                             "long_title": ep.get("long_title") or "",
                             "duration": int(ep.get("duration") or 0) // 1000,  # 毫秒->秒
                             "ep_id": ep.get("id")} for ep in best.values()]
        return info

    def _pack(self, view, prefer_cid):
        """把 view 接口的数据整理成统一结构。"""
        pages = view.get("pages") or []
        cid = prefer_cid or (pages[0].get("cid") if pages else None)
        # 番剧的 view 里 pages 为空，用 season 传来的 cid
        if cid is None:
            raise RuntimeError("没有取到 cid，可能需要登录")
        is_pgc = bool(view.get("redirect_url"))
        return {
            "bvid": view.get("bvid"),
            "aid": view.get("aid"),
            "cid": cid,
            "title": view.get("title") or "",
            "owner": (view.get("owner") or {}).get("name") or "",
            "duration": view.get("duration") or 0,
            "cover": view.get("pic") or "",
            "brief": view.get("desc") or "",
            "pages": pages,
            "is_pgc": is_pgc,
            "episodes": [],
        }

    # ---------- 播放地址 ----------

    def playurl(self, bvid, cid, qn=0):
        """取 DASH 播放地址，返回 data。qn=0 表示要最高画质（服务端会按账号权限自动降级）。"""
        common = {"bvid": bvid, "cid": cid, "qn": qn or 120, "fnver": 0, "fnval": 4048,
                  "fourk": 1, "otype": "json"}
        if self._is_pgc(bvid):
            try:
                return self.get_json(API + "/pgc/player/web/playurl", common)["result"]
            except Exception as e:
                log("  番剧播放接口失败，改用普通接口：%s" % e)
        try:
            return self.get_json(API + "/x/player/playurl", common)["data"]
        except Exception:
            # 未签名被拒时，带 WBI 签名再试一次
            return self.get_json_signed("/x/player/playurl", common)["data"]

    def _is_pgc(self, bvid):
        if bvid not in self._pgc_cache:
            try:
                view = self.get_json(API + "/x/web-interface/view", {"bvid": bvid})["data"]
                self._pgc_cache[bvid] = bool(view.get("redirect_url"))
            except Exception:
                self._pgc_cache[bvid] = False
        return self._pgc_cache[bvid]

    def pagelist(self, bvid):
        data = self.get_json(API + "/x/player/pagelist", {"bvid": bvid})["data"]
        return [{"cid": p["cid"], "part": p.get("part") or "", "page": p.get("page")} for p in data]

    # ---------- 下载 ----------

    def download(self, urls, dest, referer="https://www.bilibili.com/", threads=16, cdn="",
                 on_progress=None, should_stop=None):
        """多线程分段下载。

        两点实测结论：
        1) CDN 对长时间的单连接会直接 reset，分段（Range）请求才稳；
        2) 不同镜像速度能差 40 倍，下载前先探速挑最快的。
        """
        if isinstance(urls, str):
            urls = [urls]
        urls = self._expand_candidates(urls, cdn)
        best = self._fastest_cdn(urls, referer, should_stop=should_stop)
        order = ([best] if best else []) + [u for u in urls if u != best]
        last_err = None
        for url in order:
            try:
                self._download_split(url, dest, referer, threads, on_progress, should_stop)
                return
            except Cancelled:
                raise
            except Exception as e:
                last_err = e
                log("    换下一个地址：%s" % str(e)[:60])
        raise RuntimeError("所有下载地址都失败了：%s" % last_err)

    def _expand_candidates(self, urls, cdn=""):
        """把原始地址展开成「原地址 + 各镜像」候选列表。"""
        hosts = ([cdn] + CDN_MIRRORS) if cdn else CDN_MIRRORS
        cands = []
        for u in urls:
            p = urlparse(u)
            for host in hosts:
                cands.append(urlunparse(p._replace(netloc=host)))
            if not cdn:
                cands.append(u)
        # 去重并保持顺序
        seen, out = set(), []
        for u in cands:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _fastest_cdn(self, urls, referer, should_stop=None):
        """挑最快的镜像。

        这里以前是**串行**探的，坑很大：
        候选镜像有 18 个（9 个域名 × 主/备地址），里面不少是坏的或者极慢的。
        串行探、每个最多等 11 秒（连接 5 + 读取 6），
        实测下载开始前要白等 **11.6 秒**，而且这段时间里点「停止」几乎没反应
        （请求正卡在等响应头，取消标志根本没机会被看到）。

        改成**并行探**：所有候选一起测，取最快的。整体耗时 ≈ 单个候选的耗时。
        另外三点讲究：
        1) 计时从**收到响应头之后**开始 —— 连接和 TLS 握手那几百毫秒不该算进去，
           否则快的镜像会被误判成慢的（实测镜像之间能差 40 倍，选错就全程慢）。
        2) 探速用很短的超时（探速只是要个相对快慢，不用等满）。
        3) **同一个客户端里探过的镜像不再重复探** —— 视频流探完，音频流直接复用，
           省掉一半的连接风暴（一集番剧原本会同时开 36 个探测连接）。
        """
        if not urls:
            return None

        cache = self._probe_cache

        def probe(u):
            host = urlparse(u).netloc
            if host in cache:
                return (cache[host], u)
            try:
                resp = self.session.get(u, headers=self._range_headers(referer, 0, 256 * 1024),
                                        stream=True, timeout=(2.5, 2.5))
                self._track(resp)
                try:
                    t = time.time()          # 响应头到了才开始算传输速度
                    n = sum(len(c) for c in resp.iter_content(1 << 16))
                finally:
                    self._untrack(resp)
                    resp.close()
                if n <= 0:
                    return None
                speed = n / max(time.time() - t, 0.01)
                cache[host] = speed
                return (speed, u)
            except Exception:
                return None

        from concurrent.futures import ThreadPoolExecutor, as_completed
        best, best_speed = None, 0.0
        pool = ThreadPoolExecutor(max_workers=min(12, len(urls)))
        try:
            futures = [pool.submit(probe, u) for u in urls]
            for fut in as_completed(futures):
                if should_stop and should_stop():
                    raise Cancelled()
                res = fut.result()
                if res and res[0] > best_speed:
                    best_speed, best = res[0], res[1]
                if best_speed > 5e6:       # 5 MB/s 单连接就够快，不用等其它镜像
                    break
        finally:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)
        if best:
            log("    CDN 镜像：%s  探速 %.2f MB/s" % (urlparse(best).netloc, best_speed / 1e6))
        return best

    def _range_headers(self, referer, start, end):
        return {"Referer": referer, "Accept-Encoding": "identity",
                "Range": "bytes=%d-%d" % (start, end)}

    def _total_size(self, url, referer):
        """用一个 1 字节的 Range 请求探出文件总大小。"""
        resp = self.session.get(url, headers=self._range_headers(referer, 0, 0),
                                stream=True, timeout=(6, 10))
        self._track(resp)
        try:
            cr = resp.headers.get("Content-Range") or ""
        finally:
            self._untrack(resp)
            resp.close()
        if "/" not in cr:
            raise RuntimeError("服务端没有返回文件大小")
        return int(cr.rsplit("/", 1)[1])

    def _fetch_chunk(self, url, path, start, end, referer, prog, should_stop=None):
        """下载一个分段，中断后从断点续传本段。"""
        written = 0
        for attempt in range(5):
            if should_stop and should_stop():
                raise Cancelled()
            try:
                resp = self.session.get(url, headers=self._range_headers(referer, start + written, end),
                                        stream=True, timeout=(5, 4))
                self._track(resp)
                try:
                    if resp.status_code not in (200, 206):
                        raise RuntimeError("HTTP %s" % resp.status_code)
                    with open(path, "r+b") as fp:
                        fp.seek(start + written)
                        for chunk in resp.iter_content(1 << 16):
                            if should_stop and should_stop():
                                raise Cancelled()
                            fp.write(chunk)
                            written += len(chunk)
                            prog.add(len(chunk))
                finally:
                    self._untrack(resp)
                    resp.close()
                if written >= end - start + 1:
                    return
            except Cancelled:
                raise
            except Exception as e:
                if should_stop and should_stop():
                    raise Cancelled()      # 取消优先，别再睡一觉
                if attempt == 4:
                    raise
                log("    分段 %d-%d 中断（%s），重试" % (start, end, str(e)[:40]))
                time.sleep(1 + attempt)
        raise RuntimeError("分段 %d-%d 下载不完整" % (start, end))

    def _download_split(self, url, dest, referer, threads, on_progress=None, should_stop=None):
        tmp = dest + ".part"
        state_file = dest + ".part.state"
        total = self._total_size(url, referer)
        n_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE

        # 断点信息：已完成的分段编号
        done_chunks = set()
        if os.path.exists(state_file):
            try:
                with open(state_file) as fp:
                    done_chunks = set(json.load(fp))
            except Exception:
                done_chunks = set()
        if not os.path.exists(tmp) or os.path.getsize(tmp) != total:
            with open(tmp, "wb") as fp:
                fp.truncate(total)
            done_chunks = set()

        ranges = []
        for i in range(n_chunks):
            start = i * CHUNK_SIZE
            end = min(total - 1, start + CHUNK_SIZE - 1)
            ranges.append((i, start, end))

        prog = Progress(total, already=sum(end - start + 1 for i, start, end in ranges
                                           if i in done_chunks),
                        callback=on_progress)
        state_lock = threading.Lock()

        def task(item):
            i, start, end = item
            if i in done_chunks:
                return
            self._fetch_chunk(url, tmp, start, end, referer, prog, should_stop)
            with state_lock:
                done_chunks.add(i)
                with open(state_file, "w") as fp:
                    json.dump(sorted(done_chunks), fp)

        with ThreadPoolExecutor(max(1, min(threads, 32))) as ex:
            list(ex.map(task, ranges))

        prog.finish()
        os.replace(tmp, dest)
        if os.path.exists(state_file):
            os.remove(state_file)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


class Progress:
    """多线程下载的进度显示。callback(done, total) 供 GUI 用。

    回调要**节流**：16 路并发、每片 64KB，原始触发频率能到 250 次/秒。
    图形界面里每次回调都是一次跨线程信号，GUI 线程每秒被唤醒 250 次，
    排队的事件把主线程塞满 —— 表现就是"界面有点卡"。
    节流到 12 次/秒，人眼完全看不出差别，但界面负担降到 1/20。
    """

    def __init__(self, total, already=0, callback=None):
        self.total = total
        self.done = already        # 总进度（含断点续传已下好的部分）
        self.start = already        # 本次运行开始时的进度，用于算速度
        self.lock = threading.Lock()
        self.last = 0.0
        self.last_cb = 0.0
        self.t0 = time.time()
        self.callback = callback

    def add(self, n):
        with self.lock:
            self.done += n
            now = time.time()
            if self.callback:
                finished = bool(self.total) and self.done >= self.total
                if finished or now - self.last_cb >= 0.08:
                    self.last_cb = now
                    self.callback(self.done, self.total)
            if now - self.last < 0.4:
                return
            self.last = now
            speed = (self.done - self.start) / max(now - self.t0, 1e-6)
            pct = "%.1f%%" % (self.done * 100.0 / self.total) if self.total else ""
            log("\r    %s  %s / %s  %.1f MB/s" %
                (pct, human(self.done), human(self.total), speed / 1e6))

    def finish(self):
        # 补最后一次回调，保证界面上的百分比停在最终值
        if self.callback:
            try:
                self.callback(self.done, self.total)
            except Exception:
                pass
        log("")


def pick_video(dash, quality):
    """按画质 + 编码优先级挑一条视频流。"""
    videos = dash.get("video") or []
    if not videos:
        return None
    same = [v for v in videos if v.get("id") == quality] or videos
    for codec in VIDEO_CODEC_PRIORITY:
        for v in same:
            if v.get("codecid") == codec:
                return v
    return same[0]


def pick_audio(dash, quality):
    """按码率优先级挑一条音频流。"""
    audios = list(dash.get("audio") or [])
    flac = (dash.get("flac") or {}).get("audio")
    dolby = (dash.get("dolby") or {}).get("audio")
    if flac:
        audios.append(flac)
    if dolby and quality == 126:
        audios.append(dolby)
    if not audios:
        return None
    for q in AUDIO_PRIORITY:
        if q == -1:
            return max(audios, key=lambda a: a.get("bandwidth") or 0)
        for a in audios:
            if a.get("id") == q:
                return a
    return max(audios, key=lambda a: a.get("bandwidth") or 0)


def media_url(media):
    """base_url 失效时依次尝试 backup_url。"""
    return [media.get("base_url")] + list(media.get("backup_url") or [])


def merge(video_file, audio_file, out_file, ffmpeg="ffmpeg"):
    """ffmpeg 合并音视频（流拷贝，不重编码）。"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-i", video_file, "-i", audio_file, "-c", "copy", "-movflags", "+faststart", out_file]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 合并失败：\n%s" % proc.stderr[-800:])


def download_episode(client, bvid, cid, name, out_dir, quality=0, threads=16, cdn="",
                     audio_only=False, force=False, ffmpeg=None, on_log=None,
                     on_progress=None, on_stage=None, should_stop=None):
    """下载单集：取流 -> 下载音视频 -> ffmpeg 合并。返回输出文件路径。

    命令行和图形界面都走这个函数，保证两条路的行为一致。
    on_log(text)        打印一行日志
    on_progress(done, total)  下载字节进度
    on_stage(text)      阶段切换（"视频流" / "音频流" / "合并"）
    """
    say = on_log or (lambda t: log(t))
    ffmpeg = ffmpeg or find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，请先安装（macOS: brew install ffmpeg）")

    data = client.playurl(bvid, cid, quality)
    got_quality = data.get("quality")
    accept = data.get("accept_quality") or []
    say("画质：%s (id=%s)  可选：%s" %
        (QN_NAME.get(got_quality, str(got_quality)), got_quality,
         ",".join(str(q) for q in accept)))
    if got_quality and got_quality < 80 and not client.has_login:   # 低于 1080P
        say('提示：未登录时 B 站会限制画质（当前只给到 %s）。'
            '图形界面右上角「扫码登录」可解锁 1080P 及以上；'
            '命令行加 -c "SESSDATA=..." 也行。' % QN_NAME.get(got_quality, str(got_quality)))

    stem = sanitize(name)
    ext = ".m4a" if audio_only else ".mp4"
    out = os.path.join(out_dir, stem + ext)
    if os.path.exists(out) and not force:
        say("已存在，跳过：%s" % os.path.basename(out))
        return out

    dash = data.get("dash")
    os.makedirs(out_dir, exist_ok=True)
    tmpdir = os.path.join(out_dir, ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    afile = os.path.join(tmpdir, stem + ".a.m4s")

    # ---- 老接口：单文件 durl，直接下 ----
    if not dash:
        durl = (data.get("durl") or [{}])[0].get("url")
        if not durl:
            raise RuntimeError("没有取到播放地址")
        if on_stage:
            on_stage("下载")
        client.download(durl, out, threads=threads, cdn=cdn, on_progress=on_progress,
                        should_stop=should_stop)
        return out

    vstream = pick_video(dash, got_quality)
    astream = pick_audio(dash, got_quality)

    # ---- 只下音频 ----
    if audio_only:
        if not astream:
            raise RuntimeError("该视频没有音频流")
        if on_stage:
            on_stage("音频流")
        say("下载音频流")
        client.download(media_url(astream), afile, referer="https://www.bilibili.com/",
                        threads=threads, cdn=cdn, on_progress=on_progress,
                        should_stop=should_stop)
        if on_stage:
            on_stage("转封装")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", afile, "-c", "copy", out], check=True)
        os.remove(afile)
        try:
            os.rmdir(tmpdir)       # 临时目录空了就删掉，别在下载目录里留个 .tmp
        except OSError:
            pass
        return out

    if not vstream:
        raise RuntimeError("没有取到视频流")

    # ---- 视频流 + 音频流：并行下 ----
    # 串行的话总耗时 = 视频 + 音频（音频虽然小，但也占一整段时间）；
    # 并行之后总耗时 ≈ max(两者)，能省 15~20%。
    # 进度改成"两条流合起来算"，界面上的百分比才是连续往前的。
    vfile = os.path.join(tmpdir, stem + ".v.m4s")
    prog_lock = threading.Lock()
    pstate = {"v_done": 0, "v_total": 0, "a_done": 0, "a_total": 0}

    def _make_cb(key):
        def cb(done, total):
            with prog_lock:
                pstate[key + "_done"] = done
                pstate[key + "_total"] = total
                t = pstate["v_total"] + pstate["a_total"]
                d = pstate["v_done"] + pstate["a_done"]
            if on_progress and t:
                on_progress(d, t)
        return cb

    def _dl_v():
        if on_stage:
            on_stage("视频流")
        say("下载视频流 (%sx%s)" % (vstream.get("width"), vstream.get("height")))
        client.download(media_url(vstream), vfile, referer="https://www.bilibili.com/",
                        threads=threads, cdn=cdn, on_progress=_make_cb("v"),
                        should_stop=should_stop)

    def _dl_a():
        if on_stage:
            on_stage("音频流")
        say("下载音频流")
        client.download(media_url(astream), afile, referer="https://www.bilibili.com/",
                        threads=threads, cdn=cdn, on_progress=_make_cb("a"),
                        should_stop=should_stop)

    def _run(fn, box):
        """在线程里跑 fn，出错记下来（线程里的异常不会自己冒泡出去）。"""
        try:
            fn()
        except BaseException as e:      # noqa: BLE001 - Cancelled 也要接住
            box.append(e)

    if astream:
        box_v, box_a = [], []
        t_v = threading.Thread(target=_run, args=(_dl_v, box_v), name="dl-video", daemon=True)
        t_a = threading.Thread(target=_run, args=(_dl_a, box_a), name="dl-audio", daemon=True)
        t_v.start()
        t_a.start()
        t_v.join()
        t_a.join()
        # 取消优先抛（先取消再报网络错误没意义）
        for e in box_v + box_a:
            if isinstance(e, Cancelled):
                raise e
        if box_v:
            raise box_v[0]
        if box_a:
            raise box_a[0]
        if on_stage:
            on_stage("合并")
        say("合并 -> %s" % os.path.basename(out))
        merge(vfile, afile, out, ffmpeg=ffmpeg)
        os.remove(vfile)
        os.remove(afile)
    else:
        _dl_v()
        if on_stage:
            on_stage("转封装")
        say("该视频没有独立音频流，直接转封装")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", vfile, "-c", "copy", out], check=True)
        os.remove(vfile)
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    return out


def plan_jobs(client, info, all_episodes=False, page=0):
    """根据解析结果决定要下哪几集，返回 [(集名, bvid, cid)]。

    番剧链接默认只下该集；普通多 P 视频默认全下。命令行和界面共用这段逻辑。
    """
    jobs = []
    season = info["episodes"]
    if all_episodes and season:
        st = info.get("season_title") or info["title"]
        for i, ep in enumerate(season, 1):
            jobs.append(("%s E%02d %s" % (st, i, ep["long_title"] or ep["title"]),
                         ep["bvid"], ep["cid"]))
    elif page and page > 0:
        if season:                            # 番剧：第 N 集
            if page > len(season):
                raise ValueError("--page %d 超出范围（本季共 %d 集）" % (page, len(season)))
            ep = season[page - 1]
            jobs.append(("%s E%02d %s" % (info.get("season_title") or info["title"],
                                          page, ep["long_title"] or ep["title"]),
                         ep["bvid"], ep["cid"]))
        else:                                # 普通视频：第 N 个分P
            pages = client.pagelist(info["bvid"])
            if page > len(pages):
                raise ValueError("--page %d 超出范围（共 %d 个分P）" % (page, len(pages)))
            p = pages[page - 1]
            jobs.append((p["part"], info["bvid"], p["cid"]))
    elif season:                             # 番剧链接：只下这一集
        jobs.append((info["title"], info["bvid"], info["cid"]))
    elif info["pages"]:                      # 普通多P视频：全下
        for p in info["pages"]:
            jobs.append((p.get("part") or "P%s" % p.get("page"), info["bvid"], p["cid"]))
    else:
        jobs.append((info["title"], info["bvid"], info["cid"]))
    return jobs


def load_cookie(args):
    """从 --cookie / --cookie-file 读取 Cookie 串。"""
    if args.cookie_file:
        with open(args.cookie_file, "r", encoding="utf-8") as fp:
            text = fp.read().strip()
        # 兼容 Netscape cookies.txt：只取 SESSDATA / bili_jct / DedeUserID / buvid3 等
        pairs = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7:
                pairs.append("%s=%s" % (fields[5], fields[6]))
        return "; ".join(pairs) if pairs else text
    return args.cookie or ""


def main():
    ap = argparse.ArgumentParser(
        description="B 站视频下载器（macOS / Linux）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 bilifetch.py 'https://www.bilibili.com/bangumi/play/ep1633643'\n"
               "  python3 bilifetch.py BV1bSJez1Et8 -q 80 -o ~/Videos\n"
               "  python3 bilifetch.py 'https://www.bilibili.com/bangumi/play/ep1633643' --list")
    ap.add_argument("url", help="B 站链接或 ID（av/bv/ep/ss/b23.tv）")
    ap.add_argument("-V", "--version", action="version", version="bilifetch " + VERSION)
    ap.add_argument("-o", "--out", default="downloads", help="输出目录（默认 ./downloads）")
    ap.add_argument("-q", "--quality", type=int, default=0,
                    help="画质 id：127/126/125/120/116/112/80/74/64/32/16，0=最高可得")
    ap.add_argument("-p", "--page", type=int, default=0,
                    help="只下第几集（从 1 开始）；番剧链接默认只下该集")
    ap.add_argument("--all-episodes", action="store_true", help="番剧：下载整季所有集")
    ap.add_argument("-a", "--audio-only", action="store_true", help="只下音频")
    ap.add_argument("-c", "--cookie", default="", help="Cookie 串，例如 'SESSDATA=xxx; bili_jct=xxx'")
    ap.add_argument("--cookie-file", default="", help="Cookie 文件（浏览器导出的 cookies.txt 或纯文本）")
    ap.add_argument("--proxy", default="", help="代理，例如 http://127.0.0.1:7890（默认直连）")
    ap.add_argument("-t", "--threads", type=int, default=16,
                    help="分段下载的并发数，默认 16（1-32）")
    ap.add_argument("--cdn", default="", help="指定 CDN 镜像，如 upos-sz-mirrorhw.bilivideo.com")
    ap.add_argument("--force", action="store_true", help="已存在的文件也重新下载")
    ap.add_argument("--list", action="store_true", dest="list_q", help="只列出可用画质，不下载")
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印信息，不下载")
    args = ap.parse_args()

    client = BiliClient(cookie=load_cookie(args), proxy=args.proxy or None)

    # ---------- 解析链接 ----------
    log("解析链接：%s" % args.url)
    # 合集 / 列表 / 收藏夹：先列出来（图形界面里可以逐个勾选）
    try:
        import bilifetch_collection as collection_mod
    except ImportError:
        collection_mod = None
    if collection_mod and collection_mod.detect_collection(args.url):
        info = collection_mod.fetch_collection(client, args.url)
        if not info or not info.get("items"):
            log("这个%s里没有可下载的视频" % info.get("kind_label", "合集"))
            return 1
        main_items = [it for it in info["items"] if not it.get("extra")]
        extra = [it for it in info["items"] if it.get("extra")]
        log("  %s：%s（%d 集）" % (info["kind_label"], info["title"], len(main_items)))
        for i, it in enumerate(main_items, 1):
            log("   %3d. %s %8s  %s" % (i,
                     collection_mod.pad_display(it["title"][:40], 56),
                     collection_mod.format_duration(it["duration"]),
                     collection_mod.format_views(it["view"]) + " 播放"))
        if extra:
            log("   另有 %d 个花絮/二创分区（图形界面里可展开）" % len(extra))
        log("")
        log("这是%s，命令行只能整份下载。" % info["kind_label"])
        log("想挑着下，请用图形界面：BiliFetch.app（macOS）或 bilifetch-gui（Linux）。")
        return 0
    info = client.resolve(args.url)
    log("  标题：%s" % info["title"])
    log("  UP主：%s   时长：%d 秒" % (info["owner"], info["duration"]))

    # ---------- 决定要下哪几集 ----------
    try:
        jobs = plan_jobs(client, info, all_episodes=args.all_episodes, page=args.page)
    except ValueError as e:
        raise SystemExit(str(e))

    log("  待下载：%d 集" % len(jobs))

    # ---------- 逐集下载 ----------
    ffmpeg = find_executable("ffmpeg")
    if not (args.list_q or args.dry_run) and not ffmpeg:
        log("错误：找不到 ffmpeg。"
            "  macOS : brew install ffmpeg"
            "  Debian: sudo apt install ffmpeg")
        return 1
    if ffmpeg:
        log("ffmpeg：%s" % ffmpeg)
    os.makedirs(args.out, exist_ok=True)
    for idx, (name, bvid, cid) in enumerate(jobs, 1):
        log("")
        log("[%d/%d] %s" % (idx, len(jobs), name))
        try:
            if args.list_q or args.dry_run:
                data = client.playurl(bvid, cid, args.quality)
                quality = data.get("quality")
                accept = data.get("accept_quality") or []
                log("  实际画质：%s (id=%s)  可选：%s" %
                    (QN_NAME.get(quality, str(quality)), quality,
                     ",".join(str(q) for q in accept)))
                if args.dry_run:
                    dash = data.get("dash")
                    if dash:
                        v = pick_video(dash, quality)
                        a = pick_audio(dash, quality)
                        log("  视频流：%sx%s codecid=%s" %
                            (v.get("width"), v.get("height"), v.get("codecid")))
                        log("  音频流：id=%s" % (a or {}).get("id"))
                continue
            out = download_episode(client, bvid, cid, name, args.out,
                                   quality=args.quality, threads=args.threads,
                                   cdn=args.cdn, audio_only=args.audio_only,
                                   force=args.force, ffmpeg=ffmpeg)
            log("  -> %s" % out)
        except Exception as e:
            log("  失败：%s" % e)


    log("\n完成。输出目录：%s" % os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已中断。")
        sys.exit(130)
