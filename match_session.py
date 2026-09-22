"""自由对战（auto 房）一场到底：入席 → 打 → 归档 → 赛后统计。

需求来源：每一场自由匹配的**对局信息、日志、赛后统计**都要留档（可跨场累积复盘）。

用法：
    python match_session.py                    # 一场：匹配 → 打 → 归档 → 统计
    python match_session.py --sessions 3       # 连打三场（每场一个新 auto 房）
    python match_session.py --join-only        # 只入席不落座（自测 token/开关用）
    python match_session.py --archive ROOM     # 只给已打完的房间补档（不重打）
    python match_session.py --archive ROOM --log data/smart_gm.log   # 补档并做 chi 对拍

产物（每场一个目录，`data/` 已被 .gitignore 忽略，令牌/日志不进版本库）：

    data/matches/<room_id>/
      session.json      本场元数据：房规、起止时间、token 指纹（**不存明文**）、退出码、房间快照
      bot.log           bot 完整日志（data/smart_<bot_id>.log 的副本）
      bot.stdout.log    子进程 stdout/stderr（bot 自身日志走 bot.log）
      games.json        场次列表（batch/game_id/round/status）
      events/b<N>.json  每场完整事件流（含四家手牌、逐局结果）—— **房间关停后取不到，必须打完立刻拉**
      stats.json        赛后统计（结构化，供 match_stats.py 汇总）
      stats.md          赛后统计（人读）
    data/matches/index.tsv   全场次索引（一行一场，追加；match_stats.py 直接读它）

关键时序（踩过的坑）：
- auto 房整场打完（finished 约 60s 宽限）自动关停，此后玩家 API 一律 404；免认证数据端点
  （/api/test-rooms/{room}/games[/{batch}/events]）也会随之消失 → **归档紧跟 bot 退出执行**。
- 该端点 per-room 限速 5/s → 每场之间 sleep 0.25s，429 退避重试。
- 令牌走 `@data/global_token.txt`（smart_bot 的 @文件 形式），不进 argv/进程列表。
"""

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = "https://10.240.169.190:18080"
CTX = ssl._create_unverified_context()
MATCHES = os.path.join(ROOT, "data", "matches")
INDEX = os.path.join(MATCHES, "index.tsv")

# 日志行解析（与 smart_bot.play() 的日志格式绑定；改格式要同步这里）
RE_SUBMIT = re.compile(r'提交: (\{.*?\}) phase=')
RE_REJECT = re.compile(r'409 拒绝: (\S+) (\{.*?\}) \{')
RE_SCORE = re.compile(r'本场结束 积分: (\[[^\]]*\])')
RE_MATCH = re.compile(r'匹配成功 room=\S+ round_no=\S+ config=(\{.*?\})\s*$', re.M)


# ---------------------------------------------------------------- HTTP

