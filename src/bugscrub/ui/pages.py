from __future__ import annotations

from io import BytesIO
import json
import logging
from pathlib import Path
import time

import altair as alt
import pandas as pd
import streamlit as st

from bugscrub.bug_engine.dataset import load_bug_dataset, validate_bug_dataset_file
from bugscrub.bug_engine.service import BugEngine
from bugscrub.bug_engine.risk_summary import (
    SEVERITY_COLORS,
    available_dashboard_filters,
    build_inventory_overview_metrics,
    build_risk_dashboard_data,
    normalize_pareto_threshold,
)
from bugscrub.config import Settings
from bugscrub.db.duckdb_store import DuckDBStore
from bugscrub.discrepancies.service import compare_inventory_vs_parsed
from bugscrub.exporters.excel import ExcelExporter
from bugscrub.exporters.executive import ExecutiveExporter
from bugscrub.exporters.powerpoint import PowerPointExporter
from bugscrub.exporters.risk_charts import BUG_BREAKDOWN_SEVERITY_SEQUENCE
from bugscrub.intake.uploads import UPLOAD_SLOTS, build_session_id, find_saved_upload, save_uploads, validate_uploads
from bugscrub.normalization.service import Normalizer, generate_inventory_workbook_from_parsed_records
from bugscrub.observability import build_log_path, get_logger, log_event, log_exception
from bugscrub.parsers.service import parse_runtime_session
from bugscrub.reset import reset_application_data
from bugscrub.ui.branding import PAGE_TITLE, SERVICE_NAME
from bugscrub.ui.sample_files import render_sample_files


def render_home(settings: Settings, store: DuckDBStore) -> None:
    st.title(PAGE_TITLE)
    st.caption(SERVICE_NAME)

    analysis_tab, sample_files_tab = st.tabs([SERVICE_NAME, "Archivos de prueba"])
    with analysis_tab:
        render_analysis_page(settings=settings, store=store)
    with sample_files_tab:
        render_sample_files()


def render_analysis_page(settings: Settings, store: DuckDBStore) -> None:
    if st.button(
        "Limpiar",
        key="clear_analysis",
        help="Elimina definitivamente las cargas, los catálogos, el historial y los resultados de toda esta instalación.",
    ):
        reset_error = False
        try:
            reset_application_data(settings, store)
        except Exception as error:
            log_exception(get_logger("ui.reset"), "application_reset_failed", "Application reset failed.", error=error)
            reset_error = True
        # Clear stale results even after a partial failure, so a rerun cannot
        # recreate exports from the session being removed.
        generation = st.session_state.get("upload_generation", 0) + 1
        st.session_state.clear()
        st.session_state["upload_generation"] = generation
        st.session_state["application_reset_notice"] = "error" if reset_error else "success"
        st.rerun()

    reset_notice = st.session_state.pop("application_reset_notice", None)
    if reset_notice == "success":
        st.success("Sistema limpio, como una instalación nueva. Ya puedes subir los archivos de prueba.")
    elif reset_notice == "error":
        st.error("La limpieza no se completó. Puede haber datos pendientes de borrar. Revisa el log y vuelve a pulsar Limpiar.")

    refresh_bug_dataset_state(store)

    left, right = st.columns(2)
    with left:
        st.subheader("Runtime")
        st.write(f"DuckDB path: `{settings.duckdb_path}`")
        st.write(f"Runtime root: `{settings.runtime_root}`")
        st.write(f"Structured log: `{build_log_path(settings.runtime_root)}`")
        st.write(f"{SERVICE_NAME} · API habilitada: `{settings.api_enabled}`")
    with right:
        st.subheader("Current Scope")
        st.write(
            [
                "Upload and activate a local CSV/XLSX bug dataset to populate the bug catalog.",
                "Upload, validate, and harden required source files before processing.",
                "Parse the uploaded command bundle as Nexus or Catalyst.",
                "Parse the Excel inventory and normalize key columns.",
                "Compare inventory versus discovered data and build paired discrepancy rows.",
                "Correlate the active bug dataset by version, platform, and features.",
                "Persist datasets in DuckDB and export operational Excel plus executive PDF and PowerPoint outputs.",
            ]
        )

    st.divider()
    render_bug_dataset_manager(settings=settings, store=store)
    st.divider()
    render_upload_page(settings=settings, store=store)


