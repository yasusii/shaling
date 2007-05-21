#!/usr/bin/env python
##
##  tardb.py - tar database
##
##
##  Usage:
##
##   # creation of TarDB
##   TarDB.create('mydb')
##
##   (The following files are created.)
##   -rw-r--r--  1 yusuke   16 Dec 29 18:04 mydb/catalog
##   -rw-r--r--  1 yusuke    0 Dec 29 18:04 mydb/lock
##
##   # writing TarDB
##   db = TarDB('mydb')
##   db.open('r+')  # the entire database is locked.
##   print db.add_record(TarInfo('foo'), '123')  # 0
##   print db.add_record(TarInfo('bar'), '456')  # 1
##   db.close()
##
##   # reading TarDB
##   db = TarDB('mydb')
##   db.open()
##   (info0,data0) = get_record(0)
##   (info1,data1) = get_record(1)
##   # scanning all the records
##   for info in db:
##     print info
##   db.close()
##
##   # modifying TarDB (only meta information is changeable)
##   db = TarDB('mydb')
##   db.open('r+')
##   db[0] = TarInfo('zzz')
##   db.close()
##

import sys, os, os.path, re, atexit
from tarfile import BLOCKSIZE, TarInfo
stderr = sys.stderr


##  FileLock
##
class FileLockError(RuntimeError): pass

class FileLock:
  
  def __init__(self, fname):
    self.fname = fname
    self.locked = False
    atexit.register(self.emerge)
    return

  def __repr__(self):
    return '<FileLock: %r, locked=%r>' % (self.fname, self.locked)

  @staticmethod
  def create(fname):
    fp = file(fname, 'w')
    fp.close()
    return
  
  def acquire(self):
    if self.locked:
      raise FileLockError('already acquired: %r' % self)
    try:
      os.rename(self.fname, self.fname+'.locked')
    except OSError:
      raise FileLockError('failed to acquire: %r' % self)
    self.locked = True
    return
  
  def release(self):
    if not self.locked:
      raise FileLockError('not acquired: %r' % self)
    try:
      os.rename(self.fname+'.locked', self.fname)
    except OSError:
      raise FileLockError('failed to release: %r (THIS MUST NOT HAPPEN!)' % self)
    self.locked = False
    return
  
  def emerge(self):
    if self.locked:
      print >>stderr, 'Emergency lock released: %d: %r' % (os.getpid(), self.fname)
      self.release()
    return


