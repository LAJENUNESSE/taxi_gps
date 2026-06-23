
"""出租车GPS预测 — ARIMA需求预测 + XGBoost ETA预测

产出:
  6.1 ARIMA 需求预测 → data/demand_forecast.csv, output/figures/demand_forecast.png
  6.2 XGBoost ETA预测 → data/eta_forecast.csv, output/figures/eta_feature_importance.png
"""

import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.config import ARIMA_TEST_RATIO, DATA_DIR
from src.utils import assert_input_exists, setup_matplotlib_cjk


def arima_forecast() -> None:
    """6.1 ARIMA需求预测: 基于 hourly_orders.csv 的订单数时间序列预测."""
    print('=' * 60)
    print('6.1 ARIMA 需求预测')
    print('=' * 60)


    hourly_path = os.path.join(DATA_DIR, 'hourly_orders.csv')
    assert_input_exists(hourly_path)
    df = pd.read_csv(hourly_path)
    series = df['数量'].values.astype(float)
    print(f'数据 : {hourly_path}  ({len(series)} 行)')


    split_idx = int(len(series) * (1 - ARIMA_TEST_RATIO))
    train, test = series[:split_idx], series[split_idx:]
    print(f'训练集: {len(train)}  测试集: {len(test)}  (ratio={ARIMA_TEST_RATIO})')


    from statsmodels.tsa.arima.model import ARIMA

    model = ARIMA(train, order=(1, 1, 1))
    model_fit = model.fit()
    forecast = model_fit.forecast(steps=len(test))
    print(f'ARIMA(1,1,1) — AIC: {model_fit.aic:.2f}')


    rmse = np.sqrt(mean_squared_error(test, forecast))
    mae = mean_absolute_error(test, forecast)
    print(f'RMSE: {rmse:.2f}  MAE: {mae:.2f}')

    print('预测值 vs 实际值（前5个）:')
    for i in range(min(5, len(test))):
        print(f'  [{split_idx + i}h] 实际: {test[i]:.0f}  预测: {forecast[i]:.0f}')


    hours = list(range(split_idx, len(series)))
    df_out = pd.DataFrame({
        'hour': hours,
        'actual': test,
        'predicted': forecast,
    })
    out_path = os.path.join(DATA_DIR, 'demand_forecast.csv')
    df_out.to_csv(out_path, index=False)
    print(f'保存: {out_path}')


    setup_matplotlib_cjk()
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(series)), series, 'b-', label='全部实际值')
    ax.axvline(x=split_idx - 1, color='gray', linestyle='--', label='训练/测试分割线')
    ax.plot(range(split_idx, len(series)), forecast, 'r--', marker='o', label='ARIMA预测')
    ax.set_xlabel('小时')
    ax.set_ylabel('订单数')
    ax.set_title(f'ARIMA需求预测 (RMSE={rmse:.0f}, MAE={mae:.0f})')
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'output', 'figures', 'demand_forecast.png',
    )
    os.makedirs(os.path.dirname(fig_path), exist_ok=True)
    fig.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'保存: {fig_path}')
    print()


def xgboost_eta() -> None:
    """6.2 XGBoost ETA预测: 基于 orders.csv 预测 OD_TIME_s."""
    print('=' * 60)
    print('6.2 XGBoost ETA 预测')
    print('=' * 60)


    orders_path = os.path.join(DATA_DIR, 'orders.csv')
    assert_input_exists(orders_path)
    df = pd.read_csv(orders_path)
    print(f'数据 : {orders_path}  ({len(df):,} 行)')


    df['开始时间'] = pd.to_datetime(df['开始时间'])
    df['hour'] = df['开始时间'].dt.hour

    feature_cols = ['开始纬度', '开始经度', '结束纬度', '结束经度', 'OD_Dis_km', 'hour']
    target_col = 'OD_TIME_s'


    df = df.sort_values('开始时间').reset_index(drop=True)
    split_idx = int(len(df) * (1 - ARIMA_TEST_RATIO))
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    X_train = train_df[feature_cols].values
    y_train = train_df[target_col].values
    X_test = test_df[feature_cols].values
    y_test = test_df[target_col].values

    print(f'训练集: {len(X_train):,}  测试集: {len(X_test):,}')


    import xgboost as xgb

    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)


    y_pred = np.maximum(y_pred, 0)


    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    mae = mean_absolute_error(y_test, y_pred)
    print(f'RMSE: {rmse:.2f} s  MAE: {mae:.2f} s')


    importance = model.feature_importances_
    indices = np.argsort(importance)[::-1]
    print('特征重要性（前5个）:')
    for rank, idx in enumerate(indices[:5], 1):
        print(f'  {rank}. {feature_cols[idx]:16s}  {importance[idx]:.4f}')


    df_out = pd.DataFrame({
        'actual_s': y_test,
        'predicted_s': y_pred,
        'error_s': y_test - y_pred,
    })
    out_path = os.path.join(DATA_DIR, 'eta_forecast.csv')
    df_out.to_csv(out_path, index=False)
    print(f'保存: {out_path}')


    setup_matplotlib_cjk()
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(feature_cols)))
    ax.barh(
        [feature_cols[i] for i in indices],
        importance[indices],
        color=colors,
    )
    ax.invert_yaxis()
    ax.set_xlabel('重要性')
    ax.set_title('XGBoost 特征重要性')
    ax.grid(True, axis='x', alpha=0.3)

    fig_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'output', 'figures', 'eta_feature_importance.png',
    )
    os.makedirs(os.path.dirname(fig_path), exist_ok=True)
    fig.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'保存: {fig_path}')
    print()


def verify_nonnegative() -> None:
    """验证预测结果非负."""
    demand_path = os.path.join(DATA_DIR, 'demand_forecast.csv')
    eta_path = os.path.join(DATA_DIR, 'eta_forecast.csv')

    df_demand = pd.read_csv(demand_path)
    df_eta = pd.read_csv(eta_path)

    demand_ok = (df_demand['predicted'] >= 0).all()
    eta_ok = (df_eta['predicted_s'] >= 0).all()

    print('=' * 60)
    print('非负验证')
    print('=' * 60)
    status_d = '✓ PASS' if demand_ok else '✗ FAIL'
    status_e = '✓ PASS' if eta_ok else '✗ FAIL'
    print(f'  需求预测非负: {status_d}')
    print(f'  ETA 预测非负: {status_e}')
    print(f'  demand min: {df_demand["predicted"].min():.2f}')
    print(f'  eta    min: {df_eta["predicted_s"].min():.2f}')
    print('=' * 60)


def main() -> None:
    arima_forecast()
    xgboost_eta()
    verify_nonnegative()


if __name__ == '__main__':
    main()
