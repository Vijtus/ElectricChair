.PHONY: setup run syntax firmware-build firmware-upload firmware-monitor clean

setup:
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

run:
	python app.py

syntax:
	python -m py_compile app.py

firmware-build:
	cd electric_chair_firmware && platformio run

firmware-upload:
	cd electric_chair_firmware && platformio run -t upload

firmware-monitor:
	cd electric_chair_firmware && platformio device monitor -b 115200

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf electric_chair_firmware/.pio
