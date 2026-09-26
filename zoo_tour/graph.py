"""园区图：节点/连接的维护、带权最短路（Dijkstra）、JSON 持久化。"""
from __future__ import annotations

import json
import math
import heapq
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import (
    Node, Edge, NodeType, Congestion, WalkProfile, Show,
    EDGE_CONGESTION_FACTOR, CONGESTION_LABEL,
)


class ZooGraphError(Exception):
    """园区图数据错误。"""


@dataclass
class PathResult:
    start: str
    end: str
    nodes: list                     # 路径节点序列
    edges: list                     # 路径上的 Edge 序列
    cost: float                     # 感知步行分钟
    distance: float                 # 实际总距离（米）

    @property
    def stroller_blocked_edges(self) -> list:
        return [e for e in self.edges if not e.stroller_ok]


class ZooGraph:
    def __init__(self, nodes: Optional[list] = None,
                 edges: Optional[list] = None,
                 name: str = "城市动物园"):
        self.name = name
        self._nodes = {}             # id -> Node
        self._adj = {}               # id -> {neighbor: Edge}
        self._path_cache = {}        # (stroller_flag) -> {(s,t): PathResult}
        if nodes:
            for n in nodes:
                self.add_node(n)
        if edges:
            for e in edges:
                self.add_edge(e)

    # ---------- 基本访问 ----------
    @property
    def nodes(self) -> dict:
        return self._nodes

    def node(self, node_id: str) -> Node:
        if node_id not in self._nodes:
            raise ZooGraphError(f"节点不存在: {node_id}")
        return self._nodes[node_id]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def neighbors(self, node_id: str) -> dict:
        return dict(self._adj.get(node_id, {}))

    def edge_between(self, a: str, b: str) -> Optional[Edge]:
        return self._adj.get(a, {}).get(b)

    def all_edges(self) -> list:
        seen, result = set(), []
        for a, nbrs in self._adj.items():
            for b, e in nbrs.items():
                key = tuple(sorted((a, b)))
                if key not in seen:
                    seen.add(key)
                    result.append(e)
        return result

    def nodes_by_type(self, ntype: NodeType) -> list:
        return [n for n in self._nodes.values() if n.ntype == ntype]

    def entrances(self) -> list:
        return [n for n in self._nodes.values()
                if n.ntype == NodeType.ENTRANCE and n.can_enter]

    def exits(self) -> list:
        return [n for n in self._nodes.values()
                if n.ntype == NodeType.EXIT and n.can_exit]

    # ---------- 管理员维护 ----------
    def add_node(self, node: Node) -> None:
        if node.id in self._nodes:
            raise ZooGraphError(f"节点编号已存在: {node.id}")
        self._nodes[node.id] = node
        self._adj[node.id] = {}
        self._invalidate_cache()

    def update_node(self, node_id: str, **changes) -> Node:
        n = self.node(node_id)
        for key, value in changes.items():
            if key == "ntype" or key == "type":
                n.ntype = NodeType.parse(value)
            elif key == "congestion":
                n.congestion = Congestion.parse(value)
            elif key == "shows":
                n.shows = [v if isinstance(v, Show) else Show.from_dict(v)
                           for v in value]
            elif hasattr(n, key):
                setattr(n, key, value)
            else:
                raise ZooGraphError(f"节点没有字段 {key}")
        self._invalidate_cache()
        return n

    def set_node_congestion(self, node_id: str, level) -> Node:
        return self.update_node(node_id, congestion=Congestion.parse(level))

    def remove_node(self, node_id: str) -> None:
        self.node(node_id)
        del self._nodes[node_id]
        self._adj.pop(node_id, None)
        for nbrs in self._adj.values():
            nbrs.pop(node_id, None)
        self._invalidate_cache()

    def add_edge(self, edge: Edge) -> None:
        if edge.a == edge.b:
            raise ZooGraphError(f"道路不能连接节点自身: {edge.a}")
        if edge.a not in self._nodes or edge.b not in self._nodes:
            raise ZooGraphError(f"道路端点不存在: {edge.a}-{edge.b}")
        if edge.distance <= 0:
            raise ZooGraphError("道路距离必须为正数")
        if edge.b in self._adj[edge.a]:
            raise ZooGraphError(f"道路已存在: {edge.a}-{edge.b}")
        self._adj[edge.a][edge.b] = edge
        self._adj[edge.b][edge.a] = edge
        self._invalidate_cache()

    def update_edge(self, a: str, b: str, **changes) -> Edge:
        edge = self.edge_between(a, b)
        if edge is None:
            raise ZooGraphError(f"道路不存在: {a}-{b}")
        if "congestion" in changes:
            changes["congestion"] = Congestion.parse(changes["congestion"])
        for key, value in changes.items():
            if hasattr(edge, key):
                setattr(edge, key, value)
            else:
                raise ZooGraphError(f"道路没有字段 {key}")
        self._invalidate_cache()
        return edge

    def set_edge_congestion(self, a: str, b: str, level) -> Edge:
        return self.update_edge(a, b, congestion=Congestion.parse(level))

    def remove_edge(self, a: str, b: str) -> None:
        if self.edge_between(a, b) is None:
            raise ZooGraphError(f"道路不存在: {a}-{b}")
        self._adj[a].pop(b, None)
        self._adj[b].pop(a, None)
        self._invalidate_cache()

    def validate_connectivity(self) -> list:
        """返回从任意入口可达性问题列表（空列表表示全连通）。"""
        problems = []
        if not self._nodes:
            return ["园区没有节点"]
        start = next(iter(self._nodes))
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt in self._adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        missing = set(self._nodes) - seen
        for m in sorted(missing):
            problems.append(f"节点 {m}({self._nodes[m].name}) 与主园区不连通")
        for nid, n in self._nodes.items():
            if not self._adj[nid] and len(self._nodes) > 1:
                msg = f"节点 {nid}({n.name}) 没有任何连接道路"
                if msg not in problems:
                    problems.append(msg)
        return problems

    # ---------- 道路代价 ----------
    def edge_cost(self, edge: Edge, profile: WalkProfile) -> float:
        """计算一条边的感知通行分钟。"""
        if profile.stroller and profile.strict_stroller and not edge.stroller_ok:
            return math.inf
        base = edge.distance / profile.walking_speed
        slope_factor = profile.slope_factor(edge.slope)
        cong_factor = EDGE_CONGESTION_FACTOR.get(edge.congestion, 1.0)
        cost = base * slope_factor * cong_factor
        if profile.stroller and not edge.stroller_ok:
            cost *= profile.soft_penalty
        return cost

    # ---------- Dijkstra ----------
    def shortest_path(self, source: str, target: str,
                      profile: Optional[WalkProfile] = None) -> PathResult:
        profile = profile or WalkProfile()
        self.node(source)
        self.node(target)
        dist = {source: 0.0}
        walked = {source: 0.0}
        prev = {}
        pq = [(0.0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, math.inf):
                continue
            if u == target:
                break
            for v, edge in self._adj[u].items():
                w = self.edge_cost(edge, profile)
                if w == math.inf:
                    continue
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    walked[v] = walked[u] + edge.distance
                    prev[v] = (u, edge)
                    heapq.heappush(pq, (nd, v))
        if target not in dist:
            raise ZooGraphError(
                f"从 {source} 到 {target} 没有可达路径"
                + "（可能被儿童车限行规则阻断）" if profile.stroller else "")
        # 回溯
        chain, nodes = [], [target]
        cur = target
        while cur != source:
            u, edge = prev[cur]
            chain.append(edge)
            nodes.append(u)
            cur = u
        nodes.reverse()
        chain.reverse()
        return PathResult(source, target, nodes, chain,
                          dist[target], walked[target])

    def all_pairs_paths(self, node_ids: list,
                        profile: Optional[WalkProfile] = None) -> dict:
        """对给定节点集合计算两两最短路（道路无向，利用对称性）。

        返回 {(a,b): PathResult}，a,b 间至少有一个方向被计算。
        """
        profile = profile or WalkProfile()
        result = {}
        ids = list(node_ids)
        for i, s in enumerate(ids):
            dist = {s: 0.0}
            walked = {s: 0.0}
            prev = {}
            pq = [(0.0, s)]
            targets = set(ids[i:])
            found = set()
            while pq:
                d, u = heapq.heappop(pq)
                if d > dist.get(u, math.inf):
                    continue
                if u in targets and u not in found:
                    found.add(u)
                    if found == targets:
                        break
                for v, edge in self._adj[u].items():
                    w = self.edge_cost(edge, profile)
                    if w == math.inf:
                        continue
                    nd = d + w
                    if nd < dist.get(v, math.inf):
                        dist[v] = nd
                        walked[v] = walked[u] + edge.distance
                        prev[v] = (u, edge)
                        heapq.heappush(pq, (nd, v))
            for t in ids[i:]:
                if t == s:
                    result[(s, t)] = PathResult(s, t, [s], [], 0.0, 0.0)
                    continue
                if t not in dist:
                    continue
                chain, nodes = [], [t]
                cur = t
                while cur != s:
                    u, edge = prev[cur]
                    chain.append(edge)
                    nodes.append(u)
                    cur = u
                nodes.reverse()
                chain.reverse()
                pr = PathResult(s, t, nodes, chain, dist[t], walked[t])
                result[(s, t)] = pr
                # 反向复用：道路无向、代价对称，但节点/边顺序需要反转
                result[(t, s)] = PathResult(
                    t, s, list(reversed(nodes)), list(reversed(chain)),
                    dist[t], walked[t])
        return result

    def _invalidate_cache(self) -> None:
        self._path_cache.clear()

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self.all_edges()],
        }

    def save_json(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "ZooGraph":
        g = cls(name=data.get("name", "城市动物园"))
        for nd in data.get("nodes", []):
            g.add_node(Node.from_dict(nd))
        for ed in data.get("edges", []):
            g.add_edge(Edge.from_dict(ed))
        return g

    @classmethod
    def load_json(cls, path) -> "ZooGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    # ---------- 调试/展示 ----------
    def describe_edge(self, edge: Edge) -> str:
        tags = []
        if edge.slope >= 8:
            tags.append(f"坡度{edge.slope:g}%")
        if not edge.stroller_ok:
            tags.append("儿童车限行")
        if edge.has_steps:
            tags.append("台阶")
        cong = CONGESTION_LABEL[edge.congestion]
        if cong != "中":
            tags.append(f"拥挤:{cong}")
        return f"{edge.distance:g}米" + ("（" + "、".join(tags) + "）" if tags else "")
