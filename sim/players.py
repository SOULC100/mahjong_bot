"""模拟器策略：接口 + Baseline（打第一张、不吃碰杠）+ Smart（复用决策引擎）。

策略方法说明（引擎调用）：
- choose_discard(game, seat) -> tile        轮到出牌，返回要打的牌索引
- want_peng(game, seat, tile) -> bool       别人弃牌，是否碰
- want_chi(game, seat, tile) -> list|None   上家弃牌，返回吃的搭子（两张手牌）或 None
- want_minggang(game, seat, tile) -> bool   别人弃牌，是否明杠
- want_own_gang(game, seat, drawn) -> (kind, tile)|None  自己回合摸牌后，是否暗杠/补杠
"""

from mahjong.tiles import NUM_TILES, LAIZI_INDEX
from mahjong.decision import discard_decision, should_peng, best_chi, angang_tile, \
    SHANTEN_COST as _SC, UKEIRE_W as _UW, FAN_W as _FW

from sim.engine import ANGANG, BUGANG, CHI, PENG
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
                 ycb_escape_gap=0, dealer_policy="off",
                 shanten_cost=_SC, ukeire_w=_UW, fan_weight=_FW, god_fan_boost=1.0):
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
        return game.remain_estimate(seat)

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
        return discard_decision(hand, remain, nm, depth=not self.fast,
                                dealer=dealer, fan_override=fan_override,
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
                                shanten_cost=self.shanten_cost, ukeire_w=self.ukeire_w,
                                fan_weight=self.fan_weight, god_fan_boost=self.god_fan_boost)

    def _dealer_aggr(self, game, seat):
        """坐庄抢速副露放宽：仅当本座=庄家且 pol∈aggr*。"""
        return (game.dealer == seat) and self.dealer_policy in self.AGGR_POLICIES

    def want_peng(self, game, seat, tile):
        if not self.use_peng:
            return False
        nm = len(game.melds[seat])
        gate = self.peng_ukeire_gate or self._dealer_aggr(game, seat)
        if gate:
            max_sh = self.peng_gate_max_shanten if self.peng_gate_max_shanten is not None else 1
            return should_peng(game.hands[seat], tile, nm,
                               ukeire_gate=True, remain=self._remain(game, seat),
                               gate_max_shanten=max_sh)
        return should_peng(game.hands[seat], tile, nm)

    def want_chi(self, game, seat, tile):
        if not self.use_chi:
            return None
        nm = len(game.melds[seat])
        gate = self.chi_ukeire_gate or self._dealer_aggr(game, seat)
        if gate:
            return best_chi(game.hands[seat], tile, nm,
                            ukeire_gate=True, remain=self._remain(game, seat))
        return best_chi(game.hands[seat], tile, nm)

    def want_minggang(self, game, seat, tile):
        if not self.use_gang:
            return False
        return True  # 明杠加速（杠开 ×2 潜力）

    def want_own_gang(self, game, seat, drawn):
        if not self.use_gang:
            return None
        hand = game.hands[seat]
        nm = len(game.melds[seat])
        # 暗杠：4 张相同非财神。angang_tenpai_only=True（默认）只在自己听牌时杠（含七对保护）
        if self.angang_tenpai_only:
            t = angang_tile(hand, drawn, nm)
            if t is not None:
                return ANGANG, t
        else:
            for t in range(NUM_TILES):
                if t != LAIZI_INDEX and hand[t] >= 4:
                    return ANGANG, t
        # 补杠：已碰 + 手牌有第 4 张
        for m in game.melds[seat]:
            if m.kind == PENG and m.tiles[0] != LAIZI_INDEX and hand[m.tiles[0]] >= 1:
                return BUGANG, m.tiles[0]
        return None
