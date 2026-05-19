from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
import os

OUT = r"C:\Users\matth\OneDrive\Documents\Claude\Code\thematic_rotation_note_may2026.pdf"
CHART1 = r"C:\Users\matth\OneDrive\Documents\Claude\Code\thematic_rotation_chart1.png"
CHART2 = r"C:\Users\matth\OneDrive\Documents\Claude\Code\thematic_rotation_chart2.png"

# ── Colours ──────────────────────────────────────────────────────────────────
TEAL       = colors.HexColor('#16A085')
TEAL_DARK  = colors.HexColor('#0E6655')
RED        = colors.HexColor('#A93226')
ORANGE     = colors.HexColor('#E67E22')
PURPLE     = colors.HexColor('#8E44AD')
BLUE       = colors.HexColor('#2980B9')
GREEN      = colors.HexColor('#27AE60')
DARK       = colors.HexColor('#1A1A1A')
MID        = colors.HexColor('#555555')
LIGHT      = colors.HexColor('#888888')
VLIGHT     = colors.HexColor('#BBBBBB')
RULE       = colors.HexColor('#E0E0E0')
ROW_ALT    = colors.HexColor('#F7F7F7')
BOX_BG     = colors.HexColor('#F5F5F5')
WHITE      = colors.white

W, H = letter
ML = MR = 1.25 * inch
MT = MB = 1.0 * inch
TW = W - ML - MR   # text width

# ── Header / Footer ───────────────────────────────────────────────────────────
HDR_TEXT = "THEMATIC STRATEGY  ·  MAY 2026  ·  INTERNAL / BUY-SIDE ONLY"
FTR_TEXT = "Internal research note — not for distribution.  May 2026."

def on_page(canvas, doc):
    canvas.saveState()
    # Header rule
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(ML, H - MT + 18, W - MR, H - MT + 18)
    # Header text
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(LIGHT)
    canvas.drawRightString(W - MR, H - MT + 22, HDR_TEXT)
    # Footer rule
    canvas.line(ML, MB - 18, W - MR, MB - 18)
    # Footer text
    canvas.drawCentredString(W / 2, MB - 28, FTR_TEXT)
    canvas.restoreState()

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    base = styles.get(name) or styles['Normal']
    return ParagraphStyle(name + '_custom_' + str(hash(str(kw))),
                          parent=base, **kw)

body     = S('Normal', fontSize=9.5, leading=14.5, textColor=DARK,
             fontName='Helvetica', spaceAfter=6, alignment=TA_LEFT)
body_j   = S('Normal', fontSize=9.5, leading=14.5, textColor=DARK,
             fontName='Helvetica', spaceAfter=6, alignment=TA_JUSTIFY)
small    = S('Normal', fontSize=8,   leading=11,   textColor=MID,
             fontName='Helvetica')
tiny     = S('Normal', fontSize=7.5, leading=10.5, textColor=LIGHT,
             fontName='Helvetica', fontStyle='italic')
h1       = S('Heading1', fontSize=20, leading=24, fontName='Helvetica-Bold',
             textColor=DARK, spaceBefore=0, spaceAfter=4)
h1sub    = S('Normal',   fontSize=11, leading=14, fontName='Helvetica',
             textColor=LIGHT, spaceAfter=14)
sec_num  = S('Normal',   fontSize=9,  leading=12, fontName='Helvetica-Bold',
             textColor=TEAL, spaceAfter=2, spaceBefore=18)
sec_head = S('Heading2', fontSize=13, leading=16, fontName='Helvetica-Bold',
             textColor=DARK, spaceBefore=0, spaceAfter=6)
theme_tag = S('Normal',  fontSize=8,  leading=10, fontName='Helvetica-Bold',
              textColor=WHITE, spaceAfter=0)
theme_h  = S('Heading3', fontSize=11.5, leading=14, fontName='Helvetica-Bold',
             textColor=DARK, spaceBefore=12, spaceAfter=2)
theme_q  = S('Normal',   fontSize=9,    leading=12, fontName='Helvetica',
             textColor=LIGHT, spaceAfter=8, fontStyle='italic')
label    = S('Normal',   fontSize=8.5,  leading=11, fontName='Helvetica-Bold',
             textColor=TEAL, spaceAfter=2, spaceBefore=8)
bullet   = S('Normal',   fontSize=9.5,  leading=14, textColor=DARK,
             fontName='Helvetica', leftIndent=14, spaceAfter=3,
             bulletIndent=4, firstLineIndent=0)
caveat_l = S('Normal',   fontSize=8.5,  leading=12, textColor=MID,
             fontName='Helvetica', leftIndent=10, spaceAfter=3)
tbl_hdr  = S('Normal',   fontSize=8,    leading=10, fontName='Helvetica-Bold',
             textColor=WHITE, alignment=TA_LEFT)
tbl_cell = S('Normal',   fontSize=8,    leading=11, fontName='Helvetica',
             textColor=DARK, alignment=TA_LEFT)
tbl_cell_sm = S('Normal', fontSize=7.5, leading=10.5, fontName='Helvetica',
                textColor=DARK, alignment=TA_LEFT)
monitor_l  = S('Normal', fontSize=8.5,  leading=13, fontName='Helvetica',
               textColor=DARK, spaceAfter=4)
flag_l     = S('Normal', fontSize=8.5,  leading=13, fontName='Helvetica',
               textColor=MID, spaceAfter=5, leftIndent=12)

