"""上线 bot（smart_bot.py）协议/规则回归测试。

锁定 2026-09-09 对齐 guide v21/v25/v26 的修正：
- `can_hu` 在 YouCaiBiKao（有财必拷响）下曾用 `shanten_baotou(hand) != -1` 判「须爆头」，
  而 shanten_baotou 对 14 张胡牌最小值恒为 0（永不为 -1）→ 条件恒真 → 持财神的胡全被拒，
  YCB 赛事里 bot 会主动把胡牌打掉。现统一到 mahjong.fan.ycb_can_hu（摸前 13 张任意摸都胡
  为真·爆头；杠开免爆头）。
- v25：本人吃摊数 = melds[seat] 中 kind=="chi" 的组数，满 2 不再吃（服务端 409 强制）。
- v26：抓打圈受限 ⇔ catch_play 且本人非打财神者；打财神者本人豁免（可吃/碰、可任意出牌）。

注意：导入 smart_bot 会按其 BOT_ID 打开 data/smart_<id>.log（本测试用 "test"）。
"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# smart_bot 以脚本方式读 sys.argv，导入前先补齐（argv[2] = 编号 → 日志落 data/smart_test.log）
sys.argv = ["smart_bot.py", "test", "test"]

from mahjong.tiles import list_to_count
import smart_bot


def T(*tiles):
    return list_to_count(tiles)


def _state(hand, god=None, melds_row=None, seat=0):
    """手搓 GameState（只填 choose_action 需要的字段）。"""
    st = smart_bot.GameState()
    st.my_hand = hand
    st.god = god or {}
    st.my_seat = seat
    st.melds = [[], [], [], []]
    if melds_row is not None:
        st.melds[seat] = melds_row
    return st


def main():
    ok = True

    def ck(name, got, want=True):
        nonlocal ok
        o = got == want
        ok = ok and o
        print(f"[{'OK  ' if o else 'FAIL'}] {name}: got={got} want={want}")

    # ---------- can_hu：YCB 判据（guide v21② / 2026-09-03 修复同步到上线 bot） ----------
    bao = T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33, 27)  # 4面子 + 白 + 东（白单吊）
    ck("YCB 真爆头 can_hu", smart_bot.can_hu(bao, 0, True, 27), True)
    ck("非 YCB 真爆头 can_hu", smart_bot.can_hu(bao, 0, False, 27), True)

    h14_bt = T(0, 0, 1, 1, 2, 2, 3, 3, 4, 5, 33, 33, 33, 33)  # 3对+3单+4白 摸 4w
    ck("YCB 4白爆头 can_hu（v21②）", smart_bot.can_hu(h14_bt, 0, True, 3), True)

    plain_lz = T(0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13, 13, 33)  # 1w2w[白] 456w789w 111t 55t
    ck("YCB 平胡(财神在面子内) can_hu=False", smart_bot.can_hu(plain_lz, 0, True, 13), False)
    ck("YCB 杠开免爆头 can_hu", smart_bot.can_hu(plain_lz, 0, True, 13, True), True)
    ck("非 YCB 平胡 can_hu", smart_bot.can_hu(plain_lz, 0, False, 13), True)

    ck("13 张不给胡", smart_bot.can_hu(T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 33), 0, False, 33), False)
    ck("无财神平胡 can_hu", smart_bot.can_hu(T(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 5, 8, 8), 0, True, 8), True)

    # ---------- v25：吃最多 2 摊（按 melds[seat] 里 kind=="chi" 计数） ----------
    chi_row = [{"kind": "chi", "tiles": ["1w", "2w", "3w"]},
               {"kind": "peng", "tiles": ["5t", "5t", "5t"]}]
    ck("chi_meld_count 只数 chi", _state(T(0), melds_row=chi_row).chi_meld_count(), 1)
    ck("chi_meld_count 空副露 = 0", _state(T(0), melds_row=[]).chi_meld_count(), 0)
    ck("chi_meld_count 非 dict 格式 → None", _state(T(0), melds_row=[["1w", "2w", "3w"]]).chi_meld_count(), None)

    orig_chi, orig_peng = smart_bot.should_chi, smart_bot.should_peng
    try:
        smart_bot.should_chi = lambda *a, **k: True   # 只测门禁，不测决策
        smart_bot.should_peng = lambda *a, **k: True
        hand13 = T(0, 0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13)
        st = _state(hand13)
        ck("吃 1 摊 → 允许 chi",
           smart_bot.choose_action(st, ("chi", "3w"), 2, False, False, 1),
           {"action": "chi", "tile": "3w"})
        ck("已有 2 摊吃 → 不 chi（v25）",
           smart_bot.choose_action(st, ("chi", "3w"), 3, False, False, 2), None)
        ck("chi_count 解析不出 → 不本地拦（交服务端 409）",
           smart_bot.choose_action(st, ("chi", "3w"), 1, False, False, None),
           {"action": "chi", "tile": "3w"})
        ck("碰不占吃名额：2 摊吃但当前是碰 → 允许 peng",
           smart_bot.choose_action(st, ("peng", "3w"), 3, False, False, 2),
           {"action": "peng", "tile": "3w"})

        # ---------- v26：抓打圈豁免方 ----------
        restricted = {"catch_play": True, "god_discarder_seat": 1}  # 打财神者是 1，我 0 → 受限
        exempt = {"catch_play": True, "god_discarder_seat": 0}      # 我 = 打财神者 → 豁免
        ck("圈内受限方不碰", smart_bot.choose_action(_state(hand13, restricted), ("peng", "3w")), None)
        ck("圈内受限方不吃", smart_bot.choose_action(_state(hand13, restricted), ("chi", "3w")), None)
        ck("圈内豁免方可碰", smart_bot.choose_action(_state(hand13, exempt), ("peng", "3w")),
           {"action": "peng", "tile": "3w"})
        ck("圈内豁免方可吃", smart_bot.choose_action(_state(hand13, exempt), ("chi", "3w")),
           {"action": "chi", "tile": "3w"})
        ck("god 无 god_discarder_seat（旧服务端）→ 与旧行为一致=受限",
           smart_bot.choose_action(_state(hand13, {"catch_play": True}), ("peng", "3w")), None)
        ck("无抓打圈 → 可碰", smart_bot.choose_action(_state(hand13, {}), ("peng", "3w")),
           {"action": "peng", "tile": "3w"})

        # 出牌：受限方只能打刚摸的牌；豁免方可自由择优（这里摸白，且非 YCB → 池里不用打财神）
        hand14 = T(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 33, 33, 33)
        st_r = _state(hand14, restricted)
        st_e = _state(hand14, exempt)
        ck("圈内受限方只能打刚摸的牌",
           smart_bot.choose_action(st_r, ("draw", "白"), 0, False, True),
           {"action": "discard", "tile": "白"})
        act_e = smart_bot.choose_action(st_e, ("draw", "白"), 0, False, True)
        ck("圈内豁免方可自由出牌（不必打刚摸的财神）",
           bool(act_e) and act_e.get("action") == "discard" and act_e.get("tile") != "白", True)
    finally:
        smart_bot.should_chi, smart_bot.should_peng = orig_chi, orig_peng

    # ---------- play() 全链路冒烟：假 api 喂快照，验证 v25/v26 新字段解析不炸 ----------
    def run_play(snaps, posts, ycb=False):
        """按顺序喂快照（最后一个之后返回 finished），收集 POST 动作。"""
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
            smart_bot.play("g1", smart_bot.GameState(), ycb)
        finally:
            smart_bot.api = orig

    def snap(hand_strs, phase="draw", turn=0, drawn="", melds=None, god=None, discard="",
             responding=None):
        """hand_strs = 协议字符串列表（快照 my_hand 原样；draw 阶段含刚摸的牌）。"""
        return {"seat": 0, "phase": phase, "turn": turn, "drawn_tile": drawn,
                "last_discard": discard, "my_hand": list(hand_strs),
                "responding_seats": responding if responding is not None else [],
                "melds": melds or [[], [], [], []],
                "god": god or {}, "discards": [[], [], [], []], "wall_remaining": 60,
                "hand_counts": [14, 13, 13, 13], "scores": [0, 0, 0, 0]}

    posts = []
    run_play([snap(["1w", "1w", "1w", "2w", "2w", "2w", "3w", "3w", "3w",
                    "4w", "5w", "6w", "7w", "9w"], drawn="9w")], posts)
    ck("play() 出牌回合提交 discard", len(posts) == 1 and posts[0].get("action") == "discard", True)

    # YCB 真·爆头：必须是 hu（旧判据下这里会变成 discard —— 把胡牌打掉）
    posts_hu = []
    run_play([snap(["1w", "1w", "1w", "2w", "2w", "2w", "3w", "3w", "3w",
                    "4w", "4w", "4w", "白", "东"], drawn="东")], posts_hu, ycb=True)
    ck("play() YCB 真爆头提交 hu", len(posts_hu) == 1 and posts_hu[0].get("action") == "hu", True)

    # YCB 非爆头（财神在面子内的平胡）→ 不得提交 hu
    posts_no = []
    run_play([snap(["1w", "2w", "4w", "5w", "6w", "7w", "8w", "9w",
                    "1t", "1t", "1t", "5t", "5t", "白"], drawn="5t")], posts_no, ycb=True)
    ck("play() YCB 非爆头不提交 hu",
       bool(posts_no) and posts_no[0].get("action") == "discard", True)

    # 圈内受限方在碰窗口 → 不提交（窗口自然走满）：10 张手牌 + 1 组吃副露 = 13 张
    # 两个子用例都用 should_peng=True 打桩，只验证「圈」的门禁（不掺决策引擎判断）
    chi_row = [{"kind": "chi", "tiles": ["1w", "2w", "3w"]}]
    hand10 = ["1w", "1w", "2w", "2w", "2w", "4w", "5w", "6w", "7w", "8w"]
    orig_peng2 = smart_bot.should_peng
    smart_bot.should_peng = lambda *a, **k: True
    try:
        posts_r = []
        run_play([snap(hand10, phase="response_peng", turn=1, discard="2w",
                       responding=[0], melds=[chi_row, [], [], []],
                       god={"catch_play": True, "god_discarder_seat": 1})], posts_r)
        ck("play() 圈内受限方不碰（无 POST）", posts_r, [])

        # 同一窗口但本人是打财神者（豁免）→ 应提交
        posts_e = []
        run_play([snap(hand10, phase="response_peng", turn=1, discard="2w",
                       responding=[0], melds=[chi_row, [], [], []],
                       god={"catch_play": True, "god_discarder_seat": 0})], posts_e)
        ck("play() 圈内豁免方可碰（有 POST）",
           len(posts_e) == 1 and posts_e[0].get("action") == "peng", True)
    finally:
        smart_bot.should_peng = orig_peng2

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
