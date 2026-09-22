"""杭州麻将离线模拟器引擎：牌墙 / 发牌 / 回合循环 / 吃碰杠 / 财神 / 自摸胡 / 流局 / 计分。

规则（对齐平台 guide-rules）：
- 136 张，白板 = 财神（百搭，可替代任意牌）
- 只能自摸胡，禁止点炮
- 最后 10 墩（20 张）保留不摸，摸完流局；最后 10 墩内禁杠
- 吃最多 2 摊，碰/杠不限；财神不能吃碰杠
- 财飘：打 1 财神（手留 ≥1 财神做将）飘一次，结算 ×2^piao；打非财神链断（piao 归 0）
- 计分：庄家 ×8 / 闲家 ×1（底分默认 1）
"""

import random

from mahjong.tiles import NUM_TILES, LAIZI_INDEX, is_number
from mahjong.win import split_laizi
from mahjong.fan import calc_fan, any_draw_win
from mahjong.shanten import shanten

# 副露类型
PENG = 0
CHI = 1
ANGANG = 2      # 暗杠（手牌 4 张）
MINGGANG = 3    # 明杠（别人弃牌，手牌 3 张）
BUGANG = 4      # 补杠（碰后摸到第 4 张）

KIND_NAMES = {PENG: "peng", CHI: "chi", ANGANG: "angang", MINGGANG: "minggang", BUGANG: "bugang"}


class Meld:
    __slots__ = ("kind", "tiles", "hand_tiles", "from_seat")

    def __init__(self, kind, tiles, hand_tiles, from_seat=-1):
        self.kind = kind                 # PENG/CHI/ANGANG/MINGGANG/BUGANG
        self.tiles = list(tiles)         # 完整面子（含弃牌）
        self.hand_tiles = list(hand_tiles)  # 从手里扣掉的牌
        self.from_seat = from_seat       # 吃碰杠来源座位（-1 = 暗杠/补杠）

    def is_gang(self):
        return self.kind in (ANGANG, MINGGANG, BUGANG)

    def is_chi(self):
        return self.kind == CHI


