# Sensing Leeds Air Quality: Predictive Monitoring and Instrument Performance

MSc dissertation project (MATH5872M, University of Leeds, School of Mathematics).
Analysis of the Leeds PurpleAir PM2.5 low-cost sensor network, operated by the
University of Leeds with Leeds City Council.

**Author:** Ali Sharifzade (202007327)
**Supervisors:** Prof. Jim McQuaid (Faculty of Environment), Dr Luisa Cutillo (School of Mathematics)
**Submitted:** August 2026

---

## Overview

Low-cost optical sensors let a local authority measure PM2.5 at a spatial density
that regulatory instruments cannot reach, but they create a problem regulatory
networks do not have: when one sensor reports something its neighbours do not,
it is not obvious whether the air is unusual or the instrument is.

This project builds a reproducible pipeline over 25.4 million two-minute readings
from 47 outdoor PurpleAir PA-II units across Leeds (March 2022 – August 2026) and
uses three mutually independent network-internal diagnostics to separate genuine
local pollution from instrument problems, without any co-located reference
instrument.

## Research questions

1. Can the network be shown to detect real, city-wide pollution events?
2. Which sensors disagree with the network, and how much evidence stands behind
   each disagreement?
3. Is a sensor's disagreement explained by its calibration, or by the air at its
   site?
4. For the disagreements calibration does not explain, does the two-minute record
   look like particles or like electronics?
5. Can the result be turned into an actionable list for the network operator?

## Dataset

| | |
|---|---|
| Source | Leeds PurpleAir network archive (University of Leeds / Leeds City Council) |
| Instrument | PurpleAir PA-II, two Plantower PMS5003 channels per unit |
| Period | 7 March 2022 – 23 August 2026 (1,631 days) |
| Resolution | ~2 minutes (720 records per complete day) |
| Volume | 25,404,384 raw readings across 47 sensors |
| Variables | UTC timestamp, PM2.5 channel A and B (`cf_atm`), temperature (°F), relative humidity (%) |
| Reference data | Hourly PM2.5 from AURN Leeds Centre (UKA00222), Defra UK-AIR |

Study-set construction: 68 registered sensors → 48 pass the geographic /
outdoor / genuine-deployment rules → 47 have data on disk (SL71 Kentmere has no
folder) → 43 have ≥100 valid days and enter the similarity matrix → 4 references
+ 34 diagnosed candidates.

Two derived matrices carry the analysis: a daily matrix of 1,629 days × 43
sensors (median 20 sensors reporting per day), and an hourly matrix of 39,065
hours × 47 sensors, of which 36,293 hours clear the five-sensor bar for a
network median.

**The raw archive is not redistributed.** It is held by the University and the
Council. `data/` is gitignored.

## Methodology

**Quality flags** (flag, never delete): implausible range (>1000 µg/m³ on either
channel); two-band A/B channel disagreement following Byrne et al. (2023), with
an absolute floor of 1.0 µg/m³ added because Leeds air is clean enough for
counting noise to trip the relative test alone; and a frozen-output detector for
the failure mode the A/B test cannot see. The similarity ranking is insensitive
to the floor (Spearman ρ = 0.997 against 0.5 µg/m³ and 0.990 against 2.0).

**Correction and aggregation:** Barkjohn et al. (2021) humidity correction applied
to the channel mean. Hourly means require ≥15 clean readings (justified by a
contiguous-block subsampling test); daily means require ≥180 (justified by a
survival curve, which retains 93.1% of sensor-days and 43 of 44 sensors).

**Concentration similarity index** (Byrne et al., 2024), computed on daily means
over a lifetime window and over the final 365 days, with the network-wide shift
removed before any sensor is described as deteriorating.

**Spatial decomposition** (Lenschow et al., 2001): C_i(t) = B(t) + I_i(t), with
B(t) the 10th percentile across ≥12 reporting sensors, computed leave-one-out so
no sensor helps set the level it is measured against.

