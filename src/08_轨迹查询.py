#!/usr/bin/env python3
"""出租车轨迹查询 — 百度地图交互式轨迹回放查看器

从 2.6 GB 的 vehicle_data.json 流式抽取 ~100 辆代表性车辆的轨迹，
搭配 orders.csv 的上下客点，生成 trajectory_sample.json 数据文件与
trajectory_viewer.html（百度地图 JS API v3.0）：速度渐变折线、回放动画、
上下客标记、实时信息面板。

用法::

    python src/08_轨迹查询.py            # 生成数据 + HTML
    python src/08_轨迹查询.py --serve    # 生成后启动 HTTP 服务器
    然后浏览器打开 http://localhost:8080/trajectory_viewer.html
"""

import argparse
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import BAIDU_MAP_API_KEY, DATA_DIR, FIGURES_DIR
from src.utils import assert_input_exists


# ── 采样参数 ────────────────────────────────────────────────────────────────
N_SAMPLES = 100                 # 选取的车辆数
MAX_POINTS_PER_VEHICLE = 1500   # 单车轨迹点上限（超出则均匀降采样）
SHENZHEN_CENTER = (114.05, 22.55)  # 经度, 纬度


# ── 车辆选取 ────────────────────────────────────────────────────────────────
def _select_sample_vehicles(vehicles_path: str, orders_path: str,
                           n: int = N_SAMPLES) -> tuple[list[int], dict]:
    """分层抽样选取代表性车辆：兼顾轨迹长 / 短、订单多 / 少。

    Returns
    -------
    vids : list[int]                — 选中的车辆 ID（按升序）
    order_index : dict              — {vid: [{type,time,lon,lat}, ...]} 上下客事件
    """
    print('读取车辆元数据 ...')
    with open(vehicles_path, encoding='utf-8') as f:
        vmeta = json.load(f)
    # vmeta: {vid_str: [point_count, offset, 'vehicle_data.json']}
    print(f'  车辆总数: {len(vmeta):,}')

    print('读取订单数据 ...')
    odf = pd.read_csv(orders_path)
    odf['开始时间'] = pd.to_datetime(odf['开始时间'])
    odf['结束时间'] = pd.to_datetime(odf['结束时间'])
    print(f'  订单总数: {len(odf):,}')

    # 每辆车的订单数与上下客事件
    order_count = odf.groupby('车辆id').size()

    # 构建候选车辆表：同时拥有轨迹与订单
    rows = []
    for vid_str, meta in vmeta.items():
        vid = int(vid_str)
        point_count = meta[0]
        oc = int(order_count.get(vid, 0))
        rows.append({'vid': vid, 'point_count': point_count, 'order_count': oc})
    cand = pd.DataFrame(rows)
    # 剔除没有任何订单的车辆（无法展示上下客点）
    cand = cand[cand['order_count'] > 0].reset_index(drop=True)
    print(f'  有订单的候选车辆: {len(cand):,}')

    # ── 分层抽样：按轨迹点数排序后均分 n 个分位桶，每桶取订单最多者 ──
    cand = cand.sort_values('point_count').reset_index(drop=True)
    n = min(n, len(cand))
    picks = []
    step = len(cand) / n
    for i in range(n):
        lo = int(round(i * step))
        hi = int(round((i + 1) * step))
        bucket = cand.iloc[lo:hi]
        # 桶内挑订单数最多（"出行丰富"），平手时取轨迹最长
        best = bucket.sort_values(
            ['order_count', 'point_count'], ascending=False
        ).iloc[0]
        picks.append(int(best['vid']))

    picks = sorted(set(picks))
    print(f'  选中车辆数: {len(picks)}')
    print(f'    轨迹点数范围: {cand.loc[cand.vid.isin(picks), "point_count"].min()}'
          f' ~ {cand.loc[cand.vid.isin(picks), "point_count"].max()}')
    print(f'    订单数范围: {cand.loc[cand.vid.isin(picks), "order_count"].min()}'
          f' ~ {cand.loc[cand.vid.isin(picks), "order_count"].max()}')

    # ── 构建上下客事件索引 ──
    order_index: dict = {}
    sub = odf[odf['车辆id'].isin(picks)]
    for vid, g in sub.groupby('车辆id'):
        events = []
        for _, r in g.iterrows():
            events.append({
                'type': 'pickup',
                'time': r['开始时间'].strftime('%Y-%m-%d %H:%M:%S'),
                'lon': float(r['开始经度']),
                'lat': float(r['开始纬度']),
            })
            events.append({
                'type': 'dropoff',
                'time': r['结束时间'].strftime('%Y-%m-%d %H:%M:%S'),
                'lon': float(r['结束经度']),
                'lat': float(r['结束纬度']),
            })
        # 按时间排序，便于回放时同步显示
        events.sort(key=lambda e: e['time'])
        order_index[int(vid)] = events

    return picks, order_index


