# trajectory-progressive-playback - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** 出租车轨迹查询页面在播放时，路线会按车辆实际运动逐段画出来——箭头标记顺着行驶方向旋转、平滑移动贴着轨迹走，未走过的路径不显示；遇到 GPS 大时间断点会跳切到下一段再继续画。改动同时落到你实际打开的前端门户页面和管线生成器两份，行为一致。开改之前会先把当前工作区推到 GitHub 当回滚点。

**Why this approach:** （1）渐进画线 + requestAnimationFrame 平滑插值替代原来"一次性画完整线 + 标记 80ms 跳 N 点"——视觉上"按运动产生轨迹"；（2）同时改两份是因为你浏览器打开的是手改的演示门户副本，而管线只产出到另一个目录，只改一份等于改不到你现在看的页面；（3）工作区先推 GitHub 是你明确要求，作为改动前的安全检查点。

**What it will NOT do:**
- 不动数据生成层、不重算抽样数据文件——只是改回放的前端表现。
- 不改前端门户的 CSS 主题与 GSAP 动效，只动回放 JS 块。
- 不开发"按真实 GPS 时间戳压缩回放"语义（你已明确弃用）；速度滑块仍是「视觉倍率」。

**Effort:** Short — 单前端行为重构 + 镜像 + 纯函数自测 + 双源 diff 闭环，无数据/后端改动。
**Risk:** Low — 主要风险是百度 JS API `Marker.setRotation` 角度单位与 f-string `{{}}` 转义细节，都已写进计划，并加纯函数测试锁死 heading 约定、双源 JS diff 锁死两份行为一致。
**Decisions to sanity-check:** 基准视觉推进速度常数（BASE_PROGRESS_PER_SEC=1.2 段/秒 @ 1×），可启动后立即微调；自定义箭头图标的视觉风格。

Your next move: 跑完高精度 Momus 审查后用 `$start-work` 启动执行。

---

> TL;DR (machine): Short effort | Low risk | 5-todo 链：git-push 检查点 → frontend 重构 → 纯函数自测 → 生成器同步 + JS-diff → 终验 + 4-item F-wave。

## Scope
### Must have
1. **两份页面同步重构回放 JS**：
   - `src/visualization/trajectory.py` 内嵌 HTML f-string（`_generate_html`，约 335–722 行）— 管线真源。
   - `frontend/pages/trajectory.html`（约 167–405 行 JS）— 实际打开的演示门户副本，独立 CSS/GSAP 主题保留不动，只动回放 JS 块。
   - 改后的回放 JS 逻辑两份必须一致（同一套算法；frontend 仅数据路径 `../data/trajectory_sample.json` 与样式/GSAP 不同）。
2. **渐进画线**：移除一次性 `buildPolyline(pts)`；改为随标记 movement 逐段追加到「已走折线」overlay。未走过的折线 **不绘制**。
3. **平滑插值移动**：`setInterval(step,80)` + `playRate`-跳点 → `requestAnimationFrame`。位置状态改为浮点 `(segStartIdx, segEndIdx, segFrac)` 三元组（替代整数 `curIdx` 语义；`curIdx` 仍保留作为「最近的 GPS 整点索引用于面板显示」）。
4. **标记旋转朝向**：标记图标从默认图钉换为 **自定义方向箭头 `BMap.Icon`**（否则旋转无意义，缺口 M8）；`setRotation(deg)` 接收**度**，`atan2(dLat, dLon*cos(latRad))` 返回弧度须 `*180/Math.PI` 转换（缺口 M1）。换车时 + seek 时都须重算朝向。
5. **断点跳切（gap=1）**：当 `pts[i][5]===1`，到 `pts[i]` 即 **结束** 当前已走折线段（保留已绘制部分在地图上不动，不删除），然后从 `pts[i+1]` 作为新「当前已走折线起点」起一条新的折线段。标记直接 `setPosition` 到 `pts[i]`（先用 `pts[i]` 到 `pts[i+1]` 的方向设朝向；若到段末才能进 gap，则用到达时刻的上一朝向），**不**在 gap 跨度内做插值/滑动（与现有「跳过 gap 段」视觉一致，缺口 M4/M10/M9 已闭合）。
6. **速度滑块即时生效**：保留 `1×–60×` label，默认 15。每帧从 `playRate` 读取倍率，乘以基准推进常数 `BASE_PROGRESS_PER_SEC`（见执行策略），实时生效无须段边界等待（缺口 M12/低）。
7. **进度条 seek 重建**：seek/跳转时调用 `rebuildTraveled(seekFloatPos)`：遍历从起点到 seek 点的所有 GPS 点，跨过 gap=1 边界时分割成多段，末段末点用插值浮点坐标；把已走折线重建为多条 `Polyline`（每 gap 之间一条）。标记 `setPosition` 到插值后的 seek 位置，朝向按 seek 点方向重算（缺口 M3/M5/M6）。
8. **`reset()` 清空渐进折线**：当前 reset 只移动标记；改后须 `clearOverlays` 重建仅包含起点（无已走折线），标记回起点不旋转或旋转为第一段方向（缺口 M11）。
9. **移除 `BMAP_ANIMATION_BOUNCE`**：随标记 60fps 平滑移动，弹跳冲突，删除该 setAnimation 调用（缺口 M12/M18）。
10. **`rawToggle` 与 `header dropdown change`**：触发前先 `cancelAnimationFrame(rafId)` 暂停当前 rAF，再 `clearOverlays`、重置进度、重新驶入新车辆/原始轨迹模式；保留上下客 markers 与原视觉风格（缺口 M10）。
11. **执行前安全检查点**：在改任何代码前先 `git add -A && git commit -m "chore: pre-trajectory-playback checkpoint" && git push`，把当前工作区状态推到 GitHub 远端作为回滚点（用户明确要求）。

