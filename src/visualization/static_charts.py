
"""出租车GPS数据可视化 — 11个图表

图表:
  1. 出行小时数量统计      → output/figures/hourly_orders.png
  2. 各时段订单时长分布    → output/figures/order_duration_boxplot.png
  3. 上客点热力分布        → output/figures/static_heatmap.png
  4. 车辆位置热力分布      → output/figures/vehicle_position_heatmap.png
  5. 载客出租车数量变化    → output/figures/occupied_taxis.png
  6. 载客率变化            → output/figures/occupancy_rate.png
  7. 出行距离划分          → output/figures/trip_distance.png
  8. 各时段道路平均速度    → output/figures/avg_speed.png
  9. 15分钟热力切片        → output/figures/heatmap_slices.png
  10. 动态热力图           → output/figures/dynamic_heatmap.gif
  11. 车辆里程统计         → output/figures/vehicle_mileage.png
"""

import os
import sys
import shutil
import tempfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from PIL import Image

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.config import DATA_DIR, FIGURES_DIR
from src.utils import setup_matplotlib_cjk, assert_input_exists


setup_matplotlib_cjk()


def _save_fig(fig, filename: str) -> str:
    """Save figure to FIGURES_DIR/filename and return full path."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def plot_hourly_orders() -> str:
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


def plot_order_duration_boxplot() -> str:
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


def plot_static_heatmap() -> str:
    path = os.path.join(DATA_DIR, 'clustered_hotspots.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(
        df['lng'], df['lat'],
        c=df['count'],
        s=np.log1p(df['count']) * 8,
        cmap='YlOrRd',
        alpha=0.8,
        edgecolors='black',
        linewidths=0.5,
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label('热度(count)')
    ax.set_xlabel('经度')
    ax.set_ylabel('纬度')
    ax.set_title('上客点热力分布')
    ax.grid(alpha=0.3)

    return _save_fig(fig, 'static_heatmap.png')


def plot_occupied_taxis() -> str:
    path = os.path.join(DATA_DIR, 'occupied_taxis.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    df['TIME'] = pd.to_datetime(df['TIME'])


    df_sampled = df.iloc[::30].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(df_sampled['TIME'], df_sampled['number'],
            color='darkgreen', linewidth=1.5)
    ax.fill_between(df_sampled['TIME'], df_sampled['number'],
                    alpha=0.2, color='darkgreen')
    ax.set_xlabel('时间')
    ax.set_ylabel('载客数量')
    ax.set_title('载客出租车数量变化')
    ax.grid(alpha=0.3)

    fig.autofmt_xdate()

    return _save_fig(fig, 'occupied_taxis.png')


def plot_trip_distance() -> str:
    path = os.path.join(DATA_DIR, 'JNLuC.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)


    near = int(df['near'].sum())
    middle = int(df['middle'].sum())
    far = int(df['far'].sum())

    fig, ax = plt.subplots(figsize=(8, 8))
    sizes = [near, middle, far]
    labels = ['短途(<4km)', '中途(4-8km)', '长途(>8km)']
    colors = ['#4CAF50', '#FF9800', '#f44336']
    explode = (0.03, 0.03, 0.03)

    ax.pie(
        sizes,
        labels=labels,
        autopct='%1.1f%%',
        colors=colors,
        explode=explode,
        startangle=90,
        textprops={'fontsize': 12},
    )
    ax.set_title('出行距离划分')

    return _save_fig(fig, 'trip_distance.png')


def plot_avg_speed() -> str:
    path = os.path.join(DATA_DIR, 'avg_speed_by_hour.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df['O_time'], df['sudu'],
            color='darkorange', marker='s', linewidth=2, markersize=6)
    ax.fill_between(df['O_time'], df['sudu'],
                    alpha=0.2, color='darkorange')
    ax.set_xlabel('时段(小时)')
    ax.set_ylabel('平均速度(km/h)')
    ax.set_title('各时段道路平均速度')
    ax.set_xticks(range(0, 24))
    ax.grid(alpha=0.3)

    return _save_fig(fig, 'avg_speed.png')


def plot_heatmap_slices() -> str:
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
        ax.set_xlim(113.5, 114.8)
        ax.set_ylim(22.3, 22.9)
        ax.set_title(label, fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle('15分钟上客点热力切片', fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    return _save_fig(fig, 'heatmap_slices.png')


def plot_dynamic_heatmap_gif() -> str:
    path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(path)
    df = pd.read_csv(path)
    df['开始时间'] = pd.to_datetime(df['开始时间'])
    minutes_of_day = df['开始时间'].dt.hour * 60 + df['开始时间'].dt.minute
    df['时间窗'] = (minutes_of_day // 15).astype(int)

    os.makedirs(FIGURES_DIR, exist_ok=True)
    gif_path = os.path.join(FIGURES_DIR, 'dynamic_heatmap.gif')
    tmp_dir = tempfile.mkdtemp(prefix='heatmap_frames_')
    frames = []


    for i in range(0, 96, 4):
        sub = df[df['时间窗'] == i]
        start_min = i * 15
        end_min = (i + 1) * 15
        label = f'{start_min // 60:02d}:{start_min % 60:02d}-{end_min // 60:02d}:{end_min % 60:02d}'

        fig, ax = plt.subplots(figsize=(8, 6))
        if not sub.empty:
            ax.scatter(sub['开始经度'], sub['开始纬度'], s=1, alpha=0.3, c='red')
        ax.set_xlim(113.5, 114.8)
        ax.set_ylim(22.3, 22.9)
        ax.set_title(f'上客点热力 {label}', fontsize=14)
        ax.set_xlabel('经度')
        ax.set_ylabel('纬度')
        ax.grid(alpha=0.3)

        tmp_path = os.path.join(tmp_dir, f'frame_{i:03d}.png')
        fig.savefig(tmp_path, dpi=80, bbox_inches='tight')
        plt.close(fig)
        img = Image.open(tmp_path)
        img.load()
        frames.append(img)

    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=200,
        loop=0,
    )


    for img in frames:
        img.close()
    shutil.rmtree(tmp_dir)

    return gif_path


def plot_vehicle_position_heatmap() -> str:
    path = os.path.join(DATA_DIR, 'clean.csv')
    assert_input_exists(path)

    print('  采样车辆位置点 ...')
    sample_step = 500
    sampled_lons, sampled_lats = [], []
    chunk_iter = pd.read_csv(path, chunksize=200_000, usecols=['lati', 'long', 'status'])
    row_idx = 0
    for chunk in chunk_iter:
        occupied = chunk[chunk['status'] == 1]
        for _, row in occupied.iterrows():
            if row_idx % sample_step == 0:
                sampled_lons.append(row['long'])
                sampled_lats.append(row['lati'])
            row_idx += 1
            if len(sampled_lons) >= 80000:
                break
        if len(sampled_lons) >= 80000:
            break

    print(f'  采样点数: {len(sampled_lons):,}')

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter(sampled_lons, sampled_lats, s=1, alpha=0.3, c='steelblue')
    ax.set_xlim(113.5, 114.8)
    ax.set_ylim(22.3, 22.9)
    ax.set_xlabel('经度')
    ax.set_ylabel('纬度')
    ax.set_title('车辆位置热力分布（载客状态）')
    ax.grid(alpha=0.3)

    return _save_fig(fig, 'vehicle_position_heatmap.png')


def plot_occupancy_rate() -> str:
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


def plot_vehicle_mileage() -> str:
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
    ax2.axvline(mean_val, color='crimson', linestyle='--',
                linewidth=1.5, label=f'均值={mean_val:.0f} km')
    ax2.axvline(median_val, color='darkgreen', linestyle='--',
                linewidth=1.5, label=f'中位数={median_val:.0f} km')
    ax2.set_xlabel('单车总里程 (km)')
    ax2.set_ylabel('车辆数')
    ax2.set_title('单车总里程分布')
    ax2.legend()

    fig.suptitle(f'车辆里程统计 (n={len(df):,})', fontsize=14)
    plt.tight_layout()

    return _save_fig(fig, 'vehicle_mileage.png')


def main() -> None:
    print('=' * 60)
    print('出租车GPS数据可视化')
    print('=' * 60)

    charts = [
        ('出行小时数量统计',    plot_hourly_orders),
        ('各时段订单时长分布',  plot_order_duration_boxplot),
        ('上客点热力分布',      plot_static_heatmap),
        ('车辆位置热力分布',    plot_vehicle_position_heatmap),
        ('载客出租车数量变化',  plot_occupied_taxis),
        ('载客率变化',          plot_occupancy_rate),
        ('出行距离划分',        plot_trip_distance),
        ('各时段道路平均速度',  plot_avg_speed),
        ('15分钟热力切片',      plot_heatmap_slices),
        ('动态热力图',          plot_dynamic_heatmap_gif),
        ('车辆里程统计',        plot_vehicle_mileage),
    ]

    results = []
    for title, func in charts:
        print()
        print(f'--- 生成: {title} ---')
        fig_path = func()
        size_kb = os.path.getsize(fig_path) / 1024
        print(f'  保存: {fig_path} ({size_kb:.1f} KB)')
        results.append((title, fig_path, size_kb))


    print()
    print('=' * 60)
    print('可视化汇总')
    print('=' * 60)
    for title, fig_path, size_kb in results:
        print(f'  {title:20s}  {fig_path}  ({size_kb:.1f} KB)')
    print('=' * 60)


if __name__ == '__main__':
    main()