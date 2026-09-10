"""等待测试房间全部对局结束（日志 + 服务端 API 双确认）。"""
import json
import ssl
import sys
import time
import urllib.request

ctx = ssl._create_unverified_context()
SERVER = "https://10.240.169.190:18080"
ROOM = sys.argv[1] if len(sys.argv) > 1 else None

if not ROOM:
    import re
    ROOM = re.search(r"room:\s*(t_\w+)", open("data/room.txt", encoding="utf-8").read()).group(1)


def get(path):
    req = urllib.request.Request(SERVER + path)
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read().decode())


start = time.time()
deadline = start + 900  # 15 min hard cap
checked_logs_at = 0
while time.time() < deadline:
    # 条件1: 4 个日志都「全部完成」
    logs_done = True
    for i in range(4):
        try:
            if "全部完成" not in open("data/smart_%d.log" % i, encoding="utf-8", errors="replace").read():
                logs_done = False
                break
        except FileNotFoundError:
            logs_done = False
            break
    if logs_done:
        print("DONE via logs, elapsed=%.0fs" % (time.time() - start))
        sys.exit(0)
    # 条件2: 服务端房间 status finished（若 bot 线程崩了日志永不完成也可收）
    try:
        gd = get("/api/test-rooms/%s/games" % ROOM)
        if gd.get("status") == "finished" and all(g["status"] == "finished" for g in gd.get("games", [])):
            el = time.time() - start
            print("DONE via server, elapsed=%.0fs" % el)
            for i in range(4):
                try:
                    done = "全部完成" in open("data/smart_%d.log" % i, encoding="utf-8", errors="replace").read()
                except FileNotFoundError:
                    done = False
                if not done:
                    print("  warning: smart_%d.log 未打印全部完成" % i)
            sys.exit(0)
        running = sum(1 for g in gd.get("games", []) if g["status"] != "finished")
        if int(time.time()) - checked_logs_at >= 30:
            print("...elapsed=%.0fs room=%s games_not_finished=%d" % (time.time() - start, gd.get("status"), running), flush=True)
            checked_logs_at = int(time.time())
    except Exception as e:
        if int(time.time()) - checked_logs_at >= 30:
            print("...poll err %r" % (e,), flush=True)
            checked_logs_at = int(time.time())
    time.sleep(8)

print("TIMEOUT waiting for room %s" % ROOM)
sys.exit(2)
