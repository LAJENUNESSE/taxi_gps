
"""出租车GPS数据流向图 — 基于百度地图JavaScript API绘制OD流量线

将OD对按网格聚合 → 取Top N流量 → 过滤同格子流向 → 生成standalone HTML
"""

import argparse
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pandas as pd

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.config import (
    BAIDU_MAP_API_KEY,
    DATA_DIR,
    FIGURES_DIR,
    FLOW_GRID_SIZE,
    TOP_FLOWS,
)
from src.utils import assert_input_exists


def _grid_round(val: float, grid: float) -> float:
    return round(val / grid) * grid


def _aggregate_flows(df: pd.DataFrame) -> pd.DataFrame:
    """Grid-aggregate OD coords, count flows per cell pair."""
    print('网格聚合 OD 对 ...')
    df = df.copy()
    for prefix, col_lon, col_lat in [
        ('s', '开始经度', '开始纬度'),
        ('e', '结束经度', '结束纬度'),
    ]:
        df[f'{prefix}_lon'] = df[col_lon].apply(_grid_round, args=(FLOW_GRID_SIZE,))
        df[f'{prefix}_lat'] = df[col_lat].apply(_grid_round, args=(FLOW_GRID_SIZE,))

    flows = (
        df.groupby(['s_lon', 's_lat', 'e_lon', 'e_lat'])
        .size()
        .reset_index(name='count')
        .sort_values('count', ascending=False)
        .reset_index(drop=True)
    )
    print(f'  聚合后 OD 对总数: {len(flows):,}')


    same_grid = (
        (flows['s_lon'] == flows['e_lon'])
        & (flows['s_lat'] == flows['e_lat'])
    )
    n_same = same_grid.sum()
    flows = flows[~same_grid].reset_index(drop=True)
    print(f'  剔除同格子流向: {n_same}')

    top = flows.head(TOP_FLOWS).copy()
    print(f'  Top {TOP_FLOWS} 流量范围: {top["count"].min():,} ~ {top["count"].max():,}')
    return top


def _get_map_center(flows: pd.DataFrame) -> tuple[float, float]:
    lat = pd.concat([flows['s_lat'], flows['e_lat']]).median()
    lon = pd.concat([flows['s_lon'], flows['e_lon']]).median()
    return float(lat), float(lon)


def _build_flow_data_json(flows: pd.DataFrame) -> str:

    flows = flows.sort_values('count', ascending=True).reset_index(drop=True)
    max_c = flows['count'].max()

    rows = []
    for _, r in flows.iterrows():
        weight = r['count'] / max_c
        rows.append(

            f'    {{s:[{r["s_lat"]:.4f},{r["s_lon"]:.4f}],'
            f'e:[{r["e_lat"]:.4f},{r["e_lon"]:.4f}],'
            f'c:{int(r["count"])},w:{weight:.4f}}}'
        )
    return '[\n' + ',\n'.join(rows) + '\n]'


def _generate_html(flows: pd.DataFrame, center_lat: float, center_lon: float) -> str:
    flow_json = _build_flow_data_json(flows)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>深圳出租车OD流向图</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body,#map {{ width:100%; height:100%; overflow:hidden; }}
  #title {{
    position:absolute; top:20px; left:50%; z-index:100;
    transform:translateX(-50%);
    background:rgba(255,255,255,.92); padding:10px 28px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:700 18px/1.4 "Microsoft YaHei",sans-serif;
    pointer-events:none;
    white-space:nowrap;
  }}
  #legend {{
    position:absolute; bottom:40px; right:30px; z-index:100;
    background:rgba(255,255,255,.92); padding:14px 18px;
    border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,.18);
    font:13px/1.7 "Microsoft YaHei",sans-serif;
  }}
  #legend h4 {{ margin-bottom:4px; font-size:14px; }}
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
<div id="title">深圳出租车OD流向图</div>
<div id="legend">
  <h4>流向数量</h4>
  <div class="leg-row"><div class="leg-line" style="background:#1577FF"></div> 少</div>
  <div class="leg-row"><div class="leg-line" style="background:#FFAA00"></div> 中</div>
  <div class="leg-row"><div class="leg-line" style="background:#DC143C"></div> 多</div>
</div>
<div id="info">Top {TOP_FLOWS} OD 流向 | 网格 {FLOW_GRID_SIZE}°</div>

<script>
var flowData = {flow_json};

function weightToHex(w) {{
  // blue(0,100,255) -> orange(255,170,0) -> red(220,20,60)
  var r,g,b;
  if (w < 0.5) {{
    var t = w / 0.5;
    r = Math.round(  0 + t*255);
    g = Math.round(100 + t* 70);
    b = Math.round(255 - t*255);
  }} else {{
    var t = (w - 0.5) / 0.5;
    r = Math.round(255 - t* 35);
    g = Math.round(170 - t*150);
    b = Math.round(  0 + t* 60);
  }}
  return '#' + [r,g,b].map(function(c){{
    return ('0' + c.toString(16)).slice(-2);
  }}).join('');
}}

function initMap() {{
  var map = new BMap.Map('map');
  var ctr = new BMap.Point({center_lon:.4f}, {center_lat:.4f});
  map.centerAndZoom(ctr, 12);
  map.enableScrollWheelZoom(true);
  map.addControl(new BMap.NavigationControl());
  map.addControl(new BMap.ScaleControl());

  for (var i = 0; i < flowData.length; i++) {{
    var f = flowData[i];
    var pts = [
      new BMap.Point(f.s[1], f.s[0]),
      new BMap.Point(f.e[1], f.e[0])
    ];
    var w = f.w;
    var poly = new BMap.Polyline(pts, {{
      strokeColor: weightToHex(w),
      strokeWeight: Math.max(1.5, w * 7),
      strokeOpacity: 0.3 + w * 0.55
    }});
    map.addOverlay(poly);
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
    parser = argparse.ArgumentParser(description='生成百度地图 OD 流向图')
    parser.add_argument('--serve', action='store_true',
                        help='生成后启动 HTTP 服务器')
    parser.add_argument('--port', type=int, default=8080,
                        help='HTTP 服务器端口（默认 8080）')
    args = parser.parse_args()

    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(orders_path)

    print('读取 OD 数据 ...')
    df = pd.read_csv(orders_path)
    print(f'  行数: {len(df):,}')

    flows = _aggregate_flows(df)

    center_lat, center_lon = _get_map_center(flows)
    print(f'  地图中心: ({center_lat:.4f}, {center_lon:.4f})')

    html = _generate_html(flows, center_lat, center_lon)

    os.makedirs(FIGURES_DIR, exist_ok=True)
    out_path = os.path.join(FIGURES_DIR, 'baidu_flow_map.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n已保存: {out_path}')

    if args.serve:
        _serve_html(out_path, port=args.port)
    else:
        print()
        print('提示: 不能直接双击打开，请使用:')
        print(f'   python src/06_百度地图流向.py --serve')
        print(f'   然后打开 http://localhost:8080/baidu_flow_map.html')


if __name__ == '__main__':
    main()
