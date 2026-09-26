"""命令行界面：家长路线推荐 / 管理员数据维护。

用法：
  python -m zoo_tour demo                      # 运行内置半日游示例
  python -m zoo_tour plan --animals A1 A3 ...  # 直接出方案
  python -m zoo_tour list                      # 查看园区节点
  python -m zoo_tour admin                     # 管理员交互菜单
  python -m zoo_tour --interactive             # 家长交互选择
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .graph import ZooGraph, ZooGraphError
from .models import (
    Node, Edge, NodeType, Congestion, WalkProfile,
    CONGESTION_LABEL, parse_hhmm, fmt_time, fmt_duration,
)
from .sample_data import build_sample_zoo, DEFAULT_DATA_PATH
from .planner import PlanRequest, plan_route


# ------------------------------------------------------------------
# 路线展示
# ------------------------------------------------------------------
def _node_choices(graph: ZooGraph, ntype: NodeType):
    items = graph.nodes_by_type(ntype)
    if ntype == NodeType.ENTRANCE:
        items = graph.entrances()
    if ntype == NodeType.EXIT:
        items = graph.exits()
    return items


def print_plan(graph: ZooGraph, plan, file=sys.stdout) -> None:
    p = file.write
    b = plan.best
    req = plan.request
    p("\n" + "=" * 64 + "\n")
    p(f"  亲子半日游推荐路线（{graph.name}）\n")
    p("=" * 64 + "\n")
    p(f"时间窗：{fmt_time(req.start_minute)} - {fmt_time(req.deadline)}"
      f"（半日预算 {fmt_duration(req.time_budget)}）\n")
    p(f"儿童车：{'是（自动避开台阶/陡坡限行路）' if req.stroller else '否'}\n")
    p(f"候选方案评估：{plan.evaluated} 个（枚举展区顺序 × 午餐插入位置）\n")

    if b is None:
        p("未能生成路线。\n")
        return

    status = "✔ 可在预算内完成" if b.feasible else "✘ 超出半日预算"
    p(f"结果：{status}\n")
    p(f"预计结束：{fmt_time(b.finish_minute)}　总步行：{b.walk_distance:.0f} 米"
      f"（约 {fmt_duration(b.raw_walk_minutes)} 实际步行，"
      f"含坡度/拥挤折算 {fmt_duration(b.walk_minutes)}）\n")
    p(f"观看表演：{len(b.shows_seen)} 场\n")
    if b.warning:
        p(f"⚠ {b.warning}\n")

    # ---- 时间轴 ----
    p("\n— 行程时间轴 —\n")
    for item in b.timeline:
        if item["kind"] == "walk":
            path = item["path"]
            via = " → ".join(graph.node(i).name for i in path.nodes)
            p(f"  {fmt_time(item['start'])}–{fmt_time(item['end'])} 步行 "
              f"{path.distance:.0f}米：{via}\n")
            tags = _path_tags(path)
            if tags:
                p(f"        路况：{tags}\n")
        else:
            node = graph.node(item["node"])
            if item["stop_type"] == "lunch":
                p(f"  {fmt_time(item['active_start'])}–{fmt_time(item['end'])} "
                  f"🍚 午餐：{node.name}（{fmt_duration(item['dwell'])}）\n")
                if item["wait"] > 0:
                    if item["start"] < req.preferred_lunch:
                        p(f"        到达 {fmt_time(item['arrival'])}，"
                          f"为避免行程拖沓，等候 {fmt_duration(item['wait'])} 后提前用餐\n")
                    else:
                        p(f"        到达 {fmt_time(item['arrival'])}，"
                          f"等候 {fmt_duration(item['wait'])} 至偏好用餐时间\n")
                if item["queue"]:
                    p(f"        拥挤排队约 {item['queue']} 分钟\n")
            else:
                show = item["show"]
                if show:
                    p(f"  {fmt_time(item['active_start'])}–{fmt_time(item['end'])} "
                      f"🐾 {node.name}　★ {show.name}"
                      f"（{fmt_time(show.start_minute)} 开场）\n")
                    if item["wait"] > 0:
                        p(f"        {fmt_time(item['arrival'])} 到达，"
                          f"等待开场 {fmt_duration(item['wait'])}\n")
                else:
                    p(f"  {fmt_time(item['start'])}–{fmt_time(item['end'])} "
                      f"🐾 {node.name}（自由参观 "
                      f"{fmt_duration(item['dwell'])}）\n")
                if item["queue"]:
                    p(f"        当前拥挤：{CONGESTION_LABEL[node.congestion]}，"
                      f"排队约 {item['queue']} 分钟\n")

    if b.shows_seen:
        p("\n— 已安排的表演 —\n")
        for nid, name, start in b.shows_seen:
            p(f"  · {graph.node(nid).name}《{name}》 {fmt_time(start)}\n")

    if plan.alternatives:
        p("\n— 其它可行备选（按综合评分）—\n")
        for i, alt in enumerate(plan.alternatives, 1):
            seq = " → ".join(graph.node(x).name for x in alt.sequence)
            p(f"  {i}. {seq}  结束 {fmt_time(alt.finish_minute)}，"
              f"步行 {alt.walk_distance:.0f} 米，{len(alt.shows_seen)} 场表演\n")

    if plan.suggestion:
        s = plan.suggestion
        p("\n" + "-" * 64 + "\n")
        p(f"💡 建议：{s.reason}\n")
        if s.reduced_simulation:
            rs = s.reduced_simulation
            p("   删减后行程："
              + " → ".join([graph.node(req.entrance).name]
                           + [graph.node(i).name for i in rs.sequence]
                           + [graph.node(req.exit).name]) + "\n")
    p("=" * 64 + "\n")


def _path_tags(path) -> str:
    tags = []
    if any(not e.stroller_ok for e in path.edges):
        tags.append("含儿童车限行路段")
    steep = [e for e in path.edges if e.slope >= 8]
    if steep:
        tags.append(f"最大坡度{max(e.slope for e in steep):g}%")
    cong = max((e.congestion for e in path.edges),
               key=lambda c: c.value, default=Congestion.NORMAL)
    if cong in (Congestion.HIGH, Congestion.VERY_HIGH):
        tags.append(f"拥挤:{CONGESTION_LABEL[cong]}")
    names = [e.name for e in path.edges if e.name]
    if names:
        tags.append("途经" + "、".join(sorted(set(names))))
    return "、".join(tags)


# ------------------------------------------------------------------
# 园区列表 / 地图
# ------------------------------------------------------------------
def print_nodes(graph: ZooGraph, file=sys.stdout) -> None:
    p = file.write
    p(f"\n{graph.name} 园区数据：{len(graph.nodes)} 个节点，"
      f"{len(graph.all_edges())} 条道路\n")
    labels = {NodeType.ENTRANCE: "入口", NodeType.EXIT: "出口",
              NodeType.ANIMAL: "动物区", NodeType.LUNCH: "午餐点",
              NodeType.JUNCTION: "交汇点"}
    for ntype in (NodeType.ENTRANCE, NodeType.EXIT, NodeType.ANIMAL,
                  NodeType.LUNCH, NodeType.JUNCTION):
        items = graph.nodes_by_type(ntype)
        if not items:
            continue
        p(f"\n【{labels[ntype]}】\n")
        for n in items:
            extra = []
            if n.shows:
                extra.append("表演:" + "、".join(
                    f"{s.name} {fmt_time(s.start_minute)}" for s in n.shows))
            if n.congestion != Congestion.NORMAL:
                extra.append(f"拥挤:{CONGESTION_LABEL[n.congestion]}")
            if n.base_dwell():
                extra.append(f"停留约{n.base_dwell()}分")
            suffix = "（" + "；".join(extra) + "）" if extra else ""
            p(f"  {n.id:>4}  {n.name}{suffix}\n")

    problems = graph.validate_connectivity()
    if problems:
        p("\n⚠ 数据问题:\n")
        for m in problems:
            p(f"  - {m}\n")


def print_edges(graph: ZooGraph, file=sys.stdout) -> None:
    p = file.write
    p("\n【道路连接】\n")
    for e in graph.all_edges():
        p(f"  {e.a} {graph.node(e.a).name} ↔ {e.b} {graph.node(e.b).name}: "
          f"{graph.describe_edge(e)}\n")


ASCII_MAP = """
        N1 北门
         |  \\
         |   A1 熊猫馆=====A2 狮虎山=====A4 企鹅馆
         |  /  \\(台阶)        ||             ||
        N0 中央广场--A3 大象馆=||=L1 雨林餐厅=A6 热带鸟林
         |   \\       \\        ||   //          //
         |    \\------A5 灵长动物区=//----------
        L2 便利店   //   \\
         |        //      \\
        N2 南门--A7 儿童动物园
