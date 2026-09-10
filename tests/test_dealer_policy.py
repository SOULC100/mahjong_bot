"""dealer_policy 开关单元测试。

校验：
1. discard_decision 的 dealer_speed=True ≡ 手动 baotou_slack=0/baotou_max_shanten=0/gang_keep_pen=0。
2. Smart(dealer_policy='aggr') 在「非庄」时与现基线 Smart() 逐决策一致（坐庄抢速只在当庄激活）。
3. dealer_policy='aggr' 的当庄激活路由：当庄时 want_peng/want_chi 会走 ukeire_gate（放宽吃碰），
   且 choose_discard 会传 dealer_speed=True；非庄/基线均不触发。
4. 所有 dealer_policy 值能完整跑通模拟器（冒烟，小样本）。

注：测试手牌用「洗 136 张抽 14 张 + 财神 0~2」的拟真生成（3 财神随机手会让 shanten 递归爆炸）。
"""

import os
import sys
import random
from unittest import mock

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import NUM_TILES, LAIZI_INDEX
from mahjong.decision import discard_decision
from mahjong import shanten as _sh
from sim.engine import Game
from sim import players as players_mod
from sim.players import Smart

rng = random.Random(12345)


def deal_hand14(max_laizi=2):
    wall = []
    for t in range(LAIZI_INDEX):
        wall.extend([t] * 4)
    rng.shuffle(wall)
    laizi = rng.randint(0, max_laizi)
    h = [0] * NUM_TILES
    for t in wall[: 14 - laizi]:
        h[t] += 1
    h[LAIZI_INDEX] += laizi
    return h


def setup_hand(game, seat, hand):
    for p in range(4):
        game.hands[p] = [0] * NUM_TILES
    game.hands[seat] = list(hand)
    game.melds = [[] for _ in range(4)]
    game.discards = [[] for _ in range(4)]
    game.youcai_bikao = False
    game.piao_count = [0] * 4


def test_dealer_speed_equiv():
    n_diff = 0
    for _ in range(200):
        h = deal_hand14()
        args = dict(hand=h, melds=0, depth=False, dealer=False, fan_override=True)
        a = discard_decision(dealer_speed=True, **args)
        b = discard_decision(baotou_slack=0, baotou_max_shanten=0, gang_keep_pen=0.0, dealer_speed=False, **args)
        if a != b:
            n_diff += 1
    print(f"[1] dealer_speed 等价: 200 手 差异 {n_diff}")
    assert n_diff == 0, "dealer_speed=True 应等价于 slack/max/keep 清零"
    return True


def test_nondealer_identical():
    """dealer_policy='aggr' 在非庄时应与 Smart() 逐决策一致（出牌/碰/吃）。"""
    n_diff = 0
    g = Game(seed=1)
    for _ in range(200):
        h = deal_hand14()
        g.dealer = rng.choice([1, 2, 3])
        setup_hand(g, 0, h)
        off = Smart(dealer_policy="off")
        agr = Smart(dealer_policy="aggr")
        if off.choose_discard(g, 0) != agr.choose_discard(g, 0):
            n_diff += 1
        # 非庄：碰/吃门控也不放宽
        with mock.patch.object(players_mod, "should_peng", wraps=players_mod.should_peng) as sp, \
             mock.patch.object(players_mod, "best_chi", wraps=players_mod.best_chi) as bc:
            off.want_peng(g, 0, 0)
            agr.want_peng(g, 0, 0)
            off.want_chi(g, 0, 0)
            agr.want_chi(g, 0, 0)
            assert all(call.kwargs.get("ukeire_gate") is not True for c in [sp, bc] for call in c.call_args_list), \
                "非庄时不应放宽吃碰门控"
    print(f"[2] 非庄逐决策一致: 200 手 出牌差异 {n_diff}，且吃/碰门控未放宽")
    assert n_diff == 0
    return True


def test_dealer_active_routing():
    """当庄时 aggr 应激活：出牌传 dealer_speed=True；want_peng/want_chi 走 ukeire_gate=True。"""
    g = Game(seed=3)
    h = deal_hand14()
    g.dealer = 0
    setup_hand(g, 0, h)

    # 出牌：aggr 当庄 → discard_decision(dealer_speed=True)
    with mock.patch.object(players_mod, "discard_decision", wraps=players_mod.discard_decision) as dd:
        Smart(dealer_policy="aggr").choose_discard(g, 0)
        assert dd.call_args.kwargs.get("dealer_speed") is True, "aggr 当庄必须传 dealer_speed=True"
    with mock.patch.object(players_mod, "discard_decision", wraps=players_mod.discard_decision) as dd:
        Smart(dealer_policy="off").choose_discard(g, 0)
        assert dd.call_args.kwargs.get("dealer_speed") is not True, "基线当庄不传 dealer_speed"
    with mock.patch.object(players_mod, "discard_decision", wraps=players_mod.discard_decision) as dd:
        g.dealer = 1  # aggr 非庄
        Smart(dealer_policy="aggr").choose_discard(g, 0)
        assert dd.call_args.kwargs.get("dealer_speed") is not True, "aggr 非庄不传 dealer_speed"

    # 吃/碰：aggr 当庄 → ukeire_gate=True；基线/非庄 → False
    g.dealer = 0
    with mock.patch.object(players_mod, "should_peng", wraps=players_mod.should_peng) as sp:
        Smart(dealer_policy="aggr").want_peng(g, 0, 0)
        assert sp.call_args.kwargs.get("ukeire_gate") is True
        assert sp.call_args.kwargs.get("gate_max_shanten") == 1
    with mock.patch.object(players_mod, "best_chi", wraps=players_mod.best_chi) as bc:
        Smart(dealer_policy="aggr").want_chi(g, 0, 0)
        assert bc.call_args.kwargs.get("ukeire_gate") is True
    with mock.patch.object(players_mod, "should_peng", wraps=players_mod.should_peng) as sp:
        Smart(dealer_policy="off").want_peng(g, 0, 0)
        assert sp.call_args.kwargs.get("ukeire_gate") is not True
    g.dealer = 1
    with mock.patch.object(players_mod, "should_peng", wraps=players_mod.should_peng) as sp:
        Smart(dealer_policy="aggr").want_peng(g, 0, 0)
        assert sp.call_args.kwargs.get("ukeire_gate") is not True

    print("[3] 当庄激活路由: dealer_speed / ukeire_gate 只在 庄+aggr 时触发")
    return True


def test_smoke_sim():
    def total_tiles(g):
        n = g.wall_end - g.draw_pos
        for p in range(4):
            n += sum(g.hands[p])
            n += sum(len(m.tiles) for m in g.melds[p])
            n += len(g.discards[p])
        return n

    for pol in ("off", "aggr", "aggr_nopiao", "bigfan"):
        dealer = 0
        for i in range(25):
            g = Game(seed=i)
            g.dealer = dealer
            strat = [Smart(dealer_policy=pol), Smart(), Smart(), Smart()]
            w, mult, scores, d = g.play_round(strat)
            assert total_tiles(g) == 136, f"{pol} 牌不守恒"
            if not d and w != dealer:
                dealer = (dealer + 1) % 4
            if (i + 1) % 100 == 0:
                _sh._best.cache_clear(); _sh._mp.cache_clear()
    print("[4] 冒烟: off/aggr/aggr_nopiao/bigfan 各 25 局通过（牌守恒）")
    return True


def main():
    ok = True
    ok &= test_dealer_speed_equiv()
    ok &= test_nondealer_identical()
    ok &= test_dealer_active_routing()
    ok &= test_smoke_sim()
    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
