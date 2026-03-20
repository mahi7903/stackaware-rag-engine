def build_empty_mode_response(mode: str) -> str:
    """
    I am keeping the no-context fallback structured here so both backend modes
    still return milestone-style answers even when retrieval is too weak.
    """

    if mode == "technical_decision_support":
        return """Risk & Impact:
- I could not find enough relevant indexed context to support a safe technical decision yet.

Advice:
- I should avoid making a concrete recommendation until stronger indexed evidence is available.

Justification:
- The current retrieval did not return strong enough grounded context for this question.

Safe Alternatives:
- Narrow the question, upload more targeted technical documents, or ask about a topic that is already indexed.

Validity:
- No grounded indexed sources were strong enough for this answer.

Citations:
- No grounded citations available."""
    
    if mode == "version_change_awareness":
        return """Change Signal:
- I could not find enough indexed version or change-related context to identify a grounded change signal yet.

Risk & Impact:
- Without reliable indexed change evidence, any change warning would risk being misleading.

Recommended Action:
- Check official release notes, migration guides, or upload indexed version-specific documents for this stack area.

Justification:
- The current retrieval did not return strong enough grounded change-related context for this question.

Validity:
- No grounded version or change-related indexed sources were strong enough for this answer.

Citations:
- No grounded citations available."""

    return """Validity:
- No grounded indexed sources were strong enough for this answer.

Citations:
- No grounded citations available."""