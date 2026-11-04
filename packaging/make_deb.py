#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Debian 包（.deb）。

macOS 上没有 dpkg-deb，所以手写 ar 容器：
.deb = ar 归档( debian-binary + control.tar.gz + data.tar.gz )

用法：
    python3 packaging/make_deb.py --payload build/deb-root \
        --control packaging/control --scripts packaging/deb-scripts \
        --output dist/bilifetch_1.1.0_all.deb
"""

import argparse
import gzip
import hashlib
import io
import os
import tarfile


def ar_member(name, data, mode=0o100644):
    """按 ar 规范拼一个成员：name(16) mtime(12) uid(6) gid(6) mode(8) size(10) magic(2)。"""
    header = "%-16s%-12d%-6d%-6d%-8o%-10d`\n" % (name, 0, 0, 0, mode, len(data))
    out = header.encode("ascii") + data
    if len(data) % 2:                      # ar 成员按偶数字节对齐
        out += b"\n"
    return out


def tar_gz(entries):
    """entries: [(arcname, mode, bytes)] -> gzip 后的 tar。"""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        for arcname, mode, data in entries:
            info = tarfile.TarInfo("./" + arcname)
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            tf.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


def collect_payload(root):
    """把 payload 目录里的文件收集成 tar 条目。

    跳过 macOS 的元数据旁挂文件（._* / .DS_Store）——它们是从 exFAT 等非 HFS 盘
    拷过来时产生的，不该进安装包。
    """
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("._") and d != ".DS_Store")
        for name in sorted(filenames):
            if name.startswith("._") or name == ".DS_Store":
                continue
            full = os.path.join(dirpath, name)
            arc = os.path.relpath(full, root)
            mode = 0o755 if os.access(full, os.X_OK) else 0o644
            with open(full, "rb") as fp:
                entries.append((arc, mode, fp.read()))
    return entries


def md5sums(entries):
    lines = []
    for arc, mode, data in entries:
        lines.append("%s  %s" % (hashlib.md5(data).hexdigest(), arc))
    return ("\n".join(lines) + "\n").encode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True, help="数据目录（里面是 usr/... 这样的树）")
    ap.add_argument("--control", required=True, help="control 文件")
    ap.add_argument("--scripts", default="", help="含 postinst / prerm 的目录")
    ap.add_argument("--output", required=True, help="输出的 .deb 路径")
    args = ap.parse_args()

    data_entries = collect_payload(args.payload)
    if not data_entries:
        raise SystemExit("payload 目录是空的：%s" % args.payload)

    with open(args.control, "rb") as fp:
        control_entries = [("control", 0o644, fp.read())]
    control_entries.append(("md5sums", 0o644, md5sums(data_entries)))
    for script in ("postinst", "prerm", "postrm"):
        path = os.path.join(args.scripts, script) if args.scripts else ""
        if path and os.path.exists(path):
            with open(path, "rb") as fp:
                control_entries.append((script, 0o755, fp.read()))

    members = [
        ("debian-binary", b"2.0\n", 0o100644),
        ("control.tar.gz", tar_gz(control_entries), 0o100644),
        ("data.tar.gz", tar_gz(data_entries), 0o100644),
    ]

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as fp:
        fp.write(b"!<arch>\n")
        for name, data, mode in members:
            fp.write(ar_member(name, data, mode))

    print("已生成：%s（%d 个文件，%.1f KB）" %
          (args.output, len(data_entries), os.path.getsize(args.output) / 1024.0))


if __name__ == "__main__":
    main()
