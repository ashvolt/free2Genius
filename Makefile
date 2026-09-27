.PHONY: help setup models data train policy evals api web test all clean demo

PY := .venv/bin/python
PIP := .venv/bin/pip

help:
	@echo "Free2Genius — make targets"
	@echo ""
	@echo "  setup    create the venv and install Python dependencies"
	@echo "  models   download the open-weights GGUF model files (~2.9GB)"
	@echo "  data     generate the synthetic cohorts"
	@echo "  train    train the propensity and uplift models, write metrics and charts"
	@echo "  policy   run the targeting policy and offline policy evaluation"
	@echo "  evals    run the agent safety gate (exits non-zero on a violation)"
	@echo "  demo     seed a simulated experiment for the console"
	@echo "  all      data -> train -> policy -> evals -> demo -> model card"
	@echo "  api      run the HTTP service on :8000"
	@echo "  web      run the console on :5173"
	@echo "  test     run the full test suite"
	@echo ""
	@echo "Everything except 'models' runs with no network and no API key."

setup:
	python3 -m venv .venv
	$(PIP) install --quiet --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "done. Optional, for local LLM inference: $(PIP) install llama-cpp-python"

models:
	@mkdir -p models
	curl -L --retry 4 -o models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
	  "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
	curl -L --retry 4 -o models/Qwen2.5-3B-Instruct-Q4_K_M.gguf \
	  "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf"

data:
	$(PY) -m f2g.data.generate

train:
	$(PY) -m f2g.ml.train

policy:
	$(PY) -m f2g.ml.run_policy

evals:
	$(PY) -m f2g.evals.run --provider deterministic

evals-local:
	$(PY) -m f2g.evals.run --provider llamacpp --judge llamacpp

demo:
	$(PY) scripts/seed_experiment.py

card:
	$(PY) -m f2g.governance.model_card

all: data train policy evals demo card
	@echo ""
	@echo "Pipeline complete. Start the service with 'make api' and the console with 'make web'."

api:
	.venv/bin/uvicorn f2g.api.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd web && npm install && npm run dev

test:
	$(PY) -m pytest tests/ -q

clean:
	rm -rf artifacts data/*.csv data/*.db
	@echo "removed generated artifacts. Model weights in models/ were kept."
