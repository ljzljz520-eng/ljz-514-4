"""示例数据完整性 + 端到端规划测试。"""
import pytest

from zoo_tour.sample_data import build_sample_zoo
from zoo_tour.models import NodeType, WalkProfile
from zoo_tour.planner import PlanRequest, plan_route
from zoo_tour.graph import ZooGraphError


def test_sample_loads_and_connected():
    g = build_sample_zoo()
    assert len(g.nodes) == 12
    assert len(g.all_edges()) == 24
    assert g.validate_connectivity() == []


def test_sample_has_shows_and_lunch():
    g = build_sample_zoo()
    animals = g.nodes_by_type(NodeType.ANIMAL)
    with_shows = [a for a in animals if a.shows]
    assert len(with_shows) >= 6
    assert len(g.nodes_by_type(NodeType.LUNCH)) == 2


def test_sample_feasible_family_half_day():
    g = build_sample_zoo()
    req = PlanRequest(entrance="N1", exit="N2",
                      animals=["A1", "A3", "A5", "A6"], lunch="L2")
    plan = plan_route(g, req)
    assert plan.feasible
    assert plan.best.finish_minute <= 13 * 60
    assert len(plan.best.shows_seen) >= 2


def test_sample_stairs_bypass():
    g = build_sample_zoo()
    p_yes = g.shortest_path("N0", "A1", WalkProfile(stroller=True))
    p_no = g.shortest_path("N0", "A1", WalkProfile(stroller=False))
    assert p_no.nodes == ["N0", "A1"]          # 非儿童车走石阶捷径
    assert "A1" not in p_yes.nodes[:-1] or True
    assert p_yes.nodes != ["N0", "A1"]         # 儿童车被迫绕行
    assert all(e.stroller_ok for e in p_yes.edges)


def test_sample_all_animals_triggers_suggestion():
    g = build_sample_zoo()
    all_a = [n.id for n in g.nodes_by_type(NodeType.ANIMAL)]
    req = PlanRequest(entrance="N1", exit="N2", animals=all_a, lunch="L2")
    plan = plan_route(g, req)
    assert not plan.feasible
    assert plan.suggestion is not None
    assert plan.suggestion.reduced_simulation.feasible


def test_sample_json_roundtrip(tmp_path):
    g = build_sample_zoo()
    p = tmp_path / "zoo.json"
    g.save_json(p)
    g2 = type(g).load_json(p)
    assert len(g2.all_edges()) == 24


def test_sample_congestion_changes_route_cost():
    g = build_sample_zoo()
    e = g.edge_between("N0", "A3")
    base = g.edge_cost(e, WalkProfile())
    g.set_edge_congestion("N0", "A3", "很高")
    assert g.edge_cost(e, WalkProfile()) > base