##  Catalog
##
class Catalog:

  DEFAULT_RECORD_SIZE = 16
  
  def __init__(self, fname):
    self.fname = fname
    self.mode = None
    self.nrecords = 0
    self._fp = None
    self._record_size = None
    self._info_cache = {}
    self._cached = None
    return

  def __repr__(self):
    return '<Catalog: fname=%r, mode=%r, record_size=%s, nrecords=%s>' % \
           (self.fname, self.mode, self._record_size, self.nrecords)

  @staticmethod
  def create(fname, record_size=DEFAULT_RECORD_SIZE):
    fp = file(fname, 'wb')
    fp.write(''.join( str((i+1) % 10) for i in xrange(record_size-1) )+'\n')
    fp.close()
    return

  def open(self, mode='r', cached=True):
    if not (mode == 'r' or mode == 'r+'):
      raise IOError('invalid mode: %r' % mode)
    if self.mode:
      raise IOError('open: already opened: %r' % self)
    try:
      self._fp = file(os.path.join(self.fname), mode+'b')
    except IOError:
      raise
    first_line = self._fp.next()
    self._record_size = len(first_line)
    self._fp.seek(0, 2)
    size = self._fp.tell()
    if size % self._record_size != 0:
      raise IOError('open: illegal filesize: %r: %d mod %d != 0' % (self, size, self._record_size))
    self.nrecords = int(size / self._record_size)-1
    self.mode = mode
    self._cached = cached
    return self
  
  def close(self):
    if not self.mode:
      raise IOError('close: already closed: %r' % self)
    self._fp.close()
    self._fp = None
    self._info_cache.clear()
    self.mode = None
    return self
    
  def get(self, recno):
    if not self.mode:
      raise IOError('get: not opened: %r' % self)
    if recno < 0 or self.nrecords <= recno:
      raise IndexError('get: invalid record: %r: %d' % (self, recno))
    if recno in self._info_cache:
      return self._info_cache[recno]
    offset = (recno+1) * self._record_size
    self._fp.seek(offset)
    line = self._fp.read(self._record_size)
    if len(line) != self._record_size:
      raise IOError('get: premature eof: %r: offset=%d' % (self, offset))
    rec_offset = int(line[:8], 16)
    rec_file = line[8:].rstrip()
    if self._cached:
      self._info_cache[recno] = (rec_file, rec_offset)
    return (rec_file, rec_offset)

  def add(self, rec_file, rec_offset):
    if self.mode != 'r+':
      raise IOError('add: invalid mode: %r' % self)
    self._fp.seek(0, 2)
    line = '%08x%s' % (rec_offset, rec_file)
    nspaces = self._record_size - len(line) - 1
    if nspaces < 0:
      raise ValueError('add: too long record: %r: rec_file=%r' % (self, rec_file))
    line += ' '*nspaces
    self._fp.write(line+'\n')
    recno = self.nrecords
    if self._cached:
      self._info_cache[recno] = (rec_file, rec_offset)
    self.nrecords += 1
    return recno

  def __len__(self):
    if not self.mode:
      raise IOError('__len__: not opened: %r' % self)
    return self.nrecords

  def __getitem__(self, recno):
    if not self.mode:
      raise IOError('__getitem__: not opened: %r' % self)
    if recno < 0:
      recno %= self.nrecords
    return self.get(recno)

  def __iter__(self):
    if not self.mode:
      raise IOError('__iter__: not opened: %r' % self)
    for recno in xrange(self.nrecords):
      yield self.get(recno)
    return


