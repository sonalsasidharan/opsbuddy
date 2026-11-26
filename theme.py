"""Konnekt Noir styling for Devops-Konnekt (dark primary)."""
import html
import re

GROUND, CELL, TEXT = "#0B0B0D", "#18181B", "#F5F5F7"
CHAMPAGNE, VIOLET, RED, GREEN = "#D9B26A", "#A78BFA", "#FF7A7A", "#6EE7B7"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
:root {{
  --ground:{GROUND}; --cell:{CELL}; --text:{TEXT};
  --text2:rgba(245,245,247,.68); --line:rgba(245,245,247,.09);
  --champagne:{CHAMPAGNE}; --violet:{VIOLET}; --red:{RED}; --green:{GREEN};
  --ease:cubic-bezier(0.16,1,0.3,1);
  --s1:#101013; --s2:#0B0B0D; --s3:#0F0F12;
}}
html, body, .stApp, [data-testid="stSidebar"] {{ font-family: Inter, system-ui, sans-serif; }}
.stApp {{
  background:
    radial-gradient(900px 500px at 100% -10%, rgba(167,139,250,.10), transparent 60%),
    radial-gradient(800px 460px at 0% -10%, rgba(217,178,106,.08), transparent 60%),
    var(--ground);
  color: var(--text);
}}
[data-testid="stHeader"] {{ background: transparent; }}
footer, #MainMenu {{ visibility: hidden; }}
[data-testid="stSidebar"] {{ background: var(--ground); border-right: 1px solid var(--line); }}
.block-container {{ max-width: 1080px; padding-top: 2.2rem; }}
h1,h2,h3 {{ font-weight:600; letter-spacing:-0.02em; }}

.nk-top {{ display:flex; align-items:center; gap:14px; margin-bottom:4px; }}
.nk-title {{ font-size:30px; font-weight:600; letter-spacing:-0.035em; line-height:1.1; }}
.nk-sub {{ color:var(--text2); font-size:15px; margin:2px 0 22px 0; }}
.nk-h {{ font-size:18px; font-weight:600; letter-spacing:-0.02em; margin:26px 0 12px 0; }}

.nk-tiles {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.nk-tile {{ background:var(--cell); border:1px solid var(--line); border-radius:24px; padding:20px 22px; }}
.nk-num {{ font-size:44px; font-weight:600; letter-spacing:-0.035em; line-height:1; }}
.nk-lbl {{ color:var(--text2); font-size:14px; margin-top:8px; }}

.nk-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:12px; }}
.nk-card {{ background:var(--cell); border:1px solid var(--line); border-radius:20px; padding:18px 20px; margin-bottom:12px;
  transition:transform .2s var(--ease), border-color .2s var(--ease); }}
.nk-grid .nk-card {{ margin-bottom:0; }}
.nk-card:hover {{ border-color:rgba(245,245,247,.18); }}
.nk-name {{ font-size:16px; font-weight:600; letter-spacing:-0.02em; }}
.nk-meta {{ color:var(--text2); font-size:13px; margin-top:2px; word-break:break-all; }}
.nk-state {{ display:flex; align-items:center; gap:8px; margin-top:14px; font-size:14px; }}
.dot {{ width:9px; height:9px; border-radius:50%; display:inline-block; flex:none; }}
.dot.ok {{ background:var(--green); }} .dot.bad {{ background:var(--red); }} .dot.warn {{ background:var(--champagne); }}
.ok-t {{ color:var(--green); }} .bad-t {{ color:var(--red); }} .warn-t {{ color:var(--champagne); }}

.nk-role {{ border-radius:28px; padding:34px 32px; min-height:190px; margin-bottom:12px; border:1px solid var(--line); }}
/* Streamlit styles links blue + underlined; force the card text back to the theme */
.nk-rolelink, .nk-rolelink:hover, .nk-rolelink:focus, [data-testid="stMarkdownContainer"] a.nk-rolelink {{
  display:block; text-decoration:none !important; border-bottom:none !important; color:inherit !important; }}
.nk-rolelink *, [data-testid="stMarkdownContainer"] a.nk-rolelink * {{ text-decoration:none !important; border-bottom:none !important; }}
.nk-role {{ --c:var(--violet); --rgb:167,139,250; position:relative; border-radius:24px; padding:24px 26px 28px; margin-bottom:12px;
  background:
    radial-gradient(380px 200px at 100% 100%, rgba(var(--rgb),.22), transparent 70%),
    repeating-linear-gradient(0deg, rgba(245,245,247,.025) 0 1px, transparent 1px 22px),
    repeating-linear-gradient(90deg, rgba(245,245,247,.025) 0 1px, transparent 1px 22px),
    linear-gradient(160deg, var(--s1), var(--s2));
  border:1px solid rgba(245,245,247,.12); box-shadow:0 24px 50px -22px rgba(0,0,0,.9);
  transition:transform .3s var(--ease), border-color .3s var(--ease), box-shadow .3s var(--ease); }}
