"""Vérifie query_structured_data / list_datasets sur les données collectées,
sans dépendance à Voyage AI ou ChromaDB (non nécessaires pour ces opérations)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.rag_tools import RagToolHandler
from src.db.sqlite_store import SqliteStore
from src.questionnaire.schema import Role


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


class DummyEmbedder:
    pass


class DummyVectorstore:
    pass


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "test.sqlite3"))

        lieu1 = store.get_or_create_tiers_lieu("user-1", "Le Hangar")
        store.update_tiers_lieu(lieu1.id, pays="Belgique")
        c1 = store.get_or_create_contributeur("user-1", lieu1.id, Role.FONDATEUR.value)
        store.save_answer(lieu1.id, c1.id, "milieu", "Rural")

        lieu2 = store.get_or_create_tiers_lieu("user-2", "La Ruche")
        store.update_tiers_lieu(lieu2.id, pays="France")
        c2 = store.get_or_create_contributeur("user-2", lieu2.id, Role.FONDATEUR.value)
        store.save_answer(lieu2.id, c2.id, "milieu", "Urbain")

        lieu3 = store.get_or_create_tiers_lieu("user-3", "Le Champ des Possibles")
        store.update_tiers_lieu(lieu3.id, pays="France")
        c3 = store.get_or_create_contributeur("user-3", lieu3.id, Role.FONDATEUR.value)
        store.save_answer(lieu3.id, c3.id, "milieu", "Rural")

        handler = RagToolHandler(store, embedder=DummyEmbedder(), vectorstore=DummyVectorstore())

        datasets = handler.list_datasets({})
        names = [d["name"] for d in datasets["datasets"]]
        check("reponses_tiers_lieux listé parmi les datasets", "reponses_tiers_lieux" in names)

        result = handler.query_structured_data({
            "dataset_name": "reponses_tiers_lieux",
            "operation": "filter",
            "params": {"conditions": [{"column": "champ_id", "op": "eq", "value": "milieu"},
                                       {"column": "valeur", "op": "eq", "value": "Rural"}]},
        })
        check("2 lieux en milieu rural trouvés", result["row_count"] == 2)

        result_groupby = handler.query_structured_data({
            "dataset_name": "reponses_tiers_lieux",
            "operation": "groupby_count",
            "params": {"by": ["champ_id"], "target_column": "tiers_lieu"},
        })
        check("groupby_count renvoie un compte par champ", result_groupby["result"].get("milieu") == 3)

        print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