def render_bug_dataset_manager(settings: Settings, store: DuckDBStore) -> None:
    logger = get_logger("ui.dataset")
    st.subheader("Bug Dataset Catalog")
    st.write("Upload a CSV or Excel bug dataset, validate its schema, and choose the active catalog used by the bug engine.")

    active_dataset = store.fetch_active_bug_dataset()
    if active_dataset:
        st.success(
            f"Active bug dataset: `{active_dataset['dataset_name']}` with {active_dataset['row_count']} bug rows."
        )
    else:
        st.info("No hay un catálogo de bugs activo. Sube y activa un archivo CSV o Excel para comenzar.")

    generation = st.session_state.get("upload_generation", 0)
    with st.form(f"bug-dataset-upload-form-{generation}", clear_on_submit=True):
        dataset_name = st.text_input(
            "Dataset name",
            placeholder="Optional display name; defaults to the uploaded file name.",
        )
        dataset_file = st.file_uploader(
            "Bug dataset file",
            type=["csv", "xlsx", "xlsm"],
            key=f"bug_dataset_file_upload_{generation}",
            accept_multiple_files=False,
            help="Required columns: bug_id, headline, product_scope, affected_releases, fixed_releases, trigger_features, severity, recommended_action.",
        )
        upload_submitted = st.form_submit_button("Upload and activate bug dataset", type="primary")

    if upload_submitted:
        if dataset_file is None:
            st.error("Select a bug dataset file before uploading.")
        else:
            validation_errors = validate_bug_dataset_file(dataset_file.name)
            if validation_errors:
                st.error("Bug dataset validation failed.")
                for error in validation_errors:
                    st.write(f"- {error}")
            else:
                dataset_dir = Path(settings.runtime_root) / "bug-datasets" / build_session_id()
                dataset_dir.mkdir(parents=True, exist_ok=True)
                dataset_path = dataset_dir / dataset_file.name
                dataset_path.write_bytes(dataset_file.getbuffer())
                try:
                    dataset_definition = load_bug_dataset(
                        dataset_path,
                        dataset_name=dataset_name.strip() or None,
                    )
                    store.save_bug_dataset(dataset_definition, activate=True)
                    refresh_bug_dataset_state(store)
                    log_event(
                        logger,
                        logging.INFO,
                        "bug_dataset_activated",
                        "Bug dataset uploaded and activated.",
                        dataset_id=dataset_definition.dataset_id,
                        dataset_name=dataset_definition.dataset_name,
                        row_count=dataset_definition.row_count,
                    )
                    st.success(
                        f"Uploaded and activated bug dataset `{dataset_definition.dataset_name}` with {dataset_definition.row_count} rows."
                    )
                    if dataset_definition.warnings:
                        st.warning("The uploaded bug dataset produced validation warnings.")
                        for warning in dataset_definition.warnings:
                            st.write(f"- {warning}")
                except Exception as error:
                    log_exception(
                        logger,
                        "bug_dataset_upload_failed",
                        "Bug dataset upload failed.",
                        error=error,
                        source_file=dataset_file.name,
                    )
                    st.error(f"Bug dataset upload failed: {error}")

    active_dataset = store.fetch_active_bug_dataset()
    stored_datasets = store.fetch_bug_datasets()
    if stored_datasets:
        st.caption("Stored bug datasets")
        st.dataframe(pd.DataFrame(stored_datasets), use_container_width=True, hide_index=True)

        with st.form(f"bug-dataset-activate-form-{generation}", clear_on_submit=False):
            dataset_ids = [str(dataset["dataset_id"]) for dataset in stored_datasets]
            default_index = 0
            if active_dataset:
                active_id = str(active_dataset["dataset_id"])
                if active_id in dataset_ids:
                    default_index = dataset_ids.index(active_id)

            selected_dataset_id = st.selectbox(
                "Choose a stored dataset to activate",
                options=dataset_ids,
                index=default_index,
                format_func=lambda dataset_id: format_bug_dataset_option(dataset_id, stored_datasets),
            )
            activate_submitted = st.form_submit_button("Set active bug dataset")

        if activate_submitted:
            try:
                store.activate_bug_dataset(selected_dataset_id)
                refresh_bug_dataset_state(store)
                log_event(
                    logger,
                    logging.INFO,
                    "bug_dataset_selected",
                    "Stored bug dataset activated.",
                    dataset_id=selected_dataset_id,
                )
                st.success(f"Activated bug dataset `{selected_dataset_id}`.")
            except Exception as error:
                log_exception(
                    logger,
                    "bug_dataset_activation_failed",
                    "Stored bug dataset activation failed.",
                    error=error,
                    dataset_id=selected_dataset_id,
                )
                st.error(f"Unable to activate bug dataset: {error}")
    else:
        st.caption("Stored bug datasets")
        st.info("No uploaded bug datasets have been stored in DuckDB yet.")

    catalog_rows = store.fetch_bug_catalog()
    st.caption("Active bug catalog preview")
    if catalog_rows:
        st.dataframe(pd.DataFrame(catalog_rows), use_container_width=True, hide_index=True)
    else:
        st.info("El catálogo de bugs está vacío.")