### Must NOT have (guardrails, anti-slop, scope boundaries)
- **不动 Python 数据层**：不重算 `trajectory_sample.json`，不改 `_filter_trajectory_drift`、`_select_sample_vehicles`、`_stream_trajectories`、`_build_sample_json`、`main()` 的数据流，不改 `N_SAMPLES` / `MAX_POINTS_PER_VEHICLE` 等抽样常量。
- **不动 frontend 的 CSS 主题与 GSAP 动效**：只改 `frontend/pages/trajectory.html` 的 JS（约 167–405 行），CSS/HTML 结构、`animations.js`、`assets/` 一律不动。
- **不动 frontend/data/trajectory_sample.json**：复用现有抽样数据。
- **不碰其他三个交互页面**（od-flow / heatmap / congestion / stages/*）与本目录以外的脚本。
- **不引入新 JS 依赖**（不上 GSAP/anime 绘轨迹、不引 turf.js 做朝向）；只用百度地图 v3.0 + 原生 JS。
- **不新增 lint/format 工具**、不补 requirements、不补测试框架。
- **不做真实时间戳压缩回放语义**：速度滑块仍是视觉倍率，不映射到 GPS 时间戳→实时（这是用户显式弃用项）。
- **不在 gap=1 跨度内做直线/平滑插值穿过**（避免穿楼）。超长段（但非 gap=1）的线性插值失真 **记录为已知行为**，不做道路网络贴线（缺口 M19）。

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: **none**（项目无测试框架；不因本次单页前端改动新增测试基建）。代之以**HTML/JS 静态校验 + 逻辑走查 + 纯函数 node 临时单测**三重。
- 框架：无持续框架；纯函数（heading 计算、gap 边界分割、插值映射）可抽到项目根 `/tmp/opencode/trajectory_replay_test.mjs` 临时跑，**不**测试目录入仓。
- Evidence:
  - `.omo/evidence/task-1-trajectory-progressive-playback.git-push.txt` — `git log -1 --stat` + `git push` 输出确认远端已更新。
  - `.omo/evidence/task-4-trajectory-progressive-playback.01-syntax.txt` — `.venv/bin/python -c "import ast; ast.parse(open('src/visualization/trajectory.py').read())"` 确认 Python 语法；用 `node -e` 抽出 `_generate_html()` 生成 HTML 中 `<script>` 内的 JS 字符串再 `node --check` 确认 JS 语法（无解析可在 stderr 报错定位）。
  - `.omo/evidence/task-2-trajectory-progressive-playback.02-syntax.txt` — `node --check frontend/pages/trajectory.html` 不可行（HTML），改用：从 HTML 抽 `<script>` 块写入 `/tmp/opencode/fe_traj.js` 后 `node --check`。
  - `.omo/evidence/task-5-trajectory-progressive-playback.replay-logic.txt` — 逻辑走查表：列出 (a) 渐进画线状态机 (init→play→rAF loop→segment boundary→gap cut→seek→reset→rawToggle) 各分支应触发的 overlay/rAF/朝向动作 (b) heading/gap-cut/插值浮点公式手算。不接受「grep 命中函数名」作为完成证据（缺口 M16）。
- 终步用户目视：`.venv/bin/python src/visualization/trajectory.py --serve`（或 `python -m http.server 8080`）→ 浏览器打开 `http://localhost:8080/frontend/pages/trajectory.html` 选车点播放，目视确认：线渐进生长、标记箭头朝向行进方向移动、未走段不绘制、gap 处跳切、速度滑块即时变速、Seek 跳到定位重建已走线、RawToggle 切换正常、Reset 清空。**本步需要用户介入，不阻断 agent 完成**。
- 注：本环境**无浏览器自动化**（不安装 playwright/puppeteer），无法自动截图或 DOM 断言；agent 完成 = 静态/逻辑校验全通过，用户目视为后续验收而非 agent 阻塞门（缺口 M16/M20 已闭合）。

## Execution strategy
### 关键实现常数与算法（决策锁定，executor 必须遵循）
- **位置状态**：`posF = { seg: <int>, t: <float 0..1> }` 指当前在 `pts[seg] → pts[seg+1]` 插值中、行进了 t 比例。`playPos` = 当前车辆点数组（raw 或 filtered）。面板 `进度 N/M` 显示的整点 idx = `Math.min(seg + (t>=0.5?1:0), len-1)`。
- **基准推进速度常数**：`BASE_PROGRESS_PER_SEC = 1.2`（段/秒 @ 1×），即每秒走 1.2 个 GPS 段；60× → 72 段/秒。这使点数 ~200-1500 的轨迹在 1× 大致 3-20 分钟，60× 大致 3-20 秒。**executor 不得改此常数，先 run/校准后可写回计划附注**（缺口 M11 闭合）。每帧增量 `Δt = clamp(playRate * BASE_PROGRESS_PER_SEC * dt_sec, 0, 1)`；跨段时余量进下一段。
- **heading 公式**：`dy = (lat2-lat1)` (度)，`dx = (lon2-lon1)*cos(lat1*π/180)` (度，纬度缩放以防高纬失真)；`heading = atan2(dx, dy) * 180/π`（北=0、顺时针；按百度 `setRotation` 约定确认）。
- **自定义图标**：用 `BMap.Icon` 加载一张内联 SVG/PNG 方向箭头（base64 嵌入，避免外链资源），尺寸 ~28×28，箭头指北（rotation=0 时朝上）。两个 HTML 文件用同一 base64 字符串，避免分叉（缺口 M8）。
- **缺口 M2 `curIdx` 旧引用取代表**：旧 `step()`、`updateInfo()`、`reset()`、进度条 click 全部改读写 `posF`；`curIdx` 保留为只读派生量供面板显示。
- **缺口 M7 setPath 性能**：不在每帧 `setPath` 全数组；维护 `traveledPolys` 数组（每 gap 之间一条 Polyline），仅在 segment 边界 / 出 gap / seek 时 `setPath` 追加末点；帧内只 `marker.setPosition` + `setRotation`。性能 O(段数)，非 O(n²)。
- **缺口 M8/M3 seek**：`rebuildTraveled(posF)` 产出 `[{path:[Point...], color:...}, ...]`，每段一条 Polyline，渗入末点用末段终点插值坐标；旧 `traveledPolys` 全 `removeOverlay` 后重建。

### Parallel execution waves
> 单文件 + 一份独立副本；改动属「先在 frontend 改 iter、定稳后再镜像回生成器 f-string」。**Wave 1 单线性**（避免 f-string `{{}}` 转义双源并行错）。

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. git 安全检查点 | — | 2 | — |
| 2. frontend 回放重构 (含 herd/spin/gap/seek/reset/rawToggle) | 1 | 3, 4 | — |
| 3. 纯函数 node 测试 (heading/gap-cut/interp) | 2 | 4 | — |
| 4. 同步到生成器 f-string (含 JS 双源 diff 校验) | 2, 3 | 5 | — |
| 5. 终验 + 逻辑走查 + 双源行为一致性 + 用户目视 | 2, 4 | — | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

- [x] 1. git 安全检查点（执行前置）
  What to do:
  1. **先把 `.omo/evidence/` 与 `.omo/boulder.json` 加入 `.gitignore`**（当前 `.gitignore:31` 只忽略 `.omo/run-continuation/`）：在文件末追加两行 `.omo/evidence/` 与 `.omo/boulder.json`。这样 checkpoint commit 不会夹带会话证据 / 状态文件。
  2. 在项目根跑 `git status -s && git log --oneline -5`，确认无 .venv / data / output/figures 之外的大文件误入；若有意外 untracked 大文件（如 TaxiData.csv、vehicle_data.json、frontend/data/trajectory_sample.json 16MB），**不要 add 它们**（data/ 与 frontend/data 的策略下条）。
  3. **暂存策略：`git add -u`（仅暂存 tracked 改动，不暂存 untracked）**，然后用 `git add .gitignore .omo/plans/trajectory-progressive-playback.md` 主动加入本次计划文件（计划是 .omo/plans/ 不在 .gitignore，应入仓供团队回看）。**禁止 `git add -A`**——它会暂存任何乱入的 untracked 文件。验证暂存内容：`git diff --cached --stat` 输出应只含 .gitignore、.omo/plans/*.md、及既有 tracked 文件改动。
  4. 提交：`git commit -m "chore(checkpoint): 修改轨迹回放前的工作区快照"`。
  5. `git push origin HEAD`（或当前上游分支），把状态推上 GitHub。无 upstream 时降级 `git push -u origin $(git branch --show-current)`。
  Must NOT do: 不 force push、不 amend 历史、不创建 PR、不 rebase；只做一次 push 当回滚点。如果工作区干净无 modified 且无 untracked（除 .omo/evidence/.boulder.json 已写入 .gitignore 外），**仍需 commit 这次的 .gitignore+计划文件改动**作为 checkpoint，不能跳过 commit。
  Parallelization: Wave 1 | Blocked by: — | Blocks: 2, 3
  References: 用户原话「先把工作区推 Github 上面 然后在开始修改代码」；项目 .gitignore 与 AGENTS.md「commit 信息用中文、`<type>(<scope>): <subject>`」。
  Acceptance criteria (agent-executable):
  - 命令 `git rev-parse HEAD@{1}` 失败或 `git log --oneline -1` 显示本次 checkpoint 提交存在；`git status -s` 输出为空或仅 .omo/。
  - `git push` stderr 中含 "Everything up-to-date" 或远端已更新；用 `git rev-parse origin/$(git symbolic-ref --short HEAD) == git rev-parse HEAD` 确认远端 HEAD 与本地最新提交相等。
  QA: happy = 有改动→commit+push 成功，证据 `git log -1 --stat`+`git push` 拼接；failure = push 被拒（无 upstream），降级为 `git push -u origin $(git branch --show-current)`，证据记录。
  Evidence: `.omo/evidence/task-1-trajectory-progressive-playback.git-push.txt`
  Commit: N（1 本身就是 commit 行为，不另立 commit）

- [ ] 2. 在 `frontend/pages/trajectory.html` 重构回放 JS
  What to do / Must NOT do:
  - 改造 JS 范围：约 167–405 行（变量声明 `var TRAJ..`、`speedColor` 起、到 `initMap` 与尾部 API script）。**CSS（1-160 行）、HTML 结构、`animations.js` 引用 `DATA_FILE` 数据路径 `../data/trajectory_sample.json`（167 行）保持不变**——`DATA_FILE` 这条不要动，只动回放逻辑。
  - 移除一次性 `buildPolyline(pts)`（198-240 行）；新写 `appendTraveledSeg(fromIdx, toIdx, speedColor)` 追加段到 `traveledPolys[]`；维护 `posF = {seg, t}`。
  - 移除 `setInterval(step,80)`（298 行 `play()`）→ `requestAnimationFrame(loop)`；`cancelAnimationFrame` 暂停。
  - `markers`：用内嵌 base64 方向箭头 `BMap.Icon` 替换默认图钉；`setRotation(deg)`。
  - 移除 `BMAP_ANIMATION_BOUNCE`（249 行附近）。
  - `gap=1`（pts[i][5]===1）：到 `pts[i]` 终止当前 traveled poly、新起一条；不在跨段内插值。
  - 改 `updateInfo(idx)`（271-281）→ 基于 `posF` 计算；resetProgress/click-seek 全部走 `rebuildTraveled(posF)` + `cancelAnimationFrame`+重启 rAF。
  - `reset`（309-313）须 `clearOverlays`+重建仅起点。
  - `rawToggle`（373-377 的 input 监听）触发前先 `cancelAnimationFrame`。
  - 单点/零点轨迹守卫：`if (!playPos.length) return;` 已有 271 行，保留并补 `if (playPos.length<=1) {立标+ 不启 rAF; return}`。
  - 速度滑块 `input` 监听不变（即时倍率），只读 `playRate` 写入每帧增量公式。
  - 必须保留：`buildOrderMarkers`（211-240）整段不动；`speedColor`（169-186）不动；header `select` change、进度条 behavior 名义保留但内层换 `rebuildTraveled`。
  Must NOT do: 不动 `trajectory_sample.json` 数据结构（依赖点格式 `[time,lon,lat,status,speed,gap]`）；不上 GSAP 绘轨迹；不引外部 JS 库；不修任何 CSS。
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3, 4
  References:
  - frontend/pages/trajectory.html:1-160 (CSS 保持), :167-405 (JS 改造)
  - 数据格式 src/visualization/trajectory.py:151-158 (gap 推导), :313-326 (payload 结构)
  - 现有逻辑 frontend/pages/trajectory.html:198-240 (buildPolyline), :242-269 (renderVehicle), :271-281 (updateInfo), :288-296 (step), :298-303 (play setInterval)
  - BMap v3.0 API：`Marker.setIcon`/`setRotation`(度)、`Polyline.setPath(Array<Point>)`、`Map.removeOverlay`、`addEventListener`、`requestAnimationFrame`/`cancelAnimationFrame`
  Acceptance criteria (agent-executable):
  - 抽 HTML `<script>` 块入 `/tmp/opencode/fe_traj.js` 跑 `node --check` 退出 0、无 SyntaxError 输出。
  - 抽 ` DATA_FILE` 字符串仍为 `'../data/trajectory_sample.json'`（grep）。
  - grep `setInterval` 在改造后行 0 命中；grep `requestAnimationFrame` ≥ 1 命中；grep `BMAP_ANIMATION_BOUNCE` 0 命中；grep `setRotation` ≥ 2 命中；grep `appendTraveledSeg|traveledPolys` ≥ 1 命中。
  - 逻辑走查表 `evidence/...-02-syntax.txt` 中所有 (init/play/rAF loop/seg 边界/gap cut/seek/reset/rawToggle) 分支动作与代码一一对照无漏。
  QA: happy = `node --check` 通过 + grep 合规；failure = `node --check` 报 `Unexpected token` → 定位行号修复重校。
  Evidence: `.omo/evidence/task-2-trajectory-progressive-playback.02-syntax.txt`
  Commit: Y | `feat(trajectory): frontend 渐进式轨迹回放`

- [ ] 3. 纯函数 node 测试（验证行为而不靠浏览器）
  What to do / Must NOT do:
  - frontend 改造完成后、同步生成器前，写一份 `/tmp/opencode/trajectory_replay_test.mjs`（不入仓临时文件），将 frontend 页面中**关键纯函数**抽出来跑断言。要求被抽测的函数从 frontend/pages/trajectory.html 的 `<script>` 块里**手工复制**到测试文件中（不引 import，直接拷贝函数体到测试文件 top-level，再 in-source；测试文件不依赖浏览器全局，被测函数只允许用 Math 函数）。
  - 必测函数：
    (a) `headingDeg(lat1, lon1, lat2, lon2)` — 朝向计算，返回 0-360 度（北=0、顺时针）。断言：东方向两点 (22.55,114.05)→(22.55,114.06) 应返回 ≈90°；北方向 (22.55,114.05)→(22.56,114.05) 应返回 ≈0°；南应 ≈180°；西应 ≈270°。允许 ±1° 浮点误差。**此测试同时验证百度 setRotation 的「北=0、顺时针」约定是否被准确实现**——若断言失败，意味着公式或约定错了，必须回 frontend 修。
    (b) `segmentAndGapCut(pts)` ——输入点数组（每点 `[time,lon,lat,status,speed,gap]`），输出 `{segments: [[startIdx,endIdx],...], cuts: [gapIdx,...]}`：把 pts 按 `p[5]===1` 分段。断言：空数组→`{segments:[],cuts:[]}`；单点→`{segments:[[0,0]],cuts:[]}`；6 点中 `pts[3][5]=1`→`segments:[[0,2],[3,5]], cuts:[3]`；段末尾 gap→`segments:[[0,4]], cuts:[5], tail dropallowed`。每个断言失败必须修。
    (c) `interpolatePoint(p1, p2, t)` — 线性插值 lon/lat，返回 `[lon, lat]`。断言：t=0.5 中点精确等于平均。
  - 测试运行命令：`node /tmp/opencode/trajectory_replay_test.mjs`，要求退出码 0 且输出 `ALL PASS`，stderr 无 Trace。
  - 把测试文件 cat 内容 + 运行输出附入 evidence。
  Must NOT do: 不把测试文件入仓项目；不引 jest/mocha；不引任何 npm 包（仅用 node 内置 `assert`）；不引浏览器 BMap 全局，被测函数体内不得调用 BMap/fetch/DOM。
  Parallelization: Wave 1 | Blocked by: 2 | Blocks: 4
  References: 上一 Todo 2 改造的 frontend/pages/trajectory.html（从中抠出三个纯函数）；本项目无测试框架故放 /tmp/opencode。
  Acceptance criteria (agent-executable):
  - `/tmp/opencode/trajectory_replay_test.mjs` 文件存在（`test -f`）且 `node /tmp/opencode/trajectory_replay_test.mjs` 退出 0、stdout 含 `ALL PASS`、无 `AssertionError`。
  - 测试文件中的 `headingDeg` 函数体与 frontend/pages/trajectory.html 中的同名函数**字符一致**（用 `diff <(grep -A8 'function headingDeg' frontend/pages/trajectory.html) <(grep -A8 'function headingDeg' /tmp/opencode/trajectory_replay_test.mjs)` 输出空）——证明测试的是真代码不是临时代替品。
  - heading 四个方向断言全过；segment/gap 切割断言全过；插值断言全过。
  QA: happy = node 退出 0、ALL PASS；failure = AssertionError → 报具体 value mismatch，回 2 改函数体，再回 3 重测。
  Evidence: `.omo/evidence/task-3-trajectory-progressive-playback.pure-func.txt`（测试源 + node 输出）
  Commit: N（测试文件不入仓）

- [ ] 4. 同步到生成器 `src/visualization/trajectory.py` 的 `_generate_html` f-string
  What to do / Must NOT do:
  - 把 2 得到的 JS 逻辑逐行镜像进 `trajectory.py:335-722` 的 f-string，**所有 JS `{`、`}` 必须用 `{{`、`}}` 转义**（现有代码如 503 行 `function speedColor(s) {{` 是范例）。f-string 外层引号与 `SHENZHEN_CENTER[0]` 注入处保持原样。
  - `DATA_FILE` 改为从参数 `out_json_name` 注入（现状 501 行 `var DATA_FILE = '{out_json_name}';`），frontend 版本是常量 `../data/...`；两者差异仅这一行，不要先写死。
  - 自定义箭头图标的 base64 字符串两份必须字节相同；建议在生成器里把它定义为 Python 变量再注入 f-string，避免双份手抄导致漂移。
  - Python `main()`、`_select_sample_vehicles`、`_stream_trajectories`、`_build_sample_json`、`_serve_html`、`_filter_trajectory_drift` 一律不动。
  Must NOT do: 不动 Python 缩进规范以外的逻辑；不引入新 import；不改 N_SAMPLES/MAX_POINTS_PER_VEHICLE 等。
  Parallelization: Wave 1 (实质上 2 完成后再启动，但写为同 wave，由 dependency matrix 强约束顺序) | Blocked by: 2, 3 | Blocks: 5
  References:
  - src/visualization/trajectory.py:335-722 (整段 _generate_html f-string)
  - src/visualization/trajectory.py:501 (DATA_FILE 注入点), :703 (initMap 内 fetch)
  - f-string 转义范例：:503 (`{{`) 与 :504-518 (speedColor)
  Acceptance criteria (agent-executable):
  - `.venv/bin/python -c "import ast,sys; ast.parse(open('src/visualization/trajectory.py').read())"` exits 0。
  - `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from src.visualization.trajectory import _generate_html; html=_generate_html('x.json'); open('/tmp/opencode/gen_traj.html','w').write(html)"` 成功，文件大小 > 当前 ~1.2 MB 量级。
  - 抽出生成 HTML 中 `<script>` 部分 `node --check` 通过。
  - grep `"../data/trajectory_sample.json"` 在生成的 HTML 中 0 命中（必须是从 `x.json` 注入）；grep `var DATA_FILE = 'x.json'` 1 命中。
  - grep `\{{` 合规（无未转义单 `{`/`}` 在 JS 体内，由 node --check 间接保证）。
  QA: happy = ast.parse + generate + node --check 三步全过；failure = f-string 报 KeyError/ValueError 或 node --check 报错 → 修转义重校。
  Evidence: `.omo/evidence/task-4-trajectory-progressive-playback.01-syntax.txt` + `.02-generated-html.txt`
  Commit: Y | `feat(trajectory): 生成器同步渐进式回放`

- [ ] 5. 双源终验 + 逻辑走查 + 双源 JS 行为一致性 + 用户目视
  What to do / Must NOT do:
  - 复跑 2/4 的 static 校验确认无回归。
  - **双源行为一致性 diff 校验**：从 `frontend/pages/trajectory.html` 与生成器产物 `/tmp/opencode/gen_traj.html` 各自抽出 `<script>` 块的中段（剔除 `DATA_FILE` 那一行与 `SHENZHEN_CENTER` 注入的常量），用 `diff` 比对——两源的 JS 主体必须**逐字一致**（DATA_FILE 那行允许差异；SHENZHEN_CENTER 注入数值允许差异；其它完全相等）。产出 `task-5-...js-diff.txt` 包含两边的 `awk '/^var DATA_FILE|^var SHENZHEN|var DATA_FILE/{next} 1'` 过滤后的 diff 输出。diff 非空 → 必须回 4 修生成器至与 frontend 一致。
  - 写 `.omo/evidence/task-5-trajectory-progressive-playback.replay-logic.txt` 逻辑走查表，覆盖：渐进画线状态机（init/play/loop/seg boundary/gap/seek/reset/rawToggle），heading 公式手算样例（取一对相邻点验算 atan2(dx*cos, dy)*180/π），gap cut 行为（取一个真实含 gap=1 的车辆验算多段分割）。
  - 提示用户启动 `python -m http.server 8080`（或 `--serve`）后浏览器打开 `http://localhost:8080/frontend/pages/trajectory.html` 目视确认（用户介入，非阻塞 agent 完成）。
  Must NOT do: agent 不安装 playwright/puppeteer，不自动截图；不修改 roadmap/demo.html 或 frontend/index.html；不做 f-string `{{}}→{}` 的 reverse-transpile 提示 diff 噪声——两源脚本在各自最终形态做比对（frontend 是直接 JS、生成器产出的是 HTML 中已 expand 的 JS），二者可直接 diff。
  Parallelization: Wave 2 (final) | Blocked by: 2, 4 | Blocks: —
  References: 见 2/4 + 用户原话「我在浏览器打开的是 frontend」；frontend/README.md 访问方式 `python -m http.server 8080` + `http://localhost:8080/frontend/index.html`。
  Acceptance criteria (agent-executable):
  - 2/4 static + grep 校验全过，无新增 untracked 大文件。
  - JS diff 输出仅含 `DATA_FILE` 与 `SHENZHEN_CENTER` 那两行，其它全相同（`diff ... | wc -l` 必须为 0，或者 diff 仅含被 awk 过滤应剔除的两行的 `<`, `>` 记录）。
  - 逻辑走查表完整覆盖 9 个分支 × 预期动作 × 实际代码行号引用，无「未对应」空白。
  - F-wave F1-F4 已各自有独立明确定义（见本计划 Final verification wave 节），本步只汇总 4 项证据文件路径，不代理执行 F。
  QA: happy = 走查表与代码完全对应、JS diff 仅显 DATA_FILE/SHENZHEN_CENTER 差异；failure = diff 出现其它差异 → 回 4 修生成器重做 5。
  Evidence: `.omo/evidence/task-5-trajectory-progressive-playback.replay-logic.txt` + `.omo/evidence/task-5-trajectory-progressive-playback.js-diff.txt` + 用户目视反馈（口头）
  Commit: N（仅 evidence，不进产品代码）

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
  - 内容：遍历本计划 Scope "Must have" 与 Must NOT have，逐条列 `Met | NOT Met | NA`；每条 Met 须给出对应 Todo/evidence 路径。
  - 引用：本计划 Scope 节。
  - 通过：Must have 全 Met、Must NOT have 全 Met（即未违逆）或 NA。
  - 证据：`.omo/evidence/f1-trajectory-progressive-playback.plan-compliance.md`
- [ ] F2. Code quality review
  - 内容：审查 frontend 改造后的 167-405 行 JS + 生成器 f-string 335-722 行的代码质量——具体点：(a) 无未删的 setInterval/setTimeout 死代码、无未取消的 rAF 泄漏、(b) 单一 rAF 入口（rafId 唯一）、所有重启路径先 cancelAnimationFrame、(c) heading 公式无未保护 NaN（lat1==lat2 且 lon1==lon2 时 headingDeg 应返回 0 而非 NaN）、(d) base64 箭头字符串在两源 byte-equal、(e) gap=1 路径未把已绘 poly 错误删除而是断开起新。
  - 引用：Todo 2/4 代码产物。
  - 通过：5 个检查点全 PASS；任何 NOT PASS 必须 spawn 新 Todo 修后重做 F2。
  - 证据：`.omo/evidence/f2-trajectory-progressive-playback.code-quality.md`
- [ ] F3. Real manual QA
  - 内容：用户目视确认项（用户实际介入，agent 不能替用户完成）：(i) 选车→箭头标记从起点向行进方向开始旋转移动；(ii) 已画折线随标记推进逐步延伸，未走过段不出现；(iii) gap=1 处不画跨断直线、标记瞬移到下一段起点继续推进；(iv) 速度滑块拖动即时变速，不停顿；(v) Reset 后折线清空、标记回起点；(vi) 进度条点击 seek 跳转后已走折线被正确重建到该位置；(vii) 显示原始轨迹 toggle 切换正常且不残留旧叠加标记；(viii) 切换另一辆车不残留前一车辆叠加。
  - 引用：frontend/README.md 访问方式 `python -m http.server 8080` + `http://localhost:8080/frontend/pages/trajectory.html`。
  - 通过：8 项目视反馈全 OK；任一 FAIL → spawn 修 Todo，重做 F3。
  - 证据：`.omo/evidence/f3-trajectory-progressive-playback.manual-qa.md`（agent 收集用户口头反馈并记录）；**此步用户介入不阻断 agent 完成 F1/F2/F4**。
- [ ] F4. Scope fidelity
  - 内容：核对未越界——未触碰以下文件：data/*、taxiData.csv、output/figures/trajectory_sample.json（不应被 reacreate）、frontend/assets/*、frontend/index.html、roadmap/*、src/pipeline/*、src/config.py、src/utils.py、除 trajectory.py 外其它 visualization 子模块。`git diff --stat origin/HEAD..HEAD` 仅应含 `.gitignore` + `frontend/pages/trajectory.html` + `src/visualization/trajectory.py` + `.omo/plans/trajectory-progressive-playback.md` + 任何 frontend 已 tracked 改动。
  - 引用：本计划 Must NOT have 节。
  - 通过：`git diff --stat --name-only` 输出**严格**等于上述白名单（若 frontend/data/trajectory_sample.json 已入仓则不在本次 commit 范围）。
  - 证据：`.omo/evidence/f4-trajectory-progressive-playback.scope-fidelity.md` 含 `git diff --name-only` 完整输出。

## Commit strategy
- **Todo 1** 本身是 commit 行为（先改 .gitignore + git add -u + git add .gitignore & 计划文件 + commit + push），是第一个 commit，不另立产品 commit。
- **Todo 2 (frontend 重构)** → 单次 commit：`feat(trajectory): frontend 渐进式轨迹回放`。
- **Todo 3 (纯函数测试)** 不入仓（测试文件在 /tmp/opencode/），不 commit。
- **Todo 4 (生成器同步)** → 单次 commit：`feat(trajectory): 生成器同步渐进式回放`。**不与 2 合并**：两个文件改动分开提交，便于 git revert 单文件。
- **Todo 5 + F-wave** 证据文件 `.omo/evidence/*.md` 已加入 `.gitignore`（Todo 1 已写），不入仓；不 commit。
- 总共 3 次 product code commit：Todo 1 (.gitignore + 计划)、Todo 2 (frontend)、Todo 4 (生成器)。
- 提交信息中文，遵循 `<type>(<scope>): <subject>` 规范（AGENTS.md 全局规则）。**不 amend、不 force push、不开 PR**（仅当用户后续显式要求时另论）。

## Success criteria
**全部满足才算完成**：
1. 两条文件改动同时落地，行为一致（同一套回放 JS）：
   - `frontend/pages/trajectory.html` 的 JS 167-405 行已重构（Todo 2）；
   - `src/visualization/trajectory.py` 的 `_generate_html` f-string 已同步（Todo 4），且两源 JS 主体 diff 仅 DATA_FILE/SHENZHEN_CENTER 行差异（Todo 5 diff 校验通过）。
2. 状态机正确：选车→渐进生长折线、箭头标记旋转朝行进方向、60fps 平滑插值移动、未走段不绘制、gap=1 处跳切不画断点直线、reset 清空、seek 重建已走线、rawToggle 取消 rAF 后重建、速度滑块即时变速。
3. 静态校验全过：Python `ast.parse`、生成器 `_generate_html` 可运行、抽出两份 JS `node --check` 退出 0；grep 校验 `setInterval`=0 / `requestAnimationFrame`≥1 / `BMAP_ANIMATION_BOUNCE`=0 / `setRotation`≥2 / `../data/trajectory_sample.json` 仅 frontend 命中（生成器注入值）。
4. **纯函数 node 测试全过**（Todo 3）：`/tmp/opencode/trajectory_replay_test.mjs` 退出 0 且输出 `ALL PASS`——headingDeg 四方向 + segmentAndGapCut 边界 + interpolatePoint 三组断言。
5. 逻辑走查表 (`task-5-*-replay-logic.txt`) 9 分支 × 预期动作 × 代码行号引用全部对齐，无空白。
6. git 安全检查点 (Todo 1) 已 push 到 GitHub 远端，作为回滚点；`.omo/evidence/`、`.omo/boulder.json` 已写入 `.gitignore`，checkpoint commit 仅含 .gitignore + .omo/plans/* + 其它 tracked 改动，无乱入 untracked 大文件。
7. F-wave F1-F4 全 APPROVE；用户目视确认 8 项行为（F3）。
8. **已知行为记录**（非阻塞）：超长但非 gap=1 的相邻 GPS 点线性插值可能穿越建筑物；记录在 `task-5-*-replay-logic.txt` 中，不视为缺陷。
