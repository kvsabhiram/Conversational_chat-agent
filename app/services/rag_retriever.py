"""Phase 2: RAG retriever using ChromaDB.

Uploads sector-specific documents, chunks them, embeds them,
and retrieves relevant context for each user query.
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from dataclasses import dataclass
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger("rag")
settings = get_settings()


@dataclass
class RAGResult:
    chunks: list[str]
    sources: list[dict]
    total_chunks: int


class RAGRetriever:
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collections: dict = {}

    def _get_collection(self, sector: str):
        """Get or create a ChromaDB collection for a sector."""
        if sector not in self._collections:
            self._collections[sector] = self.client.get_or_create_collection(
                name=f"sector_{sector}",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[sector]

    async def add_document(
        self,
        sector: str,
        doc_id: str,
        content: str,
        metadata: dict | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> int:
        """Chunk a document and add to the sector's collection.

        Returns number of chunks added.
        """
        chunks = self._chunk_text(content, chunk_size, chunk_overlap)
        collection = self._get_collection(sector)

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {**(metadata or {}), "doc_id": doc_id, "chunk_index": i}
            for i in range(len(chunks))
        ]

        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
        )

        logger.info(f"Added {len(chunks)} chunks for doc={doc_id} sector={sector}")
        return len(chunks)

    async def retrieve(
        self,
        query: str,
        sector: str,
        top_k: int = 3,
    ) -> RAGResult:
        """Retrieve relevant chunks for a user query."""
        collection = self._get_collection(sector)

        if collection.count() == 0:
            return RAGResult(chunks=[], sources=[], total_chunks=0)

        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, collection.count()),
        )

        chunks = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        sources = [
            {
                "doc_id": m.get("doc_id", "unknown"),
                "chunk_index": m.get("chunk_index", 0),
                "relevance": round(1 - d, 3),  # cosine distance to similarity
            }
            for m, d in zip(metadatas, distances)
        ]

        logger.info(f"RAG: query='{query[:50]}' sector={sector} found={len(chunks)} chunks")

        return RAGResult(
            chunks=chunks,
            sources=sources,
            total_chunks=len(chunks),
        )

    async def delete_document(self, sector: str, doc_id: str):
        """Remove all chunks for a document."""
        collection = self._get_collection(sector)
        # Get all chunk IDs for this document
        results = collection.get(
            where={"doc_id": doc_id},
        )
        if results["ids"]:
            collection.delete(ids=results["ids"])
            logger.info(f"Deleted {len(results['ids'])} chunks for doc={doc_id}")

    def _chunk_text(
        self, text: str, chunk_size: int = 500, overlap: int = 50
    ) -> list[str]:
        """Split text into overlapping chunks."""
        words = text.split()
        chunks = []
        start = 0

        while start < len(words):
            end = start + chunk_size
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start = end - overlap

        return chunks if chunks else [text]


# Singleton
rag_retriever = RAGRetriever()
