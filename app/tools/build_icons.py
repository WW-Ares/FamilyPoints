# -*- coding: utf-8 -*-
"""
生成 web/icons/*.svg 与 web/icons.js。

为什么要这个脚本而不是直接手改文件：图标是六十来份 SVG，内容高度雷同
（同一个圆形底座，只有中间那几笔不同），手改必然出现某一笔写错、某个
viewBox 忘记改这类肉眼挑不出来的问题。这里把「底座 + 颜色」收成一行，
改一个图标只动 body 这一个字符串，重跑一遍就全省同步。

视觉语言（照 RewardHub 的路数）：120 版心、圆形底 + 扁平糖果色、
白色实心图形、深蓝灰 #2f3b50 做点缀。不用 stroke-only 的细线稿，
因为在手机上缩到 20px 时细线会糊成一团。

SVG 全部为本项目自绘，不引用任何第三方素材，没有授权问题。
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_SVG = os.path.join(ROOT, "web", "icons")
OUT_JS = os.path.join(ROOT, "web", "icons.js")

W = "#ffffff"
DARK = "#2f3b50"

PALETTE = {
    "red": "#ec7b72", "pink": "#e79ab5", "rose": "#d98cb0", "blush": "#EFA8B8",
    "orange": "#f5a75d", "yellow": "#f2c55c", "gold": "#f4bd5c",
    "green": "#82c8a6", "mint": "#71b69c", "teal": "#7fc4c9",
    "sky": "#8ec9e8", "blue": "#6fa8dc", "indigo": "#8fa5e0",
    "purple": "#b58bd9", "brown": "#c9905f", "grey": "#9aa5b1",
}

# (token, 显示名, 分组, 底色, 搜索关键词, 图形)
# 图形坐标范围：圆心 (60,60)，半径 44，可用区大约 22~98。
ICONS = [
    # 一、七个维度 ----------------------------------------------------------
    ("dim_heart", "心能", "维度", "red", "心 情绪 平静",
     '<path d="M60 88C41 73 31 63 31 50c0-9 7-16 16-16 6 0 11 3 13 8 2-5 7-8 13-8 9 0 16 7 16 16 0 13-10 23-29 38z" fill="%s"/>' % W),

    ("dim_study", "智识", "维度", "blue", "学习 书 专注",
     '<path d="M60 40c-7-5-18-6-26-3v42c8-3 19-2 26 3 7-5 18-6 26-3V37c-8-3-19-2-26 3z" fill="%s"/>'
     '<path d="M60 40v42" stroke="%s" stroke-width="3.5"/>'
     '<path d="M40 50h13M40 61h13M67 50h13M67 61h13" stroke="%s" stroke-width="2.6" stroke-linecap="round"/>' % (W, PALETTE["blue"], PALETTE["blue"])),

    ("dim_vigor", "活力", "维度", "orange", "运动 精力 跑",
     '<path d="M66 24 38 66h19l-7 30 28-44H58z" fill="%s"/>' % W),

    ("dim_bond", "羁绊", "维度", "blush", "家人 关心 一起",
     '<circle cx="46" cy="48" r="11" fill="%s"/><circle cx="74" cy="48" r="11" fill="%s"/>'
     '<path d="M28 86c0-9 8-16 18-16s18 7 18 16zM56 86c0-9 8-16 18-16s18 7 18 16z" fill="%s"/>' % (W, W, W)),

    ("dim_craft", "匠力", "维度", "brown", "家务 动手 做",
     '<rect x="26" y="32" width="40" height="22" rx="7" fill="%s"/>'
     '<rect x="53" y="52" width="15" height="36" rx="7" fill="%s"/>'
     '<rect x="32" y="38" width="12" height="10" rx="3" fill="%s"/>' % (W, W, PALETTE["brown"])),

    ("dim_clean", "洁净", "维度", "teal", "卫生 干净 洗",
     '<circle cx="49" cy="51" r="13" fill="%s"/><circle cx="73" cy="62" r="10" fill="%s" opacity=".9"/>'
     '<circle cx="55" cy="77" r="7" fill="%s" opacity=".8"/>'
     '<path d="M34 34c5-4 12-5 17-1" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round"/>' % (W, W, W, W)),

    ("dim_order", "秩序", "维度", "purple", "归位 整洁 房间",
     '<rect x="28" y="30" width="24" height="24" rx="5" fill="%s"/>'
     '<rect x="66" y="30" width="24" height="24" rx="5" fill="%s"/>'
     '<rect x="28" y="66" width="24" height="24" rx="5" fill="%s"/>'
     '<rect x="66" y="66" width="24" height="24" rx="5" fill="%s" opacity=".45"/>'
     '<path d="M70 78l6 7 11-13" stroke="%s" stroke-width="5.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' % (W, W, W, W, W)),

    # 二、日常 --------------------------------------------------------------
    ("task_read", "读书", "日常", "indigo", "书 阅读 看",
     '<rect x="32" y="68" width="52" height="13" rx="4" fill="%s"/>'
     '<rect x="38" y="55" width="44" height="11" rx="4" fill="%s"/>'
     '<rect x="45" y="43" width="34" height="11" rx="4" fill="%s" opacity=".85"/>'
     '<path d="M60 43v11" stroke="%s" stroke-width="2.4"/>' % (W, W, W, PALETTE["indigo"])),

    ("task_write", "写字", "日常", "yellow", "练字 笔 书法",
     '<path d="M38 82l4-13 31-31 10 10-31 31z" fill="%s"/>'
     '<path d="M42 69l10 10" stroke="%s" stroke-width="4"/>'
     '<path d="M38 82l14 4-10-18z" fill="%s"/>' % (W, W, DARK)),

    ("task_homework", "作业", "日常", "blue", "功课 学校 写",
     '<rect x="36" y="28" width="48" height="60" rx="7" fill="%s"/>'
     '<path d="M47 44h22M47 57h22" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
     '<path d="M51 68l6 7 11-13" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' % (W, PALETTE["blue"], PALETTE["green"])),

    ("task_piano", "练琴", "日常", "purple", "音乐 乐器 弹",
     '<rect x="28" y="46" width="64" height="36" rx="6" fill="%s"/>'
     '<rect x="42" y="46" width="9" height="22" rx="3" fill="%s"/>'
     '<rect x="55" y="46" width="9" height="22" rx="3" fill="%s"/>'
     '<rect x="68" y="46" width="9" height="22" rx="3" fill="%s"/>'
     '<rect x="28" y="74" width="64" height="8" rx="3" fill="%s"/>' % (W, DARK, DARK, DARK, PALETTE["purple"])),

    ("task_sport", "运动", "日常", "orange", "球 足球 锻炼",
     '<circle cx="60" cy="60" r="26" fill="%s"/>'
     '<path d="M60 38l12 9-5 15H53l-5-15z" fill="%s"/>'
     '<path d="M53 62l4 16M67 62l-4 16M45 56l15 6 15-6" stroke="%s" stroke-width="2.6" fill="none"/>' % (W, DARK, DARK)),

    ("task_swim", "游泳", "日常", "sky", "水 泳池",
     '<circle cx="50" cy="46" r="10" fill="%s"/>'
     '<path d="M40 64c6-5 13-5 17-1l14 12" stroke="%s" stroke-width="7" fill="none" stroke-linecap="round"/>'
     '<path d="M38 80c8-6 18-6 26 0s18 6 26 0" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round"/>' % (W, W, W)),

    ("task_bike", "骑车", "日常", "green", "自行车 户外",
     '<circle cx="38" cy="70" r="14" fill="none" stroke="%s" stroke-width="5"/>'
     '<circle cx="82" cy="70" r="14" fill="none" stroke="%s" stroke-width="5"/>'
     '<path d="M38 70l15-24h17l16 24M53 46l8 24" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round"/>' % (W, W, W)),

    ("task_walk", "遛弯", "日常", "teal", "散步 走路 遛狗",
     '<circle cx="52" cy="40" r="10" fill="%s"/>'
     '<path d="M52 50l-8 18M52 50l10 14 8 10M50 50l-2 18 2 14M62 64l-4 16" stroke="%s" stroke-width="6" fill="none" stroke-linecap="round"/>' % (W, W)),

    ("task_bath", "洗澡", "日常", "sky", "沐浴 晚上",
     '<path d="M30 60h60v8a14 14 0 0 1-14 12H44a14 14 0 0 1-14-12z" fill="%s"/>'
     '<path d="M30 60c0-8 5-14 12-14h36c7 0 12 6 12 14" fill="none" stroke="%s" stroke-width="5"/>'
     '<circle cx="44" cy="36" r="5" fill="%s"/><circle cx="58" cy="30" r="4" fill="%s"/><circle cx="72" cy="38" r="5" fill="%s"/>' % (W, W, W, W, W)),

    ("task_tooth", "刷牙", "日常", "green", "牙齿 卫生",
     '<rect x="46" y="38" width="30" height="13" rx="5" fill="%s"/>'
     '<rect x="55" y="50" width="12" height="38" rx="6" fill="%s"/>'
     '<path d="M50 38v-8M58 38v-8M66 38v-8M74 38v-8" stroke="%s" stroke-width="3.4" stroke-linecap="round"/>' % (W, W, W)),

    ("task_laundry", "洗衣", "日常", "indigo", "洗衣机 衣服",
     '<rect x="34" y="26" width="52" height="68" rx="11" fill="%s"/>'
     '<circle cx="60" cy="66" r="18" fill="%s"/>'
     '<circle cx="46" cy="40" r="4" fill="%s"/><circle cx="58" cy="40" r="4" fill="%s"/>' % (W, PALETTE["indigo"], PALETTE["indigo"], PALETTE["indigo"])),

    ("task_dish", "洗碗", "日常", "yellow", "盘子 厨房",
     '<path d="M32 64h56c0 15-12 25-28 25S32 79 32 64z" fill="%s"/>'
     '<circle cx="42" cy="44" r="6" fill="%s" opacity=".9"/><circle cx="56" cy="38" r="5" fill="%s"/>'
     '<circle cx="72" cy="46" r="7" fill="%s" opacity=".85"/>' % (W, W, W, W)),

    ("task_cook", "做饭", "日常", "red", "厨房 锅 菜",
     '<path d="M32 56h56v14a20 20 0 0 1-20 20H52a20 20 0 0 1-20-20z" fill="%s"/>'
     '<path d="M32 56h56" stroke="%s" stroke-width="5"/>'
     '<path d="M88 62l13-7M32 48H20" stroke="%s" stroke-width="5" stroke-linecap="round"/>' % (W, W, W)),

    ("task_tidy", "整理房间", "日常", "purple", "收拾 收纳 归位",
     '<rect x="32" y="62" width="56" height="26" rx="6" fill="%s"/>'
     '<rect x="43" y="38" width="34" height="22" rx="6" fill="%s" opacity=".85"/>'
     '<path d="M32 76h56" stroke="%s" stroke-width="3"/>'
     '<path d="M56 46h8M60 42v8" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % (W, W, PALETTE["purple"], PALETTE["purple"])),

    ("task_trash", "倒垃圾", "日常", "grey", "垃圾桶 扔",
     '<path d="M40 46h40l-4 44a6 6 0 0 1-6 5H50a6 6 0 0 1-6-5z" fill="%s"/>'
     '<rect x="34" y="38" width="52" height="9" rx="4" fill="%s"/>'
     '<rect x="52" y="31" width="16" height="8" rx="3" fill="%s"/>'
     '<path d="M53 58v26M67 58v26" stroke="%s" stroke-width="3.4"/>' % (W, W, W, PALETTE["grey"])),

    ("task_plant", "浇花", "日常", "green", "植物 水 阳台",
     '<path d="M60 60V56" stroke="%s" stroke-width="5"/>'
     '<path d="M60 62c-15 0-21-10-21-20 13 0 21 8 21 20zM60 62c15 0 21-10 21-20-13 0-21 8-21 20z" fill="%s"/>'
     '<path d="M44 74h32l-4 14a7 7 0 0 1-6 5H54a7 7 0 0 1-6-5z" fill="%s"/>' % (W, W, W)),

    ("task_pet", "照顾宠物", "日常", "brown", "猫 狗 喂",
     '<circle cx="60" cy="60" r="23" fill="%s"/>'
     '<path d="M41 42c-8-2-11 8-6 13 1-7 3-10 7-11zM79 42c8-2 11 8 6 13-1-7-3-10-7-11z" fill="%s"/>'
     '<circle cx="51" cy="56" r="4" fill="%s"/><circle cx="69" cy="56" r="4" fill="%s"/>'
     '<ellipse cx="60" cy="68" rx="6" ry="5" fill="%s"/>' % (W, W, DARK, DARK, DARK)),

    ("task_sleep", "早睡", "日常", "indigo", "睡觉 晚上 床",
     '<path d="M78 26a34 34 0 1 0 16 44 28 28 0 0 1-16-44z" fill="%s"/>'
     '<path d="M48 44l-6 9M64 38l-4 9" stroke="%s" stroke-width="3.4" stroke-linecap="round"/>' % (W, PALETTE["indigo"])),

    ("task_wake", "起床", "日常", "yellow", "闹钟 早上",
     '<circle cx="60" cy="64" r="26" fill="%s"/>'
     '<path d="M60 50v16l10 8" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round"/>'
     '<path d="M40 34l-8-8M80 34l8-8" stroke="%s" stroke-width="5" stroke-linecap="round"/>'
     '<path d="M42 88l-6 6M78 88l6 6" stroke="%s" stroke-width="5" stroke-linecap="round"/>' % (W, PALETTE["yellow"], W, W)),

    ("task_meal", "吃饭", "日常", "orange", "饭 碗 点餐",
     '<path d="M32 58h56c0 16-12 27-28 27S32 74 32 58z" fill="%s"/>'
     '<path d="M86 28L60 58M94 38L72 62" stroke="%s" stroke-width="4.6" stroke-linecap="round"/>' % (W, W)),

    ("task_drink", "喝水", "日常", "sky", "水杯 牛奶",
     '<path d="M42 40h30v42a13 13 0 0 1-13 13H55a13 13 0 0 1-13-13z" fill="%s"/>'
     '<path d="M42 52h30" stroke="%s" stroke-width="4"/>'
     '<path d="M72 50h8a7 7 0 0 1 0 14h-8" fill="none" stroke="%s" stroke-width="4.5"/>' % (W, PALETTE["sky"], W)),

    ("task_pack", "收拾书包", "日常", "green", "书包 上学 准备",
     '<path d="M42 44h36a10 10 0 0 1 10 10v30a6 6 0 0 1-6 6H38a6 6 0 0 1-6-6V54a10 10 0 0 1 10-10z" fill="%s"/>'
     '<path d="M50 44v-6a10 10 0 0 1 20 0v6" fill="none" stroke="%s" stroke-width="4"/>'
     '<rect x="44" y="66" width="32" height="11" rx="4" fill="%s"/>' % (W, W, PALETTE["green"])),

    ("task_outdoor", "出去玩", "日常", "teal", "户外 公园 树",
     '<circle cx="86" cy="34" r="9" fill="%s"/>'
     '<path d="M58 30l20 28H38z" fill="%s"/>'
     '<path d="M58 46l14 22H44z" fill="%s" opacity=".75"/>'
     '<rect x="54" y="58" width="8" height="26" rx="3" fill="%s"/>' % (W, W, W, W)),

    ("task_help", "帮忙", "日常", "rose", "搭把手 一起",
     '<path d="M28 64c10-9 21-9 32-9s22 0 32 9l-7 22c-8-6-17-6-25-6s-17 0-25 6z" fill="%s"/>'
     '<path d="M46 68c4 4 10 6 14 6s10-2 14-6" stroke="%s" stroke-width="3" fill="none" opacity=".5"/>' % (W, PALETTE["rose"])),

    # 三、奖励 --------------------------------------------------------------
    ("rw_stardust", "星尘", "奖励", "gold", "分 星星 积分",
     '<path d="M60 26l11 23 25 3-18 17 5 25-23-12-23 12 5-25-18-17 25-3z" fill="%s"/>' % W),

    ("rw_box", "宝箱", "奖励", "brown", "箱子 开箱 档位",
     '<path d="M22 66h76v26a9 9 0 0 1-9 9H31a9 9 0 0 1-9-9z" fill="%s"/>'
     '<path d="M22 66c0-13 17-22 38-22s38 9 38 22z" fill="%s" opacity=".72"/>'
     '<rect x="52" y="60" width="16" height="17" rx="4" fill="%s"/>'
     '<path d="M22 80h76" stroke="%s" stroke-width="4"/>' % (W, W, PALETTE["brown"], PALETTE["brown"])),

    ("rw_box_open", "开箱", "奖励", "brown", "打开 惊喜 完美",
     '<path d="M22 72h76v20a9 9 0 0 1-9 9H31a9 9 0 0 1-9-9z" fill="%s"/>'
     '<path d="M32 72l-9-24 62 7 9 17z" fill="%s" opacity=".8"/>'
     '<path d="M60 58V32M50 42l10-10 10 10M42 52l8-8M78 52l-8-8" stroke="%s" stroke-width="4.5" stroke-linecap="round"/>' % (W, W, W)),

    ("rw_level", "星球等级", "奖励", "purple", "等级 升级 行星",
     '<ellipse cx="60" cy="60" rx="38" ry="13" fill="none" stroke="%s" stroke-width="5" opacity=".9"/>'
     '<circle cx="60" cy="60" r="23" fill="%s"/>'
     '<path d="M48 54c6-4 14-3 18 3M56 72c6 3 13 1 16-5" stroke="%s" stroke-width="3" fill="none" stroke-linecap="round"/>' % (W, W, PALETTE["purple"])),

    ("rw_money", "零花钱", "奖励", "gold", "钱 兑换 现金",
     '<circle cx="60" cy="60" r="28" fill="%s"/>'
     '<path d="M52 42l8 13 8-13M48 55h24M48 64h24M60 55v22M51 68h18" stroke="%s" stroke-width="4" fill="none" stroke-linecap="round"/>' % (W, PALETTE["gold"])),

    ("rw_double", "翻倍", "奖励", "orange", "双倍 乘二 加倍",
     '<path d="M38 32l7 15 16 2-11 11 3 16-15-8-15 8 3-16-11-11 16-2z" fill="%s"/>'
     '<path d="M68 46l5 10 11 1-8 8 2 11-10-5-10 5 2-11-8-8 11-1z" fill="%s" opacity=".85"/>' % (W, W)),

    ("rw_dice", "骰子", "奖励", "blue", "随机 重抽 运气",
     '<rect x="32" y="32" width="56" height="56" rx="13" fill="%s"/>'
     '<circle cx="48" cy="48" r="5" fill="%s"/><circle cx="72" cy="72" r="5" fill="%s"/>'
     '<circle cx="60" cy="60" r="5" fill="%s"/>' % (W, PALETTE["blue"], PALETTE["blue"], PALETTE["blue"])),

    ("rw_rocket", "加速", "奖励", "rose", "火箭 快 冲",
     '<path d="M60 24c10 10 14 22 14 34l-9 12H55l-9-12c0-12 4-24 14-34z" fill="%s"/>'
     '<circle cx="60" cy="52" r="7" fill="%s"/>'
     '<path d="M46 60l-11 16 13-3zM74 60l11 16-13-3z" fill="%s"/>'
     '<path d="M54 70l6 18-6 7-6-7z" fill="%s"/>' % (W, PALETTE["red"], PALETTE["gold"], PALETTE["gold"])),

    ("rw_gift", "礼物", "奖励", "red", "礼品 惊喜 兑换",
     '<rect x="28" y="48" width="64" height="46" rx="7" fill="%s"/>'
     '<circle cx="50" cy="40" r="9" fill="%s"/><circle cx="70" cy="40" r="9" fill="%s"/>'
     '<circle cx="60" cy="42" r="5" fill="%s"/>'
     '<path d="M60 52v42" stroke="%s" stroke-width="6"/>' % (W, PALETTE["gold"], PALETTE["gold"], PALETTE["red"], W)),

    ("rw_card", "道具卡", "奖励", "blue", "卡片 图鉴 收藏",
     '<rect x="34" y="32" width="52" height="58" rx="9" fill="%s"/>'
     '<path d="M34 50h52" stroke="%s" stroke-width="4"/>'
     '<path d="M46 64h28M46 76h18" stroke="%s" stroke-width="4" stroke-linecap="round" opacity=".65"/>' % (W, PALETTE["blue"], PALETTE["blue"])),

    ("rw_fragment", "碎片", "奖励", "teal", "合成 拼图 换",
     '<path d="M46 40h10a6 6 0 0 1 12 0h10v10a6 6 0 0 0 0 12v10H56a6 6 0 0 0-12 0H34V62a6 6 0 0 0 0-12z" fill="%s"/>'
     '<circle cx="60" cy="61" r="5" fill="%s"/>' % (W, PALETTE["teal"])),

    ("rw_ticket", "券", "奖励", "pink", "票 通用",
     '<path d="M26 44h68v14a8 8 0 0 0 0 16v14H26V74a8 8 0 0 0 0-16z" fill="%s"/>'
     '<path d="M60 46v40" stroke="%s" stroke-width="3.5" stroke-dasharray="6 7"/>' % (W, PALETTE["pink"])),

    ("rw_ticket_fun", "娱乐券", "奖励", "indigo", "屏幕 游戏 电视",
     '<rect x="26" y="48" width="68" height="34" rx="17" fill="%s"/>'
     '<circle cx="44" cy="65" r="7" fill="%s"/>'
     '<path d="M40 65h8M44 61v8" stroke="%s" stroke-width="2.6"/>'
     '<circle cx="74" cy="58" r="4.5" fill="%s"/><circle cx="82" cy="69" r="4.5" fill="%s"/>'
     '<path d="M56 58h12" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % (W, PALETTE["indigo"], W, PALETTE["indigo"], PALETTE["indigo"], PALETTE["indigo"])),

    ("rw_ticket_company", "陪伴券", "奖励", "green", "陪 父母 亲子",
     '<circle cx="43" cy="52" r="12" fill="%s"/><circle cx="77" cy="52" r="12" fill="%s"/>'
     '<path d="M25 88c0-10 8-18 18-18s18 8 18 18zM59 88c0-10 8-18 18-18s18 8 18 18z" fill="%s"/>'
     '<path d="M60 44c-6-4-12 0-12 5 0 4 6 8 12 12 6-4 12-8 12-12 0-5-6-9-12-5z" fill="%s"/>' % (W, W, W, PALETTE["red"])),

    ("rw_ticket_choice", "选择券", "奖励", "purple", "说了算 挑 决定",
     '<rect x="32" y="32" width="56" height="56" rx="9" fill="%s"/>'
     '<circle cx="47" cy="50" r="7" fill="%s"/><circle cx="47" cy="70" r="7" fill="none" stroke="%s" stroke-width="3.4"/>'
     '<path d="M63 50h20M63 70h20" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, PALETTE["purple"], PALETTE["purple"], PALETTE["purple"])),

    ("rw_ticket_exempt", "豁免券", "奖励", "grey", "免一次 不做",
     '<rect x="32" y="32" width="56" height="56" rx="9" fill="%s"/>'
     '<path d="M44 50h32M44 66h32" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
     '<path d="M36 84l48-48" stroke="%s" stroke-width="5" stroke-linecap="round"/>' % (W, PALETTE["grey"], PALETTE["red"])),

    ("rw_ticket_friend", "好友券", "奖励", "rose", "朋友 同学 玩",
     '<circle cx="40" cy="54" r="11" fill="%s"/><circle cx="78" cy="54" r="11" fill="%s"/>'
     '<path d="M24 90c0-9 7-16 16-16s16 7 16 16zM62 90c0-9 7-16 16-16s16 7 16 16z" fill="%s"/>'
     '<path d="M60 26l3 6 6 1-5 4 2 6-6-3-6 3 2-6-5-4 6-1z" fill="%s"/>' % (W, W, W, W)),

    ("rw_ticket_solo", "独处券", "奖励", "sky", "单独 一对一 出去",
     '<circle cx="43" cy="44" r="12" fill="%s"/><path d="M27 88c0-9 7-16 16-16s16 7 16 16z" fill="%s"/>'
     '<circle cx="78" cy="55" r="9" fill="%s"/><path d="M66 88c0-7 5-13 12-13s12 6 12 13z" fill="%s"/>'
     '<path d="M59 76h9" stroke="%s" stroke-width="5" stroke-linecap="round"/>' % (W, W, W, W, W)),

    ("rw_mute", "不催", "奖励", "grey", "安静 不说话",
     '<path d="M28 44h50a8 8 0 0 1 8 8v20a8 8 0 0 1-8 8H50l-14 12V80h-8a8 8 0 0 1-8-8V52a8 8 0 0 1 8-8z" fill="%s" opacity=".45"/>'
     '<path d="M26 86l68-48" stroke="%s" stroke-width="6.5" stroke-linecap="round"/>' % (W, W)),

    # 四、系统 --------------------------------------------------------------
    ("sys_wish", "心愿", "系统", "pink", "许愿 愿望 目标",
     '<path d="M58 22l8 17 19 3-13 13 3 19-17-9-17 9 3-19-13-13 19-3z" fill="%s"/>'
     '<path d="M32 40l10 10M28 56l12 12M44 30l8 8" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, W)),

    ("sys_pool", "许愿池", "系统", "mint", "基金 存钱罐 攒",
     '<ellipse cx="58" cy="64" rx="30" ry="24" fill="%s"/>'
     '<rect x="46" y="44" width="16" height="7" rx="3" fill="%s"/>'
     '<circle cx="54" cy="34" r="8" fill="%s"/>'
     '<ellipse cx="86" cy="64" rx="8" ry="6" fill="%s"/>'
     '<path d="M40 78h18M43 85h13" stroke="%s" stroke-width="3.4" stroke-linecap="round"/>' % (W, PALETTE["mint"], PALETTE["gold"], PALETTE["mint"], PALETTE["mint"])),

    ("sys_guardian", "守护灵", "系统", "purple", "宠物 精灵 永久",
     '<path d="M60 30c18 0 28 12 28 26s-10 28-28 28-28-12-28-26 10-28 28-28z" fill="%s"/>'
     '<path d="M40 36c-5-8 0-15 7-12M80 36c5-8 0-15-7-12" fill="%s"/>'
     '<circle cx="50" cy="56" r="5" fill="%s"/><circle cx="70" cy="56" r="5" fill="%s"/>'
     '<path d="M52 72c4 4 12 4 16 0" stroke="%s" stroke-width="4" fill="none" stroke-linecap="round"/>' % (W, W, DARK, DARK, DARK)),

    ("sys_title", "称号", "系统", "gold", "徽章 头衔 永久",
     '<circle cx="60" cy="50" r="23" fill="%s"/>'
     '<path d="M44 74l7 22 9-11 9 11 7-22z" fill="%s"/>'
     '<path d="M60 34l4 8 9 1-6 6 1 9-8-4-8 4 1-9-6-6 9-1z" fill="%s"/>' % (W, PALETTE["gold"], PALETTE["red"])),

    ("sys_skin", "皮肤", "系统", "rose", "外观 换装 颜色",
     '<circle cx="60" cy="62" r="28" fill="%s"/>'
     '<circle cx="48" cy="50" r="6" fill="%s"/><circle cx="72" cy="50" r="6" fill="%s"/>'
     '<circle cx="44" cy="72" r="6" fill="%s"/><circle cx="71" cy="75" r="6" fill="%s"/>'
     '<circle cx="60" cy="62" r="5" fill="%s"/>' % (W, PALETTE["red"], PALETTE["gold"], PALETTE["green"], PALETTE["blue"], PALETTE["purple"])),

    ("sys_repair", "修复任务", "系统", "red", "道歉 补偿 补救",
     '<rect x="24" y="52" width="72" height="20" rx="10" fill="%s" transform="rotate(-30 60 62)"/>'
     '<rect x="54" y="52" width="14" height="20" fill="%s" opacity=".35" transform="rotate(-30 60 62)"/>'
     '<circle cx="40" cy="60" r="2.6" fill="%s"/><circle cx="80" cy="64" r="2.6" fill="%s"/>' % (W, PALETTE["red"], PALETTE["red"], PALETTE["red"])),

    ("sys_meeting", "家庭会议", "系统", "blue", "开会 讨论 说话",
     '<path d="M28 42h50a8 8 0 0 1 8 8v20a8 8 0 0 1-8 8H50l-14 12V78h-8a8 8 0 0 1-8-8V50a8 8 0 0 1 8-8z" fill="%s"/>'
     '<path d="M41 56h28M41 68h18" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, PALETTE["blue"])),

    ("sys_calendar", "日历", "系统", "teal", "日期 假期 周",
     '<rect x="28" y="34" width="64" height="58" rx="9" fill="%s"/>'
     '<rect x="28" y="32" width="64" height="16" rx="8" fill="%s"/>'
     '<path d="M44 26v10M76 26v10" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
     '<path d="M42 62h12M42 76h12M64 62h12M64 76h12" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, PALETTE["teal"], PALETTE["teal"], PALETTE["teal"])),

    ("sys_clock", "时间", "系统", "indigo", "时钟 期限 加时",
     '<circle cx="60" cy="60" r="27" fill="%s"/>'
     '<path d="M60 44v18l13 8" stroke="%s" stroke-width="5" fill="none" stroke-linecap="round"/>'
     '<path d="M60 26v8M60 86v8M26 60h8M86 60h8" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, PALETTE["indigo"], W)),

    ("sys_award", "成就", "系统", "gold", "奖杯 第一 表扬",
     '<path d="M40 30h40v20a20 20 0 0 1-40 0z" fill="%s"/>'
     '<path d="M40 40c-9 0-11-16-2-16M80 40c9 0 11-16 2-16" fill="none" stroke="%s" stroke-width="4.5"/>'
     '<path d="M60 70v14" stroke="%s" stroke-width="5"/>'
     '<rect x="46" y="84" width="28" height="9" rx="3" fill="%s"/>' % (W, W, W, PALETTE["gold"])),

    ("sys_holiday", "假期", "系统", "sky", "放假 暑假 寒假 太阳",
     '<circle cx="60" cy="52" r="16" fill="%s"/>'
     '<path d="M60 24v8M60 72v8M32 52h8M80 52h8M41 33l6 6M79 33l-6 6M79 71l-6-6M41 71l6-6" stroke="%s" stroke-width="4" stroke-linecap="round"/>' % (W, W)),

    ("sys_shield", "规则", "系统", "grey", "保护 红线 不可改",
     '<path d="M60 24l26 10v22c0 18-12 29-26 35-14-6-26-17-26-35V34z" fill="%s"/>'
     '<path d="M48 58l8 8 16-16" stroke="%s" stroke-width="5.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' % (W, PALETTE["grey"])),
]

# ---------------------------------------------------------------------------
# emoji 兜底：图标再全也盖不住「孩子今天想要个恐龙」这种事。
# 分组名尽量短，选择器里要横向排按钮。
# ---------------------------------------------------------------------------
EMOJI_GROUPS = [
    ("笑脸", "😀 😃 😄 😁 😆 😅 😊 🙂 😉 😍 😘 😜 🤪 🤗 🤔 😐 😴 😢 😤 😡 🥳 😎 🤩 😇"),
    ("人物", "👶 👦 👧 👨 👩 🧑‍🎓 👮 🦸 🧙 🦊 🐻 🐼 🦁 🐯 🐨 🐵 🐶 🐱 🐭 🐹 🐰"),
    ("动物", "🦄 🐴 🐷 🐮 🐔 🐤 🦆 🐸 🐢 🐍 🐙 🦋 🐝 🐞 🐌 🐳 🐬 🐟 🦈 🐊 🦖 🦕"),
    ("植物", "🌵 🌲 🌳 🌴 🌱 🌿 ☘️ 🍀 🍁 🍂 🍃 🌾 🌷 🌹 🌺 🌸 🌼 🌻 🌞 🌝 ⭐ 🌟"),
    ("吃的", "🍎 🍊 🍋 🍌 🍉 🍇 🍓 🍒 🍑 🥝 🍍 🥥 🥕 🌽 🍞 🧀 🥐 🥨 🍕 🍔 🌮"),
    ("饮料", "🍦 🍰 🎂 🍮 🍬 🍭 🍫 🍩 🍪 🥛 ☕ 🍵 🧋 🥤 🍺 🥂 🍾"),
    ("活动", "⚽ 🏀 🏈 🎾 🏐 🎱 🏓 🏸 🥊 🎯 🎳 🎮 🧩 🎲 🎰 🎨 🎬 🎤 🎧 🎹 🥁 🎺"),
    ("出行", "🚗 🚕 🚙 🚌 🚎 🏎 🚓 🚑 🚒 🚚 🚲 🛴 🛹 ✈️ 🚀 🛸 🚂 🚄 🚢 ⛵ 🗺️ 🧭"),
    ("天气", "☀️ ⛅ ☁️ 🌧️ ⛈️ ❄️ ⛄ 🌈 🌊 💧 🔥 ✨ 💫 ⚡ 🌙 🌍"),
    ("物品", "📚 📖 📝 ✏️ 🖊️ 📏 📐 🎒 💼 📦 🎁 🏆 🥇 🎖️ 🔑 🔒 💡 🔦 🕯️ 🧸 🎈 🎏"),
    ("建筑", "🏠 🏡 🏰 🗼 🗽 ⛲ 🏫 🏥 🏦 🏪 ⛺ 🌁 🌃 🌆 🌉 🎡 🎢 🎠 ⛱️ 🏖️"),
    ("符号", "❤️ 🧡 💛 💚 💙 💜 🖤 💯 💢 💥 💫 ❌ ✅ ⚠️ ❓ ❗ 🔔 🔕 💎 🔮 🧿 🎯 🏁"),
]

# 汉字兜底：系统原来那七个维度是「心 / 智 / 力 / 伴 / 匠 / 洁 / 序」，
# 这套字孩子已经认熟了，而且中文单字本身就能当图形使。选择器里单占一档，
# 想用回原来的样子随时能点回去。
CHAR_GROUPS = [
    ("汉字", "心 智 力 伴 匠 洁 序"),
    ("常用字", "读 写 算 琴 画 歌 球 泳 步 洗 刷 扫 擦 理 叠 收 搬 买 做 饭 吃 水 早 晚 睡 起 玩 帮 家 礼"),
]

HEADER = (
    "<!-- 家庭积分 · 图标。由 tools/build_icons.py 生成，不要手改 -->\n"
)


def build_one(token, body, bg):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        '<circle cx="60" cy="60" r="44" fill="%s"/>%s</svg>\n' % (bg, body)
    )


def main():
    if not os.path.isdir(OUT_SVG):
        os.makedirs(OUT_SVG)

    tokens = []
    for token, label, grp, bgname, keys, body in ICONS:
        bg = PALETTE[bgname]
        svg = HEADER + build_one(token, body, bg)
        with io.open(os.path.join(OUT_SVG, token + ".svg"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(svg)
        tokens.append({
            "t": token,
            "l": label,
            "g": grp,
            "k": keys,
        })

    lines = []
    lines.append("/* 图标清单。")
    lines.append(" * 由 tools/build_icons.py 生成，改图标请改那个脚本再跑一遍，别手改这个文件。")
    lines.append(" *")
    lines.append(" * t = token，就是存在数据库 icon 列里的那个字符串，同时也是 icons/<t>.svg 的文件名。")
    lines.append(" * l = 界面上显示的名字；g = 分组；k = 搜索时用得上的词。")
    lines.append(" *")
    lines.append(" * 图形全部自绘，无第三方素材，无授权问题。")
    lines.append(" */")
    lines.append("var ICONS = %s;" % json.dumps(tokens, ensure_ascii=False))
    emoji = [{"g": g, "items": s.split()} for g, s in EMOJI_GROUPS]
    total = sum(len(x["items"]) for x in emoji)
    lines.append("/* emoji 兜底：%d 个，分 %d 组。 */" % (total, len(emoji)))
    lines.append("var EMOJI_GROUPS = %s;" % json.dumps(emoji, ensure_ascii=False))
    chars = [{"g": g, "items": s.split()} for g, s in CHAR_GROUPS]
    ctotal = sum(len(x["items"]) for x in chars)
    lines.append("/* 汉字兜底：%d 个。系统原来那套「心 / 智 / 力 / 伴 / 匠 / 洁 / 序」就在这组里。 */" % ctotal)
    lines.append("var CHAR_GROUPS = %s;" % json.dumps(chars, ensure_ascii=False))
    lines.append("")

    with io.open(OUT_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print("SVG %d 个 -> %s" % (len(tokens), OUT_SVG))
    print("emoji %d 个，汉字 %d 个 -> %s" % (total, ctotal, OUT_JS))
    grps = {}
    for x in tokens:
        grps.setdefault(x["g"], 0)
        grps[x["g"]] += 1
    print("分组：%s" % "、".join("%s %d" % (k, v) for k, v in grps.items()))

    # 自检：token 重名、文件名非 ASCII、body 里出现没定义的颜色变量
    seen = set()
    for token, label, grp, bgname, keys, body in ICONS:
        assert re.match(r"^[a-z0-9_]+$", token), "token 非法：" + token
        assert token not in seen, "token 重名：" + token
        seen.add(token)
        assert bgname in PALETTE, "底色没定义：" + bgname
    print("自检通过：%d 个 token 无重名" % len(seen))


if __name__ == "__main__":
    main()
