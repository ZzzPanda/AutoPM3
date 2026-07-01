from __future__ import annotations

from app.core.query import _pm3_intake_candidate_docs
from app.prompts import render_pm3_paper_intake
from tests import MARKDOWN_FIXTURE


def test_pm3_intake_candidate_docs_find_variant_context():
    markdown_text = MARKDOWN_FIXTURE.read_text(encoding="utf-8", errors="replace")

    docs = _pm3_intake_candidate_docs(markdown_text, limit=6)

    assert docs
    joined = "\n".join(doc.page_content for doc in docs)
    assert "compound heterozyg" in joined.lower()
    assert "c.1319T" in joined or "L440R" in joined


def test_pm3_paper_intake_prompt_renders_evidence_ids():
    prompt = render_pm3_paper_intake(
        evidence_chunks=[
            {
                "id": "chunk-1",
                "title": "Chunk 1",
                "reason": "candidate genotype context",
                "text": "Case 1 is compound heterozygous for c.1A>G and c.2A>G.",
            }
        ]
    )

    assert "chunk-1" in prompt
    assert "candidate_variants" in prompt
    assert "The user has not provided a target variant" in prompt
