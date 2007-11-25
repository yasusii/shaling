#!/usr/bin/env python
import sys, os, re, os.path, gzip, struct
from fooling.corpus import Corpus
from fooling.document import EMailDocument
from fooling.selection import Predicate
from tardb import TarInfo, TarDB, FileLock
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
  
  def add_label(self, labels):
    self.corpus.add_label(self.loc, labels)
    self.labels.update(labels)
    return

  def del_label(self, labels):
    self.corpus.del_label(self.loc, labels)
    self.labels.difference_update(labels)
    return


##  LabelPredicate
##
class LabelPredicate(Predicate):
  
  def __init__(self, labeldb, name, neg):
    Predicate.__init__(self)
    self.neg = neg
    label = config.str2label(name)
    if neg:
      self.q = '+!'+name
    else:
      self.q = '+'+name
    self.msgids = sorted(labeldb.get_msgids(label), reverse=True)
    self.curidx = 0
    return

  def __str__(self):
    return self.q

  def narrow(self, idx):
    # Assuming: msgids are in descending order.
    # Assuming: docids are in descending order.
    (docids,_) = struct.unpack('>ii', idx[''])
    try:
      firstmsgid = int(idx['\x00'+struct.pack('>i', docids-1)])
    except (KeyError, ValueError):
      return []
    while self.curidx < len(self.msgids):
      if firstmsgid >= self.msgids[self.curidx]: break
      self.curidx += 1
    locs = []
    while self.curidx < len(self.msgids):
      k = '\xff'+str(self.msgids[self.curidx])
      if not idx.has_key(k): break
      (docid,) = struct.unpack('>i', idx[k])
      locs.append((docid, 0))
      self.curidx += 1
    return locs


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

class DefaultLabelBlock(LabelBlock):
  def __str__(self):
    return ''
DEFAULT_FILTER = DefaultLabelBlock(config.FILTERED_LABELS)
DEFAULT_FILTER_WITH_SENT = DefaultLabelBlock(config.FILTERED_LABELS.difference([config.LABEL4SENT]))


##  LabelDB
##
class LabelDB:

  class LabelDBError(Exception): pass
  class FileError(LabelDBError): pass
  
  def __init__(self, basedir, prefix='label'):
    if not os.path.isdir(basedir):
      raise LabelDB.FileError('%r is not a directory.' % basedir)
    self.basedir = basedir
    self.prefix = prefix
    self.cache = {}
    self.changed = set()
    return

  def __repr__(self):
    return '<LabelDB: basedir=%r, prefix=%r, cached=%d, changed=%d>' % \
           (self.basedir, self.prefix, len(self.cache), len(self.changed))

  def get_file(self, label):
    return os.path.join(self.basedir, '%s_%02x' % (self.prefix, ord(label)))

  def get_msgids(self, label):
    if label in self.cache:
      return self.cache[label]
    fname = self.get_file(label)
    if os.path.exists(fname):
      try:
        fp = file(fname, 'rb')
        data = fp.read()
        fp.close()
      except IOError, e:
        raise LabelDB.FileError(e)
      msgids = set(struct.unpack('>%di' % (len(data)/4), data))
    else:
      msgids = set()
    self.cache[label] = msgids
    return msgids

  def add_label(self, msgid, labels):
    for label in labels:
      msgids = self.get_msgids(label)
      if msgid not in msgids:
        msgids.add(msgid)
        self.changed.add(label)
    return

  def del_label(self, msgid, labels):
    for label in labels:
      msgids = self.get_msgids(label)
      if msgid in msgids:
        msgids.remove(msgid)
        self.changed.add(label)
    return
    
  def close(self):
    for label in self.changed:
      msgids = sorted(self.cache[label])
      data = struct.pack('>%di' % len(msgids), *msgids)
      try:
        fp = file(self.get_file(label), 'wb')
        fp.write(data)
        fp.close()
      except IOError:
        pass
    self.changed.clear()
    return


##  MailCorpus
##
class MailCorpus(Corpus):

  class MailCorpusError(Exception): pass
  class DatabaseLocked(MailCorpusError): pass

  SMALL_MERGE = 20
  LARGE_MERGE = 2000

  singleton_handler = None
  @classmethod
  def register_singleton_handler(klass, handler):
    klass.singleton_handler = handler
    return
  
  def _get_singleton(self):
    return MailCorpus.singleton_handler(self.dirname)

  def __getstate__(self):
    odict = Corpus.__getstate__(self)
    # there odict values are never treated seriously.
    del odict['mode']
    del odict['_db']
    del odict['_labeldb']
    del odict['_last_unindexed_loc']
    return odict

  def __init__(self, dirname, verbose=False):
    self.verbose = verbose
    self.dirname = dirname
    self.mode = None
    self._last_unindexed_loc = None
    self._db = TarDB(os.path.join(dirname, 'tar'))
    self._labeldb = LabelDB(os.path.join(dirname, 'label'))
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
    os.mkdir(os.path.join(dirname, 'label'))
    TarDB.create(os.path.join(dirname, 'tar'))
    return

  def set_writable(self):
    if self.mode == 'r+': return
    if self.mode == 'r':
      self.close()
    try:
      self.open('r+')
    except MailCorpus.DatabaseLocked:
      self.open('r')
      raise
    return

  def get_labeldb(self):
    return self._labeldb

  def open(self, mode='r'):
    try:
      self._db.open(mode)
    except TarDB.LockError:
      raise MailCorpus.DatabaseLocked('Database locked.')
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
        indexer.index_doc(str(i), indexyomi=config.INDEX_YOMI)
      indexer.finish()
      self.merge(force)
      self._last_unindexed_loc = None
    return

  def close(self, notice=None):
    self.flush(notice)
    self.mode = None
    self._db.close()
    self._labeldb.close()
    return
  
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
    
  def add_label(self, loc, labels):
    recno = int(loc)
    info = self._db.get_info(recno)
    labels1 = self._name2labels(info.name).union(set(labels))
    info.name = self._labels2name(recno, labels1)
    self._db.set_info(recno, info)
    self._labeldb.add_label(recno, labels)
    return

  def del_label(self, loc, labels):
    recno = int(loc)
    info = self._db.get_info(recno)
    labels1 = self._name2labels(info.name).difference(set(labels))
    info.name = self._labels2name(recno, labels1)
    self._db.set_info(recno, info)
    self._labeldb.del_label(recno, labels)
    return

  def set_deleted_label(self, loc):
    self.add_label(loc, config.LABEL4DELETED)
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
    print 'usage: %s create dbpath' % argv[0]
    print 'usage: %s [-v] info dbpath' % argv[0]
    print 'usage: %s [-m] get dbpath msgid ...' % argv[0]
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
    print len(corpus), 'messages'
    total = 0
    for loc in xrange(len(corpus)):
      total += corpus.loc_size(loc)
    print total, 'bytes in total'
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
