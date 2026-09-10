"""模拟器不变量校验 + 吃碰杠机制冒烟测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import NUM_TILES
from sim.engine import Game, Meld
from sim.players import Baseline, Smart


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


def main():
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

    print("300 局不变量校验通过（牌数守恒/手牌非负/吃≤2摊）")
    print("副露类型计数:", {k: v for k, v in sorted(kinds.items())})
    print("ALL PASS")


if __name__ == "__main__":
    main()
