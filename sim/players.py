"""模拟器策略：接口 + Baseline（打第一张、不吃碰杠）+ Smart（复用决策引擎）。

策略方法说明（引擎调用）：
- choose_discard(game, seat) -> tile        轮到出牌，返回要打的牌索引
- want_peng(game, seat, tile) -> bool       别人弃牌，是否碰
- want_chi(game, seat, tile) -> list|None   上家弃牌，返回吃的搭子（两张手牌）或 None
- want_minggang(game, seat, tile) -> bool   别人弃牌，是否明杠
- want_own_gang(game, seat, drawn) -> (kind, tile)|None  自己回合摸牌后，是否暗杠/补杠
- want_hu(game, seat, drawn, gang_kai) -> bool  已能自摸胡时，是否**接受**这个胡
  （False = 弃胡，规则 guide §1.2 明确允许；财飘链的前提。引擎三处判胡点都会问）
"""

from mahjong.tiles import NUM_TILES, LAIZI_INDEX
from mahjong.shanten import shanten
from mahjong.decision import discard_decision, should_peng, best_chi, angang_tile, \
    should_decline_hu, SHANTEN_COST as _SC, UKEIRE_W as _UW, FAN_W as _FW

from sim.engine import ANGANG, BUGANG, CHI, MINGGANG, PENG
from sim.infer import infer_remain


class Strategy:
    name = "base"

    def choose_discard(self, game, seat):
        raise NotImplementedError

    def want_peng(self, game, seat, tile):
        return False

    def want_chi(self, game, seat, tile):
        return None

    def want_minggang(self, game, seat, tile):
        return False

    def want_own_gang(self, game, seat, drawn):
        return None

    def want_hu(self, game, seat, drawn, gang_kai=False):
        """已能胡时是否接受。默认 True（旧行为：能胡就胡）。"""
        return True


class Baseline(Strategy):
    """弱基线：打第一张非财神牌，不吃碰杠（胡由引擎自动判定）。"""

    name = "baseline"

    def choose_discard(self, game, seat):
        hand = game.hands[seat]
        for t in range(NUM_TILES):
            if t != LAIZI_INDEX and hand[t] > 0:
                return t
        return LAIZI_INDEX


