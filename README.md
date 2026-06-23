# 基于出租车GPS数据的时空特征提取及可视化

深圳出租车GPS数据分析项目，完整流水线：数据清洗 → OD提取 → 数据分析 → 可视化 → 预测 → 百度地图流向 → 缓存构建 → 轨迹查询 → 交互热力图 → 路网校正与拥堵道路 → ETA → 系统集成。

---

## 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas numpy matplotlib seaborn scikit-learn folium statsmodels xgboost
```

## 原始数据

`TaxiData.csv` — 约 4,693 万行，6 列无表头。

| 列 | 说明 |
|---|---|
| id | 车辆编号 |
| time | GPS采集时间（HH:MM:SS） |
| long | 经度 |
| lati | 纬度 |
| status | 载客状态（1=载客, 0=空客） |
| speed | GPS车速 |

## 运行

按顺序执行，每步依赖上一步的输出：

```bash
source .venv/bin/activate

python src/01_数据清洗.py     # ~10-30 分钟（47M 行）
python src/02_OD提取.py       # ~2 分钟
python src/03_数据分析.py      # ~3 分钟
python src/04_可视化.py        # ~1 分钟
python src/05_预测.py          # ~1 分钟
python src/06_百度地图流向.py          # ~10 秒（生成 HTML）
python src/07_缓存构建.py      # ~20 分钟（流式读 clean.csv 生成车辆轨迹缓存）
python src/08_轨迹查询.py      # ~1 分钟（生成轨迹回放 HTML）
python src/09_交互热力图.py    # ~1 分钟（生成交互热力图 HTML）
python src/10_路网分析.py      # ~5 分钟（OSM 路网 + GPS snapping + 拥堵 HTML）

# 演示模式（4 个交互页面需 HTTP 服务器）：
python -m http.server 8080
# 然后浏览器打开 http://localhost:8080/roadmap/demo.html
# 或单页直接访问 http://localhost:8080/output/figures/xxx.html

# 单脚本支持 --serve 自动启动 HTTP 服务器：
python src/06_百度地图流向.py --serve
python src/08_轨迹查询.py --serve
python src/09_交互热力图.py --serve
python src/10_路网分析.py --serve --port 8080
```

---

## 流水线说明

### 1. 01_数据清洗.py

| 步骤 | 说明 |
|---|---|
| 读取 | `pd.read_csv` 带显式 dtype（防 OOM） |
| 排序 | 按 `(id, time)` 升序 |
| 类型转换 | `time` 转为 datetime |
| 坐标过滤 | 深圳范围：经度 113.5–114.8, 纬度 22.3–22.9 |
| 速度过滤 | 0–120 km/h |
| 重复值去重 | 按 `(id, time)` 查重，基于 status 变化判断保留行 |
| 异常值检测 | 60秒内 status 翻转判定为异常 |
| **车辆级过滤** | 剔除速度始终为0 / 全天同一状态的车辆 |

**清洗结果**：

| 指标 | 数值 |
|---|---|
| 原始行数 | 46,927,855 |
| 坐标过滤 | −63,249 |
| 速度过滤 | −18 |
| 去重 | −74,508 |
| 异常剔除 | −46,732 |
| 车辆过滤 | −7,847,069 |
| **清洗后行数** | **38,896,279** |

### 2. 02_OD提取.py

基于 status 变化（0→1 上车，1→0 下车），用 `shift(-1)` 拼接 OD 对。

**结果**：`data/orders.csv` — 486,122 个 OD 出行对。

| 字段 | 说明 |
|---|---|
| 车辆id | 车辆编号 |
| 开始时间/开始经度/开始纬度 | 上客点 |
| O_HEAD/O_SPEED/O_FLAG | 上客点车辆方向/速度/状态（HEAD无数据填0）|
| 结束时间/结束经度/结束纬度 | 下客点 |
| D_HEAD/D_SPEED/D_FLAG | 下客点车辆方向/速度/状态 |
| OD_TIME_s | 订单时长（秒） |
| OD_Dis_km | 订单距离（km） |

### 3. 03_数据分析.py

6 个子分析产出 8 个结果文件：

| 分析 | 输出文件 | 结果 |
|---|---|---|
| DBSCAN上客点聚类 | `clustered_hotspots.csv` | 28 个簇，1.02% 噪声 |
| 订单时段统计（小时） | `hourly_orders.csv` | 24 小时订单分布 |
| 订单时段统计（15分钟） | `quarter_hour_orders.csv` | 96 个 15 分钟窗口 |
| 订单时段统计（每分钟） | `minutely_orders.csv` | 1,440 分钟粒度 |
| 订单时长分布 | `order_duration_stats.csv` | 各时段均值/中位数 |
| 出行距离划分 | `JNLuC.csv` | 短途 62%, 中途 22%, 长途 16% |
| 订单平均速度 | `avg_speed_by_hour.csv` | 各时段平均速度 (km/h) |
| 载客出租车数量 | `occupied_taxis.csv` | 每 1 分钟载客车数 |

### 4. 04_可视化.py

8 张图表：

| 图表 | 文件 | 说明 |
|---|---|---|
| 出行小时数量统计 | `hourly_orders.png` | 柱状图+折线图 |
| 各时段订单时长分布 | `order_duration_boxplot.png` | 箱型图（0–60min） |
| 上客点热力分布 | `static_heatmap.png` | 散点热力图 |
| 15分钟热力切片 | `heatmap_slices.png` | 8×12 子图网格 |
| **动态热力图** | `dynamic_heatmap.gif` | 24 帧动画 |
| 载客出租车数量变化 | `occupied_taxis.png` | 折线图 |
| 出行距离划分 | `trip_distance.png` | 饼图 |
| 各时段道路平均速度 | `avg_speed.png` | 折线图 |

### 5. 05_预测.py

| 模型 | 方法 | 评估指标 |
|---|---|---|
| 乘客需求预测 | ARIMA(1,1,1) | RMSE ≈ 8,428 |
| ETA 预测 | XGBoost | MAE ≈ 323 秒, RMSE ≈ 511 秒 |

### 6. 06_百度地图流向.py

基于百度地图 JavaScript API 的 OD 流向可视化：

- 将 486K OD 对按网格（~1.5 km）聚合
- 剔除起点=终点的同格子零长度流向
- 取 Top 300 流向线，低流量先画（蓝色细线），高流量后画（红粗线）不被遮盖
- 生成 standalone HTML，需通过 HTTP 服务器打开（`file://` 会被浏览器安全策略拦截）
- 需百度地图开放平台 AK（浏览器端），已配置
- 支持 `--serve` 参数自动启动 HTTP 服务器

