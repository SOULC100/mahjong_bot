"""调试用最小 Bot —— 基于官方最小示例，增加手牌/allowed_actions 日志。

用法：python bot.py <令牌> <编号>
用于跑一局真实对局，观察牌编码与协议细节。
"""
import json
import ssl
import sys
import time
import urllib.request

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVER = "https://10.240.169.190:18080"
TOKEN = sys.argv[1]
BOT_ID = sys.argv[2] if len(sys.argv) > 2 else "x"
LOG = open("data/bot_%s.log" % BOT_ID, "w", encoding="utf-8")


def log(*a):
    print(*a, file=LOG, flush=True)


class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body


def api(method, path, body=None):
    req = urllib.request.Request(
        SERVER.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + TOKEN)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(2)
            return api(method, path, body)
        raise ApiError(e.code, e.read().decode(errors="replace"))


log("=== bot %s 启动 token=%s... ===" % (BOT_ID, TOKEN[:8]))

me = api("GET", "/api/me")
tid = me["tournament_id"] or (sys.argv[2] if len(sys.argv) > 2 else "")
log("me:", json.dumps(me, ensure_ascii=False))
if not tid:
    log("令牌未绑定锦标赛")
    sys.exit(1)
log("锦标赛:", tid)

api("POST", "/api/tournaments/%s/register" % tid)
api("POST", "/api/tournaments/%s/ready" % tid)
log("已报名+到位")

while True:
    st = api("GET", "/api/tournaments/%s" % tid)
    log("status:", st.get("status"))
    if st.get("status") == "running":
        break
    if st.get("status") in ("void", "closed"):
        log("终止:", st.get("status"))
        sys.exit(1)
    time.sleep(1)
log("开赛")


def play(gid):
    seq = 0
    while True:
        res = api("GET", "/api/games/%s/state?seq=%d" % (gid, seq))
        if res.get("finished"):
            log("本场结束, 积分:", (res.get("snapshot") or {}).get("scores"))
            log("完整结果:", json.dumps(res, ensure_ascii=False)[:2000])
            return
        if res.get("pending"):
            continue
        snap = res.get("snapshot")
        if snap is None:
            for ev in res.get("events") or []:
                seq = ev.get("seq", seq)
            snap = api("GET", "/api/games/%s/state?seq=0" % gid).get("snapshot")
        else:
            seq = res.get("seq", seq)
        allowed = snap.get("allowed_actions") or []
        hand = snap.get("hand") or snap.get("tiles") or "?"
        log("hand:", json.dumps(hand, ensure_ascii=False),
            "allowed:", json.dumps(allowed, ensure_ascii=False))
        if not allowed:
            continue
        if "hu:" in allowed or any(a.startswith("hu") for a in allowed):
            act = {"action": "hu", "tile": ""}
        else:
            d = [a.partition(":")[2] for a in allowed if a.startswith("discard")]
            act = {"action": "discard", "tile": d[0]} if d else {"action": "pass", "tile": ""}
        log("提交:", json.dumps(act, ensure_ascii=False))
        try:
            api("POST", "/api/games/%s/action" % gid, act)
        except ApiError as e:
            if e.status != 409:
                log("action 错误:", e.status, e.body[:300])
                raise
        seq = 0


for g in api("GET", "/api/me")["active_games"]:
    log("对局:", g.get("game_id"))
    play(g["game_id"])
log("全部完成")
LOG.close()
