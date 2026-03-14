"""
EmbeddingProvider abstraction and FastEmbedProvider implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderHealth:
    def __init__(self, ok: bool, info: str) -> None:
        self.ok = ok
        self.info = info

    def to_dict(self) -> dict:
        return {"ok": self.ok, "info": self.info}


class EmbeddingProvider(ABC):
    @abstractmethod
    def type(self) -> str:
        """Return 'local' or 'external'."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Return provider name."""
        ...

    @abstractmethod
    def model_id(self) -> str:
        """Return model identifier string."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return embedding dimension."""
        ...

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Check provider health. Never raises."""
        ...

    @abstractmethod
    def embed_texts(self, texts: list) -> list:
        """
        Embed a list of texts. Returns list of list[float].
        Never raises — returns empty list on failure.
        """
        ...


class FastEmbedProvider(EmbeddingProvider):
    """Local CPU embedding via fastembed. Default model: all-MiniLM-L6-v2 (384-dim)."""

    _DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    _DEFAULT_DIM = 384

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._embedder = None  # lazy init

    def type(self) -> str:
        return "local"

    def name(self) -> str:
        return "fastembed"

    def model_id(self) -> str:
        return self._model_name

    def dimension(self) -> int:
        return self._DEFAULT_DIM

    def _get_embedder(self):
        """Lazily initialize the fastembed TextEmbedding model."""
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding  # type: ignore

                self._embedder = TextEmbedding(model_name=self._model_name)
            except ImportError:
                raise RuntimeError("fastembed is not installed")
        return self._embedder

    def healthcheck(self) -> ProviderHealth:
        """Try to init embedder and embed ['hello']. Return ProviderHealth."""
        try:
            embedder = self._get_embedder()
            results = embedder.embed(["hello"])
            vec = next(iter(results))
            dim = len(vec) if hasattr(vec, "__len__") else self._DEFAULT_DIM
            return ProviderHealth(
                ok=True,
                info="ok (model={}, dim={})".format(self._model_name, dim),
            )
        except StopIteration:
            return ProviderHealth(ok=False, info="embed returned empty result")
        except RuntimeError as e:
            return ProviderHealth(ok=False, info=str(e))
        except Exception as e:
            return ProviderHealth(ok=False, info=str(e))

    def embed_texts(self, texts: list) -> list:
        """
        Batch embed texts through fastembed.
        Returns list of list[float]. Returns [] on failure.
        """
        if not texts:
            return []
        try:
            embedder = self._get_embedder()
            results = list(embedder.embed(texts))
            return [list(map(float, vec)) for vec in results]
        except Exception:
            return []
