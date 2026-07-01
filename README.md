# Sensing Leeds Air Quality — Predictive Monitoring and Instrument Performance

MATH5872M Dissertation in Data Science and Analytics, University of Leeds.

Quality assessment and fault detection across a network of 47 outdoor PurpleAir
low-cost PM2.5 sensors in Leeds (2022–2026), building toward a Cross-Sensor
Index (CSI) for network-wide analysis.

## Repository layout

```
src/
  config.py        Single source of truth: data path, column names, thresholds, output paths.
  cleaning.py      The clean_sensor quality-flagging function (Byrne et al. 2023).
  loader.py        Incremental data refresh — reads only new/changed daily files.
notebooks/
  00_check_data.ipynb       Verify the OneDrive data folder is readable.
  01_filter_sensors.ipynb   Apply study-area / indoor / test rules; save the study list + map.
  02_combine_sensors.ipynb  Stack daily CSVs into one Parquet per sensor; build the inventory.
  03_explore_quality.ipynb  PM distribution, A/B agreement, time gaps on sample sensors.
  04_cleaning.ipynb         Flag all sensors; network summary + fault-candidate table.
  05_csi.ipynb              (next) Humidity correction, resampling, Cross-Sensor Index.
data/processed/    Combined + cleaned per-sensor Parquet (gitignored — data is not committed).
outputs/figures/   Saved figures.
outputs/tables/    Decision logs, inventory, cleaning + fault tables.
Reports/           Dissertation and milestone documents.
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Set the raw-data location in one place — `src/config.py`, the `DATA_DIR` line.
Nothing else hardcodes a path.

## Run order

Run the notebooks in numeric order the first time:

1. `00_check_data` — confirm the data folder is visible.
2. `01_filter_sensors` — produces `study_sensors.csv` and the kept/excluded map.
3. `02_combine_sensors` — builds `data/processed/*.parquet` and `sensor_inventory.csv`.
4. `03_explore_quality` — exploratory figures.
5. `04_cleaning` — produces cleaned Parquet, `cleaning_summary.csv`, and the fault table.

### Refreshing the data later

The raw data updates daily for some sensors. Rather than re-running the full
combine in notebook 02, refresh incrementally from the project root:

```bash
python -m src.loader
```

This reads only new or changed daily files (re-reading the last 2 days to catch
the still-growing current day) and appends them to each sensor's Parquet. It
depends on `sensor_inventory.csv`, so notebook 02 must have run at least once.
After refreshing, re-run notebook 04 to update the cleaned outputs.

## Notes

- 48 sensors pass the study-area filter; 47 have data folders on disk (SL71
  Kentmere has none), so the analysis covers 47. The 48 → 47 drop is expected.
- Cleaning flags rows rather than deleting them, preserving a full audit trail.
- The fault table separates high-band from low-band A/B disagreement: high-band
  points to genuine hardware faults, low-band is noise-prone near-clean air.
```
