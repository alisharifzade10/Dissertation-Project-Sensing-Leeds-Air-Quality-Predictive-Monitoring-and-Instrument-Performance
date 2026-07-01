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
# Study-area definition (used by the sensor filter)
# --------------------------------------------------------------------------
# "Strict Leeds": a bounding box around the Leeds metropolitan area.
LEEDS_BOX = dict(lat_min=53.65, lat_max=54.00, lon_min=-1.80, lon_max=-1.25)