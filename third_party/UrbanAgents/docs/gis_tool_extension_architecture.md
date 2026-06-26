# GIS Tool Extension Architecture For Urban-Hermes

Date: 2026-05-19

## 1. Design Position

GIS integration should be implemented as a **tool extension package**, not as more code embedded inside the Urban-Hermes core runtime.

The Urban-Hermes core should only know how to:

1. discover an available GIS backend;
2. pass a standardized task/artifact manifest to that backend;
3. receive a standardized validation report;
4. record failures, corrections, and reusable lessons into memory.

The backend package should handle all GIS-specific details, such as QGIS Python, ArcPy, map project creation, renderer binding, web-map export, and independent validation.

This gives us a stronger answer to the paper gaps:

- **Gap 2: Verifiable tool use.** The agent's GIS claims are checked through external artifacts and validators, not by trusting generated text.
- **Gap 3: Reusable and transferable tool integration.** GIS capabilities can be packed, swapped, validated, and distributed across machines with different installed software.

## 2. Current Baseline

Current QGIS support is distributed across several places:

```text
paper4_urban_svgagent/
  hermes_urban_agent/urban_hermes/tools.py
    - urban_qgis_workspace
    - urban_qgis_process

  plugins/qgis/
    - qgis_tools.py
    - qgis_project_gen.py
    - qgis_bridge.py

  scripts/
    - package_case1_qgis_workspace.py
    - qgis_live_bridge.py

  experiments/case2_tester_package/qgis_validation/
    - validate_case_qgis.py
```

This already proves the concept, but the responsibilities are mixed:

- Hermes tool registration is in the core adapter.
- QGIS project generation is in a plugin folder.
- Case-specific packaging is in `scripts/`.
- External validation is copied into the experiment package.

The next step is not to delete this. The safer migration is to wrap and reorganize it under a backend protocol.

## 3. Proposed Directory Layout

Create a new source-of-truth package:

```text
paper4_urban_svgagent/
  plugins/
    gis_backends/
      README.md
      protocol.py
      registry.py
      schemas/
        spatial_reasoning_manifest.schema.json
        gis_backend_spec.schema.json
        gis_validation_report.schema.json
      common/
        manifest_io.py
        process_runner.py
        path_checks.py
        validation_report.py
      qgis_desktop/
        backend.py
        runtime.py
        package_workspace.py
        validate_workspace.py
        bridge.py
      arcgis_pro/
        backend.py
        runtime.py
        package_workspace.py
        validate_workspace.py
      web_map/
        backend.py
        package_workspace.py
        validate_workspace.py
        templates/
```

Keep Urban-Hermes thin:

```text
paper4_urban_svgagent/
  hermes_urban_agent/urban_hermes/
    tools.py              # existing tool registry
    tools_gis.py          # optional thin wrapper if tools.py becomes too large
```

Keep distributable reviewer scripts in the experiment package, but treat them as copies exported from the backend package:

```text
experiments/case2_tester_package/
  gis_validation/
    validate_case_qgis.py
    validate_case_arcgis.py          # future
    validate_case_web_map.py         # future
```

Rule of thumb:

> Source-of-truth code belongs in `plugins/gis_backends`. Experiment packages contain frozen copies or wrappers for collaborators.

## 4. Backend Protocol

Every GIS backend should implement the same conceptual interface.

### 4.1 Backend Spec

Each backend declares:

```json
{
  "backend_id": "qgis_desktop",
  "display_name": "QGIS Desktop",
  "runtime_kind": "qgis_python",
  "workspace_outputs": ["qgz", "gpkg", "png", "json"],
  "supports_processing": true,
  "supports_live_bridge": true,
  "supports_headless_validation": true,
  "required_executables": ["python-qgis-ltr.bat", "qgis_process-qgis-ltr.bat"],
  "validator": "qgis_desktop.validate_workspace"
}
```

ArcGIS Pro would declare:

```json
{
  "backend_id": "arcgis_pro",
  "display_name": "ArcGIS Pro",
  "runtime_kind": "arcpy",
  "workspace_outputs": ["aprx", "gdb", "lyrx", "png", "pdf", "json"],
  "supports_processing": true,
  "supports_live_bridge": false,
  "supports_headless_validation": true,
  "required_executables": ["arcgispro-py3/python.exe"],
  "validator": "arcgis_pro.validate_workspace"
}
```

Web map would declare:

```json
{
  "backend_id": "web_map",
  "display_name": "Browser Web Map",
  "runtime_kind": "browser",
  "workspace_outputs": ["html", "geojson", "png", "json"],
  "supports_processing": false,
  "supports_live_bridge": false,
  "supports_headless_validation": true,
  "required_executables": ["browser_or_playwright"],
  "validator": "web_map.validate_workspace"
}
```

### 4.2 Standard Input

All backends receive the same minimal request:

```json
{
  "task_id": "case2_city_vitality",
  "case_id": "collaborator_realistic_dialogue",
  "run_dir": "D:/UrbanAgents_Case2_Output/realistic_dialogue/turn2b_execute",
  "artifact_manifest": "D:/.../spatial_reasoning_manifest.json",
  "backend": "qgis_desktop",
  "output_dir": "D:/.../qgis_workspace",
  "mode": "package_and_validate"
}
```

### 4.3 Standard Output

All backends return:

```json
{
  "backend": "qgis_desktop",
  "success": true,
  "workspace_dir": "D:/.../qgis_workspace",
  "workspace_manifest": "D:/.../qgis_workspace/manifests/spatial_reasoning_manifest.json",
  "validation_report": "D:/.../artifact_validation_independent.json",
  "acceptance": {
    "accepted": true,
    "blocking_errors": [],
    "warnings": [],
    "known_limits": []
  }
}
```

The exact project format can differ, but this return shape should not.

## 5. Artifact Contract

The backend extension should make `spatial_reasoning_manifest.json` the center of the workflow.

Minimum required fields:

```json
{
  "task_id": "case2_city_vitality",
  "case_id": "...",
  "created_at": "...",
  "coordinate_reference_system": "EPSG:4326",
  "spatial_scope": {
    "scope_kind": "explicit_study_area | layer_derived_or_task_defined",
    "study_area": {
      "name": "optional",
      "geometry_path": "optional",
      "bbox": [0, 0, 0, 0]
    },
    "context_area": "optional",
    "description": "optional"
  },
  "layers": [
    {
      "id": "road_density_grid",
      "role": "metric_layer",
      "path": "...",
      "geometry_type": "Polygon",
      "feature_count": 100,
      "metric_fields": ["road_density_m_per_ha"],
      "renderer": {
        "type": "graduated",
        "field": "road_density_m_per_ha"
      }
    }
  ],
  "tables": [],
  "maps": [],
  "known_limits": []
}
```

The validator should never rely only on report prose. It should read this manifest and check that paths, fields, layers, renderers, and exported maps exist.

### 5.1 Plain-Language Meaning Of Manifest Fields

`spatial_scope` means "what spatial world does this task cover?" It replaces a hard-coded `AOI` requirement. Some tasks have a formal study boundary, such as a historic district polygon. Some tasks only have input layers, a route, a set of parcels, a sampled grid, or a citywide dataset. In those cases there is no universal AOI, and the backend should use `scope_kind="layer_derived_or_task_defined"`.

`study_area` is optional. It is the authoritative research boundary only when the task actually has one. Case1 uses this pattern, but it should not be forced onto all cases.

`context_area` is optional. It means surrounding context collected for interpretation, such as a buffer around a district, nearby roads, POIs, or background buildings. It should not be silently treated as the study area.

`coordinate_reference_system` or `CRS` tells the GIS software how coordinates should be interpreted. Without it, distance, area, overlay, and rendering can be wrong.

`input layers` are the data the task starts from: roads, buildings, POIs, parcels, social-media points, administrative boundaries, survey points, or any other source layer.

