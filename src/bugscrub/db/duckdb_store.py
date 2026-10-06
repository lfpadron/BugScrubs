from __future__ import annotations

import json
from pathlib import Path

import duckdb

from bugscrub.bug_engine.dataset import BugDatasetDefinition, load_internal_bug_dataset
from bugscrub.normalization.models import InventoryBatch


class DuckDBStore:
    """Central entry point for the future analytics schema."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.database_path))

    def initialize_schema(self) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS import_sessions (
                    session_id TEXT PRIMARY KEY,
                    platform_family TEXT NOT NULL,
                    support_level TEXT NOT NULL,
                    session_dir TEXT NOT NULL,
                    inventory_file TEXT,
                    inventory_sheet_names TEXT,
                    source_count INTEGER NOT NULL,
                    warnings TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS normalized_devices (
                    session_id TEXT NOT NULL,
                    hostname TEXT,
                    vendor TEXT,
                    platform_family TEXT,
                    support_level TEXT,
                    model TEXT,
                    pid TEXT,
                    serial TEXT,
                    os_name TEXT,
                    os_version TEXT,
                    inventory_file TEXT,
                    inventory_sheet_names TEXT,
                    features TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS normalized_inventory_rows (
                    session_id TEXT NOT NULL,
                    sheet_name TEXT,
                    row_number INTEGER,
                    hostname TEXT,
                    model TEXT,
                    pid TEXT,
                    serial TEXT,
                    os_version TEXT,
                    target_version TEXT,
                    site TEXT,
                    role TEXT,
                    family TEXT,
                    features TEXT,
                    business_criticality INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS discrepancy_rows (
                    session_id TEXT NOT NULL,
                    pair_id TEXT NOT NULL,
                    row_source TEXT NOT NULL,
                    discrepancy_status TEXT NOT NULL,
                    match_key TEXT NOT NULL,
                    discrepancy_fields TEXT,
                    discrepancy_summary TEXT,
                    hostname TEXT,
                    model TEXT,
                    pid TEXT,
                    serial TEXT,
                    os_version TEXT,
                    target_version TEXT,
                    site TEXT,
                    role TEXT,
                    family TEXT,
                    features TEXT,
                    business_criticality INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bug_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    dataset_name TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    selected_sheet TEXT,
                    normalized_columns TEXT,
                    row_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    loaded_at TEXT NOT NULL,
                    warnings TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bug_dataset_entries (
                    dataset_id TEXT NOT NULL,
                    bug_id TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    product_scope TEXT NOT NULL,
                    affected_releases TEXT,
                    fixed_releases TEXT,
                    trigger_features TEXT,
                    platform_pids TEXT,
                    required_features TEXT,
                    optional_features TEXT,
                    severity TEXT,
                    recommended_action TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bug_catalog (
                    bug_id TEXT PRIMARY KEY,
                    headline TEXT NOT NULL,
                    product_scope TEXT NOT NULL,
                    affected_releases TEXT,
                    fixed_releases TEXT,
                    trigger_features TEXT,
                    platform_pids TEXT,
                    required_features TEXT,
                    optional_features TEXT,
                    severity TEXT,
                    recommended_action TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bug_findings (
                    session_id TEXT NOT NULL,
                    hostname TEXT,
                    platform_family TEXT,
                    bug_id TEXT,
                    headline TEXT,
                    severity TEXT,
                    score INTEGER,
                    current_version TEXT,
                    target_version TEXT,
                    remediation_status TEXT,
                    version_match_type TEXT,
                    matched_release TEXT,
                    matched_on TEXT,
                    fixed_releases TEXT,
                    recommended_action TEXT,
                    rationale TEXT
                )
                """
            )
            connection.execute("ALTER TABLE bug_dataset_entries ADD COLUMN IF NOT EXISTS platform_pids TEXT")
            connection.execute("ALTER TABLE bug_dataset_entries ADD COLUMN IF NOT EXISTS required_features TEXT")
            connection.execute("ALTER TABLE bug_dataset_entries ADD COLUMN IF NOT EXISTS optional_features TEXT")
            connection.execute("ALTER TABLE bug_catalog ADD COLUMN IF NOT EXISTS platform_pids TEXT")
            connection.execute("ALTER TABLE bug_catalog ADD COLUMN IF NOT EXISTS required_features TEXT")
            connection.execute("ALTER TABLE bug_catalog ADD COLUMN IF NOT EXISTS optional_features TEXT")
            connection.execute("ALTER TABLE bug_findings ADD COLUMN IF NOT EXISTS current_version TEXT")
            connection.execute("ALTER TABLE bug_findings ADD COLUMN IF NOT EXISTS target_version TEXT")
            connection.execute("ALTER TABLE bug_findings ADD COLUMN IF NOT EXISTS remediation_status TEXT")
            connection.execute("ALTER TABLE bug_findings ADD COLUMN IF NOT EXISTS version_match_type TEXT")
            connection.execute("ALTER TABLE bug_findings ADD COLUMN IF NOT EXISTS matched_release TEXT")
        finally:
            connection.close()

    def save_inventory_batch(self, batch: InventoryBatch) -> None:
        self.initialize_schema()
        self.sync_bug_catalog()
        connection = self.connect()
        try:
            connection.execute("DELETE FROM normalized_devices WHERE session_id = ?", [batch.session_id])
            connection.execute("DELETE FROM normalized_inventory_rows WHERE session_id = ?", [batch.session_id])
            connection.execute("DELETE FROM discrepancy_rows WHERE session_id = ?", [batch.session_id])
            connection.execute("DELETE FROM bug_findings WHERE session_id = ?", [batch.session_id])
            connection.execute("DELETE FROM import_sessions WHERE session_id = ?", [batch.session_id])
            connection.execute(
                """
                INSERT INTO import_sessions (
                    session_id,
                    platform_family,
                    support_level,
                    session_dir,
                    inventory_file,
                    inventory_sheet_names,
                    source_count,
                    warnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch.session_id,
                    batch.platform_family,
                    batch.support_level,
                    batch.session_dir,
                    batch.inventory_workbook.file_name,
                    json.dumps(batch.inventory_workbook.sheet_names),
                    batch.source_count,
                    json.dumps(batch.warnings),
                ],
            )
            for device in batch.devices:
                connection.execute(
                    """
                    INSERT INTO normalized_devices (
                        session_id,
                        hostname,
                        vendor,
                        platform_family,
                        support_level,
                        model,
                        pid,
                        serial,
                        os_name,
                        os_version,
                        inventory_file,
                        inventory_sheet_names,
                        features
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        device.session_id,
                        device.hostname,
                        device.vendor,
                        device.platform_family,
                        device.support_level,
                        device.model,
                        device.pid,
                        device.serial,
                        device.os_name,
                        device.os_version,
                        device.inventory_file,
                        json.dumps(device.inventory_sheet_names),
                        json.dumps(device.features),
                    ],
                )
            for inventory_row in batch.inventory_rows:
                connection.execute(
                    """
                    INSERT INTO normalized_inventory_rows (
                        session_id,
                        sheet_name,
                        row_number,
                        hostname,
                        model,
                        pid,
                        serial,
                        os_version,
                        target_version,
                        site,
                        role,
                        family,
                        features,
                        business_criticality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        inventory_row.session_id,
                        inventory_row.sheet_name,
                        inventory_row.row_number,
                        inventory_row.hostname,
                        inventory_row.model,
                        inventory_row.pid,
                        inventory_row.serial,
                        inventory_row.os_version,
                        inventory_row.target_version,
                        inventory_row.site,
                        inventory_row.role,
                        inventory_row.family,
                        json.dumps(inventory_row.features),
                        inventory_row.business_criticality,
                    ],
                )
            for discrepancy_row in batch.discrepancy_rows:
                connection.execute(
                    """
                    INSERT INTO discrepancy_rows (
                        session_id,
                        pair_id,
                        row_source,
                        discrepancy_status,
                        match_key,
                        discrepancy_fields,
                        discrepancy_summary,
                        hostname,
                        model,
                        pid,
                        serial,
                        os_version,
                        target_version,
                        site,
                        role,
                        family,
                        features,
                        business_criticality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        discrepancy_row.session_id,
                        discrepancy_row.pair_id,
                        discrepancy_row.row_source,
                        discrepancy_row.discrepancy_status,
                        discrepancy_row.match_key,
                        json.dumps(discrepancy_row.discrepancy_fields),
                        discrepancy_row.discrepancy_summary,
                        discrepancy_row.hostname,
                        discrepancy_row.model,
                        discrepancy_row.pid,
                        discrepancy_row.serial,
                        discrepancy_row.os_version,
                        discrepancy_row.target_version,
                        discrepancy_row.site,
                        discrepancy_row.role,
                        discrepancy_row.family,
                        json.dumps(discrepancy_row.features),
                        discrepancy_row.business_criticality,
                    ],
                )
            for bug_finding in batch.bug_findings:
                connection.execute(
                    """
                    INSERT INTO bug_findings (
                        session_id,
                        hostname,
                        platform_family,
                        bug_id,
                        headline,
                        severity,
                        score,
                        current_version,
                        target_version,
                        remediation_status,
                        version_match_type,
                        matched_release,
                        matched_on,
                        fixed_releases,
                        recommended_action,
                        rationale
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        bug_finding["session_id"],
                        bug_finding["hostname"],
                        bug_finding["platform_family"],
                        bug_finding["bug_id"],
                        bug_finding["headline"],
                        bug_finding["severity"],
                        bug_finding["score"],
                        bug_finding.get("current_version", ""),
                        bug_finding.get("target_version", ""),
                        bug_finding.get("remediation_status", ""),
                        bug_finding.get("version_match_type", ""),
                        bug_finding.get("matched_release", ""),
                        json.dumps(bug_finding["matched_on"]),
                        json.dumps(bug_finding["fixed_releases"]),
                        bug_finding["recommended_action"],
                        json.dumps(bug_finding["rationale"]),
                    ],
                )
        finally:
            connection.close()

    def save_bug_dataset(self, dataset: BugDatasetDefinition, *, activate: bool = True) -> str:
        self.initialize_schema()
        connection = self.connect()
        try:
            connection.execute("DELETE FROM bug_dataset_entries WHERE dataset_id = ?", [dataset.dataset_id])
            connection.execute("DELETE FROM bug_datasets WHERE dataset_id = ?", [dataset.dataset_id])
            connection.execute(
                """
                INSERT INTO bug_datasets (
                    dataset_id,
                    dataset_name,
                    source_file,
                    source_kind,
                    selected_sheet,
                    normalized_columns,
                    row_count,
                    status,
                    loaded_at,
                    warnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    dataset.dataset_id,
                    dataset.dataset_name,
                    dataset.source_file,
                    dataset.source_kind,
                    dataset.selected_sheet,
                    json.dumps(dataset.normalized_columns),
                    dataset.row_count,
                    "inactive",
                    dataset.loaded_at,
                    json.dumps(dataset.warnings),
                ],
            )
            for bug in dataset.bug_records:
                connection.execute(
                    """
                    INSERT INTO bug_dataset_entries (
                        dataset_id,
                        bug_id,
                        headline,
                        product_scope,
                        affected_releases,
                        fixed_releases,
                        trigger_features,
                        platform_pids,
                        required_features,
                        optional_features,
                        severity,
                        recommended_action
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        dataset.dataset_id,
                        bug["bug_id"],
                        bug["headline"],
                        bug["product_scope"],
                        json.dumps(bug["affected_releases"]),
                        json.dumps(bug["fixed_releases"]),
                        json.dumps(bug.get("trigger_features", [])),
                        json.dumps(bug.get("platform_pids", [])),
                        json.dumps(bug.get("required_features", [])),
                        json.dumps(bug.get("optional_features", [])),
                        bug["severity"],
                        bug["recommended_action"],
                    ],
                )
        finally:
            connection.close()

        if activate:
            self.activate_bug_dataset(dataset.dataset_id)
        else:
            self.sync_bug_catalog()
        return dataset.dataset_id

    def activate_bug_dataset(self, dataset_id: str) -> None:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                "SELECT COUNT(*) FROM bug_datasets WHERE dataset_id = ?",
                [dataset_id],
            )
            count = int(cursor.fetchone()[0])
            if count == 0:
                raise ValueError(f"Bug dataset `{dataset_id}` was not found in DuckDB.")

            connection.execute("UPDATE bug_datasets SET status = 'inactive'")
            connection.execute(
                "UPDATE bug_datasets SET status = 'active' WHERE dataset_id = ?",
                [dataset_id],
            )
        finally:
            connection.close()

        self.sync_bug_catalog()

    def reset_data(self) -> None:
        """Remove all customer data and restore the initial embedded catalog atomically."""
        self.initialize_schema()
        connection = self.connect()
        try:
            connection.execute("BEGIN TRANSACTION")
            for table in (
                "bug_findings", "discrepancy_rows", "normalized_inventory_rows",
                "normalized_devices", "import_sessions", "bug_dataset_entries",
                "bug_datasets", "bug_catalog",
            ):
                connection.execute(f"DELETE FROM {table}")
            self._insert_internal_bug_catalog(connection)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def sync_bug_catalog(self) -> None:
        self.initialize_schema()
        connection = self.connect()
        try:
            active_dataset = self._fetch_active_bug_dataset(connection)
            connection.execute("DELETE FROM bug_catalog")

            if active_dataset:
                rows = connection.execute(
                    """
                    SELECT
                        bug_id,
                        headline,
                        product_scope,
                        affected_releases,
                        fixed_releases,
                        trigger_features,
                        platform_pids,
                        required_features,
                        optional_features,
                        severity,
                        recommended_action
                    FROM bug_dataset_entries
                    WHERE dataset_id = ?
                    ORDER BY bug_id
                    """,
                    [active_dataset["dataset_id"]],
                ).fetchall()
                for row in rows:
                    connection.execute(
                        """
                        INSERT INTO bug_catalog (
                            bug_id,
                            headline,
                            product_scope,
                            affected_releases,
                            fixed_releases,
                            trigger_features,
                            platform_pids,
                            required_features,
                            optional_features,
                            severity,
                            recommended_action
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        list(row),
                    )
                return

            self._insert_internal_bug_catalog(connection)
        finally:
            connection.close()

    def _insert_internal_bug_catalog(self, connection: duckdb.DuckDBPyConnection) -> None:
        for bug in load_internal_bug_dataset():
            connection.execute(
                """
                INSERT INTO bug_catalog (
                    bug_id, headline, product_scope, affected_releases, fixed_releases,
                    trigger_features, platform_pids, required_features, optional_features,
                    severity, recommended_action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    bug["bug_id"], bug["headline"], bug["product_scope"],
                    json.dumps(bug["affected_releases"]), json.dumps(bug["fixed_releases"]),
                    json.dumps(bug.get("trigger_features", [])), json.dumps(bug.get("platform_pids", [])),
                    json.dumps(bug.get("required_features", [])), json.dumps(bug.get("optional_features", [])),
                    bug["severity"], bug["recommended_action"],
                ],
            )

    def _fetch_active_bug_dataset(self, connection: duckdb.DuckDBPyConnection) -> dict[str, object] | None:
        cursor = connection.execute(
            """
            SELECT
                dataset_id,
                dataset_name,
                source_file,
                source_kind,
                selected_sheet,
                normalized_columns,
                row_count,
                status,
                loaded_at,
                warnings
            FROM bug_datasets
            WHERE status = 'active'
            ORDER BY loaded_at DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            return None

        columns = [column[0] for column in cursor.description]
        record = dict(zip(columns, row, strict=False))
        record["normalized_columns"] = json.loads(str(record["normalized_columns"] or "[]"))
        record["warnings"] = json.loads(str(record["warnings"] or "[]"))
        return record

    def fetch_devices_for_session(self, session_id: str) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    session_id,
                    hostname,
                    vendor,
                    platform_family,
                    support_level,
                    model,
                    pid,
                    serial,
                    os_name,
                    os_version,
                    inventory_file,
                    inventory_sheet_names,
                    features
                FROM normalized_devices
                WHERE session_id = ?
                ORDER BY hostname
                """,
                [session_id],
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["inventory_sheet_names"] = json.loads(str(record["inventory_sheet_names"] or "[]"))
            record["features"] = json.loads(str(record["features"] or "[]"))
            records.append(record)
        return records

    def fetch_inventory_rows_for_session(self, session_id: str) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    session_id,
                    sheet_name,
                    row_number,
                    hostname,
                    model,
                    pid,
                    serial,
                    os_version,
                    target_version,
                    site,
                    role,
                    family,
                    features,
                    business_criticality
                FROM normalized_inventory_rows
                WHERE session_id = ?
                ORDER BY row_number
                """,
                [session_id],
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["features"] = json.loads(str(record["features"] or "[]"))
            records.append(record)
        return records

    def fetch_sessions(self) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    session_id,
                    platform_family,
                    support_level,
                    session_dir,
                    inventory_file,
                    inventory_sheet_names,
                    source_count,
                    warnings
                FROM import_sessions
                ORDER BY session_id DESC
                """
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["inventory_sheet_names"] = json.loads(str(record["inventory_sheet_names"] or "[]"))
            record["warnings"] = json.loads(str(record["warnings"] or "[]"))
            records.append(record)
        return records

    def fetch_bug_datasets(self) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    dataset_id,
                    dataset_name,
                    source_file,
                    source_kind,
                    selected_sheet,
                    normalized_columns,
                    row_count,
                    status,
                    loaded_at,
                    warnings
                FROM bug_datasets
                ORDER BY loaded_at DESC, dataset_name
                """
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["normalized_columns"] = json.loads(str(record["normalized_columns"] or "[]"))
            record["warnings"] = json.loads(str(record["warnings"] or "[]"))
            records.append(record)
        return records

    def fetch_active_bug_dataset(self) -> dict[str, object] | None:
        self.initialize_schema()
        connection = self.connect()
        try:
            return self._fetch_active_bug_dataset(connection)
        finally:
            connection.close()

    def fetch_bug_catalog(self, dataset_id: str | None = None) -> list[dict[str, object]]:
        if dataset_id is None:
            self.sync_bug_catalog()
            source_table = "bug_catalog"
            where_clause = ""
            parameters: list[object] = []
        else:
            self.initialize_schema()
            source_table = "bug_dataset_entries"
            where_clause = "WHERE dataset_id = ?"
            parameters = [dataset_id]

        connection = self.connect()
        try:
            cursor = connection.execute(
                f"""
                SELECT
                    bug_id,
                    headline,
                    product_scope,
                    affected_releases,
                    fixed_releases,
                    trigger_features,
                    platform_pids,
                    required_features,
                    optional_features,
                    severity,
                    recommended_action
                FROM {source_table}
                {where_clause}
                ORDER BY bug_id
                """,
                parameters,
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["affected_releases"] = json.loads(str(record["affected_releases"] or "[]"))
            record["fixed_releases"] = json.loads(str(record["fixed_releases"] or "[]"))
            record["trigger_features"] = json.loads(str(record["trigger_features"] or "[]"))
            record["platform_pids"] = json.loads(str(record["platform_pids"] or "[]"))
            record["required_features"] = json.loads(str(record["required_features"] or "[]"))
            record["optional_features"] = json.loads(str(record["optional_features"] or "[]"))
            records.append(record)
        return records

    def fetch_discrepancy_rows_for_session(self, session_id: str) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    session_id,
                    pair_id,
                    row_source,
                    discrepancy_status,
                    match_key,
                    discrepancy_fields,
                    discrepancy_summary,
                    hostname,
                    model,
                    pid,
                    serial,
                    os_version,
                    target_version,
                    site,
                    role,
                    family,
                    features,
                    business_criticality
                FROM discrepancy_rows
                WHERE session_id = ?
                ORDER BY pair_id, row_source
                """,
                [session_id],
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["discrepancy_fields"] = json.loads(str(record["discrepancy_fields"] or "[]"))
            record["features"] = json.loads(str(record["features"] or "[]"))
            records.append(record)
        return records

    def fetch_bug_findings_for_session(self, session_id: str) -> list[dict[str, object]]:
        self.initialize_schema()
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                SELECT
                    session_id,
                    hostname,
                    platform_family,
                    bug_id,
                    headline,
                    severity,
                    score,
                    current_version,
                    target_version,
                    remediation_status,
                    version_match_type,
                    matched_release,
                    matched_on,
                    fixed_releases,
                    recommended_action,
                    rationale
                FROM bug_findings
                WHERE session_id = ?
                ORDER BY hostname, score DESC, bug_id
                """,
                [session_id],
            )
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
        finally:
            connection.close()

        records: list[dict[str, object]] = []
        for row in rows:
            record = dict(zip(columns, row, strict=False))
            record["matched_on"] = json.loads(str(record["matched_on"] or "[]"))
            record["fixed_releases"] = json.loads(str(record["fixed_releases"] or "[]"))
            record["rationale"] = json.loads(str(record["rationale"] or "[]"))
            records.append(record)
        return records
