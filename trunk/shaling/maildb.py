#!/usr/bin/env python
import sys, os, re, os.path, gzip
from fooling.corpus import Corpus
from fooling.document import EMailDocument
from tardb import TarInfo, TarDB, FileLockError
try:
  import cStringIO as StringIO
except ImportError:
  import StringIO as StringIO
import config
stderr = sys.stderr


##  EMailDocumentWithLabel
##
class EMailDocumentWithLabel(EMailDocument):

  # For displaying snippets, parsing the first 50kb is enough.
  MAX_SIZE = 50000
  
  def __init__(self, corpus, loc, mtime, labels=None):
    EMailDocument.__init__(self, corpus, loc)
    self.mtime = mtime
    self.labels = labels
    return
  
  def get_mtime(self):
    return self.mtime
  
  def __repr__(self):
    return '<EMailDocumentWithLabel: loc=%r, labels=%r>' % (self.loc, self.labels)


##  LabelBlock / LabelPass
##  picklable function objects for doc_preds.
##
class LabelBlock:

  def __init__(self, labels):
    self.filter_pat = re.compile(r'[%s]' % re.escape(''.join(labels)))
    return

  def __call__(self, loc, corpus):
    if self.filter_pat.search(''.join(sorted(corpus.get_label(loc)))): return -1
    return 0

class LabelPass:
  
  def __init__(self, labels):
    pat = ''
    for c in sorted(labels):
      c = re.escape(c)
      if pat:
        pat += '[^%s]*' % c
      pat += c
    self.filter_pat = re.compile(pat)
    return
  
  def __call__(self, loc, corpus):
    if self.filter_pat.search(''.join(sorted(corpus.get_label(loc)))): return 0
    return -1

DEFAULT_FILTER = LabelBlock(config.FILTERED_LABELS)
DEFAULT_FILTER_WITH_SENT = LabelBlock(config.FILTERED_LABELS.difference([config.LABEL4SENT]))


##  MailCorpus
##
class MailCorpus(Corpus):

  SMALL_MERGE = 20
  LARGE_MERGE = 2000

  corpus_handler = None
  @classmethod
  def register_corpus_handler(klass, handler):
    klass.corpus_handler = handler
    return
  
  def _unpickle(self):
    return MailCorpus.corpus_handler(self.dirname)

  def __getstate__(self):
    odict = Corpus.__getstate__(self)
    # there odict values are never treated seriously.
    del odict['mode']
    del odict['_db']
    del odict['_last_unindexed_loc']
    return odict

  def __init__(self, dirname, verbose=False):
    self.verbose = verbose
    self.dirname = dirname
    self.mode = None
    self._last_unindexed_loc = None
    self._db = TarDB(os.path.join(dirname, 'tar'))
    Corpus.__init__(self, os.path.join(dirname, 'idx'), 'idx')
    return

  def __len__(self):
    return len(self._db)
  
  def __repr__(self):
    return '<MailCorpus: dirname=%r, db=%r, last_unindexed_loc=%r>' % \
           (self.dirname, self._db, self._last_unindexed_loc)

  @staticmethod
  def create(dirname):
    os.mkdir(os.path.join(dirname, 'tar'))
    os.mkdir(os.path.join(dirname, 'idx'))
    TarDB.create(os.path.join(dirname, 'tar'))
    return

  def set_writable(self):
    if self.mode == 'r+': return
    if self.mode == 'r':
      self.close()
    self.open('r+')
    return

  def open(self, mode='r'):
    self._db.open(mode)
    self._last_unindexed_loc = None
    self.mode = mode
    return

  def merge(self, large=False):
    from fooling.merger import Merger
    docs_threshold = self.SMALL_MERGE
    if large:
      docs_threshold = self.LARGE_MERGE
    Merger(self, max_docs_threshold=docs_threshold).run(True)
    return

  def flush(self, notice=None, force=False):
    from fooling.indexer import Indexer
    if force:
      self._last_unindexed_loc = len(self)-1
    if self._last_unindexed_loc:
      indexer = Indexer(self, verbose=self.verbose)
      prevloc = int(self.index_lastloc() or '-1')
      lastloc = int(self._last_unindexed_loc)
      # notice is a function that receives the number of docs being indexed.
      if notice:
        notice(lastloc - prevloc)
      for i in xrange(prevloc+1, lastloc+1):
        indexer.index_doc(str(i))
      indexer.finish()
      self.merge(force)
      self._last_unindexed_loc = None
    return

  def close(self, notice=None):
    self.flush(notice)
    self.mode = None
    self._db.close()
    return
  
  def get_message(self, loc):
    (info, data) = self._db.get_record(int(loc))
    fp = gzip.GzipFile(fileobj=StringIO.StringIO(data))
    data = fp.read()
    fp.close()
    return data
    
  def get_message(self, loc):
    (info, data) = self._db.get_record(int(loc))
    fp = gzip.GzipFile(fileobj=StringIO.StringIO(data))
    data = fp.read()
    fp.close()
    return data
    
  def add_message(self, data, labels, mtime=0):
    import time
    info = TarInfo(self._labels2name(len(self._db), labels))
    info.mtime = mtime or int(time.time())
    fp = StringIO.StringIO()
    gz = gzip.GzipFile(mode='w', fileobj=fp)
    gz.write(data)
    gz.close()
    recno = self._db.add_record(info, fp.getvalue())
    self._last_unindexed_loc = str(recno)
    return self._last_unindexed_loc

  # Internal routine to access TarDB.
  def _labels2name(self, recno, labels):
    labels = ''.join(sorted(labels))
    if labels and not labels.isalnum():
      raise AssertionError('Invalid labels: %r' % labels)
    return '%08x.%s' % (recno, labels)
  
  FILENAME_PAT = re.compile(r'[0-9a-f]{8}\.(.*)')
  def _name2labels(self, name):
    m = self.FILENAME_PAT.match(name)
    if not m:
      raise AssertionError('Invalid file name: %r' % name)
    return set(m.group(1))
    
  def get_label(self, loc):
    info = self._db.get_info(int(loc))
    return self._name2labels(info.name)
    
  def set_label(self, loc, labels):
    info = self._db.get_info(int(loc))
    info.name = self._labels2name(int(loc), labels)
    self._db.set_info(int(loc), info)
    return

  def set_deleted_label(self, loc):
    self.set_label(loc, config.LABEL4DELETED)
    return

  # Corpus methods
  def loc_exists(self, loc):
    recno = int(loc)
    return 0 <= recno and recno < len(self._db)

  def loc_fp(self, loc):
    return StringIO.StringIO(self.get_message(loc))

  def loc_mtime(self, loc):
    info = self._db.get_info(int(loc))
    return info.mtime

  def loc_size(self, loc):
    return len(self.get_message(loc))

  def get_doc(self, loc):
    info = self._db.get_info(int(loc))
    labels = self._name2labels(info.name)
    return EMailDocumentWithLabel(self, loc, info.mtime, labels)


