"""B4 A/B：真实番型倍率 fan_est 候选 vs 基线（同一组 seed 序列）。

seat0 = 被测策略，seat1-3 = Baseline。主指标 = seat0 平均分；护栏 = 胡牌率（掉 >2pp 不晋级）。

基线 = Smart(use_ev=True)（EV 框架 + 启发式 _fan_value）。
候选 = Smart(use_ev=True, fan_est=...) 加不同番型估计。

用法：
  python sim_ab_b4.py --cand real   --n 1000 --seed 100
  python sim_ab_b4.py --base smart_ev --cand real_ting --n 1000 --seed 100
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Baseline, Smart
from mahjong import shanten as _sh

VARIANTS = {
    "smart_ev": dict(use_ev=True),                                  # 基线：EV 框架 + heuristic fan
    "ev_real": dict(use_ev=True, fan_est="real"),                   # calc_fan 真倍率估计
    "ev_real_k1": dict(use_ev=True, fan_est="real_k1"),             # calc_fan 真倍率，fan 降权
    "ev_real_ting": dict(use_ev=True, fan_est="real_ting"),         # 仅听牌用 calc_fan
    "smart_noev": dict(),                                           # 参考：旧默认 Smart()（无 EV）
}


def run(name, smart, n, seed):
    wins = 0
    draws = 0
    score = 0.0
    mult_sum = 0.0
    dealer = 0
    t0 = time.time()
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        w, mult, scores, d = g.play_round([smart, Baseline(), Baseline(), Baseline()])
        if d:
            draws += 1
        else:
            if w == 0:
                wins += 1
                mult_sum += mult
            if w != dealer:
                dealer = (dealer + 1) % 4
        score += scores[0]
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    dt = time.time() - t0
    avgm = mult_sum / max(1, wins)
    print(f"{name:12s}: 胡 {wins:5d}/{n} ({wins / n * 100:5.1f}%)  平均分 {score / n:+7.2f}  "
          f"流局 {draws / n * 100:4.0f}%  均胡番 {avgm:4.1f}x  ({dt:.0f}s)", flush=True)
    return wins / n * 100, score / n, draws / n * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="smart_ev", choices=list(VARIANTS))
    ap.add_argument("--cand", default="ev_real", choices=list(VARIANTS))
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--only", choices=["base", "cand", "both"], default="both")
    args = ap.parse_args()

    print(f"=== B4 A/B: {args.base} vs {args.cand}（{args.n} 局, seed {args.seed}, seat0 vs 3 baseline） ===")
    res = {}
    if args.only in ("both", "base"):
        res["base"] = run(args.base, Smart(**VARIANTS[args.base]), args.n, args.seed)
    if args.only in ("both", "cand"):
        res["cand"] = run(args.cand, Smart(**VARIANTS[args.cand]), args.n, args.seed)
    if args.only == "both":
        w0, s0, dr0 = res["base"]
        w1, s1, dr1 = res["cand"]
        print(f"\ndelta({args.cand}-{args.base}): 胡牌率 {w1 - w0:+.2f}pp  平均分 {s1 - s0:+.2f}  "
              f"流局 {dr1 - dr0:+.2f}pp")
        # 晋级判据（A/B 同 seed）：平均分 >= +0.8 且 胡牌率不掉 >2pp
        adv = (s1 - s0 >= 0.8) and (w1 - w0 >= -2.0)
        print(f"晋级? {'YES' if adv else 'no'}  (判据: 平均分+>=0.8 且 胡牌率不掉>2pp)")


if __name__ == "__main__":
    main()