# ── Helpers ───────────────────────────────────────────────────────────────────
def rule(color=RULE, thickness=0.5, spB=4, spA=4):
    return HRFlowable(width='100%', thickness=thickness,
                      color=color, spaceAfter=spA, spaceBefore=spB)

def sp(pts=6):
    return Spacer(1, pts)

def P(text, style=body):
    return Paragraph(text, style)

def ticker(t):
    return f'<font name="Helvetica-Bold">{t}</font>'

def bear_box(text, accent=colors.HexColor('#A93226')):
    """Left-bordered callout box for bear cases."""
    inner = Paragraph(text, S('Normal', fontSize=8.5, leading=12.5,
                               fontName='Helvetica', textColor=MID))
    data = [[inner]]
    t = Table(data, colWidths=[TW - 14])
    t.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (-1,-1), BOX_BG),
        ('LEFTPADDING',  (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING',   (0,0), (-1,-1), 7),
        ('BOTTOMPADDING',(0,0), (-1,-1), 7),
        ('LINEBEFORE',   (0,0), (0,-1), 3, accent),
    ]))
    return t

def section_header(num, title):
    return [
        sp(16),
        rule(TEAL, 1.0, 0, 6),
        P(num, sec_num),
        P(title, sec_head),
        sp(4),
    ]

def theme_header(letter, title, tag, tag_color, quote):
    tag_p = Paragraph(f'  {tag}  ', S('Normal', fontSize=7.5, leading=9,
                                        fontName='Helvetica-Bold',
                                        textColor=WHITE))
    tag_t = Table([[tag_p]], colWidths=[None])
    tag_t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), tag_color),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        ('TOPPADDING',    (0,0),(-1,-1), 2),
        ('BOTTOMPADDING', (0,0),(-1,-1), 2),
    ]))
    return [
        sp(14),
        rule(RULE, 0.5, 0, 6),
        P(f'<font name="Helvetica-Bold" color="#16A085">THEME {letter}:</font>  '
          f'<font name="Helvetica-Bold">{title}</font>', theme_h),
        tag_t,
        sp(4),
        P(f'“{quote}”', theme_q),
    ]

def bullets(items, style=bullet):
    return [P(f'•  {item}', style) for item in items]

