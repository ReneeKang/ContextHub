# Local dev: official OpenSearch + analysis-nori for Korean BM25 text fields.
# Build: `docker compose build opensearch` (see README).
FROM opensearchproject/opensearch:2.17.1
USER root
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch analysis-nori
USER opensearch
