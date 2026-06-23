#!/usr/bin/env python3
"""深圳路网分析 — 基于出租车GPS数据的道路级拥堵可视化

1) 从 OpenStreetMap 下载深圳 drive 路网并保存为 GeoJSON
2) 流式读取 data/cache/vehicle_data.json（不载入 2.6GB 全量内存）
3) 将 GPS 点几何 snapping 到最近道路边，按 (u,v,key) 累积车速
4) 计算边平均速度并划分拥堵等级
5) 生成 Baidu Maps 路网拥堵 HTML（绿/黄/红），支持 --serve/--port

运行:
    python src/10_路网分析.py                         # 默认流式读取 vehicle_data.json
    python src/10_路网分析.py --use-clean-csv          # 从 clean.csv 采样（更快）
    python src/10_路网分析.py --serve --port 8080      # 生成后启动 HTTP 服务器
"""

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import pyproj
from scipy.spatial import cKDTree
from shapely import distance as shapely_distance, points as shapely_points
from shapely.geometry import LineString, Point

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (
    BAIDU_MAP_API_KEY,
    DATA_DIR,
    FIGURES_DIR,
    SHENZHEN_BOUNDS,
    SPEED_MAX,
)
from src.utils import assert_input_exists

# ── Paths ───────────────────────────────────────────────────────────────────
NETWORK_DIR = os.path.join(DATA_DIR, 'road_network')
EDGES_PATH = os.path.join(NETWORK_DIR, 'shenzhen_edges.geojson')
NODES_PATH = os.path.join(NETWORK_DIR, 'shenzhen_nodes.geojson')
ROAD_SPEEDS_PATH = os.path.join(NETWORK_DIR, 'road_speeds.json')
VEHICLE_DATA_PATH = os.path.join(DATA_DIR, 'cache', 'vehicle_data.json')
CLEAN_CSV_PATH = os.path.join(DATA_DIR, 'clean.csv')
HTML_PATH = os.path.join(FIGURES_DIR, 'road_congestion.html')

# ── Constants ───────────────────────────────────────────────────────────────
CENTER_LAT = 22.55
CENTER_LON = 114.06
ZOOM = 12

SAMPLE_RATE = 0.03          # ~3% 采样，约 1.1M 点
RANDOM_SEED = 42
K_NEAREST = 5               # cKDTree 候选边数，再用 shapely 精确选最近
BATCH_SIZE = 50000

COLOR_LOW = '#228B22'       # 畅通
COLOR_MEDIUM = '#FFD700'    # 缓行
COLOR_HIGH = '#DC143C'      # 拥堵

SPEED_LOW_THRESHOLD = 45.0
SPEED_HIGH_THRESHOLD = 20.0

# 流式解析正则：顶层 vehicle_id 后接数组开始（允许 : 后空白）
_VEHICLE_KEY_RE = re.compile(r'"(\d+)":\s*\[')


# ── Network I/O ─────────────────────────────────────────────────────────────

