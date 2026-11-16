import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# ============================================================
# 0. PATHS (relative to the script, so the project runs on any PC)
# ============================================================

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()  # fallback when running cell-by-cell (F9) in Spyder

DATA_DIR = os.path.join(BASE_DIR, "..", "csv_euroleague")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

SEASONS = [f'E{y}' for y in range(2015, 2026)]

# ============================================================
# 1. LOAD DATA
# ============================================================

points = pd.read_csv(os.path.join(DATA_DIR, "euroleague_points.csv"))
points_scope = points[points['season_code'].isin(SEASONS)].copy()

# ============================================================
# 2. BUILD FIELD GOAL DATASET: exclude free throws, derive shot type, made/missed, and zone from coordinates
# ============================================================

# Free throws are logged as 'FTM' only (makes), with no separate attempt code,
# so they are not reliably trackable here and are excluded from field goal analysis.
fg = points_scope[points_scope['action_id'] != 'FTM'].copy()

fg['shot_type'] = 'unclear'
fg.loc[fg['action_id'].str.startswith('2'), 'shot_type'] = '2PT'
fg.loc[fg['action_id'].str.startswith('3'), 'shot_type'] = '3PT'
# LAYUPATT, LAYUPMD, DUNK have no numeric prefix but are always worth 2 points
fg.loc[fg['action_id'].isin(['LAYUPATT', 'LAYUPMD', 'DUNK']), 'shot_type'] = '2PT'

fg['made'] = (fg['points'] > 0).astype(int)

fg['zone'] = 'Other'
fg.loc[fg['shot_type'] == '3PT', 'zone'] = '3PT'

in_paint = (
    (fg['coord_x'].abs() <= 245) &
    (fg['coord_y'] >= -157.5) &
    (fg['coord_y'] <= 580 - 157.5)
)
fg.loc[(fg['shot_type'] == '2PT') & in_paint, 'zone'] = 'Paint'
fg.loc[(fg['shot_type'] == '2PT') & ~in_paint, 'zone'] = 'Mid-range'

print(f"Field goal attempts in scope (E2015-E2025): {len(fg)}")

# ============================================================
# 2.1 DATA QUALITY CHECKS ON THE SHOT CLASSIFICATION
# Shot type (2PT/3PT) comes from action_id, the paint/mid-range split from
# coordinates. The checks below test the classification on its own terms.
# ============================================================

print("\n=== Check 1: shots whose action_id could not be classified ===")
n_unclear = (fg['shot_type'] == 'unclear').sum()
print(f"Unclear shot type: {n_unclear} ({n_unclear / len(fg) * 100:.3f}%)")
if n_unclear > 0:
    print(fg.loc[fg['shot_type'] == 'unclear', 'action_id'].value_counts())

print("\n=== Check 2: missing or placeholder coordinates ===")
n_nan = fg[['coord_x', 'coord_y']].isna().any(axis=1).sum()
no_coords = (fg['coord_x'] == 0) & (fg['coord_y'] == 0)  # (0, 0) is the basket itself: a placeholder
print(f"Missing (NaN) coordinates: {n_nan}")
print(f"Placeholder coordinates (0, 0): {no_coords.sum()} ({no_coords.mean() * 100:.3f}%)")
print(fg.loc[no_coords, 'shot_type'].value_counts())

# Shots without usable coordinates cannot be placed on the court: drop them
fg = fg[~no_coords & fg[['coord_x', 'coord_y']].notna().all(axis=1)].copy()

print("\n=== Check 3: distance from the basket vs shot type ===")
# The three-point line is 660 cm from the basket in the corners and 675 cm at the top.
# Coordinates are measured from the basket, so distance = sqrt(x^2 + y^2).
fg['distance_cm'] = np.hypot(fg['coord_x'], fg['coord_y'])
THREE_MIN_DIST = 600   # a three-pointer closer than this is suspicious
TWO_MAX_DIST = 700     # a two-pointer farther than this is suspicious

three = fg[fg['shot_type'] == '3PT']
two = fg[fg['shot_type'] == '2PT']
print(f"3PT median distance: {three['distance_cm'].median():.0f} cm | 2PT median distance: {two['distance_cm'].median():.0f} cm")
print(f"3PT closer than {THREE_MIN_DIST} cm: {(three['distance_cm'] < THREE_MIN_DIST).sum()} ({(three['distance_cm'] < THREE_MIN_DIST).mean() * 100:.2f}% of 3PT)")
print(f"2PT farther than {TWO_MAX_DIST} cm: {(two['distance_cm'] > TWO_MAX_DIST).sum()} ({(two['distance_cm'] > TWO_MAX_DIST).mean() * 100:.2f}% of 2PT)")

print(f"\nField goal attempts used in the analysis: {len(fg)}")

# ============================================================
# 3. LEAGUE-WIDE SUMMARY: VOLUME AND EFFICIENCY BY ZONE
# ============================================================

zone_summary = fg.groupby('zone').agg(
    attempts=('made', 'count'),
    made=('made', 'sum')
)
zone_summary['share_pct'] = (zone_summary['attempts'] / zone_summary['attempts'].sum() * 100).round(1)
zone_summary['fg_pct'] = (zone_summary['made'] / zone_summary['attempts'] * 100).round(1)
zone_summary = zone_summary.reindex(['Paint', 'Mid-range', '3PT'])

