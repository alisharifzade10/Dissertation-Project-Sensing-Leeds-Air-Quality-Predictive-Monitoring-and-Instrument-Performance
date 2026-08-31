"""
Central configuration for the Sensing Leeds Air Quality project.

Every path, column name, and threshold is defined ONCE, here. Notebooks and
scripts import from this module so nothing drifts out of sync.

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

PROCESSED   = PROJECT_ROOT / "data" / "processed"    # combined per-sensor Parquet
CLEANED     = PROCESSED / "cleaned"                  # flagged per-sensor Parquet
DERIVED     = PROCESSED / "derived"                  # network-level matrices
OUT_TABLES  = PROJECT_ROOT / "outputs" / "tables"
OUT_FIGS    = PROJECT_ROOT / "outputs" / "figures"
MANIFEST    = PROCESSED / "_ingest_manifest.parquet"

# Older notebooks import these names; kept as aliases so nothing breaks.
Tables  = OUT_TABLES
Figures = OUT_FIGS

for _d in (PROCESSED, CLEANED, DERIVED, OUT_TABLES, OUT_FIGS):
    _d.mkdir(parents=True, exist_ok=True)

# Network-level products. These live in DERIVED, not PROCESSED, so that the
# per-sensor globs in later notebooks cannot accidentally pick them up.
DAILY_MATRIX  = DERIVED / "daily_matrix.parquet"
HOURLY_MATRIX = DERIVED / "network_hourly_sensors.parquet"
HOURLY_STATS  = DERIVED / "hourly_stats"             # one Parquet per sensor (NB08)
HOURLY_STATS.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Column names (exactly as they appear in the raw CSVs)
# --------------------------------------------------------------------------
DATE_COL = "date"
PM_A     = "PM2.5 A (CF=ATM) (ug/m3)"
PM_B     = "PM2.5 B (CF=ATM) (ug/m3)"
TEMP_COL = "Temperature (F)"
RH_COL   = "Humidity (%)"

# --------------------------------------------------------------------------
# Cleaning thresholds
# --------------------------------------------------------------------------
# Byrne et al. (2024, Sect. 2.1.2) quote the PMS5003 as having an EFFECTIVE
# range of 0-500 ug/m3 and a MAXIMUM range of 1000. Readings above the maximum
# cannot be a measurement at all, so that is the implausibility cut. Readings
# between the two are retained but sit outside the range the manufacturer
# claims accuracy for, and notebook 03 reports how many there are.
EFFECTIVE_MAX = 500
MAX_PLAUSIBLE = 1000

PM_BREAK      = 15       # high/low concentration breakpoint (ug/m3)
REL_HIGH      = 0.05     # above 15: flag if relative A/B diff > 5%
REL_LOW       = 0.50     # at/below 15: flag if relative A/B diff > 50%

# Absolute floor on the A/B difference. Byrne et al. (2023) apply the relative
# test alone, which is fine for Cork where wintertime PM2.5 is high. Leeds air
# is much cleaner, so a 50% relative difference is routinely produced by
# counting noise between two healthy channels. Barkjohn et al. (2021), whose
# criterion underpins the US EPA AirNow correction, pair the relative test with
# an absolute floor for exactly this reason.
# Set to 0.0 to reproduce Byrne exactly; notebook 04 sweeps this value.
AB_ABS_MIN     = 1.0
AB_FLOOR_SWEEP = (0.0, 0.5, 1.0, 2.0, 5.0)

# Flatline (frozen-reading) detector. A run of identical values on BOTH
# channels is invisible to the A/B test, because the channels agree perfectly.
# 90 readings at 2-min spacing = 3 hours.
FLATLINE_RUN = 90
# A PMS5003 in genuinely clean air reports 0.0 legitimately, so a run of exact
# zeros is not evidence of frozen electronics. Flagging it would also remove
# the cleanest readings in the network, which are the ones that set the
# spatial baseline in notebook 07. Runs at zero are therefore counted and
# reported separately rather than flagged. Notebook 04 shows both counts.
FLATLINE_IGNORE_ZERO = True

# --------------------------------------------------------------------------
# Humidity correction
# --------------------------------------------------------------------------
# Barkjohn et al. (2021) fitted their US-wide correction to PA cf_1, while the
# Leeds archive exports cf_atm. Barkjohn et al. report that the two columns
# stand in a 1:1 relationship below roughly 25 ug/m3 as reported by the sensor,
# diverging to a two-thirds ratio above it. Leeds daily means sit at a few
# ug/m3, so the columns are interchangeable across almost the whole dataset;
# the exception is event hours, where cf_atm reads low and the corrected value
# is therefore conservative. Notebook 05 reports how much data sits above it.
CF_EQUIV_LIMIT = 25

# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
# Minimum clean readings for a valid daily mean. Chosen from the survival
# sensitivity check in notebook 04: 180 (~6 h of 2-min data) retains 93.1% of
# sensor-days and 43/44 sensors; the survival cliff sits between 240 and 360.
MIN_READINGS_PER_DAY = 180

# Minimum clean readings for a valid HOURLY mean (~30 expected at 2-min
# spacing, so a 50% completeness rule). Justified by the subsampling test in
# notebook 04. Used by notebooks 06, 07 and 08.
MIN_READ_PER_HOUR = 15

# Minimum sensors reporting before a network MEDIAN is formed. A median is
# stable at small n, so this is the looser of the two bars.
MIN_SENSORS_PER_HOUR = 5

# Minimum sensors reporting before the 10th-percentile BASELINE is formed.
# This is deliberately stricter than MIN_SENSORS_PER_HOUR. With n reporting
# sensors, linear interpolation places the 0.10 quantile at index 0.1*(n-1),
# so at n = 5 the "10th percentile" carries 60% weight on the single lowest
# sensor -- i.e. it is the minimum, which is the statistic the baseline was
# chosen to avoid, and which is won by whichever sensor reads systematically
# low. At n >= 12 the quantile is set by the second and third lowest sensors
# and the intended behaviour is recovered.
MIN_SENSORS_FOR_BASELINE = 12

LOCAL_TZ = "Europe/London"    # clock time for diurnal and event analysis

# --------------------------------------------------------------------------
# Concentration Similarity Index (Byrne et al. 2024, AMT 17, 5129-5146)
# --------------------------------------------------------------------------
# The paper's final calibrated parameters (their Sect. 2.2.3):
#   relative difference uses the GEOMETRIC MEAN of the pair as denominator;
#   above PMlim the pair must agree within 20%, at/below within 70%.
CSI_PM_LIM      = 15         # PM concentration breakpoint (ug/m3)
CSI_C_UPPER     = 0.2        # strict similarity limit above PMlim
CSI_C_LOWER     = 0.7        # lenient similarity limit at/below PMlim
MIN_COMMON_DAYS = 30         # min overlapping days for a pair's CSI
MIN_VALID_DAYS  = 100        # min valid days for a sensor to enter the analysis

# Recent-window CSI (notebook 05). A full year avoids comparing a summer
# window against a lifetime that is half winter.
RECENT_WINDOW_DAYS = 365
RECENT_MIN_DAYS    = 60      # valid days a sensor needs inside the window

# --------------------------------------------------------------------------
# Baseline separation (notebook 07)
# --------------------------------------------------------------------------
BASELINE_Q       = 0.10      # quantile ACROSS sensors defining the baseline
BASELINE_Q_SWEEP = (0.05, 0.10, 0.25)
NIGHT_HOURS      = (1, 5)    # local-clock hours treated as quiet

# --------------------------------------------------------------------------
# Event analysis (notebook 06)
# --------------------------------------------------------------------------
BONFIRE_YEARS = [2022, 2023, 2024, 2025]
# One event window, used by notebooks 06, 07 and 08 alike: 17:00 on 5 November
# to 01:00 on the 6th, local clock.
EVENT_START_HOUR = 17
EVENT_N_HOURS    = 8
# Control evenings come from the same weeks in the same years: 25 October to
# 15 November, excluding 2-7 November so the neighbouring organised displays
# do not contaminate the baseline.
CONTROL_START = "10-25"
CONTROL_END   = "11-15"
EVENT_EXCLUDE = ["11-02", "11-03", "11-04", "11-05", "11-06", "11-07"]

# --------------------------------------------------------------------------
# Local-source discrimination (notebook 08)
# --------------------------------------------------------------------------
# Byrne et al. (2023) mark an hour as locally influenced when the standard
# deviation of the two-minute readings about their own hourly mean exceeds a
# threshold. They chose 2 ug/m3 by visual inspection, having also tried 1 and
# 3; the sweep below repeats that comparison on the Leeds data.
SIGMA_DPM_THRESH = 2.0
SIGMA_DPM_SWEEP  = (1.0, 2.0, 3.0)
# Longest gap, in hours, the episode background may be interpolated across.
# Beyond this the sensor has been off air and an interpolated background is a
# guess rather than a measurement.
SIGMA_DPM_MAX_GAP = 6

# Domestic solid fuel is a heating-season source, so the two halves of the year
# are compared directly. Shoulder months are left out of both, so the contrast
# is between clearly heating and clearly non-heating periods.
WINTER_MONTHS = (11, 12, 1, 2)
SUMMER_MONTHS = (5, 6, 7, 8)

# Spatial coherence test (van Zoest et al. 2018): a real event shows up at more
# than one site, an instrument fault does not.
N_NEIGHBOURS = 5             # nearest sensors used as the comparison group
EXCURSION_Q  = 0.90          # a sensor's excursion days are its own top decile

# Which sensors get a verdict in notebook 08.
CSI_FLAG_LEVEL = 0.55        # lifetime mean CSI at or below this is flagged
CSI_FLAG_N     = 6           # plus the N worst, whatever their score
# A sensor can fail the A/B test heavily and still score well on the CSI,
# because the cleaning removes the disagreeing rows and the survivors agree
# with the network. SL037 is the example. Such a sensor has to enter the
# candidate set by its own route or it is never diagnosed.
#
# 50% is deliberately loose here, and is an ENTRY bar only. NB04's own
# Figure 1 shows the network-wide high-band rate running from about 30% to
# 98% with a mean of 68%: at Leeds concentrations even a healthy PA-II fails
# Byrne's +/-5% test on Poisson noise alone, so a 50% cut catches most of the
# network. That is fine for casting a wide net at entry, but it must not also
# be the bar a VERDICT is decided on, or "candidate" becomes a synonym for
# "member of the network".
AB_FLAG_LEVEL  = 50.0        # % of high-band readings A/B-flagged (candidate entry only)
# The verdict-stage bar is a top-decile cut, not a natural break: the
# high-band ranking declines smoothly (97.9, 97.8, 97.7, 94.1, 92.7, 91.4,
# 90.5, 90.5, 88.9, 86.3, ...), so 90% is a judgement call that isolates the
# worst 8 of 47 sensors rather than a gap in the distribution. It is chosen
# to be defensible as triage, and sensors just below it (SL062 at 88.9%)
# are reported as worth monitoring rather than excluded. SL001, inside this
# group, is independently corroborated in NB03: 173,197 channel-A readings
# above the 1000 ug/m3 ceiling while channel B stayed in range.
AB_VERDICT_LEVEL = 90.0    # % of high-band readings A/B-flagged, single-channel VERDICT
# ... but only once there are enough high-band readings for the rate to mean
# anything. A clean, short-lived sensor can post 100% on a dozen readings.
AB_MIN_HIGHBAND = 500

# Verdict thresholds, each in the units of the quantity it tests.
VERDICT_BIAS_MIN = 1.0       # |bias| at 15 ug/m3, above which calibration matters
VERDICT_CSI_GAIN = 0.10      # CSI recovery after harmonisation counted as real
VERDICT_WS_RATIO = 1.5       # winter:summer local-influence ratio of a source
VERDICT_FLATLINE = 5.0       # % of readings frozen
# A candidate counts as "fluctuating" if EITHER its sigma_DPM hour-fraction OR
# its p90 daily increment above the leave-one-out baseline exceeds the
# reference group (see NB08 section 5). The two are not interchangeable:
# sigma_DPM catches short, spiky excursions, while the increment catches a
# site that sits persistently above the regional background without
# necessarily spiking minute to minute within the hour. SL051 is the case
# that makes this matter -- Bramham has the largest p90 daily increment in the
# network by a wide margin but a below-median sigma_DPM hour-fraction, because
# its evening enhancement looks like a sustained village-wide level rather
# than a single chimney plume passing the sensor. Gating on sigma_DPM alone
# sends it straight to "unresolved" despite near-zero neighbour sharing, a
# winter:summer ratio well above 1.5, strong autocorrelation and near-perfect
# channel agreement -- every other test in the notebook pointing at a local
# source.
# Lag-1 autocorrelation of the two-minute readings inside a flagged hour. A
# plume arriving and clearing over minutes is strongly autocorrelated;
# electronic noise is independent from reading to reading whatever its size.
VERDICT_LAG1     = 0.30
# Correlation between the two channels during flagged hours. Real particles
# reach both counters at once; a failing detector moves one and not the other.
VERDICT_AB_CORR  = 0.50

# --------------------------------------------------------------------------
# Study-area definition (used by the sensor filter)
# --------------------------------------------------------------------------
# "Strict Leeds": a bounding box around the Leeds metropolitan area.
LEEDS_BOX = dict(lat_min=53.65, lat_max=54.00, lon_min=-1.80, lon_max=-1.25)