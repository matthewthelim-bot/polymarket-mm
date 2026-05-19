import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Data ──────────────────────────────────────────────────────────────────────
# NTM EV/EBITDA
labels_ev   = ['CRCL', 'COIN\n(crypto exchange)', 'TW\n(Tradeweb)', 'PYPL\n(PayPal)', 'Fintech\nPeer Avg']
ev_ebitda   = [43.4,    22.1,                       25.8,             13.4,             20.4]

# NTM P/E
labels_pe   = ['CRCL', 'COIN', 'TW', 'PYPL', 'Peer Avg']
nte_pe      = [99.8,   28.5,   32.1, 17.8,   26.1]

x_ev = np.arange(len(labels_ev))
x_pe = np.arange(len(labels_pe))
bw   = 0.55

# ── Palette ───────────────────────────────────────────────────────────────────
BLUE     = '#1B3A6B'
BLUE2    = '#2F5F9E'
AMBER    = '#C8811A'
GREY     = '#CBD5E0'
BG       = '#FFFFFF'
GRID     = '#E8EDF2'
LABEL    = '#4A5568'
SOURCE   = '#8C9BB0'

# ── Figure: 2 subplots side by side ───────────────────────────────────────────
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.5))
fig.patch.set_facecolor(BG)

def style_ax(ax):
    ax.set_facecolor(BG)
    ax.spines[['top', 'right']].set_visible(False)
    ax.spines['left'].set_color(GRID)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(axis='both', which='both', length=0,
                   labelcolor=LABEL, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

# ── Helper: colors (CRCL = amber highlight, others = blue/grey) ───────────────
def bar_colors(n):
    cols = [GREY] * n
    cols[0] = AMBER   # CRCL always first
    return cols

# ── Chart A: EV/EBITDA ────────────────────────────────────────────────────────
colors_ev = bar_colors(len(ev_ebitda))
bars1 = ax1.bar(x_ev, ev_ebitda, width=bw, color=colors_ev, zorder=3, linewidth=0)
style_ax(ax1)

for bar, val, c in zip(bars1, ev_ebitda, colors_ev):
    ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.6,
             f'{val:.1f}x', ha='center', va='bottom',
             fontsize=9, fontweight='600',
             color=AMBER if c == AMBER else BLUE)

ax1.set_xticks(x_ev)
ax1.set_xticklabels(labels_ev, fontsize=8.5, color=LABEL)
ax1.set_ylim(0, 60)
ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'{v:.0f}x'))
ax1.set_ylabel('NTM EV / EBITDA', fontsize=9.5, color=LABEL, labelpad=8)
ax1.set_title('NTM EV/EBITDA vs. Peers', fontsize=11, fontweight='700',
               color=BLUE, pad=12)

# Peer avg reference line
peer_avg_ev = np.mean([v for v in ev_ebitda[1:]])
ax1.axhline(peer_avg_ev, color=BLUE2, linewidth=1.2, linestyle='--',
            zorder=2, alpha=0.7)
ax1.text(len(ev_ebitda) - 0.5, peer_avg_ev + 0.8,
         f'Peer avg: {peer_avg_ev:.1f}x',
         fontsize=7.5, color=BLUE2, ha='right')

# ── Chart B: P/E ──────────────────────────────────────────────────────────────
colors_pe = bar_colors(len(nte_pe))
bars2 = ax2.bar(x_pe, nte_pe, width=bw, color=colors_pe, zorder=3, linewidth=0)
style_ax(ax2)

for bar, val, c in zip(bars2, nte_pe, colors_pe):
    ax2.text(bar.get_x() + bar.get_width() / 2, val + 1.2,
             f'{val:.1f}x', ha='center', va='bottom',
             fontsize=9, fontweight='600',
             color=AMBER if c == AMBER else BLUE)

ax2.set_xticks(x_pe)
ax2.set_xticklabels(labels_pe, fontsize=9, color=LABEL)
ax2.set_ylim(0, 130)
ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f'{v:.0f}x'))
ax2.set_ylabel('NTM P/E', fontsize=9.5, color=LABEL, labelpad=8)
ax2.set_title('NTM P/E vs. Peers', fontsize=11, fontweight='700',
               color=BLUE, pad=12)

peer_avg_pe = np.mean([v for v in nte_pe[1:]])
ax2.axhline(peer_avg_pe, color=BLUE2, linewidth=1.2, linestyle='--',
            zorder=2, alpha=0.7)
ax2.text(len(nte_pe) - 0.5, peer_avg_pe + 2,
         f'Peer avg: {peer_avg_pe:.1f}x',
         fontsize=7.5, color=BLUE2, ha='right')

# ── Shared title ──────────────────────────────────────────────────────────────
fig.text(0.5, 0.975, 'CRCL: Valuation Multiples vs. Peer Group',
         ha='center', fontsize=13.5, fontweight='700', color=BLUE, va='top')
fig.text(0.5, 0.945, 'CRCL highlighted in amber  ·  Peers: COIN, TW, PYPL',
         ha='center', fontsize=8.5, color=LABEL, va='top')

fig.text(0.5, 0.012,
         'Source: Analyst estimates, Yahoo Finance (May 2026). '
         'Peer multiples are directional estimates; no single clean comp set exists for CRCL.',
         ha='center', fontsize=7.5, color=SOURCE, va='bottom', style='italic')

plt.tight_layout(rect=[0, 0.04, 1, 0.92])
plt.savefig(r'C:\Users\matth\OneDrive\Documents\Claude\Code\crcl_chart2_valuation.png',
            dpi=180, bbox_inches='tight', facecolor=BG)
print('Chart 2 saved.')
