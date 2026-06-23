import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
FIGURES_DIR = os.path.join(OUTPUT_DIR, 'figures')


DATA_FILE = 'TaxiData.csv'


COLUMNS = ['id', 'time', 'long', 'lati', 'status', 'speed']
DTYPES = {
    'id': 'int32',
    'time': 'str',
    'long': 'float32',
    'lati': 'float32',
    'status': 'int8',
    'speed': 'int16',
}


SHENZHEN_BOUNDS = {
    'long_min': 113.5,
    'long_max': 114.8,
    'lat_min': 22.3,
    'lat_max': 22.9,
}


SPEED_MAX = 120
ANOMALY_TIME_THRESHOLD = 60


DBSCAN_EPS = 0.004
DBSCAN_MIN_SAMPLES = 50


DISTANCE_SHORT = 4
DISTANCE_LONG = 8


BAIDU_MAP_API_KEY = 'XNkwzmc37WX3fgtuIhmTF521kuAXzgja'


FLOW_GRID_SIZE = 0.015
TOP_FLOWS = 300


ARIMA_TEST_RATIO = 0.2
