"""live_loop.py — 自动续赛 driver：反复拉起 smart_bot 打完每一波，直到锦标赛关闭。

用法：python live_loop.py <token> <botid> [最大波数]
每波 = smart_bot 进程跑完当前 active_games 后退出 → 查状态 → 仍 open 就再拉下一波。
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request

SERVER = "https://10.240.169.190:18080"
TOKEN = sys.argv[1]
BOTID = sys.argv[2] if len(sys.argv) > 2 else "loop"
MAXWAVE = int(sys.argv[3]) if len(sys.argv) > 3 else 0  # 0=无限直到关
LOG = open("data/live_loop_%s.log" % BOTID, "a", encoding="utf-8")


def log(*a):
    print(*a, file=LOG, flush=True)


def api(method, path, body=None):
    req = urllib.request.Request(SERVER.rstrip("/") + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + TOKEN)
    ctx = ssl._create_unverified_context()
    for _ in range(6):
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2)
                continue
            raise
    raise RuntimeError("api failed")


def status():
    me = api("GET", "/api/me")
    tid = me.get("tournament_id") or ""
    if not tid:
        return "NO_TID", 0
    st = api("GET", "/api/tournaments/" + tid)
    return st.get("status"), len(me.get("active_games", []))


def main():
    log("=== live_loop start bot=%s token=%s ===" % (BOTID, TOKEN[:8]))
    wave = 0
    while True:
        st, nact = status()
        log("status=%s active_games=%d" % (st, nact))
        if st in ("void", "closed", "finished") and nact == 0:
            log("锦标赛 %s，终止" % st)
            break
        wave += 1
        log("--- 波 %d: 拉起 smart_bot ---" % wave)
        rc = subprocess.call([sys.executable, "smart_bot.py", TOKEN, "%s_%d" % (BOTID, wave)])
        log("smart_bot 退出 rc=%d" % rc)
        # 每波打完自动归档本波对局数据（独立目录，避免覆盖上一波）
        try:
            me = api("GET", "/api/me")
            tid = me.get("tournament_id") or ""
            if tid:
                log("归档本波 events -> data/fetch_%s_w%03d" % (tid, wave))
                subprocess.call([sys.executable, "fetch_room_stats.py", tid,
                                 "data/fetch_%s_w%03d" % (tid, wave)])
        except Exception as e:
            log("归档失败 %r" % e)
        if MAXWAVE and wave >= MAXWAVE:
            log("达到最大波数 %d，停" % MAXWAVE)
            break
        # 等一会儿让房间重排/他人 ready
        time.sleep(8)
    log("=== live_loop end ===")
    LOG.close()


if __name__ == "__main__":
    main()
