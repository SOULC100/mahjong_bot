"""胡牌判定（含财神/白板百搭）。

使用回溯算法，保证对歧义牌型也能正确判定（不用贪心拆面子）。

杭州麻将胡牌 = 标准 4 面子 + 1 将（共 14 张），或七对（7 对 = 14 张）。
财神（白板）可替代任意牌。
"""

from .tiles import NUM_TILES, LAIZI_INDEX, is_number


def split_laizi(counts):
    """把 34 维计数数组拆成 (不含白板的计数, 财神数量)。"""
    c = list(counts)
    laizi = c[LAIZI_INDEX]
    c[LAIZI_INDEX] = 0
    return c, laizi


def can_win(counts) -> bool:
    """判断 14 张手牌（34 维计数，含白板）是否能胡。"""
    tiles, laizi = split_laizi(counts)
    if is_seven_pairs(tiles, laizi):
        return True
    return _can_win_standard(tiles, laizi)


def is_seven_pairs(tiles, laizi) -> bool:
    """七对判定：7 个对子，财神可补单张成对、剩余财神两两配对。"""
    pairs = 0
    singles = 0
    for c in tiles:
        pairs += c // 2
        singles += c % 2
    if singles > laizi:
        return False
    remaining = laizi - singles
    if remaining % 2 != 0:
        return False
    return pairs + singles + remaining // 2 == 7


def _can_win_standard(tiles, laizi) -> bool:
    """标准形：枚举将牌，剩余拆成 4 个面子。"""
    for j in range(NUM_TILES):
        if tiles[j] >= 2:
            tiles[j] -= 2
            ok = _can_meld(tiles, laizi)
            tiles[j] += 2
            if ok:
                return True
        elif tiles[j] == 1 and laizi >= 1:
            tiles[j] -= 1
            ok = _can_meld(tiles, laizi - 1)
            tiles[j] += 1
            if ok:
                return True
    # 两张财神当将
    if laizi >= 2:
        return _can_meld(tiles, laizi - 2)
    return False


def _can_meld(tiles, laizi) -> bool:
    """回溯拆面子：判断 tiles（不含财神）+ laizi 张财神能否全部拆成面子。

    每次取最小非零牌 i，尝试用「刻子」或「顺子」消去，缺的牌用财神补。
    """
    # 找到最小非零牌
    i = 0
    while i < NUM_TILES and tiles[i] == 0:
        i += 1
    if i == NUM_TILES:
        return True

    # 刻子：用 i 自身 + 财神补足 3 张
    use = min(tiles[i], 3)
    need_laizi = 3 - use
    if need_laizi <= laizi:
        tiles[i] -= use
        if _can_meld(tiles, laizi - need_laizi):
            tiles[i] += use
            return True
        tiles[i] += use

    # 顺子：i 为数牌且不超过 7（i%9 <= 6），用 i,i+1,i+2，缺的用财神补
    if is_number(i) and i % 9 <= 6:
        present = []
        miss = 0
        for k in range(3):
            if tiles[i + k] > 0:
                present.append(i + k)
            else:
                miss += 1
        if miss <= laizi:
            for k in present:
                tiles[k] -= 1
            if _can_meld(tiles, laizi - miss):
                for k in present:
                    tiles[k] += 1
                return True
            for k in present:
                tiles[k] += 1

    return False
