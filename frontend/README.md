# frontend — 深圳出租车GPS数据分析系统 · 前端门户

独立前端目录，整合 4 个百度地图交互页面与 8 个阶段路线图，使用 GSAP 做入场/滚动/hover 动效。

## 目录结构

```
frontend/
├── README.md                       # 本文件
├── index.html                      # 统一入口（合并原 roadmap/index.html + roadmap/demo.html）
├── assets/
│   ├── css/
│   │   └── style.css               # 全站样式（复制自 roadmap/style.css）
│   └── js/
│       └── animations.js           # GSAP 动画（入场 + 滚动揭示 + hover + 地图浮层）
├── pages/
│   ├── od-flow.html                # OD 流向图（原 baidu_flow_map.html）
│   ├── trajectory.html             # 轨迹回放（原 trajectory_viewer.html）
│   ├── heatmap.html                # 交互热力图（原 interactive_heatmap.html）
│   ├── congestion.html             # 路网拥堵（原 road_congestion.html）
│   └── stages/                     # 8 个阶段路线图
│       ├── 01-项目导入与清洗启动.html
│       ├── 02-清洗完成与OD启动.html
│       ├── 03-OD完成与缓存构建.html
│       ├── 04-地图基础与轨迹查询.html
│       ├── 05-热力图与统计分析.html
│       ├── 06-路网校正与地图选点.html
│       ├── 07-HMM拥堵道路与ETA.html
│       └── 08-系统集成与验收准备.html
└── data/
    └── trajectory_sample.json      # 轨迹回放依赖的离线数据（16MB，复制自 output/figures/）
```

## 与流水线的关系

- 本目录是**独立维护的前端展示层**，不参与 Python 流水线生成。
- 原始 `roadmap/` 与 `output/figures/` 保持不动，下次流水线重跑 `06/08/09/10` 脚本会覆盖 `output/figures/` 中的 HTML，但 `frontend/` 不会被覆盖。
- 如需让流水线生成的 HTML 也自带 GSAP，需修改 `src/06_百度地图流向.py` 等 4 个生成器脚本，本目录不涉及。

## 访问方式

所有交互页面基于百度地图 JavaScript API，**不能使用 `file://` 协议打开**。必须通过 HTTP 服务器访问：

```bash
# 在项目根目录启动 HTTP 服务器
python -m http.server 8080

# 浏览器访问
http://localhost:8080/frontend/index.html
```

或使用任意静态文件服务器（`serve`、`nginx`、`python src/06_百度地图流向.py --serve` 等）。

## GSAP 动效说明

`assets/js/animations.js` 通过 `gsap.matchMedia()` 同时处理响应式与无障碍：

| 条件 | 行为 |
|-----|------|
| `prefers-reduced-motion: reduce` | 跳过所有动画，元素直接显示为最终状态 |
| 桌面端（≥720px） | 卡片错开入场 + 滚动揭示 + hover 微反馈 |
| 移动端（<720px） | 同上但 stagger 间隔更短 |

三类页面的动效适配：

| 页面类型 | 动效 |
|---------|------|
| 门户首页 `index.html` | header 入场、demo-card/box/nav 错开 stagger、section 滚动揭示、卡片 hover 上浮+缩放 |
| 阶段页 `pages/stages/*.html` | header 入场、section 滚动揭示、卡片 hover |
| 交互地图 `pages/*.html` | 地图加载后浮层（#title/#legend/#info/#panel/#header）依次淡入 |

性能要点（遵循 gsap-performance 规范）：
- 只动画 `transform` 与 `opacity`（`x/y/scale/autoAlpha`），不动画 `width/height/top/left`
- hover 用 `gsap.quickTo()` 复用 tween，避免每次事件创建新 tween
- ScrollTrigger 只用于顶层 tween，`once: false` 配合 `toggleActions: 'play none none reverse'` 实现进入/离开双向

## 依赖

- GSAP 3.12.5（CDN 加载，零安装）
- ScrollTrigger 3.12.5（CDN 加载，GSAP 插件）
- 百度地图 JavaScript API v3.0（CDN 加载，AK 已配置在原 HTML 内）

GSAP CDN 地址：
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>
```

## 离线降级

如 GSAP CDN 加载失败，`animations.js` 会检测 `window.gsap` 不存在时静默退出，页面保持可用，只是无动画。百度地图 API 仍需联网加载（这是原始流水线设计的固有限制）。