##  TarDB
##
class TarDB:

  MAX_TARSIZE = 10*1024*1024            # default: 10Mbytes max
  EMPTY_BLOCK = '\x00' * BLOCKSIZE

  def __init__(self, basedir, catfile='catalog', lockfile='lock', maxsize=MAX_TARSIZE):
    self.basedir = basedir
    self.catfile = os.path.join(basedir, catfile)
    self._lock = FileLock(os.path.join(basedir, lockfile))
    self.maxsize = maxsize
    self.mode = None
    self._catalog = None
    self._tarfps = {}
    self._curname = None
    return

  def __repr__(self):
    return '<TarDB: basedir=%r, mode=%r, catfile=%r, lockfile=%r, maxsize=%d>' % \
           (self.basedir, self.mode, self.catfile, self._lock, self.maxsize)

  @staticmethod
  def create(basedir, catfile='catalog', lockfile='lock'):
    Catalog.create(os.path.join(basedir, catfile))
    FileLock.create(os.path.join(basedir, lockfile))
    return

  def generate_tarname(self, i):
    return 'db%05d' % i
  
  TARNAME_PAT = re.compile(r'^db(\d+)')
  def tarname_index(self, name):
    m = self.TARNAME_PAT.match(name)
    if not m:
      raise ValueError('tarname_index: invalid name: %r' % name)
    return int(m.group(1))

  def open(self, mode='r', cached=True):
    if not (mode == 'r' or mode == 'r+'):
      raise IOError('invalid mode: %r' % mode)
    if self.mode:
      raise IOError('open: already opened: %r' % self)
    if mode == 'r+':
      self._lock.acquire()
    try:
      self._catalog = Catalog(self.catfile)
    except IOError:
      raise
    self._catalog.open(mode, cached)
    if len(self._catalog):
      (self._curname, _) = self._catalog[-1]
    else:
      self._curname = self.generate_tarname(0)
    self.mode = mode
    return self

  def close(self):
    if not self.mode:
      raise IOError('close: already closed: %r' % self)
    for tarfp in self._tarfps.itervalues():
      tarfp.close()
    if self.mode == 'r+':
      self._lock.release()
    self._tarfps.clear()
    self._catalog.close()
    self._catalog = None
    self.mode = None
    return self

  def _get_tarfile(self, name):
    if name not in self._tarfps:
      fname = os.path.join(self.basedir, name)+'.tar'
      if os.path.exists(fname):
        tarfp = file(fname, self.mode+'b')
      else:
        # new tar file
        tarfp = file(fname, 'w+b')
      self._tarfps[name] = tarfp
    else:
      tarfp = self._tarfps[name]
    return tarfp

  def get_info(self, recno):
    if not self.mode:
      raise IOError('get_info: not opened: %r' % self)
    (name, offset) = self._catalog.get(recno)
    tarfp = self._get_tarfile(name)
    tarfp.seek(offset)
    buf = tarfp.read(BLOCKSIZE)
    if len(buf) != BLOCKSIZE:
      raise IOError('get_info: premature eof in info block: %r, info_offset=%d' % (self, offset))
    return TarInfo.frombuf(buf)
    
  def set_info(self, recno, info):
    if not self.mode:
      raise IOError('change_info: not opened: %r' % self)
    if self.mode != 'r+':
      raise IOError('add_record: invalid mode: %r' % self)
    (name, offset) = self._catalog.get(recno)
    tarfp = self._get_tarfile(name)
    tarfp.seek(offset)
    tarfp.write(info.tobuf())
    return

  def __len__(self):
    if not self.mode:
      raise IOError('__len__: not opened: %r' % self)
    return len(self._catalog)
    
  def __getitem__(self, recno):
    if not self.mode:
      raise IOError('__getitem__: not opened: %r' % self)
    return self.get_info(recno)

  def __setitem__(self, recno, info):
    if not self.mode:
      raise IOError('__setitem__: not opened: %r' % self)
    return self.set_info(recno, info)

  def __iter__(self):
    if not self.mode:
      raise IOError('__iter__: not opened: %r' % self)
    for recno in xrange(len(self._catalog)):
      yield self.get_info(recno)
    return
  
  def get_record(self, recno):
    if not self.mode:
      raise IOError('get_record: not opened: %r' % self)
    (name, offset) = self._catalog.get(recno)
    tarfp = self._get_tarfile(name)
    tarfp.seek(offset)
    buf = tarfp.read(BLOCKSIZE)
    if len(buf) != BLOCKSIZE:
      raise IOError('get_record: premature eof in info block: %r, info_offset=%d' % (self, offset))
    info = TarInfo.frombuf(buf)
    data = tarfp.read(info.size)
    if len(data) != info.size:
      raise IOError('get_record: premature eof in data block: %r, info_offset=%d' % (self, offset))
    return (info, data)

  def add_record(self, info, data):
    if not self.mode:
      raise IOError('add_record: not opened: %r' % self)
    if self.mode != 'r+':
      raise IOError('add_record: invalid mode: %r' % self)
    while 1:
      tarfp = self._get_tarfile(self._curname)
      tarfp.seek(0, 2)
      offset = tarfp.tell()
      if offset < self.maxsize: break
      i = self.tarname_index(self._curname)
      self._curname = self.generate_tarname(i+1)
    if offset % BLOCKSIZE != 0:
      raise IOError('add_record: invalid tar size: %r: info_offset=%d' % (self, offset))
    recno = self._catalog.add(self._curname, offset)
    info.size = len(data)
    tarfp.write(info.tobuf())
    tarfp.write(data)
    padsize = info.size % BLOCKSIZE
    if padsize:
      tarfp.write('\x00' * (BLOCKSIZE-padsize))
    return recno


