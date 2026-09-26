"""领域模型：园区节点、连接道路、表演场次、儿童车步行画像。

约定：
- 一天内的时间统一用“分钟数”表示（09:00 = 540）。
- 道路(Edge)是无向的；cost 以“感知步行分钟”为单位，
  综合考虑距离、坡度、拥挤程度，并对儿童车不友好的道路做软/硬处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class NodeType(Enum):
    ENTRANCE = "entrance"        # 入口（可兼作出口）
    EXIT = "exit"                # 出口（可兼作入口）
    ANIMAL = "animal"            # 动物展区
    LUNCH = "lunch"              # 午餐点
    JUNCTION = "junction"        # 道路交汇点/广场/休息处

    @staticmethod
    def parse(value: "str | NodeType") -> "NodeType":
        if isinstance(value, NodeType):
            return value
        v = str(value).strip().lower()
        aliases = {
            "入口": NodeType.ENTRANCE, "entrance": NodeType.ENTRANCE,
            "出口": NodeType.EXIT, "exit": NodeType.EXIT,
            "动物": NodeType.ANIMAL, "animal": NodeType.ANIMAL,
            "展区": NodeType.ANIMAL,
            "午餐": NodeType.LUNCH, "lunch": NodeType.LUNCH,
            "restaurant": NodeType.LUNCH, "dining": NodeType.LUNCH,
            "路口": NodeType.JUNCTION, "junction": NodeType.JUNCTION,
            "交汇点": NodeType.JUNCTION, "广场": NodeType.JUNCTION,
        }
        if v not in aliases:
            raise ValueError(f"未知节点类型: {value!r}")
        return aliases[v]


class Congestion(Enum):
    """拥挤程度，分 4 档，影响道路通行时间与节点排队时间。"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    VERY_HIGH = "very_high"

    @staticmethod
    def parse(value) -> "Congestion":
        if isinstance(value, Congestion):
            return value
        if isinstance(value, int):
            return {1: Congestion.LOW, 2: Congestion.NORMAL,
                    3: Congestion.HIGH, 4: Congestion.VERY_HIGH}[value]
        v = str(value).strip().lower()
        aliases = {
            "low": Congestion.LOW, "低": Congestion.LOW, "畅通": Congestion.LOW, "1": Congestion.LOW,
            "normal": Congestion.NORMAL, "中": Congestion.NORMAL, "正常": Congestion.NORMAL, "2": Congestion.NORMAL,
            "high": Congestion.HIGH, "高": Congestion.HIGH, "拥挤": Congestion.HIGH, "3": Congestion.HIGH,
            "very_high": Congestion.VERY_HIGH, "很高": Congestion.VERY_HIGH,
            "非常拥挤": Congestion.VERY_HIGH, "4": Congestion.VERY_HIGH,
        }
        if v not in aliases:
            raise ValueError(f"未知拥挤程度: {value!r}")
        return aliases[v]


# 各拥挤等级的通行代价系数与中文标签
EDGE_CONGESTION_FACTOR = {
    Congestion.LOW: 0.95,
    Congestion.NORMAL: 1.00,
    Congestion.HIGH: 1.30,
    Congestion.VERY_HIGH: 1.70,
}
CONGESTION_LABEL = {
    Congestion.LOW: "低",
    Congestion.NORMAL: "中",
    Congestion.HIGH: "高",
    Congestion.VERY_HIGH: "很高",
}
# 拥挤给节点（展区/午餐点）增加的排队分钟数
NODE_CONGESTION_EXTRA_MINUTES = {
    Congestion.LOW: 0,
    Congestion.NORMAL: 0,
    Congestion.HIGH: 8,
    Congestion.VERY_HIGH: 18,
}
# 各类型节点的基础停留分钟数（交汇点默认不逗留）
BASE_DWELL = {
    NodeType.ENTRANCE: 0,
    NodeType.EXIT: 0,
    NodeType.ANIMAL: 20,
    NodeType.LUNCH: 45,
    NodeType.JUNCTION: 0,
}


def parse_hhmm(text) -> int:
    """把 'HH:MM'（或已是分钟数）转换为分钟数。"""
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip()
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"时间格式应为 HH:MM: {text!r}")
    h, m = int(parts[0]), int(parts[1])
    if not 0 <= h <= 23 or not 0 <= m <= 59:
        raise ValueError(f"时间超出范围: {text!r}")
    return h * 60 + m


