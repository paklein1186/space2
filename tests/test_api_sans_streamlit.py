"""L'API (Render) n'installe que requirements-api.txt, sans Streamlit : ni elle ni l'agent
d'entretien ne doivent charger Streamlit (panne du 20/11 : ModuleNotFoundError à l'ouverture
d'un entretien depuis troistiers.space, l'agent important field_label depuis src/annuaire.py).

Usage : python3 -m tests.test_api_sans_streamlit
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODULES = ["src.api.app", "src.api.entretien_api", "src.api.observatoire", "src.sso",
           "src.agent.collecte_agent", "src.agent.collecte_tools", "src.agent.web_crawl",
           "src.api.bibliotheque_api", "src.ingest.chunking", "src.agent.embeddings", "src.agent.vectorstore"]


def main():
    for m in MODULES:
        importlib.import_module(m)
    charges = [m for m in sys.modules if m == "streamlit" or m.startswith("streamlit.")]
    print(("[OK ] " if not charges else "[KO ] ") + "l'API et l'agent d'entretien ne chargent pas Streamlit")
    if charges:
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