.nk-role.biz {{ --c:var(--champagne); --rgb:217,178,106; }}
.nk-cover {{ position:absolute; inset:0; z-index:2; display:block; border-radius:inherit; cursor:pointer; text-decoration:none !important; }}
/* Colour is on the border only: violet for Developers / DevOps, gold for Business team */
.nk-role {{ border-color:rgba(var(--rgb),.55); }}
.nk-role:hover, .nk-role:has(.nk-cover:focus-visible), .nk-role.sel {{
  border-color:rgb(var(--rgb)); box-shadow:0 0 0 1px rgb(var(--rgb)), 0 24px 50px -22px rgba(0,0,0,.9); }}
.nk-role:hover {{ transform:translateY(-4px); }}
.nk-role:active {{ transform:translateY(0) scale(.99); transition:none; }}
/* Namespace boxes on the developer page: same look as the Developers / DevOps role box */
[class*="st-key-nsbox-"] {{ --rgb:167,139,250; border-radius:20px !important; padding:12px 12px 12px !important; margin-bottom:0; gap:.2rem !important;
  background:
    radial-gradient(320px 170px at 100% 100%, rgba(var(--rgb),.22), transparent 70%),
    repeating-linear-gradient(0deg, rgba(245,245,247,.025) 0 1px, transparent 1px 22px),
    repeating-linear-gradient(90deg, rgba(245,245,247,.025) 0 1px, transparent 1px 22px),
    linear-gradient(160deg, var(--s1), var(--s2)) !important;
  border:1px solid rgba(var(--rgb),.55) !important; box-shadow:0 24px 50px -22px rgba(0,0,0,.9);
  transition:transform .3s var(--ease), border-color .3s var(--ease), box-shadow .3s var(--ease); }}
[class*="st-key-nsbox-"]:hover {{ transform:translateY(-3px); border-color:rgb(var(--rgb)) !important; box-shadow:0 0 0 1px rgb(var(--rgb)), 0 24px 50px -22px rgba(0,0,0,.9); }}
[class*="st-key-nsbox-"] .nk-name {{ color:var(--text); font-weight:500; letter-spacing:-0.02em; }}
[class*="st-key-nsbox-"] .nk-k {{ color:rgba(var(--rgb),.8); }}
[class*="st-key-nsbox-"] .stButton > button {{ justify-content:flex-start; text-align:left; width:100%; font-size:13px; min-height:0; padding:3px 8px;
  background:transparent !important; color:var(--text2) !important; border-radius:10px; }}
[class*="st-key-nsbox-"] .stButton > button p {{ color:inherit !important; }}
[class*="st-key-nsbox-"] .stButton > button:hover {{ background:rgba(var(--rgb),.14) !important; color:var(--text) !important; }}
/* Claude section: orange theme (approximate Claude orange) */
[class*="st-key-claudebox"] {{ --o:217,119,87; margin-top:22px; padding:20px 22px 22px !important; border-radius:24px !important;
  background:radial-gradient(520px 260px at 100% 0%, rgba(var(--o),.26), transparent 70%), linear-gradient(160deg, rgba(var(--o),.12), rgba(var(--o),.03)), var(--s3) !important;
  border:1px solid rgba(var(--o),.65) !important; box-shadow:0 0 0 1px rgba(var(--o),.12), 0 28px 60px -26px rgba(var(--o),.45); }}
