#!/usr/bin/env python
# -*- encoding: euc-jp -*-

import re

##  Kinsoku
##
WORD_PAT = re.compile(r'''
        [\[{(\'`"�ơȡҡԡ֡ءڡ̡ʡΡ�]* # open paren
        ([a-zA-Z0-9_\xa0]+|\w)          # core
        [-=:;,.!?��������������å�������������á��������ġ���������������\]})\'`"�ǡɡӡաס١ۡ͡ˡϡ�]* |
        \S |                            # other chars
        \s+                             # space
        ''', re.VERBOSE | re.UNICODE)
