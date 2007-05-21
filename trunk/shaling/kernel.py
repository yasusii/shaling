#!/usr/bin/env python
import sys, os, os.path, re
try:
  import cPickle as pickle
except ImportError:
  import pickle
import config, message
from getopt import getopt, GetoptError
from utils import rmsp, unique_name, escape_unsafe_chars, unicode_getalladdrs, unicode_getaddrs, \
     formataddr, msg_repr, get_msgids, get_message_part, MessagePartNotFoundError, \
     validate_message_headers, MessageFormatError
from maildb import MailCorpus, LabelPass, LabelBlock, DEFAULT_FILTER, DEFAULT_FILTER_WITH_SENT
from fooling.selection import EMailPredicate, Selection, DummySelection, SearchTimeout


##  KernelError
##
class ShowUsage(RuntimeError): pass
class KernelError(RuntimeError): pass
class KernelSyntaxError(KernelError): pass
class KernelValueError(KernelError): pass


def safeint(x):
  try:
    return int(x)
  except ValueError:
    raise KernelValueError('Invalid argument (integer expected): %r' % x)


##  MailSelection
##
class WindowMixin:
  
  def __init__(self, window_size):
    self.window_size = window_size
    self.window_start = 0
    self.window_end = 0
    self.focus = 0
    self.finished = 0
    self.nresults = 0
    self.name = None
    return

  def remove(self):
    if self.name:
      fname = os.path.join(config.SELECTION_DIR, 'sel.'+self.name)
      try:
        os.unlink(fname)
      except OSError:
        pass
    return

  def save(self, seqno):
    import time
    self.remove()
    self.name = '%d.%d' % (time.time(), seqno)
    fname = os.path.join(config.SELECTION_DIR, 'sel.'+self.name)
    fp = file(fname, 'wb')
    pickle.dump(self, fp, protocol=2)
    fp.close()
    return

  def slide_window(self, rel, window_size):
    self.window_size = window_size
    if rel == -2:
      # first window
      self.window_start = 0
    elif rel == -1:
      # previous window
      self.window_start = max(0, self.window_start - self.window_size)
    elif rel == 0:
      # current window
      pass
    else:
      # next window
      self.window_start = self.window_end + 1
    return

  def list_messages(self, terminal, verbose=1):
    if 0 < verbose:
      terminal.notice('Selection: %s' % self.description())
    n = 0
    self.focus = max(self.focus, self.window_start)
    try:
      for (i,doc) in self.iter(self.window_start):
        n += 1
        if n == self.window_size:
          self.focus = min(self.focus, i)
        if 0 <= verbose:
          message.show_digest(terminal, i, i == self.focus, doc, self, doc.labels)
        else:
          terminal.notice(str(i))
        self.window_end = i
        if n == self.window_size: break
      if 0 < verbose and n:
        (self.finished, self.nresults) = self.status()
        results = '%d-%d of ' % (self.window_start+1, self.window_end+1)
        if not self.finished:
          results += 'about '
        results += '%d messages.' % self.nresults
        terminal.display(results+'\n')
    except KeyboardInterrupt:
      pass
    return n
  
  RANGE_PAT1 = re.compile(r'(\d+):(\d+)')
  RANGE_PAT2 = re.compile(r'(\d+)-(\d+)')
  def get_messages(self, args, rel=0):
    idxs = []
    other_args = []
    for arg in args:
      if arg.isdigit():                 # 'n'
        focus = max(0, int(arg)-1)
        idxs.append( (focus, None) )
      elif arg == '.':                  # '.'
        focus = max(0, self.focus+rel)
        idxs.append( (focus, None) )
      elif arg.startswith(':') and arg[1:].isdigit():  # ':m'
        focus = self.focus
        idxs.append( (focus, int(arg[1:])) )
      elif self.RANGE_PAT1.match(arg):  # 'n:m'
        (n,m) = map(int, self.RANGE_PAT1.match(arg).groups())
        n = max(0, n-1)
        focus = n
        idxs.append( (n, m) )
      elif self.RANGE_PAT2.match(arg):  # 's-e'
        (s,e) = [ max(0, int(x)-1) for x in self.RANGE_PAT2.match(arg).groups() ]
        focus = e
        idxs.extend( (i, None) for i in range(s, e+1) )
      else:                             # otherwise
        other_args.append(arg)
    docs = []
    if idxs:
      for (i,p) in idxs:
        try:
          docs.append((i, self.get(i), p))
        except IndexError:
          raise KernelValueError('Invalid index: %d' % (i+1))
      self.focus = focus
      if self.focus < self.window_start or self.window_end < self.focus:
        self.window_start = self.window_end = self.focus
    return (docs, other_args)

