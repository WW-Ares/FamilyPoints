-- 家庭积分工程 · 数据库结构
-- 规则真值以最新的《项目当前开发文档》为准（当前 schema v44），结构变更都带 _migrate_vNN 迁移。
--
-- 两条贯穿全库的约定：
--   1. 所有余额都由流水求和得出，不存冗余余额字段（项目原则 6）。
--   2. 已有记录不物理删除，只追加「作废 / 修正」流水（红线 3：不追溯已发的奖励）。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 成员
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS member (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL,
  role        TEXT    NOT NULL CHECK (role IN ('parent', 'child')),
  avatar      TEXT    NOT NULL DEFAULT '',
  birth_year  INTEGER,
  username    TEXT    NOT NULL DEFAULT '',   -- 登录账号；空 = 还没开通
  password_hash TEXT  NOT NULL DEFAULT '',   -- 空 = 还没开通，登录时会挡下来
  is_admin    INTEGER NOT NULL DEFAULT 0,    -- 全库只有一位：能开通账号、能重置任何人密码
  sort        INTEGER NOT NULL DEFAULT 0,
  active      INTEGER NOT NULL DEFAULT 1,
  parent_yield_policy TEXT NOT NULL DEFAULT 'none',  -- none(只示范) | pool(转入许愿池)
  created_at  TEXT    NOT NULL,
  archived_at TEXT
);

-- ---------------------------------------------------------------------------
-- 设置项：v12 第 14 章的整张表就是这里的初始化数据
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS setting (
  key        TEXT PRIMARY KEY,
  value      TEXT    NOT NULL,              -- JSON 编码的值
  vtype      TEXT    NOT NULL DEFAULT 'text',   -- text|int|float|bool|json|list
  grp        TEXT    NOT NULL DEFAULT '',       -- 分组，设置页按此分节
  label      TEXT    NOT NULL DEFAULT '',
  note       TEXT    NOT NULL DEFAULT '',
  sort       INTEGER NOT NULL DEFAULT 0,
  editable   INTEGER NOT NULL DEFAULT 1,
  locked     INTEGER NOT NULL DEFAULT 0,        -- 1 = 红线项，设置页只读
  updated_at TEXT
);

-- 设置变更留痕（改价格/门槛/额度/有效期需家长双人确认）
CREATE TABLE IF NOT EXISTS setting_change (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  key         TEXT    NOT NULL,
  old_value   TEXT,
  new_value   TEXT,
  actor_id    INTEGER,
  status      TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|applied
  approver_id INTEGER,
  ts          TEXT    NOT NULL,
  resolved_at TEXT
);