def _create_synthetic_fallback():
    """离线环境下生成覆盖深圳边界的网格路网 fallback。"""
    print('  生成深圳边界网格路网 fallback ...')
    b = SHENZHEN_BOUNDS
    lon_step = 0.015
    lat_step = 0.015
    lons = np.arange(b['long_min'], b['long_max'] + lon_step, lon_step)
    lats = np.arange(b['lat_min'], b['lat_max'] + lat_step, lat_step)

    node_records = []
    node_id_map = {}
    node_id = 0
    for i, lon in enumerate(lons):
        for j, lat in enumerate(lats):
            node_id_map[(i, j)] = node_id
            node_records.append({
                'osmid': node_id,
                'x': float(lon),
                'y': float(lat),
                'geometry': Point(lon, lat),
            })
            node_id += 1

    edges_records = []
    ekey = 0
    for i in range(len(lons) - 1):
        for j in range(len(lats)):
            u = node_id_map[(i, j)]
            v = node_id_map[(i + 1, j)]
            edges_records.append({
                'u': u, 'v': v, 'key': ekey,
                'geometry': LineString([(lons[i], lats[j]), (lons[i + 1], lats[j])]),
            })
            ekey += 1
    for i in range(len(lons)):
        for j in range(len(lats) - 1):
            u = node_id_map[(i, j)]
            v = node_id_map[(i, j + 1)]
            edges_records.append({
                'u': u, 'v': v, 'key': ekey,
                'geometry': LineString([(lons[i], lats[j]), (lons[i], lats[j + 1])]),
            })
            ekey += 1

    nodes_gdf = gpd.GeoDataFrame(node_records, crs='EPSG:4326')
    edges_gdf = gpd.GeoDataFrame(edges_records, crs='EPSG:4326')
    os.makedirs(NETWORK_DIR, exist_ok=True)
    nodes_gdf.to_file(NODES_PATH, driver='GeoJSON')
    edges_gdf.to_file(EDGES_PATH, driver='GeoJSON')
    print(f'    合成边数: {len(edges_gdf):,}, 节点数: {len(nodes_gdf):,}')


def _load_or_download_network():
    """返回 WGS84 的 edges/nodes GeoDataFrame；优先尝试 OSM 下载，失败则本地 fallback。"""
    b = SHENZHEN_BOUNDS
    bbox = (b['lat_max'], b['lat_min'], b['long_max'], b['long_min'])

    print('尝试从 OpenStreetMap 下载深圳 drive 路网 ...')
    ox.settings.requests_timeout = 15
    ox.settings.overpass_rate_limit = False
    overpass_mirrors = [
        'https://overpass-api.de/api',
        'https://overpass.openstreetmap.fr/api',
    ]
    G = None
    for mirror in overpass_mirrors:
        ox.settings.overpass_url = mirror
        try:
            G = ox.graph_from_bbox(bbox=bbox, network_type='drive', simplify=True)
            print(f'  使用 Overpass 镜像: {mirror}')
            break
        except Exception as e:
            print(f'  镜像 {mirror} 失败: {e}')

    if G is not None:
        edges_wgs84 = ox.graph_to_gdfs(G, nodes=False, edges=True)
        nodes_wgs84 = ox.graph_to_gdfs(G, edges=False, nodes=True)
        os.makedirs(NETWORK_DIR, exist_ok=True)
        edges_wgs84.to_file(EDGES_PATH, driver='GeoJSON')
        nodes_wgs84.to_file(NODES_PATH, driver='GeoJSON')
        print(f'  边数: {len(edges_wgs84):,}, 节点数: {len(nodes_wgs84):,}')
        print(f'  已保存: {EDGES_PATH}, {NODES_PATH}')
        return edges_wgs84, nodes_wgs84

    print('OSM 下载不可用，使用本地路网 fallback ...')
    if not (os.path.exists(EDGES_PATH) and os.path.exists(NODES_PATH)):
        _create_synthetic_fallback()
    edges_wgs84 = gpd.read_file(EDGES_PATH)
    nodes_wgs84 = gpd.read_file(NODES_PATH)
    return edges_wgs84, nodes_wgs84


def _prepare_projected_edges(edges_wgs84, nodes_wgs84):
    """将 WGS84 边投影到度量 CRS，返回 (edges_proj, crs_proj)。"""
    # 优先使用 osmnx 自动 UTM 投影；若失败则回退到 EPSG:32649 (UTM 49N)
    try:
        G = ox.graph_from_gdfs(nodes_wgs84, edges_wgs84)
        G_proj = ox.project_graph(G)
        edges_proj = ox.graph_to_gdfs(G_proj, nodes=False, edges=True)
        crs_proj = G_proj.graph['crs']
    except Exception as e:
        print(f'  osmnx 投影失败，使用 EPSG:32649 回退: {e}')
        edges_proj = edges_wgs84.to_crs(epsg=32649)
        crs_proj = edges_proj.crs

    # 规整列并排序，保证数组对齐
    edges_proj = edges_proj.reset_index().sort_values(['u', 'v', 'key']).reset_index(drop=True)
    return edges_proj, crs_proj


