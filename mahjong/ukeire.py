"""有效进张（ukeire）与听牌计算。

出牌决策的核心：对每张候选出牌 d，计算「打掉 d 后摸哪些牌能降低向听数」，
以及这些进张在牌墙中剩余的加权张数。

remain: 每种牌在牌墙中还剩的张数（34 维）。None 时按「每种最多 4 张」估算。
"""

from .tiles import NUM_TILES
from .shanten import shanten


def unique_tiles(counts):
    """手牌中出现的牌种（升序）。"""
    return [i for i in range(NUM_TILES) if counts[i] > 0]


def shanten_after_discard(counts, d, melds=0):
    """打掉牌 d 后（13 张）的向听数。"""
    c = list(counts)
    c[d] -= 1
    return shanten(c, melds)


def ukeire_tiles(counts, d, melds=0):
    """打掉 d 后，摸哪些牌能降低向听数（返回 tile 索引列表）。"""
    c = list(counts)
    c[d] -= 1
    base = shanten(c, melds)
    result = []
    for t in range(NUM_TILES):
        c2 = list(c)
        c2[t] += 1
        if shanten(c2, melds) < base:
            result.append(t)
    return result


def ukeire_count(counts, d, remain=None, melds=0):
    """打掉 d 后的有效进张加权总数。"""
    tiles = ukeire_tiles(counts, d, melds)
    if remain is None:
        remain = [4] * NUM_TILES
    return sum(remain[t] for t in tiles)


def ukeire_quality(counts, d, remain=None, melds=0):
    """打掉 d 后的进张质量：进张数 + 进张后向听数深度加权。

    每个进张 t 的价值 = 1（进张本身）+ max(0, 3 - 进张后向听数)
    即摸到「直接听牌/更接近胡」的进张，价值高于「只降一向听」的进张。
    """
    c = list(counts)
    c[d] -= 1
    base = shanten(c, melds)
    if remain is None:
        remain = [4] * NUM_TILES
    score = 0
    for t in range(NUM_TILES):
        if remain[t] <= 0:
            continue
        c2 = list(c)
        c2[t] += 1
        s2 = shanten(c2, melds)
        if s2 < base:
            score += remain[t] * (1 + max(0, 3 - s2))
    return score


def ukeire_depth(counts, d, remain=None, melds=0):
    """打掉 d 后的二次进张期望（一步前瞻）。

    对每个进张 t（摸到后向听数下降），统计「摸到 t 后再打一张的最优二次进张数」，
    加权求和。比 ukeire_quality 更深一层，能区分「进张质量」。
    """
    c = list(counts)
    c[d] -= 1
    base = shanten(c, melds)
    if remain is None:
        remain = [4] * NUM_TILES
    total = 0
    for t in range(NUM_TILES):
        if remain[t] <= 0:
            continue
        c2 = list(c)
        c2[t] += 1
        s2 = shanten(c2, melds)
        if s2 >= base:
            continue  # 非进张
        best_second = 0
        for d2 in unique_tiles(c2):
            if shanten_after_discard(c2, d2, melds) == s2:
                best_second = max(best_second, ukeire_count(c2, d2, remain, melds))
        total += remain[t] * best_second
    return total


def ting_tiles(counts, melds=0):
    """13 张手牌，返回能胡的牌列表（听哪些牌）。"""
    result = []
    for t in range(NUM_TILES):
        c = list(counts)
        c[t] += 1
        if shanten(c, melds) == -1:
            result.append(t)
    return result


def ting_count(counts, remain=None, melds=0):
    """听牌后剩余可胡张数。"""
    if remain is None:
        remain = [4] * NUM_TILES
    return sum(remain[t] for t in ting_tiles(counts, melds))


def best_discard(counts, remain=None, melds=0):
    """纯牌效率出牌：优先最小向听数，其次最大有效进张。

    返回 (出牌 tile, 打后向听数, 进张加权数)。后续决策层叠加番型/财神权重。
    """
    best_d = -1
    best_shanten = 99
    best_val = -1
    for d in unique_tiles(counts):
        s = shanten_after_discard(counts, d, melds)
        v = ukeire_count(counts, d, remain, melds)
        if s < best_shanten or (s == best_shanten and v > best_val):
            best_shanten = s
            best_val = v
            best_d = d
    return best_d, best_shanten, best_val
