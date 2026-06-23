#!/usr/bin/env python3
"""深圳出租车上客点交互热力图 — 基于百度地图 JavaScript API + HeatmapOverlay

读取 orders.csv 的上客点(开始经度/开始纬度/开始时间) → 按小时分桶 +
~100m 网格聚合计数 → 生成 standalone HTML，含时间滑块(0-23h)、
热力图层、图例、信息面板、导航/比例控件。

运行:
    python src/09_交互热力图.py                  # 仅生成 HTML
    python src/09_交互热力图.py --serve          # 生成 + 启动 HTTP 服务器
    python src/09_交互热力图.py --serve --port 8000
"""

import argparse
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import BAIDU_MAP_API_KEY, DATA_DIR, FIGURES_DIR, SHENZHEN_BOUNDS
from src.utils import assert_input_exists


# ── 常量 ────────────────────────────────────────────────────────────────────
CENTER_LAT = 22.55
CENTER_LON = 114.06
ZOOM = 12

# ~100m 网格聚合（深圳纬度下 0.001° ≈ 111m）
HEAT_GRID = 0.001
# 每小时最大点数（避免单小时网格过多撑爆 HTML）
MAX_POINTS_PER_HOUR = 20000


def _load_pickups() -> pd.DataFrame:
    """读取上客点，提取小时，过滤越界点。"""
    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(orders_path)

    print('读取 OD 数据 ...')
    usecols = ['开始经度', '开始纬度', '开始时间']
    df = pd.read_csv(orders_path, usecols=usecols)
    print(f'  行数: {len(df):,}')

    # 解析时间 → 提取小时
    df['开始时间'] = pd.to_datetime(df['开始时间'], errors='coerce')
    df = df.dropna(subset=['开始时间'])
    df['hour'] = df['开始时间'].dt.hour

    # 越界过滤（深圳范围）
    b = SHENZHEN_BOUNDS
    mask = (
        df['开始经度'].between(b['long_min'], b['long_max'])
        & df['开始纬度'].between(b['lat_min'], b['lat_max'])
        & df['hour'].between(0, 23)
    )
    before = len(df)
    df = df[mask].copy()
    print(f'  越界/异常剔除: {before - len(df):,}')
    print(f'  有效上客点: {len(df):,}')
    return df[['开始经度', '开始纬度', 'hour']]


def _aggregate_hour_grid(df: pd.DataFrame) -> dict:
    """按 hour + ~100m 网格聚合，输出 {hour: [[lng, lat, count], ...]}。"""
    print('按小时 + 网格聚合上客点 ...')
    df = df.copy()
    df['g_lon'] = (df['开始经度'] / HEAT_GRID).round().astype('int32') * HEAT_GRID
    df['g_lat'] = (df['开始纬度'] / HEAT_GRID).round().astype('int32') * HEAT_GRID

    agg = (
        df.groupby(['hour', 'g_lon', 'g_lat'])
        .size()
        .reset_index(name='count')
        .sort_values('count', ascending=False)
    )

    hourly: dict[int, list] = {}
    global_max = 0
    total_cells = 0
    for h in range(24):
        sub = agg[agg['hour'] == h].head(MAX_POINTS_PER_HOUR)
        cells = [
            [round(float(r['g_lon']), 4), round(float(r['g_lat']), 4), int(r['count'])]
            for _, r in sub.iterrows()
        ]
        hourly[h] = cells
        if len(sub) > 0:
            global_max = max(global_max, int(sub['count'].max()))
        total_cells += len(cells)

    print(f'  网格单元总数: {total_cells:,}')
    print(f'  单格最大计数: {global_max:,}')
    return {'hours': hourly, 'max': global_max, 'total': total_cells}


def _build_hour_json(payload: dict) -> str:
    """紧凑 JSON：{0:[[lng,lat,c],...], 1:[...], ...}"""
    return json.dumps(
        payload['hours'],
        separators=(',', ':'),
        ensure_ascii=False,
    )


