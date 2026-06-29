
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
import math
import os
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pandas as pd

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.config import BAIDU_MAP_API_KEY, DATA_DIR, FIGURES_DIR
from src.utils import assert_input_exists


N_SAMPLES = 100
MAX_POINTS_PER_VEHICLE = 1500
SHENZHEN_CENTER = (114.05, 22.55)


MAX_IMPLIED_SPEED_KMH = 150
MAX_TIME_GAP_S = 300
STOP_SPEED_KMH = 5
STOP_CLUSTER_RADIUS_M = 80
STOP_MIN_POINTS = 5


def _parse_time_seconds(t):
    if ' ' in t:
        t = t.split(' ')[1]
    h, m, s = map(int, t.split(':'))
    return h * 3600 + m * 60 + s


def _haversine_m(lon1, lat1, lon2, lat2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _filter_trajectory_drift(pts):
    """对单车轨迹点做漂移过滤与停留点压缩，返回 (过滤后点集, 统计信息)。"""
    if not pts:
        return pts, {}

    parsed = []
    for p in pts:
        try:
            ts = _parse_time_seconds(p[0])
        except Exception:
            ts = None
        parsed.append({
            'time_str': p[0],
            'lon': float(p[1]),
            'lat': float(p[2]),
            'status': int(p[3]),
            'speed': int(p[4]),
            'ts': ts,
        })

    if any(pp['ts'] is None for pp in parsed):
        return [[p[0], p[1], p[2], p[3], p[4], 0] for p in pts], {'skipped': True}

    parsed.sort(key=lambda x: x['ts'])

    kept = [parsed[0]]
    jump_removed = 0
    for i in range(1, len(parsed)):
        prev = kept[-1]
        cur = parsed[i]
        dt = cur['ts'] - prev['ts']
        if dt <= 0:
            jump_removed += 1
            continue
        dist_m = _haversine_m(prev['lon'], prev['lat'], cur['lon'], cur['lat'])
        implied_speed = (dist_m / 1000) / (dt / 3600)
        if implied_speed > MAX_IMPLIED_SPEED_KMH:
            jump_removed += 1
            continue
        kept.append(cur)

    compressed = []
    stop_removed = 0
    i = 0
    while i < len(kept):
        cur = kept[i]
        if cur['speed'] >= STOP_SPEED_KMH:
            compressed.append(cur)
            i += 1
            continue

        j = i + 1
        cluster = [cur]
        centroid_lon = cur['lon']
        centroid_lat = cur['lat']
        while j < len(kept) and kept[j]['speed'] < STOP_SPEED_KMH:
            cluster.append(kept[j])
            centroid_lon += kept[j]['lon']
            centroid_lat += kept[j]['lat']
            j += 1

        if len(cluster) >= STOP_MIN_POINTS:
            max_dist = 0
            for a in cluster:
                for b in cluster:
                    d = _haversine_m(a['lon'], a['lat'], b['lon'], b['lat'])
                    if d > max_dist:
                        max_dist = d
            if max_dist <= STOP_CLUSTER_RADIUS_M:
                centroid_lon /= len(cluster)
                centroid_lat /= len(cluster)
                avg_speed = sum(p['speed'] for p in cluster) / len(cluster)
                compressed.append({
                    'time_str': cluster[0]['time_str'],
                    'lon': centroid_lon,
                    'lat': centroid_lat,
                    'status': cluster[-1]['status'],
                    'speed': round(avg_speed),
                    'ts': cluster[0]['ts'],
                })
                stop_removed += len(cluster) - 1
                i = j
                continue
        compressed.extend(cluster)
        i = j

    result = []
    for idx, p in enumerate(compressed):
        gap = 0
        if idx > 0:
            dt = p['ts'] - compressed[idx - 1]['ts']
            if dt > MAX_TIME_GAP_S:
                gap = 1
        result.append([p['time_str'], round(p['lon'], 6), round(p['lat'], 6),
                       p['status'], p['speed'], gap])

    stats = {
        'original': len(pts),
        'jump_removed': jump_removed,
        'stop_removed': stop_removed,
        'final': len(result),
    }
    return result, stats


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

    print(f'  车辆总数: {len(vmeta):,}')

    print('读取订单数据 ...')
    odf = pd.read_csv(orders_path)
    odf['开始时间'] = pd.to_datetime(odf['开始时间'])
    odf['结束时间'] = pd.to_datetime(odf['结束时间'])
    print(f'  订单总数: {len(odf):,}')


    order_count = odf.groupby('车辆id').size()


    rows = []
    for vid_str, meta in vmeta.items():
        vid = int(vid_str)
        point_count = meta[0]
        oc = int(order_count.get(vid, 0))
        rows.append({'vid': vid, 'point_count': point_count, 'order_count': oc})
    cand = pd.DataFrame(rows)

    cand = cand[cand['order_count'] > 0].reset_index(drop=True)
    print(f'  有订单的候选车辆: {len(cand):,}')


    cand = cand.sort_values('point_count').reset_index(drop=True)
    n = min(n, len(cand))
    picks = []
    step = len(cand) / n
    for i in range(n):
        lo = int(round(i * step))
        hi = int(round((i + 1) * step))
        bucket = cand.iloc[lo:hi]

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

        events.sort(key=lambda e: e['time'])
        order_index[int(vid)] = events

    return picks, order_index


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
            if s != '"':
                continue

            try:
                key_end = line.index('"', 1)
            except ValueError:
                continue
            vid = line[1:key_end]
            if vid not in targets:
                continue

            obj = json.loads('{' + line.rstrip().rstrip(',') + '}')
            traj = obj[vid]

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


def _build_sample_json(vids: list[int], traj_map: dict,
                        order_index: dict, out_path: str) -> dict:
    """生成 trajectory_sample.json，返回过滤统计信息。"""
    vehicles = []
    total_stats = {'original': 0, 'jump_removed': 0, 'stop_removed': 0, 'final': 0}
    for vid in vids:
        pts = traj_map.get(vid, [])
        if not pts:
            continue
        filtered, stats = _filter_trajectory_drift(pts)
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)
        vehicles.append({
            'id': vid,
            'points_raw': [
                [p[0], round(float(p[1]), 6), round(float(p[2]), 6),
                 int(p[3]), int(p[4]), 0]
                for p in pts
            ],
            'points': [
                [p[0], round(float(p[1]), 6), round(float(p[2]), 6),
                 int(p[3]), int(p[4]), int(p[5])]
                for p in filtered
            ],
            'orders': order_index.get(vid, []),
        })
    payload = {'vehicles': vehicles}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    size = os.path.getsize(out_path)
    print(f'  {out_path} ({size / 1024 / 1024:.2f} MB, {len(vehicles)} 辆车)')
    return total_stats


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
  <div style="margin-top:12px; display:flex; align-items:center; gap:8px;">
    <input type="checkbox" id="rawToggle" style="accent-color:#4d8cff; cursor:pointer;">
    <label for="rawToggle" style="font-size:12px; color:#8290c4; cursor:pointer;">显示原始轨迹</label>
  </div>

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
// 渐进式轨迹回放（弧长匀速版）：
//   - 位置用 posD（已走公里数）+ CUM[] 里程表表达，marker 按真实地理距离匀速推进，
//     消除"每条 GPS 边等时长"导致的屏上速度跳变。
//   - 已走折线分两部分：已提交整边（traveled[]，按色/无 gap 合并）+ 一条 frontier
//     折线随 marker 每帧延伸到当前插值点，从而线尖始终贴着 marker，不再"卡段"。
//   - gap=1 处：EDGES 跳过断点边，frontier 在断点后起新折线、marker 瞬移，不画跨断直线。
var TRAJ = null;
var map = null;
var curVid = null;
var playing = false;
var rafId = null;             // 单一 rAF 句柄
var lastTs = 0;               // 上一帧时间戳（ms），用于 dt 计算
var playRate = 15;            // 速度倍率（1×–60×），滑块即时生效
var overlays = [];            // 当前车辆叠加物（订单标记 + 回放标记 + 折线段）
var traveled = [];            // 已提交整边折线 [{{poly, path, color}}]，每 gap 一条
var frontierPoly = null;      // 当前进行中的部分边（线尖贴 marker），单条独立 Polyline
var frontierEdge = -1;        // frontierPoly 对应的 EDGES 索引，用于跨边时切换
var playMarker = null;
var orderMarkers = [];        // 上下客标记 [{{marker, trigIdx}}]，trigIdx=触发显示的 playPos 索引
var playPos = [];             // 当前车辆点数组（raw 或 filtered）
var showRaw = false;
var EDGES = [];               // 可走边起点索引（pts[i]→pts[i+1] 且 pts[i+1][5]!==1）
var EDGE_LEN = [];            // 每条可走边的长度（公里）
var CUM = [0];                // 累计里程表：CUM[k] = 前 k 条边长度和，CUM.length = EDGES.length+1
var EDGE_TOTAL = 0;           // 全程总公里数
var posD = 0;                 // 当前已走公里数 [0, EDGE_TOTAL]
var committedEdge = 0;        // 已提交到 traveled 的整边数（含 gap 切分）

