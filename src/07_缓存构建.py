#!/usr/bin/env python3
"""构建车辆轨迹缓存及统计缓存

从清洗后的 GPS 数据和订单数据构建:
  - data/cache/vehicles.json       — 车辆元数据
  - data/cache/vehicle_data.json   — 全部车辆轨迹
  - data/cache/vehicle_list.json   — 车辆 ID 列表
  - data/cache/stats_summary.json  — 聚合统计
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR, COLUMNS, DTYPES
from src.utils import assert_input_exists


def _write_vehicle_entry(f, vid: int, trajectory: list, first: bool) -> None:
    """Write one vehicle entry ``"vid": [...]`` to the open JSON file handle."""
    if not first:
        f.write(',\n')
    traj_json = json.dumps(trajectory, ensure_ascii=False)
    f.write(f'"{vid}": {traj_json}')


def build_vehicle_cache(clean_path: str, cache_dir: str):
    """Stream-clean.csv into vehicle_data.json, collecting metadata and hourly stats.

    Parameters
    ----------
    clean_path : str  — path to clean.csv
    cache_dir  : str  — output directory for cache files

    Returns
    -------
    vehicle_info    : dict  {vid: [point_count, offset, 'vehicle_data.json']}
    vehicle_list    : list  vehicle IDs in order of appearance
    occupancy_rate  : dict  {str(hour): float}
    speed_stats     : dict  {str(hour): {'avg_speed': float, 'count': int}}
    """
    print('读取车辆轨迹数据 ...')
    print(f'  文件: {clean_path}')

    chunksize = 500_000

    vd_path = os.path.join(cache_dir, 'vehicle_data.json')
    vehicle_info: dict = {}
    vehicle_list: list = []

    # Hourly accumulators from clean.csv
    hourly_occupied = {h: 0 for h in range(24)}
    hourly_total = {h: 0 for h in range(24)}
    hourly_speed_sum = {h: 0.0 for h in range(24)}
    hourly_speed_count = {h: 0 for h in range(24)}

    point_offset = 0
    prev_vid = None
    buffer_traj: list = []
    first_entry = True

    reader = pd.read_csv(
        clean_path,
        chunksize=chunksize,
        dtype=DTYPES,
        usecols=COLUMNS,
    )

    with open(vd_path, 'w', encoding='utf-8') as vd_file:
        vd_file.write('{\n')

        for chunk_idx, chunk in enumerate(reader):
            # Extract hour from time string (YYYY-MM-DD HH:MM:SS → HH)
            chunk['hour'] = chunk['time'].str[11:13].astype('int8')

            # Accumulate hourly stats
            for h in range(24):
                mask = chunk['hour'] == h
                hc = chunk[mask]
                n = len(hc)
                if n > 0:
                    hourly_total[h] += n
                    hourly_occupied[h] += int(hc['status'].sum())
                    speed_mask = hc['speed'] > 0
                    hourly_speed_count[h] += int(speed_mask.sum())
                    hourly_speed_sum[h] += float(
                        hc.loc[speed_mask, 'speed'].sum()
                    )

            # Group by vehicle (data is sorted by id → groups are contiguous)
            for vid, group in chunk.groupby('id', sort=False):
                if prev_vid is not None and vid != prev_vid:
                    # Flush completed vehicle to file
                    _write_vehicle_entry(
                        vd_file, prev_vid, buffer_traj, first_entry
                    )
                    vehicle_info[int(prev_vid)] = [
                        len(buffer_traj),
                        point_offset,
                        'vehicle_data.json',
                    ]
                    vehicle_list.append(int(prev_vid))
                    point_offset += len(buffer_traj)
                    first_entry = False
                    buffer_traj = []

                if prev_vid is None:
                    prev_vid = vid

                # Append current group points to this vehicle's trajectory
                pts = group[
                    ['time', 'long', 'lati', 'status', 'speed']
                ].values.tolist()
                buffer_traj.extend(pts)
                prev_vid = vid

            if (chunk_idx + 1) % 10 == 0:
                proc = (chunk_idx + 1) * chunksize
                print(f'  已处理 {chunk_idx + 1} 个块 ({proc:,} 行) ...')

        # Flush last vehicle
        if buffer_traj:
            _write_vehicle_entry(vd_file, prev_vid, buffer_traj, first_entry)
            vehicle_info[int(prev_vid)] = [
                len(buffer_traj),
                point_offset,
                'vehicle_data.json',
            ]
            vehicle_list.append(int(prev_vid))

        vd_file.write('\n}')

    # Build occupancy rate and speed stats from accumulated data
    occupancy_rate = {}
    speed_stats = {}
    for h in range(24):
        total = hourly_total[h]
        occ_rate = (
            round(hourly_occupied[h] / total, 4) if total > 0 else 0.0
        )
        occupancy_rate[str(h)] = occ_rate

        spd_count = hourly_speed_count[h]
        spd_avg = (
            round(hourly_speed_sum[h] / spd_count, 2)
            if spd_count > 0
            else 0.0
        )
        speed_stats[str(h)] = {'avg_speed': spd_avg, 'count': spd_count}

    return vehicle_info, vehicle_list, occupancy_rate, speed_stats


def build_order_stats(orders_path: str) -> dict:
    """从 orders.csv 构建订单统计.

    Parameters
    ----------
    orders_path : str  — path to orders.csv

    Returns
    -------
    dict with keys:
        hourly_order_counts  — {str(hour): count}
        top_pickup_areas     — list of {lat, lon, count}
        top_dropoff_areas    — list of {lat, lon, count}
        total_orders         — int
    """
    print('读取订单数据 ...')
    print(f'  文件: {orders_path}')

    df = pd.read_csv(orders_path)
    total_orders = len(df)
    print(f'  行数: {total_orders:,}')
    print(f'  列: {list(df.columns)}')

    # Parse time columns
    df['开始时间'] = pd.to_datetime(df['开始时间'])
    df['hour'] = df['开始时间'].dt.hour

    # Hourly order counts
    hourly_counts = df.groupby('hour').size().to_dict()
    hourly_order_counts = {
        str(k): int(v) for k, v in sorted(hourly_counts.items())
    }

    # Top 20 pickup areas (round to 3 decimals ≈ 100 m grid)
    df['pickup_lat'] = df['开始纬度'].round(3)
    df['pickup_lon'] = df['开始经度'].round(3)
    pickup_agg = (
        df.groupby(['pickup_lat', 'pickup_lon'])
        .size()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
    )
    top_pickup = [
        {
            'lat': row['pickup_lat'],
            'lon': row['pickup_lon'],
            'count': int(row[0]),
        }
        for _, row in pickup_agg.iterrows()
    ]

    # Top 20 dropoff areas
    df['dropoff_lat'] = df['结束纬度'].round(3)
    df['dropoff_lon'] = df['结束经度'].round(3)
    dropoff_agg = (
        df.groupby(['dropoff_lat', 'dropoff_lon'])
        .size()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
    )
    top_dropoff = [
        {
            'lat': row['dropoff_lat'],
            'lon': row['dropoff_lon'],
            'count': int(row[0]),
        }
        for _, row in dropoff_agg.iterrows()
    ]

    return {
        'hourly_order_counts': hourly_order_counts,
        'top_pickup_areas': top_pickup,
        'top_dropoff_areas': top_dropoff,
        'total_orders': total_orders,
    }


def main() -> None:
    clean_path = os.path.join(DATA_DIR, 'clean.csv')
    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    cache_dir = os.path.join(DATA_DIR, 'cache')

    assert_input_exists(clean_path)
    assert_input_exists(orders_path)

    os.makedirs(cache_dir, exist_ok=True)

    # ── Build vehicle trajectory cache ────────────────────────────────────
    vehicle_info, vehicle_list, occupancy_rate, speed_stats = (
        build_vehicle_cache(clean_path, cache_dir)
    )

    total_points = sum(info[0] for info in vehicle_info.values())
    print(f'\n车辆总数: {len(vehicle_list):,}')
    print(f'轨迹点数总量: {total_points:,}')

    # Save vehicles.json
    print('\n写入 vehicles.json ...')
    v_path = os.path.join(cache_dir, 'vehicles.json')
    vehicles_out = {str(k): v for k, v in sorted(vehicle_info.items())}
    with open(v_path, 'w', encoding='utf-8') as f:
        json.dump(vehicles_out, f, ensure_ascii=False)
    v_size = os.path.getsize(v_path)
    print(f'  {v_path} ({v_size / 1024:.1f} KB)')

    # Save vehicle_list.json
    print('写入 vehicle_list.json ...')
    vl_path = os.path.join(cache_dir, 'vehicle_list.json')
    with open(vl_path, 'w', encoding='utf-8') as f:
        json.dump(vehicle_list, f, ensure_ascii=False)
    vl_size = os.path.getsize(vl_path)
    print(f'  {vl_path} ({vl_size / 1024:.1f} KB)')

    # ── Build order stats ─────────────────────────────────────────────────
    print()
    order_stats = build_order_stats(orders_path)

    # Merge clean.csv-derived stats
    order_stats['avg_occupancy_rate'] = occupancy_rate
    order_stats['avg_speed_by_hour'] = speed_stats
    order_stats['total_vehicles'] = len(vehicle_list)
    order_stats['total_gps_points'] = total_points

    # Save stats_summary.json
    print('\n写入 stats_summary.json ...')
    ss_path = os.path.join(cache_dir, 'stats_summary.json')
    with open(ss_path, 'w', encoding='utf-8') as f:
        json.dump(order_stats, f, ensure_ascii=False, indent=2)
    ss_size = os.path.getsize(ss_path)
    print(f'  {ss_path} ({ss_size / 1024:.1f} KB)')

    # ── File sizes ────────────────────────────────────────────────────────
    vd_path = os.path.join(cache_dir, 'vehicle_data.json')
    vd_size = os.path.getsize(vd_path)

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print('=' * 50)
    print('缓存构建完成')
    print('=' * 50)
    print(f'  总车辆数:            {order_stats["total_vehicles"]:,}')
    print(f'  总订单数:            {order_stats["total_orders"]:,}')
    print(f'  总轨迹点数:          {order_stats["total_gps_points"]:,}')
    print(f'  vehicle_data.json    {vd_size / 1024 / 1024:.1f} MB')
    print(f'  vehicles.json        {v_size / 1024:.1f} KB')
    print(f'  vehicle_list.json    {vl_size / 1024:.1f} KB')
    print(f'  stats_summary.json   {ss_size / 1024:.1f} KB')


if __name__ == '__main__':
    main()
