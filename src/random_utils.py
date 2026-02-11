"""
Crypto-quality random for growth and creation (Step 6: ENHANCEMENTS_AND_OPTIMIZATIONS).
Uses secrets module to avoid bias in domain value selection.
"""
import secrets


def secure_choice(sequence):
    """Cryptographically secure random choice. Use for pick_prompt, creation, prompt_gen."""
    if not sequence:
        return None
    return secrets.choice(list(sequence))


def secure_random():
    """Cryptographically secure random float in [0, 1)."""
    return secrets.SystemRandom().random()
