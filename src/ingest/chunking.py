"""Découpage de texte en chunks pour l'indexation vectorielle, en respectant
autant que possible les paragraphes, avec un léger recouvrement pour ne pas
couper le contexte à la frontière de deux chunks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


def chunk_text(text: str, metadata: dict, chunk_size: int = 1000, overlap: int = 150) -> list:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
        if len(para) > chunk_size:
            # paragraphe trop long à lui seul : découpage brut avec recouvrement
            start = 0
            while start < len(para):
                end = start + chunk_size
                chunks.append(para[start:end])
                start = end - overlap
            current = ""
        else:
            current = para
    if current:
        chunks.append(current)

    # applique un recouvrement léger entre chunks consécutifs (contexte de fin du précédent)
    result = []
    for i, c in enumerate(chunks):
        if i > 0 and overlap > 0:
            prefix = chunks[i - 1][-overlap:]
            c = f"{prefix}\n\n{c}"
        result.append(Chunk(text=c, metadata={**metadata, "chunk_index": i}))
    return result
