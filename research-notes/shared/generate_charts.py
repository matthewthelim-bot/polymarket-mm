import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib import rcParams
from matplotlib.patches import FancyArrowPatch

rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

# ── Geological palette ──────────────────────────────────────────────────────
DEPLETED     = '#A93226'
NEUTRAL      = '#95A5A6'
TEAL_LIGHT   = '#1ABC9C'
TEAL_MID     = '#17A589'
TEAL_DARK    = '#0E6655'
BG           = '#FFFFFF'
RULE         = '#E0E0E0'
TEXT_DARK    = '#1A1A1A'
TEXT_MID     = '#555555'
TEXT_LIGHT   = '#999999'

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — YTD PERFORMANCE HORIZONTAL BAR
# ═══════════════════════════════════════════════════════════════════════════════

fig1, ax1 = plt.subplots(figsize=(15, 9.5))
fig1.patch.set_facecolor(BG)
ax1.set_facecolor(BG)

labels = [
    'EUAD  ·  European Defense ETF',
    'QQQ  ·  Magnificent Seven Proxy',
    'RSP  ·  S&P 500 Equal Weight',
    'ROBO  ·  Global Robotics & Automation',
    'XLE  ·  Energy Select Sector',
    'BOTT  ·  Robotics & Automation',
    'ELFY  ·  Electrification Infrastructure',
    'ARTY  ·  Humanoid Robotics ETF',
]
values = [-4, -2, 4, 18, 21, 23, 27, 33]

def bar_color(v):
    if v < 0:     return DEPLETED
    if v <= 4:    return NEUTRAL
    if v <= 18:   return TEAL_LIGHT
    if v <= 23:   return TEAL_MID
    return TEAL_DARK

colors = [bar_color(v) for v in values]

bars = ax1.barh(labels, values, color=colors, height=0.50,
                edgecolor=BG, linewidth=0, zorder=3)

# Value labels
for bar, val, col in zip(bars, values, colors):
    sign = '+' if val >= 0 else ''
    if val < 0:
        ax1.text(val - 0.8, bar.get_y() + bar.get_height() / 2,
                 f'{sign}{val}%', ha='right', va='center',
                 fontsize=12, color=DEPLETED, fontweight='normal')
    else:
        ax1.text(val + 0.8, bar.get_y() + bar.get_height() / 2,
                 f'{sign}{val}%', ha='left', va='center',
                 fontsize=12, color=TEXT_MID, fontweight='normal')

# Zero line
ax1.axvline(x=0, color='#CCCCCC', linewidth=1.2, zorder=4)

# Grid
ax1.xaxis.grid(True, color='#F5F5F5', linewidth=0.8, zorder=0)
ax1.set_axisbelow(True)

# Subtle zone shading
ax1.axhspan(-0.5,  1.5, alpha=0.035, color=DEPLETED, zorder=1)
ax1.axhspan( 1.5,  2.5, alpha=0.025, color=NEUTRAL,  zorder=1)
ax1.axhspan( 2.5,  7.5, alpha=0.030, color=TEAL_MID,  zorder=1)

# Spine cleanup
for spine in ['top', 'right', 'left']:
    ax1.spines[spine].set_visible(False)
ax1.spines['bottom'].set_color(RULE)

ax1.tick_params(axis='y', length=0, labelsize=11.5, colors=TEXT_DARK, pad=10)
ax1.tick_params(axis='x', colors=TEXT_LIGHT, labelsize=9.5)
ax1.set_xlim(-16, 44)

ax1.set_xlabel('Year-to-Date Return  (%)', fontsize=10, color=TEXT_LIGHT,
               labelpad=14)

# Category side labels
for (y, label, color) in [
    (0.5, 'OUTGOING', DEPLETED),
    (2.0, 'BENCHMARK', NEUTRAL),
    (5.0, 'EMERGING', TEAL_DARK),
]:
    ax1.text(43.2, y, label, fontsize=7.5, color=color, va='center',
             ha='left', alpha=0.75, rotation=90, fontweight='bold',
             fontfamily='monospace')

# ── Title block ──────────────────────────────────────────────────────────────
fig1.text(0.08, 0.965,
          'Outgoing Consensus vs. Emerging Themes',
          fontsize=18, color=TEXT_DARK, fontweight='bold', ha='left')
fig1.text(0.08, 0.930,
          '2026 Year-to-Date Performance  ·  As of May 2026',
          fontsize=11.5, color=TEXT_LIGHT, ha='left')

rule1 = plt.Line2D([0.08, 0.94], [0.920, 0.920],
                   transform=fig1.transFigure,
                   color=RULE, linewidth=0.8)
fig1.add_artist(rule1)

# Legend
patches = [
    mpatches.Patch(color=DEPLETED,   label='Outgoing / Crowded'),
    mpatches.Patch(color=NEUTRAL,    label='Benchmark'),
    mpatches.Patch(color=TEAL_DARK,  label='Emerging Themes'),
]
ax1.legend(handles=patches, loc='lower right', frameon=False,
           fontsize=10, labelcolor=TEXT_MID,
           handlelength=1.0, handleheight=0.85, borderpad=0)

