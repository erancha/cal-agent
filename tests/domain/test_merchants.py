from calagent.domain.merchants import merchant_key


def test_hebrew_company_form_and_branch_dropped() -> None:
    assert merchant_key('סלקום ישראל בע"מ 12') == "סלקום ישראל"


def test_latin_company_form_dropped_and_case_folded() -> None:
    assert merchant_key("Netflix.com  LTD") == "netflix.com"


def test_whitespace_collapsed() -> None:
    assert merchant_key("a  b") == "a b"
