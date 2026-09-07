"""Pipeline d'indexation : parcourt data/raw/{interviews,reports,datasets,geodata},
extrait/découpe/embed le texte, upsert dans ChromaDB, et écrit data/catalog.json
(inventaire des datasets et couches géographiques pour query_structured_data).

Usage : python -m src.ingest.build_index
Ré-exécutable (idempotent grâce à l'upsert Chroma et aux ids stables par
fichier+chunk).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.agent.embeddings import VoyageEmbedder
from src.agent.vectorstore import ChromaStore
from src.ingest.chunking import chunk_text
from src.ingest.geodata import (
    SUPPORTED_GEODATA_SUFFIXES,
    geodata_summary_text,
    load_geodata_features,
)
from src.ingest.loaders import SUPPORTED_TEXT_SUFFIXES, extract_text
from src.ingest.structured import (
    SUPPORTED_DATASET_SUFFIXES,
    dataset_catalog_entry,
    dataset_summary_text,
    load_dataset,
)

RAW_DIR = Path("data/raw")
CATALOG_PATH = Path("data/catalog.json")


def iter_files(subdir: str, suffixes: set) -> list:
    folder = RAW_DIR / subdir
    if not folder.exists():
        return []
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in suffixes]


def process_text_documents(doc_type: str, subdir: str, embedder, store) -> int:
    count = 0
    for path in iter_files(subdir, SUPPORTED_TEXT_SUFFIXES):
        print(f"[{doc_type}] {path}")
        text = extract_text(path)
        if not text.strip():
            print(f"  (vide, ignoré)")
            continue
        chunks = chunk_text(text, metadata={"source_file": str(path), "doc_type": doc_type})
        embeddings = embedder.embed_documents([c.text for c in chunks])
        ids = [f"{path}::{c.metadata['chunk_index']}" for c in chunks]
        store.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )
        count += len(chunks)
    return count


def process_datasets(embedder, store, catalog: dict) -> int:
    count = 0
    for path in iter_files("datasets", SUPPORTED_DATASET_SUFFIXES):
        print(f"[dataset] {path}")
        try:
            df = load_dataset(path)
        except Exception as exc:
            print(f"  erreur de chargement: {exc}")
            continue
        name = path.stem
        catalog["datasets"][name] = dataset_catalog_entry(name, path, df)
        summary = dataset_summary_text(name, df)
        embedding = embedder.embed_documents([summary])[0]
        store.upsert(
            ids=[f"{path}::summary"],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{"source_file": str(path), "doc_type": "dataset_summary", "dataset_name": name}],
        )
        count += 1
    return count


def process_geodata(embedder, store, catalog: dict) -> int:
    count = 0
    for path in iter_files("geodata", SUPPORTED_GEODATA_SUFFIXES):
        print(f"[geodata] {path}")
        features = load_geodata_features(path)
        if not features:
            continue
        name = path.stem
        catalog["geodata"][name] = {
            "name": name, "path": str(path), "type": "geodata", "feature_count": len(features),
        }
        summary = geodata_summary_text(name, features)
        embedding = embedder.embed_documents([summary])[0]
        store.upsert(
            ids=[f"{path}::summary"],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{"source_file": str(path), "doc_type": "geodata", "dataset_name": name}],
        )
        count += 1
    return count


def main():
    load_dotenv()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    embedder = VoyageEmbedder()
    store = ChromaStore()
    catalog = {"datasets": {}, "geodata": {}}

    n_interviews = process_text_documents("interview", "interviews", embedder, store)
    n_reports = process_text_documents("rapport", "reports", embedder, store)
    n_datasets = process_datasets(embedder, store, catalog)
    n_geodata = process_geodata(embedder, store, catalog)

    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nTerminé : {n_interviews} chunks d'interviews, {n_reports} chunks de rapports, "
          f"{n_datasets} datasets, {n_geodata} couches géographiques indexés.")
    print(f"Collection Chroma : {store.count()} documents au total.")


if __name__ == "__main__":
    main()