def fmt_time(minutes: float) -> str:
    """分钟数 -> 'HH:MM'（四舍五入到分钟）。"""
    total = int(round(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


def fmt_duration(minutes: float) -> str:
    total = int(round(minutes))
    h, m = divmod(total, 60)
    if h:
        return f"{h}小时{m}分" if m else f"{h}小时"
    return f"{m}分钟"


@dataclass
class Show:
    """动物喂食/表演场次。"""
    name: str
    start_minute: int          # 开始时间（分钟）
    duration: int = 20         # 时长（分钟）

    @property
    def end_minute(self) -> int:
        return self.start_minute + self.duration

    @classmethod
    def from_dict(cls, d: dict) -> "Show":
        return cls(
            name=str(d["name"]),
            start_minute=parse_hhmm(d.get("start", d.get("start_minute"))),
            duration=int(d.get("duration", 20)),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "start": fmt_time(self.start_minute),
                "duration": self.duration}


@dataclass
class Node:
    id: str
    name: str
    ntype: NodeType
    shows: list = field(default_factory=list)          # list[Show]
    dwell: Optional[int] = None                        # 自定义停留分钟
    congestion: Congestion = Congestion.NORMAL
    can_enter: bool = True                             # ENTRANCE 用：可否作为入口
    can_exit: bool = True                              # EXIT 用：可否作为出口
    x: float = 0.0                                     # 地图坐标（米）
    y: float = 0.0

    def base_dwell(self) -> int:
        if self.dwell is not None:
            return self.dwell
        return BASE_DWELL.get(self.ntype, 0)

    def queue_extra(self) -> int:
        return NODE_CONGESTION_EXTRA_MINUTES.get(self.congestion, 0)

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            ntype=NodeType.parse(d.get("type", "junction")),
            shows=[Show.from_dict(s) for s in d.get("shows", [])],
            dwell=d.get("dwell"),
            congestion=Congestion.parse(d.get("congestion", "normal")),
            can_enter=bool(d.get("can_enter", True)),
            can_exit=bool(d.get("can_exit", True)),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
        )

    def to_dict(self) -> dict:
        data = {
            "id": self.id, "name": self.name, "type": self.ntype.value,
            "congestion": self.congestion.value,
            "can_enter": self.can_enter, "can_exit": self.can_exit,
            "x": self.x, "y": self.y,
        }
        if self.shows:
            data["shows"] = [s.to_dict() for s in self.shows]
        if self.dwell is not None:
            data["dwell"] = self.dwell
        return data


@dataclass
class Edge:
    """园区道路（无向）。

    slope: 坡度等级 0-30（%），越大越费劲、越不适合儿童车。
    stroller_ok: 儿童车能否通行（台阶、陡坡设为 False）。
    congestion: 道路当前拥挤程度（管理员可维护）。
    """
    a: str
    b: str
    distance: float                       # 米
    slope: float = 0.0                    # 坡度(%)，0-30
    stroller_ok: bool = True
    congestion: Congestion = Congestion.NORMAL
    name: Optional[str] = None
    has_steps: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(
            a=str(d["a"]), b=str(d["b"]),
            distance=float(d["distance"]),
            slope=float(d.get("slope", 0.0)),
            stroller_ok=bool(d.get("stroller_ok", True)),
            congestion=Congestion.parse(d.get("congestion", "normal")),
            name=d.get("name"),
            has_steps=bool(d.get("has_steps", False)),
        )

    def to_dict(self) -> dict:
        d = {"a": self.a, "b": self.b, "distance": self.distance,
             "slope": self.slope, "stroller_ok": self.stroller_ok,
             "congestion": self.congestion.value}
        if self.name:
            d["name"] = self.name
        if self.has_steps:
            d["has_steps"] = True
        return d


@dataclass(frozen=True)
class WalkProfile:
    """家庭步行画像，决定道路代价如何计算。"""
    stroller: bool = True                  # 是否推儿童车
    walking_speed: float = 60.0            # 平地步行速度（米/分钟），亲子慢节奏
    slope_penalty_per_pct: float = 0.05    # 每 1% 坡度增加的通行时间比例
    soft_penalty: float = 2.5              # 儿童车不友好道路的软惩罚倍数
    strict_stroller: bool = True           # True=直接禁行；False=允许但加惩罚

    def slope_factor(self, slope: float) -> float:
        return 1.0 + max(slope, 0.0) * self.slope_penalty_per_pct
