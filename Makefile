# Evan Widloski - 2019-03-04
# makefile for building/testing

# run all lines in target in single shell, quit on error
.ONESHELL:
.SHELLFLAGS = -ec

version := $(shell python -c "exec(open('picklecast/version.py').read());print(__version__)")

.PHONY: dist
dist:
	python setup.py sdist

.PHONY: pypi
pypi: dist
	twine upload dist/picklecast-$(version).tar.gz