**运行**：

```bash
python src/06_百度地图流向.py --serve
# 然后浏览器打开 http://localhost:8080/baidu_flow_map.html
```

**输出**：`output/figures/baidu_flow_map.html`

### 7. 07_缓存构建.py

从 `clean.csv` 流式构建车辆轨迹与聚合统计缓存，避免后续每张地图/查询都重扫 2.3 GB 清洗结果。

| 输出文件 | 用途 |
|---|---|
| `data/cache/vehicles.json` | 车辆元数据：{vid: [point_count, offset, 'vehicle_data.json']}，支持 O(1) 偏移定位 |
| `data/cache/vehicle_data.json` | 全量轨迹缓存（~2.6 GB），按 `"vid": [[lon, lat, status, speed, hour], ...]` 流式输出 |
| `data/cache/vehicle_list.json` | 车辆 ID 列表，供地图下拉选择与查询接口 |
| `data/cache/stats_summary.json` | 小时级载客车数与平均速度聚合，供热力图/统计图复用 |

**难点**：2.6 GB 缓存不能整体 `json.load`，下游脚本用正则 `_VEHICLE_KEY_RE` 流式定位车辆键后再读片段；车辆数据跨 chunk 边界需缓存末尾续拼；元数据偏移必须与写入字节精确对应。

### 8. 08_轨迹查询.py

从 2.6 GB `vehicle_data.json` 流式抽取 100 辆代表性车辆轨迹，搭配 `orders.csv` 上下客点，生成百度地图交互式轨迹回放查看器。

- 分层抽样：按轨迹点数排序后均分 100 个分位桶，每桶取订单最多者，兼顾轨迹长/短与订单多/少。
- 单车轨迹点上限 1500，超出均匀降采样。
- 百度地图 JS API v3.0：速度渐变折线、回放动画、上下客标记、实时信息面板。

**运行**：

```bash
python src/08_轨迹查询.py --serve
# 浏览器打开 http://localhost:8080/trajectory_viewer.html
```

**输出**：`output/figures/trajectory_viewer.html` + `output/figures/trajectory_sample.json`

### 9. 09_交互热力图.py

读取 `orders.csv` 上客点 → 按小时分桶 + ~100 m 网格聚合 → 生成百度地图 HeatmapOverlay 交互热力图。

| 参数 | 值 |
|---|---|
| 网格大小 | 0.001°（深圳纬度下 ≈ 111 m） |
| 每小时最大点数 | 20000 |
| 时间滑块 | 0–23h |
| 中心/缩放 | (114.06, 22.55) / zoom 12 |

