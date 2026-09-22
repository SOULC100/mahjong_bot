"""进张账本：把「打 A」与「打 B」两个选项的有效进张按花色分项列出来做差。

用法：python discard_ledger.py <room> <batch> <round_no> <巡数> A B [uid]
例：  python discard_ledger.py a_5b83c31e82d3 0 3 5 2w 9t
"""

import json
import sys

sys.path.insert(0, ".")
from mahjong.tiles import tile_from_str, tile_to_str                     # noqa: E402
from mahjong.shanten import shanten                                      # noqa: E402

ROOM, BATCH, ROUND, TURN = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
A, B = sys.argv[5], sys.argv[6]
UID = sys.argv[7] if len(sys.argv) > 7 else "u_307259698ca9"

ev = json.load(open("data/matches/%s/events/b%s.json" % (ROOM, BATCH), encoding="utf-8"))
me = [i for i, s in enumerate(ev["seats"]) if s.get("user_id") == UID][0]
blocks = [b for b in ev["blocks"] if b.get("round_no") == ROUND]
start = next([list(h) for h in b["start_hands"]] for b in blocks if b.get("start_hands"))

hand = list(start[me])
discards = [[] for _ in range(4)]
melds = [[] for _ in range(4)]
meld_n = [0, 0, 0, 0]
nd = 0
target = snap = None
for b in blocks:
    for e in b.get("events") or []:
        t, seat, tile, d = e.get("type"), e.get("seat"), e.get("tile"), e.get("data") or {}
        if t == "tile_drawn" and seat == me:
            nd += 1
            hand.append(tile)
            if nd == TURN:
                target = list(hand)
                snap = ([list(r) for r in discards], [list(r) for r in melds])
                break
        elif t == "tile_discarded":
            discards[seat].append(tile)
            if seat == me and tile in hand:
                hand.remove(tile)
        elif t in ("chi", "peng", "gang"):
            got = ([x for x in (d.get("tiles") or []) if x != tile] if t == "chi"
                   else [tile, tile] if t == "peng"
                   else {"ming": [tile] * 3, "bu": [tile], "an": [tile] * 4}.get(d.get("kind"), []))
            melds[seat].extend(got)
            meld_n[seat] += 1
    if target:
        break
discards, melds = snap


def cnt(tiles):
    c = [0] * 34
    for x in tiles:
        c[tile_from_str(x)] += 1
    return c


visible = cnt(target)
for row in discards:
    for x in row:
        visible[tile_from_str(x)] += 1
for row in melds:
    for x in row:
        visible[tile_from_str(x)] += 1
unseen = [max(0, 4 - visible[t]) for t in range(34)]
c14 = cnt(target)
print("手牌:", " ".join(sorted(target, key=tile_from_str)), "（副露 %d 组）" % meld_n[me])


def gain_of(discard_name):
    c13 = list(c14)
    c13[tile_from_str(discard_name)] -= 1
    s = shanten(c13, meld_n[me])
    out = {}
    for u in range(34):
        if unseen[u] <= 0:
            continue
        c2 = list(c13)
        c2[u] += 1
        if shanten(c2, meld_n[me]) < s:
            out[u] = unseen[u]
    return s, out


sA, gA = gain_of(A)
sB, gB = gain_of(B)
SUIT = lambda t: "万" if t < 9 else "条" if t < 18 else "筒" if t < 27 else "字"
names = {"万": "万子", "条": "条子", "筒": "筒子", "字": "字牌(白=财神)"}
# 平台口径：w=万、**t=条**、**b=筒**（本仓索引 9~17 = 协议 t = 条，18~26 = 协议 b = 筒；
# 见 mahjong/tiles.py 文件头与 tests/test_tile_coding.py —— 早期注释把这两者写反过）

print("\n打 %s → 向听%d，有效进张 %d 张；打 %s → 向听%d，有效进张 %d 张"
      % (A, sA, sum(gA.values()), B, sB, sum(gB.values())))
for suit in ("万", "条", "筒", "字"):
    ta = {u: n for u, n in gA.items() if SUIT(u) == suit}
    tb = {u: n for u, n in gB.items() if SUIT(u) == suit}
    fmt = lambda d: " ".join("%s(%d)" % (tile_to_str(u), n) for u, n in sorted(d.items())) or "—"
    print("\n%s：" % names[suit])
    print("   打 %-3s: %2d 张 | %s" % (A, sum(ta.values()), fmt(ta)))
    print("   打 %-3s: %2d 张 | %s" % (B, sum(tb.values()), fmt(tb)))
    only_a = {u: n for u, n in ta.items() if u not in tb}
    only_b = {u: n for u, n in tb.items() if u not in ta}
    if only_a or only_b:
        print("   → 打 %s 才有的: %s（%d 张）｜ 打 %s 才有的: %s（%d 张）"
              % (A, fmt(only_a), sum(only_a.values()), B, fmt(only_b), sum(only_b.values())))
print("\n净差（打 %s − 打 %s）= %+d 张"
      % (A, B, sum(gA.values()) - sum(gB.values())))
