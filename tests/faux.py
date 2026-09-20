"""Doublures de test partagées : client Anthropic en streaming et magasin de
vecteurs, sans réseau."""

import time
import types

import numpy as np


def bloc_texte(texte):
    b = types.SimpleNamespace(type="text", text=texte)
    b.model_dump = lambda exclude_none=True: {"type": "text", "text": texte}
    return b


def bloc_tool(id_, nom, entree):
    b = types.SimpleNamespace(type="tool_use", id=id_, name=nom, input=entree)
    b.model_dump = lambda exclude_none=True: {"type": "tool_use", "id": id_, "name": nom, "input": entree}
    return b


class FluxFaux:
    def __init__(self, contenu, delai, stop_reason):
        self.contenu, self.delai, self.stop_reason = contenu, delai, stop_reason

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for bloc in self.contenu:
            if bloc.type == "text":
                for i in range(0, len(bloc.text), 10):
                    time.sleep(self.delai)
                    yield types.SimpleNamespace(type="text", text=bloc.text[i:i + 10])
            yield types.SimpleNamespace(type="content_block_stop")

    def get_final_message(self):
        return types.SimpleNamespace(
            content=self.contenu, usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason=self.stop_reason or ("tool_use" if any(b.type == "tool_use" for b in self.contenu)
                                             else "end_turn"))


class FauxClient:
    """Rejoue une liste de réponses (listes de blocs) via messages.stream ;
    enregistre les kwargs de chaque appel."""

    def __init__(self, reponses, delai=0.0, stop_reason=None):
        self.reponses, self.delai, self.stop_reason = list(reponses), delai, stop_reason
        self.appels = []
        self.messages = self

    def stream(self, **kwargs):
        self.appels.append(kwargs)
        contenu = self.reponses.pop(0) if self.reponses else [bloc_texte("fin")]
        return FluxFaux(contenu, self.delai, self.stop_reason)


class FauxVectorStore:
    """Mime SupabaseVectorStore.query : documents (doc_type, source, texte, vecteur)."""

    def __init__(self, docs, echec=False):
        self.docs, self.echec, self.requetes = docs, echec, []

    def query(self, embedding, top_k=6, where=None):
        self.requetes.append(where)
        if self.echec:
            raise RuntimeError("table absente — Bearer pa-SECRETSECRETSECRETSECRET12345")
        q = np.array(embedding, dtype=float)
        hits = []
        for type_doc, source, texte, vec in self.docs:
            if where and where.get("doc_type") != type_doc:
                continue
            v = np.array(vec, dtype=float)
            hits.append({"text": texte, "distance": 1 - float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q))),
                         "metadata": {"doc_type": type_doc, "source_file": source}})
        return sorted(hits, key=lambda h: h["distance"])[:top_k]
