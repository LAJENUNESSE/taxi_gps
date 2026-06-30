"""出租车GPS数据 — 热力图与统计分析

功能:
  1. 静态热力图 (车辆位置 + 上客点 DBSCAN 聚类)
  2. 动态热力图 (多粒度时间片: 1/15/30/60min → JSON + GIF)
  3. DBSCAN 上客点聚类
  4. 载客率统计 (小时级)
  5. 车辆里程统计
  6. 订单时段/时长/距离/速度统计

数据来源:
  - 静态热力图(车辆位置): clean.csv 载客状态 GPS 点 (每 500 点采样 1 个)
  - 静态热力图(上客点): orders.csv DBSCAN 聚类中心 + count 权重
  - 动态热力图: orders.csv 上客点, 按时间窗分桶 + 网格聚合
  - DBSCAN: orders.csv 上客点经纬度
  - 载客率/里程: clean.csv 全量 GPS 点 chunked 读取
  - 订单统计: orders.csv OD 对

策略: clean.csv 只读一次 (chunked)，避免分析脚本 3 遍读取的瓶颈。

距离计算:
  - haversine_km (src/utils.py): 大圆距离, R=6371km
  - 异常漂移过滤: >5km 的段跳过

聚合粒度:
  - 订单时段: 小时 / 分钟 / 15 分钟
  - 动态热力图: 1min / 15min / 30min / 60min
  - DBSCAN: eps=0.004° (~400m), min_samples=50
  - 网格: 0.001° (~100m)

输出:
  - data/*.csv  (统计结果)
  - data/time_slices_*.json (动态热力图时间片)
  - output/figures/*.png  (静态图)
  - output/figures/*.gif  (动态热力图)
"""

import json
import logging
import os
import sys
import shutil
import tempfile
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from PIL import Image
from sklearn.cluster import DBSCAN

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (
    DATA_DIR, FIGURES_DIR, SHENZHEN_BOUNDS,
    DBSCAN_EPS, DBSCAN_MIN_SAMPLES,
    DISTANCE_SHORT, DISTANCE_LONG,
)
from src.utils import setup_matplotlib_cjk, haversine_km, assert_input_exists

setup_matplotlib_cjk()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('heatmap_analysis')

HEAT_GRID = 0.001  # 网格大小 (度), ~100m
MAX_POINTS_PER_SLICE = 20000


# ───────────────────────── helpers ─────────────────────────

def _save_fig(fig, filename: str) -> str:
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def _fmt_size(path: str) -> str:
    return f'{os.path.getsize(path) / 1024:.1f} KB'


def _load_orders() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(path)
    print(f'  读取: {path}')
    df = pd.read_csv(path)
    print(f'  行数: {len(df):,}')
    df['开始时间'] = pd.to_datetime(df['开始时间'])
    df['结束时间'] = pd.to_datetime(df['结束时间'])
    df['小时'] = df['开始时间'].dt.hour
    return df


# ═══════════════════ 一、订单统计分析 ═══════════════════

def order_hourly_stats(df: pd.DataFrame):
    """4.2 订单时段统计 → data/hourly_orders.csv"""
    print('\n--- 4.2 订单时段统计 ---')
    df_hourcnt = df.groupby('小时')['车辆id'].count().rename('数量').reset_index()
    all_hours = pd.DataFrame({'小时': range(24)})
    df_hourcnt = all_hours.merge(df_hourcnt, on='小时', how='left').fillna(0)
    df_hourcnt['数量'] = df_hourcnt['数量'].astype(int)
    path = os.path.join(DATA_DIR, 'hourly_orders.csv')
    df_hourcnt.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_hourcnt)})')
    return df_hourcnt


def order_minutely_stats(df: pd.DataFrame):
    """4.2b 每分钟打车数量 → data/minutely_orders.csv"""
    print('\n--- 4.2b 每分钟打车数量 ---')
    df_m = df.copy()
    df_m['O_time'] = df_m['开始时间'].dt.floor('min')
    df_minutely = df_m.groupby('O_time')['车辆id'].count().reset_index()
    df_minutely.columns = ['O_time', 'count']
    path = os.path.join(DATA_DIR, 'minutely_orders.csv')
    df_minutely.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_minutely)})')


