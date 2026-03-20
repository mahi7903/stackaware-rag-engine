from typing import List


def build_validity_statement(mode: str, sources: list[dict]) -> str:
    """
    I am building a backend-side validity note here so the answer stays explicit
    about how grounded it is and what source window it is relying on.
    """

    if not sources:
        if mode == "version_change_awareness":
            return "Validity: No grounded version or change-related indexed sources were strong enough for this answer."
        return "Validity: No grounded indexed sources were strong enough for this answer."

    source_count = len(sources)
    unique_titles = []
    seen_titles = set()

    for source in sources:
        title = str(source.get("title", "")).strip()
        if title and title not in seen_titles:
            unique_titles.append(title)
            seen_titles.add(title)

    if mode == "version_change_awareness":
        return (
            f"Validity: This change-awareness answer is grounded in {source_count} retrieved indexed chunk(s) "
            f"across {len(unique_titles)} source title(s). Exact release date or as-of window may still be missing "
            f"unless the retrieved source text states it explicitly."
        )

    return (
        f"Validity: This answer is grounded in {source_count} retrieved indexed chunk(s) "
        f"across {len(unique_titles)} source title(s). Exact version/date detail may still be missing "
        f"unless the retrieved source text states it explicitly."
    )


def build_citation_block(sources: list[dict]) -> str:
    """
    I am formatting simple grounded citations here so the final answer can point
    back to the retrieved indexed chunks instead of sounding unsupported.
    """

    if not sources:
        return "Citations:\n- No grounded citations available."

    lines = ["Citations:"]
    seen_entries = set()

    for source in sources:
        title = str(source.get("title", "Unknown source")).strip() or "Unknown source"
        chunk_index = source.get("chunk_index")
        chunk_count = source.get("chunk_count")

        entry = f"- {title} (chunk {chunk_index}/{chunk_count})"

        if entry in seen_entries:
            continue

        seen_entries.add(entry)
        lines.append(entry)

    return "\n".join(lines)