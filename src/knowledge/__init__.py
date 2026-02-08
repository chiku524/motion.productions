# Base knowledge: schema, extraction, origins, blending, growth

from .schema import BaseKnowledgeExtract
from .extractor import extract_from_video
from .origins import get_all_origins, get_origin_domains
from .blending import (
    blend_colors,
    blend_palettes,
    blend_motion_params,
    blend_intensity,
    blend_lighting_presets,
    BLEND_APPROACHES,
    BLEND_FUNCTIONS_BY_DOMAIN,
)
from .registry import load_registry, save_registry, list_documented_blends
from .growth import grow_from_extract, grow_from_analysis
from .lookup import get_knowledge_for_creation
from .blend_names import generate_blend_name
from .domain_extraction import extract_to_domains, analysis_dict_to_domains
from .name_reserve import refill, take, reserve_status, ensure_reserve
from .remote_sync import grow_and_sync_to_api, post_discoveries

__all__ = [
    "BaseKnowledgeExtract",
    "extract_from_video",
    "get_all_origins",
    "get_origin_domains",
    "blend_colors",
    "blend_palettes",
    "blend_motion_params",
    "blend_intensity",
    "blend_lighting_presets",
    "BLEND_APPROACHES",
    "BLEND_FUNCTIONS_BY_DOMAIN",
    "generate_blend_name",
    "load_registry",
    "save_registry",
    "list_documented_blends",
    "grow_from_extract",
    "grow_from_analysis",
    "get_knowledge_for_creation",
    "extract_to_domains",
    "analysis_dict_to_domains",
    "refill",
    "take",
    "reserve_status",
    "ensure_reserve",
    "grow_and_sync_to_api",
    "post_discoveries",
]
