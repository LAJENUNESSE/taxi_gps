# 出租车GPS数据时空特征提取及可视化 — 工作计划

## TL;DR

> **Quick Summary**: 基于47M行深圳出租车GPS原始数据，构建5脚本串行流水线（清洗→OD提取→数据分析→可视化→预测），产出清洗后数据、OD出行表、6+图表和2个预测模型。
>
> **Deliverables**:
> - `src/01_数据清洗.py` — `data/clean.csv`
> - `src/02_OD提取.py` — `data/orders.csv`
> - `src/03_数据分析.py` — 聚类/统计/速度/距离分析结果
> - `src/04_可视化.py` — `output/figures/` 下 6+ PNG 图表
> - `src/05_预测.py` — ARIMA需求预测 + XGBoost ETA预测
>
> **Estimated Effort**: Large
> **Parallel Execution**: 有限 — 严格串行流水线，仅 Wave 5（可视化+预测）可并行
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5/6 → F1-F4

---

## Context

### Original Request
基于 `TaxiData.csv`（约4700万行，6列无表头：id,time,long,lati,status,speed）实现完整的数据清洗、OD提取、数据分析、可视化和预测流程。参考 `实训V_项目介绍.md`（项目需求）和 `数据简单处理.md`（清洗教程）。用户准备换另一个模型来实施此计划。

### Interview Summary
**Key Discussions**:
- 数据格式：CSV 无 header，time 为 HH:MM:SS 格式（缺省年月日），pd.to_datetime 会补当天日期
- 已用 uv + 阿里云镜像装好全部依赖：pandas, numpy, matplotlib, seaborn, scikit-learn, folium, statsmodels, xgboost
- 百度地图 API Key 还在审核，流向图后续单独补充
- 项目日志/ 和 pandas练习/ 目录不管
- 测试策略：无单元测试，Agent QA 验证每个脚本能跑通 + 输出文件存在 + 图表生成

**Research Findings**:
- 数据格式确认：`22223,21:09:38,114.138535,22.609266,1,19`（6列）
- 去重逻辑来自 `数据简单处理.md` 需求3-7，基于 status 前后变化判断保留哪行
- 异常检测：shift(±1) 生成前后状态，60秒内 status 翻转视为异常
- OD提取：status_chg=1 上车，-1 下车，shift(-1) 拼接成OD对
- **Metis 验证数据实况**：47M行 / 14,729辆车 / 1.8GB CSV / 单日数据(00:00-23:59) / 264行经度异常 / 929行纬度异常 / 18行速度>120
- **TaxiData_Desc.txt 部分错误**：写的是5字段+完整时间戳，实际是6字段+HH:MM:SS
- **Python 实际是 3.13.9**（venv），不是3.12

### Metis Review
**Identified Gaps** (all addressed):
- 坐标边界未指定 → 锁定 113.5≤long≤114.8, 22.3≤lat≤22.9
- 内存优化未指定 → 锁定显式 dtype (int32/float32/int8/int16)
- 中间结果保存策略 → 分3阶段保存 (stage1/stage2/clean)
- 单日假设未文档化 → 文档化 + 加单调性校验
- Must NOT Have 缺失 → 添加7条范围锁定
- 验收标准模糊 → 改为可执行命令
- NaN 处理未提及 → shift 首尾 NaN 用 fillna/过滤
- DBSCAN eps 无起点 → 0.003-0.005
- ARIMA 划分未定义 → 最后20%作测试集
- 图表语言/字体 → 中文 + CJK字体配置

---

## Work Objectives

### Core Objective
构建5个Python脚本的串行流水线，将47M行原始出租车GPS数据清洗为可用数据，提取OD出行对，进行多维数据分析（聚类/统计/速度/距离），生成6+可视化图表，并训练2个预测模型（ARIMA需求 + XGBoost ETA）。

### Concrete Deliverables
- `src/01_数据清洗.py` + `data/clean_stage1.csv` + `data/clean_stage2.csv` + `data/clean.csv`
- `src/02_OD提取.py` + `data/orders.csv`
- `src/03_数据分析.py` + `data/clustered_hotspots.csv` + `data/JNLuC.csv` + 其他统计结果
- `src/04_可视化.py` + `output/figures/` 下至少6个PNG
- `src/05_预测.py` + 预测结果输出

### Definition of Done
- [ ] 5个脚本按顺序执行全部 exit code 0
- [ ] `data/clean.csv` 行数 > 100K，无坐标越界，无(id,time)重复
- [ ] `data/orders.csv` 所有 O_time<D_time，OD_TIME_s>0，OD_Dis_km>0
- [ ] `output/figures/` 下 ≥6 个 PNG，每个 >10KB
- [ ] ARIMA RMSE 和 XGBoost MAE/RMSE 已打印，预测值非负

### Must Have
- 显式 dtype 读取 47M 行 CSV（避免 OOM）
- 坐标边界过滤（113.5-114.8, 22.3-22.9）
- 速度边界过滤（0-120 km/h）
- 分阶段保存中间结果（支持断点续跑）
- 去重逻辑严格遵循 `数据简单处理.md` 需求3-7的7种情况
- 异常值检测遵循 `数据简单处理.md` 需求8-10（60秒阈值）
- OD提取验证 id_chg==0（同一辆车）
- DBSCAN 聚类上客点
- matplotlib CJK 字体配置（中文标签）
- 每个脚本顶部 assert 输入文件存在