- 越界过滤使用 `SHENZHEN_BOUNDS`，剔除水域/边界外异常点。
- 时间滑块切换需正确释放旧热力数据，避免内存泄漏。

**运行**：

```bash
python src/09_交互热力图.py --serve
# 浏览器打开 http://localhost:8080/interactive_heatmap.html
```

**输出**：`output/figures/interactive_heatmap.html`

### 10. 10_路网分析.py

基于出租车 GPS 数据的深圳路网级拥堵可视化，串联 06 路网校正与 07 HMM/拥堵/ETA 阶段。

| 阶段 | 说明 |
|---|---|
| 路网下载 | OSM drive 路网 → GeoJSON；离线 fallback 生成深圳边界网格路网 |
| GPS snapping | 流式读 `vehicle_data.json`，~3% 采样 ~1.1M 点，cKDTree(K=5) + shapely 精确选最近边 |
| 速度统计 | 按 `(u,v,key)` 累积车速，计算边平均速度 |
| 拥堵等级 | 畅通 >45 km/h（绿 #228B22）/ 缓行 20–45 km/h（黄 #FFD700）/ 拥堵 <20 km/h（红 #DC143C） |
| 可视化 | 百度地图道路线段着色图层 |

- ETA 衔接：路段平均速度作为 `05_预测.py` XGBoost ETA 模型特征来源，形成“路网感知—速度统计—ETA”闭环。
- 采样率 `SAMPLE_RATE=0.03`、随机种子 42 固定以便复现。

**运行**：

```bash
python src/10_路网分析.py --serve --port 8080
# 浏览器打开 http://localhost:8080/road_congestion.html
# 或从 clean.csv 直接采样（无需先建缓存）：
python src/10_路网分析.py --use-clean-csv
```

**输出**：`data/road_network/shenzhen_edges.geojson`、`shenzhen_nodes.geojson`、`road_speeds.json` + `output/figures/road_congestion.html`

依赖额外包：`osmnx geopandas shapely pyproj scipy`。

```
├── TaxiData.csv                     # 原始数据（47M行）
├── src/
│   ├── config.py                    # 全局常量
│   ├── utils.py                     # 辅助函数
│   ├── 01_数据清洗.py               # 清洗流水线
│   ├── 02_OD提取.py                 # OD 提取
│   ├── 03_数据分析.py               # 多维分析
│   ├── 04_可视化.py                 # 图表输出
│   ├── 05_预测.py                   # 预测模型
│   ├── 06_百度地图流向.py           # 百度地图 OD 流向图
│   ├── 07_缓存构建.py               # 车辆轨迹/统计缓存
│   ├── 08_轨迹查询.py               # 百度地图轨迹回放查看器
│   ├── 09_交互热力图.py             # 百度地图交互热力图
│   └── 10_路网分析.py               # OSM 路网 + GPS snapping + 拥堵 HTML
├── data/                            # 数据产出
│   ├── cache/                       # 车辆轨迹与统计缓存
│   └── road_network/                # 深圳路网 GeoJSON + 速度统计
├── output/figures/                  # 图表产出（含 4 个交互 HTML）
├── roadmap/                         # 阶段路线图与演示门户
├── .omo/plans/taxi-gps-pipeline.md  # 实施计划
└── README.md                        # 本文件
```

---

## `data/` 输出文件详解

### 中间/清洗数据（按运行顺序）

| 文件 | 大小 | 用途 |
|---|---|---|
| `clean_stage1.csv` | 2.2G | **排序+类型转换**后的中间结果。若 01 中途中断，从此文件继续，不用重读原始数据 |
| `clean_stage2.csv` | 2.2G | **去重后**的中间结果。若异常检测环节中断，从这步继续 |
| `clean.csv` | 2.3G | **最终清洗结果**。02、03、04、05 步的输入数据，含 38,896,279 行 GPS 记录 |
| `orders.csv` | 59M | **OD 出行表**，核心产出。486,122 个出行对，每个对包含上下车点经纬度、时长、距离、车速、载客状态 |

### 分析结果（供可视化/预测使用）

