from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st


PAGE_TITLE = "Independent analysis of known bugs in network platforms."
SERVICE_NAME = "Independent Bug Analysis"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    logo = Path(__file__).parent / "assets" / "astrogato-labs.png"
    encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_footer() -> None:
    st.markdown(
        f"""<style>
.astrogato-footer {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    gap: 1.5rem;
    margin-top: 2rem;
    padding: 1.5rem 0;
    border-top: 1px solid rgba(128, 128, 128, 0.3);
}}
.astrogato-footer p {{ margin: 0; text-align: left; }}
.astrogato-footer a {{
    grid-column: 2;
    justify-self: center;
    display: block;
    max-width: 100%;
    padding: 0.75rem;
    border-radius: 0.5rem;
    background: #0e1117;
}}
.astrogato-footer img {{
    display: block;
    width: 320px;
    max-width: 100%;
    height: auto;
}}
@media (max-width: 760px) {{
    .astrogato-footer {{ grid-template-columns: minmax(0, 1fr); }}
    .astrogato-footer a {{ grid-column: 1; }}
}}
</style>
<footer class="astrogato-footer">
    <p>A demo mission by:</p>
    <a href="https://astrogatolabs.com.mx/" target="_blank" rel="noopener noreferrer"
       aria-label="Visit Astrogato Labs">
        <img src="{_logo_data_uri()}" alt="Astrogato Labs" width="2132" height="738">
    </a>
</footer>""",
        unsafe_allow_html=True,
    )
