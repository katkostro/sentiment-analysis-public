"""
Sentiment Analysis Agent – Azure AI Foundry + Azure AI Language

This agent leverages the full Azure AI Language service:
  - Sentiment Analysis (with opinion mining)
  - Key Phrase Extraction
  - Named Entity Recognition (NER)
  - PII Entity Recognition
  - Entity Linking
  - Language Detection
  - Abstractive & Extractive Summarization

Data source:
  - LOCAL (default): reads Excel files from the local file system
  - FABRIC: reads from Microsoft Fabric OneLake via Fabric Data Agent
    Set DATA_SOURCE=fabric and FABRIC_ONELAKE_ENDPOINT to switch.

All authentication uses managed identity (DefaultAzureCredential).

Environment variables (see .env.example):
  AZURE_AI_SERVICES_ENDPOINT – AI Services endpoint
  AZURE_LANGUAGE_ENDPOINT    – AI Language endpoint
  FOUNDRY_PROJECT_NAME       – Foundry project name
  DATA_SOURCE                – 'local' (default) or 'fabric'
  FABRIC_ONELAKE_ENDPOINT    – Fabric OneLake endpoint (when DATA_SOURCE=fabric)
  FABRIC_LAKEHOUSE_PATH      – OneLake path, e.g. 'workspace/lakehouse/Files/surveys'
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from azure.ai.textanalytics import TextAnalyticsClient
from azure.identity import DefaultAzureCredential


# ─── Configuration ───────────────────────────────────────────────────────────

LANGUAGE_ENDPOINT = os.environ.get("AZURE_LANGUAGE_ENDPOINT", "")
AI_SERVICES_ENDPOINT = os.environ.get("AZURE_AI_SERVICES_ENDPOINT", "")
FOUNDRY_PROJECT = os.environ.get("FOUNDRY_PROJECT_NAME", "sentiment-analysis")

# Data source switch: 'local' or 'fabric'
DATA_SOURCE = os.environ.get("DATA_SOURCE", "local").lower()
FABRIC_ONELAKE_ENDPOINT = os.environ.get("FABRIC_ONELAKE_ENDPOINT", "")
FABRIC_LAKEHOUSE_PATH = os.environ.get("FABRIC_LAKEHOUSE_PATH", "")


# ─── Language client ─────────────────────────────────────────────────────────

def _get_language_client() -> TextAnalyticsClient:
    """Create an authenticated TextAnalyticsClient using managed identity."""
    credential = DefaultAzureCredential()
    return TextAnalyticsClient(endpoint=LANGUAGE_ENDPOINT, credential=credential)


# ─── Data readers ───────────────────────────────────────────────────────────

def read_excel_responses(file_path: str | Path) -> list[str]:
    """
    Read text responses from a local Excel file.

    Supports both .xlsx (openpyxl) and legacy .xls (xlrd) formats.
    Looks for columns named 'Response', 'Comment', 'Feedback', or 'Text'
    (case-insensitive). Falls back to the first column if none match.
    """
    file_path = Path(file_path)
    target_columns = {"response", "comment", "feedback", "text", "survey response", "answer"}

    with open(file_path, "rb") as f:
        magic = f.read(4)

    if magic[:4] == b"\x50\x4b\x03\x04":
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    else:
        import xlrd
        wb = xlrd.open_workbook(str(file_path))
        ws = wb.sheet_by_index(0)
        rows = [
            tuple(ws.cell_value(r, c) for c in range(ws.ncols))
            for r in range(ws.nrows)
        ]

    if not rows:
        return []

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_idx = next(
        (i for i, h in enumerate(headers) if h in target_columns),
        0,
    )

    responses: list[str] = []
    for row in rows[1:]:
        if col_idx < len(row) and row[col_idx]:
            text = str(row[col_idx]).strip()
            if text:
                responses.append(text)

    return responses


def read_fabric_responses(lakehouse_path: str = "") -> list[str]:
    """
    Read text responses from Microsoft Fabric OneLake.

    Architecture: Source Data → Fabric OneLake → Semantic Model
                  → Fabric Data Agent → this Foundry Agent

    To enable:
      1. Set DATA_SOURCE=fabric
      2. Set FABRIC_ONELAKE_ENDPOINT to your OneLake endpoint
      3. Set FABRIC_LAKEHOUSE_PATH to the lakehouse path with survey files
      4. In Bicep, set enableFabric=true and provide fabricOneLakeEndpoint

    Uses fsspec with the abfs:// protocol and DefaultAzureCredential.
    """
    try:
        from azure.storage.filedatalake import DataLakeServiceClient
    except ImportError:
        print("ERROR: azure-storage-file-datalake is required for Fabric mode.")
        print("       pip install azure-storage-file-datalake")
        sys.exit(1)

    path = lakehouse_path or FABRIC_LAKEHOUSE_PATH
    endpoint = FABRIC_ONELAKE_ENDPOINT
    if not endpoint or not path:
        print("ERROR: FABRIC_ONELAKE_ENDPOINT and FABRIC_LAKEHOUSE_PATH must be set.")
        sys.exit(1)

    credential = DefaultAzureCredential()
    client = DataLakeServiceClient(account_url=endpoint, credential=credential)

    # Parse path: workspace/lakehouse/Files/surveys/file.xlsx
    parts = path.strip("/").split("/")
    filesystem = parts[0]  # workspace name
    file_path_in_lake = "/".join(parts[1:])

    fs_client = client.get_file_system_client(filesystem)
    file_client = fs_client.get_file_client(file_path_in_lake)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        download = file_client.download_file()
        tmp.write(download.readall())
        tmp_path = tmp.name

    responses = read_excel_responses(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    return responses


def load_responses(file_path: str | None = None) -> list[str]:
    """Load responses from the configured data source."""
    if DATA_SOURCE == "fabric":
        print("📡 Reading from Microsoft Fabric OneLake ...")
        return read_fabric_responses(file_path or "")
    else:
        if not file_path:
            print("ERROR: file path required for local data source.")
            sys.exit(1)
        print(f"📄 Reading from local file: {file_path}")
        return read_excel_responses(file_path)


# ─── Azure AI Language capabilities ─────────────────────────────────────────

def analyse_sentiment(texts: list[str]) -> list[dict[str, Any]]:
    """Sentiment analysis with opinion mining."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.analyze_sentiment(batch, show_opinion_mining=True)

        for doc in response:
            if doc.is_error:
                results.append({"text": doc.id, "error": doc.error.message})
                continue

            sentences = []
            for sent in doc.sentences:
                sentence_data: dict[str, Any] = {
                    "text": sent.text,
                    "sentiment": sent.sentiment,
                    "confidence_scores": {
                        "positive": sent.confidence_scores.positive,
                        "neutral": sent.confidence_scores.neutral,
                        "negative": sent.confidence_scores.negative,
                    },
                    "offset": sent.offset,
                    "length": sent.length,
                }
                if sent.mined_opinions:
                    sentence_data["opinions"] = [
                        {
                            "target": {"text": op.target.text, "sentiment": op.target.sentiment},
                            "assessments": [
                                {"text": a.text, "sentiment": a.sentiment}
                                for a in op.assessments
                            ],
                        }
                        for op in sent.mined_opinions
                    ]
                sentences.append(sentence_data)

            results.append({
                "text": doc.sentences[0].text[:80] + "..."
                if len(doc.sentences[0].text) > 80
                else doc.sentences[0].text,
                "sentiment": doc.sentiment,
                "confidence_scores": {
                    "positive": doc.confidence_scores.positive,
                    "neutral": doc.confidence_scores.neutral,
                    "negative": doc.confidence_scores.negative,
                },
                "sentences": sentences,
            })

    return results


