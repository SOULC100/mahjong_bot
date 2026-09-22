"""决策引擎：出牌 / 碰吃杠 / 财神管理。

出牌策略（优先级从高到低）：
0. 财飘：4 面子 + 2 财神时，打 1 财神做大番（×4 起，服务端维护 piao_count）
1. 不打财神（白板是百搭，价值远高于普通牌）
2. 打后向听数最小（最快听牌/胡牌）
3. 不拆对子/刻子（保留七对/将/杠的番型潜力）
4. 有效进张加权数最大
"""

import math

from .tiles import LAIZI_INDEX, NUM_TILES, is_number, pair_completions
from .win import split_laizi
from .fan import _is_four_melds, any_draw_win, calc_fan
from .shanten import shanten, shanten_baotou
from .ukeire import shanten_after_discard, ukeire_quality, ukeire_depth, ukeire_wait_width, \
    unique_tiles, ting_count

# ---- EV 权重（可调） ----
# 出牌打分 = 向听数 × SHANTEN_COST - 进张质量 × UKEIRE_W - 番型 × FAN_W × 庄家倍数
# 关键换算：1 向听 ≈ SHANTEN_COST=100；_fan_value 中 1 财神 ≈ 3。
# 闲家 1 财神 3×FAN_W×1 = 15 < 100（不抵消向听，求稳）；
# 庄家 1 财神 3×FAN_W×8 = 120 > 100（×8 值得牺牲 1 向听博爆头）。
SHANTEN_COST = 100.0
UKEIRE_W = 0.1      # 进张质量权重（ukeire ~ 数十~数百，×0.1 后作次级 tiebreak）
FAN_W = 5.0         # 番型权重（fan=3≈1财神）

# ---- 杠子保留分（protect_gang，默认开） ----
# 出牌别轻易拆「可暗杠的四张」（手牌某牌=4），把杠留到听牌时用（暗杠 = 听牌后白摸一次搏杠开）。
# 只做同向听内的次级 tiebreak（pen < SHANTEN_COST，绝不越过向听界）；向听能降时照拆不误。
# A/B（1500 局同 seed）：约 -0.08 平均分，惰性无害，按需默认开。
GANG_KEEP_PEN = 10.0

# ---- D1 喂庄防守参数（discard_decision defend_dealer=True 时启用，默认关=旧行为） ----
# 只可能被吃的是数牌顺子（吃 = 顺子，仅数牌），故惩罚只加在数牌上。
# 惩罚分叠加进 score（score 越小越好 → 惩罚分让危险牌更差）。
# 量级：SHANTEN_COST=100 → 惩罚 <100 只在「同向听」候选间重排，不越向听界（不牺牲自己的牌效率）。
D1_FEED_PEN = 40.0    # 基础喂牌惩罚分
D1_HOT_MAX = 1        # 花色危险阈值：庄家观察窗口内该花色数牌弃牌数 <= D1_HOT_MAX → 判「庄家可能还在收集该花色」
D1_WINDOW = None      # 庄家弃牌观察窗口（最近 N 张；None=全部公开弃牌）

# ---- 边张优先（edge_w，**默认关**；2026-09-22 用户假设的 A/B 开关）----
# 假设（用户提出）：中张（如 2w/6w）靠张多，边张（如 9t）靠张少，所以「先打边张」可能更划算。
# ⚠️ 与现行判据冲突：现行 EV 看的是「打掉它之后整手牌的进张」，**靠张重叠只算一次**
#   （真机例：留 2w 独占 8 张 < 留 9t 独占 10 张 → 引擎先打 2w）。edge_w 是**另一套假设**：
#   边张在 ukeire 之外还有别的代价（死搭子更难补、更晚成听、更容易被别家吃走推进），
#   故意在同一向听内给边张「减分」（score 越小越好 → 更想打它）。
# 量纲：ukeire 质量差 1 张 ≈ 0.1 分（UKEIRE_W）→ 边张减分 ~1 分就能翻转「进张差 ≤ 10 张」的平手点；
#       必须 << SHANTEN_COST=100，绝不越向听界（宁慢一档去追边张是明显亏的）。
# **已测（2026-09-22，冻结基准强场 1000 局配对）：证伪 —— edge1 −0.260（z=−0.69）、edge3 −0.621（z=−1.63）、
#   edge10 −1.275（z=−3.31）；三档全负、分半同号、剂量越大越差（胡牌率 25.2%→19.4%，只换来场均番 +0.06）。
#   见 docs/eval-rounds.md §25。默认恒 0.0，别在线上打开。**
EDGE_W = 0.0


def edge_bias(tile: int) -> float:
    """边张程度：1/9 = 3 分、2/8 = 2 分、3/7 = 1 分、其余数牌 0；字牌 0（另轴，不混进来）。

    只描述「这张牌在数牌里的位置有多靠边」，不含任何牌效判断——牌效仍由向听/进张负责。
    """
    if tile >= 27:
        return 0.0
    r = tile % 9
    if r in (0, 8):
        return 3.0
    if r in (1, 7):
        return 2.0
    if r in (2, 6):
        return 1.0
    return 0.0


