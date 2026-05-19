"""
Institutional research note PDF generator
Circle (CRCL) x Hyperliquid (HYPE) -- Deal Impact Note
UPDATED 15 MAY 2026: AQAv2 split confirmed 90/10
All string literals use ASCII-safe Unicode escapes to prevent encoding corruption.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Image
)
from reportlab.platypus.flowables import Flowable
import os

EM  = "—"   # em dash
MUL = "×"   # multiplication x
RSQ = "’"   # right single quote / apostrophe
BUL = "•"   # bullet

# Colours
C_DARK      = colors.HexColor('#1A1A2E')
C_MID       = colors.HexColor('#444455')
C_LIGHT     = colors.HexColor('#888899')
C_RULE      = colors.HexColor('#CCCCCC')
C_SHADE     = colors.HexColor('#F7F7F7')
C_WHITE     = colors.white
C_BOX_BG    = colors.HexColor('#F9F9F9')
C_BOX_BORD  = colors.HexColor('#DDDDDD')
C_BULL_BG   = colors.HexColor('#F0F7F0')
C_BEAR_BG   = colors.HexColor('#FFF5F5')
C_BULL_BORD = colors.HexColor('#88BB88')
C_BEAR_BORD = colors.HexColor('#CC8888')
C_HDR_BG    = colors.HexColor('#1A1A2E')
C_UPD_BG    = colors.HexColor('#FFF8E6')
C_UPD_BORD  = colors.HexColor('#D48A00')

# Page geometry
PAGE_W, PAGE_H = A4
L_MARGIN  = 1.25 * inch
R_MARGIN  = 1.25 * inch
T_MARGIN  = 0.9  * inch
B_MARGIN  = 0.8  * inch
CONTENT_W = PAGE_W - L_MARGIN - R_MARGIN

OUTPUT = r'C:\Users\matth\OneDrive\Documents\Claude\Code\circle_hyperliquid_note.pdf'
CHART  = r'C:\Users\matth\OneDrive\Documents\Claude\Code\circle_hyperliquid_charts.png'

# Styles
def make_styles():
    def s(name, **kw):
        return ParagraphStyle(name, **kw)
    return dict(
        stamp       = s('Stamp',       fontName='Helvetica-Bold', fontSize=6.5,
                        textColor=C_LIGHT, alignment=TA_RIGHT, leading=8, spaceAfter=0),
        title       = s('NoteTitle',   fontName='Helvetica-Bold', fontSize=16,
                        textColor=C_DARK, leading=20, spaceAfter=4),
        subtitle    = s('NoteSubtitle',fontName='Helvetica', fontSize=10,
                        textColor=C_MID, leading=14, spaceAfter=14),
        sec         = s('Section',     fontName='Helvetica-Bold', fontSize=9.5,
                        textColor=C_DARK, leading=12, spaceBefore=16, spaceAfter=6),
        body        = s('Body',        fontName='Helvetica', fontSize=9.5,
                        textColor=C_DARK, leading=14.5, spaceAfter=7, alignment=TA_JUSTIFY),
        label       = s('Label',       fontName='Helvetica-Bold', fontSize=8.5,
                        textColor=C_DARK, leading=12, spaceAfter=2, spaceBefore=6),
        flag        = s('Flag',        fontName='Helvetica', fontSize=9,
                        textColor=C_DARK, leading=13.5, spaceAfter=6,
                        leftIndent=12, firstLineIndent=-12),
        callout     = s('Callout',     fontName='Helvetica', fontSize=9,
                        textColor=C_DARK, leading=13.5, spaceAfter=4,
                        leftIndent=8, rightIndent=4),
        callout_head= s('CalloutHead', fontName='Helvetica-Bold', fontSize=8.5,
                        textColor=C_MID, leading=11, spaceAfter=3, leftIndent=8),
        caption     = s('Caption',     fontName='Helvetica', fontSize=7.5,
                        textColor=C_LIGHT, leading=10, spaceAfter=10,
                        alignment=TA_CENTER, spaceBefore=3),
        table_head  = s('TableHead',   fontName='Helvetica-Bold', fontSize=8,
                        textColor=C_DARK, leading=10, alignment=TA_LEFT),
        table_cell  = s('TableCell',   fontName='Helvetica', fontSize=8.5,
                        textColor=C_DARK, leading=12, alignment=TA_LEFT),
    )

ST = make_styles()
TICKERS = ['CRCL', 'HYPE', 'USDC', 'USDT', 'USDH', 'AQAv2', 'CCTP']

def bold_tickers(text):
    import re
    for t in TICKERS:
        text = re.sub(rf'\b({re.escape(t)})\b', r'<b>\1</b>', text)
    return text

def P(text, style='body', bold_t=True):
    if bold_t:
        text = bold_tickers(text)
    return Paragraph(text, ST[style])

def section_header(num, title):
    return [
        HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE,
                   spaceAfter=0, spaceBefore=10),
        P(f'{num:02d} {EM} {title.upper()}', 'sec', bold_t=False),
    ]

class Box(Flowable):
    def __init__(self, heading, text, bg, bord):
        super().__init__()
        self.heading = heading
        self.text    = text
        self.bg      = bg
        self.bord    = bord
        self.width   = CONTENT_W
        self._cache  = None

    def _build(self):
        if self._cache:
            return
        pad = 8
        iw  = self.width - 2 * pad - 12
        hp  = Paragraph(bold_tickers(self.heading), ST['callout_head'])
        bp  = Paragraph(bold_tickers(self.text),    ST['callout'])
        _, hh = hp.wrap(iw, 9999)
        _, bh = bp.wrap(iw, 9999)
        self._cache = (hp, hh, bp, bh)
        self.height = hh + bh + 2 * pad + 6

    def wrap(self, aw, ah):
        self._build()
        return self.width, self.height

    def draw(self):
        self._build()
        hp, hh, bp, bh = self._cache
        pad = 8
        self.canv.saveState()
        self.canv.setFillColor(self.bg)
        self.canv.setStrokeColor(self.bord)
        self.canv.setLineWidth(0.8)
        self.canv.roundRect(0, 0, self.width, self.height, 3, fill=1, stroke=1)
        self.canv.setFillColor(self.bord)
        self.canv.rect(0, 0, 3, self.height, fill=1, stroke=0)
        self.canv.restoreState()
        bp.drawOn(self.canv, 12, pad)
        hp.drawOn(self.canv, 12, pad + bh + 4)

def CalloutBox(heading, text, style='neutral'):
    bg   = C_BULL_BG   if style == 'bull' else (C_BEAR_BG   if style == 'bear' else C_BOX_BG)
    bord = C_BULL_BORD if style == 'bull' else (C_BEAR_BORD if style == 'bear' else C_BOX_BORD)
    return Box(heading, text, bg, bord)

def UpdateBanner(text):
    return Box(f'UPDATE {EM} 15 MAY 2026', text, C_UPD_BG, C_UPD_BORD)

HEADER_TEXT = f'DEAL IMPACT NOTE   CRCL {MUL} HYPE   UPDATED 15 MAY 2026   FOR FRENS AND FAMILIE ONLY'
FOOTER_TEXT = 'For frens and familie only.   Updated 15 MAY 2026.'

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(C_RULE)
    canvas.setLineWidth(0.4)
    canvas.line(L_MARGIN, PAGE_H - T_MARGIN + 6, PAGE_W - R_MARGIN, PAGE_H - T_MARGIN + 6)
    canvas.setFont('Helvetica', 6.5)
    canvas.setFillColor(C_LIGHT)
    canvas.drawRightString(PAGE_W - R_MARGIN, PAGE_H - T_MARGIN + 9, HEADER_TEXT)
    canvas.line(L_MARGIN, B_MARGIN - 4, PAGE_W - R_MARGIN, B_MARGIN - 4)
    canvas.drawCentredString(PAGE_W / 2, B_MARGIN - 14, FOOTER_TEXT)
    canvas.drawRightString(PAGE_W - R_MARGIN, B_MARGIN - 14, f'Page {doc.page}')
    canvas.restoreState()

def trade_table(rows):
    data = [[Paragraph(f'<b>{r[0]}</b>', ST['table_cell']),
             Paragraph(bold_tickers(r[1]),  ST['table_cell'])] for r in rows]
    t = Table(data, colWidths=[1.1 * inch, CONTENT_W - 1.1 * inch])
    t.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_WHITE, C_SHADE]),
        ('GRID',           (0, 0), (-1, -1), 0.5, C_RULE),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',     (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 6),
    ]))
    return t

def build_story():
    story = []
    sp = lambda n=1: Spacer(1, n * 5)

    story.append(P(f'DEAL IMPACT NOTE   CRCL {MUL} HYPE   '
                   f'UPDATED 15 MAY 2026   FOR FRENS AND FAMILIE ONLY',
                   'stamp', bold_t=False))
    story.append(sp(2))
    story.append(P(f'<b>Circle (CRCL) {MUL} Hyperliquid (HYPE) {EM} '
                   f'Partnership Impact Analysis</b>', 'title', bold_t=False))
    story.append(P(f'Two-stage deal reshapes stablecoin infrastructure for '
                   f'on-chain derivatives {EM} UPDATED: AQAv2 split confirmed, '
                   f'CRCL revenue impact inverted', 'subtitle', bold_t=False))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.2, color=C_DARK, spaceAfter=0))
    story.append(sp(2))

    story.append(UpdateBanner(
        'AQAv2 revenue split confirmed at 90% to Hyperliquid / 10% to Coinbase. '
        f'Circle{RSQ}s net revenue from the $5B Hyperliquid USDC pool is effectively zero. '
        'What was a projected ~$200M/year revenue tailwind for CRCL is now a ~$200M/year '
        'revenue hole vs. the pre-deal baseline. '
        'CRCL positioning downgraded to monitoring only. '
        'See updated sections 03, 05, and 06.'))
    story.append(sp(3))

    # 01
    story += section_header(1, 'Deal Summary')
    story.append(P(
        f'<b>Stage 1 {EM} September 16, 2025 (Circle-led):</b> Circle launched '
        f'native USDC on HyperEVM (Hyperliquid{RSQ}s EVM smart contract layer), '
        'integrated CCTP V2 cross-chain transfers across 12+ chains, acquired '
        '~80,000 HYPE tokens (~$4.6M at ~$58/HYPE), and announced evaluation of a '
        'Hyperliquid validator position. HyperCore CCTP V2 support flagged as "coming in weeks."'))
    story.append(P(
        f'<b>Stage 2 {EM} May 13{EM}14, 2026 (Coinbase-led, Circle-adjacent):</b> '
        f'Coinbase named as Hyperliquid{RSQ}s official USDC treasury deployer under the '
        f'AQAv2 framework. Hyperliquid{RSQ}s native stablecoin USDH {EM} launched '
        f'~October 2025 {EM} was sunset after seven months; Coinbase purchased the '
        'USDH brand assets. <b>AQAv2 revenue split now confirmed: Hyperliquid '
        'receives 90% of reserve yield (~$180M/year at current supply); '
        f'Coinbase retains 10% (~$20M/year). Circle{RSQ}s net from this pool: ~$0.</b> '
        'USDC supply on Hyperliquid: ~$5B.'))
    story.append(P(
        '<b>The combined effect:</b> USDC is now the structurally locked quote '
        'currency of the largest perp DEX by volume, and the platform generating '
        f'that volume captures the reserve yield. For HYPE this is a fundamental '
        f'step-change. For CRCL the deal preserves supply dominance at the cost '
        'of surrendering the economics.'))

    # 02
    story += section_header(2, 'Context: What Existed Before')
    story.append(P(
        f'USDC was already Hyperliquid{RSQ}s dominant collateral from launch in 2023. '
        'At the time of the September 2025 announcement, approximately 7% of all '
        f'USDC supply (~$5.3{EM}5.5B) resided on Hyperliquid via Arbitrum bridge. '
        'The pre-deal arrangement carried material bridge risk and was entirely '
        f'uncompensated for the platform. Native issuance eliminates the bridge. '
        f'Circle was formalising a position it already held {EM} but the '
        'AQAv2 economics confirm it did so by agreeing to cede the yield.'))
    story.append(sp(2))

    if os.path.exists(CHART):
        story.append(Image(CHART, width=CONTENT_W, height=CONTENT_W * 0.393))
        story.append(P(f'Fig. 1 {EM} USDC supply on Hyperliquid and HYPE token '
                       'price around key partnership events', 'caption', bold_t=False))
    story.append(sp(1))

    # 03
    story += section_header(3, 'Circle (CRCL): Impact Analysis')

    story.append(P('<b>Business context</b>', 'label'))
    story.append(P(
        f'CRCL IPO{RSQ}d June 5, 2025 at $31; surged to an all-time high of ~$299 '
        'on June 23, 2025. Currently trading ~$123.65 (as of May 12, 2026), ~59% '
        'off the all-time high. FY2025 revenue: $2.7B (+64% YoY). Q1 2026 revenue: '
        '$694M (+20% QoQ); net profit down ~15% QoQ '
        f'(<i>Directional estimate, pending Circle{RSQ}s own Q1 release</i>). '
        'USDC circulating supply: ~$75.3B end-2025, ~$77B Q1 2026.'))

    story.append(P(f'<b>Revenue impact {EM} AQAv2 split confirmed (BEARISH)</b>', 'label'))
    story.append(P(
        'With the 90/10 split now confirmed, the revenue arithmetic is clear. '
        f'Circle{RSQ}s gross yield on $5B at ~4% = ~$200M/year. '
        'Under AQAv2: Hyperliquid receives $180M (90%), Coinbase retains $20M (10%). '
        f'<b>Circle{RSQ}s net revenue from the Hyperliquid pool: ~$0.</b> '
        f'What was presented as a ~7{EM}8% revenue tailwind on FY2025 revenue '
        f'is now a ~7{EM}8% revenue hole vs. the pre-AQAv2 baseline. '
        f'The Hyperliquid revenue uplift narrative for CRCL is fully inverted. '
        f'Note: under Circle{RSQ}s standard distribution model, Coinbase already '
        'received a substantial share of USDC reserve income as a distribution fee '
        f'(historically ~50%+). AQAv2 layers the Hyperliquid yield-share '
        f'on top of {EM} or in replacement of {EM} that existing arrangement. '
        'Either way, Circle nets approximately zero on this pool.'))

    story.append(P('<b>Coinbase: distribution partner turned yield competitor</b>', 'label'))
    story.append(P(
        f'The AQAv2 structure reveals Coinbase{RSQ}s willingness to deploy USDC '
        f'yield to win venue distribution deals at Circle{RSQ}s direct expense. '
        f'Coinbase is not merely a pipeline for USDC {EM} it is actively '
        'structuring yield-share arrangements that strip Circle of the economics '
        'on the supply it issues. <b>If this template extends to other large USDC '
        f'venues, Circle{RSQ}s effective yield on its total supply pool compresses '
        'systemically.</b> This is the single most important structural risk '
        'to the CRCL investment case that was not visible before May 15, 2026.'))

    story.append(P('<b>Competitive positioning vs. Tether (unchanged)</b>', 'label'))
    story.append(P(
        f'USDC market cap grew 73% in 2025 to ~$75B; USDT grew 36% to ~$186B. '
        f'USDC is gaining share in supply terms but Tether still holds ~2.5{MUL} '
        f'the total market. USDC has overtaken USDT in adjusted trading volume {EM} '
        '<i>Single source:</i> Circle now accounts for ~64% of stablecoin trading '
        'volume (eand.co, 2026). The Hyperliquid lock-in forecloses Tether from the '
        'highest-velocity trading venue in DeFi. Regulatory tailwinds (MiCA, GENIUS Act) '
        f'remain favourable for Circle. '
        'This supply-growth story is now the <b>only remaining bull leg for CRCL '
        f'from this partnership</b> {EM} the yield economics have transferred entirely to Hyperliquid.'))

    story.append(P('<b>Defensive motivation: confirmed and costly</b>', 'label'))
    story.append(P(
        'The September 2025 deal timeline (Circle native launch Sep 16; USDH '
        f'launch ~Oct 2025) makes the defensive motivation explicit in retrospect. '
        f'Circle moved to protect ~$5.3B of supply from USDH displacement {EM} '
        'and succeeded. USDH is dead. But the cost was agreeing to a 90/10 '
        f'yield-share that leaves Circle with zero net income from the pool it was defending. '
        f'Circle kept the supply metric; Hyperliquid captured the cash flow.'))

    story.append(P('<b>HYPE token position</b>', 'label'))
    story.append(P(
        f'Circle{RSQ}s ~80,000 HYPE purchased at ~$58 is now worth ~$3.1M at the '
        f'current price of ~$39 {EM} underwater by ~33%. Not material to '
        f'CRCL balance sheet but directionally negative for the "ecosystem alignment" narrative.'))

    story.append(sp(1))
    story.append(KeepTogether([
        CalloutBox(
            f'Bull Case {EM} CRCL',
            'USDC supply growth is the remaining thesis. The Hyperliquid supply '
            'lock-in forecloses Tether from the largest perp DEX. If USDC total '
            'supply accelerates to $100B+ on the back of regulatory tailwinds '
            f'(GENIUS Act, MiCA) and non-Coinbase venue expansion, Circle{RSQ}s '
            'reserve income grows on a wider base that is not subject to AQAv2-style '
            'yield-sharing. The supply story is real; the Hyperliquid economics are not.',
            'bull'),
        sp(2),
        CalloutBox(
            f'Bear Case {EM} CRCL (STRENGTHENED)',
            f'The 90/10 split confirms the worst-case scenario from the prior note. '
            f'Circle nets ~$0 from a $5B pool that previously generated ~$200M/year. '
            'Coinbase is now structurally positioned as a yield intermediary that '
            'can offer similar arrangements to other high-volume venues. '
            f'If even 20{EM}30% of USDC supply ends up under AQAv2-style structures, '
            f'Circle{RSQ}s effective yield on total supply compresses by 100{EM}200bps. '
            f'Q1 2026 net profit is already down ~15% QoQ. JPMorgan{RSQ}s $155 '
            f'Overweight was set before this split was confirmed {EM} a downward '
            f'revision is likely. Oppenheimer{RSQ}s Neutral looks prescient.',
            'bear'),
    ]))
    story.append(sp(1))

    # 04
    story += section_header(4, 'Hyperliquid (HYPE): Impact Analysis')

    story.append(P('<b>Business context</b>', 'label'))
    story.append(P(
        'HYPE token price ~$39.08 (May 14, 2026), market cap ~$9.32B (rank #15), '
        f'fully diluted valuation ~$37.5B. All-time high: $59.37 on September 18, 2025 {EM} '
        'two days after the Circle announcement. Bridge TVL ~$4.9B. '
        f'FY2025 protocol revenue: $844M. Annual perp trading volume: ~$2.9T. '
        f'Open interest: ~$8.9{EM}9.6B.'))

    story.append(P('<b>What the deal structurally delivers</b>', 'label'))
    story.append(P(
        '<b>Eliminated bridge risk:</b> Prior USDC was bridged via Arbitrum. '
        'Smart contract exploit risk on a bridge holding $5B is existential '
        'for a trading platform. Native issuance removes that tail risk.'))
    story.append(P(
        '<b>Capital efficiency on-ramps:</b> CCTP V2 enables direct USDC '
        'transfers from 12+ chains without wrapping or DEX routing. '
        'Lower friction for institutional and retail entrants.'))
    story.append(P(
        f'<b>Protocol-level yield via AQAv2 {EM} now confirmed at 90%:</b> '
        f'Hyperliquid{RSQ}s $5B USDC pool was previously inert from the '
        f'protocol{RSQ}s perspective. Under AQAv2, Hyperliquid receives 90% of '
        'reserve yield: <b>~$180M/year at current supply and rates</b>. '
        'Against FY2025 protocol revenue of $844M, this is a <b>~21% confirmed revenue uplift</b>. '
        f'If USDC supply on-platform grows toward $8{EM}10B, '
        f'the yield-share contribution reaches $290{EM}360M/year {EM} '
        f'a 34{EM}43% uplift on the FY2025 base. '
        f'This is the most consequential confirmed change in HYPE{RSQ}s fundamental valuation case.'))
    story.append(P(
        f'<b>USDH sunset removes execution risk:</b> USDH{RSQ}s closure eliminates '
        'the operational and regulatory overhead of running a competing stablecoin. '
        'The AQAv2 yield-share achieves the same economic goal without that overhead.'))

    story.append(sp(1))
    story.append(KeepTogether([
        CalloutBox(
            f'Bull Case {EM} HYPE (STRENGTHENED)',
            f'AQAv2 yield-share is now confirmed at ~$180M/year incremental revenue {EM} '
            'a 21% uplift on $844M FY2025 base, with further upside as USDC supply grows. '
            'The 21Shares HYPE spot ETF listed May 13, 2026 creates a regulated institutional vehicle. '
            f'HYPE at $39 is ~34% below its all-time high with a materially stronger fundamental '
            'profile than at that high. The confirmed economics justify a position size increase '
            'vs. the prior monitoring stance.',
            'bull'),
        sp(2),
        CalloutBox(
            f'Bear Case {EM} HYPE',
            'Perp DEX market share erosion is real: Aster holds ~20% and is growing. '
            'A sustained decline from 73% to sub-40% would compress the trading revenue base '
            f'that supports HYPE{RSQ}s ~$37.5B FDV. AQAv2 also introduces Coinbase counterparty '
            'and regulatory concentration risk. If U.S. regulators challenge the yield-share '
            'structure as unregistered securities activity, the model unwinds.',
            'bear'),
    ]))
    story.append(sp(1))

    # 05
    story += section_header(5, 'Force-Ranked Impact Assessment')

    header = [
        Paragraph('<b>#</b>',                 ST['table_head']),
        Paragraph('<b>IMPACT</b>',            ST['table_head']),
        Paragraph('<b>BENEFICIARY</b>',       ST['table_head']),
        Paragraph('<b>KEY JUSTIFICATION</b>', ST['table_head']),
        Paragraph('<b>FAILURE CONDITION</b>', ST['table_head']),
    ]
    rows_data = [
        ('1', 'AQAv2 yield-share (confirmed 90%)', 'HYPE',
         f'~$180M/year confirmed incremental revenue vs. $844M FY2025 base = 21% uplift; '
         f'grows to 34{EM}43% if USDC supply reaches $8{EM}10B',
         'Regulatory challenge to yield-sharing structure'),
        ('2', 'Tether displacement', 'CRCL',
         'Hyperliquid is now a closed USDC ecosystem; Tether cannot compete without '
         'native issuance at this venue',
         'Competitor chain with USDT integration captures DEX share from Hyperliquid'),
        ('3', 'Bridge risk removal', 'HYPE',
         'Tail risk of $5B bridge exploit eliminated; institutional adoption barrier lowered',
         'Smart contract exploit on HyperEVM itself'),
        ('4', f'CRCL revenue {EM} INVERTED (headwind)', 'CRCL (negative)',
         f'90/10 confirmed: Circle nets ~$0 from the $5B pool. '
         f'Prior ~$200M/year tailwind is now a ~$200M/year hole vs. pre-deal baseline. '
         f'JPMorgan $155 target set before split confirmed {EM} revision likely.',
         'Circle discloses offsetting revenue in Q1 earnings'),
        ('5', 'Institutional legitimacy', 'HYPE',
         'Circle stake + 21Shares HYPE ETF = regulated institutional on-ramps now exist',
         'No major institutional flow materialises post-ETF launch'),
    ]

    tc = ST['table_cell']
    tbl_data = [header]
    for r in rows_data:
        tbl_data.append([Paragraph(bold_tickers(x), tc) for x in r])

    col_w = [0.25 * inch, 1.35 * inch, 0.85 * inch, 2.2 * inch, 2.05 * inch]
    tbl = Table(tbl_data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0), C_HDR_BG),
        ('TEXTCOLOR',      (0, 0), (-1, 0), C_WHITE),
        ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1, 0), 7.5),
        ('LEADING',        (0, 0), (-1, 0), 10),
        ('GRID',           (0, 0), (-1, -1), 0.5, C_RULE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_SHADE]),
        ('BACKGROUND',     (0, 4), (-1, 4), colors.HexColor('#FFF0F0')),
        ('TOPPADDING',     (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 6),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(tbl)
    story.append(sp(2))

    # 06
    story += section_header(6, 'Tradeable Expression')

    story.append(P(f'<b>CRCL {EM} DOWNGRADED TO MONITORING POSITION</b>', 'label'))
    crcl_rows = [
        ('Status',
         'DOWNGRADED. Prior 3-4% of book recommendation was based on Hyperliquid '
         'as a revenue tailwind. That leg is gone. The position is now a '
         'supply-growth monitoring play only.'),
        ('Entry trigger',
         '(1) Circle Q1 2026 earnings release explicitly quantifies AQAv2 revenue '
         'impact and demonstrates an offsetting revenue source. '
         '(2) USDC total supply crosses $90B on non-Coinbase venues. '
         '(3) JPMorgan issues revised target incorporating the 90/10 split and maintains Overweight.'),
        ('Sizing',
         'Reduce to 1-2% of book (monitoring only). Do not add until Q1 2026 '
         f'earnings confirm how AQAv2 is accounted for in Circle{RSQ}s revenue line. '
         'If AQAv2 is absorbed into distribution costs without explicit disclosure, '
         'treat that as a red flag.'),
        ('Hedge',
         f'Short Coinbase (COIN) as a partial offset {EM} COIN is the direct '
         'beneficiary of the 10% AQAv2 retention and the treasury deployer role.'),
        ('Horizon', '3-6 months to earnings clarity. Do not extend horizon until revenue structure is confirmed.'),
        ('Exit',
         'Close entirely if: (1) additional venues adopt AQAv2-style 90/10 arrangements, '
         'or (2) Q1 2026 earnings show no disclosure of AQAv2 impact.'),
    ]
    story.append(trade_table(crcl_rows))
    story.append(sp(2))

    story.append(P(f'<b>HYPE {EM} INCREASE TO CORE POSITION</b>', 'label'))
    hype_rows = [
        ('Status',
         'UPGRADED. AQAv2 at 90% is confirmed, not directional. '
         'The fundamental revenue uplift is real and quantifiable.'),
        ('Entry trigger',
         f'(1) AQAv2 yield-share mechanics confirmed {EM} DONE. '
         '(2) USDC on Hyperliquid growing toward $7B. '
         '(3) Perp DEX market share sustaining above 50%.'),
        ('Sizing',
         'Increase from prior 2-3% to 4-5% of book at current levels. '
         'Add to 6-7% on USDC supply growth toward $7B on-platform. '
         'Use 21Shares HYPE ETF for regulated sizing; confirm AUM >$50M before relying on ETF liquidity.'),
        ('Vehicle',
         f'Spot HYPE direct or via 21Shares HYPE spot ETF (listed May 13, 2026). '
         f'ETF first-day volume ~$1.8M {EM} monitor AUM trajectory.'),
        ('Horizon', '9-12 months. The yield-share compounds as USDC supply grows.'),
        ('Exit',
         'Close if perp DEX share falls below 40%, or if AQAv2 structure is challenged '
         'by U.S. regulators, or if Coinbase terminates the treasury deployer arrangement.'),
    ]
    story.append(trade_table(hype_rows))
    story.append(sp(2))

    # 07
    story += section_header(7, 'What to Monitor')

    monitor_items = [
        ('CRCL Q1 2026 EARNINGS',
         f'Circle{RSQ}s official Q1 2026 release {EM} confirm whether AQAv2 impact '
         'is disclosed explicitly or absorbed into distribution costs. '
         'No disclosure = significant red flag for CRCL.'),
        ('COINBASE AQAv2 TEMPLATE',
         'Watch for Coinbase offering similar 90/10 yield-share arrangements '
         'to other large USDC venues (Bybit, OKX on-chain, GMX). '
         'Each new venue under this model is a further Circle margin headwind.'),
        ('USDC ON-PLATFORM SUPPLY',
         f'DefiLlama / Hyperliquid dashboard {EM} $5B to $7B+ milestone '
         f'directly increases HYPE{RSQ}s AQAv2 yield-share revenue by ~$80M/year per additional $2B.'),
        ('PERP DEX MARKET SHARE',
         f'Coingecko / DefiLlama derivatives {EM} Aster at ~20% and growing. '
         'Watch for Hyperliquid sustaining >50% share. Sub-40% would materially impair the HYPE thesis.'),
        ('JPMORGAN CRCL TARGET REVISION',
         f'JPMorgan $155 OW cited Hyperliquid as a named positive and was set before the 90/10 split. '
         f'A revision toward $110{EM}120 would confirm the market has repriced the revenue loss.'),
        ('HYPE ETF AUM GROWTH',
         f'21Shares HYPE spot ETF (listed May 13, 2026) {EM} weekly AUM; '
         '>$100M signals genuine institutional adoption.'),
        ('CIRCLE VALIDATOR STATUS',
         f'Hyperliquid validator set {EM} confirm whether Circle has completed '
         'validator onboarding. Relevant for HYPE decentralisation narrative.'),
        ('GENIUS ACT PROGRESS',
         f'U.S. stablecoin legislation {EM} passage formally advantages Circle '
         'over Tether; supports the supply-growth leg of the CRCL bull case.'),
    ]

    mon_data = [[
        Paragraph(f'<b>{it[0]}</b>', ST['table_cell']),
        Paragraph(bold_tickers(it[1]), ST['table_cell'])
    ] for it in monitor_items]

    mon_tbl = Table(mon_data, colWidths=[1.7 * inch, CONTENT_W - 1.7 * inch])
    mon_tbl.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_WHITE, C_SHADE]),
        ('GRID',    (0, 0), (-1, -1), 0.5, C_RULE),
        ('VALIGN',  (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
    ]))
    story.append(mon_tbl)
    story.append(sp(2))

    # 08
    story += section_header(8, 'Time-Sensitive Flags & Low-Confidence Caveats')

    flags = [
        (f'<b>AQAv2 REVENUE SPLIT [CONFIRMED {EM} BEARISH FOR CRCL]:</b> '
         'Split confirmed at 90% to Hyperliquid / 10% to Coinbase (May 15, 2026). '
         f'Circle{RSQ}s net revenue from the $5B Hyperliquid USDC pool is ~$0. '
         f'Prior analysis treated this as a ~$200M revenue tailwind; it is a ~$200M revenue hole. '
         f'JPMorgan $155 OW target cited Hyperliquid as a positive and was set before this split {EM} '
         'a downward revision is likely.'),
        ('<b>COINBASE PRECEDENT RISK [NEW]:</b> '
         f'AQAv2 reveals Coinbase{RSQ}s willingness to deploy USDC yield '
         f'to win venue deals at Circle{RSQ}s direct expense. '
         'If this template extends to other large venues, '
         f'Circle{RSQ}s effective yield on total supply compresses systemically. '
         'This is a structural risk, not a one-off event.'),
        (f'<b>CIRCLE Q1 2026 NET PROFIT [{EM}15% QoQ {EM} DIRECTIONAL]:</b> '
         'Sourced from a single Italian crypto publication (Spaziocrypto). '
         'Treat as directional only. If confirmed at Q1 earnings, combined with the AQAv2 revenue '
         'loss, the CRCL margin compression narrative accelerates materially.'),
        ('<b>DEFENSIVE MOTIVATION [NOW CONFIRMED]:</b> '
         f'Circle{RSQ}s September 2025 deal was defensive against USDH {EM} now confirmed by outcome. '
         'Circle protected its supply position but ceded the economics. '
         'This is now established fact, not analytical framing.'),
        ('<b>USDC ADJUSTED VOLUME 64% SHARE [SINGLE SOURCE]:</b> '
         'Appears in a single source (eand.co, 2026). '
         'The directional trend is multi-source confirmed; the specific percentage is not.'),
        ('<b>CIRCLE VALIDATOR STATUS [UNFOUND]:</b> '
         'As of September 2025, Circle was "evaluating" becoming a Hyperliquid validator. '
         'No subsequent confirmation found.'),
    ]

    for f in flags:
        story.append(P(f'{BUL}  {f}', 'flag'))

    story.append(sp(4))
    story.append(HRFlowable(width=CONTENT_W, thickness=0.4, color=C_RULE, spaceAfter=6))
    story.append(P(
        '<i>For frens and familie only. '
        'All views represent forward-looking estimates subject to material revision. '
        'Updated 15 MAY 2026.</i>',
        'body', bold_t=False))

    return story

doc = SimpleDocTemplate(
    OUTPUT, pagesize=A4,
    leftMargin=L_MARGIN, rightMargin=R_MARGIN,
    topMargin=T_MARGIN,  bottomMargin=B_MARGIN,
    title=f'Circle {MUL} Hyperliquid {EM} Deal Impact Note (Updated)',
    author='frens',
    subject='CRCL x HYPE Partnership Analysis',
)
doc.build(build_story(), onFirstPage=on_page, onLaterPages=on_page)
print(f'PDF saved: {OUTPUT}')
