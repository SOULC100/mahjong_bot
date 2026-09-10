"""离线回放验证：用真实对局 events 重建局面，对比 smart 决策 vs 最小 Bot 出牌。

对每局 seat 0（我方）的每个出牌决策点，比较：
- 实际出牌（最小 Bot 打第一张）后的向听数
- smart 决策（discard_decision）出牌后的向听数
smart 若更优（向听数更低），说明决策引擎有效。
"""

import glob
import json
import sys

sys.path.insert(0, ".")

from mahjong.tiles import tile_from_str, tile_to_str
from mahjong.decision import discard_decision
from mahjong.ukeire import shanten_after_discard


def replay_seat0_hand(start_hands, events, seat=0):
    """重建 seat 的手牌，逐出牌点产出 (14张手牌计数, 实际出牌str)。"""
    # start_hands[seat] 是 list[str]
    hand = {}
    for s in start_hands[seat]:
        hand[s] = hand.get(s, 0) + 1

    results = []
    for ev in events:
        t = ev["type"]
        if t == "tile_drawn" and ev["seat"] == seat and ev.get("tile"):
            hand[ev["tile"]] = hand.get(ev["tile"], 0) + 1
        elif t == "tile_discarded" and ev["seat"] == seat and ev.get("tile"):
            # 出牌前手牌是 14 张，记录决策点
            results.append((dict(hand), ev["tile"]))
            hand[ev["tile"]] = hand.get(ev["tile"], 0) - 1
            if hand[ev["tile"]] <= 0:
                del hand[ev["tile"]]
    return results


def hand_to_counts(hand_dict):
    counts = [0] * 34
    for s, c in hand_dict.items():
        counts[tile_from_str(s)] += c
    return counts


def main():
    better = 0
    same = 0
    worse = 0
    total = 0
    for fp in sorted(glob.glob("data/room_events/events_*.json")):
        ev = json.load(open(fp, encoding="utf-8"))
        for blk in ev["blocks"]:
            sh = blk.get("start_hands")
            if not isinstance(sh, list) or len(sh) < 4 or not all(sh):
                continue
            decisions = replay_seat0_hand(sh, blk.get("events", []), seat=0)
            for hand_dict, actual_tile in decisions:
                if sum(hand_dict.values()) != 14:
                    continue
                counts = hand_to_counts(hand_dict)
                actual_idx = tile_from_str(actual_tile)
                smart_idx = discard_decision(counts)
                s_actual = shanten_after_discard(counts, actual_idx)
                s_smart = shanten_after_discard(counts, smart_idx)
                total += 1
                if s_smart < s_actual:
                    better += 1
                elif s_smart == s_actual:
                    same += 1
                else:
                    worse += 1

    print(f"决策点总数: {total}")
    print(f"smart 更优(向听数更低): {better}")
    print(f"持平: {same}")
    print(f"smart 更差: {worse}")
    if total:
        print(f"smart 更优比例: {better / total * 100:.1f}%")


if __name__ == "__main__":
    main()
