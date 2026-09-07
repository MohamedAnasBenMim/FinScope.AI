import re
from abc import ABC, abstractmethod

import httpx
from app.config import Settings
from app.errors import ProviderFailed
from app.rag.evidence import relevant_metric, requested_metric_pattern
from app.rag.lexical import tokens
from app.rag.prompts import SYSTEM_CITATION_PROMPT, build_rag_prompt
from pydantic import BaseModel, Field


class EvidenceSelection(BaseModel):
    citation_id: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class LLMResult(BaseModel):
    evidence: list[EvidenceSelection] = Field(default_factory=list, max_length=30)


class BaseLLMProvider(ABC):
    @abstractmethod
    def answer(self, question: str, chunks: list[dict]) -> LLMResult: ...


class OllamaProvider(BaseLLMProvider):
    def __init__(self, config: Settings):
        self.config = config

    def answer(self, question: str, chunks: list[dict]) -> LLMResult:
        try:
            response = httpx.post(
                self.config.LLM_BASE_URL.rstrip("/") + "/api/chat",
                timeout=self.config.PROVIDER_TIMEOUT,
                json={
                    "model": self.config.LLM_MODEL,
                    "stream": False,
                    "format": LLMResult.model_json_schema(),
                    "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1200},
                    "messages": [
                        {"role": "system", "content": SYSTEM_CITATION_PROMPT},
                        {"role": "user", "content": build_rag_prompt(chunks, question)},
                    ],
                },
            )
            response.raise_for_status()
            return LLMResult.model_validate_json(response.json()["message"]["content"])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ProviderFailed(
                "Ollama did not return a valid answer. Check model download, service URL, and PROVIDER_TIMEOUT."
            ) from exc


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-compatible Chat Completions endpoint; credentials stay server-side."""

    def __init__(self, config: Settings):
        self.config = config

    def answer(self, question: str, chunks: list[dict]) -> LLMResult:
        try:
            response = httpx.post(
                self.config.LLM_BASE_URL.rstrip("/") + "/chat/completions",
                timeout=self.config.PROVIDER_TIMEOUT,
                headers={"Authorization": f"Bearer {self.config.LLM_API_KEY}"}
                if self.config.LLM_API_KEY
                else {},
                json={
                    "model": self.config.LLM_MODEL,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_CITATION_PROMPT},
                        {"role": "user", "content": build_rag_prompt(chunks, question)},
                    ],
                },
            )
            response.raise_for_status()
            return LLMResult.model_validate_json(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ProviderFailed(
                "LLM API did not return a valid answer. Check URL, model, credentials, and provider JSON support."
            ) from exc


INJECTION_PATTERN = re.compile(
    r"ignore (?:all |previous |the )|system prompt|developer message|reveal.*(?:secret|key)|ignorez|instructions precedentes|you are now|execute.*command",
    re.I,
)


class ExtractiveProvider(BaseLLMProvider):
    """Working no-LLM mode: select relevant source lines without generating claims."""

    def answer(self, question: str, chunks: list[dict]) -> LLMResult:
        query_terms = set(tokens(question)) - {"compare", "invoice", "quote", "statement"}
        metric_pattern = requested_metric_pattern(question)
        result = []
        comparison = "compare" in tokens(question)
        seen_documents = set()
        for index, chunk in enumerate(chunks, 1):
            lines = []
            for line in chunk["content"].splitlines():
                overlap = len(query_terms & set(tokens(line)))
                if overlap and not INJECTION_PATTERN.search(line) and relevant_metric(line, metric_pattern):
                    lines.append((overlap, line))
            if comparison:
                lines = [
                    (
                        3
                        if re.search(r"(?i)ttc|grand total|net income|resultat net|revenue|chiffre", line)
                        else score,
                        line,
                    )
                    for score, line in lines
                ]
                if not lines:
                    lines = [
                        (1, line)
                        for line in chunk["content"].splitlines()
                        if re.search(r"(?i)ttc|grand total|net income|resultat net|revenue|chiffre", line)
                    ]
            lines.sort(key=lambda pair: pair[0], reverse=True)
            doc_id = chunk["metadata"]["document_id"]
            if lines and (doc_id not in seen_documents or not comparison):
                result.append(EvidenceSelection(citation_id=index, quote=lines[0][1]))
                seen_documents.add(doc_id)
            if len(result) >= 8:
                break
        return LLMResult(evidence=result)


def llm_provider(config: Settings) -> BaseLLMProvider:
    return {
        "local": OpenAIProvider,
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "extractive": lambda _: ExtractiveProvider(),
    }[config.LLM_PROVIDER](config)
