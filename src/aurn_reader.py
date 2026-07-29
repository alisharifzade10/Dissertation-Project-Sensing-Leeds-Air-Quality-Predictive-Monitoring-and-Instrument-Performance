"""
Reader for DEFRA UK-AIR 'flat file' CSVs (the site_data/{SITE}_{YEAR}.csv
downloads), used in place of pyaurn/pyreadr because DEFRA's current RData
exports are not parseable by pyreadr's librdata backend (LibrdataError).

Format notes, established against real downloaded files:
  - A variable number of metadata/banner lines precede the true header
    (observed: 4 lines -- supply date, timezone note, status legend, site
    name -- though this is not assumed fixed). The header row is located
    by CONTENT: the row starting 'Date,time,...' with a column count of
    2 + 3*k (a whole number of value/status/unit triplets), k>=1. Where
    more than one such candidate line exists, the widest match wins.
  - A near-blank separator line (observed as a single space) sits between
    the header and the data; pandas' default blank-row handling absorbs
    short/empty rows without erroring (a row with FEWER fields than the
    header is NaN-filled, not rejected -- only rows with MORE fields than
    the header raise, which is the banner-misalignment failure mode this
    module's header-detection already guards against).
  - Each pollutant occupies three columns (value, status, unit) with
    non-unique 'status'/'unit' header names, so columns are identified and
    renamed by position relative to the located header, not by name.
  - Column names carry literal HTML fragments (e.g. 'PM<sub>2.5</sub>...'),
    stripped with a regex.
  - status: R = Ratified (fully quality-assured), P = Provisional,
    P* = As-supplied (least verified, typically only the most recent days).
  - Timestamps are GMT, HOUR-ENDING: the row for 01:00 on 2024-01-01 is the
    mean over 2024-01-01 00:00-01:00. Every timestamp is shifted back one
    hour on read to an hour-START label, matching pandas' `.resample('h')`
    convention used for the PurpleAir network.
  - MIDNIGHT IS WRITTEN AS '24:00' ON THE PRECEDING DATE, not '00:00' on
    the following date -- e.g. '01-01-2022 24:00' is the hour ending at
    midnight on 2 January, i.e. the last hour of 1 January. Standard
    datetime parsing has no hour 24, so these rows are rewritten to
    '00:00' on the NEXT calendar day before parsing; the hour-ending shift
    then correctly lands them as the 23:00 hour-start bucket of the
    original date. Verified against a year-boundary case (31 Dec 24:00
    stays in the same year, not rolled into 1 Jan) so this cannot silently
    misattribute a reading to the wrong year.
  - Any row whose Date/time still fails to parse after the above (e.g. a
    genuinely blank or corrupted line) becomes NaT and is dropped, with the
    count reported, rather than aborting the whole file over one bad row.

Network notes:
  - DEFRA's server has been observed returning a non-CSV response to
    requests' default User-Agent (python-requests/x.y). A browser-like
    User-Agent header is sent to avoid this.
  - Every downloaded response is checked against the expected DEFRA banner
    ("Data supplied by UK-AIR...") before it is cached or parsed. Content
    that fails this check is never written to disk. Existing cache files
    are checked the same way before being trusted, so an already-poisoned
    cache self-heals with no manual cleanup required.
"""
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://uk-air.defra.gov.uk/datastore/data_files/site_data/{site}_{year}.csv?v=1"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "text/csv,text/plain,*/*",
}

_EXPECTED_PREFIX = b"Data supplied by UK-AIR"


def _looks_like_defra_csv(raw: bytes) -> bool:
    """True if `raw` starts like a genuine DEFRA flat-file export."""
    return raw[:len(_EXPECTED_PREFIX)] == _EXPECTED_PREFIX


def _read_text(path_or_buf) -> str:
    """Normalise a Path, bytes buffer, or file-like object to decoded text."""
    if isinstance(path_or_buf, (str, Path)):
        return Path(path_or_buf).read_text(encoding="utf-8", errors="replace")
    data = path_or_buf.read()
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data


def _find_header_row(lines):
    """Index of the real header row, located by content rather than a fixed
    offset. Raises ValueError with a preview of the file's opening lines if
    nothing matches, so a genuine format change is immediately visible.
    """
    candidates = []
    for i, line in enumerate(lines):
        parts = line.split(",")
        if (len(parts) >= 5 and parts[0].strip().lower() == "date"
                and parts[1].strip().lower() == "time"
                and (len(parts) - 2) % 3 == 0):
            candidates.append(i)
    if not candidates:
        preview = "\n".join(f"  line {i}: {l[:100]!r}" for i, l in enumerate(lines[:8]))
        raise ValueError(
            "could not locate a header row (expected 'Date,time,...' with "
            f"a whole number of value/status/unit triplets). First lines:\n{preview}"
        )
    return max(candidates, key=lambda i: len(lines[i].split(",")))


