# Leafpen PDF

A free, offline PDF editor and signer for Windows. It never touches the network:
your documents, signatures and certificates stay on your computer.

The interface is available in **English** and **Türkçe**. It follows your Windows display
language by default (Turkish → Turkish, anything else → English), and you can switch at any
time from **Help › Language**. The app restarts to apply the change.

## Features

| Area | What you can do |
|---|---|
| Viewing | Zoom (Ctrl+wheel), fit to width, page thumbnails, bookmarks (add, rename, delete), printing, drag-and-drop to open |
| Search | Find text (Ctrl+F) with Turkish-aware case matching (`ikinci` finds `İKİNCİ`) |
| Text | Add text and edit lines or whole paragraphs directly on the page: font, size, bold, italic and color per word; left, centered, right or justified; line spacing and box width. Alignment and mixed styles of existing paragraphs are kept. Full Unicode support, including Turkish characters |
| Markup | Highlight, freehand pen, rectangle, ellipse, line, arrow (fill, dashed lines, opacity), sticky notes (icon and color), stamps (any text), insert images, erase annotations |
| Select | Click a shape, stamp, note, image, form field or paragraph to move it (drag or arrow keys), resize it with its handles, change its color, fill, line or opacity, edit it (double-click) or delete it |
| Redaction | Mark areas (or every search match) and permanently remove the text, images and drawings under them |
| Pages | Rotate, delete, reorder, crop, insert pages from another PDF, save selected pages as a separate PDF |
| Page content | Text watermark (angle, opacity, in front or behind), header and footer with page number, page count and date |
| Forms | Create text, multi-line, checkbox, drop-down and list fields; fill in text fields, checkboxes, radio buttons and drop-downs |
| Export | Pages as PNG/JPEG images; a compressed copy with smaller images and subset fonts |
| Handwritten signature | Draw, type or import a scanned signature and place it on a page |
| Digital signature | PAdES signing with a .p12/.pfx certificate (visible or invisible), self-signed identity creation, signature verification |
| Security | Open, edit and sign password-protected PDFs; the password is preserved when saving |

Every edit can be undone and redone (Ctrl+Z / Ctrl+Y).

## Usage

Run `dist\LeafpenPDF\LeafpenPDF.exe`. The whole folder is portable and the target machine does
not need Python installed.

To run from source:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m leafpen [file.pdf]
```

To build, run `.\build.ps1`. It runs the tests first, then produces `dist\LeafpenPDF\`.
To run only the tests, install `pytest` (`pip install pytest pyinstaller`) and run `pytest`.

Two sample PDFs for manual testing are in [samples](samples): `sample-en.pdf` and `sample-tr.pdf`.
Each has a signature box, a form-style page and a table page.

## About digital signatures

- **Signing writes to a copy.** Signing never modifies the original file; the signed version is
  saved separately (`*_signed.pdf`). The signature is appended incrementally, so signatures that
  are already in the document stay valid.
- **Limits of a self-signed identity.** An identity created inside the app proves that the
  document has not changed since signing. The other party will not see your identity as
  "verified" unless they trust your certificate. For legally recognised signatures (for example
  a qualified e-signature), use a .pfx/.p12 certificate from an authorised provider.
  Signing with a smart card or USB token is not supported.
- **Verification is fully offline.** The trust chain is checked against the Windows root
  certificate store. Revocation (CRL/OCSP) checking is not performed, and the verification
  report says so explicitly.

## Known limitations

- Edited text is rewritten with Arial, Times New Roman or Courier New (whichever is closest to
  the original font). A paragraph that becomes longer grows downwards and may overlap the content
  below it; the app tells you when it does.
- The Select tool moves and deletes an image only when it is drawn upright and once on the page
  (not inside a form XObject). Other images can be removed with the Redact tool.
- Redaction marks are only marks until you apply them. The app offers to apply them when you save.
- Stamps are stored as images, so stamp text is not searchable.
- Text on scanned (image) pages cannot be edited because there is no OCR.
- Editing a digitally signed document and saving it makes the existing signatures appear
  invalid. The app warns you before saving.
- When adding text, the Windows fonts Arial, Times New Roman and Courier New are embedded.

## Adding a language

Strings in the code are written in English and wrapped in `tr("...")`. To add a language,
copy `leafpen/lang/tr.py` to a new module, translate the values, then register it in
`LANGUAGES` and `_CATALOGS` in `leafpen/i18n.py`. A test fails if a string in the code has no
translation or a catalog entry is unused.

## License

Leafpen PDF is licensed under the [GNU Affero General Public License v3.0](LICENSE).
This is required because PyMuPDF is AGPL-3.0: if you distribute the application (including
the compiled `.exe`), you must also make the source code available under the same license.

### Third-party components

| Component | License | Used for |
|---|---|---|
| [PyMuPDF / MuPDF](https://github.com/pymupdf/PyMuPDF) | AGPL-3.0 | PDF processing and rendering |
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | LGPL-3.0 | User interface (dynamically linked) |
| [pyHanko](https://github.com/MatthiasValvekens/pyHanko) | MIT | PAdES digital signatures |
| [pyhanko-certvalidator](https://github.com/MatthiasValvekens/certvalidator) | MIT | Certificate chain validation |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 / BSD | Cryptography and certificate handling |

Arial, Times New Roman and Courier New are owned by Microsoft. These fonts are not
distributed with the application; they are read from the user's Windows installation and
embedded into the PDF being edited.

Adobe, Acrobat and Smallpdf are trademarks of their respective owners. This project is not
affiliated with them.