| 文件 | 大小 | 行数 | 用途 |
|---|---|---|---|
| `clustered_hotspots.csv` | 1.5K | 28 | DBSCAN 聚类得到的热门上客区 → 热力图的输入数据 |
| `hourly_orders.csv` | 216B | 24 | **每小时**订单数 → 柱状图、ARIMA 需求预测的输入 |
| `quarter_hour_orders.csv` | 2.4K | 96 | **每15分钟**订单数 → 15分钟热力切片图的输入 |
| `minutely_orders.csv` | 34K | 1,440 | **每分钟**订单数 → 精细粒度分析 |
| `order_duration_stats.csv` | 1.0K | 24 | 各小时订单时长的均值/中位数 |
| `avg_speed_by_hour.csv` | 516B | 24 | 各小时道路平均速度 → 速度折线图输入 |
| `occupied_taxis.csv` | 36K | 1,440 | 每分钟处于载客状态的出租车数量 → 载客数量图输入 |
| `JNLuC.csv` | 42B | 1 | 短途/中途/长途订单数量 → 饼图输入 |
| `demand_forecast.csv` | 171B | 5 | ARIMA 预测的测试集结果（小时、实际值、预测值） |
| `eta_forecast.csv` | 3.2M | 97,224 | XGBoost 预测的测试集结果（实际秒数、预测秒数、误差） |

### 车辆轨迹缓存（`data/cache/`，由 07_缓存构建.py 产出）

| 文件 | 大小 | 用途 |
|---|---|---|
| `vehicles.json` | ~700K | 车辆元数据 {vid: [point_count, offset, 'vehicle_data.json']}，支持按偏移 O(1) 定位轨迹 |
| `vehicle_data.json` | ~2.6G | **全量轨迹缓存**，按 `"vid": [[lon, lat, status, speed, hour], ...]` 流式输出，不可整体 `json.load` |
| `vehicle_list.json` | ~30K | 车辆 ID 列表，供地图页面下拉选择与轨迹查询接口 |
| `stats_summary.json` | ~1K | 小时级载客车数与平均速度聚合，供热力图/统计图复用，避免重扫大文件 |

### 路网数据（`data/road_network/`，由 10_路网分析.py 产出）

| 文件 | 大小 | 用途 |
|---|---|---|
| `shenzhen_edges.geojson` | ~30M | 深圳路网边（LineString 集合），含 `osmid / u / v / key / geometry / highway` |
| `shenzhen_nodes.geojson` | ~5M | 路网节点（Point 集合），供 snapping 索引与可视化 |
| `road_speeds.json` | ~1M | 按 `(u,v,key)` 累积的路段速度统计与拥堵等级，供拥堵 HTML 与 ETA 模型复用 |

---

## `output/figures/` 输出文件详解

| 文件 | 大小 | 说明 |
|---|---|---|
| `hourly_orders.png` | 73K | **出行小时数量统计** — 柱状图+折线图。观察早晚高峰、夜间低峰 |
| `order_duration_boxplot.png` | 72K | **各时段订单时长箱型图** — 0~60分钟范围，看高峰期是否更堵 |
| `static_heatmap.png` | 54K | **上客点热力分布** — DBSCAN 28个簇的热力散点图，颜色越深上车越多 |
| `heatmap_slices.png` | 885K | **15分钟热力切片** — 8行×12列共96个窗口，看一天之内客流热区如何移动 |
| `dynamic_heatmap.gif` | 200K | **动态热力图 GIF** — 24帧，每小时一帧，循环播放客流空间分布变化 |
| `occupied_taxis.png` | 80K | **载客出租车数量变化** — 全天折线，看载客车数量随时间波动 |
| `trip_distance.png` | 59K | **出行距离划分饼图** — 短途 62% / 中途 22% / 长途 16% |
| `avg_speed.png` | 65K | **各时段道路平均速度** — 折线图，看早晚高峰速度下降 |
| `demand_forecast.png` | 67K | **ARIMA 需求预测对比图** — 测试集上实际 vs 预测的订单数 |
| `eta_feature_importance.png` | 32K | **XGBoost 特征重要性** — 哪个特征对 ETA 预测贡献最大 |
| `baidu_flow_map.html` | 25K | **百度地图 OD 流向图** — Top 300 流向线，颜色/粗细/透明度反映流量大小，浏览器打开 |
| `trajectory_viewer.html` | ~1.2M | **百度地图轨迹回放** — 100 辆代表性车辆，速度渐变折线 + 上下客标记 + 实时面板，HTTP 服务器访问 |
| `trajectory_sample.json` | ~2M | 轨迹回放页面异步加载的离线数据（抽样轨迹与上下客事件） |
| `interactive_heatmap.html` | ~800K | **百度地图交互热力图** — 上客点按小时切换，~100m 网格聚合，时间滑块 0–23h，HTTP 服务器访问 |
| `road_congestion.html` | ~1.5M | **百度地图路网拥堵** — 深圳 OSMdrive 路网按平均速度着色（绿/黄/红），HTTP 服务器访问 |
