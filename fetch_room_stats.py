"""拉取测试房间赛后事件流并存档，统计出牌超时率/碰吃窗口/胡牌流局。

用法: python fetch_room_stats.py [room_id]
默认从 data/room.txt 读 room。事件存 data/fetch_<room>/events_<batch>.json。
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from collections import Counter

ctx = ssl._create_unverified_context()
SERVER = "https://10.240.169.190:18080"


def get(path, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(SERVER + path)
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            body = e.read().decode(errors="replace")
            if e.code == 429:
                time.sleep(0.6 * (i + 1))
                continue
            raise SystemExit("HTTP %s GET %s: %s" % (e.code, path, body[:200]))
        except Exception as e:
            last = e
            time.sleep(0.6)
    raise SystemExit("GET %s failed: %r" % (path, last))


def main(room, outdir=None):
    outdir = outdir or ("data/fetch_%s" % room)
    os.makedirs(outdir, exist_ok=True)

    # 1) 局列表
    gdata = get("/api/test-rooms/%s/games" % room)
    games = gdata.get("games", [])
    print("room:", room, "| status:", gdata.get("status"), "| 局数:", len(games))
    with open(os.path.join(outdir, "games.json"), "w", encoding="utf-8") as f:
        json.dump(gdata, f, ensure_ascii=False, indent=1)

    D = T = resp = peng = chi = 0          # 事件累加
    wins = draws = 0
    multipliers = Counter()
    winners = Counter()
    total_scores = [0, 0, 0, 0]
    per_batch = []

    for g in games:
        b = g["batch"]
        st = g["status"]
        if st != "finished":
            print("  batch %d: %s (未结束，跳过)" % (b, st))
            continue
        ev = get("/api/test-rooms/%s/games/%d/events" % (room, b))
        with open(os.path.join(outdir, "events_%d.json" % b), "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False)
        # 事件统计
        bD = bT = bResp = bPeng = bChi = 0
        for blk in ev.get("blocks", []):
            for e in blk.get("events", []):
                t = e.get("type")
                if t == "tile_discarded":
                    bD += 1
                elif t == "timeout":
                    k = (e.get("data") or {}).get("kind")
                    if k == "discard":
                        bT += 1
                    elif k == "response":
                        bResp += 1
                elif t == "peng":
                    bPeng += 1
                elif t == "chi":
                    bChi += 1
        D += bD; T += bT; resp += bResp; peng += bPeng; chi += bChi
        # 局结果统计
        for r in ev.get("rounds", []):
            w = r.get("winner", -1)
            m = r.get("multiplier", 0)
            sc = r.get("scores", [0, 0, 0, 0])
            if w >= 0:
                wins += 1
                winners[w] += 1
                multipliers[m] += 1
            else:
                draws += 1
            for i, s in enumerate(sc):
                total_scores[i] += s
        per_batch.append((b, bD, bT, bResp, bPeng, bChi))
        print("  batch %d: D=%d T=%d resp=%d peng=%d chi=%d" % (b, bD, bT, bResp, bPeng, bChi))
        time.sleep(0.35)  # 测试房数据 API 限速 per-房间 5/s（v9 起），单房拉取留余量

    # 汇总
    print("\n==== 事件汇总 ====")
    print("出牌 tile_discarded 总数 D =", D)
    print("出牌超时 timeout.discard T =", T)
    print("出牌超时率 T/D = %.1f%% (%d/%d)" % (100.0 * T / D, T, D) if D else "N/A")
    print("碰/吃窗口走满 timeout.response =", resp)
    print("peng 事件 =", peng, "| chi 事件 =", chi)

    print("\n==== 局结果 ====")
    print("总对局:", len(games), "| 胡牌:", wins, "局 | 流局:", draws, "局")
    print("番型分布:", dict(multipliers))
    print("胡牌座位分布:", dict(winners))
    print("各座位总积分:", total_scores)

    summary = {
        "room": room, "status": gdata.get("status"),
        "D": D, "T": T, "timeout_rate_pct": round(100.0 * T / D, 1) if D else None,
        "response_timeouts": resp, "peng": peng, "chi": chi,
        "games": len(games), "wins": wins, "draws": draws,
        "multipliers": dict(multipliers), "winners": dict(winners),
        "total_scores": total_scores, "per_batch": per_batch,
    }
    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\nsummary 写至", os.path.join(outdir, "summary.json"))


if __name__ == "__main__":
    r = sys.argv[1] if len(sys.argv) > 1 else None
    od = sys.argv[2] if len(sys.argv) > 2 else None
    if not r:
        m = re.search(r"room:\s*(t_\w+)", open("data/room.txt", encoding="utf-8").read())
        r = m.group(1)
    main(r, od)
