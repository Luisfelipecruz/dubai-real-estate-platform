.PHONY: up down logs seed test clean corpus index reindex corpus-stats llm-up eval \
        eval-truths eval-retrieval eval-agent eval-routing

up:                                ## Start all available services
	docker compose up -d

down:                              ## Stop all services
	docker compose down

logs:                              ## Tail all service logs
	docker compose logs -f

seed:                              ## Ingest CSVs from raw_source/ into Postgres
	docker compose --profile tools run --rm seed

test:                              ## Run test suite in container
	docker compose --profile tools run --rm test

clean:                             ## Stop everything and wipe volumes
	docker compose down -v --remove-orphans

# ── Retrieval corpus ────────────────────────────────────────────────────────
#
# `corpus` renders documents; `index` chunks, embeds and upserts them. They are two
# targets because the first needs only the database and the second needs the embeddings
# service -- and because a corpus you can read before it is embedded is a corpus you
# can debug.

corpus:                            ## Render docs + area fact sheets + notes to corpus.jsonl
	docker compose --profile tools run --rm corpus \
		python /app/scripts/build_corpus.py --docs /app/docs --out /app/corpus/corpus.jsonl

index: corpus                      ## Build the corpus and embed only what changed
	docker compose --profile tools run --rm corpus \
		python /app/scripts/index_corpus.py --corpus /app/corpus/corpus.jsonl

reindex: corpus                    ## Full rebuild -- re-embeds everything. Required after
                                   ## changing EMBEDDING_MODEL or the chunker.
	docker compose --profile tools run --rm corpus \
		python /app/scripts/index_corpus.py --corpus /app/corpus/corpus.jsonl --force

corpus-stats:                      ## What is actually indexed, per source
	curl -s http://localhost:8000/search/corpus | python3 -m json.tool

# ── Generation layer ────────────────────────────────────────────────────────

llm-up:                            ## Start the CONTAINERISED LLM. On macOS you do not want this.
	@echo "Docker Desktop on macOS cannot pass the Apple GPU into a Linux container, so"
	@echo "this runs on CPU while the host's Ollama uses Metal. The default"
	@echo "OLLAMA_BASE_URL already points at the host (host.docker.internal:11434)."
	@echo "This target is for a Linux host with a GPU, or for CI. Ctrl-C to stop."
	docker compose --profile llm up -d ollama
	docker compose --profile llm exec ollama ollama pull $${OLLAMA_MODEL:-gpt-oss:20b}

# --record stores the result in eval_results, which is where GET /evals/latest reads it.
# Without it the score exists only in this terminal. The single-suite targets below
# deliberately do NOT record: a partial suite must not become the published score.
eval:                              ## Truths + retrieval + agent, with the regression gate
	docker compose exec api python /app/scripts/run_eval.py --suite all --gate --record

eval-truths:                       ## Seconds. Postgres only -- validates the fixture itself
	docker compose exec api python /app/scripts/run_eval.py --suite truths

eval-retrieval:                    ## The four-mode ablation over eval/golden/retrieval.yaml
	docker compose exec api python /app/scripts/run_eval.py --suite retrieval

eval-agent:                        ## Route AND answer, graded on one response per question.
	@echo "Needs Ollama on the HOST with $${OLLAMA_MODEL:-gpt-oss:20b} pulled."
	@echo "Tens of minutes: every question is a multi-turn conversation with a 20B."
	docker compose exec api python /app/scripts/run_eval.py --suite agent

eval-routing:                      ## Grade routes only. No database, runs anywhere.
	docker compose exec api python /app/scripts/run_routing_eval.py