print("\n=== League-wide: shot volume and efficiency by zone (2015-2025) ===")
print(zone_summary)

# ============================================================
# 4. TREND OVER TIME: SHOT SELECTION (ZONE SHARE BY SEASON)
# ============================================================

season_zone_counts = fg.groupby(['season_code', 'zone']).size().unstack()
season_zone_share = season_zone_counts.div(season_zone_counts.sum(axis=1), axis=0) * 100
season_zone_share = season_zone_share[['Paint', 'Mid-range', '3PT']]

print("\n=== Shot selection share by season (%) ===")
print(season_zone_share.round(1))

# ============================================================
# 5. TREND OVER TIME: SHOOTING EFFICIENCY BY ZONE, PER SEASON
# ============================================================

season_zone_fg = fg.groupby(['season_code', 'zone'])['made'].mean().unstack() * 100
season_zone_fg = season_zone_fg[['Paint', 'Mid-range', '3PT']]

print("\n=== Shooting percentage by zone, per season ===")
print(season_zone_fg.round(1))

# ============================================================
# 6. EFFECTIVE FIELD GOAL PERCENTAGE (eFG%) BY ZONE, PER SEASON
# eFG% accounts for 3PT shots being worth more than 2PT shots.
# For 2PT zones (Paint, Mid-range), eFG% equals plain FG%.
# For 3PT, eFG% = FG% times 1.5, since a make is worth 1.5x a 2PT make.
# ============================================================

season_zone_efg = season_zone_fg.copy()
season_zone_efg['3PT'] = season_zone_efg['3PT'] * 1.5

print("\n=== Effective FG% (eFG%) by zone, per season ===")
print(season_zone_efg.round(1))

print("\n=== League-wide average, FG% vs eFG%, by zone (2015-2025) ===")
avg_fg_vs_efg = pd.DataFrame({
    'FG%': season_zone_fg.mean().round(1),
    'eFG%': season_zone_efg.mean().round(1)
})
print(avg_fg_vs_efg)

# Pooled rates (all attempts together), for comparison with the mean of seasons
pooled = fg.groupby('zone')['made'].mean().reindex(['Paint', 'Mid-range', '3PT']) * 100
print("\n=== Pooled FG% by zone (all attempts together) ===")
print(pooled.round(1))

# ============================================================
# 7. PLOT 1: 3PT SHARE TREND, WITH LINEAR TREND LINE
# ============================================================

# Light palette (same as the HTML report)
BG_COLOR = '#FBFCEE'      # figure and axes background
BORDER_COLOR = '#D6DFA8'  # spines and grid
TEXT_COLOR = '#16233F'    # titles, labels, ticks
MID_COLOR = '#C6564F'     # coral
THREE_COLOR = '#B8860B'   # gold

seasons_labels = season_zone_share.index
x_numeric = np.arange(len(seasons_labels))

def plot_trend_with_line(values, color, title, filename, ylabel):
    """Plots a season-by-season line with markers, plus a linear trend line
    fitted on the same data (least squares, degree 1)."""
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    ax.plot(seasons_labels, values, marker='o', color=color, linewidth=2, label='Season value')

    # Linear trend line (least squares fit)
    slope, intercept = np.polyfit(x_numeric, values, 1)
    trend_line = slope * x_numeric + intercept
    ax.plot(seasons_labels, trend_line, color=TEXT_COLOR, linewidth=1.5, linestyle='--', label='Linear trend')

    ax.set_ylabel(ylabel, color=TEXT_COLOR)
    ax.set_title(title, color=TEXT_COLOR)
    ax.tick_params(colors=TEXT_COLOR)
    ax.tick_params(axis='x', rotation=45)
    ax.grid(color=BORDER_COLOR, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(BORDER_COLOR)

    legend = ax.legend(facecolor=BG_COLOR, edgecolor=BORDER_COLOR)
    plt.setp(legend.get_texts(), color=TEXT_COLOR)

    plt.tight_layout()
    fig.savefig(os.path.join(IMAGES_DIR, filename), dpi=150, facecolor=fig.get_facecolor(), pad_inches=0.3)
    plt.show()

    return slope

three_pt_slope = plot_trend_with_line(
    season_zone_share['3PT'].values, THREE_COLOR,
    'EuroLeague 3PT attempt share, 2015-2025',
    'three_pt_share_trend.png',
    'Share of field goal attempts (%)'
)

print(f"\n3PT share trend: {three_pt_slope:+.2f} percentage points per season")

# ============================================================
# 8. PLOT 2: MID-RANGE SHARE TREND, WITH LINEAR TREND LINE
# ============================================================

mid_range_slope = plot_trend_with_line(
    season_zone_share['Mid-range'].values, MID_COLOR,
    'EuroLeague mid-range attempt share, 2015-2025',
    'mid_range_share_trend.png',
    'Share of field goal attempts (%)'
)

print(f"Mid-range share trend: {mid_range_slope:+.2f} percentage points per season")

