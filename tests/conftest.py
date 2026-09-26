"""共享夹具：一个 9 节点的小型测试园区，结构简单、便于断言。

E1 入口 ─ J1 广场 ─ A1 熊猫 ─ A2 狮虎 ─ E2 出口
            │        │  ╲（石阶捷径，儿童车限行）
            A3 大象 ─┴   L1 餐厅
            │
            A4 鸟林（孤悬，只经 A3 到达）
"""
import pytest

from zoo_tour.graph import ZooGraph
from zoo_tour.models import Node, Edge, NodeType, Congestion, Show


@pytest.fixture
def small_zoo():
    g = ZooGraph(name="测试动物园")
    nodes = [
        Node("E1", "入口", NodeType.ENTRANCE),
        Node("E2", "出口", NodeType.EXIT),
        Node("J1", "广场", NodeType.JUNCTION),
        Node("A1", "熊猫", NodeType.ANIMAL, x=100, y=50,
             shows=[Show("喂食", 9 * 60 + 30, 20)]),
        Node("A2", "狮虎", NodeType.ANIMAL,
             shows=[Show("投喂", 10 * 60, 20)]),
        Node("A3", "大象", NodeType.ANIMAL),
        Node("A4", "鸟林", NodeType.ANIMAL),
        Node("L1", "餐厅", NodeType.LUNCH),
    ]
    for n in nodes:
        g.add_node(n)
    edges = [
        Edge("E1", "J1", 120),
        Edge("J1", "A1", 260),
        Edge("J1", "A3", 100),
        Edge("A1", "A2", 200, slope=10),
        Edge("A2", "E2", 120),
        Edge("A3", "A4", 100),
        Edge("A3", "A1", 70, slope=12, stroller_ok=False,
             has_steps=True, name="石阶捷径"),
        Edge("J1", "L1", 240, congestion=Congestion.HIGH),
        Edge("L1", "E2", 120),
    ]
    for e in edges:
        g.add_edge(e)
    return g
