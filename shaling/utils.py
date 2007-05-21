#!/usr/bin/env python
import sys, os, re, time
import config
from email import Utils, Header, Charset
stderr = sys.stderr

# ms932 hack
Charset.add_codec('shift_jis', 'ms932')


##  String utilities
##

# get_msgids
MSGID_PAT = re.compile(r'<[^>]+>')
def get_msgids(x):
  return [ m.group(0) for m in MSGID_PAT.finditer(x or '') ]

# get_numbers
NUM_PAT = re.compile(r'\d+')
def get_numbers(x):
  return [ int(m.group(0)) for m in NUM_PAT.finditer(x) ]

# rmsp
RMSP_PAT = re.compile(r'\s+', re.UNICODE)
def rmsp(x):
  return RMSP_PAT.sub(' ', x.strip())

# Remove unsafe characters.
UNSAFE_CHARS = re.compile(r'[^-a-zA-Z0-9_.]')
def escape_unsafe_chars(fname):
  return UNSAFE_CHARS.sub(lambda m: '%%%02x' % ord(m.group(0)), fname)

# Unique name for tempfile.
def unique_name(basename):
  import socket
  return '%s.%s.%x.%x' % (basename, socket.gethostname(), time.time(), os.getpid())


##  Message object utilities
##
class MessageError(ValueError): pass
class MessagePartNotFoundError(MessageError): pass
class MessageStructureError(MessageError): pass
class MessageFormatError(MessageError): pass


# get_message_part (base:1)
def get_message_part(msg, n):
  i = 0
  for m1 in msg.walk():
    if m1.is_multipart(): continue
    i += 1
    if n == i: return m1
  raise MessagePartNotFoundError(msg, n)

# get_message_date
def get_message_date(msg):
  try:
    return int(Utils.mktime_tz(Utils.parsedate_tz(msg['date'])))
  except:
    return 0

# returns [(mpart, level, idx), ...]
def enum_message_parts(msg, favor=None):
  r = []
  def walk1(i, mpart, level):
    if mpart.is_multipart():
      r.append( (None, mpart, level) )
      children = mpart.get_payload()
      if mpart.get_content_subtype() == 'alternative' and favor:
        children = [ m for m in children if m.get_content_type() == favor ] or children
      for m in children:
        i = walk1(i, m, level+1)
    else:
      r.append( (i, mpart, level) )
      i += 1
    return i
  walk1(0, msg, 0)
  return r

# validate_message_structure
def validate_message_structure(msg):
  if not msg.is_multipart():
    t = msg.get_content_maintype()
    if t != 'text':
      raise MessageStructureError('The entire non-multipart message must be a text (%r).' % t)
  else:
    children = msg.get_payload()
    if len(children) < 1:
      raise MessageStructureError('Empty multipart.')
    t = children[0].get_content_maintype()
    if t != 'text':
      raise MessageStructureError('The first part must be a text (%r).' % t)
  return

# get_body_text
def get_body_text(mpart, default_charset):
  text = mpart.get_payload(decode=True) or ''
  charset = mpart.get_content_charset(default_charset)
  try:
    text = text.decode(charset or 'ascii', 'replace')
  except LookupError:
    text = text.decode('ascii', 'replace')
  if mpart.get_content_type() == 'text/html':
    from fooling.htmlripper import HTMLRipper
    text = '\n'.join( rmsp(s) for (_,s) in HTMLRipper().feedunicode(text) )
  return text

# msg_repr
def msg_repr(msg):
  from email import Generator
  try:
    import cStringIO as StringIO
  except ImportError:
    import StringIO as StringIO
  fp = StringIO.StringIO()
  Generator.Generator(fp, mangle_from_=False).flatten(msg)
  return fp.getvalue()

make_msgid = Utils.make_msgid
formataddr = Utils.formataddr
formatdate = Utils.formatdate

##  Header utilities
##

# decode RFC header
decode_header = Header.decode_header
def unicode_header(s):
  try:
    return u' '.join( unicode(s1,t1 or 'ascii','replace') for (s1,t1) in decode_header(s) )
  except LookupError:
    return u' '.join( unicode(s1,'ascii','replace') for (s1,t1) in decode_header(s) )
  except Header.HeaderParseError:
    return unicode(s, 'ascii', 'replace')

# getall
def unicode_getall(msg, h):
  return [ unicode_header(s) for s in msg.get_all(h, []) ]

def unicode_getaddrs(v):
  return Utils.getaddresses([ rmsp(unicode_header(v)) ])

def unicode_getalladdrs(msg, *flds):
  values = []
  for f in flds:
    values += unicode_getall(msg, f)
  return Utils.getaddresses( rmsp(v) for v in values )

def encode_header(v, csmap):
  h = Header.Header()
  for t in v.split(' '):
    try:
      # Check the header is ascii encodable.
      t.encode('ascii', 'strict')
      # If so, this is not encoded.
      h.append(t)
    except UnicodeError:
      h.append(t, str(csmap.output_charset))
  return h.encode().encode('ascii', 'strict')

def validate_message_headers(msg, check_subject):
  # Check the validity of the message.
  if check_subject and not msg['subject']:
    raise MessageFormatError('No Subject.')
  # Get all the recipient addresses.
  rcpts = [ a for (n,a) in unicode_getalladdrs(msg, 'to', 'cc', 'bcc') ]
  if not rcpts:
    raise MessageFormatError('No Recipient.')
  if not msg['from']:
    raise MessageFormatError('No From.')
  (_, fromaddr) = Utils.parseaddr(msg['from'])
  for addr in [fromaddr]+rcpts:
    if '@' not in addr:
      raise MessageFormatError('Invalid address: %s' % addr)
    try:
      addr.encode('ascii', 'strict')
    except UnicodeError:
      raise MessageFormatError('Non-ascii address: %r' % addr)
  fromaddr = str(fromaddr)
  rcpts = map(str, rcpts)
  return (fromaddr, rcpts)


##  Logging
##
LOG_FP = config.LOG_FILE and file(config.LOG_FILE, 'a')
def log(x):
  if not LOG_FP: return
  if not isinstance(x, str):
    x = repr(x)
  LOG_FP.write('%s: %d: %s\n' % (time.asctime(), os.getpid(), x))
  LOG_FP.flush()
  return
