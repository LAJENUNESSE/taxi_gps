
"""出租车GPS数据分析 — 8个子分析产出8个CSV结果文件

子分析:
  4.1 DBSCAN上客点聚类 → data/clustered_hotspots.csv
  4.2 订单时段统计      → data/hourly_orders.csv
  4.3 订单时长分布      → data/order_duration_stats.csv
  4.4 出行距离划分      → data/JNLuC.csv
  4.5 订单平均速度      → data/avg_speed_by_hour.csv
  4.6 载客出租车数量    → data/occupied_taxis.csv
  4.7 载客率统计        → data/occupancy_rate.csv
  4.8 车辆里程统计      → data/vehicle_mileage.csv
"""

import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.config import (
    DATA_DIR,
    DBSCAN_EPS,
    DBSCAN_MIN_SAMPLES,
    DISTANCE_SHORT,
    DISTANCE_LONG,
)
from src.utils import assert_input_exists


def main() -> None:

    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    clean_path = os.path.join(DATA_DIR, 'clean.csv')
    assert_input_exists(orders_path)
    assert_input_exists(clean_path)


    print(f'读取数据: {orders_path}')
    df = pd.read_csv(orders_path)
    print(f'  行数: {len(df):,}')
    print(f'  列: {list(df.columns)}')


    df['开始时间'] = pd.to_datetime(df['开始时间'])
    df['结束时间'] = pd.to_datetime(df['结束时间'])
    df['小时'] = df['开始时间'].dt.hour

    total_od_pairs = len(df)


    print()
    print('--- 4.1 DBSCAN上客点聚类 ---')
    pickup_points = df[['开始纬度', '开始经度']].values

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
            'lat': center_lat,
            'lng': center_lng,
            'count': count,
            'time': '2026-06-22',
        })

    df_clusters = pd.DataFrame(cluster_data)
    hotspots_path = os.path.join(DATA_DIR, 'clustered_hotspots.csv')
    df_clusters.to_csv(hotspots_path, index=False)
    print(f'  保存: {hotspots_path} ({len(df_clusters)} 行)')


    print()
    print('--- 4.2 订单时段统计 ---')
    df_hourcnt = df.groupby('小时')['车辆id'].count().rename('数量').reset_index()


    all_hours = pd.DataFrame({'小时': range(24)})
    df_hourcnt = all_hours.merge(df_hourcnt, on='小时', how='left').fillna(0)
    df_hourcnt['数量'] = df_hourcnt['数量'].astype(int)

    hourly_path = os.path.join(DATA_DIR, 'hourly_orders.csv')
    df_hourcnt.to_csv(hourly_path, index=False)
    print(f'  保存: {hourly_path} ({len(df_hourcnt)} 行)')

    hourly_sum = int(df_hourcnt['数量'].sum())
    print(f'  时段统计总和: {hourly_sum} (OD对总数: {total_od_pairs})')


    print()
    print('--- 4.2b 每分钟打车数量统计 ---')
    df_minute = df.copy()
    df_minute['分钟'] = df_minute['开始时间'].dt.floor('min')
    df_minutely = df_minute.groupby('分钟')['车辆id'].count().reset_index()
    df_minutely.columns = ['O_time', 'count']
    minutely_path = os.path.join(DATA_DIR, 'minutely_orders.csv')
    df_minutely.to_csv(minutely_path, index=False)
    print(f'  保存: {minutely_path} ({len(df_minutely)} 行)')


    print()
    print('--- 4.2c 每15分钟打车数量统计 ---')
    df_quarter = df.copy()
    df_quarter['15分钟'] = df_quarter['开始时间'].dt.floor('15min')
    df_quarter_hour = df_quarter.groupby('15分钟')['车辆id'].count().reset_index()
    df_quarter_hour.columns = ['O_time', 'count']
    quarter_hour_path = os.path.join(DATA_DIR, 'quarter_hour_orders.csv')
    df_quarter_hour.to_csv(quarter_hour_path, index=False)
    print(f'  保存: {quarter_hour_path} ({len(df_quarter_hour)} 行)')


    print()
    print('--- 4.3 订单时长分布 ---')
    df['订单时长_min'] = (
        df['结束时间'] - df['开始时间']
    ).dt.total_seconds() / 60

    df_dur = df.groupby('小时')['订单时长_min'].agg(
        mean='mean',
        median='median',
        count='count',
    ).reset_index()
    df_dur.columns = ['小时', 'mean_min', 'median_min', 'count']

    dur_path = os.path.join(DATA_DIR, 'order_duration_stats.csv')
    df_dur.to_csv(dur_path, index=False)
    print(f'  保存: {dur_path} ({len(df_dur)} 行)')


    print()
    print('--- 4.4 出行距离划分 ---')
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

    jnluc_path = os.path.join(DATA_DIR, 'JNLuC.csv')
    df_jnluc.to_csv(jnluc_path, index=False)
    print(f'  保存: {jnluc_path} ({len(df_jnluc)} 行)')
    print(f'  near={df_jnluc.iloc[0]["near"]}, middle={df_jnluc.iloc[0]["middle"]}, far={df_jnluc.iloc[0]["far"]}')


    print()
    print('--- 4.5 订单平均速度 ---')
    df['avg_speed'] = df['OD_Dis_km'] / (df['OD_TIME_s'] / 3600)


    valid_speed = (
        df['avg_speed'].notna()
        & np.isfinite(df['avg_speed'])
        & (df['avg_speed'] > 0)
    )
    df_speed = df[valid_speed]

    df_speed_hour = df_speed.groupby('小时')['avg_speed'].mean().reset_index()
    df_speed_hour.columns = ['O_time', 'sudu']

    speed_path = os.path.join(DATA_DIR, 'avg_speed_by_hour.csv')
    df_speed_hour.to_csv(speed_path, index=False)
    print(f'  保存: {speed_path} ({len(df_speed_hour)} 行)')


    print()
    print('--- 4.6 载客出租车数量统计 ---')
    print(f'读取数据: {clean_path} (chunked)')

    occupied_per_minute: dict = defaultdict(set)

    chunk_iter = pd.read_csv(
        clean_path,
        chunksize=500_000,
        usecols=['id', 'time', 'status'],
    )

    n_total_rows = 0
    for chunk in chunk_iter:
        n_total_rows += len(chunk)
        mask = chunk['status'] == 1
        if not mask.any():
            continue

        chunk_occ = chunk.loc[mask, ['id', 'time']].copy()
        chunk_occ['time'] = pd.to_datetime(chunk_occ['time'])
        chunk_occ['time_minute'] = chunk_occ['time'].dt.floor('min')

        for minute, group in chunk_occ.groupby('time_minute'):
            occupied_per_minute[minute].update(group['id'].unique())

        if n_total_rows % 5_000_000 == 0:
            print(f'  已处理: {n_total_rows:,} 行 ...')

    print(f'  总处理行数: {n_total_rows:,}')


    df_occupied = pd.DataFrame([
        {'TIME': t, 'number': len(ids)}
        for t, ids in sorted(occupied_per_minute.items())
    ])

    occupied_path = os.path.join(DATA_DIR, 'occupied_taxis.csv')
    df_occupied.to_csv(occupied_path, index=False)
    print(f'  保存: {occupied_path} ({len(df_occupied)} 行)')


    # --- 4.7 载客率统计 ---
    # 数据来源: clean.csv 按时段统计载客GPS点数 vs 总GPS点数
    # 统计口径: 载客率 = 该小时 status==1 的点数 / 该小时全部点数
    print()
    print('--- 4.7 载客率统计 ---')

    occ_count: dict[int, int] = defaultdict(int)
    total_count: dict[int, int] = defaultdict(int)

    chunk_iter2 = pd.read_csv(
        clean_path,
        chunksize=500_000,
        usecols=['time', 'status'],
    )
    for chunk in chunk_iter2:
        chunk['time'] = pd.to_datetime(chunk['time'])
        chunk['hour'] = chunk['time'].dt.hour
        for h in range(24):
            mask_h = chunk['hour'] == h
            total_count[h] += int(mask_h.sum())
            occ_count[h] += int(((chunk['hour'] == h) & (chunk['status'] == 1)).sum())

    df_occ_rate = pd.DataFrame([
        {'小时': h, '总GPS点数': total_count[h], '载客GPS点数': occ_count[h],
         '载客率': round(occ_count[h] / total_count[h], 4) if total_count[h] > 0 else 0.0}
        for h in range(24)
    ])
    occ_rate_path = os.path.join(DATA_DIR, 'occupancy_rate.csv')
    df_occ_rate.to_csv(occ_rate_path, index=False)
    print(f'  保存: {occ_rate_path} ({len(df_occ_rate)} 行)')
    print(f'  数据来源: clean.csv 按时段统计 status==1 点数占比')
    print(f'  聚合粒度: 小时级')
    for _, r in df_occ_rate.iterrows():
        print(f'    {int(r["小时"]):02d}:00  载客率={r["载客率"]:.2%}  (载客{r["载客GPS点数"]:,} / 总{r["总GPS点数"]:,})')


    # --- 4.8 车辆里程统计 ---
    # 数据来源: clean.csv, 距离计算: haversine_km (src/utils.py)
    # 统计口径: 按车辆逐段累加相邻GPS点间的大圆距离, 按status分载客/空载
    print()
    print('--- 4.8 车辆里程统计 ---')
    print('  数据来源: clean.csv')
    print('  距离计算: haversine_km (大圆距离)')
    print('  统计口径: 按车辆逐段累加相邻GPS点距离')

    from src.utils import haversine_km

    vehicle_mileage: dict[str, dict] = {}
    last_point: dict[str, tuple[float, float]] = {}

    chunk_iter3 = pd.read_csv(
        clean_path,
        chunksize=500_000,
        usecols=['id', 'lati', 'long', 'status'],
    )
    processed_rows = 0
    for chunk in chunk_iter3:
        processed_rows += len(chunk)
        for vid, group in chunk.groupby('id'):
            vid_key = str(int(vid))
            if vid_key not in vehicle_mileage:
                vehicle_mileage[vid_key] = {'总里程': 0.0, '载客里程': 0.0, '空载里程': 0.0}

            lats = group['lati'].astype(float).values
            lons = group['long'].astype(float).values
            statuses = group['status'].astype(int).values
            n = len(lats)

            if vid_key in last_point:
                prev_lat, prev_lon = last_point[vid_key]
                seg = haversine_km(prev_lat, prev_lon, lats[0], lons[0])
                if seg <= 5.0:
                    vehicle_mileage[vid_key]['总里程'] += seg
                    if statuses[0] == 1:
                        vehicle_mileage[vid_key]['载客里程'] += seg
                    else:
                        vehicle_mileage[vid_key]['空载里程'] += seg

            for i in range(n - 1):
                lat1, lon1 = lats[i], lons[i]
                lat2, lon2 = lats[i + 1], lons[i + 1]
                seg_km = haversine_km(lat1, lon1, lat2, lon2)
                if seg_km > 5.0:
                    continue
                vehicle_mileage[vid_key]['总里程'] += seg_km
                if statuses[i + 1] == 1:
                    vehicle_mileage[vid_key]['载客里程'] += seg_km
                else:
                    vehicle_mileage[vid_key]['空载里程'] += seg_km

            last_point[vid_key] = (float(lats[-1]), float(lons[-1]))

        if processed_rows % 5_000_000 == 0:
            print(f'  已处理: {processed_rows:,} 行 ...')

    print(f'  总处理行数: {processed_rows:,}')

    df_mileage = pd.DataFrame([
        {'车辆id': vid, '总里程_km': round(v['总里程'], 2),
         '载客里程_km': round(v['载客里程'], 2),
         '空载里程_km': round(v['空载里程'], 2)}
        for vid, v in vehicle_mileage.items()
    ]).sort_values('总里程_km', ascending=False)

    mileage_path = os.path.join(DATA_DIR, 'vehicle_mileage.csv')
    df_mileage.to_csv(mileage_path, index=False)
    print(f'  保存: {mileage_path} ({len(df_mileage)} 行)')

    total_km = df_mileage['总里程_km'].sum()
    occupied_km = df_mileage['载客里程_km'].sum()
    empty_km = df_mileage['空载里程_km'].sum()
    n_vehicles = len(df_mileage)

    print(f'  车辆数: {n_vehicles:,}')
    print(f'  总里程: {total_km:,.0f} km')
    print(f'  载客里程: {occupied_km:,.0f} km ({occupied_km/total_km*100:.1f}%)')
    print(f'  空载里程: {empty_km:,.0f} km ({empty_km/total_km*100:.1f}%)')
    print(f'  单车日均里程: {total_km/n_vehicles:.0f} km')
    print(f'  全天平均载客率(按里程): {occupied_km/total_km*100:.1f}%')


    print()
    print('=' * 60)
    print('数据分析汇总')
    print('=' * 60)
    print(f'  [4.1] DBSCAN聚类簇数:        {n_clusters:>6}')
    print(f'  [4.1] DBSCAN噪声点比例:      {n_noise / max(n_clustered + n_noise, 1):>6.2%}')
    print(f'  [4.2] 时段统计行数:          {len(df_hourcnt):>6}')
    print(f'  [4.3] 订单时长统计行数:      {len(df_dur):>6}')
    print(f'  [4.4] 出行距离划分行数:      {len(df_jnluc):>6}')
    print(f'  [4.5] 平均速度统计行数:      {len(df_speed_hour):>6}')
    print(f'  [4.6] 载客出租车分钟数:      {len(df_occupied):>6}')
    print(f'  [4.7] 载客率统计行数:        {len(df_occ_rate):>6}')
    print(f'  [4.8] 车辆里程统计行数:      {len(df_mileage):>6}')
    print(f'  {"─" * 40}')
    print(f'  OD对总数:                    {total_od_pairs:>6}')
    print(f'  全天平均载客率(按里程):      {occupied_km/total_km*100:>6.1f}%')

    match = '✓' if hourly_sum == total_od_pairs else '✗'
    print(f'  验证: 时段统计总和={hourly_sum} == OD对总数={total_od_pairs} {match}')
    print('=' * 60)


if __name__ == '__main__':
    main()