# unittests
if __name__ == '__main__':
  import unittest
  dirname = './test/'
  if not os.path.exists(dirname):
    os.mkdir(dirname)
  
  class TarDBTest(unittest.TestCase):
    
    def setUp(self):
      TarDB.create(dirname)
      return
      
    def test_basic(self):
      # writing
      db = TarDB(dirname).open('r+')
      data_foo = '123'
      data_bar = 'ABCDEF'
      db.add_record(TarInfo('foo'), data_foo)
      db.add_record(TarInfo('bar'), data_bar)
      db.close()
      #
      files = os.listdir(dirname)
      self.assertEqual(len(files), 3)
      self.assertTrue('catalog' in files)
      self.assertTrue('lock' in files)
      self.assertTrue('db00000.tar' in files)
      # reading
      db = TarDB(dirname).open('r')
      (info1, data1) = db.get_record(0)
      self.assertEqual(data1, data_foo)
      self.assertEqual(len(data1), info1.size)
      (info2, data2) = db.get_record(1)
      self.assertEqual(data2, data_bar)
      self.assertEqual(len(data2), info2.size)
      # iter
      infos = list(db)
      self.assertEqual(len(infos), 2)
      self.assertEqual(infos[0].name, info1.name)
      self.assertEqual(infos[1].name, info2.name)
      db.close()
      return
    
    def test_split_tarfiles(self):
      # writing
      db = TarDB(dirname, maxsize=2048).open('r+')
      data_foo = '123'
      data_bar = 'ABCDEF'
      data_zzz = '!@#$%$'
      db.add_record(TarInfo('foo'), data_foo)
      db.add_record(TarInfo('bar'), data_bar)
      db.add_record(TarInfo('zzz'), data_zzz)
      db.close()
      #
      files = os.listdir(dirname)
      self.assertEqual(len(files), 4)
      self.assertTrue('catalog' in files)
      self.assertTrue('lock' in files)
      self.assertTrue('db00000.tar' in files)
      self.assertTrue('db00001.tar' in files)
      # reading
      db = TarDB(dirname).open('r')
      (info1, data1) = db.get_record(0)
      self.assertEqual(data1, data_foo)
      self.assertEqual(len(data1), info1.size)
      (info2, data2) = db.get_record(1)
      self.assertEqual(data2, data_bar)
      self.assertEqual(len(data2), info2.size)
      (info3, data3) = db.get_record(2)
      self.assertEqual(data3, data_zzz)
      self.assertEqual(len(data3), info3.size)
      # iter
      infos = list(db)
      self.assertEqual(len(infos), 3)
      self.assertEqual(infos[0].name, info1.name)
      self.assertEqual(infos[1].name, info2.name)
      self.assertEqual(infos[2].name, info3.name)
      db.close()
      return
    
    def test_change_info(self):
      # writing
      db = TarDB(dirname).open('r+')
      data_foo = '123'
      mtime = 12345
      info = TarInfo('foo')
      info.mtime = mtime
      db.add_record(info, data_foo)
      db.close()
      # reading
      db = TarDB(dirname).open('r+')
      info = db[0]
      self.assertEqual(info.mtime, mtime)
      db[0] = info
      db.close()
      return
    
    def test_failure(self):
      # opening failure
      self.assertRaises(IOError, lambda : TarDB('fungea').open())
      # writing failure
      db = TarDB(dirname).open('r')
      self.assertRaises(IOError, lambda : db.add_record(TarInfo('foo'), '123'))
      self.assertRaises(IndexError, lambda : db.get_record(0))
      db.close()
      return
    
    def test_tar_compatibility(self):
      # writing
      db = TarDB(dirname).open('r+')
      data_foo = '123'
      mtime = 12345
      info = TarInfo('foo')
      info.mtime = mtime
      db.add_record(info, data_foo)
      db.close()
      # reading with tarfile
      import tarfile
      tar = tarfile.TarFile(os.path.join(dirname, 'db00000.tar'))
      info = tar.next()
      data = tar.extractfile(info).read()
      self.assertEqual(data, data_foo)
      self.assertEqual(len(data), info.size)
      self.assertEqual(info.mtime, mtime)
      tar.close()
      return

    def test_lock(self):
      # opening multiple tars
      db1 = TarDB(dirname).open('r+')
      db2 = TarDB(dirname).open('r')
      self.assertRaises(FileLockError, lambda : TarDB(dirname).open('r+'))
      files = os.listdir(dirname)
      self.assertTrue('lock' not in files)
      self.assertTrue('lock.locked' in files)
      db1.close()
      db2.close()
      files = os.listdir(dirname)
      self.assertTrue('lock' in files)
      self.assertTrue('lock.locked' not in files)
      return
    
    def tearDown(self):
      for fname in os.listdir(dirname):
        if fname.startswith('.'): continue
        os.unlink(os.path.join(dirname, fname))
      return

  unittest.main()
