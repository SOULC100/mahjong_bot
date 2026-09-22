"""牌表示与基础工具。

牌编码：34 种牌，用整数 0~33 表示。
- 0~8   : 一万 ~ 九万
- 9~17  : 一筒 ~ 九筒
- 18~26 : 一条 ~ 九条
- 27~33 : 东南西北中发白（27东 28南 29西 30北 31中 32发 33白）

财神 = 白板（索引 33），百搭，可替代任意牌。
"""

NUM_TILES = 34
LAIZI_INDEX = 33  # 白板 = 财神

# 每种牌各 4 张
TOTAL_TILES = 136

SUIT_MAN = 0    # 万
SUIT_PIN = 1    # 筒
SUIT_SOU = 2    # 条
SUIT_HONOR = 3  # 字牌

_TILE_NAMES = (
    ["%d万" % (i + 1) for i in range(9)]
    + ["%d筒" % (i + 1) for i in range(9)]
    + ["%d条" % (i + 1) for i in range(9)]
    + ["东", "南", "西", "北", "中", "发", "白"]
)

# 协议字符串 <-> 整数 的双向映射
# 平台编码：1w-9w 万，1t-9t 筒，1b-9b 条，字牌用中文单字
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
    """返回牌的花色：0万 1筒 2条 3字。"""
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
    于是「手持 8筒9筒 + 财神，财神补 7筒 成 789筒」这种**财神补顺子下沿**的拆法
    被漏掉，被降级成两面搭 → 向听数被高估 1。线上实证：2万3万4万 7筒8筒9筒 白
    （已副露 2 摊）摸 7筒 时应为胡牌，旧版算 0 向听 → 爆头 ×2 漏判，
    更严重的是 can_hu 判 False 会**把胡牌打掉**。
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
