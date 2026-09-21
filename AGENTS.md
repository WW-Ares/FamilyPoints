# 项目规则

这个仓库的两条硬规则，动手前先看，收工前照做。

## 一、每次更新版本，就提交 git

- 动了版本号、改了功能、修了 bug，收工前必须 `git commit`。不许把一堆改动丢在工作区过夜。
- 提交说明只允许两个词：首次提交 `Initial commit`，之后一律 `Update`。不写 `feat:` / `fix:` / `docs:`，不写中文描述，不写正文段落。
- 更新内容写 GitHub Releases（`gh release create/edit --notes-file`），不写进 commit message。
- 发新版本走完整链路：改代码 → 提交（`Update`）→ 推送 → 写 Releases。打了标签的版本，标签一起推。
- 推送不上去不算完事，要说清卡在哪一步、还差什么。
- 在里程碑点打标签。当前版本号 `v1.2`（对外第一版），此前的 `v3`–`v39` 内部编号已作废，只作沿革留在 `旧版历史备份/`。

## 二、每次更新版本、更新功能，必须自查 + 测试跑通

改完后端、前端、配置、文档，跑通下面这些才算完成。不许「看着没问题」就交差。

1. 前端改了就查语法：`node --check app/web/app.js`
2. 通用自检：`python app/tools/check_undef.py`。改过掩码类逻辑，顺手插个假名验证它真能报出来。
3. 后端改了就跑测试：`python app/smoke_test.py`、`python app/api_test.py`，库落在 `app/data/test`。
4. 端到端：`FAMILY_BASE=http://127.0.0.1:8090 node app/tools/e2e_v13.js`，0 报错才算过。
   不带 `FAMILY_BASE` 会打到 8080 正式库，禁止。
5. 改过开发文档里的规则文本或版本状态：`python app/tools/verify_devdoc.py` 必须全项通过。
6. 要发版、要部署：`app/tools/check_docker_copy.py` → `pack_release.py` → `check_pack.py`，三件套一个不落。
7. 改过版本号：库结构版本看 `seed_data.SCHEMA_VERSION`（改它等于宣告库结构变了，要配套写 `_migrate_vNN`，并对每个在用库跑一次 `db.init_db()`）；对外版本号看 `seed_data.APP_VERSION`（页脚与打包名认它）。两个别混。

自查和测试的结果要写进汇报：跑了哪些命令、什么结果、哪些没跑、为什么没跑。

## 三、跑测试时不许碰的库

- `app/data/` 下的正式库（8080）不许当靶子，不许替用户改密码。
- 演示库（8090）、空库（8099）、测试库（`app/data/test`）可随意使用，用完不删。
- `app/data/`、`nas原数据/` 不入库；拷库要连 `-wal` / `-shm` 一起，或用 `snapshots/*.db`。
