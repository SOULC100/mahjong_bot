"""敲响弃胡（1 张财神也能「留财神做将」再摸一巡 ×2）—— 2026-09-26。

**真机现场**：a_41c78761ce3c_r1_b0_t0 第 6 局（复盘 `data/_knock_a_41c78761ce3c_b0_r6.txt`）：
我 3 副露，摸 5t 后手牌 = 3t4t5t6t + 白 = 平胡 ×1（白当 6t 的将，四家 [-1, +10, -8, -1]）。
而**打掉 6t 后剩 3t4t5t + 白 = 4 面子 + 财神做将 = 任意摸都胡** → 下一摸必胡且爆头 ×2（+20）。
旧代码到不了这一步：`should_decline_hu` 的第一道门是 `piao_after_discard`（要求手里 ≥2 张白），
只有 1 张白时必然「能胡就胡」→ 白丢一个 ×2。新增 `decision.decline_plan` 的 knock 路线。

判据性质（本文件钉死）：
1. 只有「打完某张后 13 张任意摸都胡」**且** 下一摸的番 f1 > 现在的番 f0 才成立（否则纯风险）；
2. 存活率门 `q > q* = (f0+c)/(f1+c)`：闲家 f0=1→f1=2 时 q*=0.79；庄家（c=8）q*=0.90；
3. `knock=False` = 旧行为（逐字节不变）；财飘路线（≥2 白）行为不变、且同 f1 优先飘。
"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
# smart_bot 以脚本方式读 sys.argv，导入前先补齐（argv[2] = 编号 → 日志落 data/smart_test.log）
sys.argv = ["smart_bot.py", "test", "test"]

from mahjong.tiles import list_to_count, tile_name, tile_to_str, NUM_TILES, LAIZI_INDEX   # noqa: E402
from mahjong.decision import decline_plan, should_decline_hu, any_draw_win    # noqa: E402
from mahjong import shanten as _sh                                            # noqa: E402
from sim.engine import Game, Meld, CHI, PENG                                  # noqa: E402
from sim.players import Baseline, Smart                                       # noqa: E402
import smart_bot                                                              # noqa: E402

OK = True


def ck(name, got, want=True):
    global OK
    o = got == want
    OK = OK and o
    print(f"[{'OK  ' if o else 'FAIL'}] {name}: got={got} want={want}")


def T(*tiles):
    return list_to_count(tiles)


# ---- 真机第 6 局的形态（3 副露 + 3t4t5t6t + 白，刚摸 5t） ----
H_R6 = T(11, 12, 13, 14, 33)      # 3t 4t 5t 6t 白（3t=11, 4t=12, 5t=13, 6t=14）
R6_DRAWN = 13                     # 刚摸 5t


def test_decision_knock():
    print("\n=== 1) decision.decline_plan：真机第 6 局形态 ===")
    p = decline_plan(H_R6, 3, drawn=R6_DRAWN, is_dealer=False, knock=True)
    ck("有敲响计划", p is not None)
    ck("路线=knock", p["kind"], "knock")
    # 打 3t 或 6t 都能留下「4 面子 + 白」（等效）→ 判据只保证「打完任意摸都胡」；
    # 具体打哪张由「越死的牌越先打」决定（见下面的 remain 用例）。
    c13 = list(H_R6)
    c13[p["discard"]] -= 1
    ck("舍牌打完 → 13 张「任意摸都胡」", any_draw_win(c13, 3), True)
    ck("舍牌是手牌里的一张非财神", p["discard"] != LAIZI_INDEX and H_R6[p["discard"]] > 0, True)
    ck("现在胡的番 f0=1（平胡）", p["fan_now"], 1)
    ck("下一摸的番 f1=2（爆头 ×2）", p["fan_next"], 2)
    ck("盈亏平衡 q*≈0.789（闲家 c=2.75）", round(p["q_star"], 3), round((1 + 2.75) / (2 + 2.75), 3))
    ck("打完后 13 张「任意摸都胡」", any_draw_win(T(11, 12, 13, 33), 3), True)
    # 舍牌 tie-break：未见张数少的（越"死"）优先 —— 6t 只剩 0 张未见、3t 还有 3 张
    rm = [4] * NUM_TILES
    rm[11] = 3      # 3t 还活着
    rm[14] = 0      # 6t 已经打光
    p_dead = decline_plan(H_R6, 3, drawn=R6_DRAWN, is_dealer=False, knock=True, remain=rm)
    ck("舍牌优先打最死的牌（6t）", tile_to_str(p_dead["discard"]), "6t")

    # knock=False = 旧行为（1 张白 → 无计划）
    ck("knock=False → 无计划（旧行为）", decline_plan(H_R6, 3, drawn=R6_DRAWN, knock=False), None)
    ck("should_decline_hu(knock=False) → False", should_decline_hu(H_R6, 3, drawn=R6_DRAWN), False)
    # 存活率门
    ck("闲家 q=0.90 > 0.789 → 弃胡", should_decline_hu(H_R6, 3, drawn=R6_DRAWN, knock=True, q_est=0.90), True)
    ck("闲家 q=0.75 < 0.789 → 不弃胡", should_decline_hu(H_R6, 3, drawn=R6_DRAWN, knock=True, q_est=0.75), False)
    ck("庄家 c=8 → q*=0.90，q=0.90 不 > → 不弃胡",
       should_decline_hu(H_R6, 3, drawn=R6_DRAWN, is_dealer=True, knock=True, q_est=0.90), False)

    print("\n=== 2) 已经是爆头（f1 不会更大）→ 不许弃胡 ===")
    # 4 副露 + 白 + 1t：现在这胡就是爆头 ×2；打 1t 后仍是 4 面子+白（还是 ×2）→ 无收益
    h_bao = T(0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 9)
    ck("4 面子+白+1t 已是爆头态", any_draw_win(T(0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33), 4), True)
    ck("f1 == f0 → 无计划", decline_plan(h_bao, 4, drawn=9, knock=True), None)

    print("\n=== 3) 财飘路线不受影响（≥2 白）===")
    h_piao = T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 33)
    p2 = decline_plan(h_piao, 0, drawn=0, is_dealer=False, knock=True)
    ck("路线=piao", p2["kind"], "piao")
    ck("舍牌=白", p2["discard"], LAIZI_INDEX)
    ck("f0=2 → f1=4", (p2["fan_now"], p2["fan_next"]), (2, 4))
    ck("闲家 q=0.75 → 飘（旧结论不变）", should_decline_hu(h_piao, 0, drawn=0, knock=True, q_est=0.75), True)
    ck("少一张白 → 仍是旧行为", decline_plan(T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 8, 33), 0, drawn=8, knock=True), None)


def _state(hand, god=None, melds_row=None, seat=0):
    st = smart_bot.GameState()
    st.my_hand = hand
    st.god = god or {}
    st.my_seat = seat
    st.melds = [[], [], [], []]
    if melds_row is not None:
        st.melds[seat] = melds_row
    return st


def test_online_path():
    print("\n=== 4) 线上 smart_bot.choose_action：敲响 = 打出那张多余的牌 ===")
    st = _state(H_R6)
    st.drawn_tile = R6_DRAWN
    ck("能胡", smart_bot.can_hu(st.full_hand(), 3, False, R6_DRAWN), True)
    act = smart_bot.choose_action(st, ("draw", "5t"), 3, False, False, None, False, False)
    c13 = list(H_R6)
    c13[smart_bot.tile_from_str(act.get("tile", "东"))] -= 1
    ck("闲家 → 弃胡敲响（不胡；打掉一张后仍是「任意摸都胡」）",
       act.get("action") == "discard" and any_draw_win(c13, 3), True)
    ck("庄家 → 直接胡（q*=0.90 卡住）",
       smart_bot.choose_action(st, ("draw", "5t"), 3, False, False, None, False, True),
       {"action": "hu", "tile": ""})
    _dk = smart_bot.DECLINE_KNOCK
    try:
        smart_bot.DECLINE_KNOCK = False
        ck("DECLINE_KNOCK=False → 直接胡（旧行为）",
           smart_bot.choose_action(st, ("draw", "5t"), 3, False, False, None, False, False),
           {"action": "hu", "tile": ""})
    finally:
        smart_bot.DECLINE_KNOCK = _dk
    # 毒丸：敲响舍牌被服务端 409 拒过 → 本手牌状态回到「能胡就胡」
    st_sk = _state(H_R6)
    st_sk.drawn_tile = R6_DRAWN
    ck("skip_knock=True（舍牌被拒过）→ 直接胡",
       smart_bot.choose_action(st_sk, ("draw", "5t"), 3, False, False, None, False, False,
                               skip_knock=True),
       {"action": "hu", "tile": ""})
    # 抓打圈受限方：只能打刚摸的牌 —— 敲响要打的恰好是刚摸的 5t 时无法执行（打 6t 会违规）→ 直接胡
    st_r = _state(H_R6, {"catch_play": True, "god_discarder_seat": 1})
    st_r.drawn_tile = R6_DRAWN
    ck("圈内受限方（舍牌≠刚摸的牌）→ 直接胡",
       smart_bot.choose_action(st_r, ("draw", "5t"), 3, False, False, None, False, False),
       {"action": "hu", "tile": ""})


def test_sim_path():
    print("\n=== 5) sim：want_hu 弃胡 → choose_discard 必须打那张牌 ===")
    st = Smart(decline_hu=True, decline_knock=True, decline_knock_q=0.90)
    g = Game(seed=7)
    g.hands[1] = list(H_R6)
    g.melds[1] = [Meld(CHI, [9, 10, 11], [9, 10]),
                  Meld(PENG, [0, 0, 0], [0, 0]),
                  Meld(CHI, [13, 14, 15], [14, 15])]
    ck("want_hu → False（弃胡）", st.want_hu(g, 1, R6_DRAWN), False)
    d = st.choose_discard(g, 1)
    c13 = list(H_R6)
    c13[d] -= 1
    ck("choose_discard 打出计划的牌（打完仍「任意摸都胡」）", any_draw_win(c13, 3), True)
    ck("弃胡日志记了 knock", [e["kind"] for e in st.decline_log], ["knock"])
    # 手牌快照不一致（比如中间发生了杠/补牌，或残留到下一局）→ 指定舍牌作废，
    # 必须与「从未产生过弃胡计划」的同一局面**逐位一致**地走正常出牌判据。
    st_stale = Smart(decline_hu=True, decline_knock=True, decline_knock_q=0.90)
    g_stale = Game(seed=7)
    g_stale.hands[1] = list(H_R6)
    g_stale.melds[1] = g.melds[1]
    st_stale._decline_pending[1] = (11, tuple([0] * NUM_TILES))   # 假快照
    st_none = Smart(decline_hu=True, decline_knock=True, decline_knock_q=0.90)
    g_none = Game(seed=7)
    g_none.hands[1] = list(H_R6)
    g_none.melds[1] = g.melds[1]
    ck("手牌快照不一致 → 指定舍牌作废（= 无计划时的出牌）",
       st_stale.choose_discard(g_stale, 1) == st_none.choose_discard(g_none, 1), True)
    # 关闭敲响 → 能胡就胡（旧行为）
    st3 = Smart(decline_hu=True, decline_knock=False)
    g3 = Game(seed=7)
    g3.hands[1] = list(H_R6)
    g3.melds[1] = g.melds[1]
    ck("decline_knock=False → want_hu True", st3.want_hu(g3, 1, R6_DRAWN), True)


def _total_tiles(g):
    n = g.wall_end - g.draw_pos
    for p in range(4):
        n += sum(g.hands[p])
        n += sum(len(m.tiles) for m in g.melds[p])
        n += len(g.discards[p])
    return n


def test_sim_games(n=200):
    print(f"\n=== 6) sim {n} 局不变量 + 敲响触发率 ===")
    st0 = Smart(decline_hu=True, decline_knock=True, decline_knock_q=0.90)
    strategies = [st0, Baseline(), Baseline(), Baseline()]
    knock = piao = 0
    wins = 0
    for i in range(n):
        g = Game(seed=20000 + i)
        g.dealer = i % 4
        w, mult, scores, is_draw = g.play_round(strategies)
        assert _total_tiles(g) == 136, f"牌数不守恒 seed={i}: {_total_tiles(g)}"
        assert all(g.hands[p][t] >= 0 for p in range(4) for t in range(NUM_TILES)), f"负计数 seed={i}"
        assert all(g.chi_count[p] <= 2 for p in range(4)), f"吃>2 摊 seed={i}"
        if not is_draw and w == 0:
            wins += 1
        if (i + 1) % 50 == 0:
            _sh._best.cache_clear()
            _sh._mp.cache_clear()
    for e in st0.decline_log:
        knock += (e["kind"] == "knock")
        piao += (e["kind"] == "piao")
    ck(f"{n} 局牌数守恒/非负/吃≤2 摊", True, True)
    print(f"      敲响触发 {knock} 次、财飘触发 {piao} 次；seat0 胡 {wins}/{n} ({wins / n * 100:.1f}%)")
    ck("敲响路线在 sim 里可达（触发 > 0）", knock > 0, True)


def _snap(hand_strs, phase="draw", turn=0, drawn="", melds=None, god=None, round_no=6,
          scores=None, responding=None):
    return {"seat": 0, "phase": phase, "turn": turn, "drawn_tile": drawn, "last_discard": "",
            "my_hand": list(hand_strs), "responding_seats": responding or [],
            "melds": melds or [[], [], [], []], "round_no": round_no, "god": god or {},
            "discards": [[], [], [], []], "wall_remaining": 40, "hand_counts": [5, 13, 13, 13],
            "scores": scores if scores is not None else [0, 0, 0, 0]}


def _run_play(snaps, posts, ycb=False):
    """假 api 喂快照序列，收集 POST 动作（与 tests/test_smart_bot.py 同款）。"""
    it = iter(snaps)

    def fake_api(method, path, body=None, auth=True):
        if method == "GET":
            try:
                return {"seq": 1, "snapshot": next(it)}
            except StopIteration:
                return {"finished": True, "snapshot": {"scores": [0, 0, 0, 0]}}
        posts.append(body)
        return {}

    orig = smart_bot.api
    smart_bot.api = fake_api
    try:
        smart_bot.play("g_knock", smart_bot.GameState(), ycb)
    finally:
        smart_bot.api = orig


def test_play_full_chain():
    """全链路（假 api 喂快照）：第 6 局真机序列 = 摸 5t 弃胡敲响 → 下一摸任意牌提交 hu。"""
    print("\n=== 7) play() 全链路：弃胡敲响 → 下一摸必胡 ===")
    melds = [[{"kind": "chi", "tiles": ["7b", "8b", "9b"]},
              {"kind": "peng", "tiles": ["1w", "1w", "1w"]},
              {"kind": "chi", "tiles": ["7t", "8t", "9t"]}], [], [], []]
    hand5 = ["3t", "4t", "5t", "6t", "白"]
    posts = []
    _run_play([
        # 第 5 局末：不是我方窗口（不提交动作），只为让 bot 从 scores 差恢复庄家
        _snap(["1w"] * 13, phase="response_peng", turn=1, responding=[1], round_no=5,
              scores=[0, 0, 0, 0]),
        # 第 6 局：庄家 = seat2（第 5 局赢家 +10）→ 我是闲家（真机局面）
        _snap(hand5, drawn="5t", melds=melds, scores=[-1, -1, 10, -1]),
        # 弃胡打完后摸到 9w（任意牌）→ 应提交 hu（爆头 ×2 由服务端按摸前 13 张判定）
        _snap(["4t", "5t", "6t", "白", "9w"], drawn="9w", melds=melds,
              scores=[-1, -1, 10, -1]),
    ], posts)
    ck("链路首个提交 = discard（弃胡，不是 hu）",
       bool(posts) and posts[0].get("action") == "discard", True)
    c13 = list(H_R6)
    c13[smart_bot.tile_from_str(str(posts[0].get("tile")))] -= 1
    ck("舍牌打完 → 任意摸都胡", any_draw_win(c13, 3), True)
    ck("下一摸结算 = hu",
       len(posts) > 1 and posts[1].get("action") == "hu", True)


def main():
    test_decision_knock()
    test_online_path()
    test_sim_path()
    test_play_full_chain()
    test_sim_games()
    print("\n" + ("ALL PASS" if OK else "有 FAIL"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