# ── 流式轨迹抽取 ────────────────────────────────────────────────────────────
def _stream_trajectories(vd_path: str, target_vids: list[int],
                         max_points: int = MAX_POINTS_PER_VEHICLE
                         ) -> dict[int, list]:
    """从 2.6 GB vehicle_data.json 流式抽取目标车辆轨迹，不整体加载。

    vehicle_data.json 形如::

        {
        "22223": [[time,lon,lat,status,speed], ...],
        "22224": [...],
        ...
        }

    每辆车占一行（json.dumps 默认无换行），故可逐行扫描，仅对目标行做
    json 解析。
    """
    targets = {str(v) for v in target_vids}
    found: dict[int, list] = {}
    print('流式扫描 vehicle_data.json ...')
    with open(vd_path, encoding='utf-8') as f:
        for line_no, line in enumerate(f):
            s = line[0]
            if s != '"':  # 跳过首行 '{' 与末行 '}'
                continue
            # 提取键（"vid"）
            try:
                key_end = line.index('"', 1)
            except ValueError:
                continue
            vid = line[1:key_end]
            if vid not in targets:
                continue
            # 整行包裹成单键 JSON 对象解析
            obj = json.loads('{' + line.rstrip().rstrip(',') + '}')
            traj = obj[vid]
            # 均匀降采样
            if len(traj) > max_points:
                idx = [round(i * (len(traj) - 1) / (max_points - 1))
                       for i in range(max_points)]
                traj = [traj[i] for i in idx]
            found[int(vid)] = traj
            if (len(found)) % 20 == 0:
                print(f'  已找到 {len(found)}/{len(targets)} 辆车')
            if len(found) == len(targets):
                break
    print(f'  命中 {len(found)}/{len(targets)} 辆车的目标轨迹')
    return found


# ── 数据文件生成 ────────────────────────────────────────────────────────────
def _build_sample_json(vids: list[int], traj_map: dict,
                       order_index: dict, out_path: str) -> None:
    vehicles = []
    for vid in vids:
        pts = traj_map.get(vid, [])
        if not pts:
            continue
        points = [
            [p[0], round(float(p[1]), 6), round(float(p[2]), 6),
             int(p[3]), int(p[4])]
            for p in pts
        ]
        vehicles.append({
            'id': vid,
            'points': points,
            'orders': order_index.get(vid, []),
        })
    payload = {'vehicles': vehicles}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    size = os.path.getsize(out_path)
    print(f'  {out_path} ({size / 1024 / 1024:.2f} MB, {len(vehicles)} 辆车)')


