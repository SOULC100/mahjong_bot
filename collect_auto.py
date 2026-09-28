"""collect_auto.py — 自动匹配（auto 房）赛果的**兜底收集器**：标记 → 扫 → 归档 → 状态。

需求（2026-09-23 用户）：**以后只要触发自动匹配都要收集数据**——不依赖人记得手动跑归档。

装置分三层，本文件只负责第 2/3 层，第 1 层由各触发点自己落标记：

1. **触发点**（落标记，一行 json，极轻量，失败不影响对局）
   - `match_session.py`：入席成功即落标记（归档成功后清掉）
   - `smart_bot.py`：standalone 走 `POST /api/match` 成功即落标记（谁起的进程都不用管）
   - `live_loop.py` / `live_smoke.py`：开一波/一轮后按 bot 日志抽 room 落标记
2. **扫**（`sweep`，默认动作）：`data/matches/_pending/*.json` → 逐房校验归档完整性
   → 缺件就调 `match_session.py --archive <room> --log <bot.log>` 补档 → 状态写回标记
3. **守**（`watch`，常驻）：按周期重复 sweep，并对「标记指向的房还在打」的情况轮询等它打完
   （房间关闭后免认证端点仍可读，见下），适合真机连场期间挂后台。

为什么兜底可行（2026-09-23 实测）：房间关停后**玩家** API 一律 404，但免认证端点
`/api/test-rooms/{room}/games[/{batch}/events]` 仍长期可读（对已关闭约 3 小时的
`a_f5e3bb628234` 实测 200、events 每场 150KB+）。所以归档窗口不再是「60 秒」，而是「尽量早」。

放在仓库根（而不是 `data/`）是刻意的：`data/` 被 .gitignore 排除（内含令牌/cookie 明文），
收集器属于**代码**、要进版本库；它只往 `data/` 写运行产物。

用法：
    python collect_auto.py                     # = sweep：把待归档的全部收掉
    python collect_auto.py list                # 看待归档/失败清单
    python collect_auto.py add --room a_xxx --source manual --log data/smart_gm.log
    python collect_auto.py ensure              # 确保常驻在跑（幂等；触发点自动调这个）
    python collect_auto.py status              # 常驻状态 + 待归档 + 日志尾部
    python collect_auto.py stop                # 停掉常驻
    python collect_auto.py watch --interval 300   # 前台常驻（调试用；Ctrl-C 停）
    python collect_auto.py sweep --force       # 已有归档也重收一遍

只读归档 + 只调 `match_session.py --archive`；令牌只读文件、从不打印明文。
**自动常驻**：入席自动匹配房后，触发点会调 `python collect_auto.py ensure`（幂等，PID 锁在
`data/_collector.pid`）把常驻拉起来——即「下次触发自由匹配时自动开始收集」，不必人记得挂。

设计与自检见 `docs/auto-collect.md`。
"""

import argparse
import hashlib
import json
import os
import subprocess
import ssl
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("COLLECT_SERVER") or "https://10.240.169.190:18080"
CTX = ssl._create_unverified_context()
# 数据根可被环境变量改写到沙箱目录：自检（data/_collect_auto_test.py）用它在**副本**上做
# 「破坏 → 修复」，绝不碰 data/matches 里的真实归档。
DATA = os.environ.get("COLLECT_DATA_DIR") or os.path.join(ROOT, "data")
MATCHES = os.path.join(DATA, "matches")
PENDING = os.path.join(MATCHES, "_pending")
INDEX = os.path.join(MATCHES, "index.tsv")
LOG = os.path.join(DATA, "_collector.log")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 控制台编码：Windows 默认 GBK 会把中文日志打成乱码（文件里仍是 UTF-8，不受影响）
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------- 标记（触发点共用）

def pending_dir():
    os.makedirs(PENDING, exist_ok=True)
    return PENDING


def marker_path(room):
    return os.path.join(pending_dir(), "%s.json" % room)