def order_quarter_hourly_stats(df: pd.DataFrame):
    """4.2c 每15分钟打车数量 → data/quarter_hour_orders.csv"""
    print('\n--- 4.2c 每15分钟打车数量 ---')
    df_q = df.copy()
    df_q['O_time'] = df_q['开始时间'].dt.floor('15min')
    df_qh = df_q.groupby('O_time')['车辆id'].count().reset_index()
    df_qh.columns = ['O_time', 'count']
    path = os.path.join(DATA_DIR, 'quarter_hour_orders.csv')
    df_qh.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_qh)})')


def order_duration_stats(df: pd.DataFrame):
    """4.3 订单时长分布 → data/order_duration_stats.csv"""
    print('\n--- 4.3 订单时长分布 ---')
    df = df.copy()
    df['订单时长_min'] = (df['结束时间'] - df['开始时间']).dt.total_seconds() / 60
    df_dur = df.groupby('小时')['订单时长_min'].agg(
        mean='mean', median='median', count='count',
    ).reset_index()
    df_dur.columns = ['小时', 'mean_min', 'median_min', 'count']
    path = os.path.join(DATA_DIR, 'order_duration_stats.csv')
    df_dur.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_dur)})')


def trip_distance_stats(df: pd.DataFrame):
    """4.4 出行距离划分 → data/JNLuC.csv"""
    print('\n--- 4.4 出行距离划分 ---')
    df = df.copy()
    df['距离类型'] = pd.cut(
        df['OD_Dis_km'],
        bins=[0, DISTANCE_SHORT, DISTANCE_LONG, float('inf')],
        labels=['near', 'middle', 'far'],
    )
    dist_counts = df['距离类型'].value_counts()
    df_jnluc = pd.DataFrame({
        'day': [1],
        'near': [int(dist_counts.get('near', 0))],
        'middle': [int(dist_counts.get('middle', 0))],
        'far': [int(dist_counts.get('far', 0))],
    })
    path = os.path.join(DATA_DIR, 'JNLuC.csv')
    df_jnluc.to_csv(path, index=False)
    print(f'  保存: {path}')
    print(f'  near={df_jnluc.iloc[0]["near"]}, middle={df_jnluc.iloc[0]["middle"]}, far={df_jnluc.iloc[0]["far"]}')


def avg_speed_stats(df: pd.DataFrame):
    """4.5 订单平均速度 → data/avg_speed_by_hour.csv"""
    print('\n--- 4.5 订单平均速度 ---')
    df = df.copy()
    df['avg_speed'] = df['OD_Dis_km'] / (df['OD_TIME_s'] / 3600)
    valid = df['avg_speed'].notna() & np.isfinite(df['avg_speed']) & (df['avg_speed'] > 0)
    df_speed = df[valid]
    df_sh = df_speed.groupby('小时')['avg_speed'].mean().reset_index()
    df_sh.columns = ['O_time', 'sudu']
    path = os.path.join(DATA_DIR, 'avg_speed_by_hour.csv')
    df_sh.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_sh)})')


def dbscan_clustering(df: pd.DataFrame):
    """4.1 DBSCAN 上客点聚类 → data/clustered_hotspots.csv"""
    print('\n--- 4.1 DBSCAN 上客点聚类 ---')
    pickup_points = df[['开始纬度', '开始经度']].values
    print(f'  上客点数: {len(pickup_points):,}')
    print(f'  eps={DBSCAN_EPS}, min_samples={DBSCAN_MIN_SAMPLES}')

    db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES)
    labels = db.fit_predict(pickup_points)

    n_noise = int((labels == -1).sum())
    n_clustered = int((labels != -1).sum())
    unique_labels = set(labels)
    n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    print(f'  簇数量: {n_clusters}')
    print(f'  噪声点比例: {n_noise / max(len(labels), 1):.2%} ({n_noise:,}/{len(labels):,})')

    cluster_data = []
    for cluster_id in sorted(unique_labels):
        if cluster_id == -1:
            continue
        mask = labels == cluster_id
        points = pickup_points[mask]
        center_lat = float(points[:, 0].mean())
        center_lng = float(points[:, 1].mean())
        count = int(mask.sum())
        cluster_data.append({
            'lat': center_lat, 'lng': center_lng,
            'count': count, 'time': '2026-06-22',
        })

    df_clusters = pd.DataFrame(cluster_data)
    path = os.path.join(DATA_DIR, 'clustered_hotspots.csv')
    df_clusters.to_csv(path, index=False)
    print(f'  保存: {path}  (行数={len(df_clusters)})')
    return df_clusters


