#!/usr/bin/env python3
"""出租车GPS数据清洗 — 完整流水线

排序 → 类型转换 → 坐标/速度过滤 → 重复值去重 → 异常值剔除 → 保存结果
"""

import os
import sys

import numpy as np
import pandas as pd

# Ensure src/ is importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (
    ANOMALY_TIME_THRESHOLD,
    COLUMNS,
    DATA_DIR,
    DATA_FILE,
    DTYPES,
    PROJECT_ROOT,
    SHENZHEN_BOUNDS,
    SPEED_MAX,
)
from src.utils import assert_input_exists


def main() -> None:
    # ── 0. Paths & input assertion ───────────────────────────────────────
    data_path = os.path.join(PROJECT_ROOT, DATA_FILE)
    assert_input_exists(data_path)
    os.makedirs(DATA_DIR, exist_ok=True)

    stage1_path = os.path.join(DATA_DIR, 'clean_stage1.csv')
    stage2_path = os.path.join(DATA_DIR, 'clean_stage2.csv')
    final_path = os.path.join(DATA_DIR, 'clean.csv')

    # ── 1. 读取数据（显式 dtype，防 OOM） ─────────────────────────────────
    print(f'读取数据: {data_path}')
    df = pd.read_csv(data_path, header=None, names=COLUMNS, dtype=DTYPES)
    n_original = len(df)
    print(f'  原始行数: {n_original:,}')

    # ── 2. 排序 ──────────────────────────────────────────────────────────
    print('排序 by (id, time) ...')
    df = df.sort_values(by=['id', 'time']).reset_index(drop=True)
    n_after_sort = len(df)

    # ── 3. 单调性校验 ────────────────────────────────────────────────────
    print('单调性校验 ...')
    t_dt = pd.to_datetime(df['time'], format='%H:%M:%S')
    t_diff = t_dt.groupby(df['id']).diff().dropna()
    n_non_monotonic = (t_diff.dt.total_seconds() < -1).sum()
    print(f'  Time非单调递减数（按id分组）: {n_non_monotonic}')

    # 转换为 datetime 供后续步骤使用（时间差计算、异常检测等）
    df['time'] = t_dt
    print(f'  排序后行数: {n_after_sort:,}')

    # ── 保存 Stage 1 ─────────────────────────────────────────────────────
    print(f'保存中间结果: {stage1_path}')
    df.to_csv(stage1_path, index=False)
    print(f'  → {stage1_path}')

    # ── 4. 坐标过滤 ──────────────────────────────────────────────────────
    n_before = len(df)
    b = SHENZHEN_BOUNDS
    df = df[
        (df['long'] >= b['long_min']) & (df['long'] <= b['long_max'])
        & (df['lati'] >= b['lat_min']) & (df['lati'] <= b['lat_max'])
    ]
    n_coord_removed = n_before - len(df)
    print(f'  坐标过滤删除: {n_coord_removed:,}')

    # ── 5. 速度过滤 ──────────────────────────────────────────────────────
    n_before = len(df)
    df = df[(df['speed'] >= 0) & (df['speed'] <= SPEED_MAX)]
    n_speed_removed = n_before - len(df)
    print(f'  速度过滤删除: {n_speed_removed:,}')

    # ── 6. 去重 ──────────────────────────────────────────────────────────
    print('去重处理 ...')
    n_before_dedup = len(df)
    df_dup = df[df.duplicated(subset=['id', 'time'], keep=False)].reset_index()
    print(f'  重复行数: {len(df_dup):,}')

    if len(df_dup) > 0:
        # 对重复数据分组统计
        dup_grp = (
            df_dup.groupby(['id', 'time'])
            .agg(stat_cnt=('status', 'count'), stat_sum=('status', 'sum'))
            .reset_index()
        )

        dup_mrg = pd.merge(df_dup, dup_grp, on=['id', 'time'], how='left')

        def dup_check(x: pd.DataFrame) -> int:
            """根据 stat_cnt / stat_sum 决定保留哪一行，返回原始 df 索引."""
            cnt = int(x['stat_cnt'].iloc[0])
            total = int(x['stat_sum'].iloc[0])

            if cnt == 2:
                if total == 0:   # 两个 status 均为 0
                    return int(x['index'].iloc[0])
                elif total == 1:  # 一个 0，一个 1 → 保留 status=0
                    return int(x.loc[x['status'] == 0, 'index'].iloc[0])
                elif total == 2:  # 两个 status 均为 1
                    return int(x['index'].iloc[0])
            elif cnt == 3:
                if total == 0:   # 三个 status 均为 0
                    return int(x['index'].iloc[0])
                elif total == 1:  # 一个 1，两个 0 → 保留第一个 status=0
                    return int(x.loc[x['status'] == 0, 'index'].iloc[0])
                elif total == 2:  # 两个 1，一个 0 → 保留第一个 status=1
                    return int(x.loc[x['status'] == 1, 'index'].iloc[0])
                elif total == 3:  # 三个 status 均为 1
                    return int(x['index'].iloc[0])

            # 兜底：返回第一个索引
            return int(x['index'].iloc[0])

        kp_index = dup_mrg.groupby(['id', 'time'], group_keys=False).apply(dup_check)

        # 找出要删除的行（在 dup_mrg 中但不在 kp_index 中的）
        drp_index = dup_mrg.loc[~dup_mrg['index'].isin(kp_index.values), 'index']
        df = df.loc[~df.index.isin(drp_index.values)]

    n_dedup_removed = n_before_dedup - len(df)
    print(f'  去重删除: {n_dedup_removed:,}')

    # ── 保存 Stage 2 ─────────────────────────────────────────────────────
    print(f'保存中间结果: {stage2_path}')
    df.to_csv(stage2_path, index=False)
    print(f'  → {stage2_path}')

    # ── 7. 异常检测 ──────────────────────────────────────────────────────
    print('异常值检测 ...')
    n_before_anom = len(df)

    # shift 产生 6 个辅助列
    df['status_up'] = df['status'].shift(1)
    df['status_down'] = df['status'].shift(-1)
    df['id_up'] = df['id'].shift(1)
    df['id_down'] = df['id'].shift(-1)
    df['time_up'] = df['time'].shift(1)
    df['time_down'] = df['time'].shift(-1)

    # 5 个条件
    cond_1 = df['status'] != df['status_down']
    cond_2 = df['status'] != df['status_up']
    cond_3 = df['id'] == df['id_up']
    cond_4 = df['id'] == df['id_down']
    cond_5 = (df['time_down'] - df['time_up']).dt.seconds < ANOMALY_TIME_THRESHOLD

    df_abn = df[cond_1 & cond_2 & cond_3 & cond_4 & cond_5].reset_index()
    print(f'  异常行数: {len(df_abn):,}')

    if len(df_abn) > 0:
        print('  异常数据 id 分布:')
        print(df_abn['id'].value_counts().to_string())

        df = df.loc[~df.index.isin(df_abn['index'].values)]

    n_anomaly_removed = n_before_anom - len(df)
    print(f'  异常删除: {n_anomaly_removed:,}')

    # ── 8. 清理辅助列 ────────────────────────────────────────────────────
    # 保留 status_up 和 id_up 供后续 OD 提取使用
    cols_to_drop = ['status_down', 'id_down', 'time_up', 'time_down']
    df = df.drop(columns=[c for c in cols_to_drop if c in df.columns])

    # ── 8.5 车辆级别过滤 ────────────────────────────────────────────────
    print('车辆级别过滤 ...')
    n_before_vehicle = len(df)

    speed_by_veh = df.groupby('id')[['speed', 'status']].agg(['min', 'max'])
    always_zero_speed = speed_by_veh[
        (speed_by_veh[('speed', 'min')] == 0) & (speed_by_veh[('speed', 'max')] == 0)
    ].index
    always_same_status = speed_by_veh[
        (speed_by_veh[('status', 'min')] == speed_by_veh[('status', 'max')])
    ].index

    n_always_zero_speed = len(always_zero_speed)
    n_always_same_status = len(always_same_status)
    print(f'  速度始终为0的车辆数: {n_always_zero_speed}')
    print(f'  全天同一状态的车辆数: {n_always_same_status}')

    bad_vehicles = set(always_zero_speed) | set(always_same_status)
    df = df[~df['id'].isin(bad_vehicles)]
    n_vehicle_removed = n_before_vehicle - len(df)
    print(f'  车辆过滤删除行数: {n_vehicle_removed:,}')

    # ── 保存最终结果 ─────────────────────────────────────────────────────
    n_final = len(df)
    print(f'保存最终结果: {final_path}')
    df.to_csv(final_path, index=False)
    print(f'  → {final_path} (行数: {n_final:,})')

    # ── 9. 汇总日志 ──────────────────────────────────────────────────────
    print()
    print('=' * 60)
    print('清洗汇总')
    print('=' * 60)
    print(f'  原始行数:     {n_original:>12,}')
    print(f'  排序后行数:   {n_after_sort:>12,}')
    print(f'  坐标过滤删除: {n_coord_removed:>12,}')
    print(f'  速度过滤删除: {n_speed_removed:>12,}')
    print(f'  去重删除:     {n_dedup_removed:>12,}')
    print(f'  异常删除:     {n_anomaly_removed:>12,}')
    print(f'  车辆过滤删除: {n_vehicle_removed:>12,}')
    print(f'  {"─" * 40}')
    print(f'  最终行数:     {n_final:>12,}')
    print('=' * 60)


if __name__ == '__main__':
    main()