class Smart(Strategy):
    """正式策略：复用 decision.py 的决策引擎。可用开关做 A/B。"""

    name = "smart"
    # dealer_policy='aggr*'：坐庄抢速（仅当本座=庄家时激活；闲家行为与基线逐决策一致）
    AGGR_POLICIES = ("aggr", "aggr_nopiao")

    def __init__(self, use_chi=True, use_peng=True, use_gang=True, fast=True, dealer_aware=False, use_ev=False, cheat=False, remain_mode=None,
                 peng_ukeire_gate=False, chi_ukeire_gate=False, peng_gate_max_shanten=None,
                 piao_enabled=True, piao_dealer_only=False, baotou_slack=1, baotou_max_shanten=1,
                 defend_dealer=False, defend_pen=40.0, defend_window=None, defend_hot_max=1, defend_mode="suit",
                 fan_est="heuristic", angang_tenpai_only=True, protect_gang=True, knock=False,
                 ycb_escape_gap=0, dealer_policy="off", decline_hu=False, decline_q=0.75,
                 decline_max_chain=3, remain_live_style=False, fan_value_melds=False,
                 wait_width=None, wait_tie_eps=0.0, claim_max_shanten=None, claim_min_wall=None,
                 keep_pairs_min=None, claim_gate_min_gain=0.0, use_minggang=True,
                 minggang_max_shanten=None, minggang_min_wall=None,
                 chi_gate_max_shanten=None, allow_laizi_discard=False, wait_full_max_wall=None,
                 chi_budget=None, chi_last_strict=False,
                 gang_tenpai_only=False, gang_draw_wall=None,
                 chi_narrow_max_accept=None, chi_narrow_min_shanten=None, chi_prefer_narrow=False,
                 shanten_cost=_SC, ukeire_w=_UW, fan_weight=_FW, god_fan_boost=1.0,
                 edge_w=0.0):
        self.use_chi = use_chi
        self.use_peng = use_peng
        self.use_gang = use_gang
        self.fast = fast  # True=进张质量(快)，False=二次进张深度(慢但更准)
        self.dealer_aware = dealer_aware  # 庄家×8 位置策略
        self.use_ev = use_ev  # EV 框架（番型抵消 1 向听）
        self.cheat = cheat  # 上帝视角：用真实牌墙剩余（仅诊断）
        self.remain_mode = remain_mode  # None=uniform, 'bayes', 'suji'（对手建模）
        self.peng_ukeire_gate = peng_ukeire_gate  # A1：向听不变但进张质量提升也碰
        self.chi_ukeire_gate = chi_ukeire_gate    # A1：向听不变但进张质量提升也吃
        self.peng_gate_max_shanten = peng_gate_max_shanten  # 碰门控最大前置向听数
        self.piao_enabled = piao_enabled          # B1：财飘开关（默认开）
        self.piao_dealer_only = piao_dealer_only  # B1：仅庄家飘（默认关）
        self.baotou_slack = baotou_slack          # B2：爆头路线向听 slack（默认 1）
        self.baotou_max_shanten = baotou_max_shanten  # B2：爆头路线最大向听（默认 1）
        self.defend_dealer = defend_dealer        # D1：庄家上家喂庄防守（默认关）
        self.defend_pen = defend_pen              # D1：喂牌惩罚分
        self.defend_window = defend_window        # D1：庄家弃牌观察窗口
        self.defend_hot_max = defend_hot_max      # D1：花色危险阈值
        self.defend_mode = defend_mode            # D1：'suit'=整花色罚；'pair'=按活互补搭子细分
        self.fan_est = fan_est                    # B4：番型估计 'heuristic'/'real'/'real_ting'
        self.angang_tenpai_only = angang_tenpai_only  # 暗杠只在自己听牌时做（2026-09 起默认）
        self.protect_gang = protect_gang          # 出牌不轻易拆可暗杠的四张（杠子保留分）
        self.knock = knock                        # R-敲响：向听并入财神做将(含七客)路线
        self.ycb_escape_gap = ycb_escape_gap      # YCB 逃回平胡同听门限（+坚持追爆头 / -早逃）
        self.dealer_policy = dealer_policy        # 坐庄策略：'off'(基线)/'aggr'(当庄抢速)/'bigfan'(×8走大番,对照)
        self.decline_hu = decline_hu              # 弃胡：能胡时若「打白续飘」EV 为正则弃（默认关=旧行为）
        self.decline_q = decline_q                # 弃胡判据里的「活过一圈」存活率估计 q
        self.decline_max_chain = decline_max_chain  # 连飘上限
        # 冻结基准候选（2026-09-20）：
        self.remain_live_style = remain_live_style  # True=复刻**线上口径**的 remain（漏算副露）→ 量化 live/sim 差距
        self.fan_value_melds = fan_value_melds      # True=番型启发式认副露（去掉"幻影七对"加分）
        self.wait_width = wait_width                # None/"tiebreak"/"full"：听口宽度前瞻（P1-a）
        self.wait_tie_eps = wait_tie_eps            # 「近似并列」容差（占最优分比例；0=严格并列）
        # 边张优先（用户假设的 A/B 开关，默认 0 = 关）：>0 时同向听内给边张（1/9>2/8>3/7）额外减分，
        # 即更想打边张。注意这与现行「整手牌进张」判据可能相反（靠张重叠只算一次）——收益以配对 A/B 为准。
        self.edge_w = edge_w
        self.claim_max_shanten = claim_max_shanten  # 非 None=只在向听 ≤ 该值时才吃/碰（鸣牌门控）
        self.claim_min_wall = claim_min_wall        # 非 None=墙剩余 < 该值后不再鸣牌
        self.keep_pairs_min = keep_pairs_min        # 非 None=无副露且对子 ≥ 该值时不鸣牌（护七对）
        self.claim_gate_min_gain = claim_gate_min_gain  # 门控要求的最小进张质量增益比例
        self.use_minggang = use_minggang            # 明杠开关（线上至今没做明杠 → 用它量化"缺多少"）
        self.minggang_max_shanten = minggang_max_shanten  # 明杠门控：杠后向听 ≤ 该值才杠
        self.minggang_min_wall = minggang_min_wall        # 明杠门控：墙剩余 ≤ 该值不再杠
        self.chi_gate_max_shanten = chi_gate_max_shanten  # 吃门控的最大前置向听数（None=不限）
        # 「吃最多两摊」（v25 规则）：引擎硬约束 ≤2，这里加**策略层**的两条轴 ——
        #   chi_budget：自己把吃的摊数上限压到该值（1 = 只吃一摊，用来量化**第二摊的边际价值**）
        #   chi_last_strict：最后一摊（第 2 摊）只接受**严格降向听**的吃（拒绝等向听的质量提升吃）=
        #     「把额度留给更值的一手」的留额度策略；若额度从不绑定，它应当 ≈ 纯损失
        self.chi_budget = chi_budget
        self.chi_last_strict = chi_last_strict
        # R15「窄搭子优先」：向听 ≥ chi_narrow_min_shanten 时，只吃「搭子剩余进张 ≤
        # chi_narrow_max_accept」的搭子；chi_prefer_narrow=同一弃牌多解时先消化进张最少的搭子
        self.chi_narrow_max_accept = chi_narrow_max_accept
        self.chi_narrow_min_shanten = chi_narrow_min_shanten
        self.chi_prefer_narrow = chi_prefer_narrow
        # 杠的两条门控（2026-09-25 用户指定，默认关）：
        #   gang_tenpai_only：只在"杠完就听牌"（= 补牌可能杠开 ×2）时才杠（含明杠/补杠/可选的暗杠放宽）
        #   gang_draw_wall ：墙剩余 < 该值且自己未听牌 → 明知赢不了也杠，用补牌多消耗墙加速流局
        self.gang_tenpai_only = gang_tenpai_only
        self.gang_draw_wall = gang_draw_wall
        # 复刻**线上**口径：线上把「手里所有牌（含财神）」都放进 allowed →
        # 财神也会成为出牌候选；sim 默认的 allowed=None 会把财神排除在候选池外。
        # 用来量化这个 live/sim 差异值多少分。
        self.allow_laizi_discard = allow_laizi_discard
        # 「终盘才用听口宽度全量打分」：wait_full 整体有害（初盘牺牲进张数），
        # 但终盘可摸次数少、落地宽度更重要 → 只在墙剩余 ≤ 该值时切到 wait_width="full"。
        self.wait_full_max_wall = wait_full_max_wall
        self.shanten_cost = shanten_cost          # 打分权重（可调，默认=decision 常量）
        self.ukeire_w = ukeire_w
        self.fan_weight = fan_weight
        self.god_fan_boost = god_fan_boost        # 手握财神时番型权重 × 该值（做大做强旋钮）
        if not use_chi:
            self.name = "smart-nochi"

    def _remain(self, game, seat):
        if self.cheat:
            return game.true_remain()
        if self.remain_mode:
            return infer_remain(game, seat, self.remain_mode)
        if self.remain_live_style:
            return self._remain_live_style(game, seat)
        return game.remain_estimate(seat)

    @staticmethod
    def _remain_live_style(game, seat):
        """复刻**线上** `game_state._recalc_remain` 的口径：visible = 我的手牌 + 4 家弃牌，
        **不含任何副露**；再按 wall/(wall+对手暗手) 比例缩放到牌墙。
        用来量化 P0-2（线上 remain 漏副露）在 sim 里值多少分。"""
        hand = game.hands[seat]
        visible = [0] * NUM_TILES
        for t in range(NUM_TILES):
            visible[t] = hand[t]
            for lst in game.discards:
                visible[t] += lst.count(t)
        hidden_opp = sum(sum(game.hands[p]) for p in range(4) if p != seat)
        wall = game.wall_end - game.draw_pos
        total = wall + hidden_opp
        if total <= 0:
            return [0.0] * NUM_TILES
        scale = wall / total
        return [max(0, 4 - visible[t]) * scale for t in range(NUM_TILES)]

    def _d1_active(self, game, seat):
        """D1 是否启用：仅当我 = 庄家上家（(seat+1)%4 == dealer）且庄家仍可能吃（chi 未满 2 摊）时。"""
        if not self.defend_dealer:
            return False
        if (seat + 1) % 4 != game.dealer:
            return False
        chi_done = sum(1 for m in game.melds[game.dealer] if m.kind == CHI)
        return chi_done < 2

    def choose_discard(self, game, seat):
        hand = game.hands[seat]  # 14 张（含刚摸的）
        nm = len(game.melds[seat])
        remain = self._remain(game, seat)
        pol = self.dealer_policy
        is_dealer = (game.dealer == seat)
        # dealer_aware 时把庄家×8 用于番型权重；piao_dealer_only 时仅用于财飘的「庄家才飘」判定。
        # bigfan：庄家走大番(×8 番型权重)，需同时开 fan_override 才有意义（对照方向）。
        dealer_big = self.dealer_aware or self.piao_dealer_only or pol == "bigfan"
        dealer = is_dealer and dealer_big
        fan_override = self.use_ev or (is_dealer and pol == "bigfan")
        # 坐庄抢速：仅当本座=庄家且 pol∈aggr* 激活；闲家恒 False（逐决策与基线一致）
        dealer_speed = is_dealer and pol in self.AGGR_POLICIES
        piao_eff = self.piao_enabled and not (is_dealer and pol == "aggr_nopiao")
        defend = self._d1_active(game, seat)
        allowed = None
        if self.allow_laizi_discard:
            # 复刻线上：allowed = 手里所有牌（含财神）→ 财神进候选池
            allowed = set(t for t in range(NUM_TILES) if hand[t] > 0)
        # 终盘门控：墙剩余 ≤ wait_full_max_wall 时把 wait_width 切成 "full"（覆盖 wait_width 设定）
        ww = self.wait_width
        if self.wait_full_max_wall is not None and (game.wall_end - game.draw_pos) <= self.wait_full_max_wall:
            ww = "full"
        return discard_decision(hand, remain, nm, depth=not self.fast,
                                dealer=dealer, fan_override=fan_override,
                                allowed=allowed,
                                youcai_bikao=game.youcai_bikao,
                                piao_enabled=piao_eff, piao_dealer_only=self.piao_dealer_only,
                                baotou_slack=self.baotou_slack, baotou_max_shanten=self.baotou_max_shanten,
                                defend_dealer=defend,
                                dealer_discards=game.discards[game.dealer] if defend else None,
                                defend_pen=self.defend_pen, defend_window=self.defend_window,
                                defend_hot_max=self.defend_hot_max, defend_mode=self.defend_mode,
                                fan_est=self.fan_est,
                                protect_gang=self.protect_gang,
                                knock=self.knock,
                                ycb_escape_gap=self.ycb_escape_gap,
                                dealer_speed=dealer_speed,
                                fan_value_melds=self.fan_value_melds,
                                wait_width=ww,
                                wait_tie_eps=self.wait_tie_eps,
                                shanten_cost=self.shanten_cost, ukeire_w=self.ukeire_w,
                                fan_weight=self.fan_weight, god_fan_boost=self.god_fan_boost,
                                edge_w=self.edge_w)

    def _dealer_aggr(self, game, seat):
        """坐庄抢速副露放宽：仅当本座=庄家且 pol∈aggr*。"""
        return (game.dealer == seat) and self.dealer_policy in self.AGGR_POLICIES

    def _claim_gate_ok(self, game, seat):
        """鸣牌门控（claim_max_shanten / claim_min_wall / keep_pairs_min）。

        · claim_max_shanten: 非 None → 只在该向听数及以下才吃/碰
        · claim_min_wall:    非 None → 墙剩余少于该值就不再鸣牌（终盘抢摸牌）
        · keep_pairs_min:    非 None 且**尚无副露**且对子数 ≥ 该值 → 不鸣牌（保护七对路线）
        """
        hand = game.hands[seat]
        nm = len(game.melds[seat])
        if self.claim_max_shanten is not None:
            from mahjong.shanten import shanten as _sh
            if _sh(hand, nm) > self.claim_max_shanten:
                return False
        if self.claim_min_wall is not None and (game.wall_end - game.draw_pos) < self.claim_min_wall:
            return False
        if self.keep_pairs_min is not None and nm == 0:
            pairs = sum(1 for c in hand if c >= 2)
            if pairs >= self.keep_pairs_min:
                return False
        return True

    def want_peng(self, game, seat, tile):
        if not self.use_peng:
            return False
        if not self._claim_gate_ok(game, seat):
            return False
        nm = len(game.melds[seat])
        gate = self.peng_ukeire_gate or self._dealer_aggr(game, seat)
        if gate:
            max_sh = self.peng_gate_max_shanten if self.peng_gate_max_shanten is not None else 1
            return should_peng(game.hands[seat], tile, nm,
                               ukeire_gate=True, remain=self._remain(game, seat),
                               gate_max_shanten=max_sh,
                               gate_min_gain=self.claim_gate_min_gain)
        return should_peng(game.hands[seat], tile, nm)

    def want_chi(self, game, seat, tile):
        if not self.use_chi:
            return None
        if not self._claim_gate_ok(game, seat):
            return None
        n_chi = sum(1 for m in game.melds[seat] if m.is_chi())
        if self.chi_budget is not None and n_chi >= self.chi_budget:
            return None
        nm = len(game.melds[seat])
        gate = self.chi_ukeire_gate or self._dealer_aggr(game, seat)
        if self.chi_last_strict and n_chi >= 1:
            # 留额度：第 2 摊只接受「严格降向听」（等价于关掉这手的 ukeire 门控）
            return best_chi(game.hands[seat], tile, nm)
        if gate:
            # 注意：吃门控的向听上限只由显式参数 chi_gate_max_shanten 决定（None=不限）。
            # 2026-09-21 曾在这里给「坐庄抢速」路径偷偷塞了一个 max_sh=1 → 让 dealer 的等向听吃
            # 被限到向听 ≤1，**静默改变了基准**（1000 局里 34 局结果不同，both_gate 从 +0.689 掉到 +0.531）。
            # 是冻结基准的「同配置复跑应逐位一致」把它抓出来的 —— 别再往老路径里加隐藏门控。
            return best_chi(game.hands[seat], tile, nm,
                            ukeire_gate=True, remain=self._remain(game, seat),
                            gate_min_gain=self.claim_gate_min_gain,
                            gate_max_shanten=self.chi_gate_max_shanten,
                            narrow_max_accept=self.chi_narrow_max_accept,
                            narrow_min_shanten=self.chi_narrow_min_shanten,
                            prefer_narrow=self.chi_prefer_narrow)
        return best_chi(game.hands[seat], tile, nm,
                        narrow_max_accept=self.chi_narrow_max_accept,
                        narrow_min_shanten=self.chi_narrow_min_shanten,
                        prefer_narrow=self.chi_prefer_narrow)

    def want_minggang(self, game, seat, tile):
        """明杠（别人弃牌 + 我手上有 3 张）。

        默认无条件 True = 旧行为；2026-09-21 加入门控参数，用冻结基准测「真做明杠时该带什么门控」
        （`no_minggang` 实测 Δ−0.161 分/局 → 明杠是线上缺口里最大的一项，但无条件做未必最优）。

        minggang_max_shanten: 要求「杠后（3 张进副露、手牌少 3 张、还没摸补牌）」的向听 ≤ 该值。
            0 = 只有杠完就听（等价暗杠的 angang_tenpai_only 口径）才杠。
        minggang_min_wall: 墙剩余 ≤ 该值时不再明杠（把杠留给更早的回合；规则 ≤20 本来就禁杠）。
        """
        if not self.use_gang or not self.use_minggang:
            return False
        hand = game.hands[seat]
        nm = len(game.melds[seat])
        if self.minggang_min_wall is not None and (game.wall_end - game.draw_pos) <= self.minggang_min_wall:
            return False
        if self.minggang_max_shanten is not None and hand[tile] >= 3:
            from mahjong.shanten import shanten as _sh
            c = list(hand)
            c[tile] -= 3          # 3 张做成明杠面子
            if _sh(c, nm + 1) > self.minggang_max_shanten:
                return False
        if not self._gang_gate_ok(game, seat, MINGGANG, tile):
            return False
        return True  # 明杠加速（杠开 ×2 潜力）

    def want_hu(self, game, seat, drawn, gang_kai=False):
        """弃胡判据（decline_hu=True 时启用）：只在「弃胡打白能续飘且 q>q*」时放弃这个胡。

        与线上 smart_bot 共用 mahjong.decision.should_decline_hu（同一判据，避免口径漂移）。
        返回 False = 弃胡，随后 choose_discard 会打出财神（decision.discard_decision 的财飘优先分支）。
        """
        if not self.decline_hu:
            return True
        chain = game.piao_count[seat]
        d = drawn if drawn is not None else -1
        if should_decline_hu(game.hands[seat], len(game.melds[seat]), drawn=d,
                             gang_kai=gang_kai, chain_count=chain,
                             is_dealer=(game.dealer == seat),
                             q_est=self.decline_q, max_chain=self.decline_max_chain):
            return False
        return True

    def _gang_gate_ok(self, game, seat, kind, tile):
        """杠的两条**用户指定**门控（2026-09-25，默认全关）。

        ① `gang_tenpai_only`：只有「杠完就听牌」才杠 = 杠后补牌存在**杠开**(×2) 的可能。
           - 明杠：3 张进副露后 `shanten(手−3, melds+1) <= 0`
           - 补杠：第 4 张进副露后 `shanten(手−1, melds+1) <= 0`
           - 暗杠：默认走更严的 `angang_tile`（摸前听牌 + 杠后仍听），不受此开关影响
        ② `gang_draw_wall`：**残局加速流局** —— 墙剩余 < 该值且自己**还没听牌**（赢不了）时，
           杠照做（用杠的补牌多消耗一张墙，加快流局，避免被对手胡走分）。它是 ① 的例外。
        """
        wall = game.wall_end - game.draw_pos
        s_now = shanten(game.hands[seat], len(game.melds[seat]))
        if self.gang_draw_wall is not None and wall < self.gang_draw_wall and s_now > 0:
            return True                      # ② 加速流局：明知赢不了也杠
        if not self.gang_tenpai_only:
            return True
        need = {ANGANG: 4, BUGANG: 1, MINGGANG: 3}[kind]
        if game.hands[seat][tile] < need:
            return False        # 张数不足 → 不许杠（也避免把负计数喂给 shanten）
        c = list(game.hands[seat])
        c[tile] -= need
        return shanten(c, len(game.melds[seat]) + 1) <= 0

    def want_own_gang(self, game, seat, drawn):
        if not self.use_gang:
            return None
        hand = game.hands[seat]
        nm = len(game.melds[seat])
        wall = game.wall_end - game.draw_pos
        # ---- 规则② 残局加速流局：未听牌 + 墙 < 阈值 → 有任何可做的杠就做（优先暗杠）----
        # 必须放在暗杠分支**之前**：`angang_tile` 的听牌门控正是这条规则要绕开的东西。
        if self.gang_draw_wall is not None and wall < self.gang_draw_wall \
                and shanten(hand, nm) > 0:
            for t in range(NUM_TILES):
                if t != LAIZI_INDEX and hand[t] >= 4:
                    return ANGANG, t
            for m in game.melds[seat]:
                if m.kind == PENG and m.tiles[0] != LAIZI_INDEX and hand[m.tiles[0]] >= 1:
                    return BUGANG, m.tiles[0]
        # ---- 规则① 常规：暗杠 4 张相同非财神 ----
        if self.angang_tenpai_only:
            t = angang_tile(hand, drawn, nm)
            if t is not None:
                return ANGANG, t
        else:
            for t in range(NUM_TILES):
                if t != LAIZI_INDEX and hand[t] >= 4:
                    if self._gang_gate_ok(game, seat, ANGANG, t):
                        return ANGANG, t
                    break
        # 补杠：已碰 + 手牌有第 4 张
        for m in game.melds[seat]:
            if m.kind == PENG and m.tiles[0] != LAIZI_INDEX and hand[m.tiles[0]] >= 1:
                if self._gang_gate_ok(game, seat, BUGANG, m.tiles[0]):
                    return BUGANG, m.tiles[0]
        return None
