"""复盘任意一局：回答「为什么不去敲响」（= 不保留财神做将走「任意摸都胡 ×2」的终局）。

用法：
    python why_knock.py <room> <batch> <round_no> [uid]
    python why_knock.py a_41c78761ce3c 0 6

输出（同时写入 data/_knock_<room>_b<batch>_r<round>.txt，UTF-8）：
1. 本局所有「白板/财神」事件（谁摸到、谁打出）——**没有白板 = 敲响路线根本不存在**；
2. 我每次摸牌后的 14 张：普通向听 / 财神做将(爆头)向听 / 敲响向听(knock_shanten)；
   线上实际出牌（knock=False）vs 把 knock=True 打开的判据重算结果；
3. 终局：我的胡牌形、番型（平胡/爆头/七对…）与得分。

口径：手牌重建与 `explain_round.py` / `data/_pm_rounds.py` 完全相同（事件流起手 + 摸牌 - 出牌 - 副露）；
判据直接调用线上同一份 `mahjong.decision.discard_decision`，参数与 `smart_bot.choose_discard` 对齐
（depth=False / fan_override=True / dealer_speed=aggr / youcai_bikao=房规）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from mahjong.tiles import tile_from_str, tile_to_str, LAIZI_INDEX   # noqa: E402
from mahjong.shanten import shanten, shanten_baotou, clear_caches    # noqa: E402
from mahjong import decision                                        # noqa: E402
from mahjong.fan import calc_fan, any_draw_win                      # noqa: E402

LAIZI = tile_to_str(LAIZI_INDEX)   # 白


def cnt(tiles):
    c = [0] * 34
    for t in tiles:
        c[tile_from_str(t)] += 1
    return c


def remain_of(my_counts, discards, melds):
    visible = list(my_counts)
    for row in discards:
        for t in row:
            visible[tile_from_str(t)] += 1
    for row in melds:
        for t in row:
            visible[tile_from_str(t)] += 1
    return [max(0, 4 - visible[t]) for t in range(34)]


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    room, batch, rnd = sys.argv[1], sys.argv[2], int(sys.argv[3])
    uid = sys.argv[4] if len(sys.argv) > 4 else None

    path = os.path.join(ROOT, "data", "matches", room, "events", "b%s.json" % batch)
    if not os.path.exists(path):
        print("找不到事件流：%s" % path)
        return 1
    ev = json.load(open(path, encoding="utf-8"))
    seats = ev.get("seats") or []
    if uid is None:
        sess = os.path.join(ROOT, "data", "matches", room, "session.json")
        uid = json.load(open(sess, encoding="utf-8"))["user_id"]
        if not uid or uid == "-":
            print("无法确定 uid：请在命令行给出第 4 个参数")
            return 1
    me = [i for i, s in enumerate(seats) if s.get("user_id") == uid][0]
    ycb = False
    mpath = os.path.join(ROOT, "data", "matches", room, "session.json")
    if os.path.exists(mpath):
        ycb = bool(json.load(open(mpath, encoding="utf-8")).get("config", {}).get("YouCaiBiKao"))

    blocks = sorted([b for b in ev["blocks"] if b.get("round_no") == rnd],
                    key=lambda b: b["seq_start"])
    if not blocks:
        print("第 %d 局不存在" % rnd)
        return 1
    start = None
    for b in blocks:
        if b.get("start_hands"):
            start = [list(h) for h in b["start_hands"]]
            dealer = b.get("dealer")
            break
    if not start:
        print("第 %d 局没有起手快照" % rnd)
        return 1
    events = []
    for b in blocks:
        events.extend(b["events"])

    out = []
    out.append("game=%s 第%d局 dealer=seat%s 我=seat%s(%s) 房规YouCaiBiKao=%s"
               % (ev.get("game_id"), rnd, dealer, me, seats[me].get("name"), ycb))
    out.append("我起手(%d张): %s"
               % (len(start[me]), " ".join(sorted(start[me], key=tile_from_str))))

    # ---- 1) 全桌财神事件 ----
    out.append("")
    out.append("【全桌「%s」事件】" % LAIZI)
    for e in events:
        t, seat, tile = e.get("type"), e.get("seat"), e.get("tile")
        if tile != LAIZI:
            continue
        d = e.get("data") or {}
        tag = ""
        if t == "tile_drawn":
            tag = "摸到" + ("(杠后补)" if d.get("gang_replenish") else "")
        elif t == "tile_discarded":
            tag = "打出%s" % ("（抓打圈）" if d.get("catch_play") else "")
        elif t in ("chi", "peng", "gang"):
            tag = "鸣牌"
        out.append("  seq%-5s seat%s %-12s %s%s"
                   % (e.get("seq"), seat, t, tag, "  ← 我" if seat == me else ""))

    # ---- 2) 逐巡复盘 ----
    hand = list(start[me])
    discards = [[] for _ in range(4)]
    melds = [[] for _ in range(4)]
    meld_n = [0, 0, 0, 0]
    n_draw = [0, 0, 0, 0]
    turns = []
    end = None
    for i, e in enumerate(events):
        t, seat, tile, d = e.get("type"), e.get("seat"), e.get("tile"), e.get("data") or {}
        if t == "tile_drawn":
            n_draw[seat] += 1
            if seat == me:
                hand.append(tile)
                # 该巡的可见信息（含我手上这 14 张）
                c14 = cnt(hand)
                rm = remain_of(c14, discards, melds)
                nxt = None
                for e2 in events[i + 1:]:
                    if e2.get("type") == "tile_discarded" and e2.get("seat") == me:
                        nxt = e2
                        break
                    if e2.get("type") == "round_ended":
                        break
                turns.append(dict(turn=n_draw[me], tile=tile, hand=list(hand), c14=c14, rm=rm,
                                  melds=meld_n[me], actual=(nxt or {}).get("tile")))
        elif t == "tile_discarded":
            discards[seat].append(tile)
            if seat == me and tile in hand:
                hand.remove(tile)
        elif t in ("chi", "peng", "gang"):
            if t == "chi":
                got = [x for x in (d.get("tiles") or []) if x != tile]
                meld_n[seat] += 1
            elif t == "peng":
                got = [tile, tile]
                meld_n[seat] += 1
            else:
                k = d.get("kind")
                got = {"ming": [tile] * 3, "bu": [tile], "an": [tile] * 4}.get(k, [])
                if k != "bu":
                    meld_n[seat] += 1
            melds[seat].extend(got)
            if seat == me:
                for x in got:
                    if x in hand:
                        hand.remove(x)
        elif t == "round_ended":
            end = e.get("data") or {}

    out.append("")
    out.append("【我每次摸牌后（线上判据 vs 打开 knock）】")
    changed = []
    for tn in turns:
        c14, rm, m = tn["c14"], tn["rm"], tn["melds"]
        la = c14[LAIZI_INDEX]
        s_std = shanten(c14, m)
        s_bao = shanten_baotou(c14, m)
        s_knock = decision.knock_shanten(c14, m)
        # 与 smart_bot.choose_discard 完全同参：USE_DEPTH=False / dealer=False（线上恒不传庄家番权）
        # / allowed=手里全部牌（含白，抓打圈限制在线上另判）/ dealer_speed 只在本人坐庄时开
        # （smart_bot.py:530 `DEALER_POLICY == "aggr" and is_dealer`）。
        allowed = set(t for t in range(34) if c14[t] > 0)
        common = dict(depth=False, dealer=False, fan_override=True, allowed=allowed,
                      youcai_bikao=ycb, dealer_speed=(me == dealer))
        pick_off = decision.discard_decision(c14, rm, m, knock=False, **common)
        pick_on = decision.discard_decision(c14, rm, m, knock=True, **common)
        pick_off, pick_on = tile_to_str(pick_off), tile_to_str(pick_on)
        flag = "" if pick_off == pick_on else "   ← knock 会改判"
        if pick_off != pick_on:
            changed.append(tn["turn"])
        out.append("")
        out.append("第%2d巡 摸 %-3s  白=%d  手牌(%d张): %s"
                   % (tn["turn"], tn["tile"], la, sum(c14),
                      " ".join(sorted(tn["hand"], key=tile_from_str))))
        out.append("      普通向听=%s  财神做将(爆头)向听=%s  敲响向听=%s%s"
                   % (s_std if s_std < 99 else "-",
                      s_bao if s_bao < 99 else "-",
                      s_knock if s_knock < 99 else "-",
                      "   已「任意摸都胡」×2" if la and any_draw_win(c14, m) else ""))
        out.append("      实际出 %-3s | 线上判据(knock=False) → %-3s | knock=True → %-3s%s"
                   % (tn["actual"], pick_off, pick_on, flag))

    out.append("")
    out.append("【终局】")
    if end:
        out.append("  round_ended: winner=seat%s fan=%s detail=%s scores=%s"
                   % (end.get("seat"), end.get("fan"), end.get("detail"), end.get("scores")))
    # 终局时我的手牌（末次摸牌后再无出牌时即胡形）
    if turns:
        last = turns[-1]
        if last["actual"] is None:
            la = last["c14"][LAIZI_INDEX]
            h13 = list(last["c14"])
            h13[tile_from_str(last["tile"])] -= 1
            out.append("  我胡牌形: %s" % " ".join(sorted(last["hand"], key=tile_from_str)))
            out.append("  财神=%d  摸前13张「任意摸都胡」=%s  平胡番=%d  爆头番=%d"
                       % (la, any_draw_win(h13, last["melds"]),
                          calc_fan(last["c14"], baotou=False),
                          calc_fan(last["c14"], baotou=True)))
    out.append("")
    out.append("【结论】")
    all_laizi = [tn for tn in turns if tn["c14"][LAIZI_INDEX] > 0]
    if not all_laizi:
        out.append("  本局我**从头到尾没摸到过财神（%s）** → 敲响路线（留 1 张财神做将/单吊）"
                   "在规则上就不可能，不是策略选择问题。" % LAIZI)
    else:
        out.append("  我手上有财神的巡数：%s" % [tn["turn"] for tn in all_laizi])
    if changed:
        out.append("  knock=True 会改变出牌的巡：%s（其余巡不变）" % changed)
    else:
        out.append("  knock=True **一次也不会改变我的出牌**（与 docs/improvement-plan.md 记录一致："
                   "knock_shanten >= 普通向听恒成立 → 判据惰性）")

    txt = "\n".join(out) + "\n"
    dst = os.path.join(ROOT, "data", "_knock_%s_b%s_r%d.txt" % (room, batch, rnd))
    open(dst, "w", encoding="utf-8").write(txt)
    print(txt)
    print("报告已写入 %s" % dst)
    clear_caches()
    return 0


if __name__ == "__main__":
    sys.exit(main())
