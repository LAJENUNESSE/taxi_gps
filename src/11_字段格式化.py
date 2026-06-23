#!/usr/bin/env python3
"""字段名对齐 — 将流水线输出 CSV 的字段名改为实训V_项目介绍.md 要求的命名规范。

字段名对照表（实训V_项目介绍.md Lines 28-44）：
  O_COMMADDR  出租车id
  O_time      上客点时间
  O_lat       上客点纬度
  O_lng       上客点经度
  O_HEAD      上客点车辆方向
  O_SPEED     上客点车辆速度
  O_FLAG      上客点车辆状态
  D_time      下客点时间
  D_lat       下客点纬度
  D_lng       下客点经度
  D_HEAD      下客点车辆方向
  D_SPEED     下客点车辆速度
  D_FLAG      下客点车辆状态
  OD_TIME_s   OD对的时间（秒）
  OD_Dis_km   OD对的距离（千米）

用法:
    python src/11_字段格式化.py      # 生成规整化 CSV
    python src/11_字段格式化.py -c   # 检查当前列名是否合规
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATA_DIR

# ── 字段映射 ────────────────────────────────────────────────────────────────
ORDERS_RENAME = {
    '车辆id': 'O_COMMADDR',
    '开始时间': 'O_time',
    '开始经度': 'O_lng',
    '开始纬度': 'O_lat',
    '结束时间': 'D_time',
    '结束经度': 'D_lng',
    '结束纬度': 'D_lat',
}

HOURLY_RENAME = {
    '小时': 'O_time',
    '数量': 'count',
}

REQUIRED_FILES = [
    ('orders.csv', ORDERS_RENAME),
    ('hourly_orders.csv', HOURLY_RENAME),
]


def check() -> bool:
    """检查现有 CSV 列名是否需要修正，返回 True 表示全部合规。"""
    ok = True
    for fname, mapping in REQUIRED_FILES:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            print(f'  [MISS] {fname} — 文件不存在')
            ok = False
            continue
        df = pd.read_csv(path, nrows=0)
        cols = set(df.columns)
        needed = set(mapping.values())
        if needed.issubset(cols):
            print(f'  [OK]   {fname} — 列名已合规')
        else:
            missing = needed - cols
            print(f'  [FIX]  {fname} — 缺少字段: {missing}')
            print(f'         当前列: {list(df.columns)}')
            ok = False
    return ok


def fix() -> None:
    """读取原 CSV，重命名列，写出 *_spec.csv。"""
    for fname, mapping in REQUIRED_FILES:
        src = os.path.join(DATA_DIR, fname)
        if not os.path.exists(src):
            print(f'跳过 {fname}: 文件不存在')
            continue

        df = pd.read_csv(src)
        # 只重命名 mapping 中存在的列，忽略不存在的
        df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})

        stem, ext = os.path.splitext(fname)
        dst = os.path.join(DATA_DIR, f'{stem}_spec{ext}')
        df.to_csv(dst, index=False)
        print(f'  {src} → {dst}')
        print(f'    列名: {list(df.columns)}')

    print('\n完成。运行 python src/11_字段格式化.py -c 确认合规。')


def main() -> None:
    parser = argparse.ArgumentParser(description='对齐输出 CSV 字段名到实验要求规范')
    parser.add_argument('-c', '--check', action='store_true',
                        help='仅检查列名合规性，不生成文件')
    args = parser.parse_args()

    if args.check:
        print('检查输出文件字段名合规性 ...')
        ok = check()
        print()
        if ok:
            print('全部合规 ✓')
        else:
            print('部分文件需要修复，运行 python src/11_字段格式化.py 生成规整版')
        sys.exit(0 if ok else 1)
    else:
        print('对齐字段名到实验要求规范 ...')
        fix()


if __name__ == '__main__':
    main()
