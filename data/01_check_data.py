from pathlib import Path
import pandas as pd

# The synced OneDrive folder containing the sensor data.
# Note the r before the quotes — it tells Python to treat backslashes literally (important on Windows).
DATA_DIR = Path(r"C:\Users\user\OneDrive - University of Leeds\Dissertation Data\SEE AQ Projects-PURPLEAIR - sensor_data")

# 1. Does the folder exist and can we see it?
print("Folder exists:", DATA_DIR.exists())
print()

# 2. List what's directly inside it (top-level sensor folders + any files)
print("Top-level contents:")
for item in sorted(DATA_DIR.iterdir()):
    kind = "DIR " if item.is_dir() else "FILE"
    print(f"  [{kind}] {item.name}")
print()

# 3. Find the FIRST daily CSV anywhere in the tree and read it.
# Find the first ACTUAL daily reading file (inside a sensor folder's year/month tree),
# not a top-level summary file. Daily files are named like 2024-10-05.csv.
import re

first_populated = None
empty_count = 0
checked = 0
for p in DATA_DIR.rglob("*.csv"):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.csv", p.name):
        checked += 1
        df = pd.read_csv(p)
        if len(df) > 0:
            first_populated = (p, df)
            break
        else:
            empty_count += 1
        if checked > 400:   # safety stop so we don't crawl forever over OneDrive
            break

print(f"Empty daily files skipped before finding data: {empty_count}")
print()

if first_populated is None:
    print("No populated daily file found in the first batch checked.")
else:
    p, df = first_populated
    print("First POPULATED daily file:")
    print(" ", p)
    print("Rows:", len(df), "(720 = a full day at 2-min spacing)")
    print()
    # show the key PM2.5 columns + timestamp for the first few rows
    cols = ["date", "PM2.5 A (CF=ATM) (ug/m3)", "PM2.5 B (CF=ATM) (ug/m3)",
            "Temperature (F)", "Humidity (%)"]
    print(df[cols].head(5).to_string())
    print()
    # confirm the time gap between consecutive readings
    print("First three timestamps (should be ~2 min apart):")
    for t in df["date"].head(3):
        print("  ", t)