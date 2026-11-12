"""Facts that sit next to an AI answer and come from the services, never from the model's text. PRESENTATION ONLY: it only
calls backend.services.trust (read-only, no model call, no SQL here).
"""
from backend.services import sources, trust


def service_flags(application_ids):
    """application_id -> ["Offer deadline overdue" | "Status conflict"] (rule-based, see backend/services/trust.py)."""
    return trust.risk_flags(application_ids)


def source_labels(refs):
    """Readable labels for [file:id] references, grouped by candidate (DB lookup in backend/services/sources.py)."""
    return sources.source_labels(refs)


def candidate_names():
    return sources.candidate_names()
