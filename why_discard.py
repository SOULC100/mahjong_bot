"""拆解某一次出牌：把每个候选打掉后，剩下 13 张的**真实进张**逐张列出来（回答「为什么打这张」）。

用法：
    python why_discard.py <room> <batch> <round_no> <巡数> [uid]
    python why_discard.py a_5b83c31e82d3 0 3 5      # 该房第 0 场、第 3 局、第 5 巡

输出：
- 该巡 14 张手牌（含财神张数）
- 每个候选：打掉后向听、能降向听的进张（含牌墙剩余张数）、**进张张数合计**、
  以及线上判据的「进张质量」分（= Σ remain[t] × (1 + max(0, 3 - 新向听))；同向听时它就是张数的加权）
- 附「候选牌自身的关联牌」（同花色能与之组搭子的牌 + 自己对子）

口径：可见信息**截至该巡**（bot 当时看不到后面的弃牌）；remain = 4 − 可见张数
（可见 = 我的手牌 + 四家弃牌 + 四家副露）。判据与线上同一份 `mahjong.decision`。
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from mahjong.tiles import tile_from_str, tile_to_str, LAIZI_INDEX   # noqa: E402
from mahjong.shanten import shanten, clear_caches                    # noqa: E402
from mahjong import decision                                        # noqa: E402


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    room, batch, rnd, turn = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    uid = sys.argv[5] if len(sys.argv) > 5 else None

    path = os.path.join(ROOT, "data", "matches", room, "events", "b%s.json" % batch)
    if not os.path.exists(path):
        print("找不到事件流：%s（先用 match_session.py 归档）" % path)
        return 1
    ev = json.load(open(path, encoding="utf-8"))
    seats = ev.get("seats") or []
    if uid is None:
        import hashlib
        import ssl
        import urllib.request
        tok = open(os.path.join(ROOT, "data", "global_token.txt"), encoding="utf-8").read().strip()
        req = urllib.request.Request("https://10.240.169.190:18080/api/me",
                                     headers={"Authorization": "Bearer " + tok})
        uid = json.loads(urllib.request.urlopen(
            req, context=ssl._create_unverified_context(), timeout=25).read().decode())["user_id"]
    me = [i for i, s in enumerate(seats) if s.get("user_id") == uid][0]

    blocks = [b for b in ev["blocks"] if b.get("round_no") == rnd]
    start = None
    for b in blocks:
        if b.get("start_hands"):
            start = [list(h) for h in b["start_hands"]]
            break
    if not start:
        print("第 %d 局没有起手快照" % rnd)
        return 1

    hand = list(start[me])
    discards = [[] for _ in range(4)]
    melds = [[] for _ in range(4)]
    meld_n = [0, 0, 0, 0]
    nd = 0
    target_hand = snap_discards = snap_melds = None
    for b in blocks:
        for e in b.get("events") or []:
            t, seat, tile, d = e.get("type"), e.get("seat"), e.get("tile"), e.get("data") or {}
            if t == "tile_drawn" and seat == me:
                nd += 1
                hand.append(tile)
                if nd == turn:
                    target_hand = list(hand)
                    snap_discards = [list(r) for r in discards]
                    snap_melds = [list(r) for r in melds]
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
        if target_hand is not None:
            break
    if target_hand is None:
        print("没到第 %d 巡" % turn)
        return 1
    discards, melds = snap_discards, snap_melds

    def cnt(tiles):
        c = [0] * 34
        for t in tiles:
            c[tile_from_str(t)] += 1
        return c

    visible = cnt(target_hand)
    for row in discards:
        for t in row:
            visible[tile_from_str(t)] += 1
    for row in melds:
        for t in row:
            visible[tile_from_str(t)] += 1
    raw_unseen = [max(0, 4 - visible[t]) for t in range(34)]

    c14 = cnt(target_hand)
    print("第 %d 巡手牌（%d 张）: %s" % (turn, sum(c14), " ".join(sorted(target_hand, key=tile_from_str))))
    print("副露 %d 组；白(财神)=%d 张\n" % (meld_n[me], c14[LAIZI_INDEX]))

    rows = []
    for t in range(34):
        if c14[t] <= 0:
            continue
        c13 = list(c14)
        c13[t] -= 1
        s = shanten(c13, meld_n[me])
        gain = []
        for u in range(34):
            if raw_unseen[u] <= 0:
                continue
            c2 = list(c13)
            c2[u] += 1
            if shanten(c2, meld_n[me]) < s:
                gain.append((u, raw_unseen[u], shanten(c2, meld_n[me])))
        rows.append((s, -decision._draw_quality(c13, raw_unseen, meld_n[me]), t, gain,
                     decision._draw_quality(c13, raw_unseen, meld_n[me])))
    rows.sort()

    print("按线上判据排序（向听 → 进张质量）:")
    for s, _nq, t, gain, q in rows:
        tiles_txt = " ".join("%s×%d→%d" % (tile_to_str(u), n, ns) for u, n, ns in gain) or "（无进张）"
        print("  打 %-3s → 向听%d  进张 %2d 张 | 质量 %5.1f | %s"
              % (tile_to_str(t), s, sum(n for _u, n, _ns in gain), q, tiles_txt))

    print("\n附：候选牌**自身的关联牌**（同花色能与之组搭子的牌 + 自己对子）")
    for name in ("2w", "6w", "9t"):
        if tile_from_str(name) not in [tile_to_str(t) for _s, _n, t, _g, _q in rows]:
            continue
        t = tile_from_str(name)
        r = t % 9
        cand = {t}
        if r >= 1:
            cand.add(t - 1)
        if r >= 2:
            cand.add(t - 2)
        if r <= 7:
            cand.add(t + 1)
        if r <= 6:
            cand.add(t + 2)
        cand = sorted(x for x in cand if x // 9 == t // 9)
        print("  %-3s 关联牌 %s → 未见合计 %d 张（%d 种）"
              % (name, " ".join("%s(%d)" % (tile_to_str(x), raw_unseen[x]) for x in cand),
                 sum(raw_unseen[x] for x in cand), len(cand)))
    clear_caches()
    return 0


if __name__ == "__main__":
    sys.exit(main())
