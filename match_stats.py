"""自由对战跨场汇总：读 data/matches/*/stats.json（或 index.tsv）出总表。

用法：
    python match_stats.py              # 人读总表（stdout）
    python match_stats.py --json       # 机器读（全量 stats 数组）
    python match_stats.py --csv out.csv

口径说明：
- 净分/番型/胡牌率等**只统计成功解析到事件流的场次**（事件流缺失的场次单列「缺事件流」）。
- 「chi 对拍」= bot 日志的 chi 提交（扣除被 409 拒的）与服务端事件流 chi 副露的多重集一致性，
  即 `smart_bot` 发 `tiles` 后服务端是否真按我们选的那副吃（见 docs/debug_log.md §十二）。
"""

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MATCHES = os.path.join(ROOT, "data", "matches")


def load_all():
    out = []
    for p in sorted(glob.glob(os.path.join(MATCHES, "*", "stats.json"))):
        try:
            out.append(json.load(open(p, encoding="utf-8")))
        except Exception as e:
            print("  ! 读不了 %s: %r" % (p, e), file=sys.stderr)
    out.sort(key=lambda s: s.get("started_at") or s.get("ended_at") or "")
    return out


def pct(n, d):
    return "%.1f%%" % (100.0 * n / d) if d else "n/a"


def main():
    ap = argparse.ArgumentParser(description="自由对战跨场汇总")
    ap.add_argument("--json", action="store_true", help="输出全量 stats JSON")
    ap.add_argument("--csv", default=None, help="把每场一行导出 CSV")
    args = ap.parse_args()

    stats = load_all()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0
    if not stats:
        print("还没有归档场次。跑 `python match_session.py` 打一场即会写入 data/matches/")
        return 0

    with_ev = [s for s in stats if s["rounds"]["total"]]
    no_ev = [s for s in stats if not s["rounds"]["total"]]
    games = sum(len(s["me"]["per_game"]) for s in with_ev)
    rounds = sum(s["rounds"]["total"] for s in with_ev)
    my_hu = sum(s["rounds"]["my_hu"] for s in with_ev)
    others = sum(s["rounds"]["others_hu"] for s in with_ev)
    draws = sum(s["rounds"]["draws"] for s in with_ev)
    net = sum(s["me"]["net_score"] for s in with_ev)
    rank1 = sum(s["me"]["games_rank1"] for s in with_ev)
    fan = {}
    detail = {}
    for s in with_ev:
        for k, v in (s["rounds"]["fan_hist"] or {}).items():
            fan[k] = fan.get(k, 0) + v
        for k, v in (s["rounds"]["detail_hist"] or {}).items():
            detail[k] = detail.get(k, 0) + v
    to_discard = sum(s["timeouts"]["discard"] for s in with_ev)
    discards = sum((s["bot"] or {}).get("submissions", {}).get("discard", 0) for s in with_ev)
    parity_ok = sum(1 for s in with_ev
                    if (s["verify"]["chi_tiles_parity"] or {}).get("ok"))
    parity_done = sum(1 for s in with_ev if s["verify"]["chi_tiles_parity"])
    v25_bad = [s["room_id"] for s in with_ev if not s["claims"]["v25_chi_le_2_ok"]]
    crashes = [s["room_id"] for s in stats
               if (s["bot"] or {}).get("tracebacks") or (s["bot_exit_code"] not in (0, None))]
    zero_sum_bad = [s["room_id"] for s in with_ev if not s["zero_sum_ok"]]

    print("自由对战累计汇总（%d 场，其中可统计 %d 场）" % (len(stats), len(with_ev)))
    print("=" * 64)
    print("场次        : %d 场（每场 M=%s / Rounds=%s）"
          % (games, (with_ev[0]["config"] or {}).get("M") if with_ev else "?",
             (with_ev[0]["config"] or {}).get("Rounds") if with_ev else "?"))
    print("局数        : %d 局 → 我胡 %d（%s）、他人胡 %d、流局 %d"
          % (rounds, my_hu, pct(my_hu, rounds), others, draws))
    print("净分        : 合计 %+d（会话均 %+.1f / 内部场次均 %+.2f），场冠军 %d/%d（%s）"
          % (net, net / len(with_ev) if with_ev else 0, net / games if games else 0,
             rank1, games, pct(rank1, games)))
    print("累计用时    : %.0f 分钟" % (sum((s["duration_s"] or 0) for s in stats) / 60.0))
    print("场均番（我）: %s"
          % (round(sum((s["rounds"]["avg_fan"] or 0) * s["rounds"]["my_hu"] for s in with_ev)
                   / my_hu, 3) if my_hu else "n/a"))
    print("番型（我）  : %s"
          % (", ".join("%s番×%d" % (k, v) for k, v in sorted(fan.items())) or "-"))
    print("番型明细    : %s"
          % (", ".join("%s×%d" % (k, v) for k, v in sorted(detail.items())) or "-"))
    print("出牌超时    : %d 次 / %d 次出牌（%s）" % (to_discard, discards, pct(to_discard, discards)))
    print("chi 对拍    : %d/%d 场一致%s"
          % (parity_ok, parity_done or len(with_ev),
             "" if parity_done == len(with_ev) else "（有场次缺日志或事件流）"))
    print("规则/健康   : 吃摊越限 %s；进程异常 %s；零和校验失败 %s"
          % (v25_bad or "无", crashes or "无", zero_sum_bad or "无"))
    if no_ev:
        print("缺事件流    : %s" % ", ".join(s["room_id"] for s in no_ev))
    print()
    print("%-22s %-19s %6s %6s %6s %7s %6s %5s" %
          ("room", "起打", "场次", "局数", "我胡", "净分", "对拍", "退出"))
    for s in stats:
        v = s["verify"]["chi_tiles_parity"] or {}
        tag = "✅" if v.get("ok") else ("—" if not v else "❌")
        print("%-22s %-19s %6d %6d %6d %+7d %6s %5s"
              % (s["room_id"], s["started_at"] or s["ended_at"] or "-",
                 len(s["me"]["per_game"]), s["rounds"]["total"], s["rounds"]["my_hu"],
                 s["me"]["net_score"], tag, s["bot_exit_code"]))

    if args.csv:
        cols = ["room_id", "started_at", "ended_at", "duration_s", "M", "Rounds", "games", "rounds",
                "my_hu", "my_hu_rate", "net_score", "games_rank1", "avg_rank", "avg_fan",
                "discard_timeouts", "discard_rate", "chi_parity_ok", "v25_ok", "exit_code"]
        with open(args.csv, "w", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")
            for s in stats:
                v = s["verify"]["chi_tiles_parity"] or {}
                row = [s["room_id"], s["started_at"], s["ended_at"], s["duration_s"],
                       (s["config"] or {}).get("M"), (s["config"] or {}).get("Rounds"),
                       len(s["me"]["per_game"]), s["rounds"]["total"], s["rounds"]["my_hu"],
                       s["rounds"]["my_hu_rate"], s["me"]["net_score"], s["me"]["games_rank1"],
                       s["me"]["avg_rank"], s["rounds"]["avg_fan"], s["timeouts"]["discard"],
                       s["timeouts"]["discard_rate"], "1" if v.get("ok") else "0",
                       "1" if s["claims"]["v25_chi_le_2_ok"] else "0", s["bot_exit_code"]]
                f.write(",".join("" if x is None else str(x) for x in row) + "\n")
        print("\nCSV 已写 %s" % args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
