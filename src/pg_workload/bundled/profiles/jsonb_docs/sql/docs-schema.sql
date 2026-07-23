DROP SCHEMA IF EXISTS jsonb_docs CASCADE;
CREATE SCHEMA jsonb_docs;

CREATE TABLE jsonb_docs.documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_type text NOT NULL,
    doc jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Containment (@>) lookups.
CREATE INDEX documents_doc_gin ON jsonb_docs.documents USING gin (doc jsonb_path_ops);
-- Equality on the most-filtered key.
CREATE INDEX documents_status_idx ON jsonb_docs.documents ((doc ->> 'status'));
