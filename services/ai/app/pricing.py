"""USD per 1M tokens, Gemini API paid tier (ai.google.dev/gemini-api/docs/pricing, checked 2026-09).
Output prices include thinking tokens. Keep in sync — cost numbers drive NFR-3 budget checks.
Note: gemini-3.8-flash prices are an introductory rate through 2026-12-31 (then $1.50 / $7.50 / $0.15)."""

PRICES = {
    # model: (input, output, cached input)
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.1-pro-preview": (2.00, 12.00, 0.20),  # prompts <= 200k tokens
}


def cost_usd_micros(model: str, usage: dict) -> int | None:
    """$/1M tokens x tokens = micro-dollars. Gemini's prompt count includes cached tokens;
    thinking tokens are billed at the output rate."""
    if model not in PRICES or not usage:
        return None
    input_price, output_price, cached_price = PRICES[model]
    cached = usage.get("cached_tokens", 0)
    return round(
        (usage.get("input_tokens", 0) - cached) * input_price
        + cached * cached_price
        + (usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)) * output_price
    )