"""


# ------------------------------------------------------------------
# 家长交互
# ------------------------------------------------------------------
def _ask_index(prompt, items, allow_empty=False, name_fn=lambda x: x.name):
    while True:
        print(prompt)
        for i, it in enumerate(items, 1):
            print(f"  {i}. {name_fn(it)}")
        raw = input("请输入编号（多个用逗号，回车"
                    + ("跳过）: " if allow_empty else "确认）: ")).strip()
        if allow_empty and not raw:
            return []
        try:
            idxs = [int(x) for x in raw.replace("，", ",").split(",") if x]
            if allow_empty and not idxs:
                return []
            chosen = [items[i - 1] for i in idxs]
            if chosen and (allow_empty or len(chosen) >= 1):
                return chosen
        except (ValueError, IndexError):
            pass
        print("输入无效，请重试。")


def interactive_parent(graph: ZooGraph, data_path: str) -> None:
    print(f"\n欢迎使用{graph.name}亲子半日游推荐系统")
    print(ASCII_MAP)
    entrances = _node_choices(graph, NodeType.ENTRANCE)
    exits = _node_choices(graph, NodeType.EXIT)
    animals = graph.nodes_by_type(NodeType.ANIMAL)
    lunches = graph.nodes_by_type(NodeType.LUNCH)

    entry = _ask_index("选择入口：", entrances)[0]
    out = _ask_index("选择出口：", exits)[0]
    chosen_animals = _ask_index(
        "选择想看的动物区（按意愿排序，逗号分隔，最多7个）：",
        animals, allow_empty=False)[:7]
    lunch = _ask_index("选择午餐点（可跳过）：", lunches, allow_empty=True)
    lunch_id = lunch[0].id if lunch else None

    raw = input("入园时间（回车默认 09:00）: ").strip()
    start = parse_hhmm(raw) if raw else 9 * 60
    raw = input("半日时间预算小时数（回车默认 4）: ").strip()
    budget = int(float(raw) * 60) if raw else 240
    raw = input("偏好午餐时间（回车默认 12:00）: ").strip()
    pref_lunch = parse_hhmm(raw) if raw else 12 * 60
    stroller = input("是否推儿童车？(Y/n，回车=是): ").strip().lower() != "n"

    req = PlanRequest(
        entrance=entry.id, exit=out.id,
        animals=[a.id for a in chosen_animals], lunch=lunch_id,
        start_minute=start, time_budget=budget,
        preferred_lunch=pref_lunch, stroller=stroller)
    try:
        plan = plan_route(graph, req)
    except ZooGraphError as ex:
        print(f"无法规划：{ex}")
        return
    print_plan(graph, plan)


# ------------------------------------------------------------------
# 管理员交互
# ------------------------------------------------------------------
def _pause():
    input("\n回车继续...")


def admin_menu(graph: ZooGraph, data_path: str) -> None:
    while True:
        print(f"\n==== 管理员后台（{graph.name}） 数据文件: {data_path} ====")
        print("1. 查看全部节点\n2. 查看全部道路\n3. 新增节点\n4. 删除节点")
        print("5. 新增道路\n6. 删除道路\n7. 设置节点拥挤度")
        print("8. 设置道路拥挤度\n9. 新增表演场次\n10. 连通性检查")
        print("11. 保存数据\n0. 退出")
        choice = input("选择: ").strip()
        try:
            if choice == "1":
                print_nodes(graph)
            elif choice == "2":
                print_edges(graph)
            elif choice == "3":
                _admin_add_node(graph)
            elif choice == "4":
                _admin_del_node(graph)
            elif choice == "5":
                _admin_add_edge(graph)
            elif choice == "6":
                _admin_del_edge(graph)
            elif choice == "7":
                _admin_set_node_congestion(graph)
            elif choice == "8":
                _admin_set_edge_congestion(graph)
            elif choice == "9":
                _admin_add_show(graph)
            elif choice == "10":
                probs = graph.validate_connectivity()
                print("✔ 园区连通性正常" if not probs else
                      "\n".join("⚠ " + x for x in probs))
            elif choice == "11":
                graph.save_json(data_path)
                print(f"已保存到 {data_path}")
            elif choice == "0":
                if input("有未保存的修改，退出前保存吗？(Y/n): ").strip().lower() != "n":
                    graph.save_json(data_path)
                print("再见。")
                return
            else:
                print("无效选项。")
        except ZooGraphError as ex:
            print(f"操作失败：{ex}")
        _pause()


def _admin_add_node(graph):
    nid = input("节点编号(如 A8): ").strip()
    name = input("名称: ").strip()
    print("类型: 1入口 2出口 3动物区 4午餐点 5交汇点")
    tmap = {"1": NodeType.ENTRANCE, "2": NodeType.EXIT,
            "3": NodeType.ANIMAL, "4": NodeType.LUNCH,
            "5": NodeType.JUNCTION}
    ntype = tmap[input("类型编号: ").strip()]
    dwell = input("自定义停留分钟（回车默认）: ").strip()
    graph.add_node(Node(
        id=nid, name=name, ntype=ntype,
        dwell=int(dwell) if dwell else None))
    print("✔ 已新增节点（尚未保存）")


def _admin_del_node(graph):
    nid = input("要删除的节点编号: ").strip()
    graph.remove_node(nid)
    print("✔ 已删除（尚未保存）")


def _admin_add_edge(graph):
    a = input("端点A编号: ").strip()
    b = input("端点B编号: ").strip()
    dist = float(input("距离(米): ").strip())
    slope = float(input("坡度%（回车0）: ").strip() or 0)
    sok = input("儿童车可通行？(Y/n): ").strip().lower() != "n"
    print("拥挤: 1低 2中 3高 4很高")
    cong = Congestion.parse(input("等级（回车2）: ").strip() or 2)
    name = input("道路名称（可空）: ").strip() or None
    graph.add_edge(Edge(a=a, b=b, distance=dist, slope=slope,
                        stroller_ok=sok, congestion=cong, name=name))
    print("✔ 已新增道路（尚未保存）")


def _admin_del_edge(graph):
    a = input("端点A: ").strip()
    b = input("端点B: ").strip()
    graph.remove_edge(a, b)
    print("✔ 已删除（尚未保存）")


def _admin_set_node_congestion(graph):
    nid = input("节点编号: ").strip()
    print("拥挤: 1低 2中 3高 4很高")
    level = Congestion.parse(input("等级: ").strip())
    graph.set_node_congestion(nid, level)
    print(f"✔ {graph.node(nid).name} 拥挤度 -> {CONGESTION_LABEL[level]}（尚未保存）")


def _admin_set_edge_congestion(graph):
    a = input("端点A: ").strip()
    b = input("端点B: ").strip()
    print("拥挤: 1低 2中 3高 4很高")
    level = Congestion.parse(input("等级: ").strip())
    graph.set_edge_congestion(a, b, level)
    print("✔ 道路拥挤度已更新（尚未保存）")


def _admin_add_show(graph):
    nid = input("动物区节点编号: ").strip()
    node = graph.node(nid)
    if node.ntype != NodeType.ANIMAL:
        raise ZooGraphError("只有动物区可以添加表演")
    name = input("表演名称: ").strip()
    start = parse_hhmm(input("开始时间 HH:MM: ").strip())
    dur = int(input("时长分钟（回车20）: ").strip() or 20)
    from .models import Show
    node.shows.append(Show(name, start, dur))
    print("✔ 表演场次已添加（尚未保存）")


# ------------------------------------------------------------------
# 入口
# ------------------------------------------------------------------
def load_graph(path: str) -> ZooGraph:
    p = Path(path)
    if p.exists():
        return ZooGraph.load_json(p)
    g = build_sample_zoo()
    g.save_json(p)
    return g


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="动物园亲子游半日路线推荐系统")
    parser.add_argument("-d", "--data", default=DEFAULT_DATA_PATH,
                        help="园区数据 JSON 路径")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("demo", help="运行内置示例")
    sub.add_parser("list", help="列出园区节点与道路")
    sub.add_parser("admin", help="管理员后台")
    sub.add_parser("interactive", help="家长交互选择")

    sp = sub.add_parser("plan", help="直接生成路线")
    sp.add_argument("--entrance", default="N1")
    sp.add_argument("--exit", dest="exit_id", default="N2")
    sp.add_argument("--animals", nargs="+", default=["A1", "A3", "A5", "A6"])
    sp.add_argument("--lunch", default="L2")
    sp.add_argument("--start", default="09:00")
    sp.add_argument("--budget-hours", type=float, default=4.0)
    sp.add_argument("--lunch-time", default="12:00")
    sp.add_argument("--no-stroller", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cmd = args.command or "demo"
    try:
        graph = load_graph(args.data)
        if cmd == "demo":
            print("演示场景：北门入园、南门出，看熊猫/大象/灵长/鸟林，"
                  "便利店午餐，推儿童车，09:00 开始 4 小时\n")
            req = PlanRequest(
                entrance="N1", exit="N2",
                animals=["A1", "A3", "A5", "A6"], lunch="L2",
                start_minute=9 * 60, time_budget=240,
                preferred_lunch=12 * 60, stroller=True)
            print_plan(graph, plan_route(graph, req))
        elif cmd == "list":
            print(ASCII_MAP)
            print_nodes(graph)
            print_edges(graph)
        elif cmd == "admin":
            admin_menu(graph, args.data)
        elif cmd == "interactive":
            interactive_parent(graph, args.data)
        elif cmd == "plan":
            req = PlanRequest(
                entrance=args.entrance, exit=args.exit_id,
                animals=args.animals, lunch=args.lunch,
                start_minute=parse_hhmm(args.start),
                time_budget=int(args.budget_hours * 60),
                preferred_lunch=parse_hhmm(args.lunch_time),
                stroller=not args.no_stroller)
            print_plan(graph, plan_route(graph, req))
    except (ZooGraphError, ValueError, KeyError) as ex:
        print(f"错误：{ex}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
