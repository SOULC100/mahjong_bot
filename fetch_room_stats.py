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
    missing = []

    for g in games:
        b = g["batch"]
        rnd = g.get("round")
        want_gid = g.get("game_id")
        st = g["status"]
        if st != "finished":
            print("  batch %d: %s (未结束，跳过)" % (b, st))
            continue
        ev = get("/api/test-rooms/%s/games/%d/events" % (room, b))
        got_gid = ev.get("game_id")
        # v4/v5 跨轮复用：每轮 batch 从 0 重号；免认证端点按 batch 只服当前轮，
        # 旧轮取不到（想留旧轮务必在该轮结束后、下一轮 open 前拉取，或用 owner 会话的
        # GET /portal/api/games/{id}/events 按 game_id 拉）。
        if want_gid and got_gid and want_gid != got_gid:
            print("  batch %d: 跳过——期望 %s，端点返回 %s（跨轮重号，旧轮不可得）"
                  % (b, want_gid, got_gid))
            missing.append(want_gid)
            continue
        fn = "events_r%s_b%d.json" % (rnd if rnd is not None else "x", b)
        with open(os.path.join(outdir, fn), "w", encoding="utf-8") as f:
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
        per_batch.append((rnd, b, bD, bT, bResp, bPeng, bChi))
        print("  round %s batch %d: D=%d T=%d resp=%d peng=%d chi=%d"
              % (rnd, b, bD, bT, bResp, bPeng, bChi))
        time.sleep(0.35)  # 测试房数据 API 限速 per-房间 5/s（v9 起），单房拉取留余量

    # 汇总（注意：只统计能取到的轮次；跨轮重号取不到的旧轮计入 missing）
    print("\n==== 事件汇总 ====")
    print("出牌 tile_discarded 总数 D =", D)
    print("出牌超时 timeout.discard T =", T)
    print("出牌超时率 T/D = %.1f%% (%d/%d)" % (100.0 * T / D, T, D) if D else "N/A")
    print("碰/吃窗口走满 timeout.response =", resp)
    print("peng 事件 =", peng, "| chi 事件 =", chi)
    if missing:
        print("取不到的旧轮场次 %d 个（跨轮 batch 重号）：%s" % (len(missing), missing[:6]))

    print("\n==== 局结果 ====")
    print("房间场次总数:", len(games), "| 本次可统计:", wins + draws,
          "| 胡牌:", wins, "局 | 流局:", draws, "局")
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
        "unavailable_old_rounds": missing,
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
