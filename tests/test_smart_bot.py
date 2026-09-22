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
from mahjong.decision import chi_combos
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

    # ---------- remain 副露修正（2026-09-21；鸣牌门控的输入口径必须与 sim 一致）----------
    st_m = _state(T(0, 1, 2, 13, 14, 15, 18, 19, 20, 26, 26, 33, 33))
    st_m.melds = [[], [{"kind": "peng", "tiles": ["5w", "5w", "5w"]}], [],
                  [{"kind": "chi", "tiles": ["2t", "3t", "4t"]}]]
    st_m.hand_counts = [13, 10, 13, 10]
    st_m.wall_remaining = 40
    st_m._recalc_remain()
    scale = 40.0 / (40 + (13 + 10 + 13 + 10 - 13))
    ck("remain 计入 4 家副露：被碰掉的 5w 只剩 1 张未见",
       abs(st_m.remain[smart_bot.tile_from_str("5w")] - 1 * scale) < 1e-6, True)
    ck("remain 计入副露：吃掉的 2t 只剩 3 张未见",
       abs(st_m.remain[smart_bot.tile_from_str("2t")] - 3 * scale) < 1e-6, True)
    # raw_unseen = 未见的**原始张数**（不缩放）——绝对张数类判据（如 §22 的窄搭子门控）必须用它：
    # 用缩放过的 remain 会让同一个阈值在线上/离线含义不同（线上 ≈0.47×）。
    ck("raw_unseen 是不缩放的口径：被碰掉的 5w = 1 张、吃掉的 2t = 3 张",
       st_m.raw_unseen[smart_bot.tile_from_str("5w")] == 1
       and st_m.raw_unseen[smart_bot.tile_from_str("2t")] == 3
       and abs(st_m.raw_unseen[smart_bot.tile_from_str("5w")] * scale
               - st_m.remain[smart_bot.tile_from_str("5w")]) < 1e-6, True)

    orig_chi, orig_peng = smart_bot.best_chi, smart_bot.should_peng
    peng_kwargs, chi_kwargs = [], []
    try:
        smart_bot.best_chi = lambda *a, **k: (chi_kwargs.append(k), [1, 2])[1]   # 只测门禁，不测决策
        smart_bot.should_peng = lambda *a, **k: (peng_kwargs.append(k), True)[1]
        hand13 = T(0, 0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13)
        st = _state(hand13)
        ck("吃 1 摊 → 允许 chi",
           smart_bot.choose_action(st, ("chi", "3w"), 2, False, False, 1),
           {"action": "chi", "tile": "3w", "tiles": ["2w", "3w"]})
        ck("已有 2 摊吃 → 不 chi（v25）",
           smart_bot.choose_action(st, ("chi", "3w"), 3, False, False, 2), None)
        ck("chi_count 解析不出 → 不本地拦（交服务端 409）",
           smart_bot.choose_action(st, ("chi", "3w"), 1, False, False, None),
           {"action": "chi", "tile": "3w", "tiles": ["2w", "3w"]})
        ck("碰不占吃名额：2 摊吃但当前是碰 → 允许 peng",
           smart_bot.choose_action(st, ("peng", "3w"), 3, False, False, 2),
           {"action": "peng", "tile": "3w"})
        # ---------- 鸣牌 ukeire 门控（2026-09-21 冻结基准晋级）----------
        ck("线上碰/吃都传 ukeire_gate + remain + gate_max_shanten",
           peng_kwargs and peng_kwargs[-1].get("ukeire_gate") is True
           and peng_kwargs[-1].get("gate_max_shanten") == smart_bot.CLAIM_GATE_MAX_SHANTEN
           and peng_kwargs[-1].get("remain") is not None
           and chi_kwargs and chi_kwargs[-1].get("ukeire_gate") is True
           and chi_kwargs[-1].get("remain") is not None, True)
        # ---------- R15：吃多解时先消化"补不上"的搭子（2026-09-25 晋级）----------
        # 3000 局配对：+0.265 分/局、z=2.66（发现集 +0.392 → 确认集 +0.202，分半同号）
        ck("线上吃传 prefer_narrow（与冠军 genome 一致）",
           chi_kwargs and chi_kwargs[-1].get("prefer_narrow") is smart_bot.CHI_PREFER_NARROW
           and smart_bot.CHI_PREFER_NARROW is True, True)

        # ---------- R18：防庄（D1，目标函数按积分）----------
        # 积分流向（真机/模拟一致）：付给庄家胡 −4.24/局 = 最大流出；概率每降 1pp ≈ +0.118 分/局。
        ck("R18 防庄已上线（三套种子池化 5000 局 +0.180、z=2.18）", smart_bot.DEFEND_DEALER, True)
        cap = []
        orig_dd = smart_bot.discard_decision
        try:
            smart_bot.discard_decision = lambda *a, **k: (cap.append(k), 3)[1]
            h_def = T(0, 0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13)
            st_d = _state(h_def, seat=0)
            st_d.discards = [[], [], [], []]
            st_d.melds = [[], [], [], [{"kind": "chi", "tiles": ["2t", "3t", "4t"]}]]
            smart_bot.DEFEND_DEALER = True            # 我的下家（seat1）当庄时我才"喂庄"；庄家=seat3（我的上家）时我没风险
            smart_bot.choose_action(st_d, ("draw", "5w"), 0, False, False, None, False,
                                    None, False, False, dealer_seat=3)
            ok_not_feed = cap and cap[-1].get("defend_dealer") is False
            smart_bot.choose_action(st_d, ("draw", "5w"), 0, False, False, None, False,
                                    None, False, False, dealer_seat=1)
            ok_feed = (cap[-1].get("defend_dealer") is True
                       and cap[-1].get("dealer_discards") is not None)
            ck("D1：只在「我 = 庄家上家」时启用并传庄家弃牌", bool(ok_not_feed and ok_feed), True)
            # 庄家已吃满 2 摊 → 不再有喂庄风险 → 关闭
            st_d.melds[1] = [{"kind": "chi", "tiles": ["2t", "3t", "4t"]},
                             {"kind": "chi", "tiles": ["5t", "6t", "7t"]}]
            smart_bot.choose_action(st_d, ("draw", "5w"), 0, False, False, None, False,
                                    None, False, False, dealer_seat=1)
            ck("D1：庄家吃满 2 摊后关闭", cap[-1].get("defend_dealer"), False)
        finally:
            smart_bot.discard_decision = orig_dd
            smart_bot.DEFEND_DEALER = False

        # ---------- R16：杠的时机（2026-09-25 用户指定；规则① 已确认晋级）----------
        # ① 只在「杠完就听牌」（补牌可能杠开 ×2）时才明杠/补杠
        #    3000 局配对：+0.230 分/局、z=2.40，场均番 1.104→1.173（发现集 +0.368 → 确认集 +0.162）
        ck("线上开启 GANG_TENPAI_ONLY（与冠军 genome 一致）",
           smart_bot.GANG_TENPAI_ONLY is True, True)
        ck("杠完不听牌 → 不许明杠",
           smart_bot.gang_tenpai_ok(T(0, 0, 0, 5, 9, 13, 17, 21, 25, 27, 29, 31, 33, 33),
                                    0, 0, "ming"), False)
        ck("杠完就听牌 → 允许（1111万 234万 + 55条678条 + 白白 的 4 张…）",
           smart_bot.gang_tenpai_ok(T(0, 0, 0, 0, 1, 2, 3, 13, 13, 14, 15, 16, 33, 33),
                                    0, 0, "an") is True, True)
        ck("张数不足 → 直接拒（不把负计数喂给 shanten）",
           smart_bot.gang_tenpai_ok(T(0, 0, 1, 2, 3, 4, 5, 9, 9, 9, 13, 14, 15, 33),
                                    0, 0, "an"), False)
        # ② 残局加速流局（弱场 3000 局 +0.527、z=6.16；强场 0 次触发 ⇒ 免费期权）
        ck("线上开启 GANG_DRAW_WALL=28", smart_bot.GANG_DRAW_WALL, 28)
        #   未听牌 + 墙 25 + 手里 4 张 → 即使"杠完不听牌"也要杠（绕过听牌门控）
        gsw = smart_bot.GANG_TENPAI_ONLY, smart_bot.GANG_DRAW_WALL
        try:
            smart_bot.GANG_TENPAI_ONLY, smart_bot.GANG_DRAW_WALL = True, 28
            h_quad = T(0, 0, 0, 0, 5, 9, 13, 17, 21, 25, 27, 29, 31, 33)
            st_q = _state(h_quad)
            st_q.wall_remaining = 25
            ck("规则②：未听牌 + 墙 25 + 手里 4 张 → 杠（绕过听牌门控）",
               smart_bot.choose_action(st_q, ("draw", "8t"), 0, False, False), {"action": "gang", "tile": "1w"})
            st_hi = _state(h_quad)
            st_hi.wall_remaining = 40
            act_hi = smart_bot.choose_action(st_hi, ("draw", "8t"), 0, False, False)
            ck("规则②只在残局触发：同手牌墙 40 → 不杠（改为正常出牌）",
               (act_hi or {}).get("action"), "discard")
        finally:
            smart_bot.GANG_TENPAI_ONLY, smart_bot.GANG_DRAW_WALL = gsw

        # ---------- v26：抓打圈豁免方 ----------
        restricted = {"catch_play": True, "god_discarder_seat": 1}  # 打财神者是 1，我 0 → 受限
        exempt = {"catch_play": True, "god_discarder_seat": 0}      # 我 = 打财神者 → 豁免
        ck("圈内受限方不碰", smart_bot.choose_action(_state(hand13, restricted), ("peng", "3w")), None)
        ck("圈内受限方不吃", smart_bot.choose_action(_state(hand13, restricted), ("chi", "3w")), None)
        ck("圈内豁免方可碰", smart_bot.choose_action(_state(hand13, exempt), ("peng", "3w")),
           {"action": "peng", "tile": "3w"})
        act_exempt_chi = smart_bot.choose_action(_state(hand13, exempt), ("chi", "3w"))
        ck("圈内豁免方可吃", bool(act_exempt_chi) and act_exempt_chi.get("action") == "chi"
           and len(act_exempt_chi.get("tiles") or []) == 2, True)
        ck("god 无 god_discarder_seat（旧服务端）→ 与旧行为一致=受限",
           smart_bot.choose_action(_state(hand13, {"catch_play": True}), ("peng", "3w")), None)
        ck("无抓打圈 → 可碰", smart_bot.choose_action(_state(hand13, {}), ("peng", "3w")),
           {"action": "peng", "tile": "3w"})

        # 出牌：受限方只能打刚摸的牌；豁免方可自由择优
        # （注意手上只留 1 张白 → 打不出财飘，走普通择优出牌；财飘见下面的专项用例）
        hand14 = T(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 20, 21, 33)
        st_r = _state(hand14, restricted)
        st_e = _state(hand14, exempt)
        ck("圈内受限方只能打刚摸的牌",
           smart_bot.choose_action(st_r, ("draw", "白"), 0, False, True),
           {"action": "discard", "tile": "白"})
        act_e = smart_bot.choose_action(st_e, ("draw", "白"), 0, False, True)
        ck("圈内豁免方可自由出牌（不必打刚摸的财神）",
           bool(act_e) and act_e.get("action") == "discard" and act_e.get("tile") != "白", True)

        # ---------- 弃胡 + 财飘（2026-09-20，guide §1.2） ----------
        # 已成胡形（4 面子 + 2 财神）→ 打 1 张白仍是「任意摸都胡」= 飘合法
        win_piao = T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 33)
        st_w = _state(win_piao)
        st_w.drawn_tile = 0  # 摸到 1w（面子里的牌）；can_hu 非 YCB 只看张数+向听
        ck("能胡（非 YCB 4面子+2财神）", smart_bot.can_hu(st_w.full_hand(), 0, False, 0), True)
        ck("闲家 → 弃胡打财飘（discard 白）",
           smart_bot.choose_action(st_w, ("draw", "1w"), 0, False, False, None, False, False),
           {"action": "discard", "tile": "白"})
        ck("庄家 → 不弃胡（q* 更高，直接胡）",
           smart_bot.choose_action(st_w, ("draw", "1w"), 0, False, False, None, False, True),
           {"action": "hu", "tile": ""})
        ck("庄家未知 → 保守按庄家处理（直接胡）",
           smart_bot.choose_action(st_w, ("draw", "1w"), 0, False, False, None, False, None),
           {"action": "hu", "tile": ""})
        st_w.god = {"chain_count": 3}  # 已达连飘上限
        ck("连飘到上限 → 直接胡",
           smart_bot.choose_action(st_w, ("draw", "1w"), 0, False, False, None, False, False),
           {"action": "hu", "tile": ""})
        st_w.god = {}
        # 手上只有 1 张白 → 打白链会断，不弃胡
        h1 = T(0, 0, 0, 1, 2, 3, 13, 14, 15, 26, 26, 26, 33, 9)
        st_h1 = _state(h1)
        st_h1.drawn_tile = 9
        ck("只有 1 张财神 → 不弃胡（打白链断）",
           smart_bot.choose_action(st_h1, ("draw", "1t"), 0, False, False, None, False, False),
           {"action": "hu", "tile": ""})
        # 抓打圈受限方：只能打刚摸的牌（自摸胡照常合法）
        st_restricted = _state(win_piao, restricted)
        st_restricted.drawn_tile = 0
        ck("圈内受限方摸非白 → 不能飘（只能打刚摸的牌，但能胡就胡）",
           smart_bot.choose_action(st_restricted, ("draw", "1w"), 0, False, False, None, False, False),
           {"action": "hu", "tile": ""})
        # 受限方摸到的正好是财神 → 打刚摸的牌 == 打白，飘合法
        st_r2 = _state(win_piao, restricted)
        st_r2.drawn_tile = 33
        ck("圈内受限方摸到白 → 仍可飘（打刚摸的那张白）",
           smart_bot.choose_action(st_r2, ("draw", "白"), 0, False, False, None, False, False),
           {"action": "discard", "tile": "白"})
        # 开关关掉 → 回到旧行为（能胡就胡）
        _dh = smart_bot.DECLINE_HU
        try:
            smart_bot.DECLINE_HU = False
            ck("DECLINE_HU=False → 能胡就胡",
               smart_bot.choose_action(st_w, ("draw", "1w"), 0, False, False, None, False, False),
               {"action": "hu", "tile": ""})
        finally:
            smart_bot.DECLINE_HU = _dh
    finally:
        smart_bot.best_chi, smart_bot.should_peng = orig_chi, orig_peng

    # ---------- v2 契约：chi 必须显式发 tiles（线上 = 离线同副搭子，2026-09-22 审计修复）----------
    # 缺省时服务端取「第一组可行顺子」，而 sim/engine.py:213 吃的是 want_chi 返回的搭子 —— 两者
    # 不同源时，R15「多解先消化窄搭子」（CHI_PREFER_NARROW）只影响「吃不吃」，被消耗的搭子照旧
    # 由服务端挑，离线 +0.265 分/局 兑不了现。此处锁定「线上发的 tiles ≡ best_chi 的返回」。
    h_multi = T(0, 0, 1, 3, 4, 5, 6, 7, 8, 9, 9, 9, 13)
    st_multi = _state(h_multi)
    want = orig_chi(h_multi, smart_bot.tile_from_str("3w"), 0,
                    ukeire_gate=smart_bot.CLAIM_UKEIRE_GATE,
                    remain=st_multi.remain, prefer_narrow=smart_bot.CHI_PREFER_NARROW)
    want_tiles = None if want is None else [smart_bot.tile_to_str(want[0]),
                                            smart_bot.tile_to_str(want[1])]
    act_multi = smart_bot.choose_action(st_multi, ("chi", "3w"), 0, False, False, 0)
    ck("同一张弃牌有多解（本例 3 组）——否则本用例测不到「选哪副」",
       len(chi_combos(h_multi, smart_bot.tile_from_str("3w"))) >= 2, True)
    ck("该手牌 best_chi 有解（用例前提）", want is not None, True)
    ck("吃发的 tiles ≡ best_chi 选中的搭子（线上/离线同源）",
       (act_multi or {}).get("tiles") == want_tiles, True)

    # ---------- 坐庄抢速（dealer_speed，2026-09-21 补齐线上缺口）----------
    ds_calls = []
    orig_dd = smart_bot.discard_decision

    def _spy_dd(*a, **k):
        ds_calls.append(k.get("dealer_speed"))
        return orig_dd(*a, **k)

    try:
        smart_bot.discard_decision = _spy_dd
        h_ds = T(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 21)
        s_ds = _state(h_ds)
        s_ds.drawn_tile = 21
        s_ds.wall_remaining = 60
        smart_bot.choose_action(s_ds, ("draw", "1b"), 0, False, False, None, False, True)
        smart_bot.choose_action(s_ds, ("draw", "1b"), 0, False, False, None, False, False)
        smart_bot.choose_action(s_ds, ("draw", "1b"), 0, False, False, None, False, None)
        ck("坐庄抢速：庄家 True / 闲家 False / 未知 False",
           ds_calls == [True, False, False], True)
    finally:
        smart_bot.discard_decision = orig_dd

    # ---------- YCB 专用档位（2026-09-21 冻结基准 YCB 专项）----------
    ycb_kw = []
    orig_dd2 = smart_bot.discard_decision

    def _spy_dd2(*a, **k):
        ycb_kw.append((k.get("fan_override"), k.get("ycb_escape_gap")))
        return orig_dd2(*a, **k)

    try:
        smart_bot.discard_decision = _spy_dd2
        s_y = _state(T(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 21))
        s_y.drawn_tile = 21
        s_y.wall_remaining = 60
        smart_bot.choose_action(s_y, ("draw", "1b"), 0, True, False, None, False, False)   # YCB
        smart_bot.choose_action(s_y, ("draw", "1b"), 0, False, False, None, False, False)  # 非 YCB
        ck("YCB 档位：EV 框架始终开；逃回门限 YCB=+1 / 非 YCB=0",
           ycb_kw == [(True, smart_bot.YCB_ESCAPE_GAP), (True, 0)], True)
    finally:
        smart_bot.discard_decision = orig_dd2

    # ---------- 明杠 / 补杠（2026-09-21 冻结基准：不加门控最好）----------
    def _st_ming(hand, wall=60, god=None, melds_row=None):
        s = _state(hand, god or {}, melds_row)
        s.wall_remaining = wall
        return s

    h_mg = T(2, 2, 2, 4, 5, 6, 10, 11, 12, 20, 20, 20, 33)          # 手里 3 张 3w
    ck("明杠：手里 3 张同一弃牌 → gang（优先于碰）",
       smart_bot.choose_action(_st_ming(h_mg), ("peng", "3w"), 0, False, False, None, False, True),
       {"action": "gang", "tile": "3w"})
    ck("明杠：财神不能被杠（3 张白板 → 不 gang）",
       smart_bot.choose_action(_st_ming(T(33, 33, 33, 0, 1, 2, 4, 5, 6, 10, 11, 12, 20)),
                               ("peng", "白"), 0, False, False, None, False, True),
       None)
    ck("明杠：墙剩 ≤20（最后 10 墩禁杠）→ 不 gang",
       smart_bot.choose_action(_st_ming(h_mg, wall=20), ("peng", "3w"), 0, False, False, None, False, True),
       None)
    ck("明杠：抓打圈受限方不能明杠",
       smart_bot.choose_action(_st_ming(h_mg, god={"catch_play": True, "god_discarder_seat": 1}),
                               ("peng", "3w"), 0, False, False, None, False, True),
       None)
    ck("明杠：skip_gang 置位后不再提杠",
       smart_bot.choose_action(_st_ming(h_mg), ("peng", "3w"), 0, False, False, None, False, True,
                               skip_gang=True) is None
       or smart_bot.choose_action(_st_ming(h_mg), ("peng", "3w"), 0, False, False, None, False, True,
                                  skip_gang=True).get("action") != "gang", True)

    # 补杠：已碰 5w + 手里第 4 张
    h_bg = T(4, 0, 1, 2, 3, 4, 5, 10, 11, 12, 33, 33, 20, 21)       # 含 1 张 5w（碰的 3 张在副露里）
    bg_row = [{"kind": "peng", "tiles": ["5w", "5w", "5w"]}]
    st_bg = _st_ming(h_bg, melds_row=bg_row)
    st_bg.drawn_tile = 24
    ck("补杠：已碰 + 手里第 4 张 → gang",
       smart_bot.choose_action(st_bg, ("draw", "1b"), 1, False, False, None, False, True),
       {"action": "gang", "tile": "5w"})
    st_bg2 = _st_ming(T(0, 1, 2, 3, 5, 6, 7, 10, 11, 12, 33, 33, 20), melds_row=bg_row)  # 手里没有 5w
    st_bg2.drawn_tile = 24
    ck("补杠：手里没有第 4 张 → 不提杠",
       (smart_bot.choose_action(st_bg2, ("draw", "1b"), 1, False, False, None, False, True) or {}).get("action") != "gang",
       True)
    ck("peng_meld_tiles 只认 kind==peng 且排除财神",
       _state(T(0), melds_row=[{"kind": "peng", "tiles": ["5w", "5w", "5w"]},
                               {"kind": "chi", "tiles": ["1w", "2w", "3w"]},
                               {"kind": "peng", "tiles": ["白", "白", "白"]}]).peng_meld_tiles(),
       [smart_bot.tile_from_str("5w")])

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
             responding=None, round_no=1):
        """hand_strs = 协议字符串列表（快照 my_hand 原样；draw 阶段含刚摸的牌）。"""
        return {"seat": 0, "phase": phase, "turn": turn, "drawn_tile": drawn,
                "last_discard": discard, "my_hand": list(hand_strs),
                "responding_seats": responding if responding is not None else [],
                "melds": melds or [[], [], [], []], "round_no": round_no,
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
    hand10 = ["1w", "1w", "2w", "2w", "5w", "4w", "5w", "6w", "7w", "8w"]  # 只留 2 张 2w（否则会先明杠）
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

        # 豁免方 + 手里 3 张 → 优先明杠（与 sim/engine 的 明杠 > 碰 优先级一致）
        posts_g = []
        run_play([snap(["1w", "1w", "2w", "2w", "2w", "4w", "5w", "6w", "7w", "8w"],
                       phase="response_peng", turn=1, discard="2w",
                       responding=[0], melds=[chi_row, [], [], []],
                       god={"catch_play": True, "god_discarder_seat": 0})], posts_g)
        ck("play() 豁免方手里 3 张 → 提交明杠",
           len(posts_g) == 1 and posts_g[0].get("action") == "gang", True)
    finally:
        smart_bot.should_peng = orig_peng2

    # v31（2026-09-11）局间 5s 停顿：phase="settled" 不发动作，且要能继续跑到下一局
    posts_settled = []
    run_play([snap(["1w"], phase="settled", round_no=1)], posts_settled)
    ck("play() settled 阶段不提交动作", posts_settled, [])

    posts_after = []
    run_play([snap(["1w"], phase="settled", round_no=1),
              snap(["1w", "1w", "1w", "2w", "2w", "2w", "3w", "3w", "3w",
                    "4w", "5w", "6w", "7w", "9w"], drawn="9w", round_no=2)], posts_after)
    ck("play() settled 后继续处理下一局（提交 discard）",
       len(posts_after) == 1 and posts_after[0].get("action") == "discard", True)

    # ---------- 弃胡打财飘：play() 全链路 + 409 poison pill ----------
    # 已成胡形（4 面子 + 2 白）摸到面子里的 1w：**闲家**应弃胡打白（seat=1，首局庄家=seat0）；
    # 打白若被 409 拒 → 改胡，不得重提。
    win_piao_strs = ["1w", "1w", "1w", "2w", "3w", "4w", "5t", "6t", "7t", "9b", "9b", "9b", "白", "白"]

    def snap_non_dealer(**kw):
        s = snap(win_piao_strs, **kw)
        s["seat"] = 1  # 首局庄家 = seat 0 → seat 1 = 闲家（弃胡只在闲家触发）
        s["turn"] = 1  # 必须 turn==seat 才是「我的出牌回合」
        return s

    posts_piao = []
    run_play([snap_non_dealer(drawn="1w")], posts_piao)
    ck("play() 闲家弃胡打财飘（提交 discard 白）",
       len(posts_piao) == 1 and posts_piao[0] == {"action": "discard", "tile": "白"}, True)

    posts_409 = []
    n_post = [0]

    def fake_api_409(method, path, body=None, auth=True):
        if method == "GET":
            if len(posts_409) >= 2:
                return {"finished": True, "snapshot": {"scores": [0, 0, 0, 0]}}
            return {"seq": 1, "snapshot": snap_non_dealer(drawn="1w")}
        n_post[0] += 1
        posts_409.append(body)
        if n_post[0] == 1:
            raise smart_bot.ApiError(409, '{"code":"INVALID_ACTION"}')  # 服务端不认这次飘
        return {}

    _orig_api = smart_bot.api
    smart_bot.api = fake_api_409
    try:
        smart_bot.play("g409", smart_bot.GameState(), False)
    finally:
        smart_bot.api = _orig_api
    ck("打财神被 409 拒后不重提，改提交 hu（poison pill）",
       posts_409 == [{"action": "discard", "tile": "白"}, {"action": "hu", "tile": ""}], True)

    # 提杠被 409 拒 → 不重提（明杠回退到碰/过），防历史那种重提死循环
    posts_g409 = []
    n_g = [0]
    n_get = [0]

    def fake_api_gang409(method, path, body=None, auth=True):
        if method == "GET":
            n_get[0] += 1
            # 真实服务端到点会推进窗口；假 api 必须自己兜底，否则「无动作」时会无限轮询同一快照
            if len(posts_g409) >= 2 or n_get[0] > 8:
                return {"finished": True, "snapshot": {"scores": [0, 0, 0, 0]}}
            return {"seq": 1, "snapshot": snap(["1w", "1w", "2w", "2w", "2w", "4w", "5w", "6w", "7w", "8w"],
                                               phase="response_peng", turn=1, discard="2w",
                                               responding=[0], melds=[chi_row, [], [], []],
                                               god={"catch_play": True, "god_discarder_seat": 0})}
        n_g[0] += 1
        posts_g409.append(body)
        if n_g[0] == 1:
            raise smart_bot.ApiError(409, '{"code":"INVALID_ACTION"}')
        return {}

    _orig_api2 = smart_bot.api
    smart_bot.api = fake_api_gang409
    try:
        smart_bot.play("g409b", smart_bot.GameState(), False)
    finally:
        smart_bot.api = _orig_api2
    ck("提杠被 409 拒后不重提（poison pill）",
       len(posts_g409) >= 1 and posts_g409[0].get("action") == "gang"
       and all(p.get("action") != "gang" for p in posts_g409[1:]), True)

    # ---------- CLI：令牌可写 `@文件`（免明文进 argv/进程列表；match_session.py 走这条）----------
    import tempfile
    tf = os.path.join(tempfile.gettempdir(), "_dsh_token_probe.txt")
    with open(tf, "w", encoding="utf-8") as f:
        f.write("  deadbeef" + "0" * 56 + "\n")
    try:
        ck("令牌 @文件 → 读文件并 strip",
           smart_bot._token_from("@" + tf), "deadbeef" + "0" * 56)
        ck("字面令牌照旧（含不以 @ 开头）",
           smart_bot._token_from("abc123"), "abc123")
        ck("_parse_args 支持 @文件 + 编号",
           smart_bot._parse_args(["smart_bot.py", "@" + tf, "gm"])[:2],
           ("deadbeef" + "0" * 56, "gm"))
    finally:
        os.remove(tf)

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