def extract_key_phrases(texts: list[str]) -> list[dict[str, Any]]:
    """Extract key phrases from each document."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.extract_key_phrases(batch)
        for doc in response:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({"key_phrases": list(doc.key_phrases)})
    return results


def recognize_entities(texts: list[str]) -> list[dict[str, Any]]:
    """Named Entity Recognition (NER)."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.recognize_entities(batch)
        for doc in response:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "entities": [
                        {"text": e.text, "category": e.category,
                         "subcategory": e.subcategory, "confidence": e.confidence_score}
                        for e in doc.entities
                    ]
                })
    return results


def recognize_pii_entities(texts: list[str]) -> list[dict[str, Any]]:
    """PII Entity Recognition — detects personal data."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.recognize_pii_entities(batch)
        for doc in response:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "redacted_text": doc.redacted_text,
                    "pii_entities": [
                        {"text": e.text, "category": e.category, "confidence": e.confidence_score}
                        for e in doc.entities
                    ],
                })
    return results


def recognize_linked_entities(texts: list[str]) -> list[dict[str, Any]]:
    """Entity Linking — links entities to Wikipedia."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.recognize_linked_entities(batch)
        for doc in response:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "linked_entities": [
                        {"name": e.name, "url": e.url, "data_source": e.data_source,
                         "matches": [{"text": m.text, "confidence": m.confidence_score}
                                     for m in e.matches]}
                        for e in doc.entities
                    ]
                })
    return results


def detect_language(texts: list[str]) -> list[dict[str, Any]]:
    """Detect the language of each document."""
    client = _get_language_client()
    BATCH_SIZE = 10
    results: list[dict[str, Any]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.detect_language(batch)
        for doc in response:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "language": doc.primary_language.name,
                    "iso_code": doc.primary_language.iso6391_name,
                    "confidence": doc.primary_language.confidence_score,
                })
    return results


