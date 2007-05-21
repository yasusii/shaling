#!/usr/bin/env python
import sys, os, re, time, os.path
from config import str2label
from utils import get_message_date, unicode_header, unicode_getalladdrs
stderr = sys.stderr

class RuleSetSyntaxError(ValueError): pass
class PredicateSyntaxError(ValueError): pass
class MessagePOP3Error(IOError): pass

# LabelPredicate
def LabelPredicate(neg, name):
  if name == '*':
    if neg:
      return (lambda msg, labels: not labels)
    else:
      return (lambda msg, labels: labels)
  try:
    label = str2label(name)
  except KeyError:
    raise PredicateSyntaxError('Unknown label: %s' % name)
  if neg:
    return (lambda msg, labels: label not in labels)
  else:
    return (lambda msg, labels: label in labels)

# DatePredicate:
def DatePredicate(neg, s):
  if s == 'future':
    t0 = -sys.maxint
    t1 = -3600
  elif s == 'today':
    t0 = 0
    t1 = 86400
  if neg:
    def func1(msg, labels):
      t = time.time()-get_message_date(msg)
      return not (t0 <= t and t <= t1)
    return func1
  else:
    def func2(msg, labels):
      t = time.time()-get_message_date(msg)
      return t0 <= t and t <= t1
    return func2

# SubjectPredicate
def SubjectPredicate(neg, subj):
  pat = re.compile(subj, re.I)
  def func(msg, labels):
    s = unicode_header(msg['subject'])
    return s and pat.search(s)
  return func

# AddressPredicate
def AddressPredicate(neg, addr, *flds):
  # abc@def
  # abc@
  # abc
  # @def
  # @*def
  i = addr.index('@')
  user0 = str(addr[:i].lower())
  domain0 = str(addr[i+1:].lower())
  def func(msg, labels):
    for (_,a) in unicode_getalladdrs(msg, *flds):
      if '@' in a:
        i = a.index('@')
        (user,domain) = (a[:i].lower(), a[i+1:].lower())
      else:
        (user,domain) = (a, '?')
      if user0 and user0 != user: continue
      if (not domain0 or domain0 == domain or 
          domain0.startswith('*') and domain.endswith(domain0[1:])):
        return not neg
    return neg
  
  return func

# FromPredicate
def FromPredicate(neg, addr):
  return AddressPredicate(neg, addr, 'from')
# ToCcPredicate
def ToCcPredicate(neg, addr):
  return AddressPredicate(neg, addr, 'to', 'cc')
# StrictCcPredicate
def StrictCcPredicate(neg, addr):
  return AddressPredicate(neg, addr, 'cc')


# parse_predicate(s):
DICT = {
  'label:': LabelPredicate,
  'date:': DatePredicate,
  'from:': FromPredicate,
  'to:': ToCcPredicate,
  'rcpt:': ToCcPredicate,
  'cc:': StrictCcPredicate,
  'subj:': SubjectPredicate,
  'subject:': SubjectPredicate,
  }
PRED_PAT = re.compile(r'([-!])?\s*([-\w]+[:=])\s*(.+)')
def parse_predicate1(s):
  m = PRED_PAT.match(unicode(s.strip()))
  if not m:
    raise PredicateSyntaxError('Invalid predicate: %r' % s)
  (neg, f, arg) = m.groups()
  try:
    factory = DICT[f.lower()]
  except KeyError:
    raise PredicateSyntaxError('Unknown predicate: %r' % f)
  return factory(neg, arg)


