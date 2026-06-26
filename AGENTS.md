# AGENTS.md — taxi_gps

深圳出租车GPS数据分析项目流水线：数据清洗 → OD提取 → 数据分析 → 可视化 → 预测 → 百度地图交互地图 → 路网拥堵 → ETA。

## 项目结构

- `src/` — 编号流水线脚本（`01_数据清洗.py` … `10_路网分析.py`），外加 `config.py`（全局常量）和 `utils.py`（CJK 字体设置、haversine 距离）。
- `data/` — 生成的 CSV、缓存、路网 GeoJSON（`.gitignore` 已忽略）。
- `output/figures/` — 静态 PNG/GIF 和 4 个交互 HTML 页面（PNG/GIF 在 `.gitignore` 中，HTML 被追踪）。
- `roadmap/` — 演示门户（`demo.html`）、阶段里程碑页面、`style.css`。
- `TaxiData.csv` — 约 4700 万行，6 列无表头。在 `.gitignore` 中——不提交。

## 环境与依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas numpy matplotlib seaborn scikit-learn folium statsmodels xgboost osmnx geopandas shapely pyproj scipy
```

没有 `requirements.txt`、`pyproject.toml`、`setup.py`。虚拟环境是 Python 3.13，已加入 `.gitignore`。

### 虚拟环境使用规则（强制）

- 所有 Python 操作必须使用 `.venv/bin/python`，不能依赖系统 `python` 命令。
- 使用 `.venv/bin/pip` 安装依赖，不要全局安装。
- 虚拟环境已存在，通常无需重建。如需重建用 `python3 -m venv .venv`。
- 除非在流水线脚本中使用 `--serve` 启动 HTTP 服务，否则不要安装、下载或引入任何额外软件（浏览器、截图工具、无头浏览器等）。

## 流水线执行

脚本**严格按顺序执行**——每个脚本依赖上一步的输出。在项目根目录下运行，需激活虚拟环境。

```bash
python src/01_数据清洗.py      # ~10-30 分钟（4700 万行）
python src/02_OD提取.py        # ~2 分钟
python src/03_数据分析.py       # ~3 分钟
python src/04_可视化.py         # ~1 分钟
python src/05_预测.py           # ~1 分钟
python src/06_百度地图流向.py   # ~10 秒（生成 HTML）
python src/07_缓存构建.py       # ~20 分钟（流式读取 clean.csv 生成轨迹缓存）
python src/08_轨迹查询.py       # ~1 分钟（轨迹回放 HTML）
python src/09_交互热力图.py     # ~1 分钟（交互热力图 HTML）
python src/10_路网分析.py       # ~5 分钟（OSM 路网 + 地图匹配 + 拥堵 HTML）
```

### 常见失败模式

- **01_数据清洗.py 内存不足（OOM）** — `config.py` 保留了 `DTYPES` 映射（`int32`、`float32`、`int8`），实测 16 GB 机器上即使去掉 dtype 优化、用默认 int64/float64 读取，峰值 RSS 也仅 3.93 GB，远在安全线内（数据来源：4700 万行 × 6 列，`pd.read_csv` → `sort_values` → `pd.to_datetime`，完整流水线全链路验证通过）。如果机器 < 8 GB 可启用 dtype 优化；否则删掉 `DTYPES` 让 pandas 自动推断即可。
- **脚本运行时提示"找不到输入文件"** — 检查 `data/` 下上一步生成的中间文件。流水线有检查点文件（`clean_stage1.csv`、`clean_stage2.csv`、`clean.csv`）——如果某一步只运行了一部分，手动删掉部分输出重新运行。
- **01_数据清洗.py 卡在排序步骤** — `sort_values(by=['id', 'time'])` 需要约 4 GB 内存（实测默认 dtype 下 4700 万行排序，RSS 无额外增量）。确保机器至少有 4 GB 可用内存。
- **08/09/10 运行失败** — 必须先运行 `07_缓存构建.py`，除非使用 `10_路网分析.py --use-clean-csv`。

## 四个交互地图页面

由脚本 06、08、09、10 生成。**都使用百度地图 JavaScript API**——不能用 `file://` 打开（浏览器安全策略会拦截 API 请求）。必须通过 HTTP 服务器访问：

```bash
# 方式 A：使用 --serve 参数自动启动服务器
python src/06_百度地图流向.py --serve

# 方式 B：手动启动 HTTP 服务器
python -m http.server 8080
# → http://localhost:8080/roadmap/demo.html（统一入口）
# → http://localhost:8080/output/figures/baidu_flow_map.html（单个页面）
```

脚本 06/08/09 默认端口 8080；`10_路网分析.py` 也默认 8080，但支持 `--port` 参数。

**百度地图 API Key** 硬编码在 `src/config.py`（`BAIDU_MAP_API_KEY`），已经配好，无需额外配置。

## 大文件处理

- `data/cache/vehicle_data.json` **大约 2.6 GB**。绝对不能直接用 `json.load()` 加载整个文件。下游脚本用正则表达式 `_VEHICLE_KEY_RE` 按字节偏移定位车辆数据，然后读取片段。如果修改任何读取缓存的脚本，务请保持这种方式。
- `data/cache/vehicles.json` 提供了 O(1) 的偏移量查找，指向 `vehicle_data.json` 中的数据。
- `10_路网分析.py` 可以使用 `--use-clean-csv` 参数绕过缓存（直接从 `clean.csv` 流式读取）。

## 中文字体渲染

`utils.py` 中的 `setup_matplotlib_cjk()` 会自动检测字体：`SimHei` → `WenQuanYi Micro Hei` → `Noto Sans CJK SC` → `DejaVu Sans`。如果 matplotlib 图表显示空白方块而不是中文，安装一个 CJK 字体即可（`fonts-wqy-microhei` 或 `fonts-noto-cjk`）。

## 路网（脚本 10）

首次运行时从 OSM 下载驾车路网（保存到 `data/road_network/`）。有离线 fallback 机制，会在深圳范围内生成一个网格路网。需要额外依赖：`osmnx geopandas shapely pyproj scipy`。

## 这个仓库没有什么

- **没有测试**、没有 CI、没有 lint 配置、没有类型检查。
- **没有测试数据**——需要完整的 4700 万行 `TaxiData.csv` 才能运行流水线。
- **没有 Docker / 容器配置**。
- **没有 requirements.txt**——依赖列表见上面的 `pip install`。
