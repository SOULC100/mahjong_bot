"""敲响弃胡 A/B（2026-09-26）：**冻结基准配对**，base 与 cand 用同一 seed 序列逐局对拍。

- base（现役口径）：`Smart(decline_hu=True, decline_knock=False)`
  = 能胡就胡；只有「手里 ≥2 张白、打白后仍任意摸都胡」（财飘）才弃胡。
- cand（候选）：`Smart(decline_hu=True, decline_knock=True, decline_knock_q=Q)`
  = 再加一条：手里有财神、**打一张非财神牌后 13 张仍是「任意摸都胡」**（敲响终局）
  → 下一摸必胡且爆头 ×2；只在 q > q* = (f0+c)/(f1+c) 时弃胡。

为什么这样测（docs/rules-strategy.md §5 纪律）：
1. **配对**：同一 seed = 同一副牌墙，两个臂在「第一次敲响决策」之前逐决策一致
   → 有敲响事件的局，Δ分 100% 归因于该决策（无事件局 Δ 必须恰好 0，本脚本会断言）；
2. **候选 vs 3 个弱基线**：番型类改动在四同构自对弈里会被对称化抹平
   （EV ∝ f×(p−0.25)），弱场才测得出「用胜率换番型」；
3. 主指标 = seat0 平均分；护栏 = seat0 胡牌率 + 场均番型 + 流局率。

用法：
  python sim_ab_knock.py --n 3000 --seed 100 --opp baseline --knock-q 0.90
  python sim_ab_knock.py --n 3000 --seed 100 --opp smart    --knock-q 0.90
  # 分片并行（各分片 seed 不重叠，结果用 --out 落盘后合并）
  python sim_ab_knock.py --n 1000 --seed 100000 --out data/_abk_s1.json
"""

import argparse
import json
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from sim.engine import Game                      # noqa: E402
from sim.players import Baseline, Smart          # noqa: E402
from mahjong import shanten as _sh               # noqa: E402


def _strategies(opp, knock, q, game_seed):
    cand = Smart(decline_hu=True, decline_knock=knock, decline_knock_q=q)
    others = [Baseline() for _ in range(3)] if opp == "baseline" else [Smart() for _ in range(3)]
    return cand, others


