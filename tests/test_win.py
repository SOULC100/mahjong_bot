"""胡牌判定单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count
from mahjong.win import can_win


def T(*tiles):
    return list_to_count(tiles)


def check(name, tiles, expected):
    got = can_win(T(*tiles))
    status = "OK  " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    return got == expected


def main():
    results = []
    # 牌索引：0-8万 9-17**条**(协议 t) 18-26**筒**(协议 b) 27东 28南 29西 30北 31中 32发 33白

    # 1. 标准胡：111 222 333 456 99
    results.append(check(
        "标准胡 11122233345699",
        [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8], True))

    # 2. 七对：11 22 33 44 55 66 77
    results.append(check(
        "七对 11223344556677",
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6], True))

    # 3. 含财神将：111 222 333 444 白白（4刻子 + 财神对做将）
    results.append(check(
        "4刻子+财神将 111222333444白白",
        [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 33], True))

    # 4. 含财神七对：11 22 33 44 55 66 白白
    results.append(check(
        "6对+财神对 112233445566白白",
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 33, 33], True))

    # 5. 财神补顺子：1万2万[白当3万] 456 789 东东东 南南
    results.append(check(
        "财神补顺子 12白456789东东东南南",
        [0, 1, 33, 3, 4, 5, 6, 7, 8, 27, 27, 27, 28, 28], True))

    # 6. 散牌不胡
    results.append(check(
        "散牌不胡",
        [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 28, 29, 31, 32], False))

    # 7. 4张相同需拆刻子+顺子：1111 23 456 789 东东
    #    拆法：111 + 123 + 456 + 789 + 东东(将)
    results.append(check(
        "4张相同 111123456789东东",
        [0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 27], True))

    # 8. 一向听不胡：111 234 567 88 99 东（88/99 两个对子 + 东孤张，凑不出第4个面子）
    results.append(check(
        "一向听不胡 1112345678899东",
        [0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 7, 8, 8, 27], False))

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
