"""示例园区数据：城市动物园。

布局（坐标单位米）：
  北门 N1 ─ 熊猫馆 A1(缓坡) ─ 狮虎山 A2 ─ 企鹅馆 A4(海滨)
   │            │                  │            │
  主广场 N0 ─ 象馆 A3 ─ 灵长区 A5 ─ 餐厅 L1 ─ 鸟林 A6
   │            │        │
  南门 N2 ─ 儿童动物园 A7 ─ 便利店 L2

A1-N0 另有“石阶捷径”（距离短但台阶+陡坡，儿童车限行），
A2-N1/A2-A1 为山坡路（陡坡、儿童车限行），
旺季时主广场周边、餐厅路段等由管理员调高拥挤度。
"""
from __future__ import annotations

from .graph import ZooGraph
from .models import Node, Edge, NodeType, Congestion


def build_sample_zoo() -> ZooGraph:
    g = ZooGraph(name="城市动物园")

    nodes = [
        # id, name, type, x, y, 其它
        ("N0", "中央广场", NodeType.JUNCTION, 0, 0, {}),
        ("N1", "北门", NodeType.ENTRANCE, -120, 260, {}),
        ("N2", "南门", NodeType.EXIT, -120, -300, {}),
        ("A1", "熊猫馆", NodeType.ANIMAL, 240, 300, {"shows": [("熊猫喂食", "09:30", 20)]}),
        ("A2", "狮虎山", NodeType.ANIMAL, 520, 300, {"shows": [("猛兽喂食", "10:15", 20)]}),
        ("A3", "大象馆", NodeType.ANIMAL, 200, 0, {"shows": [("大象洗澡", "10:30", 25)]}),
        ("A4", "企鹅馆", NodeType.ANIMAL, 720, 220, {"shows": [("企鹅巡游", "11:15", 20)]}),
        ("A5", "灵长动物区", NodeType.ANIMAL, 360, -180, {"shows": [("金丝猴投食", "11:00", 20)]}),
        ("A6", "热带鸟林", NodeType.ANIMAL, 700, -60, {"shows": [("鹦鹉飞行秀", "11:45", 25)]}),
        ("A7", "儿童动物园", NodeType.ANIMAL, 120, -300, {"shows": [("小羊互动", "10:00", 20)]}),
        ("L1", "雨林餐厅", NodeType.LUNCH, 540, -40, {"congestion": Congestion.HIGH}),
        ("L2", "便利店简餐", NodeType.LUNCH, -40, -300, {}),
    ]
    for nid, name, ntype, x, y, extra in nodes:
        shows = []
        for sname, start, dur in extra.get("shows", []):
            from .models import Show
            from .models import parse_hhmm
            shows.append(Show(sname, parse_hhmm(start), dur))
        g.add_node(Node(
            id=nid, name=name, ntype=ntype, x=x, y=y,
            shows=shows,
            congestion=extra.get("congestion", Congestion.NORMAL),
        ))

    # 道路：(a, b, 米, 坡度%, 儿童车可通行, 拥挤, 名称, 台阶)
    C = Congestion
    edges = [
        ("N1", "N0", 300, 2, True, C.NORMAL, None, False),
        ("N1", "A1", 360, 4, True, C.NORMAL, None, False),
        ("A1", "N0", 220, 0, False, C.NORMAL, "石阶捷径", True),
        ("A1", "A2", 300, 12, False, C.NORMAL, None, False),
        ("A1", "A3", 280, 3, True, C.NORMAL, None, False),
        ("A2", "N1", 640, 14, False, C.LOW, "北环山坡路", False),
        ("A2", "A4", 240, 4, True, C.NORMAL, None, False),
        ("A2", "L1", 420, 3, True, C.NORMAL, None, False),
        ("N0", "A3", 220, 0, True, C.HIGH, None, False),
        ("N0", "L2", 320, 2, True, C.NORMAL, None, False),
        ("N0", "N2", 360, 0, True, C.HIGH, None, False),
        ("N2", "L2", 120, 0, True, C.NORMAL, None, False),
        ("N2", "A7", 260, 1, True, C.NORMAL, None, False),
        ("L2", "A7", 200, 0, True, C.NORMAL, None, False),
        ("A7", "A5", 300, 3, True, C.NORMAL, None, False),
        ("A7", "A3", 320, 2, True, C.NORMAL, None, False),
        ("A3", "A5", 300, 2, True, C.NORMAL, None, False),
        ("A5", "L1", 220, 0, True, C.HIGH, "餐厅路", False),
        ("A5", "A6", 360, 2, True, C.NORMAL, None, False),
        ("L1", "A6", 180, 1, True, C.NORMAL, None, False),
        ("A6", "A4", 300, 4, True, C.NORMAL, None, False),
        ("A3", "L1", 400, 2, True, C.NORMAL, None, False),
        ("A4", "L1", 480, 3, True, C.LOW, None, False),
        ("N0", "A5", 400, 0, True, C.NORMAL, None, False),
    ]
    for a, b, dist, slope, sok, cong, name, steps in edges:
        g.add_edge(Edge(a=a, b=b, distance=dist, slope=slope,
                        stroller_ok=sok, congestion=cong,
                        name=name, has_steps=steps))
    return g


DEFAULT_DATA_PATH = "data/sample_zoo.json"


def ensure_sample_file(path: str = DEFAULT_DATA_PATH) -> str:
    import os
    from pathlib import Path
    if not Path(path).exists():
        build_sample_zoo().save_json(path)
    return path
