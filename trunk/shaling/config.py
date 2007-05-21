#!/usr/bin/env python
import sys, os, os.path

#######################################################
##
##  We first define "overridable" settings so that a user can
##  change their variables in .sharingrc.
##

# Default personal settings.
# (MUST BE OVERRIDDEN IN .sharingrc)
TOP_DIR = None
SPOOL = None
MY_FROM = 'unknown'
EDITOR = os.environ.get('EDITOR', 'vi')+' %s'
SMTP_HOST = ('localhost', 25, '', '', False)
MESSAGE_COLOR = []
LABELS = {}
ALIESES = {}
RULES = []

# Terminal charset
TERMINAL_CHARSET = 'euc-jp'
# Default message charset
MESSAGE_CHARSET = 'iso-2022-jp'

# Colors
COLOR4INFO = ''
COLOR4WARNING = 'white+bg_red'
COLOR4HIGHLIGHT = 'red+bold+underline'
COLOR4MIMETREE = 'cyan'

HEADER_COLOR = {
  'from': 'cyan',
  'subject': 'cyan',
}

PRINTABLE_HEADERS = [
  'Date',
  'From',
  'Subject',
  'To',
  'Cc',
]

EDITABLE_HEADERS = [
  'From',
  'To',
  'Cc',
  'Bcc',
  'Subject',
  'Label',
  'In-Reply-To',
  'References',
  'Reply-To',
  'X-Forward-Msg',
  ]

# External Applications
MIME_HELPER = {
  'application/pdf': 'xpdf %s',
  'application/postscript': 'gv %s',
  'text/html': 'lynx -force_html %s',
  'text/plain': 'less %s',
  'image/pdf': 'xpdf %s',
  'image/png': 'xloadimage %s',
  'image/gif': 'xloadimage %s',
  'image/jpeg': 'xloadimage %s',
  }
DEFAULT_PAGER = os.environ.get('PAGER', 'less')

# Command Aliases
COMMAND_ALIASES = {
  's': 'scan',
  'a': 'scan all',
  'all': 'scan all',
  'next': 'scan -N',
  'prev': 'scan -P',
  'first': 'scan -R',
  'draft': 'scan +draft',
  'back': 'sel 1',
  'm': 'show',
  'M': 'show -a',
  'n': 'show -N',
  'p': 'show -P',
  'forw': 'comp -F',
  'repl': 'comp -r',
  'sent': 'scan +sent',
  'rmm': 'label -R +deleted',
  }

# Address Aliases
ADDRESS_ALIASES = { }

# Quote a message
def quotemsg(from0, date0, subject0, lines):
  yield u'On %s, %s wrote:' % (date0, from0)
  for line in lines:
    yield '> '+line
  return

# Read user settings here.
try:
  _fname = os.path.join(os.environ['HOME'], '.shalingrc')
  _fp = file(_fname)
  eval(compile(_fp.read(), _fname, 'exec'))
  _fp.close()
  del _fp, _fname
except Exception, e:
  print >>sys.stderr, e
  print >>sys.stderr, 'shalinrc not found!'
  sys.exit(100)

#######################################################
##
##  The following settings are overriden on user settings.
##

# Pathnames
INBOX_DIR = TOP_DIR and os.path.join(TOP_DIR, 'inbox')
SELECTION_DIR = TOP_DIR and os.path.join(TOP_DIR, 'sel')
TMP_DIR = TOP_DIR and os.path.join(TOP_DIR, 'tmp')
LOG_FILE = TOP_DIR and os.path.join(TOP_DIR, 'log')

# Be verbose if the number of documents that are going
# to be indexed is more than this:
VERBOSE_INDEX_THRESHOLD = 10
MAX_SELECTIONS = 10
SCAN_DEFAULT_MSGS = 20

RESOLVE_ADDRESS_NADDRS = 10
RESOLVE_ADDRESS_RATIO = 0.5

# Predefined labels
LABEL4DELETED = '0'
LABEL4SENT = '1'
LABEL4DRAFT = '2'
LABEL4READ = '3'
LABEL4JUNK = '9'
FILTERED_LABELS = set([LABEL4SENT, LABEL4DELETED, LABEL4JUNK])

LABELS.update({
  LABEL4READ: 'read',
  LABEL4DRAFT: 'draft',
  LABEL4SENT: 'sent',
  LABEL4DELETED: 'deleted',
  LABEL4JUNK: 'junk',
  })

LABEL_NAME = dict( (name,c) for (c,name) in LABELS.iteritems() )

def str2label(s):
  s = str(s.strip())
  if len(s) == 1:
    return s
  if s in LABEL_NAME:
    return LABEL_NAME[s]
  raise KeyError('Unknown label: %r' % s)


# Additional colors
MESSAGE_COLOR = [ (str2label(label), color) for (label, color) in MESSAGE_COLOR ]
