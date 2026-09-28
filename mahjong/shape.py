"""形状评估模块（牌型构建引擎 L1，2026-09-23）。

**为什么需要它**（本会话实测）：我的暗手「自然面子数」只有 0.45~0.93，而爆头形要求暗手是
「(4−m) 个自然面子 + 单白」⇒ 任何 m 下「可进爆头听」都是 0%~0.74%（`data/_pm_shape_probe.py`）。
根因：现有打分的进张项用 `shanten`（**白当百搭**）来估值，于是**能长出自然面子的牌**与
**靠白补的牌**被等价看待 —— 手牌自然结构因此长不起来。

本模块只做**只读评估**（纯函数，不改任何策略默认行为）：
  · `natural_melds`      暗手已有的自然面子数（同花色刻子/顺子，白不算）
  · `isolated_count`     孤张数（±2 内无邻牌的单张，白不算）
  · `natural_meld_ukeire` 「摸到哪些牌能**新长出自然面子**」的加权期望（与 `_draw_quality` 同单位量纲）
  · `shape_report`       诊断用汇总（自然面子 / 孤张 / 两个目标形的向听与可达性 / 白富余）

设计意图（见 `docs/shape-engine-design.md` §3 L1）：给出牌打分加**软定价**项
`score -= λ_nat × natural_meld_ukeire(打后)`、`score += λ_iso × isolated_count(打后)`，
默认 λ=0（逐位等于现状）。与已被证否的 `plan_bao_live_cand`（硬换口径、禁止白当百搭）的区别：
这里是**在同等速度下偏好"能长出自然面子"的路线**，不是禁止用白。
"""
from mahjong.tiles import NUM_TILES, LAIZI_INDEX

_SUITS = ((0, 9), (9, 18), (18, 27))


def natural_melds(counts):
    """暗手里的**自然**面子数（白不参与）：先数刻子，再数顺子（贪心，与 `_mp` 的拆法同风格）。"""
    c = list(counts)
    n = 0
    for lo, hi in _SUITS:
        for t in range(lo, hi):
            while c[t] >= 3:
                c[t] -= 3
                n += 1
    for lo, hi in _SUITS:
        for t in range(lo, hi - 2):
            while c[t] > 0 and c[t + 1] > 0 and c[t + 2] > 0:
                c[t] -= 1
                c[t + 1] -= 1
                c[t + 2] -= 1
                n += 1
    # 字牌（含白）只可能是刻子；白不计入"自然"
    for t in range(27, NUM_TILES):
        if t == LAIZI_INDEX:
            continue
        while c[t] >= 3:
            c[t] -= 3
            n += 1
    return n


def isolated_count(counts):
    """孤张数：计数为 1、且 ±2 内没有任何其他牌（同花色）、且不是白的牌。"""
    n = 0
    for lo, hi in _SUITS:
        for t in range(lo, hi):
            if counts[t] != 1:
                continue
            lo2, hi2 = max(lo, t - 2), min(hi - 1, t + 2)
            if all(counts[x] == 0 for x in range(lo2, hi2 + 1) if x != t):
                n += 1
    for t in range(27, NUM_TILES):
        if t != LAIZI_INDEX and counts[t] == 1:
            n += 1
    return n


def natural_meld_ukeire(counts13, remain=None):
    """摸到一张牌能**新长出自然面子**的加权张数（与 `_draw_quality` 同量纲：张数 × 深度权重）。

    counts13: 13 张（打后）的 34 维计数。remain: 未见张数（None ⇒ 按每种 4 张估算）。
    只统计"新增自然面子"（不含白补的），这是与现行 `_draw_quality` 的**唯一区别**。
    """
    base = natural_melds(counts13)
    score = 0.0
    for t in range(NUM_TILES):
        if t == LAIZI_INDEX:
            continue
        if remain is not None and remain[t] <= 0:
            continue
        w = 4.0 if remain is None else remain[t]
        c = list(counts13)
        c[t] += 1
        gain = natural_melds(c) - base
        if gain > 0:
            score += w * gain
    return score


def shape_report(counts, melds=0, remain=None):
    """诊断汇总（不对决策产生影响）：自然面子 / 孤张 / 两目标形的可达性 / 白富余。

    ⚠️ `counts` 必须是**摸牌后的 14 张**（内部按"弃 1 张 → 13 张"评估）；
    传 13 张会整体偏差一档（自检脚本已注明）。
    """
    from mahjong.shanten import shanten, shanten_baotou
    c = list(counts)
    w = c[LAIZI_INDEX]
    reach_std = reach_bao = False
    d_std = d_bao = 99
    for t in range(NUM_TILES):
        if c[t] <= 0:
            continue
        c2 = list(c)
        c2[t] -= 1
        s = shanten(c2, melds)
        sb = shanten_baotou(c2, melds)
        d_std = min(d_std, s)
        d_bao = min(d_bao, sb)
        if s == 0:
            reach_std = True
        if sb == 0:
            reach_bao = True
    return dict(
        laizi=w,
        natural_melds=natural_melds(c),
        isolated=isolated_count(c),
        d_std=d_std, d_bao=d_bao,
        reach_std=reach_std, reach_bao=reach_bao,
        white_spare=int(w >= 2),          # 有 2 张白才是真"富余"（1 张白要留着做将）
    )


if __name__ == "__main__":
    # 自检：几个手牌的自然面子/孤张
    from mahjong.tiles import list_to_count
    tests = [
        ("1w 2w 3w 4w 5w 6w 7w 8w 9w 1t 2t 3t 白", 3, 0),
        ("1w 2w 3w 4w 5w 6w 7w 8w 9w 1t 2t 白 白", 3, 0),
        ("1w 5w 9w 1t 5t 9t 1b 5b 9b 东 南 西 白", 0, 12),
    ]
    for s, nm, iso in tests:
        c = list_to_count(s.split()) if hasattr(list_to_count, "__call__") else None
        if c is None:
            continue
        print("%-42s natural_melds=%d isolated=%d" % (s, natural_melds(c), isolated_count(c)))
