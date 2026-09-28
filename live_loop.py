"""live_loop.py — 自动续赛 driver：反复拉起 smart_bot 打完每一波，直到锦标赛关闭。

用法：python live_loop.py <token> <botid> [最大波数]
每波 = smart_bot 进程跑完当前 active_games 后退出 → 查状态 → 仍 open 就再拉下一波。
"""
import json
import os
import re
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
PENDING = os.path.join("data", "matches", "_pending")
RE_ROOM = re.compile(r"匹配成功 room=(\S+)")


def mark_pending(room, bot_id, log_path):
    """落待归档标记（collect_auto.py 扫）——本 driver 归档失败/被中断时的兜底。绝不抛异常。"""
    try:
        os.makedirs(PENDING, exist_ok=True)
        p = os.path.join(PENDING, "%s.json" % room)
        old = {}
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    old = json.load(f)
            except ValueError:
                old = {}
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"room_id": room,
                       "created_at": old.get("created_at") or now, "updated_at": now,
                       "source": "live_loop",
                       "sources": sorted(set((old.get("sources") or []) + ["live_loop"])),
                       "bot_id": bot_id,
                       "log_path": log_path or old.get("log_path"),
                       "token_file": "data/global_token.txt",
                       "status": "pending", "attempts": 0, "last_error": None}, f,
                      ensure_ascii=False, indent=1)
    except Exception as e:
        log("落待归档标记失败: %r" % (e,))


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
        # 本波打的房：从 bot 日志抽（auto 房每波一个新 room）→ 落兜底标记，归档失败也能被收集器收掉
        bot_id = "%s_%d" % (BOTID, wave)
        bot_log = "data/smart_%s.log" % bot_id
        try:
            txt = open(bot_log, encoding="utf-8", errors="replace").read()
            rooms = RE_ROOM.findall(txt)
            if rooms:
                log("本波入席 room=%s（%d 次匹配记录）" % (rooms[-1], len(rooms)))
                mark_pending(rooms[-1], bot_id, bot_log)
        except FileNotFoundError:
            log("本波日志缺失 %s，跳过落标记" % bot_log)
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
