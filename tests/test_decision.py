"""决策引擎单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count, tile_name, LAIZI_INDEX
from mahjong.decision import discard_decision, discard_decision_full


def T(*tiles):
    return list_to_count(tiles)


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

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