def _generate_html(payload: dict) -> str:
    hours_json = _build_hour_json(payload)
    global_max = payload['max']

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>深圳出租车上客点热力图</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body,#map {{ width:100%; height:100%; overflow:hidden; }}
  body {{ font-family:"Microsoft YaHei",sans-serif; }}
  #title {{
    position:absolute; top:20px; left:50%; z-index:100;
    transform:translateX(-50%);
    background:rgba(255,255,255,.92); padding:10px 28px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:700 18px/1.4 "Microsoft YaHei",sans-serif;
    pointer-events:none; white-space:nowrap;
  }}
  #panel {{
    position:absolute; bottom:40px; left:30px; z-index:100;
    background:rgba(255,255,255,.92); padding:14px 18px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:13px/1.7 "Microsoft YaHei",sans-serif;
    min-width:240px;
  }}
  #panel h4 {{ font-size:14px; margin-bottom:6px; }}
  #hour-display {{ font-size:22px; font-weight:700; color:#DC143C; }}
  #count-display {{ font-size:14px; color:#333; }}
  #slider {{
    width:230px; margin:8px 0 4px; cursor:pointer;
    accent-color:#DC143C;
  }}
  #legend {{
    position:absolute; bottom:40px; right:30px; z-index:100;
    background:rgba(255,255,255,.92); padding:14px 18px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:13px/1.7 "Microsoft YaHei",sans-serif;
  }}
  #legend h4 {{ margin-bottom:6px; font-size:14px; }}
  #legend .scale {{
    width:160px; height:12px; border-radius:6px;
    background:linear-gradient(to right,
      rgb(50,80,200), rgb(0,255,0), rgb(255,255,0),
      rgb(255,140,0), rgb(255,0,0));
    margin:6px 0 4px;
  }}
  .leg-labels {{ display:flex; justify-content:space-between;
    font-size:11px; color:#666; }}
  #play-toggle {{
    margin-top:6px; padding:4px 12px; cursor:pointer;
    background:#DC143C; color:#fff; border:none;
    border-radius:4px; font:12px/1.6 "Microsoft YaHei",sans-serif;
  }}
  #play-toggle:hover {{ background:#B01030; }}
  #info-toast {{
    position:absolute; top:70px; right:30px; z-index:100;
    background:rgba(255,255,255,.92); padding:8px 14px;
    border-radius:6px; box-shadow:0 1px 6px rgba(0,0,0,.12);
    font:12px/1.5 "Microsoft YaHei",sans-serif;
    display:none; max-width:280px;
  }}
  #heatCanvas {{
    position:absolute; top:0; left:0; z-index:50; pointer-events:none;
  }}
</style>
</head>
<body>
<div id="map"></div>
<div id="title">深圳出租车上客点热力图</div>

<div id="panel">
  <h4>时间控制</h4>
  <div>当前时段: <span id="hour-display">0</span>:00 — <span id="hour-end">0</span>:59</div>
  <input type="range" id="slider" min="0" max="23" value="0" step="1">
  <div>上客点网格数: <span id="count-display">0</span></div>
  <button id="play-toggle">▶ 自动播放</button>
</div>

<div id="legend">
  <h4>热力强度</h4>
  <div class="scale"></div>
  <div class="leg-labels">
    <span>低</span><span>中</span><span>高</span>
  </div>
  <div style="margin-top:6px;font-size:11px;color:#666;">
    网格 {HEAT_GRID:.3f}° (~{HEAT_GRID*111000:.0f}m)
  </div>
</div>

<div id="info-toast"></div>

<script>
var heatData = {hours_json};
var globalMax = {global_max};

var map = null;
var heatCtx = null;
var playTimer = null;
var currentHour = 0;

function initMap() {{
  map = new BMap.Map('map');
  var ctr = new BMap.Point({CENTER_LON}, {CENTER_LAT});
  map.centerAndZoom(ctr, {ZOOM});
  map.enableScrollWheelZoom(true);
  map.addControl(new BMap.NavigationControl());
  map.addControl(new BMap.ScaleControl());
  map.addControl(new BMap.MapTypeControl());

  // 热力 Canvas
  var canvas = document.getElementById('heatCanvas');
  heatCtx = canvas.getContext('2d');

  // 点击地图显示坐标信息
  map.addEventListener('click', function(e) {{
    var p = e.point;
    var toast = document.getElementById('info-toast');
    toast.style.display = 'block';
    toast.innerHTML =
      '坐标: ' + p.lng.toFixed(5) + ', ' + p.lat.toFixed(5) +
      '<br>当前时段: ' + currentHour + ':00 — ' + currentHour + ':59' +
      '<br>该时段上客网格: ' + (heatData[currentHour] ? heatData[currentHour].length : 0);
    clearTimeout(toast._t);
    toast._t = setTimeout(function() {{ toast.style.display = 'none'; }}, 3000);
  }});

  // 地图移动/缩放时重绘
  map.addEventListener('moveend', redrawHeat);
  map.addEventListener('zoomend', function() {{ resizeCanvas(); redrawHeat(); }});
  map.addEventListener('resize', function() {{ resizeCanvas(); redrawHeat(); }});

  resizeCanvas();
  updateHour(0);
}}

function resizeCanvas() {{
  var s = map.getSize();
  var c = document.getElementById('heatCanvas');
  c.width = s.width;
  c.height = s.height;
  c.style.width = s.width + 'px';
  c.style.height = s.height + 'px';
}}

