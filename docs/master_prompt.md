# BugScrub Local-First — Kit de Arranque para Codex

## 1. Propósito

Construir un MVP sólido, demostrable a nivel ejecutivo en dos semanas, para una herramienta **local-first** de automatización de **Bug Scrubs** para equipos Cisco.

El MVP debe:

- soportar **Cisco Nexus** de forma completa
- soportar **Cisco Catalyst** de forma básica
- operar con **cientos de equipos**
- correr en **Windows 11** usando **Docker Desktop**
- poder desplegarse también en **VMs de centros de datos del cliente**
- procesar información de manera **local**
- permitir uso **opcional y controlado** de la Cisco API
- generar:
  - inventario real
  - discrepancias contra inventario del cliente
  - análisis de bug scrub
  - filtros dinámicos
  - exportes a **Excel**
  - exportes ejecutivos a **PDF o PowerPoint**

---

## 2. Resumen de decisiones cerradas

### Arquitectura
- Local-first
- Streamlit
- DuckDB
- Docker

### Alcance técnico del MVP
- Nexus: soporte completo
- Catalyst: soporte básico

### Escala
- Debe ser útil con cientos de equipos

### Fuente de bugs
- Híbrida:
  - dataset interno
  - Cisco API opcional

### Modo de operación
- Asistido
- No autónomo en fase 1

### Seguridad
- Cisco API desactivada por defecto
- Activación explícita en pantalla dedicada
- Políticas cargadas y administradas en otra pantalla
- Secrets desde archivo montado
- Fallback a variables de entorno

### Exportación ejecutiva
- PDF o PowerPoint

---

## 3. Objetivo del MVP

Construir una herramienta usable por un ingeniero de redes que permita:

1. subir datos crudos de red o inventarios
2. normalizar el inventario real
3. comparar contra inventario esperado del cliente
4. cruzar con base de bugs
5. explorar riesgos con filtros intuitivos
6. exportar reportes estándar y ejecutivos

---

## 4. Criterios de aceptación del MVP

El MVP estará aceptado si puede:

- cargar outputs de:
  - `show version`
  - `show inventory`
  - `show running-config`
  - `show module`
- cargar inventario Excel del cliente
- construir inventario normalizado para Nexus y Catalyst
- detectar discrepancias relevantes
- procesar al menos **300 dispositivos** en una corrida razonable
- mostrar filtros dinámicos por:
  - tecnología
  - modelo
  - versión
  - features
  - ubicación
  - criticidad
- generar:
  - Excel estándar
  - Excel filtrado
  - PDF ejecutivo
  - PowerPoint ejecutivo
- correr con Docker en Windows 11
- mantener Cisco API apagada por defecto
- permitir activar Cisco API solo si se habilita desde la UI y las políticas lo permiten

---

## 5. Estructura de repo sugerida

```text
bugscrub-local-first/
├─ app/
│  ├─ main.py
│  ├─ pages/
│  │  ├─ 01_upload.py
│  │  ├─ 02_inventory.py
│  │  ├─ 03_discrepancies.py
│  │  ├─ 04_bug_scrub.py
│  │  ├─ 05_dashboards.py
│  │  ├─ 06_exports.py
│  │  ├─ 07_api_enablement.py
│  │  └─ 08_policy_management.py
│  └─ components/
│     ├─ filters.py
│     ├─ tables.py
│     ├─ charts.py
│     └─ status_cards.py
├─ core/
│  ├─ config/
│  │  ├─ settings.py
│  │  ├─ secrets_loader.py
│  │  └─ policy_loader.py
│  ├─ parsers/
│  │  ├─ common/
│  │  │  ├─ regex_utils.py
│  │  │  ├─ textfsm_loader.py
│  │  │  └─ parser_base.py
│  │  ├─ nexus/
│  │  │  ├─ show_version.py
│  │  │  ├─ show_inventory.py
│  │  │  ├─ show_running_config.py
│  │  │  └─ show_module.py
│  │  └─ catalyst/
│  │     ├─ show_version.py
│  │     ├─ show_inventory.py
│  │     ├─ show_running_config.py
│  │     └─ show_module.py
│  ├─ normalization/
│  │  ├─ inventory_model.py
│  │  ├─ feature_extraction.py
│  │  ├─ platform_mapper.py
│  │  └─ location_mapper.py
│  ├─ discrepancy/
│  │  ├─ compare_inventory.py
│  │  └─ discrepancy_rules.py
│  ├─ bug_engine/
│  │  ├─ bug_loader.py
│  │  ├─ version_matcher.py
│  │  ├─ feature_matcher.py
│  │  ├─ bug_correlator.py
│  │  ├─ scoring.py
│  │  └─ recommendation.py
│  ├─ data/
│  │  ├─ duckdb_manager.py
│  │  ├─ schema.sql
│  │  └─ repositories.py
│  ├─ exporters/
│  │  ├─ excel_exporter.py
│  │  ├─ pdf_exporter.py
│  │  ├─ pptx_exporter.py
│  │  └─ executive_pack.py
│  ├─ security/
│  │  ├─ api_guard.py
│  │  ├─ audit.py
│  │  └─ retention.py
│  └─ integrations/
│     └─ cisco_api/
│        ├─ client.py
│        ├─ auth.py
│        ├─ policy_checks.py
│        └─ sync_bugs.py
├─ data/
│  ├─ samples/
│  │  ├─ nexus/
│  │  ├─ catalyst/
│  │  ├─ inventory_excel/
│  │  └─ telemetry/
│  ├─ bug_datasets/
│  │  ├─ internal/
│  │  │  ├─ bugs_master.csv
│  │  │  └─ bugs_master.json
│  │  └─ synced/
│  └─ policies/
│     ├─ default_policy.yaml
│     ├─ demo_policy.yaml
│     └─ enterprise_locked_policy.yaml
├─ docker/
│  ├─ Dockerfile
│  ├─ docker-compose.yml
│  └─ entrypoint.sh
├─ docs/
│  ├─ README.md
│  ├─ architecture.md
│  ├─ decisions.md
│  ├─ backlog.md
│  ├─ api_security.md
│  ├─ data_model.md
│  ├─ export_format.md
│  ├─ performance.md
│  └─ demo_script.md
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ performance/
│  └─ fixtures/
├─ scripts/
│  ├─ seed_sample_data.py
│  ├─ generate_synthetic_inventory.py
│  └─ run_demo.sh
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
└─ Makefile
