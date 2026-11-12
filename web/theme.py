"""Look of the web app: colours, fonts, CSS and the shared Plotly style. PRESENTATION ONLY. The CSS is a fixed string
(no user or data text goes into it) and is added with st.html.
"""
import streamlit as st

# Sidebar = the background colour of assets/logo_dark.png (median of its border pixels; scripts/make_logos.py prints it).
SIDEBAR = "#1A0B3F"
TEXT = "#201936"
CORAL = "#FF674C"
CORAL_SOFT = "#FF9C86"
PURPLE = "#75619B"
PURPLE_SOFT = "#B7A9D3"
LAVENDER = "#E9E3F2"
BG = "#FAF9F8"
CARD = "#FFFFFF"
MUTED = "#777384"
LINE = "#E3DDEE"
# Inter is bundled in assets/fonts (SIL OFL, see OFL.txt there) and served by Streamlit static serving (web/static/fonts -> assets/fonts); no web font is loaded from the internet.
FONT = "Inter, -apple-system, 'Segoe UI', Roboto, sans-serif"
LOGO_WIDTH = 170          # displayed width of the sidebar logo in px; assets/logo_sidebar.png is exported at 2x this
CHART_HEIGHT = 280        # every chart has this height
MONO = "'JetBrains Mono', ui-monospace, Menlo, monospace"

