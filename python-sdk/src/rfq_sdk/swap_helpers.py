"""Helper functions for processing swap updates.

Thin compatibility shim — the canonical helpers live on
:class:`rfq_sdk.streaming.swap_update_helpers` (mirroring the Rust module
``streaming::swap_update_helpers``). Import from there in new code.
"""

from .streaming import swap_update_helpers as _h

is_pong = _h.is_pong
is_connection_ready = _h.is_connection_ready
is_error = _h.is_error
is_transaction_confirmed = _h.is_transaction_confirmed
is_swap_available = _h.is_swap_available
get_status_message = _h.get_status_message
get_swap_uuid = _h.get_swap_uuid
get_unsigned_transaction = _h.get_unsigned_transaction
get_transaction_signature = _h.get_transaction_signature
extract_confirmation_details = _h.extract_confirmation_details
extract_swap_details = _h.extract_swap_details
update_type_description = _h.update_type_description

__all__ = [
    "extract_confirmation_details",
    "extract_swap_details",
    "get_status_message",
    "get_swap_uuid",
    "get_transaction_signature",
    "get_unsigned_transaction",
    "is_connection_ready",
    "is_error",
    "is_pong",
    "is_swap_available",
    "is_transaction_confirmed",
    "update_type_description",
]
