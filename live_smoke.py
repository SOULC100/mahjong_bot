"""真机烟测编排：4 令牌 register+ready 开一轮 → 并发跑 4 个 smart_bot → 归档 + 汇总。

用法（在工作区根目录跑）：
    python live_smoke.py [--timeout 900] [--dry]

流程：
  1) data/tokens.txt（4 个测试房令牌）+ data/room.txt（房间 id 来源）
  2) 每个令牌 register + ready（v4/v5：finished 房 4 令牌各 ready 一次 = 开下一轮）
  3) 轮询房间状态直到 running / 出现 my_games（或超时）
  4) 为每个令牌起一个 smart_bot.py 进程（stdout 落 data/_smoke_bot_<i>.out）
  5) 等进程全部退出（或超时），拉 /api/test-rooms/{id}/games，跑 fetch_room_stats.py 归档
  6) 扫描每个 bot 日志的关键字（异常/错误/Traceback/张数守恒/409/429）+ 汇总写入
     data/_smoke_report.txt

配套：对局数据落地后用 verify_live.py 做规则/番型校验（吃摊 ≤2、抓打圈、番型对拍）。
只动测试房（kind=test），不碰正式锦标赛。
"""
import argparse
import io
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = "https://10.240.169.190:18080"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

REPORT = io.TextIOWrapper(open(os.path.join(ROOT, "data", "_smoke_report.txt"), "wb"),
                          encoding="utf-8")


def rp(*a):
    print(*a, file=REPORT, flush=True)
    print(*a, flush=True)


def api(method, path, token=None, body=None):
    req = urllib.request.Request(SERVER + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw or "{}")
        except ValueError:
            return e.code, {"_raw": raw[:200]}
    except Exception as e:
        return 0, {"_err": repr(e)}


def load_tokens():
    toks = [l.strip() for l in io.open(os.path.join(ROOT, "data", "tokens.txt"), encoding="utf-8") if l.strip()]
    room = io.open(os.path.join(ROOT, "data", "room.txt"), encoding="utf-8").read().strip()
    rid = room.split(":", 1)[1].strip() if ":" in room else room
    return toks, rid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900, help="等对局结束的最长秒数")
    ap.add_argument("--dry", action="store_true", help="只做 register/ready + 报告状态，不起 bot")
    args = ap.parse_args()

    toks, rid = load_tokens()
    rp("=== 真机烟测 %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
    rp("room=%s 令牌数=%d" % (rid, len(toks)))
    st, f = api("GET", "/portal/api/features")
    rp("features: %s %s" % (st, json.dumps(f, ensure_ascii=False)))

    tids = set()
    for i, tk in enumerate(toks):
        st, me = api("GET", "/api/me", tk)
        rp("[%d] /api/me %s tid=%s user=%s active=%s"
           % (i, st, me.get("tournament_id"), me.get("user_id"),
              len(me.get("active_games") or [])))
        if st != 200:
            rp("    令牌无效，终止")
            return 1
        tids.add(me.get("tournament_id"))
        for act in ("register", "ready"):
            st2, r = api("POST", "/api/tournaments/%s/%s" % (rid, act), tk)
            rp("[%d] %s -> %s %s" % (i, act, st2, json.dumps(r, ensure_ascii=False)[:160]))
        time.sleep(0.4)
    if len(tids) != 1 or rid not in tids:
        rp("!! 令牌绑定的房间不一致: %s（期望 %s）" % (tids, rid))

    deadline = time.time() + 90
    status = None
    while time.time() < deadline:
        st, t = api("GET", "/api/tournaments/%s" % rid, toks[0])
        status = t.get("status")
        n_games = len(t.get("my_games") or [])
        if status == "running" or n_games:
            rp("开赛: status=%s my_games=%d config=%s"
               % (status, n_games, json.dumps(t.get("config"), ensure_ascii=False)))
            break
        rp("等待开赛... status=%s ready_users=%s"
           % (status, t.get("ready_users", t.get("stage_ready_count"))))
        time.sleep(5)
    else:
        rp("!! 90s 内未开赛（status=%s）——可能其他人没 ready；先停" % status)
        return 2

    if args.dry:
        rp("--dry：不起 bot，结束")
        return 0

    procs = []
    for i, tk in enumerate(toks):
        out = open(os.path.join(ROOT, "data", "_smoke_bot_%d.out" % i), "wb")
        p = subprocess.Popen([sys.executable, "smart_bot.py", tk, str(i)],
                             cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
        procs.append((i, p, out))
        rp("起 bot %d pid=%d" % (i, p.pid))
        time.sleep(0.5)

    t0 = time.time()
    while any(p.poll() is None for _, p, _ in procs):
        if time.time() - t0 > args.timeout:
            rp("!! 超时 %ds，杀剩余进程" % args.timeout)
            for i, p, _ in procs:
                if p.poll() is None:
                    p.kill()
            break
        time.sleep(10)
        st, t = api("GET", "/api/tournaments/%s" % rid, toks[0])
        alive = sum(1 for _, p, _ in procs if p.poll() is None)
        rp("...%ds status=%s 存活 bot=%d" % (int(time.time() - t0), t.get("status"), alive))
    for i, p, out in procs:
        out.close()
        rp("bot %d 退出码=%s" % (i, p.returncode))

    st, g = api("GET", "/api/test-rooms/%s/games" % rid)
    games = (g.get("games") if isinstance(g, dict) else []) or []
    rp("\n房间 %s 局数=%d status=%s" % (rid, len(games), g.get("status") if isinstance(g, dict) else "?"))
    arch = os.path.join(ROOT, "data", "_smoke_fetch_%s_%d" % (rid, int(time.time())))
    subprocess.call([sys.executable, "fetch_room_stats.py", rid, arch], cwd=ROOT,
                    stdout=open(os.path.join(ROOT, "data", "_smoke_fetch.out"), "wb"),
                    stderr=subprocess.STDOUT)
    rp("归档目录: %s" % arch)

    pats = {
        "Traceback": re.compile(r"Traceback"),
        "线程异常": re.compile(r"线程异常退出"),
        "action 错误": re.compile(r"action 错误"),
        "409 拒绝": re.compile(r"409 拒绝"),
        "张数守恒异常": re.compile(r"张数守恒异常"),
        "429": re.compile(r"429"),
        "错误": re.compile(r"错误"),
    }
    rp("\n== 各 bot 日志扫描（data/smart_<i>.log） ==")
    for i in range(len(toks)):
        p = os.path.join(ROOT, "data", "smart_%d.log" % i)
        if not os.path.exists(p):
            rp("bot %d: 日志缺失 %s" % (i, p))
            continue
        s = io.open(p, encoding="utf-8", errors="replace").read()
        counts = {k: len(rx.findall(s)) for k, rx in pats.items()}
        hu = len(re.findall(r'"action": "hu"', s))
        ends = re.findall(r"本场结束 积分: (\[[^\]]*\])", s)
        rp("bot %d: 行数=%d 主动hu=%d 场次结束=%d 扫描=%s"
           % (i, s.count("\n"), hu, len(ends), counts))
        if ends:
            rp("        末场积分=%s" % ends[-1])
        for kw in ("Traceback", "线程异常", "action 错误"):
            for line in s.splitlines():
                if kw in line:
                    rp("        >> %s" % line[:200])
    rp("\n报告：data/_smoke_report.txt ｜ 归档：%s" % arch)
    rp("下一步：python verify_live.py \"%s\"" % arch)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        REPORT.flush()
