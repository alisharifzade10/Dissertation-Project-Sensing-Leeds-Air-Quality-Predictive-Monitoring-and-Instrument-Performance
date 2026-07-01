"""
Incremental loader for the Leeds PurpleAir network.

Reads the authoritative folder list from sensor_inventory.csv (its `folder`
column holds the real on-disk names, produced by 02_combine_sensors), then
ingests ONLY new or changed daily CSVs per sensor, appending to each sensor's
combined Parquet in data/processed/.

Old day-files never change, so they are read once and remembered in a manifest.
The most recent few days are always re-read because the current day grows until
midnight and a just-closed day may still be syncing through OneDrive.

Run from the project root:
    python -m src.loader
"""
from pathlib import Path
import re
import pandas as pd

from src.config import (
    DATA_DIR, PROCESSED, OUT_TABLES, MANIFEST, DATE_COL,
)

INVENTORY = OUT_TABLES / "sensor_inventory.csv"
REPROCESS_RECENT_DAYS = 2
DAILY_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.csv$")


def study_folders():
    """Exact on-disk folder names for the study sensors, from the inventory."""
    if not INVENTORY.exists():
        raise FileNotFoundError(
            f"{INVENTORY} not found — run 02_combine_sensors first to build it."
        )
    inv = pd.read_csv(INVENTORY)
    return inv["folder"].dropna().tolist()


def load_manifest():
    if MANIFEST.exists():
        m = pd.read_parquet(MANIFEST)
        return {(r.sensor, r.file): r.mtime for r in m.itertuples()}
    return {}


def save_manifest(seen):
    rows = [{"sensor": s, "file": f, "mtime": mt} for (s, f), mt in seen.items()]
    pd.DataFrame(rows).to_parquet(MANIFEST, index=False)


def daily_files(sensor_dir):
    """Daily CSVs under a sensor folder, excluding monthly/ duplicates and empties."""
    out = []
    for p in sensor_dir.rglob("*.csv"):
        if not DAILY_RE.search(p.name):      # only YYYY-MM-DD.csv
            continue
        if "monthly" in p.parts:             # skip monthly/ duplicates
            continue
        if p.stat().st_size == 0:            # skip empty day-files
            continue
        out.append(p)
    return out


def update_sensor(sensor_dir, seen, recent_cutoff):
    name  = sensor_dir.name
    out   = PROCESSED / f"{name}.parquet"
    files = daily_files(sensor_dir)
    if not files:
        return name, 0, "no files"

    # candidates = day-files that changed or fall inside the recent re-read window
    candidates = []
    for f in files:
        mt  = f.stat().st_mtime
        key = (name, f.name)
        day = f.stem                          # 'YYYY-MM-DD'
        if day >= recent_cutoff or seen.get(key) != mt:
            candidates.append((f, mt, key))

    if not candidates:
        return name, 0, "up to date"

    # rebuild when the parquet is missing or we'd re-read most of it anyway.
    # CRITICAL: a rebuild reads EVERY file, not just the candidates — otherwise
    # older days outside the recent window get silently dropped from the output.
    rebuild = (not out.exists()) or (len(candidates) > 0.5 * len(files))

    if rebuild:
        to_read  = [(f, f.stat().st_mtime, (name, f.name)) for f in files]
        combined = pd.concat([pd.read_csv(f) for f, _, _ in to_read], ignore_index=True)
    else:
        to_read = candidates
        new = pd.concat([pd.read_csv(f) for f, _, _ in to_read], ignore_index=True)
        old = pd.read_parquet(out)
        reread_days = {f.stem for f, _, _ in to_read}
        old_day = old[DATE_COL].astype(str).str[:10]
        old = old[~old_day.isin(reread_days)]          # drop days we just re-read
        combined = pd.concat([old, new], ignore_index=True)

    combined = (combined
                .drop_duplicates()
                .sort_values(DATE_COL)
                .reset_index(drop=True))
    combined.to_parquet(out, index=False)

    for f, mt, key in to_read:
        seen[key] = mt
    return name, len(to_read), ("rebuilt" if rebuild else "appended")


def run():
    recent_cutoff = (pd.Timestamp.now(tz="UTC").normalize()
                     - pd.Timedelta(days=REPROCESS_RECENT_DAYS)).strftime("%Y-%m-%d")
    seen = load_manifest()
    folders = study_folders()

    total_new = 0
    for fname in sorted(folders):
        d = DATA_DIR / fname
        if not d.is_dir():
            print(f"  ! {fname}: folder missing on disk, skipped")
            continue
        name, n, status = update_sensor(d, seen, recent_cutoff)
        if n:
            print(f"  {name}: +{n} day-files ({status})")
            total_new += n

    save_manifest(seen)
    print(f"done — {total_new} day-files ingested this run, cutoff {recent_cutoff}")


if __name__ == "__main__":
    run()