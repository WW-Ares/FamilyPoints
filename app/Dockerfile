# 家庭积分 · 单容器镜像
#
# 零第三方依赖：整个服务只用 Python 标准库（http.server + sqlite3 + json），
# 所以这里没有 pip install，镜像小、构建快、断网也能构建，也不存在依赖版本哪天突然崩掉的问题。

FROM python:3.13-alpine

# 时区：容器默认 UTC，会让「今天」错 8 小时，打分日期就全乱了
RUN apk add --no-cache tzdata \
 && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && echo "Asia/Shanghai" > /etc/timezone

WORKDIR /srv

COPY server.py db.py engine.py notify.py schema.sql seed_data.py ./
COPY api ./api
COPY web ./web

# 数据库、快照都放在这里，挂载出来就不会随容器重建而丢失
ENV FAMILY_DATA_DIR=/data \
    FAMILY_PORT=3637 \
    FAMILY_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/data"]
EXPOSE 3637

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('FAMILY_PORT','8080')+'/api/bootstrap',timeout=4).read()"

CMD ["python", "server.py"]
