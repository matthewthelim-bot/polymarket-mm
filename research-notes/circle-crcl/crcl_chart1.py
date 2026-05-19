import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Data ──────────────────────────────────────────────────────────────────────
years   = ['FY2024A', 'FY2025A', 'FY2026E']
revenue = [1.70,       2.75,       2.90]     # $B
ebitda  = [0.112,      0.582,      0.634]    # $B

x = np.arange(len(years))
bar_w = 0.52

# ── Palette (Reserve Geometry) ─────────────────────────────────────────────
BLUE      = '#1B3A6B'      # deep institutional blue
BLUE_LITE = '#2F5F9E'
AMBER     = '#C8811A'      # accumulation / return line
BG        = '#FFFFFF'
GRID      = '#E8EDF2'
LABEL     = '#4A5568'
ANNOT     = '#1B3A6B'
SOURCE    = '#8C9BB0'

# ── Figure ────────────────────────────────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(9, 5.5))
fig.patch.set_facecolor(BG)
ax1.set_facecolor(BG)

# ── Bars — Revenue ────────────────────────────────────────────────────────────
bars = ax1.bar(x, revenue, width=bar_w, color=BLUE, zorder=3,
               linewidth=0, alpha=0.92)

# Subtle gradient-feel: lighter top strip
for bar, val in zip(bars, revenue):
    ax1.bar(bar.get_x(), val, width=bar_w, bottom=val * 0.88,
            color=BLUE_LITE, alpha=0.30, zorder=4, linewidth=0)

# Bar value labels
for bar, val in zip(bars, revenue):
    ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.04,
             f'${val:.2f}B', ha='center', va='bottom',
             fontsize=9.5, fontweight='600', color=ANNOT, zorder=5)

# ── Line — Adj. EBITDA (right axis) ───────────────────────────────────────────
ax2 = ax1.twinx()
ax2.set_facecolor('none')

ax2.plot(x, ebitda, color=AMBER, linewidth=2.2, marker='o',
         markersize=7, markerfacecolor=AMBER, markeredgewidth=0,
         zorder=6, solid_capstyle='round')

# EBITDA value labels
for xi, val in zip(x, ebitda):
    offset = 0.028
    ax2.text(xi + 0.06, val + offset,
             f'${val*1000:.0f}M', ha='left', va='bottom',
             fontsize=9, fontweight='600', color=AMBER, zorder=7)

# ── Grid ──────────────────────────────────────────────────────────────────────
ax1.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
ax1.set_axisbelow(True)

# ── Axes styling ──────────────────────────────────────────────────────────────
ax1.spines[['top', 'right']].set_visible(False)
ax1.spines['left'].set_color(GRID)
ax1.spines['bottom'].set_color(GRID)
ax2.spines[['top', 'left', 'bottom']].set_visible(False)
ax2.spines['right'].set_color(GRID)

ax1.tick_params(axis='both', which='both', length=0, labelcolor=LABEL, labelsize=9)
ax2.tick_params(axis='both', which='both', length=0, labelcolor=AMBER, labelsize=9)

ax1.set_xticks(x)
ax1.set_xticklabels(years, fontsize=10, color=LABEL, fontweight='500')

ax1.set_ylim(0, 3.9)
ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'${v:.1f}B'))
ax1.set_ylabel('Total Revenue & Reserve Income', fontsize=9.5, color=LABEL,
               labelpad=10)

ax2.set_ylim(0, 0.85)
ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'${v*1000:.0f}M'))
ax2.set_ylabel('Adj. EBITDA', fontsize=9.5, color=AMBER, labelpad=10)

# ── Title block ───────────────────────────────────────────────────────────────
fig.text(0.065, 0.965,
         'CRCL: Revenue & Adj. EBITDA Trend',
         fontsize=13.5, fontweight='700', color=BLUE, va='top')
fig.text(0.065, 0.935,
         'Total Revenue & Reserve Income (bars, left)  ·  Adj. EBITDA (line, right)',
         fontsize=8.5, color=LABEL, va='top')

# ── Legend ────────────────────────────────────────────────────────────────────
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
legend_handles = [
    Patch(facecolor=BLUE, label='Revenue & Reserve Income'),
    Line2D([0], [0], color=AMBER, linewidth=2.2, marker='o', markersize=6,
           label='Adj. EBITDA'),
]
ax1.legend(handles=legend_handles, loc='upper left', frameon=False,
           fontsize=8.5, labelcolor=LABEL, handlelength=1.6)

# ── Source note ───────────────────────────────────────────────────────────────
fig.text(0.065, 0.012,
         'Source: Circle earnings releases, analyst estimates. '
         'FY2024 Adj. EBITDA is a directional estimate.',
         fontsize=7.5, color=SOURCE, va='bottom', style='italic')

plt.tight_layout(rect=[0, 0.03, 1, 0.93])
plt.savefig(r'C:\Users\matth\OneDrive\Documents\Claude\Code\crcl_chart1_revenue_ebitda.png',
            dpi=180, bbox_inches='tight', facecolor=BG)
print('Chart 1 saved.')