CSS = f"""
<style>
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 400; font-display: swap; src: url('/app/static/fonts/Inter-400.woff2') format('woff2'); }}
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 500; font-display: swap; src: url('/app/static/fonts/Inter-500.woff2') format('woff2'); }}
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 600; font-display: swap; src: url('/app/static/fonts/Inter-600.woff2') format('woff2'); }}
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 700; font-display: swap; src: url('/app/static/fonts/Inter-700.woff2') format('woff2'); }}
html, body, .stApp, [data-testid="stMarkdownContainer"], button, input, textarea {{ font-family: {FONT}; }}
.stApp {{ background: {BG}; color: {TEXT}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.stMain {{ overflow-x: hidden; }}
.block-container {{ padding: 1.6rem 1.4rem 1.4rem; max-width: 1760px; }}

/* ONE highlight: coral for hover, focus, active and selected */
a:hover {{ color: {CORAL}; }}
.stMain .stButton button {{ border-color: {LINE}; background: {CARD}; color: {TEXT}; }}
.stMain .stButton button:hover, .stMain .stButton button:focus-visible,
.stMain .stButton button:active {{ border-color: {CORAL} !important; background: rgba(255,103,76,.07) !important; color: {CORAL} !important; }}
.stMain .stButton button:hover *, .stMain .stButton button:focus-visible * {{ color: {CORAL} !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{ background: rgba(233,227,242,.65) !important; border: 1px solid {LINE}; }}
[data-testid="stAlertContentInfo"], [data-testid="stAlertContentInfo"] * {{ color: {TEXT} !important; }}
[data-baseweb="select"] > div:hover, [data-baseweb="select"] > div:focus-within {{ border-color: {CORAL} !important; }}
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] {{ color: {CORAL}; background: rgba(255,103,76,.08); }}
[data-testid="stChatInput"]:focus-within {{ border-color: {CORAL}; }}
[data-testid="stSelectbox"] label p {{ color: {MUTED}; }}

/* sidebar: 210 px wide, flat navigation */
section[data-testid="stSidebar"] {{ background: {SIDEBAR}; width: 210px !important; min-width: 210px !important; max-width: 210px !important; }}
section[data-testid="stSidebar"] > div:first-child {{ width: 210px !important; }}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ height: 2rem; min-height: 0; padding: .25rem .5rem 0; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding: 0 .8rem 1rem; }}
section[data-testid="stSidebar"] * {{ color: #E7E1F4; }}
section[data-testid="stSidebar"] hr {{ border-color: rgba(231,225,244,.14); }}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color: #A99FC4; }}
section[data-testid="stSidebar"] [data-testid="stImage"] {{ margin: 0 0 .9rem .1rem; }}
section[data-testid="stSidebar"] [class*="st-key-nav-"] button, section[data-testid="stSidebar"] .st-key-new-chat button {{
  background: transparent !important; box-shadow: none !important; border: 0 !important; border-left: 3px solid transparent !important;
  border-radius: 6px !important; justify-content: flex-start; padding: .5rem .7rem; font-weight: 500; color: #D9D2EA !important; }}
section[data-testid="stSidebar"] [class*="st-key-nav-"] button *, section[data-testid="stSidebar"] .st-key-new-chat button * {{
  color: inherit !important; justify-content: flex-start; }}
section[data-testid="stSidebar"] [class*="st-key-nav-"] button:hover, section[data-testid="stSidebar"] .st-key-new-chat button:hover {{
  color: {CORAL} !important; background: rgba(255,103,76,.07) !important; }}
section[data-testid="stSidebar"] [class*="st-key-nav-"] button[kind="primary"] {{
  background: rgba(117,97,155,.30) !important; border-left-color: {CORAL} !important; color: {CORAL} !important; }}
section[data-testid="stSidebar"] .st-key-new-chat button {{ border: 1px solid rgba(231,225,244,.30) !important; justify-content: center; }}

/* page header: decorative shapes behind it (CSS only): soft grey-lavender diagonal bands and one solid coral parallelogram */
[class*="st-key-page-header"] {{ position: relative; isolation: isolate; padding: .2rem 0 .8rem; gap: .4rem; }}
[class*="st-key-page-header"]::before {{ content: ""; position: absolute; z-index: -1; top: -1.6rem; bottom: 0; left: 28%; right: -4rem;
  background: linear-gradient(112deg, transparent 0 36%, rgba(203,197,219,.34) 36% 56%, transparent 56% 60%,
                              rgba(203,197,219,.22) 60% 70%, transparent 70% 76%, rgba(203,197,219,.30) 76% 90%, transparent 90%); }}
[class*="st-key-page-header"]::after {{ content: ""; position: absolute; z-index: -1; top: -1.7rem; right: 43%; width: 11%; height: 4.6rem;
  background: {CORAL}; clip-path: polygon(34% 0, 100% 0, 66% 100%, 0 100%); }}
[class*="st-key-title-two-line"] h1 {{ max-width: 6.3em; }}
[class*="st-key-topbar-status"] {{ text-align: right; }}
[class*="st-key-topbar-status"] p {{ font-size: .9rem; margin: 0; }}
[class*="st-key-header-sub"] {{ border-left: 1px solid #CFC8DE; padding-left: 2rem; }}
[class*="st-key-header-sub"] p {{ font-size: 1.1rem; line-height: 1.55; color: {TEXT}; }}
h1 {{ font-size: 3.8rem !important; line-height: 1.0 !important; font-weight: 700 !important; letter-spacing: -0.03em; color: {TEXT};
  padding: 0 !important; margin: 0 !important; }}
h2, h3 {{ color: {TEXT}; font-weight: 600 !important; letter-spacing: -0.01em; }}
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}

/* cards: one container style for charts and tables */
[class*="st-key-card-"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: 1rem 1.1rem .8rem;
  box-shadow: 0 1px 2px rgba(32,25,54,.05); gap: .4rem; }}
[class*="st-key-card-half"] {{ min-height: 400px; }}
[class*="st-key-card-tall"] {{ min-height: 640px; }}
[class*="st-key-card-short"] {{ min-height: 250px; }}
[class*="st-key-warn-line"] {{ margin: .5rem 0 .6rem; }}
[class*="st-key-warn-line"] p {{ color: {CORAL}; font-weight: 600; margin: 0; }}

/* clickable cards (KPI cards, role rows): the whole card is an invisible button. Open card: coral border. Urgent card: coral bar */
[class*="st-key-kpi-card-"] {{ position: relative; background: {CARD}; border: 1px solid {LINE}; border-radius: 10px;
  padding: .9rem 1.1rem .7rem; box-shadow: 0 1px 2px rgba(32,25,54,.05); gap: .1rem; min-height: 180px; }}
[class*="st-key-kpi-card-"] [data-testid="stMetric"] {{ display: flex; flex-direction: column-reverse; border: 0; box-shadow: none;
  background: transparent; padding: 0; min-height: 0; }}
[class*="st-key-kpi-card-"] [data-testid="stMetricValue"] {{ font-size: 2.8rem; line-height: 1.1; font-weight: 600; }}
[class*="st-key-kpi-card-"] [data-testid="stMetricLabel"] {{ padding-right: 2rem; }}
[class*="st-key-kpi-card-"] [data-testid="stMetricLabel"] * {{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
[class*="st-key-kpi-card-"] [data-testid="stMetricLabel"] p {{ color: {TEXT}; font-weight: 500; font-size: .78rem; }}
[class*="st-key-kpi-card-"] [data-testid="stCaptionContainer"] {{ margin-top: -.1rem; }}
[class*="st-key-kpi-card-"] [data-testid="stCaptionContainer"] * {{ color: #3D3656; font-size: .85rem; }}
[class*="st-key-kpi-icon-"] {{ position: absolute; top: .8rem; right: 1rem; width: auto; z-index: 2; }}
[class*="st-key-kpi-icon-"] p {{ color: #8C879A; font-size: 1.5rem; margin: 0; }}
[class*="-urgent"][class*="st-key-kpi-card-"] {{ border-left: 5px solid {CORAL}; }}
[class*="-urgent"][class*="st-key-kpi-card-"] [data-testid="stMetricValue"], [class*="-urgent"] [class*="st-key-kpi-icon-"] p {{ color: {CORAL}; }}
[class*="st-key-role-row-"] {{ position: relative; border-top: 1px solid {LINE}; border-left: 3px solid transparent; padding: .55rem .5rem .45rem; gap: .15rem; }}
:is([class*="st-key-kpi-card-"], [class*="st-key-role-row-"], [class*="st-key-ptile-"]) [data-testid="stElementContainer"]:has(button) {{ position: absolute; inset: 0; z-index: 3; width: 100% !important; }}
:is([class*="st-key-kpi-card-"], [class*="st-key-role-row-"], [class*="st-key-ptile-"]) [data-testid="stElementContainer"]:has(button) > * {{ height: 100%; width: 100%; }}
:is([class*="st-key-kpi-card-"], [class*="st-key-role-row-"], [class*="st-key-ptile-"]) [data-testid="stElementContainer"]:has(button) :is(div, span) {{ height: 100%; width: 100%; }}
:is([class*="st-key-kpi-card-"], [class*="st-key-role-row-"], [class*="st-key-ptile-"]) button {{ width: 100%; height: 100%; min-height: 100%; opacity: 0; cursor: pointer; }}
[class*="st-key-kpi-card-"]:hover, [class*="st-key-kpi-card-"][class*="-selected"] {{ border-color: {CORAL}; }}
[class*="st-key-kpi-card-"][class*="-selected"] {{ box-shadow: 0 0 0 1px {CORAL}; }}
[class*="st-key-role-row-"]:hover {{ background: rgba(255,103,76,.05); }}
[class*="st-key-role-row-"][class*="-selected"] {{ border-left: 5px solid {CORAL}; background: rgba(255,103,76,.11); padding-left: .65rem; }}
[class*="st-key-viewing-bar"] {{ border-left: 5px solid {CORAL}; background: rgba(255,103,76,.08); border-radius: 8px; padding: .6rem 1rem; gap: 0; height: auto; overflow: hidden; }}
[class*="st-key-viewing-bar"] {{ gap: .2rem !important; }}
[class*="st-key-viewing-bar"] p {{ margin: 0; font-size: 1.02rem; line-height: 1.4; }}
[class*="st-key-conflict-box-"] {{ border: 2px solid {CORAL}; border-radius: 10px; background: #FFF4F1; padding: .7rem 1rem; gap: .1rem; margin-bottom: .6rem; }}
[class*="st-key-conflict-box-"] * {{ color: {TEXT} !important; }}
.stagebar {{ display: flex; gap: 2px; height: 10px; border-radius: 6px; overflow: hidden; background: #EFEAF6; margin: .1rem 0 0; }}
.stagebar span {{ display: block; height: 100%; }}
[class*="st-key-prio-row-"], [class*="st-key-activity-row-"] {{ border-top: 1px solid {LINE}; padding: .45rem 0 .3rem; gap: 0; }}
[class*="st-key-prio-row-"] p, [class*="st-key-activity-row-"] p {{ margin: 0; }}
[class*="st-key-prio-row-"] [data-testid="stColumn"]:first-child p, [class*="st-key-activity-row-"] [data-testid="stColumn"]:first-child p {{
  color: {CORAL}; font-size: 1.3rem; }}
[class*="st-key-activity-row-"] [data-testid="stColumn"]:last-child p {{ text-align: right; color: {MUTED}; }}
[class*="st-key-card-"] [data-testid="stMarkdownContainer"] p strong {{ font-size: 1.02rem; }}
[class*="st-key-card-"] [data-testid="stCaptionContainer"] strong {{ font-size: inherit; color: {TEXT}; }}
[class*="st-key-card-"] h2 {{ font-size: 3rem; line-height: 1.1; margin: 0 0 .25rem; padding: 0; }}
[class*="st-key-card-tall-funnel"] [data-testid="stMarkdownContainer"] p {{ font-size: .9rem; }}
[class*="st-key-prio-row-"] [data-testid="stMarkdownContainer"] p {{ font-size: .93rem; }}
[data-testid="stForm"] {{ padding: 0; }}
[data-testid="stForm"] button {{ background: {SIDEBAR} !important; border-color: {SIDEBAR} !important; border-radius: 6px; min-height: 2.6rem; }}
[data-testid="stForm"] button span[data-testid="stIconMaterial"] {{ color: {CORAL} !important; }}
[data-testid="stForm"] button:hover {{ background: {CORAL} !important; border-color: {CORAL} !important; }}
[data-testid="stForm"] button:hover span[data-testid="stIconMaterial"] {{ color: #FFFFFF !important; }}
[data-testid="stMetric"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: 14px 16px; min-height: 122px;
  box-shadow: 0 1px 2px rgba(32,25,54,.05); }}
[data-testid="stMetricValue"] {{ font-size: 2.1rem; font-weight: 600; color: {TEXT}; }}
[data-testid="stMetricLabel"] p {{ text-transform: uppercase; letter-spacing: .04em; font-size: .72rem; color: {MUTED}; }}

/* right AI panel: dark header with tiles, light conversation area. A normal column, not sticky. */
[class*="st-key-ai-panel"] {{ border: 1px solid {SIDEBAR}; border-radius: 14px; overflow: hidden; gap: 0; background: #F3F0F8;
  box-shadow: 0 4px 14px rgba(26,11,63,.18); }}
[class*="st-key-ai-head"] {{ background: {SIDEBAR}; padding: .9rem 1.1rem 1rem; gap: .5rem; }}
[class*="st-key-ai-head"] :is(p, h3, span, div) {{ color: #F3EEFB; }}
[class*="st-key-ai-head"] [data-testid="stCaptionContainer"] * {{ color: #B9AFD2; }}
[class*="st-key-ai-head"] h3 {{ font-size: 1.7rem; line-height: 1.25; margin: 0; padding: .5rem 0 .2rem; color: #FFFFFF; }}
[class*="st-key-ai-head"] > [data-testid="stElementContainer"]:first-child p {{ display: inline-block; border-bottom: 2px solid {CORAL}; padding-bottom: .45rem; margin: 0; }}
[class*="st-key-ptile-"] {{ position: relative; background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.14); border-radius: 10px;
  padding: .6rem .8rem; gap: .15rem; min-height: 4.1rem; justify-content: center; }}
[class*="st-key-ptile-"]:hover {{ border-color: {CORAL}; background: rgba(255,103,76,.16); }}
[class*="st-key-ptile-"] p {{ margin: 0; line-height: 1.25; }}
[class*="st-key-ptile-"] [data-testid="stColumn"]:first-child :is(p, span) {{ color: {CORAL} !important; font-size: 1.7rem; }}
[class*="st-key-ptile-"] [data-testid="stMarkdownContainer"] strong {{ color: #FFFFFF; font-size: .98rem; }}
[class*="st-key-open-chat"] button, [class*="st-key-read-full-"] button {{ background: transparent !important; border: 1.5px solid {PURPLE} !important; color: {PURPLE} !important;
  border-radius: 8px; font-weight: 600; width: 100%; }}
[class*="st-key-open-chat"] button *, [class*="st-key-read-full-"] button * {{ color: {PURPLE} !important; }}
[class*="st-key-open-chat"] button:hover, [class*="st-key-read-full-"] button:hover {{ border-color: {CORAL} !important; background: rgba(255,103,76,.08) !important; }}
[class*="st-key-open-chat"] button:hover *, [class*="st-key-read-full-"] button:hover * {{ color: {CORAL} !important; }}
[class*="st-key-top-row-"] {{ border-top: 1px solid {LINE}; padding: .45rem 0 .4rem; gap: .4rem !important; }}
[class*="st-key-top-row-"] [data-testid="stElementContainer"] {{ overflow: visible; }}
[class*="st-key-top-row-"] p {{ margin: 0; }}
[class*="st-key-decision-row-"] {{ border-top: 1px solid {LINE}; padding: .5rem 0 .3rem; gap: 0; }}
[class*="st-key-decision-row-"] p {{ margin: 0; }}
[class*="st-key-quality-"] li {{ margin-bottom: .35rem; font-size: .9rem; }}
[class*="st-key-quality-fixed"] strong {{ color: {PURPLE}; }}
[class*="st-key-quality-human"] strong {{ color: {CORAL}; }}
[class*="st-key-ai-body"] {{ padding: .9rem 1.1rem 1rem; gap: .6rem; }}
[class*="st-key-ai-chat"] {{ background: transparent; border: 0; padding: 0; box-shadow: none; }}
[class*="st-key-ai-body"] [data-testid="stChatMessage"] {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; padding: .6rem .8rem; }}
[class*="st-key-ai-body"] [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ background: {LAVENDER}; }}
[class*="st-key-ai-body"] [data-testid="stTextInput"] input {{ background: #FFFFFF; }}
[class*="st-key-answer-block-"] {{ border-left: 4px solid {PURPLE_SOFT}; padding: .1rem 0 .1rem .9rem; margin: .6rem 0; gap: .45rem !important; }}
[class*="st-key-answer-block-facts"] {{ border-left-color: {PURPLE}; }}
[class*="st-key-answer-block-ai-"] {{ border-left-color: {CORAL}; }}
[class*="st-key-answer-block-caveats"] {{ border-left-color: {PURPLE_SOFT}; background: rgba(233,227,242,.55); border-radius: 0 10px 10px 0; padding: .6rem .9rem; }}
[class*="st-key-answer-block-"] [data-testid="stCaptionContainer"], [class*="st-key-footer-meta"] [data-testid="stCaptionContainer"] {{ margin-top: .35rem !important; }}
[class*="st-key-answer-block-"] h5 {{ font-size: 1.12rem !important; font-weight: 700 !important; letter-spacing: .04em; margin: 0; padding: 0 !important; color: {TEXT}; }}
[class*="st-key-answer-block-facts"] h5 {{ color: {PURPLE}; }}
[class*="st-key-answer-block-ai-"] h5 {{ color: {CORAL}; }}
[class*="st-key-answer-block-caveats"] h5 {{ color: #4B3F6B; }}
[class*="st-key-src-row-"] {{ gap: .1rem !important; padding: .15rem 0 .3rem; }}
[class*="st-key-src-row-"] p {{ margin: 0; }}
[class*="st-key-cand-card-"] {{ position: relative; background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .8rem 1rem .7rem; gap: .5rem !important;
  box-shadow: 0 1px 2px rgba(32,25,54,.05); }}
[class*="st-key-cand-card-"] h3 {{ color: {PURPLE}; margin: 0; padding: 0; font-size: 1.8rem; }}
[class*="st-key-cand-card-"] p {{ margin: 0; }}
[class*="st-key-cand-card-"][class*="-urgent"] {{ border: 2px solid {CORAL}; }}
[class*="st-key-cand-card-"][class*="-urgent"] h3 {{ color: {CORAL}; }}
[class*="st-key-ranking-card-"], [class*="st-key-answer-view-"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .8rem 1rem .6rem;
  box-shadow: 0 1px 2px rgba(32,25,54,.05); gap: .4rem !important; margin-top: .5rem; }}
[class*="st-key-answer-view-tasks-"] h2 {{ font-size: 2.2rem; line-height: 1.1; margin: 0; padding: 0; color: {PURPLE}; }}
/* the three quick-action buttons of the Ask AI page: all identical, dark, coral icons; no permanent selected state */
.stMain [class*="st-key-askbtn-"] button {{ background: {SIDEBAR}; border: 1px solid {SIDEBAR}; color: #FFFFFF; border-radius: 10px; min-height: 3.2rem;
  width: 100%; font-weight: 600; cursor: pointer; white-space: nowrap; justify-content: center; }}
.stMain [class*="st-key-askbtn-"] button * {{ color: #FFFFFF !important; white-space: nowrap; }}
.stMain [class*="st-key-askbtn-"] button > div {{ justify-content: center; gap: .55rem; }}
.stMain [class*="st-key-askbtn-"] button span[data-testid="stIconMaterial"] {{ color: #FF7964 !important; }}
.stMain [class*="st-key-askbtn-"] button:hover {{ background: #34245D !important; border-color: #34245D !important; color: #FFFFFF !important; cursor: pointer; }}
.stMain [class*="st-key-askbtn-"] button:hover * {{ color: #FFFFFF !important; }}
.stMain [class*="st-key-askbtn-"] button:hover span[data-testid="stIconMaterial"] {{ color: #FF7964 !important; }}
.stMain [class*="st-key-askbtn-"] button:active {{ background: #120830 !important; border-color: #120830 !important; }}
.stMain [class*="st-key-askbtn-"] button:focus-visible {{ outline: 2px solid #FF7964 !important; outline-offset: 2px; }}
[class*="st-key-ask-actions"] [data-testid="stHorizontalBlock"] {{ gap: .8rem; }}
@media (max-width: 900px) {{
  [class*="st-key-ask-actions"] [data-testid="stHorizontalBlock"] {{ flex-direction: column; }}
  [class*="st-key-ask-actions"] [data-testid="stColumn"] {{ width: 100% !important; flex: 1 1 100% !important; }}
}}
/* Streamlit gives every markdown block a -1rem bottom margin; with zero p margins the text then overflows its box */
:is([class*="st-key-viewing-bar"], [class*="st-key-dq-tile-"], [class*="st-key-decision-row-"], [class*="st-key-dq-row-"], [class*="st-key-attention-banner"]) [data-testid="stMarkdownContainer"],
:is([class*="st-key-viewing-bar"], [class*="st-key-dq-tile-"], [class*="st-key-decision-row-"], [class*="st-key-dq-row-"], [class*="st-key-attention-banner"]) [data-testid="stMarkdown"],
:is([class*="st-key-viewing-bar"], [class*="st-key-dq-tile-"], [class*="st-key-decision-row-"], [class*="st-key-dq-row-"], [class*="st-key-attention-banner"]) [data-testid="stCaptionContainer"] {{ margin-bottom: 0 !important; height: auto !important; overflow: visible !important; }}
/* Ask AI: the chat input floats at the bottom of the window, so leave room under the last answer line */
[data-testid="stMainBlockContainer"]:has([class*="st-key-ask-actions"]) {{ padding-bottom: 9rem !important; }}
/* data health check, data quality, candidates page */
.dqbar {{ display: flex; gap: 1px; height: 20px; border-radius: 10px; overflow: hidden; background: #EFEAF6; margin: .4rem 0 .5rem; }}
.dqbar span {{ display: block; height: 100%; cursor: default; }}
.dqkeys {{ display: flex; flex-wrap: wrap; gap: .4rem 1.1rem; font-size: .9rem; color: {TEXT}; margin-bottom: .6rem; }}
.dqkey i {{ display: inline-block; width: 11px; height: 11px; border-radius: 3px; margin-right: .4rem; }}
[class*="st-key-card-wide-quality"] {{ border-color: #E9E3F2; }}
[class*="st-key-dq-tile-"] {{ padding: .8rem 1rem; border-radius: 14px; gap: .1rem !important; background: #FFFFFF; border: 1px solid #E9E3F2; min-height: 9.2rem; }}
[class*="st-key-dq-tile-"] h1 {{ font-size: 2.4rem !important; line-height: 1.1 !important; padding: 0 !important; margin: 0 !important; }}
[class*="st-key-dq-tile-"] p {{ margin: 0; }}
[class*="st-key-dq-tile-"] [data-testid="stMarkdownContainer"] p:first-child {{ font-size: 1.15rem; }}
[class*="st-key-dq-tile-fixed"] h1, [class*="st-key-dq-tile-fixed"] [data-testid="stMarkdownContainer"] p:first-child {{ color: {PURPLE}; }}
[class*="st-key-dq-tile-left"] h1 {{ color: {TEXT}; }}
[class*="st-key-dq-tile-left"] [data-testid="stMarkdownContainer"] p:first-child {{ color: #8E86A0; }}
[class*="st-key-dq-tile-human"] {{ background: #FFF1ED; border: 1.5px solid #FFC9BD; }}
[class*="st-key-dq-tile-human"] h1 {{ color: #D9543C; }}
[class*="st-key-dq-tile-human"] [data-testid="stMarkdownContainer"] p:first-child {{ color: #FF674C; }}
.dqtable {{ overflow-x: auto; }}
.dqtable table {{ width: 100%; border-collapse: collapse; font-size: .85rem; color: {TEXT}; background: #FFFFFF; }}
.dqtable th {{ text-align: left; font-weight: 600; font-size: .75rem; color: {MUTED}; padding: .35rem .6rem; border-bottom: 1px solid #E9E3F2; white-space: nowrap; }}
.dqtable td {{ padding: .45rem .6rem; border-bottom: 1px solid #F1EDF7; vertical-align: top; line-height: 1.35; }}
.dqtable .dq-issue {{ font-weight: 600; min-width: 11rem; }}
.dqtable .dq-src {{ color: {MUTED}; font-size: .78rem; overflow-wrap: anywhere; min-width: 12.5rem; }}
.dqtable .dq-content {{ min-width: 16rem; color: #4A4360; }}
.dq-badge {{ display: inline-block; background: #FFF1ED; color: #D9543C; border-radius: 6px; padding: .1rem .5rem; font-weight: 600; font-size: .78rem; white-space: nowrap; }}
[class*="st-key-dq-row-"] {{ border-top: 1px solid {LINE}; padding: .35rem 0; gap: 0; }}
[class*="st-key-card-wide-quality"] h2 {{ font-size: 2rem; margin: 0; padding: 0; }}
[class*="st-key-attention-banner"] {{ background: #FFF1EE; border: 1px solid #FFC9BD; border-radius: 12px; padding: .9rem 1.2rem; margin-bottom: .8rem; gap: 0; }}
[class*="st-key-attention-banner"] p {{ margin: 0; }}
[class*="st-key-attention-banner"] strong {{ font-size: 1.25rem; color: {TEXT}; }}
[class*="st-key-attention-banner"] button {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 8px; }}
[class*="st-key-pg-"] button {{ border-radius: 50%; width: 2.2rem; height: 2.2rem; min-height: 2.2rem; padding: 0; }}
[class*="st-key-pg-"] button[kind="primary"] {{ background: {PURPLE} !important; border-color: {PURPLE} !important; color: #FFFFFF !important; }}
[class*="st-key-pg-"] button[kind="primary"] * {{ color: #FFFFFF !important; }}
[class*="st-key-cand-tab"] button {{ border-radius: 8px; }}
[class*="st-key-card-short-decision"] {{ border-left: 5px solid {CORAL}; background: #FFF8F6; }}

/* global footer: the sidebar colour, in the normal flow after the content */
[data-testid="stMainBlockContainer"]:has([class*="st-key-site-footer"]) {{ display: flex; flex-direction: column; min-height: calc(100vh - 3.2rem); }}
[data-testid="stMainBlockContainer"]:has([class*="st-key-site-footer"]) > [data-testid="stVerticalBlock"] {{ flex: 1 1 auto; }}
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-site-footer"]) {{ margin-top: auto !important; padding-top: 1.2rem; }}
[class*="st-key-site-footer"] {{ background: {SIDEBAR}; border-radius: 12px; padding: .9rem 1.4rem; border-top: 3px solid {CORAL}; gap: .3rem !important; }}
[class*="st-key-site-footer"] p {{ color: #FFFFFF; margin: 0; }}
[class*="st-key-site-footer"] [data-testid="stCaptionContainer"] * {{ color: #BDB3D6; }}
[class*="st-key-footer-meta"] {{ border-left: 1px solid rgba(231,225,244,.18); padding-left: 1.4rem; gap: .25rem !important; }}
[class*="st-key-site-footer"] [data-testid="stImage"] {{ margin: 0; }}
[class*="st-key-site-footer"] [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; row-gap: .6rem; }}
[class*="st-key-site-footer"] [data-testid="stColumn"] {{ min-width: 190px; }}
@media (max-width: 900px) {{
  [class*="st-key-site-footer"] {{ padding: .8rem 1rem; }}
  [class*="st-key-footer-meta"] {{ border-left: 0; padding-left: 0; }}
  .block-container {{ padding-left: .8rem; padding-right: .8rem; }}
}}
[data-testid="stExpander"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; box-shadow: 0 1px 2px rgba(32,25,54,.05); }}
[data-testid="stExpander"] summary:hover, [data-testid="stExpander"] summary:hover * {{ color: {CORAL} !important; }}
code {{ font-family: {MONO}; }}
</style>
"""


def apply():
    st.html(CSS)


def style_figure(fig, height=CHART_HEIGHT):
    """One look for every Plotly chart: same height and margins, same font, transparent background, light grid,
    legend above the plot, coral outline on the hover label."""
    fig.update_layout(
        font=dict(family=FONT, size=12, color=TEXT), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=24, t=30, b=8), height=height, bargap=0.35,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
        hoverlabel=dict(font_family=FONT, bgcolor=CARD, bordercolor=CORAL, font_color=TEXT))
    fig.update_xaxes(gridcolor="#EFEAF6", zeroline=False, linecolor=LINE, tickfont=dict(color=MUTED), title_font=dict(color=MUTED, size=11),
                     automargin=True)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", zeroline=False, linecolor=LINE, tickfont=dict(color=TEXT), automargin=True)
    return fig