**Instrument bias:** per-sensor `sensor = gain × network + offset` fitted on
spatially uniform hours against a leave-one-out network median, on decile-binned
medians.

**Diagnosis** (four steps): harmonise and recompute the CSI; convert an observed
CSI into an equivalent fault size using response curves recomputed on real Leeds
series; test the residual for seasonal organisation using σ_ΔPM; and characterise
the excursions by lag-1 autocorrelation and A/B channel correlation. Verdicts are
assigned by a stated rule in `src/config.py`, not by judgement.

**Supporting checks:** an adapted van Zoest et al. (2018) within-class Tukey-fence
outlier test on daily local increments, hierarchical clustering of the CSI matrix,
and an Isolation Forest ranking that combines CSI, bias and van Zoest flag rate.
None of these decides a verdict on its own.

**Validation:** faults of known type and size planted in real data — a fixed
offset for the calibration branch, and smooth two-channel bumps versus one-channel
noise at three severities for the local-source and channel branches.

## Notebook workflow

Run in order; each notebook consumes the previous one's saved output.

| Notebook | Purpose | Key output |
|---|---|---|
| `00_check_data` | Pre-flight check on archive access and file structure | — |
| `01_filter_sensors` | Study-set selection with a full decision log | `study_sensors.csv`, `sensor_filter_decisions.csv` |
| `02_combine_sensors` | Combine daily CSVs; coverage inventory | per-sensor Parquet, `sensor_inventory.csv` |
| `03_explore_quality` | Pre-cleaning inspection of three contrasting sensors | evidence for the flag rules |
| `04_cleaning` | Apply flags; justify every threshold | `cleaned/*.parquet`, `cleaning_summary.csv`, `hourly_sensitivity.csv`, `coverage_check.csv` |
| `05_csi` | Daily matrix; pairwise CSI; lifetime vs recent | `csi_matrix.csv`, `csi_sensor_ranking.csv`, `correction_clipping.csv` |
| `06_events` | Hourly matrix; Bonfire Night analysis | `06_bonfire_enhancement.csv`, `bonfire_enhancement_per_sensor.csv` |
| `07_baseline` | Baseline separation, source indices, instrument bias, AURN check | `instrument_bias.csv`, `07_local_increment_by_sensor.csv`, `baseline_sensitivity.csv` |
| `08_event_or_fault` | Diagnosis, verdicts, validation | `sensor_verdicts.csv`, `nb08_final_summary.csv` |

`FORCE_REBUILD = False` in NB02 skips sensors that already have a Parquet, making
re-runs near-instant. For routine data refreshes use `python -m src.loader`,
which re-reads only new or changed daily files via a manifest.

## Main findings

**The network detects real events.** Bonfire Night produced network-median
enhancements of 35.0–58.9 µg/m³ in each of 2022–2025, a factor of 7.5–10.1 above
matched control evenings, registering at all 20 sensors with sufficient coverage
(+22.9 to +101.3 µg/m³). Measured instead as an increment above the concurrent
spatial baseline — an independent route needing no control days — the same
evenings run at a factor of 11–13, in the two years where enough sensors were
reporting for a baseline to be defined.

**The baseline is real.** The network's own 10th-percentile baseline correlates
at r = 0.77 with the independent AURN reference instrument at Leeds Centre over
1,217 days. The shared regional background accounts for roughly 30% of a typical
reading, and is defined for 66% of hours.

**No city-wide traffic signature in PM2.5.** The baseline's weekday-minus-weekend
contrast at commuting hours is −0.05 µg/m³, and the site-specific traffic index is
near zero across every site type. The evening excess is what varies between sites,
reaching +7.44 µg/m³ at SL051 — the signature of intermittent combustion close to
a sensor rather than of the working week.

**Instrument agreement is good.** Only 3 of 43 sensors are out by more than
2 µg/m³ within their fitted range; the largest additive offset is 1.91 µg/m³.
Against enhancements of 40–65 µg/m³, that is adequate for event detection and
poor for regulatory compliance. The bias ranking and the CSI corroborate each
other only as a tendency (Spearman −0.38, p = 0.013 on |offset|; −0.21, not
significant, on total bias), which is the right direction but not a confirmation.