def _parse_defra_datetime(date_str: pd.Series, time_str: pd.Series) -> pd.Series:
    """Parse DEFRA's Date+time columns into hour-START timestamps.

    Handles the hour-24-midnight convention (see module docstring). Rows
    that still fail to parse become NaT rather than raising.
    """
    time_clean = time_str.astype(str).str.strip()
    is_midnight = time_clean == "24:00"

    date_parsed = pd.to_datetime(date_str, format="%d-%m-%Y", errors="coerce")
    date_adj = date_parsed.where(~is_midnight, date_parsed + pd.Timedelta(days=1))
    time_adj = time_clean.where(~is_midnight, "00:00")

    combined = date_adj.dt.strftime("%d-%m-%Y").fillna("") + " " + time_adj
    parsed = pd.to_datetime(combined, format="%d-%m-%Y %H:%M", errors="coerce")
    return parsed - pd.Timedelta(hours=1)          # hour-ending -> hour-start


def read_defra_flat_csv(path_or_buf, site_name=None, verbose=False):
    """Parse one already-downloaded DEFRA flat-file CSV into a tidy frame.

    Accepts a Path, an open file-like object, or a bytes buffer.

    Returns columns: [site,] date, then for each pollutant found in the
    file: <pollutant>, <pollutant>_status, <pollutant>_unit. Rows whose
    timestamp could not be parsed are dropped (count printed if verbose).
    """
    text = _read_text(path_or_buf)
    lines = text.splitlines()
    header_idx = _find_header_row(lines)

    raw = pd.read_csv(io.StringIO(text), skiprows=header_idx, header=0)

    value_cols = list(range(2, raw.shape[1], 3))
    pollutants = [re.sub(r"<[^>]+>", "", raw.columns[i]).strip() for i in value_cols]

    out = pd.DataFrame()
    out["date"] = _parse_defra_datetime(raw["Date"], raw["time"])

    for i, name in zip(value_cols, pollutants):
        out[name] = pd.to_numeric(raw.iloc[:, i], errors="coerce")
        out[f"{name}_status"] = raw.iloc[:, i + 1]
        out[f"{name}_unit"] = raw.iloc[:, i + 2]

    n_bad = int(out["date"].isna().sum())
    if n_bad:
        if verbose:
            print(f"      ({n_bad} row(s) with an unparseable timestamp dropped)")
        out = out[out["date"].notna()].reset_index(drop=True)

    if site_name:
        out.insert(0, "site", site_name)
    return out


def download_defra_site(site, years, out_dir=None, site_name=None,
                        pause=1.0, verbose=True):
    """Download and parse one AURN site across multiple years.

    Parameters
    ----------
    site : str, DEFRA site code, e.g. 'LED6' (Headingley Kerbside), 'LEED'
        (Leeds Centre).
    years : iterable of int.
    out_dir : Path, if given each year's raw CSV is cached here. A cached
        file is only trusted if it passes `_looks_like_defra_csv`;
        otherwise it is treated as absent and re-downloaded.
    pause : float, seconds between live requests. Not applied on cache hits.

    Returns
    -------
    DataFrame, all years concatenated and sorted by date. A year that fails
    for any reason is skipped with a printed diagnostic rather than raising.
    """
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for year in years:
        cache = out_dir / f"{site}_{year}.csv" if out_dir else None
        content = None

        if cache is not None and cache.exists():
            cached = cache.read_bytes()
            if _looks_like_defra_csv(cached):
                content = cached
            elif verbose:
                print(f"  ! {site} {year}: cached file doesn't look like a "
                      f"DEFRA export -- ignoring cache, re-downloading")

        if content is None:
            url = BASE_URL.format(site=site, year=year)
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200 or len(r.content) < 200:
                if verbose:
                    print(f"  ! {site} {year}: no data (HTTP {r.status_code}), skipped")
                continue
            if not _looks_like_defra_csv(r.content):
                if verbose:
                    preview = r.content[:150].decode("utf-8", errors="replace")
                    print(f"  ! {site} {year}: response isn't a DEFRA CSV "
                          f"(final URL after redirects: {r.url})")
                    print(f"      first bytes received: {preview!r}")
                continue                                # never cached
            if cache is not None:
                cache.write_bytes(r.content)
            content = r.content
            time.sleep(pause)

        try:
            df = read_defra_flat_csv(io.BytesIO(content),
                                     site_name=site_name or site, verbose=verbose)
        except Exception as e:
            if verbose:
                text = content.decode("utf-8", errors="replace")
                preview = "\n".join(f"    line {i}: {l[:100]!r}"
                                    for i, l in enumerate(text.splitlines()[:8]))
                print(f"  ! {site} {year}: parse failed ({e})")
                print(f"      first lines of the file actually received:\n{preview}")
            continue

        frames.append(df)
        if verbose:
            n_pm25 = df.filter(like="PM2.5").iloc[:, 0].notna().sum() if \
                any("PM2.5" in c for c in df.columns) else 0
            print(f"  {site} {year}: {len(df):,} hours, {n_pm25:,} with PM2.5")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
