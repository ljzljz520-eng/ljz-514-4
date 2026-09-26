"""半日亲子路线规划。

思路：
1. 先对“入口/出口/动物区/午餐点”求两两最短路（综合距离、坡度、
   拥挤、儿童车限行）。
2. 枚举动物区参观顺序（最多 7 个展区），并在每个可能的位置插入午餐。
3. 逐方案做时间轴仿真：步行 -> 展区（可等待并观看表演）-> 午餐 -> 出口，
   累计综合评分（越低越好）。
4. 选出时间预算内的最佳方案；全部超时则给出“删减展区”的贪心建议。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
from typing import Optional

from .graph import ZooGraph, PathResult, ZooGraphError
from .models import Node, NodeType, Show, WalkProfile, fmt_time

# ---- 评分参数 ----
SHOW_BONUS = 50.0                 # 赶上一场表演的奖励（评分减去）
WAIT_PENALTY_RATE = 0.5           # 原地等待每分钟的代价
LUNCH_DEVIATION_RATE = 0.8        # 午餐开始时间偏离偏好的代价/分钟
CROWD_QUEUE_FACTOR = 0.3          # 拥挤排队时间的折扣代价
OVERTIME_PENALTY_RATE = 3.0       # 超出半日预算的代价/分钟
DEFAULT_BUDGET_MINUTES = 240      # 半日 = 4 小时
DEFAULT_START_MINUTE = 9 * 60
DEFAULT_LUNCH_MINUTE = 12 * 60
DEFAULT_LATE_GRACE = 5            # 表演开始后多少分钟内赶到仍可入场
MAX_SHOW_WAIT = 25                 # 等一场表演最多等多久（分钟），超时放弃该场
MAX_LUNCH_WAIT = 15                # 未到偏好午餐时间时最多等多久，之后提前用餐
MAX_ANIMALS = 7


@dataclass
class PlanRequest:
    entrance: str
    exit: str
    animals: list                      # 想看的动物区节点 id（按意愿排序）
    lunch: Optional[str] = None        # 午餐点 id
    start_minute: int = DEFAULT_START_MINUTE
    time_budget: int = DEFAULT_BUDGET_MINUTES
    preferred_lunch: int = DEFAULT_LUNCH_MINUTE
    stroller: bool = True
    profile: Optional[WalkProfile] = None
    show_late_grace: int = DEFAULT_LATE_GRACE
    max_show_wait: int = MAX_SHOW_WAIT
    max_lunch_wait: int = MAX_LUNCH_WAIT

    @property
    def deadline(self) -> int:
        return self.start_minute + self.time_budget

    @property
    def day_end(self) -> int:
        return self.deadline


@dataclass
class Simulation:
    """单条候选路线的时间轴仿真结果。"""
    sequence: list                     # 含午餐点的完整参观顺序
    lunch_index: int
    feasible: bool
    finish_minute: float
    score: float
    walk_minutes: float                # 感知步行分钟合计
    raw_walk_minutes: float            # 纯距离/速度合计（不含惩罚）
    walk_distance: float               # 总步行米数
    shows_seen: list = field(default_factory=list)   # [(node_id, show_name, start)]
    timeline: list = field(default_factory=list)
    overtime: float = 0.0
    warning: Optional[str] = None

    def summary_key(self):
        # 可行优先，再按评分、距离、结束时间排序，保证结果稳定
        return (not self.feasible, round(self.score, 4),
                round(self.walk_distance, 1), round(self.finish_minute, 2))


@dataclass
class Suggestion:
    """无法按预算完成时的删减建议。"""
    dropped: list
    reduced_sequence: list
    reduced_simulation: Optional[Simulation]
    reason: str


@dataclass
class RoutePlan:
    request: PlanRequest
    best: Optional[Simulation]
    alternatives: list
    suggestion: Optional[Suggestion]
    evaluated: int

    @property
    def feasible(self) -> bool:
        return self.best is not None and self.best.feasible


# ------------------------------------------------------------------
# 单方案时间轴仿真
# ------------------------------------------------------------------
def _pick_show(node: Node, arrival: float, day_end: float, late_grace: int,
           max_wait: int = MAX_SHOW_WAIT):
    """选择到达后能赶上的最合适场次：优先能完整等待的最近一场。"""
    if not node.shows:
        return None
    upcoming = [s for s in node.shows
                if s.start_minute + s.duration <= day_end
                and 0 <= s.start_minute - arrival <= max_wait]
    if upcoming:
        return min(upcoming, key=lambda s: s.start_minute)
    # 表演已经开始但在宽限内：可观看剩余部分
    for s in sorted(node.shows, key=lambda s: s.start_minute):
        if (s.start_minute < arrival < s.end_minute
                and arrival - s.start_minute <= late_grace
                and s.end_minute <= day_end):
            return s
    return None


def simulate(graph: ZooGraph, pair_paths: dict, sequence: list,
             lunch_index: int, req: PlanRequest) -> Simulation:
    """按 sequence（动物区，午餐通过 lunch_index 标记插入位置）仿真。

    lunch_index = k 表示在第 k 个动物区之后吃午餐（0=先吃，n=最后吃）。
    """
    timeline = []
    cur = req.entrance
    t = float(req.start_minute)
    deadline = req.deadline

    walk_minutes = raw_walk_minutes = walk_distance = 0.0
    score = 0.0
    shows_seen = []
    warning = None

    def do_walk(dest: str, t_now: float):
        key = (cur, dest)
        path = pair_paths.get(key)
        if path is None:
            raise ZooGraphError(f"{cur} 到 {dest} 不可达")
        return path

    full_seq = list(sequence)
    if req.lunch:
        full_seq.insert(lunch_index, req.lunch)
    lunch_done = False
    animals_done = 0

    for nid in full_seq:
        node = graph.node(nid)
        path = do_walk(nid, t)
        if path.nodes:
            timeline.append({
                "kind": "walk", "start": t, "end": t + path.cost,
                "from": cur, "to": nid, "path": path,
            })
        t += path.cost
        walk_minutes += path.cost
        raw_walk_minutes += path.distance / (
            req.profile.walking_speed if req.profile else 60.0)
        walk_distance += path.distance
        cur = nid
        arrival = t
        queue = node.queue_extra()

        if nid == req.lunch:
            # ---- 午餐 ----
            early = req.preferred_lunch - arrival
            if early > 0:
                lunch_wait = min(early, float(req.max_lunch_wait))
                lunch_start = arrival + lunch_wait
            else:
                lunch_wait = 0.0
                lunch_start = arrival
            dwell = node.base_dwell() + queue
            departure = lunch_start + dwell
            timeline.append({
                "kind": "stop", "stop_type": "lunch", "node": nid,
                "arrival": arrival, "start": arrival, "end": departure,
                "active_start": lunch_start,
                "wait": lunch_wait, "queue": queue, "dwell": dwell,
                "show": None,
            })
            score += lunch_wait * WAIT_PENALTY_RATE
            score += abs(lunch_start - req.preferred_lunch) * LUNCH_DEVIATION_RATE
            score += queue * CROWD_QUEUE_FACTOR
            lunch_done = True
        else:
            # ---- 动物展区 ----
            show = _pick_show(node, arrival, req.day_end,
                              req.show_late_grace, req.max_show_wait)
            wait = watch = 0.0
            if show is not None:
                if arrival <= show.start_minute:
                    wait = show.start_minute - arrival
                    watch = show.duration
                else:
                    wait = 0.0
                    watch = show.end_minute - arrival
                departure = arrival + wait + watch + queue
                shows_seen.append((nid, show.name, show.start_minute))
                score -= SHOW_BONUS
                score += wait * WAIT_PENALTY_RATE
                score += queue * CROWD_QUEUE_FACTOR
            else:
                dwell = node.base_dwell() + queue
                departure = arrival + dwell
            timeline.append({
                "kind": "stop", "stop_type": "animal", "node": nid,
                "arrival": arrival,
                "start": arrival, "end": departure,
                "active_start": arrival + wait,
                "wait": wait, "queue": queue,
                "dwell": (watch + queue) if show is not None
                         else node.base_dwell() + queue,
                "watch": watch if show is not None else 0.0,
                "show": show,
            })
            if show is None:
                score += queue * CROWD_QUEUE_FACTOR
            animals_done += 1
        t = departure

    # ---- 前往出口 ----
    path = do_walk(req.exit, t)
    timeline.append({
        "kind": "walk", "start": t, "end": t + path.cost,
        "from": cur, "to": req.exit, "path": path,
    })
    t += path.cost
    walk_minutes += path.cost
    raw_walk_minutes += path.distance / (
        req.profile.walking_speed if req.profile else 60.0)
    walk_distance += path.distance

    overtime = max(0.0, t - deadline)
    score += walk_minutes
    score += overtime * OVERTIME_PENALTY_RATE
    if overtime > 0:
        warning = f"超出半日预算 {overtime:.0f} 分钟"

    return Simulation(
        sequence=full_seq, lunch_index=lunch_index,
        feasible=overtime <= 0, finish_minute=t, score=score,
        walk_minutes=walk_minutes, raw_walk_minutes=raw_walk_minutes,
        walk_distance=walk_distance, shows_seen=shows_seen,
        timeline=timeline, overtime=overtime, warning=warning,
    )


# ------------------------------------------------------------------
# 枚举与规划
# ------------------------------------------------------------------
def _waypoint_ids(req: PlanRequest) -> list:
    ids = [req.entrance, req.exit] + list(req.animals)
    if req.lunch:
        ids.append(req.lunch)
    return ids


def validate_request(graph: ZooGraph, req: PlanRequest) -> None:
    if len(req.animals) > MAX_ANIMALS:
        raise ZooGraphError(
            f"一次最多选择 {MAX_ANIMALS} 个动物区（当前 {len(req.animals)} 个）")
    if len(set(req.animals)) != len(req.animals):
        raise ZooGraphError("动物区选择有重复")
    e = graph.node(req.entrance)
    if e.ntype not in (NodeType.ENTRANCE, NodeType.EXIT) or not e.can_enter:
        raise ZooGraphError(f"{req.entrance} 不能作为入口")
    x = graph.node(req.exit)
    if x.ntype not in (NodeType.EXIT, NodeType.ENTRANCE) or not x.can_exit:
        raise ZooGraphError(f"{req.exit} 不能作为出口")
    for a in req.animals:
        if graph.node(a).ntype != NodeType.ANIMAL:
            raise ZooGraphError(f"{a} 不是动物展区")
    if req.lunch and graph.node(req.lunch).ntype != NodeType.LUNCH:
        raise ZooGraphError(f"{req.lunch} 不是午餐点")
    if req.preferred_lunch < req.start_minute or req.preferred_lunch > req.deadline:
        raise ZooGraphError("偏好午餐时间不在半日时间窗内")


def _evaluate(graph, pair_paths, animals, req) -> list:
    sims = []
    n = len(animals)
    slots = range(n + 1) if req.lunch else [0]
    for perm in permutations(animals):
        for slot in slots:
            sims.append(simulate(graph, pair_paths, list(perm),
                                 slot if req.lunch else 0, req))
    return sims


def plan_route(graph: ZooGraph, req: PlanRequest) -> RoutePlan:
    validate_request(graph, req)
    if req.profile is None:
        req.profile = WalkProfile(stroller=req.stroller)

    waypoints = _waypoint_ids(req)
    pair_paths = graph.all_pairs_paths(waypoints, req.profile)

    # 连通性检查
    missing = []
    for i, a in enumerate(waypoints):
        for b in waypoints[i + 1:]:
            if (a, b) not in pair_paths:
                missing.append(f"{graph.node(a).name}↔{graph.node(b).name}")
    if missing:
        hint = "（可能被儿童车限行道路阻断，可尝试取消儿童车模式）" if req.stroller else ""
        raise ZooGraphError("以下节点之间不可达: " + "、".join(missing) + hint)

    sims = _evaluate(graph, pair_paths, req.animals, req)
    sims.sort(key=lambda s: s.summary_key())

    feasible = [s for s in sims if s.feasible]
    alternatives = (feasible[1:6] if feasible else [])
    best = sims[0]

    suggestion = None
    if not best.feasible:
        suggestion = _greedy_drop(graph, pair_paths, req)

    return RoutePlan(request=req, best=best, alternatives=alternatives,
                     suggestion=suggestion, evaluated=len(sims))


def _greedy_drop(graph, pair_paths, req: PlanRequest) -> Suggestion:
    """逐个尝试删除“删除后收益最大”的动物区，直到可行或删光。"""
    remaining = list(req.animals)
    dropped = []
    best_sim = None
    while remaining:
        candidates = []
        for victim in remaining:
            subset = [a for a in remaining if a != victim]
            if not subset:
                # 删光动物区：入口->(午餐)->出口
                sim = simulate(graph, pair_paths, [], 0, req)
            else:
                sims = _evaluate(graph, pair_paths, subset, req)
                sim = min(sims, key=lambda s: s.summary_key())
            candidates.append((sim.summary_key(), victim, subset, sim))
        candidates.sort(key=lambda c: c[0])
        _, victim, subset, sim = candidates[0]
        dropped.append(victim)
        remaining = subset
        best_sim = sim
        if sim.feasible:
            return Suggestion(
                dropped=dropped, reduced_sequence=remaining,
                reduced_simulation=sim,
                reason=(f"按当前时间预算无法看完全部展区，"
                        f"建议放弃 {len(dropped)} 个展区："
                        + "、".join(graph.node(d).name for d in dropped)
                        + f"，可在 {fmt_time(sim.finish_minute)} 前到达出口。"))
    return Suggestion(
        dropped=dropped, reduced_sequence=[], reduced_simulation=best_sim,
        reason="即使不参观任何动物区也无法在预算内完成行程，建议增加时间预算。")