def _draw_quality(counts, remain=None, melds=0):
    """13 张基准手牌的进张质量（有效进张加权）。

    与 ukeire_quality 的区别：counts 已处于「13 张基准」状态（暗手 + 3×副露 = 13，
    即轮到摸牌前的手牌），不再先打一张，直接统计「摸哪些牌能降向听」并按
    牌墙剩余 + 深度加权（进张后越接近听/胡价值越高）。

    用于 A1 门控：向听数不变的吃/碰，若使该进张质量提升则值得做。
    """
    base = shanten(counts, melds)
    if remain is None:
        remain = [4] * NUM_TILES
    score = 0.0
    for t in range(NUM_TILES):
        if remain[t] <= 0:
            continue
        c2 = list(counts)
        c2[t] += 1
        s2 = shanten(c2, melds)
        if s2 < base:
            score += remain[t] * (1 + max(0, 3 - s2))
    return score


def should_piao(hand) -> bool:
    """是否应该飘财：手牌 = 4 面子 + 2 财神（打 1 财神变爆头听牌，听任意牌）。"""
    tiles, laizi = split_laizi(hand)
    if laizi != 2:
        return False
    return _is_four_melds(tiles)


# ---- 弃胡 + 财飘（2026-09-20） ----
# 规则依据（guide v34 §1.2 / §1.3 财飘表）：
#   「弃胡」= 摸牌后不强制自动胡，可继续打牌（飘/杠链的前提）；
#   「爆头摸到白板」：可提交 hu（爆头 ×2），也可弃胡打白飘（博财飘 ×4 起，可连飘 ×8/×16）；
#   v33 起杠后补牌同口径。打出非飘非杠的牌（含非爆头态打白板）→ 链断。
# 结论：飘的**合法前提 = 打完那张财神后仍处「任意摸都胡」态**（否则链断，白丢一个胡）。
PIAO_Q_EST = 0.75         # 「活过一圈（自己下次摸牌前没人胡）」的存活率估计（rules-strategy §2.5 实测 0.75~0.80）
PIAO_MAX_CHAIN = 3        # 连飘上限：每多飘一次都要再活一圈，q^n 衰减
PIAO_LOSS_DEALER = 8.0    # 被抢先时我方损失（庄家：谁胡都按 ×8 付）
PIAO_LOSS_IDLE = 2.75     # 闲家：1/4 概率庄家胡（付 8）+ 3/4 闲家胡（付 1）≈ 2.75


def piao_after_discard(hand, melds=0) -> bool:
    """打出一张财神后是否仍「任意摸都胡」= 财飘的合法前提（guide §1.2）。

    hand: 14-3*melds 张（含 ≥2 张财神）。判据与 mahjong.fan.any_draw_win 同源，
    覆盖两种形态：①平胡形 4 面子 + 2 财神；②七对形（七客：6 对 + 2 财神，或豪华组）。
    """
    if hand[LAIZI_INDEX] < 2:
        return False
    c = list(hand)
    c[LAIZI_INDEX] -= 1
    return any_draw_win(c, melds)


def should_decline_hu(hand, melds=0, drawn=-1, gang_kai=False, chain_count=0,
                      is_dealer=False, q_est=PIAO_Q_EST, max_chain=PIAO_MAX_CHAIN) -> bool:
    """能胡时**是否弃胡去打财飘**（规则明确允许的战术，guide §1.2）。

    调用方须已确认这手牌能胡（can_hu）。EV 模型（rules-strategy §2.5，底分 1）：

        EV(弃胡飘) − EV(直接胡) = f0·(2q − 1) − (1 − q)·c
        ⇒ 盈亏平衡存活率 q* = (f0 + c) / (2·f0 + c)

    f0 = 现在胡的番（爆头 ×2 / 4 白 ×2 / 已有链 ×2^chain 都算进去）
    c  = 被对手抢先时我方损失（庄家 8、闲家 ≈2.75，按对手番型 1 估）
    q  = 活过一圈的概率（默认保守取 PIAO_Q_EST=0.75）

    只在**同时**满足「打白后仍爆头」+「q_est > q*」+「连飘未超上限」时才弃胡。
    典型结果：闲家 f0=2 → q*=0.70 < 0.75 → 飘；庄家 f0=2 → q*=0.83 > 0.75 → 不飘。

    hand: 14-3*melds 张胡牌形；drawn: 刚摸的牌（判「现在这胡算不算爆头」用，-1=未知）。
    """
    if chain_count >= max_chain:
        return False
    if shanten(hand, melds) != -1:
        return False                      # 不是胡牌形 → 谈不上弃胡
    if not piao_after_discard(hand, melds):
        return False                      # 打白后链会断 → 纯亏，不弃
    baotou_win = False
    if 0 <= drawn < NUM_TILES and hand[drawn] > 0:
        h13 = list(hand)
        h13[drawn] -= 1
        baotou_win = any_draw_win(h13, melds)
    fan_now = calc_fan(hand, gang_kai=gang_kai, piao_count=chain_count, baotou=baotou_win)
    loss = PIAO_LOSS_DEALER if is_dealer else PIAO_LOSS_IDLE
    q_star = (fan_now + loss) / (2.0 * fan_now + loss)
    return q_est > q_star


