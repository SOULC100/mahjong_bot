"""live 排行监控：每 tick 打印锦标赛排行榜前几（含我们的 rank/总分）。"""
import json, ssl, sys, time, urllib.request

tok = sys.argv[1]
ME = "u_7f511bb839be"
ctx = ssl._create_unverified_context()


def api(path):
    req = urllib.request.Request("https://10.240.169.190:18080" + path)
    req.add_header("Authorization", "Bearer " + tok)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=12, context=ctx).read().decode())
    except Exception:
        return {}


def main():
    me = api("/api/me")
    tid = me.get("tournament_id") or ""
    st = api("/api/tournaments/%s" % tid) if tid else {}
    rank = st.get("ranking") or []
    me_user = me.get("user_id") or ME
    mine = next((r for r in rank if r.get("user_id") == me_user), None)
    others = [r for r in rank if r.get("user_id") != me_user]
    s = "[%s] %s" % (time.strftime("%H:%M:%S"), st.get("status", "?"))
    if mine:
        s += " | 我=rank%d total%+.0f 番%d god%d gp%d" % (
            mine.get("rank"), mine.get("total_score", 0), mine.get("place_points", 0),
            mine.get("god_count", 0), mine.get("games_played", 0))
    top = sorted(rank, key=lambda r: -(r.get("total_score") or 0))[:3]
    s += " | top3:" + ",".join("rank%d=%+.0f" % (r.get("rank"), r.get("total_score") or 0) for r in top)
    print(s, flush=True)


if __name__ == "__main__":
    main()