def _build_edge_lookup(edges_proj):
    """基于边中点构建 cKDTree，返回搜索所需数组。"""
    mid = edges_proj.geometry.centroid
    xs = mid.x.values
    ys = mid.y.values
    tree = cKDTree(np.column_stack([xs, ys]))
    return {
        'tree': tree,
        'geoms': edges_proj.geometry.values,
        'u': edges_proj['u'].values,
        'v': edges_proj['v'].values,
        'key': edges_proj['key'].values,
    }


# ── GPS streaming ───────────────────────────────────────────────────────────

def _stream_vehicles(path):
    """流式读取 vehicle_data.json，每次 yield (vid, records)。

    数据格式: {"22223": [[time, lon, lat, status, speed], ...], ...}
    通过查找顶层 key 与对应外层数组的结束位置实现增量解析，避免全量加载。
    """
    read_size = 2 * 1024 * 1024
    with open(path, 'r', encoding='utf-8') as f:
        buf = f.read(read_size)
        start = buf.find('{')
        while start == -1:
            more = f.read(read_size)
            if not more:
                return
            buf += more
            start = buf.find('{')
        buf = buf[start + 1:]

        while True:
            m = _VEHICLE_KEY_RE.search(buf)
            if not m:
                more = f.read(read_size)
                if not more:
                    return
                buf += more
                m = _VEHICLE_KEY_RE.search(buf)
                if not m:
                    return

            vid = m.group(1)
            value_start = m.end() - 1  # '[' 位置

            # 查找外层数组结束：']]'' 后紧跟 ',' 或 '}'
            end_pos = None
            pos = value_start
            while True:
                p = buf.find(']]', pos)
                if p == -1:
                    more = f.read(read_size)
                    if not more:
                        break
                    buf += more
                    continue
                after = p + 2
                while after < len(buf) and buf[after] in ' \t\r\n':
                    after += 1
                if after < len(buf) and buf[after] in ',}':
                    end_pos = p + 2
                    break
                pos = p + 2

            if end_pos is None:
                break

            value_str = buf[value_start:end_pos]
            try:
                records = json.loads(value_str)
            except Exception as e:
                print(f'  警告: 车辆 {vid} 解析失败: {e}')
                records = []

            yield vid, records
            buf = buf[end_pos:]


# ── Snapping & accumulation ─────────────────────────────────────────────────

def _snap_points(lons, lats, transformer, tree, edge_geoms, k=K_NEAREST):
    """将 WGS84 经纬度点投影后，用 cKDTree 候选 + shapely 精确距离找最近边索引。"""
    xs, ys = transformer.transform(lons, lats)
    pts = shapely_points(xs, ys)
    _, idxs = tree.query(np.column_stack([xs, ys]), k=k, workers=-1)

    n = len(pts)
    best_idx = np.zeros(n, dtype=np.int64)
    best_dist = np.full(n, np.inf)

    # 若点数不足 k，query 返回一维数组
    if idxs.ndim == 1:
        idxs = idxs.reshape(-1, 1)

    for j in range(min(k, idxs.shape[1])):
        cand = edge_geoms[idxs[:, j]]
        d = shapely_distance(pts, cand)
        mask = d < best_dist
        best_dist[mask] = d[mask]
        best_idx[mask] = idxs[:, j][mask]

    return best_idx


def _process_batch(lons, lats, speeds, transformer, tree, edge_geoms, edge_u, edge_v, edge_key,
                   speed_sum, count):
    """处理一批 GPS 点，更新边速度累积。"""
    best_idx = _snap_points(lons, lats, transformer, tree, edge_geoms)
    for i, speed in enumerate(speeds):
        idx = best_idx[i]
        key = (int(edge_u[idx]), int(edge_v[idx]), int(edge_key[idx]))
        speed_sum[key] += float(speed)
        count[key] += 1


