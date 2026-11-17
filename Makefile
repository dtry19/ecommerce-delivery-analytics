.PHONY: setup data build research test serve
PYTHON ?= python3

setup:
	$(PYTHON) -m pip install -r requirements.txt
data:
	$(PYTHON) download_data.py
build:
	$(PYTHON) pipeline.py
research: build
	$(PYTHON) research.py
test:
	$(PYTHON) -m unittest discover -s tests -v
serve:
	$(PYTHON) server.py
