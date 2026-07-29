"""
Central configuration for the Sensing Leeds Air Quality project.

Every path, column name, and cleaning threshold is defined ONCE, here.
Notebooks and scripts import from this module so nothing drifts out of sync.

Usage from a notebook in notebooks/:
    import sys; sys.path.append(str(Path.cwd().parent))
    from src.config import *
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# The synced OneDrive folder holding the raw sensor data.
# The r"" prefix keeps Windows backslashes literal.
DATA_DIR = Path(
    r"C:\Users\user\OneDrive - University of Leeds\Dissertation Data\SEE AQ Projects-PURPLEAIR - sensor_data"
)

# Project root = the parent of this src/ folder. Everything else hangs off it,
# so the code works regardless of where the repo is cloned.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROCESSED   = PROJECT_ROOT / "data" / "processed"   # combined per-sensor Parquet
CLEANED     = PROCESSED / "cleaned"                  # flagged per-sensor Parquet
OUT_TABLES  = PROJECT_ROOT / "outputs" / "tables"
OUT_FIGURES = PROJECT_ROOT / "outputs" / "figures"
MANIFEST    = PROCESSED / "_ingest_manifest.parquet"

# Make sure the output locations exist on import.
for _d in (PROCESSED, CLEANED, OUT_TABLES, OUT_FIGURES):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Column names (exactly as they appear in the raw CSVs)
# --------------------------------------------------------------------------
DATE_COL = "date"
PM_A     = "PM2.5 A (CF=ATM) (ug/m3)"
PM_B     = "PM2.5 B (CF=ATM) (ug/m3)"
TEMP_COL = "Temperature (F)"
RH_COL   = "Humidity (%)"

# --------------------------------------------------------------------------
# Cleaning thresholds (all from Byrne et al. 2023)
# --------------------------------------------------------------------------
MAX_PLAUSIBLE = 1000     # operational range cap (ug/m3)
PM_BREAK      = 15       # high/low concentration breakpoint (ug/m3)
REL_HIGH      = 0.05     # above 15: flag if relative A/B diff > 5%
REL_LOW       = 0.50     # at/below 15: flag if relative A/B diff > 50%

# --------------------------------------------------------------------------
# Daily aggregation
# --------------------------------------------------------------------------
# Minimum clean readings for a valid daily mean. Chosen from the survival
# sensitivity check: 180 (~6 h of 2-min data) retains 90.6% of sensor-days
# and 43/44 sensors; the survival cliff sits between 240 and 360.
MIN_READINGS_PER_DAY = 180

# Minimum clean readings for a valid HOURLY mean (~30 expected at 2-min
# spacing, so this is a 50% completeness rule). Justified by the subsampling
# test in notebook 04: a contiguous block of 15 readings estimates the true
# hourly mean to ~4% (90th percentile ~16%), and relaxing the threshold to 5
# raises network coverage only to ~52%, so hourly resolution fails even in
# its most permissive form. Used by notebooks 06, 07 and 08.
MIN_READ_PER_HOUR    = 15

# Minimum sensors reporting in an hour for a network-level statistic
# (median or baseline) to be formed from them.
MIN_SENSORS_PER_HOUR = 5

LOCAL_TZ = "Europe/London"    # clock time for diurnal and event analysis

# --------------------------------------------------------------------------
# Concentration Similarity Index (Byrne et al. 2024, AMT 17, 5129-5146)
# --------------------------------------------------------------------------
# The paper's final calibrated parameters (their Sect. 2.2.3):
#   relative difference uses the GEOMETRIC MEAN of the pair as denominator;
#   above PMlim the pair must agree within 20%, at/below within 70%.
CSI_PM_LIM   = 15        # PM concentration breakpoint (ug/m3)
CSI_C_UPPER  = 0.2       # strict similarity limit above PMlim
CSI_C_LOWER  = 0.7       # lenient similarity limit at/below PMlim
MIN_COMMON_DAYS = 30     # min overlapping days for a pair's CSI to be reported
MIN_VALID_DAYS      = 100 # minimum valid days for a sensor to be included in the pairwise analysis

# --------------------------------------------------------------------------
# Baseline separation (notebook 07; Lenschow et al. 2001 decomposition)
# --------------------------------------------------------------------------
# Quantile ACROSS sensors defining the regional baseline at each hour. The
# minimum (q=0) would be set by a single sensor and would be won every hour by
# any sensor reading systematically low, which is the fault being tested for.
BASELINE_Q      = 0.10
# Window for the single-site temporal baseline: long enough to span a synoptic
# episode, short enough to follow seasonal change.
BASELINE_WINDOW = "7D"
# Local-clock hours treated as quiet for the instrument-bias diagnostic.
# Night is a conditioning period, not a definition of clean air: the nocturnal
# boundary layer is shallow, so emissions accumulate rather than disperse.
NIGHT_HOURS     = (1, 5)

# --------------------------------------------------------------------------
# Event analysis (notebook 06)
# --------------------------------------------------------------------------
BONFIRE_YEARS = [2022, 2023, 2024, 2025]
# Excluded from the CONTROL baseline only (neighbouring organised displays);
# raw time-series plots are unaffected.
EVENT_EXCLUDE = ["11-03", "11-04", "11-05", "11-06", "11-07"]

# --------------------------------------------------------------------------
# Study-area definition (used by the sensor filter)
# --------------------------------------------------------------------------
# "Strict Leeds": a bounding box around the Leeds metropolitan area.
LEEDS_BOX = dict(lat_min=53.65, lat_max=54.00, lon_min=-1.80, lon_max=-1.25)
