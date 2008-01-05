#!/usr/bin/env python
import sys, re
import config
from utils import rmsp, get_msgids, get_numbers, \
     unicode_header, unicode_getall, unicode_getalladdrs, \
     encode_header, formataddr, formatdate, \
     get_message_part, get_body_text, enum_message_parts, msg_repr, make_msgid, \
     validate_message_structure, MessageStructureError


##  Internal functions
##

# get_message_color
def get_message_color(labels):
  for (c, color) in config.MESSAGE_COLOR:
    if c in labels:
      return color
  return ''

# get_label_names
def get_label_names(labels):
  return ', '.join( config.LABELS.get(c,c) for c in labels )

# show line with highlights
def highlight(term, selection, color, line):
  s = ''
  for (state,x) in selection.matched_range(line):
    if state:
      s += term.color(config.COLOR4HIGHLIGHT, x)
    else:
      s += term.color(color, x)
  return s


##  show_digest
##
WDAY = ['Sun','Mon','Tue','Wed','Thr','Fri','Sat']
def show_digest(term, idx, focused, doc, selection, labels):
  
  addrs = unicode_getalladdrs(doc.get_msg(), 'from')
  if addrs:
    (gecos, addr) = addrs[0]
  else:
    (gecos, addr) = ('???','???')

  # disptime - max 9chrs
  def disptime(t):
    import time
    if t == 0:
      return '      ???'
    d = int(time.time()) - t
    (yy0,mm0,dd0,hr0,mt0,sc0,day0,x,x) = time.localtime()
    (yy,mm,dd,hr,mt,sc,day,x,x) = time.localtime(t)
    if d < 0:
      return ' (future)'
    if d < 86400 and dd == dd0:
      return '%02d:%02d   .' % (hr, mt)
    if d < 86400*2 and dd == dd0-1:
      return '%02d:%02d  ..' % (hr, mt)
    if d < 86400*6:
      return '%02d:%02d %3s' % (hr, mt, WDAY[day])
    if d < 86400*365 and yy == yy0:
      return '%02d/%02d' % (mm, dd)
    return '%02d/%02d/%02d' % (yy%100, mm, dd)

  # truncate
  def trunc(n, s0):
    length = 0
    for (i,c) in enumerate(s0):
      length += term.length(c)
      if n <= length+2:
        return s0[:i+1]+'.'*(n-length)
    return s0

  # Creata a line bufffer.
  width = term.cols or 80
  line = '%3d:%s%9s  ' % (idx+1, ' +'[int(focused)], disptime(doc.get_mtime()))
  t1 = trunc(20, (gecos or addr).strip())
  line += t1+(' '*(20-term.length(t1)))
  if labels:
    line += ' [%s]' % (get_label_names(labels))
  line += ' '+trunc(40, doc.get_title())
  left = width-len(line)-4
  line += ' >> '+doc.get_snippet(selection, maxchars=left, maxcontext=left)
  line = trunc(width-4, line)

  # Output with highlights.
  color = get_message_color(labels)
  if focused:
    color += '+underline'
  term.display(highlight(term, selection, color, line)+'\n')
  return


