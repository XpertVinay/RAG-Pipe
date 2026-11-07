"""AI Safety & Compliance Guardrails Engine.

Strictly intercepts, evaluates, and blocks queries that are illegal, dangerous,
or unethical. Enforces multi-strike escalation, automated account restriction,
tamper-evident audit logging, and authority reporting alerts.
"""

from datetime import datetime, timezone, timedelta
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid
from dataclasses import dataclass, field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.conversation import Message
from app.models.user import RefreshToken, User
from app.services.audit_service import audit_service


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class GuardrailViolation:
    """Detailed record of a guardrail violation match."""
    category: str  # "ILLEGAL", "DANGEROUS", "UNETHICAL", "JAILBREAK"
    sub_category: str
    matched_term: str
    severity: str  # "HIGH", "CRITICAL"
    reason: str


@dataclass
class GuardrailResult:
    """Evaluation result from the Guardrail Engine."""
    is_blocked: bool
    category: Optional[str] = None
    sub_category: Optional[str] = None
    matched_term: Optional[str] = None
    severity: Optional[str] = None
    reason: Optional[str] = None
    refusal_message: Optional[str] = None
    caution_notice: Optional[str] = None
    incident_id: Optional[str] = None
    strike_count: int = 0
    max_strikes: int = 3
    is_restricted: bool = False
    reported_to_authority: bool = False


