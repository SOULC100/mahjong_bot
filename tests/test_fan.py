"""番型计分单元测试。"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count
from mahjong.fan import calc_fan, seven_pairs_branch, any_draw_win, ycb_can_hu
from mahjong.win import split_laizi


def T(*tiles):
    return list_to_count(tiles)


def main():
    ok = True
    cases = [
        ("平胡 11122233345699", [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8], 1),
        ("七对 11223344556677", [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6], 2),
        ("豪华七对 11223344445566", [0, 0, 1, 1, 2, 2, 3, 3, 3, 3, 4, 4, 5, 5], 4),
        ("4白板 111234567白白白白东", [0, 0, 0, 1, 2, 3, 4, 5, 6, 33, 33, 33, 33, 27], 2),
    ]
    for name, tiles, expected in cases:
        got = calc_fan(T(*tiles))
        ok2 = got == expected
        ok = ok and ok2
        print(f"[{'OK  ' if ok2 else 'FAIL'}] {name}: got=x{got} expected=x{expected}")

    # 真·爆头：摸牌前已是 4面子+财神单吊（任意摸都胡）→ 需显式 baotou=True 才 ×2
    baotou_hand = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 27)  # 111222333444白东
    g = calc_fan(baotou_hand, baotou=True)
    print(f"[{'OK  ' if g == 2 else 'FAIL'}] 爆头(显式baotou): got=x{g} expected=x2")
    ok = ok and g == 2
    # 无 baotou 标记时平胡形不得 ×2
    g0 = calc_fan(baotou_hand)
    print(f"[{'OK  ' if g0 == 1 else 'FAIL'}] 爆头(无baotou标记=平胡): got=x{g0} expected=x1")
    ok = ok and g0 == 1

    # 2026-09-03 回归：七对+「最后摸来的财神补对」非爆头，只 ×4 不 ×8（服务器口径，青龙实证）
    # 真实青龙手: 1w1w 7w7w 8w8w 3t3t3t 9b9b9b9b 白 (14)  → 编码 1w=0,7w=6,8w=7,3t=11,9b=26,白=33
    qh = T(0, 0, 6, 6, 7, 7, 11, 11, 11, 26, 26, 26, 26, 33)
    gq = calc_fan(qh)  # baotou=False：豪华七对 ×4
    print(f"[{'OK  ' if gq == 4 else 'FAIL'}] 青龙手(七对+摸来财神) 非爆头: got=x{gq} expected=x4")
    ok = ok and gq == 4

    # 动态番型
    pinghu = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8)
    print("杠开(平胡+gang): x%d (期望2)" % calc_fan(pinghu, gang_kai=True))
    ok = ok and calc_fan(pinghu, gang_kai=True) == 2
    print("杠爆(爆头+gang): x%d (期望4)" % calc_fan(baotou_hand, gang_kai=True, baotou=True))
    ok = ok and calc_fan(baotou_hand, gang_kai=True, baotou=True) == 4
    print("财飘(piao=1, 爆头底): x%d (期望4)" % calc_fan(baotou_hand, piao_count=1, baotou=True))
    ok = ok and calc_fan(baotou_hand, piao_count=1, baotou=True) == 4
    print("双财飘(piao=2, 爆头底): x%d (期望8)" % calc_fan(baotou_hand, piao_count=2, baotou=True))
    ok = ok and calc_fan(baotou_hand, piao_count=2, baotou=True) == 8
    print("三财飘(piao=3, 爆头底): x%d (期望32)" % calc_fan(baotou_hand, piao_count=3, baotou=True))
    ok = ok and calc_fan(baotou_hand, piao_count=3, baotou=True) == 32

    # ---------- guide v21（2026-09-07）白板口径；期望值全部用免认证端点对拍确认 ----------
    # 对拍命令：POST /portal/api/tools/fan-calc {hand:[13张], draw:"<1张>"}
    # ① 七对「豪华组」：4 张真白板被用作百搭补落单 → 不重复计豪华（旧码恒 +1 组 → 多一层倍率）
    def ck(name, got, want):
        nonlocal ok
        o = got == want
        ok = ok and o
        print(f"[{'OK  ' if o else 'FAIL'}] {name}: got={got} want={want}")

    def branch(tiles10):
        """10 张非财神 + 4 张白板 → 七对分支因子（真实手牌 14 张）。"""
        return seven_pairs_branch(list_to_count(tiles10), 4)

    # 1w×4 2w×4 + 白板补 5w/6w 单张：自然 2 组四张（白板补单不算）→ 双豪华 ×8（旧码 ×16）
    ck("v21① 2自然四张+白板补2单 → 双豪华", branch([0, 0, 0, 0, 1, 1, 1, 1, 4, 5]), 8)
    # 1w×4 2w2w 3w3w + 白板补 5w/6w 单张：自然 1 组四张（白板补单不算）→ 豪华 ×4（旧码 ×8）
    ck("v21① 1自然四张+白板补2单 → 豪华", branch([0, 0, 0, 0, 1, 1, 2, 2, 4, 5]), 4)
    # 其余牌全自然对、白板两两自配：4 白板仍计 1 组四张 → 双豪华 ×8（若把 +1 整条删掉会掉成 ×4）
    ck("v21① 其余全自然对 4白仍计1组 → 双豪华", branch([0, 0, 0, 0, 1, 1, 2, 2, 3, 3]), 8)
    # 端到端（对拍 server：1w1w1w1w2w2w2w2w5w6w白白白 + 摸白 → fan=x32 detail=['豪华七对×2','4个白板','爆头']）
    ck("v21① 端到端 2自然四张+白板补2单+爆头 = x32",
       calc_fan(T(0, 0, 0, 0, 1, 1, 1, 1, 4, 5, 33, 33, 33, 33), baotou=True), 32)

    # ② 爆头：撤销「听牌态正好 4 张白板不算爆头」旧裁 —— 4 白听任意即胡计爆头，与 4 白板×2 叠加
    # 3对+3单+4白（摸前 13 张），摸 4w 成七对；对拍 server fan=x8 detail=['七对','4个白板','爆头']
    h13_bt = T(0, 0, 1, 1, 2, 2, 3, 4, 5, 33, 33, 33, 33)
    ck("v21② 3对+3单+4白 摸前13张 任意摸都胡", any_draw_win(h13_bt), True)
    h14_bt = list(h13_bt); h14_bt[3] += 1  # 摸 4w
    ck("v21② 端到端 3对+3单+4白+爆头 = x8",
       calc_fan(h14_bt, baotou=any_draw_win(h13_bt)), 8)
    # 1w1w2w2w3w3w4w4w5w 白白白白（摸前 13 张，白板自配）摸 5w；对拍 server fan=x16
    h13_bt2 = T(0, 0, 1, 1, 2, 2, 3, 3, 4, 33, 33, 33, 33)
    h14_bt2 = list(h13_bt2); h14_bt2[4] += 1
    ck("v21② 4白爆头 + 豪华七对 端到端 = x16",
       calc_fan(h14_bt2, baotou=any_draw_win(h13_bt2)), 16)

    # ---------- YCB（有财必拷响）判据：摸前 13 张任意摸都胡 → 可胡；否则不可（杠开豁免） ----------
    # 2026-09-09 修正：旧判据 shanten_baotou(...) != -1 对 14 张胡牌恒真 → 持财神的胡全被拒
    bao14 = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 27)  # 4面子 + 白 + 东（白单吊）
    ck("YCB 真爆头(白单吊) 可胡", ycb_can_hu(bao14, drawn=27), True)
    ck("YCB 4白爆头 可胡（v21②）", ycb_can_hu(h14_bt2, drawn=4), True)
    ck("YCB 七对+摸来财神(青龙) 不可胡", ycb_can_hu(qh, drawn=33), False)
    ck("YCB 无财神 平胡可胡", ycb_can_hu(T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8), drawn=8), True)
    # 平胡但财神作百搭补面子（非爆头）→ YCB 拒；杠开（杠上花）免爆头 → 准
    plain_lz = T(0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13, 13, 33)  # 1w2w[白] 456w789w 111t 55t
    ck("YCB 平胡(财神在面子内) 不可胡", ycb_can_hu(plain_lz, drawn=13), False)
    ck("YCB 杠开(杠上花) 免爆头 可胡", ycb_can_hu(plain_lz, drawn=13, gang_kai=True), True)

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
