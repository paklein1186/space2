-- Magasin de vecteurs persistant (remplace Chroma local, dont le disque est
-- éphémère sur Streamlit Cloud : chaque redéploiement le vidait, et la
-- recherche sémantique ne retrouvait plus que quelques lieux — vécu avec
-- « Quatre Quarts »). Voyage voyage-multilingual-2 = 1024 dimensions.
create extension if not exists vector;

create table if not exists documents_vectoriels (
    id text primary key,
    doc_type text not null,
    tiers_lieu_id uuid references tiers_lieux(id) on delete cascade,  -- profils : supprimés avec leur lieu
    source_file text,
    contenu text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1024) not null,
    maj_le timestamptz not null default now()
);
create index if not exists documents_vectoriels_doc_type_idx on documents_vectoriels (doc_type);
create index if not exists documents_vectoriels_embedding_idx
    on documents_vectoriels using hnsw (embedding vector_cosine_ops);

-- Accès uniquement via la clé service_role (côté serveur : app et API).
alter table documents_vectoriels enable row level security;

create or replace function match_documents(
    query_embedding vector(1024),
    match_count int default 6,
    filter_doc_type text default null
) returns table (id text, contenu text, metadata jsonb, similarity float)
language sql stable as $$
    select d.id, d.contenu, d.metadata, 1 - (d.embedding <=> query_embedding) as similarity
    from documents_vectoriels d
    where filter_doc_type is null or d.doc_type = filter_doc_type
    order by d.embedding <=> query_embedding
    limit match_count;
$$;
