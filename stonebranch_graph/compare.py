from __future__ import annotations

from .comparison_model import Comparison, SideComparisonIndex
from .compare_engine import (
    build_diagnostics,
    build_edge_diff_payloads,
    build_node_diff_payloads,
    build_risks,
    build_side_indexes,
    build_summary,
    bucket_edges,
    bucket_nodes,
    compare_graphs,
    compare_matched_attributes,
    single_item_index,
)
from .compare_keys import (
    comparison_edge_components,
    comparison_edge_key,
    comparison_kind,
    comparison_node_key,
    edge_key_parts,
    lookup_mapping,
    normalize_key,
)
from .compare_payloads import (
    command_difference_payload,
    command_difference_reason,
    command_normalization_payload,
    combined_command_normalization_diagnostics,
    comparable_hash,
    condition_difference_payload,
    count_command_differences_by_status,
    edge_pair_payload,
    edge_payload,
    list_of_strings,
    node_pair_payload,
    node_payload,
    node_payload_with_key,
)
from .compare_diagnostics import (
    collision_node_payload,
    collision_payload,
    edge_collision_payload,
    node_collision_payload,
    node_enterprise_parts,
    unused_mapping_payload,
)
from .compare_export import (
    append_collision_section,
    append_command_normalization_section,
    export_comparison,
    write_command_diff_csv,
    write_critical_diff,
    write_diagnostics_csv,
    write_diff_index,
    write_edge_diff_csv,
    write_missing_csvs,
    write_overlay_mermaid,
    write_remediation_plan,
    write_report,
)

__all__ = [
    "Comparison",
    "SideComparisonIndex",
    "compare_graphs",
    "export_comparison",
    "normalize_key",
    "comparison_edge_key",
    "comparison_node_key",
    "comparison_kind",
    "comparison_edge_components",
    "edge_key_parts",
]
