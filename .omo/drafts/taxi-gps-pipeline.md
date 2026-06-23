# Draft: 出租车GPS数据时空特征提取及可视化

## Requirements (confirmed)
- 基于原始数据 `TaxiData.csv`（约4700万行，6列无表头：id,time,long,lati,status,speed）实现完整的数据处理分析流程
- 参考两份文档：`实训V_项目介绍.md`（项目需求）和 `数据简单处理.md`（清洗教程）
- 时间格式 HH:MM:SS（缺省年月日，pd.to_datetime 会补当天）
- 数据是深圳出租车GPS（经度114.x，纬度22.x）

## Technical Decisions
- 包管理：uv + 阿里云镜像
- Python 3.12 + .venv/
- 已装包：pandas, numpy, matplotlib, seaborn, scikit-learn, folium, statsmodels, xgboost
- 项目结构：src/01-05 五个脚本 + data/ 中间产物 + output/figures/
- 运行顺序严格串行：01→02→03→04→05（每步依赖上一步输出）
- folium/pyecharts 替代百度地图（API Key 还在审核）

## Research Findings
- 数据格式确认：22223,21:09:38,114.138535,22.609266,1,19（6列，无header）
- 去重逻辑来自 `数据简单处理.md` 需求3-7，基于 status 前后变化判断保留哪行
- 异常值检测：shift(±1) 生成前后状态，60秒阈值内 status 翻转视为异常
- OD提取：status_chg=1 上车，status_chg=-1 下车，shift(-1) 拼接成OD对

## Scope Boundaries
- INCLUDE: 数据清洗、OD提取、数据分析（DBSCAN聚类/统计/速度/载客数/距离划分）、可视化（静态热力图/动态热力图/折线图/箱型图/柱状图）、预测（ARIMA需求 + XGBoost ETA）
- EXCLUDE: 百度地图API流向图（Key还在审核，后续单独补充）、项目日志目录、pandas练习目录

## Test Strategy Decision
- Infrastructure exists: NO（纯数据分析项目，无测试框架）
- Automated tests: NO（数据分析脚本以运行通过 + 输出文件存在为验收）
- Agent-Executed QA: ALWAYS — 每个脚本跑一遍，检查 stdout 无报错 + 输出文件存在 + 图表 PNG 生成

## Metis Review Findings (Critical)

### Data Reality (Metis verified)
- 47M行 / 14,729辆车 / 1.8GB CSV
- 时间范围 00:00:00-23:59:59（单日数据）
- 坐标异常：264行经度>120°，929行纬度>90°（必须过滤）
- 速度异常：18行 >120 km/h
- TaxiData_Desc.txt 部分错误（5字段+完整时间戳），实际是6字段+HH:MM:SS
- Python 实际是 3.13.9（不是3.12）

### Critical Guardrails (from Metis)
- 坐标边界：113.5≤long≤114.8, 22.3≤lat≤22.9（作为脚本顶部常量）
- 速度边界：0≤speed≤120
- 显式 dtype：id=int32, time=str, long=float32, lati=float32, status=int8, speed=int16
- 中间结果分阶段保存：clean_stage1.csv（排序+类型转换后）→ clean_stage2.csv（去重后）→ clean.csv（异常剔除后）
- 单日假设文档化 + 按 id 分组时间单调性校验
- NaN 处理：shift 产生的首尾 NaN，用 fillna 或过滤
- matplotlib CJK 字体配置（SimHei/WenQuanYi Micro Hei）

### Must NOT Have (Scope Lock-down)
- 不做交互式 folium 地图（仅静态 PNG）
- 不加外部特征工程（天气/POI/交通）
- 不上深度学习（LSTM 等）
- 不做实时预测 API/服务器
- 不做 k-fold/网格搜索
- 动态热力图 = 时间切片静态帧，不做动画
- 不做坐标变换/geo-hashing

### Defaults Applied (auto-resolved)
- 日期分配：单日数据，pd.to_datetime 补当天日期即可（不影响分析）
- DBSCAN eps 起始值：0.003-0.005（深圳纬度约22.5°N，0.01°≈1km，热门上客点半径200-500m）
- ARIMA 训练/测试划分：按时间顺序最后20%作测试集
- 图表语言：中文（与项目文档一致），配置 CJK 字体
- 零时长/零距离订单：过滤（OD_TIME_s>0 且 OD_Dis_km>0）
- 单条记录车辆：OD提取前过滤
- 全0/全1状态车辆：统计并报告数量，不参与OD提取

### Acceptance Criteria (executable)
每个脚本验收用具体命令验证，不用"跑通"这种模糊说法：
- 01: `data/clean.csv` 存在且行数>100K，无坐标越界，无(id,time)重复，速度≤120
- 02: `data/orders.csv` 所有 O_time<D_time，OD_TIME_s>0，OD_Dis_km>0，O_FLAG=1&D_FLAG=0
- 03: 簇数量>0（非全噪声），订单数总和=OD对总数
- 04: ≥6 个 PNG，每个>10KB
- 05: RMSE/MAE 打印，预测值非负

## Open Questions
- 无（所有问题已用合理默认值解决）

## Architecture Notes
- 47M 行原始数据，显式 dtype 后内存约 1.5-2GB
- 清洗后行数待实际跑出（教程数据 54万 是参考，实际比例可能不同）
- 中间结果分3阶段保存，支持断点续跑
