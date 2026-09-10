"""A1 吃/碰 ukeire 门控 A/B：候选 vs 基线（同一组 seed 序列）。

用法：python sim_ab_a1.py --variant {base,peng_gate,chi_gate,both_gate} --n 1000 --seed 100
基准 config = Smart()（老行为）；候选 config 只开一处 A1 门控。
seat0 = 被测策略，seat1-3 = Baseline。统计 seat0 胡牌率 / 平均分 / 副露类型。
"""

import argparse
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from sim.engine import Game, KIND_NAMES
from sim.players import Baseline, Smart
from mahjong import shanten as _sh

VARIANTS = {
    "base": dict(),
    "peng_gate": dict(peng_ukeire_gate=True),
    "chi_gate": dict(chi_ukeire_gate=True),
    "both_gate": dict(peng_ukeire_gate=True, chi_ukeire_gate=True),
    "peng_gate_sh1": dict(peng_ukeire_gate=True, peng_gate_max_shanten=1),
    "peng_gate_sh2": dict(peng_ukeire_gate=True, peng_gate_max_shanten=2),
}


def run(cfgname, smart, n, seed):
    meld_cnt = Counter()
    wins = 0
    draws = 0
    score = 0.0
    dealer = 0
    t0 = time.time()
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        w, mult, scores, d = g.play_round([smart, Baseline(), Baseline(), Baseline()])
        for m in g.melds[0]:
            meld_cnt[KIND_NAMES[m.kind]] += 1
        if d:
            draws += 1
        else:
            if w == 0:
                wins += 1
            if w != dealer:
                dealer = (dealer + 1) % 4
        score += scores[0]
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    dt = time.time() - t0
    meld_s = " ".join(f"{k}={meld_cnt.get(k, 0)}" for k in ("peng", "chi", "angang", "minggang", "bugang"))
    print(f"{cfgname:12s}: 胡 {wins:5d}/{n} ({wins / n * 100:5.1f}%)  "
          f"平均分 {score / n:+7.2f}  流局 {draws / n * 100:4.0f}%  seat0副露[{meld_s}]  ({dt:.0f}s)", flush=True)
    return wins, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="peng_gate", choices=list(VARIANTS))
    ap.add_argument("--base", default="base", choices=list(VARIANTS), help="基线 config（当前最优）")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    args = ap.parse_args()

    base_cfg = VARIANTS[args.base]
    cand_cfg = VARIANTS[args.variant]
    print(f"=== A1 A/B: {args.base} vs {args.variant}（{args.n} 局, seed {args.seed}，seat0 vs 3 baseline） ===")
    w0, s0 = run(args.base, Smart(**base_cfg), args.n, args.seed)
    w1, s1 = run(args.variant, Smart(**cand_cfg), args.n, args.seed)
    print(f"\ndelta({args.variant}-{args.base}): 胡牌率 {(w1 - w0) / args.n * 100:+.2f}pp  平均分 {s1 / args.n - s0 / args.n:+.2f}")


if __name__ == "__main__":
    main()
