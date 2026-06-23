
"""出租车GPS数据可视化 — 8个图表

图表:
  1. 出行小时数量统计      → output/figures/hourly_orders.png
  2. 各时段订单时长分布    → output/figures/order_duration_boxplot.png
  3. 上客点热力分布        → output/figures/static_heatmap.png
  4. 载客出租车数量变化    → output/figures/occupied_taxis.png
  5. 出行距离划分          → output/figures/trip_distance.png
  6. 各时段道路平均速度    → output/figures/avg_speed.png
  7. 15分钟热力切片        → output/figures/heatmap_slices.png
  8. 动态热力图            → output/figures/dynamic_heatmap.gif
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


def main() -> None:
    print('=' * 60)
    print('出租车GPS数据可视化')
    print('=' * 60)

    charts = [
        ('出行小时数量统计',    plot_hourly_orders),
        ('各时段订单时长分布',  plot_order_duration_boxplot),
        ('上客点热力分布',      plot_static_heatmap),
        ('载客出租车数量变化',  plot_occupied_taxis),
        ('出行距离划分',        plot_trip_distance),
        ('各时段道路平均速度',  plot_avg_speed),
        ('15分钟热力切片',      plot_heatmap_slices),
        ('动态热力图',          plot_dynamic_heatmap_gif),
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