def _accumulate_speeds_from_vehicles(lookup, transformer, sample_rate=SAMPLE_RATE, max_points=None):
    """流式读取 vehicle_data.json，采样并累积车速。"""
    assert_input_exists(VEHICLE_DATA_PATH)
    rng = random.Random(RANDOM_SEED)
    speed_sum = defaultdict(float)
    count = defaultdict(int)

    b = SHENZHEN_BOUNDS
    total = 0
    used = 0
    batch_lons, batch_lats, batch_speeds = [], [], []

    edge_geoms = lookup['geoms']
    edge_u, edge_v, edge_key = lookup['u'], lookup['v'], lookup['key']
    tree = lookup['tree']

    t0 = time.time()
    for vid, records in _stream_vehicles(VEHICLE_DATA_PATH):
        for rec in records:
            total += 1
            if rng.random() > sample_rate:
                continue
            if len(rec) < 5:
                continue
            lon, lat, speed = float(rec[1]), float(rec[2]), float(rec[4])
            if not (b['long_min'] <= lon <= b['long_max'] and b['lat_min'] <= lat <= b['lat_max']):
                continue
            if not (0 <= speed <= SPEED_MAX):
                continue

            batch_lons.append(lon)
            batch_lats.append(lat)
            batch_speeds.append(speed)
            used += 1

            if len(batch_lons) >= BATCH_SIZE:
                _process_batch(
                    np.array(batch_lons), np.array(batch_lats), batch_speeds,
                    transformer, tree, edge_geoms, edge_u, edge_v, edge_key,
                    speed_sum, count,
                )
                batch_lons, batch_lats, batch_speeds = [], [], []

            if max_points and used >= max_points:
                break
        if max_points and used >= max_points:
            break

    if batch_lons:
        _process_batch(
            np.array(batch_lons), np.array(batch_lats), batch_speeds,
            transformer, tree, edge_geoms, edge_u, edge_v, edge_key,
            speed_sum, count,
        )

    print(f'  扫描总 GPS 点数: {total:,}, 有效采样: {used:,}, 耗时: {time.time()-t0:.1f}s')
    return speed_sum, count


def _accumulate_speeds_from_clean_csv(lookup, transformer, sample_rate=SAMPLE_RATE, max_points=1_500_000):
    """从 clean.csv 分块采样并累积车速（vehicle_data.json 的快捷替代）。"""
    assert_input_exists(CLEAN_CSV_PATH)
    rng = random.Random(RANDOM_SEED)
    speed_sum = defaultdict(float)
    count = defaultdict(int)

    b = SHENZHEN_BOUNDS
    used = 0
    batch_lons, batch_lats, batch_speeds = [], [], []

    edge_geoms = lookup['geoms']
    edge_u, edge_v, edge_key = lookup['u'], lookup['v'], lookup['key']
    tree = lookup['tree']

    dtype = {'long': np.float64, 'lati': np.float64, 'speed': np.float64}
    t0 = time.time()
    for chunk in pd.read_csv(CLEAN_CSV_PATH, usecols=['long', 'lati', 'speed'],
                             dtype=dtype, chunksize=200_000):
        for _, row in chunk.iterrows():
            if rng.random() > sample_rate:
                continue
            lon, lat, speed = row['long'], row['lati'], row['speed']
            if not (b['long_min'] <= lon <= b['long_max'] and b['lat_min'] <= lat <= b['lat_max']):
                continue
            if not (0 <= speed <= SPEED_MAX):
                continue

            batch_lons.append(lon)
            batch_lats.append(lat)
            batch_speeds.append(speed)
            used += 1

            if len(batch_lons) >= BATCH_SIZE:
                _process_batch(
                    np.array(batch_lons), np.array(batch_lats), batch_speeds,
                    transformer, tree, edge_geoms, edge_u, edge_v, edge_key,
                    speed_sum, count,
                )
                batch_lons, batch_lats, batch_speeds = [], [], []

            if max_points and used >= max_points:
                break
        if max_points and used >= max_points:
            break

    if batch_lons:
        _process_batch(
            np.array(batch_lons), np.array(batch_lats), batch_speeds,
            transformer, tree, edge_geoms, edge_u, edge_v, edge_key,
            speed_sum, count,
        )

    print(f'  clean.csv 有效采样: {used:,}, 耗时: {time.time()-t0:.1f}s')
    return speed_sum, count