.nk-claude-h {{ font-size:22px; font-weight:700; letter-spacing:-0.03em; color:rgb(var(--o,217,119,87)); }}
.nk-claude-h span {{ margin-right:6px; }}
[class*="st-key-claudebox"] .nk-note {{ color:rgba(245,245,247,.75); }}
[class*="st-key-claudebox"] .stButton > button[kind="primary"] {{ background:rgb(var(--o)) !important; border:1px solid rgb(var(--o)) !important; color:#1A0E0A !important; font-weight:600; }}
[class*="st-key-claudebox"] .stButton > button[kind="primary"]:hover {{ filter:brightness(1.08); transform:translateY(-1px); }}
[class*="st-key-claudebox"] .stFormSubmitButton > button {{ background:rgb(var(--o)) !important; border:1px solid rgb(var(--o)) !important; color:#1A0E0A !important; font-weight:600; }}
[class*="st-key-claudebox"] .stButton > button:not([kind="primary"]) {{ border-color:rgba(var(--o),.45); }}
[class*="st-key-claudebox"] .stButton > button:not([kind="primary"]):hover {{ border-color:rgb(var(--o)); color:rgb(var(--o)); }}
/* Left panel */
.nk-brand {{ display:flex; align-items:center; gap:12px; margin:2px 0 22px; }}
.nk-brand-t {{ font-size:24px; font-weight:700; letter-spacing:-0.04em; line-height:1.1; white-space:nowrap; }}
.nk-sc {{ --rgb:167,139,250; border-radius:14px; padding:10px 13px 12px; margin-bottom:10px;
  background:radial-gradient(220px 110px at 100% 0%, rgba(var(--rgb),.20), transparent 70%), linear-gradient(160deg, rgba(var(--rgb),.09), rgba(var(--rgb),.02)), var(--s3);
  border:1px solid rgba(var(--rgb),.55); box-shadow:0 10px 24px -18px rgba(0,0,0,.9); }}
.nk-sc-t {{ --rgb:94,234,212; }} .nk-sc-s {{ --rgb:125,180,255; }}
.nk-sc-p {{ --rgb:240,166,202; }} .nk-sc-o {{ --rgb:253,186,116; }}
.nk-sc-l {{ font-size:10.5px; font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:rgb(var(--rgb)); margin-bottom:6px; }}
.nk-sc-v {{ font-size:14.5px; font-weight:600; word-break:break-all; }}
.nk-sc-conn {{ display:flex; align-items:center; gap:7px; font-size:12.5px; color:var(--green); margin-top:7px; }}
.nk-chip {{ display:inline-block; font-size:13.5px; font-weight:600; color:rgb(var(--rgb)); background:rgba(var(--rgb),.12);
  border:1px solid rgba(var(--rgb),.4); border-radius:999px; padding:3px 12px; }}
.nk-big {{ font-size:30px; font-weight:700; letter-spacing:-0.03em; line-height:1.1; }}
.nk-big span {{ font-size:13px; font-weight:500; color:var(--text2); letter-spacing:0; margin-left:6px; }}
.nk-bar {{ height:7px; border-radius:999px; background:rgba(245,245,247,.1); margin:12px 0 12px; overflow:hidden; }}
.nk-bar i {{ display:block; height:100%; border-radius:999px; transition:width .4s var(--ease); }}
.nk-sc-row {{ display:flex; justify-content:space-between; align-items:center; font-size:13px; color:var(--text2); margin-top:4px; }}
.nk-sc-row .dot {{ margin-right:8px; }}
.nk-sc-row b {{ color:var(--text); font-weight:600; }}
.nk-step {{ display:flex; gap:10px; align-items:flex-start; font-size:12.5px; line-height:1.55; color:var(--text2); margin-top:8px; }}
.nk-step b {{ flex:none; width:20px; height:20px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:11px; color:var(--champagne); border:1px solid rgba(217,178,106,.5); background:rgba(217,178,106,.1); }}
/* Big boundary box around the whole "Pods by namespace" section */
[class*="st-key-podsection"] {{ border-radius:28px !important; padding:6px 20px 14px !important; margin-top:8px;
  background:radial-gradient(700px 300px at 0% 0%, rgba(167,139,250,.10), transparent 70%), rgba(245,245,247,.02) !important;
  border:1px solid rgba(245,245,247,.2) !important; box-shadow:0 30px 70px -40px rgba(0,0,0,.9); }}
[class*="st-key-podsection"] .nk-h {{ margin-top:16px; }}
[class*="st-key-nsbox-"] [data-testid="stCaptionContainer"] {{ margin-top:2px; }}
[class*="st-key-nsbox-"] .nk-name {{ padding-bottom:4px; }}
/* Role boxes: fill the page on the landing screen, with a professional "How to use" panel */
.nk-role-steps {{ margin-top:22px; display:flex; flex-direction:column; }}
.nk-howto {{ font-size:11.5px; font-weight:600; letter-spacing:.18em; text-transform:uppercase; color:rgb(var(--rgb)); margin-bottom:4px; }}
.nk-rstep {{ display:flex; gap:14px; align-items:center; font-size:15px; line-height:1.5; color:var(--text2);
  padding:11px 0; border-top:1px solid rgba(245,245,247,.08); }}
.nk-rstep b {{ flex:none; width:26px; height:26px; border-radius:8px; display:flex; align-items:center; justify-content:center;
  font-size:12.5px; color:rgb(var(--rgb)); border:1px solid rgba(var(--rgb),.55); background:rgba(var(--rgb),.12); }}
.nk-role:not(.compact):not(.slim) {{ aspect-ratio:4 / 5; min-height:0; padding:36px 34px 32px; border-radius:32px; display:flex; flex-direction:column; }}
.nk-role:not(.compact):not(.slim) .nk-ico {{ width:68px; height:68px; border-radius:20px; }}
.nk-role:not(.compact):not(.slim) .nk-ico svg {{ width:32px; height:32px; }}
.nk-role:not(.compact):not(.slim) .nk-role-t {{ font-size:30px; font-weight:600; letter-spacing:-0.035em; }}
.nk-role:not(.compact):not(.slim) .nk-num2 {{ font-size:13px; }}
.nk-role:not(.compact):not(.slim) .nk-rhead {{ gap:20px; }}
.nk-role:not(.compact):not(.slim) .nk-role-steps {{ margin-top:auto; padding-top:24px; }}
.nk-role:not(.compact):not(.slim) .nk-rstep {{ font-size:15.5px; padding:13px 0; gap:14px; }}
.nk-role:not(.compact):not(.slim) .nk-rstep b {{ width:30px; height:30px; font-size:14px; border-radius:9px; }}
.nk-role:not(.compact):not(.slim) .nk-howto {{ font-size:12.5px; margin-bottom:6px; }}
.nk-role.compact .nk-role-steps {{ margin-top:12px; }}
.nk-role.compact .nk-rstep {{ font-size:13.5px; padding:7px 0; }}
.nk-hero {{ display:flex; align-items:center; gap:16px; margin:4px 0 6px; }}
.nk-hero-t {{ font-size:56px; font-weight:700; letter-spacing:-0.045em; line-height:1.05; }}
.nk-hero-s {{ font-size:24px; font-weight:600; letter-spacing:-0.02em; margin:4px 0 18px; }}
.nk-role.compact {{ padding:16px 22px 18px; }}
.nk-role.compact .nk-role-d {{ margin-top:10px; font-size:13.5px; }}
.nk-rhead {{ display:flex; align-items:center; gap:14px; }}
.nk-ico {{ width:48px; height:48px; flex:none; border-radius:14px; display:flex; align-items:center; justify-content:center;
  color:var(--c); background:rgba(var(--rgb),.10); border:1px solid rgba(var(--rgb),.45); }}
.nk-role-t {{ font-size:22px; font-weight:500; letter-spacing:-0.02em; color:var(--text); flex:1; }}
.nk-num2 {{ font-size:12px; letter-spacing:.12em; color:rgba(var(--rgb),.55); align-self:flex-start; }}
.nk-role-d {{ color:var(--text2); font-size:14px; line-height:1.65; margin-top:18px; max-width:92%; }}
.nk-role.slim {{ padding:16px 22px; border-radius:20px; }}
.nk-role.slim .nk-role-t {{ font-size:19px; color:var(--c); font-weight:600; }}
.nk-role.slim .nk-role-d {{ font-size:13.5px; margin-top:6px; }}
.nk-attn-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }}
.nk-line {{ margin-top:12px; font-size:15px; line-height:1.5; }}
.nk-k {{ color:var(--text2); }}
.nk-facts {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px; padding-top:14px; border-top:1px solid var(--line); }}
.nk-facts div span {{ display:block; color:var(--text2); font-size:12px; }}
.nk-facts div b {{ font-weight:600; font-size:14px; word-break:break-all; }}
.nk-commit {{ margin-top:14px; padding:14px 16px; border:1px solid var(--line); border-radius:14px; background:rgba(245,245,247,.03); }}
.nk-commit .who {{ font-weight:600; }}
.nk-commit a {{ color:var(--champagne); text-decoration:none; }}
.nk-commit a:hover {{ text-decoration:underline; }}
.nk-commit code, .nk-line code {{ background:rgba(245,245,247,.08); border-radius:6px; padding:1px 6px; font-size:12.5px; }}
.nk-note {{ color:var(--text2); font-size:13px; margin-top:8px; }}

.nk-mark .dotc {{ fill:currentColor; }}
.nk-mark .arc {{ stroke:currentColor; fill:none; stroke-width:2.2; stroke-linecap:round; }}
.nk-mark.warn {{ color:var(--champagne); }} .nk-mark.ok {{ color:var(--green); }} .nk-mark.work {{ color:var(--violet); animation:breathe 2.4s var(--ease) infinite; }}
@keyframes breathe {{ 0%,100% {{ opacity:.55; }} 50% {{ opacity:1; }} }}

/* ChatGPT-style chat: user = right-hand bubble, assistant = plain left text, no avatars */
[data-testid="stChatMessage"] {{ background:transparent; border:none; border-radius:0; padding:6px 0;
  width:100%; max-width:100%; }}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"],
[data-testid="stChatMessageAvatarCustom"] {{ display:none; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
  flex-direction:row-reverse; width:fit-content; max-width:70%; margin-left:auto;
  background:rgba(245,245,247,.08); border-radius:22px; padding:10px 18px; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {{ margin-right:auto; }}
@media (max-width:760px) {{ [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ max-width:90%; }} }}
[data-testid="stChatInput"] {{ border-radius:28px; }}
.stButton > button {{ border-radius:12px; border:1px solid var(--line); background:var(--cell); color:var(--text);
  font-weight:500; transition:transform .08s var(--ease), border-color .2s var(--ease); }}
.stButton > button:hover {{ border-color:var(--champagne); color:var(--champagne); }}
.stButton > button:active {{ transform:scale(.97); }}
.stButton > button[kind="primary"], .stButton > button[kind="primary"] p {{ color:#1A1205 !important; font-weight:600; }}
[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:16px; background:var(--cell); }}
[data-testid="stSidebar"] .stButton > button {{ text-align:left; justify-content:flex-start; width:100%; }}

/* Keyboard focus: a clear outline when tabbing */
.nk-cover:focus, .nk-cover:focus-visible {{ outline:none !important; }}
.nk-role:has(.nk-cover:focus-visible) {{ outline:3px solid var(--champagne); outline-offset:4px; }}
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {{ outline:2px solid var(--champagne) !important; outline-offset:2px; }}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-testid="stChatInput"]:focus-within {{ outline:2px solid var(--champagne); outline-offset:2px; }}
@media (max-width:760px) {{
  .nk-tiles {{ grid-template-columns:1fr; }} .nk-facts {{ grid-template-columns:repeat(2,1fr); }}
}}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
</style>
"""


def mark(state: str = "warn", size: int = 34) -> str:
    """The Devops-Konnekt mark: a connector arc and a dot. state: warn | ok | work."""
    return (
        f'<svg class="nk-mark {state}" width="{size}" height="{size}" viewBox="0 0 34 34" aria-hidden="true">'
        '<path class="arc" d="M5 24 C 8 10, 22 6, 28 12"/>'
        '<circle class="dotc" cx="26" cy="22" r="5"/></svg>'
    )


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def inline(text: str) -> str:
    """Escape text, then turn `code` spans into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(text))


LIGHT_CSS = """
<style>
:root {
  --ground:#F6F4EF; --cell:#FFFFFF; --text:#1A1A1D; --text2:rgba(26,26,29,.66); --line:rgba(26,26,29,.14);
  --champagne:#9A6B1F; --violet:#6D4FD6; --red:#C0392B; --green:#18835C;
  --s1:#FFFFFF; --s2:#F1EEE6; --s3:#FFFFFF;
}
.stApp { background:var(--ground) !important; color:var(--text) !important; }
[data-testid="stSidebar"] { background:#EFECE4 !important; }
.stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp div[data-testid="stMarkdownContainer"],
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stWidgetLabel"] { color:var(--text) !important; }
.nk-sc-l, .nk-howto, .nk-claude-h, .nk-corr-h, .nk-name { color:inherit; }
.nk-role-t { color:var(--text) !important; } .nk-role-d, .nk-rstep, .nk-step, .nk-sc-row, .nk-note, .nk-k, .nk-meta { color:var(--text2) !important; }
.nk-rstep > .nk-rolelink, .nk-rstep span { color:var(--text2) !important; }
.nk-role, .nk-sc, [class*="st-key-nsbox-"], [class*="st-key-podsection"], .nk-card, .nk-tile {
  background:#FFFFFF !important; box-shadow:0 10px 28px -18px rgba(26,26,29,.35) !important; }
[class*="st-key-podsection"] { background:rgba(255,255,255,.55) !important; }
.stButton > button { background:#FFFFFF !important; color:var(--text) !important; border-color:var(--line) !important; }
.stButton > button p { color:inherit !important; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background:rgba(26,26,29,.07) !important; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-testid="stChatInput"] { background:#FFFFFF !important; border-color:var(--line) !important; }
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-testid="stChatInput"] textarea { color:var(--text) !important; -webkit-text-fill-color:var(--text) !important; }
[data-testid="stHeader"] { background:transparent !important; }
label:has(input[role="switch"]:not(:checked)) > div:first-of-type { background:rgba(26,26,29,.28) !important; }
.stMarkdownColoredText { filter:saturate(1.4) brightness(.8); }
.nk-sc-l, .nk-chip, .nk-corr-h { filter:brightness(.55) saturate(1.3); }
</style>
"""
