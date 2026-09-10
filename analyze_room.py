"""分析测试房间对局结果：胡牌局数、番型、积分。"""

import json
import ssl
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, ".")

ctx = ssl._create_unverified_context()


def get(path):
    req = urllib.request.Request("https://10.240.169.190:18080" + path)
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read().decode())


def main(room):
    games = get(f"/api/test-rooms/{room}/games")["games"]
    wins = 0
    draws = 0
    multipliers = Counter()
    winners = Counter()
    total_scores = [0, 0, 0, 0]
    for g in games:
        if g["status"] != "finished":
            print(f"batch {g['batch']}: {g['status']} (未结束)")
            continue
        b = g["batch"]
        try:
            ev = get(f"/api/test-rooms/{room}/games/{b}/events")
        except Exception as e:
            print(f"batch {b}: 拉取失败 {e}")
            continue
        for r in ev.get("rounds", []):
            w = r.get("winner", -1)
            m = r.get("multiplier", 0)
            scores = r.get("scores", [0, 0, 0, 0])
            if w >= 0:
                wins += 1
                winners[w] += 1
                multipliers[m] += 1
            else:
                draws += 1
            for i, s in enumerate(scores):
                total_scores[i] += s
        time.sleep(0.8)

    print(f"\n总对局: {len(games)}，胡牌: {wins} 局，流局: {draws} 局")
    print(f"番型分布: {dict(multipliers)}")
    print(f"胡牌座位分布: {dict(winners)}")
    print(f"各座位总积分: {total_scores}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "t_0329bd0195c8")
