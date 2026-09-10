"""有效进张单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count, tile_name
from mahjong.ukeire import (
    ukeire_tiles,
    ting_tiles,
    shanten_after_discard,
    best_discard,
)


def T(*tiles):
    return list_to_count(tiles)


def main():
    ok = True

    # 手牌：111 234 567 88 99 东（打东后 13 张四门听：万7/万8/万9/白板）
    hand = T(0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8, 27)
    dong = 27

    s = shanten_after_discard(hand, dong)
    print("打东后向听数:", s, "(期望 0)")
    ok = ok and s == 0

    uke = ukeire_tiles(hand, dong)
    print("打东进张:", [tile_name(t) for t in uke], "(期望 万7/万8/万9/白)")
    ok = ok and (uke == [6, 7, 8, 33])

    c13 = list(hand)
    c13[27] -= 1
    ting = ting_tiles(c13)
    print("13张听牌:", [tile_name(t) for t in ting], "(期望 万7/万8/万9/白)")
    ok = ok and (ting == [6, 7, 8, 33])

    d, s, v = best_discard(hand)
    print(f"best_discard: 打{tile_name(d)} 向听={s} 进张={v} (期望 打东 向听=0)")
    ok = ok and (d == dong and s == 0)

    # 另一个：已听牌不应选到打掉听牌关键张
    # 111 234 567 白 99 东 南（白为财神，拆法多样），这里只验证 best_discard 不崩且向听不劣化

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