def should_peng(hand13, peng_tile, melds=0, ukeire_gate=False, remain=None, gate_max_shanten=None,
                gate_min_gain=0.0) -> bool:
    """是否碰：碰后（副露 + 打 1 张）向听数下降才碰。

    hand13: 13 张暗手（34 维计数，不含刚摸的）
    peng_tile: 要碰的牌
    melds: 已副露的面子数
    ukeire_gate: A1 门控。True 时向听数不变、但进张质量提升也碰（默认 False=旧行为）。
    remain: 牌墙剩余估算（34 维），None 时按每种 4 张估算。
    gate_max_shanten: 门控最大前置向听数。仅当 pre 向听 <= 该值才允许「等向听但质量提升」的碰
                      （限制过早锁面子；None=不限）。
    gate_min_gain: 门控的最小质量增益比例（0=只要有提升就碰）。1.05 = 要求提升 ≥5%，
                   用来过滤「提升一点点就锁面子」的边缘情形。
    """
    s_no = shanten(hand13, melds)
    if hand13[peng_tile] < 2:
        return False  # 手里不足 2 张，无法碰
    c = list(hand13)
    c[peng_tile] -= 2  # 去掉 2 张碰牌
    best = 99
    for d in unique_tiles(c):
        c2 = list(c)
        c2[d] -= 1  # 碰后打 1 张
        best = min(best, shanten(c2, melds + 1))
    if best < s_no:
        return True
    if ukeire_gate and best == s_no and (gate_max_shanten is None or s_no <= gate_max_shanten):
        # 向听数不变，但碰后进张质量提升也碰（在等向听数的出牌里取质量最高）
        best_q = -1.0
        for d in unique_tiles(c):
            c2 = list(c)
            c2[d] -= 1
            if shanten(c2, melds + 1) != best:
                continue
            best_q = max(best_q, _draw_quality(c2, remain, melds + 1))
        cur_q = _draw_quality(hand13, remain, melds)
        return best_q > cur_q * (1.0 + gate_min_gain) if cur_q > 0 else best_q > cur_q
    return False


def chi_combos(hand13, chi_tile):
    """返回所有能吃的搭子（每个是 [两张某他牌索引]），吃 chi_tile 组成顺子。

    chi_tile 可为顺子的下/中/上任意位置；须同花色数牌。
    """
    if not is_number(chi_tile):
        return []
    combos = []
    for lo in range(chi_tile - 2, chi_tile + 1):
        if lo < 0 or lo % 9 > 6:  # 顺子起点须在同花色 0-6 内
            continue
        others = [x for x in (lo, lo + 1, lo + 2) if x != chi_tile]
        if hand13[others[0]] >= 1 and hand13[others[1]] >= 1:
            combos.append(others)
    return combos


def best_chi(hand13, chi_tile, melds=0, ukeire_gate=False, remain=None, gate_min_gain=0.0,
             gate_max_shanten=None, narrow_max_accept=None, narrow_min_shanten=None,
             prefer_narrow=False, accept_remain=None):
    """返回吃 chi_tile 的最优搭子（两张某他手牌索引），不可吃返回 None。

    hand13: 13 张暗手；chi_tile: 上家打出的牌；melds: 已副露面数。
    默认条件：吃后（副露 + 打 1 张）向听数下降。
    ukeire_gate: A1 门控。True 时向听数不变、但进张质量提升也吃。
    gate_min_gain: 门控的最小质量增益比例（0=有提升就吃；1.05=要求 ≥5%）。
    gate_max_shanten: 等向听门控的最大前置向听数（None=不限；与 should_peng 同义）。

    **吃额度/搭子宽度（2026-09-25，R15）**：
    narrow_max_accept / narrow_min_shanten：向听 ≥ narrow_min_shanten 时，
        只吃「搭子剩余进张 ≤ narrow_max_accept」的搭子（0 = 不吃这副搭子就废了）。
        理由：还剩好几手才能听牌时，搭子自己能摸进来的宽搭子不急着用吃（吃额度只有 2 摊），
        把额度留给**摸不进来**的窄搭子；见 docs/eval-rounds.md §22。
    prefer_narrow：同一张弃牌有多个吃法时，优先消耗**剩余进张最少**的那副搭子
        （先消化死搭子，把宽搭子留在手里继续摸）。
    accept_remain：只给「搭子剩余进张」判据用的口径（默认 = remain）。**必须传原始未见张数**
        （`GameState.raw_unseen` / sim `remain_estimate`）：narrow_max_accept 是绝对张数阈值，
        若用线上那个按牌墙缩放过的 remain（≈0.47×），同一个阈值在线上/离线含义不同。
    """
    combos = chi_combos(hand13, chi_tile)
    if not combos:
        return None
    s_no = shanten(hand13, melds)
    acc_src = remain if accept_remain is None else accept_remain

    def _accept(pair):
        """这副搭子去掉被吃的这张后，还能靠自摸补上的张数（口径未知时返回 None）。"""
        if acc_src is None:
            return None
        return sum(acc_src[t] for t in pair_completions(pair[0], pair[1]) if t != chi_tile)

    best_eq = None
    best_eq_q = -1.0
    best_eq_acc = None
    strict = []            # 严格降向听的吃法：(剩余进张, 吃后质量, 吃后向听, 搭子)
    for others in combos:
        acc = _accept(others)
        if (narrow_max_accept is not None and acc is not None
                and s_no >= (narrow_min_shanten or 0) and acc > narrow_max_accept):
            continue                      # 宽搭子：把额度留给窄的（见 §22）
        c = list(hand13)
        c[others[0]] -= 1
        c[others[1]] -= 1
        # 吃后打哪张最优（向听最小；等向听时取质量最高）
        best_s = 99
        best_s_q = -1.0
        for d in unique_tiles(c):
            c2 = list(c)
            c2[d] -= 1  # 吃后打 1 张
            s = shanten(c2, melds + 1)
            if s < best_s:
                best_s = s
                best_s_q = _draw_quality(c2, remain, melds + 1) if ukeire_gate else 0.0
            elif ukeire_gate and s == best_s:
                q = _draw_quality(c2, remain, melds + 1)
                if q > best_s_q:
                    best_s_q = q
        if best_s < s_no:
            if not prefer_narrow:
                return others  # 严格降向听：直接吃（与旧行为一致）
            strict.append((best_s, acc if acc is not None else 0, best_s_q, others))
            continue
        if ukeire_gate and best_s == s_no and (gate_max_shanten is None or s_no <= gate_max_shanten):
            if best_eq is None:
                best_eq, best_eq_q, best_eq_acc = others, best_s_q, acc
            elif prefer_narrow and acc is not None and best_eq_acc is not None:
                if (acc, -best_s_q) < (best_eq_acc, -best_eq_q):
                    best_eq, best_eq_q, best_eq_acc = others, best_s_q, acc
            elif best_s_q > best_eq_q:
                best_eq, best_eq_q, best_eq_acc = others, best_s_q, acc
    if prefer_narrow and strict:
        # 先保「吃后向听最好」，再消化进张最少的搭子，最后看吃后进张质量
        strict.sort(key=lambda x: (x[0], x[1], -x[2]))
        return strict[0][3]
    if ukeire_gate and best_eq is not None:
        # 向听数不变，但吃后进张质量提升也吃（gate_min_gain 可要求最小增益比例）
        cur_q = _draw_quality(hand13, remain, melds)
        if best_eq_q > (cur_q * (1.0 + gate_min_gain) if cur_q > 0 else cur_q):
            return best_eq
    return None


