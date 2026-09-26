"""示例数据：构建一个示例动物园。

布局（坐标单位：米，仅用于展示）：

        森林餐厅          熊猫馆                 湖畔餐厅        猛兽谷
           |               |                       |             |
  正门 — j1 ———————— j2 ———————— j3 — 东门        （主干道）
           |               |    \                  |             |
          j4 ———————— j5 ———————— j6               |
           |               |    \                  |             |
       长颈鹿园           j7 — 企鹅馆 — 海洋剧场 — 大象馆
           \             /  \                        /
            ———————— 猴山 ——————————————————————————
"""
from __future__ import annotations

from .models import ZooGraph, Node, Edge, Show


def build_sample_zoo() -> ZooGraph:
    g = ZooGraph()

    def N(*args, **kw):
        g.add_node(Node(*args, **kw))

    def E(*args, **kw):
        g.add_edge(Edge(*args, **kw))

    # ---- 大门 ----
    N("gate_main", "正门", "gate", 0, 0, visit_minutes=0)
    N("gate_east", "东门", "gate", 900, 0, visit_minutes=0)

    # ---- 路口 ----
    for i, (x, y) in enumerate([(180, 0), (400, 0), (620, 0),
                                (180, 240), (400, 240), (620, 240),
                                (400, 500)], start=1):
        N(f"j{i}", f"路口{i}", "junction", x, y, visit_minutes=0)

    # ---- 动物区 ----
    N("panda", "熊猫馆", "animal", 200, 320, visit_minutes=35, shows=[
        Show("09:30", 20, "熊猫喂食秀"), Show("11:00", 20, "熊猫喂食秀"),
        Show("14:00", 20, "熊猫喂食秀")])
    N("tiger", "猛兽谷", "animal", 720, 320, visit_minutes=30, shows=[
        Show("10:00", 20, "猛虎投喂"), Show("11:30", 20, "猛虎投喂")])
    N("giraffe", "长颈鹿园", "animal", 150, 500, visit_minutes=25, shows=[
        Show("10:15", 15, "长颈鹿讲解")])
    N("elephant", "大象馆", "animal", 700, 520, visit_minutes=30, shows=[
        Show("13:30", 20, "大象行为展示")])
    N("penguin", "企鹅馆", "animal", 400, 620, visit_minutes=25, shows=[
        Show("10:45", 15, "企鹅巡游"), Show("13:00", 15, "企鹅巡游")])
    N("monkey", "猴山", "animal", 200, 640, visit_minutes=25)
    N("aquarium", "海洋剧场", "animal", 600, 640, visit_minutes=30, shows=[
        Show("12:30", 25, "海豚表演")])

    # ---- 餐厅 ----
    N("rest_lake", "湖畔餐厅", "restaurant", 400, 330, visit_minutes=0)
    N("rest_forest", "森林餐厅", "restaurant", 160, 380, visit_minutes=0)

    # ---- 道路：a, b, 距离m, 坡度%, 婴儿车友好, 拥挤度 ----
    E("gate_main", "j1", 180, 0, True, 0.2)
    E("j1", "j2", 220, 1, True, 0.2)
    E("j2", "j3", 220, 1, True, 0.3)
    E("j3", "gate_east", 180, 0, True, 0.2)
    E("j1", "j4", 240, 2, True, 0.1)
    E("j2", "j5", 240, 2, True, 0.2)
    E("j3", "j6", 240, 3, True, 0.2)
    E("j4", "panda", 120, 1, True, 0.3)
    E("j4", "giraffe", 260, 4, True, 0.1)
    E("j4", "j5", 230, 1, True, 0.2)
    E("j5", "j6", 230, 2, True, 0.3)
    E("j5", "rest_lake", 90, 0, True, 0.4)
    E("j6", "tiger", 110, 2, True, 0.3)
    E("j5", "j7", 260, 3, True, 0.2)
    E("j6", "elephant", 240, 4, True, 0.2)
    E("j7", "penguin", 170, 2, True, 0.3)
    E("j7", "monkey", 190, 5, False, 0.1)   # 台阶路，婴儿车不友好
    E("j7", "elephant", 300, 6, True, 0.1)
    E("giraffe", "rest_forest", 80, 1, True, 0.2)
    E("rest_forest", "monkey", 230, 3, True, 0.1)
    E("penguin", "aquarium", 160, 1, True, 0.3)
    E("aquarium", "elephant", 150, 2, True, 0.2)
    E("j2", "j7", 320, 12, False, 0.0)      # 陡坡台阶捷径，婴儿车不友好
    return g


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "data/zoo_sample.json"
    build_sample_zoo().save(out)
    print(f"示例数据已写入 {out}")
