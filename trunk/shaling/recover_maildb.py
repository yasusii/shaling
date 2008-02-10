#!/usr/bin/env python
import sys
from tarfile import TarInfo, BLOCKSIZE
from os.path import basename
stdout = sys.stdout
stderr = sys.stderr

def generate_catalog(args, recsize, out=stdout, verbose=0):
  out.write(''.join( str(i % 10) for i in xrange(1,recsize) ) + '\n')
  args.sort()
  recno = 0
  errno = 0
  for fname in args:
    if verbose:
      print >>stderr, 'reading: %r...' % fname
    name = basename(fname)
    if name.endswith('.tar'):
      name = name[:-4]
    if recsize < (len(name) + 9):
      print >>stderr, 'tarfile %r does not fit to the catalog record size.' % fname
      errno = 1
      continue
    name += ' '*(recsize-9-len(name))
    missing = 'x'*(recsize-1)
    tarfp = file(fname, 'rb')
    while 1:
      offset = tarfp.tell()
      buf = tarfp.read(BLOCKSIZE)
      if len(buf) != BLOCKSIZE: break
      try:
        info = TarInfo.frombuf(buf)
      except ValueError:
        print >>stderr, '%r: tar record corrputed at offset=%d' % (fname, offset)
        errno = 1
        break
      size = ((info.size + BLOCKSIZE-1) / BLOCKSIZE) * BLOCKSIZE
      data = tarfp.read(size)
      if len(data) != size:
        print >>stderr, '%r: premature eof at offset=%d' % (fname, offset)
        errno = 1
        break
      recid = int(info.name[:8], 16)
      if recid < recno:
        print >>stderr, '%r: duplicated recno: %d at offset=%d' % (fname, recid, offset)
        errno = 1
        continue
      if recno < recid:
        print >>stderr, '%r: missing recno: %d-%d' % (fname, recno, recid-1)
        for _ in xrange(recno, recid):
          out.write(missing+'\n')
        recno = recid
        errno = 1
      out.write('%08x%s\n' % (offset, name))
      recno += 1
    tarfp.close()
  return errno


def generate_labelidx(args, prefix, verbose=0):
  import re, struct
  pat = re.compile(r'([0-9a-f]{8})\.(.*)')
  valid_labels = re.compile(r'[0-9a-zA-Z]')
  labelmap = {}
  errno = 0
  for fname in args:
    if verbose:
      print >>stderr, 'reading: %r...' % fname
    tarfp = file(fname, 'rb')
    while 1:
      offset = tarfp.tell()
      buf = tarfp.read(BLOCKSIZE)
      if len(buf) != BLOCKSIZE: break
      try:
        info = TarInfo.frombuf(buf)
      except ValueError:
        print >>stderr, '%r: tar record corrputed at offset=%d' % (fname, offset)
        errno = 1
        break
      size = ((info.size + BLOCKSIZE-1) / BLOCKSIZE) * BLOCKSIZE
      data = tarfp.read(size)
      if len(data) != size:
        print >>stderr, '%r: premature eof at offset=%d' % (fname, offset)
        errno = 1
        break
      m = pat.match(info.name)
      if not m:
        print >>stderr, '%r: invalid name %r at offset=%d' % (fname, info.name, offset)
        errno = 1
        continue
      (recno, labels) = m.groups()
      recno = int(recno, 16)
      for label in valid_labels.findall(labels):
        if label not in labelmap: labelmap[label] = []
        labelmap[label].append(recno)
    tarfp.close()
  #
  for (label,recnos) in labelmap.iteritems():
    fname = '%s_%02x' % (prefix, ord(label))
    recnos.sort(reverse=True)
    data = struct.pack('>%di' % len(recnos), *recnos)
    fp = file(fname, 'wb')
    fp.write(data)
    fp.close()
  return errno

def main(argv):
  import getopt
  def usage():
    print 'usage: %s [-v] {-C [-n recsize] | -L [-o prefix]} [file ...]' % argv[0]
    return 100
  try:
    (opts, args) = getopt.getopt(argv[1:], 'CLn:')
  except getopt.GetoptError:
    return usage()
  recsize = 16
  prefix = './label'
  mode = 0
  verbose = 0
  for (k,v) in opts:
    if k == '-v': verbose += 1
    elif k == '-C': mode = 1
    elif k == '-L': mode = 2
    elif k == '-n': recsize = int(v)
    elif k == '-o': prefix = v
  if not mode: return usage()
  if mode == 1:
    return generate_catalog(args, recsize, verbose=verbose)
  elif mode == 2:
    return generate_labelidx(args, prefix, verbose=verbose)
  return

if __name__ == '__main__': sys.exit(main(sys.argv))
