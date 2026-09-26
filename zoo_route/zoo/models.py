"""数据模型：园区节点、道路（边）与图结构。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


def edge_id(a: str, b: str) -> str:
    """无向边的唯一标识。"""
    return "|".join(sorted((a, b)))


@dataclass
class Show:
    start: str                 # "HH:MM"
    duration_min: int = 20
    title: str = "动物表演"


@dataclass
class Node:
    id: str
    name: str
    kind: str                  # gate / animal / restaurant / junction
    x: float = 0.0
    y: float = 0.0
    visit_minutes: int = 30    # 默认游玩时长
    shows: list = field(default_factory=list)


@dataclass
class Edge:
    a: str
    b: str
    distance_m: float
    slope_pct: float = 0.0         # 坡度百分比
    stroller_friendly: bool = True # 是否婴儿车友好
    congestion: float = 0.0        # 拥挤度 0~1（管理员维护）

    @property
    def id(self) -> str:
        return edge_id(self.a, self.b)

    def other(self, node_id: str) -> str:
        return self.b if node_id == self.a else self.a


class ZooGraph:
    """园区图：节点 + 无向边。"""

    def __init__(self) -> None:
        self.nodes: dict = {}
        self.edges: dict = {}
        self._adj: dict = {}

    # ---------- 节点 ----------
    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self._adj.setdefault(node.id, [])

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise KeyError(f"未知节点: {node_id}")
        for e in list(self._adj.get(node_id, [])):
            self.remove_edge(e.a, e.b)
        del self.nodes[node_id]
        self._adj.pop(node_id, None)

    # ---------- 边 ----------
    def add_edge(self, edge: Edge) -> None:
        for nid in (edge.a, edge.b):
            if nid not in self.nodes:
                raise KeyError(f"未知节点: {nid}")
        if edge.id in self.edges:
            raise ValueError(f"道路已存在: {edge.a} <-> {edge.b}")
        self.edges[edge.id] = edge
        self._adj[edge.a].append(edge)
        self._adj[edge.b].append(edge)

    def remove_edge(self, a: str, b: str) -> None:
        eid = edge_id(a, b)
        if eid not in self.edges:
            raise KeyError(f"未知道路: {a} <-> {b}")
        e = self.edges.pop(eid)
        self._adj[e.a].remove(e)
        self._adj[e.b].remove(e)

    def get_edge(self, a: str, b: str) -> Edge:
        eid = edge_id(a, b)
        if eid not in self.edges:
            raise KeyError(f"未知道路: {a} <-> {b}")
        return self.edges[eid]

    def neighbors(self, node_id: str) -> list:
        return list(self._adj.get(node_id, []))

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ZooGraph":
        g = cls()
        for nd in data["nodes"]:
            nd = dict(nd)
            nd["shows"] = [Show(**s) for s in nd.get("shows", [])]
            g.add_node(Node(**nd))
        for ed in data["edges"]:
            g.add_edge(Edge(**ed))
        return g

    def save(self, path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path) -> "ZooGraph":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
