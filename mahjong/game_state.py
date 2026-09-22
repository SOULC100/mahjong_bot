"""局面状态管理：解析服务器快照，维护手牌/副露/弃牌/牌墙剩余。

协议字段（从真实数据确认，2026-09 实测修正）：
- my_hand: 我的手牌（**已含刚摸的牌**；draw 阶段 14 张、其余 13 张）
- drawn_tile: 刚摸的那张牌（指针字段，仅用于抓打圈/胡牌门禁；非 draw 阶段为空）
- discards: 4 家弃牌列表
- melds: 4 家副露（碰/杠/吃）
- wall_remaining: 牌墙剩余张数
- god: {baotou, chain_count, catch_play, god_discarder_seat}
  （2026-09-03：服务端实发 chain_count 非 piao_count；
    2026-09-08 v26：新增 god_discarder_seat = 打财神者座位，无圈 = -1）
- allowed_actions: ["discard:8w", "pass:", "chi:8t", "peng:发", ...]
"""

from .tiles import NUM_TILES, LAIZI_INDEX, tile_from_str, empty_counts, hand_from_strs


class GameState:
    def __init__(self):
        self.my_hand = empty_counts()   # 13 张手牌（不含 drawn）
        self.drawn_tile = -1            # 刚摸的牌，-1 表示无
        self.my_melds = []              # 我的副露（占位）
        self.discards = [[] for _ in range(4)]  # 4 家弃牌
        self.melds = [[] for _ in range(4)]     # 4 家副露
        self.wall_remaining = 0
        self.hand_counts = []           # 4 家暗手张数
        self.god = {}
        self.my_seat = 0
        self.remain = [4.0] * NUM_TILES  # 牌墙剩余估算（贝叶斯期望张数）
        # 未见的**原始张数**（4 − 可见，不做牌墙缩放）——与 sim `Game.remain_estimate` 同口径。
        # 绝对张数类的判据（如 R15「窄搭子」吃门控 narrow_max_accept）必须用它：
        # 用上面缩放过的 remain 会让同一个阈值在线上/离线含义不同（线上 ≈0.47×，见 §22）。
        self.raw_unseen = [4] * NUM_TILES

    def update_from_snapshot(self, snap):
        """从服务器快照更新局面。"""
        if snap.get("my_hand"):
            self.my_hand = hand_from_strs(snap["my_hand"])
        dt = snap.get("drawn_tile", "")
        self.drawn_tile = tile_from_str(dt) if dt else -1
        if snap.get("discards"):
            self.discards = [[tile_from_str(t) for t in lst] for lst in snap["discards"]]
        if snap.get("melds"):
            self.melds = snap["melds"]
        self.wall_remaining = snap.get("wall_remaining", 0)
        if snap.get("hand_counts"):
            self.hand_counts = snap["hand_counts"]
        if snap.get("god"):
            self.god = snap["god"]
        if snap.get("seat") is not None:
            self.my_seat = snap["seat"]
        self._recalc_remain()

    def _recalc_remain(self):
        """贝叶斯估算每种牌在牌墙中的剩余张数。

        已知可见牌：我的手牌 + 刚摸的 + 所有弃牌 + **4 家副露**（2026-09-21 修正）。
        未见牌分布在「对手暗手」和「牌墙」之间，按比例分配到牌墙。

        2026-09-21 修正：旧实现漏算副露（只算我的手牌 + 弃牌），已经被吃/碰/杠掉的牌
        仍被当成"牌墙里还有" → 依赖这些死张的搭子被高估。sim 的 `Game.remain_estimate`
        一直是算副露的，所以线上/离线的**进张质量输入口径不同**（实测 3.48% 出牌点被翻转，
        见 `data/_parity_report.txt`；冻结基准里 `live_remain` 方案量化过它的代价）。
        鸣牌 ukeire 门控（CLAIM_UKEIRE_GATE）依赖这个 remain，口径必须与 sim 一致。
        """
        visible = [0] * NUM_TILES
        for t in range(NUM_TILES):
            visible[t] = self.my_hand[t]  # my_hand 已含刚摸的牌，不再叠加 drawn_tile
            for lst in self.discards:
                visible[t] += lst.count(t)
        for row in self.melds:  # 4 家副露都是公开信息（碰/吃/杠各 3~4 张）
            if not isinstance(row, list):
                continue
            for m in row:
                if not isinstance(m, dict):
                    continue
                for s in (m.get("tiles") or []):
                    try:
                        visible[tile_from_str(s)] += 1
                    except Exception:  # noqa: BLE001 - 未知牌面字符串不计入估算
                        continue

        # 对手暗手张数（从 hand_counts 推断）
        my_hand_cnt = sum(self.my_hand)
        if self.hand_counts:
            hidden_opp = max(0, sum(self.hand_counts) - my_hand_cnt)
        else:
            hidden_opp = 39  # 无 hand_counts 时用默认（3 家 × 13）

        total_unseen = self.wall_remaining + hidden_opp
        remain = [0.0] * NUM_TILES
        self.raw_unseen = [max(0, 4 - visible[t]) for t in range(NUM_TILES)]
        if total_unseen <= 0:
            self.remain = remain
            return
        for t in range(NUM_TILES):
            unseen_t = self.raw_unseen[t]
            remain[t] = unseen_t * self.wall_remaining / total_unseen
        self.remain = remain

    def full_hand(self):
        """我的完整手牌，返回 34 维计数。

        服务器快照的 my_hand 已含刚摸的牌（draw 阶段 14 张、其余 13 张），
        直接返回，不再叠加 drawn_tile（否则恒多算 1 张，破坏胡牌判定与守恒校验）。
        """
        return list(self.my_hand)

    def is_baotou(self):
        return bool(self.god.get("baotou"))

    def is_catch_restricted(self):
        """抓打圈是否限制本人（guide v26，2026-09-08）。

        受限 ⇔ catch_play 且本人不是打财神者：圈内**打财神者本人豁免**（可吃/碰/明杠/
        补杠、可任意出牌、吃碰后继续打财神 = 财飘链 +1）。旧服务端无 god_discarder_seat
        → 取默认 -1 ≠ seat → 与旧行为（一律受限）一致。
        """
        if not self.god.get("catch_play"):
            return False
        return self.god.get("god_discarder_seat", -1) != self.my_seat

    def chi_meld_count(self):
        """本人吃摊数 = melds[seat] 中 kind=="chi" 的组数（guide v25 服务端强制 ≤2）。

        解析不出（老格式/字段缺失）返回 None = 不做本地门禁，交给服务端 409 兜底。
        """
        if not (0 <= self.my_seat < len(self.melds)):
            return None
        row = self.melds[self.my_seat]
        if not isinstance(row, list):
            return None
        n = 0
        for m in row:
            if not isinstance(m, dict):
                return None
            if str(m.get("kind", "")).lower() == "chi":
                n += 1
        return n

    def peng_meld_tiles(self):
        """本人**已碰**的牌（tile 索引列表；碰后手里再摸到第 4 张即可补杠）。

        解析不出（老格式/字段缺失）返回 [] = 不做补杠（保守），不抛异常。
        """
        out = []
        if not (0 <= self.my_seat < len(self.melds)):
            return out
        row = self.melds[self.my_seat]
        if not isinstance(row, list):
            return out
        for m in row:
            if not isinstance(m, dict):
                continue
            if str(m.get("kind", "")).lower() != "peng":
                continue
            tiles = m.get("tiles") or []
            if not tiles:
                continue
            try:
                t = tile_from_str(tiles[0])
            except Exception:  # noqa: BLE001 - 未知牌面字符串跳过
                continue
            if t != LAIZI_INDEX:  # 财神不能被碰/杠（防御性）
                out.append(t)
        return out

    def piao_count(self):
        """动作链计数（杠/飘连乘 ×2）。服务端字段为 chain_count（2026-09-03 更正），
        旧 piao_count 已不存在。无调用方，保留为兼容读数。"""
        return int(self.god.get("chain_count", self.god.get("piao_count", 0)))