def api(method, path, token=None, body=None, tries=6, quiet=False):
    """返回 (status, payload)。429/网络抖动退避重试；4xx 原样返回给调用方判型。"""
    req = urllib.request.Request(
        SERVER + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    last = None
    for i in range(tries):
        try:
            r = urllib.request.urlopen(req, context=CTX, timeout=35)
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            last = (e.code, payload)
            if e.code == 429 or e.code >= 500:
                time.sleep(0.4 * (i + 1))
                continue
            return last
        except Exception as e:                      # 网络抖动
            last = (0, repr(e))
            time.sleep(0.5 * (i + 1))
    if not quiet:
        print("  ! 请求重试耗尽 %s %s -> %s" % (method, path, str(last)[:120]))
    return last or (0, "no attempt")


def read_token(path):
    """读全局令牌并做形状校验；只回指纹，绝不打印明文。"""
    with open(path, encoding="utf-8") as f:
        tok = f.read().strip()
    if not tok:
        raise SystemExit("令牌文件为空：%s（门户「我的 AI 身份」取全局令牌）" % path)
    return tok


def fingerprint(tok):
    return hashlib.sha256(tok.encode()).hexdigest()[:8]


# ---------------------------------------------------------------- 入席

def join(token, m=None, r=None, deadline_s=600):
    """POST /api/match 入席；等待类错误（404/409/429）退避重试到 deadline。返回 (room, config, round_no)。"""
    body = None
    if m is not None or r is not None:
        # v15：显式上限 < 服务默认（M=10/Rounds=8）→ 永久 404，先本地拦掉
        if (m is not None and m < 10) or (r is not None and r < 8):
            raise SystemExit("--m/--r 低于服务默认 M=10/Rounds=8（v15）→ 必然永久 404")
        body = {}
        if m is not None:
            body["M"] = m
        if r is not None:
            body["Rounds"] = r
    t0 = time.time()
    attempt = 0
    while time.time() - t0 < deadline_s:
        attempt += 1
        st, payload = api("POST", "/api/match", token, body, tries=1)
        code = (payload or {}).get("code") if isinstance(payload, dict) else ""
        if st == 200 and isinstance(payload, dict) and payload.get("room_id"):
            return payload["room_id"], payload.get("config") or {}, payload.get("round_no")
        if code in ("FEATURE_DISABLED", "PORTAL_BINDING_REQUIRED", "TOKEN_NOT_SCOPED"):
            raise SystemExit("入席被永久拒绝（%s %s）：%s" % (st, code, payload))
        if code == "NO_ROOM_AVAILABLE" and body is not None:
            raise SystemExit("显式上限过低导致 404 NO_ROOM_AVAILABLE（永久条件）")
        wait = min(3.0 * attempt, 20.0)
        print("  匹配暂不可用（%s %s）→ %.0fs 后重试 #%d" % (st, code or payload, wait, attempt))
        time.sleep(wait)
    raise SystemExit("匹配重试超时（%.0fs）" % deadline_s)


# ---------------------------------------------------------------- 打

def run_bot(bot_id, token_file, max_wait_s, log_path):
    """起 smart_bot 子进程（令牌走 @文件，不进 argv）。返回 (exit_code, 耗时秒, 是否超时被杀)。"""
    out = open(log_path, "w", encoding="utf-8")
    cmd = [sys.executable, "smart_bot.py", "@" + os.path.relpath(token_file, ROOT).replace("\\", "/"),
           bot_id]
    print("  起 bot: %s" % " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    t0 = time.time()
    killed = False
    while proc.poll() is None:
        time.sleep(5)
        if max_wait_s and time.time() - t0 > max_wait_s:
            print("  ! 超过 --max-wait %.0f 分钟，结束本场" % (max_wait_s / 60.0))
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            killed = True
            break
    out.close()
    return proc.returncode, time.time() - t0, killed


# ---------------------------------------------------------------- 归档

def room_snapshot(token, room):
    st, payload = api("GET", "/api/tournaments/%s" % room, token, tries=3, quiet=True)
    if not isinstance(payload, dict):
        return {"status": st, "body": str(payload)[:200]}
    keep = ("status", "config", "my_games", "ranking", "voided", "stage")
    return {k: payload.get(k) for k in keep if k in payload} or {"status": st}


def fetch_events(room, outdir):
    """拉 /api/test-rooms/{room}/games 与每场事件流 → 落盘。返回 (games, 取到数, 失败说明)。"""
    st, payload = api("GET", "/api/test-rooms/%s/games" % room, tries=3, quiet=True)
    games = payload.get("games") if isinstance(payload, dict) else None
    if not games:
        return [], 0, "games 列表不可用（HTTP %s / %s）" % (st, str(payload)[:120])
    with open(os.path.join(outdir, "games.json"), "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False, indent=1)
    evdir = os.path.join(outdir, "events")
    os.makedirs(evdir, exist_ok=True)
    ok, fail = 0, []
    for item in sorted(games, key=lambda x: x.get("batch", 0)):
        batch = item.get("batch")
        st, ev = api("GET", "/api/test-rooms/%s/games/%s/events" % (room, batch), tries=4, quiet=True)
        time.sleep(0.25)                       # per-room 限速 5/s
        if st == 200 and isinstance(ev, dict):
            with open(os.path.join(evdir, "b%s.json" % batch), "w", encoding="utf-8") as f:
                json.dump(ev, f, ensure_ascii=False)
            ok += 1
        else:
            fail.append("b%s:%s" % (batch, st))
    return games, ok, ("; ".join(fail) if fail else "")


# ---------------------------------------------------------------- 统计

def trip(obj):
    """chi 动作 → 规范化三张牌。日志的 tiles 是**两张手牌**（要补 tile），事件流 data.tiles **已含弃牌**。"""
    ts = list(obj.get("tiles") or [])
    if len(ts) < 3:
        ts = ts + [obj.get("tile") or ""]
    return tuple(sorted(t for t in ts if t))


def parse_bot_log(path):
    """解析 bot 日志：提交动作、409、异常、每场积分、chi 提交明细。文件不存在返回 None。"""
    if not path or not os.path.exists(path):
        return None
    txt = open(path, encoding="utf-8", errors="replace").read()
    subs = collections.Counter()
    chi_submitted = []
    for m in RE_SUBMIT.findall(txt):
        try:
            act = json.loads(m)
        except ValueError:
            subs["?"] += 1
            continue
        subs[act.get("action", "?")] += 1
        if act.get("action") == "chi":
            chi_submitted.append(trip(act))
    rejects = collections.Counter()
    rej_chi = []
    for line in txt.splitlines():
        m = RE_REJECT.search(line)
        if not m:
            continue
        code = m.group(1)
        rejects[code] += 1
        try:
            act = json.loads(m.group(2))
        except ValueError:
            continue
        if act.get("action") == "chi":
            rej_chi.append(trip(act))
    scores = []
    for m in RE_SCORE.findall(txt):
        try:
            scores.append(json.loads(m))
        except ValueError:
            pass
    # 房规兜底：房间关停后 /api/tournaments/{room} 一律 404，补档时只能从日志的匹配行恢复
    cfg_from_log = None
    m = RE_MATCH.search(txt)
    if m:
        try:
            cfg_from_log = json.loads(m.group(1))
        except ValueError:
            cfg_from_log = None
    return {
        "path": os.path.relpath(path, ROOT),
        "lines": txt.count("\n") + 1,
        "submissions": dict(subs),
        "chi_submitted": chi_submitted,
        "rejects": dict(rejects),
        "rejected_chi": rej_chi,
        "tracebacks": txt.count("Traceback"),
        "conservation_errors": txt.count("张数守恒异常"),
        "rate_limited": len(re.findall(r"\b429\b", txt)),
        "settled_waits": txt.count("phase=settled"),
        "per_game_scores": scores,
        "config_from_log": cfg_from_log,
    }


def analyze_events(evdir, uid):
    """解析事件流：我的座位/得分/名次、逐局结果、超时、副露、对局信息（四家席位）、时间范围。"""
    out = {"games": [], "rounds_total": 0, "my_hu": 0, "draws": 0, "others_hu": 0,
           "fan_hist": {}, "detail_hist": {}, "my_claims": collections.Counter(),
           "timeout_discard": 0, "timeout_response": 0, "timeout_by_kind": collections.Counter(),
           "chi_events": collections.Counter(), "per_round_chi_max": 0,
           "score_sum_check": 0, "ts_min": None, "ts_max": None, "my_hu_rounds": []}
    if not os.path.isdir(evdir):
        return out
    for fn in sorted(os.listdir(evdir), key=lambda x: int(re.findall(r"\d+", x)[0]) if re.findall(r"\d+", x) else 0):
        ev = json.load(open(os.path.join(evdir, fn), encoding="utf-8"))
        seats = ev.get("seats") or []
        mine = [i for i, s in enumerate(seats) if s.get("user_id") == uid]
        if not mine:
            continue
        me = mine[0]
        rounds = ev.get("rounds") or []
        # 四家净分（每场）→ 我的净分与名次（并列按同分同名次）
        totals = [sum(int((r.get("scores") or [0, 0, 0, 0])[i]) for r in rounds) for i in range(4)]
        my_score = totals[me]
        rank = 1 + sum(1 for i, t in enumerate(totals) if i != me and t > my_score)
        for r in rounds:
            out["score_sum_check"] += sum(int(x) for x in (r.get("scores") or []))
        out["games"].append({"batch": ev.get("batch"), "game_id": ev.get("game_id"),
                             "seat": me, "rounds": len(rounds), "my_score": my_score,
                             "rank": rank, "all_scores": totals,
                             "round_scores": [int((r.get("scores") or [0, 0, 0, 0])[me]) for r in rounds],
                             "seats": seats})
        per_round = collections.Counter()
        for blk in ev.get("blocks") or []:
            rno = blk.get("round_no")
            for e in blk.get("events") or []:
                t, seat = e.get("type"), e.get("seat")
                d = e.get("data") or {}
                ts = e.get("ts")
                if isinstance(ts, int):
                    out["ts_min"] = ts if out["ts_min"] is None else min(out["ts_min"], ts)
                    out["ts_max"] = ts if out["ts_max"] is None else max(out["ts_max"], ts)
                if t == "round_ended":
                    won = (seat == me) and not d.get("draw")
                    if d.get("draw"):
                        out["draws"] += 1
                    elif won:
                        out["my_hu"] += 1
                        fan = d.get("fan")
                        out["fan_hist"][str(fan)] = out["fan_hist"].get(str(fan), 0) + 1
                        key = "+".join(d.get("detail") or []) or "-"
                        out["detail_hist"][key] = out["detail_hist"].get(key, 0) + 1
                        out["my_hu_rounds"].append({"batch": ev.get("batch"), "round_no": d.get("round_no"),
                                                    "fan": fan, "detail": d.get("detail"),
                                                    "scores": d.get("scores")})
                    else:
                        out["others_hu"] += 1
                    out["rounds_total"] += 1
                elif seat == me and t in ("chi", "peng", "gang", "hu"):
                    out["my_claims"][t] += 1
                    if t == "chi":
                        out["chi_events"][trip({"tiles": d.get("tiles"), "tile": e.get("tile")})] += 1
                        per_round[rno] += 1
                elif seat == me and t == "timeout":
                    out["timeout_by_kind"]["%s/%s" % (d.get("kind"), d.get("window"))] += 1
                    if d.get("kind") == "discard":
                        out["timeout_discard"] += 1
                    else:
                        out["timeout_response"] += 1
        if per_round:
            out["per_round_chi_max"] = max(out["per_round_chi_max"], max(per_round.values()))
    return out


def build_stats(room, meta, games, log_info, ev):
    """把元数据 + 日志 + 事件流汇成 stats dict（结构化，供汇总与人读 md 共用）。"""
    cfg = meta.get("config") or (log_info or {}).get("config_from_log") or {}
    n_games = len(ev["games"])
    total_rounds = ev["rounds_total"]
    submits = (log_info or {}).get("submissions", {})
    # 时间兜底：补档时房间已关、runner 没记时间 → 用事件流 ts（对局权威时间）
    ev_from = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev["ts_min"])) if ev["ts_min"] else None
    ev_to = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev["ts_max"])) if ev["ts_max"] else None
    parity = None
    if log_info is not None:
        # 日志每次 chi 提交 = tile + 两张手牌（三张）；扣掉被 409 拒的，就是服务端该落子的多重集
        expect = collections.Counter(log_info.get("chi_submitted") or [])
        for r in log_info.get("rejected_chi", []):
            expect[r] -= 1
        expect = +expect
        got = collections.Counter(ev["chi_events"])
        parity = {"submitted": len(log_info.get("chi_submitted") or []),
                  "rejected": len(log_info.get("rejected_chi", [])),
                  "expected": sum(expect.values()), "matched": sum((expect & got).values()),
                  "missing": {"|".join(k): v for k, v in (expect - got).items()},
                  "extra": {"|".join(k): v for k, v in (got - expect).items()}}
        parity["ok"] = not parity["missing"] and not parity["extra"]
    stat = {
        "room_id": room,
        "kind": cfg.get("Kind") or meta.get("kind"),
        "config": cfg,
        "started_at": meta.get("started_at") or ev_from,
        "ended_at": meta.get("ended_at") or ev_to,
        "duration_s": meta.get("duration_s") or ((ev["ts_max"] - ev["ts_min"]) if ev["ts_min"] else None),
        "game_time": {"from": ev_from, "to": ev_to,
                      "span_s": (ev["ts_max"] - ev["ts_min"]) if ev["ts_min"] else None},
        "bot_id": meta.get("bot_id"),
        "token_fingerprint": meta.get("token_fingerprint"),
        "user_id": meta.get("user_id"),
        "bot_exit_code": meta.get("exit_code"),
        "bot_killed": meta.get("killed", False),
        "backfilled": meta.get("backfilled", False),
        "bot": log_info,
        "events": {"games_in_list": len(games), "games_analyzed": n_games,
                   "fetch_failures": meta.get("events_failures") or ""},
        "me": {"seats": sorted({g["seat"] for g in ev["games"]}),
               "net_score": sum(g["my_score"] for g in ev["games"]),
               "per_game": ev["games"],
               "games_positive": sum(1 for g in ev["games"] if g["my_score"] > 0),
               "games_rank1": sum(1 for g in ev["games"] if g.get("rank") == 1),
               "avg_rank": round(sum(g.get("rank", 4) for g in ev["games"]) / n_games, 2) if n_games else None},
        "rounds": {"total": total_rounds, "my_hu": ev["my_hu"],
                   "my_hu_rate": round(ev["my_hu"] / total_rounds, 4) if total_rounds else None,
                   "draws": ev["draws"], "others_hu": ev["others_hu"],
                   "fan_hist": ev["fan_hist"], "detail_hist": ev["detail_hist"],
                   "my_hu_rounds": ev["my_hu_rounds"],
                   "avg_fan": round(sum(int(k) * v for k, v in ev["fan_hist"].items())
                                    / max(1, ev["my_hu"]), 3) if ev["my_hu"] else None},
        "claims": {"mine": dict(ev["my_claims"]), "chi_events": sum(ev["chi_events"].values()),
                   "per_round_chi_max": ev["per_round_chi_max"],
                   "v25_chi_le_2_ok": ev["per_round_chi_max"] <= 2},
        "timeouts": {"discard": ev["timeout_discard"], "response": ev["timeout_response"],
                     "by_kind": dict(ev["timeout_by_kind"]),
                     "discard_rate": round(ev["timeout_discard"] / submits.get("discard", 1), 4)
                     if submits.get("discard") else None},
        "verify": {"chi_tiles_parity": parity},
        "zero_sum_ok": ev["score_sum_check"] == 0,
    }
    return stat


