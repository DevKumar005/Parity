"""Tests for the LLM client, mock provider, and ledger tracking."""

from backend import AgentRole
from backend.llm import LLMClient, MockProvider


def test_mock_provider_is_available():
    """Mock provider must always report available even without any API keys."""
    provider = MockProvider()
    assert provider.is_available() is True


def test_mock_provider_routing_by_role():
    """Mock provider routes responses to match agent requirements."""
    client = LLMClient()

    # Archaeologist test
    resp_arch = client.complete(
        messages=[
            {"role": "system", "content": "You are the archaeologist agent."},
            {"role": "user", "content": "Analyze tiered_pricing.c"},
        ],
        role=AgentRole.ARCHAEOLOGIST,
        purpose="extract signatures",
    )
    assert resp_arch.provider == "mock"
    assert "calculate_tier_price" in resp_arch.content

    # Fuzzer test
    resp_fuzz = client.complete(
        messages=[
            {"role": "system", "content": "You are the fuzzer agent generating test inputs."},
            {"role": "user", "content": "Generate edge cases for tiered_pricing.c"},
        ],
        role=AgentRole.FUZZER,
        purpose="fuzz edge cases",
    )
    assert "edge_cases" in resp_fuzz.content


def test_usage_ledger_recording():
    """Client properly logs calls, tokens, and roles in usage ledger."""
    client = LLMClient()
    client.complete(
        messages=[
            {"role": "system", "content": "archaeologist"},
            {"role": "user", "content": "tiered_pricing"},
        ],
        role=AgentRole.ARCHAEOLOGIST,
        purpose="test call",
    )
    assert len(client.ledger) >= 1
    entry = client.ledger[-1]
    assert entry.role == AgentRole.ARCHAEOLOGIST.value
    assert entry.purpose == "test call"

