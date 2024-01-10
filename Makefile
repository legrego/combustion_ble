.PHONY : docs
docs :
	rm -rf docs/build/
	sphinx-autobuild -b html --watch combustion_ble/ docs/source/ docs/build/

.PHONY : run-checks
run-checks :
	isort --check .
	black --check .
	ruff check .
	mypy .
	pytest -v --color=yes --doctest-modules tests/ combustion_ble/

.PHONY : build
build :
	rm -rf *.egg-info/
	python -m build
