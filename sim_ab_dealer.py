"""坐庄策略（dealer_policy）A/B：seat0 = 被测策略，seat1-3 = 现役 Smart（或 3×Baseline）。

被测只改「自己当庄时」的打法（dealer_policy='off' 时 = 现行为基线，不区分庄闲）。

主指标 = seat0 平均分；护栏 = seat0 胡牌率（候选掉 >2pp 不晋级）。
按「seat0 当庄 vs 当闲」拆平均分（引擎 Game.dealer 知道谁庄；rot 模式下同一策略
在不同 seed 里当庄/当闲都会出现，统计时按 g.dealer==0 拆桶）。

mode:
  rot    - dealer 正常轮转（闲胡 → 庄下家接庄；庄胡/流局连庄），与 sim_run 一致。
           seat0 约 1/4 局当庄、3/4 局当闲，给出真实分布的总体/拆桶指标。
  dealer0- dealer 恒 = 0 → seat0 恒当庄，放大「坐庄抢速」信号（筛候选用）。
opp:
  smart   - 3 × 现役 Smart()（强场，主竞技场）
  baseline- 3 × Baseline（弱对照）

用法：
  python sim_ab_dealer.py --cand aggr --mode rot    --n 2000 --seed 100 --workers 10
  python sim_ab_dealer.py --cand aggr --mode dealer0 --n 800  --seed 100 --workers 10 --opp smart
  python sim_ab_dealer.py --base off --cand bigfan  --mode dealer0 --n 800 ...
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from sim.engine import Game, PENG, CHI, ANGANG, MINGGANG, BUGANG
from sim.players import Baseline, Smart
from mahjong import shanten as _sh

# 传给 Smart() 的 kwargs。off = 现行为基线（dealer_policy='off'，不区分庄闲）。
VARIANTS = {
    "off": dict(dealer_policy="off"),
    # ---- 坐庄抢速候选（dealer_policy 在 Smart 里定义） ----
    "aggr": dict(dealer_policy="aggr"),                # 抢速：出牌紧爆头/拆杠 + 当庄放宽吃碰
    "aggr_nopiao": dict(dealer_policy="aggr_nopiao"),  # 抢速 + 当庄不飘财
    "bigfan": dict(dealer_policy="bigfan"),            # 反向对照：当庄时番型权重×8 走大番（旧 dealer_aware 方向）
}


def _meld_kinds(game, seat):
    c = {"peng": 0, "chi": 0, "gang": 0}
    for m in game.melds[seat]:
        if m.kind == PENG:
            c["peng"] += 1
        elif m.kind == CHI:
            c["chi"] += 1
        elif m.kind in (ANGANG, MINGGANG, BUGANG):
            c["gang"] += 1
    return c


def _run_chunk(kwargs, n, seed, mode, opp):
    """跑 n 局（seed 起连续递增），返回累计统计 dict。独立进程 worker 用。

    rot 模式：dealer 从 0 起按 庄胡连庄/闲胡庄下家接庄 在 chunk 内演化（与 sim_run 一致）。
    dealer0 模式：dealer 恒 0（seat0 恒庄，放大器）。
    """
    use_baseline_opp = (opp == "baseline")
    st = dict(n=n, draws=0, wins=0, score=0.0, winmult=0.0,
              dl_games=0, dl_wins=0, dl_score=0.0, dl_winmult=0.0,
              id_games=0, id_wins=0, id_score=0.0, id_winmult=0.0,
              dwin=0,  # 庄家胡局数（seat0 视角=0 时即 seat0 胡；作整体对照）
              meld_peng=0, meld_chi=0, meld_gang=0)
    dealer = 0  # rot 从 0 演化；dealer0 恒 0
    for i in range(n):
        g = Game(seed=seed + i)
        g.dealer = dealer
        if use_baseline_opp:
            strategies = [Smart(**kwargs), Baseline(), Baseline(), Baseline()]
        else:
            strategies = [Smart(**kwargs), Smart(), Smart(), Smart()]
        w, mult, scores, d = g.play_round(strategies)
        mk = _meld_kinds(g, 0)
        st["meld_peng"] += mk["peng"]
        st["meld_chi"] += mk["chi"]
        st["meld_gang"] += mk["gang"]
        is_dl = (g.dealer == 0)
        if is_dl:
            st["dl_games"] += 1
            st["dl_score"] += scores[0]
            if not d and w == 0:
                st["dl_wins"] += 1
                st["dl_winmult"] += mult
        else:
            st["id_games"] += 1
            st["id_score"] += scores[0]
            if not d and w == 0:
                st["id_wins"] += 1
                st["id_winmult"] += mult
        if d:
            st["draws"] += 1
        else:
            if w == 0:
                st["wins"] += 1
                st["winmult"] += mult
            if w == dealer:
                st["dwin"] += 1
        st["score"] += scores[0]
        if mode == "rot" and not d and w != dealer:
            dealer = (dealer + 1) % 4  # 闲胡 → 庄家下家接庄（与 sim_run/guide 一致）；dealer0 恒庄
        if (i + 1) % 40 == 0:  # 防 shanten lru_cache 无限增长（4-Smart 强场每局调点多，需勤清）
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    return st


def _agg(sts):
    r = dict(n=0, draws=0, wins=0, score=0.0, winmult=0.0,
             dl_games=0, dl_wins=0, dl_score=0.0, dl_winmult=0.0,
             id_games=0, id_wins=0, id_score=0.0, id_winmult=0.0,
             dwin=0, meld_peng=0, meld_chi=0, meld_gang=0)
    for s in sts:
        for k in r:
            r[k] += s[k]
    return r


def run(name, kwargs, n, seed, mode="rot", opp="smart", workers=1):
    t0 = time.time()
    if workers <= 1:
        sts = [_run_chunk(kwargs, n, seed, mode, opp)]
    else:
        import multiprocessing as mp
        base, extra = divmod(n, workers)
        sizes = [base + 1] * extra + [base] * (workers - extra)
        sizes = [c for c in sizes if c > 0]
        args = []
        s = seed
        for c in sizes:
            args.append((kwargs, c, s, mode, opp))
            s += c
        with mp.Pool(min(workers, len(args))) as pool:
            sts = pool.starmap(_run_chunk, args)
    r = _agg(sts)
    nn = r["n"]
    dl, id_ = r["dl_games"], r["id_games"]
    w = r["wins"]
    def _pct(a, b):
        return a / b * 100 if b else 0.0
    def _avg(x, b):
        return x / b if b else 0.0
    print(f"{name:12s} [{mode} vs {opp}]: win {w:5d}/{nn} ({_pct(w, nn):5.1f}%)  "
          f"avg {_avg(r['score'], nn):+7.2f}  draw {_pct(r['draws'], nn):4.0f}%  "
          f"dwin {_pct(r['dwin'], nn - r['draws']):4.1f}%  meld P/C/G {r['meld_peng']}/{r['meld_chi']}/{r['meld_gang']}  "
          f"({time.time() - t0:.0f}s)", flush=True)
    print(f"     当庄: n={dl:5d}  win {_pct(r['dl_wins'], dl):5.1f}%  avg {_avg(r['dl_score'], dl):+7.2f}  "
          f"winmult {_avg(r['dl_winmult'], r['dl_wins']):.2f}", flush=True)
    print(f"     当闲: n={id_:5d}  win {_pct(r['id_wins'], id_):5.1f}%  avg {_avg(r['id_score'], id_):+7.2f}  "
          f"winmult {_avg(r['id_winmult'], r['id_wins']):.2f}", flush=True)
    res = dict(
        avg=_avg(r['score'], nn), win=_pct(w, nn), draw=_pct(r['draws'], nn),
        dl_avg=_avg(r['dl_score'], dl), dl_win=_pct(r['dl_wins'], dl), dl_n=dl,
        id_avg=_avg(r['id_score'], id_), id_win=_pct(r['id_wins'], id_), id_n=id_,
        meld_peng=r['meld_peng'], meld_chi=r['meld_chi'], meld_gang=r['meld_gang'],
    )
    return res


def _delta(a, b, label="cand-base"):
    """b = 候选, a = 基线 时 delta = b - a。约定调用 run 先 base 后 cand。"""
    print(f"\ndelta({label}):  avg {b['avg'] - a['avg']:+.2f}   win {b['win'] - a['win']:+.2f}pp  "
          f"draw {b['draw'] - a['draw']:+.2f}pp")
    print(f"   当庄 delta: avg {b['dl_avg'] - a['dl_avg']:+.2f}  win {b['dl_win'] - a['dl_win']:+.2f}pp")
    print(f"   当闲 delta: avg {b['id_avg'] - a['id_avg']:+.2f}  win {b['id_win'] - a['id_win']:+.2f}pp")
    adv = (b['avg'] - a['avg'] >= 0.8) and (b['win'] - a['win'] >= -2.0)
    print(f"ADVANCE? {'YES' if adv else 'no'}  (criterion: 总体 avg +>=0.8 and win not down >2pp)")
    return adv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="off", choices=list(VARIANTS))
    ap.add_argument("--cand", default="aggr", choices=list(VARIANTS))
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--mode", choices=["rot", "dealer0"], default="rot",
                    help="rot=正常轮转（真实分布）；dealer0=seat0 恒庄（放大信号）")
    ap.add_argument("--opp", choices=["smart", "baseline"], default="smart")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", choices=["base", "cand", "both"], default="both")
    args = ap.parse_args()

    print(f"=== dealer_policy A/B: {args.base} vs {args.cand} ({args.n} games, seed {args.seed}, "
          f"seat0 vs 3x{args.opp}, mode={args.mode}, workers={args.workers}) ===")
    if args.only in ("both", "base"):
        res_base = run(args.base, VARIANTS[args.base], args.n, args.seed, args.mode, args.opp, workers=args.workers)
    if args.only in ("both", "cand"):
        res_cand = run(args.cand, VARIANTS[args.cand], args.n, args.seed, args.mode, args.opp, workers=args.workers)
    if args.only == "both":
        _delta(res_base, res_cand, f"{args.cand}-{args.base}")


if __name__ == "__main__":
    main()