##  RuleSet
##
class RuleSet:

  def __init__(self, args, labels=None):
    self.rules = []
    if labels:
      try:
        labels = ''.join( str2label(x.strip()) for x in labels )
      except KeyError, e:
        raise RuleSetSyntaxError('Unknown label: %s' % e)
      self.rules.append((lambda a,b:True, labels, False))
    for fname in args:
      self.read(fname)
    return

  def __repr__(self):
    return '<RuleSet rules=%r>' % (self.rules)

  def dump(self):
    for (pred, labels, terminate) in self.rules:
      print >>sys.stderr, pred, labels, terminate
    return

  # read_rules
  def read(self, fname):
    fp = file(fname)
    preds = []

    labelstr = ''
    for (lineno,line) in enumerate(fp.xreadlines()):
      def add1(preds, s):
        if s.endswith('!'):
          terminate = True
          assign = s[:-1].split(',')
        else:
          terminate = False
          assign = s.split(',')
        try:
          assign = ''.join( str2label(x.strip()) for x in assign )
        except KeyError, e:
          raise RuleSetSyntaxError('Unknown label: %s: line %d in %r' % (e, lineno, fname))
        if len(preds) == 1:
          pred = preds[0]
        else:
          # closure
          def conj(msg, labels):
            for p in preds:
              if not p(msg, labels): return False
            return True
          pred = conj
        return (pred, assign, terminate)

      # Strip comments.
      line = unicode(line[:line.find('#')].strip())
      if not line: continue
      if line.startswith('[') and line.endswith(']'):
        # Label spec.
        if labelstr and preds:
          self.rules.append(add1(preds, labelstr))
        labelstr = line[1:-1].strip()
        preds = []
      else:
        # Pattern spec.
        try:
          pred1 = parse_predicate1(line)
        except PredicateSyntaxError, e:
          raise RuleSetSyntaxError('Syntax Error: %s: line %d in %r.' % (e, lineno, fname))
        preds.append(pred1)
    if labelstr and preds:
      self.rules.append(add1(preds, labelstr))
    return self

  # apply_rules
  def apply_msg(self, msg, debug=0):
    labels = ''
    for (pred, label1, terminate) in self.rules:
      if pred(msg, labels):
        labels += label1
        if debug:
          print >>stderr, 'applied: %r: labels=%r' % (pred, labels)
        if terminate: break
    return ''.join(sorted(set(labels)))
    

##  MessageImporter
##
##  A MessageImporter is responsible for retrieving email messages
##  in a chronological order.
##
class MessageImporter:
  
  def is_empty(self):
    raise NotImplementedError
  
  def read_messages(self):
    raise NotImplementedError
  
  def finish(self):
    raise NotImplementedError
    
  def close(self, cleanup=False):
    raise NotImplementedError


##  MaildirImporter
##
class MaildirImporter(MessageImporter):

  def __init__(self, dirname, ruleset=None):
    if not os.path.isdir(dirname):
      raise IOError('Directory does not exist: %r' % dirname)
    self.dirname = dirname
    self.ruleset = ruleset
    self.msgs = []
    return

  def __repr__(self):
    return '<MaildirImporter: dirname=%r, ruleset=%r, msgs=%d>' % (self.dirname, self.ruleset, len(self.msgs))

  def is_empty(self):
    return not self.msgs

  def read_messages(self):
    from email import Parser
    for fname in os.listdir(self.dirname):
      if fname.startswith('.'): continue
      fname = os.path.join(self.dirname, fname)
      fp = file(fname, 'rb')
      p = Parser.FeedParser()
      for line in fp:
        p.feed(line)
        if not line.strip(): break
      msg = p.close()
      if self.ruleset:
        labels = self.ruleset.apply_msg(msg)
      else:
        labels = []
      self.msgs.append((fname, labels, get_message_date(msg)))
    return

  def finish(self):
    self.msgs.sort(key=lambda (fname,label,mtime): mtime)
    for (loc, labels, mtime) in self.msgs:
      fp = file(loc)
      data = fp.read()
      fp.close()
      yield (data, labels, mtime)
    return

  def close(self, cleanup=False):
    if cleanup:
      for (loc, labels, mtime) in self.msgs:
        os.unlink(loc)
    return


