.PHONY: setup run check fw upload monitor clean

setup:
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

run:
	python app.py

check:
	python -m py_compile app.py

fw:
	platformio run -d firmware

upload:
	platformio run -d firmware -t upload

monitor:
	platformio device monitor -d firmware -b 115200

clean:
	rm -rf .venv __pycache__ .pytest_cache firmware/.pio
	find . -name '*.pyc' -delete
