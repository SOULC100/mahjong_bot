"""YouCaiBiKao（有财必拷响）策略 A/B 校准。

seat0 = 被测 Smart（config 变体），seat1-3 = Baseline。
所有 config 用同一 seed 序列（牌墙一致）；dealer 按局序 i%4 确定性轮转（保证配对）。
YCB 下分两类赢法并分别统计：
  - 持财神赢（爆头/七客/杠开，win 时 seat0 手仍持财神）
  - 逃回平胡赢（win 时 seat0 手已无财神）
主指标 = seat0 平均分；护栏 = seat0 胡牌率（候选比 base 掉 >2pp 不晋级）。

用法：
  python sim_ab_ycb.py --cand chase1 --n 1000 --seeds 100,200 --workers 6
  python sim_ab_ycb.py --all --n 800 --seeds 100,200 --workers 6
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from sim.engine import Game
from sim.players import Baseline, Smart
from mahjong import shanten as _sh
from mahjong.tiles import LAIZI_INDEX

# 候选 = Smart(**kwargs)。'smart' 为基线（修复引擎 bug 后、未加任何 YCB 新旋钮）。
VARIANTS = {
    # ---- ① 弃财神逃平胡同听门限（ycb_escape_gap：+坚持追爆头 / -更早逃） ----
    "smart":      dict(),                          # gap=0 自然
    "chase1":     dict(ycb_escape_gap=1),          # 稍坚持爆头（逃回须比追爆头快 ≥2 向听才弃财神）
    "chase2":     dict(ycb_escape_gap=2),          # 更坚持
    "hard_chase": dict(ycb_escape_gap=99),         # 几乎不逃，硬追爆头
    "eager":      dict(ycb_escape_gap=-1),         # 更早逃回平胡
    # ---- ② EV/番型框架在 YCB 下是否该开（real smart_bot 线是关的） ----
    "use_ev":     dict(use_ev=True),
    # ---- ③ 杠在 YCB 下是否更值（杠开=免爆头胡法） ----
    "no_gang":    dict(use_gang=False),
    # ②+① 组合（可选候选）
    "use_ev_chase1": dict(use_ev=True, ycb_escape_gap=1),
}

# 默认只跑这组（省 CPU）：①逃回门限族 + ②EV + ③杠开关
DEFAULT_ONLY = ["smart", "chase1", "chase2", "hard_chase", "use_ev", "no_gang"]


def _run_chunk(kwargs, n, seed, mode, opp="baseline"):
    """跑 n 局（seed 起连续递增），返回累计统计 dict。独立进程 worker 用。

    opp="baseline": seat1-3 = Baseline（弱场，主 A/B）
    opp="smart"   : seat1-3 = Smart()（4×Smart 自对弈，强场校验）
    """
    dealer = 0
    st = dict(n=n, seat0_wins=0, draws=0, score=0.0,
              w0_laizi=0, w0_no_laizi=0, esc_discards=0,
              w0_gang=0, mult=0.0, w0_baotou_mult=0.0)
    if opp == "smart":
        strategies = [Smart(**kwargs), Smart(), Smart(), Smart()]
    else:
        strategies = [Smart(**kwargs), Baseline(), Baseline(), Baseline()]
    for i in range(n):
        g = Game(seed=seed + i, youcai_bikao=True)
        if mode == "det":
            g.dealer = (seed + i) % 4   # 庄家只依赖牌墙种子（跨 chunk/worker 一致），保证配对
        else:
            g.dealer = dealer
        w, mult, scores, d = g.play_round(strategies)
        if 33 in g.discards[0]:       # seat0 本局打过财神（弃/飘）
            st["esc_discards"] += 1
        if d:
            st["draws"] += 1
        else:
            if w == 0:
                st["seat0_wins"] += 1
                st["mult"] += mult
                if g.hands[0][LAIZI_INDEX] > 0:
                    st["w0_laizi"] += 1
                    st["w0_baotou_mult"] += mult
                else:
                    st["w0_no_laizi"] += 1
                if any(m.is_gang() for m in g.melds[0]):
                    st["w0_gang"] += 1
            if mode == "rot" and w != dealer:
                dealer = (dealer + 1) % 4
        st["score"] += scores[0]
        if (i + 1) % 100 == 0:
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    return st


def _agg(sts):
    r = dict(n=0, seat0_wins=0, draws=0, score=0.0, w0_laizi=0, w0_no_laizi=0,
             esc_discards=0, w0_gang=0, mult=0.0, w0_baotou_mult=0.0)
    for s in sts:
        for k in r:
            r[k] += s[k]
    return r


def run(name, kwargs, n, seed, mode="det", workers=1, opp="baseline"):
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
    wl_pct = r["w0_laizi"] / max(1, r["seat0_wins"]) * 100
    avg_mult = r["mult"] / max(1, r["seat0_wins"])
    bao_mult = r["w0_baotou_mult"] / max(1, r["w0_laizi"])
    tag = "4xSmart" if opp == "smart" else "v3Bl"
    print(f"{name:14s}[{tag}]: win {r['seat0_wins']:5d}/{nn} ({r['seat0_wins']/nn*100:5.1f}%)  "
          f"avgscore {r['score']/nn:+7.2f}  draw {r['draws']/nn*100:4.0f}%  "
          f"持财神赢 {r['w0_laizi']}({wl_pct:4.0f}%) 逃平胡赢 {r['w0_no_laizi']}  "
          f"打财神局 {r['esc_discards']} 杠赢~{r['w0_gang']}  avgmult {avg_mult:.2f}  ({time.time()-t0:.0f}s)", flush=True)
    return (r["seat0_wins"] / nn * 100, r["score"] / nn, r["draws"] / nn * 100,
            r["w0_laizi"] / nn * 100, r["w0_no_laizi"] / nn * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="smart")
    ap.add_argument("--cand", default="chase1")
    ap.add_argument("--all", action="store_true", help="跑全部变体（相对 base 逐个 A/B）")
    ap.add_argument("--only", default=None, help="逗号分隔要跑的变体名（省 CPU），默认 DEFAULT_ONLY")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seeds", default="100,200")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--mode", choices=["det", "rot"], default="det")
    ap.add_argument("--selftest", action="store_true", help="4xSmart 自对弈（候选 vs 3xSmart，强场）")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x]
    if len(seeds) < 1:
        print("需 ≥1 个 seed")
        return
    opp = "smart" if args.selftest else "baseline"

    if args.only:
        names = [x.strip() for x in args.only.split(",") if x.strip() in VARIANTS]
    elif args.all:
        names = list(VARIANTS)
    else:
        names = [args.base, args.cand]
    # 确保 base 在列（A/B 对照）
    if args.base not in names:
        names = [args.base] + names
    res = {}
    t_all = time.time()
    for name in names:
        seed_res = []
        for sd in seeds:
            seed_res.append(run(name, VARIANTS[name], args.n, sd, args.mode, args.workers, opp))
        res[name] = seed_res
        nn = args.n * len(seeds)
        w = sum(x[0] * args.n for x in seed_res) / nn
        s = sum(x[1] * args.n for x in seed_res) / nn
        d = sum(x[2] * args.n for x in seed_res) / nn
        print(f"  >> {name:14s} 汇总({len(seeds)} seeds): win {w:5.2f}%  avgscore {s:+7.2f}  draw {d:4.0f}%")

    # 逐 config 相对 base 打印 delta（多 seed 逐条 + 汇总）
    if not args.all:
        names = [args.base, args.cand]
    for nm in names:
        if nm == args.base:
            continue
        for i, sd in enumerate(seeds):
            dw = res[nm][i][0] - res[args.base][i][0]
            ds = res[nm][i][1] - res[args.base][i][1]
            print(f"  seed{sd}: delta({nm}-{args.base}) win {dw:+.2f}pp  avgscore {ds:+.2f}")
        w_b = sum(x[0] * args.n for x in res[args.base]) / (args.n * len(seeds))
        w_n = sum(x[0] * args.n for x in res[nm]) / (args.n * len(seeds))
        s_b = sum(x[1] * args.n for x in res[args.base]) / (args.n * len(seeds))
        s_n = sum(x[1] * args.n for x in res[nm]) / (args.n * len(seeds))
        d_b = sum(x[2] * args.n for x in res[args.base]) / (args.n * len(seeds))
        d_n = sum(x[2] * args.n for x in res[nm]) / (args.n * len(seeds))
        adv = (s_n - s_b >= 0.8) and (w_n - w_b >= -2.0)
        print(f"  >> 汇总 delta({nm}-{args.base}): avgscore {s_n - s_b:+.2f}  win {w_n - w_b:+.2f}pp  "
              f"draw {d_n - d_b:+.2f}pp  ADVANCE={'YES' if adv else 'no'}")
    print(f"  (总耗时 {time.time()-t_all:.0f}s)")


if __name__ == "__main__":
    main()