def _compute_road_speeds(speed_sum, count):
    """计算边平均速度并划分拥堵等级。"""
    result = {}
    for key, s in speed_sum.items():
        c = count[key]
        if c == 0:
            continue
        avg = s / c
        if avg > SPEED_LOW_THRESHOLD:
            cong = 'low'
        elif avg >= SPEED_HIGH_THRESHOLD:
            cong = 'medium'
        else:
            cong = 'high'
        edge_id = f"{key[0]}_{key[1]}_{key[2]}"
        result[edge_id] = {
            'speed': round(float(avg), 2),
            'count': int(c),
            'congestion': cong,
        }
    return result


# ── HTML generation ─────────────────────────────────────────────────────────

def _geometry_to_path(geom):
    """将 WGS84 LineString/MultiLineString 转为 [[lat, lon], ...]。"""
    if geom.geom_type == 'LineString':
        coords = list(geom.coords)
    elif geom.geom_type == 'MultiLineString':
        coords = list(geom.geoms[0].coords)
    else:
        return None
    return [[round(float(y), 5), round(float(x), 5)] for x, y in coords]


def _generate_html(edges_wgs84, road_speeds):
    """生成 Baidu Maps 路网拥堵 HTML。"""
    if 'u' not in edges_wgs84.columns:
        edges_wgs84 = edges_wgs84.reset_index()

    edge_geom_map = {}
    for _, row in edges_wgs84.iterrows():
        key = (int(row['u']), int(row['v']), int(row['key']))
        edge_geom_map[key] = row.geometry

    segments = []
    for edge_id, info in road_speeds.items():
        parts = edge_id.split('_')
        if len(parts) != 3:
            continue
        key = (int(parts[0]), int(parts[1]), int(parts[2]))
        geom = edge_geom_map.get(key)
        if geom is None:
            continue
        path = _geometry_to_path(geom)
        if not path:
            continue
        color = COLOR_LOW if info['congestion'] == 'low' else (
            COLOR_MEDIUM if info['congestion'] == 'medium' else COLOR_HIGH)
        segments.append(
            f'    {{path: {json.dumps(path, ensure_ascii=False)}, '
            f'color: "{color}", speed: {info["speed"]}, count: {info["count"]}}}'
        )

    segments_js = '[\n' + ',\n'.join(segments) + '\n  ]'
    n_segments = len(segments)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>深圳路网拥堵分析</title>
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
  #legend {{
    position:absolute; bottom:40px; right:30px; z-index:100;
    background:rgba(255,255,255,.92); padding:14px 18px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:13px/1.7 "Microsoft YaHei",sans-serif;
  }}
  #legend h4 {{ margin-bottom:6px; font-size:14px; }}
  .leg-row {{ display:flex; align-items:center; gap:8px; }}
  .leg-line {{ width:36px; height:5px; border-radius:3px; }}
  #info {{
    position:absolute; bottom:40px; left:30px; z-index:100;
    background:rgba(255,255,255,.88); padding:8px 14px;
    border-radius:6px; box-shadow:0 1px 6px rgba(0,0,0,.12);
    font:12px/1.5 "Microsoft YaHei",sans-serif;
  }}
</style>
</head>
<body>
<div id="map"></div>
<div id="title">深圳路网拥堵分析</div>

<div id="legend">
  <h4>拥堵程度</h4>
  <div class="leg-row"><div class="leg-line" style="background:{COLOR_LOW}"></div> 畅通 &gt;45 km/h</div>
  <div class="leg-row"><div class="leg-line" style="background:{COLOR_MEDIUM}"></div> 缓行 20-45 km/h</div>
  <div class="leg-row"><div class="leg-line" style="background:{COLOR_HIGH}"></div> 拥堵 &lt;20 km/h</div>