##  show_message
##
MAX_PP_SIZE = 100000
def show_message(term, idx, doc, selection,
                 showall=False, needpager=False, headerlevel=0, verbose=True):

  # lines left
  if term.lines and not showall:
    lines = term.lines-5
  else:
    lines = sys.maxint

  # get mime info.
  def get_mime_info(i, mpart):
    s = ':%d [%s]' % (i+1, mpart.get_content_type())
    if mpart.get_content_charset():
      s += ' (%s)' % (mpart.get_content_charset())
    if mpart.get_filename():
      s += ' "%s"' % (mpart.get_filename())
    return s
  
  # get mime tree.
  def get_tree(msg):
    r = []
    for (i,mpart,level) in enum_message_parts(msg):
      if i == None:
        # Multipart object
        r.append('  '*level + '== %s' % mpart.get_content_type())
      else:
        r.append('  '*level + get_mime_info(i, mpart))
    return r

  # get_headers
  def get_headers(msg):
    if 2 <= headerlevel:
      return [ (h, unicode_header(v)) for (h,v) in msg.items() ]
    else:
      r = []
      for h in config.PRINTABLE_HEADERS:
        if h in msg:
          for v1 in unicode_getall(msg, h):
            r.append((h,v1))
      return r

  # get_header_color
  def get_header_color(x):
    return config.HEADER_COLOR.get(x.lower(), '')

  # fold_text
  def fold_text(term, text, indent2=''):
    from kinsoku import WORD_PAT
    if not term.cols:
      for line in text.splitlines():
        yield line
      return
    width = term.cols-4
    for line in text.splitlines():
      s = ''
      l0 = len(s)
      i = 0
      for m in WORD_PAT.finditer(line):
        w = m.group(0)
        l1 = term.length(w)
        if i and (width < l0+l1):
          yield s
          s = indent2
          l0 = len(s)
        s += w
        l0 += l1
        i = 1
      yield s
    return

  # show contents.
  def genlines(msg):
    charset = msg.get_content_charset(config.MESSAGE_CHARSET)
    # Show part(s).
    for (i,mpart,level) in enum_message_parts(msg, favor='text/plain'):
      if i != None and level:
        yield term.color(config.COLOR4MIMETREE, '--- '+get_mime_info(i, mpart))
      # Show the child headers.
      if headerlevel:
        for (h,v) in get_headers(mpart):
          s = '%s: %s' % (h, rmsp(v))
          color = config.HEADER_COLOR.get(h.lower(), '')
          for line in fold_text(term, s, indent2='    '):
            yield highlight(term, selection, color, line.rstrip())
        yield ''
      # Show the payload.
      if mpart.get_content_maintype() == 'text':
        r = u''
        text = get_body_text(mpart, charset)
        if MAX_PP_SIZE < len(text):
          for line in text.splitlines():
            yield term.normal(line)
        else:
          for line in fold_text(term, text):
            r += line+'\n'
          for line in highlight(term, selection, '', r).splitlines():
            yield line
      yield ''
    return

  # Show the headline.
  if needpager:
    term = term.open_pager()

  if verbose:
    labels = doc.get_labels()
    term.display(term.color(get_message_color(labels),
                            '*** %d: (%s) [%s]\n' % (idx+1, doc.loc, get_label_names(labels))))
  msg0 = doc.get_msg(0)
  trees = []
  if msg0.is_multipart():
    trees = get_tree(msg0)
    lines -= len(trees)

  empty = False
  for line in genlines(msg0):
    if lines < 0:
      term.warning('(continued)')
      break
    if not line.strip():
      if not empty:
        term.display('\n')
        empty = True
        lines -= 1
    else:
      term.display(line+'\n')
      empty = False
      lines -= line.count('\n')+1

  for line in trees:
    term.display(term.color(config.COLOR4MIMETREE, line)+'\n')

  if needpager:
    term.wait_finish()
  return


##  show_mime_part
##
def show_mime_part(term, msg, part, headerlevel=0, charset=None):
  mpart = get_message_part(msg, part)
  
  # Binary - might get InterfaceError.
  if mpart.get_content_type() != 'text/plain':
    content = mpart.get_payload(decode=True)
    term.show_binary(content, mpart.get_content_type())
    return

  # Headers are normally not displayed.
  if 2 <= headerlevel:
    for (h,v) in mpart.items():
      term.display(term.normal('%s: %s\n' % (h, rmsp(v))))
    term.display('\n')

  charset = msg.get_content_charset(charset or config.MESSAGE_CHARSET)
  term.display(term.normal(get_body_text(mpart, charset)))
  return


