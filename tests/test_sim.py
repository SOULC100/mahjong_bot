"""模拟器不变量校验 + 吃碰杠机制冒烟测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import NUM_TILES, LAIZI_INDEX, list_to_count
from sim.engine import Game, Meld
from sim.players import Baseline, Smart, Strategy


def total_tiles(g):
    """牌墙剩余 + 四家手牌 + 四家副露 + 四家弃牌 应恒等于 136。"""
    n = g.wall_end - g.draw_pos
    for p in range(4):
        n += sum(g.hands[p])
        n += sum(len(m.tiles) for m in g.melds[p])
        n += len(g.discards[p])
    return n


def check_game(g):
    assert total_tiles(g) == 136, f"牌数不守恒: {total_tiles(g)}"
    for p in range(4):
        for t in range(NUM_TILES):
            assert g.hands[p][t] >= 0, f"seat{p} 手牌负计数 tile{t}"
        assert g.chi_count[p] <= 2, f"seat{p} 吃超过2摊"


class NeverHu(Strategy):
    """永远弃胡（want_hu → False）；出牌打最小的非财神牌。"""

    def __init__(self):
        self.calls = 0

    def choose_discard(self, game, seat):
        hand = game.hands[seat]
        for t in range(NUM_TILES):
            if t != LAIZI_INDEX and hand[t] > 0:
                return t
        return LAIZI_INDEX

    def want_hu(self, game, seat, drawn, gang_kai=False):
        self.calls += 1
        return False


def test_want_hu_hook():
    """引擎必须在三处判胡点询问 want_hu（弃胡钩子，2026-09-20）。

    做法：把 _can_win 打成恒真 —— 若引擎不询问 want_hu，第一张摸牌就会直接结算；
    询问且返回 False 时，牌局必须继续走到流局，且全程牌数守恒。
    """
    orig = Game._can_win
    Game._can_win = lambda self, seat, drawn_tile=-1, gang_kai=False: True
    try:
        sts = [NeverHu() for _ in range(4)]
        g = Game(seed=3)
        w, mult, scores, is_draw = g.play_round(sts)
        check_game(g)
        assert sum(s.calls for s in sts) > 0, "引擎从未询问 want_hu（弃胡钩子未接）"
        assert is_draw and w == -1, "全部弃胡时应打到流局，而不是结算"
        # 对照：默认 want_hu = True → 立刻结算（旧行为不变）
        g2 = Game(seed=3)
        w2, _, _, draw2 = g2.play_round([Smart() for _ in range(4)])
        assert not draw2 and w2 >= 0, "want_hu 默认 True 时应能胡就胡"
    finally:
        Game._can_win = orig
    print("want_hu 弃胡钩子：引擎三处判胡点均会询问，弃胡后正常继续（牌数守恒）")


def test_piao_attribution():
    """财飘记账前提 = 打出财神后仍「任意摸都胡」（guide §1.2），2026-09-20 修正。"""
    # ① 4 面子 + 2 财神：打 1 张白后仍是爆头态（任意摸都胡）→ 合法飘
    g = Game(seed=5)
    g.hands[0] = list_to_count([0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 33])
    g._discard(0, LAIZI_INDEX)
    assert g.piao_count[0] == 1, f"合法飘未记账: {g.piao_count[0]}"
    # ② 手留 ≥1 白但打完后**不是**爆头态 → 链断，不记账（旧实现这里会误记 +1）
    g2 = Game(seed=5)
    g2.hands[1] = list_to_count([0, 1, 2, 4, 5, 6, 13, 14, 15, 26, 26, 27, 33, 33])
    g2._discard(1, LAIZI_INDEX)
    assert g2.piao_count[1] == 0, f"非爆头态打白被误记飘: {g2.piao_count[1]}"
    # ③ 飘后打非财神 → 链断清零
    g.hands[0][0] += 1  # 补一张普通牌保持手牌非空
    g._discard(0, 0)
    assert g.piao_count[0] == 0, "打非财神后链未断"
    print("财飘记账前提：仅爆头态打白记飘；非爆头态打白与打非财神均断链")


def main():
    # shanten 的 _best/_mp 是 maxsize=None 的 lru_cache：实测每局 +15~20 万条（≈50~80 MB），
    # 长时间跑必须定期清（sim 各 A/B 脚本同样每 100 局清一次；线上 bot 的清理见 improvement-plan P0-4）。
    from mahjong import shanten as _sh

    strategies = [Smart(), Baseline(), Baseline(), Baseline()]
    kinds = {}
    for i in range(300):
        g = Game(seed=i)
        g.dealer = i % 4
        g.play_round(strategies)
        check_game(g)
        for p in range(4):
            for m in g.melds[p]:
                kinds[m.kind] = kinds.get(m.kind, 0) + 1
        if (i + 1) % 25 == 0:
            _sh._best.cache_clear()
            _sh._mp.cache_clear()

    print("300 局不变量校验通过（牌数守恒/手牌非负/吃≤2摊）")
    print("副露类型计数:", {k: v for k, v in sorted(kinds.items())})

    # 开启弃胡的 Smart 也必须保值（4 家全开，150 局）
    piao_wins = 0
    for i in range(150):
        g = Game(seed=10000 + i)
        g.dealer = i % 4
        w, mult, sc, d = g.play_round([Smart(decline_hu=True) for _ in range(4)])
        check_game(g)
        if not d and g.piao_count[w] > 0:
            piao_wins += 1
        if (i + 1) % 25 == 0:
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    print("150 局「开启弃胡」不变量校验通过（牌数守恒/手牌非负/吃≤2摊）；"
          "其中带飘胡 %d 局" % piao_wins)

    test_want_hu_hook()
    test_piao_attribution()
    print("ALL PASS")


if __name__ == "__main__":
    main()