def write_marker(room, source, bot_id=None, log_path=None, token_file=None, note=None):
    """落/更新待归档标记。**绝不抛异常**（触发点在对局关键路径上，失败只记一笔）。

    返回标记文件路径或 None。同一房重复触发时保留原 created_at、只补新信息。
    """
    if not room:
        return None
    try:
        p = marker_path(room)
        old = {}
        if os.path.exists(p):
            try:
                old = json.load(open(p, encoding="utf-8"))
            except Exception:
                old = {}
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        m = {
            "room_id": room,
            "created_at": old.get("created_at") or now,
            "updated_at": now,
            "source": source,
            "bot_id": bot_id or old.get("bot_id"),
            "log_path": log_path or old.get("log_path"),
            "token_file": token_file or old.get("token_file") or os.path.join("data", "global_token.txt"),
            "status": "pending",
            "attempts": 0,
            "sources": sorted(set((old.get("sources") or []) + [source])),
            "last_error": None,
            "archived_at": old.get("archived_at"),
        }
        if note:
            m["note"] = note
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return p
    except Exception:
        return None


def read_marker(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_marker(m):
    try:
        p = marker_path(m["room_id"])
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass


def clear_marker(room):
    """归档确认完成后删标记（失败不回滚：删不掉也只影响一次重扫）。"""
    try:
        os.remove(marker_path(room))
        return True
    except OSError:
        return False


def read_token(token_file):
    """读全局令牌；只回明文给请求头，绝不打印。"""
    p = token_file if os.path.isabs(token_file) else os.path.join(ROOT, token_file)
    if not os.path.exists(p):
        return "", None
    tok = open(p, encoding="utf-8").read().strip()
    return tok, (hashlib.sha256(tok.encode()).hexdigest()[:8] if tok else None)


# ---------------------------------------------------------------- 归档完整性

def archive_state(room):
    """看归档「到不到位」。返回 dict：ok / missing / events / note。

    判据（都是本地文件，不联网）：
      - `session.json` 存在且能解析
      - `stats.json` 存在且能解析
      - `events/` 里可解析的 b*.json 数 == games.json 里的场次数（缺场次说明抓取失败过）
    """
    d = os.path.join(MATCHES, room)
    out = {"room": room, "ok": False, "missing": [], "events": 0, "games": None, "note": ""}
    if not os.path.isdir(d):
        out["missing"].append("目录")
        out["note"] = "尚无归档目录"
        return out
    for fn in ("session.json", "stats.json", "games.json"):
        p = os.path.join(d, fn)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            out["missing"].append(fn)
            continue
        try:
            json.load(open(p, encoding="utf-8"))
        except Exception as e:
            out["missing"].append("%s(解析失败:%s)" % (fn, type(e).__name__))
    games = None
    gp = os.path.join(d, "games.json")
    if os.path.exists(gp) and os.path.getsize(gp):
        try:
            g = json.load(open(gp, encoding="utf-8"))
            games = len(g) if isinstance(g, list) else len(g.get("games") or [])
        except Exception:
            games = None
    out["games"] = games
    evdir = os.path.join(d, "events")
    n = 0
    if os.path.isdir(evdir):
        for fn in os.listdir(evdir):
            if not fn.endswith(".json"):
                continue
            try:
                json.load(open(os.path.join(evdir, fn), encoding="utf-8"))
                n += 1
            except Exception:
                pass
    out["events"] = n
    if games is not None and n < games:
        out["missing"].append("events(%d/%d)" % (n, games))
    if not out["missing"]:
        out["ok"] = True
        out["note"] = "归档完整（%s 场事件流）" % n
    else:
        out["note"] = "缺件：" + "、".join(out["missing"])
    return out


# ---------------------------------------------------------------- 联网（只读）

def http_get(path, token=None, timeout=25):
    req = urllib.request.Request(SERVER + path, method="GET")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw[:300]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]
    except Exception as e:
        return 0, repr(e)


def room_progress(room):
    """免认证快照端点看房间进度：{status, games, finished, running, live} 或 None（查不到）。

    `live` 的判据（2026-09-23 真机踩到过）：**不能只看"有没有在跑的对局"**——
    刚入席时房间是 `registering`、`games=[]`，那时补档只会把空列表当成功（还写出半截归档 +
    把标记判成 failed）。所以只要房没到终态（closed/finished/void）就算 live，等着。
    """
    st, body = http_get("/api/test-rooms/%s/games" % room)
    if st != 200 or not isinstance(body, dict):
        return None
    games = body.get("games") or []
    status = body.get("status")
    return {"status": status, "games": len(games),
            "finished": sum(1 for g in games if g.get("status") == "finished"),
            "running": sum(1 for g in games if g.get("status") not in ("finished", "void")),
            "live": status not in ("closed", "finished", "void")}


