#!/usr/bin/env python3
"""出租车GPS数据OD提取 — 从清洗后数据提取出行对

重新计算 status_up / id_up → 筛选上下车点 → shift(-1) 拼接OD对 → 过滤无效 → 保存
"""

import os
import sys

import pandas as pd

# Ensure src/ is importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import COLUMNS, DATA_DIR, PROJECT_ROOT
from src.utils import assert_input_exists, haversine_km


def main() -> None:
    # ── 0. Paths & input assertion ───────────────────────────────────────
    clean_path = os.path.join(DATA_DIR, 'clean.csv')
    assert_input_exists(clean_path)

    orders_path = os.path.join(DATA_DIR, 'orders.csv')

    # ── 1. 读取 clean.csv ────────────────────────────────────────────────
    print(f'读取数据: {clean_path}')
    df = pd.read_csv(clean_path)
    print(f'  行数: {len(df):,}')
    print(f'  列: {list(df.columns)}')

    # ── 2. 类型转换 ──────────────────────────────────────────────────────
    print('转换 time 列为 datetime ...')
    df['time'] = pd.to_datetime(df['time'])

    # ── 3. 重新计算 status_up / id_up（不依赖前一步保留的列） ────────────
    print('重新计算 status_up / id_up ...')
    df['status_up'] = df['status'].shift(1)
    df['id_up'] = df['id'].shift(1)

    # NaN 处理：首行无上一行
    df['status_up'] = df['status_up'].fillna(-1)
    df['id_up'] = df['id_up'].fillna(-999)

    # ── 4. 计算变化量 ────────────────────────────────────────────────────
    df['status_chg'] = df['status'] - df['status_up']   # 1=上车(0→1), -1=下车(1→0)
    df['id_chg'] = df['id'] - df['id_up']               # 0=同一辆车

    # ── 5. 筛选上下车点 ──────────────────────────────────────────────────
    n_pickup = int((df['status_chg'] == 1).sum())
    n_dropoff = int((df['status_chg'] == -1).sum())
    print(f'  上车点数 (status_chg==1): {n_pickup:,}')
    print(f'  下车点数 (status_chg==-1): {n_dropoff:,}')

    # 只保留上下车点，且同一辆车（id_chg == 0）
    df_temp = df[(df['status_chg'].isin([1, -1])) & (df['id_chg'] == 0)].copy()
    print(f'  上下车点（同车）: {len(df_temp):,}')

    # ── 6. shift(-1) 拼接OD对 ────────────────────────────────────────────
    print('shift(-1) 拼接OD对 ...')
    df_temp['Etime'] = df_temp['time'].shift(-1)
    df_temp['Elong'] = df_temp['long'].shift(-1)
    df_temp['Elati'] = df_temp['lati'].shift(-1)
    df_temp['Espeed'] = df_temp['speed'].shift(-1)
    df_temp['Estatus'] = df_temp['status'].shift(-1)

    # ── 7. 筛选上车行（确保上下车是同一辆车） ────────────────────────────
    # 上车行: status_chg == 1，且下一行（shift(-1)后的id）也是同一辆车
    mask = (df_temp['status_chg'] == 1) & (df_temp['id'] == df_temp['id'].shift(-1))
    df_od = df_temp[mask].copy()
    n_paired = len(df_od)
    print(f'  配对成功数: {n_paired:,}')

    # ── 8. 列重命名 ──────────────────────────────────────────────────────
    df_od = df_od.rename(columns={
        'id':     '车辆id',
        'time':   '开始时间',
        'long':   '开始经度',
        'lati':   '开始纬度',
        'speed':  'O_SPEED',
        'status': 'O_FLAG',
        'Etime':  '结束时间',
        'Elong':  '结束经度',
        'Elati':  '结束纬度',
        'Espeed': 'D_SPEED',
        'Estatus':'D_FLAG',
    })
    # 新增 O_HEAD / D_HEAD（原始数据无方向字段，填0表示无数据）
    df_od['O_HEAD'] = 0
    df_od['D_HEAD'] = 0

    # ── 9. 计算OD时间和距离 ──────────────────────────────────────────────
    print('计算 OD_TIME_s / OD_Dis_km ...')
    df_od['OD_TIME_s'] = (
        df_od['结束时间'] - df_od['开始时间']
    ).dt.total_seconds()

    df_od['OD_Dis_km'] = df_od.apply(
        lambda r: haversine_km(
            r['开始纬度'], r['开始经度'],
            r['结束纬度'], r['结束经度'],
        ),
        axis=1,
    )

    # ── 10. 过滤无效OD对 ─────────────────────────────────────────────────
    n_before_filter = len(df_od)

    df_od = df_od[df_od['OD_TIME_s'] > 0]
    n_time_removed = n_before_filter - len(df_od)

    n_before_dist = len(df_od)
    df_od = df_od[df_od['OD_Dis_km'] > 0]
    n_dist_removed = n_before_dist - len(df_od)

    n_invalid_removed = n_time_removed + n_dist_removed
    print(f'  删除 OD_TIME_s<=0: {n_time_removed:,}')
    print(f'  删除 OD_Dis_km<=0: {n_dist_removed:,}')
    print(f'  无效过滤总数: {n_invalid_removed:,}')

    # ── 11. 选取输出列并保存 ─────────────────────────────────────────────
    out_cols = [
        '车辆id',
        '开始时间', '开始经度', '开始纬度',
        'O_HEAD', 'O_SPEED', 'O_FLAG',
        '结束时间', '结束经度', '结束纬度',
        'D_HEAD', 'D_SPEED', 'D_FLAG',
        'OD_TIME_s', 'OD_Dis_km',
    ]
    df_od = df_od[out_cols].reset_index(drop=True)

    print(f'保存: {orders_path}')
    df_od.to_csv(orders_path, index=False)
    print(f'  → {orders_path} (行数: {len(df_od):,})')

    # ── 12. 汇总日志 ──────────────────────────────────────────────────────
    print()
    print('=' * 60)
    print('OD提取汇总')
    print('=' * 60)
    print(f'  上车点数:       {n_pickup:>12,}')
    print(f'  下车点数:       {n_dropoff:>12,}')
    print(f'  配对成功数:     {n_paired:>12,}')
    print(f'  无效过滤数:     {n_invalid_removed:>12,}')
    print(f'  {"─" * 40}')
    print(f'  最终OD对数:     {len(df_od):>12,}')
    print('=' * 60)


if __name__ == '__main__':
    main()