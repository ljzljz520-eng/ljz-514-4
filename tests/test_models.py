import pytest

from zoo_tour.models import (
    Node, Edge, Show, NodeType, Congestion, WalkProfile,
    parse_hhmm, fmt_time, fmt_duration, BASE_DWELL,
    NODE_CONGESTION_EXTRA_MINUTES,
)


def test_parse_hhmm():
    assert parse_hhmm("09:30") == 570
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("23:59") == 1439
    assert parse_hhmm(540) == 540


def test_parse_hhmm_bad():
    with pytest.raises(ValueError):
        parse_hhmm("9点")
    with pytest.raises(ValueError):
        parse_hhmm("24:00")


def test_fmt_time_and_duration():
    assert fmt_time(570) == "09:30"
    assert fmt_time(570.6) == "09:31"
    assert fmt_duration(25) == "25分钟"
    assert fmt_duration(125) == "2小时5分"
    assert fmt_duration(120) == "2小时"


def test_congestion_parse_aliases():
    assert Congestion.parse("高") is Congestion.HIGH
    assert Congestion.parse("high") is Congestion.HIGH
    assert Congestion.parse(3) is Congestion.HIGH
    assert Congestion.parse("正常") is Congestion.NORMAL
    with pytest.raises(ValueError):
        Congestion.parse("爆满")


def test_node_type_parse():
    assert NodeType.parse("动物") is NodeType.ANIMAL
    assert NodeType.parse("restaurant") is NodeType.LUNCH
    assert NodeType.parse("广场") is NodeType.JUNCTION


def test_node_dwell_and_queue():
    n = Node("A", "展区", NodeType.ANIMAL)
    assert n.base_dwell() == BASE_DWELL[NodeType.ANIMAL]
    n.congestion = Congestion.HIGH
    assert n.queue_extra() == NODE_CONGESTION_EXTRA_MINUTES[Congestion.HIGH]
    n.dwell = 99
    assert n.base_dwell() == 99
    gate = Node("E", "门", NodeType.ENTRANCE)
    assert gate.base_dwell() == 0


def test_show_roundtrip():
    s = Show.from_dict({"name": "表演", "start": "10:15", "duration": 25})
    assert s.start_minute == 615 and s.end_minute == 640
    assert s.to_dict() == {"name": "表演", "start": "10:15", "duration": 25}


def test_node_serialization_roundtrip():
    n = Node.from_dict({
        "id": "A1", "name": "熊猫", "type": "animal",
        "congestion": "高", "shows": [{"name": "喂食", "start": "09:30"}],
        "x": 10, "y": 20,
    })
    d = n.to_dict()
    assert d["type"] == "animal"
    assert d["congestion"] == "high"
    assert d["shows"][0]["start"] == "09:30"


def test_walk_profile_slope_factor():
    p = WalkProfile()
    assert p.slope_factor(0) == 1.0
    assert p.slope_factor(10) == pytest.approx(1.5)
