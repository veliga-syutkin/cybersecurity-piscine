# Exif in JPEG — reading notes

How Exif metadata is stored inside a JPEG file, from the first byte down to a
single tag value. Reference notes for `scorpion`.

> **About the name.** Exif stands for ***Exchangeable image file format*** — the
> full title of the standard is *Exchangeable image file format for digital still
> cameras*, published jointly by CIPA (DC-008) and JEITA (CP-3451) [Exif].
> The specification spells it **"Exif"**; the all-caps "EXIF" is common usage,
> not the official form — hence the name of this file.
> Despite its name, Exif does **not define a new container**: "the
> file-recording format is based on existing formats" — JPEG for compressed
> images, TIFF 6.0 for uncompressed ones [Exif §3.2]. What Exif adds is a set of
> **metadata** stored in the TIFF structure and embedded in those files: an APP1
> segment in a JPEG (§3). Other formats have since adopted it, such as PNG with
> its `eXIf` chunk (§10).

All byte values are hexadecimal. "Offset" always means a position counted in bytes.
Bracketed tags such as **[Exif §4.6.2]** point to the specifications listed in
[References](#references); every statement below is checked against them.

---

## 1. Endianness

A file is a sequence of **bytes**. As soon as a number spans several bytes, the
format must say in which order those bytes are stored.

Example with the 32-bit value `0x12345678` (`0x12` = most significant byte):

| Byte order | Bytes in the file | Rule |
|---|---|---|
| **Big endian** | `12 34 56 78` | most significant byte first |
| **Little endian** | `78 56 34 12` | least significant byte first |

Key points:

- **Bytes** are reordered, never bits or hex digits: `0x12` never becomes `0x21`.
- A single byte, and text (a sequence of independent bytes), have **no** endianness.
- The bytes alone don't tell how to read them: `01 00` is **1** in little endian
  and **256** in big endian. The **format specification** decides.
- The `0x…` notation always shows the number in human order (most significant
  first), whatever the byte order in the file.
- Network protocols use big endian ("network byte order") — the reason `htons()`
  exists in socket code (`man 3 byteorder`).

| Format | Byte order | Source |
|---|---|---|
| JPEG (marker segment parameters) | big endian | [JPEG B.1.1.1] |
| PNG (all multi-byte integers) | big endian | [PNG §7.1] |
| GIF (multi-byte numeric fields) | little endian | [GIF §4] |
| BMP (`BITMAPFILEHEADER` fields) | little endian | [BMP] |
| **TIFF / Exif** | **declared by the file itself** (see §4) | [TIFF §2] |

---

## 2. Magic numbers (file signatures)

A few fixed bytes at a known position (usually the start of the file) that
identify the format **regardless of the extension**.

| Format | Signature (hex) | As ASCII | Source |
|---|---|---|---|
| JPEG | `FF D8` (SOI marker), followed by another marker (`FF xx`) | — | [JPEG Table B.1] |
| PNG | `89 50 4E 47 0D 0A 1A 0A` | `.PNG....` | [PNG §5.2] |
| GIF | `47 49 46 38 39 61` / `47 49 46 38 37 61` | `GIF89a` / `GIF87a` | [GIF §17] |
| BMP | `42 4D` | `BM` | [BMP] |
| TIFF | `49 49 2A 00` / `4D 4D 00 2A` | `II*.` / `MM.*` | [TIFF §2] |

The PNG signature is designed to detect bad file transfers [PNG-1.2 §12.12]:

- `89`: a non-ASCII byte, so a text file is unlikely to be taken for a PNG; it
  also catches transfers that clear bit 7;
- `50 4E 47`: the format name, `PNG`;
- `0D 0A` (CR-LF): catches transfers that alter newline sequences;
- `1A` (Ctrl-Z): stops file display under MS-DOS;
- `0A` (LF): catches the inverse of the CR-LF translation.

This is how the `file` command works (see `man 5 magic`).

---

## 3. JPEG structure: marker segments

A JPEG file is a sequence of **markers**: `FF` followed by a byte that is neither
`00` nor `FF` [JPEG B.1.1.2]. Most markers start a **marker segment** (marker +
parameters); a few **stand alone** (no parameters).

| Marker | Name | Role | Stand-alone |
|---|---|---|---|
| `FF D8` | SOI — Start Of Image | first marker of the file | yes |
| `FF E0` … `FF EF` | APP0 – APP15 | application segments (**APP1: Exif**; APP2: Exif FlashPix extension data [Exif Table 2]; APP0 is commonly used by JFIF) | |
| `FF DB` | DQT | quantization tables | |
| `FF C4` | DHT | Huffman tables | |
| `FF DD` | DRI | restart interval | |
| `FF C0` … `FF CF` (except `C4`, `C8`, `CC`) | SOF*n* — Start Of Frame | frame header: **image width and height** (SOF0 = baseline, SOF2 = progressive…) | |
| `FF DA` | SOS — Start Of Scan | scan header; **entropy-coded image data follows** | |
| `FF D0` … `FF D7` | RST0 – RST7 | restart markers inside the image data | yes |
| `FF FE` | COM | free-text comment (also metadata) | |
| `FF D9` | EOI — End Of Image | last marker of the file | yes |

Source: [JPEG Table B.1].

### Segment length

The first parameter of a marker segment is a **2-byte length, big endian**. It
counts the bytes of the segment **including the length field itself and
excluding the 2-byte marker** [JPEG B.1.1.4].

```
next marker position = current marker position + 2 (marker) + length
```

Things a reader must handle:

- **Fill bytes**: "any marker may optionally be preceded by any number of fill
  bytes" with value `FF` [JPEG B.1.1.2].
- **After SOS**, image data follows instead of a new segment: stop walking the
  segments there (metadata segments all come before it).
- **Unknown APP*n* / COM** segments: skip them using their length; Exif readers
  "should be designed to skip over unknown APPn and COM" [Exif §4.5.4].

### Order of segments in an Exif file

Exif requires **APP1 immediately after SOI** [Exif §4.7.2 A, Table 2]. Files
rewritten by other software may still put a JFIF APP0 first: a robust reader
looks for APP1 among the segments instead of assuming its position.

### APP1 / Exif layout [Exif §4.7.2, Figure 30]

```
offset  +00 +01   +02 +03   +04 +05 +06 +07 +08 +09   +0A ...
        FF  E1  | LL  LL  | 45  78  69  66  00  00  | TIFF header ...
        marker    length    "E" "x" "i" "f" NUL pad    attribute information
```

- The **Exif ID code** is 6 bytes: `Exif`, a `00` terminator and a `00` padding
  byte [Exif §4.7.2 C].
- The whole APP1 segment **cannot exceed 64 KBytes** [Exif §4.5.4, §4.7.2] —
  a direct consequence of the 16-bit length field.

---

## 4. TIFF header

Exif attribute information follows the **TIFF** structure, starting with an
8-byte header [TIFF §2 "Image File Header"], [Exif §4.7.2 E]:

| Bytes | Field | Little endian (`II`, Intel) | Big endian (`MM`, Motorola) |
|---|---|---|---|
| 0–1 | Byte order | `49 49` | `4D 4D` |
| 2–3 | Magic number 42 | `2A 00` | `00 2A` |
| 4–7 | Offset of the first IFD (0th IFD) | e.g. `08 00 00 00` | e.g. `00 00 00 08` |

Rules:

- The byte order applies to **every 16-bit and 32-bit integer** of the TIFF
  structure [TIFF §2]: each number is reversed **inside its own field**; the order
  of the fields never changes.
- The magic number is "an arbitrary but carefully chosen number (42) that
  further identifies the file as a TIFF file" [TIFF §2]. Checking byte order
  **and** 42 together validates both the position and the endianness; anything
  else means a wrong position or a corrupted / malicious file.
- **All offsets inside Exif are relative to the first byte of the byte order
  field** (`II` / `MM`), not to the start of the JPEG file [Exif §4.7.2 E].
  (TIFF counts offsets from the start of the TIFF file [TIFF §2]; inside APP1,
  the TIFF "file" starts at the header.)
- Exif readers are recommended to support **both** byte orders [Exif §4.8.4].

### Two byte orders in one file

- The **JPEG envelope** (markers, segment lengths) is **always big endian**
  [JPEG B.1.1.1].
- **Everything inside the TIFF structure** follows `II` / `MM`: entry counts,
  tags, types, counts, values, offsets, pointed-to values, child IFDs.
- Text (ASCII) and raw bytes (BYTE, UNDEFINED) are byte sequences, so they are
  not affected.

---

## 5. IFD — Image File Directory

```
[ N: 2 bytes ] [ entry 0: 12 bytes ] … [ entry N-1: 12 bytes ] [ next IFD offset: 4 bytes ]
```

Source: [TIFF §2 "Image File Directory"], [Exif §4.6.2].

- **N**: number of entries ("fields").
- Entries are **always 12 bytes**: entry *k* (from 0) starts at
  `IFD start + 2 + 12 × k`.
- Entries **must be sorted in ascending order by tag** [TIFF §2], [Exif §4.6.2].
  The values they point to may be stored in any order.
- **Next IFD offset**: `0` if there is none [TIFF §2]. In Exif, the 0th IFD
  points to the **1st IFD**, which may hold the **thumbnail** [Exif §4.7.2 D].
- Offsets are expected to be **even** (word boundary) [TIFF §2] — a reader
  should not rely on it.

### Entry layout (12 bytes)

| Bytes | Field | Meaning |
|---|---|---|
| 0–1 | **Tag** | *what* it is (unique 2-byte identifier) |
| 2–3 | **Type** | *how* to read the value |
| 4–7 | **Count** | *how many* values of that type — **not** a number of bytes |
| 8–11 | **Value Offset** | the value itself if it fits in 4 bytes, **otherwise an offset** (relative to the TIFF header) |

### Types [Exif §4.6.2]

| Code | Name | Size of one value | Content |
|---|---|---|---|
| 1 | BYTE | 1 | 8-bit unsigned integer |
| 2 | ASCII | 1 | 7-bit ASCII code; the string ends with `00` (NULL) |
| 3 | SHORT | 2 | 16-bit unsigned integer |
| 4 | LONG | 4 | 32-bit unsigned integer |
| 5 | RATIONAL | 8 | **two** LONGs: numerator, then denominator |
| 7 | UNDEFINED | 1 | byte whose meaning depends on the field definition |
| 9 | SLONG | 4 | 32-bit signed integer (two's complement) |
| 10 | SRATIONAL | 8 | two SLONGs: numerator, then denominator |

TIFF 6.0 also defines 6 SBYTE, 8 SSHORT, 11 FLOAT and 12 DOUBLE [TIFF §2],
not used by Exif 2.x. Exif 3.0 adds a UTF-8 type (see [Exif] for its code).
A reader should skip any entry whose type it does not know.

### Inline value or offset?

"The Value Offset contains the Value instead of pointing to the Value if and only
if the Value fits into 4 bytes" — determined by the **Type** and the **Count**
[TIFF §2]:

```
total size = size of one value (from the type) × count
```

- **≤ 4 bytes** → the value is **inside** the field, **left-justified**, i.e.
  stored in the lower-numbered bytes [TIFF §2], [Exif §4.6.2].
- **> 4 bytes** → the field holds an **offset** to the value.

Consequences:

- A RATIONAL (8 bytes) is **always** stored elsewhere.
- An ASCII string longer than 3 characters (+ its final `00`) is stored elsewhere.
- **Left-justified trap**: the spec's own example — in big endian, a SHORT of
  value 1 is recorded as `00 01 00 00` [Exif §4.6.2]; in little endian it is
  `01 00 00 00`. Reading the field as a 4-byte LONG gives the right result in
  little endian **by luck** and a wrong one in big endian (`0x00010000`).
  Always read according to the **type**.

### Cross-check the fields

The fields must agree with each other. Example: a count of 256 for a SHORT means
512 bytes, so the last field **must** be an offset — if you concluded it was an
inline value, one of your readings is wrong.

---

## 6. The IFD tree

Exif is not a flat list but a **tree of IFDs** linked by offsets
[Exif §4.6.3]:

```
TIFF header
 └─ 0th IFD (primary image: camera, dates, orientation…)
     ├─ tag 0x8769 → Exif IFD (shooting conditions, original date…)
     │                └─ tag 0xA005 → Interoperability IFD
     ├─ tag 0x8825 → GPS Info IFD (location)
     └─ next IFD → 1st IFD (thumbnail)
```

### Common tags

| Tag | Name | IFD | Type | Source |
|---|---|---|---|---|
| `0x0100` | ImageWidth | 0th | SHORT / LONG | [Exif §4.6.4] |
| `0x0101` | ImageLength (height) | 0th | SHORT / LONG | [Exif §4.6.4] |
| `0x010E` | ImageDescription | 0th | ASCII | [Exif §4.6.4] |
| `0x010F` | Make (manufacturer) | 0th | ASCII | [Exif §4.6.4] |
| `0x0110` | Model | 0th | ASCII | [Exif §4.6.4] |
| `0x0112` | Orientation | 0th | SHORT | [Exif §4.6.4] |
| `0x0131` | Software | 0th | ASCII | [Exif §4.6.4] |
| `0x0132` | DateTime (file change date and time) | 0th | ASCII, 20 | [Exif §4.6.4] |
| `0x013B` | Artist | 0th | ASCII | [Exif §4.6.4] |
| `0x8298` | Copyright | 0th | ASCII | [Exif §4.6.4] |
| `0x8769` | **Exif IFD Pointer** | 0th | LONG | [Exif §4.6.3] |
| `0x8825` | **GPS Info IFD Pointer** | 0th | LONG | [Exif §4.6.3] |
| `0x9003` | DateTimeOriginal (capture) | Exif | ASCII, 20 | [Exif §4.6.5] |
| `0x9004` | DateTimeDigitized | Exif | ASCII, 20 | [Exif §4.6.5] |
| `0x9011` | OffsetTimeOriginal (UTC offset of DateTimeOriginal) | Exif | ASCII, 7 | [Exif §4.6.5] |
| `0x927C` | MakerNote (manufacturer notes) | Exif | UNDEFINED | [Exif §4.6.5] |
| `0x9286` | UserComment | Exif | UNDEFINED | [Exif §4.6.5] |
| `0xA002` | PixelXDimension (valid image width) | Exif | SHORT / LONG | [Exif §4.6.5] |
| `0xA003` | PixelYDimension (valid image height) | Exif | SHORT / LONG | [Exif §4.6.5] |
| `0xA005` | Interoperability IFD Pointer | Exif | LONG | [Exif §4.6.3] |
| `0x0201` | JPEGInterchangeFormat (offset to thumbnail SOI) | 1st | LONG | [Exif §4.6.4] |
| `0x0202` | JPEGInterchangeFormatLength (thumbnail size) | 1st | LONG | [Exif §4.6.4] |

GPS Info IFD tags [Exif §4.6.6]:

| Tag | Name | Type, count |
|---|---|---|
| `0x0001` | GPSLatitudeRef (`N` / `S`) | ASCII, 2 |
| `0x0002` | GPSLatitude (degrees, minutes, seconds) | RATIONAL, 3 |
| `0x0003` | GPSLongitudeRef (`E` / `W`) | ASCII, 2 |
| `0x0004` | GPSLongitude (degrees, minutes, seconds) | RATIONAL, 3 |
| `0x0005` | GPSAltitudeRef | BYTE, 1 |
| `0x0006` | GPSAltitude | RATIONAL, 1 |

### Image dimensions in a JPEG

For JPEG compressed data, Exif says ImageWidth / ImageLength "shall not be used
because a JPEG marker is used instead" [Exif §4.6.4]: the authoritative size is
in the **SOF*n*** frame header [JPEG B.2.2]. PixelXDimension / PixelYDimension
(Exif IFD) record the valid image size. Some cameras record ImageWidth anyway
(see the example in §7).

### Dates [Exif §4.6.4, §4.6.5]

- Format: `YYYY:MM:DD HH:MM:SS`, 24-hour clock, one space between date and time;
  **20 bytes including the final NULL**. Unknown parts are filled with spaces
  (colons kept), or the whole field is blank.
- **DateTime** (`0x0132`, 0th IFD) is the date the **file was changed**, not the
  capture date.
- **DateTimeOriginal** (`0x9003`, Exif IFD) is when the picture was taken, as
  given by the **camera's clock**. It carries **no time zone**; the UTC offset,
  if recorded, is in **OffsetTimeOriginal** (`0x9011`, format `±HH:MM`).

---

## 7. Worked example

First bytes of a phone photo (`xxd -g 1 -l 34`):

```
00000000: ff d8 ff e1 c7 fc 45 78 69 66 00 00 49 49 2a 00  ......Exif..II*.
00000010: 08 00 00 00 13 00 00 01 03 00 01 00 00 00 c0 0c  ................
00000020: 00 00
```

| File position | Bytes | Meaning |
|---|---|---|
| `0x00` | `FF D8` | SOI |
| `0x02` | `FF E1` | APP1, immediately after SOI as required |
| `0x04` | `C7 FC` | segment length, big endian → 51 196; next marker at `0x02 + 2 + 51196` = 51 200 |
| `0x06` | `45 78 69 66 00 00` | Exif ID code: `Exif`, NULL, padding |
| `0x0C` | `49 49` | **TIFF header start** (base for all offsets) — `II`, little endian |
| `0x0E` | `2A 00` | magic number 42 |
| `0x10` | `08 00 00 00` | 0th IFD offset = 8 → file position `0x0C + 8` = `0x14` |
| `0x14` | `13 00` | the 0th IFD has 19 entries |
| `0x16` | `00 01` | entry 0, tag `0x0100` — ImageWidth |
| `0x18` | `03 00` | type 3 — SHORT |
| `0x1A` | `01 00 00 00` | count = 1 → 2 bytes total → inline value |
| `0x1E` | `C0 0C 00 00` | SHORT, left-justified: `0x0CC0` = **3264** pixels |

Note: this camera records ImageWidth in a JPEG although Exif says it shall not
(see §6) — real files do not always follow the spec, so a reader must be tolerant.

---

## 8. Safety checks

A parser reads data controlled by whoever made the file. Malformed or malicious
images are a classic source of vulnerabilities. TIFF says "readers must follow
the pointers wherever they may lead" [TIFF §2] — which is exactly why each
pointer must be checked first.

- **Bounds**: every offset and every `offset + size` must stay inside the APP1
  segment (and the file). An IFD offset larger than the segment length is
  impossible.
- **Loops**: an offset that points back to an IFD already visited would make a
  naive parser loop forever — keep track of visited offsets.
- **Magic number**: byte order + 42 must match before reading anything else.
- **Sanity of counts**: an entry count of thousands is almost always an
  endianness or position error.
- **Truncated files**: reading past the end must be handled, not crash.
- **Unknown tags, types and segments**: skip them instead of failing.

---

## 9. Editing or removing metadata (bonus)

Changing a value in place is easy only if its size does not change. If a value
becomes longer (or an entry is removed), the data after it **shifts**, and
**every offset pointing past that point must be recomputed** — otherwise the file
is broken. Removing the whole APP1 segment is the simplest way to strip Exif from
a JPEG.

---

## 10. Other formats handled by scorpion

- **PNG**: after the signature, a sequence of chunks: 4-byte length (data only),
  4-byte type, data, 4-byte CRC [PNG §5.3]. Text metadata lives in `tEXt`,
  `zTXt`, `iTXt` [PNG §11.3.3]. Exif lives in the `eXIf` chunk: the same TIFF
  structure as APP1, **without** the APP1 marker, length and `Exif` ID code — the
  data starts directly with `II` / `MM`; at most one `eXIf` chunk
  [PNG §11.3.4.5].
- **GIF**: header `GIF87a` / `GIF89a` [GIF §17]; logical screen width and height
  are 2-byte little-endian fields [GIF §18]; free text in Comment Extensions,
  label `0xFE` [GIF §24]. No Exif.
- **BMP**: `BITMAPFILEHEADER` starts with `bfType` = `0x4D42` ("BM"), followed by
  file size and the offset to the pixel data [BMP]. No Exif.

---

## References

| Key | Document | Link |
|---|---|---|
| **[Exif]** | CIPA DC-008 / JEITA CP-3451, *Exchangeable image file format for digital still cameras*. Section numbers above refer to **Exif 2.31** (CIPA DC-008-Translation-2016); the current edition is Exif 3.1 (CIPA DC-008-2026). | <https://www.cipa.jp/e/std/std-sec.html> |
| **[TIFF]** | *TIFF Revision 6.0*, Final — June 3, 1992 (Aldus / Adobe). §2 = Section 2 "TIFF Structure", pp. 13–16. | <https://www.itu.int/itudoc/itu-t/com16/tiff-fx/docs/tiff6.pdf> |
| **[JPEG]** | ITU-T T.81 \| ISO/IEC 10918-1, *Digital compression and coding of continuous-tone still images*, Annex B. | <https://www.w3.org/Graphics/JPEG/itu-t81.pdf> |
| **[PNG]** | W3C, *Portable Network Graphics (PNG) Specification (Third Edition)*, Recommendation, 24 June 2025. | <https://www.w3.org/TR/png-3/> |
| **[PNG-1.2]** | *PNG Specification, Version 1.2*, Rationale, §12.12 "PNG file signature". | <http://www.libpng.org/pub/png/spec/1.2/PNG-Rationale.html> |
| **[GIF]** | CompuServe, *Graphics Interchange Format, Version 89a*. | <https://www.w3.org/Graphics/GIF/spec-gif89a.txt> |
| **[BMP]** | Microsoft, `BITMAPFILEHEADER` structure (wingdi.h). | <https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-bitmapfileheader> |
