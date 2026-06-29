# Draft: trajectory-progressive-playback (v2 — scope updated)

## 请求
修改「出租车轨迹查询」页面，轨迹按车辆运动渐产生。

## Intent 路由
CLEAR（OVERRIDE：用户显式要求被提问，关闭 adopt-default 过滤）。

## 关键事实（已核实）
- 管线脚本 `src/visualization/trajectory.py` (脚本08) → `main()` 输出到 `output/figures/trajectory_viewer.html`（trajectory.py:786-795），`--serve` 在 `output/figures/` 起 HTTP。
- 另存在手动维护的演示门户副本 `frontend/pages/trajectory.html`（含独立 CSS 主题 + GSAP 面板脉冲/按钮动效 + 数据路径 `../data/`）。README/AGENTS.md 未描述 frontend/ 与管线的关系。
- 用户实际在浏览器打开的是 **frontend/pages/trajectory.html**，不是管线 output。两个 JS 结构都包含 setInterval/step/playRate/buildPolyline（同一套回放逻辑的两份 copy）。
- 用户认可范围可能需调整："管线输出不在这里，可能需要进行调整"。

## 已确认的行为决策（用户访谈）
1. 渐进画线 + 平滑插值（线随标记逐段延伸）
2. 沿段平滑插值（requestAnimationFrame 替代 setInterval 跳点）
3. 旋转朝向 + 隐藏未走段（BMap.Marker.setRotation 度数；未走折线不绘制）
速度滑块 = 实时拖动即时生效，倍率语义（实现自由常数）。
gap=1 断点：标记跳切，不画跨断点直线。

## Metis 缺口（已记，plan 须消化）
阻塞级：
- M1 setRotation 单位（度，atan2 返回弧度需 ×180/π）
- M2 curIdx 整数→浮点 (segIdx, segFrac) 位置表示法重定义，4 处共享点（step/updateInfo/reset/进度条seek）全改
- M3 进度条 seek 后折线重建算法（从起点-append 到 seek 点）
- M4 gap=1 折线「清除」具体语义
- M5 基准视觉速度常数须明确给定
- M6 (新) 文件作用域拍板
高：
- M7 setPath 逐帧性能（建议段边界 append，不逐帧 setPath 全数组）
- M8 自定义方向箭头图标（默认图钉旋转无意义）
- M9 playing 下 seek 后 rAF 重启
- M10 rawToggle 重建须取消 rAF
中：
- M11 reset() 须清空渐进折线
- M12 移除 BMAP_ANIMATION_BOUNCE（与连续移动冲突）
- M13 f-string {{}} 转义语法校验步骤
- M14 gap 后朝向来源 / gap 前插值终点
低：单点轨迹守卫、超长段线性失真记录为已知、initMap 语法错误无反馈。

## 作用域拍板（待用户回答）
选项见 question。

## Approval Gate
status: awaiting-approval (v2 — scope re-present)
pending action: write .omo/plans/trajectory-progressive-playback.md
approach: 待用户确认作用域后定。