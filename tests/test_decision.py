"""决策引擎单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count, tile_name, LAIZI_INDEX
from mahjong.decision import discard_decision, discard_decision_full, \
    should_piao, piao_after_discard, should_decline_hu


def T(*tiles):
    return list_to_count(tiles)


def test_decline_hu():
    """弃胡 + 财飘判据（2026-09-20，guide §1.2）。"""
    ok = True

    def ck(name, got, want):
        nonlocal ok
        o = got == want
        ok = ok and o
        print(f"[{'OK  ' if o else 'FAIL'}] {name}: got={got} want={want}")

    # 平胡形：4 面子 + 2 财神（摸到面子里的 1w；摸前 13 张仍是「任意摸都胡」）
    h_ping = T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 33)
    ck("should_piao(4面子+2财神)", should_piao(h_ping), True)
    ck("piao_after_discard(平胡形)", piao_after_discard(h_ping, 0), True)
    ck("弃胡：闲家（f0=2,c=2.75 → q*=0.70<0.75）", should_decline_hu(h_ping, 0, drawn=0, is_dealer=False), True)
    ck("弃胡：庄家（c=8 → q*=0.83>0.75）", should_decline_hu(h_ping, 0, drawn=0, is_dealer=True), False)
    ck("弃胡：连飘到上限", should_decline_hu(h_ping, 0, drawn=0, chain_count=3, is_dealer=False), False)
    ck("弃胡：q 估计更悲观(0.6)", should_decline_hu(h_ping, 0, drawn=0, is_dealer=False, q_est=0.6), False)

    # 七对形（七客：6 对 + 2 财神）也能飘（guide v3：七对可财飘）。
    # 用「6 个互相搭不上面子的对子」来暴露窄/宽判据的差别：
    #   should_piao（要求 12 张能拆成 4 面子）→ False；piao_after_discard（打白后仍爆头）→ True
    h_qi = T(0, 0, 3, 3, 6, 6, 9, 9, 12, 12, 15, 15, 33, 33)
    ck("should_piao(纯对子七对形)=False（窄判据）", should_piao(h_qi), False)
    ck("piao_after_discard(纯对子七对形)=True（宽判据）", piao_after_discard(h_qi, 0), True)
    ck("弃胡：七对形闲家", should_decline_hu(h_qi, 0, drawn=15, is_dealer=False), True)

    # 只有 1 张财神 → 打白链断 → 不弃胡
    h_one = T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 9)
    ck("只有 1 财神 → piao_after_discard=False", piao_after_discard(h_one, 0), False)
    ck("只有 1 财神 → 不弃胡", should_decline_hu(h_one, 0, drawn=9, is_dealer=False), False)

    # 打白后不再是爆头态（手里 2 白但拆不出面子）→ 不弃胡
    h_bad = T(0, 2, 4, 6, 8, 9, 11, 13, 15, 20, 22, 24, 33, 33)
    ck("非爆头形 → piao_after_discard=False", piao_after_discard(h_bad, 0), False)

    # 非胡牌形：不该被判成「能弃胡」（这里的 14 张连向听 0 都不是）
    h_nw = T(0, 2, 4, 15, 17, 18, 20, 22, 24, 26, 27, 28, 33, 33)
    ck("未成胡 → 不弃胡", should_decline_hu(h_nw, 0, drawn=0, is_dealer=False), False)
    return ok


def main():
    ok = True

    # 1. 听牌打孤张东
    hand1 = T(0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8, 27)  # 111 234 567 88 99 东
    d1 = discard_decision(hand1)
    print("听牌手牌 打:", tile_name(d1), "(期望 东)")
    ok = ok and d1 == 27

    # 2. 含财神不打财神
    hand2 = T(0, 0, 0, 1, 2, 3, 4, 5, 6, 33, 33, 8, 8, 27)  # 111 234 567 白白 99 东
    d2 = discard_decision(hand2)
    print("含财神手牌 打:", tile_name(d2), "(期望非白板，应是东)")
    ok = ok and d2 != LAIZI_INDEX

    # 3. 打印完整决策信息
    d, s, uke = discard_decision_full(hand2)
    print(f"  完整: 打{tile_name(d)} 向听={s} 进张={uke}")

    # 4. 弃胡 + 财飘判据
    ok = test_decline_hu() and ok

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
