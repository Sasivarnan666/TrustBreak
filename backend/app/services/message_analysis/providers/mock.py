"""Offline demo provider: deterministic keyword rules. NOT an AI model."""

from .. import mock_extractor
from ..schema import MessageExtraction


class MockProvider:
    name = "mock"
    model = None

    def analyze_message(self, text: str) -> MessageExtraction:
        return mock_extractor.extract(text)
