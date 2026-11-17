# -*- coding: utf-8 -*-
"""
HTTP 服务入口。

只用标准库：http.server + sqlite3 + json。没有第三方依赖，Docker 镜像里不用 pip install。
启动：python server.py  （默认监听 0.0.0.0:8080）
"""
import json
import os
import secrets
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import hashlib
import engine as E
import notify
import api
from api import ApiError
from api.auth import resolve_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
MAX_BODY = 1000000

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "FamilyPoints/1.0"
    protocol_version = "HTTP/1.1"
    sys_version = ""

    # --- 日志 ---------------------------------------------------------------
    def log_message(self, fmt, *args):
        if os.environ.get("FAMILY_QUIET"):
            return
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # --- 响应 ---------------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:;"
                         " style-src 'self' 'unsafe-inline';"
                         " script-src 'self' 'unsafe-inline';"
                         " connect-src 'self'; manifest-src 'self';"
                         " base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200, set_cookie=None, headers=None):
        h = dict(headers or {})
        if set_cookie:
            h["Set-Cookie"] = set_cookie
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str), headers=h)

    # --- 入口 ---------------------------------------------------------------
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_HEAD(self):
        self._handle("GET")

    def _token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("fam_token="):
                return part[len("fam_token="):]
        # 也支持 Authorization: Bearer，方便脚本调用
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def _handle(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = {}
        for k, v in urllib.parse.parse_qs(parsed.query).items():
            query[k] = v[0]
        try:
            if path.startswith("/api/"):
                return self._api(method, path, query)
            return self._static(path)
        except Exception:
            rid = secrets.token_hex(6)
            traceback.print_exc()
            print("request_id=%s" % rid)
            try:
                self._json({"error": "服务器内部错误", "request_id": rid}, 500)
            except Exception:
                pass

    # --- API ---------------------------------------------------------------
    def _api(self, method, path, query):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return self._json({"error": "请求头不对"}, 400)
        if length < 0:
            return self._json({"error": "请求头不对"}, 400)
        if length > MAX_BODY:
            return self._json({"error": "请求体太大"}, 413,
                              headers={"Connection": "close"})
        body = {}
        if length:
            raw = self.rfile.read(length)
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return self._json({"error": "请求体不是合法 JSON"}, 400)
        if not isinstance(body, dict):
            body = {"value": body}

        token = self._token()
        member = resolve_session(token)
        ctx = api.Ctx(member, query, body, raw=self, token=token)
        try:
            result = api.dispatch(method, path, ctx)
        except ApiError as e:
            return self._json({"error": e.message}, e.status, headers=e.headers)
        except Exception:
            rid = secrets.token_hex(6)
            traceback.print_exc()
            print("request_id=%s" % rid)
            return self._json({"error": "服务器内部错误", "request_id": rid}, 500)
        if result is None:
            return
        cookie = None
        if isinstance(result, dict):
            cookie = result.pop("_set_cookie", None)
        return self._json(result, 200, set_cookie=cookie)

    # --- 静态文件 -----------------------------------------------------------
    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        try:
            web = os.path.realpath(WEB_DIR)
            full = os.path.realpath(os.path.join(web, path.lstrip("/")))
            if os.path.commonpath([web, full]) != web:
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
        except (ValueError, OSError):
            return self._send(403, "forbidden", "text/plain; charset=utf-8")
        if not os.path.isfile(full):
            # 单页应用，未命中的路径都回到首页
            full = os.path.join(WEB_DIR, "index.html")
            if not os.path.isfile(full):
                return self._send(404, "还没放前端文件", "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        # 内容指纹。有了它，下面那些 no-cache 的资源才能回 304 而不是每趟整份重下。
        etag = '"%s-%s"' % (len(data), hashlib.md5(data).hexdigest()[:16])
        if self.headers.get("If-None-Match") == etag:
            return self._send(304, b"", ctype, headers={"ETag": etag, "Cache-Control": "no-cache"})
        # 缓存分三档。图标和清单被系统/桌面按「快照」缓存：iOS 加到主屏幕那一刻
        # 就拍下图标，安卓装桌面时同样，之后换文件内容它们不会回来问，只有 URL
        # 变了才更新。所以这两类必须可随时校验（no-cache + ETag），不能压 24 小时；
        # 换图标时再给 URL 加版本号（index.html 与 site.webmanifest 里的 ?v=）。
        if ext in (".html", ".js", ".css", ".webmanifest", ".json", ".png", ".ico"):
            cache = "no-cache"
        elif ext in (".svg", ".jpg", ".jpeg", ".webp", ".gif"):
            cache = "public, max-age=3600"
        else:
            cache = "public, max-age=86400"
        return self._send(200, data, ctype, headers={"ETag": etag, "Cache-Control": cache})


def main():
    port = int(os.environ.get("FAMILY_PORT", "8080"))
    host = os.environ.get("FAMILY_HOST", "0.0.0.0")
    db.init_db(verbose=True)
    n = api.load()
    # 首次设置的一次性安装码。只在「一个密码都没设」的库上生成一次。
    try:
        api.auth.ensure_setup_token()
    except Exception:
        traceback.print_exc()
    # 推送线程。放在 init_db 之后：它一起来就会去查 notification 表和设置，
    # 表还没建出来的话第一轮必然报错。
    notify.start()
    try:
        db.snapshot(int(db.cfg("ops.snapshot_keep_days", 30)))
    except Exception as e:
        print("快照失败（不影响使用）：", e)
    print("路由 %d 条" % n)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print("家庭积分已启动：http://%s:%d" % ("127.0.0.1" if host == "0.0.0.0" else host, port))
    print("数据文件：%s" % db.DB_PATH)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
