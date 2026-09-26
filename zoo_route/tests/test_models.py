"""数据模型与图结构测试。"""
import unittest

from zoo.models import ZooGraph, Node, Edge, Show, edge_id
from zoo.data import build_sample_zoo


class ModelTest(unittest.TestCase):
    def test_edge_id_symmetric(self):
        self.assertEqual(edge_id("a", "b"), edge_id("b", "a"))

    def test_remove_node_removes_edges(self):
        g = build_sample_zoo()
        n_edges = len(g.neighbors("j5"))
        self.assertGreater(n_edges, 0)
        g.remove_node("j5")
        self.assertNotIn("j5", g.nodes)
        for eid, e in g.edges.items():
            self.assertNotIn("j5", (e.a, e.b))

    def test_add_edge_unknown_node_raises(self):
        g = build_sample_zoo()
        with self.assertRaises(KeyError):
            g.add_edge(Edge("j1", "ghost", 100))

    def test_duplicate_edge_rejected(self):
        g = build_sample_zoo()
        with self.assertRaises(ValueError):
            g.add_edge(Edge("j1", "j2", 999))

    def test_json_roundtrip(self):
        g = build_sample_zoo()
        g2 = ZooGraph.from_dict(g.to_dict())
        self.assertEqual(len(g.nodes), len(g2.nodes))
        self.assertEqual(len(g.edges), len(g2.edges))
        panda = g2.nodes["panda"]
        self.assertIsInstance(panda.shows[0], Show)
        self.assertEqual(panda.shows[0].title, "熊猫喂食秀")

    def test_sample_data_counts(self):
        g = build_sample_zoo()
        kinds = {}
        for n in g.nodes.values():
            kinds[n.kind] = kinds.get(n.kind, 0) + 1
        self.assertEqual(kinds["gate"], 2)
        self.assertEqual(kinds["animal"], 7)
        self.assertEqual(kinds["restaurant"], 2)
        self.assertGreaterEqual(len(g.edges), 20)


if __name__ == "__main__":
    unittest.main()