# Source note
fig1.text(0.08, 0.022,
          'Sources: Motley Fool, 24/7 Wall St., etfdb.com, investing.com — May 2026.  '
          'Returns are approximate and directional.',
          fontsize=8, color='#C0C0C0', ha='left', style='italic')

plt.tight_layout(rect=[0, 0.05, 0.96, 0.915])
out1 = r'C:\Users\matth\OneDrive\Documents\Claude\Code\thematic_rotation_chart1.png'
fig1.savefig(out1, dpi=220, bbox_inches='tight', facecolor=BG)
plt.close(fig1)
print('Chart 1 saved:', out1)


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — THEME SCORING RADAR
# ═══════════════════════════════════════════════════════════════════════════════

themes = [
    'Power Grid & Electrification',
    'Humanoid Robotics',
    'Autonomous Defense',
    'Nuclear & SMR',
    'Longevity Biotech',
    'Emerging Markets',
]
theme_colors = [
    '#16A085', '#2980B9', '#8E44AD',
    '#E67E22', '#27AE60', '#C0392B',
]
dim_labels = ['Narrative\nReadiness', 'Fundamental\nAnchor',
              'Positioning\nAsymmetry', 'Catalyst\nProximity']
scores = np.array([
    [5, 5, 3, 5],
    [4, 4, 4, 4],
    [4, 4, 4, 5],
    [4, 3, 3, 3],
    [3, 4, 5, 3],
    [3, 5, 5, 2],
])

N = 4
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

fig2 = plt.figure(figsize=(16, 12.5))
fig2.patch.set_facecolor(BG)

# Manual axes positions: [left, bottom, width, height]
positions = [
    [0.04, 0.48, 0.28, 0.40],
    [0.37, 0.48, 0.28, 0.40],
    [0.70, 0.48, 0.28, 0.40],
    [0.04, 0.06, 0.28, 0.40],
    [0.37, 0.06, 0.28, 0.40],
    [0.70, 0.06, 0.28, 0.40],
]

for theme, color, score, pos in zip(themes, theme_colors, scores, positions):
    ax = fig2.add_axes(pos, polar=True)
    ax.set_facecolor(BG)

    vals = score.tolist() + [score[0]]
    ax.fill(angles, vals, color=color, alpha=0.13)
    ax.plot(angles, vals, color=color, linewidth=2.0, solid_capstyle='round')
    ax.scatter(angles[:-1], score, color=color, s=38, zorder=5, linewidths=0)

    ring_a = np.linspace(0, 2 * np.pi, 300)
    ax.plot(ring_a, [4]*300, color='#DDDDDD', lw=0.9, ls='--', zorder=1)
    for r in [1, 2, 3, 5]:
        ax.plot(ring_a, [r]*300, color='#F3F3F3', lw=0.5, zorder=0)

    ax.set_ylim(0, 5)
    ax.set_yticks([])
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color='#EEEEEE', lw=0.7)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dim_labels, size=8.0, color='#777777')
    ax.tick_params(pad=10)
    ax.spines['polar'].set_color('#E8E8E8')
    ax.spines['polar'].set_linewidth(0.8)

    # Theme label: placed via fig coords just above subplot
    cx = pos[0] + pos[2] / 2
    top_y = pos[1] + pos[3] + 0.010
    fig2.text(cx, top_y, theme, ha='center', va='bottom',
              fontsize=11, color=color, fontweight='bold')

    # Score label below subplot
    total = int(score.sum())
    fig2.text(cx, pos[1] - 0.022, f'{total} / 20',
              ha='center', va='top', fontsize=8.5,
              color=color, alpha=0.72, style='italic')

# ── Title block ──────────────────────────────────────────────────────────────
fig2.text(0.04, 0.965,
          'Theme Scoring: Narrative x Fundamental x Positioning x Catalyst',
          fontsize=17, color=TEXT_DARK, fontweight='bold', ha='left')
fig2.text(0.04, 0.935,
          'Four-dimension assessment across six candidate themes  |  Scale: 1 (weak) to 5 (strong)  |  Dashed ring = 4',
          fontsize=10.5, color=TEXT_LIGHT, ha='left')

rule2 = plt.Line2D([0.04, 0.96], [0.926, 0.926],
                   transform=fig2.transFigure,
                   color=RULE, linewidth=0.8)
fig2.add_artist(rule2)

fig2.text(0.04, 0.016,
          'Internal assessment -- May 2026.  Scores represent analyst judgment, not quantitative backtests.',
          fontsize=8, color='#BBBBBB', ha='left', style='italic')

out2 = r'C:\Users\matth\OneDrive\Documents\Claude\Code\thematic_rotation_chart2.png'
fig2.savefig(out2, dpi=220, bbox_inches='tight', facecolor=BG)
plt.close(fig2)
print('Chart 2 saved:', out2)
print('Done.')
