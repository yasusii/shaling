#!/usr/bin/env python
# -*- encoding: euc-jp -*-

import re

##  Kinsoku
##
WORD_PAT = re.compile(r'''
        [\[{(\'`"‘“〈《「『【〔（［｛]* # open paren
        ([a-zA-Z0-9_\xa0]+|\w)          # core
        [-=:;,.!?ぁぃぅぇぉゃゅょっァィゥェォャュョッ々ゝゞ・…、。：；，．！？\]})\'`"’”〉》」』】〕）］｝]* |
        \S |                            # other chars
        \s+                             # space
        ''', re.VERBOSE | re.UNICODE)
