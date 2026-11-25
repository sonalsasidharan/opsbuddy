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

[data-testid="stChatMessage"] {{ background:var(--cell); border:1px solid var(--line); border-radius:20px; }}
[data-testid="stChatInput"] {{ border-radius:20px; }}
.stButton > button {{ border-radius:12px; border:1px solid var(--line); background:var(--cell); color:var(--text);
  font-weight:500; transition:transform .08s var(--ease), border-color .2s var(--ease); }}
.stButton > button:hover {{ border-color:var(--champagne); color:var(--champagne); }}
.stButton > button:active {{ transform:scale(.97); }}
[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:16px; background:var(--cell); }}
[data-testid="stSidebar"] .stButton > button {{ text-align:left; justify-content:flex-start; width:100%; }}

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