class Game:
    def __init__(self, seed=None, youcai_bikao=False, base_score=1):
        self.rng = random.Random(seed)
        self.youcai_bikao = youcai_bikao
        self.base_score = base_score
        self.wall = []
        self.hands = [[0] * NUM_TILES for _ in range(4)]
        self.melds = [[] for _ in range(4)]
        self.discards = [[] for _ in range(4)]
        self.chi_count = [0] * 4
        self.piao_count = [0] * 4  # 财飘次数/座位（打出财神且手留≥1财神 = 飘一次）
        self.dealer = 0
        self.last_discard_tile = -1
        self.last_discard_seat = -1
        self._build_wall()

    # ---- 牌墙 ----
    def _build_wall(self):
        wall = []
        for t in range(NUM_TILES):
            wall.extend([t] * 4)
        self.rng.shuffle(wall)
        self.wall = wall
        self.draw_pos = 0
        self.wall_end = len(wall)

    def _remaining(self):
        """剩余可摸张数（含杠替换的墙尾）。"""
        return self.wall_end - self.draw_pos

    def _draw(self):
        t = self.wall[self.draw_pos]
        self.draw_pos += 1
        return t

    def _kang_draw(self):
        self.wall_end -= 1
        return self.wall[self.wall_end]

    # ---- 发牌 ----
    def _deal(self):
        for _ in range(13):
            for p in range(4):
                self.hands[p][self._draw()] += 1
        # 庄家起手 14 张（多摸一张）
        self.hands[self.dealer][self._draw()] += 1

    # ---- 剩余牌估算（供策略参考，仅用公开信息） ----
    def remain_estimate(self, seat):
        visible = [0] * NUM_TILES
        for t in range(NUM_TILES):
            visible[t] = self.hands[seat][t]
            for p in range(4):
                visible[t] += self.discards[p].count(t)
                for m in self.melds[p]:  # 副露（含暗杠）都是公开信息
                    visible[t] += m.tiles.count(t)
        return [max(0, 4 - visible[t]) for t in range(NUM_TILES)]

    def true_remain(self):
        """真实牌墙剩余（上帝视角，仅用于诊断对手建模的上限收益）。"""
        remain = [0] * NUM_TILES
        for i in range(self.draw_pos, self.wall_end):
            remain[self.wall[i]] += 1
        return remain

    # ---- 主循环 ----
    def play_round(self, strategies):
        """打一局，返回 (winner, multiplier, scores, is_draw)。"""
        self._deal()
        cur = self.dealer
        # 庄家起手 14 张，直接出牌
        d = strategies[cur].choose_discard(self, cur)
        self._discard(cur, d)
        cur = (cur + 1) % 4
        while True:
            if self._remaining() <= 20:
                return self._draw_result()
            # 处理对上一张弃牌的吃碰杠
            claim = self._resolve_claims(strategies)
            if claim:
                claimer, meld = claim
                self._apply_claim(claimer, meld)
                if meld.kind == MINGGANG:
                    # 明杠：补牌 + 杠开检查（YCB 下杠开豁免爆头，gang_kai=True）
                    rt = self._kang_draw()
                    self.hands[claimer][rt] += 1
                    if self._can_win(claimer, drawn_tile=rt, gang_kai=True) and \
                            strategies[claimer].want_hu(self, claimer, rt, True):
                        return self._win_result(claimer, gang_kai=True, drawn_tile=rt)
                d = strategies[claimer].choose_discard(self, claimer)
                self._discard(claimer, d)
                cur = (claimer + 1) % 4
                continue
            # 无人要：cur 摸牌
            t = self._draw()
            self.hands[cur][t] += 1
            if self._can_win(cur, drawn_tile=t, gang_kai=False) and \
                    strategies[cur].want_hu(self, cur, t, False):
                return self._win_result(cur, gang_kai=False, drawn_tile=t)
            if self._try_own_gang(strategies, cur, t):
                rt = self._kang_draw()
                self.hands[cur][rt] += 1
                if self._can_win(cur, drawn_tile=rt, gang_kai=True) and \
                        strategies[cur].want_hu(self, cur, rt, True):
                    return self._win_result(cur, gang_kai=True, drawn_tile=rt)
            d = strategies[cur].choose_discard(self, cur)
            self._discard(cur, d)
            cur = (cur + 1) % 4
        return self._draw_result()

    def _discard(self, seat, tile):
        self.hands[seat][tile] -= 1
        self.discards[seat].append(tile)
        self.last_discard_tile = tile
        self.last_discard_seat = seat
        # 财飘跟踪（2026-09-20 修正为规则口径，guide §1.2）：
        # 「飘」= 打出财神**且打完后仍「任意摸都胡」**（爆头态续听），此时动作链 +1；
        # 打出非飘非杠的牌（含**非爆头态**打白板）→ 链断重新计数。
        # 旧实现只判「手里还剩 ≥1 张白」就记飘 → 实测 2000 局里 1716 次非法记账（虽未进入结算），
        # 一旦打开弃胡就会把飘的价值算高，故与 mahjong.decision.piao_after_discard 对齐。
        if tile == LAIZI_INDEX and any_draw_win(self.hands[seat], len(self.melds[seat])):
            self.piao_count[seat] += 1
        else:
            self.piao_count[seat] = 0

    def _can_win(self, seat, drawn_tile=-1, gang_kai=False):
        """能否自摸胡（含 YouCaiBiKao 约束）。

        2026-09-03 修正 YCB 判据：旧代码用 `shanten_baotou(hand) != -1` 拦截「有财神须爆头」，
        但 shanten_baotou 对 14 张胡牌的最小值恒为 0（永不为 -1），导致 YCB 下所有持财神的
        胡（含真爆头/七客）一律被拒。正确定义：
        - 手无财神 → 平胡随便胡；
        - 杠开（gang_kai=True）→ YCB 免爆头胡法（规则明确列出「必须爆头/杠开才能胡」）；
        - 有财神普通自摸 → 必须真·爆头 = 摸前 13 张已是「任意摸都胡」
          （4面子+财神单吊 或 6对+财神/七客），由 _any_draw_win(摸前13) 判定。
        """
        nm = len(self.melds[seat])
        if shanten(self.hands[seat], nm) != -1:
            return False
        if not self.youcai_bikao:
            return True
        tiles, laizi = split_laizi(self.hands[seat])
        if laizi == 0:
            return True                 # 无财神 → 平胡合法
        if gang_kai:
            return True                 # 杠开 = YCB 免爆头胡法
        return self._any_draw_win(seat, drawn_tile)   # 有财神自摸：须真·爆头

    # ---- 吃碰杠 ----
    def _resolve_claims(self, strategies):
        """返回 (seat, Meld) 或 None。优先级：明杠 > 碰 > 吃（仅下家）。"""
        d = self.last_discard_tile
        seat = self.last_discard_seat
        if d < 0 or d == LAIZI_INDEX:
            return None  # 财神不能吃碰明杠
        # 明杠：任意 3 家有 3 张 d
        for i in range(1, 4):
            p = (seat + i) % 4
            if self.hands[p][d] >= 3 and strategies[p].want_minggang(self, p, d):
                return p, Meld(MINGGANG, [d] * 4, [d] * 3, seat)
        # 碰：任意 3 家有 2 张 d
        for i in range(1, 4):
            p = (seat + i) % 4
            if self.hands[p][d] >= 2 and strategies[p].want_peng(self, p, d):
                return p, Meld(PENG, [d] * 3, [d] * 2, seat)
        # 吃：仅下家
        p = (seat + 1) % 4
        if self.chi_count[p] < 2:
            combo = strategies[p].want_chi(self, p, d)
            if combo:
                return p, Meld(CHI, sorted([d] + list(combo)), list(combo), seat)
        return None

    def _apply_claim(self, seat, meld):
        for t in meld.hand_tiles:
            self.hands[seat][t] -= 1
        # 被认领的弃牌从弃牌堆移除（牌守恒：弃牌 -> 副露）
        if meld.from_seat >= 0:
            self.discards[meld.from_seat].pop()
        self.melds[seat].append(meld)
        if meld.kind == CHI:
            self.chi_count[seat] += 1

    def _try_own_gang(self, strategies, seat, drawn_tile):
        """自己回合的杠：暗杠 / 补杠。返回是否杠了。

        财飘链语义（简化建模）：杠是动作链的另一项，此处既不重置也不增加 piao_count——
        杠开时仅由 `_win_result` 在 `calc_fan(gang_kai=True, piao_count=…)` 中与 piao 叠加
        （杠×2 × 财飘×2^piao 连乘）。完整规则里杠与飘的先后时序对链的影响不追求完美。

        drawn_tile: 本回合刚摸的牌（供策略的「听牌才杠」gate 还原摸前手牌）。
        """
        if self._remaining() <= 20:
            return False  # 最后 10 墩禁杠
        g = strategies[seat].want_own_gang(self, seat, drawn_tile)
        if g is None:
            return False
        kind, tile = g
        if kind == ANGANG:
            self.melds[seat].append(Meld(ANGANG, [tile] * 4, [tile] * 4, -1))
            for _ in range(4):
                self.hands[seat][tile] -= 1
        else:  # BUGANG：碰后摸到第 4 张
            for m in self.melds[seat]:
                if m.kind == PENG and m.tiles[0] == tile:
                    m.kind = BUGANG
                    m.tiles = [tile] * 4
                    break
            self.hands[seat][tile] -= 1
        return True

    # ---- 结算 ----
    def _any_draw_win(self, seat, drawn_tile):
        """摸牌前 13 张是否「任意摸都胡」= 真·爆头（4面子+财神单吊 / 6对+财神）。

        判据：还原刚摸的牌后的 13 张，手里已有 ≥1 财神，且任意补 1 张都成胡。
        用摸前形判定，避免把「最后摸来的财神补成七对/面子」误算成爆头（服务器不给 ×2）。
        v21②（2026-09-07）：撤销「正好 4 张白板不算爆头」旧裁——判据与线上 bot 共用
        mahjong.fan.any_draw_win。
        """
        if drawn_tile is None or drawn_tile < 0:
            return False
        h = list(self.hands[seat])
        h[drawn_tile] -= 1
        if h[drawn_tile] < 0:
            return False
        return any_draw_win(h, len(self.melds[seat]))

    def _win_result(self, seat, gang_kai, drawn_tile):
        baotou = self._any_draw_win(seat, drawn_tile)
        mult = calc_fan(self.hands[seat], gang_kai=gang_kai,
                        piao_count=self.piao_count[seat], baotou=baotou)
        scores = self._score(seat, mult)
        return seat, mult, scores, False

    def _draw_result(self):
        return -1, 0, [0, 0, 0, 0], True

    def _score(self, seat, mult):
        b = self.base_score
        scores = [0, 0, 0, 0]
        if seat == self.dealer:
            # 庄家胡：三家闲家各付 base*mult*8
            for p in range(4):
                if p != seat:
                    scores[p] = -b * mult * 8
                    scores[seat] += b * mult * 8
        else:
            # 闲家胡：庄家付 base*mult*8，另两闲家各付 base*mult*1
            for p in range(4):
                if p == seat:
                    continue
                w = 8 if p == self.dealer else 1
                scores[p] = -b * mult * w
                scores[seat] += b * mult * w
        return scores
