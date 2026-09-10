"""离线模拟器 CLI：跑 N 局，统计胡牌率 / 平均分 / 番型分布 / 流局率。

用法：
  python sim_run.py --games 10000 --strategies smart,baseline,baseline,baseline
  python sim_run.py --games 10000 --strategies smart,baseline,baseline,baseline --youcai-bikao

策略名：baseline | smart | smart-nochi | smart-nopeng | smart-nogang
"""

import argparse
import sys
from collections import Counter

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Baseline, Smart


def build_strategy(name):
    if name == "baseline":
        return Baseline()
    if name == "smart":
        return Smart()
    if name == "smart-nochi":
        return Smart(use_chi=False)
    if name == "smart-nopeng":
        return Smart(use_peng=False)
    if name == "smart-nogang":
        return Smart(use_gang=False)
    raise ValueError("unknown strategy: " + name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--strategies", default="smart,baseline,baseline,baseline")
    ap.add_argument("--youcai-bikao", action="store_true")
    args = ap.parse_args()

    names = args.strategies.split(",")
    if len(names) != 4:
        raise SystemExit("需要恰好 4 个策略（逗号分隔）")

    strategies = [build_strategy(n) for n in names]

    wins = [0] * 4
    total_score = [0] * 4
    draws = 0
    mult_counter = Counter()
    dealer = 0

    for i in range(args.games):
        g = Game(seed=args.seed + i, youcai_bikao=args.youcai_bikao)
        g.dealer = dealer
        winner, mult, scores, is_draw = g.play_round(strategies)
        if is_draw:
            draws += 1
            # 流局庄家连庄
        else:
            wins[winner] += 1
            mult_counter[mult] += 1
            if winner != dealer:
                dealer = (dealer + 1) % 4  # 闲家胡，庄家下家接庄
            # 庄家胡则连庄
        for p in range(4):
            total_score[p] += scores[p]

    n = args.games
    print(f"对局数: {n}")
    print(f"流局: {draws} ({draws / n * 100:.1f}%)")
    print("座位表现:")
    for p, name in enumerate(names):
        print(f"  seat{p} ({name:12s}): 胡 {wins[p]:5d} ({wins[p] / n * 100:5.1f}%)  "
              f"平均分 {total_score[p] / n:+7.2f}")
    print(f"番型分布: {dict(sorted(mult_counter.items()))}")


if __name__ == "__main__":
    main()