-- ---------------------------------------------------------------------------
-- 打分维度（七个）+ 假期版名称
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dimension (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  code         TEXT    NOT NULL UNIQUE,
  name         TEXT    NOT NULL,
  holiday_name TEXT    NOT NULL DEFAULT '',   -- 假期版改名，空=沿用
  meaning      TEXT    NOT NULL DEFAULT '',
  icon         TEXT    NOT NULL DEFAULT '',
  score        REAL    NOT NULL DEFAULT 1,
  sort         INTEGER NOT NULL DEFAULT 0,
  active       INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- 周期（每个成员各自一个周期；默认周六起，7 天）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cycle (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id       INTEGER NOT NULL REFERENCES member(id),
  start_date      TEXT    NOT NULL,
  end_date        TEXT    NOT NULL,
  fixed_score     REAL    NOT NULL DEFAULT 0,   -- 本周每日固定分合计
  bonus_energy    REAL    NOT NULL DEFAULT 0,   -- 星探 + 任务发的周能量
  energy          REAL    NOT NULL DEFAULT 0,   -- 周能量 = fixed + bonus
  countable_days  INTEGER NOT NULL DEFAULT 7,   -- 折算用：本周可计分天数（扣过渡日）
  threshold_ratio REAL    NOT NULL DEFAULT 1.0, -- 假期跨界周期的门槛折算系数
  status          TEXT    NOT NULL DEFAULT 'open',  -- open|settled
  tier_awarded    INTEGER NOT NULL DEFAULT 0,   -- 已发放的免费箱档位，0=未发
  stardust_grant  REAL    NOT NULL DEFAULT 0,   -- 本周结算入账的星尘
  settled_at      TEXT,
  UNIQUE (member_id, start_date)
);

-- ---------------------------------------------------------------------------
-- 每日打分记录（固定 7 分 + 修正窗口）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS score_entry (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id      INTEGER NOT NULL REFERENCES member(id),
  cycle_id       INTEGER REFERENCES cycle(id),
  day            TEXT    NOT NULL,               -- YYYY-MM-DD
  dimension_id   INTEGER NOT NULL REFERENCES dimension(id),
  value          REAL    NOT NULL DEFAULT 1,
  is_fixed       INTEGER NOT NULL DEFAULT 1,     -- 1=每日固定分, 0=额外
  mode           TEXT    NOT NULL DEFAULT 'school',  -- school|holiday
  note           TEXT    NOT NULL DEFAULT '',
  operator_id    INTEGER REFERENCES member(id),
  created_at     TEXT    NOT NULL,
  revised_at     TEXT,
  revision_count INTEGER NOT NULL DEFAULT 0,
  voided         INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_score ON score_entry (member_id, day, dimension_id) WHERE voided = 0;
CREATE INDEX IF NOT EXISTS ix_score_day ON score_entry (member_id, day);
CREATE INDEX IF NOT EXISTS ix_score_cycle ON score_entry (member_id, cycle_id, voided);
CREATE INDEX IF NOT EXISTS ix_cycle_member ON cycle (member_id, status, start_date);

-- 修正审计（超过 3 次在家长侧打标记）
CREATE TABLE IF NOT EXISTS correction (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT    NOT NULL,
  target_id   INTEGER NOT NULL,
  before_json TEXT    NOT NULL DEFAULT '',
  after_json  TEXT    NOT NULL DEFAULT '',
  actor_id    INTEGER,
  ts          TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 流水：一切数值变动的唯一真值源
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id      INTEGER NOT NULL REFERENCES member(id),
  cycle_id       INTEGER REFERENCES cycle(id),
  ts             TEXT    NOT NULL,
  day            TEXT,
  kind           TEXT    NOT NULL,
  delta_energy   REAL    NOT NULL DEFAULT 0,
  delta_stardust REAL    NOT NULL DEFAULT 0,
  delta_debt     REAL    NOT NULL DEFAULT 0,   -- 罚款欠款（正数=欠），结算时优先抵扣
  delta_fragment REAL    NOT NULL DEFAULT 0,
  delta_ticket   REAL    NOT NULL DEFAULT 0,   -- 券的通用计数（按张）
  delta_minutes  REAL    NOT NULL DEFAULT 0,   -- 娱乐券余额（分钟口径）
  ref_type       TEXT    NOT NULL DEFAULT '',
  ref_id         INTEGER,
  note           TEXT    NOT NULL DEFAULT '',
  operator_id    INTEGER REFERENCES member(id),
  meta           TEXT    NOT NULL DEFAULT '{}',
  voided         INTEGER NOT NULL DEFAULT 0,
  void_of        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ledger_member ON ledger (member_id, ts);
CREATE INDEX IF NOT EXISTS ix_ledger_kind   ON ledger (kind);
CREATE INDEX IF NOT EXISTS ix_ledger_day    ON ledger (member_id, day);

-- 道具/券的逐项变动（挂在 ledger 上，余额 = 求和）
CREATE TABLE IF NOT EXISTS ledger_item (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ledger_id  INTEGER NOT NULL REFERENCES ledger(id),
  member_id  INTEGER NOT NULL REFERENCES member(id),
  item_id    INTEGER NOT NULL REFERENCES item(id),
  holding_id INTEGER REFERENCES holding(id),
  qty_delta  REAL    NOT NULL,
  reason     TEXT    NOT NULL DEFAULT '',
  ts         TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 道具图鉴（23 张卡 + 6 种券）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS item (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  code            TEXT    NOT NULL UNIQUE,
  name            TEXT    NOT NULL,
  category        TEXT    NOT NULL,              -- card|ticket|special
  rarity          TEXT    NOT NULL DEFAULT '',   -- common|rare|legend|diamond（券为空）
  card_no         TEXT    NOT NULL DEFAULT '',
  icon            TEXT    NOT NULL DEFAULT '',
  price           INTEGER,                       -- 星尘价，NULL=不售
  purchasable     INTEGER NOT NULL DEFAULT 0,
  weekly_limit    INTEGER,                       -- NULL=不限
  shelf_life_days INTEGER,                       -- NULL=永久
  max_hold        INTEGER,                       -- NULL=不限
  renew_cost_pct  REAL    NOT NULL DEFAULT 20,   -- 续期代价 = 原值百分比
  renew_times     INTEGER NOT NULL DEFAULT 1,
  expire_refund   REAL    NOT NULL DEFAULT 0,    -- 到期折半返还的星尘
  fragment_value  REAL    NOT NULL DEFAULT 0,    -- 重复卡拆解的碎片
  transferable    INTEGER NOT NULL DEFAULT 0,
  effect_key      TEXT    NOT NULL DEFAULT '',
  effect_json     TEXT    NOT NULL DEFAULT '{}',
  desc            TEXT    NOT NULL DEFAULT '',
  sort            INTEGER NOT NULL DEFAULT 0,
  active          INTEGER NOT NULL DEFAULT 1
);

-- 持有批次（有效期按批次算，消耗走 FIFO）
CREATE TABLE IF NOT EXISTS holding (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL REFERENCES member(id),
  item_id     INTEGER NOT NULL REFERENCES item(id),
  qty         REAL    NOT NULL DEFAULT 0,        -- 剩余可用的张数
  source      TEXT    NOT NULL DEFAULT 'box',    -- box|shop|task|grant
  acquired_at TEXT    NOT NULL,
  expires_at  TEXT,                              -- NULL=永久
  renew_count INTEGER NOT NULL DEFAULT 0,
  delay_count INTEGER NOT NULL DEFAULT 0,        -- 假期顺延次数
  note        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_holding_member ON holding (member_id, item_id);
CREATE INDEX IF NOT EXISTS ix_holding_expiry ON holding (member_id, expires_at);
CREATE INDEX IF NOT EXISTS ix_ledger_item_member ON ledger_item (member_id, item_id);

-- 道具使用记录
-- 「同类卡每周期最多用 1 张」这条护栏查的就是这张表：
-- 不查的话，攒 5 张翻倍卡一天全用掉这种事就会发生（第 04 章）。
CREATE TABLE IF NOT EXISTS item_use (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id  INTEGER NOT NULL,
  item_id    INTEGER NOT NULL,
  holding_id INTEGER,
  qty        REAL    NOT NULL DEFAULT 1,
  ts         TEXT    NOT NULL,
  meta       TEXT    NOT NULL DEFAULT '{}',
  note       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_item_use_member ON item_use (member_id, item_id, ts);

-- 碎片（重复卡拆解而来，只朝上换钻石级）
CREATE TABLE IF NOT EXISTS fragment_use (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id INTEGER NOT NULL,
  qty       REAL    NOT NULL,
  kind      TEXT    NOT NULL,   -- gain|spend
  note      TEXT    NOT NULL DEFAULT '',
  ts        TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 宝箱七档
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_tier (
  tier             INTEGER PRIMARY KEY,          -- 1..7
  code             TEXT    NOT NULL,
  name             TEXT    NOT NULL,
  threshold        INTEGER NOT NULL,
  tickets          REAL    NOT NULL DEFAULT 0,   -- 保底券
  stardust         REAL    NOT NULL DEFAULT 0,   -- 保底星尘；v24 起七档全部为 0，别再往里填
  random_rate      REAL    NOT NULL DEFAULT 0,   -- 随机件概率
  random_pool      TEXT    NOT NULL DEFAULT '[]',
  cards_json       TEXT    NOT NULL DEFAULT '[]', -- v24 保底高级件：[{"rarity":"common","count":1}]
  card_rarity      TEXT    NOT NULL DEFAULT '',  -- 旧列，v24 起不用（留着免得老库报错）
  card_count       INTEGER NOT NULL DEFAULT 0,
  diamond_rate     REAL    NOT NULL DEFAULT 0,   -- 完美箱专属：10% 钻石级
  purchase_price   INTEGER,                      -- 直购价，NULL=不售
  purchase_allowed INTEGER NOT NULL DEFAULT 0,
  icon             TEXT    NOT NULL DEFAULT '',  -- v21：图标 token，见 web/icons.js
  sort             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS box_open (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id     INTEGER NOT NULL,
  cycle_id      INTEGER,
  tier          INTEGER NOT NULL,
  source        TEXT    NOT NULL,                -- free|purchase
  tickets       REAL    NOT NULL DEFAULT 0,
  stardust      REAL    NOT NULL DEFAULT 0,
  card_item_id  INTEGER,
  diamond_item_id INTEGER,
  random_json   TEXT    NOT NULL DEFAULT '[]',
  cost          INTEGER NOT NULL DEFAULT 0,
  ts            TEXT    NOT NULL,
  operator_id   INTEGER,
  opened_at     TEXT    -- v38：NULL=还没开，有值=开过了（箱内容压到这一刻才抽）
);

-- ---------------------------------------------------------------------------
-- 星探时刻（额外加分，增益通道）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS explore (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id    INTEGER NOT NULL,
  cycle_id     INTEGER,
  day          TEXT    NOT NULL,
  kind         TEXT    NOT NULL,                 -- stardust|energy|both
  energy       REAL    NOT NULL DEFAULT 0,
  stardust     REAL    NOT NULL DEFAULT 0,
  phrase       TEXT    NOT NULL DEFAULT '',      -- 必须附一句具体的话
  dimension_id INTEGER,
  operator_id  INTEGER,
  ts           TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 心愿单（个人目标）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wish (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id        INTEGER NOT NULL,
  title            TEXT    NOT NULL,
  cond_type        TEXT    NOT NULL,   -- fixed|stardust|task_count|streak|perfect_day|custom|any
                                       -- custom = 家长自己写的一句话（只有它能提交审核）
                                       -- any    = 多选，勾 2 至 6 条，另定「做到几条算成」
  cond_json        TEXT    NOT NULL DEFAULT '{}',
  reward_desc      TEXT    NOT NULL DEFAULT '',
  price_note       TEXT    NOT NULL DEFAULT '',
  selfpay_stardust REAL    NOT NULL DEFAULT 0,
  -- wished：孩子许下了，条件还没定，挂在墙上等家长处理，不算「进行中」
  -- active：条件定了，心愿点亮生效，进度开始算
  -- achieved：条件到了（系统自己判，算够了就落），球到家长那边 —— 去把事情办了
  -- delivered：家长说「已经给他了」，球回孩子那边，等他点一下
  -- claimed：孩子点过「我收到了」，这条算完
  status           TEXT    NOT NULL DEFAULT 'active',  -- wished|active|achieved|delivered|claimed|cancelled
  created_at       TEXT, achieved_at TEXT, claimed_at TEXT, cancelled_at TEXT,
  delivered_at     TEXT,                 -- v44：家长点「已经给他了」的时刻
  delivered_by     INTEGER,              -- v44：这一步是谁做的（他回头问「谁给的」有地方可查）
  configured_at    TEXT,               -- v17：家长把条件定下来的时刻，进度从这里开始算
  configured_by    INTEGER,            -- v17：定条件的那位家长
  closed_by        INTEGER,            -- v18：谁把它结束的（驳回 / 撤回 / 放弃都记这里）
  closed_from      TEXT    NOT NULL DEFAULT '',  -- v18：结束之前是什么状态，用来分「被驳回」和「自己放弃」
  ready_notified_at TEXT   NOT NULL DEFAULT '',  -- v20：进度报过没有，存的是周期起点日
  icon             TEXT    NOT NULL DEFAULT '',  -- v21：图标 token。家长选，不给孩子选
  operator_id      INTEGER
);

-- 心愿「按哪一条提交」（v29）
-- 一条心愿可以挂好几条条件，孩子说「我做到了」的时候，必须说清是做到了哪一条。
-- 以前只有一个按钮，提交的是整条心愿 —— 家长在审核页看到的也是整条，
-- 于是「他到底靠哪条达成的」只能靠问。这张表把那句话记下来。
--
-- 只有系统算不了的那条（custom，家长自己写的一句话）才需要提交和审核：
-- 分数、星尘、任务数、连着几周这些，系统自己算得出来，算够了就是够了，
-- 不需要谁点头，也不该让孩子为了一件已经成立的事实去等人批。
CREATE TABLE IF NOT EXISTS wish_claim (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  wish_id      INTEGER NOT NULL,
  cond_key     TEXT    NOT NULL,              -- 条件的类型，custom 为主
  note         TEXT    NOT NULL DEFAULT '',   -- 孩子提交时写的那句话
  status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
  created_at   TEXT, created_by INTEGER,
  resolved_at  TEXT, resolved_by INTEGER,
  reject_note  TEXT    NOT NULL DEFAULT ''    -- 驳回必填，对孩子可见
);

CREATE INDEX IF NOT EXISTS ix_wish_claim ON wish_claim (wish_id, cond_key);

-- 许愿池（全家共攒的体验型协作目标）
CREATE TABLE IF NOT EXISTS wish_pool (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT    NOT NULL,
  target_desc   TEXT    NOT NULL DEFAULT '',
  target_stardust REAL  NOT NULL DEFAULT 0,
  status        TEXT    NOT NULL DEFAULT 'active',
  created_at    TEXT, achieved_at TEXT
);
CREATE TABLE IF NOT EXISTS wish_pool_entry (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pool_id   INTEGER NOT NULL,
  member_id INTEGER,
  source    TEXT    NOT NULL,   -- fine|selfpay|task|penalty
  stardust  REAL    NOT NULL DEFAULT 0,
  cash      REAL    NOT NULL DEFAULT 0,
  note      TEXT    NOT NULL DEFAULT '',
  ts        TEXT    NOT NULL
);

-- 许愿池日志（v30）：进池子的每一笔「不是某个人主动投的」都要留一张凭据。
--
-- 罚款入池和主动投币都看得到是谁、什么时候、多少，账目自洽；只有
-- 「全家忘打卡」这一笔是系统自己判的 —— 谁也没点这一下，星尘却进了池子。
-- 光有一条 wish_pool_entry 不够：那里只有金额，说不清是哪一天漏了、
-- 漏的是哪个孩子、条数几条。这一张表专门记那几句话。
--
--   kind   penalty = 全家忘打卡的惩罚注入（当前只有这一种）
--   day    触发日：被漏打的那一天，按自然日归属
--   member_id  责任人；系统判定的写 NULL，由具体人承担的才写 id
--   counted    这一笔算不算进目标进度（进度 = 所有 entry 求和，所以默认算）
CREATE TABLE IF NOT EXISTS wish_pool_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pool_id   INTEGER,
  kind      TEXT    NOT NULL DEFAULT 'penalty',
  day       TEXT    NOT NULL,
  member_id INTEGER,
  kids_json TEXT    NOT NULL DEFAULT '[]',   -- 这一天被漏打的孩子 [{id,name}]
  kids_days INTEGER NOT NULL DEFAULT 0,      -- 漏打涉及的孩子天数合计
  stardust  REAL    NOT NULL DEFAULT 0,      -- 实际注入池子的星尘
  cash      REAL    NOT NULL DEFAULT 0,      -- v44：这笔罚款的元数（补投时「一共收了多少元」要算上）
  counted   INTEGER NOT NULL DEFAULT 1,      -- 1 = 计入目标进度
  note      TEXT    NOT NULL DEFAULT '',
  ts        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pool_log_day ON wish_pool_log (kind, day);

-- ---------------------------------------------------------------------------
-- 任务清单（奖励任务 + 系统生成的修复任务）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  kind           TEXT    NOT NULL DEFAULT 'reward',  -- reward|repair
  title          TEXT    NOT NULL,
  std            TEXT    NOT NULL DEFAULT '',        -- 完成标准，必须可核对
  assignee_id    INTEGER,                            -- v15 起可空：NULL = 挂在大厅里等人领
  created_by     INTEGER NOT NULL,
  reward_type    TEXT    NOT NULL DEFAULT '',
  reward_json    TEXT    NOT NULL DEFAULT '{}',
  deadline       TEXT,
  status         TEXT    NOT NULL DEFAULT 'pending', -- open|pending|claimed|submitted|confirmed|returned|archived
  cooldown_key   TEXT    NOT NULL DEFAULT '',
  visibility     TEXT    NOT NULL DEFAULT 'family',  -- 修复任务永远 private
  template       TEXT    NOT NULL DEFAULT '',
  calibration_id INTEGER,
  return_count   INTEGER NOT NULL DEFAULT 0,
  auto_confirm   INTEGER NOT NULL DEFAULT 1,         -- 48h 未处理自动通过
  slots          INTEGER NOT NULL DEFAULT 1,         -- v15：大厅名额，1=先到先得，0=每个孩子各一份
  hall_id        INTEGER,                            -- v15：领取后生成的副本指向大厅那条
  claimed_at     TEXT,                               -- v15：被领走的时刻
  icon           TEXT    NOT NULL DEFAULT '',        -- v21：图标 token，发任务的人选
  created_at     TEXT, submitted_at TEXT, confirmed_at TEXT, archived_at TEXT
);

-- ---------------------------------------------------------------------------
-- 校准（惩罚）三层
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id    INTEGER NOT NULL,
  level        INTEGER NOT NULL,      -- 1 自校准 | 2 联动校准 | 3 契约校准
  dimension_id INTEGER,
  reason       TEXT    NOT NULL,
  effect_type  TEXT    NOT NULL DEFAULT '',  -- ticket_min|fine|task|device|none
  effect_json  TEXT    NOT NULL DEFAULT '{}',
  amount       REAL    NOT NULL DEFAULT 0,
  operator_id  INTEGER,
  ts           TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 假期日历
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holiday (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT    NOT NULL,
  start_date TEXT    NOT NULL,
  end_date   TEXT    NOT NULL,
  auto_mode  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT
);

-- ---------------------------------------------------------------------------
-- 国家法定节假日（自动拉取，只读）
-- ---------------------------------------------------------------------------
-- 跟上面那张 holiday 是两件事，别合并：
--   holiday      = 家长手填的放假区间（寒暑假、学校自己放的），带着
--                  「假期版维度名」和「首尾过渡日不计分」两层副作用。
--   calendar_day = 从公开数据源拉回来的国家日历，只回答「这天放不放假」。
-- 把法定假日塞进 holiday，元旦那三天的前后两天就变成「不计分」了。
CREATE TABLE IF NOT EXISTS calendar_day (
  day        TEXT    PRIMARY KEY,          -- YYYY-MM-DD
  is_off     INTEGER NOT NULL,             -- 1=放假  0=调休上班
  name       TEXT    NOT NULL DEFAULT '',  -- 元旦、春节、国庆节…
  year       INTEGER NOT NULL,             -- 冗余，删整年时省一次扫描
  updated_at TEXT
);

-- 求助记录（常驻按钮，每周 ≤3 次）
CREATE TABLE IF NOT EXISTS help_request (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL,
  day         TEXT    NOT NULL,
  week_key    TEXT    NOT NULL,
  detail      TEXT    NOT NULL,
  verified_by INTEGER,
  verified_at TEXT,
  stardust    REAL    NOT NULL DEFAULT 1,
  ts          TEXT    NOT NULL
);

-- 加时申请
CREATE TABLE IF NOT EXISTS overtime_request (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL,
  day         TEXT    NOT NULL,
  week_key    TEXT    NOT NULL,
  minutes     REAL    NOT NULL DEFAULT 30,
  cost        REAL    NOT NULL DEFAULT 10,
  status      TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
  reason      TEXT    NOT NULL DEFAULT '',
  reject_note TEXT    NOT NULL DEFAULT '',         -- 拒绝必填且对孩子可见
  operator_id INTEGER,
  ts          TEXT    NOT NULL,
  resolved_at TEXT,
  consumed_by INTEGER   -- v14：这条加时被哪次券核销用掉了（NULL=还没用）
);

-- 券核销申请（v14）：券是孩子挣的，但核销要家长点头。
-- 娱乐券在申请前先过五道闸门（前置 / 单次 / 间隔 / 晚间 / 硬停止），
-- 闸门不过的直接在孩子那边就拒掉，不拿去烦家长；过了闸门的才生成一条待办。
CREATE TABLE IF NOT EXISTS ticket_request (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL REFERENCES member(id),
  item_id     INTEGER NOT NULL REFERENCES item(id),
  qty         REAL    NOT NULL DEFAULT 1,
  day         TEXT    NOT NULL,               -- YYYY-MM-DD，按自然日归属
  minutes     REAL    NOT NULL DEFAULT 0,     -- qty × 券面值
  status      TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|expired|self
  gate        TEXT    NOT NULL DEFAULT '{}',  -- 申请时的闸门快照
  note        TEXT    NOT NULL DEFAULT '',    -- 孩子填的用途
  reject_note TEXT    NOT NULL DEFAULT '',    -- 拒绝必填，且对孩子可见
  operator_id INTEGER,
  ts          TEXT    NOT NULL,
  expire_at   TEXT,
  resolved_at TEXT,
  start_at    TEXT,                           -- 同意即开始计时
  end_at      TEXT,
  -- v42：不带时长的券（陪伴 / 选择 / 豁免 / 独处 / 好友）批了不等于办好了，
  -- 它们要的是家长真的去做那件事。waiting → done / void，'' = 用不着（带时长的券）。
  fulfill_status TEXT NOT NULL DEFAULT '',
  fulfill_note   TEXT NOT NULL DEFAULT '',    -- 家长办完写的那一句，孩子看得到
  fulfilled_at   TEXT,
  fulfilled_by   INTEGER,
  remind_at      TEXT,                        -- 孩子最近一次催，每天限一次
  ack_at         TEXT                         -- 玩完了那张存档卡，孩子点过「知道了」
);

CREATE INDEX IF NOT EXISTS idx_ticket_req_member ON ticket_request (member_id, day);
CREATE INDEX IF NOT EXISTS idx_ticket_req_status ON ticket_request (status);

-- ---------------------------------------------------------------------------
-- 通知 / 会话 / 审计
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id INTEGER,                 -- NULL = 全家
  kind      TEXT    NOT NULL,
  title     TEXT    NOT NULL,
  body      TEXT    NOT NULL DEFAULT '',
  ts        TEXT    NOT NULL,
  read_at   TEXT,
  pushed_at TEXT,                    -- v20：推手机成功的时刻；空 = 还没推
  push_tries INTEGER NOT NULL DEFAULT 0,
  push_error TEXT    NOT NULL DEFAULT ''
);
-- 注意：这个索引不写在这里。notification 是老表，老库跑
-- CREATE TABLE IF NOT EXISTS 不会补上新列，紧接着建索引就会报
-- 「no such column: pushed_at」。它跟着 _migrate_v20 一起建。

-- ---------------------------------------------------------------------------
-- 推送目标（v20）：一个人可以有多条（手机一条、平板一条）
-- target 是 Bark 的 device key，等于「谁能往这台设备发通知」的钥匙，
-- 跟密码一个级别，所以列表接口只回显后四位，不回显明文。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS push_target (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id  INTEGER NOT NULL REFERENCES member(id),
  kind       TEXT    NOT NULL DEFAULT 'bark',   -- 先只支持 bark
  server     TEXT    NOT NULL DEFAULT 'https://api.day.app',
  target     TEXT    NOT NULL,
  label      TEXT    NOT NULL DEFAULT '',
  enabled    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT    NOT NULL,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_ok_at TEXT,
  last_err   TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_push_target_member ON push_target (member_id);
CREATE INDEX IF NOT EXISTS ix_task_assignee ON task (assignee_id, status);
CREATE INDEX IF NOT EXISTS ix_wish_member ON wish (member_id, status);
CREATE INDEX IF NOT EXISTS ix_explore_member ON explore (member_id, day);

CREATE TABLE IF NOT EXISTS session (
  token      TEXT PRIMARY KEY,
  member_id  INTEGER NOT NULL REFERENCES member(id),
  created_at TEXT    NOT NULL,
  expires_at TEXT    NOT NULL
);
-- 每个请求都要按 token 查一行；没索引时它跟着会话表长度走
CREATE INDEX IF NOT EXISTS ix_session_member ON session (member_id);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id    INTEGER,
  action      TEXT    NOT NULL,
  target_type TEXT    NOT NULL DEFAULT '',
  target_id   INTEGER,
  before_json TEXT    NOT NULL DEFAULT '',
  after_json  TEXT    NOT NULL DEFAULT '',
  ts          TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 两个独立事件通道（第 09 / 10 章）
--
-- 这两件事都不进打分表、不罚钱、不进违约金。罚金那条线只管「说了不算」，
-- 不管「做错事」；把偷玩和抄作业折成钱，等于把性质问题换成价格问题。
-- ---------------------------------------------------------------------------
-- 偷玩游戏：处理方式是「设备降级」不是没收也不是扣券。
-- 设备使用权从「自主使用」降为「公开使用」（只能在公共区域用），
-- 时长仍按券走，到期自动恢复，不需要再谈。30 天内重复则 3 天延长到 7 天。
CREATE TABLE IF NOT EXISTS device_downgrade (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL REFERENCES member(id),
  reason      TEXT    NOT NULL DEFAULT '',   -- 先查因：问出来的那句话记在这里
  days        INTEGER NOT NULL DEFAULT 3,
  start_date  TEXT    NOT NULL,
  end_date    TEXT    NOT NULL,
  status      TEXT    NOT NULL DEFAULT 'active',  -- active|ended
  operator_id INTEGER,
  created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_device_dg_member ON device_downgrade (member_id, status);

-- 抄作业：事后才发现的处理留痕。
-- 撤的是一个还没被验证的判断，不是已经发出去的东西，所以不算追溯。
CREATE TABLE IF NOT EXISTS homework_check (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL REFERENCES member(id),
  day         TEXT    NOT NULL,
  subject     TEXT    NOT NULL DEFAULT '',
  revoked     INTEGER NOT NULL DEFAULT 0,    -- 撤掉的智识分
  note        TEXT    NOT NULL DEFAULT '',
  operator_id INTEGER,
  created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_homework_member ON homework_check (member_id, day);

-- 运行期元信息（schema 版本等）
-- 卡片兑现单（v22）。
-- 之前用一张卡只记一条消耗流水，效果本身没人管：点了「使用」，库存少一张，
-- 然后什么都没发生。这张表把「这一张卡现在是什么状态」变成一条能查的记录：
--   pending 等爸爸妈妈兑现（陪伴、点餐、好友过夜这些要真人配合的）
--   active  当天生效的标记（免催、免等、晚睡、免家务日），日终自动过期
--   armed   装填中，下一次触发它的动作来了才消费（翻倍、零花钱加倍、重抽）
--   done    已兑现 / 已消费
--   void    作废
CREATE TABLE IF NOT EXISTS card_redeem (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id   INTEGER NOT NULL REFERENCES member(id),
  item_id     INTEGER NOT NULL REFERENCES item(id),
  effect_key  TEXT    NOT NULL,
  payload     TEXT    NOT NULL DEFAULT '{}',
  day         TEXT    NOT NULL,          -- 生效日；pending 的用申请日
  status      TEXT    NOT NULL DEFAULT 'pending',
  auto        INTEGER NOT NULL DEFAULT 0,  -- 1=系统自己就把事办了，不用家长动手
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL,
  done_at     TEXT,
  operator_id INTEGER,
  note        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_card_redeem_status ON card_redeem (status, day);
CREATE INDEX IF NOT EXISTS ix_card_redeem_member ON card_redeem (member_id, effect_key, status);

-- ---------------------------------------------------------------------------
-- 零花钱兑换申请（v24）
-- ---------------------------------------------------------------------------
-- 兑换从「孩子点一下就到账」改成三步：孩子发起、家长审核（同意即发放）、
-- 孩子确认收到。中间这一步不是审批门槛，是「谁什么时候把现金给到他」的
-- 凭据：钱是爸妈从口袋里掏的，系统扣的只是星尘，两边必须对得上。
--   pending   孩子提了，等家长看一眼
--   approved  家长点了同意，星尘已扣、账已记，等孩子说收到了
--   received  孩子确认拿到现金，这一条算完结
--   rejected  家长拒了（要写理由）
--   cancelled 孩子自己撤回
CREATE TABLE IF NOT EXISTS cash_request (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id      INTEGER NOT NULL REFERENCES member(id),
  stardust       REAL    NOT NULL,                    -- 要扣多少星尘
  cash           REAL    NOT NULL DEFAULT 0,          -- 实际给多少元（审批时定，含加倍卡）
  bonus          REAL    NOT NULL DEFAULT 0,          -- 其中加倍卡多给的那部分
  status         TEXT    NOT NULL DEFAULT 'pending',
  note           TEXT    NOT NULL DEFAULT '',         -- 孩子写的用途
  reject_note    TEXT    NOT NULL DEFAULT '',
  ledger_id      INTEGER,                             -- 发放时写的那条流水
  created_at     TEXT    NOT NULL,
  resolved_at    TEXT,
  resolved_by    INTEGER,
  received_at    TEXT,
  operator_id    INTEGER
);
CREATE INDEX IF NOT EXISTS ix_cash_request_member ON cash_request (member_id, status);
CREATE INDEX IF NOT EXISTS ix_cash_request_status ON cash_request (status, created_at);

-- ---------------------------------------------------------------------------
-- 赛季（v44）：欠款与道具的冲刷周期
-- ---------------------------------------------------------------------------
-- 之前欠款是「每个周期末免一次」（周期默认 7 天），太勤 —— 一张大额罚单
-- 一期就免掉大半。现在改成跨周期滚动累积，只在赛季末清一次。
--
-- 一季默认 90 天（跟历史上卡有效期的「一个赛季」对齐），到点自动推下一季；
-- 家长可以改长度。结束日撞上寒暑假就顺延（复用假期保护窗那套参数）。
--
-- 季末清算只动「欠账与道具」：清欠款 / 清消耗卡（按 expire_refund 折星尘）/
-- 清六种券 / 清碎片；星尘余额、等级、三张身份卡一律不动。没开的宝箱留着，
-- 让他在新赛季自己点开。
CREATE TABLE IF NOT EXISTS season (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  idx        INTEGER NOT NULL,              -- 第几季，从 1 开始
  theme      TEXT    NOT NULL DEFAULT '',   -- 主题占位（换皮以后用得上）
  start_date TEXT    NOT NULL,
  end_date   TEXT    NOT NULL,
  settled_at TEXT,                          -- 季末清算完成的时刻；空 = 还没结
  created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_season_dates ON season (start_date, end_date);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