// 1× 时每秒推进 0.03 km（≈ 30 m/s ≈ 108 km/h 屏上速度基准）；slider 倍率叠加。
var SPEED_PER_SEC = 0.03;

// 方向箭头图标（base64 内联，rotation=0 时箭头朝北）
var ARROW_ICON_URL = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScyOCcgaGVpZ2h0PScyOCcgdmlld0JveD0nMCAwIDI4IDI4Jz48cGF0aCBkPSdNMTQgMiBMMjUgMjUgTDE0IDE5IEwzIDI1IFonIGZpbGw9JyMyNTYzZWInIHN0cm9rZT0nI2ZmZmZmZicgc3Ryb2tlLXdpZHRoPScxLjUnIHN0cm9rZS1saW5lam9pbj0ncm91bmQnLz48Y2lyY2xlIGN4PScxNCcgY3k9JzE0JyByPScyJyBmaWxsPScjZmZmZmZmJy8+PC9zdmc+';
var arrowIcon = null;

var DATA_FILE = '{out_json_name}';

// ── 纯函数（仅用 Math，便于 node 单测） ─────────────────────────────────
// 朝向角（度）：北=0、顺时针，百度 setRotation 约定。
function headingDeg(lat1, lon1, lat2, lon2) {{
  var dy = lat2 - lat1;
  var dx = (lon2 - lon1) * Math.cos(lat1 * Math.PI / 180);
  if (dx === 0 && dy === 0) return 0;
  var h = Math.atan2(dx, dy) * 180 / Math.PI;
  if (h < 0) h += 360;
  return h;
}}