def abstractive_summarize(texts: list[str]) -> list[dict[str, Any]]:
    """Abstractive Summarization — generates a concise summary."""
    client = _get_language_client()
    results: list[dict[str, Any]] = []

    poller = client.begin_abstract_summary(texts)
    for result in poller.result():
        for doc in result:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "summaries": [
                        {"text": s.text, "contexts": [
                            {"offset": c.offset, "length": c.length} for c in s.contexts
                        ]} for s in doc.summaries
                    ]
                })
    return results


def extractive_summarize(texts: list[str]) -> list[dict[str, Any]]:
    """Extractive Summarization — picks the most important sentences."""
    client = _get_language_client()
    results: list[dict[str, Any]] = []

    poller = client.begin_extract_summary(texts)
    for result in poller.result():
        for doc in result:
            if doc.is_error:
                results.append({"error": doc.error.message})
            else:
                results.append({
                    "sentences": [
                        {"text": s.text, "rank_score": s.rank_score}
                        for s in doc.sentences
                    ]
                })
    return results


# Map CLI capability names to functions
CAPABILITIES = {
    "sentiment": analyse_sentiment,
    "key-phrases": extract_key_phrases,
    "entities": recognize_entities,
    "pii": recognize_pii_entities,
    "entity-linking": recognize_linked_entities,
    "language-detection": detect_language,
    "abstractive-summary": abstractive_summarize,
    "extractive-summary": extractive_summarize,
}


def summarise_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce an aggregate summary from sentiment results."""
    counts = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
    for r in results:
        sentiment = r.get("sentiment", "neutral")
        counts[sentiment] = counts.get(sentiment, 0) + 1

    total = len(results) or 1
    return {
        "total_documents": len(results),
        "sentiment_distribution": {
            k: {"count": v, "percentage": round(v / total * 100, 1)}
            for k, v in counts.items()
            if v > 0
        },
        "overall_sentiment": max(counts, key=counts.get),  # type: ignore[arg-type]
    }


# ─── Agent system prompt (used when creating the Foundry agent) ─────────────

AGENT_SYSTEM_PROMPT = """You are a Survey Analysis Agent powered by Azure AI Language.

Your capabilities via the Azure AI Language service:
1. Sentiment Analysis — document & sentence-level, with opinion mining
2. Key Phrase Extraction — surface the main topics
3. Named Entity Recognition (NER) — people, places, organisations, dates
4. PII Detection — find and redact personal data
5. Entity Linking — link entities to Wikipedia knowledge base
6. Language Detection — identify the language of each response
7. Abstractive Summarization — generate concise AI-written summaries
8. Extractive Summarization — pick the most informative sentences

Data sources:
- Local Excel files (.xlsx / .xls) — default mode
- Microsoft Fabric OneLake — when the Fabric Data Agent pipeline is enabled
  (Source Data → OneLake → Semantic Model → Fabric Data Agent → you)

When presenting results:
- Always show the overall sentiment distribution first
- Highlight any strongly negative responses that may need attention
- Group responses by sentiment category
- Surface key phrases and entities as themes
- Flag any PII found and suggest redaction
- Provide actionable insights based on the analysis
"""


# ─── CLI entry point ────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Azure AI Language analysis on survey data"
    )
    parser.add_argument(
        "file", nargs="?",
        help="Excel file path (local mode) or OneLake path (fabric mode)",
    )
    parser.add_argument(
        "--capability", "-c",
        choices=list(CAPABILITIES.keys()),
        default="sentiment",
        help="Language capability to run (default: sentiment)",
    )
    parser.add_argument(
        "--all-capabilities", action="store_true",
        help="Run all Language capabilities on the data",
    )
    args = parser.parse_args()

    responses = load_responses(args.file)
    print(f"   Found {len(responses)} responses\n")

    if not responses:
        print("No responses found. Check the file and column headers.")
        sys.exit(1)

    capabilities_to_run = list(CAPABILITIES.keys()) if args.all_capabilities else [args.capability]

    all_output: dict[str, Any] = {}
    for cap_name in capabilities_to_run:
        cap_fn = CAPABILITIES[cap_name]
        print(f"🔍 Running {cap_name} ...\n")
        results = cap_fn(responses)
        all_output[cap_name] = results

        if cap_name == "sentiment":
            summary = summarise_results(results)
            print("═" * 60)
            print("  SENTIMENT ANALYSIS SUMMARY")
            print("═" * 60)
            print(json.dumps(summary, indent=2))
            all_output["sentiment_summary"] = summary

        print(f"\n   {cap_name}: {len(results)} results\n")

    # Write results to JSON
    output_path = Path(args.file or "fabric_analysis").with_suffix(".results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_output, f, indent=2)
    print(f"\n✅ Results written to: {output_path}")


if __name__ == "__main__":
    main()
