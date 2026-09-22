"""向听数单元测试 + 交叉验证。"""

import os
import random
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count
from mahjong.win import can_win
from mahjong.shanten import shanten


def T(*tiles):
    return list_to_count(tiles)


def random_hand(n=14):
    """从 136 张牌池随机抽 n 张（每种最多 4 张）。"""
    pool = [i for i in range(34) for _ in range(4)]
    return list_to_count(random.sample(pool, n))


def main():
    # ---- 固定牌型（标准基准：已胡=-1，听牌=0） ----
    cases = [
        ("已胡标准 11122233345699", [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8], -1),
        ("已胡七对 11223344556677", [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6], -1),
        ("已胡含财神 111222333444白白", [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 33], -1),
        ("听牌 1112345678899东", [0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8, 27], 0),
        ("4面子+1搭子听牌 11112345678989", [0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8], 0),
        ("散牌", [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 28, 29, 31, 32], 2),
    ]
    all_ok = True
    for name, tiles, expected in cases:
        got = shanten(T(*tiles))
        ok = got == expected
        all_ok = all_ok and ok
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}: got={got} expected={expected}")

    # ---- 交叉验证 1：shanten==-1 当且仅当 can_win ----
    random.seed(12345)
    mismatch = 0
    for _ in range(800):
        counts = random_hand()
        s = shanten(counts)
        w = can_win(counts)
        if (s == -1) != w:
            mismatch += 1
            if mismatch <= 3:
                print("MISMATCH shanten==-1 vs can_win:", counts, "s=", s, "w=", w)
    print(f"\n交叉验证1 (shanten==-1 ⟺ can_win, 800局): {'OK' if mismatch == 0 else str(mismatch) + ' mismatches'}")
    all_ok = all_ok and mismatch == 0

    # ---- 交叉验证 2：打一摸一性质 ----
    # 对 shanten==k (k>=0) 的牌，min_{打d,摸t} shanten == k-1
    def random_win_hand():
        while True:
            c = random_hand()
            if can_win(c):
                return c

    random.seed(777)
    win_hand = random_win_hand()
    bad = 0
    verified = {}
    for _ in range(40):
        c = win_hand[:]
        d = random.choice([i for i in range(34) if c[i] > 0])
        t = random.randint(0, 33)
        c[d] -= 1
        c[t] += 1
        k = shanten(c)
        if k < 0 or k > 3:
            continue
        best = k
        for dd in range(34):
            if c[dd] == 0:
                continue
            c1 = c[:]
            c1[dd] -= 1
            for tt in range(34):
                c2 = c1[:]
                c2[tt] += 1
                s2 = shanten(c2)
                if s2 < best:
                    best = s2
                    if best == k - 1:
                        break
            if best == k - 1:
                break
        if best != k - 1:
            bad += 1
            print("BAD shanten=", k, "但打一摸一最小=", best, c)
        verified[k] = verified.get(k, 0) + 1
    print(f"交叉验证2 (打一摸一后向听数减一): 覆盖 {dict(sorted(verified.items()))}, 错误={bad}")
    all_ok = all_ok and bad == 0

    # ---- 性能 ----
    random.seed(999)
    samples = [random_hand() for _ in range(200)]
    t0 = time.perf_counter()
    for c in samples:
        shanten(c)
    dt = time.perf_counter() - t0
    avg_ms = dt / len(samples) * 1000
    print(f"\n性能: {len(samples)} 次 shanten 平均 {avg_ms:.3f} ms/次")

    # ---- P0-4：缓存必须有上界（否则 20 局就攒到 500 万条 → 内存压力把单次决策拖到几十秒）----
    from mahjong import shanten as _sh
    ok = (_sh._mp.cache_info().maxsize == _sh.CACHE_MAXSIZE
          and _sh._best.cache_info().maxsize == _sh.CACHE_MAXSIZE
          and _sh.CACHE_MAXSIZE is not None)
    print(f"[{'OK  ' if ok else 'FAIL'}] 缓存上界：_mp/_best maxsize = "
          f"{_sh._mp.cache_info().maxsize}/{_sh._best.cache_info().maxsize}（CACHE_MAXSIZE={_sh.CACHE_MAXSIZE}）")
    all_ok = all_ok and ok
    _sh.clear_caches()
    ok2 = _sh._mp.cache_info().currsize == 0
    print(f"[{'OK  ' if ok2 else 'FAIL'}] clear_caches() 清空缓存（线上每局调用，保证长赛程内存不涨）")
    all_ok = all_ok and ok2

    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
