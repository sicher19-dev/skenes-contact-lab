# Skenes Contact Point Lab

Interactive contact-point + damage map for Paul Skenes' arsenal, built from Statcast pitch-by-pitch and bat-tracking data.

**Live data range:** 2024-05-17 → 2026-05-23
**Counts:** 6,420 pitches · 979 BIP · 880 tracked-BIP (89.9% bat-tracking coverage) · 72 games

---

## Data verification

Cross-checked against [Baseball Savant's Skenes player page](https://baseballsavant.mlb.com/savant-player/paul-skenes-694973) for the 2026 regular season:

| Metric (2026) | This dataset | Savant | Match |
|---|---|---|---|
| Avg EV | 87.3 | 87.4 | ✓ |
| Hard Hit % | 34.5 | 34.6 | ✓ |
| Barrel % | 4.8 | 4.6 | ✓ |
| wOBA | .248 | .246 | ✓ |
| xwOBA | .253 | .248 | ✓ |

Pitch classifications come straight from MLB's Statcast (same source Savant displays). The `FS` label = **Splinker** (93.8 mph, ~0 IVB, armside HB) — confirmed against the movement profile, not a generic splitter.

**Caveats:**
- Bat tracking went live May 14, 2024 — earlier Skenes pitches don't have intercept data
- 99 of 979 BIP don't have intercept coordinates (broadcast/tech gaps); the scatter and depth-chart panels filter to the 880 tracked BIP, but cell summaries show both counts
- Three cells run thin (< 25 tracked BIP) and are flagged in the UI: **SL vs LHH** (6), **CU vs RHH** (10), **CH vs RHH** (7)

---

## Files

```
contact-lab/
├── index.html         ← the app (single file, no build step)
├── skenes_data.json   ← pre-aggregated dataset (203 KB)
└── build_data.py      ← pipeline to refresh skenes_data.json
```

---

## How to update after each start

After a Skenes start, refresh the data:

```bash
cd contact-lab
pip install pybaseball pandas numpy   # one-time
python build_data.py --since-last
```

`--since-last` reads the cached parquet and only pulls new games — takes ~10 seconds. To do a full rebuild instead, drop the flag:

```bash
python build_data.py
```

To pull through a specific date (useful for re-running historical):

```bash
python build_data.py --end 2026-06-15
```

The script overwrites `skenes_data.json` in place. Commit and push to deploy.

---

## How to deploy to GitHub Pages

**Option A — new repo (recommended, matches Scout pattern):**

```bash
# 1. Create the repo on github.com → name it skenes-contact-lab (or whatever)
# 2. Locally:
mkdir skenes-contact-lab && cd skenes-contact-lab
cp /path/to/contact-lab/* .
git init
git add index.html skenes_data.json build_data.py README.md
git commit -m "initial: contact point lab"
git branch -M main
git remote add origin https://github.com/sicher19-dev/skenes-contact-lab.git
git push -u origin main

# 3. On GitHub: Settings → Pages → Source: "Deploy from a branch"
#    → Branch: main / root → Save
# 4. Wait ~30s. Live at:  https://sicher19-dev.github.io/skenes-contact-lab/
```

**Option B — add as a subdirectory of an existing GH Pages repo:**

```bash
# e.g. inside your skenes-scout repo:
cd skenes-scout
mkdir contact-lab
cp /path/to/contact-lab/* contact-lab/
git add contact-lab/
git commit -m "add: contact point lab"
git push
# Live at: https://sicher19-dev.github.io/skenes-scout/contact-lab/
```

**To refresh between starts:**

```bash
cd skenes-contact-lab
python build_data.py --since-last
git add skenes_data.json skenes_raw.parquet
git commit -m "data: through $(date +%Y-%m-%d)"
git push
```

GH Pages will auto-rebuild in ~30 seconds. No other deploy step needed.

**Note on `skenes_raw.parquet`:** the script caches the raw pull (~3 MB) here so `--since-last` works. You can either commit it (faster reruns from any machine) or `.gitignore` it (keeps the repo small but `--since-last` only works on the machine that ran the last full pull).

---

## How to run it locally without deploying

```bash
cd contact-lab
python3 -m http.server 8000
# open http://localhost:8000
```

Plain static files, no server-side logic. Works in any browser.

---

## What's in the app

- **Selectors:** pitch type · batter handedness (LHH/RHH)
- **Stats row:** pitches, whiff%, BIP (total + tracked), xwOBAcon, avg EV, mean contact depth, avg velo
- **Read-out:** plain-English summary that updates per cell — flags thin samples
- **Pitch location panel:** 5×5 zone grid, cell color = xwOBA on contact, cell size = BIP density, with strike zone overlay (measured from the data)
- **Contact point distribution:** scatter of every tracked BIP — depth (vertical) vs lateral — color-coded by damage, with mean centroid overlay
- **Damage by depth:** xwOBA as a function of intercept depth, with BIP-count histogram underlay — directly visualizes "jammed contact = weak / out-front contact = damage"

---

## Pipeline architecture

```
pybaseball.statcast_pitcher(694973)
        ↓
raw pitch-level data  (skenes_raw.parquet)
        ↓
  derive flags  (is_swing, is_whiff, is_bip, has_intercept, xwobacon)
        ↓
  aggregate at three levels:
    • per (pitch_type × stand)            → cells[]
    • per (pitch_type × stand × xb × zb)  → grid[]
    • per BIP row                          → bip[]
        ↓
skenes_data.json
        ↓
index.html (vanilla JS canvas rendering, no framework)
```

Whole pipeline is ~250 lines of Python + one HTML file. Easy to fork, easy to debug.