def should_chi(hand13, chi_tile, melds=0, ukeire_gate=False, remain=None, gate_min_gain=0.0,
               gate_max_shanten=None, narrow_max_accept=None, narrow_min_shanten=None,
               prefer_narrow=False, accept_remain=None) -> bool:
    """是否吃：吃后（副露 + 打 1 张）向听数下降才吃。

    ukeire_gate: A1 门控。True 时向听数不变、但进张质量提升也吃。
    gate_min_gain: 门控的最小质量增益比例（0=有提升就吃；1.05=要求 ≥5%）。
    gate_max_shanten: 等向听门控的最大前置向听数（None=不限）。
    narrow_max_accept / narrow_min_shanten / prefer_narrow / accept_remain：见 best_chi。
    """
    return best_chi(hand13, chi_tile, melds, ukeire_gate, remain, gate_min_gain,
                    gate_max_shanten, narrow_max_accept, narrow_min_shanten,
                    prefer_narrow, accept_remain) is not None


# ---- 暗杠时机（听牌才杠 + 七对/豪华七对保护）----
# 2026-09 决策：不做无脑杠。暗杠只在该赚时才做：
#   杠前听牌（还原刚摸的牌后 shanten==0）——非听牌把 4 张锁成杠面子会牺牲灵活性/胡牌率；
#   杠后仍听（4 张做成 1 杠面子后 shanten<=0）——若当前听牌靠七对/豪华七对手里这个 quad
#     （melds==0），杠后必然回退到 >=1，该条件自动拦下 → 保留豪华七对 ×4/×8 路线。
# 财神(白板)不能被杠，天然排除。
def angang_tile(hand14, drawn, melds=0):
    """暗杠时机：返回值得暗杠的牌索引；无则 None。

    hand14: 当前 14 张计数（已含刚摸的牌）；drawn: 刚摸的牌 idx（-1/None = 非真摸牌回合）。
    判据（见模块注释）：杠前听牌 + 杠后仍听。
    """
    if drawn is None or drawn < 0:
        return None
    pre = list(hand14)
    pre[drawn] -= 1  # 还原摸前 13 张
    if pre[drawn] < 0 or shanten(pre, melds) != 0:
        return None  # 非听牌不杠（或 drawn 越界防御）
    for t in range(NUM_TILES):
        if t == LAIZI_INDEX or hand14[t] < 4:
            continue
        h2 = list(hand14)
        h2[t] -= 4  # 4 张做成杠面子
        if shanten(h2, melds + 1) <= 0:  # 杠后标准仍听（七对依赖 quad 则拦下）
            return t
    return None


