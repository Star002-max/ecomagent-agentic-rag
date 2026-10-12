"""Load Markdown knowledge, split it, embed locally, and retrieve with Chroma."""

import hashlib
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.agent.model import redact
from src.config import (EmbeddingSettings, PROJECT_ROOT,
                        load_embedding_settings)


class KnowledgeBaseError(RuntimeError):
    """The local knowledge base cannot be loaded or searched."""


ALIYUN_MAX_INPUT_UTF8_BYTES = 4096


class LocalHashEmbeddings(Embeddings):
    """Small deterministic character n-gram embeddings for this local Chinese KB.

    They need no API key or model download. This is intentionally a learning-
    project baseline, not a replacement for a production semantic model.
    """

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 32:
            raise ValueError("Embedding维度不能小于32。")
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        normalized = re.sub(r"\s+", "", text.lower())
        grams = [normalized[index:index + size]
                 for size in (1, 2, 3)
                 for index in range(max(0, len(normalized) - size + 1))]
        vector = [0.0] * self.dimensions
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            vector[value % self.dimensions] += 1.0 if value & 1 else -1.0
        norm = math.sqrt(sum(item * item for item in vector))
        return [item / norm for item in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class ProtectedEmbeddings(Embeddings):
    """Keep provider failures useful while removing the embedding credential."""

    def __init__(self, inner: Embeddings, api_key: str, *, dimensions: int,
                 provider: str, model: str,
                 max_input_utf8_bytes: int = ALIYUN_MAX_INPUT_UTF8_BYTES) -> None:
        self._inner = inner
        self._api_key = api_key
        self.dimensions = dimensions
        self.provider = provider
        self.model = model
        self.max_input_utf8_bytes = max_input_utf8_bytes

    def _validate_input_size(self, texts: list[str] | str) -> None:
        values = [texts] if isinstance(texts, str) else texts
        for index, text in enumerate(values, start=1):
            if len(text.encode("utf-8")) > self.max_input_utf8_bytes:
                raise ValueError(
                    f"Embedding输入第{index}条超过"
                    f"{self.max_input_utf8_bytes} UTF-8字节限制；请缩短输入。"
                )

    def _call(self, method: str, texts: list[str] | str):
        self._validate_input_size(texts)
        try:
            return getattr(self._inner, method)(texts)
        except Exception as exc:
            message = redact(str(exc), self._api_key)
            raise RuntimeError(
                f"Embedding请求失败（{type(exc).__name__}）：{message[:800]}"
            ) from None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call("embed_documents", texts)

    def embed_query(self, text: str) -> list[float]:
        return self._call("embed_query", text)


def _validate_aliyun_settings(config: EmbeddingSettings) -> None:
    if config.model != "text-embedding-v4" or config.dimensions != 1024:
        raise ValueError("aliyun Embedding固定使用text-embedding-v4和1024维。")
    if not config.api_key or not config.base_url:
        raise ValueError("aliyun Embedding缺少API Key或Base URL。")
    url = urlsplit(config.base_url)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment
            or not url.hostname.endswith(".cn-beijing.maas.aliyuncs.com")
            or url.path.rstrip("/") != "/compatible-mode/v1"):
        raise ValueError("aliyun Embedding必须使用北京地域OpenAI兼容接口Base URL。")


def create_embeddings(settings: EmbeddingSettings | None = None) -> Embeddings:
    """Create the explicitly selected provider; local hashing is the safe default."""
    config = settings or load_embedding_settings()
    if config.provider == "local_hash":
        return LocalHashEmbeddings()
    if config.provider != "aliyun":
        raise ValueError("未知Embedding provider。")
    _validate_aliyun_settings(config)
    try:
        embeddings = OpenAIEmbeddings(
            model=config.model, api_key=config.api_key, base_url=config.base_url,
            dimensions=config.dimensions, timeout=20, max_retries=0,
            # For compatible APIs, send strings directly. The explicit byte guard
            # below keeps inputs bounded without assuming the provider's tokenizer.
            check_embedding_ctx_length=False,
            chunk_size=10, tiktoken_enabled=False,
        )
    except Exception as exc:
        message = redact(str(exc), config.api_key)
        raise RuntimeError(f"Embedding客户端初始化失败：{message[:800]}") from None
    return ProtectedEmbeddings(embeddings, config.api_key,
                               dimensions=config.dimensions,
                               provider=config.provider, model=config.model)


