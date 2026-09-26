"""路线规划算法测试（标准库 unittest，亦可被 pytest 直接运行）。"""
import unittest

from zoo.data import build_sample_zoo
from zoo.planner import (RoutePlanner, Preferences, shortest_path,
                         parse_time, edge_cost)


def uses_edge(nodes, a, b):
    return any({x, y} == {a, b} for x, y in zip(nodes, nodes[1:]))


class ShortestPathTest(unittest.TestCase):
    def setUp(self):
        self.graph = build_sample_zoo()

    def test_stroller_avoids_unfriendly_path(self):
        """推儿童车时应绕开陡坡台阶捷径 j2-j7；不推车时走捷径更优。"""
        p_stroller = Preferences(has_stroller=True)
        path = shortest_path(self.graph, "j2", "j7", p_stroller)
        self.assertFalse(uses_edge(path.nodes, "j2", "j7"),
                         f"婴儿车路线不应经过陡坡台阶: {path.nodes}")

        p_walk = Preferences(has_stroller=False)
        path2 = shortest_path(self.graph, "j2", "j7", p_walk)
        self.assertTrue(uses_edge(path2.nodes, "j2", "j7"),
                        f"步行路线应走更短的捷径: {path2.nodes}")

    def test_congestion_increases_cost_and_time(self):
        """拥挤度上调后，同一路径代价与耗时都应增加。"""
        p = Preferences()
        before = shortest_path(self.graph, "j2", "j5", p)
        self.graph.get_edge("j2", "j5").congestion = 0.9
        after = shortest_path(self.graph, "j2", "j5", p)
        self.assertGreater(after.cost, before.cost)
        self.assertGreater(after.minutes, before.minutes)

    def test_slope_increases_cost(self):
        flat = edge_cost(self.graph.get_edge("gate_main", "j1"), Preferences())
        e = self.graph.get_edge("j2", "j7")  # 坡度 12%
        steep = edge_cost(e, Preferences(has_stroller=False))
        self.assertGreater(steep / e.distance_m, 1.0)  # 单位距离代价 > 1
        self.assertGreater(flat, 0)

    def test_unreachable_raises(self):
        self.graph.remove_edge("j3", "gate_east")
        self.graph.remove_edge("j2", "j3")
        # gate_east 仅剩 j3 相连，全部删除后不可达
        with self.assertRaises(ValueError):
            shortest_path(self.graph, "gate_main", "gate_east", Preferences())


class RoutePlanTest(unittest.TestCase):
    def setUp(self):
        self.graph = build_sample_zoo()
        self.planner = RoutePlanner(self.graph)
        self.zones = ["panda", "giraffe", "tiger", "penguin"]

    def plan(self, **kw):
        prefs = kw.pop("prefs", Preferences())
        return self.planner.plan("gate_main", "gate_east",
                                 self.zones, "rest_lake", prefs)

    def test_visits_all_required_and_endpoints(self):
        plan = self.plan()
        ids = [s.node_id for s in plan.stops]
        self.assertEqual(ids[0], "gate_main")
        self.assertEqual(ids[-1], "gate_east")
        for z in self.zones + ["rest_lake"]:
            self.assertIn(z, ids)
        self.assertEqual(len(ids), len(set(ids)), "每个站点只应停一次")

    def test_lunch_within_window(self):
        plan = self.plan()
        self.assertIsNotNone(plan.lunch_start)
        self.assertLessEqual(parse_time("11:30"), plan.lunch_start)
        self.assertLessEqual(plan.lunch_start, parse_time("13:00"))

    def test_show_alignment(self):
        """到达时间在表演开始前且等待不超过上限时，应安排观看表演。"""
        prefs = Preferences(start_time="09:15", want_shows=True)
        plan = self.planner.plan("gate_main", "gate_east", ["panda"], None, prefs)
        self.assertTrue(plan.shows, "09:15 出发应赶上 09:30 的熊猫喂食秀")
        stop = next(s for s in plan.stops if s.node_id == "panda")
        self.assertLessEqual(stop.arrive, parse_time("09:30"))
        self.assertLessEqual(parse_time("09:30") - stop.arrive,
                             prefs.max_wait_for_show_min)

    def test_no_shows_preference(self):
        prefs = Preferences(want_shows=False)
        plan = self.plan(prefs=prefs)
        self.assertEqual(plan.shows, [])

    def test_half_day_budget_default_ok(self):
        plan = self.plan()
        self.assertLessEqual(plan.total_minutes, 300)

    def test_overtime_budget_warns(self):
        prefs = Preferences(max_total_min=120)  # 预算过紧
        plan = self.plan(prefs=prefs)
        self.assertTrue(any("超出" in w for w in plan.warnings))

    def test_timeline_monotonic(self):
        plan = self.plan()
        times = [t for s in plan.stops for t in (s.arrive, s.depart)]
        self.assertEqual(times, sorted(times), "时间轴必须单调不减")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self.planner.plan("gate_main", "gate_east", ["no_such"], None)
        with self.assertRaises(ValueError):
            self.planner.plan("gate_main", "gate_east", ["rest_lake"], None)  # 非动物区
        with self.assertRaises(ValueError):
            self.planner.plan("gate_main", "gate_east", ["panda"], "panda")   # 非餐厅

    def test_many_zones_greedy_fallback(self):
        """动物区数量超过全排列上限时走贪心+2-opt，仍应访问全部动物区。"""
        import zoo.planner as pl
        from zoo.models import Node, Edge
        g = build_sample_zoo()
        # 扩充到 9 个动物区，超过 EXHAUSTIVE_LIMIT=8
        g.add_node(Node("lion", "狮山", "animal", 750, 400, visit_minutes=25))
        g.add_edge(Edge("lion", "j6", 130, 2, True, 0.2))
        g.add_node(Node("koala", "考拉馆", "animal", 300, 640, visit_minutes=20))
        g.add_edge(Edge("koala", "monkey", 120, 1, True, 0.1))
        all_zones = [n.id for n in g.nodes.values() if n.kind == "animal"]
        self.assertGreater(len(all_zones), pl.EXHAUSTIVE_LIMIT)

        plan = RoutePlanner(g).plan("gate_main", "gate_main", all_zones,
                                    "rest_lake", Preferences())
        ids = {s.node_id for s in plan.stops}
        for z in all_zones:
            self.assertIn(z, ids)

    def test_greedy_quality_close_to_exhaustive(self):
        """贪心+2-opt 的结果质量应接近全排列最优解。"""
        import zoo.planner as pl
        zones = ["panda", "giraffe", "tiger", "penguin", "monkey"]
        prefs = Preferences()
        exact = self.planner.plan("gate_main", "gate_east",
                                  zones, "rest_lake", prefs)
        old = pl.EXHAUSTIVE_LIMIT
        pl.EXHAUSTIVE_LIMIT = 3  # 强制走贪心+2-opt 分支
        try:
            approx = self.planner.plan("gate_main", "gate_east",
                                       zones, "rest_lake", prefs)
        finally:
            pl.EXHAUSTIVE_LIMIT = old
        ids = {s.node_id for s in approx.stops}
        for z in zones:
            self.assertIn(z, ids)
        # 贪心解不会优于最优解，且差距应在 25%（+200 容差）以内
        self.assertGreaterEqual(approx.score, exact.score - 1e-6)
        self.assertLessEqual(approx.score,
                             exact.score + 0.25 * abs(exact.score) + 200)


if __name__ == "__main__":
    unittest.main()