##  show_headers
##
def show_headers(term, doc, headers):
  msg = doc.get_msg()
  for (h, showname) in headers:
    if h.lower() == 'label':
      values = [doc.get_labels()]
    else:
      values = unicode_getall(msg, h)
    for v in values:
      v = rmsp(v)
      if showname:
        s = '%s: %s' % (h, v)
      else:
        s = v
      term.display(term.normal(s+'\n'))
  return

  
##  setup_template_string
##
def setup_template_string(fromaddr, addrs_to, addrs_cc, addrs_bcc, is_group, subject, labels,
                          headermsgs, includemsgs, forwardlocs):
  width = 80
  def fold_header(items, sep=', '):
    lines = []
    line = ''
    for x in items:
      if not line:
        line = x
      elif width < len(line)+len(sep)+len(x):
        lines.append(line+sep)
        line = '\t'+x
      else:
        line += sep+x
    if line:
      lines.append(line)
    return '\n'.join(lines)
  
  if forwardlocs:
    # Append 'Fwd:' if necessary.
    for m in headermsgs:
      # Take the subject of the first message.
      if not subject and m['subject']:
        subject = 'Fwd: '+unicode_header(m['subject'])
        break
  else:
    # Append 'Re:' if necessary.
    for m in headermsgs:
      # Take the subject if not set.
      if not subject and m['subject']:
        subject = unicode_header(m['subject'])
        if not re.match('\s*re:', subject, re.I):
          subject = 'Re: '+subject
        break
    # Add extra recipients.
    for m in headermsgs:
      if m['mail-reply-to']:
        addrs_to.extend(unicode_getall(m, 'mail-reply-to'))
      elif m['reply-to']:
        addrs_to.extend(unicode_getall(m, 'reply-to'))
      else:
        addrs_to.append(unicode_header(m['from']))
      if is_group:
        addrs_cc.extend( formataddr((n,a)) for (n,a) in
                         unicode_getalladdrs(m, 'to', 'cc') )
  #
  msgids = set()
  refids = set()
  if headermsgs:
    for msg in headermsgs:
      if msg['message-id']:
        msgids.add(msg['message-id'])
      if msg['references']:
        for x in msg.get_all('references'):
          refids.update(get_msgids(x))
  #
  lines = []
  lines.append('From: %s' % fromaddr)
  lines.append('To: %s' % fold_header(addrs_to))
  lines.append('Cc: %s' % fold_header(addrs_cc))
  lines.append('Bcc: %s' % fold_header(addrs_bcc))
  lines.append('Label: %s' % get_label_names(labels))
  lines.append('Subject: %s' % subject)
  if headermsgs:
    lines.append('References: %s' % fold_header(msgids.union(refids), ' '))
    lines.append('In-Reply-To: %s' % fold_header(msgids, ' '))
  if forwardlocs:
    lines.append('X-Forward-Msg: %s' % (', '.join(forwardlocs)))
  lines.append('')
  if includemsgs:
    for msg in includemsgs:
      from0 = unicode_header(msg['from']) or 'unknown person'
      date0 = unicode_header(msg['date']) or 'unknown date'
      subject0 = unicode_header(msg['subject']) or 'unknown subject'
      quoted_lines = []
      charset = msg.get_content_charset()
      for (i,mpart,level) in enum_message_parts(msg, favor='text/plain'):
        if mpart.get_content_maintype() == 'text':
          text = get_body_text(mpart, charset)
          quoted_lines.extend(text.splitlines())
      lines.extend(config.quotemsg(from0, date0, subject0, quoted_lines))

  return '\n'.join(lines)+'\n'


##  get_editable_string
##
def get_editable_string(msg, labels):
  mpart = msg
  if msg.is_multipart():
    mpart = get_message_part(msg, 1)
    if mpart.get_content_maintype() != 'text':
      raise MessageStructureError('The first part is not text??.')
  
  # Construct text.
  text = u''
  for h in config.EDITABLE_HEADERS:
    for v in unicode_getall(msg, h):
      text += u'%s: %s\n' % (h, rmsp(v))
  if labels:
    text += u'Label: %s\n' % get_label_names(labels)
  text += u'\n' + get_body_text(mpart, msg.get_content_charset())
  return text