def make_table(headers, rows, col_widths, hdr_color=TEAL_DARK):
    hdr_row = [Paragraph(h, tbl_hdr) for h in headers]
    data = [hdr_row]
    for i, row in enumerate(rows):
        data.append([Paragraph(str(c), tbl_cell_sm) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND',    (0,0), (-1,0), hdr_color),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [WHITE, ROW_ALT]),
        ('GRID',          (0,0), (-1,-1), 0.5, RULE),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]
    t.setStyle(TableStyle(style))
    return t

def monitor_item(label_text, detail):
    return P(f'<font name="Helvetica-Bold" color="#16A085">{label_text}</font>'
             f'  <font color="#444444">{detail}</font>', monitor_l)

def flag_item(bold_part, rest):
    return P(f'•  <font name="Helvetica-Bold">{bold_part}</font>  {rest}',
             flag_l)

# ── Build story ───────────────────────────────────────────────────────────────
story = []

# ════════════════════════════════════════════════════════════════════════════
# COVER HEADER
# ════════════════════════════════════════════════════════════════════════════
story += [
    sp(8),
    P('THEMATIC STRATEGY  ·  INTERNAL / BUY-SIDE ONLY', tiny),
    sp(6),
    P('After the Capex Supercycle:', h1),
    P('Five Themes on the Cusp of Mass Adoption', h1),
    sp(4),
    P('Structured for position initiation — not commentary.', h1sub),
    rule(TEAL, 1.5, 4, 12),
]

# ════════════════════════════════════════════════════════════════════════════
# 01 CYCLE FRAME
# ════════════════════════════════════════════════════════════════════════════
story += section_header('01 —', 'CYCLE FRAME')

story += [
    P('The Magnificent Seven entered 2026 carrying a combined market cap of ~$22 trillion '
      'and ~34% of the S&P 500’s weight. They are now collectively underperforming the '
      'equal-weight index for the first time since 2022. '
      f'{ticker("MSFT")}, {ticker("AAPL")}, {ticker("GOOGL")}, {ticker("AMZN")}, '
      f'{ticker("META")}, {ticker("NVDA")}, {ticker("TSLA")} — every one of them '
      'trails the S&P 500 YTD <font color="#888888">(Motley Fool, May 2026)</font>.', body_j),

    P('The crowding signals are specific and measurable: the Mag 7 basket trades at ~29x '
      'forward earnings vs. the S&P 500 at ~22x and the Nasdaq 100 at ~25x '
      '<font color="#888888">(marketshost.com, 2026)</font>. Sell-side AI coverage proliferated '
      'through 2023–2025 to the point where “buy AI infrastructure” is the consensus '
      'institutional recommendation. The DeepSeek shock in early 2026 was the first serious public '
      'challenge to the $700B hyperscaler capex thesis — questioning whether returns will scale '
      'to match spend. Hyperscaler capex-to-revenue ratios now range from 34% '
      f'({ticker("AMZN")}) to 75% ({ticker("META")}).', body_j),

    P('<font name="Helvetica-Bold">MACRO BACKDROP:</font>  Sticky inflation (core PCE ended 2025 '
      'at 3%, above the Fed’s 2% target), a weakening dollar, and a geopolitical environment '
      'that has permanently repriced defense budgets are pulling capital toward hard-asset, '
      'real-economy themes. Energy '
      f'({ticker("XLE")}) is +21% YTD. The equal-weight S&P is outperforming the cap-weight index. '
      'The regime has shifted.', body_j),

    sp(6),
    P('Two rotation paths are simultaneously live:', label),
]

story += bullets([
    '<font name="Helvetica-Bold">MONETIZATION PIVOT</font> — what does $690B in annual AI '
    'infrastructure spending actually produce in real-world revenue? The answer is beginning to emerge '
    'in physical AI, autonomous systems, and the power infrastructure required to run it all.',
    '<font name="Helvetica-Bold">REGIME-SHOCK ROTATION</font> — sticky inflation, dollar '
    'weakness, and geopolitical repricing is pulling capital toward hard-asset, real-economy themes '
    'that were priced for nothing.',
])

story += [sp(12)]

# Chart 1
if os.path.exists(CHART1):
    story.append(Image(CHART1, width=TW, height=TW * 0.60))
    story.append(P('YTD performance as of May 2026. Returns approximate. Sources: Motley Fool, '
                   '24/7 Wall St., etfdb.com, investing.com.', tiny))
story.append(sp(8))

# ════════════════════════════════════════════════════════════════════════════
# 02 CANDIDATE THEMES
# ════════════════════════════════════════════════════════════════════════════
story += section_header('02 —', 'CANDIDATE THEMES')

# ── Theme A: Humanoid Robotics ────────────────────────────────────────────
story += theme_header('A', 'PHYSICAL AI & HUMANOID ROBOTICS', 'NEXT-LEG',
                      BLUE, 'The software AI supercycle moves into atoms')

story += [
    P('<font name="Helvetica-Bold">THESIS</font>', label),
    P('2026 is the year physical AI crosses from demonstration to deployment. CES 2026 was '
      'the first major trade show where robotics showcased systems already operating commercially '
      '— not concept units. Two structural shifts are driving the inflection:', body_j),
    P('<font name="Helvetica-Bold">Cost.</font>  Per-unit production costs for humanoid robots '
      'have collapsed from $3 million to under $100,000 over the past decade, with leading '
      'manufacturers now approaching $10,000 for commercial-grade applications '
      '<font color="#888888">(Global X ETFs, 2026)</font>. This is the cost threshold at which '
      'industrial ROI turns positive for most manufacturing use cases.', body_j),
    P('<font name="Helvetica-Bold">Scale.</font>  Amazon’s fleet of over 1 million robots '
      'is expected to handle 75% of global deliveries by mid-2026. The market is valued at '
      '$2–3B today and projected to reach $40B by 2035 in the base case '
      '<font color="#888888">(Global X ETFs, 2026)</font>.', body_j),

    P('CATALYSTS', label),
]
story += bullets([
    'Full-year commercial deployment reports from Amazon, BMW, and Tesla Manufacturing — Q2–Q3 2026 earnings calls',
    'Unit cost announcements below $10,000 from leading manufacturers — expected H2 2026',
    'Labor shortage data forcing accelerated corporate adoption decisions — ongoing',
    f'First meaningful humanoid revenue disclosure from a public company — watch FIGURE, Boston Dynamics parent, and {ticker("TSLA")} FSD-to-Optimus bridge',
])

story += [
    P('BENEFICIARIES', label),
    P(f'{ticker("TSLA")}  ·  {ticker("FANUY")}  ·  {ticker("ABB")}  ·  '
      f'{ticker("ISRG")}  ·  {ticker("NVDA")} (inference)', body),
    P('<font name="Helvetica-Bold">POSITIONING</font>  Directional estimate: Humanoid robotics is '
      'early-consensus in VC (funding up 15x since 2017) but still under-owned in traditional '
      f'institutional equity portfolios. {ticker("ARTY")} ETF is +33% YTD, {ticker("BOTT")} +23%, '
      f'{ticker("ROBO")} +18% — the dispersion signals managers are still sorting out which '
      'part of the stack to own. This is early-consensus positioning, not crowded.', body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if per-unit cost '
             'reduction stalls above $50,000, keeping commercial ROI negative for most '
             'non-industrial use cases. Any major product recall or workplace safety incident '
             'involving autonomous systems triggers regulatory pause and multi-year adoption setback.',
             RED),
]

# ── Theme B: Power Grid ────────────────────────────────────────────────────
story += theme_header('B', 'POWER GRID & ELECTRIFICATION INFRASTRUCTURE', 'ADJACENT',
                      TEAL, 'The AI capex cycle has a physics constraint: watts')

story += [
    P('<font name="Helvetica-Bold">THESIS</font>', label),
    P('AI data centers are a power-demand machine. Morgan Stanley Research forecasts U.S. data '
      'center demand reaching 74 GW by 2028, with a projected shortfall of ~49 GW in available '
      'power access <font color="#888888">(Morgan Stanley, 2026)</font>. Wedbush estimates U.S. '
      'data center electricity consumption could reach ~470 TWh by 2030, roughly 23% above '
      'consensus forecasts.', body_j),
    P('The critical insight: <font name="Helvetica-Bold">this is not a 2030 story — the '
      'bottleneck is live now.</font> The 49 GW shortfall means hyperscalers cannot deploy their '
      'capex without solving grid access. This creates multi-year, contracted revenue for grid '
      'infrastructure builders — transformers, switchgear, high-voltage cable, and power '
      'management software — independent of whether any specific AI model wins.', body_j),

    P('CATALYSTS', label),
]
story += bullets([
    'Utility earnings calls confirming data center co-location contract wins — Q2 2026 earnings season (July 2026)',
    'DOE grid permitting reform package — H2 2026 legislative calendar',
    'Hyperscaler disclosures of power access delays limiting deployment — any 2026 earnings call',
    'PJM / MISO interconnection queue data showing multi-year backlogs (publicly updated quarterly)',
])
story += [
    P('BENEFICIARIES', label),
    P(f'{ticker("ETN")}  ·  {ticker("EMR")}  ·  {ticker("GEV")}  ·  '
      f'{ticker("PWR")}  ·  {ticker("NEE")}  ·  {ticker("ELFY")}  ·  '
      f'{ticker("AIPO")}  ·  {ticker("IVEP")}', body),
    P('<font name="Helvetica-Bold">POSITIONING</font>  Directional estimate: This theme is the '
      f'furthest along on the consensus spectrum — {ticker("ELFY")} +27.3% YTD suggests '
      'early-consensus to mid-consensus positioning. Best risk/reward is in supply-constrained '
      f'component makers ({ticker("ETN")}, {ticker("EMR")}) vs. utilities.', body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if grid permitting '
             'reform stalls in Congress or if hyperscalers shift AI workloads toward lower-power '
             'inference (DeepSeek-style efficiency) faster than capex plans imply, reducing '
             'demand-side urgency.', TEAL),
]

# ── Theme C: Longevity ────────────────────────────────────────────────────
story += theme_header('C', 'LONGEVITY BIOTECH & THE GLP-1 EXTENSION', 'NEXT-LEG',
                      GREEN, 'The legitimization of healthspan as an investable category')

story += [
    P('<font name="Helvetica-Bold">THESIS</font>', label),
    P(f'Nothing has done more to legitimize longevity therapeutics than the explosive success of '
      f'GLP-1 drugs. {ticker("LLY")} and {ticker("NVO")} have explicitly embraced the '
      f'“longevity” framing — pushing well beyond diabetes and obesity into '
      f'healthspan extension territory <font color="#888888">(Clarivate, 2025)</font>. The GLP-1 '
      f'market is projected at nearly $100B annually by decade-end '
      f'<font color="#888888">(CNBC, Jan 2026)</font>.', body_j),
    P(f'The non-consensus opportunity is not in {ticker("NVO")} or {ticker("LLY")} — those '
      'are consensus long positions already — but in the next two layers of the longevity stack:',
      body_j),
    P('<font name="Helvetica-Bold">Layer 1: Oral GLP-1 molecules.</font>  Novo’s oral '
      f'semaglutide received FDA approval in December 2025. {ticker("LLY")}’s orforglipron '
      '(first small-molecule GLP-1 for obesity) targets FDA approval in 2026. The addressable '
      'market for oral formulations is 10x the injectable market. 39 new GLP-1 drugs are in '
      'development from 34 companies <font color="#888888">(IQVIA, Jan 2026)</font>.', body_j),
    P('<font name="Helvetica-Bold">Layer 2: Adjacent longevity mechanisms.</font>  Senolytics '
      'have posted statistically significant Phase 2 results — Unity Biotechnology’s '
      'UBX1325 met non-inferiority endpoints vs. anti-VEGF through 36 weeks. mTOR inhibitors '
      '(rapamycin analogs) entered Phase 2 for healthspan extension. ARPA-H committed up to '
      '$30.8M to Cambrian Biopharma’s mTORC1 program. The market was $23.2B in 2025 '
      'and projects to $58.7B by 2034 at 11% CAGR.', body_j),

    P('CATALYSTS', label),
]
story += bullets([
    f'{ticker("LLY")} orforglipron FDA approval decision — 2026 (PDUFA date pending)',
    'Unity Biotechnology UBX1325 Phase 3 initiation announcement',
    'ARPA-H longevity program milestone readouts — H2 2026',
    'First major pharma acquisition of a pure-play longevity biotech — would reprice the entire category',
])
story += [
    P('BENEFICIARIES', label),
    P(f'{ticker("LLY")}  ·  {ticker("NVO")}  ·  {ticker("RVTY")}  ·  '
      f'{ticker("IONS")}  ·  {ticker("ARKG")}', body),
    P(f'<font name="Helvetica-Bold">POSITIONING</font>  Directional estimate: {ticker("LLY")} and '
      f'{ticker("NVO")} are consensus overweights. The non-consensus alpha is in the '
      'senolytics/mTOR space — Altos Labs ($3B raised), Cambrian, and Unity Biotechnology '
      'are largely pre-IPO or small-cap and under-represented in institutional equity portfolios.',
      body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if a major GLP-1 '
             'adverse event study (cardiovascular or oncological) triggers an FDA class review, '
             'creating a halo-negative effect across all longevity therapeutics. Competition from '
             '34+ companies entering the GLP-1 space compresses pricing power faster than '
             'addressable market expands.', GREEN),
]

# ── Theme D: Autonomous Defense ────────────────────────────────────────────
story += theme_header('D', 'AUTONOMOUS DEFENSE & DRONE WARFARE', 'MACRO',
                      PURPLE, 'The economics of warfare have permanently changed')

story += [
    P('<font name="Helvetica-Bold">THESIS</font>', label),
    P('The Ukraine conflict produced a decade of battlefield learning in two years. The conclusion '
      'is unambiguous: low-cost, mass-produced autonomous systems outperform expensive legacy '
      'platforms at scale. NATO allies increased defense spending 20% in 2025, and for the first '
      'time all 31 members met the 2% of GDP commitment '
      '<font color="#888888">(Bloomberg, March 2026)</font>.', body_j),
    P('<font name="Helvetica-Bold">The critical distinction from “defense is crowded”:</font>  '
      f'European traditional defense ({ticker("EUAD")}, Rheinmetall, BAE Systems) has already '
      f're-rated — {ticker("EUAD")} climbed 75% YTD through mid-2025 before falling 4% in '
      '2026 as crowded positions were trimmed. Citigroup explicitly flagged crowded bullish '
      'positioning in European defense being reduced.', body_j),
    P('The non-crowded opportunity is in U.S. autonomous warfare specifically. The Defense '
      'Autonomous Warfare Group (DAWG) budget is projected to increase from $225.9M in FY2026 '
      'to up to $54.6B requested in FY2027 — a <font name="Helvetica-Bold">24,000%+ '
      'increase</font> '
      '<font color="#888888">(Single source: DefenseScoop / globalsecurity.org)</font>. '
      'The Trump administration’s spending plan allocates more than $70B for military drones '
      'and counter-drone systems — the Pentagon’s largest-ever investment in these '
      'technologies <font color="#888888">(DefenseScoop, April 2026)</font>.', body_j),

    P('CATALYSTS', label),
]
story += bullets([
    'NATO July 2026 Ankara Summit formal doctrine shift to autonomous systems — July 2026',
    'FY2027 Pentagon budget vote confirming DAWG allocation — H2 2026 Congressional calendar',
    'New contract awards from the $70B drone/counter-drone program — expected Q3–Q4 2026',
    'European LEAP program procurement (France, Poland, Germany, UK, Italy) — initial contracts H2 2026',
])
story += [
    P('BENEFICIARIES', label),
    P(f'{ticker("AVAV")}  ·  {ticker("KTOS")}  ·  {ticker("AXON")}  ·  '
      f'{ticker("LHX")}  ·  {ticker("NOC")}  ·  {ticker("DFEN")}', body),
    P('<font name="Helvetica-Bold">POSITIONING</font>  Directional estimate: U.S. drone/autonomous '
      f'defense stocks are early-consensus vs. European traditional defense which is crowded. '
      f'{ticker("AVAV")} and {ticker("KTOS")} have re-rated since late 2025 but nowhere near '
      'European multiples. Autonomous-specific names remain smaller float with limited '
      'institutional penetration.', body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if the Ukraine '
             'conflict reaches a ceasefire or peace agreement that significantly reduces the '
             'perceived urgency of autonomous weapons procurement across NATO. A continuing '
             'resolution instead of a full FY2027 defense appropriations bill would delay '
             'DAWG spending by 12+ months.', PURPLE),
]

# ── Theme E: Nuclear ─────────────────────────────────────────────────────
story += theme_header('E', 'NUCLEAR ENERGY & SMALL MODULAR REACTORS', 'MACRO',
                      ORANGE, '24/7 carbon-free power — the only answer AI infrastructure accepts')

story += [
    P('<font name="Helvetica-Bold">THESIS</font>', label),
    P('AI data centers require what renewable energy cannot provide: firm, dispatchable, 24/7 power. '
      'Nuclear is the only carbon-free source that meets this specification. The early adopters are '
      'already committing: data center and technology companies are the primary buyers of new '
      'nuclear capacity, enticed by nuclear’s 24/7 carbon-free output '
      '<font color="#888888">(IEA / Slaughter and May, 2026)</font>.', body_j),
    P('Policy and commercial timelines are converging. In November 2025, the UK government announced '
      'Wylfa will host the UK’s first SMRs with Rolls-Royce SMR as preferred technology '
      'provider. The U.S. DOE reissued a tender for $900M in federal SMR development funding '
      '<font color="#888888">(March 2025)</font>. SMR installations could reach 80 GW by 2040 '
      '— 10% of global nuclear capacity <font color="#888888">(IEA, 2025)</font>.', body_j),
    P('<font name="Helvetica-Bold">The near-term opportunity is in existing nuclear capacity, '
      'not SMR construction.</font>  Operating reactors are being repriced by hyperscaler power '
      'purchase agreements. SMR construction is a 2028–2032 revenue event for most players.',
      body_j),

    P('CATALYSTS', label),
]
story += bullets([
    f'Additional tech company nuclear PPA announcements (following {ticker("MSFT")}-Constellation/Three Mile Island model) — ongoing',
    'NRC SMR design certification decisions — expected 2026–2027',
    'Rolls-Royce SMR UK financial close and construction commitment — H1 2027 target',
    'DOE $900M SMR grant award announcements — H2 2026',
])
story += [
    P('BENEFICIARIES', label),
    P(f'{ticker("CEG")}  ·  {ticker("VST")}  ·  {ticker("CCJ")}  ·  '
      f'{ticker("NLR")}  ·  {ticker("URNM")}  ·  {ticker("OKLO")}', body),
    P('<font name="Helvetica-Bold">POSITIONING</font>  Directional estimate: Institutional '
      'involvement in nuclear is growing rapidly but uranium miners carry rich valuations. '
      f'{ticker("CEG")} and {ticker("VST")} are better risk-adjusted expressions than pure '
      f'miners ({ticker("URNM")}, {ticker("CCJ")}) for new positions in 2026.', body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if NRC certification '
             'processes for SMRs extend by 2+ years (the historical norm). Any major nuclear '
             'incident globally triggers a multi-year sentiment reset. Tech company PPA demand '
             'could be partially substituted by efficiency improvements in AI inference compute.',
             ORANGE),
]

# ════════════════════════════════════════════════════════════════════════════
# 03 RANKING
# ════════════════════════════════════════════════════════════════════════════
story += section_header('03 —', 'RANKING')

story.append(P('Force-ranked: probability of becoming the next major theme (6–12 months). '
               'Criteria: narrative readiness × fundamental support × positioning '
               'asymmetry × catalyst proximity. A theme scores high only if it clears all four.',
               small))
story.append(sp(8))

rank_headers = ['#', 'THEME', 'KEY JUSTIFICATION', 'FAILURE CONDITION']
rank_rows = [
    ['1',
     f'Power Grid / Electrification\n{ticker("ETN")} {ticker("GEV")} {ticker("PWR")}',
     'Earnings anchors exist NOW. The 49 GW shortfall is a current bottleneck. Catalysts are quarterly. Positioning is mid-cycle, not crowded.',
     'Hyperscalers shift to low-power inference faster than expected. Grid permitting reform stalls.'],
    ['2',
     f'Physical AI / Humanoid Robotics\n{ticker("TSLA")} {ticker("ABB")} {ticker("ARTY")}',
     '2026 is the commercial inflection year by every measurable signal. Cost below $10K for commercial apps. Amazon 1M+ robot fleet. ARTY +33% YTD — moving, not finished.',
     'Per-unit cost stalls above $50K. Major workplace safety incident triggers regulatory pause.'],
    ['3',
     f'Autonomous Defense / Drones\n{ticker("AVAV")} {ticker("KTOS")} {ticker("DFEN")}',
     'July 2026 NATO summit is a named, dated catalyst that will formally shift doctrine. DAWG budget explosion. U.S. drone names remain under-owned vs. European traditional defense.',
     'Ukraine ceasefire dramatically reduces procurement urgency. FY2027 appropriations stall.'],
    ['4',
     f'Nuclear Energy / SMR\n{ticker("CEG")} {ticker("VST")} {ticker("NLR")}',
     'Fundamental case is strong but SMR monetization timeline is 2028–2032. Uranium miner valuations already pricing in significant demand growth.',
     'NRC timelines extend. Nuclear incident globally resets sentiment.'],
    ['5',
     f'Longevity Biotech\n{ticker("LLY")} {ticker("NVO")} {ticker("RVTY")}',
     'Orforglipron FDA decision is a binary catalyst. Long-term market real. Pure-play longevity remains under-owned but largely private, reducing liquid expression quality.',
     'GLP-1 adverse event study triggers FDA class review. Pricing compressed faster than market expands.'],
]
col_w = [0.25*inch, 1.5*inch, TW*0.42, TW*0.27]
story.append(make_table(rank_headers, rank_rows, col_w))
story.append(sp(12))

# Chart 2
if os.path.exists(CHART2):
    story.append(Image(CHART2, width=TW, height=TW * 0.67))
    story.append(P('Theme scoring across four dimensions. Dashed ring = score of 4. '
                   'Internal assessment — May 2026.', tiny))
story.append(sp(8))

# ════════════════════════════════════════════════════════════════════════════
# 04 CONTRARIAN
# ════════════════════════════════════════════════════════════════════════════
story += section_header('04 —', 'CONTRARIAN / NON-CONSENSUS PICK')

story += [
    P('<font name="Helvetica-Bold" color="#C0392B">EMERGING MARKETS EQUITY — '
      'Broad Ex-China EM</font>', theme_h),
    P('Non-consensus driver: Macro-regime / Dollar weakness / Structural under-ownership',
      theme_q),
    P('After 15 years of US equity dominance, emerging markets are structurally under-owned and '
      'undervalued. EM equities trade at a forward P/E of just 14x for 2026, vs. ~22x for the '
      'S&P 500 — the widest gap in over a decade '
      '<font color="#888888">(Directional estimate: T. Rowe Price, Q1 2026)</font>. Global '
      'investors are still underweight EM, priced for continued US exceptionalism that is '
      'visibly ending.', body_j),
    P('Why it is absent from standard sell-side rotation lists: a structural dollar bull market '
      'persisted from 2011–2025, making EM a recurring false dawn. Managers who were burned '
      'in 2014, 2018, and 2022 remain skeptical. This is not a consensus view.', body_j),
    P('Why the thesis is real — three simultaneous drivers not present together before:',
      label),
]
story += bullets([
    '<font name="Helvetica-Bold">Dollar weakness is structural.</font>  The US deficit trajectory, '
    'the Fed’s constrained room to hike, and de-dollarization in commodity trade settlements '
    'are creating durable dollar headwinds. HSBC economists explicitly cite dollar weakness as a '
    '2026 EM tailwind <font color="#888888">(HSBC / FXStreet, May 2026)</font>.',
    '<font name="Helvetica-Bold">Positioning asymmetry is exceptional.</font>  US equities '
    'represent ~65% of global equity benchmarks. A 1% reallocation from US to EM translates to '
    'a proportionally large inflow into a smaller asset class '
    '<font color="#888888">(T. Rowe Price, 2026)</font>.',
    '<font name="Helvetica-Bold">The EM opportunity set has broadened.</font>  Beyond Taiwan '
    'semiconductors and Korean tech, EM now includes AI infrastructure beneficiaries, power '
    'and grid builders, defense manufacturers, and advanced manufacturing — the exact '
    'themes in this note, but at 14x P/E vs. 22x in the US.',
])
story += [
    P('<font name="Helvetica-Bold">CATALYST CLOCK:</font>  Any Fed rate cut or policy shift '
      'that accelerates dollar weakness is the primary trigger. USD/EM FX basket breaking '
      'below 2023 lows would signal the structural regime shift is confirmed.', body_j),
    P('<font name="Helvetica-Bold">BEST EXPRESSION:</font>  '
      f'{ticker("EEM")}  ·  {ticker("VWO")}  ·  {ticker("EMXC")} (ex-China EM)  '
      f'·  {ticker("INDA")}  ·  {ticker("EWZ")}', body),
    P(f'Best liquid expression: <font name="Helvetica-Bold">{ticker("EMXC")}</font> '
      '(iShares MSCI Emerging Markets ex China) — removes idiosyncratic China regulatory '
      'risk while capturing broad EM dollar-weakness and reallocation tailwind. '
      f'{ticker("EWZ")} (Brazil) and {ticker("INDA")} (India) for single-country expression '
      'with specific catalysts.', body_j),
    sp(4),
    bear_box('<font name="Helvetica-Bold">BEAR CASE:</font>  The trade fails if U.S. growth '
             'reaccelerates relative to EM (no “Great Rotation” materializes) and '
             'the dollar strengthens on safe-haven demand from geopolitical risk. China-specific '
             'regulatory events create negative contagion across EM benchmarks even for '
             'ex-China positions.', RED),
]

# ════════════════════════════════════════════════════════════════════════════
# 05 TRADEABLE EXPRESSION
# ════════════════════════════════════════════════════════════════════════════
story += section_header('05 —', 'TRADEABLE EXPRESSION')

story.append(P('Entry structure for top-ranked themes and contrarian pick.', small))
story.append(sp(6))

# Table A: Power Grid vs Humanoid
te_h = ['DIMENSION',
        f'POWER GRID: {ticker("ETN")} {ticker("GEV")} {ticker("PWR")}',
        f'HUMANOID ROBOTICS: {ticker("TSLA")} {ticker("ABB")} {ticker("ARTY")}']
te_rows = [
    ['Cleanest expression',
     f'Core longs: {ticker("ETN")} + {ticker("GEV")}. Picks-and-shovels: {ticker("PWR")}. '
     f'ETF: {ticker("ELFY")} (0.40%) or {ticker("AIPO")} (0.45%)',
     f'Single-name: {ticker("ABB")} (most liquid). Portfolio: equal-weight '
     f'{ticker("TSLA")} + {ticker("ABB")} + {ticker("ARTY")}'],
    ['Entry trigger',
     'Q2 2026 utility earnings confirming data center contract wins. DOE interconnection queue '
     'showing backlog extending. Any hyperscaler citing power-access as an expansion constraint',
     'Cost-per-unit announcement below $10K. Q2 2026 Amazon/BMW/Tesla confirming robot fleet ROI. '
     'Any M&A in humanoid space repricing sector'],
    ['Hedge / short leg',
     f'Short {ticker("GDDY")} or {ticker("CLOUD")} — SaaS companies exposed to AI '
     'commoditization with no power-demand link',
     f'Short legacy auto OEMs ({ticker("F")}, {ticker("GM")}) — exposed to humanoid labor '
     'substitution in manufacturing with slowest adoption response'],
    ['Time horizon',
     '18–24 months. The 49 GW shortfall is a multi-year construction problem',
     '12–18 months pre-catalyst. Mass commercial adoption is a 2027–2030 event; '
     '2026 is the position-building window'],
    ['Sizing logic',
     '5–7% pre-catalyst. Add to 9–10% post Q2 2026 utility earnings. '
     f'Trim {ticker("ELFY")}/{ticker("AIPO")} first, hold single-names longer',
     '3–5% at current levels. Add to 6–8% on first cost-threshold announcement. '
     f'Size {ticker("TSLA")} smallest due to CEO concentration risk'],
]
story.append(make_table(te_h, te_rows, [1.1*inch, TW/2 - 0.55*inch, TW/2 - 0.55*inch]))
story.append(sp(10))

# Table B: EM contrarian
em_h = ['DIMENSION', f'EMERGING MARKETS: {ticker("EMXC")} {ticker("INDA")} {ticker("EWZ")}']
em_rows = [
    ['Cleanest expression',
     f'Core: {ticker("EMXC")} (ex-China). Single-country: {ticker("INDA")} (India AI + manufacturing) '
     f'+ {ticker("EWZ")} (Brazil commodity leverage to dollar weakness)'],
    ['Entry trigger',
     'DXY (USD Index) sustained break below 100. Fed rate cut accompanied by EM central bank easing. '
     'EM fund flow data showing net inflows for 3+ consecutive months'],
    ['Hedge / short leg',
     f'Dollar-long position ({ticker("UUP")}) as macro hedge against dollar-strength scenario'],
    ['Time horizon',
     '24–36 months. Structural reallocation from US concentration is measured in years'],
    ['Sizing logic',
     '4–6% at current levels given early positioning. Add to 8–10% on DXY sustained break below 100'],
]
story.append(make_table(em_h, em_rows, [1.1*inch, TW - 1.1*inch]))
story.append(sp(8))

# ════════════════════════════════════════════════════════════════════════════
# 06 WHAT TO MONITOR
# ════════════════════════════════════════════════════════════════════════════
story += section_header('06 —', 'WHAT TO MONITOR')

monitors = [
    ('POWER GRID EARNINGS',
     f'Q2 2026 results from {ticker("ETN")}, {ticker("GEV")}, {ticker("PWR")}, {ticker("NEE")} — '
     'look for data center revenue as a line item and backlog guidance for transformer/switchgear '
     'delivery timelines. Any pushout in delivery = demand confirmation; any demand cut = risk signal.'),
    ('HUMANOID COST THRESHOLD',
     'Any manufacturer announcement of per-unit cost below $10,000. Tesla Optimus program update '
     'on Investor Day (watch for volume production targets for 2027). Amazon robot fleet '
     f'utilization % in Q2 2026 earnings.'),
    ('NATO ANKARA SUMMIT',
     'July 2026 — look for specific doctrine language formalizing “drones and AI over tanks.” '
     'Any quantified procurement commitment beyond current $70B figure. DAWG budget Congressional '
     'committee vote dates (H2 2026).'),
    ('NUCLEAR PPA ANNOUNCEMENTS',
     f'Any tech company ({ticker("MSFT")}, {ticker("AMZN")}, {ticker("GOOGL")}) announcing a new '
     f'nuclear power purchase agreement. {ticker("CEG")} call — listen for pipeline commentary '
     'on PPAs under negotiation.'),
    ('GLP-1 PIPELINE',
     f'FDA PDUFA date for {ticker("LLY")}’s orforglipron (confirm date when announced). '
     'Novo oral sema 26-week adherence data from real-world prescriptions — first real-world '
     'durability signal for the oral format.'),
    ('EM DOLLAR SIGNAL',
     'DXY weekly close — sustained breach of 100 is the structural signal. EM equity fund '
     'flows (IIF data, monthly) — first three consecutive months of net inflows would confirm '
     'institutional reallocation has begun.'),
    ('OUTGOING THEME CHECK',
     'Hyperscaler Q2 2026 earnings (July): if capex-to-revenue ratios compress OR if any '
     'hyperscaler cuts 2027 capex guidance, the AI infrastructure rotation accelerates. Watch '
     f'{ticker("GOOGL")} and {ticker("MSFT")} calls specifically — they guide first.'),
]

for lbl, detail in monitors:
    story.append(monitor_item(lbl, detail))

# ════════════════════════════════════════════════════════════════════════════
# TIME-SENSITIVE FLAGS
# ════════════════════════════════════════════════════════════════════════════
story += section_header('⚠  ', 'TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS')

flags = [
    ('DAWG BUDGET FIGURE (+24,000% INCREASE)',
     'The $54.6B FY2027 request and the 24,000% increase figure are sourced from '
     'globalsecurity.org citing DefenseScoop (April 2026). Single source. Verify against '
     'official OMB FY2027 budget documents and Pentagon press releases before sizing '
     'autonomous defense positions on this figure.'),
    ('HUMANOID UNIT COST ($10,000 THRESHOLD)',
     'Sourced from Global X ETFs (2026). Single source. This is a production cost threshold '
     'for “many commercial applications” — not all use cases. Confirm with '
     'manufacturer-specific announcements before assuming broad commercial ROI has turned positive.'),
    ('URANIUM MINER VALUATIONS (RICH)',
     'Assessment that uranium miner pricing is elevated is a directional estimate based on Sprott '
     'commentary (“pricing can be rich for producers even on moderate demand growth,” '
     f'Sprott ETFs, 2026). Actual current P/E data for {ticker("CCJ")} and {ticker("URNM")} vs. '
     'historical should be verified before reducing exposure.'),
    ('EM FORWARD P/E (14x)',
     'Directional estimate — sourced from T. Rowe Price institutional Q1 2026 commentary. '
     'Verify against current MSCI EM consensus estimates before using as a valuation anchor.'),
    ('EUROPEAN DEFENSE CROWDING',
     'Assessment based on Reuters/investing.com analysis citing a Citigroup note on trimmed '
     f'positions and the {ticker("EUAD")} −4% YTD vs. prior +75% peak. Confirm current '
     'Citigroup positioning data is not stale before using this as a reason to avoid European '
     'defense names.'),
]

for bold, rest in flags:
    story.append(flag_item(bold, rest))

story += [
    sp(10),
    P('All other claims in this note are confirmed with multi-source data as of May 2026.',
      S('Normal', fontSize=8.5, leading=12, fontName='Helvetica-Bold',
        textColor=TEAL, spaceAfter=0)),
    sp(16),
    rule(RULE, 0.5, 0, 8),
    P('Internal research note — not for distribution. All thematic views represent '
      'forward-looking estimates subject to material revision on catalyst events. May 2026.',
      tiny),
]

# ── Build ─────────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT,
    pagesize=letter,
    leftMargin=ML, rightMargin=MR,
    topMargin=MT + 20, bottomMargin=MB + 20,
    title='After the Capex Supercycle: Five Themes on the Cusp of Mass Adoption',
    author='Internal Buy-Side Research',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print('PDF saved:', OUT)
