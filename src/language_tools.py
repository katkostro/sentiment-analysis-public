"""
Azure AI Language SDK tool implementations.

Used when LANGUAGE_TOOL_MODE=sdk (the default).
The agent declares these as function tools; the app intercepts required_action
runs, executes the appropriate function here, and submits the output back.

Switch to LANGUAGE_TOOL_MODE=mcp once the Foundry Agent Service supports
Streamable HTTP MCP transport (currently POST-only, Agent Service uses SSE GET).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.ai.textanalytics import TextAnalyticsClient


# ─── Client ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> TextAnalyticsClient:
    endpoint = os.environ["AZURE_LANGUAGE_ENDPOINT"].rstrip("/")
    return TextAnalyticsClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _docs(documents: Any) -> list[str]:
    """Accept either a JSON string or a Python list."""
    if isinstance(documents, str):
        try:
            documents = json.loads(documents)
        except json.JSONDecodeError:
            documents = [documents]
    return [str(d) for d in documents]


# ─── Tool implementations ─────────────────────────────────────────────────────

def analyze_sentiment(documents: Any) -> str:
    """Analyse sentiment and mine opinions for each document."""
    client = _get_client()
    docs = _docs(documents)
    results = client.analyze_sentiment(docs, show_opinion_mining=True)
    output = []
    for i, doc in enumerate(results):
        if doc.is_error:
            output.append({"index": i, "error": doc.error.message})
            continue
        sentences = []
        for sent in doc.sentences:
            s: dict[str, Any] = {
                "text": sent.text,
                "sentiment": sent.sentiment,
                "confidence": {
                    "positive": round(sent.confidence_scores.positive, 3),
                    "neutral": round(sent.confidence_scores.neutral, 3),
                    "negative": round(sent.confidence_scores.negative, 3),
                },
                "opinions": [],
            }
            for mined in sent.mined_opinions:
                s["opinions"].append({
                    "target": mined.target.text,
                    "sentiment": mined.target.sentiment,
                    "assessments": [
                        {"text": a.text, "sentiment": a.sentiment}
                        for a in mined.assessments
                    ],
                })
            sentences.append(s)
        output.append({
            "index": i,
            "text": docs[i],
            "sentiment": doc.sentiment,
            "confidence": {
                "positive": round(doc.confidence_scores.positive, 3),
                "neutral": round(doc.confidence_scores.neutral, 3),
                "negative": round(doc.confidence_scores.negative, 3),
            },
            "sentences": sentences,
        })
    return json.dumps(output, ensure_ascii=False)


def extract_key_phrases(documents: Any) -> str:
    """Extract the key phrases from each document."""
    client = _get_client()
    docs = _docs(documents)
    results = client.extract_key_phrases(docs)
    output = []
    for i, doc in enumerate(results):
        if doc.is_error:
            output.append({"index": i, "error": doc.error.message})
        else:
            output.append({"index": i, "text": docs[i], "key_phrases": list(doc.key_phrases)})
    return json.dumps(output, ensure_ascii=False)


def recognize_entities(documents: Any) -> str:
    """Recognise named entities (people, places, organisations, dates, …)."""
    client = _get_client()
    docs = _docs(documents)
    results = client.recognize_entities(docs)
    output = []
    for i, doc in enumerate(results):
        if doc.is_error:
            output.append({"index": i, "error": doc.error.message})
        else:
            output.append({
                "index": i,
                "text": docs[i],
                "entities": [
                    {
                        "text": e.text,
                        "category": e.category,
                        "subcategory": e.subcategory,
                        "confidence": round(e.confidence_score, 3),
                    }
                    for e in doc.entities
                ],
            })
    return json.dumps(output, ensure_ascii=False)


def detect_language(documents: Any) -> str:
    """Detect the language of each document."""
    client = _get_client()
    docs = _docs(documents)
    results = client.detect_language(docs)
    output = []
    for i, doc in enumerate(results):
        if doc.is_error:
            output.append({"index": i, "error": doc.error.message})
        else:
            output.append({
                "index": i,
                "text": docs[i],
                "language": doc.primary_language.name,
                "iso6391_name": doc.primary_language.iso6391_name,
                "confidence": round(doc.primary_language.confidence_score, 3),
            })
    return json.dumps(output, ensure_ascii=False)


def recognize_pii_entities(documents: Any) -> str:
    """Detect PII (names, emails, phone numbers, etc.) in each document."""
    client = _get_client()
    docs = _docs(documents)
    results = client.recognize_pii_entities(docs)
    output = []
    for i, doc in enumerate(results):
        if doc.is_error:
            output.append({"index": i, "error": doc.error.message})
        else:
            output.append({
                "index": i,
                "text": docs[i],
                "redacted_text": doc.redacted_text,
                "entities": [
                    {
                        "text": e.text,
                        "category": e.category,
                        "confidence": round(e.confidence_score, 3),
                    }
                    for e in doc.entities
                ],
            })
    return json.dumps(output, ensure_ascii=False)


# ─── Dispatch table ───────────────────────────────────────────────────────────

TOOL_DISPATCH: dict[str, Any] = {
    "analyze_sentiment": analyze_sentiment,
    "extract_key_phrases": extract_key_phrases,
    "recognize_entities": recognize_entities,
    "detect_language": detect_language,
    "recognize_pii_entities": recognize_pii_entities,
}

# ─── Function tool definitions (OpenAI function-calling schema) ───────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_sentiment",
            "description": (
                "Analyse the sentiment (positive / neutral / negative) of one or more text "
                "documents and mine fine-grained opinions about specific aspects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents to analyse (max 10 per call).",
                    }
                },
                "required": ["documents"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_key_phrases",
            "description": "Extract the most important key phrases from one or more documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents (max 10 per call).",
                    }
                },
                "required": ["documents"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recognize_entities",
            "description": (
                "Recognise named entities such as people, organisations, locations, dates, "
                "events, and products in one or more documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents (max 10 per call).",
                    }
                },
                "required": ["documents"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_language",
            "description": "Detect the language of one or more documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents (max 10 per call).",
                    }
                },
                "required": ["documents"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recognize_pii_entities",
            "description": (
                "Detect Personally Identifiable Information (PII) such as names, email "
                "addresses, phone numbers and ID numbers. Returns detected entities and "
                "a redacted version of the text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of text documents (max 10 per call).",
                    }
                },
                "required": ["documents"],
            },
        },
    },
]