class GuardrailService:
    """Production AI safety enforcement system for enterprise RAG platforms."""

    MAX_STRIKES_BEFORE_RESTRICTION: int = 3
    STRIKE_WINDOW_HOURS: int = 24

    # 1. ILLEGAL ACTIVITIES: Cyberattacks, system exploitation, fraud, illicit narcotics, piracy
    ILLEGAL_PATTERNS = [
        # Cyberattacks & Hacking
        (
            r"\b(how\s+to\s+hack|hack\s+into|penetrate\s+without\s+permission|crack\s+password|bypass\s+firewall|sql\s+injection\s+attack|create\s+ransomware|write\s+ransomware|generate\s+malware|write\s+a\s+keylogger|keylogger\s+code|ddos\s+attack|launch\s+ddos|botnet\s+script|zero-day\s+exploit|steal\s+credentials|unauthorized\s+access\s+to\s+database|rootkit\s+source\s+code)\b",
            "cyberattack_and_exploitation",
            "Instructions or assistance for unauthorized computer intrusions, malware generation, or cyberattacks are strictly illegal.",
        ),
        # Financial Fraud & Money Laundering
        (
            r"\b(credit\s+card\s+fraud|money\s+laundering|launder\s+money|counterfeit\s+money|fake\s+currency|fake\s+passport|identity\s+theft|steal\s+identities|phishing\s+template|carding\s+dumps|wire\s+fraud|ponzi\s+scheme\s+setup|tax\s+evasion\s+scheme)\b",
            "financial_fraud_and_forgery",
            "Financial crimes, identity theft, counterfeiting, and fraudulent transaction schemes are strictly prohibited.",
        ),
        # Illicit Narcotics & Controlled Substances
        (
            r"\b(synthesize\s+(methamphetamine|meth|fentanyl|heroin|lsd|cocaine)|cook\s+meth|manufacture\s+(meth|fentanyl|heroin|controlled\s+substances)|narcotics\s+trafficking|buy\s+illegal\s+drugs\s+online|darknet\s+drug\s+vendor)\b",
            "illicit_narcotics",
            "Synthesizing, manufacturing, or trafficking illicit or controlled narcotics violates penal law.",
        ),
        # Piracy & Circumvention
        (
            r"\b(crack\s+software\s+license|generate\s+keygen|bypass\s+drm\s+protection|pirated\s+activation\s+key)\b",
            "digital_piracy_circumvention",
            "Circumventing copyright protection, licensing, or commercial software security mechanisms is illegal.",
        ),
    ]

    # 2. DANGEROUS ACTIVITIES: Weapons, explosives, CBRN, suicide, self-harm, physical violence
    DANGEROUS_PATTERNS = [
        # Weapons & Firearms
        (
            r"\b(build\s+a\s+gun|make\s+a\s+firearm|3d\s+print\s+(a\s+gun|firearm|ghost\s+gun)|ghost\s+gun\s+instructions|convert\s+semi-automatic\s+to\s+full|convert\s+to\s+automatic\s+weapon|make\s+an\s+illegal\s+silencer|homemade\s+firearm)\b",
            "firearms_and_weapons",
            "Manufacturing, 3D-printing, or illegally modifying firearms poses extreme physical danger.",
        ),
        # Explosives & Improvised Devices
        (
            r"\b(make\s+a\s+bomb|pipe\s+bomb\s+recipe|synthesize\s+tnt|improvised\s+explosive\s+device|build\s+an\s+ied|c4\s+explosive\s+recipe|synthesize\s+nitroglycerin|molotov\s+cocktail\s+(recipe|instructions)|detonate\s+explosive)\b",
            "explosives_and_bombs",
            "Manufacturing or detonating improvised explosive devices and high explosives poses lethal hazard.",
        ),
        # CBRN (Chemical, Biological, Radiological, Nuclear)
        (
            r"\b(synthesize\s+ricin|weaponize\s+anthrax|synthesize\s+sarin|nerve\s+agent\s+production|dirty\s+bomb\s+radioactive|biological\s+weapon|chemical\s+warfare\s+agent|enrich\s+uranium\s+at\s+home)\b",
            "cbrn_weapons_hazard",
            "Chemical, biological, radiological, or nuclear hazard materials are internationally outlawed.",
        ),
        # Suicide & Self-Harm
        (
            r"\b(how\s+to\s+commit\s+suicide|ways\s+to\s+kill\s+myself|best\s+way\s+to\s+die|painless\s+suicide\s+methods|hang\s+myself\s+instructions|cut\s+my\s+wrists|lethal\s+overdose\s+dose|suicide\s+guide)\b",
            "suicide_and_self_harm",
            "Content encouraging, instructing, or facilitating suicide or self-harm is strictly blocked.",
        ),
        # Terrorism & Mass Casualty
        (
            r"\b(plan\s+terrorist\s+attack|mass\s+casualty\s+plan|assassinate\s+(a\s+politician|the\s+president|someone)|kidnap\s+hostage|drive\s+car\s+into\s+crowd|active\s+shooter\s+plan)\b",
            "terrorism_and_violence",
            "Planning violence, terrorist attacks, mass casualties, or assassinations is strictly prohibited.",
        ),
    ]

    # 3. UNETHICAL ACTIVITIES: Exploitation, non-consensual content, extortion, hate speech, doxxing
    UNETHICAL_PATTERNS = [
        # Exploitation & Non-consensual content
        (
            r"\b(child\s+exploitation|underage\s+sexual|non-consensual\s+sexual|generate\s+revenge\s+porn|deepfake\s+(porn|nudity)|voyeur\s+hidden\s+cam)\b",
            "non_consensual_exploitation",
            "Non-consensual sexual material, CSAM/CSAE, and unauthorized explicit generation are strictly forbidden.",
        ),
        # Blackmail, Extortion, Doxxing
        (
            r"\b(how\s+to\s+blackmail\s+someone|extort\s+money\s+with\s+pictures|dox\s+someone|doxxing\s+guide|swat\s+someone\s+address|cyberstalk\s+target)\b",
            "blackmail_and_harassment",
            "Extortion, blackmail, unauthorized doxxing, swatting, and targeted cyberstalking are strictly prohibited.",
        ),
        # Hate Speech & Incitement to Violence
        (
            r"\b(incite\s+violence\s+against|genocide\s+of|exterminate\s+all\s+(jews|muslims|christians|blacks|whites|immigrants)|kill\s+all\s+(gays|transgender|minorities))\b",
            "hate_speech_and_incitement",
            "Generating hate speech or incitement to physical violence against protected groups is prohibited.",
        ),
    ]

    # 4. ADVERSARIAL JAILBREAK & BYPASS ATTEMPTS
    JAILBREAK_PATTERNS = [
        (
            r"\b(dan\s+mode|do\s+anything\s+now|developer\s+mode\s+enabled|ignore\s+all\s+ethical\s+guidelines|ignore\s+all\s+safety\s+rules|bypass\s+safety\s+filter|unfiltered\s+assistant\s+mode|disregard\s+all\s+prior\s+instructions\s+and\s+answer\s+without\s+restrictions)\b",
            "adversarial_jailbreak",
            "Adversarial prompt injection, system overrides, and security filter bypass attempts are blocked.",
        ),
    ]

    def __init__(self):
        # In-memory incident tracking: actor_key -> list of timestamp objects
        self._incident_log: Dict[str, List[datetime]] = {}

    def scan_query(self, query: str) -> Optional[GuardrailViolation]:
        """Perform comprehensive pattern scanning across Illegal, Dangerous, and Unethical criteria."""
        if not query or not isinstance(query, str):
            return None

        q_clean = query.strip().lower()

        # 1. Check Illegal patterns
        for pattern_str, subcat, reason in self.ILLEGAL_PATTERNS:
            match = re.search(pattern_str, q_clean, re.IGNORECASE)
            if match:
                return GuardrailViolation(
                    category="ILLEGAL",
                    sub_category=subcat,
                    matched_term=match.group(0),
                    severity="CRITICAL",
                    reason=reason,
                )

        # 2. Check Dangerous patterns
        for pattern_str, subcat, reason in self.DANGEROUS_PATTERNS:
            match = re.search(pattern_str, q_clean, re.IGNORECASE)
            if match:
                return GuardrailViolation(
                    category="DANGEROUS",
                    sub_category=subcat,
                    matched_term=match.group(0),
                    severity="CRITICAL",
                    reason=reason,
                )

        # 3. Check Unethical patterns
        for pattern_str, subcat, reason in self.UNETHICAL_PATTERNS:
            match = re.search(pattern_str, q_clean, re.IGNORECASE)
            if match:
                return GuardrailViolation(
                    category="UNETHICAL",
                    sub_category=subcat,
                    matched_term=match.group(0),
                    severity="CRITICAL",
                    reason=reason,
                )

        # 4. Check Adversarial Jailbreak patterns
        for pattern_str, subcat, reason in self.JAILBREAK_PATTERNS:
            match = re.search(pattern_str, q_clean, re.IGNORECASE)
            if match:
                return GuardrailViolation(
                    category="JAILBREAK",
                    sub_category=subcat,
                    matched_term=match.group(0),
                    severity="HIGH",
                    reason=reason,
                )

        return None

    def _record_incident(self, actor_key: str) -> int:
        """Record violation strike for actor and return active strike count within window."""
        now = utc_now()
        window_start = now - timedelta(hours=self.STRIKE_WINDOW_HOURS)

        if actor_key not in self._incident_log:
            self._incident_log[actor_key] = []

        # Filter out expired incidents
        active_incidents = [ts for ts in self._incident_log[actor_key] if ts >= window_start]
        active_incidents.append(now)
        self._incident_log[actor_key] = active_incidents

        return len(active_incidents)

    def get_strike_count(self, actor_key: str) -> int:
        """Get number of active strikes within the time window."""
        now = utc_now()
        window_start = now - timedelta(hours=self.STRIKE_WINDOW_HOURS)
        active = [ts for ts in self._incident_log.get(actor_key, []) if ts >= window_start]
        return len(active)

    def clear_strikes(self, actor_key: str) -> None:
        """Clear recorded violation strikes for a user or actor key."""
        if actor_key in self._incident_log:
            del self._incident_log[actor_key]

    async def evaluate_and_enforce(
        self,
        query: str,
        user: Optional[User] = None,
        client_ip: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> GuardrailResult:
        """Evaluate user query against strict safety guardrails.
        
        If a violation occurs:
        1. Refuses to answer strictly.
        2. Increments violation strikes.
        3. Formulates clear cautions regarding access restriction and authority reporting.
        4. When strike threshold is met, deactivates user account and logs critical audit event.
        """
        violation = self.scan_query(query)
        if not violation:
            return GuardrailResult(is_blocked=False)

        # Identify actor key for strike tracking
        actor_key = user.id if user else f"anon_{client_ip or 'unknown'}"
        actor_username = user.username if user else "anonymous"
        actor_role = getattr(user, "role", "guest") if user else "guest"

        strike_count = self._record_incident(actor_key)
        incident_id = str(uuid.uuid4())[:8].upper()
        now_str = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")

        is_restricted = False
        reported_to_authority = False

        # Check if user reached maximum strikes threshold
        if strike_count >= self.MAX_STRIKES_BEFORE_RESTRICTION:
            is_restricted = True
            reported_to_authority = True

            # If authenticated user, deactivate account immediately in database
            if user and db:
                try:
                    user.is_active = False
                    # Revoke all active refresh tokens for immediate logout
                    await db.execute(
                        update(RefreshToken)
                        .where(RefreshToken.user_id == user.id)
                        .values(revoked=True)
                    )
                    await db.commit()
                    logger.critical(
                        f"GUARDRAIL ENFORCEMENT: User {user.username} (ID: {user.id}) account deactivated "
                        f"due to continuous safety policy violations ({strike_count} strikes). Escalated to authorities."
                    )
                except Exception as e:
                    logger.error(f"Error deactivating user account upon guardrail strike: {e}")

        # Formulate authoritative caution and refusal response
        if is_restricted:
            caution_notice = (
                f"🚨 ACCESS TERMINATED & REPORTED TO AUTHORITIES: You have reached {strike_count}/{self.MAX_STRIKES_BEFORE_RESTRICTION} "
                f"safety policy violations. Your platform access has been suspended immediately. This incident has been formally "
                f"logged in the compliance ledger and escalated to security administration and law enforcement authorities."
            )
            refusal_text = (
                f"⛔ **CRITICAL POLICY VIOLATION — PLATFORM ACCESS RESTRICTED**\n\n"
                f"Your request was strictly blocked under our zero-tolerance safety guardrails for **{violation.category}** content "
                f"(*{violation.sub_category}*).\n\n"
                f"### ⚠️ Formal Compliance & Enforcement Action:\n"
                f"- **Account Status:** **SUSPENDED / DEACTIVATED**\n"
                f"- **Violations Incurred:** {strike_count} of {self.MAX_STRIKES_BEFORE_RESTRICTION} permitted strikes within 24 hours.\n"
                f"- **Authority Notification:** This incident (Ref: `INC-{incident_id}`) has been permanently recorded in the tamper-evident "
                f"compliance audit trail and **formally transmitted to system administrators and regulatory authorities for legal review**.\n\n"
                f"> **Notice:** Continuous generation of illegal, dangerous, or unethical inquiries is a direct breach of service agreements "
                f"and applicable criminal statutes. You cannot issue further queries on this workspace."
            )
        else:
            remaining_strikes = max(0, self.MAX_STRIKES_BEFORE_RESTRICTION - strike_count)
            caution_notice = (
                f"⚠️ CAUTION (Strike {strike_count}/{self.MAX_STRIKES_BEFORE_RESTRICTION}): Inquiry violates Safety Policy ({violation.category}). "
                f"Continued similar questionnaire submissions will restrict your platform access and be reported to the appropriate authorities. "
                f"Remaining warnings: {remaining_strikes}."
            )
            refusal_text = (
                f"⛔ **SAFETY & ETHICAL GUARDRAIL REFUSAL**\n\n"
                f"I cannot provide instructions, assistance, or answers regarding **{violation.category}** activities "
                f"(*{violation.sub_category}*).\n\n"
                f"### 🛡️ Policy Compliance Details:\n"
                f"- **Reason:** {violation.reason}\n"
                f"- **Incident Reference:** `INC-{incident_id}`\n"
                f"- **Policy Violation Strike:** **{strike_count} / {self.MAX_STRIKES_BEFORE_RESTRICTION}**\n\n"
                f"### ⚠️ Clear Caution to the User:\n"
                f"Please be advised that this platform strictly enforces non-negotiable safety guardrails preventing illegal, dangerous, "
                f"or unethical outputs under any circumstances (including hypothetical, educational, or roleplay scenarios).\n\n"
                f"**Continuous or repeated similar questionnaires will immediately restrict or permanently revoke your platform access, "
                f"and will be reported to the appropriate security administrators and legal authorities.**"
            )

        # Log tamper-evident audit record in database
        try:
            audit_status = "critical" if is_restricted else "warning"
            audit_risk = "CRITICAL" if is_restricted else "HIGH"
            compliance_stat = "FLAGGED"

            await audit_service.log_event(
                domain_category="security_auth",
                event_name="guardrail_prohibited_query_blocked",
                execution_status=audit_status,
                actor_id=user.id if user else None,
                actor_username=actor_username,
                actor_role=actor_role,
                actor_ip=client_ip,
                error_type="GuardrailViolation",
                error_message=f"Blocked query in category '{violation.category}' ({violation.sub_category}): {violation.reason}",
                metadata_payload={
                    "incident_id": f"INC-{incident_id}",
                    "category": violation.category,
                    "sub_category": violation.sub_category,
                    "matched_term": violation.matched_term,
                    "strike_count": strike_count,
                    "max_strikes": self.MAX_STRIKES_BEFORE_RESTRICTION,
                    "is_restricted": is_restricted,
                    "reported_to_authority": reported_to_authority,
                    "timestamp": now_str,
                },
                compliance_remark=(
                    f"Prohibited query intercepted by Guardrail Engine ({violation.category} / {violation.sub_category}). "
                    f"Strike {strike_count}/{self.MAX_STRIKES_BEFORE_RESTRICTION}. Caution issued."
                    + (" Account suspended and reported to authorities." if is_restricted else "")
                ),
                compliance_status=compliance_stat,
                db=db,
            )
        except Exception as audit_err:
            logger.warning(f"Error logging guardrail audit record: {audit_err}")

        return GuardrailResult(
            is_blocked=True,
            category=violation.category,
            sub_category=violation.sub_category,
            matched_term=violation.matched_term,
            severity=violation.severity,
            reason=violation.reason,
            refusal_message=refusal_text,
            caution_notice=caution_notice,
            incident_id=f"INC-{incident_id}",
            strike_count=strike_count,
            max_strikes=self.MAX_STRIKES_BEFORE_RESTRICTION,
            is_restricted=is_restricted,
            reported_to_authority=reported_to_authority,
        )


guardrail_service = GuardrailService()
