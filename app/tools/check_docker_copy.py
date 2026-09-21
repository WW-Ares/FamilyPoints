# -*- coding: utf-8 -*-
"""部署前的自检：镜像里该有的东西，Dockerfile 是不是都 COPY 了。

为什么要专门写这个。这个服务在容器里没有 pip，靠的就是那几个 .py 文件本身。
本地 `python server.py` 永远跑得通（文件都在磁盘上），但只要 Dockerfile 漏掉一个
COPY，镜像起来就是 ModuleNotFoundError，而且是「构建成功、启动即崩」，
不看容器日志根本不知道哪一步错了。

这个坑真踩过：Dockerfile 里一度只有 `server.py db.py engine.py schema.sql seed_data.py`，
`notify.py` 没进镜像，而 server / engine / api.push 三个地方都在 import 它。

顺带查另外两件在 NAS 上很容易出事的事：
  - Dockerfile 的 EXPOSE / FAMILY_PORT 和 docker-compose.yml 的端口映射是不是对得上；
    这两处是手写的，README 里明确说了「改的时候要一起改」。
  - 文本文件有没有 CRLF。Windows 上编辑过的 Dockerfile 带 \\r，老的 docker build
    会把 \\r 当成值的一部分，`ENV FAMILY_PORT=3637` 就变成 "3637\\r"，启动时 int() 直接炸。

用法：python tools/check_docker_copy.py   （退出码非 0 表示有问题）
"""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DOCKERFILE = APP / "Dockerfile"
COMPOSE = APP / "docker-compose.yml"

# 入口文件自己也得进镜像
ENTRY = "server.py"

TEXT_SUFFIX = {".py", ".yml", ".yaml", ".md", ".sql", ".js", ".css",
               ".html", ".json", ".svg", ".txt"}
TEXT_NAMES = {"Dockerfile", ".dockerignore"}

_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+([A-Za-z_][\w.]*)|from\s+([A-Za-z_][\w.]*)\s+import)", re.M)

problems = []
notes = []


# ---------------------------------------------------------------------------
# 一、Dockerfile 的 COPY 覆盖了哪些文件
# ---------------------------------------------------------------------------
def copy_sources(text):
    """取出所有 COPY 的源路径（最后一个参数是目标，不算源）。"""
    srcs, literal = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not re.match(r"^COPY\s", s, re.I):
            continue
        parts = [p for p in s.split() if not p.startswith("--")]
        args = parts[1:]
        if len(args) < 2:
            problems.append("Dockerfile 有一行 COPY 参数不完整：%s" % s)
            continue
        srcs.extend(args[:-1])
        literal.append(s)
    return srcs, literal


def covered_files(srcs):
    """把 COPY 的源展开成「相对 app/ 的文件路径」集合。"""
    covered = set()
    for s in srcs:
        p = APP / s
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    covered.add(f.relative_to(APP).as_posix())
        elif p.is_file():
            covered.add(Path(s).as_posix())
        else:
            problems.append("Dockerfile 里写了 %s，但 app/ 下没有这个东西" % s)
    return covered


# ---------------------------------------------------------------------------
# 二、代码实际 import 了哪些本地模块
# ---------------------------------------------------------------------------
def runtime_python_files():
    """会被打进镜像的 .py。测试文件不算——它们不进容器。"""
    out = []
    for f in sorted(APP.glob("*.py")):
        if f.name.endswith("_test.py") or f.name == "smoke_test.py":
            continue
        out.append(f)
    for f in sorted((APP / "api").glob("*.py")):
        out.append(f)
    return out


def local_modules(files):
    """这些文件 import 的、确实属于本项目的模块名。"""
    stdlib = getattr(sys, "stdlib_module_names", set())
    names = set()
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in _IMPORT_RE.finditer(text):
            top = (m.group(1) or m.group(2)).split(".")[0]
            if top in stdlib:
                continue
            if (APP / (top + ".py")).is_file() or (APP / top / "__init__.py").is_file():
                names.add(top)
    return names


# ---------------------------------------------------------------------------
# 三、端口 / 换行
# ---------------------------------------------------------------------------
def check_ports(df_text, compose_text):
    m = re.search(r"^ENV\s+(.*)$", df_text, re.M)
    env_port = None
    for mm in re.finditer(r"FAMILY_PORT=(\S+)", df_text):
        env_port = mm.group(1).strip()
    exp = re.search(r"^EXPOSE\s+(\d+)", df_text, re.M)
    expose = exp.group(1) if exp else None

    maps = re.findall(r'-\s*"(\d+):(\d+)"', compose_text)
    if not maps:
        problems.append("docker-compose.yml 里找不到形如 \"3637:3637\" 的端口映射")
        return
    host_port, container_port = maps[0]

    if expose and expose != container_port:
        problems.append("Dockerfile EXPOSE %s，compose 映射到容器 %s，对不上"
                        % (expose, container_port))
    if env_port and env_port != container_port:
        problems.append("Dockerfile ENV FAMILY_PORT=%s，compose 映射到容器 %s，对不上"
                        % (env_port, container_port))
    if host_port == "":
        problems.append("compose 的宿主端口是空的")
    notes.append("端口：宿主 %s → 容器 %s" % (host_port, container_port))


def check_crlf():
    for name in ["Dockerfile", "docker-compose.yml", ".dockerignore"]:
        p = APP / name
        if not p.is_file():
            continue
        raw = p.read_bytes()
        n = raw.count(b"\r\n")
        if n:
            problems.append("%s 有 %d 处 CRLF。打包脚本会自动转成 LF，"
                            "但如果直接把这几个文件拷到 NAS 上构建，可能出问题" % (name, n))


# ---------------------------------------------------------------------------
def main():
    if not DOCKERFILE.is_file():
        print("找不到 %s" % DOCKERFILE)
        return 1
    df_text = DOCKERFILE.read_text(encoding="utf-8", errors="replace")
    compose_text = COMPOSE.read_text(encoding="utf-8", errors="replace") \
        if COMPOSE.is_file() else ""

    srcs, _ = copy_sources(df_text)
    covered = covered_files(srcs)
    print("Dockerfile 共 COPY %d 个源，展开 %d 个文件" % (len(srcs), len(covered)))

    files = runtime_python_files()
    mods = local_modules(files)
    print("代码里出现的本地模块 %d 个：%s" % (len(mods), "、".join(sorted(mods))))

    # 逐个模块核对
    missing = []
    for name in sorted(mods):
        candidates = ["%s.py" % name, "%s/__init__.py" % name]
        if not any(c in covered for c in candidates):
            missing.append(name)
    if missing:
        for name in missing:
            problems.append(
                "模块 %s 被 import，但 Dockerfile 没把它 COPY 进镜像 —— "
                "镜像一起来就会 ModuleNotFoundError" % name)

    if ENTRY not in covered:
        problems.append("入口 %s 不在 COPY 清单里" % ENTRY)

    # 静态目录：前端整站都在 web/ 下，server.py 按路径读它
    if "web/index.html" not in covered:
        problems.append("web/ 没进镜像，容器起来只有接口没有页面")
    else:
        n_web = sum(1 for c in covered if c.startswith("web/"))
        notes.append("前端静态文件 %d 个" % n_web)

    if compose_text:
        check_ports(df_text, compose_text)
    check_crlf()

    # 出结果
    print("")
    for n in notes:
        print("  · %s" % n)
    if problems:
        print("")
        for p in problems:
            print("  ✗ %s" % p)
        print("")
        print("自检没通过，先修上面这些再谈部署。")
        return 1
    print("")
    print("自检通过：镜像需要的文件齐了，端口对得上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