##  MboxImporter
##
class MboxImporter(MessageImporter):
  
  def __init__(self, fname, ruleset=None):
    self.fname = fname
    self.ruleset = ruleset
    return

  def __repr__(self):
    return '<MboxImporter: fname=%r, ruleset=%r>' % (self.fname, self.ruleset)

  def is_empty(self):
    return not os.path.isfile(self.fname)
  
  def read_messages(self):
    return
  
  def finish(self):
    from mailbox import PortableUnixMailbox
    from email import Parser
    try:
      fp = file(self.fname, 'rb')
    except IOError:
      return
    for data in PortableUnixMailbox(fp, lambda msgfp: msgfp.read()):
      p = Parser.FeedParser()
      p.feed(data)
      msg = p.close()
      if self.ruleset:
        labels = self.ruleset.apply_msg(msg)
      else:
        labels = []
      yield (data, labels, get_message_date(msg))
    fp.close()
    return
  
  def close(self, cleanup=False):
    if cleanup:
      try:
        os.unlink(self.fname)
      except OSError:
        pass
    return

 
##  POP3Importer
##  Contributed by Yasusi Iwata.
##
class POP3Importer(MessageImporter):

  def __init__(self, hostname, username, password, port=110, ruleset=None):
    self.hostname = hostname
    self.username = username
    self.password = password
    self.port = port
    self.ruleset = ruleset
    self.msgcount = 0
    self.server = None   
    return

  def __repr__(self):
    return '<POP3Importer: hostname=%r, username=%r, password=%r, port=%r, ruleset=%r, msgcount=%r, server=%r>' % (self.hostname, self.username, self.password, self.port, self.ruleset, self.msgcount, self.server)

  def is_empty(self):
    return not self.msgcount
  
  def read_messages(self):
    import poplib
    try:
      self.server = poplib.POP3(self.hostname, self.port)
      if self.server.timestamp.match(self.server.welcome):
        # APOP login
        self.server.apop(self.username, self.password)
      else:
        # plain text login
        self.server.user(self.username)
        self.server.pass_(self.password)
      self.msgcount = len(self.server.list()[1])
    except poplib.error_proto, e:
      raise MessagePOP3Error(str(e))
    return
  
  def finish(self):
    from email import Parser
    for i in xrange(self.msgcount):
      try:
        data = self.server.retr(i+1)[1]
      except poplib.error_proto, e:
        raise MessagePOP3Error(str(e))
      data = '\r\n'.join(data)
      p = Parser.FeedParser()
      p.feed(data)
      msg = p.close()
      if self.ruleset:
        labels = self.ruleset.apply_msg(msg)
      else:
        labels = []
      yield (data, labels, get_message_date(msg))
    return
  
  def close(self, cleanup=False):
    if self.server:
      if cleanup:
        for i in xrange(self.msgcount):
          self.server.dele(i+1)
      self.server.quit()
      self.server = None
      self.msgcount = 0
    return

##  POP3SSLImporter
##
class POP3SSLImporter(POP3Importer):

  def __init__(self, hostname, username, password, port='995', ruleset=None):
    POP3Importer.__init__(self, hostname, username, password, port, ruleset)

  def read_messages(self):
    import poplib
    try:
      self.server = poplib.POP3_SSL(self.hostname, self.port)
      self.server.user(self.username)
      self.server.pass_(self.password)
      self.msgcount = len(self.server.list()[1])
    except poplib.error_proto, e:
      raise MessagePOP3Error(str(e))
    return

def CreateMessageImporter(spool, ruleset=None):
  if spool.endswith('/'):
    return MaildirImporter(spool, ruleset)
  elif spool.startswith('pop3:'):
    hostname, username, password = spool[5:].split(',')
    return POP3Importer(hostname, username, password, ruleset=ruleset)
  elif spool.startswith('pop3ssl:'):
    hostname, username, password = spool[8:].split(',')
    return POP3SSLImporter(hostname, username, password, ruleset=ruleset)
  else:
    return MboxImporter(spool, ruleset)