function getColor(c) {{
  // 基于 globalMax 的归一化值 -> 蓝(0,0,255) → 绿(0,255,0) → 黄(255,255,0) → 红(255,0,0)
  var t = Math.min(1, c / globalMax);
  var r, g, b;
  if (t < 0.33) {{
    var s = t / 0.33;
    r = Math.round(0 + s * 0);
    g = Math.round(0 + s * 255);
    b = Math.round(255 + s * (0 - 255));
  }} else if (t < 0.66) {{
    var s = (t - 0.33) / 0.33;
    r = Math.round(0 + s * 255);
    g = Math.round(255 + s * (255 - 255));
    b = Math.round(0 + s * (0 - 0));
  }} else {{
    var s = (t - 0.66) / 0.34;
    r = Math.round(255 + s * (255 - 255));
    g = Math.round(255 + s * (0 - 255));
    b = Math.round(0 + s * (0 - 0));
  }}
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}}

function redrawHeat() {{
  if (!heatCtx || !map) return;
  var rows = heatData[currentHour] || [];
  var s = map.getSize();
  if (!s) return;
  heatCtx.clearRect(0, 0, s.width, s.height);
  if (!rows.length) return;

  var rad = 22;
  // 先画大半径低透明度底色
  for (var pass = 0; pass < 3; pass++) {{
    var r = [rad * 1.5, rad, rad * 0.4][pass];
    for (var i = 0; i < rows.length; i++) {{
      var d = rows[i];
      var alpha = Math.min(0.8, (d[2] / globalMax) * 2.5) * [0.12, 0.25, 0.55][pass];
      if (alpha < 0.02) continue;
      var px = map.pointToPixel(new BMap.Point(d[0], d[1]));
      heatCtx.fillStyle = getColor(d[2]);
      heatCtx.globalAlpha = alpha;
      heatCtx.beginPath();
      heatCtx.arc(px.x, px.y, r, 0, Math.PI * 2);
      heatCtx.fill();
    }}
  }}
  heatCtx.globalAlpha = 1;
}}

function updateHour(h) {{
  currentHour = h;
  document.getElementById('slider').value = h;
  document.getElementById('hour-display').textContent = h;
  document.getElementById('hour-end').textContent = h;
  var rows = heatData[h] || [];
  document.getElementById('count-display').textContent = rows.length;
  redrawHeat();
}}

document.getElementById('slider').addEventListener('input', function(e) {{
  stopPlay();
  updateHour(parseInt(e.target.value, 10));
}});

document.getElementById('play-toggle').addEventListener('click', function() {{
  playTimer ? stopPlay() : startPlay();
}});

function startPlay() {{
  var btn = document.getElementById('play-toggle');
  btn.textContent = '■ 停止播放';
  playTimer = setInterval(function() {{
    updateHour((currentHour + 1) % 24);
  }}, 1200);
}}

function stopPlay() {{
  if (playTimer) {{
    clearInterval(playTimer);
    playTimer = null;
    document.getElementById('play-toggle').textContent = '▶ 自动播放';
  }}
}}
</script>
<script src="https://api.map.baidu.com/api?v=3.0&ak={BAIDU_MAP_API_KEY}&callback=initMap"></script>
</body>
</html>'''


def _serve_html(out_path: str, port: int = 8080) -> None:
    serve_dir = str(Path(out_path).parent)
    os.chdir(serve_dir)

    host = '0.0.0.0'
    filename = Path(out_path).name
    url = f'http://localhost:{port}/{filename}'

    print(f'\n启动 HTTP 服务器: {serve_dir}')
    print(f'   浏览器打开:')
    print(f'   ┌────────────────────────────────────────────────────┐')
    print(f'   │  {url}  │')
    print(f'   └────────────────────────────────────────────────────┘')
    print()
    print('   如果地图不显示:')
    print('   1. 确认 AK 的 Referer 白名单包含 http://localhost:8080')
    print('   2. 或暂时在 Referer 白名单填 *')
    print('   3. 关闭广告拦截器后刷新')
    print()
    print('   按 Ctrl+C 停止服务器')
    print()

    server = HTTPServer((host, port), SimpleHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n服务器已停止')
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description='生成百度地图交互热力图')
    parser.add_argument('--serve', action='store_true',
                        help='生成后启动 HTTP 服务器')
    parser.add_argument('--port', type=int, default=8080,
                        help='HTTP 服务器端口（默认 8080）')
    args = parser.parse_args()

    df = _load_pickups()
    payload = _aggregate_hour_grid(df)

    html = _generate_html(payload)

    os.makedirs(FIGURES_DIR, exist_ok=True)
    out_path = os.path.join(FIGURES_DIR, 'interactive_heatmap.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n已保存: {out_path}')

    if args.serve:
        _serve_html(out_path, port=args.port)
    else:
        print()
        print('提示: 不能直接双击打开，请使用:')
        print(f'   python src/09_交互热力图.py --serve')
        print(f'   然后打开 http://localhost:8080/interactive_heatmap.html')


if __name__ == '__main__':
    main()