</div>

<div id="info">
  路段数: {n_segments:,}<br>
  中心: ({CENTER_LAT}, {CENTER_LON}) | 缩放: {ZOOM}
</div>

<script>
var roadSegments = {segments_js};

function initMap() {{
  var map = new BMap.Map('map');
  var ctr = new BMap.Point({CENTER_LON}, {CENTER_LAT});
  map.centerAndZoom(ctr, {ZOOM});
  map.enableScrollWheelZoom(true);
  map.addControl(new BMap.NavigationControl());
  map.addControl(new BMap.ScaleControl());

  for (var i = 0; i < roadSegments.length; i++) {{
    var seg = roadSegments[i];
    var pts = seg.path.map(function(c) {{ return new BMap.Point(c[1], c[0]); }});
    var poly = new BMap.Polyline(pts, {{
      strokeColor: seg.color,
      strokeWeight: 3,
      strokeOpacity: 0.85
    }});
    map.addOverlay(poly);
  }}
}}
</script>
<script src="https://api.map.baidu.com/api?v=3.0&ak={BAIDU_MAP_API_KEY}&callback=initMap"></script>
</body>
</html>'''
    return html


# ── HTTP server ─────────────────────────────────────────────────────────────

def _serve_html(out_path, port=8080):
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


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='深圳路网拥堵分析')
    parser.add_argument('--serve', action='store_true', help='生成后启动 HTTP 服务器')
    parser.add_argument('--port', type=int, default=8080, help='HTTP 服务器端口（默认 8080）')
    parser.add_argument('--use-clean-csv', action='store_true',
                        help='从 clean.csv 采样而非 vehicle_data.json（更快）')
    parser.add_argument('--sample-rate', type=float, default=SAMPLE_RATE,
                        help=f'采样率（默认 {SAMPLE_RATE}）')
    parser.add_argument('--max-points', type=int, default=None,
                        help='最大处理 GPS 点数（默认无限制）')
    args = parser.parse_args()

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    os.makedirs(NETWORK_DIR, exist_ok=True)
    os.makedirs(FIGURES_DIR, exist_ok=True)

    # 1) 路网
    edges_wgs84, nodes_wgs84 = _load_or_download_network()
    edges_proj, crs_proj = _prepare_projected_edges(edges_wgs84, nodes_wgs84)
    lookup = _build_edge_lookup(edges_proj)
    transformer = pyproj.Transformer.from_crs('EPSG:4326', crs_proj, always_xy=True)
    print(f'  投影 CRS: {crs_proj}')

    # 2) 采样 +  snapping + 累积速度
    print('读取并 snapping GPS 轨迹 ...')
    if args.use_clean_csv:
        speed_sum, count = _accumulate_speeds_from_clean_csv(
            lookup, transformer, sample_rate=args.sample_rate, max_points=args.max_points)
    else:
        speed_sum, count = _accumulate_speeds_from_vehicles(
            lookup, transformer, sample_rate=args.sample_rate, max_points=args.max_points)

    # 3) 计算拥堵
    print('计算边平均速度与拥堵等级 ...')
    road_speeds = _compute_road_speeds(speed_sum, count)
    print(f'  有速度记录的边数: {len(road_speeds):,}')

    with open(ROAD_SPEEDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(road_speeds, f, ensure_ascii=False, indent=2)
    print(f'  已保存: {ROAD_SPEEDS_PATH}')

    # 4) 生成 HTML
    print('生成 Baidu Maps 拥堵可视化 HTML ...')
    html = _generate_html(edges_wgs84, road_speeds)
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  已保存: {HTML_PATH}')

    if args.serve:
        _serve_html(HTML_PATH, port=args.port)
    else:
        print()
        print('提示: 不能直接双击打开，请使用:')
        print(f'   python src/10_路网分析.py --serve')
        print(f'   然后打开 http://localhost:{args.port}/road_congestion.html')


if __name__ == '__main__':
    main()