`output layers` are the layers produced by analysis: grids with indicators, clipped roads, accessibility nodes, hotspot polygons, model residuals, or classified zones.

`metric fields` are the attribute columns that carry computed indicators, such as `road_density_m_per_ha`, `accessibility_score`, `building_coverage_ratio`, or `vitality_score`.

`renderer field` is the field actually used to color or classify a map layer. A metric field existing in a table is not enough; if the map claims to show vitality, the renderer should be bound to the vitality field.

`maps`, screenshots, and project paths are the human-reviewable outputs. They point to files such as `.qgz`, `.aprx`, `.html`, `.png`, or `.pdf`.

`known_limits` records what the artifact cannot prove: proxy variables, missing height data, uncertain geocoding, synthetic smoke data, incomplete basemaps, or unavailable backend software.

## 6. Validation Contract

Every backend validator should produce a normalized report.

Required top-level fields:

```json
{
  "backend": "qgis_desktop",
  "runtime": {
    "available": true,
    "executable": "...",
    "version": "..."
  },
  "project_read_ok": true,
  "layer_count": 0,
  "layers": [],
  "missing_datasources": [],
  "invalid_layers": [],
  "missing_metric_fields": [],
  "renderer_checks": [],
  "exported_maps": [],
  "manifest_consistency": {
    "ok": true,
    "missing_paths": [],
    "schema_errors": []
  },
  "needs_correction": false,
  "blocking_errors": [],
  "warnings": []
}
```

Backend-specific fields are allowed, but the normalized fields above must exist so Hermes can reason over failures without knowing the details of QGIS or ArcGIS.

## 7. Urban-Hermes Tool Surface

Short term, keep the existing tools:

```text
urban_qgis_workspace
urban_qgis_process
```

Add one generic tool only after the backend package is stable:

```text
urban_gis_workspace
```

Suggested schema:

```json
{
  "backend": "qgis_desktop | arcgis_pro | web_map | auto",
  "run_dir": "string",
  "artifact_manifest": "string",
  "mode": "probe | package | validate | package_and_validate",
  "output_dir": "string",
  "runtime_executable": "string optional",
  "timeout": 600
}
```

Hermes should then call the backend extension, not implement GIS logic itself.

Possible internal call path:

```text
urban_gis_workspace
  -> plugins.gis_backends.registry.resolve_backend(...)
  -> backend.probe_runtime()
  -> backend.package_workspace(...)
  -> backend.validate_workspace(...)
  -> normalized validation report
  -> urban_research_memory / urban_record_feedback
```

This keeps the LLM-facing tool stable while allowing backends to be added or removed.

## 8. Acceptance Workflow

The GIS workflow should be staged and auditable.

### Stage 1: Probe

Check local runtime availability:

```text
QGIS Python available?
ArcGIS Pro ArcPy available?
Browser/web validator available?
```

Output:

```text
gis_backend_probe.json
```

### Stage 2: Package

Convert common artifacts into backend-native review workspace:

```text
QGIS: .qgz + gpkg + styles + png
ArcGIS Pro: .gdb + optional .aprx from template + optional png/pdf
Web map: index.html + geojson + style json + screenshots
```

Output:

```text
<backend>_workspace/
```

### Stage 3: Validate

Run independent backend validator.

Output:

```text
<backend>_validation.json
```

### Stage 4: Accept Or Correct

Acceptance requires:

- project, geodatabase, or web map opens successfully, depending on backend and validation level;
- no broken/invalid layers;
- all declared manifest paths exist;
- metric fields exist in the actual layers;
- renderer fields match the declared metric fields;
- exported image/PDF/screenshot exists when the backend is expected to produce visual outputs;
- `needs_correction=false`.

For ArcGIS Pro, FileGDB validation is a valid data-level acceptance. Full visual acceptance additionally uses a readable `.aprx` template. The backend first searches ArcGIS Pro's default `Blank.aprx`; `template_aprx` is only needed when the default template is unavailable.

If any condition fails, Hermes must treat the GIS artifact as incomplete and either correct it or record the limitation.

