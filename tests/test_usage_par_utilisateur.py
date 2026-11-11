"""Suivi d'usage/coût LLM par utilisateur (migration_018 : llm_calls.user_id) —
log_llm_call enregistre bien l'utilisateur, get_usage_par_utilisateur agrège
correctement par utilisateur et respecte le filtre de période, et les appels
sans utilisateur attribuable (tâches de fond) n'apparaissent dans aucune
ligne. Sans réseau, sans appel LLM.

Usage : python3 -m tests.test_usage_par_utilisateur
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.sqlite_store import SqliteStore


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "usage.sqlite3"))

        # Deux utilisateurs, plusieurs appels chacun, un appel de fond sans utilisateur.
        store.log_llm_call("rag_query", "claude-sonnet-5", 1000, 200, 0.01, user_id="user-a")
        store.log_llm_call("rag_query", "claude-sonnet-5", 2000, 400, 0.02, user_id="user-a")
        store.log_llm_call("entretien", "claude-sonnet-5", 500, 100, 0.005, user_id="user-b")
        store.log_llm_call("enrichissement", "claude-sonnet-5", 9000, 900, 0.5, user_id=None)

        usage = store.get_usage_par_utilisateur()
        check("2 utilisateurs distincts (pas le user_id=None)", len(usage) == 2)
        par_user = {u["user_id"]: u for u in usage}
        check("user-a : 2 appels agrégés", par_user["user-a"]["nb_appels"] == 2)
        check("user-a : tokens_in cumulés (1000+2000)", par_user["user-a"]["tokens_in"] == 3000)
        check("user-a : coût cumulé (0.01+0.02)", abs(par_user["user-a"]["cout_total"] - 0.03) < 1e-9)
        check("user-b : 1 appel", par_user["user-b"]["nb_appels"] == 1)
        check("trié du coût le plus élevé au plus faible", usage[0]["user_id"] == "user-a")
        check("appel sans utilisateur (tâche de fond) absent de l'agrégation",
              all(u["user_id"] != "None" for u in usage))

        # Filtre de période : un appel "ancien" ne doit pas compter dans une
        # fenêtre récente, mais doit rester visible sans filtre.
        ancien = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        store.conn.execute(
            "insert into llm_calls (id, type_appel, user_id, model, tokens_in, tokens_out, "
            "cout_estime, cree_le) values ('ancien-1', 'rag_query', 'user-c', 'claude-sonnet-5', "
            "100, 10, 0.001, ?)", (ancien,),
        )
        store.conn.commit()
        recent = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        usage_recent = store.get_usage_par_utilisateur(depuis=recent)
        check("filtre de période : l'appel ancien de user-c est exclu",
              "user-c" not in {u["user_id"] for u in usage_recent})
        usage_tout = store.get_usage_par_utilisateur()
        check("sans filtre : user-c apparaît bien",
              "user-c" in {u["user_id"] for u in usage_tout})

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
