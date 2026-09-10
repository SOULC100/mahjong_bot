"""D1 庄家上家防守 A/B：4-Smart 自对弈（庄家才可能吃，D1 才能测到）。

seat0 = 被测策略（Smart(defend_dealer=?)），seat1-3 = 普通 Smart()。
主指标 = seat0 平均分；护栏 = seat0 胡牌率（候选掉 >2pp 不晋级）。

mode=fixed：dealer 恒 = 1 -> seat0 恒为庄家上家（防守恒生效），放大 D1 信号。
mode=rot  ：dealer 正常轮转（连庄简化），防守只在 seat0 是庄家上家那 ~1/4 局生效。

--workers >1 时按 seed 段并行（局间独立，结果确定性不受影响）。

用法：
  python sim_ab_d1.py --base smart --cand d1_basic --n 1000 --seed 100 --mode fixed --workers 8
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from sim.engine import CHI, Game
from sim.players import Smart
from mahjong import shanten as _sh

# seat0 候选/基线 Smart kwargs（传给 Smart()）
VARIANTS = {
    "smart": dict(),                                    # 基线：普通 Smart（无防守）
    # ---- D1 喂庄防守候选（默认关） ----
    "d1_basic": dict(defend_dealer=True, defend_pen=40.0, defend_window=None, defend_hot_max=1),
    "d1_pen60": dict(defend_dealer=True, defend_pen=60.0, defend_window=None, defend_hot_max=1),
    "d1_pen90": dict(defend_dealer=True, defend_pen=90.0, defend_window=None, defend_hot_max=1),
    "d1_pen120": dict(defend_dealer=True, defend_pen=120.0, defend_window=None, defend_hot_max=1),
    "d1_pen200": dict(defend_dealer=True, defend_pen=200.0, defend_window=None, defend_hot_max=1),
    "d1_pen300": dict(defend_dealer=True, defend_pen=300.0, defend_window=None, defend_hot_max=1),
    "d1_w3": dict(defend_dealer=True, defend_pen=40.0, defend_window=3, defend_hot_max=1),
    "d1_w6": dict(defend_dealer=True, defend_pen=40.0, defend_window=6, defend_hot_max=1),
    "d1_hot0": dict(defend_dealer=True, defend_pen=40.0, defend_window=None, defend_hot_max=0),
    "d1_hot2": dict(defend_dealer=True, defend_pen=40.0, defend_window=None, defend_hot_max=2),
    # tile 级：按「活互补搭子数」在危险花色内细分（边张惩罚低/为 0）
    "d1_pair": dict(defend_dealer=True, defend_pen=100.0, defend_window=None, defend_hot_max=1, defend_mode="pair"),
    "d1_pair200": dict(defend_dealer=True, defend_pen=200.0, defend_window=None, defend_hot_max=1, defend_mode="pair"),
}


def _run_chunk(kwargs, n, seed, mode, fixed_dealer):
    """跑 n 局（seed 起连续递增），返回累计统计 dict。独立进程 worker 用。"""
    dealer = fixed_dealer if mode == "fixed" else 0
    st = dict(n=n, seat0_wins=0, draws=0, score=0.0, dealer_wins=0,
              feed0=0, dealer_chi_total=0, up_games=0, up_score=0.0)
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        strategies = [Smart(**kwargs), Smart(), Smart(), Smart()]
        w, mult, scores, d = g.play_round(strategies)
        for m in g.melds[dealer]:
            if m.kind == CHI:
                st["dealer_chi_total"] += 1
                if m.from_seat == 0:
                    st["feed0"] += 1
        if (0 + 1) % 4 == dealer:
            st["up_games"] += 1
            st["up_score"] += scores[0]
        if d:
            st["draws"] += 1
        else:
            if w == dealer:
                st["dealer_wins"] += 1
            if w == 0:
                st["seat0_wins"] += 1
            if mode == "rot" and w != dealer:
                dealer = (dealer + 1) % 4
        st["score"] += scores[0]
        if (i + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    return st


def _agg(sts):
    r = dict(n=0, seat0_wins=0, draws=0, score=0.0, dealer_wins=0,
             feed0=0, dealer_chi_total=0, up_games=0, up_score=0.0)
    for s in sts:
        for k in r:
            r[k] += s[k]
    return r


def run(name, kwargs, n, seed, mode="fixed", fixed_dealer=1, workers=1):
    t0 = time.time()
    if workers <= 1:
        sts = [_run_chunk(kwargs, n, seed, mode, fixed_dealer)]
    else:
        import multiprocessing as mp
        base, extra = divmod(n, workers)
        sizes = [base + 1] * extra + [base] * (workers - extra)
        sizes = [c for c in sizes if c > 0]
        args = []
        s = seed
        for c in sizes:
            args.append((kwargs, c, s, mode, fixed_dealer))
            s += c
        with mp.Pool(min(workers, len(args))) as pool:
            sts = pool.starmap(_run_chunk, args)
    r = _agg(sts)
    nn = r["n"]
    up_avg = f"{r['up_score'] / max(1, r['up_games']):+.2f}"
    print(f"{name:12s}: win {r['seat0_wins']:5d}/{nn} ({r['seat0_wins']/nn*100:5.1f}%)  "
          f"avgscore {r['score']/nn:+7.2f}  dealerwin {r['dealer_wins']/nn*100:5.1f}%  "
          f"draw {r['draws']/nn*100:4.0f}%  feed0 {r['feed0']}  dealerchi {r['dealer_chi_total']}"
          f"  up_avg {up_avg}  ({time.time()-t0:.0f}s)", flush=True)
    return (r["seat0_wins"] / nn * 100, r["score"] / nn,
            r["dealer_wins"] / nn * 100, r["draws"] / nn * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="smart", choices=list(VARIANTS))
    ap.add_argument("--cand", default="d1_basic", choices=list(VARIANTS))
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--mode", choices=["fixed", "rot"], default="fixed", help="fixed=dealer恒1（放大D1），rot=正常轮转")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", choices=["base", "cand", "both"], default="both")
    args = ap.parse_args()

    print(f"=== D1 A/B: {args.base} vs {args.cand} ({args.n} games, seed {args.seed}, "
          f"4-Smart self-play, mode={args.mode}, workers={args.workers}) ===")
    res = {}
    if args.only in ("both", "base"):
        res["base"] = run(args.base, VARIANTS[args.base], args.n, args.seed, args.mode, workers=args.workers)
    if args.only in ("both", "cand"):
        res["cand"] = run(args.cand, VARIANTS[args.cand], args.n, args.seed, args.mode, workers=args.workers)
    if args.only == "both":
        w0, s0, dw0, dr0 = res["base"]
        w1, s1, dw1, dr1 = res["cand"]
        print(f"\ndelta({args.cand}-{args.base}): win {w1-w0:+.2f}pp  avgscore {s1-s0:+.2f}  "
              f"dealerwin {dw1-dw0:+.2f}pp  draw {dr1-dr0:+.2f}pp")
        adv = (s1 - s0 >= 0.8) and (w1 - w0 >= -2.0)
        print(f"ADVANCE? {'YES' if adv else 'no'}  (criterion: avgscore +>=0.8 and win not down >2pp)")


if __name__ == "__main__":
    main()
