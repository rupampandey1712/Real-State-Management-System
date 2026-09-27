from app import guardrails


def test_redacts_indian_phone_email_and_ids():
    text = "Call me on +91 98765 43210 or 9876543210, mail a.b@example.com, PAN ABCDE1234F, 1234 5678 9012"
    redacted = guardrails.redact_pii(text)
    assert "98765" not in redacted and "9876543210" not in redacted
    assert "example.com" not in redacted
    assert "ABCDE1234F" not in redacted
    assert "1234 5678 9012" not in redacted


def test_sanitize_strips_control_chars_and_truncates():
    assert guardrails.sanitize("hello​  \x00world", 100) == "hello world"
    assert len(guardrails.sanitize("x" * 500, 300)) == 300


def test_fair_housing_flags_exclusion_language():
    copy = "Spacious 2 BHK with balcony. Ideal for vegetarian families only. Close to lift."
    assert guardrails.fair_housing_violations(copy) == ["Ideal for vegetarian families only."]


def test_fair_housing_allows_neutral_copy():
    assert guardrails.fair_housing_violations("A bright 2 BHK suitable for working professionals.") == []


def test_unsupported_numbers_catches_invented_facts():
    source = "Bedrooms (BHK): 2\nCarpet area: 950 sq ft\nPrice: ₹78 L"
    assert guardrails.unsupported_numbers("2 BHK, 950 sq ft for ₹78 L", source) == []
    assert guardrails.unsupported_numbers("2 BHK with 2 covered parking and 1,200 sq ft", source) == ["1200"]


def test_citation_validation():
    answer = "Maintenance is ₹3,500 [S5]. Pets are allowed [D2]. Parking [S99]."
    assert guardrails.invalid_citations(answer, {"S5", "D2"}) == ["S99"]
    assert guardrails.citations_in(answer) == ["S5", "D2", "S99"]


def test_advice_screen():
    assert guardrails.screen_intent("Is this a good investment?") == "advice"
    assert guardrails.screen_intent("Will the price go up next year?") == "advice"
    assert guardrails.screen_intent("Is parking included?") is None


def test_unknown_answer_detection():
    assert guardrails.is_unknown_answer("I don't have that information in this listing.")
