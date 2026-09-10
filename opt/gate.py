"""gate.py — 晋级门槛：screen → confirm → holdout + placebo。

2026-09-03 审查修订（防周期性误晋/多重比较骗人）：
- confirm 对同轮候选数做 Bonferroni 式校正（k 候选 ⇒ 单侧 z 门槛升到 ~2.6~2.9），
  消除「k=16 时每轮 0.3~0.6 个纯噪声晋级」的缺陷。
- holdout 不只判 mean>0：加 z≥1.0 且效果量与 confirm 一致（≥0.5×confirm mean）。
- placebo 恒 0 → confirm 每块 mean>0 必拒 → 只作实现金丝雀。
"""
import math

WIN_GUARD = -2.0          # 胡牌率掉 >2pp 一票否决
DEALER_IDLE_BOTH = -0.5   # 当庄与当闲同时显著负 → 拒
ALPHA = 0.05              # 每轮 family-wise error
Z_HOLDOUT = 1.0
CONSIST = 0.5             # holdout mean ≥ CONSIST × confirm mean


def z_crit(k):
    """单侧标准正态分位数，控制 family 误放行 ≈ ALPHA（k 候选，简化映射）。"""
    # 常用点：z(0.95)=1.645 z(0.975)=1.96 z(0.99)=2.33 z(0.995)=2.58 z(0.9975)=2.81 z(0.99875)=3.02
    if k <= 1:
        return 1.96
    if k <= 2:
        return 2.33
    if k <= 5:
        return 2.58
    if k <= 10:
        return 2.81
    if k <= 16:
        return 3.02
    return 3.3


def screen_ok(d):
    """d: arena.deltas 单块结果。宽松：不太差就放行。"""
    if d is None:
        return False
    if d["mean"] < -1.0 and d["z"] < -0.5:
        return False
    if d["win_pp"] < -4.0:
        return False
    return True


def _guards(dm):
    if dm["win_pp"] < WIN_GUARD:
        return False
    de, ie = dm["dealer"][0], dm["idle"][0]
    if de is not None and ie is not None and de < DEALER_IDLE_BOTH and ie < DEALER_IDLE_BOTH:
        return False
    return True


def confirm_pass(per_block, dm, k=1):
    """per_block: 每块 deltas 列表；dm: 合并 deltas；k: 本轮候选数(多重比较校正)。"""
    if not per_block or not all(d["mean"] > 0 for d in per_block):
        return False                      # 每块符号一致且都 >0
    if dm["z"] < z_crit(k):
        return False
    return _guards(dm)


def holdout_pass(dm, confirm_mean):
    """全新 seed 复验：z≥1.0 且效果量与 confirm 一致（防单块噪声放大）。"""
    if dm is None:
        return False
    if dm["mean"] <= 0 or dm["z"] < Z_HOLDOUT:
        return False
    if confirm_mean and dm["mean"] < CONSIST * confirm_mean:
        return False
    return _guards(dm)