### Must NOT Have (Guardrails)
- 不做交互式 folium 地图（仅静态 PNG）
- 不加外部特征工程（天气/POI/交通数据）
- 不上深度学习（LSTM/Transformer 等）
- 不做实时预测 API/服务器
- 不做 k-fold 交叉验证/网格搜索
- 动态热力图 = 时间切片静态帧，不做动画
- 不做坐标变换/geo-hashing
- 不依赖 `TaxiData_Desc.txt`（该文件部分错误，以实际CSV为准）
- 不写单元测试（数据分析项目，Agent QA 验证脚本运行）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: NO
- **Automated tests**: NO（数据分析项目，无测试框架）
- **Framework**: none
- **Agent QA**: 每个脚本跑一遍，检查 stdout 无报错 + 输出文件存在 + 图表 PNG 生成 + 数据约束校验

### QA Policy
每个任务包含 agent-executed QA scenarios。Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **数据分析脚本**: Use Bash — `python src/0X_xxx.py`，检查 exit code + 输出文件
- **数据约束验证**: Use Bash (python -c) — 读 CSV 验证列/行数/值域
- **图表验证**: Use Bash — 检查 PNG 文件存在且 >10KB

---

## Execution Strategy

### Parallel Execution Waves

> 本项目是严格串行流水线（每步依赖上一步输出），并行性有限。
> 仅 Wave 5（可视化+预测）可并行，因两者都依赖 03 的输出但互不依赖。