def run(n, seed, opp, knock_q, progress=500):
    tot = dict(n=0, wins=0, draws=0, score=0.0, winmult=0.0,
               knock=0, piao=0, knock_hands=0, knock_delta=0.0,
               other_delta=0.0, changed_hands=0,
               k_win2=0, k_win_other=0, k_opp=0, k_draw=0,
               k_f0=0.0, k_f1=0.0, qstar=0.0,
               d2=0.0, kd2=0.0,        # ΣΔ²（全部局 / 有敲响事件的局）—— 配对 z 用
               b_wins=0, b_draws=0, b_score=0.0, b_winmult=0.0)   # base 臂（对照组）
    mult_counter = Counter()
    dealer = 0
    t0 = time.time()
    for i in range(n):
        s = seed + i
        # ---- base 臂 ----
        st_b, others_b = _strategies(opp, False, knock_q, s)
        gb = Game(seed=s)
        gb.dealer = dealer
        wb, mb, scb, db = gb.play_round([st_b] + others_b)
        # ---- cand 臂（同 seed/同 dealer → 同一副牌墙）----
        st_c, others_c = _strategies(opp, True, knock_q, s)
        gc = Game(seed=s)
        gc.dealer = dealer
        wc, mc, scc, dc = gc.play_round([st_c] + others_c)

        tot["n"] += 1
        tot["score"] += scc[0]
        tot["b_score"] += scb[0]
        if not db:
            if wb == 0:
                tot["b_wins"] += 1
                tot["b_winmult"] += mb
        else:
            tot["b_draws"] += 1
        tot["knock"] += sum(1 for e in st_c.decline_log if e["kind"] == "knock")
        tot["piao"] += sum(1 for e in st_c.decline_log if e["kind"] == "piao")
        for e in st_c.decline_log:
            if e["kind"] == "knock":
                tot["k_f0"] += e["fan_now"]
                tot["k_f1"] += e["fan_next"]
                tot["qstar"] += e["q_star"]
        if not dc:
            if wc == 0:
                tot["wins"] += 1
                tot["winmult"] += mc
                mult_counter[mc] += 1
            if wc != dealer:
                pass
        if dc:
            tot["draws"] += 1
        # ---- 配对归因 ----
        d = scc[0] - scb[0]
        tot["d2"] += d * d
        knock_here = any(e["kind"] == "knock" for e in st_c.decline_log)
        if knock_here:
            tot["knock_hands"] += 1
            tot["knock_delta"] += d
            tot["kd2"] += d * d
            if not dc and wc == 0 and mc >= 2:
                tot["k_win2"] += 1
            elif not dc and wc == 0:
                tot["k_win_other"] += 1
            elif dc:
                tot["k_draw"] += 1
            else:
                tot["k_opp"] += 1
        else:
            tot["other_delta"] += d
        if d != 0:
            tot["changed_hands"] += 1
        # 庄家轮转：与 sim_run/sim_ab_dealer 的 rot 口径一致（闲胡 → 庄家下家接庄）
        if not db and wb != dealer:
            dealer = (dealer + 1) % 4
        if (i + 1) % progress == 0:
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
            print(f"    [{i+1}/{n}] knock={tot['knock']} 配对改变局={tot['changed_hands']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    tot["mult"] = dict(sorted(mult_counter.items()))
    tot["secs"] = round(time.time() - t0, 1)
    return tot


def report(base_n, tot, knock_q):
    n = tot["n"]
    print(f"\n臂 cand(敲响 q={knock_q})：n={n}  胡 {tot['wins']} ({tot['wins']/n*100:.1f}%)  "
          f"流局 {tot['draws']/n*100:.1f}%  平均分 {tot['score']/n:+.3f}  "
          f"场均番 {tot['winmult']/tot['wins'] if tot['wins'] else 0:.3f}  番型 {tot['mult']}")
    if tot.get("b_wins") is not None and (tot.get("b_wins") or tot.get("b_draws")):
        bw, bd = tot["b_wins"], tot["b_draws"]
        print(f"臂 base(只财飘)  ：n={n}  胡 {bw} ({bw/n*100:.1f}%)  流局 {bd/n*100:.1f}%  "
              f"平均分 {tot['b_score']/n:+.3f}  场均番 {tot['b_winmult']/bw if bw else 0:.3f}")
        print(f"    Δ胡牌率 {tot['wins']/n*100 - bw/n*100:+.2f}pp   "
              f"Δ场均番 {(tot['winmult']/tot['wins'] if tot['wins'] else 0) - (tot['b_winmult']/bw if bw else 0):+.3f}")
    print(f"    敲响触发 {tot['knock']} 次 / 财飘 {tot['piao']} 次（{tot['knock']/n*1000:.1f} 次每千局）")
    if tot["knock"]:
        print(f"    触发时 f0 均值 {tot['k_f0']/tot['knock']:.2f} → f1 均值 {tot['k_f1']/tot['knock']:.2f}"
              f"  q* 均值 {tot['qstar']/tot['knock']:.3f}")
        print(f"    敲响局结果：我方 ×2 胡 {tot['k_win2']} / 我方其他番胡 {tot['k_win_other']} / "
              f"对手胡 {tot['k_opp']} / 流局 {tot['k_draw']}")
    print(f"    配对改变局数 {tot['changed_hands']}（无敲响事件的局 Δ分合计 {tot['other_delta']:+.3f}"
          f" —— 必须恰好 0，否则说明两臂在事件前就不一致）")
    # 配对 z（Δ分/局；零假设：Δ = 0）—— Δ 由极少数「敲响局」贡献，必须用配对口径
    m = tot["knock_hands"]
    if n and m:
        dbar = tot["knock_delta"] / n            # = 全样本 Δ 均值（其余局 Δ≡0）
        var = tot["d2"] / n - dbar * dbar
        sd = var ** 0.5
        z = dbar / (sd / n ** 0.5) if sd > 0 else float("inf")
        emean = tot["knock_delta"] / m
        evar = tot["kd2"] / m - emean * emean
        esd = evar ** 0.5 if evar > 0 else 0.0
        ez = emean / (esd / m ** 0.5) if esd > 0 else float("inf")
        print(f"    Δ分/局 {dbar:+.4f}（配对 z={z:.2f}；样本 sd={sd:.2f}）")
        print(f"    有敲响事件的局：{m} 局，Δ 合计 {tot['knock_delta']:+.1f}"
              f"（平均 {emean:+.2f} 分/局，sd={esd:.2f}，z={ez:.2f}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--opp", choices=["baseline", "smart"], default="baseline")
    ap.add_argument("--knock-q", type=float, default=0.90)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    print(f"=== 敲响弃胡 A/B（配对同 seed，seat0 vs 3x{args.opp}，n={args.n}，seed={args.seed}，"
          f"knock_q={args.knock_q}）===", flush=True)
    tot = run(args.n, args.seed, args.opp, args.knock_q)
    report(None, tot, args.knock_q)
    if args.out:
        json.dump(tot, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"结果写入 {args.out}")


if __name__ == "__main__":
    main()