# ---------------------------------------------------------------- 落盘

def stats_markdown(stat):
    me, rd, cl, to = stat["me"], stat["rounds"], stat["claims"], stat["timeouts"]
    v = stat["verify"]["chi_tiles_parity"] or {}
    lines = [
        "# 自由对战赛后统计 —— %s" % stat["room_id"],
        "",
        "| 项 | 值 |",
        "|----|----|",
        "| 房规 | M=%s / Rounds=%s / BaseScore=%s / YouCaiBiKao=%s |"
        % ((stat["config"] or {}).get("M"), (stat["config"] or {}).get("Rounds"),
           (stat["config"] or {}).get("BaseScore"), (stat["config"] or {}).get("YouCaiBiKao")),
        "| 起止 | %s → %s（%.1f 分钟；对局时间 %s → %s） |"
        % (stat["started_at"], stat["ended_at"], (stat["duration_s"] or 0) / 60.0,
           (stat.get("game_time") or {}).get("from"), (stat.get("game_time") or {}).get("to")),
        "| bot | id=%s exit=%s%s%s |" % (stat["bot_id"], stat["bot_exit_code"],
                                        "（超时被杀）" if stat["bot_killed"] else "",
                                        "（补档）" if stat.get("backfilled") else ""),
        "| 令牌指纹 | %s（明文不落盘） |" % stat["token_fingerprint"],
        "| 我的座位 | %s（每场重洗） |" % me["seats"],
        "| **净分** | **%+d**（%d 场，正分 %d 场、场冠军 %d 次、平均名次 %s） |"
        % (me["net_score"], len(me["per_game"]), me["games_positive"], me["games_rank1"], me["avg_rank"]),
        "| 局数 | %d 局：我胡 %d（%.1f%%）、他人胡 %d、流局 %d |"
        % (rd["total"], rd["my_hu"], 100 * (rd["my_hu_rate"] or 0), rd["others_hu"], rd["draws"]),
        "| 番型（我） | %s；场均番 %s |"
        % (", ".join("%s番×%d" % (k, n) for k, n in sorted(rd["fan_hist"].items())) or "-",
           rd["avg_fan"]),
        "| 番型明细（我） | %s |" % (", ".join("%s×%d" % (k, n) for k, n in rd["detail_hist"].items()) or "-"),
        "| 我的副露 | %s |" % (", ".join("%s=%d" % (k, n) for k, n in sorted(cl["mine"].items())) or "-"),
        "| 吃摊 ≤2（v25） | %s（单局最多 %d 摊） |" % ("✅" if cl["v25_chi_le_2_ok"] else "❌", cl["per_round_chi_max"]),
        "| 出牌超时 | %d 次（%s）；响应窗口走满 %d 次 |"
        % (to["discard"], ("%.2f%%" % (100 * to["discard_rate"])) if to["discard_rate"] is not None else "n/a",
           to["response"]),
        "| **chi tiles 对拍** | %s 提交 %s / 被拒 %s → 期望 %s，事件流命中 %s |"
        % ("✅" if v.get("ok") else "❌/未做", v.get("submitted"), v.get("rejected"),
           v.get("expected"), v.get("matched")),
        "| 日志异常 | Traceback %s、守恒异常 %s、429 %s、409 %s |"
        % (stat["bot"]["tracebacks"] if stat["bot"] else "-",
           stat["bot"]["conservation_errors"] if stat["bot"] else "-",
           stat["bot"]["rate_limited"] if stat["bot"] else "-",
           sum((stat["bot"]["rejects"] or {}).values()) if stat["bot"] else "-"),
        "| 零和校验 | %s |" % ("✅ 各场四家和恒 0" if stat["zero_sum_ok"] else "❌"),
        "| 事件流 | 列表 %s 场 / 解析 %s 场 %s |"
        % (stat["events"]["games_in_list"], stat["events"]["games_analyzed"],
           ("（缺失：%s）" % stat["events"]["fetch_failures"]) if stat["events"]["fetch_failures"] else ""),
        "",
        "## 每场明细",
        "",
        "| batch | game_id | 我的座位 | 局数 | 四家净分（我加粗） | 我的净分 | 名次 |",
        "|---|---|---|---|---|---|---|",
    ]
    for g in me["per_game"]:
        sc = g.get("all_scores") or []
        marks = ["**%+d**" % v if i == g["seat"] else "%+d" % v for i, v in enumerate(sc)]
        lines.append("| %s | %s | %s | %s | %s | %+d | %s |"
                     % (g["batch"], g["game_id"], g["seat"], g["rounds"],
                        " / ".join(marks) or "-", g["my_score"], g.get("rank", "-")))
    hu = rd.get("my_hu_rounds") or []
    if hu:
        lines += ["", "## 我的胡牌明细", "",
                  "| 场次 | 局 | 番 | 番型 | 四家得分 |", "|---|---|---|---|---|"]
        for h in hu:
            lines.append("| %s | %s | %s | %s | %s |"
                         % (h.get("batch"), h.get("round_no"), h.get("fan"),
                            "+".join(h.get("detail") or []) or "-",
                            " / ".join("%+d" % int(x) for x in (h.get("scores") or []))))
    lines += ["", "日志：`bot.log`（完整 bot 日志）、`bot.stdout.log`；事件流：`events/`；结构化：`stats.json`",
              "（对局信息含四家席位与逐局结果，见 `stats.json` 的 `me.per_game[].seats` 与 `events/`）", ""]
    return "\n".join(lines)