def load_markdown_documents(directory: Path) -> list[Document]:
    """Load each non-empty Markdown file with its repository-relative source."""
    if not directory.is_dir():
        raise KnowledgeBaseError(f"知识库目录不存在：{directory.name}")
    documents = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if content:
            documents.append(Document(page_content=content, metadata={
                "source": path.name,
            }))
    if not documents:
        raise KnowledgeBaseError("知识库中没有可加载的Markdown文档。")
    return documents


def split_markdown_documents(documents: list[Document], *, chunk_size: int = 420,
                             chunk_overlap: int = 60) -> list[Document]:
    """Preserve Markdown headings, then cap long sections with a simple splitter."""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "title"), ("##", "section")],
        strip_headers=False,
    )
    section_documents = []
    for document in documents:
        for section in header_splitter.split_text(document.page_content):
            section.metadata = {**document.metadata, **section.metadata}
            section_documents.append(section)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", ""],
    )
    chunks = splitter.split_documents(section_documents)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = index
    return chunks


class KnowledgeBase:
    """Own one in-memory Chroma collection and expose a small search result."""

    def __init__(self, documents: list[Document], embeddings: Embeddings,
                 *, collection_name: str = "ecomagent_operations",
                 embedding_provider: str | None = None,
                 embedding_dimensions: int | None = None) -> None:
        if not documents:
            raise KnowledgeBaseError("不能用空文档初始化知识库。")
        self.embedding_provider = embedding_provider or "injected"
        self.embedding_dimensions = embedding_dimensions
        self.documents = documents
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name=collection_name,
            collection_metadata={"hnsw:space": "cosine"},
        )
        self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 3})

    def search(self, query: str, *, k: int = 3) -> dict:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("query不能为空。")
        if not 1 <= k <= 5:
            raise ValueError("k必须在1到5之间。")
        documents = self.vector_store.similarity_search(cleaned, k=k)
        return {
            "query": cleaned,
            "matches": [{
                "content": document.page_content,
                "source": document.metadata["source"],
                "title": document.metadata.get("title"),
                "section": document.metadata.get("section"),
                "chunk_id": document.metadata["chunk_id"],
            } for document in documents],
        }


def build_knowledge_base(
    directory: Path = PROJECT_ROOT / "knowledge",
    embeddings: Embeddings | None = None,
    *,
    settings: EmbeddingSettings | None = None,
) -> KnowledgeBase:
    """Build a fresh provider-isolated in-memory index for the selected embedding."""
    if settings is None:
        if embeddings is not None and isinstance(embeddings, LocalHashEmbeddings):
            config = EmbeddingSettings(provider="local_hash")
        elif embeddings is not None:
            raise ValueError("注入非LocalHash Embeddings时必须同时提供匹配的EmbeddingSettings。")
        else:
            config = load_embedding_settings()
    else:
        config = settings
    if config.provider == "aliyun":
        _validate_aliyun_settings(config)
    selected = embeddings if embeddings is not None else create_embeddings(config)
    if config.provider == "local_hash":
        if not isinstance(selected, LocalHashEmbeddings):
            raise ValueError("local_hash配置必须使用LocalHashEmbeddings。")
        dimensions = selected.dimensions
    elif config.provider == "aliyun":
        selected_provider = getattr(selected, "provider", "aliyun"
                                    if isinstance(selected, OpenAIEmbeddings) else None)
        selected_model = getattr(selected, "model", config.model)
        selected_dimensions = getattr(selected, "dimensions", None)
        if (selected_provider != "aliyun" or selected_model != config.model
                or selected_dimensions != config.dimensions):
            raise ValueError("注入的Embeddings必须与aliyun provider、模型和维度配置一致。")
        dimensions = config.dimensions
    else:
        raise ValueError("未知Embedding provider。")
    documents = load_markdown_documents(directory)
    chunks = split_markdown_documents(documents)
    return KnowledgeBase(chunks, selected,
                         collection_name=f"ecomagent_operations_{config.provider}_{dimensions}d",
                         embedding_provider=config.provider,
                         embedding_dimensions=dimensions)
