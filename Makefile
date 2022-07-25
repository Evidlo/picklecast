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

# build debian source package in deb_dist/python3-picklecast_X.X.X-X._all.deb
# generate a key with 'gpg --no-default-keyring --keyring trustedkeys.gpg --quick-generate-key debian rsa4096'
.PHONY: deb
deb:
	# py2dsc --sign-results --sign-key "debian" dist/picklecast-$(version).tar.gz
	python3 setup.py \
		--command-packages=stdeb.command sdist_dsc \
		--sign-results --sign-key debian \
		--copyright-file debian_copyright \
		--build-depends dh-python

	# also build binary package for this distribution
	# cd deb_dist/picklecast-$(version)/
	# dpkg-buildpackage -rfakeroot -uc -us
	# cd ../..

.PHONY: deb_upload
deb_upload:
	dput mentors picklecast-

.PHONY:
clean:
	rm dist deb_dist -rf
