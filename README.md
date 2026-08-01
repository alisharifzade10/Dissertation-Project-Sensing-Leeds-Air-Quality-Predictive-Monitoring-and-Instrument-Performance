# Sensing Leeds Air Quality: Predictive Monitoring and Instrument Performance

MSc dissertation project, MATH5872M (Data Science and Analytics), University of Leeds.

**Author:** Ali Sharifzade
**Supervisors:** Jim McQuaid (Faculty of Environment), Luisa Cutillo (School of Mathematics)

---

## 1. What this project does

Leeds runs a network of roughly 48 outdoor PurpleAir PA-II low-cost sensors measuring PM2.5. Each unit logs a reading about every two minutes, and the archive used here runs from March 2022 to July 2026, which is on the order of 25 million rows before any filtering.

Two questions drive the analysis, and both come from the practical needs of whoever operates the network:

1. **Event detection.** When PM2.5 rises at a site, is that a real local pollution episode worth reporting to Leeds City Council, or is it an artefact of the instrument?
2. **Fault detection.** Which units are drifting, half-dead, or reporting nonsense, so that a site visit can be scheduled instead of the data being trusted?

The two questions are the same question asked from opposite sides. A sensor that disagrees with its neighbours is either seeing something they cannot see, or is broken. Separating those two cases is the core methodological problem of the dissertation.

Everything in this repository is built to answer that separation question in a reproducible way: ingest the raw archive once, clean it according to published low-cost-sensor practice, decompose each site into a network-wide component plus a local residual, and then flag both events and faults from that decomposition.

---

## 2. Repository layout

```
Dissertation Sensing Leeds Air Quality/
├── src/                        # importable package, all reusable logic
│   ├── __init__.py
│   ├── config.py               # thresholds, paths, constants (single source of truth)
│   ├── loader.py               # manifest-driven incremental ingestion to Parquet
│   ├── cleaning.py             # A/B channel flagging + humidity correction
│   ├── csi.py                  # Concentration Similarity Index
│   ├── baseline.py             # spatial baseline, offset/gain, diurnal, site typing
│   └── aurn_reader.py          # DEFRA AURN flat-file downloader and parser
├── notebooks/                  # numbered 00-08, narrative analysis
├── data/
│   ├── raw/                    # symlink / path to OneDrive archive (not in git)
│   └── processed/              # Parquet outputs (gitignored)
├── figures/                    # exported figures used in the report
├── reports/                    # milestone documents
└── README.md
```

The split is deliberate. Notebooks tell the story and produce figures; they do not define constants and they do not hold algorithms. Anything that could be reused, tested, or quoted in the methodology chapter lives in `src/`. This also satisfies the handbook requirement that code be referenced by module name in the main text rather than pasted into it.

### Data locations