# ---------------------------------------------------------------- 归档动作

def run_archive(room, log_path, token_file, timeout_s=900):
    """调 match_session.py --archive 补档（复用既有 finalize：元数据+快照+事件流+stats+索引）。

    `--require-complete`：事件流抓到缺件时 match_session 返回 3 → 收集器按「没成」处理、下轮重试。
    """
    cmd = [sys.executable, os.path.join(ROOT, "match_session.py"),
           "--archive", room, "--token-file", token_file, "--require-complete"]
    if log_path:
        cmd += ["--log", log_path]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout_s)
    tail = (p.stdout or "").strip().splitlines()[-3:]
    return {"cmd": " ".join(cmd[1:]), "rc": p.returncode, "sec": round(time.time() - t0, 1),
            "tail": tail, "stderr": (p.stderr or "").strip()[-300:]}


def log_line(*a):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(str(x) for x in a))
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def purge_partial(room):
    """删掉「还没打完就归档」留下的空壳目录（`session.json` / `stats.*` / `games.json`）。

    为什么需要：2026-09-23 真机验收时，房间还在 `registering` 就被补档 → 写出 0 场的
    `session.json`/`stats.json`，还挂了一行 `index.tsv`。这些假记录会污染跨场汇总，
    所以一旦发现房间仍 live，就把空壳清掉，等真打完再补。
    `bot.log` 不删（补档时本来从 `data/smart_<bot>.log` 复制，不依赖归档内的副本）。
    """
    d = os.path.join(MATCHES, room)
    removed = []
    if os.path.isdir(d):
        for fn in ("session.json", "stats.json", "stats.md", "games.json"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                try:
                    os.remove(p)
                    removed.append(fn)
                except OSError:
                    pass
        ev = os.path.join(d, "events")
        if os.path.isdir(ev):
            for fn in os.listdir(ev):
                try:
                    os.remove(os.path.join(ev, fn))
                except OSError:
                    pass
    # 索引那一行必须**独立于文件删除**来检查：文件可能上一轮已经删了、假行却还在
    # （2026-09-23 实测：purge 被 `if removed:` 挡住 → 28 行的假行一直挂着）。
    try:
        rows = [l.rstrip("\n").split("\t") for l in open(INDEX, encoding="utf-8")
                if l.strip() and not l.startswith("room_id")]
        keep = [r for r in rows if r and r[0] != room]
        if len(keep) != len(rows):
            header = ["room_id", "started_at", "ended_at", "duration_s", "M", "Rounds", "games",
                      "rounds", "my_hu", "my_net", "chi_parity_ok", "discard_timeouts", "exit_code"]
            with open(INDEX, "w", encoding="utf-8") as f:
                f.write("\t".join(header) + "\n")
                for r in keep:
                    f.write("\t".join(r) + "\n")
            removed.append("index.tsv 行")
    except Exception as e:
        log_line("WARN", room, "撤索引行失败：%r（假行可能残留，需人工核对）" % (e,))
    return removed


def collect_one(m, force=False, wait_live=False, dry=False, max_wait_s=0):
    """收一个房。返回 'done'（已完整）/ 'archived'（本次补齐）/ 'running'（还在打）/ 'fail'。

    `max_wait_s`（>0 时）：标记搁太久还没收成 → 直接判失败留在清单里，避免 watch 无限空转。
    """
    room = m["room_id"]
    if max_wait_s:
        try:
            age = time.time() - time.mktime(time.strptime(m.get("created_at") or "", "%Y-%m-%d %H:%M:%S"))
        except Exception:
            age = 0
        if age > max_wait_s:
            st = archive_state(room)
            if not st["ok"]:
                m["status"] = "failed"
                m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                m["last_error"] = "等待超限（%.1fh）：%s" % (age / 3600.0, st["note"])
                save_marker(m)
                log_line("FAIL", room, m["last_error"])
                return "fail"
    before = archive_state(room)
    if before["ok"] and not force:
        log_line("SKIP", room, "归档已完整（%s 场事件流），清标记" % before["events"])
        clear_marker(room)
        return "done"

    prog = room_progress(room)
    if wait_live and prog and prog["live"]:
        # 房还在进行（含刚入席的 registering）：现在补档只能拿到半场甚至空列表，等它打完再来。
        # 顺手把「上一轮误判写出的空壳归档」清掉，并把标记降回 pending（别在 list 里显示 failed）。
        gone = purge_partial(room)
        if m.get("status") != "pending":
            m["status"] = "pending"
            m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            m["last_error"] = None
            save_marker(m)
        log_line("WAIT", room, "房间进行中 status=%s %d/%d 场完成%s"
                 % (prog["status"], prog["finished"], prog["games"],
                    ("；已清空壳：" + ",".join(gone)) if gone else ""))
        return "running"
    if prog is None and before["missing"] and before["missing"] != ["目录"] and not force:
        log_line("WARN", room, "快照端点查不到（可能尚未开赛或已彻底清理）")

    if dry:
        log_line("DRY ", room, "需要归档：%s" % (before["note"]))
        return "archived"

    log_line("ARCH", room, "开始补档（%s）；房间 status=%s %s/%s 场"
             % (before["note"], (prog or {}).get("status"), (prog or {}).get("finished"), (prog or {}).get("games")))
    try:
        r = run_archive(room, m.get("log_path"), m.get("token_file") or "data/global_token.txt")
    except subprocess.TimeoutExpired:
        r = {"rc": -9, "sec": -1, "tail": ["归档子进程超时（900s）"], "stderr": ""}
    after = archive_state(room)
    m["attempts"] = int(m.get("attempts") or 0) + 1
    m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    m["last_archive"] = r
    if after["ok"]:
        m["status"] = "archived"
        m["archived_at"] = m["updated_at"]
        m["last_error"] = None
        save_marker(m)
        log_line("OK  ", room, "归档完成 rc=%s %.1fs → %s" % (r.get("rc"), r.get("sec"), after["note"]))
        # 归档完整才清标记；清不掉也不算失败
        clear_marker(room)
        return "archived"
    m["status"] = "failed"
    m["last_error"] = after["note"] + (" | stderr: " + (r.get("stderr") or "")[:200] if r.get("stderr") else "")
    save_marker(m)
    log_line("FAIL", room, "归档仍不完整（%s）rc=%s %s" % (after["note"], r.get("rc"), (r.get("tail") or [""])[-1][:200]))
    if os.environ.get("COLLECT_DEBUG"):
        log_line("DBG ", room, "cmd=%s sec=%s stderr=%r tail=%r"
                 % (r.get("cmd"), r.get("sec"), (r.get("stderr") or "")[:300], r.get("tail")))
    return "fail"


# ---------------------------------------------------------------- 子命令

def iter_markers():
    pending_dir()
    for fn in sorted(os.listdir(PENDING)):
        if not fn.endswith(".json"):
            continue
        m = read_marker(os.path.join(PENDING, fn))
        if m and m.get("room_id"):
            yield m


def cmd_sweep(args):
    ms = list(iter_markers())
    if args.room:
        ms = [m for m in ms if m["room_id"] in set(args.room)]
    if not ms:
        log_line("sweep", "无待归档标记（%s）" % os.path.relpath(PENDING, ROOT))
        return 0
    log_line("sweep", "待归档 %d 个房：%s" % (len(ms), ", ".join(m["room_id"] for m in ms)))
    counts = {"done": 0, "archived": 0, "running": 0, "fail": 0}
    for i, m in enumerate(ms):
        counts[collect_one(m, force=args.force, wait_live=args.wait_live, dry=args.dry,
                           max_wait_s=args.max_wait * 60)] += 1
        if i + 1 < len(ms):
            time.sleep(args.sleep)          # 免认证端点 per-room 5/s；房间之间留点空
    log_line("sweep", "结束 " + " ".join("%s=%d" % kv for kv in counts.items()))
    return 1 if counts["fail"] else 0


def cmd_watch(args):
    log_line("watch", "常驻开始：每 %ds 扫一遍（Ctrl-C 停）；--wait-live=%s" % (args.interval, args.wait_live))
    rounds = 0
    try:
        while True:
            ns = argparse.Namespace(room=args.room, force=args.force, wait_live=args.wait_live,
                                    max_wait=args.max_wait, interval=args.interval,
                                    sleep=args.sleep, dry=args.dry)
            cmd_sweep(ns)
            rounds += 1
            if args.rounds and rounds >= args.rounds:
                log_line("watch", "达到 --rounds %d，退出" % args.rounds)
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log_line("watch", "收到中断，退出")
        return 0


def cmd_list(args):
    ms = list(iter_markers())
    if not ms:
        print("无待归档标记：%s（说明所有触发点都已归档或还没触发过）" % os.path.relpath(PENDING, ROOT))
        return 0
    print("%-18s %-9s %-19s %-3s %-42s %s" % ("room", "status", "updated_at", "att", "note/last_error", "log"))
    for m in ms:
        st = archive_state(m["room_id"])
        note = (m.get("last_error") or st["note"])[:42]
        print("%-18s %-9s %-19s %-3s %-42s %s"
              % (m["room_id"], m.get("status"), m.get("updated_at"), m.get("attempts"),
                 note, (m.get("log_path") or "-")))
    print("\n标记目录：%s" % os.path.relpath(PENDING, ROOT))
    return 0


def cmd_add(args):
    for room in args.room:
        p = write_marker(room, args.source, bot_id=args.bot_id, log_path=args.log,
                         token_file=args.token_file, note=args.note)
        if p:
            print("已落标记：%s" % os.path.relpath(p, ROOT))
            log_line("add ", room, "来源=%s log=%s" % (args.source, args.log or "-"))
        else:
            print("落标记失败：%s" % room)
            return 1
    return 0


# ---------------------------------------------------------------- 常驻守护（触发自动匹配时自启）

PIDFILE = os.path.join(DATA, "_collector.pid")
OUT = os.path.join(DATA, "_collector.out")


def _pid_alive(pid):
    """进程活着吗。

    Windows 上**不能**用 `os.kill(pid, 0)`：探测不存在的 PID 时它会抛
    `OSError(WinError 87, 参数错误)`，而且 CPython 会把它再包成
    `SystemError: <class 'OSError'> returned a result with an exception set`（绕过 except OSError）。
    所以 Windows 走 ctypes 的 OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)+GetExitCodeProcess。
    """
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:
            return True          # 探测本身失败时保守当作"活着"，宁可不重复起进程
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def read_pidfile():
    """读 PID 文件原文（不管死活）；文件不存在/空/读不到都返回 0。"""
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            return int((f.read() or "0").strip() or 0)
    except Exception:
        return 0


def daemon_pid():
    """活着的常驻 PID；没有（或文件残留但进程已死）返回 None。"""
    pid = read_pidfile()
    return pid if _pid_alive(pid) else None


def acquire_lock(pid):
    """原子抢 PID 锁。返回 True=抢到（文件由本进程创建）。

    为什么必须用 `O_CREAT|O_EXCL`：`ensure` 可能被并发调用（bot 与 match_session 同时入席），
    "先看有没有、再写" 会双双通过检查 → 起两个常驻 → 两个进程同时归档同一房（文件互相覆盖）。
    残留文件（上次被 kill -9）在这里顺手清掉。
    """
    for _ in range(3):
        try:
            fd = os.open(PIDFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(pid))
            return True
        except FileExistsError:
            other = read_pidfile()
            if _pid_alive(other):
                return False
            try:
                os.remove(PIDFILE)          # 残留锁：清掉再抢
            except OSError:
                return False
        except OSError:
            return False
    return False


def spawn_daemon(interval=300, why="", quiet=False):
    """确保收集器常驻在跑（幂等：PID 锁 + 存活检查）。返回 'already' / 'spawned' / 'failed'。

    触发点（`match_session.py` / `smart_bot.py`）在**入席自动匹配房之后**调它：
    用户定的规则是「下次触发自由匹配时自动开始收集」——所以不在开机时挂，而是在真正打起来时起，
    并且只起一个（多个进程同时归档同一房会互相覆盖文件）。
    """
    pid = daemon_pid()
    if pid:
        if not quiet:
            log_line("ensure", "收集器已在跑 pid=%d（%s）" % (pid, why))
        return "already"
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        out = open(OUT, "a", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                       | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        p = subprocess.Popen([sys.executable, "-u", os.path.abspath(__file__),
                              "daemon", "--interval", str(interval)],
                             cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, **kwargs)
        # 等常驻把 PID 锁写出来再返回：否则这中间有个空窗，并发 ensure 会以为没人管而**重复起**
        # （实测：spawn 后立刻 read_pidfile 拿到空文件 → 误判"未运行"）。
        t0 = time.time()
        got = 0
        while time.time() - t0 < 10.0:
            got = read_pidfile()
            if got and _pid_alive(got):
                break
            time.sleep(0.2)
        if got and _pid_alive(got):
            log_line("ensure", "已拉起收集器常驻 pid=%d interval=%ds（%s）" % (got, interval, why))
            return "spawned"
        log_line("ensure", "已发起收集器 pid=%d，但 %.1fs 内未确认 PID 锁（%s）——下轮 ensure 会再试"
                 % (p.pid, time.time() - t0, why))
        return "spawned"
    except Exception as e:
        log_line("ensure", "拉起收集器失败：%r（不影响对局）" % (e,))
        return "failed"


def cmd_daemon(args):
    """常驻真身：原子抢 PID 锁 → 周期 sweep。抢不到说明已有实例，直接退出。

    存活性的坑（2026-09-23 实测）：`ensure` 用 DETACHED_PROCESS 起的常驻，在**父 shell 退出后
    会被回收**（活着约 30s 就没了；同条件的纯 sleep 子进程却能活，说明是 shell/沙箱的进程组清理）。
    所以常驻应该跑在**管得住它的地方**：前台终端 / 计划任务 / DSH 后台作业（`collect_auto.py
    watch` 或本命令都行）。`ensure` 只是"尽力拉起"，不能当成常驻保险。
    """
    if not acquire_lock(os.getpid()):
        other = read_pidfile()
        log_line("daemon", "已有常驻在跑 pid=%d，本进程退出（不重复收）" % other)
        return 0
    log_line("daemon", "常驻开始 pid=%d interval=%ds（PID 锁 %s）"
             % (os.getpid(), args.interval, os.path.relpath(PIDFILE, ROOT)))
    ns = argparse.Namespace(room=args.room, force=args.force, wait_live=args.wait_live,
                            max_wait=args.max_wait, interval=args.interval,
                            sleep=args.sleep, dry=args.dry)
    try:
        while True:
            try:
                cmd_sweep(ns)
            except KeyboardInterrupt:
                raise
            except Exception as e:                      # 单轮异常不能打死常驻
                log_line("daemon", "本轮 sweep 异常（继续）：%r" % (e,))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log_line("daemon", "收到中断，退出")
        return 0
    finally:
        try:
            if read_pidfile() == os.getpid():
                os.remove(PIDFILE)
        except OSError:
            pass


def cmd_ensure(args):
    r = spawn_daemon(args.interval, why="ensure 子命令", quiet=args.quiet)
    if args.quiet is False:
        print("收集器常驻：%s" % r)
    return 0 if r != "failed" else 1


def cmd_status(args):
    pid = daemon_pid()
    print("常驻收集器：%s（PID 文件 %s%s）"
          % ("运行中 pid=%d" % pid if pid else "未运行",
             os.path.relpath(PIDFILE, ROOT),
             "" if os.path.exists(PIDFILE) else "（不存在）"))
    ms = list(iter_markers())
    print("待归档标记：%d 个" % len(ms))
    for m in ms:
        st = archive_state(m["room_id"])
        print("  %s  %s  %s" % (m["room_id"], m.get("status"), (m.get("last_error") or st["note"])[:60]))
    if os.path.exists(LOG):
        print("日志尾部（%s）：" % os.path.relpath(LOG, ROOT))
        for line in open(LOG, encoding="utf-8", errors="replace").read().splitlines()[-5:]:
            print("  " + line)
    return 0


def cmd_stop(args):
    pid = daemon_pid()
    if not pid:
        print("常驻收集器未在运行")
        return 0
    # Windows：`os.kill(pid, 15)` 与 `taskkill /F` 在受限/跨会话环境里都可能 `Access denied`，
    # 但 `OpenProcess(PROCESS_TERMINATE)+TerminateProcess` 能成（2026-09-23 实测：
    # taskkill 拒绝访问、Stop-Process 成功；两者底层都是 TerminateProcess，差别在权限路径）。
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_TERMINATE = 0x0001
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
            if not h:
                print("停不掉 pid=%d：OpenProcess 失败（err=%d）" % (pid, ctypes.get_last_error()))
                return 1
            try:
                ok = bool(k32.TerminateProcess(h, 1))
            finally:
                k32.CloseHandle(h)
            err = "" if ok else "TerminateProcess 失败"
        else:
            os.kill(pid, 15)
            ok, err = True, ""
    except Exception as e:
        print("停不掉 pid=%d：%r" % (pid, e))
        return 1
    time.sleep(1.5)
    alive = bool(daemon_pid())
    if not alive:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
    if alive:
        print("停不掉 pid=%d：%s（权限不足或被别的会话占有；可在任务管理器/管理员终端结束）"
              % (pid, err or "taskkill 返回非零"))
    else:
        print("已停 pid=%d" % pid)
    return 0 if not alive else 1


def build_parser():
    ap = argparse.ArgumentParser(description="自动匹配赛果的兜底收集器（标记 → 扫 → 归档 → 状态）")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--room", action="append", default=None, help="只处理指定房（可重复）")
        p.add_argument("--force", action="store_true", help="已有完整归档也重收一遍")
        p.add_argument("--wait-live", action="store_true", default=True,
                       help="房间还在打就等它打完（默认开）")
        p.add_argument("--no-wait-live", dest="wait_live", action="store_false")
        p.add_argument("--max-wait", type=float, default=120.0, help="单房等待上限（分钟，默认 120）")
        p.add_argument("--sleep", type=float, default=1.0, help="房间之间的间隔秒（默认 1.0）")
        p.add_argument("--dry", action="store_true", help="只看要收哪些，不真归档")

    p_sweep = sub.add_parser("sweep", help="扫一遍待归档（默认动作）")
    common(p_sweep)
    p_sweep.add_argument("--interval", type=int, default=60, help="watch 用；sweep 里占位")
    p_sweep.set_defaults(func=cmd_sweep)

    p_watch = sub.add_parser("watch", help="常驻：按周期反复 sweep")
    common(p_watch)
    p_watch.add_argument("--interval", type=int, default=60, help="扫描周期秒（默认 60）")
    p_watch.add_argument("--rounds", type=int, default=0, help="扫几轮后退出（0=无限）")
    p_watch.set_defaults(func=cmd_watch)

    p_list = sub.add_parser("list", help="列待归档/失败清单")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="手工落一个待归档标记")
    p_add.add_argument("--room", action="append", required=True)
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--bot-id", default=None)
    p_add.add_argument("--log", default=None, help="bot 日志路径（做 chi 对拍用）")
    p_add.add_argument("--token-file", default=os.path.join("data", "global_token.txt"))
    p_add.add_argument("--note", default=None)
    p_add.set_defaults(func=cmd_add)

    p_daemon = sub.add_parser("daemon", help="常驻真身（带 PID 锁；一般由 ensure/触发点自动拉起）")
    common(p_daemon)
    p_daemon.add_argument("--interval", type=int, default=300, help="扫描周期秒（默认 300）")
    p_daemon.set_defaults(func=cmd_daemon)

    p_ensure = sub.add_parser("ensure", help="确保常驻在跑（幂等；触发点用）")
    p_ensure.add_argument("--interval", type=int, default=300)
    p_ensure.add_argument("--quiet", action="store_true")
    p_ensure.set_defaults(func=cmd_ensure)

    p_status = sub.add_parser("status", help="常驻状态 + 待归档清单 + 日志尾部")
    p_status.set_defaults(func=cmd_status)

    p_stop = sub.add_parser("stop", help="停掉常驻")
    p_stop.set_defaults(func=cmd_stop)
    return ap


def main(argv=None):
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # 默认动作 = sweep（`python collect_auto.py` 直接可用）
    known = ("sweep", "watch", "list", "add", "daemon", "ensure", "status", "stop")
    if not argv or argv[0] not in known:
        argv = ["sweep"] + argv
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
