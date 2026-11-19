# Third-party notices

## Hershey fonts (`src/print_forge/font_data.py`)

The stroke data for the letter and legend generators is the Hershey Roman Simplex font
(`futural.jhf`), taken from the Hershey font distribution as packaged in
<https://github.com/kamalmostafa/hershey-fonts> and converted to Python tuples for print-forge.
It is not covered by print-forge's MIT licence; it is used under the distribution terms of the
Hershey font data, which allow use for any purpose provided that:

1. The following acknowledgements are distributed with the font data:
   - The Hershey Fonts were originally created by Dr. A. V. Hershey while working at the
     U. S. National Bureau of Standards.
   - The format of the Font data in this distribution was originally created by
     James Hurt, Cognition, Inc., 900 Technology Park Drive, Billerica, MA 01821
     (mit-eddie!ci-dandelion!hurt).
2. The font data may be converted into any other format *except* the format distributed by
   the U.S. NTIS.

print-forge stores the glyphs as integer coordinate tuples, not in the NTIS format.

## Keycap stem reference values

The nominal MX-style stem and socket dimensions in `src/print_forge/families/cap.py` are numbers
read from the KeyV2 OpenSCAD library (<https://github.com/rsheldiii/KeyV2>, GPL-3.0). Only the
numeric values are used as a reference; no KeyV2 code is included.
