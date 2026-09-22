"""财神补顺子「下沿」拆解回归测试（2026-09-25）。

背景（线上 100 局复核发现）：拆面子时旧版只枚举「以最低现有牌为起点」的顺子，
漏掉 **财神补顺子下沿** 的拆法（手持 8筒9筒 + 财神 → 财神当 7筒 成 789筒）。
后果：
- `shanten` 高估 1 → `can_hu`（线上判据就是 `shanten(hand, melds) == -1`）判 False
  → **把胡牌打掉**（最贵的一类错误）；
- `any_draw_win` 漏判真·爆头 → 番型少算 ×2；
- `can_win` 同样漏判。

线上实证牌型：已副露 2 摊，暗手 2万3万4万 7筒8筒9筒 白，摸 7筒
（234万 + 789筒 + 将 7筒/白）——服务器结算 fan=2（爆头），旧版本地算 0 向听。

本测试用**独立的参考实现**（枚举财神的具体指派 + 无百搭纯手牌判定）做差分对照，
保证修复是「补全枚举」而不是「针对某个牌型打补丁」。
"""

import os
import random
import sys
import time
from itertools import combinations_with_replacement

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count, run_starts, NUM_TILES, LAIZI_INDEX  # noqa: E402
from mahjong.win import can_win  # noqa: E402
from mahjong.shanten import shanten  # noqa: E402
from mahjong.fan import any_draw_win  # noqa: E402


def T(*tiles):
    return list_to_count(tiles)


# ---------------------------------------------------------------- 参考实现
# 独立写法：把财神「具体化」成 0..32 的某张牌，再用无百搭的纯手牌拆解判定。
# 纯手牌下最低张 i 必是它所在面子的最低张，所以只需要试 (iii) 与 (i,i+1,i+2)。
def _ref_sets(c, k):
    """c: 34 维具体牌计数（无财神），能否恰好拆成 k 个面子。"""
    if k == 0:
        return all(x == 0 for x in c)
    i = next((j for j, x in enumerate(c) if x > 0), None)
    if i is None:
        return False
    if c[i] >= 3:
        c[i] -= 3
        ok = _ref_sets(c, k - 1)
        c[i] += 3
        if ok:
            return True
    if i < 27 and i % 9 <= 6 and c[i + 1] > 0 and c[i + 2] > 0:
        c[i] -= 1
        c[i + 1] -= 1
        c[i + 2] -= 1
        ok = _ref_sets(c, k - 1)
        c[i] += 1
        c[i + 1] += 1
        c[i + 2] += 1
        if ok:
            return True
    return False


def _ref_concrete_win(c, need_melds):
    for j in range(NUM_TILES):
        if c[j] >= 2:
            c[j] -= 2
            ok = _ref_sets(c, need_melds)
            c[j] += 2
            if ok:
                return True
    return False


def _ref_concrete_seven(c):
    return sum(c) == 14 and all(x % 2 == 0 for x in c)


def ref_can_win(counts, melds=0):
    """参考判定：存在一种财神指派使手牌成胡（标准形 或 七对）。"""
    c = list(counts)
    laizi = c[LAIZI_INDEX]
    c[LAIZI_INDEX] = 0
    need = 4 - melds
    for assign in combinations_with_replacement(range(33), laizi):
        d = list(c)
        for a in assign:
            d[a] += 1
        if _ref_concrete_win(d, need):
            return True
        if melds == 0 and _ref_concrete_seven(d):
            return True
    return False


# ---------------------------------------------------------------- 造牌
def _rand_meld(rng):
    if rng.random() < 0.4:
        t = rng.randrange(34)
        return [t, t, t]
    s = rng.randrange(3) * 9 + rng.randrange(7)
    return [s, s + 1, s + 2]


def make_win_hand(need_melds, rng, n_laizi):
    """随机造一副胡牌（need_melds 个面子 + 1 将），再替换 n_laizi 张为财神。"""
    while True:
        tiles = []
        for _ in range(need_melds):
            tiles += _rand_meld(rng)
        pair = rng.randrange(34)
        tiles += [pair, pair]
        if any(tiles.count(t) > 4 for t in set(tiles)):
            continue
        if n_laizi:
            if len(tiles) < n_laizi:
                continue
            for t in rng.sample(tiles, n_laizi):
                tiles.remove(t)
            tiles += [LAIZI_INDEX] * n_laizi
        return list_to_count(tiles)


