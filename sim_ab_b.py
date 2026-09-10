"""B1/B2 A/B：财飘时机(B1) / 爆头路线(B2) 候选 vs 基线（同一组 seed 序列）。

用法：python sim_ab_b.py --base smart --cand bao_loose1 --n 1000 --seed 100
seat0 = 被测策略，seat1-3 = Baseline。主指标 = seat0 平均分；胡牌率作护栏（候选掉 >2pp 不晋级）。
附带统计 seat0 财飘事件/财飘赢/杠开赢 次数，辅助判断 B1 是否真的能测到。

VARIANT 里每一项都是传给 Smart() 的 kwargs；默认 smart = 现行为基线。
"""

import argparse
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Baseline, Smart
from mahjong import shanten as _sh

VARIANTS = {
    "smart": dict(),                                   # 现基线 Smart()
    # ---- B1 财飘时机 ----
    "no_piao": dict(piao_enabled=False),               # 完全不飘（对照，看飘的净贡献）
    "piao_dealer": dict(piao_dealer_only=True),        # 仅庄家飘
    # ---- B2 爆头路线阈值 ----
    "bao_slack2": dict(baotou_slack=2),                # 放宽：s_bao <= s_std+2（仍 s_bao<=1）
    "bao_max2": dict(baotou_max_shanten=2),            # 放宽：s_bao <= 2（仍 slack=1）
    "bao_loose22": dict(baotou_slack=2, baotou_max_shanten=2),  # 双向放宽
    "bao_tight0": dict(baotou_slack=0, baotou_max_shanten=0),   # 收紧：仅已爆头听牌(s_bao<=0)且无 +1
    "bao_tight_slack0": dict(baotou_slack=0),          # 收紧：不许为爆头多牺牲向听（s_bao<=s_std, 仍<=1）
}


def run(name, smart, n, seed):
    wins = 0
    draws = 0
    score = 0.0
    dealer = 0
    piao_ev = 0      # seat0 本局发生过 piao_count>0
    piao_win = 0     # seat0 飘后赢
    gangkai_win = 0  # seat0 杠开赢
    t0 = time.time()
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        w, mult, scores, d = g.play_round([smart, Baseline(), Baseline(), Baseline()])
        if g.piao_count[0]:
            piao_ev += 1
        if d:
            draws += 1
        else:
            if w == 0:
                wins += 1
                if g.piao_count[0]:
                    piao_win += 1
                # 用 seat0 的副露判断是否杠开（近似：win 的 mult 含 gang_kai 时由 engine 置位，
                # 这里无法直接读 gang_kai，故以是否有暗/明/补杠 meld 近似）
                if any(m.is_gang() for m in g.melds[0]):
                    gangkai_win += 1
            if w != dealer:
                dealer = (dealer + 1) % 4
        score += scores[0]
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    dt = time.time() - t0
    print(f"{name:14s}: 胡 {wins:5d}/{n} ({wins / n * 100:5.1f}%)  平均分 {score / n:+7.2f}  "
          f"流局 {draws / n * 100:4.0f}%  飘 {piao_ev}({piao_win}赢) 杠开赢~{gangkai_win}  ({dt:.0f}s)", flush=True)
    return wins / n * 100, score / n, draws / n * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="smart", choices=list(VARIANTS))
    ap.add_argument("--cand", default="bao_loose22", choices=list(VARIANTS))
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--only", choices=["base", "cand", "both"], default="both",
                    help="both=跑 base+cand（A/B）；cand=只跑候选（对比已记录的基线指标）；base=只跑基线")
    args = ap.parse_args()

    print(f"=== B1/B2 A/B: {args.base} vs {args.cand}（{args.n} 局, seed {args.seed}, seat0 vs 3 baseline） ===")
    if args.only in ("both", "base"):
        wr0, sc0, dr0 = run(args.base, Smart(**VARIANTS[args.base]), args.n, args.seed)
    if args.only in ("both", "cand"):
        wr1, sc1, dr1 = run(args.cand, Smart(**VARIANTS[args.cand]), args.n, args.seed)
    if args.only == "both":
        print(f"\ndelta({args.cand}-{args.base}): 胡牌率 {wr1 - wr0:+.2f}pp  平均分 {sc1 - sc0:+.2f}  "
              f"流局 {dr1 - dr0:+.2f}pp")
        # 晋级判据（A/B 同 seed）：平均分 >= +0.8 且 胡牌率不掉 >2pp
        adv = (sc1 - sc0 >= 0.8) and (wr1 - wr0 >= -2.0)
        print(f"晋级? {'YES' if adv else 'no'}  (判据: 平均分+>=0.8 且 胡牌率不掉>2pp)")


if __name__ == "__main__":
    main()
