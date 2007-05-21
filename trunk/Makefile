# Makefile

PACKAGE=shaling
VERSION=`python -E shaling/__init__.py`

all:

clean:
	-rm *.pyc *.pyo *~
	-cd shaling; rm *.pyc *.pyo *~
	-cd shaling/fooling; rm *.pyc *.pyo *~


# Packaging:

pack: clean
	ln -s $(PACKAGE) ../$(PACKAGE)-dist-$(VERSION)
	gtar c -z -C.. -f ../$(PACKAGE)-dist-$(VERSION).tar.gz $(PACKAGE)-dist-$(VERSION) \
		--dereference --numeric-owner --exclude '.*' --exclude 'OZOU'
	rm ../$(PACKAGE)-dist-$(VERSION)

publish: pack
	mv ../$(PACKAGE)-dist-$(VERSION).tar.gz ~/public_html/python/shaling/
	cp docs/*.html ~/public_html/python/shaling/

push: clean
	rs ./ access:work/m/shaling/


# Pychecker:

pychecker:
	pychecker shaling/*.py
