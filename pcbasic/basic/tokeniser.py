"""
PC-BASIC - tokeniser.py
Convert plain-text BASIC code to tokenised form

(c) 2013, 2014, 2015, 2016 Rob Hagemans
This file is released under the GNU GPL version 3 or later.
"""

import string
import struct

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from . import basictoken as tk
from . import util
from . import values


def ascii_read_to(ins, findrange):
    """Read until a character from a given range is found."""
    out = ''
    while True:
        d = ins.read(1)
        if d == '':
            break
        if d in findrange:
            break
        out += d
    ins.seek(-len(d), 1)
    return out


class Tokeniser(object):
    """BASIC tokeniser."""

    # keywords than can followed by one or more line numbers
    _linenum_words = (
        tk.KW_GOTO, tk.KW_THEN, tk.KW_ELSE, tk.KW_GOSUB,
        tk.KW_LIST, tk.KW_RENUM, tk.KW_EDIT, tk.KW_LLIST,
        tk.KW_DELETE, tk.KW_RUN, tk.KW_RESUME, tk.KW_AUTO,
        tk.KW_ERL, tk.KW_RESTORE, tk.KW_RETURN)

    # newline is considered whitespace: ' ', '\t', '\n'
    _ascii_whitespace = ' \t\n'
    # operator symbols
    _ascii_operators = '+-=/\\^*<>'

    def __init__(self, values, keyword_dict):
        """Initialise tokeniser."""
        self._values = values
        self._keyword_to_token = keyword_dict.to_token

    def tokenise_line(self, line):
        """Convert an ascii program line to tokenised form."""
        ins = StringIO(line)
        outs = StringIO()
        # skip whitespace at start of line
        d = util.skip(ins, self._ascii_whitespace)
        if d == '':
            # empty line at EOF
            return outs
        # read the line number
        self._tokenise_line_number(ins, outs)
        # expect line number
        allow_jumpnum = False
        # expect number (6553 6 -> the 6 is encoded as \x17)
        allow_number = True
        # flag for SPC( or TAB( as numbers can follow the closing bracket
        spc_or_tab = False
        # parse through elements of line
        while True:
            # peek next character
            c = util.peek(ins)
            # anything after NUL is ignored till EOL
            if c == '\0':
                ins.read(1)
                ascii_read_to(ins, ('', '\r'))
                break
            # end of line
            elif c in ('', '\r'):
                break
            # handle whitespace
            elif c in self._ascii_whitespace:
                ins.read(1)
                outs.write(c)
            # handle string literals
            elif util.peek(ins) == '"':
                self._tokenise_literal(ins, outs)
            # handle jump numbers
            elif allow_number and allow_jumpnum and c in string.digits + '.':
                self._tokenise_jump_number(ins, outs)
            # handle numbers
            # numbers following var names with no operator or token in between
            # should not be parsed, eg OPTION BASE 1
            # note we don't include leading signs, encoded as unary operators
            # number starting with . or & are always parsed
            elif c in ('&', '.') or (allow_number and
                                      not allow_jumpnum and c in string.digits):
                outs.write(self.tokenise_number(ins))
            # operator keywords ('+', '-', '=', '/', '\\', '^', '*', '<', '>'):
            elif c in self._ascii_operators:
                ins.read(1)
                # operators don't affect line number mode - can do line number
                # arithmetic and RENUM will do the strangest things
                # this allows for 'LIST 100-200' etc.
                outs.write(self._keyword_to_token[c])
                allow_number = True
            # special case ' -> :REM'
            elif c == "'":
                ins.read(1)
                outs.write(':' + tk.REM + tk.O_REM)
                self._tokenise_rem(ins, outs)
            # special case ? -> PRINT
            elif c == '?':
                ins.read(1)
                outs.write(tk.PRINT)
                allow_number = True
            # keywords & variable names
            elif c in string.ascii_letters:
                word = self._tokenise_word(ins, outs)
                # handle non-parsing modes
                if (word in (tk.KW_REM, "'") or
                            (word == tk.KW_DEBUG and word in self._keyword_to_token)):
                    self._tokenise_rem(ins, outs)
                elif word == tk.KW_DATA:
                    self._tokenise_data(ins, outs)
                else:
                    allow_jumpnum = (word in self._linenum_words)
                    # numbers can follow tokenised keywords
                    # (which does not include the word 'AS')
                    allow_number = (word in self._keyword_to_token)
                    if word in (tk.KW_SPC, tk.KW_TAB):
                        spc_or_tab = True
            else:
                ins.read(1)
                if c in (',', '#', ';'):
                    # can separate numbers as well as jumpnums
                    allow_number = True
                elif c in ('(', '['):
                    allow_jumpnum, allow_number = False, True
                elif c == ')' and spc_or_tab:
                    spc_or_tab = False
                    allow_jumpnum, allow_number = False, True
                else:
                    allow_jumpnum, allow_number = False, False
                # replace all other nonprinting chars by spaces;
                # HOUSE 0x7f is allowed.
                outs.write(c if ord(c) >= 32 and ord(c) <= 127 else ' ')
        outs.seek(0)
        return outs

    def _tokenise_rem(self, ins, outs):
        """Pass anything after REM as is till EOL."""
        outs.write(ascii_read_to(ins, ('', '\r', '\0')))

    def _tokenise_data(self, ins, outs):
        """Pass DATA as is, till end of statement, except for literals."""
        while True:
            outs.write(ascii_read_to(ins, ('', '\r', '\0', ':', '"')))
            if util.peek(ins) == '"':
                # string literal in DATA
                self._tokenise_literal(ins, outs)
            else:
                break

    def _tokenise_literal(self, ins, outs):
        """Pass a string literal."""
        outs.write(ins.read(1))
        outs.write(ascii_read_to(ins, ('', '\r', '\0', '"') ))
        if util.peek(ins) == '"':
            outs.write(ins.read(1))

    def _tokenise_line_number(self, ins, outs):
        """Convert an ascii line number to tokenised start-of-line."""
        linenum = self._tokenise_uint(ins)
        if linenum != '':
            # terminates last line and fills up the first char in the buffer
            # (that would be the magic number when written to file)
            # in direct mode, we'll know to expect a line number if the output
            # starts with a  00
            outs.write('\0')
            # write line number. first two bytes are for internal use
            # & can be anything nonzero; we use this.
            outs.write('\xC0\xDE' + linenum)
            # ignore single whitespace after line number, if any,
            # unless line number is zero (as does GW)
            if util.peek(ins) == ' ' and linenum != '\0\0' :
                ins.read(1)
        else:
            # direct line; internally, we need an anchor for the program pointer,
            # so we encode a ':'
            outs.write(':')

    def _tokenise_jump_number(self, ins, outs):
        """Convert an ascii line number pointer to tokenised form."""
        word = self._tokenise_uint(ins)
        if word != '':
            outs.write(tk.T_UINT + word)
        elif util.peek(ins) == '.':
            ins.read(1)
            outs.write('.')

    def _tokenise_word(self, ins, outs):
        """Convert a keyword to tokenised form."""
        word = ''
        while True:
            c = ins.read(1)
            word += c.upper()
            # special cases 'GO     TO' -> 'GOTO', 'GO SUB' -> 'GOSUB'
            if word == 'GO':
                pos = ins.tell()
                # GO SUB allows 1 space
                if util.peek(ins, 4).upper() == ' SUB':
                    word = tk.KW_GOSUB
                    ins.read(4)
                else:
                    # GOTO allows any number of spaces
                    nxt = util.skip(ins, self._ascii_whitespace)
                    if ins.read(2).upper() == 'TO':
                        word = tk.KW_GOTO
                    else:
                        ins.seek(pos)
                if word in (tk.KW_GOTO, tk.KW_GOSUB):
                    nxt = util.peek(ins)
                    if nxt and nxt in tk.name_chars:
                        ins.seek(pos)
                        word = 'GO'
            if word in self._keyword_to_token:
                # ignore if part of a longer name, except FN, SPC(, TAB(, USR
                if word not in (tk.KW_FN, tk.KW_SPC, tk.KW_TAB, tk.KW_USR):
                    nxt = util.peek(ins)
                    if nxt and nxt in tk.name_chars:
                        continue
                token = self._keyword_to_token[word]
                # handle special case ELSE -> :ELSE
                if word == tk.KW_ELSE:
                    outs.write(':' + token)
                # handle special case WHILE -> WHILE+
                elif word == tk.KW_WHILE:
                    outs.write(token + tk.O_PLUS)
                else:
                    outs.write(token)
                break
            # allowed names: letter + (letters, numbers, .)
            elif not c:
                outs.write(word)
                break
            elif c not in tk.name_chars:
                word = word[:-1]
                ins.seek(-1, 1)
                outs.write(word)
                break
        return word

    def _tokenise_uint(self, ins):
        """Convert a line or jump number to tokenised form."""
        word = bytearray()
        ndigits, nblanks = 0, 0
        # don't read more than 5 digits
        while (ndigits < 5):
            c = util.peek(ins)
            if not c:
                break
            elif c in string.digits:
                word += ins.read(1)
                nblanks = 0
                ndigits += 1
                if int(word) > 6552:
                    # note: anything >= 65530 is illegal in GW-BASIC
                    # in loading an ASCII file, GWBASIC would interpret these as
                    # '6553 1' etcetera, generating a syntax error on load.
                    break
            elif c in self._ascii_whitespace:
                ins.read(1)
                nblanks += 1
            else:
                break
        # don't claim trailing w/s
        ins.seek(-nblanks, 1)
        # no token
        if len(word) == 0:
            return ''
        return struct.pack('<H', int(word))

    def tokenise_number(self, ins):
        """Convert Python-string number representation to number token."""
        c = util.peek(ins)
        if not c:
            return ''
        elif c == '&':
            # handle hex or oct constants
            ins.read(1)
            if util.peek(ins).upper() == 'H':
                # hex constant
                return self._tokenise_hex(ins)
            else:
                # octal constant
                return self._tokenise_oct(ins)
        elif c in string.digits + '.+-':
            # handle other numbers
            # note GW passes signs separately as a token
            # and only stores positive numbers in the program
            return self._tokenise_dec(ins)

    def _tokenise_dec(self, ins):
        """Convert decimal expression in Python string to number token."""
        have_exp = False
        have_point = False
        word = ''
        while True:
            c = ins.read(1).upper()
            if not c:
                break
            elif c == '.' and not have_point and not have_exp:
                have_point = True
                word += c
            elif c in 'ED' and not have_exp:
                # there's a special exception for number followed by EL or EQ
                # presumably meant to protect ELSE and maybe EQV ?
                if c == 'E' and util.peek(ins).upper() in ('L', 'Q'):
                    ins.seek(-1, 1)
                    break
                else:
                    have_exp = True
                    word += c
            elif c in '-+' and (not word or word[-1] in 'ED'):
                # must be first character or in exponent
                word += c
            elif c in string.digits + values.BLANKS + values.SEPARATORS:
                # we'll remove blanks later but need to keep it for now
                # so we can reposition the stream on removing trailing whitespace
                word += c
            elif c in '!#' and not have_exp:
                word += c
                # must be last character
                break
            elif c == '%':
                # swallow a %, but break parsing
                break
            else:
                ins.seek(-1, 1)
                break
        # don't claim trailing whitespace
        trimword = word.rstrip(values.BLANKS)
        ins.seek(-len(word)+len(trimword), 1)
        # remove all internal whitespace
        word = trimword.strip(values.BLANKS)
        return self._values.from_repr(word, allow_nonnum=False).to_token()

    def _tokenise_hex(self, ins):
        """Convert hex expression in Python string to number token."""
        # pass the H in &H
        ins.read(1)
        word = ''
        while True:
            c = util.peek(ins)
            # hex literals must not be interrupted by whitespace
            if c and c in string.hexdigits:
                word += ins.read(1)
            else:
                break
        x = self._values.new_integer().from_hex(word)
        y = x.to_token_hex()
        return y

    def _tokenise_oct(self, ins):
        """Convert octal expression in Python string to number token."""
        # O is optional, could also be &777 instead of &O777
        if util.peek(ins).upper() == 'O':
            ins.read(1)
        word = ''
        while True:
            c = util.peek(ins)
            # oct literals may be interrupted by whitespace
            if c and c in string.octdigits + values.BLANKS:
                word += ins.read(1)
            else:
                break
        return self._values.new_integer().from_oct(word).to_token_oct()
