"""loop.py — 自迭代一轮（Phase A，2026-09-03 审查修订版）。

用法：python -m opt.loop --round r0001 --proposer hill --k 16 --workers 16
       --screen 300 --confirm 1500 [--ycb]
流程：champion 固定 → base 预计算 → proposer 出候选(含 placebo) → screen
      → confirm(2 独立 seed 块, 配对, 按候选数 Bonferroni 校正 z) → holdout(全新 seed, z≥1 + 效果量一致)
→ 自动晋级(条件全过) → 台账 + round_report.md。
修复：confirm 不再重复跑同一 seed 段；proposer 随机种子随轮次派生；placebo 恒 0 必被拒。
"""
import argparse
import random
import time

from opt import arena, gate, ledger
from opt.genome import genome_id, resolved
from opt.propose import HillClimb, Random, Template

_PROPOSERS = {"hill": HillClimb, "random": Random, "template": Template}


def _fmt(d):
    if d is None:
        return "None"
    return ("mean=%+.3f se=%.3f z=%+.2f win%+.2fpp dealer=%s idle=%s n=%d"
            % (d["mean"], d["se"], d["z"], d["win_pp"],
               ("%+.3f" % d["dealer"][0]) if d["dealer"][0] is not None else ".",
               ("%+.3f" % d["idle"][0]) if d["idle"][0] is not None else ".",
               d["n"]))


