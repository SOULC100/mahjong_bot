"""arena.py — 强场评估竞技场：被测 genome 坐 seat0，另 3 座 = 冻结 champion genome。

返回按 seed 对齐的每局 seat0 得分（配对 base 缓存用）。零和真实计分（引擎 _score）。
自然轮庄：闲胡/流局 → 庄家下家接庄，庄胡 → 连庄（与 sim_run/sim_ab 一致）。
多进程：按 seed 切块分给 workers，Windows spawn 需顶层函数。

用法：
    base = arena.run_seat(champ, champ, seed0, n, ycb, workers)   # champ打自己=σ0/placebo 基线
    cand = arena.run_seat(cand,  champ, seed0, n, ycb, workers)   # 同 seed 段配对
    arena.deltas(base, cand) -> {mean,se,z, dealer/idle 拆分}
"""
import multiprocessing as mp

from sim.engine import Game
from sim.players import Smart
from mahjong import shanten as _sh


def _smart(genome):
    return Smart(**genome)


def _worker(args):
    """跑一批 seed，返回 [(seed, seat0_score, seat0_is_dealer, seat0_won, is_draw), ...]。"""
    genome, champ_genome, seeds, ycb = args
    cand = _smart(genome)
    champ = _smart(champ_genome)
    strategies = [cand, champ, champ, champ]
    out = []
    dealer = 0
    for k, seed in enumerate(seeds):
        g = Game(seed=seed, youcai_bikao=ycb)
        g.dealer = dealer
        w, mult, scores, d = g.play_round(strategies)
        if not d and w != dealer:
            dealer = (dealer + 1) % 4  # 闲胡 → 下家接庄；庄胡/流局连庄
        out.append((seed, scores[0], (g.dealer == 0), (not d and w == 0), d))
        if (k + 1) % 100 == 0:  # 防 shanten lru_cache 无限增长
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    return out


def set_global_pool(workers):
    """整轮共享一个 Pool（一次 spawn），避免每 run_seat 建池导致 Windows 句柄/信号量耗尽。"""
    global _GP
    if _GP is None:
        _GP = mp.Pool(processes=workers)
    return _GP


def close_global_pool():
    global _GP
    if _GP is not None:
        _GP.close()
        _GP.join()
        _GP = None


_GP = None


def run_seat(genome: dict, champ_genome: dict, seed0: int, n: int,
             ycb=False, workers=8) -> dict:
    """被测 genome 坐 seat0 vs 3×champ_genome，跑 [seed0, seed0+n)，返回 {seed:(score,is_dealer,won,draw)}。

    若已 set_global_pool 则复用全局池（推荐整轮调用一次 set_global_pool）；否则每次自建。
    """
    from opt.genome import resolved
    g_res = resolved(genome)
    c_res = resolved(champ_genome)
    seeds = list(range(seed0, seed0 + n))
    chunk = max(1, (n + workers - 1) // workers)
    tasks = [(g_res, c_res, seeds[i:i + chunk], ycb) for i in range(0, n, chunk)]
    results = {}
    if _GP is not None:
        for part in _GP.map(_worker, tasks):
            for seed, sc, isd, won, dr in part:
                results[seed] = (sc, isd, won, dr)
    else:
        with mp.Pool(processes=workers) as pool:
            for part in pool.map(_worker, tasks):
                for seed, sc, isd, won, dr in part:
                    results[seed] = (sc, isd, won, dr)
    return results


def merge(*blocks):
    """把多个 seed 段的 run_seat 结果合并成一个大 dict（跨块累计，seed 应互不重叠）。"""
    out = {}
    for b in blocks:
        out.update(b)
    return out


def deltas(base: dict, cand: dict):
    """配对差（base/cand 必须同 seed 段）。返回 mean/se/z + 当庄/当闲拆分 + 胡牌/流局差值。"""
    common = [s for s in base if s in cand]
    ds = [cand[s][0] - base[s][0] for s in common]
    n = len(ds)
    if n == 0:
        return None
    mean = sum(ds) / n
    var = sum((x - mean) ** 2 for x in ds) / max(1, n - 1)
    se = (var / n) ** 0.5
    z = mean / se if se > 0 else (float("inf") if mean > 0 else float("-inf"))
    dl = [cand[s][0] - base[s][0] for s in common if base[s][1]]
    il = [cand[s][0] - base[s][0] for s in common if not base[s][1]]
    won_c = sum(1 for s in common if cand[s][2]) / n
    won_b = sum(1 for s in common if base[s][2]) / n
    drw_c = sum(1 for s in common if cand[s][3]) / n
    drw_b = sum(1 for s in common if base[s][3]) / n

    def stat(xs):
        if not xs:
            return (None, None)
        m = sum(xs) / len(xs)
        v = sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)
        return (m, (v / len(xs)) ** 0.5)

    return {"n": n, "mean": mean, "se": se, "z": z, "dealer": stat(dl), "idle": stat(il),
            "win_pp": (won_c - won_b) * 100.0, "draw_pp": (drw_c - drw_b) * 100.0}


if __name__ == "__main__":
    import time
    champ = {"use_ev": True}
    t0 = time.time()
    a = run_seat(champ, champ, 100, 200, workers=4)
    b = run_seat(champ, champ, 100, 200, workers=4)
    print("placebo self-paired:", deltas(a, b), " (%.0fs)" % (time.time() - t0))
