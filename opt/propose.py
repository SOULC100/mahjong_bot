"""propose.py — 提议器：在 champion 附近采样候选（爬山/随机/模板）。

Phase A 纯 CPU（无 LLM）。每个候选 = 完整 genome + diff(相对 parent) + rationale。
"""
import random

from opt import genome as G


class Proposer:
    name = "base"

    def propose(self, parent, k, rng=None):
        raise NotImplementedError


class Random(Proposer):
    name = "random"

    def propose(self, parent, k, rng=None):
        rng = rng or random.Random(0)
        out = []
        for i in range(k):
            g = G.random_genome(rng)
            out.append({"genome": g, "diff": _diff(parent, g),
                        "rationale": "随机扰动", "proposer": self.name})
        return out


class HillClimb(Proposer):
    name = "hill"

    def __init__(self, n_changes=(1, 2), temp=(0.5, 1.5)):
        self.n_changes = n_changes
        self.temp = temp

    def propose(self, parent, k, rng=None):
        rng = rng or random.Random(0)
        out = []
        for i in range(k):
            nc = rng.randint(*self.n_changes)
            tp = rng.uniform(*self.temp)
            g = G.mutate(parent, rng, n_changes=nc, temp=tp)
            out.append({"genome": g, "diff": _diff(parent, g),
                        "rationale": "爬山变异(%d处, temp=%.2f)" % (nc, tp), "proposer": self.name})
        return out


# 模板：把历史上 A/B 脚本的候选组合数据化（保证老方向被覆盖）
_TEMPLATES = [
    ({"use_ev": True}, "EV 番型抵消(对齐线上)"),
    ({"baotou_slack": 2, "baotou_max_shanten": 2}, "B2 放宽爆头路线"),
    ({"peng_ukeire_gate": True, "chi_ukeire_gate": True}, "A1 吃碰门控"),
    ({"use_gang": False}, "关杠(对照)"),
    ({"angang_tenpai_only": False}, "无脑暗杠(对照)"),
    ({"defend_dealer": True}, "D1 喂庄防守(对照,预期负)"),
]


class Template(Proposer):
    name = "template"

    def propose(self, parent, k, rng=None):
        out = []
        for diff, rationale in _TEMPLATES[:k]:
            g = G.resolved({**parent, **diff})
            out.append({"genome": g, "diff": diff, "rationale": rationale, "proposer": self.name})
        return out


def _diff(parent, child):
    """返回候选相对 parent 改动的项（child 是完整 genome）。"""
    return {k: v for k, v in child.items()
            if parent.get(k) != v or (k in child and k not in parent)}
