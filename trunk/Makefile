# Makefile

PACKAGE=shaling
VERSION=`python -E shaling/__init__.py`
TAR=tar
SVN=svn

WORKDIR=..
DISTNAME=$(PACKAGE)-dist-$(VERSION)
DISTFILE=$(DISTNAME).tar.gz

all:

clean:
	-cd shaling; rm *.pyc *.pyo *~
	-cd shaling/fooling; rm *.pyc *.pyo *~


# Maintainance:

pack: clean
	$(SVN) cleanup
	$(SVN) export . $(WORKDIR)/$(DISTNAME)
	$(TAR) c -z -C$(WORKDIR) -f $(WORKDIR)/$(DISTFILE) $(DISTNAME) --dereference --numeric-owner
	rm -rf $(WORKDIR)/$(DISTNAME)

publish: pack
	mv $(WORKDIR)/$(DISTFILE) ~/public_html/python/shaling/
	cp docs/*.html ~/public_html/python/shaling/

pychecker:
	-pychecker --limit=0 shaling/*.py

commit: clean
	$(SVN) commit
