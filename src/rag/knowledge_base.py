"""Load Markdown knowledge, split it, embed locally, and retrieve with Chroma."""

import hashlib
import math
import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.config import PROJECT_ROOT


class KnowledgeBaseError(RuntimeError):
    """The local knowledge base cannot be loaded or searched."""


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
                 *, collection_name: str = "ecomagent_operations") -> None:
        if not documents:
            raise KnowledgeBaseError("不能用空文档初始化知识库。")
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
) -> KnowledgeBase:
    """Build the complete local pipeline in one explicit composition function."""
    documents = load_markdown_documents(directory)
    chunks = split_markdown_documents(documents)
    return KnowledgeBase(chunks, embeddings or LocalHashEmbeddings())