# ═══════════════════ 二、clean.csv 单遍分析 ═══════════════════

def analyze_clean_once():
    """单遍读取 clean.csv (chunked)，同时产出 4.6/4.7/4.8 及车辆位置采样。"""
    clean_path = os.path.join(DATA_DIR, 'clean.csv')
    assert_input_exists(clean_path)

    print('\n--- 读取 clean.csv (单遍 chunked) ---')
    print(f'  路径: {clean_path}')

    # 4.6 载客出租车 → occupied_taxis.csv
    occupied_per_minute: dict = defaultdict(set)
    # 4.7 载客率
    occ_count: dict[int, int] = defaultdict(int)
    total_count: dict[int, int] = defaultdict(int)
    # 4.8 里程
    vehicle_mileage: dict[str, dict] = {}
    last_point: dict[str, tuple[float, float]] = {}
    # 车辆位置采样 (载客状态)
    veh_sample_lons: list[float] = []
    veh_sample_lats: list[float] = []
    VEH_SAMPLE_RATE = 500
    VEH_SAMPLE_MAX = 80000
    veh_row_idx = 0

    chunk_iter = pd.read_csv(
        clean_path, chunksize=500_000,
        usecols=['id', 'time', 'long', 'lati', 'status'],
        dtype={'id': 'int32', 'status': 'int8',
               'long': 'float32', 'lati': 'float32', 'time': 'str'},
    )
    processed = 0
    for chunk in chunk_iter:
        processed += len(chunk)

        # ── 4.6 载客出租车 ──
        mask_occ = chunk['status'] == 1
        if mask_occ.any():
            chunk_occ = chunk.loc[mask_occ, ['id', 'time']]
            chunk_occ['time'] = pd.to_datetime(chunk_occ['time'], errors='coerce')
            chunk_occ['time_minute'] = chunk_occ['time'].dt.floor('min')
            for minute, group in chunk_occ.groupby('time_minute'):
                occupied_per_minute[minute].update(group['id'].unique())

        # ── 4.7 载客率 ──
        t = pd.to_datetime(chunk['time'], errors='coerce')
        h = t.dt.hour
        for hr in range(24):
            mask_h = h == hr
            total_count[hr] += int(mask_h.sum())
            occ_count[hr] += int((mask_h & (chunk['status'] == 1)).sum())

        # ── 4.8 里程 ──
        for vid, group in chunk.groupby('id'):
            vk = str(int(vid))
            if vk not in vehicle_mileage:
                vehicle_mileage[vk] = {'总里程': 0.0, '载客里程': 0.0, '空载里程': 0.0}
            lats_arr = group['lati'].astype(float).values
            lons_arr = group['long'].astype(float).values
            status_arr = group['status'].astype(int).values
            n = len(lats_arr)

            if vk in last_point:
                plati, plon = last_point[vk]
                seg = haversine_km(plati, plon, lats_arr[0], lons_arr[0])
                if seg <= 5.0:
                    vehicle_mileage[vk]['总里程'] += seg
                    if status_arr[0] == 1:
                        vehicle_mileage[vk]['载客里程'] += seg
                    else:
                        vehicle_mileage[vk]['空载里程'] += seg

            for i in range(n - 1):
                seg = haversine_km(lats_arr[i], lons_arr[i], lats_arr[i + 1], lons_arr[i + 1])
                if seg > 5.0:
                    continue
                vehicle_mileage[vk]['总里程'] += seg
                if status_arr[i + 1] == 1:
                    vehicle_mileage[vk]['载客里程'] += seg
                else:
                    vehicle_mileage[vk]['空载里程'] += seg

            last_point[vk] = (float(lats_arr[-1]), float(lons_arr[-1]))

        # ── 车辆位置采样 ──
        if len(veh_sample_lons) < VEH_SAMPLE_MAX:
            occ_rows = chunk[chunk['status'] == 1]
            for _, row in occ_rows.iterrows():
                if veh_row_idx % VEH_SAMPLE_RATE == 0:
                    veh_sample_lons.append(row['long'])
                    veh_sample_lats.append(row['lati'])
                    if len(veh_sample_lons) >= VEH_SAMPLE_MAX:
                        break
                veh_row_idx += 1

        if processed % 5_000_000 == 0:
            print(f'  已处理: {processed:,} 行 ...')

    print(f'  总处理行数: {processed:,}')

    # ── 保存 4.6 ——
    print('\n--- 4.6 载客出租车数量统计 ---')
    df_occupied = pd.DataFrame([
        {'TIME': str(t), 'number': len(ids)}
        for t, ids in sorted(occupied_per_minute.items())
    ])
    occ_path = os.path.join(DATA_DIR, 'occupied_taxis.csv')
    df_occupied.to_csv(occ_path, index=False)
    print(f'  保存: {occ_path}  (行数={len(df_occupied)})')

    # ── 保存 4.7 ——
    print('\n--- 4.7 载客率统计 ---')
    df_occ_rate = pd.DataFrame([
        {'小时': h, '总GPS点数': total_count[h], '载客GPS点数': occ_count[h],
         '载客率': round(occ_count[h] / total_count[h], 4) if total_count[h] > 0 else 0.0}
        for h in range(24)
    ])
    occ_rate_path = os.path.join(DATA_DIR, 'occupancy_rate.csv')
    df_occ_rate.to_csv(occ_rate_path, index=False)
    print(f'  保存: {occ_rate_path}  (行数={len(df_occ_rate)})')
    for _, r in df_occ_rate.iterrows():
        print(f'    {int(r["小时"]):02d}:00  载客率={r["载客率"]:.2%}  '
              f'(载客{r["载客GPS点数"]:,} / 总{r["总GPS点数"]:,})')

    # ── 保存 4.8 ——
    print('\n--- 4.8 车辆里程统计 ---')
    df_mileage = pd.DataFrame([
        {'车辆id': vid, '总里程_km': round(v['总里程'], 2),
         '载客里程_km': round(v['载客里程'], 2),
         '空载里程_km': round(v['空载里程'], 2)}
        for vid, v in vehicle_mileage.items()
    ]).sort_values('总里程_km', ascending=False)

    mil_path = os.path.join(DATA_DIR, 'vehicle_mileage.csv')
    df_mileage.to_csv(mil_path, index=False)
    print(f'  保存: {mil_path}  (行数={len(df_mileage)})')
    total_km = df_mileage['总里程_km'].sum()
    occ_km = df_mileage['载客里程_km'].sum()
    empty_km = df_mileage['空载里程_km'].sum()
    n_veh = len(df_mileage)
    print(f'  车辆数: {n_veh:,}')
    print(f'  总里程: {total_km:,.0f} km')
    print(f'  载客里程: {occ_km:,.0f} km ({occ_km/total_km*100:.1f}%)')
    print(f'  空载里程: {empty_km:,.0f} km ({empty_km/total_km*100:.1f}%)')
    print(f'  单车日均里程: {total_km/n_veh:.0f} km')
    print(f'  全天平均载客率(按里程): {occ_km/total_km*100:.1f}%')

    return veh_sample_lons, veh_sample_lats