class MailSelection(Selection, WindowMixin):

  def __init__(self, corpus, term_preds, doc_preds=None, ext_preds=None, disjunctive=False, window_size=0):
    # safe=False : we don't want to skip "future" messages.
    WindowMixin.__init__(self, window_size)
    Selection.__init__(self, corpus, term_preds, doc_preds, safe=False, disjunctive=disjunctive)
    self.ext_preds = ext_preds
    return

  def estimation(self):
    if self.finished:
      return '%d messages' % self.nresults
    else:
      return 'about %d messages' % self.nresults

  def description(self):
    r = [ '"%s"' % rmsp(pred.q) for pred in self.get_preds() ]
    if self.ext_preds:
      r.extend(self.ext_preds)
    return ' '.join(r) or 'all'

class DummyMailSelection(DummySelection, WindowMixin):

  def __init__(self, descr, corpus, locs, window_size=0):
    # safe=False : we don't want to skip "future" messages.
    WindowMixin.__init__(self, window_size)
    DummySelection.__init__(self, corpus, locs)
    self.descr = descr
    return

  def estimation(self):
    return '%d messages' % len(self.locs)

  def description(self):
    return self.descr


##  Kernel
##
class Kernel:

  def __init__(self, terminal):
    if not config.TOP_DIR:
      raise KernelError('TOP_DIR is not configured!')
    self.terminal = terminal
    self.corpus = {}
    self.current_selection = None
    self.selection_seqno = 0
    return

  def save_current_selection(self):
    if self.current_selection:  # do not save an empty selection.
      self.current_selection.save(self.selection_seqno)
      self.selection_seqno += 1
      selections = self.list_selections()
      # Delete old selections.
      for fname in selections[config.MAX_SELECTIONS:]:
        try:
          os.unlink(fname)
        except OSError:
          pass
    return

  def list_selections(self):
    selections = [ fname for fname in os.listdir(config.SELECTION_DIR) if fname.startswith('sel.') ]
    selections.sort(reverse=True)
    return [ os.path.join(config.SELECTION_DIR, fname) for fname in selections ] 

  def get_selection(self, i=0):
    if i == 0 and self.current_selection != None:
      return self.current_selection
    selections = self.list_selections()
    if not selections:
      raise KernelValueError('No message is selected.')
    self.save_current_selection()
    fp = file(selections[i], 'rb')
    MailCorpus.register_corpus_handler(self.get_corpus)
    self.current_selection = pickle.load(fp)
    fp.close()
    return self.current_selection

  def set_selection(self, selection):
    assert selection
    if selection != self.current_selection: 
      self.save_current_selection()
      self.current_selection = selection
    return

  def remove_selection(self):
    if self.current_selection:
      self.current_selection.remove()
    self.current_selection = None
    return

  def notice_indexing(self, n):
    if config.VERBOSE_INDEX_THRESHOLD < n:
      self.terminal.notice('Indexing %d docs...' % n)
    return

  def close(self):
    self.save_current_selection()
    for corpus in self.corpus.itervalues():
      corpus.close(self.notice_indexing)
    return

  def get_corpus(self, dirname=config.INBOX_DIR):
    if dirname in self.corpus:
      corpus = self.corpus[dirname]
    else:
      corpus = MailCorpus(dirname)
      self.corpus[dirname] = corpus
      corpus.open()
    return corpus

  # get_messages
  def get_messages(self, args, rel=0):
    return self.get_selection().get_messages(args, rel)

  # Show temporary selection.
  def select_tmp(self, descr, corpus, locs, verbose=0):
    locs = [ loc for loc in locs if 0 <= DEFAULT_FILTER(loc, corpus) ]
    self.set_selection(DummyMailSelection(descr, corpus, locs, window_size=len(locs)))
    self.get_selection().list_messages(self.terminal, verbose)
    return

  # Add text to the database.
  # This part should be robust enough. Don't throw any execption.
  # but this might cause FileLockError. In that case, the edit will be lost...
  def submit_message(self, data, original=None):
    corpus = self.get_corpus()
    corpus.set_writable()
    if not original:
      (msg, labels) = message.create_message(corpus, data)
    else:
      doc = corpus.get_doc(original)
      (msg, labels) = message.create_message(corpus, data, doc.get_msg(0))
      corpus.set_deleted_label(original)

    # Get labels.
    # We silently ignore unknown labels, because we shouldn't throw any exception.
    def get_labels(labels):
      for name in labels:
        try:
          c = config.str2label(name)
          yield c
        except KeyError:
          pass
      return
    labels = set(get_labels(labels))
    
    # Resolve addresses.
    # We silently ignore unresolved addresses.
    def resolve1((user,addr)):
      if user: return formataddr((user, addr))
      if addr in config.ADDRESS_ALIASES: return config.ADDRESS_ALIASES[addr]
      r = self.resolve_address(addr)
      if not r: return addr
      (n, x) = r[0]
      threshold = int(len(r)*config.RESOLVE_ADDRESS_RATIO + 0.5)
      if n <= threshold: return addr
      return x
    alt_headers = []
    for (k,v) in msg.items():
      if k.lower() in ('to', 'cc', 'bcc'):
        v = ', '.join( resolve1(addr) for addr in unicode_getaddrs(v) )
        alt_headers.append((k,v))
    for (k,_) in alt_headers:
      del msg[k]
    for (k,v) in alt_headers:
      msg[k] = v
    
    loc = corpus.add_message(msg_repr(msg), labels)
    corpus.flush(self.notice_indexing)
    # show the edited message.
    self.select_tmp('edit', corpus, [loc])
    return loc
  
  # resolve_address
  def resolve_address(self, addr):
    r = {}
    pat = re.compile(re.escape(addr), re.I | re.UNICODE)
    preds = [ EMailPredicate('addr:'+addr) ]
    corpus = self.get_corpus()
    try:
      selection = Selection(corpus, preds, doc_preds=[ DEFAULT_FILTER_WITH_SENT ], safe=False)
      for (i,doc) in selection.iter(timeout=1):
        msg = doc.get_msg()
        for (n, a) in unicode_getalladdrs(msg, 'from', 'to', 'cc'):
          x = formataddr((n, a))
          if not pat.search(x): continue
          a = a.lower()
          if a not in r:
            r[a] = (1, x)
          else:
            (n, x) = r[a]
            r[a] = (n+1, x)
        if config.RESOLVE_ADDRESS_NADDRS <= (i+1): break
    except SearchTimeout:
      pass
    # ambiguous?
    return sorted(r.itervalues(), reverse=True)

  # cmd_scan
  def cmd_scan(self, args):
    'usage: scan [-q] [-n nmsgs] [-S selection] [-a)ll] [-P)rev|-N)ext|-R)eset] [-O)r] predicates ...'
    try:
      (opts, args) = getopt(args, 'qn:S:aPNRO')
    except GetoptError:
      raise ShowUsage()
    # Get command line options.
    verbose = 1
    nmsgs = config.SCAN_DEFAULT_MSGS
    selection = 0
    disjunctive = False
    search_all = False
    rel = 0
    for (k,v) in opts:
      if k == '-q': verbose -= 1
      elif k == '-n': nmsgs = safeint(v)
      elif k == '-S': selection = safeint(v)
      elif k == '-a':
        search_all = True
        if not args: args = ['all']
      elif k == '-N': rel = 1
      elif k == '-P': rel = -1
      elif k == '-R': rel = -2
      elif k == '-O': disjunctive = True

    if not args:
      # No query - use the previous result.
      # (argument omitted and the previous selection is saved.)
      selection = self.get_selection(selection)
      selection.slide_window(rel, nmsgs)
      corpus = selection.get_corpus()
    else:
      corpus = self.get_corpus()
      # Query specified.
      # Create an appropriate selection.
      if args == ['all'] or args == ['a']:
        # "scan all"
        if search_all:
          selection = MailSelection(corpus, [], window_size=nmsgs)
        else:
          selection = MailSelection(corpus, [], doc_preds=[ DEFAULT_FILTER ], window_size=nmsgs)
      else:
        # "scan something"
        term_preds = []
        label_preds = []
        label_pass = set()
        if search_all:
          label_block = set()
        else:
          label_block = config.FILTERED_LABELS.copy()
        for kw in args:
          if kw and kw[0] not in '+-!': 
            term_preds.append(EMailPredicate(kw))
            continue
          if kw.startswith('!') or kw.startswith('-'):
            kw = kw[1:]
            neg = True
          elif kw.startswith('+-') or  kw.startswith('+!'):
            kw = kw[2:]
            neg = True
          else:
            kw = kw[1:]
            neg = False
          try:
            label = config.str2label(kw)
          except KeyError, e:
            raise KernelValueError('Unknown label: %s' % e)
          if neg:
            label_preds.append('-'+kw)
            label_block.add(label)
            if label in label_pass:
              label_pass.remove(label)
          else:
            label_preds.append('+'+kw)
            label_pass.add(label)
            if label in label_block:
              label_block.remove(label)
        doc_preds = []
        if label_block:
          doc_preds.append(LabelBlock(label_block))
        if label_pass:
          doc_preds.append(LabelPass(label_pass))
        selection = MailSelection(corpus, term_preds, doc_preds, label_preds,
                                  disjunctive=disjunctive, window_size=nmsgs)

    # Perform search.
    n = selection.list_messages(self.terminal, verbose)
    if not n: raise KernelValueError('Not found.')
    # Save the search results.
    self.set_selection(selection)
    return

  # cmd_show
  def cmd_show(self, args):
    'usage: show [-q] [-l)ist] [-a)ll] [-h)eaders] [-c charset] [-P)rev|-N)ext] msg:part ...'
    try:
      (opts, args) = getopt(args, 'qlahc:PN')
    except GetoptError:
      raise ShowUsage()
    #
    verbose = 1
    dolist = False
    showall = False
    headerlevel = 1
    charset = None
    rel = 0
    for (k,v) in opts:
      if k == '-q': verbose = 0
      elif k == '-l': dolist = True
      elif k == '-a': showall = True
      elif k == '-h': headerlevel = 2
      elif k == '-c': charset = v
      elif k == '-P': rel = -1
      elif k == '-N': rel = +1
    #
    (docs, args) = self.get_messages(args or ['.'], rel)
    if args:
      self.terminal.warning('Arguments ignored: %r' % args)
    for (i,doc,part) in docs:
      if dolist:
        message.show_digest(self.terminal, i, False, doc, self.get_selection(), doc.labels)
        continue
      if part == None:
        message.show_message(self.terminal, i, doc, self.get_selection(),
                             showall, showall, headerlevel, verbose)
        continue
      try:
        message.show_mime_part(self.terminal, doc.get_msg(0), part, headerlevel, charset)
      except MessagePartNotFoundError:
        raise KernelValueError('Message part not found.')
    return

  # cmd_get
  def cmd_get(self, args):
    'usage: get [-f|-F field] [-o filename] msg:part'
    try:
      (opts, args) = getopt(args, 'f:F:c:o:')
    except GetoptError:
      raise ShowUsage()
    #
    fields = []
    outputfile = None
    for (k,v) in opts:
      if k == '-f': fields.extend( (h,True) for h in v.split(',') )
      elif k == '-F': fields.extend( (h,False) for h in v.split(',') )
      elif k == '-o': outputfile = v
    #
    (docs, args) = self.get_messages(args or ['.'])
    if args:
      self.terminal.warning('Arguments ignored: %r' % args)
    if fields:
      for (_,doc,part) in docs:
        message.show_headers(self.terminal, doc, fields)
      return
    if len(docs) != 1:
      raise KernelSyntaxError('Can save only one file at a time.')
    (_,doc,part) = docs[0]
    confirm = False
    if part == None:
      # Save the entire message.
      data = doc.corpus.get_message(doc.loc)
    else:
      # Save the mime part.
      try:
        mpart = get_message_part(doc.get_msg(0), part)
      except MessagePartNotFoundError:
        raise KernelValueError('Message part not found.')
      if not outputfile:
        outputfile = escape_unsafe_chars(mpart.get_filename() or '')
        confirm = True
      data = mpart.get_payload(decode=True)
    if not outputfile:
      raise KernelValueError('Speficy the filename to save.')
    self.terminal.save_file(data, outputfile, confirm)
    return

  # cmd_resolve
  def cmd_resolve(self, args):
    'usage: resolve addr ...'
    try:
      (opts, args) = getopt(args, '')
    except GetoptError:
      raise ShowUsage()
    #
    if not args: raise ShowUsage()
    for addr in args:
      if addr in config.ADDRESS_ALIASES:
        self.terminal.notice('%s: by alias' % addr)
        self.terminal.notice('\t'+config.ADDRESS_ALIASES[addr])
      else:
        r = self.resolve_address(addr)
        if not r:
          self.terminal.notice('%s: cannot resolve.' % addr)
        else:
          if len(r) == 1:
            self.terminal.notice('%s: uniquely resolved.' % addr)
          else:
            self.terminal.notice('%s: multiple candidates:' % addr)
          for (n, x) in r:
            self.terminal.notice('\t%2d: %s' % (n, x))
    return

  # cmd_comp
  def cmd_comp(self, args):
    'usage: comp [-g)roup] [-r)eply] [-F)orward] [-s subject] [+label] [msg:part] addrs ...'
    try:
      (opts, args) = getopt(args, 'grFs:')
    except GetoptError:
      raise ShowUsage()
    #
    group = False
    reply = False
    forward = False
    subject = u''
    labels = config.LABEL4DRAFT
    for (k,v) in opts:
      if k == '-g': group = True
      elif k == '-r': reply = True
      elif k == '-F': forward = True
      elif k == '-s': subject = v
    if (forward or reply) and not args:
      args = ['.']
    elif not args:
      raise ShowUsage()
    # Setup a template text.
    # First, get recipient addresses.
    (addrs_to, addrs_cc, addrs_bcc) = ([], [], [])
    try:
      (docs, args) = self.get_messages(args)
    except KernelValueError:
      docs = []
    for arg in args:
      if arg.startswith('+'):
        try:
          labels = config.str2label(arg[1:])
        except KeyError, e:
          raise KernelValueError('Unknown label: %s' % e)
      elif arg.startswith('to:'):
        addrs_to.extend(arg[3:].split(','))
      elif arg.startswith('cc:'):
        addrs_cc.extend(arg[3:].split(','))
      elif arg.startswith('bcc:'):
        addrs_bcc.extend(arg[3:].split(','))
      else:
        addrs_to.extend(arg.split(','))
    if (not docs or forward) and not (addrs_to or addrs_cc or addrs_bcc):
      raise KernelSyntaxError('At least one recipient is required.')
    if (forward or reply) and not docs:
      raise KernelSyntaxError('Specify the message to reply/forward.')
    
    def resolve1(addr):
      if '@' in addr: return addr
      if addr in config.ADDRESS_ALIASES: return config.ADDRESS_ALIASES[addr]
      r = self.resolve_address(addr)
      if not r:
        raise KernelValueError('Cannot resolve address: %s' % addr)
      (n, x) = r[0]
      threshold = int(len(r)*config.RESOLVE_ADDRESS_RATIO + 0.5)
      if n <= threshold:
        raise KernelValueError('Ambiguous address: %s: %s' % (addr, ', '.join( a for (n,a) in r )))
      return x
    
    addrs_to = [ resolve1(addr) for addr in addrs_to ]
    addrs_cc = [ resolve1(addr) for addr in addrs_cc ]
    addrs_bcc = [ resolve1(addr) for addr in addrs_bcc ]
    # Select messages to reuse.
    headermsgs = []
    includemsgs = []
    forwardmsgids = []
    if docs:
      headermsgs = [ doc.get_msg() for (i,doc,_) in docs ]
      if forward:
        # Forwarding messages
        forwardmsgids = [ doc.loc for (i,doc,_) in docs ]
      else:
        # Replying to messages
        if reply:
          includemsgs = headermsgs
    # Setup a template and edit it.
    tmpl = message.setup_template_string(config.MY_FROM, addrs_to, addrs_cc, addrs_bcc, group,
                                         subject, labels, headermsgs, includemsgs, forwardmsgids)
    return self.terminal.edit_text(self, tmpl)
  
  # cmd_edit
  def cmd_edit(self, args):
    'usage: edit [-f)orce] [msg]'
    try:
      (opts, args) = getopt(args, 'f')
    except GetoptError:
      raise ShowUsage()
    #
    force = False
    for (k,v) in opts:
      if k == '-f': force = True
    #
    (docs, args) = self.get_messages(args or ['.'])
    if args:
      self.terminal.warning('Arguments ignored: %r' % args)
    if len(docs) != 1:
      raise KernelSyntaxError('Can edit only one message at a time.')
    (_,doc,part) = docs[0]
    if not force and (config.LABEL4DRAFT not in doc.labels):
      raise KernelValueError('Message not in the draft.')
    data = message.get_editable_string(doc.get_msg(0), doc.labels)
    return self.terminal.edit_text(self, data, doc.loc)

  # cmd_mime
  def cmd_mime(self, args):
    'usage: mime [-R)emove] [-m mimetype] [-c charset] msg[:part] files ...'
    try:
      (opts, args) = getopt(args, 'Rm:c:')
    except GetoptError:
      raise ShowUsage()
    #
    charset = None
    mimetype = None
    remove = False
    for (k,v) in opts:
      if k == '-R': remove = True
      elif k == '-m': mimetype = v
      elif k == '-c': charset = v
    #
    (docs, args) = self.get_messages(args)
    corpus = self.get_selection().get_corpus()
    corpus.set_writable()
    if len(docs) != 1:
      raise KernelSyntaxError('Can edit only one message at a time.')
    #
    (_,doc,part) = docs[0]
    if config.LABEL4DRAFT not in doc.labels:
      raise KernelValueError('Message not in the draft.')
    msg = doc.get_msg(0)
    if remove:
      # Remove an attachment.
      if args:
        self.terminal.warning('Arguments ignored: %r' % args)
      msg = message.mime_del(msg, part)
    elif part:
      # Replace an attachment.
      if len(args) != 1:
        raise KernelSyntaxError('Need to supply exactly one filename.')
      (fname, data) = self.terminal.load_file(args[0])
      obj = message.mime_new(fname, data, mimetype, charset)
      msg = message.mime_alter(msg, part, obj)
    else:
      if not args:
        raise KernelSyntaxError('Need to supply attachment(s).')
      # Append an object.
      for fname in args:
        (fname, data) = self.terminal.load_file(fname)
        obj = message.mime_new(fname, data, mimetype, charset)
        msg = message.mime_add(msg, obj)
    corpus.set_deleted_label(doc.loc)
    loc = corpus.add_message(msg_repr(msg), doc.labels)
    self.select_tmp('mime', corpus, [loc])
    return

  # cmd_label
  def cmd_label(self, args):
    'usage: label [-q] [-R)eset] {+|+-}labels [msg]'
    try:
      (opts, args) = getopt(args, 'qR')
    except GetoptError:
      raise ShowUsage()
    #
    reset = False
    verbose = 1
    for (k,v) in opts:
      if k == '-q': verbose -= 1
      elif k == '-R': reset = True
    #
    (docs, args) = self.get_messages(args)
    if not docs:
      (docs, _) = self.get_messages(['.'])
      if not docs:
        raise KernelSyntaxError('No message is specified.')
    label_add = set()
    label_del = set()
    for kw in args:
      if kw.startswith('!') or kw.startswith('-'):
        kw = kw[1:]
        neg = True
      elif kw.startswith('+-') or  kw.startswith('+!'):
        kw = kw[2:]
        neg = True
      else:
        kw = kw[1:]
        neg = False
      try:
        label = config.str2label(kw)
      except KeyError, e:
        raise KernelValueError('Unknown label: %s' % e)
      if neg:
        label_del.add(label)
      else:
        label_add.add(label)

    corpus = self.get_selection().get_corpus()
    corpus.set_writable()
    # Reopen the corpus.
    for (_,doc,part) in docs:
      if reset:
        labels = label_add
      else:
        labels = doc.labels.union(label_add).difference(label_del)
      corpus.set_label(doc.loc, labels)
    # Redisplay the selection.
    if 0 < verbose:
      self.get_selection().list_messages(self.terminal, verbose)
    return

  # cmd_send
  def cmd_send(self, args):
    'usage: send [-q)uiet] [-f)orce] [msg] ...'
    try:
      (opts, args) = getopt(args, 'qf')
    except GetoptError:
      raise ShowUsage()
    #
    force = False
    verbose = 1
    for (k,v) in opts:
      if k == '-q': verbose = 0
      elif k == '-f': force = True
    #
    (docs, args) = self.get_messages(args or ['.'])
    if args:
      self.terminal.warning('Arguments ignored: %r' % args)
    if not docs:
      raise KernelSyntaxError('No message is specified.')
    msgs = []
    for (i,doc,part) in docs:
      if config.LABEL4DRAFT not in doc.labels:
        raise KernelValueError('Message not in the draft: %d' % (i+1))
      msg = doc.get_msg(0)
      try:
        (fromaddr, rcpts) = validate_message_headers(msg, not force)
      except MessageFormatError, e:
        raise KernelValueError('%s: message %d' % (e, i+1))
      msgs.append((doc.loc, msg, fromaddr, rcpts))

    # Move the message from the draft to inbox (sent).
    corpus = self.get_selection().get_corpus()
    corpus.set_writable()
    for (loc,msg,fromaddr,rcpts) in msgs:
      try:
        data = message.send_message(msg, fromaddr, rcpts)
      except message.MessageTransportError, e:
        raise KernelValueError('%s: %r' % (e, rcpts))
      if verbose:
        self.terminal.notice('From: %r' % fromaddr)
        self.terminal.notice('Rcpt: %r' % rcpts)
      corpus.set_deleted_label(loc)
      corpus.add_message(data, config.LABEL4SENT)
    corpus.flush(self.notice_indexing)
    self.remove_selection()
    return

  # cmd_inc
  def cmd_inc(self, args):
    'usage: inc [-q)uiet] [-E)rase] [-P)reserve] [-r rulefile] [+label] [spool ...]'
    import importer
    try:
      (opts, args) = getopt(args, 'qEPr:')
    except GetoptError:
      raise ShowUsage()
    #
    labels = [ v[1:] for v in args if v.startswith('+') ]
    spools = [ v for v in args if not v.startswith('+') ]
    if spools:
      cleanup = False
    else:
      spools = [ config.SPOOL ]
      cleanup = True
    verbose = 1
    rules = []
    for (k,v) in opts:
      if k == '-q': verbose = 0
      elif k == '-E': cleanup = True
      elif k == '-P': cleanup = False
      elif k == '-r': rules.append(v)
    try:
      ruleset = importer.RuleSet(rules or config.RULES, labels)
    except importer.RuleSetSyntaxError, e:
      raise KernelValueError('Invalid ruleset: %s' % e)
    corpus = self.get_corpus()
    corpus.set_writable()
    locs = []
    for spool in spools:
      if not spool: continue
      importer = importer.CreateMessageImporter(spool, ruleset)
      importer.read_messages()
      if importer.is_empty(): continue
      for (data,labels,mtime) in importer.finish():
        locs.append(corpus.add_message(data, labels, mtime))
      importer.close(cleanup)
    corpus.flush(self.notice_indexing)
    if verbose and locs:
      locs.reverse()
      self.select_tmp('inc', corpus, locs)
    return

  # cmd_apply
  def cmd_apply(self, args):
    'usage: apply [-r rulefile] [-n)ull] [-v)erbose] [-R)eset] [msg]'
    import importer
    try:
      (opts, args) = getopt(args, 'nvRr:')
    except GetoptError:
      raise ShowUsage()
    #
    reset = False
    dryrun = False
    verbose = 0
    rules = []
    for (k,v) in opts:
      if k == '-R': reset = True
      elif k == '-n': dryrun = True
      elif k == '-v': verbose += 1
      elif k == '-r': rules.append(v)
    if not rules:
      rules = config.RULES
    #
    (docs, args) = self.get_messages(args or ['.'])
    if not docs:
      raise KernelSyntaxError('No message is specified.')
    # Apply rules.
    try:
      ruleset = importer.RuleSet(rules)
    except importer.RuleSetSyntaxError, e:
      raise KernelValueError('Invalid ruleset: %s' % e)
    corpus = self.get_selection().get_corpus()
    corpus.set_writable()
    for (i,doc,part) in docs:
      labels = set(ruleset.apply_msg(doc.get_msg()))
      if not reset:
        labels.update(doc.labels)
      if not dryrun:
        corpus.set_label(doc.loc, labels)
      if dryrun or verbose:
        message.show_digest(self.terminal, i, False, doc, self.get_selection(), labels)
    return

  # cmd_sel
  def cmd_sel(self, args):
    'usage: sel [-q] [-n nmsgs] [selection]'
    try:
      (opts, args) = getopt(args, 'n:q')
    except GetoptError:
      raise ShowUsage()
    #
    nmsgs = 0
    verbose = 1
    for (k,v) in opts:
      if k == '-n': nmsgs = safeint(v)
      elif k == '-q': verbose = 0
    #
    selections = self.list_selections()
    if args:
      selection = self.get_selection(safeint(args[0]))
      if verbose:
        self.cmd_scan([])
    else:
      for (i,fname) in enumerate(selections):
        fp = file(fname, 'rb')
        MailCorpus.register_corpus_handler(self.get_corpus)
        selection = pickle.load(fp)
        fp.close()
        self.terminal.notice('%2d: %s (%s)' % (i, selection.description(), selection.estimation()))
    return
  
  # cmd_cleanup
  def cmd_cleanup(self, args):
    'usage: cleanup'
    corpus = self.get_corpus()
    corpus.set_writable()
    corpus.flush(self.notice_indexing, force=True)
    for fname in os.listdir(config.TMP_DIR):
      fname = os.path.join(config.TMP_DIR, fname)
      if os.path.isfile(fname):
        os.unlink(fname)
    return

  # cmd_thread
  def cmd_thread(self, args):
    'usage: thread [msg]'
    try:
      (opts, args) = getopt(args, '')
    except GetoptError:
      raise ShowUsage()
    (docs, args) = self.get_messages(args or ['.'])
    if args:
      self.terminal.warning('Arguments ignored: %r' % args)
    if not docs:
      raise KernelSyntaxError('No message is specified.')
    msgids = set()
    for (_,doc,part) in docs:
      msg = doc.get_msg()
      if 'references' in msg:
        msgids.update(get_msgids(msg['references']))
      if 'in-reply-to' in msg:
        msgids.update(get_msgids(msg['in-reply-to']))
      if 'message-id' in msg:
        msgids.add(msg['message-id'])
    self.cmd_scan(['references: '+' '.join(list(msgids))])
    return