def run(rid, proposer_name, k, workers, n_screen=300, n_confirm=1500, ycb=False, seedbase=0):
    champ = ledger.current_champion()
    champ_id = genome_id(champ)
    P = _PROPOSERS[proposer_name]()
    t0 = time.time()
    R = int("".join(ch for ch in rid if ch.isdigit()) or 0)
    sb = 10_000_000 + seedbase + R * 1_000_000
    rng = random.Random(sb)            # 种子随轮次派生，避免 champion 不变时每轮重复同批候选
    arena.set_global_pool(workers)     # 整轮共享一个 Pool（防 Windows spawn 句柄耗尽）

    s_screen = sb
    s_cA, s_cB = sb + 100_000, sb + 200_000
    s_hA, s_hB = sb + 300_000, sb + 400_000

    print("== round %s | proposer=%s k=%d workers=%d champ=%s ==" % (rid, proposer_name, k, workers, champ_id), flush=True)

    props = P.propose(champ, k, rng)
    props.append({"genome": resolved(champ), "diff": {}, "rationale": "PLACEBO(必须被拒)", "proposer": "placebo"})
    cands = [{"cid": genome_id(resolved(p["genome"])), "genome": resolved(p["genome"]),
              "diff": p.get("diff", {}), "rationale": p.get("rationale", ""),
              "proposer": p.get("proposer", "")} for p in props]

    print("预计算 base ...", flush=True)
    b_screen = arena.run_seat(champ, champ, s_screen, n_screen, ycb=ycb, workers=workers)
    b_A = arena.run_seat(champ, champ, s_cA, n_confirm, ycb=ycb, workers=workers)
    b_B = arena.run_seat(champ, champ, s_cB, n_confirm, ycb=ycb, workers=workers)

    survivors = []
    for c in cands:
        raw = arena.run_seat(c["genome"], champ, s_screen, n_screen, ycb=ycb, workers=workers)
        r = arena.deltas(b_screen, raw)
        ok = gate.screen_ok(r)
        ledger.append_ledger(rid, dict(round=rid, cid=c["cid"], proposer=c["proposer"], parent=champ_id,
                                       n_block=n_screen, mean=r["mean"], se=r["se"], z=r["z"],
                                       win_pp=r["win_pp"], dealer_mean=r["dealer"][0], idle_mean=r["idle"][0],
                                       status="screen_ok" if ok else "screen_reject", note=c["rationale"]))
        print("  screen %s %s %s" % (c["cid"], "OK " if ok else "REJ", _fmt(r)), flush=True)
        if ok:
            survivors.append(c)
    print("screen 幸存 %d/%d" % (len(survivors), len(cands)), flush=True)

    nsur = len([s for s in survivors if s["proposer"] != "placebo"])
    k_eff = max(1, nsur)               # 多重比较按真实候选数校正
    advanced = []
    for c in survivors:
        cand_A = arena.run_seat(c["genome"], champ, s_cA, n_confirm, ycb=ycb, workers=workers)
        cand_B = arena.run_seat(c["genome"], champ, s_cB, n_confirm, ycb=ycb, workers=workers)
        rA = arena.deltas(b_A, cand_A)
        rB = arena.deltas(b_B, cand_B)
        dm = arena.deltas(arena.merge(b_A, b_B), arena.merge(cand_A, cand_B))
        passed = gate.confirm_pass([rA, rB], dm, k=k_eff)
        ledger.append_ledger(rid, dict(round=rid, cid=c["cid"], proposer=c["proposer"], parent=champ_id,
                                       n_block=2 * n_confirm, mean=dm["mean"], se=dm["se"], z=dm["z"],
                                       win_pp=dm["win_pp"], dealer_mean=dm["dealer"][0], idle_mean=dm["idle"][0],
                                       status="confirm_pass" if passed else "confirm_reject", note=c["rationale"]))
        print("  confirm %s %s %s" % (c["cid"], "PASS" if passed else "no  ", _fmt(dm)), flush=True)
        if passed:
            advanced.append((c, dm["mean"]))

    placebo_adv = any(c["proposer"] == "placebo" for c, _ in advanced)
    best = None
    if advanced and not placebo_adv:
        hb = arena.merge(arena.run_seat(champ, champ, s_hA, n_confirm, ycb=ycb, workers=workers),
                         arena.run_seat(champ, champ, s_hB, n_confirm, ycb=ycb, workers=workers))
        for c, cmean in advanced:
            hc = arena.merge(arena.run_seat(c["genome"], champ, s_hA, n_confirm, ycb=ycb, workers=workers),
                             arena.run_seat(c["genome"], champ, s_hB, n_confirm, ycb=ycb, workers=workers))
            hm = arena.deltas(hb, hc)
            ok = gate.holdout_pass(hm, confirm_mean=cmean)
            ledger.append_ledger(rid, dict(round=rid, cid=c["cid"], proposer=c["proposer"], parent=champ_id,
                                           n_block=2 * n_confirm, mean=hm["mean"], se=hm["se"], z=hm["z"],
                                           win_pp=hm["win_pp"], dealer_mean=hm["dealer"][0], idle_mean=hm["idle"][0],
                                           status="holdout_pass" if ok else "holdout_reject", note="holdout"))
            print("  holdout %s %s %s" % (c["cid"], "PASS" if ok else "no  ", _fmt(hm)), flush=True)
            if ok and (best is None or hm["mean"] > best[1]):
                best = (c, hm["mean"])

    report = ["# round %s" % rid, "champion=%s" % champ_id, "placebo_advanced=%s (必须 False)" % placebo_adv, ""]
    report.append("## 候选 & diff")
    for c in cands:
        report.append("- %s [%s] %s" % (c["cid"], c["proposer"], c["rationale"]))
        report.append("    diff=%s" % (c["diff"] or "{}"))
    report.append("")
    if best and not placebo_adv:
        c, m = best
        ledger.promote(c["genome"], rid, note=c["rationale"])
        report.append("## 晋级")
        report.append("新 champion = %s (%s), holdout mean=%+.3f" % (c["cid"], c["diff"], m))
        print(">>> 晋级 champion -> %s (%s) holdout mean=%+.3f" % (c["cid"], c["diff"], m), flush=True)
    else:
        report.append("## 本轮无晋级")
        if placebo_adv:
            report.append("⚠️ placebo 晋级 → 门槛失效，本轮作废")
        print(">>> 本轮无晋级" + ("（placebo 晋级=异常）" if placebo_adv else ""), flush=True)
    report.append("")
    report.append("耗时 %.0fs" % (time.time() - t0))
    arena.close_global_pool()
    ledger.write_round_report(rid, report)
    print("round_report 写入 opt/rounds/%s/round_report.md" % rid, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--proposer", choices=list(_PROPOSERS), default="hill")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--screen", type=int, default=300)
    ap.add_argument("--confirm", type=int, default=1500)
    ap.add_argument("--ycb", action="store_true")
    ap.add_argument("--seedbase", type=int, default=0)
    a = ap.parse_args()
    run(a.round, a.proposer, a.k, a.workers, a.screen, a.confirm, a.ycb, a.seedbase)


if __name__ == "__main__":
    main()
