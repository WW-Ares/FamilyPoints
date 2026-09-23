# -*- coding: utf-8 -*-
"""把打好的包解压到临时目录跑一遍，确认它在「只有这个包」的条件下能起来。

tools/check_docker_copy.py 管的是「Dockerfile 声明了哪些文件」，
这个脚本管的是「包里的文件真的够不够」。两者查的不是一回事：
COPY 清单可以是对的，但打包脚本漏带了某个文件；也可以反过来。

它会做的事：解压最新那个包 → 用一个空的临时数据目录起服务 → 请求
/api/bootstrap 和几个静态资源 → 走一遍首次设置 → 确认数据库落到指定位
置。本机没有 docker，所以这里不验镜像本身，只验包。

用法：python tools/check_pack.py    （退出码非 0 表示这个包不能用）
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
WORK = APP / ".tmp" / "pkgtest"
PORT = 8097
BASE = "http://127.0.0.1:%d" % PORT


def get(path, raw=False):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        body = r.read()
        return r.status, (body if raw else json.loads(body.decode("utf-8")))


def port_busy(port):
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pack_key(p):
    """按「日期 + 版本号」排，不能按文件名字符串排。
       v1.10 一出来就踩到了：字符串序里 `v1.10` 排在 `v1.8` / `v1.9` **前面**
       （'1' < '8' < '9'），原来那句 `sorted(...)[-1]` 于是拿的是上一版的包，
       验得一路绿灯，验的却是旧代码。v1.10 实测就是这么被骗过一次：
       包里的 seed_data 已经是 1.10，这里却报「版本 1.9」。"""
    m = re.search(r"family-points-v(\d+)\.(\d+)-(\d{8})\.tar\.gz$", p.name)
    return (m.group(3), int(m.group(1)), int(m.group(2))) if m else ("", 0, 0)


def main():
    packs = sorted((APP / "dist").glob("family-points-*.tar.gz"), key=_pack_key)
    if not packs:
        print("dist/ 下没有包，先跑 python tools/pack_release.py")
        return 1
    pkg_file = packs[-1]

    if port_busy(PORT):
        print("端口 %d 上已经有东西在监听，先腾出来" % PORT)
        return 1

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    with tarfile.open(pkg_file) as tf:
        tf.extractall(WORK, filter="data")
    pkg = WORK / "family-points"
    print("包：%s" % pkg_file.name)
    print("解压到 %s" % pkg)

    env = dict(os.environ)
    env.update({
        "FAMILY_DATA_DIR": str(WORK / "data"),
        "FAMILY_PORT": str(PORT),
        "FAMILY_QUIET": "1",
        "PYTHONUNBUFFERED": "1",
    })
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=str(pkg), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    fails = []
    try:
        up = False
        for _ in range(60):
            time.sleep(0.25)
            try:
                get("/api/bootstrap")
                up = True
                break
            except Exception:
                if proc.poll() is not None:
                    break
        if not up:
            print("起不来，进程输出：")
            print(proc.stdout.read())
            return 1

        _, boot = get("/api/bootstrap")
        print("  /api/bootstrap           200")
        print("       需要首次设置：%s" % boot.get("needs_setup"))
        print("       成员 %s 位，版本 %s"
              % (len(boot.get("members") or []), boot.get("version")))
        for p in ["/", "/index.html", "/app.js", "/style.css",
                  "/avatars/dad_1.svg", "/avatars.js", "/icons.js"]:
            try:
                c, _ = get(p, raw=True)
                if c != 200:
                    fails.append("%s 返回 %s" % (p, c))
            except Exception as e:
                fails.append("%s 请求失败：%s" % (p, e))
        print("  静态资源 7 项 %s" % ("全部 200" if not fails else "有问题"))

        if boot.get("needs_setup"):
            body = json.dumps({"username": "爸爸", "password": "pack-check-1234"}).encode()
            rq = urllib.request.Request(BASE + "/api/setup/admin", data=body,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=5) as r:
                print("  POST /api/setup/admin   %s" % r.status)
            _, boot2 = get("/api/bootstrap")
            if boot2.get("needs_setup"):
                fails.append("首次设置之后 needs_setup 还是 true")
            else:
                print("  设置完这扇门已关闭")

        db = WORK / "data" / "family.db"
        print("  数据库 %s" % ("已生成" if db.is_file() else "没生成"))
        if not db.is_file():
            fails.append("数据库没建出来")

        if fails:
            print("")
            for f in fails:
                print("  ✗ %s" % f)
            return 1
        print("")
        print("包能跑：解压即起，库建得出来，首次设置这扇门也开得对。")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