##  create_message:
##  Creates a Message object from human-edited text data.
##  This should be very robust.
##
def create_message(corpus, data, msg0=None):
  from email import Charset, Parser, MIMEMessage
  if not isinstance(data, unicode):
    raise TypeError('data must be a unicode.')
  p = Parser.FeedParser()
  p.feed(data)
  msg1 = p.close()
  csmap = Charset.Charset(config.MESSAGE_CHARSET)
  attach_msgs = []
  # Re-encode the headers.
  headers = []
  labels = []
  for (k,v) in msg1.items():
    v = rmsp(v)
    if not v: continue
    kl = k.lower()
    if kl == 'x-forward-msg':
      attach_msgs.extend(get_numbers(v))
      continue
    if kl == 'label':
      labels = v.split(',')
      continue
    headers.append((k.encode('ascii', 'strict'), encode_header(v, csmap)))
  # Remove all the existing headers.
  for k in msg1.keys():
    del msg1[k]
  # Reattach the headers.
  for (k,v) in headers:
    msg1[k] = v
  # Change the body.
  data = msg1.get_payload(decode=False)
  try:
    # First try to encode with us-ascii.
    data.encode('ascii', 'strict')
    # Succeed.
    msg1.set_charset('ascii')
  except UnicodeError:
    # Re-encode the body.
    if not csmap.output_charset:
      csmap = Charset.Charset('utf-8')
    msg1.set_charset(str(csmap.output_charset))
    data = data.encode(str(csmap.output_codec), 'replace')
  msg1.set_payload(data)
  # Attach other messages (for forwarding).
  if attach_msgs:
    for loc in attach_msgs:
      p = Parser.FeedParser()
      p.feed(corpus.get_message(loc))
      msg1 = mime_add(msg1, MIMEMessage.MIMEMessage(p.close()))
  # Integrate other mime objects.
  if msg0 and msg0.is_multipart():
    for obj in msg0.get_payload()[1:]:
      msg1 = mime_add(msg1, obj)
  validate_message_structure(msg1)
  return (msg1, labels)


##  send_message
##
class MessageTransportError(IOError): pass

def send_message(msg, fromaddr, rcpts):
  import time, smtplib
  def getlogin():
    import os
    if hasattr(os, 'getlogin'):
      return os.getlogin()
    try:
      # WARNING: untested code!
      import _winreg
      key = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer')
      (name, _) = _winreg.QueryValueEx(key, 'Logon User Name')
      key.Close()
      return name
    except ImportError:
      return '???'
  # Assign a message-id if there isn't one.
  if not msg['message-id']:
    msg['Message-ID'] = make_msgid(getlogin())
  # Assign the date.
  msg['Date'] = formatdate(time.time(), localtime=True)
  # Now remove BCC and other redundant (empty) headers.
  del msg['bcc']
  for (k,v) in msg.items():
    if not rmsp(v):
      del msg[k]
  data = msg_repr(msg)
  # Send the message.
  smtp = smtplib.SMTP()
  (host, port, user, password, tls) = config.SMTP_HOST
  try:
    smtp.connect(host, port)
    if tls:
      smtp.ehlo()
      smtp.starttls()
      smtp.ehlo()
    if user and password:
      smtp.login(user, password)
    smtp.sendmail(fromaddr, rcpts, data)
  except smtplib.SMTPException, e:
    raise MessageTransportError(str(e))
  smtp.close()
  return data


#####################################################################
##
##  MIME tools
##

##  mime_new:
##  Creates a mime object from a file.
##  The mimetype is automatically determined by the file extension.
##
class EncodingError(ValueError): pass

