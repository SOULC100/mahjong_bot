"""4-smart 自对弈统计分析：胜率 / 番型分布 / 胡牌用时。

用法：python sim_analyze.py [局数]
"""

import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Smart
from mahjong.fan import seven_pairs_branch, is_baotou
from mahjong.win import split_laizi
from mahjong import shanten as _sh


def classify(hand):
    """番型类型：七对 / 爆头 / 平胡。"""
    tiles, laizi = split_laizi(hand)
    if seven_pairs_branch(tiles, laizi) is not None:
        return "七对"
    if is_baotou(hand):
        return "爆头"
    return "平胡"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    players = [Smart() for _ in range(4)]
    wins = [0] * 4
    draws = 0
    fan_type = Counter()       # 平胡/七对/爆头
    fan_mult = Counter()       # 番型倍率分布
    durations = []             # 胡牌时已摸张数（发牌后）
    dealer = 0
    t0 = time.time()

    for i in range(n):
        g = Game(seed=i)
        g.dealer = dealer
        w, mult, scores, d = g.play_round(players)
        if d:
            draws += 1
        else:
            wins[w] += 1
            fan_type[classify(g.hands[w])] += 1
            fan_mult[mult] += 1
            durations.append(g.draw_pos - 53)  # 发牌 53 张后，再摸几张才胡
            if w != dealer:
                dealer = (dealer + 1) % 4
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长 + 进度显示
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
            win_rate = (i + 1 - draws) / (i + 1) * 100
            print(f"  [进度 {i+1}/{n}] 流局 {draws} ({draws/(i+1)*100:.1f}%)  "
                  f"结算率 {win_rate:.1f}%  各座胜 {wins}  用时 {time.time()-t0:.0f}s",
                  flush=True)

    dt = time.time() - t0
    print(f"=== 4-smart 自对弈 {n} 局 ===")
    print(f"流局: {draws} ({draws / n * 100:.1f}%)  结算率: {(n - draws) / n * 100:.1f}%")
    print("各座位胜率:")
    for p in range(4):
        print(f"  seat{p}: 胡 {wins[p]} ({wins[p] / n * 100:.1f}%)")
    print(f"番型类型分布: {dict(fan_type)}")
    print(f"番型倍率分布: {dict(sorted(fan_mult.items()))}")
    if durations:
        avg = sum(durations) / len(durations)
        print(f"胡牌用时(发牌后再摸张数): 平均 {avg:.1f} 张, 最小 {min(durations)}, 最大 {max(durations)}")
    print(f"耗时 {dt:.0f}s")


if __name__ == "__main__":
    main()
