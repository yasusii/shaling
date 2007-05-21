#!/usr/bin/env python
# aliases.py - list shell aliases
#

import sys
stderr = sys.stderr

def main(argv):
  import os, getopt
  from kernel import Kernel
  from config import COMMAND_ALIASES
  def usage():
    print 'usage: %s [-b|-c] [command_name]' % argv[0]
    return 100
  try:
    (opts, args) = getopt.getopt(argv[1:], 'bc')
  except getopt.GetoptError:
    return usage()
  cshell = os.environ.get('SHELL','sh').endswith('csh')
  for (k, v) in opts:
    if k == '-b': cshell = False
    elif k == '-c': cshell = True
  name = 'shaling'
  if args:
    name = args[0]
  cmds = [ k[4:] for k in dir(Kernel) if k.startswith('cmd_') ]
  cmds += [ k for k in COMMAND_ALIASES.iterkeys() ]
  for k in cmds:
    if cshell:
      print 'alias %s "%s %s";' % (k, name, k)
    else:
      print 'alias %s="%s %s";' % (k, name, k)
  return

if __name__ == '__main__': sys.exit(main(sys.argv))
