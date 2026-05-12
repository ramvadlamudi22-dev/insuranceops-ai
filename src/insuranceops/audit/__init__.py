"""Audit module: hash-chained audit event management and verification."""

from insuranceops.audit.chain import append_audit_event
from insuranceops.audit.verifier import VerificationResult, verify_chain

__all__ = ["append_audit_event", "verify_chain", "VerificationResult"]
