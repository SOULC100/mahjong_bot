"""番型判定与计分（杭州麻将，2026-09 新规则）。

总番 = 分支因子 × 2^动作链 × (4白板×2) × (爆头×2)
- 分支因子: 平胡×1 / 七对×2 / 豪华七对×4 / 双豪华×8 / 三豪华×16
- 动作链: 杠/飘 每个动作 ×2（杠飘可组合叠加）
- 4白板: 手牌留存 + 链内飘出的白板 = 4（正好4）
- 爆头: 摸任意牌即胡（财神做将单吊），含七客（6对+财神）

guide v21（2026-09-07 两条用户裁定，已用免认证 POST /portal/api/tools/fan-calc 对拍复验）：
- 七对「豪华组」：4 张真白板在其余牌**全为自然对**（白板两两自配、未用于补落单）时
  也算 1 组四张；白板已作百搭补配其他牌成对时**不重复计豪华**（见 seven_pairs_branch）。
- 爆头：撤销旧裁「听牌态正好 4 张白板不算爆头」——4 白听任意即胡按爆头计，
  并与「4 个白板 ×2」叠加（见 any_draw_win）。
"""

from .tiles import NUM_TILES, LAIZI_INDEX, is_number
from .win import split_laizi, is_seven_pairs, _can_meld
from .shanten import shanten


def _count_quads(tiles):
    """真牌（非财神）中「四张相同」的组数。"""
    return sum(1 for c in tiles if c >= 4)


def _is_four_melds(tiles):
    """12 张（无财神）能否拆成 4 个面子（供 should_piao 判断 4 面子 + 2 财神）。"""
    return _can_meld(list(tiles), 0)


def seven_pairs_branch(tiles, laizi):
    """七对分支因子：普通×2 / 豪华×4 / 双豪华×8 / 三豪华×16；非七对返回 None。

    4 张真白板是否额外算 1 组四张（v21① 口径）：
    - 其余牌全为自然对（无落单）→ 白板两两自配，算 1 组 → +1；
    - 其余牌存在落单（白板被用作百搭补配成对）→ 不重复计豪华 → 不计。
    """
    if not is_seven_pairs(tiles, laizi):
        return None
    quads = _count_quads(tiles)
    if laizi == 4 and sum(c % 2 for c in tiles) == 0:
        quads += 1  # 4 张真白板两两自配（未用于补落单）= 1 组四张
    if quads >= 3:
        return 16
    if quads == 2:
        return 8
    if quads == 1:
        return 4
    return 2


def _is_n_pairs(tiles, laizi, n):
    """tiles（不含财神）+ laizi 张财神能否凑成 n 个对子。"""
    pairs = sum(c // 2 for c in tiles)
    singles = sum(c % 2 for c in tiles)
    if singles > laizi:
        return False
    rem = laizi - singles
    if rem % 2 != 0:
        return False
    return pairs + singles + rem // 2 == n


def is_baotou(counts):
    """爆头：财神做将的「单吊任意」胡。含七客（6对+财神）。

    counts: 14 张胡牌手牌（34 维计数，含白板）。
    注意：本函数是**终局结构**判据，"最后摸来的财神补成七对/面子"也会被判成 True，
    服务端不给 ×2——计分请用 any_draw_win(摸前13)（见 calc_fan 的 baotou 参数）。
    v21②：撤销「正好 4 张白板不算爆头」旧裁，4 白不再排除。
    """
    tiles, laizi = split_laizi(counts)
    if laizi < 1:
        return False
    # 七客：七对 + 财神做将（财神补第 7 对的单张）
    if is_seven_pairs(tiles, laizi):
        return True
    # 标准：4 面子 + 财神做将（枚举将牌 x：财神 + x）
    for x in range(NUM_TILES):
        if tiles[x] >= 1:
            tiles[x] -= 1
            ok = _can_meld(list(tiles), laizi - 1)
            tiles[x] += 1
            if ok:
                return True
    return False


def any_draw_win(counts13, melds=0) -> bool:
    """摸牌前 13 张是否「任意摸都胡」= 真·爆头（4面子+财神单吊 / 6对+财神/七客）。

    counts13: 摸牌前的 13 张（含财神）。摸后形判定会把「最后摸来的财神补成七对/面子」
    误算成爆头（服务器不给 ×2），必须用摸前形——见 calc_fan 的 baotou 参数。

    v21②（2026-09-07）：不再排除「正好 4 张白板」——4 白听任意即胡按爆头计，
    并与「4 个白板 ×2」叠加。
    """
    if counts13[LAIZI_INDEX] < 1:
        return False
    for t in range(NUM_TILES):
        c2 = list(counts13)
        c2[t] += 1
        if shanten(c2, melds) != -1:
            return False
    return True


def ycb_can_hu(hand14, drawn=-1, melds=0, gang_kai=False) -> bool:
    """YouCaiBiKao（有财必拷响）下这手牌能否胡。

    调用方需先确认 hand14 已是胡形（shanten == -1）。判据与对局服务端一致：
    - 手无财神 → 平胡合法；
    - 杠开（杠上花 / gang_kai=True）→ 免爆头胡法；
    - 有财神普通自摸 → 必须真·爆头（摸前 13 张任意摸都胡）。
    """
    _, laizi = split_laizi(hand14)
    if laizi == 0:
        return True
    if gang_kai:
        return True
    if drawn is None or drawn < 0 or hand14[drawn] <= 0:
        return False  # 无「刚摸的牌」信息 → 无法证明摸前形是爆头，保守拒
    h13 = list(hand14)
    h13[drawn] -= 1
    return any_draw_win(h13, melds)


def calc_fan(hand_counts, gang_kai=False, piao_count=0, baotou=False) -> int:
    """计算胡牌番型倍率。

    hand_counts: 14 张胡牌手牌（34 维计数，含白板）。
    gang_kai: 是否杠开（动作链 +1）。
    piao_count: 财飘次数（动作链 +piao，且计入 4 白板判定）。
    baotou: 是否真·爆头（摸牌前已是「4面子+财神单吊」或「6对+财神」=任意摸都胡，
            2026-09-03 修：不能仅凭终局 14 张结构判——"最后摸来的财神补成七对/面子"不算爆头，
            服务器口径 fan=4（青龙 1w1w7w7w8w8w3t3t3t9b9b9b9b+白 实证）。引擎在胡牌瞬间知道
            摸前 13 张形，由调用方（sim/engine）用 `_any_draw_win(摸前13)` 计算后传入。）
    """
    tiles, laizi = split_laizi(hand_counts)

    # 分支因子（七对 / 豪华 / 双豪华 / 三豪华；否则平胡 ×1）
    branch = seven_pairs_branch(tiles, laizi)
    mult = branch if branch is not None else 1

    # 动作链：杠/飘 每个动作 ×2
    chain = (1 if gang_kai else 0) + piao_count
    mult *= 2 ** chain

    # 4 白板：手留 + 链内飘出的白板 = 4（2026-09 v1#13 更正）
    if laizi + piao_count == 4:
        mult *= 2

    # 爆头（真·爆头才 ×2）。不再用 is_baotou 纯结构判——见 baotou 参数注释。
    # v21②：4 白板不再排除，可与上面的「4 个白板 ×2」叠加。
    if baotou:
        mult *= 2

    return mult
