"""牌墙剩余估算（对手建模）。

当前 uniform 估算 = `4 - 已见牌`（乐观假设对手一张不扣）。
上帝视角诊断显示：真实牌墙剩余（非均匀）可 +4pp 胡牌率。
本模块用对手弃牌反推「哪些牌更可能在牌墙 / 被对手扣着」，得到非均匀 remain。
"""

from mahjong.tiles import NUM_TILES

# 实测（150 局统计）：某牌可见 v 张时，其未见牌中被对手扣住的比例。
# 可见越多 → 对手越不想要 → 未见牌越可能在牌墙（被扣比例越低）。
HELD_RATE = [0.64, 0.59, 0.45, 0.25]  # 对应可见 0/1/2/3 张


def _visible(game, seat):
    """每张牌的已见数（我的手牌 + 四家弃牌 + 四家副露）。"""
    visible = [0] * NUM_TILES
    for t in range(NUM_TILES):
        visible[t] = game.hands[seat][t]
        for p in range(4):
            visible[t] += game.discards[p].count(t)
            for m in game.melds[p]:
                visible[t] += m.tiles.count(t)
    return visible


def _opp_hidden(game, seat):
    """对手暗手总张数（近似 3 家 × 13 扣副露）。"""
    hidden = 3 * 13
    for p in range(4):
        if p != seat:
            hidden -= 3 * len(game.melds[p])
    return max(0, hidden)


def infer_remain(game, seat, mode="empirical"):
    """反推每张牌在牌墙中的剩余张数（float，可喂给 ukeire）。

    mode:
      uniform   - 当前行为：4 - 已见（乐观上界，假设对手 0 扣）
      bayes     - 均匀贝叶斯缩放（README 已证不改变决策排序）
      empirical - 实测查表：可见数 → 牌墙比例（非均匀，本模块核心）
      suji      - 筋牌(±3)启发式（已证无效，保留参考）
    """
    visible = _visible(game, seat)
    wall_remaining = game._remaining()
    if wall_remaining <= 0:
        return [0.0] * NUM_TILES

    if mode == "uniform":
        return [float(max(0, 4 - visible[t])) for t in range(NUM_TILES)]

    opp_hidden = _opp_hidden(game, seat)
    total_unseen = wall_remaining + opp_hidden
    if total_unseen <= 0:
        return [0.0] * NUM_TILES

    if mode == "empirical":
        remain = [0.0] * NUM_TILES
        for t in range(NUM_TILES):
            v = min(visible[t], 3)
            unseen = max(0, 4 - visible[t])
            remain[t] = unseen * (1.0 - HELD_RATE[v])
        return remain

    # 均匀贝叶斯基线
    base = [max(0, 4 - visible[t]) * wall_remaining / total_unseen for t in range(NUM_TILES)]
    if mode == "bayes":
        return base

    # suji（保留参考）
    remain = [0.0] * NUM_TILES
    for t in range(NUM_TILES):
        b = base[t]
        if b <= 0:
            remain[t] = 0.0
            continue
        adj = 1.0
        if t < 27:
            suji = 0
            for dt in (-3, 3):
                u = t + dt
                if 0 <= u < 27 and u // 9 == t // 9:
                    suji += visible[u]
            adj = 1.0 + 0.25 * (suji / 8.0)
        remain[t] = min(float(4 - visible[t]), b * adj)
    return remain
