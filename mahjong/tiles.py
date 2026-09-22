"""牌表示与基础工具。

牌编码：34 种牌，用整数 0~33 表示（**本仓内部索引顺序**，与平台协议字母的对应见下）。
- 0~8   : 一万 ~ 九万   （协议 w）
- 9~17  : 一条 ~ 九条   （协议 **t**）
- 18~26 : 一筒 ~ 九筒   （协议 **b**）
- 27~33 : 东南西北中发白（27东 28南 29西 30北 31中 32发 33白）

⚠️ **平台花色字母：w=万、t=条、b=筒**（2026-09-22 定案，此前本文件注释写反了）。
证据（服务端门户自己的渲染代码，非本仓推断）：
- `/portal/tiles.js` 的 `tileSVG`：`suit === "b"` 画 `<circle>`（圆点=筒），否则画 `<rect rx=1.3>`（竹条=条）；
  `TILE_COLOR = {w,b,t}` 三色 + `suit === "w"` 出「萬」字。
- 同一文件 `TILE_RECT` 的贴图取片：`1b` → y 0~137（底图**行0=筒**），`1t` → y 305~443（**行2=条**）。
- 门户番型计算器分组：`FC_ALL_TILES` 按 `["w","b","t"]` 生成后，`slice(9,18)` 标为「筒子」、`slice(18,27)` 标为「条子」。

索引顺序本身是内部约定（本规则番型与花色无关，故顺序不影响任何决策与线上行为），
但**任何面向人的花色文字/命名都必须按上面的平台口径**，否则会误导复盘（踩过：把 9t 说成九筒）。
"""

NUM_TILES = 34
LAIZI_INDEX = 33  # 白板 = 财神

# 每种牌各 4 张
TOTAL_TILES = 136

# ⚠️ 常量名沿用日式术语（pin=筒/sou=条），但**索引区间按本仓内部顺序**：
#    1 号区间 = 协议 t = **条**；2 号区间 = 协议 b = **筒**。别按名字推花色。
SUIT_MAN = 0    # 万（协议 w）
SUIT_PIN = 1    # 条（协议 t）——名字是日式「筒」，本区间实际是条
SUIT_SOU = 2    # 筒（协议 b）——名字是日式「条」，本区间实际是筒
SUIT_HONOR = 3  # 字牌

_TILE_NAMES = (
    ["%d万" % (i + 1) for i in range(9)]
    + ["%d条" % (i + 1) for i in range(9)]     # 索引 9~17 = 协议 1t~9t = 条
    + ["%d筒" % (i + 1) for i in range(9)]     # 索引 18~26 = 协议 1b~9b = 筒
    + ["东", "南", "西", "北", "中", "发", "白"]
)

# 协议字符串 <-> 整数 的双向映射
# 平台编码：1w-9w 万，**1t-9t 条**，**1b-9b 筒**，字牌用中文单字（见文件头证据）
STR_TO_IDX = {}
IDX_TO_STR = {}
for i in range(9):
    STR_TO_IDX["%dw" % (i + 1)] = i
    IDX_TO_STR[i] = "%dw" % (i + 1)
for i in range(9):
    STR_TO_IDX["%dt" % (i + 1)] = 9 + i
    IDX_TO_STR[9 + i] = "%dt" % (i + 1)
for i in range(9):
    STR_TO_IDX["%db" % (i + 1)] = 18 + i
    IDX_TO_STR[18 + i] = "%db" % (i + 1)
for idx, name in enumerate(["东", "南", "西", "北", "中", "发", "白"], start=27):
    STR_TO_IDX[name] = idx
    IDX_TO_STR[idx] = name


def tile_from_str(s: str) -> int:
    """协议字符串 -> 整数索引。"""
    return STR_TO_IDX[s]


def tile_to_str(tile: int) -> str:
    """整数索引 -> 协议字符串。"""
    return IDX_TO_STR[tile]


def hand_from_strs(strs) -> list:
    """协议字符串列表 -> 34 维计数数组。"""
    counts = empty_counts()
    for s in strs:
        counts[tile_from_str(s)] += 1
    return counts


def suit(tile: int) -> int:
    """返回牌的花色：0万 1条 2筒 3字（对应协议 w / t / b / 字牌）。"""
    return tile // 9


def is_number(tile: int) -> bool:
    """是否为数牌（万/筒/条，可组成顺子）。"""
    return tile < 27


def is_honor(tile: int) -> bool:
    """是否为字牌（东南西北中发白）。"""
    return tile >= 27


def is_laizi(tile: int) -> bool:
    """是否为财神（白板百搭）。"""
    return tile == LAIZI_INDEX


def run_starts(tile: int) -> tuple:
    """所有可能「包含 tile」的顺子起点 s（顺子 = s,s+1,s+2，同一花色内）。

    tile 可以是顺子的下沿/中间/上沿，因此 s ∈ {tile-2, tile-1, tile}。
    返回按升序排列，可直接用于拆解枚举。

    为什么需要它（2026-09 线上复核）：旧版拆解只试 s = tile（最低现有牌当下沿），
    于是「手持 8筒9筒 + 财神，财神补 7筒 成 789筒」（协议 8b9b + 白 → 7b8b9b，b=筒）
    这种**财神补顺子下沿**的拆法被漏掉，被降级成两面搭 → 向听数被高估 1。
    线上实证：2万3万4万 7筒8筒9筒 白（已副露 2 摊）摸 7筒 时应为胡牌，旧版算 0 向听 →
    爆头 ×2 漏判，更严重的是 can_hu 判 False 会**把胡牌打掉**。
    """
    if not is_number(tile):
        return ()
    out = []
    for s in (tile - 2, tile - 1, tile):
        if s < 0 or s // 9 != tile // 9 or s % 9 > 6:
            continue
        out.append(s)
    return tuple(out)


def pair_completions(a: int, b: int) -> tuple:
    """两张手牌 (a,b) 要成顺子还需要的那张牌（≤2 种，同花色内）。

    用于「吃这张牌时，我消耗掉的是哪一副搭子」的评估：吃掉之后，
    这副搭子原本还能靠**自己摸**补上的牌就是 pair_completions − 被吃的那张。
    """
    lo, hi = (a, b) if a <= b else (b, a)
    if not is_number(lo) or hi - lo > 2:
        return ()
    out = set()
    for s in range(max(0, hi - 2), lo + 1):
        if s // 9 != lo // 9 or s % 9 > 6:
            continue
        for t in (s, s + 1, s + 2):
            if t != a and t != b:
                out.add(t)
    return tuple(sorted(out))


def tile_name(tile: int) -> str:
    return _TILE_NAMES[tile]


def count_to_list(counts) -> list:
    """34 维计数数组 -> 展开的牌索引列表。"""
    result = []
    for i, c in enumerate(counts):
        result.extend([i] * c)
    return result


def list_to_count(tiles) -> list:
    """牌索引列表 -> 34 维计数数组。"""
    counts = [0] * NUM_TILES
    for t in tiles:
        counts[t] += 1
    return counts


def empty_counts() -> list:
    return [0] * NUM_TILES
