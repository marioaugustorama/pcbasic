"""
PC-BASIC - typeface.py
Font handling

(c) 2014, 2015 Rob Hagemans
This file is released under the GNU GPL version 3.
"""

import os
import logging

try:
    import numpy
except ImportError:
    numpy = None

import plat
import config

def prepare():
    """ Perpare the typeface module. """
    global debug
    debug = config.get('debug')

def font_filename(name, height, ext='hex'):
    """ Return name_height.hex if filename exists in current path, else font_dir/name_height.hex. """
    name = '%s_%02d.%s' % (name, height, ext)
    if not os.path.exists(name):
        # if not found in current dir, try in font directory
        name = os.path.join(plat.font_dir, name)
    return name

def load(families, height, unicode_needed, nowarn=False):
    """ Load the specified fonts for a given codepage. """
    names = [ font_filename(name, height) for name in families ]
    fontfiles = [ open(name, 'rb') for name in reversed(names) if os.path.exists(name) ]
    if len(fontfiles) == 0:
        if not nowarn:
            logging.warning('Could not read font file for height %d', height)
        return None
    fontdict = load_hex(fontfiles, height, unicode_needed)
    for f in fontfiles:
        f.close()
    # in debug mode, check if we have all needed glyphs
    # fontdict: unicode char -> glyph
    if debug and not nowarn:
        missing = unicode_needed - set(fontdict)
        warnings = 0
        for u in missing:
            warnings += 1
            logging.debug(u'Codepoint %x [%s] not represented in font', ord(u), u)
            if warnings == 3:
                logging.debug('Further codepoint warnings suppressed.')
                break
    return fontdict

def load_hex(fontfiles, height, unicode_needed):
    """ Load a set of overlaying unifont .hex files. """
    fontdict = {}
    for fontfile in fontfiles:
        for line in fontfile:
            # ignore empty lines and comment lines (first char is #)
            if (not line) or (line[0] == '#'):
                continue
            # split unicodepoint and hex string (max 32 chars)
            ucshex = line[0:4]
            fonthex = line[5:69]
            # extract codepoint and hex string;
            # discard anything following whitespace; ignore malformed lines
            try:
                c = unichr(int(ucshex, 16))
                # skip chars we won't need
                if c not in unicode_needed:
                    continue
                # skip chars we already have
                if (c in fontdict):
                    continue
                # string must be 32-byte or 16-byte; cut to required font size
                if len(fonthex) < 32:
                    raise ValueError
                if len(fonthex) < 64:
                    fonthex = fonthex[:2*height]
                else:
                    fonthex = fonthex[:4*height]
                fontdict[c] = fonthex.decode('hex')
            except Exception as e:
                logging.warning('Could not parse line in font file: %s', repr(line))
    # char 0 should always be defined and empty
    fontdict[u'\0'] = '\0'*height
    return fontdict

def fixfont(height, font, unicode_needed, font16):
    """ Fill in missing codepoints in font using 16-line font or blanks. """
    if not font:
        font = {}
    if height == 16:
        for c in unicode_needed:
            if c not in font:
                font[c] = ('\0'*16 if len(c) == 1 else '\0'*32)
    else:
        for c in unicode_needed:
            if c not in font:
                if font16 and c in font16:
                    font[c] = glyph_16_to(height, font16[c])
                else:
                    font[c] = ('\0'*height if len(c) == 1 else '\0'*2*height)
    return font

def glyph_16_to(height, glyph16):
    """ Crudely convert 16-line character to n-line character by taking out top and bottom. """
    s16 = list(glyph16)
    start = (16 - height) // 2
    if len(s16) == 16:
        return ''.join([ s16[i] for i in range(start, 16-start) ])
    else:
        return ''.join([ s16[i] for i in range(start*2, 32-start*2) ])


def load_fonts(font_families, heights_needed, unicode_needed):
    """ Load font typefaces. """
    fonts = {}
    for height in reversed(sorted(heights_needed)):
        if height in fonts:
            # already force loaded
            continue
        # load a Unifont .hex font and take the codepage subset
        fonts[height] = load(font_families, height, unicode_needed)
        # fix missing code points font based on 16-line font
        if 16 not in fonts:
            # if available, load the 16-pixel font unrequested
            font_16 = load(font_families, 16, unicode_needed, nowarn=True)
            if font_16:
                fonts[16] = font_16
        if 16 in fonts and fonts[16]:
            fixfont(height, fonts[height], unicode_needed, fonts[16])
    return fonts


def build_glyph(c, font_face, req_width, req_height, carry_col_9, carry_row_9):
    """ Build a glyph for the given unicode character. """
    # req_width can be 8, 9 (SBCS), 16, 18 (DBCS) only
    req_width_base = req_width if req_width <= 9 else req_width // 2
    try:
        face = bytearray(font_face[c])
    except KeyError:
        logging.debug(u'%s [code point %x] not represented in codepage, replacing with blank glyph.', c, ord(c))
        # codepoint 0 must be blank by our definitions
        face = bytearray(font_face[u'\0'])
        c = u'\0'
    # shape of encoded mask (8 or 16 wide; usually 8, 14 or 16 tall)
    code_height = 8 if req_height == 9 else req_height
    code_width = (8*len(face))//code_height
    force_double = req_width >= code_width*2
    if force_double:
        # i.e. we need a double-width char but got single
        logging.debug(u'Incorrect glyph width for %s [code point %x].', c, ord(c))
    if numpy:
        glyph = numpy.unpackbits(face, axis=0).reshape((code_height, code_width)).astype(bool)
        # repeat last rows (e.g. for 9-bit high chars)
        if req_height > glyph.shape[0]:
            if carry_row_9:
                repeat_row = glyph[-1]
            else:
                repeat_row = numpy.zeros((1, code_width), dtype = numpy.uint8)
            while req_height > glyph.shape[0]:
                glyph = numpy.vstack((glyph, repeat_row))
        if force_double:
            glyph = glyph.repeat(2, axis=1)
        # repeat last cols (e.g. for 9-bit wide chars)
        if req_width > glyph.shape[1]:
            if carry_col_9:
                repeat_col = numpy.atleast_2d(glyph[:,-1]).T
            else:
                repeat_col = numpy.zeros((code_height, 1), dtype = numpy.uint8)
            while req_width > glyph.shape[1]:
                glyph = numpy.hstack((glyph, repeat_col))
    else:
        glyph = [ [False]*req_width for _ in range(req_height) ]
        for yy in range(code_height):
            for half in range(code_width//8):
                line = face[yy*(code_width//8)+half]
                for xx in range(8):
                    if (line >> (7-xx)) & 1 == 1:
                        glyph[yy][half*8 + xx] = True
            # MDA/VGA 9-bit characters
            if carry_col_9 and req_width == 9:
                glyph[yy][8] = glyph[yy][7]
        # tandy 9-bit high characters
        if carry_row_9 and req_height == 9:
            for xx in range(8):
                glyph[8][xx] = glyph[7][xx]
        if force_double:
            for yy in range(code_height):
                for xx in range(req_width_base, -1, -1):
                    glyph[yy][2*xx+1] = glyph[yy][xx]
                    glyph[yy][2*xx] = glyph[yy][xx]
    return glyph

prepare()
