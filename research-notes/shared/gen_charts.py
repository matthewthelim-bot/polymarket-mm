import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker
import numpy as np

CIRCLE_BLUE = '#2775CA'
HYPE_GREEN  = '#00D4AA'
GRID_COLOR  = '#E8E8E8'
AXIS_COLOR  = '#AAAAAA'
TEXT_COLOR  = '#1A1A2E'
LABEL_COLOR = '#555555'
BG          = '#FFFFFF'

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), facecolor=BG)
fig.subplots_adjust(left=0.06, right=0.97, top=0.88, bottom=0.18, wspace=0.12)

# ── CHART 1: USDC on Hyperliquid ────────────────────────────────────────────
ax1.set_facecolor(BG)
labels = ['Pre-deal\n(bridged, Aug 2025)', 'Post native launch\n(Sep 2025)', 'Post AQAv2\n(May 2026)']
values = [5.3, 5.5, 5.0]
x = np.arange(len(labels))
bar_width = 0.42

bars = ax1.bar(x, values, width=bar_width, color=CIRCLE_BLUE,
               alpha=0.88, zorder=3, linewidth=0)

# bar value labels
for bar, val in zip(bars, values):
    ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.08,
             f'${val}B', ha='center', va='bottom',
             fontsize=9.5, color=TEXT_COLOR, fontweight='500',
             fontfamily='DejaVu Sans')

# 7% reference line
ref_y = 5.3
ax1.axhline(ref_y, color=CIRCLE_BLUE, linewidth=1.1,
            linestyle=(0, (5, 4)), alpha=0.55, zorder=2)
ax1.text(len(labels) - 0.55, ref_y + 0.12,
         '7% of total USDC supply', ha='right', va='bottom',
         fontsize=8, color=CIRCLE_BLUE, alpha=0.75,
         fontfamily='DejaVu Sans', style='italic')

ax1.set_ylim(0, 8)
ax1.set_xlim(-0.5, len(labels) - 0.5)
ax1.set_xticks(x)
ax1.set_xticklabels(labels, fontsize=8.5, color=LABEL_COLOR, fontfamily='DejaVu Sans')
ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'${v:g}B'))
ax1.tick_params(axis='y', labelsize=8.5, colors=LABEL_COLOR)
ax1.tick_params(axis='x', length=0)
ax1.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
ax1.set_axisbelow(True)
for spine in ax1.spines.values():
    spine.set_visible(False)
ax1.spines['bottom'].set_visible(True)
ax1.spines['bottom'].set_color(GRID_COLOR)

ax1.set_title('USDC on Hyperliquid — Supply Growth',
              fontsize=11, fontweight='bold', color=TEXT_COLOR,
              fontfamily='DejaVu Sans', pad=10, loc='left')
ax1.text(0, -0.20, 'Sources: CoinMarketCap, DefiLlama, Circle Blog (2025–2026)',
         transform=ax1.transAxes, fontsize=7, color='#999999',
         fontfamily='DejaVu Sans')

# ── CHART 2: HYPE Token Price ────────────────────────────────────────────────
ax2.set_facecolor(BG)

# Data: (label, x_pos, price)  x_pos is arbitrary numeric for spacing
months = ['Aug 2025', 'Sep 16\n(Circle)', 'Sep 18\n(ATH)', 'Oct 2025',
          'Jan 2026', 'Mar 2026', 'May 2026\n(AQAv2)']
prices = [18, 40, 59, 45, 28, 20, 39]
x2 = np.arange(len(months))

ax2.plot(x2, prices, color=HYPE_GREEN, linewidth=2.2, zorder=3,
         solid_capstyle='round', solid_joinstyle='round')
ax2.fill_between(x2, prices, alpha=0.08, color=HYPE_GREEN, zorder=2)
ax2.scatter(x2, prices, color=HYPE_GREEN, s=38, zorder=4, linewidths=0)

# Event verticals
for xi, label in [(1, 'Circle deal\nSep 16, 2025'), (6, 'AQAv2\nMay 2026')]:
    ax2.axvline(xi, color=HYPE_GREEN, linewidth=0.9,
                linestyle='--', alpha=0.45, zorder=2)
    ax2.text(xi + 0.07, max(prices) * 0.96, label,
             fontsize=7.2, color=HYPE_GREEN, alpha=0.80,
             fontfamily='DejaVu Sans', va='top')

ax2.set_ylim(0, 72)
ax2.set_xlim(-0.3, len(months) - 0.7)
ax2.set_xticks(x2)
ax2.set_xticklabels(months, fontsize=8.2, color=LABEL_COLOR, fontfamily='DejaVu Sans')
ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'${v:g}'))
ax2.tick_params(axis='y', labelsize=8.5, colors=LABEL_COLOR)
ax2.tick_params(axis='x', length=0)
ax2.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
ax2.set_axisbelow(True)
for spine in ax2.spines.values():
    spine.set_visible(False)
ax2.spines['bottom'].set_visible(True)
ax2.spines['bottom'].set_color(GRID_COLOR)

ax2.set_title('HYPE Token Price — Around Partnership Events',
              fontsize=11, fontweight='bold', color=TEXT_COLOR,
              fontfamily='DejaVu Sans', pad=10, loc='left')
ax2.text(0, -0.20, 'Sources: CoinMarketCap, DefiLlama, Circle Blog (2025–2026)',
         transform=ax2.transAxes, fontsize=7, color='#999999',
         fontfamily='DejaVu Sans')

out = r'C:\Users\matth\OneDrive\Documents\Claude\Code\circle_hyperliquid_charts.png'
fig.savefig(out, dpi=180, bbox_inches='tight', facecolor=BG)
plt.close(fig)
print(f'Saved: {out}')
