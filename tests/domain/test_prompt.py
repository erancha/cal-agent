from calagent.domain.merchants import MerchantQuery
from calagent.domain.prompt import CATEGORY_GUIDES, SYSTEM_PROMPT, merchant_lines, taxonomy_digest
from calagent.domain.taxonomy import TAXONOMY


def test_there_is_a_guide_for_every_category_and_all_are_in_the_prompt() -> None:
    assert set(CATEGORY_GUIDES) == set(TAXONOMY)
    assert "%s" not in SYSTEM_PROMPT
    assert all(f"- {name}: {guide}" in SYSTEM_PROMPT for name, guide in CATEGORY_GUIDES.items())


def test_digest_is_stable_hex() -> None:
    assert taxonomy_digest() == taxonomy_digest()
    assert len(taxonomy_digest()) == 64


def test_merchant_lines_carry_the_sector() -> None:
    queries = [MerchantQuery("a", "x"), MerchantQuery("b", "y")]
    assert merchant_lines(queries) == "a [sector: x]\nb [sector: y]"
