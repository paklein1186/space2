"""Vraie visite de Space2 dans un navigateur sans écran (workflow keep-awake).

Un simple `curl` ne compte pas comme une visite pour Streamlit Community Cloud :
il ne reçoit que la page HTML vide, sans ouvrir la session (websocket) qui fait
tourner l'app — l'app retombait donc en veille malgré le ping (constaté le
25/11/2026). Ici, Chromium charge la page, clique sur le bouton de réveil si
l'app dort, attend que l'accueil soit réellement affiché, puis reste connecté
quelques secondes.

Code de sortie 1 si l'accueil ne s'affiche pas : le workflow échoue et GitHub
prévient par email, ce qui sert aussi de surveillance.
"""

import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = "https://space2.streamlit.app/"
DELAI_MAX = 300           # secondes : un réveil à froid prend 1 à 3 minutes
MARQUEUR = re.compile(r"Lieux recensés|Places listed")
BOUTON_REVEIL = re.compile(r"get this app back up|wake", re.I)


def texte_app(page) -> str:
    textes = []
    for frame in page.frames:
        try:
            textes.append(frame.locator("body").inner_text(timeout=2000))
        except Exception:
            pass
    return "\n".join(textes)


def main() -> int:
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        debut, reveil_clique = time.monotonic(), False
        while time.monotonic() - debut < DELAI_MAX:
            if MARQUEUR.search(texte_app(page)):
                print(f"Accueil affiché après {time.monotonic() - debut:.0f}s"
                      + (" (app réveillée)" if reveil_clique else ""))
                time.sleep(20)   # session ouverte assez longtemps pour compter comme visite
                navigateur.close()
                return 0
            bouton = page.get_by_role("button", name=BOUTON_REVEIL)
            if not reveil_clique and bouton.count():
                print("App en veille : clic sur le bouton de réveil")
                bouton.first.click()
                reveil_clique = True
            time.sleep(5)
        page.screenshot(path="space2.png", full_page=True)
        print(f"Accueil non affiché après {DELAI_MAX}s. Texte vu :\n{texte_app(page)[:1500]}")
        navigateur.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
