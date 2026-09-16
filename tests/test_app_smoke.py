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
    check("Pas d'exception (page d'accueil, sans connexion)", not at.exception)

    # Accueil (pages/0_Accueil.py) est désormais la page par défaut — publique,
    # sans auth_screen() — donc user_id/session_state["user_id"] n'est PAS
    # renseigné tant qu'aucune page authentifiée n'a été visitée dans cette
    # session : les anciennes assertions "auto-login visible dès le chargement"
    # ne s'appliquent plus au chargement initial. Vérifie à la place que la
    # page d'accueil elle-même s'affiche correctement (str(at) est un repr de
    # debug, pas le texte rendu — utiliser les accesseurs typés d'AppTest).
    check("Titre de la page d'accueil affiché",
          any("réseau des lieux hybrides" in ti.value for ti in at.title))
    check("Bénéfices affichés (ex. documenter ses pratiques)",
          any("Documenter vos pratiques" in m.value for m in at.markdown))

    # Entretien/Bibliothèque/Lieux hybrides/Administration sont des pages
    # basées sur une fonction (st.Page(fonction, ...), pas un fichier) :
    # AppTest.switch_page() n'accepte que des pages basées sur un fichier,
    # donc ni l'auto-login LOCAL_DEV_AUTOLOGIN (déclenché par auth_screen(),
    # appelé seulement par ces pages) ni le contenu d'Administration ne sont
    # vérifiables ici — comportement confirmé manuellement dans le navigateur.

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