# ---- 敲响路线（R-敲响，knock=True 时启用，默认关） ----
# 「敲响/爆头」= 留 1 张财神做将/单吊，4 面子(标准)或 6 对(七客)成型后任意摸都胡 ×2。
# 现有 shanten() 只取「标准面子 / 七对」两条路线的 min，且 shanten_baotou(财神做将)只在
# 贴近听牌时才被 baotou_route 启用、并且只建模标准面子——「七对+财神单吊(七客/豪华七客)」
# 这一路线从未进入向听模型。knock 把「财神做将」作为第三条向听路线并入：只要不比普通路线
# 慢就采纳 → bot 会主动保留财神单吊、打掉冗余牌，去够「任意摸都胡」的敲响终局。
def _seven_knock_dist(tiles, la):
    """七客距离：留 1 财神当单吊(将来和任意摸牌成第 7 对)，其余真实牌 + (la-1) 财神凑 6 对
    还差的步数（基准同 _shanten_seven_pairs：到「6对+财神=任意摸胡」为 0）。"""
    if la < 1:
        return 99
    use = la - 1
    pairs = sum(c // 2 for c in tiles)
    singles = sum(c % 2 for c in tiles)
    fill = min(singles, use)
    rem = use - fill
    return 6 - (pairs + fill + rem // 2)


def knock_shanten(counts, melds=0):
    """敲响路线向听：标准爆头(shanten_baotou，财神做将) 与 七客(七对+财神单吊) 取小。

    无财神返回 99（不可行）。仅当 melds==0 才考虑七客（七对不能有副露）。
    """
    tiles, la = split_laizi(counts)
    best = 99
    if la >= 1:
        best = min(best, shanten_baotou(counts, melds))
    if melds == 0:
        best = min(best, _seven_knock_dist(tiles, la))
    return best


def _fan_value(counts, melds=0, melds_aware=False) -> int:
    """手牌的番型价值（越高越有做大番的潜力）。

    - 财神：爆头/财飘潜力（每个 +3）
    - 对子 >= 4：七对路线（每个对子 +1）——**melds_aware=True 且已有副露时不给**
      （2026-09-20：`shanten(..., melds>0)` 已把七对分支置 99，有副露还给这个加分就是"幻影七对"，
       等于每次吃碰后白拿几分；作为候选方案 `fan_value_melds` 由调用方显式打开）
    - 刻子：杠潜力（每个 +1）
    """
    tiles, laizi = split_laizi(counts)
    pairs = sum(1 for c in tiles if c >= 2)
    triples = sum(1 for c in tiles if c >= 3)
    val = laizi * 3
    if pairs >= 4 and not (melds_aware and melds > 0):
        val += pairs
    val += triples
    return val


# B4：fan_est="real" 把启发式 fan 换成更贴 calc_fan 的估计。
# 统一量纲：fan 越大越值得保留（score 里 -fan*fan_w 项），heuristic 的 1 财神≈3。
# 这里把「已锁定的翻倍次数」×FAN_REAL_K 对齐 heuristic 量级（1 翻倍 ≈ 3，等价 1 财神）。
FAN_REAL_K = 3.0


def _fan_ting_expect(counts, melds=0, remain=None):
    """已听牌（向听=0）时，摸到胡牌的真实期望番型翻倍次数 = log2(期望倍率)。

    对每个仍剩的可胡进张 t，用 calc_fan(补 t 后的 14 张) 试算真实倍率，
    按牌墙剩余 remain 加权求期望，再取 log2（翻倍次数，平胡=0）。
    非听牌返回 None（13 张非听牌没有可直接 calc_fan 的胡形）。

    2026-09-25 修（docs/improvement-plan.md §1 记的 bug）：旧版调 calc_fan **不传 baotou**，
    于是「4 面子 + 财神单吊」这类**真·爆头**听牌被算成平胡 ×1 → 番型估计系统性低估 ×2，
    使 `fan_est="real*"` 的旧证伪结论（B4）不成立。修法：爆头是**摸牌前 13 张**的性质，
    与本函数拿到的 13 张 counts 完全同源 → `baotou = any_draw_win(counts, melds)`。
    """
    if shanten(counts, melds) != 0:
        return None
    if remain is None:
        remain = [1] * NUM_TILES
    baotou = any_draw_win(counts, melds)   # 摸前 13-3m 张「任意摸都胡」→ 每张进张都是 ×2
    tw = 0.0
    tm = 0.0
    for t in range(NUM_TILES):
        if remain[t] <= 0:
            continue
        c2 = list(counts)
        c2[t] += 1
        if shanten(c2, melds) == -1:  # 摸 t 即胡
            w = float(remain[t])
            tw += w
            tm += w * calc_fan(c2, gang_kai=False, piao_count=0, baotou=baotou)
    if tw <= 0:
        return 0.0
    return math.log2(max(tm / tw, 1.0))


def _fan_value_real(counts, melds=0, remain=None, k=FAN_REAL_K) -> float:
    """更贴 calc_fan 的 13 张番型潜力估计（fan_est="real"）。

    已听牌：摸到胡牌的真实期望翻倍次数（calc_fan 试算）× k。
    未听牌：只记「已锁定」的翻倍——七对路线不比标准慢（melds==0 时押七对，
            至少 ×2，已有 4 张/4 财神再加豪七层）。财神/刻子等「未锁定潜力」不再白送。
    单位与 _fan_value 对齐（1 翻倍 ≈ FAN_REAL_K 分）；k 可下调（如 "real_k1" 用 k=1，
    使 fan 只作次级 tiebreak，不再盖过进张宽度）。
    """
    e = _fan_ting_expect(counts, melds, remain)
    if e is not None:
        return k * e
    tiles, laizi = split_laizi(counts)
    s = shanten(counts, melds)
    doublings = 0.0
    if melds == 0:
        pairs = sum(v // 2 for v in tiles)
        singles = sum(v % 2 for v in tiles)
        fill = min(singles, laizi)
        rem_lz = laizi - fill
        seven_s = 6 - (pairs + fill + rem_lz // 2)
        if seven_s <= s:  # 七对路线不比标准慢 → 押七对至少 ×2
            nquads = sum(1 for v in tiles if v >= 4) + (1 if laizi == 4 else 0)
            doublings += 1 + nquads
    return k * doublings


def _d1_penalty_vector(dealer_discards, hand=None, pen=D1_FEED_PEN, hot_max=D1_HOT_MAX, window=D1_WINDOW, mode="suit"):
    """根据庄家公开弃牌估计「喂庄吃」风险，返回 34 维惩罚分（0 = 无风险）。

    庄家只能吃「上家」的弃牌（顺子，仅数牌）。公开信息只有庄家弃牌（+ 我自己的手牌）。
    字牌/财神不能被吃 → 惩罚恒 0。

    mode="suit"（最简）：某数牌花色在庄家弃牌中出现次数 <= hot_max → 判庄家可能还在收集该
    花色 → 该花色整条全罚。缺点：同花色内所有牌一视同仁，无法区分「中心张（顺子搭子多，
    易被吃）」与「边张（几乎无搭子可吃）」。
    mode="pair"（tile 级）：在 suit 基础上，用「活互补搭子数」细分——某数牌 t 能被吃当且仅当
    庄家手里同时有互补两邻张。t 的互补搭子 = {t±邻} 的 3 种组合（边张更少）；只要某一互补张
    已无剩余（我方手牌 + 庄家弃牌已见满 4 张），该搭子即死。活搭子越少 → 被吃风险越低。
    """
    zeros = [0.0] * NUM_TILES
    if not dealer_discards or pen <= 0:
        return zeros
    dd = dealer_discards if window is None else dealer_discards[-window:]
    suit_cnt = [0, 0, 0]
    for t in dd:
        if t < 27:  # 数牌
            suit_cnt[t // 9] += 1
    if mode == "pair":
        # 每张数牌的「仍可能在庄家手里的张数」：4 - 我方手牌 - 庄家弃牌
        unseen = [0] * 27
        for t in range(27):
            unseen[t] = max(0, 4 - (hand[t] if hand is not None else 0) - dd.count(t))
    for s in range(3):
        if suit_cnt[s] > hot_max:
            continue  # 庄家已大量弃该花色 → 不太可能还在收集 → 安全
        for t in range(s * 9, s * 9 + 9):
            if mode == "pair":
                v = t % 9
                pairs = 0.0
                # 枚举包含 t 的顺子下界 lo（与 chi_combos 相同），搭子 = 另两张
                for lo in (v - 2, v - 1, v):
                    if lo < 0 or lo + 2 > 8:
                        continue
                    other = [x for x in (lo, lo + 1, lo + 2) if x != v]
                    a, b = other[0], other[1]
                    if unseen[s * 9 + a] > 0 and unseen[s * 9 + b] > 0:
                        pairs += 1.0
                if pairs <= 0:
                    zeros[t] = 0.0  # 无活搭子 → 实际上吃不了
                else:
                    zeros[t] = pen * (0.35 + 0.65 * (pairs / 3.0))
            else:
                zeros[t] = float(pen)
    return zeros


def discard_decision(hand, remain=None, melds=0, depth=True, dealer=False, fan_override=True, allowed=None, youcai_bikao=False,
                     piao_enabled=True, piao_dealer_only=False, baotou_slack=1, baotou_max_shanten=1,
                     defend_dealer=False, dealer_discards=None, defend_pen=D1_FEED_PEN,
                     defend_hot_max=D1_HOT_MAX, defend_window=D1_WINDOW, defend_mode="suit",
                     fan_est="heuristic", protect_gang=True, gang_keep_pen=GANG_KEEP_PEN, knock=False,
                     ycb_escape_gap=0, dealer_speed=False,
                     fan_value_melds=False, wait_width=None, wait_tie_eps=0.0,
                     shanten_cost=SHANTEN_COST, ukeire_w=UKEIRE_W, fan_weight=FAN_W,
                     god_fan_boost=1.0, edge_w=EDGE_W):
    """出牌决策：返回最优出牌 tile 索引。

    优先级：
    0. 财飘（4 面子 + 2 财神打财神）
    1. 爆头路线（财神做将向听数 ≤ 标准 + slack 时，保留财神走 ×2）
    2. EV 打分：向听数最小 → 进张质量（听牌宽度 / 二次进张）→ 番型 × 庄家权重
       fan_override=True 时，番型 × 庄家倍数可抵消 1 向听走大番。

    melds: 已副露的面子数。
    depth: True 用二次进张深度（ukeire_depth，慢但更准）；False 用进张质量（ukeire_quality，快）。
    dealer: 是否庄家（庄家 ×8，番型权重放大）。
    fan_override: EV 框架开关（番型能否抵消 1 向听）。
    allowed: 服务器允许打出的牌集合（可迭代 tile 索引）；None 则默认手牌全部非财神牌。
    youcai_bikao: 有财必拷响——手有财神不能平胡，留财神必走爆头、弃财神可逃回平胡。
    piao_enabled: B1 开关——关闭则完全不飘财（对照）。
    piao_dealer_only: B1——仅庄家飘财（A/B 用，默认关）。
    baotou_slack / baotou_max_shanten: B2 爆头路线阈值（默认 1/1 = 现行为）。
    defend_dealer / dealer_discards: D1 防守——True 且给出庄家公开弃牌时，对「庄家可能吃」的牌
        加喂牌惩罚分（默认关闭 = 旧行为）。
    defend_pen / defend_hot_max / defend_window / defend_mode: D1 启发式系数（见 _d1_penalty_vector）。
    fan_est: B4 番型估计开关。默认 "heuristic"=旧 _fan_value（粗潜力）；
        "real"=用 _fan_value_real（已听牌用 calc_fan 试算真实倍率、未听牌只记锁定翻倍）；
        "real_k1"=同 real 但翻倍按 k=1 降权（fan 只作次级 tiebreak）；
        "real_ting"=仅对已听牌候选用 calc_fan 试算，其余仍用 _fan_value。
    protect_gang / gang_keep_pen: 杠子保留分——不轻易拆「可暗杠的四张」，把杠留到听牌时用
        （同向听内 tiebreak，pen < SHANTEN_COST 不越向听界；默认开）。
    knock: R-敲响——出牌向听并入「财神做将/单吊(含七客=七对+财神单吊)」第三路线，
        只要不比普通(标准/七对)路线慢就采纳，主动走向「任意摸都胡 ×2」的敲响终局。
    ycb_escape_gap: YCB 逃回平胡门限（向听步数）。有财必拷响下弃「最后一张财神」=逃回平胡，
        其参与比较的虚向听 = 弃财神后 plain shanten + ycb_escape_gap。
        gap>0 → 逃回更难被选中（更坚持追爆头/七客，赌 ×2 起）；gap<0 → 更早放弃财神逃平胡；
        gap=0 → 自然行为（纯比向听，谁小选谁）。默认 0。
    dealer_speed: 坐庄抢速（dealer_policy='aggr'，2026-09-03 实测当庄 +0.8~+1.9 avg）。
        坐庄方宝押胡牌率而非番型/动作：把爆头路线 slack/max 收紧到 0（不为爆头牺牲向听）、
        杠子保留分清零（protect_gang 失效，别为未来杠压牌速）。闲家不触发 = 逐决策与基线一致。
    fan_value_melds: 番型启发式是否认副露——True 时有副露不再给「对子>=4 的七对加分」
        （默认 False=旧行为；修的是"幻影七对"：有副露时七对分支已不可达）。
    wait_width: P1-a 听口宽度（None=旧行为 / "tiebreak"=只在总分并列时按"进张×落地听口"破平
        / "full"=直接把 ukeire 项换成 wait-width 口径）。
        动机实测：向听=1 的出牌点里 4.5% 现引擎选的不是两步最优（data/_wait_opportunity.txt）。
    shanten_cost / ukeire_w / fan_weight: 打分权重（2026-09-03 穿参，默认=模块常量现值）。
        score = shanten×shanten_cost - ukeire×ukeire_w - fan×fan_w(fan_override)×dealer_mult；
        shanten_cost=100 时 1 向听 ≈ 单位；fan_weight 控制「番型抵消向听」力度。
    edge_w: 边张优先偏置（**默认 0 = 关**，见模块常量 EDGE_W）。>0 时对边张候选额外减分
        `edge_w × edge_bias(d)`（1/9=3、2/8=2、3/7=1 分），只在同向听内重排。
        这是「中张靠张多于边张，所以先打边张」这一假设的 A/B 开关；与现行「整手牌进张」判据
        可能相反（靠张重叠只算一次），**收益必须由冻结基准配对 A/B 判定**。
    """
    dealer_mult = 8 if dealer else 1
    if dealer_speed:
        baotou_slack = 0
        baotou_max_shanten = 0
        gang_keep_pen = 0.0

    # 财飘优先（财神须在可打集合内）
    # 2026-09-20：判据由 should_piao（4 面子 + 2 财神）放宽到 piao_after_discard（打白后仍爆头）——
    # 后者是规则口径的超集，额外覆盖**七对形**财飘（guide v3「七对可财飘」：6 对 + 2 财神 / 豪华组）。
    # 弃胡路径依赖它把财神真的打出去（否则弃了胡又打别的牌 = 链断 + 白丢一个胡）。
    if piao_enabled and piao_after_discard(hand, melds) and (not piao_dealer_only or dealer) and (allowed is None or LAIZI_INDEX in allowed):
        return LAIZI_INDEX

    tiles, laizi = split_laizi(hand)
    ycb = youcai_bikao and laizi >= 1  # 有财必拷响且手有财神

    # 爆头路线：财神做将（×2）值得牺牲 slack 个向听数（仅非 YouCaiBiKao 模式判断）
    baotou_route = False
    if not ycb and laizi >= 1:
        s_std = shanten(hand, melds)
        s_bao = shanten_baotou(hand, melds)
        if s_bao <= s_std + baotou_slack and s_bao <= baotou_max_shanten:
            baotou_route = True

    if allowed is not None:
        pool = [d for d in allowed if hand[d] > 0]
    else:
        candidates = unique_tiles(hand)
        non_laizi = [d for d in candidates if d != LAIZI_INDEX]
        pool = non_laizi if non_laizi else candidates
    # 有财必拷响：财神可打出（逃回平胡）
    if ycb and LAIZI_INDEX not in pool and (allowed is None or LAIZI_INDEX in allowed):
        pool.append(LAIZI_INDEX)

    # 先算每个候选的打后向听数（只依赖向听，fan 值推迟到 bound 内再算，省 real 版开销）
    s_map = {}
    for d in pool:
        c = list(hand)
        c[d] -= 1
        if ycb:
            # 有财必拷响：
            #  - 弃「最后一张」财神 → 逃回平胡（plain shanten；用 ycb_escape_gap 控制逃回时机）
            #  - 留财神（含弃非最后财神） → 必走爆头/七客路线（财神做将任意摸都胡）。
            #    2026-09-03：YCB 合法胡含七客（6对+财神），故距离用 knock_shanten = min(标准爆头, 七客)
            #    而非旧版只用 shanten_baotou（漏了七客路线）。
            if d == LAIZI_INDEX and laizi == 1:
                # 逃回平胡的「虚向听」= 弃财神后 plain shanten + ycb_escape_gap。
                # gap>0 让逃回更难被选中（=更坚持追爆头）；gap<0 更早逃回；gap=0 为自然行为。
                s_map[d] = shanten(c, melds) + ycb_escape_gap
            else:
                s_map[d] = knock_shanten(c, melds)
        else:
            if baotou_route:
                s_map[d] = shanten_baotou(c, melds)
            else:
                s_map[d] = shanten(c, melds)
            # R-敲响：把「财神做将/单吊(含七客)」当第三条向听路线，只要不比普通路线慢就采纳
            if knock and laizi >= 1:
                s_map[d] = min(s_map[d], knock_shanten(c, melds))

    # EV 打分（越小越好）：向听数主导，进张质量次级 tiebreak，番型 × 庄家权重可抵消向听。
    # fan_override=False 时番型权重归零，退化为「向听 → 进张」的旧行为。
    fan_w = (fan_weight * (god_fan_boost if laizi >= 1 else 1.0)) if fan_override else 0.0
    min_s = min(s_map.values())
    # 只对可能胜出的候选算 ukeire（进张是次级 tiebreak，最多抵消 1 向听），避免 14 个候选全算导致性能崩
    bound = min_s + 1 if fan_override else min_s

    # D1 喂庄防守：只在出牌者 = 庄家上家时启用（调用方负责判断），对危险牌叠加惩罚。
    d1_pen = _d1_penalty_vector(dealer_discards, hand, defend_pen, defend_hot_max, defend_window, defend_mode) \
        if (defend_dealer and dealer_discards is not None) else None

    def _fan_for(c):
        """按 fan_est 取 13 张番型估计（c = 打 d 后的手牌）。"""
        if fan_est == "heuristic":
            return _fan_value(c, melds, melds_aware=fan_value_melds)
        if fan_est == "real":
            return _fan_value_real(c, melds, remain)
        if fan_est == "real_k1":
            return _fan_value_real(c, melds, remain, k=1.0)  # 降权：fan 只作次级 tiebreak
        # real_ting：仅已听牌用 calc_fan 试算真实倍率，其余仍用启发式
        e = _fan_ting_expect(c, melds, remain)
        return FAN_REAL_K * e if e is not None else _fan_value(c, melds, melds_aware=fan_value_melds)

    best_d = -1
    best_score = None
    tied = []          # wait_width="tiebreak"：并列最优的候选，稍后用「进张×落地听口」破平
    for d in pool:
        if s_map[d] > bound:
            continue
        c = list(hand)
        c[d] -= 1
        fan = _fan_for(c)
        if s_map[d] == 0:
            ukeire_val = ting_count(c, remain, melds)  # 听牌宽度：能胡的牌加权数
        elif wait_width == "full":
            ukeire_val = ukeire_wait_width(hand, d, remain, melds)
        elif baotou_route or not depth:
            ukeire_val = ukeire_quality(hand, d, remain, melds)
        else:
            ukeire_val = ukeire_depth(hand, d, remain, melds)
        score = s_map[d] * shanten_cost - ukeire_val * ukeire_w - fan * fan_w * dealer_mult
        if d1_pen is not None:
            score += d1_pen[d]  # D1：喂庄风险 → 该候选更差（同向听内重排）
        if protect_gang and hand[d] >= 4:
            score += gang_keep_pen  # 杠子保留分：不轻易拆可暗杠的四张（同向听 tiebreak）
        if edge_w:
            # 边张优先（默认关，见 EDGE_W）：score 越小越好 → 给边张减分 = 更想打它。
            # 必须 << shanten_cost，只在同向听候选间重排。
            score -= edge_w * edge_bias(d)
        if best_score is None or score < best_score - 1e-9:
            best_score = score
            best_d = d
            tied = [d]
        elif abs(score - best_score) <= 1e-9:
            tied.append(d)
    if wait_width == "tiebreak" and wait_tie_eps > 0 and best_score is not None:
        # 「近似并列」版本：把与最优分相差 ≤ eps×|最优分| 的候选也算进并列集合
        # （实测多数分歧发生在分数并列时；放宽一点让听口宽度有机会参与定夺）
        tol = abs(best_score) * wait_tie_eps
        tied = []
        for d in pool:
            if s_map[d] > bound:
                continue
            c = list(hand)
            c[d] -= 1
            fan = _fan_for(c)
            if s_map[d] == 0:
                uv = ting_count(c, remain, melds)
            elif wait_width == "full":
                uv = ukeire_wait_width(hand, d, remain, melds)
            elif baotou_route or not depth:
                uv = ukeire_quality(hand, d, remain, melds)
            else:
                uv = ukeire_depth(hand, d, remain, melds)
            sc = s_map[d] * shanten_cost - uv * ukeire_w - fan * fan_w * dealer_mult
            if d1_pen is not None:
                sc += d1_pen[d]
            if protect_gang and hand[d] >= 4:
                sc += gang_keep_pen
            if sc <= best_score + tol:
                tied.append(d)
    if wait_width == "tiebreak" and len(tied) > 1:
        # P1-a：并列时（实测分歧都发生在并列点）改用「进张 × 落地听口宽度」挑
        best_d = max(tied, key=lambda d: ukeire_wait_width(hand, d, remain, melds))
    return best_d


def discard_decision_full(hand, remain=None, melds=0, depth=True, dealer=False):
    """出牌决策，返回 (出牌, 打后向听数, 进张质量)，供调试与调优。"""
    best = discard_decision(hand, remain, melds, depth, dealer)
    return best, shanten_after_discard(hand, best, melds), ukeire_quality(hand, best, remain, melds)
