#!/usr/bin/env python3
"""
build_data.py — Skenes Contact Point Lab data builder

Pulls fresh Statcast pitch-by-pitch data for Paul Skenes (MLBAM 694973),
aggregates contact-point + damage metrics by (pitch type x batter handedness),
and writes skenes_data.json next to index.html.

Usage:
  python build_data.py                    # pulls from 2024-05-14 to today
  python build_data.py --end 2026-06-15   # pulls through a custom end date
  python build_data.py --since-last       # pulls only since last build (faster)

Requirements:
  pip install pybaseball pandas numpy
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ---------- Config ----------
SKENES_MLBAM = 694973
BAT_TRACKING_START = "2024-05-14"  # Statcast bat tracking goes live
OUT_DIR = Path(__file__).parent
CACHE_PATH = OUT_DIR / "skenes_raw.parquet"
JSON_PATH = OUT_DIR / "skenes_data.json"

PITCH_NAMES = {
    "FF": "Four-Seam",
    "FS": "Splinker",
    "CH": "Changeup",
    "CU": "Curveball",
    "SI": "Sinker",
    "SL": "Slider (Gyro)",
    "ST": "Sweeper",
}

# 5x5 strike-zone + chase grid (feet)
X_EDGES = np.linspace(-1.5, 1.5, 6)
Z_EDGES = np.linspace(1.0, 4.0, 6)


# ---------- Pull ----------
def pull_data(start: str, end: str) -> pd.DataFrame:
    """Pull every Skenes Statcast pitch in [start, end]."""
    try:
        from pybaseball import statcast_pitcher
    except ImportError:
        sys.exit("ERROR: pip install pybaseball pandas numpy")
    print(f"Pulling Statcast for Skenes ({SKENES_MLBAM}) {start} → {end}…")
    df = statcast_pitcher(start, end, SKENES_MLBAM)
    print(f"  → {len(df)} pitches across {df['game_pk'].nunique()} games")
    return df


def load_or_pull(start: str, end: str, since_last: bool) -> pd.DataFrame:
    if since_last and CACHE_PATH.exists():
        cached = pd.read_parquet(CACHE_PATH)
        cached["game_date"] = pd.to_datetime(cached["game_date"])
        last_date = cached["game_date"].max().date()
        next_day = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if next_day > end:
            print(f"Cache already covers {last_date} → no new data to pull.")
            return cached
        print(f"Cache has data through {last_date}; pulling {next_day} → {end}")
        fresh = pull_data(next_day, end)
        fresh["game_date"] = pd.to_datetime(fresh["game_date"])
        df = pd.concat([cached, fresh], ignore_index=True).drop_duplicates(
            subset=["game_pk", "at_bat_number", "pitch_number"], keep="last"
        )
        df["game_date"] = pd.to_datetime(df["game_date"])
        return df
    df = pull_data(start, end)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


# ---------- Aggregate ----------
def derive(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_swing"] = df["description"].isin(
        [
            "swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
            "hit_into_play", "foul_bunt", "missed_bunt", "bunt_foul_tip",
        ]
    )
    df["is_whiff"] = df["description"].isin(
        ["swinging_strike", "swinging_strike_blocked", "foul_tip"]
    )
    df["is_bip"] = df["type"] == "X"
    df["xwobacon"] = df["estimated_woba_using_speedangle"]
    df["has_intercept"] = df["intercept_ball_minus_batter_pos_y_inches"].notna()
    return df


def cell_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    def _agg(g):
        swings = int(g["is_swing"].sum())
        bip = g[g["is_bip"]]
        bip_tr = g[g["is_bip"] & g["has_intercept"]]
        return pd.Series({
            "pitches": int(len(g)),
            "swings": swings,
            "whiffs": int(g["is_whiff"].sum()),
            "whiff_pct": (g["is_whiff"].sum() / swings) if swings else 0.0,
            "bip": int(len(bip)),
            "bip_tracked": int(len(bip_tr)),
            "mean_ev": float(bip["launch_speed"].mean()) if len(bip) else None,
            "mean_la": float(bip["launch_angle"].mean()) if len(bip) else None,
            "hardhit_pct": float((bip["launch_speed"] >= 95).mean()) if len(bip) else None,
            "xwobacon": float(bip["xwobacon"].mean()) if len(bip) else None,
            "mean_iy": float(bip_tr["intercept_ball_minus_batter_pos_y_inches"].mean()) if len(bip_tr) else None,
            "mean_ix": float(bip_tr["intercept_ball_minus_batter_pos_x_inches"].mean()) if len(bip_tr) else None,
            "popup_pct": float((bip["bb_type"] == "popup").mean()) if len(bip) else None,
            "gb_pct": float((bip["bb_type"] == "ground_ball").mean()) if len(bip) else None,
            "mean_velo": float(g["release_speed"].mean()),
        })

    cells = df.groupby(["pitch_type", "stand"]).apply(_agg, include_groups=False).reset_index()
    return cells


def grid_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["xb"] = pd.cut(df["plate_x"], X_EDGES, labels=False, include_lowest=True)
    df["zb"] = pd.cut(df["plate_z"], Z_EDGES, labels=False, include_lowest=True)
    g = df.dropna(subset=["xb", "zb"]).copy()
    g["xb"] = g["xb"].astype(int)
    g["zb"] = g["zb"].astype(int)
    grid = g.groupby(["pitch_type", "stand", "xb", "zb"]).agg(
        n=("plate_x", "size"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        bip=("is_bip", "sum"),
        xwobacon=("xwobacon", "mean"),
        mean_iy=("intercept_ball_minus_batter_pos_y_inches", "mean"),
    ).reset_index()
    return grid


def bip_records(df: pd.DataFrame) -> pd.DataFrame:
    """BIP-level records (with intercept data filtered for scatter)."""
    cols = [
        "pitch_type", "stand", "plate_x", "plate_z",
        "intercept_ball_minus_batter_pos_x_inches",
        "intercept_ball_minus_batter_pos_y_inches",
        "launch_speed", "launch_angle", "xwobacon",
        "bb_type", "events", "release_speed",
    ]
    out = df[df["is_bip"]][cols].rename(columns={
        "intercept_ball_minus_batter_pos_x_inches": "ix",
        "intercept_ball_minus_batter_pos_y_inches": "iy",
        "launch_speed": "ev",
        "launch_angle": "la",
        "release_speed": "velo",
    })
    return out


# ---------- Write ----------
def round_floats(rec, dp=2):
    return {k: (round(v, dp) if isinstance(v, float) else v) for k, v in rec.items()}


def build(df: pd.DataFrame) -> dict:
    df = derive(df)
    cells = cell_aggregate(df).replace({np.nan: None})
    grid = grid_aggregate(df).replace({np.nan: None})
    bip = bip_records(df).replace({np.nan: None})

    # Strike zone bounds — use batter-specific average sz_top/sz_bot from data
    sz_top = float(df["sz_top"].dropna().mean()) if "sz_top" in df.columns else 3.50
    sz_bot = float(df["sz_bot"].dropna().mean()) if "sz_bot" in df.columns else 1.55

    return {
        "pitch_names": PITCH_NAMES,
        "cells": [round_floats(r) for r in cells.to_dict("records")],
        "bip": [round_floats(r) for r in bip.to_dict("records")],
        "grid": [round_floats(r) for r in grid.to_dict("records")],
        "grid_meta": {"x_edges": X_EDGES.tolist(), "z_edges": Z_EDGES.tolist()},
        "sz_bounds": {"top": round(sz_top, 2), "bot": round(sz_bot, 2)},
        "meta": {
            "date_min": str(df["game_date"].min().date()),
            "date_max": str(df["game_date"].max().date()),
            "total_pitches": int(len(df)),
            "total_bip": int(df["is_bip"].sum()),
            "total_bip_tracked": int((df["is_bip"] & df["has_intercept"]).sum()),
            "games": int(df["game_pk"].nunique()),
            "built_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=BAT_TRACKING_START, help="ISO date (default: bat tracking start)")
    ap.add_argument("--end", default=date.today().isoformat(), help="ISO date (default: today)")
    ap.add_argument("--since-last", action="store_true",
                    help="Pull only since the last cached date (much faster)")
    args = ap.parse_args()

    df = load_or_pull(args.start, args.end, args.since_last)
    df.to_parquet(CACHE_PATH)
    print(f"Cached raw data → {CACHE_PATH}")

    data = build(df)
    with open(JSON_PATH, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    size_kb = JSON_PATH.stat().st_size / 1024

    m = data["meta"]
    print()
    print("=" * 60)
    print("BUILD SUMMARY")
    print("=" * 60)
    print(f"  Date range:    {m['date_min']} → {m['date_max']}")
    print(f"  Games:         {m['games']}")
    print(f"  Pitches:       {m['total_pitches']:,}")
    print(f"  BIP:           {m['total_bip']:,}")
    print(f"  BIP tracked:   {m['total_bip_tracked']:,} ({m['total_bip_tracked']/m['total_bip']*100:.1f}% coverage)")
    print(f"  Output:        {JSON_PATH}  ({size_kb:.0f} KB)")
    print()
    print("Thin cells (BIP < 25):")
    for c in data["cells"]:
        if c["bip"] < 25:
            print(f"  {c['pitch_type']} vs {c['stand']}H: {c['bip']} BIP")


if __name__ == "__main__":
    main()