**The frozen-output flag found nothing.** Across 47 sensors and 25.4 million
readings, no run of three hours or more frozen at a non-zero value occurs. The
1.9 million readings frozen at exactly zero are counted and deliberately retained,
since a PMS5003 in clean air reports zero legitimately and removing those runs
would delete the readings that set the spatial baseline.

**The similarity index is not a site-visit list.** Recomputing its response to
synthetic faults at Leeds concentrations shows it is highly sensitive to additive
offsets (1 µg/m³ drives mean CSI from 0.78 to 0.64) and nearly blind to gain
(a gain of 0.85 costs about 0.01). The two lowest-scoring sensors therefore score
low for opposite reasons:

- **SL050** (CSI 0.320): its humidity channel reports a median of exactly 100%
  across 637,225 readings, which drives the correction below zero and floors
  61.5% of its record at zero. Harmonisation recovers it to 0.637. The fault is
  in the auxiliary channel feeding the correction, not in the optical counters.
- **SL051** (CSI 0.318): harmonisation recovers only +0.017. Its fitted bias is a
  gain deficit (0.83) rather than an offset (+0.39), and the index barely responds
  to gain, so calibration is excluded. The residual excursions are seasonal
  (winter:summer 2.78), temporally smooth (lag-1 0.954), seen by both counters
  (channel correlation 0.998) and shared with none of its five nearest neighbours
  (1% of the excess). This is consistent with a genuine hyper-local source.

**Verdicts.** Of 34 candidates: 11 single-channel behaviour, 12 unresolved,
5 possible local source, 4 intermittent fault, 2 calibration fault, 0 frozen.
Rolled up operationally across all 47 sensors, 13 were still reporting at the end
of the study period and 34 were offline; current status and historical finding are
reported as separate fields, since most units stopped reporting for reasons
unrelated to their readings.

**Supporting checks agree without deciding anything.** The adapted van Zoest test
flags 3.3% of 70,047 sensor-days, with SL019 the most affected (16.3%). Clustering
the CSI matrix returns its best silhouette at k = 2 (0.550) but partitions 42
sensors against 1, so the score is inflated by isolation rather than reflecting
network structure.

**Validation.** Planted local-source events were recovered in 81 of 81
simulations — 27 of 27 at each of three severities. Planted channel faults were
recovered in 25.9% of cases at the weakest severity (1 hour, noise SD 7 µg/m³),
59.3% at moderate and 85.2% at the strongest (3 hours, 15 µg/m³), for a blended
56.8%. Most of the shortfall at the weak end is the fault never being flagged as
unusual at all, rather than being flagged and misdiagnosed.

## Limitations

- The Barkjohn correction is itself a source of artefact: a network median of
  10.8% of clean readings are floored at zero, which interacts directly with the
  CSI's handling of zeros. Its coefficients are US-fitted and derived on `cf_1`,
  while this archive exports `cf_atm` (affects 6.06% of readings).
- Candidate screening is deliberately broad (34 of 43 sensors), so "candidate"
  carries little information on its own; all conclusions rest on the verdict stage.
- The reference group was chosen on similarity and site type, not on the absence
  of local sources — SL017 has one of the highest winter:summer ratios in the set
  (3.37) and sets the fluctuation bar at 18.3% of hours. That makes the bar
  conservative and explains much of the unresolved count.
- The A/B channel-correlation test is a pooled Pearson correlation on raw readings
  and is sensitive to a small number of extreme values; 5 of the 11 single-channel
  verdicts rest on it, so inspection rather than replacement is the right action
  for that group.
- Some verdicts sit on a threshold (SL020 and SL018 at a winter:summer ratio of
  1.50; SL019 and SL050 within 0.02 of the 0.50 channel-correlation bar) and
  should be read as provisional.
