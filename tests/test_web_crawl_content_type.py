"""fetch_page_text / fetch_page_text_complet : le type de contenu réel de
l'URL est détecté avant de le traiter comme du HTML — un PDF/docx passe par
la vraie extraction, un type binaire non pris en charge lève une erreur
explicite. Sans réseau (requests.get simulé).

Vécu : un lien vers un PDF de 20 Mo, sa réponse brute parsée comme HTML faute
de détection, avait produit ~24 500 passages de charabia binaire lors de
l'ajout à la base de connaissances (au lieu de quelques centaines de vrais
passages), saturant Voyage/Supabase pendant de longues minutes.

Usage : python3 -m tests.test_web_crawl_content_type
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.agent.web_crawl as web_crawl
from src.agent.web_crawl import DOCX_CONTENT_TYPE, fetch_page_text, fetch_page_text_complet


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def faux_get(reponse):
    def _get(url, timeout=None, headers=None):
        return reponse
    return _get


class FauxReponse:
    def __init__(self, content_type=None, contenu_binaire=b"", texte_html=""):
        self.headers = {"content-type": content_type} if content_type else {}
        self.content = contenu_binaire
        self.text = texte_html

    def raise_for_status(self):
        pass


def pdf_minimal() -> bytes:
    """Un PDF valide minimal (une page, le mot GARE), généré à la volée."""
    from pypdf import PdfWriter

    import io
    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    return buf.getvalue()


def main():
    reel = web_crawl.requests.get
    try:
        # --- PDF détecté par content-type (même sans extension .pdf dans l'URL) ---
        pdf_bytes = pdf_minimal()
        web_crawl.requests.get = faux_get(FauxReponse(content_type="application/pdf", contenu_binaire=pdf_bytes))
        texte = fetch_page_text_complet("https://exemple.org/telecharger?id=42")
        check("PDF (content-type) : extrait via pypdf, pas parsé comme HTML",
              "%PDF" not in texte and "obj" not in texte)

        # --- PDF détecté par l'extension de l'URL, sans en-tête content-type ---
        web_crawl.requests.get = faux_get(FauxReponse(content_type=None, contenu_binaire=pdf_bytes))
        texte = fetch_page_text_complet("https://exemple.org/rapport.pdf")
        check("PDF (extension d'URL, sans content-type) : extrait via pypdf",
              "%PDF" not in texte and "obj" not in texte)

        # --- docx détecté par content-type ---
        import docx
        import io
        buf = io.BytesIO()
        d = docx.Document()
        d.add_paragraph("Contenu du rapport docx.")
        d.save(buf)
        web_crawl.requests.get = faux_get(FauxReponse(content_type=DOCX_CONTENT_TYPE, contenu_binaire=buf.getvalue()))
        texte = fetch_page_text_complet("https://exemple.org/telecharger?id=7")
        check("docx (content-type) : extrait via python-docx", "Contenu du rapport docx." in texte)

        # --- page HTML normale : comportement inchangé ---
        html = "<html><body><nav>menu</nav><p>Premier paragraphe.</p><p>Second paragraphe.</p></body></html>"
        web_crawl.requests.get = faux_get(FauxReponse(content_type="text/html; charset=utf-8", texte_html=html))
        texte = fetch_page_text_complet("https://exemple.org/page")
        check("HTML : nav exclu, paragraphes conservés",
              "menu" not in texte and "Premier paragraphe." in texte and "Second paragraphe." in texte)
        court = fetch_page_text("https://exemple.org/page")
        check("fetch_page_text (court) : même filtrage, sur une seule ligne",
              "menu" not in court and "Premier paragraphe." in court)

        # --- content-type absent (certains serveurs) : traité comme HTML, comportement d'avant ---
        web_crawl.requests.get = faux_get(FauxReponse(content_type=None, texte_html=html))
        check("sans en-tête content-type, URL sans extension connue : toujours traité comme HTML",
              "Premier paragraphe." in fetch_page_text_complet("https://exemple.org/page-sans-extension"))

        # --- type binaire non supporté : erreur explicite, jamais parsé comme HTML ---
        web_crawl.requests.get = faux_get(FauxReponse(content_type="image/png", contenu_binaire=b"\x89PNG\r\n"))
        try:
            fetch_page_text_complet("https://exemple.org/photo")
            check("image : devrait lever une erreur", False)
        except ValueError as exc:
            check("image : erreur explicite mentionnant le type de contenu", "image/png" in str(exc))

        web_crawl.requests.get = faux_get(FauxReponse(content_type="application/zip", contenu_binaire=b"PK\x03\x04"))
        try:
            fetch_page_text_complet("https://exemple.org/archive.zip")
            check("zip : devrait lever une erreur", False)
        except ValueError:
            check("zip : erreur explicite plutôt que du charabia", True)
    finally:
        web_crawl.requests.get = reel
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