# main: 
def main(argv):
  import getopt
  def usage():
    print 'usage: %s [-m] {create,info,get} dbpath [args]' % argv[0]
    return 100
  try:
    (opts, args) = getopt.getopt(argv[1:], 'vm')
  except getopt.GetoptError:
    return usage()
  verbose = 0
  mbox = False
  for (k, v) in opts:
    if k == '-v': verbose += 1
    elif k == '-m': mbox = True
  if len(args) < 2:
    return usage()
  cmd = args.pop(0)
  dirname = args.pop(0)
  if cmd == 'create':
    # create new database
    os.umask(0077)
    try:
      os.mkdir(dirname)
    except OSError, e:
      print >>stderr, 'Cannot create a directory: %s' % e
      return 1
    os.chdir(dirname)
    for subdir in ('inbox',):
      os.mkdir(subdir)
      MailCorpus.create(subdir)
    os.mkdir('sel')
    os.mkdir('tmp')
  elif cmd == 'info':
    # info
    corpus = MailCorpus(os.path.join(dirname, 'inbox'))
    corpus.open()
    print len(corpus)
    total = 0
    for loc in xrange(len(corpus)):
      total += corpus.loc_size(loc)
    print total
    corpus.close()
  elif cmd == 'info':
    # info
    corpus = MailCorpus(os.path.join(dirname, 'inbox'))
    corpus.open()
    print len(corpus)
    total = 0
    for loc in xrange(len(corpus)):
      total += corpus.loc_size(loc)
    print total
    corpus.close()
  elif cmd == 'get':
    # get messages
    corpus = MailCorpus(os.path.join(dirname, 'inbox'))
    corpus.open()
    for loc in args:
      try:
        data = corpus.get_message(loc)
      except IndexError:
        print >>stderr, 'Invalid index: %s' % loc
        continue
      if mbox:
        print '\nFrom <#@[]>'
      if verbose:
        print 'Shaling-Record-Index:', loc
        print 'Shaling-Record-Mtime:', corpus.loc_mtime(loc)
        print 'Shaling-Record-Length:', len(data)
        print 'Shaling-Record-Label:', ' '.join(corpus.get_label(loc))
      sys.stdout.write(data)
    corpus.close()
  else:
    return usage()
  return

if __name__ == '__main__': sys.exit(main(sys.argv))