```
Wave 1 (Start Immediately - scaffolding):
└── Task 1: 项目脚手架 — 创建目录结构 + 常量配置 + 字体设置 [quick]

Wave 2 (After Wave 1 - 数据清洗，最耗时):
└── Task 2: 01_数据清洗.py — 读取/排序/类型转换/去重/异常剔除 [deep]

Wave 3 (After Wave 2 - OD提取):
└── Task 3: 02_OD提取.py — status变化提取上下车点 [unspecified-high]

Wave 4 (After Wave 3 - 数据分析):
└── Task 4: 03_数据分析.py — DBSCAN/统计/速度/距离/载客数 [deep]

Wave 5 (After Wave 4 - 可并行):
├── Task 5: 04_可视化.py — 6+图表输出 [visual-engineering]
└── Task 6: 05_预测.py — ARIMA + XGBoost [deep]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 2 → Task 3 → Task 4 → Task 5/6 → F1-F4 → user okay
Parallel Speedup: ~15% (only Wave 5 parallel)
Max Concurrent: 2 (Wave 5) / 4 (Final)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|---|---|---|
| 1 | - | 2 |
| 2 | 1 | 3 |
| 3 | 2 | 4 |
| 4 | 3 | 5, 6 |
| 5 | 4 | F1-F4 |
| 6 | 4 | F1-F4 |
| F1-F4 | 5, 6 | - |

### Agent Dispatch Summary

- **Wave 1**: 1 task — T1 → `quick`
- **Wave 2**: 1 task — T2 → `deep`
- **Wave 3**: 1 task — T3 → `unspecified-high`
- **Wave 4**: 1 task — T4 → `deep`
- **Wave 5**: 2 tasks — T5 → `visual-engineering`, T6 → `deep`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. 项目脚手架 — 创建目录结构 + 常量配置 + 字体设置

  **What to do**:
  - 创建目录结构: `src/`, `data/`, `output/figures/`
  - 创建 `src/config.py`，定义全局常量：
    - `DATA_FILE = 'TaxiData.csv'`
    - `COLUMNS = ['id', 'time', 'long', 'lati', 'status', 'speed']`
    - `DTYPES = {'id': 'int32', 'time': 'str', 'long': 'float32', 'lati': 'float32', 'status': 'int8', 'speed': 'int16'}`
    - `SHENZHEN_BOUNDS = {'long_min': 113.5, 'long_max': 114.8, 'lat_min': 22.3, 'lat_max': 22.9}`
    - `SPEED_MAX = 120`
    - `ANOMALY_TIME_THRESHOLD = 60` (秒)
    - `DBSCAN_EPS = 0.004`
    - `DBSCAN_MIN_SAMPLES = 50`
    - `DISTANCE_SHORT = 4` (km)
    - `DISTANCE_LONG = 8` (km)
    - `ARIMA_TEST_RATIO = 0.2`
  - 创建 `src/utils.py`，包含：
    - `setup_matplotlib_cjk()` — 配置中文字体: `plt.rcParams['font.sans-serif'] = ['SimHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'DejaVu Sans']`, `plt.rcParams['axes.unicode_minus'] = False`
    - `haversine_km(lat1, lon1, lat2, lon2)` — Haversine 公式计算经纬度距离(km)
    - `assert_input_exists(filepath)` — 断言输入文件存在，否则 raise FileNotFoundError
    - `assert_output_valid(filepath, min_size=1)` — 断言输出文件存在且非空
  - 创建 `.gitignore`（如需要）忽略 `data/*.csv`, `output/figures/*.png`, `.venv/`

  **Must NOT do**:
  - 不在 config.py 里写业务逻辑
  - 不硬编码路径（全部用相对路径或 config 常量）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯文件创建和常量定义，无需复杂逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (alone)
  - **Blocks**: Task 2
  - **Blocked By**: None (can start immediately)

  **References**:
  - `数据简单处理.md:16-20` — 列名定义 `['id','time','long','lati','status','speed']`
  - `实训V_项目介绍.md:14` — 深圳市范围外数据需删除（坐标边界）
  - `实训V_项目介绍.md:14` — 速度超过120km/h需删除
  - `实训V_项目介绍.md:90` — 4km/8km 距离阈值
  - Metis review: 坐标边界 113.5-114.8, 22.3-22.9; DBSCAN eps 0.003-0.005

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 目录结构和配置文件创建成功
    Tool: Bash
    Preconditions: 项目根目录 /home/lajenunesse/projects/python/taxi_gps/
    Steps:
      1. 运行 `ls -d src/ data/ output/figures/` — 三个目录都存在
      2. 运行 `python -c "from src.config import COLUMNS, DTYPES, SHENZHEN_BOUNDS, DBSCAN_EPS; print(COLUMNS, DTYPES, SHENZHEN_BOUNDS, DBSCAN_EPS)"` — 无 ImportError
      3. 运行 `python -c "from src.utils import setup_matplotlib_cjk, haversine_km; print(haversine_km(22.55, 114.05, 22.60, 114.10))"` — 输出一个正数（约6-7km）
    Expected Result: 目录存在，config 导入成功，haversine 返回正数
    Failure Indicators: ImportError, 目录不存在, haversine 返回0或负数
    Evidence: .omo/evidence/task-1-scaffold-check.txt

  Scenario: 中文字体配置可用
    Tool: Bash
    Preconditions: src/utils.py 已创建
    Steps:
      1. 运行 `python -c "from src.utils import setup_matplotlib_cjk; setup_matplotlib_cjk(); import matplotlib.pyplot as plt; fig=plt.figure(); plt.title('测试中文'); plt.savefig('output/figures/font_test.png'); plt.close()"`
      2. 检查 `ls -la output/figures/font_test.png` 文件存在且 >1KB
    Expected Result: PNG 文件生成，大小 >1KB（字体配置成功，即使没有中文字体也不报错，会 fallback）
    Failure Indicators: 文件不存在，python 报错
    Evidence: .omo/evidence/task-1-font-test.png
  ```

  **Commit**: YES
  - Message: `chore: scaffold project structure and config`
  - Files: `src/config.py`, `src/utils.py`, `src/__init__.py`, `.gitignore`

- [x] 2. 01_数据清洗.py — 读取/排序/类型转换/去重/异常剔除

  **What to do**:
  - **读取数据** (参考 `数据简单处理.md` 需求1):
    - `pd.read_csv('TaxiData.csv', header=None, names=COLUMNS, dtype=DTYPES)`
    - 打印 `df.info()` 和 `df.head(20)` 到 stdout（日志）
  - **排序** (需求1):
    - `df = df.sort_values(by=['id', 'time']).reset_index(drop=True)`
    - 注意: time 是 HH:MM:SS 字符串，定宽格式可直接字符串排序
    - 排序后验证: 按 id 分组，每组 time 单调不减（单日假设校验）
    - 保存中间结果 `data/clean_stage1.csv`
  - **类型转换** (需求2):
    - `df['time'] = pd.to_datetime(df['time'])` — 补当天日期
  - **坐标+速度过滤** (Metis guardrail):
    - 过滤 `long` 在 [113.5, 114.8] 之外 → 打印删除行数
    - 过滤 `lati` 在 [22.3, 22.9] 之外 → 打印删除行数
    - 过滤 `speed` > 120 或 < 0 → 打印删除行数
  - **重复值处理** (需求3-7，核心难点):
    - 1. `df_dup = df[df.duplicated(subset=['id','time'], keep=False)].reset_index()` — 保留全部重复，reset_index 把原索引变为列
    - 2. 检查重复数量 >2: `(df_dup.groupby(['id','time'])['status'].count()==2).all()` — 打印结果
    - 3. 分组统计: `dup_grp = df_dup.groupby(['id','time']).agg(stat_cnt=('status','count'), stat_sum=('status','sum')).reset_index()`
    - 4. 合并: `dup_mrg = pd.merge(df_dup, dup_grp, on=['id','time'], how='left')`
    - 5. 实现 `dup_check(x)` 函数（7种情况，见下方表格）
    - 6. `kp_index = dup_mrg.groupby(['id','time']).apply(dup_check)`
    - 7. `drp_index = dup_mrg.loc[~dup_mrg['index'].isin(kp_index.values), 'index']`
    - 8. `df = df.loc[~df.index.isin(drp_index.values)]`
    - 保存中间结果 `data/clean_stage2.csv`

  **dup_check 7种情况表**:
  | stat_cnt | stat_sum | 含义 | 保留 |
  |---|---|---|---|
  | 2 | 0 | 两个status都0 | 第一个索引 `x['index'].values[0]` |
  | 2 | 1 | status为[1,0] | status=0的行 `x.loc[x.status==0, 'index'].values[0]` |
  | 2 | 2 | 两个status都1 | 第一个索引 |
  | 3 | 0 | 三个0 | 第一个索引 |
  | 3 | 1 | [1,0,0] | 第一个0 |
  | 3 | 2 | [1,1,0] | 第一个1 |
  | 3 | 3 | 三个1 | 第一个索引 |

  - **异常值处理** (需求8-10):
    - 1. shift 生成6个辅助列: `status_up=status.shift(1)`, `status_down=status.shift(-1)`, `id_up=id.shift(1)`, `id_down=id.shift(-1)`, `time_up=time.shift(1)`, `time_down=time.shift(-1)`
    - 2. 5个筛选条件:
       - `cond_1 = status != status_down`
       - `cond_2 = status != status_up`
       - `cond_3 = id == id_up`
       - `cond_4 = id == id_down`
       - `cond_5 = (time_down - time_up).dt.seconds < 60`
    - 3. `df_abn = df[cond_1 & cond_2 & cond_3 & cond_4 & cond_5].reset_index()`
    - 4. 打印异常数据 id 分布: `df_abn.id.value_counts()`
    - 5. `df = df.loc[~df.index.isin(df_abn['index'].values)]`
  - **清理辅助列**: 删除 `status_up, status_down, id_up, id_down, time_up, time_down`（保留 `status_up, id_up` 用于后续OD提取，但保存到 clean.csv 时可保留或删除）
  - **保存最终结果**: `df.to_csv('data/clean.csv', index=False)`
  - **打印汇总日志**: 原始行数、排序后行数、坐标过滤删除数、速度过滤删除数、去重删除数、异常删除数、最终行数

  **Must NOT do**:
  - 不用 for 循环去重（47M行会跑几小时），必须用 groupby+merge+apply
  - 不依赖 `TaxiData_Desc.txt`（该文件格式描述有误）
  - 不跳过中间结果保存（断点续跑需要）
  - 不在 read_csv 时省略 dtype（会 OOM）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 47M行数据处理 + 复杂去重逻辑 + 内存优化 + 多阶段流程，需要深度思考和调试
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (alone)
  - **Blocks**: Task 3
  - **Blocked By**: Task 1

  **References**:
  - `数据简单处理.md:16-20` — 读取数据 + 列名定义
  - `数据简单处理.md:48-58` — 排序逻辑
  - `数据简单处理.md:64-75` — time 类型转换
  - `数据简单处理.md:82-100` — 重复值查找（需求3）
  - `数据简单处理.md:109-141` — 重复数量统计（需求4-5）
  - `数据简单处理.md:143-167` — 分组统计+合并（需求6）
  - `数据简单处理.md:168-209` — dup_check 函数+去重（需求7）
  - `数据简单处理.md:229-261` — shift 生成辅助列+异常筛选（需求8-9）
  - `数据简单处理.md:274-283` — 异常剔除（需求10）
  - `实训V_项目介绍.md:14` — 坐标/速度/载客状态异常需删除
  - Metis review: 显式 dtype、坐标边界、速度边界、中间结果分阶段保存、单调性校验、NaN处理

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 清洗脚本完整运行并产出 clean.csv
    Tool: Bash
    Preconditions: Task 1 完成，TaxiData.csv 存在
    Steps:
      1. 运行 `python src/01_数据清洗.py` — 等待完成（可能10-30分钟）
      2. 检查 exit code == 0
      3. 检查 `ls -la data/clean_stage1.csv data/clean_stage2.csv data/clean.csv` 都存在
    Expected Result: 三个 CSV 都存在，clean.csv 行数 > 100000
    Failure Indicators: exit code != 0，文件不存在，行数 < 100000
    Evidence: .omo/evidence/task-2-clean-output.txt (包含 stdout 日志)

  Scenario: 清洗后数据约束验证
    Tool: Bash
    Preconditions: data/clean.csv 已生成
    Steps:
      1. 运行 `python -c "import pandas as pd; df=pd.read_csv('data/clean.csv'); print('rows:', len(df)); print('bad_long:', (df['long']>120).sum()); print('bad_lat:', (df['lat']>90).sum()); print('dups:', df.duplicated(subset=['id','time']).sum()); print('max_speed:', df['speed'].max()); print('min_speed:', df['speed'].min())"`
    Expected Result: rows > 100000, bad_long=0, bad_lat=0, dups=0, max_speed<=120, min_speed>=0
    Failure Indicators: 任何约束不满足
    Evidence: .omo/evidence/task-2-constraints.txt

  Scenario: 单日数据单调性校验
    Tool: Bash
    Preconditions: data/clean_stage1.csv 已生成
    Steps:
      1. 运行 `python -c "import pandas as pd; df=pd.read_csv('data/clean_stage1.csv'); df['time_str']=df['time'].astype(str); mono=df.groupby('id')['time_str'].apply(lambda x: x.is_monotonic_increasing); print('all_monotonic:', mono.all()); print('non_mono_count:', (~mono).sum())"`
    Expected Result: all_monotonic=True（或 non_mono_count 很小），验证单日假设成立
    Failure Indicators: 大量非单调数据（说明跨天数据混入）
    Evidence: .omo/evidence/task-2-monotonicity.txt
  ```

  **Commit**: YES
  - Message: `feat(clean): data cleaning pipeline with dedup and anomaly detection`
  - Files: `src/01_数据清洗.py`, `data/clean_stage1.csv`, `data/clean_stage2.csv`, `data/clean.csv`

- [x] 3. 02_OD提取.py — status变化提取上下车OD对

  **What to do**:
  - **读取清洗后数据**: `df = pd.read_csv('data/clean.csv')`
    - 断言文件存在: `assert_input_exists('data/clean.csv')`
    - 转换 time 列: `df['time'] = pd.to_datetime(df['time'])`
  - **生成辅助列** (参考 `数据简单处理.md` 需求11):
    - `df['status_up'] = df['status'].shift(1)` — 上一个状态
    - `df['id_up'] = df['id'].shift(1)` — 上一个车辆id
    - 处理首行 NaN: `df['status_up'] = df['status_up'].fillna(-1)`, `df['id_up'] = df['id_up'].fillna(-999)` (避免 NaN 影响计算)
  - **计算状态差**:
    - `df['status_chg'] = df['status'] - df['status_up']` — 1=上车(0→1), -1=下车(1→0), 0=无变化
    - `df['id_chg'] = df['id'] - df['id_up']` — 0=同一辆车
  - **筛选上下车点**:
    - `df_temp = df.loc[((df['status_chg']==1) | (df['status_chg']==-1)) & (df['id_chg']==0)]`
    - 打印上车点数量 (status_chg==1) 和下车点数量 (status_chg==-1)
  - **拼接OD对** (shift(-1) 将下车信息上移):
    - `df_temp['Etime'] = df_temp['time'].shift(-1)`
    - `df_temp['Elong'] = df_temp['long'].shift(-1)`
    - `df_temp['Elati'] = df_temp['lati'].shift(-1)`
    - 筛选上车行且与下一行(下车)为同一车辆:
      `df_order = df_temp.loc[(df_temp['status_chg']==1) & (df_temp['id']==df_temp['id'].shift(-1)), ['id','time','long','lati','Etime','Elong','Elati']]`
  - **重命名列** (按 `实训V_项目介绍.md` OD数据字段):
    - `id → 车辆id` (或 `O_COMMADDR`)
    - `time → 开始时间` (或 `O_time`)
    - `long → 开始经度` (或 `O_lng`)
    - `lati → 开始纬度` (或 `O_lat`)
    - `Etime → 结束时间` (或 `D_time`)
    - `Elong → 结束经度` (或 `D_lng`)
    - `Elati → 结束纬度` (或 `D_lat`)
  - **计算OD时间和距离**:
    - `df_order['OD_TIME_s'] = (df_order['结束时间'] - df_order['开始时间']).dt.total_seconds()`
    - `df_order['OD_Dis_km'] = df_order.apply(lambda r: haversine_km(r['开始纬度'], r['开始经度'], r['结束纬度'], r['结束经度']), axis=1)`
  - **过滤无效OD对** (Metis guardrail):
    - 删除 OD_TIME_s <= 0 的行 → 打印删除数
    - 删除 OD_Dis_km <= 0 的行 → 打印删除数
    - 删除跨天OD（开始时间 > 结束时间）→ 打印删除数
  - **保存**: `df_order.to_csv('data/orders.csv', index=False)`
  - **打印汇总日志**: 上车点数、下车点数、配对成功数、无效过滤数、最终OD对数

  **Must NOT do**:
  - 不跳过 id_chg==0 检查（否则 shift 会跨车辆泄漏）
  - 不保留 NaN 行（首行 status_up 为 NaN 需处理）
  - 不输出跨天/零时长/零距离的OD对

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 中等复杂度，shift 逻辑需要仔细处理，但不需要深度设计
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (alone)
  - **Blocks**: Task 4
  - **Blocked By**: Task 2

  **References**:
  - `数据简单处理.md:291-323` — OD提取完整逻辑（需求11）
  - `数据简单处理.md:298-306` — status_chg 和 id_chg 计算
  - `数据简单处理.md:313-322` — shift(-1) 拼接 + 列重命名
  - `实训V_项目介绍.md:24-44` — OD数据字段定义表（O_COMMADDR, O_time, O_lat, O_lng, D_time, D_lat, D_lng, OD_TIME_s, OD_Dis_km）
  - `src/utils.py:haversine_km()` — 距离计算函数
  - Metis review: NaN 处理、id_chg 校验、零时长/零距离过滤

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: OD提取脚本运行并产出 orders.csv
    Tool: Bash
    Preconditions: data/clean.csv 存在（Task 2 完成）
    Steps:
      1. 运行 `python src/02_OD提取.py`
      2. 检查 exit code == 0
      3. 检查 `ls -la data/orders.csv` 存在且 >0 bytes
    Expected Result: orders.csv 生成，行数 > 1000
    Failure Indicators: exit code != 0，文件不存在或为空
    Evidence: .omo/evidence/task-3-od-output.txt

  Scenario: OD数据完整性约束验证
    Tool: Bash
    Preconditions: data/orders.csv 已生成
    Steps:
      1. 运行 `python -c "import pandas as pd; df=pd.read_csv('data/orders.csv'); print('rows:', len(df)); print('cols:', list(df.columns)); print('neg_duration:', (df['OD_TIME_s']<=0).sum()); print('neg_distance:', (df['OD_Dis_km']<=0).sum()); print('max_duration_h:', df['OD_TIME_s'].max()/3600)"`
    Expected Result: rows > 1000, neg_duration=0, neg_distance=0, max_duration_h < 24（单日数据，订单不超过24小时）
    Failure Indicators: 任何约束不满足
    Evidence: .omo/evidence/task-3-constraints.txt
  ```

  **Commit**: YES
  - Message: `feat(od): extract origin-destination pairs from status changes`
  - Files: `src/02_OD提取.py`, `data/orders.csv`

- [x] 4. 03_数据分析.py — DBSCAN聚类/时段统计/速度/距离/载客数

  **What to do**:
  - **读取数据**: `df_order = pd.read_csv('data/orders.csv')`, 转换时间列
  - **断言输入存在**: `assert_input_exists('data/orders.csv')`

  - **4.1 DBSCAN上客点聚类** (`实训V_项目介绍.md` 对上客点进行密度聚类):
    - 提取上客点: `pickup_points = df_order[['开始纬度', '开始经度']].values`
    - DBSCAN: `db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES).fit(pickup_points)`
    - 统计簇: 对非噪声点(labels != -1)按簇分组，计算中心点(均值)和count
    - 保存: `data/clustered_hotspots.csv` (列: lat, lng, count, time)
      - time 列填入当天日期字符串即可
    - 打印: 簇数量、噪声点比例

  - **4.2 订单时段统计** (`数据简单处理.md` 需求12):
    - `df_order['小时'] = pd.to_datetime(df_order['开始时间']).dt.hour`
    - `df_hourcnt = df_order.groupby('小时')['车辆id'].count().rename('数量').reset_index()`
    - 保存: `data/hourly_orders.csv`

  - **4.3 订单时长分布** (`数据简单处理.md` 需求13):
    - `df_order['订单时长'] = (pd.to_datetime(df_order['结束时间']) - pd.to_datetime(df_order['开始时间'])).dt.total_seconds() / 60` (分钟)
    - 保存: `data/order_duration_stats.csv` (按小时分组的统计: mean, median, count)

  - **4.4 订单耗时与路程** (`实训V_项目介绍.md` 计算订单耗时与路程):
    - 已在 Task 3 计算 OD_TIME_s 和 OD_Dis_km
    - 按4km/8km划分短/中/长途:
      - `df_order['距离类型'] = pd.cut(df_order['OD_Dis_km'], bins=[0, 4, 8, float('inf')], labels=['near', 'middle', 'far'])`
    - 按天统计: `data/JNLuC.csv` (列: day, near, middle, far)
      - day = 1 (单日数据)

  - **4.5 订单平均速度** (`实训V_项目介绍.md` 计算订单平均速度):
    - `df_order['avg_speed'] = df_order['OD_Dis_km'] / (df_order['OD_TIME_s'] / 3600)` (km/h)
    - 按时段(小时)统计平均速度: `data/avg_speed_by_hour.csv` (列: O_time, sudu)

  - **4.6 载客出租车数量统计** (`实训V_项目介绍.md` 统计载客出租车数量):
    - 回到 `data/clean.csv`，筛选 status==1 的行
    - 按1分钟间隔升采样: 将时间按 floor 到分钟，统计每分钟不同 id 的数量
    - 保存: `data/occupied_taxis.csv` (列: TIME, number)

  - **打印汇总日志**: 每个子分析的输出行数、关键统计值

  **Must NOT do**:
  - 不做网格搜索调 DBSCAN 参数（用 config 里的默认值）
  - 不加外部数据（天气/POI）
  - 不做交互式可视化（本任务只产出数据，图表在 Task 5）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 6个子分析模块，涉及聚类、统计、时间序列重采样，需要仔细处理
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (alone)
  - **Blocks**: Task 5, Task 6
  - **Blocked By**: Task 3

  **References**:
  - `数据简单处理.md:331-353` — 订单时段统计（需求12）
  - `数据简单处理.md:361-377` — 订单时长分布（需求13）
  - `实训V_项目介绍.md:46-56` — DBSCAN对上客点密度聚类
  - `实训V_项目介绍.md:58-65` — 统计乘客打车时间分布
  - `实训V_项目介绍.md:67-68` — 计算订单耗时与路程
  - `实训V_项目介绍.md:70-78` — 计算订单平均速度
  - `实训V_项目介绍.md:80-87` — 统计载客出租车数量
  - `实训V_项目介绍.md:88-98` — 划分出行距离
  - `实训V_项目介绍.md:136-197` — DBSCAN算法简介和示例代码
  - `src/config.py` — DBSCAN_EPS, DBSCAN_MIN_SAMPLES, DISTANCE_SHORT, DISTANCE_LONG

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 数据分析脚本运行并产出所有结果文件
    Tool: Bash
    Preconditions: data/orders.csv 和 data/clean.csv 存在（Task 2, 3 完成）
    Steps:
      1. 运行 `python src/03_数据分析.py`
      2. 检查 exit code == 0
      3. 检查 `ls -la data/clustered_hotspots.csv data/hourly_orders.csv data/order_duration_stats.csv data/JNLuC.csv data/avg_speed_by_hour.csv data/occupied_taxis.csv` 全部存在
    Expected Result: 6个CSV文件全部存在且非空
    Failure Indicators: exit code != 0，任何文件缺失或为空
    Evidence: .omo/evidence/task-4-analysis-output.txt

  Scenario: DBSCAN聚类结果有效性
    Tool: Bash
    Preconditions: data/clustered_hotspots.csv 已生成
    Steps:
      1. 运行 `python -c "import pandas as pd; df=pd.read_csv('data/clustered_hotspots.csv'); print('clusters:', len(df)); print('cols:', list(df.columns)); print('total_count:', df['count'].sum()); print('lat_range:', df['lat'].min(), df['lat'].max()); print('lng_range:', df['lng'].min(), df['lng'].max())"`
    Expected Result: clusters > 0, 列包含 [lat, lng, count, time], lat在22.3-22.9之间, lng在113.5-114.8之间
    Failure Indicators: clusters=0（全噪声），坐标越界
    Evidence: .omo/evidence/task-4-dbscan-check.txt

  Scenario: 订单时段统计一致性
    Tool: Bash
    Preconditions: data/hourly_orders.csv 和 data/orders.csv 已生成
    Steps:
      1. 运行 `python -c "import pandas as pd; h=pd.read_csv('data/hourly_orders.csv'); o=pd.read_csv('data/orders.csv'); print('hourly_sum:', h['数量'].sum()); print('orders_rows:', len(o)); print('match:', h['数量'].sum()==len(o))"`
    Expected Result: hourly_sum == orders_rows（时段统计总和等于OD对总数）
    Failure Indicators: 总和不匹配
    Evidence: .omo/evidence/task-4-consistency.txt
  ```

  **Commit**: YES
  - Message: `feat(analysis): DBSCAN clustering and multi-dimension analysis`
  - Files: `src/03_数据分析.py`, `data/clustered_hotspots.csv`, `data/hourly_orders.csv`, `data/order_duration_stats.csv`, `data/JNLuC.csv`, `data/avg_speed_by_hour.csv`, `data/occupied_taxis.csv`

