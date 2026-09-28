"""R7「碰门形状判据」单测（2026-09-23）。

被测：`mahjong.decision.should_peng(..., bao_live=...)` 与
`mahjong.decision.discard_decision(..., plan_bao_live=...)`，以及 `sim.players.Smart` 的透传。

三条必须成立的性质：
  ① 默认关（`bao_live=False`）= 与旧行为逐位一致；
  ② 形状判据在「不亏向听 + 碰后爆头路线活着 + 持白」时**确实会把 False 变 True**（不是惰性开关）；
  ③ 阴性/无效档必须**恒不触发**（`bao_live_slack=-1`、`plan_bao_live_min_melds=99`）——
     用来保证「装置」可信：一旦这些档出现差异，说明实现写错了。
"""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mahjong.decision import should_peng, discard_decision, plan_route    # noqa: E402
from mahjong.shanten import shanten, shanten_baotou, clear_caches     # noqa: E402
from mahjong.tiles import tile_from_str, LAIZI_INDEX                 # noqa: E402
from sim.players import Smart                                         # noqa: E402

PASS = FAIL = 0


def ck(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  ✅ %s" % name)
    else:
        FAIL += 1
        print("  ❌ %s：got=%r want=%r" % (name, got, want))


def hand(s):
    """ASCII 牌串 → 34 维计数（w=万 t=条 b=筒，白=财神）。"""
    c = [0] * 34
    i = 0
    while i < len(s):
        if s[i] == " ":
            i += 1
            continue
        if s[i] in "东南西北中发白":
            c[tile_from_str(s[i])] += 1
            i += 1
        else:
            c[tile_from_str(s[i:i + 2])] += 1
            i += 2
    return c


def main():
    print("=== R7 碰门形状判据 ===")

    # 探针搜出的真实用例（`data/_tmp_find_peng_cases.py`）：
    #  s=标准向听、best=碰后最优向听（= s ⇒ 不亏速、旧判据拒绝）、sb=爆头向听
    A = hand("1w 5w 4b 5b 5b 6b 6b 6b 6b 7b 北 北 白")     # s=1 best=1 sb=2
    B = hand("1t 1t 1t 2t 3t 4b 5b 6b 8b 8b 北 北 白")     # s=0 best=0 sb=2
    for tag, h, t in (("A", A, "5b"), ("B", B, "1t")):
        ti = tile_from_str(t)
        ck("%s 前置：手里有 ≥2 张 %s" % (tag, t), h[ti] >= 2, True)
        base = should_peng(h, ti, 0, ukeire_gate=False, bao_live=False)
        live = should_peng(h, ti, 0, ukeire_gate=False, bao_live=True)
        noop = should_peng(h, ti, 0, ukeire_gate=False, bao_live=True, bao_live_slack=-1)
        ck("%s 旧判据拒绝（不亏速）" % tag, base, False)
        ck("%s 形状判据接受（判据真的会动）" % tag, live, True)
        ck("%s 阴性档 slack=-1 恒不触发" % tag, noop, False)
        ck("%s 副露上限 0 时不触发" % tag,
           should_peng(h, ti, 0, ukeire_gate=False, bao_live=True, bao_live_max_melds=0), False)

    # 不持白 → 不触发（need_white 默认 True）
    nw = hand("1w 5w 4b 5b 5b 6b 6b 6b 6b 7b 北 北 中")
    ck("不持白时不触发", should_peng(nw, tile_from_str("5b"), 0, ukeire_gate=False,
                                     bao_live=True), False)
    # need_white=False 只能**放宽**不能收紧（单调性；在真实手牌样本上验证）
    random.seed(4242)
    loose = strict = 0
    for _ in range(400):
        c = [0] * 34
        for _m in range(random.randint(2, 3)):
            lo = random.choice([0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23, 24])
            if all(c[x] < 3 for x in (lo, lo + 1, lo + 2)):
                for x in (lo, lo + 1, lo + 2):
                    c[x] += 1
        for _ in range(random.randint(0, 2)):
            t = random.randrange(34)
            if c[t] <= 2:
                c[t] += 2
        n = sum(c)
        while n < 13:
            x = random.randrange(34)
            if c[x] < 4:
                c[x] += 1
                n += 1
        while n > 13:
            for x in range(34):
                if c[x] > 0 and x != LAIZI_INDEX:
                    c[x] -= 1
                    n -= 1
                    break
        for t in range(34):
            if t == LAIZI_INDEX or c[t] < 2:
                continue
            strict += 1 if should_peng(c, t, 0, ukeire_gate=False, bao_live=True) else 0
            loose += 1 if should_peng(c, t, 0, ukeire_gate=False, bao_live=True,
                                      bao_live_need_white=False) else 0
    ck("need_white=False 只会放宽（loose ≥ strict，且样本里 strict > 0）",
       (loose >= strict, strict > 0), (True, True))

    # ---- plan_bao_live：直接断言「路线语义」（不依赖 argmin 是否变；实测改写很少见）----
    found = None
    random.seed(31)
    for _ in range(4000):
        c = [0] * 34
        for _m in range(random.randint(2, 3)):
            lo = random.choice([0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23, 24])
            if all(c[x] < 3 for x in (lo, lo + 1, lo + 2)):
                for x in (lo, lo + 1, lo + 2):
                    c[x] += 1
        c[LAIZI_INDEX] = 1
        n = sum(c)
        while n < 14:
            x = random.randrange(34)
            if c[x] < 4:
                c[x] += 1
                n += 1
        while n > 14:
            for x in range(34):
                if c[x] > 0 and x != LAIZI_INDEX:
                    c[x] -= 1
                    n -= 1
                    break
        if not plan_route(c, 0) and plan_route(c, 0, plan_bao_live=True):
            found = c
            break
    ck("plan_bao_live 找到「默认不切、开了才切」的真实手牌", found is not None, True)
    if found is not None:
        ck("  该手牌：默认路线 False / plan_bao_live True",
           (plan_route(found, 0), plan_route(found, 0, plan_bao_live=True)), (False, True))
        ck("  该手牌：min_melds=99 的无效档仍为 False",
           plan_route(found, 0, plan_bao_live=True, plan_bao_live_min_melds=99), False)
        ck("  该手牌：坐庄时不生效（不覆盖 dealer_speed）",
           plan_route(found, 0, plan_bao_live=True, dealer_speed=True), False)

    random.seed(20260923)
    diff = 0
    same_off = True
    same_noop = True
    for _ in range(150):
        c = [0] * 34
        for _m in range(random.randint(2, 3)):
            lo = random.choice([0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23, 24])
            if all(c[x] < 3 for x in (lo, lo + 1, lo + 2)):
                for x in (lo, lo + 1, lo + 2):
                    c[x] += 1
        t = random.randrange(34)
        if c[t] <= 2:
            c[t] += 2
        c[LAIZI_INDEX] = 1
        n = sum(c)
        while n < 14:
            x = random.randrange(34)
            if c[x] < 4:
                c[x] += 1
                n += 1
        while n > 14:
            for x in range(34):
                if c[x] > 0 and x != LAIZI_INDEX:
                    c[x] -= 1
                    n -= 1
                    break
        kw = dict(remain=None, melds=0, depth=False, dealer=False, fan_override=True)
        d0 = discard_decision(c, **kw)
        d_off = discard_decision(c, plan_bao_live=False, **kw)
        d_noop = discard_decision(c, plan_bao_live=True, plan_bao_live_min_melds=99, **kw)
        d_on = discard_decision(c, plan_bao_live=True, plan_bao_live_min_melds=0, **kw)
        if d_off != d0:
            same_off = False
        if d_noop != d0:
            same_noop = False
        if d_on != d0:
            diff += 1
    ck("plan_bao_live=False 与默认逐位一致（150 手）", same_off, True)
    ck("plan_bao_live 无效档（min_melds=99）逐位一致（150 手）", same_noop, True)

    # ---- sim 透传 ----
    s_off = Smart()
    s_on = Smart(peng_bao_live=True, peng_bao_live_max_melds=1, peng_bao_live_slack=0,
                 plan_bao_live=True, plan_bao_live_min_melds=2)
    ck("Smart 默认 peng_bao_live=False", s_off.peng_bao_live, False)
    ck("Smart 透传 peng_bao_live 参数", (s_on.peng_bao_live, s_on.peng_bao_live_max_melds,
                                        s_on.peng_bao_live_slack), (True, 1, 0))
    ck("Smart 透传 plan_bao_live 参数", (s_on.plan_bao_live, s_on.plan_bao_live_min_melds), (True, 2))

    clear_caches()
    print("\n%d/%d 通过" % (PASS, PASS + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
