"""吃（chi）决策单元测试 + 模拟器不变量校验。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count
from mahjong.decision import chi_combos, should_chi, best_chi
from mahjong.shanten import shanten


def T(*tiles):
    return list_to_count(tiles)


def check(name, got, expected):
    ok = got == expected
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}: got={got} expected={expected}")
    return ok


def main():
    results = []
    # 牌索引：0-8万 9-17筒 18-26条 27东 28南 29西 30北 31中 32发 33白

    # 1. 吃 5万(4)：手牌有 3/4/6/7万，应枚举 3 种顺子位置
    hand = [0] * 34
    for t in (2, 3, 5, 6):  # 3万 4万 6万 7万
        hand[t] = 1
    combos = sorted(sorted(c) for c in chi_combos(hand, 4))
    expected = sorted(sorted(c) for c in ([2, 3], [3, 5], [5, 6]))
    results.append(check("吃5万枚举顺子", combos, expected))

    # 2. 字牌不能吃
    h2 = [0] * 34
    h2[27] = 1
    h2[28] = 1
    results.append(check("字牌(东)不能吃", chi_combos(h2, 27), []))
    results.append(check("字牌should_chi=False", should_chi(h2, 27), False))

    # 3. 1万(0)只能作顺子下家；9万(8)只能作顺子上家
    h3 = [0] * 34
    h3[1] = 1
    h3[2] = 1  # 2万 3万
    results.append(check("吃1万用2万3万", chi_combos(h3, 0), [[1, 2]]))
    h4 = [0] * 34
    h4[6] = 1
    h4[7] = 1  # 7万 8万
    results.append(check("吃9万用7万8万", chi_combos(h4, 8), [[6, 7]]))

    # 4. 吃确实降向听：一向听手牌，吃 6万 变听牌
    hand5 = [0] * 34
    for t in (0, 1, 2):       # 123万
        hand5[t] = 1
    hand5[3] = 1               # 4万
    hand5[4] = 1               # 5万
    hand5[8] = 1               # 9万（浮牌）
    hand5[9] = 3               # 111筒
    hand5[19] = 1              # 2条
    hand5[20] = 1              # 3条
    hand5[27] = 2              # 东东
    s_before = shanten(hand5, 0)
    results.append(check("示例手牌向听=1", s_before, 1))
    results.append(check("吃6万 should_chi=True", should_chi(hand5, 5, 0), True))
    results.append(check("吃6万 best_chi=[4万,5万]", best_chi(hand5, 5, 0), [3, 4]))

    # 5. 吃不能降向听则不吃：把 4万5万 换成已成刻子的牌
    hand6 = [0] * 34
    for t in (0, 1, 2):
        hand6[t] = 1
    hand6[0] = 3               # 111万（改成刻子，无可吃的搭子）
    hand6[8] = 1               # 9万
    hand6[9] = 3               # 111筒
    hand6[19] = 1
    hand6[20] = 1
    hand6[27] = 2
    results.append(check("无搭子 should_chi=False", should_chi(hand6, 5, 0), False))

    print("\n" + ("ALL PASS" if all(results) else "SOME FAILED"))


if __name__ == "__main__":
    main()
