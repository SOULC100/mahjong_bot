"""A/B 对比：不同策略开关 vs 3 个 baseline，输出 seat0 胡牌率/平均分对比。

用法：python sim_ab.py [每配置局数] [seed]

每配置用相同 seed 序列（牌墙一致），隔离「吃/碰/杠」开关的影响。
"""

import sys
import time

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Baseline, Smart
from mahjong import shanten as _sh

CONFIGS = [
    ("smart(uniform)", Smart(use_ev=False)),
    ("smart(empirical读牌)", Smart(use_ev=False, remain_mode="empirical")),
    ("smart-cheat(上帝视角)", Smart(use_ev=False, cheat=True)),
]


def run(name, smart, n, seed):
    strategies = [smart, Baseline(), Baseline(), Baseline()]
    wins = 0
    draws = 0
    score = 0
    dealer = 0
    t0 = time.time()
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        w, mult, scores, d = g.play_round(strategies)
        if d:
            draws += 1
        else:
            if w == 0:
                wins += 1
            if w != dealer:
                dealer = (dealer + 1) % 4
        score += scores[0]
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长 + 进度显示
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
            print(f"    [{name} 进度 {i+1}/{n}] 胡 {wins} ({wins/(i+1)*100:.1f}%)  "
                  f"流局 {draws/(i+1)*100:.1f}%  ({time.time()-t0:.0f}s)", flush=True)
    dt = time.time() - t0
    print(f"{name:16s}: 胡 {wins:5d}/{n} ({wins / n * 100:5.1f}%)  "
          f"平均分 {score / n:+7.2f}  流局 {draws / n * 100:4.0f}%  ({dt:.0f}s)")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(f"=== A/B 对比（每配置 {n} 局，seat0 vs 3 baseline，相同牌墙） ===")
    for name, smart in CONFIGS:
        run(name, smart, n, seed)


if __name__ == "__main__":
    main()
