from __future__ import annotations

from pathlib import Path

import streamlit as st


SAMPLE_FILES_DIR = Path(__file__).parent / "assets" / "sample-files"


def render_sample_files() -> None:
    st.write("Dar clic en los botones correspondientes para bajar archivos de prueba")

    st.write("Archivo con la definición de bugs")
    st.download_button(
        "Bug dataset",
        data=(SAMPLE_FILES_DIR / "demo_bug_dataset-01.csv").read_bytes(),
        file_name="demo_bug_dataset-01.csv",
        mime="text/csv",
        key="download_sample_bug_dataset",
        on_click="ignore",
    )

    st.write("Salida de comandos show config de equipos Nexus")
    st.download_button(
        "Nexus configuration",
        data=(SAMPLE_FILES_DIR / "nexus-demo-120-equipos.zip").read_bytes(),
        file_name="nexus-demo-120-equipos.zip",
        mime="application/zip",
        key="download_sample_nexus_configuration",
        on_click="ignore",
    )
