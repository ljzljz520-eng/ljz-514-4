"""管理员维护功能测试。"""
import unittest

from zoo.data import build_sample_zoo
from zoo.models import Node, Edge
from zoo.admin import ZooAdmin
from zoo.planner import RoutePlanner, Preferences


class AdminCrudTest(unittest.TestCase):
    def setUp(self):
        self.admin = ZooAdmin(build_sample_zoo())

    def test_add_update_remove_node(self):
        self.admin.add_node(Node("cafe", "咖啡屋", "restaurant", 400, 350))
        self.admin.add_edge(Edge("cafe", "j5", 60, 1, True, 0.1))
        self.assertEqual(self.admin.validate(), [])

        self.admin.update_node("cafe", name="湖畔咖啡屋",
                               shows=[{"start": "12:00", "duration_min": 10,
                                       "title": "魔术表演"}])
        node = self.admin.graph.nodes["cafe"]
        self.assertEqual(node.name, "湖畔咖啡屋")
        self.assertEqual(node.shows[0].title, "魔术表演")

        self.admin.remove_node("cafe")
        self.assertNotIn("cafe", self.admin.graph.nodes)
        # 关联道路应一并删除
        self.assertFalse(any("cafe" in eid for eid in self.admin.graph.edges))

    def test_edge_maintenance(self):
        self.admin.update_edge("j5", "rest_lake", distance_m=120,
                               stroller_friendly=False)
        e = self.admin.graph.get_edge("j5", "rest_lake")
        self.assertEqual(e.distance_m, 120)
        self.assertFalse(e.stroller_friendly)

        self.admin.remove_edge("j5", "rest_lake")
        with self.assertRaises(KeyError):
            self.admin.graph.get_edge("j5", "rest_lake")

    def test_congestion_validation(self):
        self.admin.set_congestion("j1", "j2", 0.8)
        self.assertAlmostEqual(
            self.admin.graph.get_edge("j1", "j2").congestion, 0.8)
        with self.assertRaises(ValueError):
            self.admin.set_congestion("j1", "j2", 1.5)
        with self.assertRaises(ValueError):
            self.admin.set_congestion("j1", "j2", -0.1)
        with self.assertRaises(KeyError):
            self.admin.set_congestion("j1", "no_such", 0.5)

    def test_validate_detects_isolated_node(self):
        self.admin.add_node(Node("lonely", "孤岛", "animal"))
        issues = self.admin.validate()
        self.assertTrue(any("不可达" in i for i in issues))

    def test_duplicate_node_rejected(self):
        with self.assertRaises(ValueError):
            self.admin.add_node(Node("panda", "重复", "animal"))

    def test_sample_zoo_is_healthy(self):
        self.assertEqual(self.admin.validate(), [])


class CongestionEffectTest(unittest.TestCase):
    def test_congestion_changes_recommendation(self):
        graph = build_sample_zoo()
        planner = RoutePlanner(graph)
        prefs = Preferences()
        zones = ["panda", "giraffe", "tiger", "penguin"]
        before = planner.plan("gate_main", "gate_east", zones, "rest_lake", prefs)

        admin = ZooAdmin(graph)
        for eid in list(graph.edges):
            e = graph.edges[eid]
            admin.set_congestion(e.a, e.b, 0.9)  # 全园大客流
        after = planner.plan("gate_main", "gate_east", zones, "rest_lake", prefs)

        self.assertGreater(after.total_minutes, before.total_minutes,
                           "全园拥挤后总用时应变长")
        self.assertGreater(after.score, before.score,
                           "全园拥挤后路线代价应变高")

    def test_save_load_roundtrip(self):
        import tempfile, os
        admin = ZooAdmin(build_sample_zoo())
        admin.set_congestion("j2", "j7", 0.7)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "zoo.json")
            admin.save(path)
            loaded = ZooAdmin.load(path)
        self.assertEqual(len(loaded.graph.nodes), len(admin.graph.nodes))
        self.assertEqual(len(loaded.graph.edges), len(admin.graph.edges))
        self.assertAlmostEqual(
            loaded.graph.get_edge("j2", "j7").congestion, 0.7)
        self.assertEqual(loaded.graph.nodes["panda"].shows[0].start, "09:30")


if __name__ == "__main__":
    unittest.main()