def main():
    all_ok = True

    # ---- 1. run_starts 边界 ----
    cases = [
        (0, (0,)),            # 1万：无更低
        (8, (6,)),            # 9万：只能作 (7,8,9万) 的上沿；起点 7/8万 不成顺子
        (9, (9,)),            # 1条：不能跨到万
        (17, (15,)),          # 9条
        (18, (18,)),          # 1筒
        (26, (24,)),          # 9筒
        (2, (0, 1, 2)),       # 3万：下沿/中间/上沿三种都能成顺子
        (27, ()),             # 东：字牌无顺子
    ]
    for t, expected in cases:
        got = run_starts(t)
        ok = got == expected
        all_ok = all_ok and ok
        print(f"[{'OK  ' if ok else 'FAIL'}] run_starts({t}) = {got} expected {expected}")

    # ---- 2. 线上实证牌型 ----
    W2, W3, W4 = 1, 2, 3
    T7, T8, T9 = 24, 25, 26
    pre = T(W2, W3, W4, T7, T8, T9, LAIZI_INDEX)          # 暗手 7 张
    print()
    got = shanten(pre, 2)
    ok = got == 0
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 线上实证 摸前 shanten(234万789筒白, melds=2) = {got} expected 0")

    got = any_draw_win(pre, 2)
    ok = got is True
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 线上实证 真·爆头 any_draw_win = {got} expected True")

    bad = []
    for t in range(NUM_TILES):
        c2 = list(pre)
        c2[t] += 1
        if shanten(c2, 2) != -1:
            bad.append(t)
    ok = not bad
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 线上实证 任意摸都胡：失败摸牌 {bad if bad else '无'}")

    # ---- 3. 差分：造出来的胡牌必须判胡（含财神补下沿） ----
    rng = random.Random(20260925)
    print()
    total = mismatch = 0
    t0 = time.perf_counter()
    for _ in range(400):
        melds = rng.choice([0, 0, 1, 2, 3])
        n_laizi = rng.choice([0, 1, 1, 2, 2])
        h = make_win_hand(4 - melds, rng, n_laizi)
        total += 1
        ref = ref_can_win(h, melds)          # 参考实现自检：造出来的牌必须是胡
        got = shanten(h, melds) == -1
        got2 = can_win(h) if melds == 0 else got
        if not ref or not got or not got2:
            mismatch += 1
            if mismatch <= 5:
                print("MISMATCH", h, "melds=", melds, "ref=", ref, "shanten==-1=", got, "can_win=", got2)
    dt = time.perf_counter() - t0
    ok = mismatch == 0
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 差分A 造胡牌 {total} 手（财神≤2）：不一致 {mismatch}（{dt:.1f}s）")

    # ---- 4. 差分：听牌（打掉一张的形）必须判 0 向听 ----
    random.seed(4242)
    bad = 0
    checked = 0
    for _ in range(300):
        melds = random.choice([0, 0, 1, 2])
        h = make_win_hand(4 - melds, random, random.choice([1, 2, 2]))
        pool = [i for i in range(NUM_TILES) if h[i] > 0]
        d = random.choice(pool)
        h[d] -= 1                              # 3*(4-melds)+1 张 = 听牌形
        s = shanten(h, melds)
        checked += 1
        if s != 0:
            bad += 1
            if bad <= 5:
                print("TENPAI MISMATCH", h, "melds=", melds, "shanten=", s)
    ok = bad == 0
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 差分B 听牌形 {checked} 手：非 0 向听 {bad}")

    # ---- 5. 差分：纯随机手牌（多数不胡）不能出现假胡 ----
    random.seed(31337)
    pool = [i for i in range(34) for _ in range(4)]
    false_win = 0
    for _ in range(300):
        c = list_to_count(random.sample(pool, 14))
        if shanten(c) == -1 and not ref_can_win(c, 0):
            false_win += 1
            if false_win <= 3:
                print("FALSE WIN", c)
    ok = false_win == 0
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 差分C 随机 14 张 300 手：假胡 {false_win}")

    # ---- 6. 3~4 张财神的极端形（参考实现全枚举，只跑少量） ----
    print()
    bad = 0
    n = 0
    for _ in range(12):
        melds = random.choice([0, 1])
        h = make_win_hand(4 - melds, random, random.choice([3, 4]))
        if h[LAIZI_INDEX] < 3:
            continue
        n += 1
        if not (ref_can_win(h, melds) and shanten(h, melds) == -1):
            bad += 1
            print("MULTI-LAIZI MISMATCH", h, "melds=", melds)
    ok = bad == 0
    all_ok = all_ok and ok
    print(f"[{'OK  ' if ok else 'FAIL'}] 差分D 财神 3~4 张的胡牌 {n} 手：不一致 {bad}")

    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
