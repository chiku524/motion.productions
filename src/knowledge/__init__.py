# Base knowledge: schema and extraction from video files

from .schema import BaseKnowledgeExtract
from .extractor import extract_from_video

__all__ = [
    "BaseKnowledgeExtract",
    "extract_from_video",
]