// haversine 距离（公里）。
function haversineKm(lat1, lon1, lat2, lon2) {{
  var R = 6371;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.pow(Math.sin(dLat / 2), 2) +
          Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
          Math.pow(Math.sin(dLon / 2), 2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}}

// 按 gap=1 将点序列切成连续段：返回 {{ segments: [[a,b],...], cuts: [gapIdx,...] }}。
function segmentAndGapCut(pts) {{
  var segments = [], cuts = [];
  if (!pts || !pts.length) return {{ segments: segments, cuts: cuts }};
  var start = 0;
  for (var i = 1; i < pts.length; i++) {{
    if (pts[i][5] === 1) {{
      if (i - 1 >= start) segments.push([start, i - 1]);
      cuts.push(i);
      start = i;
    }}
  }}
  if (start < pts.length - 1) segments.push([start, pts.length - 1]);
  else if (pts.length === 1) segments.push([0, 0]);
  return {{ segments: segments, cuts: cuts }};
}}

// 线性插值两点 [lon, lat]。
function interpolatePoint(p1, p2, t) {{
  return [p1[1] + (p2[1] - p1[1]) * t, p1[2] + (p2[2] - p1[2]) * t];
}}

// ── 颜色映射（0=蓝, 60=黄, 120=红） ────────────────────────────────────
function speedColor(s) {{
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

// 第 k 条可走边的颜色（取两端点速度均值）。
function edgeColor(k) {{
  var i0 = EDGES[k];
  return speedColor((playPos[i0][4] + playPos[i0 + 1][4]) / 2);
}}

// ── 叠加物管理 ──────────────────────────────────────────────────────────
function removeFrontier() {{
  if (frontierPoly) {{
    map.removeOverlay(frontierPoly);
    var i = overlays.indexOf(frontierPoly);
    if (i >= 0) overlays.splice(i, 1);
    frontierPoly = null;
    frontierEdge = -1;
  }}
}}

function clearOverlays() {{
  for (var i = 0; i < overlays.length; i++) map.removeOverlay(overlays[i]);
  overlays = [];
  traveled = [];
  orderMarkers = [];
  frontierPoly = null;
  frontierEdge = -1;
  playMarker = null;
  posD = 0;
  committedEdge = 0;
}}

function clearTraveled() {{
  for (var i = 0; i < traveled.length; i++) map.removeOverlay(traveled[i].poly);
  traveled = [];
  removeFrontier();
}}

function statusBadge(st) {{
  if (st === 1) return '<span class="badge occupied">载客</span>';
  return '<span class="badge empty">空车</span>';
}}

// 追加一条已走边到 traveled（同色且无 gap 则并入末条 poly，否则新起一条）。
// t=1 整边；t<1 当前进行中（仅 seek 重建时用）。
function appendEdgeFrac(k, t) {{
  if (k < 0 || k >= EDGES.length) return;
  var i0 = EDGES[k];
  var p0 = playPos[i0], p1 = playPos[i0 + 1];
  var col = edgeColor(k);
  var gapBefore = (k > 0 && EDGES[k] !== EDGES[k - 1] + 1);
  var startPt = new BMap.Point(p0[1], p0[2]);
  var endPt = new BMap.Point(p0[1] + (p1[1] - p0[1]) * t, p0[2] + (p1[2] - p0[2]) * t);
  var last = traveled.length ? traveled[traveled.length - 1] : null;
  if (!last || last.color !== col || gapBefore) {{
    var poly = new BMap.Polyline([startPt, endPt], {{
      strokeColor: col, strokeWeight: 4, strokeOpacity: 0.85
    }});
    map.addOverlay(poly);
    overlays.push(poly);
    traveled.push({{ poly: poly, path: [startPt, endPt], color: col }});
  }} else {{
    last.path.push(endPt);
    last.poly.setPath(last.path);
  }}
}}

// 把 frontier（进行中边）更新或重建到当前 posD 位置，并同步 marker 朝向。
function setFrontier() {{
  if (!EDGES.length || committedEdge >= EDGES.length) {{ removeFrontier(); return; }}
  var k = committedEdge;
  var i0 = EDGES[k];
  var p0 = playPos[i0], p1 = playPos[i0 + 1];
  var t = EDGE_LEN[k] > 1e-9 ? (posD - CUM[k]) / EDGE_LEN[k] : 0;
  if (t < 0) t = 0; if (t > 1) t = 1;
  var startPt = new BMap.Point(p0[1], p0[2]);
  var endPt = new BMap.Point(p0[1] + (p1[1] - p0[1]) * t, p0[2] + (p1[2] - p0[2]) * t);
  if (!frontierPoly || frontierEdge !== k) {{
    removeFrontier();
    frontierPoly = new BMap.Polyline([startPt, endPt], {{
      strokeColor: edgeColor(k), strokeWeight: 4, strokeOpacity: 0.85
    }});
    map.addOverlay(frontierPoly);
    overlays.push(frontierPoly);
    frontierEdge = k;
  }} else {{
    frontierPoly.setPath([startPt, endPt]);
  }}
  if (playMarker) {{
    playMarker.setPosition(endPt);
    playMarker.setRotation(headingDeg(p0[2], p0[1], p1[2], p1[1]));
  }}
}}

// 在 posD 给定时，先把所有已完整走过的边提交到 traveled，再 setFrontier 处理进行中边。
function rebuildTraveled() {{
  clearTraveled();
  committedEdge = 0;
  while (committedEdge < EDGES.length && posD >= CUM[committedEdge + 1] - 1e-9) {{
    appendEdgeFrac(committedEdge, 1.0);
    committedEdge++;
  }}
  setFrontier();
  syncOrdersVisible();
}}

// 按 playPos 时间串字典序找到首个 time >= orderTime 的点索引；没找到则放最后一个点
function orderTrigIndex(orderTime) {{
  if (!playPos.length) return 0;
  var lo = 0, hi = playPos.length;
  while (lo < hi) {{
    var mid = (lo + hi) >> 1;
    if (playPos[mid][0] < orderTime) lo = mid + 1; else hi = mid;
  }}
  return Math.min(lo, playPos.length - 1);
}}

// 按当前 currentIndex 显示/隐藏上下客标记：已到的显示、未到的隐藏
function syncOrdersVisible() {{
  var idx = currentIndex();
  for (var i = 0; i < orderMarkers.length; i++) {{
    var m = orderMarkers[i];
    if (idx >= m.trigIdx) {{ if (!m.marker.isVisible()) m.marker.show(); }}
    else {{ if (m.marker.isVisible()) m.marker.hide(); }}
  }}
}}

function buildOrderMarkers(orders) {{
  orderMarkers = [];
  for (var i = 0; i < orders.length; i++) {{
    var o = orders[i];
    var pt = new BMap.Point(o.lon, o.lat);
    var isPick = o.type === 'pickup';
    var col = isPick ? '#1aa240' : '#d8232f';
    var marker = new BMap.Marker(pt);
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
    marker.hide();   // 初始隐藏，由 syncOrdersVisible 在推进时按顺序揭示
    map.addOverlay(marker);
    overlays.push(marker);
    orderMarkers.push({{marker: marker, trigIdx: orderTrigIndex(o.time)}});
  }}
}}

// ── 位置派生 ────────────────────────────────────────────────────────────
function currentIndex() {{
  if (!EDGES.length) return playPos.length ? 0 : 0;
  if (committedEdge >= EDGES.length) return playPos.length - 1;
  var k = committedEdge;
  var t = EDGE_LEN[k] > 1e-9 ? (posD - CUM[k]) / EDGE_LEN[k] : 0;
  var idx = EDGES[k] + (t >= 0.5 ? 1 : 0);
  return Math.min(idx, playPos.length - 1);
}}

// ── 渲染车辆 ────────────────────────────────────────────────────────────
function renderVehicle(v) {{
  if (rafId) {{ cancelAnimationFrame(rafId); rafId = null; }}
  playing = false; lastTs = 0;
  clearOverlays();
  curVid = v.id;
  var pts = (showRaw ? v.points_raw : v.points) || [];
  playPos = pts;
  buildOrderMarkers(v.orders || []);

  // 构造可走边集合 + 里程表
  var segs = segmentAndGapCut(playPos).segments;
  EDGES = [];
  for (var s = 0; s < segs.length; s++) {{
    for (var i = segs[s][0]; i < segs[s][1]; i++) EDGES.push(i);
  }}
  EDGE_LEN = [];
  CUM = [0];
  EDGE_TOTAL = 0;
  for (var k = 0; k < EDGES.length; k++) {{
    var i0 = EDGES[k];
    var L = haversineKm(playPos[i0][2], playPos[i0][1], playPos[i0 + 1][2], playPos[i0 + 1][1]);
    if (L < 1e-9) L = 1e-9;
    EDGE_LEN.push(L);
    EDGE_TOTAL += L;
    CUM.push(EDGE_TOTAL);
  }}
  posD = 0;
  committedEdge = 0;
  traveled = [];
  frontierPoly = null;
  frontierEdge = -1;

  document.getElementById('s-pts').textContent = pts.length;
  document.getElementById('s-ords').textContent = (v.orders || []).length;

  if (!pts.length) {{ resetProgress(); return; }}
  if (!arrowIcon) arrowIcon = new BMap.Icon(ARROW_ICON_URL, new BMap.Size(28, 28), {{ anchor: new BMap.Size(14, 14) }});
  playMarker = new BMap.Marker(new BMap.Point(pts[0][1], pts[0][2]), {{ icon: arrowIcon }});
  map.addOverlay(playMarker);
  overlays.push(playMarker);
  setFrontier();   // 将 marker 移到起点并设首朝向

  var bpoints = pts.map(function(p){{ return new BMap.Point(p[1], p[2]); }});
  var view = map.getViewport(bpoints);
  map.centerAndZoom(view.center, view.zoom);

  updateInfo();
  resetProgress();
  syncOrdersVisible();

  if (window.GSAPPage && window.GSAPPage.trajectoryPanelPulse) {{
    GSAPPage.trajectoryPanelPulse('#panel .stat');
  }}
}}

function updateInfo() {{
  if (!playPos.length) return;
  var idx = currentIndex();
  var p = playPos[idx];
  document.getElementById('s-vid').textContent = curVid;
  document.getElementById('s-time').textContent = p[0];
  document.getElementById('s-speed').textContent = p[4];
  document.getElementById('s-status').innerHTML = statusBadge(p[3]);
  document.getElementById('s-prog').textContent = (idx + 1) + ' / ' + playPos.length;
  var frac = EDGE_TOTAL > 1e-9 ? posD / EDGE_TOTAL : (EDGES.length ? committedEdge / EDGES.length : 0);
  if (committedEdge >= EDGES.length && EDGES.length) frac = 1;
  document.getElementById('progress').firstElementChild.style.width = (frac * 100) + '%';
}}

function resetProgress() {{
  document.getElementById('progress').firstElementChild.style.width = '0%';
  document.getElementById('s-prog').textContent = '1 / ' + (playPos.length || 0);
}}

// ── 推进与动画循环 ──────────────────────────────────────────────────────
function advance(deltaKm) {{
  if (!EDGES.length) return;
  if (deltaKm < 0) deltaKm = 0;
  var newD = Math.min(posD + deltaKm, EDGE_TOTAL);
  // 跨越整边边界 → 提交到 traveled
  while (committedEdge < EDGES.length && newD >= CUM[committedEdge + 1] - 1e-9) {{
    appendEdgeFrac(committedEdge, 1.0);
    committedEdge++;
  }}
  posD = newD;
  if (committedEdge < EDGES.length) {{
    setFrontier();   // frontier 折线随 marker 实时延伸
  }} else {{
    removeFrontier();
    if (playMarker && playPos.length) {{
      var e = playPos[playPos.length - 1];
      playMarker.setPosition(new BMap.Point(e[1], e[2]));
    }}
  }}
  updateInfo();
  syncOrdersVisible();
}}

function loop(ts) {{
  if (!playing) return;
  if (!lastTs) lastTs = ts;
  var dt = (ts - lastTs) / 1000;
  lastTs = ts;
  if (dt > 0 && dt < 1) advance(playRate * SPEED_PER_SEC * dt);   // dt<1 防止后台标签页回来时大跳
  if (committedEdge >= EDGES.length) {{ pause(); return; }}
  rafId = requestAnimationFrame(loop);
}}

function play() {{
  if (!EDGES.length) return;
  if (committedEdge >= EDGES.length) {{           // 已到终点 → 从头起
    clearTraveled();
    posD = 0;
    committedEdge = 0;
    setFrontier();
  }}
  playing = true; lastTs = 0;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(loop);
}}

function pause() {{
  playing = false;
  if (rafId) {{ cancelAnimationFrame(rafId); rafId = null; }}
  lastTs = 0;
}}

function reset() {{
  pause();
  clearTraveled();
  posD = 0;
  committedEdge = 0;
  setFrontier();
  updateInfo();
  resetProgress();
  syncOrdersVisible();
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
        '<p style="color:#dc2626;margin-top:12px;">数据加载失败: ' + e + '<br>请通过 --serve HTTP 方式打开（fetch 在 file:// 下不可用）</p>';
    }});

  document.getElementById('btnPlay').addEventListener('click', function() {{
    if (window.GSAPPage && window.GSAPPage.buttonClickFeedback) GSAPPage.buttonClickFeedback(this);
    play();
  }});
  document.getElementById('btnPause').addEventListener('click', function() {{
    if (window.GSAPPage && window.GSAPPage.buttonClickFeedback) GSAPPage.buttonClickFeedback(this);
    pause();
  }});
  document.getElementById('btnReset').addEventListener('click', function() {{
    if (window.GSAPPage && window.GSAPPage.buttonClickFeedback) GSAPPage.buttonClickFeedback(this);
    reset();
  }});

  document.getElementById('rawToggle').addEventListener('change', function(e){{
    showRaw = e.target.checked;
    if (rafId) {{ cancelAnimationFrame(rafId); rafId = null; }}
    playing = false; lastTs = 0;
    var sel = document.getElementById('vehicleSel');
    if (TRAJ && sel.value !== '') renderVehicle(TRAJ[parseInt(sel.value)]);
  }});

  var spd = document.getElementById('spdRange');
  var spv = document.getElementById('spdVal');
  spd.addEventListener('input', function(){{
    playRate = parseInt(spd.value);
    spv.textContent = playRate + '×';
  }});

  // 点击进度条跳转：按里程比例 seek，重建已走折线到该位置
  var prog = document.getElementById('progress');
  prog.addEventListener('click', function(e){{
    if (!EDGES.length) return;
    var rect = prog.getBoundingClientRect();
    var frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    posD = frac * EDGE_TOTAL;
    rebuildTraveled();
    updateInfo();
    if (playing) {{ if (rafId) cancelAnimationFrame(rafId); lastTs = 0; rafId = requestAnimationFrame(loop); }}
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


    vids, order_index = _select_sample_vehicles(vehicles_path, orders_path)


    traj_map = _stream_trajectories(vd_path, vids)


    sample_path = os.path.join(FIGURES_DIR, 'trajectory_sample.json')
    print('\n生成 trajectory_sample.json ...')
    stats = _build_sample_json(vids, traj_map, order_index, sample_path)
    print(f'  漂移过滤: 原始 {stats["original"]:,} 点, '
          f'剔除跳点 {stats["jump_removed"]:,}, 压缩停留点 {stats["stop_removed"]:,}, '
          f'剩余 {stats["final"]:,}')


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