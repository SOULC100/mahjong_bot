"""决策引擎单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count, tile_name, tile_from_str, LAIZI_INDEX, NUM_TILES
from mahjong.decision import discard_decision, discard_decision_full, \
    should_piao, piao_after_discard, should_decline_hu, \
    _fan_ting_expect, _fan_value_real
from mahjong import decision
from mahjong.fan import any_draw_win


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


def test_fan_est_baotou():
    """`fan_est="real*"` 的爆头漏算修复（2026-09-25）。

    旧 `_fan_ting_expect` 调 `calc_fan` 不传 `baotou` → 「4 面子 + 财神单吊」这类真·爆头听牌
    被算成平胡 ×1，期望倍率 2 被算成 1 → log2 期望 = 0（本该 1）。
    见 docs/improvement-plan.md §1「`fan_est="real*"` B4 已证伪但判据有 bug」。
    """
    ok = True

    def ck(name, got, want):
        nonlocal ok
        o = got == want
        ok = ok and o
        print(f"[{'OK  ' if o else 'FAIL'}] {name}: got={got} want={want}")

    remain = [4] * NUM_TILES
    # 真·爆头听牌 13 张：4 面子 + 财神（任意摸 t：白当 t 成将 → 全部胡，且都是爆头 ×2）
    h_bao = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33)
    ck("爆头听牌 any_draw_win=True", any_draw_win(h_bao, 0), True)
    ck("爆头听牌 期望翻倍次数 = 1.0（log2 2）", _fan_ting_expect(h_bao, 0, remain), 1.0)
    ck("爆头听牌 _fan_value_real（k=3）= 3.0", _fan_value_real(h_bao, 0, remain), 3.0)

    # 平胡听牌 13 张（两面听 8m/9m，无任何翻倍）→ 期望翻倍次数 0
    h_ping = T(0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8)
    ck("平胡听牌 any_draw_win=False", any_draw_win(h_ping, 0), False)
    ck("平胡听牌 期望翻倍次数 = 0.0", _fan_ting_expect(h_ping, 0, remain), 0.0)
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

    # 5. fan_est="real*" 的爆头漏算修复
    ok = test_fan_est_baotou() and ok

    # 6. 边张优先开关 edge_w（默认关；2026-09-22 用户假设的 A/B 开关）
    #    真机复盘手牌 room a_5b83c31e82d3 第 3 局第 5 巡：2w 6w 2t3t4t4t 9t 1b2b6b6b7b 白白。
    #    默认（edge_w=0）打 2w：留 2w 独占 8 张 < 留 9t 独占 10 张（4w 被 6w 覆盖，见 strategy §3.13）。
    #    edge_w ≥ 1 时应翻转为打 9t（1 张进张 ≈ 0.1 分，边张 1/9 减 3 分）。
    hand_e = T(1, 5, 10, 11, 12, 12, 17, 18, 19, 23, 23, 24, 33, 33)
    rem_u = [4] * 34
    kw = dict(depth=False, dealer=False, fan_override=True, allowed=None,
              youcai_bikao=False, dealer_speed=False)

    def ck2(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("[%s] %s: got=%r want=%r" % ("OK  " if good else "FAIL", name, got, want))
        return good

    d_off = discard_decision(hand_e, rem_u, 0, edge_w=0.0, **kw)
    d_on = discard_decision(hand_e, rem_u, 0, edge_w=3.0, **kw)
    ck2("edge_w=0（默认）→ 打 2万（整手牌进张优先）", tile_name(d_off), "2万")
    ck2("edge_w=3 → 翻转为打 9条（边张优先生效）", tile_name(d_on), "9条")
    ck2("edge_bias：1/9=3、2/8=2、3/7=1、中张/字牌=0",
        [decision.edge_bias(t) for t in
         (tile_from_str("1w"), tile_from_str("9t"), tile_from_str("2w"),
          tile_from_str("8b"), tile_from_str("3t"), tile_from_str("5w"),
          tile_from_str("东"))],
        [3.0, 3.0, 2.0, 2.0, 1.0, 0.0, 0.0])
    # 打白会掉到 3 向听；即使边张分最高（白=0，但验证不越向听界）也不该被选中
    ck2("edge_w 不越向听界（仍不会打财神）",
        tile_name(discard_decision(hand_e, rem_u, 0, edge_w=3.0, **kw)) != "白", True)

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
