#!/usr/bin/env python
import sys, re, cmd
from __init__ import __version__


##  ShellLexer
##
class ShellLexer:

  def __init__(self):
    self.parse = self.parse_main
    self.quote = None
    self.arg = ''
    return

  def feed(self, s):
    self.tokens = []
    pos = 0
    while pos < len(s):
      (self.parse, pos) = self.parse(s, pos)
    return self.tokens

  def output(self):
    self.tokens.append(self.arg)
    self.arg = ''
    return

  END_MAIN = re.compile(r'\S')
  def parse_main(self, s, pos0):
    # search non-space.
    m = self.END_MAIN.search(s, pos0)
    if not m:
      return (self.parse_main, len(s))
    endpos = m.start(0)
    w = m.group(0)
    if w == '#':
      return (self.parse_comment, endpos+1)
    return (self.parse_arg, endpos)

  END_COMMENT = re.compile(r'\n')
  def parse_comment(self, s, pos0):
    m = self.END_COMMENT.search(s, pos0)
    if not m:
      return (self.parse_comment, len(s))
    endpos = m.start(0)
    return (self.parse_main, endpos)

  END_ARG = re.compile(r'[\\#\s"'+r"']")
  def parse_arg(self, s, pos0):
    m = self.END_ARG.search(s, pos0)
    if not m:
      self.arg += s[pos0:]
      return (self.parse_arg, len(s))
    endpos = m.start(0)
    w = m.group(0)
    self.arg += s[pos0:endpos]
    if w == '\\':
      self.prev_state = self.parse_arg
      return (self.parse_escape, endpos+1)
    if w == '"' or w == "'":
      self.quote = w
      return (self.parse_quote, endpos+1)
    # w is space
    self.output()
    return (self.parse_main, endpos)

  def parse_escape(self, s, pos0):
    self.arg += s[pos0]
    return (self.prev_state, pos0+1)

  END_QUOTE = re.compile(r'[\\"'+r"']")
  def parse_quote(self, s, pos0):
    m = self.END_QUOTE.search(s, pos0)
    if not m:
      self.arg += s[pos0:]
      return (self.parse_quote, len(s))
    w = m.group(0)
    endpos = m.start(0)
    self.arg += s[pos0:endpos]
    if w == '\\':
      self.prev_state = self.parse_quote
      return (self.parse_escape, endpos+1)
    elif w != self.quote:
      self.arg += w
      return (self.parse_quote, endpos+1)
    return (self.parse_arg, endpos+1)


##  ShalingShell
##
class ShalingShell(cmd.Cmd):
  
  prompt = 'Shaling> '
  intro = 'Welcome to Shaling version-%s.' % __version__
  
  def __init__(self, terminal, kernel):
    cmd.Cmd.__init__(self)
    self.terminal = terminal
    self.kernel = kernel
    return

  def execute(self, cmd, args):
    from config import COMMAND_ALIASES
    from kernel import ShowUsage, KernelError
    from interface import InterfaceCancelled, InterfaceAbort, InterfaceError
    from maildb import FileLockError
    from utils import log
    log('execute: %s %r' % (cmd, args))
    if cmd in COMMAND_ALIASES:
      ext = COMMAND_ALIASES[cmd].split(' ')
      cmd = ext[0]
      args[0:0] = ext[1:]
    try:
      f = 'cmd_'+cmd
      if hasattr(self.kernel, f):
        getattr(self.kernel, f)(args)
      else:
        self.terminal.warning('Unknown command: %s' % cmd)
    except ShowUsage, e:
      self.terminal.notice(getattr(self.kernel, f).__doc__)
    except KernelError, e:
      self.terminal.warning(str(e))
    except InterfaceError, e:
      self.terminal.warning(str(e))
    except InterfaceAbort, e:
      self.terminal.warning(str(e))
    except InterfaceCancelled, e:
      self.terminal.warning(str(e))
    except KeyboardInterrupt, e:
      self.terminal.warning('Interrupted.')
    except FileLockError, e:
      self.terminal.warning('Database in use: %s' % e)
    return

  def do_exit(self, _):
    return True
  do_quit = do_exit
  do_EOF = do_exit
  do_q = do_exit

  def default(self, s):
    s = self.terminal.from_terminal(s)
    args = ShellLexer().feed(s+'\n')
    if not args: return
    self.execute(args[0], args[1:])
    return


# main
def main(argv):
  import os
  import config
  from interface import InteractiveTerminalInterface, DumbTerminalInterface
  from kernel import Kernel
  try:
    os.ttyname(1)
    terminal = InteractiveTerminalInterface(sys.stdout, config.TERMINAL_CHARSET)
  except OSError:
    terminal = DumbTerminalInterface(sys.stdout, config.TERMINAL_CHARSET)
  kernel = Kernel(terminal)
  try:
    shell = ShalingShell(terminal, kernel)
    if len(argv) < 2:
      shell.cmdloop()
    else:
      (cmd, args) = (argv[1], argv[2:])
      shell.execute(cmd, [ terminal.from_terminal(x) for x in args ])
  finally:
    kernel.close()
  return

if __name__ == '__main__': sys.exit(main(sys.argv))