def render_upload_page(settings: Settings, store: DuckDBStore) -> None:
    logger = get_logger("ui.upload")
    st.subheader("Upload Inputs")
    st.write(
        "Provide either an existing Excel inventory or only the command outputs. If no Excel inventory is uploaded, the app will generate one automatically from the parsed `show` files before normalization."
    )

    generation = st.session_state.get("upload_generation", 0)
    with st.form(f"upload-form-{generation}", clear_on_submit=False):
        platform_family = st.selectbox(
            "Platform family",
            options=["Nexus", "Catalyst"],
            index=0,
            help="Select the parser family that matches the uploaded command outputs.",
        )
        uploads: dict[str, object | None] = {}
        for slot in UPLOAD_SLOTS:
            allowed_types = ", ".join(sorted(slot.allowed_extensions))
            uploads[slot.key] = st.file_uploader(
                label=f"{slot.label} ({allowed_types})",
                type=[extension.lstrip(".") for extension in sorted(slot.allowed_extensions)],
                key=f"{slot.key}_{generation}",
                accept_multiple_files=False,
                help=f"Detected input type will be recorded as `{slot.detected_type}`.",
            )

        submitted = st.form_submit_button("Validate and save uploads", type="primary")

    if submitted:
        errors = validate_uploads(uploads)
        if errors:
            log_event(
                logger,
                logging.WARNING,
                "upload_validation_failed",
                "Upload validation failed before processing.",
                platform_family=platform_family,
                error_count=len(errors),
                errors=errors,
            )
            st.error("Upload validation failed. Fix the items below and try again.")
            for error in errors:
                st.write(f"- {error}")
        else:
            progress_bar = st.progress(0, text="Starting protected session processing...")
            progress_status = st.empty()
            started_at = time.perf_counter()
            session_dir: Path | None = None

            try:
                update_progress(progress_bar, progress_status, 10, "Saving validated uploads into the runtime area...")
                session_dir, saved_files = save_uploads(
                    upload_map={slot.key: uploads[slot.key] for slot in UPLOAD_SLOTS},
                    runtime_root=settings.runtime_root,
                )
                log_event(
                    logger,
                    logging.INFO,
                    "uploads_saved",
                    "Validated uploads were saved to the runtime area.",
                    session_id=session_dir.name,
                    saved_file_count=len(saved_files),
                )

                update_progress(progress_bar, progress_status, 30, "Parsing command bundles...")
                parsed_session = parse_runtime_session(platform_family, session_dir)

                inventory_path: Path | None
                generated_inventory_path: Path | None = None
                inventory_upload = find_saved_upload(saved_files, "excel_inventory")
                if inventory_upload is not None:
                    inventory_path = Path(inventory_upload.saved_path)
                else:
                    update_progress(
                        progress_bar,
                        progress_status,
                        45,
                        "Generating an inventory workbook from parsed command outputs...",
                    )
                    generated_inventory_path = session_dir / "generated_inventory.xlsx"
                    inventory_path = generate_inventory_workbook_from_parsed_records(
                        parsed_records=parsed_session.parsed_records,
                        destination=generated_inventory_path,
                        platform_family=parsed_session.platform_family,
                    )
                    log_event(
                        logger,
                        logging.INFO,
                        "inventory_generated_from_show_files",
                        "Inventory workbook was generated from parsed command outputs.",
                        session_id=session_dir.name,
                        generated_inventory_path=str(generated_inventory_path),
                        generated_rows=len(parsed_session.parsed_records),
                    )

                update_progress(progress_bar, progress_status, 50, "Normalizing parsed devices and workbook data...")
                normalizer = Normalizer()
                batch = normalizer.normalize_parsed_devices(
                    parsed_records=parsed_session.parsed_records,
                    platform_family=parsed_session.platform_family,
                    support_level=parsed_session.support_level,
                    session_dir=session_dir,
                    inventory_path=inventory_path,
                    source_count=len(saved_files),
                    warnings=parsed_session.warnings,
                )

                update_progress(progress_bar, progress_status, 70, "Comparing inventory versus discovered devices...")
                batch.discrepancy_rows = compare_inventory_vs_parsed(
                    session_id=batch.session_id,
                    inventory_rows=batch.inventory_rows,
                    parsed_devices=batch.devices,
                )

                update_progress(progress_bar, progress_status, 85, "Correlating bug findings and refreshing DuckDB...")
                active_bug_catalog = store.fetch_bug_catalog()
                batch.bug_findings = [
                    finding.to_record()
                    for finding in BugEngine(bug_records=active_bug_catalog).run(batch)
                ]
                store.save_inventory_batch(batch)

                update_progress(progress_bar, progress_status, 100, "Session processing completed successfully.")
                processing_seconds = round(time.perf_counter() - started_at, 2)

                st.session_state["platform_family"] = platform_family
                st.session_state["upload_manifest"] = [saved_file.to_record() for saved_file in saved_files]
                st.session_state["upload_session_dir"] = str(session_dir)
                st.session_state["parsed_preview"] = list(parsed_session.parsed_records)
                st.session_state["normalized_devices"] = [device.to_record() for device in batch.devices]
                st.session_state["inventory_rows"] = [row.to_record() for row in batch.inventory_rows]
                st.session_state["discrepancy_rows"] = [row.to_record() for row in batch.discrepancy_rows]
                st.session_state["bug_findings"] = list(batch.bug_findings)
                st.session_state["inventory_workbook"] = [batch.inventory_workbook.to_record()]
                st.session_state["generated_inventory_path"] = str(generated_inventory_path) if generated_inventory_path else ""
                st.session_state["generated_inventory_download_name"] = (
                    generated_inventory_path.name if generated_inventory_path else ""
                )
                st.session_state["inventory_workbook_origin"] = "generated" if generated_inventory_path else "uploaded"
                st.session_state["session_warnings"] = list(batch.warnings)
                st.session_state["processing_metrics"] = build_processing_metrics(
                    saved_files=saved_files,
                    parsed_bundle_count=len(parsed_session.parsed_records),
                    batch=batch,
                    processing_seconds=processing_seconds,
                )
                st.session_state["duckdb_devices"] = store.fetch_devices_for_session(batch.session_id)
                st.session_state["duckdb_inventory_rows"] = store.fetch_inventory_rows_for_session(batch.session_id)
                st.session_state["duckdb_discrepancy_rows"] = store.fetch_discrepancy_rows_for_session(batch.session_id)
                st.session_state["duckdb_bug_findings"] = store.fetch_bug_findings_for_session(batch.session_id)
                st.session_state["duckdb_bug_catalog"] = store.fetch_bug_catalog()
                st.session_state["duckdb_bug_datasets"] = store.fetch_bug_datasets()
                st.session_state["duckdb_active_bug_dataset"] = store.fetch_active_bug_dataset()
                st.session_state["duckdb_sessions"] = store.fetch_sessions()
                st.session_state["current_session_id"] = batch.session_id

                log_event(
                    logger,
                    logging.INFO,
                    "session_processed",
                    "Upload session processed successfully.",
                    session_id=batch.session_id,
                    platform_family=batch.platform_family,
                    uploaded_files=len(saved_files),
                    parsed_bundles=len(parsed_session.parsed_records),
                    normalized_devices=len(batch.devices),
                    discrepancy_pairs=count_discrepancy_pairs(batch.discrepancy_rows),
                    bug_findings=len(batch.bug_findings),
                    warning_count=len(batch.warnings),
                    processing_seconds=processing_seconds,
                )
                st.success(
                    f"Saved {len(saved_files)} uploaded files, parsed {len(parsed_session.parsed_records)} command bundle(s), and persisted session `{session_dir.name}` in {processing_seconds:.2f}s."
                )
            except Exception as error:
                update_progress(progress_bar, progress_status, 100, "Session processing stopped because an error was detected.")
                log_exception(
                    logger,
                    "session_processing_failed",
                    "Upload session processing failed.",
                    error=error,
                    platform_family=platform_family,
                    session_dir=str(session_dir) if session_dir else "",
                )
                st.error("Session processing failed. Review the uploaded files and the runtime log for more detail.")
                st.write(f"- {error.__class__.__name__}: {error}")
                st.caption(f"Structured log: `{build_log_path(settings.runtime_root)}`")

    render_processing_metrics(settings)
    render_manifest_table()
    render_risk_dashboard()
    render_inventory_workbook_table()
    render_parsed_preview_table()
    render_inventory_rows_table()
    render_discrepancy_rows_table()
    render_bug_findings_table()
    render_export_section(settings=settings, store=store)
    render_normalized_preview_table()
    render_persisted_preview_table()

    with st.expander("Runtime check"):
        st.write("Use `./scripts/run-app.ps1` as the standard command to launch the app from the repo .venv.")
        st.code(f"Store class: {store.__class__.__name__}")
        st.code(f"Runtime directory base: {Path(settings.runtime_root)}")
        st.code(f"DuckDB file: {settings.duckdb_path}")
        st.code(f"Structured log: {build_log_path(settings.runtime_root)}")