# ═══════════════════ 三、静态热力图 ═══════════════════

def plot_vehicle_position_heatmap(lons: list, lats: list):
    """车辆位置热力图 (载客状态采样点) → output/figures/vehicle_position_heatmap.png"""
    print('\n--- 车辆位置热力图 ---')
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter(lons, lats, s=1, alpha=0.3, c='steelblue')
    ax.set_xlim(SHENZHEN_BOUNDS['long_min'], SHENZHEN_BOUNDS['long_max'])
    ax.set_ylim(SHENZHEN_BOUNDS['lat_min'], SHENZHEN_BOUNDS['lat_max'])
    ax.set_xlabel('经度')
    ax.set_ylabel('纬度')
    ax.set_title('车辆位置热力分布（载客状态采样）')
    ax.grid(alpha=0.3)
    path = _save_fig(fig, 'vehicle_position_heatmap.png')
    print(f'  保存: {path} ({_fmt_size(path)})')


def plot_static_heatmap(df_clusters: pd.DataFrame):
    """上客点 DBSCAN 聚类热力图 → output/figures/static_heatmap.png"""
    print('\n--- 上客点 DBSCAN 热力图 ---')
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(
        df_clusters['lng'], df_clusters['lat'],
        c=df_clusters['count'], s=np.log1p(df_clusters['count']) * 8,
        cmap='YlOrRd', alpha=0.8, edgecolors='black', linewidths=0.5,
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label('热度 (count)')
    ax.set_xlabel('经度')
    ax.set_ylabel('纬度')
    ax.set_title('上客点 DBSCAN 聚类热力图')
    ax.grid(alpha=0.3)
    path = _save_fig(fig, 'static_heatmap.png')
    print(f'  保存: {path} ({_fmt_size(path)})')


# ═══════════════════ 四、动态热力图 —— 多粒度时间片 ═══════════════════

GRID_SIZE = 0.001  # ~100m


def _build_time_slices(df: pd.DataFrame, agg_minutes: int) -> dict:
    """构建时间片列表.

    数据来源: orders.csv 上客点 (开始经度/开始纬度/开始时间)
    聚合粒度: agg_minutes 分钟
    网格大小: 0.001° (~100m)
    输出结构: {
        'agg_minutes': int,
        'total_slices': int,
        'max_weight': int,
        'grid_size': float,
        'data_source': str,
        'slices': [
            {
                'slot': int,
                'start': 'HH:MM',
                'end': 'HH:MM',
                'points': [[lng, lat, weight], ...],  # [lon, lat, count]
            },
            ...
        ],
    }
    """
    df = df.copy()
    minutes_of_day = df['开始时间'].dt.hour * 60 + df['开始时间'].dt.minute
    df['时间窗'] = (minutes_of_day // agg_minutes).astype(int)

    df['g_lon'] = (df['开始经度'] / GRID_SIZE).round().astype('int32') * GRID_SIZE
    df['g_lat'] = (df['开始纬度'] / GRID_SIZE).round().astype('int32') * GRID_SIZE

    agg = (
        df.groupby(['时间窗', 'g_lon', 'g_lat'])
        .size()
        .reset_index(name='weight')
        .sort_values('weight', ascending=False)
    )

    num_slots = 1440 // agg_minutes
    slices = []
    global_max = 0
    total_cells = 0

    for slot_idx in range(num_slots):
        sub = agg[agg['时间窗'] == slot_idx].head(MAX_POINTS_PER_SLICE)
        points = [
            [round(float(r['g_lon']), 4), round(float(r['g_lat']), 4), int(r['weight'])]
            for _, r in sub.iterrows()
        ]
        start_min = slot_idx * agg_minutes
        end_min = start_min + agg_minutes
        slices.append({
            'slot': slot_idx,
            'start': f'{start_min // 60:02d}:{start_min % 60:02d}',
            'end': f'{end_min // 60:02d}:{end_min % 60:02d}',
            'points': points,
        })
        if points:
            global_max = max(global_max, max(p[2] for p in points))
        total_cells += len(points)

    log.info('  时间片数=%d, 网格单元总数=%d, 最大权重=%d',
             num_slots, total_cells, global_max)

    return {
        'agg_minutes': agg_minutes,
        'total_slices': num_slots,
        'max_weight': global_max,
        'grid_size': GRID_SIZE,
        'data_source': 'orders.csv 上客点',
        'slices': slices,
    }


def _export_time_slices_json(payload: dict, suffix: str) -> str:
    """导出时间片数据为 JSON 文件. 格式: [lat, lon, weight] 列表."""
    os.makedirs(DATA_DIR, exist_ok=True)
    filename = f'time_slices_{suffix}.json'
    path = os.path.join(DATA_DIR, filename)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info('  保存时间片JSON: %s (%s)', path, _fmt_size(path))
    return path


def _generate_time_slice_gif(payload: dict, suffix: str) -> str:
    """从时间片数据生成动态热力图 GIF."""
    slices = payload['slices']
    num_slots = len(slices)
    agg_minutes = payload['agg_minutes']
    global_max = payload['max_weight'] or 1

    os.makedirs(FIGURES_DIR, exist_ok=True)
    gif_path = os.path.join(FIGURES_DIR, f'dynamic_heatmap_{suffix}.gif')
    tmp_dir = tempfile.mkdtemp(prefix=f'heatmap_{suffix}_')
    frames = []

    # 分钟级降采样
    if agg_minutes <= 1:
        step = 15
    else:
        step = 1

    for idx in range(0, num_slots, step):
        s = slices[idx]
        points = s['points']
        if not points:
            continue

        fig, ax = plt.subplots(figsize=(8, 6))
        lons = [p[0] for p in points]
        lats = [p[1] for p in points]
        weights = np.array([p[2] for p in points])

        sizes = np.clip(weights / global_max * 60, 1, 80)
        colors = np.clip(weights / global_max, 0.05, 1.0)

        ax.scatter(lons, lats, s=sizes, c=colors, cmap='YlOrRd',
                   alpha=0.6, edgecolors='none')
        ax.set_xlim(SHENZHEN_BOUNDS['long_min'], SHENZHEN_BOUNDS['long_max'])
        ax.set_ylim(SHENZHEN_BOUNDS['lat_min'], SHENZHEN_BOUNDS['lat_max'])
        ax.set_xlabel('经度')
        ax.set_ylabel('纬度')
        ax.set_title(f'上客点热力 {s["start"]}-{s["end"]} ({agg_minutes}min聚合)',
                     fontsize=14)
        ax.grid(alpha=0.3)

        tmp_path = os.path.join(tmp_dir, f'frame_{idx:04d}.png')
        fig.savefig(tmp_path, dpi=80, bbox_inches='tight')
        plt.close(fig)
        img = Image.open(tmp_path)
        img.load()
        frames.append(img)

    if not frames:
        log.warning('无有效帧，未生成GIF')
        shutil.rmtree(tmp_dir)
        return ''

    frames[0].save(
        gif_path, save_all=True,
        append_images=frames[1:],
        duration=200 if agg_minutes <= 1 else 300,
        loop=0,
    )
    for img in frames:
        img.close()
    shutil.rmtree(tmp_dir)

    log.info('  保存动态热力图GIF: %s (%s, %d帧)', gif_path, _fmt_size(gif_path), len(frames))
    return gif_path


def build_dynamic_heatmaps(df_orders: pd.DataFrame):
    """生成多粒度动态热力图 (1/15/30/60 min) JSON + GIF."""
    granularities = [
        (1, 'minute'),
        (15, '15min'),
        (30, '30min'),
        (60, '60min'),
    ]
    for agg_min, suffix in granularities:
        log.info('动态热力图: %s (%dmin聚合)', suffix, agg_min)
        log.info('  数据来源: orders.csv 上客点')
        log.info('  聚合粒度: %d 分钟', agg_min)
        log.info('  网格大小: %.3f° (~%dm)', GRID_SIZE, int(GRID_SIZE * 111000))

        payload = _build_time_slices(df_orders, agg_min)
        _export_time_slices_json(payload, suffix)
        _generate_time_slice_gif(payload, suffix)


# ═══════════════════ 五、静态图表 (由已生成的 CSV 绘制) ═══════════════════

def plot_hourly_orders():
    path = os.path.join(DATA_DIR, 'hourly_orders.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(df['小时'], df['数量'], color='steelblue', alpha=0.6, label='订单数量')
    ax.plot(df['小时'], df['数量'], color='crimson', marker='o', linewidth=2, label='趋势')
    ax.set_xlabel('小时')
    ax.set_ylabel('数量')
    ax.set_title('出行小时数量统计')
    ax.set_xticks(range(0, 24))
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    return _save_fig(fig, 'hourly_orders.png')


def plot_order_duration_boxplot():
    path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    df['开始时间'] = pd.to_datetime(df['开始时间'])
    df['结束时间'] = pd.to_datetime(df['结束时间'])
    df['小时'] = df['开始时间'].dt.hour
    df['订单时长(分钟)'] = (df['结束时间'] - df['开始时间']).dt.total_seconds() / 60
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.boxplot(x='小时', y='订单时长(分钟)', data=df, ax=ax, color='lightblue')
    ax.set_ylim(0, 60)
    ax.set_xlabel('小时')
    ax.set_ylabel('订单时长(分钟)')
    ax.set_title('各时段订单时长分布')
    ax.grid(axis='y', alpha=0.3)
    return _save_fig(fig, 'order_duration_boxplot.png')


def plot_occupied_taxis():
    path = os.path.join(DATA_DIR, 'occupied_taxis.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    df['TIME'] = pd.to_datetime(df['TIME'])
    df_sampled = df.iloc[::30].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(df_sampled['TIME'], df_sampled['number'], color='darkgreen', linewidth=1.5)
    ax.fill_between(df_sampled['TIME'], df_sampled['number'], alpha=0.2, color='darkgreen')
    ax.set_xlabel('时间')
    ax.set_ylabel('载客数量')
    ax.set_title('载客出租车数量变化')
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save_fig(fig, 'occupied_taxis.png')


def plot_trip_distance():
    path = os.path.join(DATA_DIR, 'JNLuC.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    near = int(df['near'].sum())
    middle = int(df['middle'].sum())
    far = int(df['far'].sum())
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.pie(
        [near, middle, far],
        labels=['短途(<4km)', '中途(4-8km)', '长途(>8km)'],
        autopct='%1.1f%%',
        colors=['#4CAF50', '#FF9800', '#f44336'],
        explode=(0.03, 0.03, 0.03),
        startangle=90,
    )
    ax.set_title('出行距离划分')
    return _save_fig(fig, 'trip_distance.png')


def plot_avg_speed():
    path = os.path.join(DATA_DIR, 'avg_speed_by_hour.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df['O_time'], df['sudu'], color='darkorange', marker='s', linewidth=2, markersize=6)
    ax.fill_between(df['O_time'], df['sudu'], alpha=0.2, color='darkorange')
    ax.set_xlabel('时段(小时)')
    ax.set_ylabel('平均速度(km/h)')
    ax.set_title('各时段道路平均速度')
    ax.set_xticks(range(0, 24))
    ax.grid(alpha=0.3)
    return _save_fig(fig, 'avg_speed.png')


def plot_heatmap_slices():
    path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    df['开始时间'] = pd.to_datetime(df['开始时间'])
    minutes_of_day = df['开始时间'].dt.hour * 60 + df['开始时间'].dt.minute
    df['时间窗'] = (minutes_of_day // 15).astype(int)

    fig, axes = plt.subplots(8, 12, figsize=(24, 16))
    axes_flat = axes.flatten()
    for i in range(96):
        ax = axes_flat[i]
        sub = df[df['时间窗'] == i]
        start_min = i * 15
        end_min = (i + 1) * 15
        label = f'{start_min // 60:02d}:{start_min % 60:02d}-{end_min // 60:02d}:{end_min % 60:02d}'
        if not sub.empty:
            ax.scatter(sub['开始经度'], sub['开始纬度'], s=1, alpha=0.3, c='red')
        ax.set_xlim(SHENZHEN_BOUNDS['long_min'], SHENZHEN_BOUNDS['long_max'])
        ax.set_ylim(SHENZHEN_BOUNDS['lat_min'], SHENZHEN_BOUNDS['lat_max'])
        ax.set_title(label, fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle('15分钟上客点热力切片', fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    return _save_fig(fig, 'heatmap_slices.png')


def plot_occupancy_rate():
    path = os.path.join(DATA_DIR, 'occupancy_rate.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.bar(df['小时'], df['载客率'], color='steelblue', alpha=0.5, label='载客率')
    ax1.plot(df['小时'], df['载客率'], color='crimson', marker='o', linewidth=2, label='趋势')
    ax1.set_xlabel('小时')
    ax1.set_ylabel('载客率', color='steelblue')
    ax1.set_ylim(0, 1)
    ax1.set_xticks(range(0, 24))
    ax1.tick_params(axis='y', labelcolor='steelblue')
    ax1.grid(axis='y', alpha=0.3)
    ax2 = ax1.twinx()
    ax2.plot(df['小时'], df['载客GPS点数'] / 1000, color='darkgreen',
             marker='s', linewidth=1.5, label='载客GPS点数(千)')
    ax2.set_ylabel('载客GPS点数(千)', color='darkgreen')
    ax2.tick_params(axis='y', labelcolor='darkgreen')
    ax1.set_title('出租车载客率变化（小时级）')
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    return _save_fig(fig, 'occupancy_rate.png')


def plot_vehicle_mileage():
    path = os.path.join(DATA_DIR, 'vehicle_mileage.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    total = df['总里程_km'].sum()
    occupied = df['载客里程_km'].sum()
    empty = df['空载里程_km'].sum()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    categories = ['总里程', '载客里程', '空载里程']
    values = [total, occupied, empty]
    colors = ['#4682B4', '#4CAF50', '#FF9800']
    bars = ax1.bar(categories, values, color=colors, alpha=0.8, width=0.5)
    for bar, val in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + total * 0.01,
                 f'{val:,.0f} km\n({val/total*100:.1f}%)',
                 ha='center', va='bottom', fontsize=10)
    ax1.set_ylabel('里程 (km)')
    ax1.set_title('车辆全天里程统计')
    mean_val = df['总里程_km'].mean()
    median_val = df['总里程_km'].median()
    ax2.hist(df['总里程_km'].clip(0, 800), bins=40, color='steelblue',
             alpha=0.7, edgecolor='white')
    ax2.axvline(mean_val, color='crimson', linestyle='--', linewidth=1.5,
                label=f'均值={mean_val:.0f} km')
    ax2.axvline(median_val, color='darkgreen', linestyle='--', linewidth=1.5,
                label=f'中位数={median_val:.0f} km')
    ax2.set_xlabel('单车总里程 (km)')
    ax2.set_ylabel('车辆数')
    ax2.set_title('单车总里程分布')
    ax2.legend()
    fig.suptitle(f'车辆里程统计 (n={len(df):,})', fontsize=14)
    plt.tight_layout()
    return _save_fig(fig, 'vehicle_mileage.png')


# ═══════════════════ main ═══════════════════

def main():
    log.info('=' * 60)
    log.info('热力图与统计分析')
    log.info('=' * 60)

    # ── 一、订单统计 ──
    log.info('')
    log.info('>>> 阶段一: 订单统计分析 (orders.csv) <<<')
    log.info('数据来源: orders.csv (OD对)')
    log.info('距离计算: haversine_km, R=6371km')
    log.info('异常过滤: OD_TIME_s<=0 or OD_Dis_km<=0 删除')
    log.info('距离划分: 短途<%dkm, 中途%d-%dkm, 长途>%dkm',
             DISTANCE_SHORT, DISTANCE_SHORT, DISTANCE_LONG, DISTANCE_LONG)

    df_orders = _load_orders()
    total_od = len(df_orders)

    df_hourcnt = order_hourly_stats(df_orders)
    order_minutely_stats(df_orders)
    order_quarter_hourly_stats(df_orders)
    order_duration_stats(df_orders)
    trip_distance_stats(df_orders)
    avg_speed_stats(df_orders)
    df_clusters = dbscan_clustering(df_orders)

    # ── 验证 ──
    hourly_sum = int(df_hourcnt['数量'].sum())
    match = '✓' if hourly_sum == total_od else '✗'
    log.info('验证: 时段统计总和=%d == OD对总数=%d %s', hourly_sum, total_od, match)

    # ── 二、clean.csv 单遍分析 ──
    log.info('')
    log.info('>>> 阶段二: clean.csv 单遍分析 <<<')
    log.info('数据来源: clean.csv (全量GPS点, chunked读取)')
    log.info('统计口径: 载客率=status==1点数/总点数 (小时级)')
    log.info('          里程=相邻GPS点haversine逐段累加, >5km跳点忽略')
    log.info('          载客车=每分钟独立车辆数')
    log.info('          车辆位置采样=载客状态每500点采1个, 上限8万')
    veh_lons, veh_lats = analyze_clean_once()

    # ── 三、静态热力图 ──
    log.info('')
    log.info('>>> 阶段三: 静态热力图 <<<')
    log.info('车辆位置热力图 数据来源: clean.csv 载客状态GPS点 (采样)')
    log.info('上客点热力图    数据来源: orders.csv DBSCAN聚类中心+权重')
    plot_vehicle_position_heatmap(veh_lons, veh_lats)
    plot_static_heatmap(df_clusters)

    # ── 四、动态热力图 (多粒度) ──
    log.info('')
    log.info('>>> 阶段四: 动态热力图 (多粒度) <<<')
    log.info('数据来源: orders.csv 上客点')
    log.info('网格大小: %.3f° (~%dm)', GRID_SIZE, int(GRID_SIZE * 111000))
    log.info('输出格式: JSON时间片列表 + GIF')
    log.info('时间片结构: [{slot, start, end, points:[[lng,lat,weight],...]}]')
    build_dynamic_heatmaps(df_orders)

    # ── 五、静态图表 ──
    log.info('')
    log.info('>>> 阶段五: 静态统计图表 <<<')
    charts = [
        ('出行小时数量统计',   plot_hourly_orders),
        ('各时段订单时长分布', plot_order_duration_boxplot),
        ('载客出租车数量变化', plot_occupied_taxis),
        ('出行距离划分',       plot_trip_distance),
        ('各时段道路平均速度', plot_avg_speed),
        ('15分钟热力切片',     plot_heatmap_slices),
        ('载客率变化',         plot_occupancy_rate),
        ('车辆里程统计',       plot_vehicle_mileage),
    ]
    for title, func in charts:
        log.info('生成: %s', title)
        fpath = func()
        log.info('  保存: %s (%s)', fpath, _fmt_size(fpath))

    log.info('')
    log.info('=' * 60)
    log.info('全部完成')
    log.info('=' * 60)


if __name__ == '__main__':
    main()