- Channel-fault detection is severity-dependent (25.9% to 85.2%).
- Clustering the CSI matrix produced a degenerate partition (42 sensors and 1);
  reported as a negative result, mirroring the weak clustering Byrne et al. (2024)
  report for Cork.
- **No verdict has been checked against a physical site visit.** Confidence rests
  on agreement between independent tests and on synthetic faults with known
  ground truth.
- Only 48.4% of hours at the median sensor are adequately sampled, which forced
  daily aggregation for the similarity work and left two of the four Bonfire
  Nights without a defined spatial baseline.

## Reproducibility

Every path, column name and threshold is defined once, in `src/config.py`.
Notebooks orchestrate and visualise; all reusable logic lives in `src/`. Random
operations are seeded (`numpy.random.default_rng`, and an MD5-derived stable seed
in the NB08 synthetic validation, so results do not change between kernel
restarts). Intermediate data are Parquet.

To reproduce:

```bash
git clone <repo>
cd <repo>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# point DATA_DIR in src/config.py at the raw archive
jupyter lab            # then run notebooks 01 → 08 in order
```

## Software requirements

- Python 3.14
- pandas, numpy, scipy, scikit-learn, pyarrow
- matplotlib, contextily, pyproj
- requests (AURN download in NB07)
- jupyter / nbformat

## Repository structure

```
.
├── src/
│   ├── config.py        # all paths, column names and thresholds — single source of truth
│   ├── loader.py        # incremental, manifest-based ingestion of daily CSVs
│   ├── cleaning.py      # the three quality flags and the Barkjohn correction
│   ├── csi.py           # pairwise concentration similarity index and ranking
│   ├── baseline.py      # spatial baseline, local increment, offset-gain fit, harmonisation
│   ├── highfreq.py      # sigma_DPM filter, exposure fractions, excursion structure
│   └── synthetic.py     # fault injection for the CSI response curves
├── notebooks/
│   ├── 00_check_data.ipynb
│   ├── 01_filter_sensors.ipynb
│   ├── 02_combine_sensors.ipynb
│   ├── 03_explore_quality.ipynb
│   ├── 04_cleaning.ipynb
│   ├── 05_csi.ipynb
│   ├── 06_events.ipynb
│   ├── 07_baseline.ipynb
│   └── 08_event_or_fault.ipynb
├── outputs/
│   ├── tables/          # every CSV referenced in the dissertation
│   └── figures/         # every figure
├── data/                # gitignored — raw and processed data are not redistributed
├── report/              # LaTeX source and compiled dissertation
├── requirements.txt
└── README.md
```

## References

Key sources for the methods used here:

- Byrne, R., Wenger, J. C. & Hellebust, S. (2024). Spatial analysis of PM2.5
  using a concentration similarity index applied to air quality sensor networks.
  *Atmospheric Measurement Techniques*, 17, 5129–5146.
- Byrne, R., Ryan, K., Venables, D. S., Wenger, J. C. & Hellebust, S. (2023).
  Highly local sources and large spatial variations in PM2.5 across a city.
  *Environmental Science: Atmospheres*, 3, 919–930.
- Barkjohn, K. K., Gantt, B. & Clements, A. L. (2021). Development and
  application of a United States-wide correction for PM2.5 data collected with
  the PurpleAir sensor. *Atmospheric Measurement Techniques*, 14, 4617–4637.
- van Zoest, V. M., Stein, A. & Hoek, G. (2018). Outlier detection in urban air
  quality sensor networks. *Water, Air, & Soil Pollution*, 229, 111.
- Lenschow, P. et al. (2001). Some ideas about the sources of PM10.
  *Atmospheric Environment*, 35(S1), S23–S33.
- Rousseeuw, P. J. (1987). Silhouettes: a graphical aid to the interpretation and
  validation of cluster analysis. *Journal of Computational and Applied
  Mathematics*, 20, 53–65.

## Acknowledgements

Thanks to Leeds City Council and the School of Earth and Environment for access
to the sensor archive, and to the schools and residents who host the units.