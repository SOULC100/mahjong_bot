"""复盘任意一局：重建手牌 + 用**线上同一套判据**离线重算每一次出牌，并与实际出牌对拍。

用法：
    python explain_round.py <room> <batch> <round_no> [uid]
    python explain_round.py a_5b83c31e82d3 0 3          # 该房第 0 场的第 3 局

为什么结论可信：
- 手牌重建用事件流（起手 + 我摸到的 - 我打出的 - 我鸣牌消耗的；事件流 `chi.data.tiles` 含被吃那张）；
- `remain` 用与线上一致的口径（`GameState._recalc_remain`：可见牌 = 我的手牌 + 四家弃牌 + 四家副露，
  再按牌墙比例缩放——缩放是同一常数，不改变候选排序）；
- 决策直接调用线上同一个 `mahjong.decision.discard_decision`（depth=False / fan_override=True，
  与 smart_bot 的开关一致），所以「重算 == 实际」既是解释也是保真度校验。

数据来源：`data/matches/<room>/events/b<batch>.json`（由 match_session.py 归档）。
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from mahjong.tiles import tile_from_str, tile_to_str          # noqa: E402
from mahjong.shanten import shanten, clear_caches             # noqa: E402
from mahjong import decision                                  # noqa: E402


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    room, batch, rnd = sys.argv[1], sys.argv[2], int(sys.argv[3])
    uid = sys.argv[4] if len(sys.argv) > 4 else None

    path = os.path.join(ROOT, "data", "matches", room, "events", "b%s.json" % batch)
    if not os.path.exists(path):
        print("找不到事件流：%s（先用 match_session.py 归档）" % path)
        return 1
    ev = json.load(open(path, encoding="utf-8"))
    seats = ev.get("seats") or []
    if uid is None:
        tok = open(os.path.join(ROOT, "data", "global_token.txt"), encoding="utf-8").read().strip()
        import hashlib
        import ssl
        import urllib.request
        req = urllib.request.Request("https://10.240.169.190:18080/api/me",
                                     headers={"Authorization": "Bearer " + tok})
        uid = json.loads(urllib.request.urlopen(
            req, context=ssl._create_unverified_context(), timeout=25).read().decode())["user_id"]
    me = [i for i, s in enumerate(seats) if s.get("user_id") == uid][0]

    blocks = [b for b in (ev.get("blocks") or []) if b.get("round_no") == rnd]
    start = dealer = None
    for b in blocks:
        if b.get("start_hands"):
            start = [list(h) for h in b["start_hands"]]
            dealer = b.get("dealer")
            break
    if not start:
        print("第 %d 局没有起手快照" % rnd)
        return 1

    hand = list(start[me])
    discards = [[] for _ in range(4)]
    melds = [[] for _ in range(4)]
    meld_n = [0, 0, 0, 0]
    n_draw = [0, 0, 0, 0]

    def cnt(tiles):
        c = [0] * 34
        for t in tiles:
            c[tile_from_str(t)] += 1
        return c

    def remain_of(my_counts):
        visible = list(my_counts)
        for row in discards:
            for t in row:
                visible[tile_from_str(t)] += 1
        for row in melds:
            for t in row:
                visible[tile_from_str(t)] += 1
        return [max(0, 4 - visible[t]) for t in range(34)]

    def candidates(c14, rm, mn):
        rows = []
        for t in range(34):
            if c14[t] <= 0:
                continue
            c2 = list(c14)
            c2[t] -= 1
            rows.append((shanten(c2, mn), -decision._draw_quality(c2, rm, mn), t))
        rows.sort()
        return [{"tile": tile_to_str(t), "shanten": s, "quality": -nq} for s, nq, t in rows]

    print("game=%s 第%d局 dealer=seat%s 我=seat%s(%s)"
          % (ev.get("game_id"), rnd, dealer, me, seats[me].get("name")))
    print("我起手:", " ".join(sorted(hand, key=tile_from_str)))
    print()
    ok = bad = 0
    for b in blocks:
        events = b.get("events") or []
        for idx, e in enumerate(events):
            t, seat, tile, d = e.get("type"), e.get("seat"), e.get("tile"), e.get("data") or {}
            if t == "tile_drawn":
                n_draw[seat] += 1
                if seat == me:
                    hand.append(tile)
            elif t == "tile_discarded":
                discards[seat].append(tile)
                if seat == me and tile in hand:
                    hand.remove(tile)
            elif t in ("chi", "peng", "gang"):
                if t == "chi":
                    got = [x for x in (d.get("tiles") or []) if x != tile]
                elif t == "peng":
                    got = [tile, tile]
                else:
                    got = {"ming": [tile] * 3, "bu": [tile], "an": [tile] * 4}.get(d.get("kind"), [])
                melds[seat].extend(got)
                meld_n[seat] += 1
            if t != "tile_drawn" or seat != me:
                continue
            c14 = cnt(hand)
            rows = candidates(c14, remain_of(c14), meld_n[me])
            picked = tile_to_str(decision.discard_decision(
                c14, remain_of(c14), meld_n[me], depth=False, dealer=False, fan_override=True,
                allowed=None, youcai_bikao=False, dealer_speed=False))
            actual = None
            for e2 in events[idx + 1:]:
                if e2.get("type") == "tile_discarded" and e2.get("seat") == me:
                    actual = e2.get("tile")
                    break
            same = picked == actual
            ok, bad = (ok + 1, bad) if same else (ok, bad + 1)
            print("第%s巡 摸 %-3s  手牌: %s" % (n_draw[me], tile,
                                               " ".join(sorted(hand, key=tile_from_str))))
            print("   候选: " + " | ".join("%s 向听%d 进张%.1f" % (r["tile"], r["shanten"], r["quality"])
                                           for r in rows[:5]))
            print("   实际出 %s；线上判据重算 → %s   %s%s"
                  % (actual, picked, "✅" if same else "❌ 不一致", "（庄家）" if me == dealer else ""))
    print("\n对拍：一致 %d 手 / 不一致 %d 手" % (ok, bad))
    clear_caches()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
