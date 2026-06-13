"""agents.image_gen — provider image-generation adapters.

Public API:
    from agents.image_gen.dispatch import generate_image_bytes
    from agents.image_gen.base import ImageGenError
"""
from agents.image_gen.base import ImageGenError
from agents.image_gen.dispatch import generate_image_bytes

__all__ = ["ImageGenError", "generate_image_bytes"]
