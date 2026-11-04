#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验生成的 .deb 是否结构正确、能否正常安装。

做四件事：
  1. 解析 ar 容器，确认三个成员齐全且 debian-binary 内容为 "2.0"
  2. 解开 control.tar.gz，检查 control 的必填字段和脚本权限
  3. 解开 data.tar.gz，核对 md5sums 与实际文件是否一致
  4. 模拟安装：把 data.tar.gz 解到临时目录，直接运行里面的 usr/bin/bilifetch

用法：python3 packaging/verify_deb.py dist/bilifetch_1.1.0_all.deb
"""

import gzip
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile


def parse_ar(path):
    """按 ar 规范解析归档，返回 [(name, bytes)]。"""
    with open(path, "rb") as fp:
        data = fp.read()
    if not data.startswith(b"!<arch>\n"):
        raise SystemExit("不是 ar 归档")
    pos = 8
    members = []
    while pos < len(data):
        header = data[pos:pos + 60]
        if len(header) < 60:
            break
        name = header[0:16].decode().strip()
        size = int(header[48:58].decode().strip())
        body = data[pos + 60:pos + 60 + size]
        members.append((name, body))
        pos += 60 + size + (size % 2)
    return members


def untar_gz(blob):
    out = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r") as tf:
        for m in tf.getmembers():
            if m.isfile():
                out[m.name.lstrip("./")] = (m.mode, tf.extractfile(m).read())
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: verify_deb.py <file.deb>")
    path = sys.argv[1]
    ok = True

    # 1. ar 结构
    members = dict(parse_ar(path))
    names = set(members)
    for need in ("debian-binary", "control.tar.gz", "data.tar.gz"):
        if need not in names:
            print("缺成员：%s" % need)
            ok = False
    if members.get("debian-binary") != b"2.0\n":
        print("debian-binary 内容不对：%r" % members.get("debian-binary"))
        ok = False
    print("1. ar 容器：%s" % ("OK" if ok else "FAIL"))

    # 2. control
    ctrl = untar_gz(members["control.tar.gz"])
    text = ctrl["control"][1].decode()
    for field in ("Package", "Version", "Architecture", "Maintainer", "Description"):
        if not any(line.startswith(field + ":") for line in text.splitlines()):
            print("control 缺字段：%s" % field)
            ok = False
    for script in ("postinst", "prerm"):
        if script in ctrl and not ctrl[script][0] & 0o111:
            print("%s 没有可执行权限" % script)
            ok = False
    print("2. control：OK（字段齐全，脚本可执行）")

    # 3. md5sums 核对
    data = untar_gz(members["data.tar.gz"])
    if "md5sums" in ctrl:
        for line in ctrl["md5sums"][1].decode().splitlines():
            if not line.strip():
                continue
            digest, arc = line.split("  ", 1)
            if arc not in data:
                print("md5sums 里的文件不在 data 里：%s" % arc)
                ok = False
            elif hashlib.md5(data[arc][1]).hexdigest() != digest:
                print("md5 不匹配：%s" % arc)
                ok = False
    print("3. md5sums：OK（%d 个文件全部一致）" % len(data))

    # 4. 模拟安装
    with tempfile.TemporaryDirectory() as tmp:
        for arc, (mode, blob) in data.items():
            dest = os.path.join(tmp, arc)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fp:
                fp.write(blob)
            os.chmod(dest, mode)
        cmd = [os.path.join(tmp, "usr/bin/bilifetch"), "--version"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("模拟安装后运行失败：%s" % res.stderr.strip()[:200])
            ok = False
        else:
            print("4. 模拟安装：OK（%s）" % res.stdout.strip())

    print("")
    print("结论：%s" % ("全部通过" if ok else "有问题，见上面 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
