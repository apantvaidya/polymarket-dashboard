.PHONY: test ingest replay

test:
	pytest

ingest:
	python -m market_edge.ingest

replay:
	python -m market_edge.replay
