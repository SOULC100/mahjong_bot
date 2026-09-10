"""向听数（shanten）计算，含财神/白板百搭。

采用标准公式，对任意张数（13/14 张）基准一致，可直接比较大小：
- 14 张已胡 = -1
- 13 张听牌 = 0（摸一张即胡）
- 13 张一向听 = 1
- 向听数越大手牌越差

标准形：shanten = 8 - 2*面子 - 搭子 - 将牌
七对单独计算，取两者较小值。
"""

from functools import lru_cache

from .tiles import NUM_TILES, LAIZI_INDEX, is_number
from .win import split_laizi, can_win


def shanten(counts, melds=0) -> int:
    """返回标准向听数（14 张已胡 = -1，13 张听牌 = 0）。

    melds: 已副露的面子数（碰/吃/杠各记 1 个面子），默认为 0。
    """
    tiles, laizi = split_laizi(counts)
    groups = 4 - melds
    standard = 8 - 2 * melds - _best(tuple(tiles), laizi, groups)
    seven = _shanten_seven_pairs(tiles, laizi) if melds == 0 else 99
    return min(standard, seven)


def shanten_baotou(counts, melds=0) -> int:
    """财神必须做将（1 财神 + 摸牌当将）的向听数。

    用于爆头/财飘路线：去掉 1 财神（留做将），剩余拆面子+搭子。
    无财神时返回 99（不可行）。
    """
    tiles, laizi = split_laizi(counts)
    if laizi < 1:
        return 99
    groups = 4 - melds
    return 8 - 2 * melds - _mp(tuple(tiles), laizi - 1, groups)


def _shanten_seven_pairs(tiles, laizi) -> int:
    """七对向听数（标准基准：已胡=-1，听牌=0）。"""
    pairs = sum(c // 2 for c in tiles)
    singles = sum(c % 2 for c in tiles)
    fill = min(singles, laizi)      # 财神补单张成对
    rem = laizi - fill              # 剩余财神两两配对
    formed = pairs + fill + rem // 2
    return 6 - formed


@lru_cache(maxsize=None)
def _best(tiles, laizi, groups) -> int:
    """2*面子 + 搭子 + 将牌 的最大值。

    关键约束：面子 + 搭子 + 将 的总组数 <= 5（14 张最多 4 面子 + 1 将）。
    `groups` 为暗手牌中「面子 + 搭子」的剩余组数上限（= 4 - 已副露面子数）。
    """
    best = _mp(tiles, laizi, groups)  # 无将（单吊）：面子+搭子最多 groups 组
    # 枚举将牌（将占 1 组，剩余面子+搭子最多 groups 组）
    for j in range(NUM_TILES):
        if tiles[j] >= 2:
            best = max(best, 1 + _mp(_sub(tiles, j, 2), laizi, groups))
        elif tiles[j] == 1 and laizi >= 1:
            best = max(best, 1 + _mp(_sub(tiles, j, 1), laizi - 1, groups))
    if laizi >= 2:
        best = max(best, 1 + _mp(tiles, laizi - 2, groups))
    return best


@lru_cache(maxsize=None)
def _mp(tiles, laizi, groups) -> int:
    """2*面子 + 搭子 的最大值（不含将），最多再组 `groups` 组。"""
    i = 0
    while i < NUM_TILES and tiles[i] == 0:
        i += 1
    if i == NUM_TILES:
        return _laizi_value(laizi, groups)
    if groups <= 0:
        return 0

    best = 0
    # 跳过 i（当作孤张）
    best = max(best, _mp(_sub(tiles, i, 1), laizi, groups))

    # 完整刻子（用 i 自身 + 财神补足 3 张）-> 面子 +2
    for use in (3, 2, 1):
        if tiles[i] >= use and (3 - use) <= laizi:
            best = max(best, 2 + _mp(_sub(tiles, i, use), laizi - (3 - use), groups - 1))

    # 完整顺子 i,i+1,i+2（缺的用财神补）-> 面子 +2
    if is_number(i) and i % 9 <= 6:
        nt, miss = _remove_seq(tiles, i)
        if miss <= laizi:
            best = max(best, 2 + _mp(nt, laizi - miss, groups - 1))

    # 对子搭子 -> +1
    if tiles[i] >= 2:
        best = max(best, 1 + _mp(_sub(tiles, i, 2), laizi, groups - 1))
    elif tiles[i] >= 1 and laizi >= 1:
        best = max(best, 1 + _mp(_sub(tiles, i, 1), laizi - 1, groups - 1))

    # 两面/边张搭 i,i+1 -> +1
    if is_number(i) and i % 9 <= 7:
        nt, miss = _remove_two(tiles, i, i + 1)
        if miss <= laizi:
            best = max(best, 1 + _mp(nt, laizi - miss, groups - 1))

    # 嵌张搭 i,i+2 -> +1
    if is_number(i) and i % 9 <= 6:
        nt, miss = _remove_two(tiles, i, i + 2)
        if miss <= laizi:
            best = max(best, 1 + _mp(nt, laizi - miss, groups - 1))

    return best


def _laizi_value(laizi, groups):
    """只剩财神时，最多 groups 组，能组成的最优 2*面子+搭子。"""
    if laizi <= 0 or groups <= 0:
        return 0
    best = 0
    max_m = min(laizi // 3, groups)
    for m in range(max_m + 1):
        rem = laizi - 3 * m
        rem_groups = groups - m
        p = min(rem // 2, rem_groups)
        best = max(best, 2 * m + p)
    return best


def _remove_seq(tiles, i):
    """从 tiles 中消去 i,i+1,i+2 各一张，返回 (新tuple, 缺失数)。"""
    nt = list(tiles)
    miss = 0
    for k in range(3):
        if nt[i + k] > 0:
            nt[i + k] -= 1
        else:
            miss += 1
    return tuple(nt), miss


def _remove_two(tiles, a, b):
    """从 tiles 中消去 a,b 各一张，返回 (新tuple, 缺失数)。"""
    nt = list(tiles)
    miss = 0
    for k in (a, b):
        if nt[k] > 0:
            nt[k] -= 1
        else:
            miss += 1
    return tuple(nt), miss


def _sub(tiles, idx, n):
    nt = list(tiles)
    nt[idx] -= n
    return tuple(nt)
