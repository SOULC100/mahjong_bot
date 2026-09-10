"""YouCaiBiKao（有财必拷响）语义单元测试。

覆盖：
① 手有财神不允许平胡（标准胡形但非真·爆头 → YCB 下不是胡；无 YCB 时可胡）
② 爆头形允许胡：4面子+财神单吊（真爆头）/ 七客（6对+财神）任意摸都胡
③ 弃最后一张财神 = 逃回平胡后允许平胡（decision 层 + engine 层）
④ 杠开在 YCB 下是免爆头胡法（普通形 + gang_kai 允许胡）
⑤ 七对+财神：仅「摸前已是 6对+财神（七客）」能胡；「最后摸来财神补成七对」
   不能胡（青龙实证，服务器只给 ×4）

2026-09-03 关键回归：`shanten_baotou` 对 14 张胡牌最小值恒为 0、永不为 -1，
旧 YCB 判据 `shanten_baotou(hand) != -1` 会把所有持财神的胡（含真爆头/七客）全拒。
本测试锁定修复后的正确判据（_can_win 用 _any_draw_win(摸前13) + 杠开豁免）。
"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong.tiles import list_to_count
from mahjong.win import can_win, split_laizi
from mahjong.decision import discard_decision
from sim.engine import Game
from sim.players import Baseline, Smart
from mahjong import shanten as _sh


def T(*tiles):
    return list_to_count(tiles)


def _gate(hand14, drawn, ycb=True, gang=False):
    """构造一个局面：seat0 手牌 = hand14（14 张，无副露），问能否胡。"""
    g = Game(seed=1, youcai_bikao=ycb)
    g.hands[0] = hand14
    g.melds[0] = []
    return g._can_win(0, drawn_tile=drawn, gang_kai=gang)


def _win_mult(hand14, drawn, gang=False, piao=0):
    """结算 seat0 的番型倍率（连 score 一起走 engine._win_result）。"""
    g = Game(seed=1, youcai_bikao=True)
    g.hands[0] = hand14
    g.melds[0] = []
    g.piao_count[0] = piao
    w, mult, scores, d = g._win_result(0, gang_kai=gang, drawn_tile=drawn)
    return mult


def main():
    ok = True
    def ck(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"[{'OK  ' if cond else 'FAIL'}] {name}")

    # ---------- ① 手有财神不允许平胡 ----------
    # 111w222w333w + 6t7t[白] + 9t9t，摸 7t 成 567t（白作 5t），平胡且财神在面子内 → YCB 拒
    plain_laizi = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 14, 15, 17, 17, 33)  # 摸7t(idx15)
    ck("① 平胡(财神在面子内) can_win=True", can_win(plain_laizi))
    ck("① YCB 拒平胡: _can_win=False", _gate(plain_laizi, 15) is False)
    ck("① 非 YCB 允许平胡: _can_win=True", _gate(plain_laizi, 15, ycb=False) is True)

    # ---------- ② 爆头形允许胡 ----------
    # 真爆头：111w222w333w444w + 白 摸 9w → 财神做将单吊，任意摸都胡
    bao = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 8)
    ck("② 真爆头 can_win=True", can_win(bao))
    ck("② YCB 允许真爆头: _can_win=True", _gate(bao, 8) is True)
    # 七客：6对 + 白 摸 9b → 任意摸都胡
    qike = T(0, 0, 1, 1, 2, 2, 9, 9, 10, 10, 11, 11, 33, 26)
    ck("② 七客(6对+财神) can_win=True", can_win(qike))
    ck("② YCB 允许七客: _can_win=True", _gate(qike, 26) is True)

    # ---------- ③ 弃最后财神逃回平胡 ----------
    # 123w456w789w 东东 2t3t 白：弃白 → 3面子+将+搭子=平胡听牌；留白须追爆头（慢）
    esc = T(0, 1, 2, 3, 4, 5, 6, 7, 8, 27, 27, 10, 11, 33)
    ck("③ YCB 弃最后财神逃平胡: discard=白",
       discard_decision(esc, youcai_bikao=True) == 33)
    ck("③ 非 YCB 保留财神: discard!=白",
       discard_decision(esc, youcai_bikao=False) != 33)
    # ycb_escape_gap 门限：gap 很大 → 不逃，继续追爆头
    d_gap = discard_decision(esc, youcai_bikao=True, ycb_escape_gap=999)
    ck("③ gap=999 时不逃平胡: discard!=白", d_gap != 33)
    # 逃回后（无财神）平胡在 YCB 下允许
    no_laizi_plain = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8)  # 11122233345699
    ck("③ 无财神平胡在 YCB 下允许: _can_win=True", _gate(no_laizi_plain, 8) is True)

    # ---------- ④ 杠开在 YCB 是免爆头胡法 ----------
    # 同样的「财神在面子内的平胡」，若是杠开（gang_kai=True）→ YCB 允许
    ck("④ 平胡形(持财神)+杠开 YCB 允许: _can_win=True",
       _gate(plain_laizi, 15, gang=True) is True)
    # 杠爆 = 爆头形 + 杠 → YCB 允许且倍率 x4
    ck("④ 爆头形+杠 YCB 允许: _can_win=True", _gate(bao, 8, gang=True) is True)
    ck("④ 真爆头自摸倍率 x2", _win_mult(bao, 8, gang=False) == 2)
    ck("④ 杠爆(爆头+杠开)倍率 x4", _win_mult(bao, 8, gang=True) == 4)
    # 杠开平胡(持财神、非爆头) 倍率 x2（仅杠开）
    ck("④ 杠开平胡(持财神)倍率 x2", _win_mult(plain_laizi, 15, gang=True) == 2)

    # ---------- ⑤ 七对+财神：什么时候能胡 ----------
    # 青龙手 1w1w 7w7w 8w8w 3t3t3t 9b9b9b9b 白（摸来的白补成豪华七对）→ 非爆头，YCB 拒
    qinglong = T(0, 0, 6, 6, 7, 7, 11, 11, 11, 26, 26, 26, 26, 33)
    ck("⑤ 青龙(七对+摸来财神) can_win=True", can_win(qinglong))
    ck("⑤ YCB 拒青龙(非爆头七对): _can_win=False", _gate(qinglong, 33) is False)
    ck("⑤ 非 YCB 允许青龙: _can_win=True", _gate(qinglong, 33, ycb=False) is True)
    ck("⑤ 青龙倍率 x4（非爆头不 x8）", _win_mult(qinglong, 33, gang=False) == 4)

    # ---------- 引擎级回归：YCB 整局不再把持财神爆头全拒 ----------
    # 真爆头 13 张（4面子+白），任意摸 t 都得 14 张胡牌且 YCB 必须认胡（修复前恒拒）
    pre13 = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33]
    any_ok = True
    for t in range(34):
        if t == 33:  # 摸财神也胡（变两白将）
            final = T(*(pre13 + [33]))
        else:
            final = T(*(pre13 + [t]))
        if not (can_win(final) and _gate(final, t) is True):
            any_ok = False
            ck(f"② YCB 爆头任意摸[{t}] 均胡", False)
            break
    if any_ok:
        ck("② YCB 真爆头任意摸均胡（engine _can_win 不再误拒 34/34）", True)

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
