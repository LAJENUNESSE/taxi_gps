import os

# ── Project paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
FIGURES_DIR = os.path.join(OUTPUT_DIR, 'figures')

# ── Data file ──────────────────────────────────────────────────────────────
DATA_FILE = 'TaxiData.csv'

# ── Columns & dtypes ───────────────────────────────────────────────────────
COLUMNS = ['id', 'time', 'long', 'lati', 'status', 'speed']
DTYPES = {
    'id': 'int32',
    'time': 'str',
    'long': 'float32',
    'lati': 'float32',
    'status': 'int8',
    'speed': 'int16',
}

# ── Geographic bounds (Shenzhen) ──────────────────────────────────────────
SHENZHEN_BOUNDS = {
    'long_min': 113.5,
    'long_max': 114.8,
    'lat_min': 22.3,
    'lat_max': 22.9,
}

# ── Filtering & anomaly detection ─────────────────────────────────────────
SPEED_MAX = 120                          # km/h — speed cap for reasonable GPS
ANOMALY_TIME_THRESHOLD = 60              # seconds — gap threshold for trip break

# ── DBSCAN clustering ──────────────────────────────────────────────────────
DBSCAN_EPS = 0.004                       # radians (~400 m at Shenzhen lat)
DBSCAN_MIN_SAMPLES = 50

# ── Trip classification ────────────────────────────────────────────────────
DISTANCE_SHORT = 4                       # km
DISTANCE_LONG = 8                        # km

# ── Baidu Maps API ─────────────────────────────────────────────────────────
BAIDU_MAP_API_KEY = 'XNkwzmc37WX3fgtuIhmTF521kuAXzgja'

# ── Flow map grid ──────────────────────────────────────────────────────────
FLOW_GRID_SIZE = 0.015               # degrees (~1.5 km grid for aggregation)
TOP_FLOWS = 300                      # number of flow lines to draw

# ── ARIMA ──────────────────────────────────────────────────────────────────
ARIMA_TEST_RATIO = 0.2
