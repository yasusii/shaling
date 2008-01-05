#!/usr/bin/env python
import sys, os, os.path, re
import config
from utils import unique_name


def charwidth(c):
  if u'\u2000' <= c: return 2
  return 1


##  Interface
##
class Interface:

  class InterfaceError(Exception): pass
  class Cancelled(InterfaceError): pass
  class Unauthorized(InterfaceError): pass
  class Aborted(InterfaceError): pass

  UNPRINTABLE = re.compile('')
  
  def __init__(self, charset):
    import codecs
    self.charset = charset
    self.encoder = codecs.getencoder(charset)
    self.decoder = codecs.getdecoder(charset)
    self.lines = 0
    self.cols = 0
    self.title = ''
    return

  def set_title(self, title):
    self.title = title
    return

  def get_username(self):
    return os.environ["USER"]

  def normal(self, s):
    return self.to_terminal(s)
  
  def color(self, color, s):
    return self.to_terminal(s)
  
  def to_terminal(self, us):
    return self.encoder(self.UNPRINTABLE.sub('', us), 'replace')[0]

  def from_terminal(self, s):
    return self.decoder(s, 'replace')[0]

  def length(self, us):
    return sum( charwidth(c) for c in us )

  def warning(self, s):
    self.display(self.color(config.COLOR4WARNING, s)+'\n')
    return

  def notice(self, s):
    self.display(self.color(config.COLOR4INFO, s)+'\n')
    return

  def display(self, s):
    raise NotImplementedError()

  def flush(self):
    raise NotImplementedError()

  def show_binary(self, data, mimetype):
    raise NotImplementedError()

  def open_pager(self):
    return self

  # "interactive" features.
  
  def prompt(self, question):
    raise Interface.InterfaceError('Unsupported on this terminal.')

  def wait_finish(self):
    raise Interface.InterfaceError('Unsupported on this terminal.')

  def save_file(self, data, filename, confirm=False):
    raise Interface.InterfaceError('Unsupported on this terminal.')

  def load_file(self, filename):
    raise Interface.InterfaceError('Unsupported on this terminal.')

  def edit_text(self, kernel, loc, data):
    raise Interface.InterfaceError('Unsupported on this terminal.')


##  DumbTerminalInterface
##
class DumbTerminalInterface(Interface):
  
  UNPRINTABLE = re.compile(ur'\033')
  
  def __init__(self, outfp, charset):
    Interface.__init__(self, charset)
    self.outfp = outfp
    return
  
  def display(self, s):
    assert isinstance(s, str)
    self.outfp.write(s)
    return
  
  def flush(self):
    self.outfp.flush()
    return
    
  def show_binary(self, data, mimetype):
    self.display(data)
    return

  def save_file(self, data, filename, confirm=False):
    if not confirm and filename == '-':
      self.outfp.write(data)
    else:
      raise Interface.InterfaceError('Unsupported on this terminal.')
      

##  ColorTerminalInterface
##
def _ansi(n): return '\033[%dm' % n
class ColorTerminalInterface(DumbTerminalInterface):

  RESET = '\033[m'
  ANSICOLOR = {
    'bold': _ansi(1),
    'italic': _ansi(2),
    'underline': _ansi(4),

    'black': _ansi(30),
    'red': _ansi(31),
    'green': _ansi(32),
    'yellow': _ansi(33),
    'blue': _ansi(34),
    'magenta': _ansi(35),
    'cyan': _ansi(36),
    'white': _ansi(37),
    'default': '',

    'bg_black': _ansi(40),
    'bg_red': _ansi(41),
    'bg_green': _ansi(42),
    'bg_yellow': _ansi(43),
    'bg_blue': _ansi(44),
    'bg_magenta': _ansi(45),
    'bg_cyan': _ansi(46),
    'bg_white': _ansi(47)
    }

  def color(self, color, s):
    return ''.join( self.ANSICOLOR.get(c,'') for c in color.split("+") )+self.to_terminal(s)+self.RESET
  
  