| What | Where |
|---|---|
| Raw PurpleAir CSVs | `C:\Users\user\OneDrive - University of Leeds\SEE AQ Projects-PURPLEAIR - sensor_data` |
| Project root | `C:\Users\user\Desktop\University\Dissertation\Dissertation Sensing Leeds Air Quality\` |
| Processed Parquet | `data/processed/` (gitignored) |
| AURN reference CSVs | fetched on demand by `aurn_reader.py`, cached locally |

The GitHub repository holds code only. No sensor data is committed, partly for size and partly because the archive sits on university storage.

---

## 3. Environment

- Python 3.14 in a local `.venv`
- VS Code with the Jupyter extension
- Core libraries: `pandas`, `pyarrow`, `matplotlib`, `folium`, `contextily`, `nbformat`, `nbclient`

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Notebooks import from `src/` as a package, so run them with the project root on the path. During active development, put this at the top of each notebook:

```python
%load_ext autoreload
%autoreload 2
# keep the magic on its own line, above the imports
```

Stale modules caused several hours of confusion early in the project: a file was edited on disk, the notebook kept raising the identical error, and the cause was the old module still sitting in `sys.modules`. If `%autoreload` is not enough, force it:

```python
import importlib, src.cleaning
importlib.reload(src.cleaning)
```

---

## 4. Pipeline

### 4.0 Configuration (`src/config.py`)

Every threshold, path and constant lives here. Nothing is hard-coded in a notebook. This started as tidiness and became a correctness requirement: an earlier version of `csi.py` imported its constants inside a `try/except ImportError` block with a misspelled name, so the import silently failed and the module quietly ran on fallback values for several days. The fix was to import explicitly and let a bad name raise.

Constants of note:

| Name | Value | Basis |
|---|---|---|
| `MIN_READINGS_PER_DAY` | 180 | Survival test: retains 90.6% of sensor-days and 43/44 sensors; the survival cliff sits between 240 and 360 |
| `MIN_READ_PER_HOUR` | 15 | 50% completeness at 2-min spacing; subsampling test gives ~4% typical error, ~16% at the 90th percentile |
| `MIN_SENSORS_PER_HOUR` | 5 | Minimum reporting sensors for a network median or baseline to be formed |
| `LOCAL_TZ` | `Europe/London` | Applied once, at the point of resampling |
| `CSI_PM_LIM` | 15 µg/m³ | Byrne et al. (2024) concentration breakpoint |
| `CSI_C_UPPER` / `CSI_C_LOWER` | 0.2 / 0.7 | Strict limit above the breakpoint, lenient at or below |
| `MIN_COMMON_DAYS` | 30 | Suppresses a CSI computed from negligible deployment overlap |
| `MIN_VALID_DAYS` | 100 | Sensor inclusion threshold for the pairwise matrix |
| `BASELINE_Q` | 0.10 | Quantile across sensors defining the regional baseline |
| `BASELINE_WINDOW` | `7D` | Long enough to span a synoptic episode, short enough to follow seasonal change |
| `NIGHT_HOURS` | (1, 5) | Well-mixed conditioning hours for the instrument bias diagnostic |
| `BONFIRE_YEARS` | 2022–2025 | Event study years |

`BASELINE_Q` is set at the 10th percentile rather than the minimum for a specific reason: the minimum is set by a single sensor at every timestep, and would be won every hour by whichever unit reads systematically low — which is precisely the fault the pipeline is trying to detect.

Timezone handling is worth flagging in the write-up. Raw timestamps are UTC; diurnal profiles and Bonfire Night windows only make sense in local time. Converting in one place avoids the classic hour-shifted evening peak in October and November.

### 4.1 Ingestion (`src/loader.py`)

The raw archive is a large pile of per-sensor CSVs that grows over time. `loader.py` keeps a manifest of files already ingested along with their size and modification time, so a re-run only processes what is new or changed. Output is columnar Parquet partitioned for fast per-sensor and per-period reads.

This matters at 25 million rows. Reading the archive from CSV every time is a multi-minute cost per notebook run; reading Parquet is seconds, and the incremental manifest means adding a month of new data does not mean reprocessing four years.

### 4.2 Cleaning (`src/cleaning.py`)

Two stages, in this order.

**A/B channel agreement, after Byrne et al. (2023).** Each PA-II holds two Plantower PMS5003 units logging in parallel. When both are healthy they track each other closely, so disagreement between the channels is direct evidence of a hardware problem: a blocked inlet, an insect, a failing laser, a fan losing speed. Readings where the two channels disagree beyond the configured absolute and relative tolerance are flagged rather than silently dropped, so the flag rate itself becomes a diagnostic.

**Humidity correction, after Barkjohn et al. (2021).** Plantower sensors overestimate PM2.5 in humid conditions because water uptake grows the particles they are optically sizing. Barkjohn's US-wide correction is applied per reading.

Two details that took work and should both appear in the methodology chapter:

- The correction is applied to the **mean of channels A and B**, not to channel A alone. An early version used channel A only, which throws away half the instrument and biases the result toward whichever channel happens to be dirtier.
- Barkjohn's coefficients were fitted in the United States against `cf_1` data. This project uses `cf_atm`, following Giordano et al. (2021). That is a defensible choice for outdoor ambient work, but it is a known caveat and is the most likely explanation for part of the underreading discussed in section 5.

### 4.3 Similarity (`src/csi.py`)

The Concentration Similarity Index of Byrne et al. (2024) scores every pair of sensors on how similar their concentration-time profiles are, using different tolerance bands above and below a PM concentration limit. The logic is that a 3 µg/m³ discrepancy means something very different at 5 µg/m³ than at 50 µg/m³.

Byrne et al. compute the CSI on hourly averages. **This project computes it daily, and that adaptation is my own.** The reason is coverage: only about 36% of hours in the Leeds archive have enough simultaneously reporting sensors to support a fair network-wide comparison, so hourly CSI would be computed on a non-random subset of hours biased toward periods when the network happened to be healthy. Daily resampling brings coverage to a level where the pairwise matrix is populated across the full four years. The trade-off is a loss of diurnal detail in the CSI itself, which is recovered separately through the diurnal profiling in `baseline.py`.

The adaptation is described as mine in the write-up. It is not attributed to Byrne et al., who should be credited with the index and its thresholds, not with the daily variant.

### 4.4 Baseline decomposition and instrument performance (`src/baseline.py`)

This module exists because of supervisor feedback on Milestone 2, which asked for more applied methodology beyond cleaning. It does four things.

**Spatial baseline.** This follows the general concept of Lenschow et al. (2001), who separate a measured concentration into regional, urban and local components, but the implementation differs and the difference should be stated in the write-up: Lenschow subtract measurements from three distinct station types, whereas this network has no such tiering, so the regional component is estimated as a low quantile across the reporting sensors at each timestep. Subtracting it from each site leaves a local residual, which is the quantity that actually matters for reporting a local event to the council. A citywide rise on a still, cold day is not a local event; a rise at one site while its neighbours sit flat is.

**Offset and gain.** Regressing each sensor against the network baseline gives a slope and an intercept per unit. A healthy sensor lands near unit slope and near-zero intercept. A persistent positive intercept points at contamination or drift; a slope far from one points at a scaling or channel problem. Byrne et al. show that a 5 µg/m³ offset alone roughly halves the CSI, which ties the two diagnostics together neatly.

**Diurnal profiling.** Median profile by hour of day, in local time, per site and per season. Residential solid-fuel burning shows up as an evening peak; traffic sites show a twin-peaked weekday profile that flattens at weekends.

**Site classification.** Sites are grouped by the shape of their diurnal profile and their CSI relationships rather than by their address, which follows the finding in Byrne et al. (2024) that location *type* predicts similarity better than physical proximity does.

### 4.5 Reference comparison (`src/aurn_reader.py`)

DEFRA's Automatic Urban and Rural Network provides reference-grade measurements at a small number of Leeds sites, which is the only external check available on absolute concentration. Two stations fall inside the study area, and their official DEFRA classification happens to map onto the outer tiers of the baseline decomposition:

| Site | Code | Coordinates | DEFRA type | PM2.5 method |
|---|---|---|---|---|
| Leeds Centre | `LEED` | 53.80378, −1.546472 | Urban Background | FIDAS |
| Headingley Kerbside | `LED6` | 53.819972, −1.576361 | Urban Traffic | BAM |

Each station is paired with its nearest PurpleAir unit. Barkjohn-corrected values are compared against a locally fitted correction on a chronological 70/30 train/test split, so the local fit is evaluated on held-out data rather than on the period it was fitted to. The kerbside-minus-background difference between the two reference instruments also gives a genuine traffic increment, which is checked against the network-derived traffic index from the baseline notebook.

The standard route (`pyaurn` via `pyreadr`) does not work against DEFRA's current RData exports, so this module downloads and parses the flat-file CSVs directly. Four problems had to be solved and each is a small trap:

- DEFRA blocks the default Python user agent, so a browser-like `User-Agent` header is required.
- A failed or truncated response was being written to the local cache, so every later run read the corrupt copy. The cache now only writes on a validated response.
- The CSVs carry a four-line banner above the real header, so the header row has to be located rather than assumed.
- DEFRA writes midnight as hour 24 of the previous day. `01-01-2022 24:00` means the final hour of 1 January, and it crashes every standard datetime parser. The parser normalises it before conversion.

---

## 5. Results so far

**SL051 (Bramham) is the strongest fault candidate.** It is flagged independently by three methods that do not share inputs. It has the lowest lifetime mean CSI in the network (0.300); it records the highest network mean daily PM2.5 (7.7 µg/m³) despite sitting at a rural site, where the opposite would be expected; and the well-mixed-hours regression against the spatial baseline returns an offset of +1.36 µg/m³ with a gain of 0.649. Across the network, bias magnitude and CSI are negatively correlated by Spearman rank, which is the expected direction and supports using CSI as a screening statistic for instrument problems.

**The recent-window CSI separates chronic from developing faults.** SL051's recent (365-day) CSI recovers to roughly 0.65, so its problems are largely historical — the lifetime matrix alone would have sent a technician to a unit that is currently behaving. The opposite case is **SL006**, which falls from a lifetime CSI of 0.47 to 0.26 in the recent window and is the clearest newly deteriorating sensor in the network. Running both windows is what makes the ranking actionable rather than merely descriptive.

**SL037 has the worst raw A/B disagreement rate but a high CSI after cleaning.** 86.6% of its readings are flagged, and its channel A sat stuck near 3,333 µg/m³ for months. Yet once the flagged readings are removed, the survivors look unremarkable against the network. This is the most useful single result in the project so far, because it shows the two detectors are not redundant: A/B disagreement catches intermittent hardware failure that cleaning then removes, while CSI catches systematic drift shared by both channels, which cleaning cannot see. Either one alone would miss a class of fault.

**Bonfire Night is a positive control.** Every year from 2022 to 2025 produces an enhancement of 35–62 µg/m³ over the control baseline, a ratio of 7 to 11 fold, with correct timing and a plausible spatial gradient. A pipeline that failed to recover an event this large would not be worth trusting on subtler ones. Note that the 3 to 7 November exclusion window applies only to the control baseline used for the enhancement table; raw time series are plotted unexcluded.

**AURN comparison shows the sensors read low.** After A/B cleaning and Barkjohn correction, PurpleAir units read at 52 to 67% of the co-located reference value. A locally fitted correction roughly halves out-of-sample error at Headingley — MAE 1.99 µg/m³ against 3.82 for Barkjohn on held-out data — which suggests the shortfall is a correctable calibration problem rather than irreducible sensor noise. The framing in the dissertation is still open. The leading explanation is the `cf_1` versus `cf_atm` mismatch noted in section 4.2, since Barkjohn's coefficients were fitted against `cf_1`. UK aerosol composition and humidity regime differing from the US fitting set is a plausible secondary contributor. The honest position is that the network is well suited to relative and temporal comparison and should not be quoted as an absolute concentration without local calibration.

**Negative result: the England World Cup match analysis.** The hypothesis was that traffic-related PM2.5 would drop during England matches. It did not, or at least not detectably above the day-to-day variance. This is reported briefly as a negative result rather than dropped, since it bounds the sensitivity of the method.

---

## 6. Things that went wrong, and what fixed them

Kept here because they cost real time and because several of them belong in the dissertation as methodological caveats rather than being quietly buried.

| Problem | Resolution |
|---|---|
| Barkjohn correction applied to channel A only | Applied to the A/B mean instead |
| CSI daily adaptation initially attributed to Byrne et al. | Correctly described as my own adaptation |
| Misspelled config name inside `try/except` silently used fallback CSI constants | Explicit imports, no swallowed `ImportError` |
| Edits to `.py` files not picked up by the notebook | `%autoreload 2` plus explicit `importlib.reload()` |
| Shared matplotlib locator and formatter objects across axes in `csi.py` | Construct fresh locator/formatter per axis |
| Thresholds drifting between notebook and module | All thresholds moved to `config.py` |
| PurpleAir website CSV export used as a validation target | Abandoned. The site applies undocumented averaging and gap-filling, so it cannot validate raw Parquet |
| `pyaurn` / `pyreadr` failing on DEFRA RData | Custom flat-file CSV reader |

---

## 7. Reproducing the analysis

Run the notebooks in order. Each writes its outputs to `data/processed/` and its figures to `figures/`, so later notebooks do not recompute earlier stages.

| Notebook | Purpose |
|---|---|
| `00_check_data` | Confirms the OneDrive archive is readable and structured as expected |
| `01_filter_sensors` | Outdoor sensors inside the Leeds bounding box; study-area map; `study_sensors.csv` (48 rows) |
| `02_combine_sensors` | Per-sensor Parquet plus `sensor_inventory.csv` (47 rows) |
| `03_explore_quality` | Distributions, A/B scatter, gap structure, per-sensor record counts |
| `04_cleaning` | A/B flagging, Barkjohn correction, and the subsampling test that fixes daily resolution |
| `05_csi` | Lifetime and recent-window CSI matrices, fault ranking, per-sensor CSI map |
| `06_events` | Bonfire Night 2022–2025 and the England World Cup match analysis |
| `07_baseline` | Spatial baseline, offset and gain regression, diurnal profiling, site classification |
| `08_aurn_validation` | DEFRA reference download, sensor–reference comparison, local correction fit |

One number worth stating explicitly, because it looks like a bug and is not: `study_sensors.csv` holds 48 rows and `sensor_inventory.csv` holds 47. SL071 (Kentmere) passes the study-area filter but has no data folder on disk, so it drops out at the combine step. The 48 → 47 reduction is expected behaviour.

`src/loader.py` is run from the terminal rather than as a notebook. It is infrastructure: it produces no figure and makes no argument, it just rebuilds `data/processed/` incrementally so the analytical notebooks have fresh input. It depends on `02_combine_sensors` having run at least once, since it reads the `folder` column of `sensor_inventory.csv`.

---

## 8. Still open

Milestones 1 and 2 are submitted; Milestone 2 comprised a Word and PDF report with three embedded figures. Supervisor feedback on Milestone 2 asked for more applied methodology beyond cleaning, which is what motivated the baseline decomposition and the AURN validation. The pipeline now runs end to end from 00 to 08.

Outstanding:

- A consolidated fault-candidate list showing the evidence from each detector side by side — A/B flag rate, lifetime CSI, recent CSI, offset, gain — which is the artefact that would actually be handed to whoever schedules site visits. Each detector currently produces its own ranking in its own notebook.
- How to frame the 52 to 67% AURN underreading. Options are to present it as an uncorrected bias with a stated cause, to fit local correction coefficients against AURN and report both, or to reframe the network's output as a relative index rather than a concentration. The second is the strongest if time allows, since it turns a caveat into a contribution.
- Whether the predictive component in notebook 08 forecasts concentration or forecasts fault probability. The second is closer to the stated project aims and is more defensible in the viva.
- Sensitivity analysis on `BASELINE_Q` and on the CSI daily-versus-hourly choice, to show the conclusions do not depend on a single arbitrary threshold.

---

## 9. References

Barkjohn, K. K., Gantt, B. and Clements, A. L. (2021) Development and application of a United States-wide correction for PM2.5 data collected with the PurpleAir sensor. *Atmospheric Measurement Techniques*, 14(6), 4617–4637.

Byrne, R., Ryan, M., Venables, D. S., Wenger, J. C. and Hellebust, S. (2023) Highly local sources and large spatial variations in PM2.5 across a city. *Environmental Science: Atmospheres*, 3, 1123–1134.

Byrne, R., Wenger, J. C. and Hellebust, S. (2024) Spatial analysis of PM2.5 using a concentration similarity index applied to air quality sensor networks. *Atmospheric Measurement Techniques*, 17, 5129–5146.

Giordano, M. R. et al. (2021) From low-cost sensors to high-quality data: a summary of challenges and best practices for effectively calibrating low-cost particulate matter mass sensors. *Journal of Aerosol Science*, 158, 105833.

van Zoest, V. M., Stein, A. and Hoek, G. (2018) Outlier detection in urban air quality sensor networks. *Water, Air, and Soil Pollution*, 229, 111.

---

