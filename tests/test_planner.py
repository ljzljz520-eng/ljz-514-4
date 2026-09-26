import pytest

from zoo_tour.graph import ZooGraphError
from zoo_tour.models import NodeType, fmt_time
from zoo_tour.planner import (
    PlanRequest, plan_route, simulate, validate_request, SHOW_BONUS,
)


def _req(**kw):
    base = dict(entrance="E1", exit="E2",
                animals=["A1", "A2", "A3"], lunch="L1",
                start_minute=9 * 60, time_budget=300,
                preferred_lunch=12 * 60, stroller=True)
    base.update(kw)
    return PlanRequest(**base)


def test_feasible_plan_with_shows(small_zoo):
    plan = plan_route(small_zoo, _req(time_budget=300))
    assert plan.feasible
    assert plan.best.finish_minute <= 9 * 60 + 300
    # 熊猫 09:30 与狮虎 10:00 两场表演都在时间轴上
    show_names = {(n, name) for n, name, _ in plan.best.shows_seen}
    assert ("A1", "喂食") in show_names
    assert ("A2", "投喂") in show_names
    assert len(plan.best.shows_seen) == 2


def test_start_and_end_match_request(small_zoo):
    plan = plan_route(small_zoo, _req())
    kinds = plan.best.timeline
    assert kinds[0]["from"] == "E1"
    assert kinds[-1]["to"] == "E2"


def test_lunch_is_in_sequence(small_zoo):
    plan = plan_route(small_zoo, _req())
    assert "L1" in plan.best.sequence
    stops = [i for i in plan.best.timeline if i.get("stop_type") == "lunch"]
    assert len(stops) == 1
    assert stops[0]["node"] == "L1"


def test_all_animals_visited_once(small_zoo):
    plan = plan_route(small_zoo, _req())
    animals_in_seq = [x for x in plan.best.sequence if x != "L1"]
    assert sorted(animals_in_seq) == ["A1", "A2", "A3"]


def test_timeline_is_monotonic_and_continuous(small_zoo):
    plan = plan_route(small_zoo, _req())
    for item in plan.best.timeline:
        assert item["end"] >= item["start"]
    for a, b in zip(plan.best.timeline, plan.best.timeline[1:]):
        assert b["start"] == pytest.approx(a["end"])


def test_evaluated_count(small_zoo):
    # 3! 种顺序 × (3+1) 个午餐插入位 = 24
    plan = plan_route(small_zoo, _req())
    assert plan.evaluated == 24


def test_stroller_route_avoids_steps(small_zoo):
    plan = plan_route(small_zoo, _req(animals=["A3", "A1"]))
    for item in plan.best.timeline:
        if item["kind"] == "walk":
            for e in item["path"].edges:
                assert e.stroller_ok, f"儿童车方案使用了限行边 {e.a}-{e.b}"


def test_no_stroller_may_use_steps(small_zoo):
    plan = plan_route(small_zoo, _req(animals=["A3", "A1"], stroller=False))
    used_steps = any(
        item["kind"] == "walk"
        and any(not e.stroller_ok for e in item["path"].edges)
        for item in plan.best.timeline)
    # 60 米石阶捷径代价远低于绕行，非儿童车方案应当使用它
    assert used_steps


def test_crowded_lunch_adds_queue(small_zoo):
    small_zoo.set_node_congestion("L1", "高")
    plan = plan_route(small_zoo, _req(preferred_lunch=11 * 60,
                                      time_budget=320))
    stop = next(i for i in plan.best.timeline
                if i.get("stop_type") == "lunch")
    assert stop["queue"] == 8
    # 实际用餐时长 = 基础45 + 排队8（条目时间跨度还可能含等待）
    assert stop["dwell"] == 45 + 8
    assert stop["end"] - stop["active_start"] == pytest.approx(45 + 8)


def test_invalid_entrance_rejected(small_zoo):
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(entrance="A1"))


def test_invalid_lunch_type_rejected(small_zoo):
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(lunch="A1"))


def test_duplicate_animals_rejected(small_zoo):
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(animals=["A1", "A1"]))


def test_too_many_animals_rejected(small_zoo):
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(animals=["A1"] * 8))


def test_over_budget_produces_suggestion(small_zoo):
    plan = plan_route(small_zoo, _req(time_budget=60,
                                      preferred_lunch=9 * 60 + 45))
    assert not plan.feasible
    assert plan.best.overtime > 0
    assert plan.suggestion is not None
    assert plan.suggestion.dropped


def test_unreachable_pair_raises(small_zoo):
    # A4 只经过 A3 到达；路线不含 A3 时仍可能可达（只要图里有路径即可）。
    # 这里通过删除 A3 全部连接让 A4 孤岛化。
    for v in list(small_zoo.neighbors("A4")):
        small_zoo.remove_edge("A4", v)
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(animals=["A1", "A2"]))


def test_preferred_lunch_outside_window_rejected(small_zoo):
    with pytest.raises(ZooGraphError):
        plan_route(small_zoo, _req(preferred_lunch=8 * 60))


def test_deterministic_best(small_zoo):
    p1 = plan_route(small_zoo, _req())
    p2 = plan_route(small_zoo, _req())
    assert [tuple(x) if isinstance(x, list) else x
            for x in []] is not None
    assert p1.best.sequence == p2.best.sequence
    assert p1.best.score == p2.best.score


def test_show_skip_when_wait_too_long(small_zoo):
    # 11:00 才入园，熊猫 09:30 早已结束；不应再看到该场
    plan = plan_route(small_zoo, _req(start_minute=11 * 60,
                                      preferred_lunch=12 * 60 + 30,
                                      time_budget=240))
    assert all(n != "A1" or name != "喂食"
               for n, name, _ in plan.best.shows_seen)


def test_alternatives_exist(small_zoo):
    plan = plan_route(small_zoo, _req())
    assert 0 <= len(plan.alternatives) <= 5