# ── HTML 生成 ───────────────────────────────────────────────────────────────
def _generate_html(out_json_name: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>出租车轨迹查询 · 深圳出租车GPS</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body,#map {{ width:100%; height:100%; overflow:hidden; }}
  body {{ font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}

  #header {{
    position:absolute; top:0; left:0; right:0; z-index:200;
    height:64px; display:flex; align-items:center; gap:14px;
    padding:0 22px;
    background:linear-gradient(90deg,#0f1830 0%,#1b2a57 100%);
    box-shadow:0 2px 16px rgba(0,0,0,.35);
  }}
  #header h1 {{
    font-size:18px; font-weight:700; letter-spacing:2px; color:#eaf0ff;
    white-space:nowrap;
  }}
  #header h1 .sub {{
    font-size:11px; font-weight:400; letter-spacing:0; color:#8fa3d8;
    display:block; margin-top:2px;
  }}
  #header select {{
    margin-left:auto; min-width:230px; height:36px; padding:0 12px;
    border:1px solid #3a4d83; border-radius:6px; background:#0a1124;
    color:#eaf0ff; font:13px/1 "Microsoft YaHei",sans-serif; cursor:pointer;
  }}
  #header select:focus {{ outline:none; border-color:#4d8cff; }}

  #panel {{
    position:absolute; top:64px; left:0; z-index:150;
    width:300px; max-height:calc(100% - 64px); overflow-y:auto;
    padding:18px 18px 22px;
    background:rgba(10,17,36,.94); color:#cdd8f5;
    box-shadow:2px 0 18px rgba(0,0,0,.3);
  }}
  #panel h3 {{
    font-size:13px; font-weight:700; letter-spacing:1px; color:#7e92d6;
    margin-bottom:10px; text-transform:uppercase;
  }}
  .stat {{ font-size:13px; line-height:1.9; }}
  .stat .k {{ color:#8290c4; display:inline-block; width:62px; }}
  .stat .v {{ color:#eaf0ff; font-weight:700; font-variant-numeric:tabular-nums; }}
  .stat .badge {{
    display:inline-block; padding:1px 8px; border-radius:10px;
    font-size:11px; font-weight:700;
  }}
  .badge.occupied {{ background:#1f7a3a; color:#d8ffe6; }}
  .badge.empty {{ background:#5a3a3a; color:#ffd8d8; }}

  #ctrl {{ display:flex; gap:8px; margin:14px 0 6px; flex-wrap:wrap; }}
  #ctrl button {{
    flex:1; min-width:64px; height:36px; border:none; border-radius:6px;
    font:13px/1 "Microsoft YaHei",sans-serif; cursor:pointer;
    background:#2752c9; color:#fff; transition:background .15s;
  }}
  #ctrl button:hover {{ background:#3a66e0; }}
  #ctrl button.secondary {{ background:#2a3559; }}
  #ctrl button.secondary:hover {{ background:#3a4a78; }}
  #ctrl button:disabled {{ opacity:.4; cursor:default; }}

  #speedctl {{ display:flex; align-items:center; gap:10px; margin-top:8px; }}
  #speedctl input[type=range] {{ flex:1; accent-color:#4d8cff; }}
  #speedctl .lbl {{ font-size:12px; color:#8290c4; white-space:nowrap; }}

  #progress {{
    margin-top:14px; height:6px; border-radius:3px; background:#1a2548;
    overflow:hidden; cursor:pointer;
  }}
  #progress > div {{
    height:100%; width:0%; background:linear-gradient(90deg,#4d8cff,#29d3ff);
    transition:width .08s linear;
  }}

  #legend {{
    position:absolute; bottom:46px; right:24px; z-index:120;
    padding:12px 16px; border-radius:8px;
    background:rgba(255,255,255,.94); box-shadow:0 2px 12px rgba(0,0,0,.22);
    font:12px/1.6 "Microsoft YaHei",sans-serif;
  }}
  #legend h4 {{ font-size:13px; margin-bottom:6px; }}
  .leg-bar {{
    width:140px; height:8px; border-radius:4px;
    background:linear-gradient(90deg,#1577FF,#FFD700,#DC143C);
    margin:4px 0 2px;
  }}
  .leg-labels {{ display:flex; justify-content:space-between; font-size:10px; color:#666; }}

  #marker-legend {{
    position:absolute; bottom:46px; left:24px; z-index:120;
    padding:10px 14px; border-radius:8px;
    background:rgba(255,255,255,.94); box-shadow:0 2px 12px rgba(0,0,0,.22);
    font:12px/1.6 "Microsoft YaHei",sans-serif;
  }}
  .mk-row {{ display:flex; align-items:center; gap:8px; }}
  .mk-dot {{ width:12px; height:12px; border-radius:50%; }}
</style>
</head>
<body>
<div id="map"></div>

<div id="header">
  <h1>出租车轨迹查询<span class="sub">深圳出租车GPS · 交互回放</span></h1>
  <select id="vehicleSel"></select>
</div>

<div id="panel">
  <h3>实时状态</h3>
  <div class="stat"><span class="k">车辆ID</span><span class="v" id="s-vid">—</span></div>
  <div class="stat"><span class="k">时间</span><span class="v" id="s-time">—</span></div>
  <div class="stat"><span class="k">速度</span><span class="v" id="s-speed">—</span> km/h</div>
  <div class="stat"><span class="k">状态</span><span class="badge" id="s-status">—</span></div>
  <div class="stat"><span class="k">进度</span><span class="v" id="s-prog">0 / 0</span></div>

  <h3 style="margin-top:18px;">回放控制</h3>
  <div id="ctrl">
    <button id="btnPlay">播放</button>
    <button id="btnPause" class="secondary">暂停</button>
    <button id="btnReset" class="secondary">重置</button>
  </div>
  <div id="speedctl">
    <span class="lbl">速度</span>
    <input type="range" id="spdRange" min="1" max="60" value="15">
    <span class="lbl" id="spdVal">15×</span>
  </div>
  <div id="progress"><div></div></div>

  <h3 style="margin-top:18px;">轨迹信息</h3>
  <div class="stat"><span class="k">点数</span><span class="v" id="s-pts">—</span></div>
  <div class="stat"><span class="k">上下客</span><span class="v" id="s-ords">—</span></div>
</div>

<div id="legend">
  <h4>速度 (km/h)</h4>
  <div class="leg-bar"></div>
  <div class="leg-labels"><span>0</span><span>60</span><span>120+</span></div>
</div>

<div id="marker-legend">
  <div class="mk-row"><div class="mk-dot" style="background:#1aa240"></div> 上客点</div>
  <div class="mk-row" style="margin-top:4px;"><div class="mk-dot" style="background:#d8232f"></div> 下客点</div>
</div>

<script>
// ── 加载轨迹数据 ────────────────────────────────────────────────────────
var TRAJ = null;
var map = null;
var curVid = null;
var curIdx = 0;
var playing = false;
var timer = null;
var playRate = 15;            // 每帧步进点数
var overlays = [];            // 当前车辆叠加物（折线段+标记+回放点）
var playMarker = null;
var playPos = [];

var DATA_FILE = '{out_json_name}';

function speedColor(s) {{
  // 0=蓝, 60=黄, 120=红 的 RGB 渐变
  s = Math.max(0, Math.min(120, s));
  var r, g, b;
  if (s < 60) {{
    var t = s / 60;
    r = Math.round( 21 + t*(255 - 21));
    g = Math.round(119 + t*(215 - 119));
    b = Math.round(255 + t*(  0 - 255));
  }} else {{
    var t = (s - 60) / 60;
    r = Math.round(255 + t*(220 - 255));
    g = Math.round(215 + t*( 35 - 215));
    b = Math.round(  0 + t*( 60 -   0));
  }}
  return '#' + [r,g,b].map(function(c){{ return ('0'+c.toString(16)).slice(-2); }}).join('');
}}

function clearOverlays() {{
  for (var i = 0; i < overlays.length; i++) map.removeOverlay(overlays[i]);
  overlays = [];
  playMarker = null;
}}

function statusBadge(st) {{
  if (st === 1) return '<span class="badge occupied">载客</span>';
  return '<span class="badge empty">空车</span>';
}}

function buildPolyline(pts) {{
  // 按相邻段的速度着色，连续相同颜色合并以减少叠加物
  var segs = [];
  for (var i = 1; i < pts.length; i++) {{
    var sp = (pts[i-1][4] + pts[i][4]) / 2;
    var col = speedColor(sp);
    if (segs.length && segs[segs.length-1].col === col) {{
      segs[segs.length-1].pts.push(pts[i]);
    }} else {{
      segs.push({{col: col, pts: [pts[i-1], pts[i]]}});
    }}
  }}
  for (var i = 0; i < segs.length; i++) {{
    var bp = segs[i].pts.map(function(p){{ return new BMap.Point(p[1], p[2]); }});
    var poly = new BMap.Polyline(bp, {{
      strokeColor: segs[i].col, strokeWeight: 4, strokeOpacity: 0.85
    }});
    map.addOverlay(poly);
    overlays.push(poly);
  }}
}}

function buildOrderMarkers(orders) {{
  for (var i = 0; i < orders.length; i++) {{
    var o = orders[i];
    var pt = new BMap.Point(o.lon, o.lat);
    var isPick = o.type === 'pickup';
    var icon = new BMap.Icon(
      'https://api.map.baidu.com/images/markers.png',
      new BMap.Size(23, 25),
      {{offset: new BMap.Size(10, 25),
        imageOffset: new BMap.Size(isPick ? 0 : -23, 0)}}
    );
    // 自定义颜色标记：用带标签的小圆点更清晰
    var col = isPick ? '#1aa240' : '#d8232f';
    var marker = new BMap.Marker(pt, {{
      icon: new BMap.Icon(
        'data:image/svg+xml;base64,' + btoa(
          '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="30" viewBox="0 0 22 30">'+
          '<path d="M11 0C5 0 0 5 0 11c0 8 11 19 11 19s11-11 11-19C22 5 17 0 11 0z" fill="'+col+'"/>'+
          '<circle cx="11" cy="11" r="4" fill="#fff"/></svg>'
        )
      )
    }});
    var label = new BMap.Label(
      (isPick ? '上客' : '下客') + '<br>' + o.time,
      {{offset: new BMap.Size(14, -4)}}
    );
    label.setStyle({{
      padding:'3px 6px', borderRadius:'4px', fontSize:'11px',
      background: col, color:'#fff', border:'none',
      fontFamily:'Microsoft YaHei', whiteSpace:'nowrap'
    }});
    marker.setLabel(label);
    map.addOverlay(marker);
    overlays.push(marker);
  }}
}}

function renderVehicle(v) {{
  clearOverlays();
  curVid = v.id;
  curIdx = 0;
  var pts = v.points;
  playPos = pts;
  buildPolyline(pts);
  buildOrderMarkers(v.orders);
  // 回放标记
  playMarker = new BMap.Marker(new BMap.Point(pts[0][1], pts[0][2]));
  playMarker.setAnimation(BMAP_ANIMATION_BOUNCE);
  map.addOverlay(playMarker);
  overlays.push(playMarker);

  // 视图自适应到轨迹范围
  var bpoints = pts.map(function(p){{ return new BMap.Point(p[1], p[2]); }});
  var view = map.getViewport(bpoints);
  map.centerAndZoom(view.center, view.zoom);

  updateInfo(0);
  document.getElementById('s-pts').textContent = pts.length;
  document.getElementById('s-ords').textContent = v.orders.length;
  resetProgress();
}}

function updateInfo(idx) {{
  if (!playPos.length) return;
  var p = playPos[idx];
  document.getElementById('s-vid').textContent = curVid;
  document.getElementById('s-time').textContent = p[0];
  document.getElementById('s-speed').textContent = p[4];
  document.getElementById('s-status').innerHTML = statusBadge(p[3]);
  document.getElementById('s-prog').textContent = (idx + 1) + ' / ' + playPos.length;
  document.getElementById('progress').firstElementChild.style.width =
    ((idx + 1) / playPos.length * 100) + '%';
}}

function resetProgress() {{
  document.getElementById('progress').firstElementChild.style.width = '0%';
  document.getElementById('s-prog').textContent = '1 / ' + (playPos.length||0);
}}

function step() {{
  if (!playPos.length) return;
  curIdx += playRate;
  if (curIdx >= playPos.length) curIdx = playPos.length - 1;
  var p = playPos[curIdx];
  playMarker.setPosition(new BMap.Point(p[1], p[2]));
  updateInfo(curIdx);
  if (curIdx >= playPos.length - 1) {{ pause(); return; }}
}}

function play() {{
  if (!playPos.length) return;
  if (curIdx >= playPos.length - 1) curIdx = 0;
  playing = true;
  if (timer) clearInterval(timer);
  timer = setInterval(step, 80);
}}
function pause() {{
  playing = false;
  if (timer) {{ clearInterval(timer); timer = null; }}
}}
function reset() {{
  pause();
  curIdx = 0;
  if (playPos.length) {{
    var p = playPos[0];
    playMarker.setPosition(new BMap.Point(p[1], p[2]));
    updateInfo(0);
  }}
}}

function loadThen(v) {{
  document.getElementById('s-pts').textContent = v.points.length;
  document.getElementById('s-ords').textContent = v.orders.length;
}}

function initMap() {{
  map = new BMap.Map('map');
  map.centerAndZoom(new BMap.Point({SHENZHEN_CENTER[0]}, {SHENZHEN_CENTER[1]}), 12);
  map.enableScrollWheelZoom(true);
  map.addControl(new BMap.NavigationControl());
  map.addControl(new BMap.ScaleControl());
  map.addControl(new BMap.MapTypeControl());

  fetch(DATA_FILE)
    .then(function(r){{ return r.json(); }})
    .then(function(data){{
      TRAJ = data.vehicles;
      var sel = document.getElementById('vehicleSel');
      for (var i = 0; i < TRAJ.length; i++) {{
        var v = TRAJ[i];
        var opt = document.createElement('option');
        opt.value = i;
        opt.textContent = '车辆 #' + v.id + '  (' + v.points.length + '点 · ' + v.orders.length + '上下客)';
        sel.appendChild(opt);
      }}
      sel.addEventListener('change', function(){{
        pause();
        renderVehicle(TRAJ[parseInt(sel.value)]);
      }});
      if (TRAJ.length) {{
        renderVehicle(TRAJ[0]);
        document.getElementById('s-pts').textContent = TRAJ[0].points.length;
        document.getElementById('s-ords').textContent = TRAJ[0].orders.length;
      }}
    }})
    .catch(function(e){{
      console.error(e);
      document.getElementById('panel').innerHTML +=
        '<p style="color:#ff8a8a;margin-top:12px;">数据加载失败: ' + e + '<br>请通过 --serve HTTP 方式打开（fetch 在 file:// 下不可用）</p>';
    }});

  document.getElementById('btnPlay').addEventListener('click', play);
  document.getElementById('btnPause').addEventListener('click', pause);
  document.getElementById('btnReset').addEventListener('click', reset);

  var spd = document.getElementById('spdRange');
  var spv = document.getElementById('spdVal');
  spd.addEventListener('input', function(){{
    playRate = parseInt(spd.value);
    spv.textContent = playRate + '×';
  }});

  // 点击进度条跳转
  var prog = document.getElementById('progress');
  prog.addEventListener('click', function(e){{
    if (!playPos.length) return;
    var rect = prog.getBoundingClientRect();
    var frac = (e.clientX - rect.left) / rect.width;
    curIdx = Math.max(0, Math.min(playPos.length - 1, Math.floor(frac * playPos.length)));
    var p = playPos[curIdx];
    playMarker.setPosition(new BMap.Point(p[1], p[2]));
    updateInfo(curIdx);
    if (playing) {{ clearInterval(timer); timer = setInterval(step, 80); }}
  }});
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
    print('   浏览器打开:')
    print(f'   ┌──────────────────────────────────────────────────────────┐')
    print(f'   │  {url}  │')
    print(f'   └──────────────────────────────────────────────────────────┘')
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
    parser = argparse.ArgumentParser(description='生成百度地图轨迹回放查看器')
    parser.add_argument('--serve', action='store_true',
                        help='生成后启动 HTTP 服务器')
    parser.add_argument('--port', type=int, default=8080,
                        help='HTTP 服务器端口（默认 8080）')
    args = parser.parse_args()

    vehicles_path = os.path.join(DATA_DIR, 'cache', 'vehicles.json')
    vd_path = os.path.join(DATA_DIR, 'cache', 'vehicle_data.json')
    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    for p in (vehicles_path, vd_path, orders_path):
        assert_input_exists(p)

    os.makedirs(FIGURES_DIR, exist_ok=True)

    # 1. 选车
    vids, order_index = _select_sample_vehicles(vehicles_path, orders_path)

    # 2. 流式抽取轨迹
    traj_map = _stream_trajectories(vd_path, vids)

    # 3. 生成 trajectory_sample.json
    sample_path = os.path.join(FIGURES_DIR, 'trajectory_sample.json')
    print('\n生成 trajectory_sample.json ...')
    _build_sample_json(vids, traj_map, order_index, sample_path)

    # 4. 生成 HTML
    html_path = os.path.join(FIGURES_DIR, 'trajectory_viewer.html')
    print('\n生成 trajectory_viewer.html ...')
    html = _generate_html(Path(sample_path).name)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  {html_path} ({os.path.getsize(html_path) / 1024:.1f} KB)')

    print('\n完成。')
    if args.serve:
        _serve_html(html_path, port=args.port)
    else:
        print()
        print('提示: 不能直接双击打开，请使用:')
        print(f'   python src/08_轨迹查询.py --serve')
        print(f'   然后打开 http://localhost:8080/trajectory_viewer.html')


if __name__ == '__main__':
    main()