##  InteractiveTerminalInterface
##
class InteractiveTerminalInterface(ColorTerminalInterface):
  
  def __init__(self, outfp, charset):
    ColorTerminalInterface.__init__(self, outfp, charset)
    from termios import TIOCGWINSZ
    from fcntl import ioctl
    from struct import unpack
    fileno = outfp.fileno()
    os.ttyname(fileno)
    (self.lines, self.cols, _x, _y) = unpack('HHHH', ioctl(fileno, TIOCGWINSZ, '_'*8))
    self.x11display = os.environ.get("DISPLAY")
    return

  def show_binary(self, data, mimetype):
    import tempfile
    prog = config.MIME_HELPER.get(mimetype)
    if not prog:
      raise Interface.Aborted("Cannot display to a terminal: %s" % mimetype)
    fp = tempfile.NamedTemporaryFile(prefix=unique_name('view'), dir=config.TMP_DIR)
    fp.write(data)
    fp.flush()
    cmdline = prog % fp.name
    status = os.WEXITSTATUS(os.system(cmdline))
    fp.close()
    if status:
      raise Interface.Aborted("Viewer aborted: (%04x) %r" % (status, cmdline))
    return

  def prompt(self, question):
    self.display(question)
    self.flush()
    try:
      s = raw_input().strip()
    except (KeyboardInterrupt, EOFError):
      raise Interface.Cancelled('Cancelled.')
    return s

  def save_file(self, data, filename, confirm=False):
    if confirm:
      filename = self.prompt('Filename [%s] ' % filename) or filename
    try:
      if filename == '-':
        self.outfp.write(data)
      else:
        fp = file(filename, 'wb')
        fp.write(data)
        fp.close()
    except IOError, e:
      raise Interface.Aborted(e)
    return
      
  def load_file(self, filename):
    try:
      fp = file(filename, 'rb')
      data = fp.read()
      fp.close()
    except IOError, e:
      raise Interface.Aborted(e)
    return (os.path.basename(filename), data)

  # text: unicode string
  def edit_text(self, kernel, data, original=None):
    import stat
    def modtime(fname):
      return os.stat(fname)[stat.ST_MTIME]
    fname = os.path.join(config.TMP_DIR, unique_name('edit'))
    fp = file(fname, 'wb')
    fp.write(self.to_terminal(data))
    fp.close()
    t0 = modtime(fname)
    cmdline = config.EDITOR % fp.name
    status = os.WEXITSTATUS(os.system(cmdline))
    if config.CHECK_EDITOR_STATUS and status:
      raise Interface.Aborted("Editor aborted: (%04x) %r" % (status, cmdline))
    if modtime(fname) <= t0:
      raise Interface.Cancelled("Edit cancelled.")
    fp = file(fname, 'rb')
    data = self.from_terminal(fp.read())
    fp.close()
    kernel.submit_message(data, original)
    return

  def open_pager(self):
    return PagerTerminalInterface(self.outfp, self.charset)


##  PagerTerminalInterface
##
class PagerTerminalInterface(DumbTerminalInterface):

  def __init__(self, outfp, charset):
    from subprocess import Popen, STDOUT, PIPE
    try:
      self.child = Popen(config.DEFAULT_PAGER, stdin=PIPE, stdout=None, stderr=STDOUT)
    except OSError, e:
      raise Interface.Aborted(e)
    DumbTerminalInterface.__init__(self, self.child.stdin, charset)
    return
  
  def wait_finish(self):
    self.child.stdin.close()
    self.child.wait()
    return
  

##  CGIInterface (todo)
##
class CGIInterface(Interface):

  HTMLCOLOR = {
    'bold': ('<strong>', '</strong>'),
    'italic': ('<em>', '</em>'),
    'underline': ('<u>', '</u>'),

    'black': ('<font color="#000">', '</font>'),
    'red': ('<font color="#f00">', '</font>'),
    'green': ('<font color="#080">', '</font>'),
    'yellow': ('<font color="#880">', '</font>'),
    'blue': ('<font color="#00f">', '</font>'),
    'magenta': ('<font color="#c4c">', '</font>'),
    'cyan': ('<font color="#08c">', '</font>'),
    'white': ('<font color="#eee">', '</font>'),
    'default': ('', ''),

    'bg_black': ('<span style="background:#000">', '</span>'),
    'bg_red': ('<span style="background:#f00">', '</span>'),
    'bg_green': ('<span style="background:#080">', '</span>'),
    'bg_yellow': ('<span style="background:#880">', '</span>'),
    'bg_blue': ('<span style="background:#00f">', '</span>'),
    'bg_magenta': ('<span style="background:#c4c">', '</span>'),
    'bg_cyan': ('<span style="background:#08c">', '</span>'),
    'bg_white': ('<span style="background:#eee">', '</span>'),
    }
