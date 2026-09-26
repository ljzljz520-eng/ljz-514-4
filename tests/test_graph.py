import pytest

from zoo_tour.graph import ZooGraph, ZooGraphError
from zoo_tour.models import Node, Edge, NodeType, Congestion, WalkProfile


def test_add_duplicate_node_raises(small_zoo):
    with pytest.raises(ZooGraphError):
        small_zoo.add_node(Node("A1", "重复", NodeType.ANIMAL))


def test_edge_endpoints_must_exist(small_zoo):
    with pytest.raises(ZooGraphError):
        small_zoo.add_edge(Edge("A1", "ZZ", 100))


def test_no_self_loop_and_positive_distance(small_zoo):
    with pytest.raises(ZooGraphError):
        small_zoo.add_edge(Edge("A1", "A1", 100))
    with pytest.raises(ZooGraphError):
        small_zoo.add_edge(Edge("A1", "A2", 0))


def test_remove_node_cleans_edges(small_zoo):
    small_zoo.remove_node("A4")
    assert not small_zoo.has_node("A4")
    assert small_zoo.edge_between("A3", "A4") is None


def test_remove_edge(small_zoo):
    small_zoo.remove_edge("A3", "A1")
    assert small_zoo.edge_between("A3", "A1") is None
    with pytest.raises(ZooGraphError):
        small_zoo.remove_edge("A3", "A1")


def test_update_node_congestion(small_zoo):
    small_zoo.set_node_congestion("L1", "很高")
    assert small_zoo.node("L1").congestion is Congestion.VERY_HIGH


def test_update_edge_congestion(small_zoo):
    small_zoo.set_edge_congestion("J1", "L1", 3)
    assert small_zoo.edge_between("J1", "L1").congestion is Congestion.HIGH


def test_connectivity_ok(small_zoo):
    assert small_zoo.validate_connectivity() == []


def test_disconnected_node_detected():
    g = ZooGraph()
    g.add_node(Node("E", "门", NodeType.ENTRANCE))
    g.add_node(Node("X", "孤岛", NodeType.ANIMAL))
    problems = g.validate_connectivity()
    assert any("X" in p for p in problems)


def test_shortest_path_basic(small_zoo):
    r = small_zoo.shortest_path("E1", "A1")
    assert r.nodes[0] == "E1" and r.nodes[-1] == "A1"
    # 120+260 米 @60m/min ≈ 6.33 分钟
    assert r.cost == pytest.approx(380 / 60)
    assert r.distance == pytest.approx(380.0)


def test_stroller_blocks_steps_and_reroutes(small_zoo):
    # 大象馆->熊猫有一条 60 米石阶捷径（儿童车限行）。
    # 非儿童车：广场->大象->石阶->熊猫（180+60=240米，石阶又短又陡）
    # 儿童车：走广场->熊猫 120 米平路直达，绝不踩石阶
    r_no = small_zoo.shortest_path("J1", "A1", WalkProfile(stroller=False))
    assert r_no.nodes == ["J1", "A3", "A1"]
    r_yes = small_zoo.shortest_path("J1", "A1", WalkProfile(stroller=True))
    assert r_yes.nodes == ["J1", "A1"]
    assert all(e.stroller_ok for e in r_yes.edges)


def test_soft_stroller_penalty(small_zoo):
    soft = WalkProfile(stroller=True, strict_stroller=False)
    # 软惩罚模式允许走石阶（60米捷径，虽有 2.5 倍惩罚仍优于绕行 300 米）
    rf = small_zoo.shortest_path("A3", "A1", soft)
    assert rf.nodes == ["A3", "A1"]
    # 限行边在软惩罚下的代价高于“假设它可通行”时的代价
    edge = small_zoo.edge_between("A3", "A1")
    # 无坡度时也能看出限行软惩罚
    flat_edge = type(edge)(a=edge.a, b=edge.b, distance=edge.distance,
                           slope=0, stroller_ok=False)
    assert small_zoo.edge_cost(flat_edge, soft) == pytest.approx(
        flat_edge.distance / soft.walking_speed * soft.soft_penalty)


def test_slope_and_congestion_increase_cost(small_zoo):
    flat = Edge("X", "Y", 300, slope=0, congestion=Congestion.NORMAL)
    hill = Edge("X", "Y", 300, slope=10, congestion=Congestion.NORMAL)
    busy = Edge("X", "Y", 300, slope=0, congestion=Congestion.VERY_HIGH)
    p = WalkProfile()
    assert small_zoo.edge_cost(hill, p) > small_zoo.edge_cost(flat, p)
    assert small_zoo.edge_cost(busy, p) > small_zoo.edge_cost(flat, p)


def test_unreachable_with_strict_stroller(small_zoo):
    # 让 A4 只通过一条儿童车限行边连接
    e = small_zoo.edge_between("A3", "A4")
    small_zoo.update_edge("A3", "A4", stroller_ok=False)
    with pytest.raises(ZooGraphError):
        small_zoo.shortest_path("J1", "A4", WalkProfile(stroller=True))
    # 非儿童车仍可达
    r = small_zoo.shortest_path("J1", "A4", WalkProfile(stroller=False))
    assert r.nodes[-1] == "A4"


def test_all_pairs_symmetry(small_zoo):
    ids = ["E1", "A1", "A2", "E2"]
    pp = small_zoo.all_pairs_paths(ids)
    assert pp[("E1", "A2")].cost == pytest.approx(pp[("A2", "E1")].cost)
    assert pp[("A2", "E1")].nodes[0] == "A2"
    assert pp[("A2", "E1")].nodes[-1] == "E1"


def test_json_roundtrip(tmp_path, small_zoo):
    path = tmp_path / "zoo.json"
    small_zoo.save_json(path)
    g2 = ZooGraph.load_json(path)
    assert len(g2.nodes) == len(small_zoo.nodes)
    assert len(g2.all_edges()) == len(small_zoo.all_edges())
    assert g2.node("A1").shows[0].start_minute == 570
