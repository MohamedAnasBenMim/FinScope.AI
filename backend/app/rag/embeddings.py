from abc import ABC, abstractmethod
from threading import Lock

import httpx
from app.config import Settings
from app.errors import EmbeddingFailed


class BaseEmbeddingProvider(ABC):
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, config: Settings):
        self.config = config
        self.dimensions = config.EMBEDDING_DIMENSIONS
        self._model = None
        self._lock = Lock()

    def _load(self):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        if self.config.EMBEDDING_MODEL == "intfloat/multilingual-e5-small":
            if not any(
                m["model"] == self.config.EMBEDDING_MODEL for m in TextEmbedding.list_supported_models()
            ):
                TextEmbedding.add_custom_model(
                    model=self.config.EMBEDDING_MODEL,
                    pooling=PoolingType.MEAN,
                    normalization=True,
                    sources=ModelSource(hf="Xenova/multilingual-e5-small"),
                    dim=384,
                    model_file="onnx/model_quantized.onnx",
                    description="Multilingual E5 small, ONNX int8",
                    license="mit",
                    size_in_gb=0.12,
                )
        self.config.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        description = next(
            (
                model
                for model in TextEmbedding.list_supported_models()
                if model["model"] == self.config.EMBEDDING_MODEL
            ),
            None,
        )
        cached = False
        if description and description.get("sources", {}).get("hf"):
            repo = description["sources"]["hf"].replace("/", "--")
            cache = self.config.MODEL_CACHE_DIR / f"models--{repo}"
            cached = any(path.is_file() for path in cache.glob("snapshots/*/" + description["model_file"]))
        self._model = TextEmbedding(
            model_name=self.config.EMBEDDING_MODEL,
            cache_dir=str(self.config.MODEL_CACHE_DIR),
            threads=self.config.EMBEDDING_THREADS,
            local_files_only=self.config.EMBEDDING_LOCAL_ONLY or cached,
        )

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        try:
            with self._lock:
                if self._model is None:
                    self._load()
            prefix = ("query: " if query else "passage: ") if "e5" in self.config.EMBEDDING_MODEL else ""
            vectors = [
                vector.tolist()
                for vector in self._model.embed([prefix + text for text in texts], batch_size=16)
            ]
            if any(len(vector) != self.dimensions for vector in vectors):
                raise EmbeddingFailed(
                    "Embedding dimensions differ from EMBEDDING_DIMENSIONS. Use a new collection for a different model."
                )
            return vectors
        except EmbeddingFailed:
            raise
        except Exception as exc:
            raise EmbeddingFailed(
                "Local embedding failed. Check model download/cache permissions and model configuration."
            ) from exc


class APIEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, config: Settings):
        self.config = config
        self.dimensions = config.EMBEDDING_DIMENSIONS

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        vectors = []
        try:
            with httpx.Client(timeout=self.config.PROVIDER_TIMEOUT) as client:
                for start in range(0, len(texts), 32):
                    response = client.post(
                        self.config.EMBEDDING_BASE_URL.rstrip("/") + "/embeddings",
                        headers={"Authorization": f"Bearer {self.config.EMBEDDING_API_KEY}"}
                        if self.config.EMBEDDING_API_KEY
                        else {},
                        json={"model": self.config.EMBEDDING_MODEL, "input": texts[start : start + 32]},
                    )
                    response.raise_for_status()
                    vectors.extend(
                        row["embedding"]
                        for row in sorted(response.json()["data"], key=lambda row: row["index"])
                    )
            if len(vectors) != len(texts) or any(len(v) != self.dimensions for v in vectors):
                raise ValueError("Invalid embedding shape")
            return vectors
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingFailed(
                "Embedding API failed. Check credentials, URL, model and dimensions."
            ) from exc


def embedding_provider(config: Settings) -> BaseEmbeddingProvider:
    return (
        LocalEmbeddingProvider(config)
        if config.EMBEDDING_PROVIDER == "local"
        else APIEmbeddingProvider(config)
    )
