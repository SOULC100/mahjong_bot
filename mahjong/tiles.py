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
