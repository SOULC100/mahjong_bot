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
    # 牌索引：0-8万 9-17**条**(协议 t) 18-26**筒**(协议 b) 27东 28南 29西 30北 31中 32发 33白
    # （平台口径 w=万/t=条/b=筒，见 mahjong/tiles.py 文件头与 tests/test_tile_coding.py）

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
    hand5[9] = 3               # 111条（协议 1t）
    hand5[19] = 1              # 2筒（协议 2b）
    hand5[20] = 1              # 3筒（协议 3b）
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
    hand6[9] = 3               # 111条（协议 1t）
    hand6[19] = 1
    hand6[20] = 1
    hand6[27] = 2
    results.append(check("无搭子 should_chi=False", should_chi(hand6, 5, 0), False))

    # 6. R15「先消化摸不进来的搭子」（prefer_narrow，2026-09-25 晋级）
    #    手牌 4万5万 + 7万8万，吃 6万：两种吃法
    #      A) 用 4万5万 → 剩下的 7万8万 还能靠 6万/9万 自摸（还有其他进张）
    #      B) 用 7万8万 → 剩下的 4万5万 只能靠 3万/6万（6万=刚被打出，实际只剩 3万）
    #    prefer_narrow 应挑「吃后剩余进张更少」的那一副（这里是把"唯一靠 6万"的那副消化掉）。
    h7 = [0] * 34
    for t in (3, 4, 6, 7):      # 4万 5万 7万 8万
        h7[t] = 1
    h7[9] = 3                   # 111条刻子（协议 1t）
    h7[18] = 3                  # 111筒刻子（协议 1b）
    remain_live = [4] * 34
    remain_live[5] = 0          # 刚被打出的 6万 已不在池中
    plain = best_chi(h7, 5, 0, ukeire_gate=True, remain=remain_live)
    narrow = best_chi(h7, 5, 0, ukeire_gate=True, remain=remain_live, prefer_narrow=True)
    results.append(check("prefer_narrow 仍能吃到牌", narrow is not None, True))
    results.append(check("prefer_narrow 结果在合法吃法内",
                         sorted(narrow) in [sorted(c) for c in chi_combos(h7, 5)], True))
    # 判别性用例：手牌 4万5万7万8万 吃 6万 有 **3 种**吃法，各自的"剩余进张"不同：
    #   (4万,5万)：还能靠 3万 补         → 进张 4
    #   (5万,7万)：嵌张，唯一补张就是刚被打出的 6万 → 进张 0  ← 最该消化
    #   (7万,8万)：还能靠 9万 补         → 进张 4
    # prefer_narrow 的判据就是"消化补不上的那副"，所以应当选进张最少的那一种。
    from mahjong.tiles import pair_completions

    def acc_of(pair, remain, d):
        return sum(remain[t] for t in pair_completions(pair[0], pair[1]) if t != d)

    remain_live2 = [4] * 34
    remain_live2[5] = 0                 # 6万 = 刚被打出（已不在池中）
    combos7 = chi_combos(h7, 5)
    min_acc = min(acc_of(c, remain_live2, 5) for c in combos7)
    picked = best_chi(h7, 5, 0, ukeire_gate=True, remain=remain_live2, prefer_narrow=True)
    default_pick = best_chi(h7, 5, 0, ukeire_gate=True, remain=remain_live2)
    accs = {tuple(c): acc_of(c, remain_live2, 5) for c in combos7}
    results.append(check("三种吃法枚举", sorted(tuple(c) for c in combos7), [(3, 4), (4, 6), (6, 7)]))
    results.append(check("各吃法剩余进张（4万5万 / 5万7万 / 7万8万）",
                         [accs[(3, 4)], accs[(4, 6)], accs[(6, 7)]], [4, 0, 4]))
    results.append(check("prefer_narrow 选中的吃法 = 进张最少的那种（消化的正是嵌张）",
                         acc_of(picked, remain_live2, 5), min_acc))
    results.append(check("prefer_narrow 选中 (5万,7万)",
                         sorted(picked), [4, 6]))
    print("         （对照：默认排序选中 %s，进张 %d）"
          % (sorted(default_pick), acc_of(default_pick, remain_live2, 5)))

    # 7. 可选的"不吃宽搭子"门控（narrow_max_accept，**未晋级**，仅作为对照轴保留）
    #    向听 ≥3 时只吃剩余进张 ≤ 阈值的搭子
    h8 = [0] * 34
    for t in (0, 1, 3, 4):      # 1万 2万 4万 5万
        h8[t] = 1
    h8[9] = 2                   # 1条1条（协议 1t）
    h8[18] = 2                  # 1筒1筒（协议 1b）
    h8[27] = 2                  # 东东
    s8 = shanten(h8, 0)
    r8 = [4] * 34
    r8[2] = 0                   # 3万 已死
    open_chi = should_chi(h8, 2, 0, ukeire_gate=True, remain=r8)
    gated = should_chi(h8, 2, 0, ukeire_gate=True, remain=r8,
                       narrow_max_accept=0, narrow_min_shanten=3)
    results.append(check("narrow 门控：低向听时不生效（向听<3）",
                         gated, open_chi if s8 < 3 else gated))
    results.append(check("narrow 门控：向听≥3 且搭子仍有进张 → 被挡",
                         should_chi(h8, 2, 0, ukeire_gate=True, remain=[4] * 34,
                                    narrow_max_accept=1, narrow_min_shanten=3), False))

    print("\n" + ("ALL PASS" if all(results) else "SOME FAILED"))


if __name__ == "__main__":
    main()