def finalize(room, outdir, meta, token, uid=None):
    """归档（会话元数据 + 房间快照 + 事件流）并产出 stats.json / stats.md / index 行。"""
    games, ok, fail = fetch_events(room, outdir)
    meta["events_failures"] = fail
    meta["events_fetched"] = ok
    meta["end_snapshot"] = room_snapshot(token, room) if token else None
    if not uid and token:
        st, me = api("GET", "/api/me", token, tries=3, quiet=True)
        uid = (me or {}).get("user_id") if isinstance(me, dict) else None
    meta["user_id"] = uid
    with open(os.path.join(outdir, "session.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    log_info = parse_bot_log(meta.get("log_path") or "")
    ev = analyze_events(os.path.join(outdir, "events"), uid)
    stat = build_stats(room, meta, games, log_info, ev)
    with open(os.path.join(outdir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stat, f, ensure_ascii=False, indent=1)
    with open(os.path.join(outdir, "stats.md"), "w", encoding="utf-8") as f:
        f.write(stats_markdown(stat))
    append_index(stat)
    return stat


def append_index(stat):
    """追加一行到 data/matches/index.tsv（同 room 已存在则替换该行，便于补档重跑）。"""
    v = stat["verify"]["chi_tiles_parity"] or {}
    row = [stat["room_id"], stat["started_at"] or "", stat["ended_at"] or "",
           "%.0f" % (stat["duration_s"] or 0), str((stat["config"] or {}).get("M") or ""),
           str((stat["config"] or {}).get("Rounds") or ""),
           str(len(stat["me"]["per_game"])), str(stat["rounds"]["total"]),
           str(stat["rounds"]["my_hu"]), "%+.0f" % stat["me"]["net_score"],
           "1" if v.get("ok") else "0", str(stat["timeouts"]["discard"]),
           str(stat["bot_exit_code"] if stat["bot_exit_code"] is not None else "")]
    header = ["room_id", "started_at", "ended_at", "duration_s", "M", "Rounds", "games", "rounds",
              "my_hu", "my_net", "chi_parity_ok", "discard_timeouts", "exit_code"]
    os.makedirs(MATCHES, exist_ok=True)
    rows = []
    if os.path.exists(INDEX):
        rows = [l.rstrip("\n").split("\t") for l in open(INDEX, encoding="utf-8")
                if l.strip() and not l.startswith("room_id")]
    rows = [r for r in rows if r and r[0] != stat["room_id"]]
    rows.append(row)
    rows.sort(key=lambda r: r[1] or "")
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")


# ---------------------------------------------------------------- 主流程

def session_once(args, token, meta_common):
    """一场：入席 → 打 → 归档。返回 stats dict。"""
    room, config, round_no = join(token, args.m, args.r)
    print("入席 room=%s round_no=%s M=%s Rounds=%s（kind=%s）"
          % (room, round_no, config.get("M"), config.get("Rounds"), config.get("Kind")))
    outdir = os.path.join(MATCHES, room)
    os.makedirs(outdir, exist_ok=True)
    bot_id = args.bot_id or ("gm-%s" % time.strftime("%Y%m%d-%H%M%S"))
    log_src = os.path.join(ROOT, "data", "smart_%s.log" % bot_id)
    meta = dict(meta_common)
    meta.update({"room_id": room, "config": config, "round_no": round_no,
                 "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "bot_id": bot_id, "join_snapshot": room_snapshot(token, room),
                 "log_path": os.path.relpath(log_src, ROOT)})
    if args.join_only:
        meta["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta["duration_s"] = 0
        meta["exit_code"] = None
        with open(os.path.join(outdir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        print("--join-only：已入席并归档 session.json（未落座对局）")
        return None
    t0 = time.time()
    code, dur, killed = run_bot(bot_id, args.token_file, args.max_wait * 60, os.path.join(outdir, "bot.stdout.log"))
    meta.update({"ended_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "duration_s": round(time.time() - t0, 1), "exit_code": code, "killed": killed})
    print("bot 退出 code=%s，用时 %.1f 分钟 → 立刻归档事件流" % (code, (time.time() - t0) / 60.0))
    if os.path.exists(log_src):
        shutil.copy2(log_src, os.path.join(outdir, "bot.log"))
    stat = finalize(room, outdir, meta, token)
    print("归档完成：%s" % os.path.relpath(outdir, ROOT))
    return stat


def main():
    ap = argparse.ArgumentParser(description="自由对战一场到底：入席 → 打 → 归档 → 赛后统计")
    ap.add_argument("--token-file", default=os.path.join("data", "global_token.txt"),
                    help="全局令牌文件（默认 data/global_token.txt；门户「我的 AI 身份」取）")
    ap.add_argument("--sessions", type=int, default=1, help="连打几场（每场一个新 auto 房）")
    ap.add_argument("--m", type=int, default=None, help="声明可承受上限 M（须 ≥10）")
    ap.add_argument("--r", type=int, default=None, help="声明可承受上限 Rounds（须 ≥8）")
    ap.add_argument("--bot-id", default=None, help="bot 编号（决定日志名 data/smart_<id>.log）")
    ap.add_argument("--max-wait", type=float, default=60.0, help="单场最长等待分钟数（默认 60）")
    ap.add_argument("--join-only", action="store_true", help="只入席不落座（自测用）")
    ap.add_argument("--archive", default=None, metavar="ROOM",
                    help="只给已打完的房间补档（不重打）；可配 --log 做 chi 对拍")
    ap.add_argument("--log", default=None, help="补档时用的 bot 日志（默认 data/smart_gm.log）")
    args = ap.parse_args()

    token_file = args.token_file if os.path.isabs(args.token_file) else os.path.join(ROOT, args.token_file)
    token = read_token(token_file)
    st, me = api("GET", "/api/me", token, tries=3)
    if st != 200 or not isinstance(me, dict):
        raise SystemExit("令牌不可用（%s %s）——门户「我的 AI 身份」重新取" % (st, str(me)[:120]))
    if me.get("tournament_id"):
        raise SystemExit("这不是全局令牌（tid=%s）→ /api/match 会 400 TOKEN_NOT_SCOPED" % me["tournament_id"])
    meta_common = {"token_fingerprint": fingerprint(token), "user_id": me.get("user_id"),
                   "token_file": os.path.relpath(token_file, ROOT)}
    print("令牌 ok（指纹 %s，user=%s）" % (meta_common["token_fingerprint"], me.get("user_id")))

    if args.archive:
        room = args.archive.strip()
        outdir = os.path.join(MATCHES, room)
        os.makedirs(outdir, exist_ok=True)
        meta = dict(meta_common)
        meta.update({"room_id": room, "started_at": None, "ended_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "duration_s": None, "exit_code": None, "backfilled": True,
                     "bot_id": None,
                     "log_path": os.path.relpath(args.log or os.path.join(ROOT, "data", "smart_gm.log"),
                                                 ROOT)})
        log_src = os.path.join(ROOT, meta["log_path"])
        if os.path.exists(log_src):
            shutil.copy2(log_src, os.path.join(outdir, "bot.log"))
        stat = finalize(room, outdir, meta, token)
        print("补档完成：%s（净分 %+d、局数 %d、chi 对拍 %s）"
              % (os.path.relpath(outdir, ROOT), stat["me"]["net_score"], stat["rounds"]["total"],
                 "✅" if (stat["verify"]["chi_tiles_parity"] or {}).get("ok") else "❌/未做"))
        return 0

    for i in range(max(1, args.sessions)):
        print("\n=== 第 %d/%d 场 ===" % (i + 1, max(1, args.sessions)))
        stat = session_once(args, token, meta_common)
        if stat:
            print("本场：净分 %+d、我胡 %d/%d 局、出牌超时 %d、chi 对拍 %s"
                  % (stat["me"]["net_score"], stat["rounds"]["my_hu"], stat["rounds"]["total"],
                     stat["timeouts"]["discard"],
                     "✅" if (stat["verify"]["chi_tiles_parity"] or {}).get("ok") else "❌/未做"))
    print("\n索引：%s（跑 python match_stats.py 看跨场汇总）" % os.path.relpath(INDEX, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