- [x] 5. 04_可视化.py — 生成6+可视化图表

  **What to do**:
  - **初始化**: 调用 `setup_matplotlib_cjk()` 配置中文字体
  - **断言输入存在**: `assert_input_exists('data/hourly_orders.csv')`, `assert_input_exists('data/order_duration_stats.csv')` 等

  - **图表1: 出行小时数量统计** (`数据简单处理.md` 需求12):
    - 读取 `data/hourly_orders.csv`
    - 折线图 + 柱状图组合: `plt.plot()` + `plt.bar()`
    - X轴: 小时(0-23), Y轴: 数量
    - 标题: '出行小时数量统计'
    - 保存: `output/figures/hourly_orders.png`

  - **图表2: 订单时长箱型图** (`数据简单处理.md` 需求13):
    - 读取 `data/orders.csv`，计算订单时长(分钟)
    - `sns.boxplot(x='小时', y='订单时长(分钟)', data=df_order)`
    - Y轴限制: 0-60分钟
    - 标题: '各时段订单时长分布'
    - 保存: `output/figures/order_duration_boxplot.png`

  - **图表3: 静态热力图** (`实训V_项目介绍.md` 静态热力图):
    - 读取 `data/clustered_hotspots.csv`
    - 用 folium 或 matplotlib 绘制上客点热力图
    - folium 方案: `folium.Map(location=[22.55, 114.1], zoom_start=11)`, 添加 `HeatMap` 插件
    - 保存: `output/figures/static_heatmap.html` (folium) 或 `output/figures/static_heatmap.png` (matplotlib)
    - 如果用 matplotlib: scatter + colorbar 表示热度

  - **图表4: 载客出租车数量变化** (`实训V_项目介绍.md` 载客车数量):
    - 读取 `data/occupied_taxis.csv`
    - 折线图: X轴=时间, Y轴=载客数量
    - 标题: '载客出租车数量变化'
    - 保存: `output/figures/occupied_taxis.png`

  - **图表5: 路程分析占比** (`实训V_项目介绍.md` 路程分析):
    - 读取 `data/JNLuC.csv`
    - 堆叠柱状图或饼图: 短/中/长途占比
    - 标题: '出行距离划分'
    - 保存: `output/figures/trip_distance.png`

  - **图表6: 道路平均速度** (`实训V_项目介绍.md` 道路速度):
    - 读取 `data/avg_speed_by_hour.csv`
    - 折线图: X轴=时段, Y轴=平均速度(km/h)
    - 标题: '各时段道路平均速度'
    - 保存: `output/figures/avg_speed.png`

  - **打印汇总日志**: 每个图表的文件路径和大小

  **Must NOT do**:
  - 不做交互式地图（仅静态 PNG/HTML）
  - 不做动态动画（"动态热力图"后续如有需要再单独处理）
  - 不在图表里用英文标签（中文标题和轴标签）
  - 不硬编码数据路径（从 config 或相对路径读取）

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 6个图表的绘制，涉及 matplotlib/seaborn/folium 的可视化技巧
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Task 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 4

  **References**:
  - `数据简单处理.md:336-352` — 出行小时数量统计绘图代码
  - `数据简单处理.md:366-377` — 订单时长箱型图代码
  - `实训V_项目介绍.md:99-113` — 可视化模块需求（静态热力图/载客车数量/路程分析/道路速度）
  - `src/utils.py:setup_matplotlib_cjk()` — 中文字体配置
  - `src/config.py` — 路径常量

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 可视化脚本运行并产出6+图表
    Tool: Bash
    Preconditions: Task 4 完成，data/ 下所有分析结果文件存在
    Steps:
      1. 运行 `python src/04_可视化.py`
      2. 检查 exit code == 0
      3. 运行 `ls -la output/figures/*.png output/figures/*.html 2>/dev/null | wc -l` — 文件数量
      4. 运行 `ls -la output/figures/` — 检查每个文件大小
    Expected Result: >=6 个文件，每个 >10KB
    Failure Indicators: exit code != 0，文件数 <6，任何文件 <10KB（空白图）
    Evidence: .omo/evidence/task-5-figures-list.txt

  Scenario: 图表内容非空验证
    Tool: Bash
    Preconditions: output/figures/ 下有图片
    Steps:
      1. 运行 `python -c "from PIL import Image; import os; [print(f, os.path.getsize(os.path.join('output/figures', f))) for f in os.listdir('output/figures') if f.endswith('.png')]"`
      2. 检查每个 PNG 尺寸 >10KB
    Expected Result: 所有 PNG 文件 >10KB
    Failure Indicators: 任何文件 <10KB（可能空白或渲染失败）
    Evidence: .omo/evidence/task-5-png-sizes.txt
  ```

  **Commit**: YES
  - Message: `feat(viz): generate 6+ visualization charts`
  - Files: `src/04_可视化.py`, `output/figures/*.png`, `output/figures/*.html`

- [x] 6. 05_预测.py — ARIMA需求预测 + XGBoost ETA预测

  **What to do**:
  - **断言输入存在**: `assert_input_exists('data/orders.csv')`, `assert_input_exists('data/hourly_orders.csv')`

  - **6.1 乘客需求预测 (ARIMA)** (`实训V_项目介绍.md` 乘客需求预测):
    - 读取 `data/hourly_orders.csv`，按小时排列订单数
    - 划分训练/测试集: 最后20%的小时数据作测试集
    - ARIMA 建模: `from statsmodels.tsa.arima.model import ARIMA`
      - `model = ARIMA(train, order=(1,1,1))` (起始参数，可调)
      - `model_fit = model.fit()`
      - `forecast = model_fit.forecast(steps=len(test))`
    - 评估: `from sklearn.metrics import mean_squared_error; rmse = np.sqrt(mean_squared_error(test, forecast))`
    - 打印: RMSE, 预测值, 实际值
    - 保存预测结果: `data/demand_forecast.csv` (列: hour, actual, predicted)
    - 绘制预测对比图: `output/figures/demand_forecast.png`

  - **6.2 ETA预测 (XGBoost)** (`实训V_项目介绍.md` ETA预测):
    - 读取 `data/orders.csv`
    - 构造特征:
      - `start_lat, start_lng` (开始经纬度)
      - `end_lat, end_lng` (结束经纬度)
      - `distance_km` (OD_Dis_km)
      - `hour` (开始时间的小时)
      - `avg_speed` (平均速度)
    - 目标变量: `OD_TIME_s` (订单耗时，秒)
    - 划分训练/测试集: 按时间顺序最后20%作测试集
    - XGBoost 回归: `import xgboost as xgb`
      - `model = xgb.XGBRegressor(n_estimators=100, max_depth=6, random_state=42)`
      - `model.fit(X_train, y_train)`
      - `y_pred = model.predict(X_test)`
    - 评估: `from sklearn.metrics import mean_absolute_error, mean_squared_error`
      - MAE 和 RMSE
    - 打印: MAE, RMSE, 特征重要性
    - 保存预测结果: `data/eta_forecast.csv` (列: actual_s, predicted_s, error_s)
    - 绘制特征重要性图: `output/figures/eta_feature_importance.png`

  - **验证**: 预测值非负（需求和耗时不能为负）
  - **打印汇总日志**: 两个模型的评估指标

  **Must NOT do**:
  - 不做 LSTM/深度学习
  - 不做网格搜索/超参数调优
  - 不加外部特征（天气/POI/交通）
  - 不做实时预测 API
  - 不做 k-fold 交叉验证

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 涉及时间序列建模、特征工程、模型训练和评估，需要ML经验
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Task 5)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 4

  **References**:
  - `实训V_项目介绍.md:116-127` — 预测模块需求（乘客需求预测 + ETA预测）
  - `实训V_项目介绍.md:120-122` — ARIMA/回归模型建议
  - `实训V_项目介绍.md:124-127` — XGBoost/线性回归建议
  - `src/config.py:ARIMA_TEST_RATIO` — 测试集比例
  - statsmodels ARIMA 文档: `https://www.statsmodels.org/stable/generated/statsmodels.tsa.arima.model.ARIMA.html`
  - XGBoost 文档: `https://xgboost.readthedocs.io/en/latest/python/python_api.html`

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 预测脚本运行并产出两个模型结果
    Tool: Bash
    Preconditions: data/orders.csv 和 data/hourly_orders.csv 存在（Task 4 完成）
    Steps:
      1. 运行 `python src/05_预测.py`
      2. 检查 exit code == 0
      3. 检查 `ls -la data/demand_forecast.csv data/eta_forecast.csv output/figures/demand_forecast.png output/figures/eta_feature_importance.png`
    Expected Result: 2个CSV + 2个PNG 全部存在且非空
    Failure Indicators: exit code != 0，任何文件缺失
    Evidence: .omo/evidence/task-6-predict-output.txt

  Scenario: 模型评估指标和预测非负性验证
    Tool: Bash
    Preconditions: 预测结果已生成
    Steps:
      1. 检查 stdout 日志包含 "RMSE" 和 "MAE"（ARIMA 和 XGBoost 的指标都已打印）
      2. 运行 `python -c "import pandas as pd; d=pd.read_csv('data/demand_forecast.csv'); print('neg_pred:', (d['predicted']<0).sum()); e=pd.read_csv('data/eta_forecast.csv'); print('neg_eta:', (e['predicted_s']<0).sum())"`
    Expected Result: neg_pred=0, neg_eta=0（预测值非负）
    Failure Indicators: 预测值出现负数
    Evidence: .omo/evidence/task-6-metrics.txt
  ```

  **Commit**: YES
  - Message: `feat(predict): ARIMA demand forecast and XGBoost ETA prediction`
  - Files: `src/05_预测.py`, `data/demand_forecast.csv`, `data/eta_forecast.csv`, `output/figures/demand_forecast.png`, `output/figures/eta_feature_importance.png`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
- [x] F2. **Code Quality Review** — `unspecified-high`
- [x] F3. **Real Manual QA** — `unspecified-high`
- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff or file content). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes. Verify no百度地图 API code (excluded), no LSTM/deep learning (excluded), no interactive folium (excluded).
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Task 1**: `chore: scaffold project structure and config` - src/, data/, output/figures/, constants
- **Task 2**: `feat(clean): data cleaning pipeline with dedup and anomaly detection` - src/01_数据清洗.py, data/clean*.csv
- **Task 3**: `feat(od): extract origin-destination pairs from status changes` - src/02_OD提取.py, data/orders.csv
- **Task 4**: `feat(analysis): DBSCAN clustering and multi-dimension analysis` - src/03_数据分析.py, data/clustered_hotspots.csv, data/JNLuC.csv
- **Task 5**: `feat(viz): generate 6+ visualization charts` - src/04_可视化.py, output/figures/
- **Task 6**: `feat(predict): ARIMA demand forecast and XGBoost ETA prediction` - src/05_预测.py

---

## Success Criteria

### Verification Commands
```bash
# 1. 清洗后数据验证
python -c "import pandas as pd; df=pd.read_csv('data/clean.csv'); print('rows:', len(df)); print('bad_long:', (df['long']>120).sum()); print('bad_lat:', (df['lat']>90).sum()); print('dups:', df.duplicated(subset=['id','time']).sum()); print('max_speed:', df['speed'].max())"
# Expected: rows > 100000, bad_long=0, bad_lat=0, dups=0, max_speed<=120

# 2. OD数据验证
python -c "import pandas as pd; df=pd.read_csv('data/orders.csv'); print('rows:', len(df)); print('neg_duration:', (df['OD_TIME_s']<=0).sum()); print('neg_distance:', (df['OD_Dis_km']<=0).sum())"
# Expected: rows > 1000, neg_duration=0, neg_distance=0

# 3. 图表验证
ls -la output/figures/*.png | wc -l  # Expected: >= 6
ls -la output/figures/*.png  # Each file > 10KB

# 4. 全流程串行执行
python src/01_数据清洗.py && python src/02_OD提取.py && python src/03_数据分析.py && python src/04_可视化.py && python src/05_预测.py
# Expected: all exit code 0
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] 5 scripts compile and run sequentially without error
- [ ] data/clean.csv passes all constraint checks
- [ ] data/orders.csv passes all constraint checks
- [ ] output/figures/ has 6+ PNG files, each >10KB
- [ ] ARIMA RMSE and XGBoost MAE/RMSE printed in stdout
