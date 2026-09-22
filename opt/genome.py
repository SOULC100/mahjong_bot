"""genome.py — 策略基因组：schema 自动从 Smart 构造签名生成 + 规范化 + hash + 变异。

每个 genome 是一份能直接 `Smart(**genome)` 的完整参数 dict（含默认值），
保证 champion/candidate 可复现、可哈希、可回滚（不依赖 Smart() 默认值随时间漂移）。
2026-09-03 审查修订：
- 只在「活跃/未证伪」维度变异（排除 defend×4、dealer_aware、piao_dealer_only、
  ukeire 门控、ycb_escape_gap 等死/已证伪维度），减少无效应候选 + 多重比较污染；
- str 参数按允许枚举变异；None 阈值不参与。
- 打分权重(SHANTEN_COST/UKEIRE_W/FAN_W/GANG_KEEP_PEN)已穿参进 schema，可搜索。
"""
import hashlib
import inspect
import json

from sim.players import Smart

# 不进 schema/搜索空间的诊断参数：cheat=上帝视角(作弊)、remain_mode=对手建模(记忆证过 uniform 即可)
EXCLUDE = {"cheat", "remain_mode"}
# 活跃可搜索维度（结构开关 + 权重；defend/dealer_aware 等已证伪或死维度在 schema 里保留
# 但不进随机/爬山——Template 负向对照仍可显式给它们）
# 注：decline_hu / decline_q / decline_max_chain（弃胡+财飘，2026-09-20）**不进 ACTIVE**：
#     机会频率只有 0~4 次/千局，A/B 分辨不出（会被当噪声随机游走）→ 作为固定部署开关，
#     由 opt/champion.json 显式带上，保证离线评估与线上 DECLINE_HU 同口径。
ACTIVE = ["use_chi", "use_peng", "use_gang", "fast", "use_ev", "dealer_policy", "fan_est",
          "angang_tenpai_only", "protect_gang", "knock", "piao_enabled",
          "baotou_slack", "baotou_max_shanten", "gang_keep_pen",
          "shanten_cost", "ukeire_w", "fan_weight", "god_fan_boost"]

# str 参数的允许值（变异用）
_STR_ALLOW = {
    "dealer_policy": ["off", "aggr", "bigfan", "aggr_nopiao"],
    "fan_est": ["heuristic", "real_ting"],
}


def schema() -> dict:
    """从 Smart.__init__ 的签名默认值生成完整 genome schema（以后新增 knob 自动纳入）。"""
    sig = inspect.signature(Smart.__init__)
    out = {}
    for name, p in sig.parameters.items():
        if name in ("self",) or name in EXCLUDE:
            continue
        out[name] = p.default
    return out


def resolved(genome: dict) -> dict:
    """把局部 genome（只含要改的项）补成完整 genome，过滤非法键。"""
    base = schema()
    base.update(genome or {})
    return {k: v for k, v in base.items() if k in schema()}


def smart_from(genome: dict) -> Smart:
    return Smart(**resolved(genome))


def genome_id(genome: dict) -> str:
    g = resolved(genome)
    canon = json.dumps(g, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:10]


def _mutate_value(name, val, rng, temp=1.0):
    """对选中参数**必定**产生一个不同值（否则 mutate 会产出重复废候选）。"""
    if isinstance(val, bool):
        return not val
    if isinstance(val, str):
        opts = _STR_ALLOW.get(name)
        if opts and len(opts) > 1:
            others = [o for o in opts if o != val]
            return others[rng.randrange(len(others))]
        return val
    if isinstance(val, int):
        step = max(1, int(abs(val) * 0.3 * temp) if val else 1)
        return val + (step if rng.random() < 0.5 else -step)
    if isinstance(val, float):
        if name in ("shanten_cost", "ukeire_w", "fan_weight", "gang_keep_pen"):
            # 权重类：乘法 ±5~35%
            f = 1.0 + rng.uniform(-0.05, 0.05) * temp + rng.choice([-1, 1]) * rng.uniform(0.03, 0.12) * temp
            return val * f
        return val + rng.gauss(0, max(abs(val), 1.0) * 0.15 * temp)
    return val  # None 等不动


def mutate(parent: dict, rng, n_changes=2, temp=1.0) -> dict:
    """在活跃维度上改 n_changes 个；保证与 parent 不同（否则重试/强制翻转）。"""
    base_id = genome_id(parent)
    keys = [k for k in ACTIVE if k in parent]
    for _ in range(25):
        g = resolved(parent)
        chosen = rng.sample(keys, min(max(1, n_changes), len(keys)))
        for k in chosen:
            g[k] = _mutate_value(k, g[k], rng, temp)
        g = resolved(g)
        if genome_id(g) != base_id:
            return g
    # 兜底：翻转一个活跃 bool（必有）
    g = resolved(parent)
    for k in ACTIVE:
        if isinstance(g[k], bool):
            g[k] = not g[k]
            return g
    return g


def random_genome(rng) -> dict:
    """每个活跃参数随机扰动（必改）→ 随机候选。"""
    g = resolved({})
    for k in ACTIVE:
        if k in g:
            g[k] = _mutate_value(k, g[k], rng, temp=rng.uniform(0.5, 2.0))
    return resolved(g)
