"""ledger.py — 台账 + 版本化 + champion 指针（可回溯、一键回滚）。

目录：opt/rounds/<round_id>/ledger.tsv + candidates/<cid>.json；opt/champion.json = 当前最优。
champion 永远从 JSON 读（不依赖 Smart() 默认），genome hash 定版本 → 回滚=指针指回旧版本。
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
ROUNDS = os.path.join(ROOT, "rounds")
CHAMP_PATH = os.path.join(ROOT, "champion.json")
# 初始 champion = 对齐线上(EV 开) + 坐庄抢速 aggr(2026-09-03 实测当庄 +0.8~+1.9 avg)。
# 其余取 Smart 默认（含 angang_tenpai_only/protect_gang 等）。
DEFAULT_CHAMP = {"use_ev": True, "dealer_policy": "aggr"}

_FIELDS = ["round", "cid", "proposer", "parent", "n_block", "mean", "se", "z",
           "win_pp", "dealer_mean", "idle_mean", "status", "note"]


def _makedirs(p):
    os.makedirs(p, exist_ok=True)


def round_dir(rid):
    return os.path.join(ROUNDS, rid)


def default_champion():
    from opt.genome import resolved
    return resolved(DEFAULT_CHAMP)


def current_champion():
    """读 champion.json；兼容两种结构：promote 的包装 {genome, version_id,...} 或纯 genome dict。"""
    if os.path.exists(CHAMP_PATH):
        try:
            d = json.load(open(CHAMP_PATH, encoding="utf-8"))
        except Exception:
            d = None
        if isinstance(d, dict):
            g = d.get("genome") if "genome" in d else d
            if isinstance(g, dict):
                from opt.genome import resolved
                return resolved(g)
    return default_champion()


def promote(genome, rid, note=""):
    from opt.genome import resolved, genome_id
    g = resolved(genome)
    data = {"genome": g, "version_id": genome_id(g), "promoted_at_round": rid, "note": note}
    json.dump(data, open(CHAMP_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 同时存一份历史
    _makedirs(os.path.join(ROUNDS, "champions"))
    with open(os.path.join(ROUNDS, "champions", genome_id(g) + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return g


def rollback(version_id):
    """回滚 champion 到历史版本。"""
    p = os.path.join(ROUNDS, "champions", version_id + ".json")
    if not os.path.exists(p):
        return False
    d = json.load(open(p, encoding="utf-8"))
    json.dump(d, open(CHAMP_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return True


def save_candidate(rid, cid, genome, meta):
    _makedirs(os.path.join(round_dir(rid), "candidates"))
    with open(os.path.join(round_dir(rid), "candidates", cid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"genome": genome, **meta}, f, ensure_ascii=False, indent=1)


def append_ledger(rid, row):
    _makedirs(round_dir(rid))
    p = os.path.join(round_dir(rid), "ledger.tsv")
    row = {k: row.get(k, "") for k in _FIELDS}
    new = not os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS, delimiter="\t")
        if new:
            w.writeheader()
        w.writerow(row)


def write_round_report(rid, lines):
    _makedirs(round_dir(rid))
    with open(os.path.join(round_dir(rid), "round_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
