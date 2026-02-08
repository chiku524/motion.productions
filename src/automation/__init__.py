"""
Automation: procedural prompt generation and continuous knowledge-building.
No external models — uses only our keyword data.
"""
from .prompt_gen import generate_procedural_prompt, generate_prompt_batch

__all__ = ["generate_procedural_prompt", "generate_prompt_batch"]
