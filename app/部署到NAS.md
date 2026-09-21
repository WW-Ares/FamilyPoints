# 部署到 NAS

这份说明只讲一件事：把 `app/` 搬到你 NAS 上跑起来，跑的是 Docker。

服务本身没有第三方依赖，镜像里没有 pip install，所以这一步不涉及虚拟环境、不涉及包版本。
难点只有两个：文件要传对，端口要选对。

## 一、本机先跑一遍自检

```bash
cd app
python tools/check_docker_copy.py
```

它会检查三件事：Dockerfile 的 COPY 清单有没有漏掉代码里 import 的模块、端口映射两处写的是不是一回事、
文件里有没有混进 CRLF。**必须退出码 0 再往下走。**

为什么专门查第一件：容器里没有 pip，靠的就是那几个 `.py` 文件。本地 `python server.py`
永远跑得通，因为文件都在磁盘上；Dockerfile 少 COPY 一个，镜像是「构建成功、启动即崩」，
不看容器日志根本不知道错在哪。`notify.py` 就这么漏过一次。

## 二、打一个包

```bash
python tools/pack_release.py
```

产物是 `app/dist/family-points-v<版本>-<日期>.tar.gz`，两百多 KB。

包里的文件清单不是手写的，是从 Dockerfile 的 COPY 指令里读出来的，所以不会出现
「本地加了文件、包忘了带」。打完之后脚本会把包重新打开一遍，确认 Dockerfile 和
docker-compose.yml 都在里面。

包里的文本文件统一转成了 LF。Windows 上编辑过的 Dockerfile 是 CRLF，
构建时 `ENV FAMILY_PORT=3637` 有可能变成 `"3637\r"`，容器启动时 `int()` 直接抛异常。

**不带数据库。** `app/data/` 下面躺着 demo、empty、test、probe 一堆测试库，
自动带上就是拿测试数据上生产，孩子点进去会看见别人的分数。

**搬家不是首次部署**，要连数据一起走的加个参数：

```bash
python tools/pack_release.py --db    # 额外带上 app/data/family.db
```

## 三、传到 NAS

任选一条，都是把那个 tar.gz 放上去：

- **SMB / 文件管理器拖拽**：群晖 File Station、威联通 File Station 都行。最省事，不用开 SSH。
- **scp**：`scp dist/family-points-v26-*.tar.gz 你的账号@NAS地址:/volume1/docker/`
- **Windows 共享**：NAS 上建个共享文件夹，映射成网络驱动器，直接拷。

## 四、在 NAS 上起服务

SSH 进 NAS，或者用群晖 Container Manager 的「终端机」：

```bash
mkdir -p /volume1/docker/family-points
cd /volume1/docker/family-points
tar -xzf ~/family-points-v26-*.tar.gz
cd family-points
docker compose up -d --build
```

群晖用户注意两点：

- Container Manager 的「项目」功能要求 compose 文件在项目文件夹根目录。路径直接填
  `/volume1/docker/family-points/family-points`，Compose 文件选 `docker-compose.yml`。
  走这条路的话把第四步的 `docker compose up` 换成在界面上点「构建」，或者照旧用 SSH。
- SSH 登录后执行 docker 命令一般要加 `sudo`。

**必须在 `family-points` 目录里执行。** compose 里写的是 `./data:/data` 相对路径，
换个目录执行，数据库就落到别的地方去了。

### 端口

默认是 `3637:3637`，左侧那个是 NAS 上的端口，改成没被占用的就行：

```yaml
ports:
  - "3637:3637"
```

容器里那个 3637 别动。真要改，`Dockerfile` 里的 `EXPOSE` 和 `ENV FAMILY_PORT`
和这里三处要一起改，`tools/check_docker_copy.py` 会替你盯着。

### 拉不到基础镜像

`FROM python:3.13-alpine` 要从 Docker Hub 拉，约 50MB。国内 NAS 上可能很慢或者直接失败。
两条路：

1. 在 NAS 的 Docker 设置里配镜像加速地址（群晖在「注册表」设置里有这一项）。
2. 在能联网的机器上 `docker build -t family-points:latest .` 然后
   `docker save family-points:latest -o family-points.tar`，把 tar 传到 NAS，
   `sudo docker load -i family-points.tar`。之后在 compose 文件所在目录
   `sudo docker compose up -d`（不加 `--build`，直接用加载进来的镜像）。

## 五、看它起没起来

```bash
sudo docker compose logs -f
```