def render_manifest_table() -> None:
    manifest = st.session_state.get("upload_manifest", [])
    session_dir = st.session_state.get("upload_session_dir")

    st.subheader("Uploaded Files")
    if not manifest:
        st.info("No files have been saved yet. Complete the upload form to create a runtime session.")
        return

    if session_dir:
        st.caption(f"Latest runtime session: `{session_dir}`")

    frame = pd.DataFrame(manifest)
    frame = frame.rename(
        columns={
            "input_label": "Input",
            "detected_type": "Detected input type",
            "original_name": "Original file",
            "saved_path": "Saved path",
            "size_bytes": "Size (bytes)",
        }
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_processing_metrics(settings: Settings) -> None:
    metrics = st.session_state.get("processing_metrics", {})

    st.subheader("Processing Metrics")
    if not metrics:
        st.info("Session metrics will appear here after a successful processing run.")
        return

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Uploaded files", int(metrics.get("uploaded_files", 0)))
    col2.metric("Parsed bundles", int(metrics.get("parsed_bundles", 0)))
    col3.metric("Normalized devices", int(metrics.get("normalized_devices", 0)))
    col4.metric("Discrepancy pairs", int(metrics.get("discrepancy_pairs", 0)))
    col5.metric("Bug findings", int(metrics.get("bug_findings", 0)))
    col6.metric("Warnings", int(metrics.get("warning_count", 0)))
    st.caption(
        f"Processing time: `{metrics.get('processing_seconds', 0.0):.2f}s` | Structured log: `{build_log_path(settings.runtime_root)}`"
    )


def render_risk_dashboard() -> None:
    devices = st.session_state.get("duckdb_devices", [])
    inventory_rows = st.session_state.get("duckdb_inventory_rows", [])
    discrepancy_rows = st.session_state.get("duckdb_discrepancy_rows", [])
    bug_findings = st.session_state.get("duckdb_bug_findings", [])
    inventory_origin = str(st.session_state.get("inventory_workbook_origin", "uploaded") or "uploaded")

    st.subheader("Risk Summary")
    if not devices:
        st.info("The prioritization dashboard will appear here after a session has been processed.")
        return

    overview_metrics = build_inventory_overview_metrics(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=discrepancy_rows,
        bug_findings=bug_findings,
        customer_inventory_uploaded=inventory_origin == "uploaded",
    )
    render_overview_metric_cards(overview_metrics)
    render_dataset_download_row(discovered_devices=devices, discrepancy_rows=discrepancy_rows)

    filters = available_dashboard_filters(devices=devices, inventory_rows=inventory_rows, bug_findings=bug_findings)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        selected_hostnames = st.multiselect(
            "Equipo",
            options=filters["hostnames"],
            default=filters["hostnames"],
            key="risk_hostname_filter",
        )
    with col2:
        selected_platforms = st.multiselect(
            "Plataforma",
            options=filters["platform_families"],
            default=filters["platform_families"],
            key="risk_platform_filter",
        )
    with col3:
        selected_versions = st.multiselect(
            "Versión actual",
            options=filters["versions"],
            default=[],
            key="risk_version_filter",
        )
    with col4:
        selected_features = st.multiselect(
            "Feature",
            options=filters["features"],
            default=[],
            key="risk_feature_filter",
        )
    with col5:
        selected_bug_ids = st.multiselect(
            "Bug / CVE / FN / PSIRT",
            options=filters["bug_ids"],
            default=[],
            key="risk_bug_id_filter",
        )

    col6, col7, col8 = st.columns(3)
    with col6:
        selected_finding_types = st.multiselect(
            "Tipo de hallazgo",
            options=filters["finding_types"],
            default=filters["finding_types"],
            key="risk_finding_type_filter",
            format_func=format_finding_type_label,
        )
    with col7:
        selected_severities = st.multiselect(
            "Severidad",
            options=filters["severities"],
            default=filters["severities"],
            key="risk_severity_filter",
        )
    with col8:
        selected_models = st.multiselect(
            "Modelo",
            options=filters["models"],
            default=[],
            key="risk_model_filter",
        )

    firmware_column = st.columns(1)[0]
    with firmware_column:
        selected_firmwares = st.multiselect(
            "Firmware",
            options=filters["firmwares"],
            default=[],
            key="risk_firmware_filter",
            help="Usa la target version del inventario normalizado cuando está disponible.",
        )

    pareto_threshold = normalize_pareto_threshold(
        st.slider(
            "Pareto cumulative threshold (%)",
            min_value=10,
            max_value=100,
            value=80,
            step=5,
            help="80% highlights the canonical urgent findings; 100% renders all currently filtered bars.",
            key="risk_pareto_threshold",
        )
    )

    dashboard = build_risk_dashboard_data(
        devices=devices,
        inventory_rows=inventory_rows,
        discrepancy_rows=discrepancy_rows,
        bug_findings=bug_findings,
        platform_family=selected_platforms[0] if len(selected_platforms) == 1 else "All",
        platform_families=selected_platforms,
        hostnames=selected_hostnames,
        severities=selected_severities,
        features=selected_features,
        models=selected_models,
        versions=selected_versions,
        firmwares=selected_firmwares,
        bug_ids=selected_bug_ids,
        finding_types=selected_finding_types,
        pareto_cumulative_threshold=pareto_threshold,
    )
    st.session_state["risk_dashboard_data"] = dashboard
    st.session_state["risk_dashboard_filters"] = {
        "platform_family": selected_platforms if selected_platforms else ["All"],
        "hostnames": selected_hostnames,
        "severities": selected_severities,
        "features": selected_features,
        "models": selected_models,
        "versions": selected_versions,
        "firmwares": selected_firmwares,
        "bug_ids": selected_bug_ids,
        "finding_types": selected_finding_types,
        "pareto_threshold": pareto_threshold,
    }

    metrics = dashboard["metrics"]
    impacted_rows = dashboard.get("impacted_severity_rows", [])
    render_impacted_metric_cards(metrics=metrics, impacted_severity_rows=impacted_rows)

    narrative_lines = dashboard.get("narrative_lines", [])
    if narrative_lines:
        st.caption("Narrative")
        for line in narrative_lines:
            st.write(f"- {line}")

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.caption("Gráfica de barras apiladas - desglose por bug")
        if dashboard.get("bug_severity_stack_rows"):
            st.altair_chart(build_bug_severity_chart(dashboard["bug_severity_stack_rows"]), use_container_width=True)
        else:
            st.info("No hay datos de bug/severidad con los filtros activos.")
    with chart_right:
        st.caption("Gráfica de barras apiladas - desglose por plataforma")
        if dashboard.get("platform_stack_rows"):
            st.altair_chart(build_platform_stack_chart(dashboard["platform_stack_rows"]), use_container_width=True)
        else:
            st.info("No hay datos de plataforma con los filtros activos.")

    st.caption("Gráfico de treemap")
    if dashboard.get("treemap_rows"):
        st.altair_chart(build_treemap_chart(dashboard["treemap_rows"]), use_container_width=True)
    else:
        st.info("No hay datos para el treemap con los filtros activos.")

    st.caption("Tabla exportable con datos filtrados")
    detail_rows = dashboard.get("detailed_rows", [])
    if detail_rows:
        detail_frame = pd.DataFrame(detail_rows)
        st.dataframe(detail_frame, use_container_width=True, hide_index=True)
        render_tabular_download_buttons(
            prefix="filtered-details",
            title="Exportar detalles filtrados",
            frame=detail_frame,
        )
    else:
        st.info("No hay datos filtrados para exportar.")

    st.caption("Devices impactados")
    if dashboard["device_summary_rows"]:
        st.dataframe(pd.DataFrame(dashboard["device_summary_rows"]), use_container_width=True, hide_index=True)
    else:
        st.info("No hay dispositivos impactados con los filtros activos.")

    st.caption("Top bugs")
    if dashboard["bug_summary_rows"]:
        st.dataframe(pd.DataFrame(dashboard["bug_summary_rows"]), use_container_width=True, hide_index=True)
    else:
        st.info("No hay bugs en alcance con los filtros activos.")

    st.caption("Pareto bug impact quick analysis")
    pareto_rows = dashboard.get("pareto_quick_analysis_rows", [])
    if pareto_rows:
        st.caption(
            f"Showing findings up to the active cumulative threshold of {pareto_threshold}% of total impacted-device risk."
        )
        pareto_frame = prepare_pareto_quick_analysis_frame(pareto_rows)
        st.dataframe(pareto_frame, use_container_width=True, hide_index=True)
        st.caption("Pareto risk priority graphic")
        st.altair_chart(build_pareto_priority_chart(pareto_rows), use_container_width=True)
        render_pareto_quick_analysis_exports(
            quick_analysis_frame=pareto_frame,
            dashboard_data=dashboard,
            filter_summary=st.session_state.get("risk_dashboard_filters", {}),
            session_id=str(st.session_state.get("current_session_id", "") or ""),
            platform_family=str(st.session_state.get("platform_family", "All")),
        )
    else:
        st.info("No pareto quick-analysis data is available for the active filters.")


def render_inventory_workbook_table() -> None:
    workbook_rows = st.session_state.get("inventory_workbook", [])
    generated_inventory_path = str(st.session_state.get("generated_inventory_path", "") or "")
    inventory_origin = str(st.session_state.get("inventory_workbook_origin", "") or "")

    st.subheader("Inventory Workbook")
    if not workbook_rows:
        st.info("Inventory workbook metadata will appear here after a successful upload.")
        return

    if inventory_origin == "generated" and generated_inventory_path:
        generated_path = Path(generated_inventory_path)
        st.caption("This inventory workbook was generated automatically from the uploaded command outputs.")
        if generated_path.exists():
            st.download_button(
                label="Download generated inventory Excel",
                data=generated_path.read_bytes(),
                file_name=generated_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=False,
                key="generated_inventory_workbook_download",
            )

    frame = pd.DataFrame(workbook_rows)
    frame = frame.rename(
        columns={
            "file_name": "Workbook file",
            "sheet_names": "Sheet names",
            "sheet_count": "Sheet count",
            "selected_sheet": "Selected sheet",
            "normalized_columns": "Normalized columns",
            "parsed_row_count": "Parsed rows",
        }
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_parsed_preview_table() -> None:
    parsed_preview = st.session_state.get("parsed_preview", [])
    warnings = st.session_state.get("session_warnings", [])

    st.subheader("Parsed Device Preview")
    if not parsed_preview:
        st.info("Parsed device output will appear here after a successful upload.")
        return

    if warnings:
        st.warning("Parser warnings were produced for this session.")
        for warning in warnings:
            st.write(f"- {warning}")

    frame = pd.DataFrame(parsed_preview)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_inventory_rows_table() -> None:
    inventory_rows = st.session_state.get("inventory_rows", [])

    st.subheader("Normalized Inventory Rows")
    if not inventory_rows:
        st.info("Normalized inventory rows will appear here after the workbook is parsed.")
        return

    frame = pd.DataFrame(inventory_rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_discrepancy_rows_table() -> None:
    discrepancy_rows = st.session_state.get("discrepancy_rows", [])

    st.subheader("Discrepancy Output Rows")
    if not discrepancy_rows:
        st.info("Discrepancy rows will appear here when inventory and discovered data do not match.")
        return

    frame = pd.DataFrame(discrepancy_rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_bug_findings_table() -> None:
    bug_findings = st.session_state.get("bug_findings", [])

    st.subheader("Bug Findings")
    if not bug_findings:
        st.info("Bug findings will appear here when internal bug matches are detected.")
        return

    frame = pd.DataFrame(bug_findings)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_export_section(settings: Settings, store: DuckDBStore) -> None:
    session_id = st.session_state.get("current_session_id")
    dashboard_data = st.session_state.get("risk_dashboard_data", {})
    filter_summary = st.session_state.get("risk_dashboard_filters", {})
    platform_family = str(st.session_state.get("platform_family", "All"))

    st.subheader("Export")
    if not session_id:
        st.info("An Excel export will be available here after a session has been processed.")
        return

    discrepancy_rows = store.fetch_discrepancy_rows_for_session(session_id)
    bug_findings = store.fetch_bug_findings_for_session(session_id)
    if not discrepancy_rows:
        st.info(
            "No discrepancy rows were detected for the current session. "
            "The Excel export will still be generated with an empty `Discrepancias` sheet."
        )

    exporter = ExcelExporter()
    export_bytes = exporter.export_discrepancies_to_bytes(discrepancy_rows, bug_findings=bug_findings)
    export_dir = Path(settings.runtime_root) / "exports" / session_id
    export_path = export_dir / f"{session_id}-discrepancias.xlsx"
    exporter.export_discrepancies(discrepancy_rows, export_path, bug_findings=bug_findings)

    executive_exporter = ExecutiveExporter()
    pdf_path = export_dir / f"{session_id}-executive.pdf"
    pdf_bytes = executive_exporter.export_pdf_to_bytes(
        session_id=session_id,
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        filter_summary=filter_summary,
    )
    executive_exporter.export_pdf(
        session_id=session_id,
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        destination=pdf_path,
        filter_summary=filter_summary,
    )

    powerpoint_exporter = PowerPointExporter()
    pptx_path = export_dir / f"{session_id}-executive.pptx"
    pptx_bytes = powerpoint_exporter.export_pptx_to_bytes(
        session_id=session_id,
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        filter_summary=filter_summary,
    )
    powerpoint_exporter.export_pptx(
        session_id=session_id,
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        destination=pptx_path,
        filter_summary=filter_summary,
    )

    st.caption(f"Excel saved to `{export_path}`")
    st.caption(f"PDF saved to `{pdf_path}`")
    st.caption(f"PowerPoint saved to `{pptx_path}`")
    button_left, button_middle, button_right = st.columns(3)
    with button_left:
        st.download_button(
            label="Download discrepancy Excel",
            data=export_bytes,
            file_name=export_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with button_middle:
        st.download_button(
            label="Download executive PDF",
            data=pdf_bytes,
            file_name=pdf_path.name,
            mime="application/pdf",
            use_container_width=True,
        )
    with button_right:
        st.download_button(
            label="Download executive PowerPoint",
            data=pptx_bytes,
            file_name=pptx_path.name,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


def render_overview_metric_cards(overview_metrics: dict[str, object]) -> None:
    cards = st.columns(5)
    inventory_count = overview_metrics.get("devices_in_inventory")
    inconsistency_count = overview_metrics.get("inconsistency_count")
    devices_with_bugs_percentage = format_percentage(overview_metrics.get("devices_with_bugs_percentage"))
    inconsistency_percentage = format_percentage(overview_metrics.get("inconsistency_percentage"))

    cards[0].metric("Devices in Inventory", "--" if inventory_count is None else int(inventory_count))
    cards[1].metric("Discovered Devices", int(overview_metrics.get("discovered_devices", 0)))
    cards[2].metric(
        "Inconsistencies",
        "--" if inconsistency_count is None else int(inconsistency_count),
        inconsistency_percentage,
    )
    cards[3].metric(
        "Devices with bugs",
        int(overview_metrics.get("devices_with_bugs_count", 0)),
        devices_with_bugs_percentage,
    )
    cards[4].metric("Bugs", int(overview_metrics.get("total_bugs_found", 0)))


def render_impacted_metric_cards(*, metrics: dict[str, object], impacted_severity_rows: list[dict[str, object]]) -> None:
    severity_cards = impacted_severity_rows if impacted_severity_rows else []
    columns = st.columns(max(1, len(severity_cards) + 1))
    columns[0].metric("Total Impacted Devices", int(metrics.get("impacted_devices_in_scope", 0)))
    for index, row in enumerate(severity_cards, start=1):
        columns[index].metric(
            str(row.get("severity_label", "Other")),
            int(row.get("impacted_device_count", 0)),
            format_percentage(row.get("percentage")),
        )


def render_dataset_download_row(*, discovered_devices: list[dict[str, object]], discrepancy_rows: list[dict[str, object]]) -> None:
    st.caption("Descargas rápidas")
    left, right = st.columns(2)
    discovered_frame = pd.DataFrame(discovered_devices)
    discrepancy_frame = pd.DataFrame(discrepancy_rows)

    with left:
        st.caption("Discovered devices")
        buttons = st.columns(3)
        for column, fmt in zip(buttons, ("excel", "csv", "json"), strict=False):
            data, mime, extension = build_tabular_download_payload(discovered_frame, fmt)
            column.download_button(
                label=fmt.upper(),
                data=data,
                file_name=f"discovered-devices.{extension}",
                mime=mime,
                use_container_width=True,
                key=f"download-discovered-{fmt}",
            )

    with right:
        st.caption("Discrepancies")
        has_discrepancies = not discrepancy_frame.empty
        buttons = st.columns(3)
        for column, fmt in zip(buttons, ("excel", "csv", "json"), strict=False):
            data, mime, extension = build_tabular_download_payload(discrepancy_frame, fmt)
            column.download_button(
                label=fmt.upper(),
                data=data,
                file_name=f"discrepancies.{extension}",
                mime=mime,
                use_container_width=True,
                disabled=not has_discrepancies,
                key=f"download-discrepancies-{fmt}",
            )


def render_tabular_download_buttons(*, prefix: str, title: str, frame: pd.DataFrame) -> None:
    st.caption(title)
    col1, col2, col3 = st.columns(3)
    for column, fmt in zip((col1, col2, col3), ("excel", "csv", "json"), strict=False):
        data, mime, extension = build_tabular_download_payload(frame, fmt)
        column.download_button(
            label=f"Download {fmt.upper()}",
            data=data,
            file_name=f"{prefix}.{extension}",
            mime=mime,
            use_container_width=True,
            key=f"{prefix}-{fmt}-download",
        )


def build_tabular_download_payload(frame: pd.DataFrame, fmt: str) -> tuple[bytes, str, str]:
    if fmt == "csv":
        export_frame = flatten_frame_for_export(frame)
        return export_frame.to_csv(index=False).encode("utf-8"), "text/csv", "csv"
    if fmt == "json":
        return frame.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8"), "application/json", "json"

    export_frame = flatten_frame_for_export(frame)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export_frame.to_excel(writer, index=False, sheet_name="Data")
    return (
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    )


def flatten_frame_for_export(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    export_frame = frame.copy()
    for column in export_frame.columns:
        export_frame[column] = export_frame[column].apply(
            lambda value: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (list, dict))
            else value
        )
    return export_frame


def format_percentage(value: object) -> str:
    if value in {None, ""}:
        return "--"
    return f"{float(value):.2f}%"


def format_finding_type_label(value: str) -> str:
    mapping = {
        "bug": "Bug",
        "cve": "CVE",
        "field_notice": "Field Notice",
        "psirt": "PSIRT",
    }
    return mapping.get(str(value), str(value).replace("_", " ").title())


def build_bug_severity_chart(rows: list[dict[str, object]]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("severity_label:N", sort=BUG_BREAKDOWN_SEVERITY_SEQUENCE, title="Severity"),
            y=alt.Y("affected_device_count:Q", title="Impacted devices"),
            color=alt.Color("bug_id:N", title="Bug"),
            order=alt.Order("stack_order:Q", sort="ascending"),
            tooltip=["severity_label", "bug_id", "headline", "affected_device_count", "total_score"],
        )
    )


def build_platform_stack_chart(rows: list[dict[str, object]]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    color_domain = list(SEVERITY_COLORS.keys())
    color_range = [SEVERITY_COLORS[key] for key in color_domain]
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("platform_family:N", sort=alt.SortField("platform_order", order="ascending"), title="Platform"),
            y=alt.Y("finding_count:Q", title="Bug findings"),
            color=alt.Color(
                "severity_label:N",
                title="Severity",
                scale=alt.Scale(domain=[label.title() if label.startswith("s") else label.capitalize() for label in color_domain], range=color_range),
            ),
            order=alt.Order("severity_order:Q", sort="ascending"),
            tooltip=["platform_family", "severity_label", "finding_count", "platform_total_findings"],
        )
    )


def build_treemap_chart(rows: list[dict[str, object]]) -> alt.LayerChart:
    frame = pd.DataFrame(rows)
    color_domain = sorted(frame["severity_label"].dropna().unique().tolist())
    color_range = [SEVERITY_COLORS.get(str(label).lower(), SEVERITY_COLORS["other"]) for label in color_domain]
    rect_chart = (
        alt.Chart(frame)
        .mark_rect(stroke="white")
        .encode(
            x=alt.X("x0:Q", scale=alt.Scale(domain=[0, 1]), axis=None),
            x2="x1:Q",
            y=alt.Y("y0:Q", scale=alt.Scale(domain=[1, 0]), axis=None),
            y2="y1:Q",
            color=alt.Color("severity_label:N", scale=alt.Scale(domain=color_domain, range=color_range), title="Severity"),
            tooltip=["severity_label", "bug_id", "headline", "affected_device_count", "total_score", "finding_type"],
        )
    )
    text_chart = (
        alt.Chart(frame)
        .mark_text(fontSize=10, color="black", align="left", baseline="top", dx=4, dy=4)
        .encode(
            x=alt.X("x0:Q", scale=alt.Scale(domain=[0, 1]), axis=None),
            y=alt.Y("y0:Q", scale=alt.Scale(domain=[1, 0]), axis=None),
            text=alt.Text("bug_id:N"),
        )
    )
    return rect_chart + text_chart


def prepare_pareto_quick_analysis_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    display_frame = frame.copy()
    if "affected_devices" in display_frame.columns:
        display_frame["affected_devices"] = display_frame["affected_devices"].apply(
            lambda value: ", ".join(value) if isinstance(value, list) else value
        )
    if "recommended_actions" in display_frame.columns:
        display_frame["recommended_actions"] = display_frame["recommended_actions"].apply(
            lambda value: "; ".join(value) if isinstance(value, list) else value
        )
    display_frame = display_frame.rename(
        columns={
            "bug_id": "Bug ID",
            "headline": "Headline",
            "total_risk_score": "Total Risk score",
            "finding_type": "Finding type",
            "platform_family": "Platform family",
            "finding_count": "Finding count",
            "affected_devices": "Affected devices (host names)",
            "affected_device_count": "Affected device count",
            "remediation_status": "Remediation status",
            "recommended_actions": "Recommended actions",
            "cumulative_percentage": "Cumulative %",
        }
    )
    ordered_columns = [
        "Bug ID",
        "Headline",
        "Total Risk score",
        "Finding type",
        "Platform family",
        "Finding count",
        "Affected device count",
        "Affected devices (host names)",
        "Remediation status",
        "Recommended actions",
        "Cumulative %",
    ]
    return display_frame[[column for column in ordered_columns if column in display_frame.columns]]


def build_pareto_priority_chart(rows: list[dict[str, object]]) -> alt.LayerChart:
    frame = pd.DataFrame(rows)
    frame["bug_axis_label"] = frame.apply(
        lambda row: f"{int(row.get('sort_rank', 0) or 0)}. {row.get('bug_id', '')}",
        axis=1,
    )
    frame["affected_devices_label"] = frame["affected_devices"].apply(
        lambda value: ", ".join(value) if isinstance(value, list) else str(value)
    )
    frame["recommended_actions_label"] = frame["recommended_actions"].apply(
        lambda value: "; ".join(value) if isinstance(value, list) else str(value)
    )
    sort_domain = frame.sort_values(["sort_rank", "bug_id"])["bug_axis_label"].tolist()

    bar_chart = (
        alt.Chart(frame)
        .mark_bar(color="#4C78A8")
        .encode(
            x=alt.X(
                "bug_axis_label:N",
                sort=sort_domain,
                title="Bug / Finding (ranked by total risk)",
                axis=alt.Axis(labelAngle=-35, labelLimit=140),
            ),
            y=alt.Y("total_risk_score:Q", title="Total risk score"),
            tooltip=[
                alt.Tooltip("bug_id:N", title="Bug ID"),
                alt.Tooltip("headline:N", title="Headline"),
                alt.Tooltip("total_risk_score:Q", title="Total Risk score"),
                alt.Tooltip("finding_count:Q", title="Finding count"),
                alt.Tooltip("affected_devices_label:N", title="Affected devices"),
                alt.Tooltip("remediation_status:N", title="Remediation status"),
                alt.Tooltip("recommended_actions_label:N", title="Recommended actions"),
                alt.Tooltip("cumulative_percentage:Q", title="Cumulative %", format=".1f"),
            ],
        )
    )
    line_chart = (
        alt.Chart(frame)
        .mark_line(color="#E45756", point=True)
        .encode(
            x=alt.X(
                "bug_axis_label:N",
                sort=sort_domain,
                title="Bug / Finding (ranked by total risk)",
                axis=alt.Axis(labelAngle=-35, labelLimit=140),
            ),
            y=alt.Y(
                "cumulative_percentage:Q",
                title="Cumulative %",
                axis=alt.Axis(format=".0f", orient="right"),
            ),
        )
    )
    return alt.layer(bar_chart, line_chart).resolve_scale(y="independent")


def render_pareto_quick_analysis_exports(
    *,
    quick_analysis_frame: pd.DataFrame,
    dashboard_data: dict[str, object],
    filter_summary: dict[str, object],
    session_id: str,
    platform_family: str,
) -> None:
    st.caption("Pareto quick analysis exports")
    excel_bytes, excel_mime, excel_extension = build_tabular_download_payload(quick_analysis_frame, "excel")
    json_bytes, json_mime, json_extension = build_tabular_download_payload(quick_analysis_frame, "json")

    pdf_bytes = ExecutiveExporter().export_pdf_to_bytes(
        session_id=session_id or "session",
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        filter_summary=filter_summary,
    )
    pptx_bytes = PowerPointExporter().export_pptx_to_bytes(
        session_id=session_id or "session",
        platform_family=platform_family,
        dashboard_data=dashboard_data,
        filter_summary=filter_summary,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.download_button(
        label="Excel",
        data=excel_bytes,
        file_name=f"{session_id or 'session'}-pareto-quick-analysis.{excel_extension}",
        mime=excel_mime,
        use_container_width=True,
        key="pareto-quick-analysis-excel",
    )
    col2.download_button(
        label="JSON",
        data=json_bytes,
        file_name=f"{session_id or 'session'}-pareto-quick-analysis.{json_extension}",
        mime=json_mime,
        use_container_width=True,
        key="pareto-quick-analysis-json",
    )
    col3.download_button(
        label="PDF",
        data=pdf_bytes,
        file_name=f"{session_id or 'session'}-pareto-quick-analysis.pdf",
        mime="application/pdf",
        use_container_width=True,
        key="pareto-quick-analysis-pdf",
    )
    col4.download_button(
        label="PowerPoint",
        data=pptx_bytes,
        file_name=f"{session_id or 'session'}-pareto-quick-analysis.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        use_container_width=True,
        key="pareto-quick-analysis-pptx",
    )


def refresh_bug_dataset_state(store: DuckDBStore) -> None:
    st.session_state["duckdb_bug_catalog"] = store.fetch_bug_catalog()
    st.session_state["duckdb_bug_datasets"] = store.fetch_bug_datasets()
    st.session_state["duckdb_active_bug_dataset"] = store.fetch_active_bug_dataset()


def format_bug_dataset_option(dataset_id: str, datasets: list[dict[str, object]]) -> str:
    dataset = next((row for row in datasets if str(row["dataset_id"]) == dataset_id), None)
    if dataset is None:
        return dataset_id
    return f"{dataset['dataset_name']} ({dataset['row_count']} rows)"


def render_normalized_preview_table() -> None:
    normalized_rows = st.session_state.get("normalized_devices", [])

    st.subheader("Normalized Device Preview")
    if not normalized_rows:
        st.info("Normalized device rows will appear here after parsing succeeds.")
        return

    frame = pd.DataFrame(normalized_rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_persisted_preview_table() -> None:
    persisted_rows = st.session_state.get("duckdb_devices", [])
    persisted_inventory_rows = st.session_state.get("duckdb_inventory_rows", [])
    persisted_discrepancy_rows = st.session_state.get("duckdb_discrepancy_rows", [])
    persisted_bug_findings = st.session_state.get("duckdb_bug_findings", [])
    persisted_bug_catalog = st.session_state.get("duckdb_bug_catalog", [])
    persisted_bug_datasets = st.session_state.get("duckdb_bug_datasets", [])
    session_rows = st.session_state.get("duckdb_sessions", [])

    st.subheader("DuckDB Persisted Rows")
    if not persisted_rows:
        st.info("Persisted DuckDB rows will appear here after normalization is saved.")
        return

    if persisted_inventory_rows:
        st.caption("Normalized inventory rows")
        inventory_frame = pd.DataFrame(persisted_inventory_rows)
        st.dataframe(inventory_frame, use_container_width=True, hide_index=True)

    if persisted_discrepancy_rows:
        st.caption("Discrepancy rows")
        discrepancy_frame = pd.DataFrame(persisted_discrepancy_rows)
        st.dataframe(discrepancy_frame, use_container_width=True, hide_index=True)

    if persisted_bug_findings:
        st.caption("Bug findings")
        findings_frame = pd.DataFrame(persisted_bug_findings)
        st.dataframe(findings_frame, use_container_width=True, hide_index=True)

    if persisted_bug_catalog:
        st.caption("Active bug catalog")
        catalog_frame = pd.DataFrame(persisted_bug_catalog)
        st.dataframe(catalog_frame, use_container_width=True, hide_index=True)

    if persisted_bug_datasets:
        st.caption("Stored bug datasets")
        dataset_frame = pd.DataFrame(persisted_bug_datasets)
        st.dataframe(dataset_frame, use_container_width=True, hide_index=True)

    st.caption("Normalized device rows")
    device_frame = pd.DataFrame(persisted_rows)
    st.dataframe(device_frame, use_container_width=True, hide_index=True)

    if session_rows:
        st.caption("Imported sessions")
        session_frame = pd.DataFrame(session_rows)
        st.dataframe(session_frame, use_container_width=True, hide_index=True)


def update_progress(
    progress_bar: "st.delta_generator.DeltaGenerator",
    progress_status: "st.delta_generator.DeltaGenerator",
    value: int,
    message: str,
) -> None:
    progress_bar.progress(value, text=message)
    progress_status.caption(message)


def build_processing_metrics(
    *,
    saved_files: list[object],
    parsed_bundle_count: int,
    batch: object,
    processing_seconds: float,
) -> dict[str, object]:
    return {
        "uploaded_files": len(saved_files),
        "parsed_bundles": parsed_bundle_count,
        "normalized_devices": len(getattr(batch, "devices", [])),
        "discrepancy_pairs": count_discrepancy_pairs(getattr(batch, "discrepancy_rows", [])),
        "bug_findings": len(getattr(batch, "bug_findings", [])),
        "warning_count": len(getattr(batch, "warnings", [])),
        "processing_seconds": processing_seconds,
    }


def count_discrepancy_pairs(discrepancy_rows: list[object]) -> int:
    pair_ids: set[str] = set()
    for row in discrepancy_rows:
        if isinstance(row, dict):
            pair_id = str(row.get("pair_id", "") or "")
        else:
            pair_id = str(getattr(row, "pair_id", "") or "")
        if pair_id:
            pair_ids.add(pair_id)
    return len(pair_ids)
