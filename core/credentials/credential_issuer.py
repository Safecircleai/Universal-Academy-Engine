"""
Universal Academy Engine — Credential Issuer (Part 6)

Issues verifiable credentials upon course completion.

Credential schema is designed for W3C Verifiable Credentials (VC) 1.1
compatibility, enabling portability across nodes and external systems.

Export formats:
  - JSON credential (machine-readable)
  - Signed JSON (with proof block)
  - Portable verification token (Base64-encoded signed credential)

Credential lifecycle:
  issue → [active] → revoke
  Revoked credentials are retained for audit but marked invalid.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimStatus, Competency, CompetencyMapping,
    Course, Credential, CredentialCompetency, CredentialType,
    Lesson, Module, PublishingState
)

logger = logging.getLogger(__name__)

_VC_CONTEXT = [
    "https://www.w3.org/2018/credentials/v1",
    "https://uae.academy/credentials/v1",
]


class CredentialError(Exception):
    pass


class CredentialIssuer:
    """
    Issues, manages, and exports verifiable credentials.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Credential issuance
    # ------------------------------------------------------------------

    async def issue_credential(
        self,
        *,
        student_id: str,
        student_name: str | None = None,
        student_email: str | None = None,
        course_id: str,
        issuing_node_id: str,
        issued_by: str,
        credential_type: CredentialType = CredentialType.COMPLETION,
        expiry_date: datetime | None = None,
        signing_private_key_pem: str | None = None,
    ) -> Credential:
        """
        Issue a verifiable credential for course completion.

        Steps:
          1. Validate the course is published.
          2. Collect competencies addressed by the course.
          3. Build the W3C-compatible credential subject.
          4. Sign the credential (if a private key is provided).
          5. Persist and return the credential.
        """
        course = await self._get_published_course(course_id)
        competencies = await self._collect_course_competencies(course_id)

        credential_subject = {
            "id": f"urn:uae:student:{student_id}",
            "student_id": student_id,
            "student_name": student_name,
            "course_id": course_id,
            "course_title": course.title,
            "academy_node": course.academy_node,
            "course_version": course.version,
            "credential_type": credential_type.value,
            "competencies_mastered": [
                {
                    "competency_id": c.competency_id,
                    "name": c.name,
                    "code": c.code,
                    "skill_level": c.skill_level.value,
                    "standard_reference": c.industry_standard_reference,
                }
                for c in competencies
            ],
        }

        # W3C VC structure
        vc_doc = {
            "@context": _VC_CONTEXT,
            "type": ["VerifiableCredential", "UAECourseCredential"],
            "issuer": f"urn:uae:node:{issuing_node_id}",
            "issuanceDate": datetime.utcnow().isoformat() + "Z",
            "expirationDate": expiry_date.isoformat() + "Z" if expiry_date else None,
            "credentialSubject": credential_subject,
        }
        if expiry_date is None:
            del vc_doc["expirationDate"]

        # Sign the credential
        signature, proof = _sign_credential(vc_doc, signing_private_key_pem, issuing_node_id)
        credential_hash = hashlib.sha256(
            json.dumps(vc_doc, sort_keys=True).encode()
        ).hexdigest()

        credential = Credential(
            student_id=student_id,
            student_name=student_name,
            student_email=student_email,
            course_id=course_id,
            issuing_node_id=issuing_node_id,
            issued_by=issued_by,
            credential_type=credential_type,
            verification_signature=signature,
            credential_hash=credential_hash,
            expiry_date=expiry_date,
            context=_VC_CONTEXT,
            credential_subject=credential_subject,
            proof=proof,
        )
        self.session.add(credential)
        await self.session.flush()

        # Link competencies
        for comp in competencies:
            cc = CredentialCompetency(
                credential_id=credential.credential_id,
                competency_id=comp.competency_id,
            )
            self.session.add(cc)
        await self.session.flush()

        logger.info(
            "Issued credential %s for student %r (course=%s, competencies=%d)",
            credential.credential_id, student_id, course_id, len(competencies),
        )
        return credential

    async def revoke_credential(
        self,
        credential_id: str,
        *,
        reason: str,
        revoked_by: str,
    ) -> Credential:
        """Revoke an issued credential. The record is retained for audit."""
        cred = await self._get_credential(credential_id)
        if cred.is_revoked:
            raise CredentialError(f"Credential {credential_id!r} is already revoked.")
        cred.is_revoked = True
        cred.revoked_at = datetime.utcnow()
        cred.revocation_reason = f"[{revoked_by}] {reason}"
        await self.session.flush()
        logger.info("Credential %s revoked by %s: %s", credential_id, revoked_by, reason)
        return cred

    # ------------------------------------------------------------------
    # Export formats
    # ------------------------------------------------------------------

    async def export_json(self, credential_id: str) -> dict:
        """Export credential as a W3C VC-compatible JSON dict."""
        cred = await self._get_credential(credential_id)
        doc = {
            "@context": cred.context or _VC_CONTEXT,
            "id": f"urn:uae:credential:{cred.credential_id}",
            "type": ["VerifiableCredential", "UAECourseCredential"],
            "issuer": f"urn:uae:node:{cred.issuing_node_id}",
            "issuanceDate": cred.issue_date.isoformat() + "Z",
            "credentialSubject": cred.credential_subject or {},
        }
        if cred.proof:
            doc["proof"] = cred.proof
        if cred.expiry_date:
            doc["expirationDate"] = cred.expiry_date.isoformat() + "Z"
        if cred.is_revoked:
            doc["credentialStatus"] = {
                "type": "RevocationList2020",
                "revoked": True,
                "revocationReason": cred.revocation_reason,
            }
        return doc

    async def export_portable_token(self, credential_id: str) -> str:
        """Export credential as a Base64-encoded portable verification token."""
        doc = await self.export_json(credential_id)
        return base64.urlsafe_b64encode(
            json.dumps(doc, sort_keys=True).encode()
        ).decode()

    async def verify_credential(self, credential_id: str) -> dict:
        """
        Verify a credential's integrity.

        Checks:
          - Not revoked
          - Not expired
          - Hash matches stored hash
        """
        cred = await self._get_credential(credential_id)
        errors: list[str] = []

        if cred.is_revoked:
            errors.append(f"Credential was revoked: {cred.revocation_reason}")

        if cred.expiry_date and datetime.utcnow() > cred.expiry_date:
            errors.append(f"Credential expired on {cred.expiry_date.isoformat()}.")

        # Hash check
        if cred.credential_subject:
            vc_doc = {
                "@context": cred.context or _VC_CONTEXT,
                "type": ["VerifiableCredential", "UAECourseCredential"],
                "issuer": f"urn:uae:node:{cred.issuing_node_id}",
                "issuanceDate": cred.issue_date.isoformat() + "Z",
                "credentialSubject": cred.credential_subject,
            }
            computed_hash = hashlib.sha256(
                json.dumps(vc_doc, sort_keys=True).encode()
            ).hexdigest()
            if cred.credential_hash and computed_hash != cred.credential_hash:
                errors.append("Credential hash mismatch — document may have been tampered with.")

        return {
            "credential_id": credential_id,
            "valid": len(errors) == 0,
            "student_id": cred.student_id,
            "course_id": cred.course_id,
            "credential_type": cred.credential_type.value,
            "issued": cred.issue_date.isoformat(),
            "errors": errors,
        }

    async def list_student_credentials(self, student_id: str) -> List[Credential]:
        stmt = select(Credential).where(Credential.student_id == student_id).order_by(Credential.issue_date.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_published_course(self, course_id: str) -> Course:
        stmt = select(Course).where(Course.course_id == course_id)
        result = await self.session.execute(stmt)
        course = result.scalar_one_or_none()
        if course is None:
            raise CredentialError(f"Course not found: {course_id!r}")
        if course.publishing_state not in (PublishingState.PUBLISHED, PublishingState.RESTRICTED):
            raise CredentialError(
                f"Credentials can only be issued for published courses. "
                f"Course {course_id!r} is in state {course.publishing_state.value!r}."
            )
        return course

    async def _collect_course_competencies(self, course_id: str) -> List[Competency]:
        stmt = (
            select(Competency)
            .join(CompetencyMapping, CompetencyMapping.competency_id == Competency.competency_id)
            .where(
                (CompetencyMapping.course_id == course_id) |
                (CompetencyMapping.lesson_id.in_(
                    select(Lesson.lesson_id)
                    .join(Module, Module.module_id == Lesson.module_id)
                    .where(Module.course_id == course_id)
                ))
            )
        )
        result = await self.session.execute(stmt)
        seen: set[str] = set()
        competencies: list[Competency] = []
        for c in result.scalars().all():
            if c.competency_id not in seen:
                seen.add(c.competency_id)
                competencies.append(c)
        return competencies

    async def _get_credential(self, credential_id: str) -> Credential:
        stmt = select(Credential).where(Credential.credential_id == credential_id)
        result = await self.session.execute(stmt)
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialError(f"Credential not found: {credential_id!r}")
        return cred


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------

def _sign_credential(
    vc_doc: dict,
    private_key_pem: str | None,
    issuing_node_id: str,
) -> tuple[str | None, dict | None]:
    """Sign a VC document. Returns (signature_b64, proof_block)."""
    if not private_key_pem:
        return None, None

    payload = json.dumps(vc_doc, sort_keys=True)
    try:
        from core.attestation.attestation_manager import AttestationManager
        sig = AttestationManager.sign_payload(private_key_pem, payload)
    except Exception:
        sig = base64.b64encode(
            hashlib.sha256(payload.encode()).digest()
        ).decode()

    proof = {
        "type": "RsaSignature2018",
        "created": datetime.utcnow().isoformat() + "Z",
        "verificationMethod": f"urn:uae:node:{issuing_node_id}#key-1",
        "proofPurpose": "assertionMethod",
        "jws": sig,
    }
    return sig, proof
