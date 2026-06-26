# UrbanAgent Tool Inventory

Classified following GeoAgent's 3-category taxonomy (Lin et al., Table 1).

## Summary

| Category | Count | Description |
|----------|-------|-------------|
| System Interaction | 6 | External service calls, connectors, infrastructure |
| Data Understanding | 7 | Spatial analytics, data transformation, metrics |
| Domain Knowledge | 5 | Visualization, reporting, domain-specific reasoning |
| **Total** | **18** | |

## System Interaction Tools (6)

| Tool | Description | Access |
|------|-------------|--------|
| `fetch_osm_data` | Fetch OpenStreetMap data for a given area | Perception: R/W |
| `list_connectors` | List available external connectors | All: R |
| `rhino_health_check` | Check Rhino.Compute service status | All: R |
| `evaluate_grasshopper_definition` | Execute Grasshopper definition files | Cartographer: R/W |
| `call_grasshopper_hops` | Call Grasshopper Hops remote endpoints | Cartographer: R/W |
| `invoke_rhino_compute` | Call Rhino.Compute REST endpoints | Cartographer: R/W |

## Data Understanding Tools (7)

| Tool | Description | Access |
|------|-------------|--------|
| `analyze_connectivity` | Analyze road network connectivity | Analyst: R/W |
| `measure_accessibility` | Measure building-to-POI accessibility | Analyst: R/W |
| `calculate_density` | Calculate building density distribution | Analyst: R/W |
| `build_topology` | Build topological graph from spatial features | Analyst: R/W |
| `export_geojson` | Export GeoJSON spatial data | Cartographer/Analyst: W |
| `infer_population_from_indicators` | Estimate population from indicators | Analyst: R/W |
| `rank_traffic_signal_phases` | Rank traffic signal phases by priority | Analyst: R/W |

## Domain Knowledge Tools (5)

| Tool | Description | Access |
|------|-------------|--------|
| `generate_svg_overlay` | Generate SVG spatial visualization | Cartographer: W |
| `generate_measurement_report` | Generate spatial measurement reports | Reporter: W |
| `select_multiple_choice_option` | Map raw answers to standard options | Analyst: R/W |
| `score_navigation_plan` | Evaluate navigation action sequence | Analyst/Reviewer: R |
| `select_exploration_target` | Select optimal exploration target | Analyst: R/W |

## Access Control Matrix

Following RMDA's role-based permission model (Sun et al., Table 2):

| Role | System Interaction | Data Understanding | Domain Knowledge |
|------|-------------------|-------------------|-----------------|
| Planner | R | R | R |
| Perception | R/W | R/W | R |
| Analyst | R | R/W | R/W |
| Cartographer | R/W | R | R |
| Reporter | R | R | R |
| Spatial Reviewer | R | R | R |
| Quality Controller | R | R | R |
| Manager | R/W | R/W | R/W |

## Comparison with Related Work

| Framework | Tool Count | Categories | Access Control |
|-----------|-----------|------------|----------------|
| GeoAgent (Lin et al.) | 8 | 3 categories | Not formalized |
| RMDA (Sun et al.) | 6 agents | Module-based | Table 2 R/W matrix |
| GeoJSON Agents (Luo et al.) | 2 modes | Function call / Code gen | N/A |
| **UrbanAgent** | **18** | **3 categories** | **8-role R/W matrix** |
