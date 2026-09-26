"""命令行入口：python -m zoo.cli

示例：
  python -m zoo.cli                          # 默认场景规划
  python -m zoo.cli --zones panda,tiger --lunch rest_forest --no-stroller
  python -m zoo.cli --demo-admin             # 演示管理员改拥挤度后重新规划
  python -m zoo.cli --json data/zoo_sample.json   # 从 JSON 加载园区
"""
from __future__ import annotations

import argparse

from .data import build_sample_zoo
from .models import ZooGraph
from .planner import RoutePlanner, Preferences
from .admin import ZooAdmin


def main(argv=None):
    ap = argparse.ArgumentParser(description="动物园亲子半日游路线推荐")
    ap.add_argument("--json", help="从 JSON 文件加载园区数据")
    ap.add_argument("--entrance", default="gate_main")
    ap.add_argument("--exit", default="gate_east")
    ap.add_argument("--zones", default="panda,giraffe,tiger,penguin",
                    help="想看的动物区，逗号分隔")
    ap.add_argument("--lunch", default="rest_lake")
    ap.add_argument("--start", default="09:00")
    ap.add_argument("--no-stroller", action="store_true", help="不推儿童车")
    ap.add_argument("--no-shows", action="store_true", help="不看表演")
    ap.add_argument("--demo-admin", action="store_true",
                    help="演示管理员维护拥挤度并重新规划")
    args = ap.parse_args(argv)

    graph = ZooGraph.load(args.json) if args.json else build_sample_zoo()
    planner = RoutePlanner(graph)
    prefs = Preferences(has_stroller=not args.no_stroller,
                        want_shows=not args.no_shows,
                        start_time=args.start)
    zones = [z for z in args.zones.split(",") if z]

    print("=== 动物园亲子半日游推荐路线 ===")
    print(f"入口={args.entrance} 出口={args.exit} 动物区={zones} "
          f"午餐={args.lunch} 出发={args.start} "
          f"儿童车={'是' if prefs.has_stroller else '否'}")
    plan = planner.plan(args.entrance, args.exit, zones, args.lunch, prefs)
    print(plan.itinerary(graph))

    if args.demo_admin:
        print("\n=== 管理员演示：午高峰主干道拥挤度上调 ===")
        admin = ZooAdmin(graph)
        for a, b in [("j1", "j2"), ("j2", "j3"), ("j4", "j5"), ("j5", "j6")]:
            admin.set_congestion(a, b, 0.9)
        print("拥挤度 TOP5：")
        for e, na, nb in admin.congestion_report()[:5]:
            print(f"  {na} <-> {nb}: {e.congestion:.1f}")
        issues = admin.validate()
        print(f"园区校验: {'通过' if not issues else issues}")
        print("\n=== 拥挤调整后重新规划 ===")
        plan2 = planner.plan(args.entrance, args.exit, zones, args.lunch, prefs)
        print(plan2.itinerary(graph))


if __name__ == "__main__":
    main()
