"""路线规划：多目标最短路径 + 时间感知的访问顺序优化。

代价模型（可配权重）：
  路径代价 = 距离 × (1 + 坡度惩罚×坡度) × (1 + 拥挤惩罚×拥挤度)
             × (婴儿车不友好倍率)
  总得分   = 路径代价 + 等表演惩罚 + 午餐偏离窗口惩罚 + 超时惩罚 - 看表演奖励
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Optional

from .models import ZooGraph, Edge

EXHAUSTIVE_LIMIT = 8  # 动物区数量 <= 8 时全排列枚举，否则用贪心+2-opt


def parse_time(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def fmt_time(t: float) -> str:
    t = int(round(t))
    return f"{t // 60:02d}:{t % 60:02d}"


@dataclass
class Preferences:
    has_stroller: bool = True          # 是否推儿童车
    walk_speed_mpm: float = 55.0       # 带娃步行速度（米/分钟）
    start_time: str = "09:00"
    lunch_window: tuple = ("11:30", "13:00")
    lunch_duration_min: int = 45
    want_shows: bool = True            # 是否想看表演
    max_wait_for_show_min: int = 30    # 为一场表演最多等多久
    max_total_min: int = 300           # 半日游总时长预算
    show_bonus: float = 500.0          # 看一场表演的奖励分
    wait_penalty_per_min: float = 2.0
    lunch_deviation_per_min: float = 6.0
    overtime_per_min: float = 8.0
    slope_penalty: float = 0.08        # 每 1% 坡度的代价增幅
    congestion_penalty: float = 1.5    # 拥挤代价权重
    stroller_penalty: float = 5.0      # 婴儿车不友好路段代价倍率


# ---------------- 单条边的代价与耗时 ----------------

def edge_cost(edge: Edge, p: Preferences) -> float:
    cost = edge.distance_m
    cost *= 1.0 + p.slope_penalty * edge.slope_pct
    cost *= 1.0 + p.congestion_penalty * edge.congestion
    if p.has_stroller and not edge.stroller_friendly:
        cost *= p.stroller_penalty
    return cost


def edge_minutes(edge: Edge, p: Preferences) -> float:
    speed = p.walk_speed_mpm
    speed /= 1.0 + 0.04 * edge.slope_pct   # 上坡减速
    speed *= 1.0 - 0.5 * edge.congestion   # 拥挤减速
    minutes = edge.distance_m / max(speed, 1.0)
    if p.has_stroller and not edge.stroller_friendly:
        minutes *= 1.5                     # 抬车、找坡道
    return minutes


@dataclass
class PathInfo:
    nodes: list
    cost: float
    minutes: float
    distance_m: float


def shortest_path(graph: ZooGraph, start: str, goal: str, p: Preferences) -> PathInfo:
    """按偏好加权代价的 Dijkstra 最短路。"""
    for nid in (start, goal):
        if nid not in graph.nodes:
            raise KeyError(f"未知节点: {nid}")
    if start == goal:
        return PathInfo(nodes=[start], cost=0.0, minutes=0.0, distance_m=0.0)

    dist = {start: 0.0}
    prev = {}
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == goal:
            break
        if d > dist.get(u, float("inf")):
            continue
        for e in graph.neighbors(u):
            v = e.other(u)
            nd = d + edge_cost(e, p)
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, e)
                heapq.heappush(pq, (nd, v))
    if goal not in dist:
        raise ValueError(f"{start} 与 {goal} 之间没有可达道路")

    nodes, edges, cur = [goal], [], goal
    while cur != start:
        u, e = prev[cur]
        edges.append(e)
        nodes.append(u)
        cur = u
    nodes.reverse()
    edges.reverse()
    return PathInfo(
        nodes=nodes,
        cost=dist[goal],
        minutes=sum(edge_minutes(e, p) for e in edges),
        distance_m=sum(e.distance_m for e in edges),
    )


# ---------------- 路线结果 ----------------

@dataclass
class Stop:
    node_id: str
    name: str
    arrive: float
    depart: float
    note: str = ""


@dataclass
class Leg:
    frm: str
    to: str
    path: list
    distance_m: float
    minutes: float
    cost: float


@dataclass
class RoutePlan:
    stops: list
    legs: list
    total_distance_m: float
    total_minutes: float
    score: float
    shows: list = field(default_factory=list)
    lunch_start: Optional[float] = None
    warnings: list = field(default_factory=list)

    def itinerary(self, graph: ZooGraph) -> str:
        lines = [f"{fmt_time(self.stops[0].depart)}  从【{self.stops[0].name}】出发"]
        for leg, stop in zip(self.legs, self.stops[1:]):
            names = " → ".join(graph.nodes[n].name for n in leg.path)
            lines.append(f"  🚶 步行 {leg.distance_m:.0f}m / 约{leg.minutes:.0f}分钟（{names}）")
            if stop.depart > stop.arrive:
                lines.append(f"{fmt_time(stop.arrive)}–{fmt_time(stop.depart)}  【{stop.name}】{stop.note}")
            else:
                lines.append(f"{fmt_time(stop.arrive)}  到达【{stop.name}】{stop.note}")
        lines.append(
            f"—— 全程 {self.total_distance_m:.0f}m，"
            f"用时 {self.total_minutes:.0f} 分钟，"
            f"观看表演 {len(self.shows)} 场 ——"
        )
        for w in self.warnings:
            lines.append(f"⚠️  {w}")
        return "\n".join(lines)


# ---------------- 规划器 ----------------

class RoutePlanner:
    def __init__(self, graph: ZooGraph):
        self.graph = graph

    def plan(self, entrance: str, exit: str, animal_zones: list,
             lunch_spot: Optional[str] = None,
             prefs: Optional[Preferences] = None) -> RoutePlan:
        p = prefs or Preferences()
        zones = list(dict.fromkeys(animal_zones))  # 去重保序
        self._validate(entrance, exit, zones, lunch_spot)

        pois = [entrance, exit, *zones] + ([lunch_spot] if lunch_spot else [])
        matrix = {a: {b: shortest_path(self.graph, a, b, p)
                      for b in pois if b != a} for a in pois}

        best = None
        for seq in self._candidate_orders(zones, entrance, exit, matrix):
            for full in self._with_lunch(seq, lunch_spot):
                plan = self._simulate(entrance, exit, full, lunch_spot, matrix, p)
                if best is None or plan.score < best.score:
                    best = plan
        return best

    # ---------- 校验 ----------
    def _validate(self, entrance, exit, zones, lunch_spot):
        for nid, label in [(entrance, "入口"), (exit, "出口")]:
            if nid not in self.graph.nodes:
                raise ValueError(f"{label}不存在: {nid}")
        for z in zones:
            if z not in self.graph.nodes:
                raise ValueError(f"动物区不存在: {z}")
            if self.graph.nodes[z].kind != "animal":
                raise ValueError(f"{z} 不是动物区节点")
        if lunch_spot is not None:
            if lunch_spot not in self.graph.nodes:
                raise ValueError(f"午餐点不存在: {lunch_spot}")
            if self.graph.nodes[lunch_spot].kind != "restaurant":
                raise ValueError(f"{lunch_spot} 不是餐厅节点")

    # ---------- 访问顺序 ----------
    def _candidate_orders(self, zones, entrance, exit_, matrix):
        if len(zones) <= EXHAUSTIVE_LIMIT:
            yield from itertools.permutations(zones)
        else:  # 大实例：贪心最近邻 + 2-opt
            yield self._greedy_2opt(zones, entrance, exit_, matrix)

    def _greedy_2opt(self, zones, entrance, exit_, matrix):
        remaining, cur, order = set(zones), entrance, []
        while remaining:
            nxt = min(remaining, key=lambda z: matrix[cur][z].cost)
            order.append(nxt)
            remaining.discard(nxt)
            cur = nxt

        def travel(seq):
            pts = [entrance, *seq, exit_]
            return sum(matrix[a][b].cost for a, b in zip(pts, pts[1:]))

        best, improved = travel(order), True
        while improved:
            improved = False
            for i in range(len(order) - 1):
                for j in range(i + 1, len(order)):
                    cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    c = travel(cand)
                    if c < best - 1e-9:
                        order, best, improved = cand, c, True
        return tuple(order)

    @staticmethod
    def _with_lunch(seq, lunch_spot):
        if lunch_spot is None:
            yield list(seq)
        else:
            for i in range(len(seq) + 1):
                yield list(seq[:i]) + [lunch_spot] + list(seq[i:])

    # ---------- 时间轴模拟 ----------
    def _simulate(self, entrance, exit_, seq, lunch_spot, matrix, p) -> RoutePlan:
        t = parse_time(p.start_time)
        start_t = t
        stops, legs, shows, warnings = [], [], [], []
        score, total_dist, lunch_start = 0.0, 0.0, None
        cur = entrance
        stops.append(Stop(entrance, self.graph.nodes[entrance].name, t, t, ""))

        for nxt in list(seq) + [exit_]:
            path = matrix[cur][nxt]
            t += path.minutes
            score += path.cost
            total_dist += path.distance_m
            legs.append(Leg(cur, nxt, path.nodes, path.distance_m, path.minutes, path.cost))

            node = self.graph.nodes[nxt]
            arrive = t
            if nxt == exit_:
                stops.append(Stop(nxt, node.name, arrive, arrive, "行程结束"))
            elif nxt == lunch_spot:
                lunch_start = arrive
                depart = arrive + p.lunch_duration_min
                stops.append(Stop(nxt, node.name, arrive, depart,
                                  f"午餐 {p.lunch_duration_min} 分钟"))
                t = depart
            else:  # 动物区
                show = self._pick_show(node, arrive, p)
                if show:
                    s = parse_time(show.start)
                    wait = s - arrive
                    score += wait * p.wait_penalty_per_min
                    score -= p.show_bonus
                    shows.append(f"{node.name}《{show.title}》{show.start}")
                    depart = s + show.duration_min + 10  # 表演后稍作游览
                    note = (f"观看表演《{show.title}》{show.start} 开始 "
                            f"{show.duration_min} 分钟" +
                            (f"（等候 {wait:.0f} 分钟）" if wait >= 1 else ""))
                else:
                    depart = arrive + node.visit_minutes
                    note = f"游览约 {node.visit_minutes} 分钟"
                stops.append(Stop(nxt, node.name, arrive, depart, note))
                t = depart
            cur = nxt

        # 午餐时间窗口惩罚
        if lunch_spot is not None:
            ws, we = parse_time(p.lunch_window[0]), parse_time(p.lunch_window[1])
            dev = max(0, ws - lunch_start) + max(0, lunch_start - we)
            if dev > 0:
                score += dev * p.lunch_deviation_per_min
                warnings.append(
                    f"午餐开始于 {fmt_time(lunch_start)}，"
                    f"偏离理想窗口 {p.lunch_window[0]}–{p.lunch_window[1]}")

        total = t - start_t
        if total > p.max_total_min:
            score += (total - p.max_total_min) * p.overtime_per_min
            warnings.append(
                f"总用时 {total:.0f} 分钟，超出半日预算 {p.max_total_min} 分钟")
        if p.want_shows and not shows:
            warnings.append("时间窗口内没有可衔接的表演")

        return RoutePlan(
            stops=stops, legs=legs,
            total_distance_m=total_dist, total_minutes=total,
            score=score, shows=shows, lunch_start=lunch_start,
            warnings=warnings,
        )

    @staticmethod
    def _pick_show(node, arrive, p):
        if not p.want_shows or not node.shows:
            return None
        cands = [s for s in node.shows
                 if 0 <= parse_time(s.start) - arrive <= p.max_wait_for_show_min]
        return min(cands, key=lambda s: parse_time(s.start)) if cands else None
