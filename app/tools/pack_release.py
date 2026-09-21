# -*- coding: utf-8 -*-
"""打一个可以直接丢到 NAS 上跑的压缩包。

镜像里需要什么，由 Dockerfile 的 COPY 指令说了算。这个脚本不另维护一份清单，
也不手写死哪些文件要带 —— 免得哪天加了文件、改了目录，这边的清单忘了跟，
打出来的包少东西，到了 NAS 上才发现。v25 到 v26 之间 notify.py 就是这么漏的。

两件顺带做掉的事：

1. **文本文件一律规范成 LF。** Dockerfile 和 docker-compose.yml 在 Windows 上编辑过，
   是 CRLF。构建时 Docker 的解析器不一定帮你剥掉 \\r，`ENV FAMILY_PORT=3637` 会变成
   "3637\\r"，容器启动时 int() 直接抛异常。包里的文件统一成 LF，NAS 上就不用操心。

2. **不带测试库。** app/data 下面躺着 demo / empty / test / probe 一堆测试库，
   正式部署只要一个空目录（或者你明确指定要带的那一份）。测试数据跟着上生产，
   孩子点进去看见别人的分数，这锅不好背。

用法：
    python tools/pack_release.py              # 打包，不带任何数据库
    python tools/pack_release.py --db         # 连 data/family.db 一起带（搬家场景）
    python tools/pack_release.py -o D:/共享    # 指定输出目录

产物：dist/family-points-<版本>-<日期>.tar.gz
"""
import argparse
import io
import re
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PKG_ROOT = "family-points"

TEXT_SUFFIX = {".py", ".yml", ".yaml", ".md", ".sql", ".js", ".css",
               ".html", ".json", ".svg", ".txt"}
TEXT_NAMES = {"Dockerfile", ".dockerignore"}

# 包里额外带上的文件。Dockerfile 的 COPY 里不会有它们（它们不是被 COPY 的对象，
# 而是执行 COPY 的人），但 NAS 上没有一个都构建不了。
EXTRA = ["Dockerfile", "docker-compose.yml", ".dockerignore", "README.md",
         "部署到NAS.md", "tools/carryover_in.py"]
REQUIRED = ["Dockerfile", "docker-compose.yml"]


def app_version():
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"',
                  (APP / "seed_data.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0"


def copy_sources():
    """解析 Dockerfile 的 COPY，拿到源路径列表（最后一个参数是目标）。"""
    srcs = []
    for line in (APP / "Dockerfile").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or not re.match(r"^COPY\s", s, re.I):
            continue
        parts = [p for p in s.split() if not p.startswith("--")]
        args = parts[1:]
        if len(args) >= 2:
            srcs.extend(args[:-1])
    return srcs


def collect(srcs):
    """展开成清单：[相对路径, ...]，按 Dockerfile 的书写顺序。"""
    out = []
    for s in srcs:
        p = APP / s
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    out.append(f.relative_to(APP).as_posix())
        elif p.is_file():
            out.append(Path(s).as_posix())
        else:
            print("  ! Dockerfile 写了 %s，但 app/ 下没有，跳过" % s)
    return out


def normalize(data: bytes, name: str) -> bytes:
    """文本文件转成 LF。不是文本的原样返回。"""
    is_text = Path(name).suffix in TEXT_SUFFIX or Path(name).name in TEXT_NAMES
    if is_text and b"\r\n" in data:
        return data.replace(b"\r\n", b"\n")
    return data


def add_bytes(tf, arcname, data: bytes):
    ti = tarfile.TarInfo(arcname)
    ti.size = len(data)
    ti.mtime = int(time.time())
    ti.mode = 0o644
    tf.addfile(ti, io.BytesIO(data))


def main():
    ap = argparse.ArgumentParser(description="打包家庭积分，丢给 NAS")
    ap.add_argument("--db", action="store_true",
                    help="把 app/data/family.db 一起打进包里（搬家，不是首次部署）")
    ap.add_argument("-o", "--out", default=str(APP / "dist"), help="输出目录")
    args = ap.parse_args()

    ver = app_version()
    stamp = datetime.now().strftime("%Y%m%d")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / ("family-points-v%s-%s.tar.gz" % (ver, stamp))

    names = collect(copy_sources())
    for extra in EXTRA:
        if (APP / extra).is_file() and extra not in names:
            names.append(extra)

    crlf_fixed = []
    total = 0
    with tarfile.open(target, "w:gz") as tf:
        dirs = set()
        for rel in names:
            src = APP / rel
            if not src.is_file():
                print("  ! 缺文件 %s" % rel)
                continue
            raw = src.read_bytes()
            data = normalize(raw, rel)
            if data is not raw and b"\r\n" in raw:
                crlf_fixed.append(rel)
            arc = "%s/%s" % (PKG_ROOT, rel)

            parent = str(Path(arc).parent).replace("\\", "/")
            if parent not in dirs and parent != ".":
                ti = tarfile.TarInfo(parent + "/")
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                ti.mtime = int(time.time())
                tf.addfile(ti)
                dirs.add(parent)

            add_bytes(tf, arc, data)
            total += len(data)

        # 数据库：显式点名才带，并且只带正式那一个
        if args.db:
            dbf = APP / "data" / "family.db"
            if dbf.is_file():
                ti = tarfile.TarInfo(PKG_ROOT + "/data/")
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                ti.mtime = int(time.time())
                tf.addfile(ti)
                add_bytes(tf, PKG_ROOT + "/data/family.db", dbf.read_bytes())
                print("  带上数据库 data/family.db（%.0f KB）" % (dbf.stat().st_size / 1024))
            else:
                print("  ! --db 指定了，但 app/data/family.db 不存在，包里没带")

    # 打完自己开一遍。少了 Dockerfile 的包，在 NAS 上会以
    # 「docker compose 找不到 Dockerfile」收场，这种错不该等传到 NAS 才发现。
    with tarfile.open(target) as tf:
        inside = set(tf.getnames())
    missing = [n for n in REQUIRED if "%s/%s" % (PKG_ROOT, n) not in inside]
    if missing:
        print("  ! 包里少了 %s，不能用来部署" % "、".join(missing))
        return 2

    size = target.stat().st_size
    print("")
    print("打好了：%s" % target)
    print("  版本 %s，共 %d 个文件，解压后 %.1f MB，压缩包 %.0f KB"
          % (ver, len(names), total / 1024 / 1024, size / 1024))
    if crlf_fixed:
        print("  换行符已规范成 LF：%s" % "、".join(crlf_fixed))
    print("")
    print("NAS 上：tar -xzf %s && cd %s && docker compose up -d --build"
          % (target.name, PKG_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
