# 动物园亲子游半日路线推荐系统

家长选择 **入口、想看的动物区、午餐点和出口**，系统综合
**距离、坡度、儿童车友好度、园区拥挤程度和表演时间**，
推荐一条评分最优的半日游路线；管理员可以维护园区节点、道路连接和拥挤程度。

## 功能一览

- 家长端
  - 选择入口 / 出口（支持同一门进出）
  - 勾选最多 7 个想看的动物区（按意愿排序）
  - 选择午餐点、入园时间、半日预算、偏好午餐时间、是否推儿童车
  - 输出带时刻的行程时间轴：步行路段（含经停点、路况标签）、
    动物表演、自由参观、拥挤排队、午餐
  - 自动等待 / 追赶表演场次（等太久会放弃），给出 5 条备选路线
  - 预算内无法看完时，给出“放弃哪些展区”的贪心建议
- 算法
  - 园区为带权无向图；Dijkstra 求节点两两最短路（带缓存复用）
  - 枚举动物区顺序（≤7!）× 午餐插入位置（n+1），逐方案时间轴仿真
  - 道路代价 = 距离/步速 × 坡度系数 × 拥挤系数，儿童车限行道路
    严格模式直接禁行（自动绕行台阶/陡坡），软模式施加 2.5 倍惩罚
  - 评分 = 步行代价 + 等待×0.5 + 午餐偏离×0.8 + 排队×0.3
         − 每场表演 50 分奖励 + 超时×3
  - 可行方案优先，再按评分、步行距离、结束时间稳定排序
- 管理员端（`python -m zoo_tour --data <文件> admin`）
  - 节点 / 道路的增删
  - 设置节点或道路的拥挤度（低 / 中 / 高 / 很高 4 档）
  - 维护动物区表演场次、自定义停留时间
  - 园区连通性检查（孤岛节点检查）
  - JSON 文件持久化保存

## 目录结构

```
zoo_tour/
  models.py        # 枚举、节点/道路/表演、步行画像、时间工具
  graph.py         # 园区图、Dijkstra 最短路、管理员维护、JSON 持久化
  planner.py       # 路线枚举、时间轴仿真、评分、删减建议
  sample_data.py   # 12 节点 24 道路的示例园区
  cli.py           # 命令行（家长交互 / 管理员后台 / 演示）
  __main__.py      # python -m zoo_tour 入口
data/sample_zoo.json
tests/             # 51 个测试（pytest 风格 + 无依赖运行器）
```

## 快速开始

需要 Python 3.9+，无第三方依赖。

```bash
# 1) 内置示例：北门进南门出、4 个动物区、便利店午餐、推儿童车
python3 -m zoo_tour demo

# 2) 直接指定参数
python3 -m zoo_tour plan \
    --entrance N1 --exit N2 \
    --animals A1 A3 A5 A6 --lunch L2 \
    --start 09:00 --budget-hours 4 --lunch-time 12:00

# 不推儿童车（可能走石阶捷径、穿陡坡）
python3 -m zoo_tour plan --animals A1 A2 --lunch L1 --no-stroller

# 3) 家长交互选择
python3 -m zoo_tour interactive

# 4) 查看园区节点、表演、道路和示意地图
python3 -m zoo_tour list

# 5) 管理员后台（改完选 11 保存）
python3 -m zoo_tour admin
```

所有命令都可以加 `-d/--data 路径.json` 切换园区数据文件
（放在子命令之前，如 `python3 -m zoo_tour -d myzoo.json admin`）。

## 示例园区说明

`data/sample_zoo.json` 包含：北门 / 南门、7 个动物展区、2 个午餐点、
1 个中央广场、24 条道路、8 场定时表演。其中：

- 熊猫馆 ↔ 中央广场的 **石阶捷径**（220 米、台阶）——儿童车模式自动绕行；
- 狮虎山周边的北环山坡路（坡度 12%~14%）——儿童车限行；
- 雨林餐厅及“餐厅路”默认 **高拥挤**（影响通行和排队时间）；
- 便利店靠近南门，适合把午餐放在后半程、从南门离开的家庭。

拥挤度 4 档对道路通行的系数：低 0.95 / 中 1.00 / 高 1.30 / 很高 1.70；
节点在高 / 很高拥挤时额外增加 8 / 18 分钟排队时间。

## 代价模型

道路（边）的感知步行分钟：

```
cost = 距离 / 步速 × (1 + 坡度% × 0.05) × 拥挤系数
若推儿童车且道路限行：严格模式 = 不可通行；软模式 × 2.5
```

默认亲子步速 60 米/分钟。方案总评分（越低越好）：

```
score  = 所有路段 cost 之和
       + 等表演分钟 × 0.5
       + |午餐开始 − 偏好午餐| × 0.8
       + 排队分钟 × 0.3
       − 50 × 看到的表演场数
       + max(0, 结束时间 − 预算结束) × 3
```

为避免无意义的长等：等一场表演最多 25 分钟
（`PlanRequest.max_show_wait`），距离偏好午餐时间最多等 15 分钟
（`max_lunch_wait`），超时则放弃该表演 / 提前用餐。

## 运行测试

```bash
# 有 pytest 时
python3 -m pytest tests/ -q

# 没有 pytest 时（沙箱离线也能跑）
python3 -m tests.run_tests
```

测试覆盖：模型解析与序列化、节点/道路维护校验、拥挤与坡度代价、
儿童车限行绕行与软惩罚、Dijkstra 两两最短路对称性、
时间轴仿真（表演等待/排队/午餐/连续性）、超预算删减建议、
示例数据端到端规划等 51 个用例。

## 作为库调用

```python
from zoo_tour.graph import ZooGraph
from zoo_tour.planner import PlanRequest, plan_route

g = ZooGraph.load_json("data/sample_zoo.json")
req = PlanRequest(
    entrance="N1", exit="N2",
    animals=["A1", "A3", "A5", "A6"], lunch="L2",
    start_minute=9*60, time_budget=240,
    preferred_lunch=12*60, stroller=True)
plan = plan_route(g, req)
print(plan.feasible, plan.best.shows_seen, plan.best.timeline)
```