## 9. Migration Plan

Implementation status on 2026-05-19:

- `plugins/gis_backends/qgis_desktop/` exists and has passed a no-AOI smoke run through the real `urban_gis_workspace` tool.
- `plugins/gis_backends/arcgis_pro/` exists and has passed ArcPy runtime probe plus FileGDB package/validate on the same no-AOI smoke fixture.
- The generic `urban_gis_workspace` Hermes tool is registered as a thin wrapper over the backend registry.
- Web map backend is still planned.

### Phase 1: Consolidate QGIS Under The Protocol

Move or wrap current QGIS logic into:

```text
plugins/gis_backends/qgis_desktop/
```

Initial wrappers can import the existing code from `plugins/qgis` to avoid breaking working code.

Done / current behavior:

1. `plugins/gis_backends` package created;
2. `spatial_scope` manifest normalization added;
3. QGIS Desktop backend creates `.qgz` and PNG preview from declared layers;
4. QGIS validator checks project readability, invalid layers, missing datasources, metric fields, renderer fields, manifest consistency;
5. old QGIS-specific tools remain available for backward compatibility.

### Phase 2: Add Generic Hermes Entry Tool

Add `urban_gis_workspace` as a thin wrapper. Keep `urban_qgis_workspace` for backward compatibility.

Done / current behavior:

1. `urban_gis_workspace` schema added to `urban_hermes/tools.py`;
2. `backend="auto"` resolves to `qgis_desktop`;
3. `backend="qgis_desktop"` and `backend="arcgis_pro"` are supported;
4. normalized validation reports are returned to Hermes.

### Phase 3: ArcGIS Pro Backend

Add ArcGIS Pro as a backend without changing the LLM-facing protocol.

Done / current behavior:

1. ArcGIS Pro Python / ArcPy detection works;
2. layers are packaged into a file geodatabase;
3. GeoJSON Point, LineString, Polygon, MultiLineString, and MultiPolygon are written with ArcPy cursors so metric fields are preserved;
4. FileGDB feature count, metric fields, spatial reference, and manifest consistency are validated;
5. `.aprx` creation is supported through automatic `Blank.aprx` discovery or an explicit `template_aprx`; without a readable template the backend emits a warning, not a false project artifact.

Remaining ArcGIS Pro work:

1. refine a minimal `.aprx` template and layout for collaborator machines when the default ArcGIS Pro blank project is not enough;
2. add optional `.lyrx` symbology application;
3. export layout PNG/PDF from the template;
4. validate broken project layers and exported maps as full visual acceptance.

### Phase 4: Web Map Backend

Add a cross-platform visual review backend.

Tasks:

1. generate static Leaflet/MapLibre viewer;
2. load GeoJSON and style metadata from manifest;
3. export screenshots with Playwright;
4. validate page nonblank, layer count, and manifest consistency.

## 10. Collaborator Package Policy

The collaborator package should not ask the tester to understand all backend internals.

It should say:

```text
If QGIS is installed: run QGIS validation.
If only ArcGIS Pro is installed: run ArcGIS validation.
If neither GIS desktop is installed: return common artifacts and web-map validation if available.
```

Required return files:

```text
transcript.md
spatial_reasoning_manifest.json
<backend>_workspace/
<backend>_validation.json
tester_notes.md
```

This lets the experiment compare not just final maps, but also whether the agent can select, invoke, repair, and validate tools under different local environments.

## 11. How This Supports The Paper Claims

This architecture directly supports two claims.

First, it strengthens verifiability. The GIS process leaves a checkable trail:

```text
prompt -> tool call -> artifact manifest -> backend workspace -> independent validation -> correction/memory
```

Second, it strengthens transferability. The same protocol can run through QGIS, ArcGIS Pro, or a web map without rewriting the research task:

```text
same task + same manifest + different backend adapter + same validation contract
```

This is the key paper argument: Urban-Hermes is not just calling tools opportunistically. It accumulates reusable tool-use procedures and turns external software into modular, inspectable, shareable research instruments.