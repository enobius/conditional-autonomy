"""Request seed encoding from the owner-supplied Stage 2 draft v5.

This pure helper does not authorize evaluation or freeze any run configuration.
"""

from __future__ import annotations

import hashlib
import struct


def request_seed(
    trial_seed: int, evaluation_instance_id: str, global_model_call_index: int
) -> int:
    """Return the signed-safe seed for one zero-based episode model request."""
    for name, value in (
        ("trial_seed", trial_seed),
        ("global_model_call_index", global_model_call_index),
    ):
        if type(value) is not int or not 0 <= value < 2**64:
            raise ValueError(f"{name} must be an unsigned 64-bit integer")
    if not isinstance(evaluation_instance_id, str) or not evaluation_instance_id:
        raise ValueError("evaluation_instance_id must be a nonempty string")
    encoded_id = evaluation_instance_id.encode("utf-8")
    if len(encoded_id) >= 2**32:
        raise ValueError("encoded evaluation_instance_id exceeds uint32 length")
    message = (
        struct.pack(">Q", trial_seed)
        + struct.pack(">I", len(encoded_id))
        + encoded_id
        + struct.pack(">Q", global_model_call_index)
    )
    return int.from_bytes(hashlib.sha256(message).digest()[:4], "big") & 0x7FFFFFFF