def mime_new(fname, data, mimetype, charset):
  import mimetypes
  from email import Charset, Encoders
  from email import MIMEBase, MIMEText, MIMEImage, MIMEAudio
  # Try to guess the mimetype.
  if not mimetype:
    (mimetype, _) = mimetypes.guess_type(fname)
    if not mimetype:
      mimetype = 'text/plain'
  (maintype, subtype) = mimetype.split('/')
  # Create a MIME object.
  if maintype == 'text':                # Text
    # Try to determine the character encoding.
    charset = charset or config.TERMINAL_CHARSET
    # Re-encode the data in a specified encoding.
    csmap = Charset.Charset(charset)
    try:
      if csmap.input_codec:
        data = unicode(data, str(csmap.input_codec), 'replace')
      if csmap.output_codec:
        data = data.encode(str(csmap.output_codec), 'replace')
        charset = str(csmap.output_charset)
    except UnicodeError:
      raise EncodingError('Cannot encode with %s' % charset)
    obj = MIMEText.MIMEText(data, subtype, charset)
  elif maintype == 'image':             # Image
    obj = MIMEImage.MIMEImage(data, subtype)
  elif maintype == 'audio':             # Audio
    obj = MIMEAudio.MIMEAudio(data, subtype)
  else:                                 # Other
    obj = MIMEBase.MIMEBase(maintype, subtype)
    obj.set_payload(data)
    Encoders.encode_base64(obj)
  # Attach the MIME object to the original Message.
  obj.add_header('Content-Disposition', 'attachment', filename=fname)
  return obj


##  mime_add:
##  Append a MIME object to a Message.
##
UNTOUCHED_HEADERS = ('mime-version', 'content-type', 'content-transfer-encoding')
def mime_add(msg, obj):
  from email import MIMEMultipart, MIMEText
  validate_message_structure(msg)
  # First, assure it to be multipart.
  if msg.is_multipart():
    # This is already multipart.
    msg.attach(obj)
    return msg

  # If not, wrap the original Message with a new Multipart object.
  def move_headers(destmsg, srcmsg):
    # clear all headers
    for k in srcmsg.keys():
      if k.lower() not in UNTOUCHED_HEADERS:
        del destmsg[k]
    # append headers (with avoiding duplication)
    for (k,v) in srcmsg.items():
      if k.lower() not in UNTOUCHED_HEADERS:
        del srcmsg[k]
        destmsg[k] = v
    return
  # Create a Multipart message object.
  multi = MIMEMultipart.MIMEMultipart()
  # Move the old headers to the new one (EXCEPT mime-related headers).
  move_headers(multi, msg)
  multi.preamble = 'This message contains MIME objects.\n\n'
  # Sometime get_content_charset returns a unicode object!
  # We must coerce it to str.
  charset = msg.get_content_charset(config.MESSAGE_CHARSET)
  # Obtain the original content (which must be text) and reattach it.
  multi.attach(MIMEText.MIMEText(msg.get_payload(), _charset=str(charset)))
  # Attach the object.
  multi.attach(obj)
  return multi


##  mime_alter:
##  Replaces an existing MIME object in a Message with a new one.
##
def mime_alter(msg, part, obj):
  validate_message_structure(msg)
  # Get the old object to be replaced.
  mpart = get_message_part(msg, part)
  # Get the list of the children of the parent object.
  children = msg.get_payload()
  if mpart not in children:
    raise MessageStructureError('Cannot change that part.')
  i = children.index(mpart)
  if i == 0:
    raise MessageStructureError('Cannot change the first text part.')
  # Replace it with a new one.
  children[i] = obj
  return msg


##  mime_del:
##  Removes an existing MIME object in a Message.
##
def mime_del(msg, part):
  validate_message_structure(msg)
  # Get the old object to be removed.
  mpart = get_message_part(msg, part)
  # Get the list of the children of the parent object.
  children = msg.get_payload()
  if mpart not in children:
    raise MessageStructureError('Cannot remove that part.')
  i = children.index(mpart)
  if i == 0:
    raise MessageStructureError('Cannot remove the first text part.')
  # Remove it.
  children.remove(mpart)
  return msg