正常的话会看到这些行：

```
成员 4 位
维度 7 个
宝箱 7 档
道具 23 张卡 + 6 种券
设置项新增 90 条
[通知] 后台线程已启动
路由 103 条
家庭积分已启动：http://127.0.0.1:3637
数据文件：/data/family.db
```

`数据文件` 那行确认数据落在 `/data`，也就是 NAS 上 `family-points/data/`。
如果它显示的不是这个路径，说明你不是在 `family-points` 目录里执行的 compose。

然后从电脑或手机浏览器打开 `http://NAS的局域网地址:3637`。
群晖可以在「容器」列表里看 `family-points` 那一行的状态，健康的话会显示「健康」。

镜像里带了 HEALTHCHECK，每 60 秒请求一次 `/api/bootstrap`，连续三次失败会标成不健康。
第一次构建后要等十几秒才开始探。

## 六、第一件要做的事：设管理员

第一次打开会进「首次设置」页。账号名填 `爸爸`，设一个密码。

这一步只在**全库一个设过密码的账号都没有**的时候出现，设完立刻永久关闭。
所以别在局域网以外的网络上开着不动，先把密码设了。

设完之后：

- 爸爸就是管理员，能开通其他三个人的账号、改密码、改名字。
- 妈妈、女儿、儿子的密码都是空的，登录页会提示「让管理员在家人账号里开通一下」。
  爸爸进「家人账号」给每个人设一个。
- 四个人第一次登录后各自去「我的」里挑头像。

**密码没法找回。** 管理员忘了密码只能停机改库，做法写在《规则全书》第 18 节。
设之前想清楚，或者记在密码管理器里。

## 七、手机加到主屏

这一版是移动优先的网页，没有做 PWA（没有 service worker 和 manifest），
所以是**普通网页加到主屏**，不是「安装应用」：

- iPhone：Safari 打开 → 分享 → 添加到主屏幕。
- 安卓：Chrome 打开 → 菜单 → 添加到主屏幕。

不需要 HTTPS，局域网 http 直接能用。

想把推送弄到手机上（Bark，仅 iPhone），在设置页里填 device key，具体在 README 的推送那一节。

## 八、数据在哪，怎么备份

数据库和每日快照都在容器的 `/data`，也就是 NAS 上 `family-points/data/`：

```
data/
  family.db                    主库
  family.db-wal                预写日志，跟主库一起才完整
  family.db-shm
  snapshots/family-YYYY-MM-DD.db   每天一份快照，默认留 30 天
```

备份就是**整个 `data/` 目录拷走**。别只拷 `family.db`，WAL 里可能有还没合并的事务。
要在线备份的话，`snapshots/` 里每天那份是干净的，可以直接单独取。

恢复：停掉容器，把 `data/` 换回去，再起。

```bash
cd /volume1/docker/family-points/family-points
sudo docker compose down
# 换 data 目录
sudo docker compose up -d
```

## 九、把纸上的账搬进来（星尘 / 券）

孩子手里已经在纸质账上攒了星尘和券，两条路把它搬进库。**先读下面的坑，再动手。**

### 换库文件为什么会出现「换了跟没换一样」

这个坑真踩过。数据库是 WAL 模式，`PRAGMA journal_mode=WAL` 每次连接都会执行，于是：

- **主库文件可能只是个 4096 字节的空壳**，内容全在同目录的 `family.db-wal` 里。
  实测拷回来的 `family.db` 就是 4096 字节、1 页、**一张表都没有**。
  所以「拷一份库出来」必须连 `-wal` 和 `-shm` 一起拷，或者直接用 `snapshots/` 里那份。
- **运行中换库文件会被顶回去。** 服务还开着旧库，SQLite 的页面缓存和旁边那份旧 `-wal`
  会把你的新数据盖掉，现象就是「换完一点变化都没有」。
- **换完必须确认没有旧的 `-wal` / `-shm` 留在那儿。**

### 路线 A：在容器里直接改（推荐，不用搬文件）

服务开着也能写，SQLite 自己会协调。脚本连着写两次会被拦住（同一个孩子只准结转一次）。

