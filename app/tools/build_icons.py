# -*- coding: utf-8 -*-
"""
生成 web/icons/*.svg 与 web/icons.js。

为什么要这个脚本而不是直接手改文件：图标是六七十份 SVG，内容高度雷同
（同一个圆形底座，只有中间那几笔不同），手改必然出现某一笔写错、某个
viewBox 忘记改这类肉眼挑不出来的问题。这里把「底座 + 颜色」收成一行，
改一个图标只动 body 这一个字符串，重跑一遍就全省同步。

视觉语言（v41 整套重画）：
  · 120 版心，圆形底 r=46，右下角压一道 10% 深色月牙做体积 —— 全套共用
    同一道，凑在一起才像一套，不像七个人各画各的。
  · 图形一律白色实心，只有「眼睛 / 表盘刻度」这类必须空的地方才用底色
    挖（{bg}）。深色 #2f3b50 只做少量点缀，不拿来画主体。
  · 不用 stroke-only 的细线稿：手机上缩到 20px 时细线会糊成一团。真要用
    线，线宽不低于 5。
  · 图形落在 26~94 这一段里，四周留白一致。

宝箱七档单独一组，配色照抄孩子端 web/candy/i-chest-*.svg
（木 #B8824A / 铜 #C4793C / 银 #C3CAD6 / 金 #FFC93C / 钻 #6FC8F5 /
王 #8B6BFF / 完满 #FF9FCE，描边各自那支深色）。两处画的是同一只箱子：
孩子端宝箱页那七只，和家长在「给它们换张图」里挑的，必须长得一样 ——
不同步的话，家长挑的箱子跟孩子看到的就不是同一个东西。

「任务」那一组（quest_*）是给发活时配的那张图用的，18 张，走的不是
「读书 / 洗碗」这种具体行为，而是游戏里认的那套符号：悬赏令、目标靶、
钥匙、勋章、沙漏、行囊。理由是大厅里孩子先看见的就是这张图，一张
「今天有什么活」的告示，比一张「洗碗」更配得上那个位置；真要具体到
某一件事，隔壁「日常」那 24 张随时能挑。这一组排在 ICONS 最前面，
配图面板一打开就先看到它。

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
    # 任务那一组比别的组张数多（18 张），底色不够分会撞成一片，
    # 借一支介于紫与蓝之间的补上。
    "violet": "#a98be0",
    # 宝箱七档的底色。比箱子本体浅一档，箱子压在上面才看得出来；
    # 数值照孩子端那七只箱盖的颜色。
    "wood": "#E7C79E", "copper": "#EFD3B4", "silver": "#DFE5EC",
    "goldbox": "#FFE7A8", "diamond": "#C9EEFF", "king": "#DCD3FF",
    "perfect": "#FFDCEB",
}


# ---------------------------------------------------------------------------
# 宝箱：七档同一副骨架，只换配色。
#
# 现行这套（CRATES）是 2026-09-22 改版定的：扁平正面箱，没有圆底，
# 骨架直接照搬设计稿画板 728497723585730 的七列箱图（26 版心）。
# 不带圆底是有意的 —— 箱子的颜色本身就是档位，再垫一层同色圆底，
# 七只箱子远看全一样；去掉圆底，颜色直接顶到边上，一眼分得出。
# 同一个文件在宝箱页七列画 26、在能量卡那只大箱画 118，
# 不再像原来那样留两幅画（改一处忘一处）。
#
# 底下那七只带圆底的（BXOLD）是上一版的样子，留在图库里当备选，
# 家长在「给它们换张图」里还能挑回来。
# ---------------------------------------------------------------------------
def crate_body(lid, body):
    return (
        '<path d="M4 11c0-3.4 4-6 9-6s9 2.6 9 6v1H4z" fill="%s"/>'
        '<rect x="4" y="12" width="18" height="9" rx="2" fill="%s"/>'
        '<rect x="4" y="15.8" width="18" height="1.3" fill="%s" opacity=".35"/>'
        '<rect x="11.5" y="10.5" width="3" height="4.5" rx="1" fill="#FFE9A8"/>'
        '<circle cx="13" cy="13" r=".75" fill="%s"/>'
        % (lid, body, body, body)
    )


# (token, 显示名, 箱盖色, 箱体色, 搜索词)
CRATES = [
    ("bx_wood", "木箱", "#A9754A", "#6B4213", "木 一档 7 分"),
    ("bx_copper", "铜箱", "#B07B4A", "#8A3E0C", "铜 二档 14 分"),
    ("bx_silver", "银箱", "#7C8794", "#4E5A68", "银 三档 21 分"),
    ("bx_gold", "金箱", "#B57A1F", "#7A520E", "金 四档 28 分"),
    ("bx_diamond", "钻石箱", "#2E8CA5", "#1D6273", "钻 五档 35 分"),
    ("bx_king", "王者箱", "#7B4FB0", "#523080", "王 六档 42 分"),
    ("bx_perfect", "完美箱", "#D6537F", "#9A2F52", "完满 七档 49 分"),
]


# 宝箱（旧）：七档同一副骨架，只换配色和顶上那件小装饰。
# 骨架照抄 web/candy/i-chest-*.svg，22 版心放大到 120 版心（约 ×2.7）。
def chest_body(lid, body, stroke, ornament=""):
    return (
        '<path d="M30 59c0-11 8-19 18-19h24c10 0 18 8 18 19z" fill="%s" '
        'stroke="%s" stroke-width="4" stroke-linejoin="round"/>'
        '<rect x="30" y="59" width="60" height="31" rx="7" fill="%s" '
        'stroke="%s" stroke-width="4"/>'
        '<path d="M30 59h60" stroke="%s" stroke-width="3"/>%s'
        % (lid, stroke, body, stroke, stroke, ornament)
    )


BOXES = [
    # (token, 显示名, 底色, 箱盖, 箱体, 描边, 顶上的小装饰, 搜索词)
    ("bxold_wood", "木箱·旧", "wood", "#D9A063", "#B8824A", "#6B4213",
     '<path d="M32 68h56M32 80h56" stroke="#6B4213" stroke-width="3" opacity=".5"/>',
     "木 一档 7 分"),
    ("bxold_copper", "铜箱·旧", "copper", "#E3A96E", "#C4793C", "#8A3E0C",
     '<path d="M36 76h48" stroke="#8A3E0C" stroke-width="4" stroke-linecap="round"/>',
     "铜 二档 14 分"),
    ("bxold_silver", "银箱·旧", "silver", "#EDF1F6", "#C3CAD6", "#76808F",
     '<rect x="53" y="63" width="14" height="16" rx="4" fill="#76808F"/>',
     "银 三档 21 分"),
    ("bxold_gold", "金箱·旧", "goldbox", "#FFD76B", "#FFC93C", "#B87A0C",
     '<rect x="53" y="63" width="14" height="16" rx="4" fill="#B87A0C"/>'
     '<circle cx="74" cy="50" r="4" fill="#ffffff" opacity=".9"/>',
     "金 四档 28 分"),
    ("bxold_diamond", "钻石箱·旧", "diamond", "#B7E7FF", "#6FC8F5", "#2F7FE8",
     '<path d="M60 42l11 8-11 8-11-8z" fill="#EAF8FF" stroke="#2F7FE8" '
     'stroke-width="3" stroke-linejoin="round"/>',
     "钻 五档 35 分"),
    ("bxold_king", "王者箱·旧", "king", "#C9BAFF", "#8B6BFF", "#4B2FB8",
     '<path d="M48 47l4-15 8 10 8-10 4 15z" fill="#FFC93C" stroke="#4B2FB8" '
     'stroke-width="3" stroke-linejoin="round"/>',
     "王 六档 42 分"),
    ("bxold_perfect", "完美箱·旧", "perfect", "#FFC9E4", "#FF9FCE", "#C2185B",
     '<path d="M60 24l4.5 9 10 1.5-7 7 1.6 10-9.1-5-9.1 5 1.6-10-7-7 10-1.5z" '
     'fill="#FFE9A8" stroke="#C2185B" stroke-width="3" stroke-linejoin="round"/>',
     "完满 七档 49 分"),
]

# 通用箱子：不带档位，任务与心愿配图的兜底用这一只。
RW_BOX = chest_body("#D9A063", "#B8824A", "#6B4213",
                    '<rect x="53" y="63" width="14" height="16" rx="4" fill="#6B4213"/>')
RW_BOX_OPEN = (
    '<path d="M40 44c0-9 8-16 20-16s20 7 20 16z" fill="#D9A063" stroke="#6B4213" '
    'stroke-width="4" stroke-linejoin="round"/>'
    '<rect x="30" y="52" width="60" height="34" rx="7" fill="#B8824A" '
    'stroke="#6B4213" stroke-width="4"/>'
    '<path d="M52 40l6-10 4 8 6-10 4 12" fill="none" stroke="#f2c55c" '
    'stroke-width="4" stroke-linecap="round"/>'
)

# 券：同一张票，右半边换一件小东西表示是哪一种。
def ticket_body(emblem):
    return (
        '<path d="M28 42h64v12a6 6 0 0 0 0 12v12H28V66a6 6 0 0 0 0-12z" fill="{w}"/>'
        '<path d="M62 50v28" stroke="{bg}" stroke-width="3" stroke-dasharray="4 5"/>'
        '<path d="M40 54h12M40 66h12" stroke="{bg}" stroke-width="4" '
        'stroke-linecap="round"/>' + emblem
    )


# (token, 显示名, 分组, 底色, 搜索关键词, 图形)
# 图形坐标范围：圆心 (60,60)、半径 46，主体尽量落在 26~94 这一段里。
# body 里三个占位符：{w} 白、{bg} 底色（挖空用）、{d} 深蓝灰。
ICONS = [
    # 零、任务（发活时配的那张图，走游戏里那一套语汇） ----------------------
    # 大厅里孩子先看见的就是这张图，所以这一组排在最前面，配图面板一打开
    # 先看到的是它。默认那张是悬赏令 —— 一张贴出来的活的本来面目。
    ("quest_scroll", "悬赏令", "任务", "red", "任务 悬赏 卷轴 布告",
     '<rect x="36" y="34" width="48" height="52" fill="{w}"/>'
     '<rect x="30" y="26" width="60" height="12" rx="6" fill="{w}"/>'
     '<rect x="30" y="82" width="60" height="12" rx="6" fill="{w}"/>'
     '<path d="M46 50h28M46 62h28M46 74h18" stroke="{bg}" stroke-width="4" '
     'stroke-linecap="round"/>'),

    ("quest_board", "任务板", "任务", "brown", "布告栏 板子 张贴 接活",
     '<rect x="28" y="28" width="64" height="64" rx="9" fill="{d}" opacity=".22"/>'
     '<rect x="38" y="40" width="44" height="34" rx="4" fill="{w}"/>'
     '<path d="M46 50h28M46 60h28M46 68h16" stroke="{d}" stroke-width="3.5" '
     'stroke-linecap="round" opacity=".45"/>'
     '<circle cx="60" cy="36" r="4.5" fill="{w}"/>'),

    ("quest_target", "目标", "任务", "rose", "靶心 达标 命中 完成",
     '<circle cx="60" cy="60" r="30" fill="{w}"/>'
     '<circle cx="60" cy="60" r="19" fill="{bg}"/>'
     '<circle cx="60" cy="60" r="9" fill="{w}"/>'),

    ("quest_flag", "旗帜", "任务", "orange", "终点 插旗 达成 目标点",
     '<path d="M38 26v68" stroke="{w}" stroke-width="7" stroke-linecap="round"/>'
     '<path d="M44 32h42l-11 12 11 12H44z" fill="{w}"/>'
     '<rect x="28" y="88" width="40" height="8" rx="4" fill="{w}"/>'),

    ("quest_map", "藏宝图", "任务", "yellow", "地图 冒险 寻路 宝",
     '<path d="M28 36l22-8v56l-22 8z" fill="{w}" opacity=".8"/>'
     '<path d="M50 28l20 8v56l-20-8z" fill="{w}"/>'
     '<path d="M70 36l22-8v56l-22 8z" fill="{w}" opacity=".8"/>'
     '<path d="M40 68c8-10 18-4 24-12" stroke="{bg}" stroke-width="3.5" fill="none" '
     'stroke-dasharray="5 5"/>'
     '<path d="M74 62l10 10M84 62l-10 10" stroke="{d}" stroke-width="4" '
     'stroke-linecap="round"/>'),

    ("quest_compass", "罗盘", "任务", "teal", "方向 指南针 探索 找路",
     '<circle cx="60" cy="60" r="30" fill="{w}"/>'
     '<path d="M60 34l12 26H48z" fill="{d}" opacity=".72"/>'
     '<path d="M60 86l-12-26h24z" fill="{bg}"/>'
     '<circle cx="60" cy="60" r="5" fill="{w}"/>'),

    ("quest_key", "钥匙", "任务", "grey", "钥匙 解锁 开启 通关",
     '<circle cx="45" cy="45" r="16" fill="none" stroke="{w}" stroke-width="9"/>'
     '<path d="M56 56l24 24" stroke="{w}" stroke-width="9" stroke-linecap="round"/>'
     '<path d="M67 67l-9 9M76 76l-9 9" stroke="{w}" stroke-width="8" '
     'stroke-linecap="round"/>'),

    ("quest_medal", "勋章", "任务", "blue", "奖章 授勋 表现 表扬",
     '<path d="M46 26l14 30-10 8-14-30z" fill="{w}" opacity=".7"/>'
     '<path d="M74 26L60 56l10 8 14-30z" fill="{w}" opacity=".7"/>'
     '<circle cx="60" cy="74" r="18" fill="{w}"/>'
     '<path d="M60 64l3.5 7 8 1-6 6 1.5 8-7-4-7 4 1.5-8-6-6 8-1z" fill="{bg}"/>'),

    ("quest_crown", "皇冠", "任务", "purple", "冠军 第一 王者 厉害",
     '<path d="M32 78V40l16 14 12-20 12 20 16-14v38z" fill="{w}"/>'
     '<rect x="30" y="78" width="60" height="11" rx="5" fill="{w}"/>'
     '<circle cx="60" cy="46" r="4" fill="{bg}"/>'),

    ("quest_gem", "宝石", "任务", "sky", "钻石 稀有 珍贵 结晶",
     '<path d="M48 28h24l12 20-24 40-24-40z" fill="{w}"/>'
     '<path d="M48 28l-12 20h48L72 28z" fill="{w}" opacity=".72"/>'
     '<path d="M36 48h48M60 28v60" stroke="{bg}" stroke-width="3"/>'),

    ("quest_coin", "金币", "任务", "gold", "金币 报酬 赏钱 攒",
     '<circle cx="60" cy="60" r="30" fill="{w}"/>'
     '<circle cx="60" cy="60" r="21" fill="none" stroke="{bg}" stroke-width="4"/>'
     '<path d="M60 46l4 9 10 1-7.5 7 2 10-8.5-5-8.5 5 2-10-7.5-7 10-1z" fill="{bg}"/>'),

    ("quest_potion", "药水", "任务", "green", "补血 能量 补给 恢复",
     '<rect x="48" y="24" width="24" height="10" rx="4" fill="{w}"/>'
     '<rect x="52" y="30" width="16" height="24" fill="{w}"/>'
     '<circle cx="60" cy="70" r="24" fill="{w}"/>'
     '<path d="M44 74a16 16 0 0 0 32 0z" fill="{bg}"/>'
     '<circle cx="52" cy="62" r="3.5" fill="{bg}"/>'
     '<circle cx="66" cy="56" r="3" fill="{bg}" opacity=".7"/>'),

    ("quest_sword", "剑", "任务", "indigo", "挑战 对决 打怪 勇气",
     '<path d="M60 24l8 14v34H52V38z" fill="{w}"/>'
     '<rect x="38" y="66" width="44" height="9" rx="4.5" fill="{w}"/>'
     '<rect x="55" y="75" width="10" height="20" rx="4" fill="{w}"/>'),

    ("quest_torch", "火把", "任务", "blush", "火把 照路 引路 点亮",
     '<rect x="55" y="64" width="10" height="28" rx="5" fill="{w}"/>'
     '<rect x="45" y="58" width="30" height="9" rx="4" fill="{w}"/>'
     '<path d="M60 20c10 12 17 20 17 27 0 10-8 17-17 17s-17-7-17-17c0-7 7-15 17-27z" fill="{w}"/>'
     '<path d="M60 44c5 6 8 10 8 14 0 5-4 8-8 8s-8-3-8-8c0-4 3-8 8-14z" fill="{bg}" '
     'opacity=".45"/>'),

    ("quest_hourglass", "沙漏", "任务", "mint", "限时 倒计时 计时 时间",
     '<rect x="34" y="26" width="52" height="9" rx="4" fill="{w}"/>'
     '<rect x="34" y="85" width="52" height="9" rx="4" fill="{w}"/>'
     '<path d="M44 35h32v9c0 8-16 12-16 16s16 8 16 16v9H44v-9c0-8 16-12 16-16'
     's-16-8-16-16z" fill="{w}"/>'
     '<path d="M50 78h20l-10-14z" fill="{bg}" opacity=".65"/>'),

    ("quest_bag", "行囊", "任务", "brown", "背包 准备 出门 带上",
     '<path d="M34 46h52v34a12 12 0 0 1-12 12H46a12 12 0 0 1-12-12z" fill="{w}"/>'
     '<path d="M48 46c0-8 5-14 12-14s12 6 12 14" fill="none" stroke="{w}" '
     'stroke-width="6"/>'
     '<rect x="34" y="56" width="52" height="7" fill="{bg}" opacity=".45"/>'
     '<circle cx="60" cy="74" r="6" fill="{bg}"/>'),

    ("quest_door", "下一关", "任务", "violet", "传送门 关卡 通过 进入",
     '<path d="M36 86V50a24 24 0 0 1 48 0v36z" fill="{w}"/>'
     '<rect x="28" y="84" width="64" height="9" rx="4" fill="{w}"/>'
     '<circle cx="72" cy="68" r="5" fill="{bg}"/>'),

    # 一、七个维度 ----------------------------------------------------------
    ("dim_heart", "心能", "维度", "red", "心 情绪 平静",
     '<path d="M60 86C39 68 29 57 29 45c0-10 8-18 18-18 6 0 11 3 13 8 2-5 7-8 13-8 '
     '10 0 18 8 18 18 0 12-10 23-31 41z" fill="{w}"/>'),

    ("dim_study", "智识", "维度", "blue", "学习 书 专注",
     '<path d="M60 42c-8-6-19-7-27-4v44c9-3 20-2 27 4 8-6 19-7 27-4V38c-8-3-19-2-27 4z" fill="{w}"/>'
     '<path d="M60 42v44" stroke="{bg}" stroke-width="4"/>'
     '<path d="M39 54h14M39 66h14M67 54h14M67 66h14" stroke="{bg}" stroke-width="3" '
     'stroke-linecap="round"/>'),

    ("dim_vigor", "活力", "维度", "orange", "吃饭 碗 饭菜 营养",
     '<path d="M68 26 38 68h19l-6 28 27-43H58z" fill="{w}"/>'),

    ("dim_bond", "羁绊", "维度", "blush", "家人 关心 一起",
     '<circle cx="44" cy="46" r="11" fill="{w}"/>'
     '<path d="M28 86c0-9 7-16 16-16s16 7 16 16z" fill="{w}"/>'
     '<circle cx="77" cy="46" r="11" fill="{w}"/>'
     '<path d="M61 86c0-9 7-16 16-16s16 7 16 16z" fill="{w}"/>'
     '<path d="M52 72c5 5 11 5 16 0" stroke="{bg}" stroke-width="4" fill="none" '
     'stroke-linecap="round"/>'),

    ("dim_craft", "匠力", "维度", "brown", "家务 动手 做",
     '<g transform="rotate(45 60 60)">'
     '<rect x="40" y="26" width="40" height="18" rx="6" fill="{w}"/>'
     '<rect x="54" y="40" width="12" height="46" rx="6" fill="{w}"/>'
     '<rect x="44" y="31" width="12" height="8" rx="3" fill="{bg}"/></g>'),

    ("dim_clean", "洁净", "维度", "teal", "卫生 干净 洗",
     '<circle cx="47" cy="53" r="14" fill="{w}"/>'
     '<circle cx="72" cy="65" r="10" fill="{w}" opacity=".92"/>'
     '<circle cx="55" cy="79" r="6" fill="{w}" opacity=".85"/>'
     '<path d="M32 34c6-5 14-6 20-1" stroke="{w}" stroke-width="5" fill="none" '
     'stroke-linecap="round"/>'),

    ("dim_order", "秩序", "维度", "purple", "归位 整洁 房间",
     '<rect x="27" y="29" width="26" height="26" rx="7" fill="{w}" opacity=".55"/>'
     '<rect x="67" y="29" width="26" height="26" rx="7" fill="{w}" opacity=".55"/>'
     '<rect x="27" y="67" width="26" height="26" rx="7" fill="{w}" opacity=".55"/>'
     '<rect x="67" y="67" width="26" height="26" rx="7" fill="{w}"/>'
     '<path d="M73 80l6 7 12-14" stroke="{bg}" stroke-width="6" fill="none" '
     'stroke-linecap="round" stroke-linejoin="round"/>'),

    # 二、日常 --------------------------------------------------------------
    ("task_read", "读书", "日常", "indigo", "书 阅读 看",
     '<rect x="30" y="70" width="56" height="12" rx="5" fill="{w}"/>'
     '<rect x="36" y="56" width="48" height="12" rx="5" fill="{w}" opacity=".92"/>'
     '<rect x="43" y="42" width="38" height="12" rx="5" fill="{w}" opacity=".84"/>'
     '<path d="M60 42v12" stroke="{bg}" stroke-width="3"/>'),

    ("task_write", "写字", "日常", "yellow", "练字 笔 书法",
     '<path d="M36 84l5-14 30-30a7 7 0 0 1 10 10L51 80l-14 5z" fill="{w}"/>'
     '<path d="M41 70l11 11" stroke="{bg}" stroke-width="4"/>'
     '<path d="M36 84l14 5-9-19z" fill="{d}"/>'),

    ("task_homework", "作业", "日常", "blue", "功课 学校 写",
     '<rect x="34" y="28" width="52" height="62" rx="10" fill="{w}"/>'
     '<rect x="50" y="22" width="20" height="12" rx="6" fill="{w}"/>'
     '<path d="M45 46h30M45 58h30" stroke="{bg}" stroke-width="4" stroke-linecap="round"/>'
     '<path d="M50 70l7 8 13-15" stroke="{bg}" stroke-width="5.5" fill="none" '
     'stroke-linecap="round" stroke-linejoin="round"/>'),

    ("task_piano", "练琴", "日常", "purple", "音乐 乐器 弹",
     '<rect x="26" y="44" width="68" height="38" rx="8" fill="{w}"/>'
     '<rect x="40" y="44" width="10" height="24" rx="4" fill="{bg}"/>'
     '<rect x="55" y="44" width="10" height="24" rx="4" fill="{bg}"/>'
     '<rect x="70" y="44" width="10" height="24" rx="4" fill="{bg}"/>'
     '<rect x="26" y="74" width="68" height="8" rx="4" fill="{bg}" opacity=".55"/>'),

    ("task_sport", "运动", "日常", "orange", "球 足球 锻炼",
     '<circle cx="60" cy="60" r="28" fill="{w}"/>'
     '<path d="M60 32l14 11-5 18H51l-5-18z" fill="none" stroke="{bg}" stroke-width="4"/>'
     '<path d="M51 61l5 18M69 61l-5 18M43 55l17 6 17-6" stroke="{bg}" stroke-width="3.5" '
     'fill="none"/>'),

    ("task_swim", "游泳", "日常", "sky", "水 泳池",
     '<circle cx="48" cy="44" r="10" fill="{w}"/>'
     '<path d="M38 62c6-5 14-5 18 0l14 12" stroke="{w}" stroke-width="7" fill="none" '
     'stroke-linecap="round"/>'
     '<path d="M34 78c8-6 18-6 26 0s18 6 26 0M34 90c8-6 18-6 26 0s18 6 26 0" '
     'stroke="{w}" stroke-width="5.5" fill="none" stroke-linecap="round"/>'),

    ("task_bike", "骑车", "日常", "green", "自行车 户外",
     '<circle cx="36" cy="72" r="15" fill="none" stroke="{w}" stroke-width="6"/>'
     '<circle cx="84" cy="72" r="15" fill="none" stroke="{w}" stroke-width="6"/>'
     '<path d="M36 72l16-26h20l16 26M52 46l10 26" stroke="{w}" stroke-width="6" '
     'fill="none" stroke-linecap="round"/>'),

    ("task_walk", "遛弯", "日常", "teal", "散步 走路 遛狗",
     '<circle cx="52" cy="38" r="9" fill="{w}"/>'
     '<path d="M52 47l-9 20 3 20M52 47l11 15 5 25M48 47l-5 20 5 20" stroke="{w}" '
     'stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'),

    ("task_bath", "洗澡", "日常", "sky", "沐浴 晚上",
     '<path d="M28 62h64v6a16 16 0 0 1-16 16H44a16 16 0 0 1-16-16z" fill="{w}"/>'
     '<path d="M28 62c0-9 6-15 14-15h36c8 0 14 6 14 15" fill="none" stroke="{w}" '
     'stroke-width="6"/>'
     '<circle cx="44" cy="36" r="6" fill="{w}" opacity=".9"/>'
     '<circle cx="60" cy="30" r="4.5" fill="{w}" opacity=".8"/>'
     '<circle cx="74" cy="38" r="5" fill="{w}" opacity=".85"/>'),

    ("task_tooth", "刷牙", "日常", "green", "牙齿 卫生",
     '<path d="M60 28c-12 0-20 8-20 19 0 9 3 14 4 22 1 7 6 21 16 21s15-14 16-21'
     'c1-8 4-13 4-22 0-11-8-19-20-19z" fill="{w}"/>'
     '<path d="M52 76c2 8 4 12 8 12s6-4 8-12" stroke="{bg}" stroke-width="4" fill="none"/>'),

    ("task_laundry", "洗衣", "日常", "indigo", "洗衣机 衣服",
     '<rect x="30" y="30" width="60" height="66" rx="12" fill="{w}"/>'
     '<circle cx="60" cy="68" r="20" fill="{bg}"/>'
     '<circle cx="60" cy="68" r="13" fill="{w}"/>'
     '<rect x="38" y="38" width="16" height="6" rx="3" fill="{bg}"/>'
     '<circle cx="78" cy="41" r="4" fill="{bg}"/>'),

    ("task_dish", "洗碗", "日常", "yellow", "盘子 厨房",
     '<circle cx="60" cy="62" r="28" fill="{w}"/>'
     '<circle cx="60" cy="62" r="16" fill="{bg}" opacity=".85"/>'
     '<circle cx="40" cy="38" r="6" fill="{w}" opacity=".9"/>'
     '<circle cx="52" cy="30" r="4" fill="{w}" opacity=".8"/>'),

    ("task_cook", "做饭", "日常", "red", "厨房 锅 菜",
     '<path d="M30 54h60v22a16 16 0 0 1-16 16H46a16 16 0 0 1-16-16z" fill="{w}"/>'
     '<rect x="24" y="46" width="72" height="10" rx="5" fill="{w}"/>'
     '<path d="M36 38c6-6 12-6 18 0M66 38c6-6 12-6 18 0" stroke="{w}" stroke-width="5" '
     'fill="none" stroke-linecap="round"/>'),

    ("task_tidy", "整理房间", "日常", "purple", "收拾 收纳 归位",
     '<path d="M32 52h56l-6 34H38z" fill="{w}"/>'
     '<rect x="28" y="44" width="64" height="10" rx="5" fill="{w}"/>'
     '<path d="M46 62v18M60 62v18M74 62v18" stroke="{bg}" stroke-width="3" '
     'stroke-linecap="round"/>'),

    ("task_trash", "倒垃圾", "日常", "grey", "垃圾桶 扔",
     '<path d="M38 42h44l-5 46a6 6 0 0 1-6 5H49a6 6 0 0 1-6-5z" fill="{w}"/>'
     '<rect x="32" y="34" width="56" height="10" rx="5" fill="{w}"/>'
     '<rect x="52" y="27" width="16" height="8" rx="4" fill="{w}"/>'
     '<path d="M50 56v26M70 56v26" stroke="{bg}" stroke-width="3.5" stroke-linecap="round"/>'),

    ("task_plant", "浇花", "日常", "green", "植物 水 阳台",
     '<path d="M42 58h36l-5 32a6 6 0 0 1-6 5H53a6 6 0 0 1-6-5z" fill="{w}"/>'
     '<rect x="38" y="50" width="44" height="10" rx="4" fill="{w}"/>'
     '<path d="M60 50V34M60 40c-8 0-12-4-12-9 6 0 11 3 12 9M60 44c6-2 9-6 9-11-5 1-9 5-9 11" '
     'stroke="{w}" stroke-width="5" fill="none" stroke-linecap="round"/>'),

    ("task_pet", "照顾宠物", "日常", "brown", "猫 狗 喂",
     '<circle cx="60" cy="62" r="22" fill="{w}"/>'
     '<path d="M40 47l-4-16 18 8M80 47l4-16-18 8" fill="{w}"/>'
     '<circle cx="52" cy="58" r="4" fill="{bg}"/>'
     '<circle cx="68" cy="58" r="4" fill="{bg}"/>'
     '<path d="M54 70c4 3 8 3 12 0" stroke="{bg}" stroke-width="3.5" fill="none" '
     'stroke-linecap="round"/>'),

    ("task_sleep", "早睡", "日常", "indigo", "睡觉 晚上 床",
     '<path d="M64 28a32 32 0 1 0 28 44A28 28 0 0 1 64 28z" fill="{w}"/>'
     '<circle cx="36" cy="44" r="4" fill="{w}" opacity=".85"/>'
     '<circle cx="46" cy="34" r="3" fill="{w}" opacity=".75"/>'),

    ("task_wake", "起床", "日常", "yellow", "闹钟 早上",
     '<circle cx="60" cy="64" r="24" fill="{w}"/>'
     '<path d="M60 50v14l11 8" stroke="{bg}" stroke-width="5" fill="none" '
     'stroke-linecap="round"/>'
     '<path d="M42 42L32 32M78 42l10-10" stroke="{w}" stroke-width="6" stroke-linecap="round"/>'
     '<circle cx="28" cy="28" r="7" fill="{w}"/><circle cx="92" cy="28" r="7" fill="{w}"/>'),

    ("task_meal", "吃饭", "日常", "orange", "饭 碗 点餐",
     '<path d="M26 56h68c0 18-15 32-34 32S26 74 26 56z" fill="{w}"/>'
     '<rect x="22" y="50" width="76" height="9" rx="4.5" fill="{w}"/>'
     '<path d="M48 40c6-6 12-6 18 0M62 40c4-4 8-6 12-5" stroke="{w}" stroke-width="5" '
     'fill="none" stroke-linecap="round"/>'),

    ("task_drink", "喝水", "日常", "sky", "水杯 牛奶",
     '<path d="M62 28l10 8-24 26" stroke="{w}" stroke-width="5" fill="none" '
     'stroke-linecap="round"/>'
     '<path d="M40 46h40l-4 40a7 7 0 0 1-7 6H51a7 7 0 0 1-7-6z" fill="{w}"/>'),

    ("task_pack", "收拾书包", "日常", "green", "书包 上学 准备",
     '<rect x="34" y="44" width="52" height="50" rx="14" fill="{w}"/>'
     '<path d="M46 44V34a14 14 0 0 1 28 0v10" fill="none" stroke="{w}" stroke-width="6"/>'
     '<rect x="48" y="66" width="24" height="16" rx="6" fill="{bg}"/>'),

    ("task_outdoor", "出去玩", "日常", "teal", "户外 公园 树",
     '<path d="M60 30l18 28H42z" fill="{w}"/>'
     '<path d="M60 46l22 34H38z" fill="{w}" opacity=".85"/>'
     '<rect x="55" y="78" width="10" height="14" rx="3" fill="{w}"/>'),

    ("task_help", "帮忙", "日常", "rose", "搭把手 一起",
     '<path d="M42 86V60c0-5 4-9 9-9s9 4 9 9V50c0-5 4-9 9-9s9 4 9 9v8c0-5 4-9 9-9s9 4 9 9'
     'v27c0 12-10 21-24 21s-21-9-21-21z" fill="{w}"/>'),

    # 三、奖励 --------------------------------------------------------------
    ("rw_stardust", "星尘", "奖励", "gold", "分 星星 积分",
     '<path d="M60 26l12 25 27 4-20 19 5 27-24-13-24 13 5-27-20-19 27-4z" fill="{w}"/>'),

    ("rw_box", "宝箱", "奖励", "brown", "箱子 开箱 档位", RW_BOX),

    ("rw_box_open", "开箱", "奖励", "brown", "打开 惊喜 完美", RW_BOX_OPEN),

    ("rw_level", "星球等级", "奖励", "purple", "等级 升级 行星",
     '<ellipse cx="60" cy="60" rx="38" ry="12" fill="none" stroke="{w}" stroke-width="6"/>'
     '<circle cx="60" cy="58" r="24" fill="{w}"/>'
     '<path d="M46 52a10 10 0 0 1 16-4" stroke="{bg}" stroke-width="4" fill="none" '
     'stroke-linecap="round"/>'
     '<circle cx="70" cy="66" r="6" fill="{bg}" opacity=".7"/>'),

    ("rw_money", "零花钱", "奖励", "gold", "钱 兑换 现金",
     '<rect x="26" y="42" width="68" height="40" rx="7" fill="{w}"/>'
     '<circle cx="60" cy="62" r="11" fill="none" stroke="{bg}" stroke-width="5"/>'
     '<path d="M36 62h10M74 62h10" stroke="{bg}" stroke-width="4" stroke-linecap="round"/>'),

    ("rw_double", "翻倍", "奖励", "orange", "双倍 乘二 加倍",
     '<path d="M60 28l22 22H38z" fill="{w}"/>'
     '<path d="M60 56l22 22H38z" fill="{w}" opacity=".82"/>'),

    ("rw_dice", "骰子", "奖励", "blue", "随机 重抽 运气",
     '<rect x="32" y="32" width="56" height="56" rx="14" fill="{w}"/>'
     '<circle cx="46" cy="46" r="6" fill="{bg}"/>'
     '<circle cx="60" cy="60" r="6" fill="{bg}"/>'
     '<circle cx="74" cy="74" r="6" fill="{bg}"/>'),

    ("rw_rocket", "加速", "奖励", "rose", "火箭 快 冲",
     '<path d="M60 26c12 10 18 24 18 38l-9 10H51l-9-10c0-14 6-28 18-38z" fill="{w}"/>'
     '<circle cx="60" cy="52" r="8" fill="{bg}"/>'
     '<path d="M42 62l-11 13 13-3zM78 62l11 13-13-3z" fill="{d}" opacity=".35"/>'
     '<path d="M52 78l8 12 8-12z" fill="{w}" opacity=".85"/>'),

    ("rw_gift", "礼物", "奖励", "red", "礼品 惊喜 兑换",
     '<rect x="28" y="52" width="64" height="40" rx="6" fill="{w}"/>'
     '<rect x="26" y="42" width="68" height="14" rx="5" fill="{w}"/>'
     '<path d="M60 42v50" stroke="{bg}" stroke-width="6"/>'
     '<circle cx="47" cy="34" r="12" fill="{w}"/><circle cx="73" cy="34" r="12" fill="{w}"/>'),

    ("rw_card", "道具卡", "奖励", "blue", "卡片 图鉴 收藏",
     '<rect x="30" y="34" width="60" height="52" rx="9" fill="{w}"/>'
     '<path d="M30 52h60" stroke="{bg}" stroke-width="4"/>'
     '<circle cx="60" cy="70" r="11" fill="{bg}" opacity=".85"/>'
     '<path d="M60 62l3 6 7 1-5 5 1 7-6-4-6 4 1-7-5-5 7-1z" fill="{w}"/>'),

    ("rw_fragment", "碎片", "奖励", "teal", "合成 拼图 换",
     '<path d="M40 30l20 8-6 24-18-6z" fill="{w}"/>'
     '<path d="M62 40l18 10-8 22-16-6z" fill="{w}" opacity=".85"/>'
     '<path d="M52 68l14 4-4 18-14-6z" fill="{w}" opacity=".7"/>'),

    ("rw_ticket", "券", "奖励", "pink", "票 通用",
     ticket_body('<path d="M66 58h20v6H66z" fill="{bg}"/>'
                 '<path d="M76 50l6 4-6 4z" fill="{bg}"/>')),

    ("rw_ticket_fun", "娱乐券", "奖励", "indigo", "屏幕 游戏 电视",
     ticket_body('<rect x="66" y="52" width="20" height="14" rx="3" fill="{bg}"/>'
                 '<path d="M76 56l6 4-6 4z" fill="{w}"/>')),

    ("rw_ticket_company", "陪伴券", "奖励", "green", "陪 父母 亲子",
     ticket_body('<circle cx="70" cy="57" r="5" fill="{bg}"/>'
                 '<circle cx="82" cy="57" r="5" fill="{bg}"/>'
                 '<path d="M64 70c0-4 3-6 6-6s6 2 6 6z" fill="{bg}" opacity=".75"/>')),

    ("rw_ticket_choice", "选择券", "奖励", "purple", "说了算 挑 决定",
     ticket_body('<path d="M68 62l5 6 10-13" stroke="{bg}" stroke-width="5" fill="none" '
                 'stroke-linecap="round" stroke-linejoin="round"/>')),

    ("rw_ticket_exempt", "豁免券", "奖励", "grey", "免一次 不做",
     ticket_body('<path d="M76 51l9 3v7c0 5-4 8-9 10-5-2-9-5-9-10v-7z" fill="{bg}"/>')),

    ("rw_ticket_friend", "好友券", "奖励", "rose", "朋友 同学 玩",
     ticket_body('<circle cx="71" cy="58" r="6" fill="{bg}"/>'
                 '<circle cx="84" cy="58" r="6" fill="{bg}" opacity=".7"/>')),

    ("rw_ticket_solo", "独处券", "奖励", "sky", "单独 一对一 出去",
     ticket_body('<circle cx="78" cy="55" r="6" fill="{bg}"/>'
                 '<path d="M69 70c0-5 4-9 9-9s9 4 9 9z" fill="{bg}"/>')),

    ("rw_mute", "不催", "奖励", "grey", "安静 不说话",
     '<path d="M60 32c-13 0-20 9-20 19 0 9-5 13-7 15h54c-2-2-7-6-7-15 0-10-7-19-20-19z" fill="{w}"/>'
     '<path d="M46 84c-2-3-3-6-3-9h10c0 3-1 6-3 9z" fill="{w}"/>'
     '<path d="M34 82L86 30" stroke="{bg}" stroke-width="7" stroke-linecap="round"/>'),

    # 四、宝箱七档（现行：扁平箱，配色照设计稿）
] + [(t, n, "宝箱", "", k, crate_body(lid, bd))
     for (t, n, lid, bd, k) in CRATES] + [
    # 四之二、宝箱七档（旧：带圆底那一版，留作备选）
] + [(t, n, "宝箱·旧", bg, k, chest_body(lid, bd, st, orn))
     for (t, n, bg, lid, bd, st, orn, k) in BOXES] + [

    # 五、系统 --------------------------------------------------------------
    ("sys_wish", "心愿", "系统", "pink", "许愿 愿望 目标",
     '<path d="M60 24c3 15 10 22 26 25-16 3-23 10-26 25-3-15-10-22-26-25 16-3 23-10 26-25z" fill="{w}"/>'
     '<circle cx="84" cy="34" r="4" fill="{w}" opacity=".8"/>'
     '<circle cx="34" cy="76" r="3.5" fill="{w}" opacity=".7"/>'),

    ("sys_pool", "许愿池", "系统", "mint", "基金 存钱罐 攒",
     '<path d="M40 44h40v36a12 12 0 0 1-12 12H52a12 12 0 0 1-12-12z" fill="{w}"/>'
     '<rect x="34" y="38" width="52" height="9" rx="4.5" fill="{w}"/>'
     '<path d="M46 56h28" stroke="{bg}" stroke-width="4" stroke-linecap="round"/>'
     '<circle cx="60" cy="74" r="9" fill="{bg}"/>'),

    ("sys_guardian", "守护灵", "系统", "purple", "宠物 精灵 永久",
     '<path d="M60 30c16 0 26 12 26 28v14c0 6-4 10-9 10h-6l-5 10-6-10H44c-6 0-11-5-11-11'
     'V58c0-16 11-28 27-28z" fill="{w}"/>'
     '<circle cx="51" cy="56" r="5" fill="{bg}"/><circle cx="69" cy="56" r="5" fill="{bg}"/>'
     '<path d="M52 70c5 5 11 5 16 0" stroke="{bg}" stroke-width="4" fill="none" '
     'stroke-linecap="round"/>'),

    ("sys_title", "称号", "系统", "gold", "徽章 头衔 永久",
     '<path d="M46 60l-6 34 10-6 10 6 10-6-6-34z" fill="{w}" opacity=".9"/>'
     '<circle cx="60" cy="46" r="22" fill="{w}"/>'
     '<circle cx="60" cy="46" r="11" fill="{bg}"/>'),

    ("sys_skin", "皮肤", "系统", "rose", "外观 换装 颜色",
     '<path d="M60 28l14 7-5 8-5-3v34a4 4 0 0 1-4 4H50a4 4 0 0 1-4-4V40l-5 3-5-8z" fill="{w}"/>'),

    ("sys_repair", "修复任务", "系统", "red", "道歉 补偿 补救",
     '<path d="M60 26l34 34-34 34-34-34z" fill="{w}"/>'
     '<path d="M60 46v28M46 60h28" stroke="{bg}" stroke-width="7" stroke-linecap="round"/>'),

    ("sys_meeting", "家庭会议", "系统", "blue", "开会 讨论 说话",
     '<rect x="26" y="34" width="60" height="40" rx="12" fill="{w}"/>'
     '<path d="M44 74l-4 14 16-14z" fill="{w}"/>'
     '<circle cx="42" cy="54" r="4" fill="{bg}"/>'
     '<circle cx="56" cy="54" r="4" fill="{bg}"/>'
     '<circle cx="70" cy="54" r="4" fill="{bg}"/>'),

    ("sys_calendar", "日历", "系统", "teal", "日期 假期 周",
     '<rect x="28" y="34" width="64" height="58" rx="10" fill="{w}"/>'
     '<path d="M38 34h44a10 10 0 0 1 10 10v6H28v-6a10 10 0 0 1 10-10z" fill="{bg}"/>'
     '<rect x="42" y="26" width="8" height="14" rx="4" fill="{w}"/>'
     '<rect x="70" y="26" width="8" height="14" rx="4" fill="{w}"/>'
     '<circle cx="46" cy="64" r="5" fill="{bg}"/><circle cx="60" cy="64" r="5" fill="{bg}"/>'
     '<circle cx="74" cy="64" r="5" fill="{bg}"/>'
     '<circle cx="46" cy="80" r="5" fill="{bg}" opacity=".55"/>'
     '<circle cx="60" cy="80" r="5" fill="{bg}" opacity=".55"/>'),

    ("sys_clock", "时间", "系统", "indigo", "时钟 期限 加时",
     '<circle cx="60" cy="60" r="28" fill="{w}"/>'
     '<path d="M60 42v18l14 9" stroke="{bg}" stroke-width="6" fill="none" stroke-linecap="round"/>'
     '<circle cx="60" cy="60" r="4.5" fill="{bg}"/>'),

    ("sys_award", "成就", "系统", "gold", "奖杯 第一 表扬",
     '<path d="M40 30h40v20a20 20 0 0 1-40 0z" fill="{w}"/>'
     '<path d="M40 40c-9 0-11-16-2-16M80 40c9 0 11-16 2-16" fill="none" stroke="{w}" '
     'stroke-width="4.5"/>'
     '<rect x="52" y="68" width="16" height="16" fill="{w}"/>'
     '<rect x="42" y="84" width="36" height="9" rx="4" fill="{w}"/>'),

    ("sys_holiday", "假期", "系统", "sky", "放假 暑假 寒假 太阳",
     '<circle cx="60" cy="52" r="16" fill="{w}"/>'
     '<path d="M60 30v-10M60 74v10M44 36l-7-7M76 36l7-7M44 68l-7 7M76 68l7 7'
     'M32 52h-9M88 52h9" stroke="{w}" stroke-width="5.5" stroke-linecap="round"/>'),

    ("sys_shield", "规则", "系统", "grey", "保护 红线 不可改",
     '<path d="M60 26l28 10v22c0 18-12 29-28 35-16-6-28-17-28-35V36z" fill="{w}"/>'
     '<path d="M48 60l8 9 16-18" stroke="{bg}" stroke-width="7" fill="none" '
     'stroke-linecap="round" stroke-linejoin="round"/>'),
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

# 右下角那道月牙。全套共用一个做法，凑成一套；用 clipPath 裁在圆里，
# 不然它会从圆的边上露出去。
CRESCENT = ('<circle cx="72" cy="74" r="44" fill="%s" opacity=".10" '
            'clip-path="url(#k)"/>' % DARK)


def build_one(token, body, bg):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        '<defs><clipPath id="k"><circle cx="60" cy="60" r="46"/></clipPath></defs>'
        '<circle cx="60" cy="60" r="46" fill="%s"/>%s%s</svg>\n' % (bg, CRESCENT, body)
    )


def build_flat(body):
    """不带圆底的那一类：图形自己就是全部，外面多垫一层就成了第八种颜色。
    viewBox 用图形自己的 26，谁用谁按需缩放（26 / 118 都行）。"""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 26 26">%s</svg>\n'
            % body)


def main():
    if not os.path.isdir(OUT_SVG):
        os.makedirs(OUT_SVG)

    tokens = []
    for token, label, grp, bgname, keys, body in ICONS:
        # bgname 空 = 这一类不垫圆底（现在只有宝箱七档这么画）
        if bgname == "":
            svg = HEADER + build_flat(body.format(w=W, d=DARK, bg=""))
        else:
            bg = PALETTE[bgname]
            svg = HEADER + build_one(token, body.format(w=W, d=DARK, bg=bg), bg)
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

    # 自检：token 重名、底色没定义、占位符漏填
    seen = set()
    for token, label, grp, bgname, keys, body in ICONS:
        assert re.match(r"^[a-z0-9_]+$", token), "token 非法：" + token
        assert token not in seen, "token 重名：" + token
        seen.add(token)
        assert bgname == "" or bgname in PALETTE, "底色没定义：" + bgname
        filled = body.format(w=W, d=DARK, bg=PALETTE.get(bgname, ""))
        assert "{" not in filled, "占位符没填完：" + token
    print("自检通过：%d 个 token 无重名" % len(seen))


if __name__ == "__main__":
    main()
