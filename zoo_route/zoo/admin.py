"""管理员后台：维护园区节点、道路连接与拥挤程度。"""
from __future__ import annotations

from collections import deque

from .models import ZooGraph, Node, Edge, Show, edge_id


class ZooAdmin:
    def __init__(self, graph: ZooGraph = None):
        self.graph = graph or ZooGraph()

    # ---------- 节点维护 ----------
    def add_node(self, node: Node) -> None:
        if node.id in self.graph.nodes:
            raise ValueError(f"节点已存在: {node.id}")
        if node.kind not in ("gate", "animal", "restaurant", "junction"):
            raise ValueError(f"非法节点类型: {node.kind}")
        self.graph.add_node(node)

    def update_node(self, node_id: str, **fields) -> None:
        node = self._node(node_id)
        for k, v in fields.items():
            if k == "shows":
                v = [s if isinstance(s, Show) else Show(**s) for s in v]
            if not hasattr(node, k):
                raise ValueError(f"节点没有属性: {k}")
            setattr(node, k, v)

    def remove_node(self, node_id: str) -> None:
        self.graph.remove_node(node_id)  # 关联道路一并删除

    # ---------- 道路维护 ----------
    def add_edge(self, edge: Edge) -> None:
        self._check_congestion(edge.congestion)
        self.graph.add_edge(edge)

    def update_edge(self, a: str, b: str, **fields) -> None:
        edge = self.graph.get_edge(a, b)
        for k, v in fields.items():
            if k == "congestion":
                self._check_congestion(v)
            if not hasattr(edge, k):
                raise ValueError(f"道路没有属性: {k}")
            setattr(edge, k, v)

    def remove_edge(self, a: str, b: str) -> None:
        self.graph.remove_edge(a, b)

    # ---------- 拥挤度 ----------
    def set_congestion(self, a: str, b: str, level: float) -> None:
        """实时更新某段道路的拥挤度（0=畅通，1=严重拥堵）。"""
        self._check_congestion(level)
        self.graph.get_edge(a, b).congestion = level

    def congestion_report(self) -> list:
        """按拥挤度降序返回 (道路, 两端节点名) 列表，便于大屏展示。"""
        rows = []
        for e in sorted(self.graph.edges.values(),
                        key=lambda e: e.congestion, reverse=True):
            rows.append((e, self.graph.nodes[e.a].name, self.graph.nodes[e.b].name))
        return rows

    # ---------- 校验与持久化 ----------
    def validate(self) -> list:
        """返回问题列表：空列表表示园区图健康。"""
        issues = []
        gates = [n for n in self.graph.nodes.values() if n.kind == "gate"]
        if not gates:
            issues.append("园区缺少大门(gate)节点")
            return issues
        # 从第一个大门 BFS，检查所有节点可达
        seen = {gates[0].id}
        q = deque([gates[0].id])
        while q:
            u = q.popleft()
            for e in self.graph.neighbors(u):
                v = e.other(u)
                if v not in seen:
                    seen.add(v)
                    q.append(v)
        for n in self.graph.nodes.values():
            if n.id not in seen:
                issues.append(f"节点从大门不可达: {n.name}({n.id})")
        for e in self.graph.edges.values():
            if e.distance_m <= 0:
                issues.append(f"道路距离必须为正: {e.a}<->{e.b}")
        return issues

    def save(self, path) -> None:
        self.graph.save(path)

    @classmethod
    def load(cls, path) -> "ZooAdmin":
        return cls(ZooGraph.load(path))

    # ---------- 内部 ----------
    def _node(self, node_id: str) -> Node:
        if node_id not in self.graph.nodes:
            raise KeyError(f"未知节点: {node_id}")
        return self.graph.nodes[node_id]

    @staticmethod
    def _check_congestion(level: float) -> None:
        if not 0.0 <= level <= 1.0:
            raise ValueError("拥挤度必须在 0~1 之间")
