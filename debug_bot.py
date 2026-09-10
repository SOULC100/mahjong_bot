"""调试：轮询并 dump 快照关键字段（phase/turn/seat/waited_seat/responding_seats/last_discard/drawn_tile/god），不行动让服务器超时自打，观察阶段流转。"""
import json
import ssl
import sys
import time
import urllib.request

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVER = "https://10.240.169.190:18080"
TOKEN = sys.argv[1].strip()
TAG = sys.argv[2].strip() if len(sys.argv) > 2 else "0"
MAX_POLLS = int(sys.argv[3]) if len(sys.argv) > 3 else 80


def api(method, path, body=None):
    req = urllib.request.Request(SERVER.rstrip("/") + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + TOKEN)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(TAG, "HTTP", e.code, e.read().decode(errors="replace")[:200], flush=True)
        raise


def main():
    me = api("GET", "/api/me")
    tid = me["tournament_id"]
    api("POST", "/api/tournaments/%s/register" % tid)
    api("POST", "/api/tournaments/%s/ready" % tid)
    print(TAG, "registered", flush=True)
    while True:
        st = api("GET", "/api/tournaments/%s" % tid)
        if st.get("status") == "running":
            break
        if st.get("status") in ("void", "closed"):
            print(TAG, "终止", st.get("status"), flush=True)
            return
        time.sleep(1)
    gid = api("GET", "/api/me")["active_games"][0]["game_id"]
    print(TAG, "gid=", gid, flush=True)
    seq = 0
    last_phase = None
    for _ in range(MAX_POLLS):
        res = api("GET", "/api/games/%s/state?seq=%d" % (gid, seq))
        if res.get("finished"):
            print(TAG, "finished scores=", (res.get("snapshot") or {}).get("scores"), flush=True)
            return
        if res.get("pending"):
            time.sleep(0.3)
            continue
        snap = res.get("snapshot")
        if snap is None:
            for ev in res.get("events") or []:
                seq = ev.get("seq", seq)
            continue
        seq = res.get("seq", seq)
        phase = snap.get("phase")
        if phase != last_phase:
            last_phase = phase
            keys = {k: snap.get(k) for k in
                    ("phase", "turn", "seat", "waited_seat", "responding_seats",
                     "last_discard", "drawn_tile", "god", "hand_counts")}
            print(TAG, "阶段变化 ->", json.dumps(keys, ensure_ascii=False), flush=True)
        time.sleep(0.2)


if __name__ == "__main__":
    main()
