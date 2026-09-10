"""Vérifie que src/app.py s'exécute sans exception via streamlit.testing.v1.AppTest
(mode admin auto-login local, forcé explicitement — indépendant du contenu de
.env) — attrape les bugs de rendu (comme les KeyError/AttributeError
rencontrés en prod) sans avoir besoin d'un vrai navigateur.

Usage : python3 -m tests.test_app_smoke
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Forcé explicitement, indépendamment de ce que contient .env sur cette
# machine — le test doit être déterministe partout (CI comprise).
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SUPABASE_SERVICE_KEY"] = ""
os.environ["LOCAL_DEV_AUTOLOGIN"] = "true"
os.environ["LOCAL_DEV_ADMIN_EMAIL"] = "test-smoke@localhost"

from streamlit.testing.v1 import AppTest


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    at = AppTest.from_file("src/app.py", default_timeout=30)
    at.run()
    check("Pas d'exception (auto-login admin + rendu complet)", not at.exception)

    page = str(at)
    check("Session bien auto-loguée en admin", "test-smoke@localhost" in page)
    check("Les 3 onglets sont présents", all(t in page for t in ["Entretien", "Assistant RAG", "Annuaire"]))

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
