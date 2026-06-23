import math
import os
import logging

logger = logging.getLogger(__name__)

# ── Matplotlib CJK font setup ─────────────────────────────────────────────

def setup_matplotlib_cjk() -> None:
    """Configure matplotlib to render CJK characters.

    Uses a fallback chain: SimHei → WenQuanYi Micro Hei → Noto Sans CJK SC
    → DejaVu Sans (last resort).  Silently succeeds if any CJK font is
    found, otherwise logs a warning.
    """
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties, findfont

    _FALLBACK_FONTS = [
        'SimHei',
        'WenQuanYi Micro Hei',
        'Noto Sans CJK SC',
        'DejaVu Sans',
    ]

    chosen = None
    for name in _FALLBACK_FONTS:
        try:
            fp = FontProperties(family=name)
            findfont(fp, fallback_to_default=False)
            chosen = name
            break
        except Exception:
            continue

    if chosen is None:
        logger.warning('No CJK font found; matplotlib may not render Chinese correctly.')
        return

    plt.rcParams['font.family'] = chosen
    plt.rcParams['axes.unicode_minus'] = False
    logger.info('matplotlib CJK font set to %s', chosen)


# ── Haversine ──────────────────────────────────────────────────────────────

def haversine_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Great-circle distance between two points on Earth (Haversine formula).

    Parameters
    ----------
    lat1, lon1 : float  — point A in decimal degrees.
    lat2, lon2 : float  — point B in decimal degrees.

    Returns
    -------
    float — distance in kilometres.
    """
    R = 6371.0  # Earth mean radius, km

    φ1 = math.radians(lat1)
    φ2 = math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)

    a = (
        math.sin(Δφ / 2) ** 2
        + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ── I/O helpers ────────────────────────────────────────────────────────────

def assert_input_exists(path: str) -> None:
    """Raise ``FileNotFoundError`` if *path* does not exist."""
    if not os.path.exists(path):
        raise FileNotFoundError(f'Input file not found: {path}')


def assert_output_valid(path: str) -> None:
    """Raise ``RuntimeError`` if *path* does not exist after a write
    operation (i.e. something went wrong during creation)."""
    if not os.path.exists(path):
        raise RuntimeError(f'Output file was not created: {path}')