```bash
cd /volume1/docker/family-points/family-points    # 有 docker-compose.yml 的那层

sudo docker cp tools/carryover_in.py family-points:/srv/

cat > /tmp/结转.json <<'JSON'
{ "by": "爸爸", "note": "纸质账结转",
  "children": {
    "女儿": {"stardust": 200, "items": {"ticket_fun": 20}},
    "儿子": {"stardust": 50,  "items": {"ticket_fun": 12}} } }
JSON
sudo docker cp /tmp/结转.json family-points:/srv/结转.json

sudo docker exec family-points python /srv/carryover_in.py --show
sudo docker exec family-points python /srv/carryover_in.py --file /srv/结转.json
sudo docker exec family-points python /srv/carryover_in.py --file /srv/结转.json --apply
```

第三行不加 `--apply` 是预演，库里什么都不动。跑完刷新页面就能看到。

### 路线 B：换文件

**前提：这个库没有要留的东西。** 换库会把账号、密码、规则配置一起换掉。

1. 停容器，留底，把三个文件都清掉。

```bash
cd /volume1/docker/family-points/family-points
sudo docker compose down
sudo tar czf ~/family-data-$(date +%F).tar.gz data/          # 留底，出事能回
sudo rm -f data/family.db data/family.db-wal data/family.db-shm
```

注意是**三个一起删**，不是只覆盖 `family.db`。把新的 `family.db` 拷进 `data/`，
文件名必须还是 `family.db`。

2. 起容器，然后**自检**。这一步别跳。

```bash
sudo docker compose up -d
sudo docker exec family-points ls -l /data/
sudo docker exec family-points python -c "import sqlite3;print('ledger 行数', sqlite3.connect('/data/family.db').execute('select count(*) from ledger').fetchone()[0])"
```

`ls -l /data/` 应该看到 `family.db` 约 336 KB，而且**没有** `-wal` / `-shm`；
第二行应该打印 `ledger 行数 4`。还是 4096 字节或者 0 行，就是没换上，回第 1 步重来。

3. 打开页面，会重新出现「首次设置」，账号填 `爸爸`，密码自己设。
   设完按第六节把妈妈和两个孩子开通。

换进去那个库里的事情：

- 星尘和券都在里面，孩子登录就能看到。
- 星尘**不进「累计获得」**，等级从 Lv.1 起。升级奖励要看以后自己挣的，不追认纸上的。
- 账号密码是空的，所以会出现首次设置。这是故意的：不然换完密码会变成一个谁也不知道的值，
  你就得停机改库才能进去。

### 想把现成的库拷出来看看

别只拷 `family.db`。两个办法：

- 停容器之后，**整个 `data/` 目录拷走**（`family.db` + `family.db-wal` + `family.db-shm` 一起）。
- 或者直接拿 `data/snapshots/family-YYYY-MM-DD.db`。那是每次启动时用 SQLite 在线备份生成的，
  单文件、完整、一致，拷那个最省事（但它只反映当天启动那一刻的状态）。

## 十、常见问题

**页面打开是白的，接口有响应。**
浏览器控制台看报什么。前端的 `index.html` 里有白屏兜底，真出问题会显示提示而不是全白。

**「今天」差了一天，或者打分日期全错了。**
时区。Dockerfile 里装了 tzdata 并设成 Asia/Shanghai，compose 里也设了 `TZ`，
两处都在的情况下不会错。如果你改过 Dockerfile，把这两处加回去。

**改了代码想重新部署。**
重新打包、传上去覆盖、`sudo docker compose up -d --build`。数据在 `data/`，
不随容器重建丢失，改代码不会动数据。

**升级后界面还是旧的。**
`app.js` 和 `css` 走的是 `no-cache`，HTML 也是，一般不会。真遇到了在浏览器里强刷。

**数据库文件是 root 所有，SMB 里删不掉。**
容器以 root 跑，挂载出来的 `data/` 就是 root 的。用 SSH 加 `sudo` 处理，
或者在 compose 里加 `user: "1000:1000"`（要保证 NAS 上这个 uid 对 `data/` 有写权限）。

**容器一直重启。**
`sudo docker compose logs --tail 50` 看最后几行。启动阶段最常见的两个错：
一个是 `ModuleNotFoundError`（Dockerfile 漏 COPY），跑第一步的自检能提前发现；
一个是 `unable to open database file`（`data/` 目录没有写权限或者路径写错了）。

## 十一、日常维护

```bash
# 看状态
sudo docker compose ps

# 看日志
sudo docker compose logs --tail 100

# 停
sudo docker compose stop

# 停并删除容器（数据在 data/ 里，不会丢）
sudo docker compose down

# 重新构建并起
sudo docker compose up -d --build
```

`restart: unless-stopped` 意味着 NAS 重启后容器自己会起来，不用管。
