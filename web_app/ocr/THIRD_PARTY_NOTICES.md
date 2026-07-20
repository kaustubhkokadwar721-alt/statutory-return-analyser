# OCR Runtime Notices

This directory contains pinned, local runtime assets used only for in-browser OCR.
No client document is sent to these projects or their hosts during use.

- PDF.js 4.10.38, Mozilla, Apache-2.0.
- Tesseract.js 5.1.1 and Tesseract.js Core 5.1.1, Naptha, Apache-2.0.
- English `eng.traineddata` from `tesseract-ocr/tessdata_fast` 4.1.0, Apache-2.0.

Run `python vendor_ocr.py --verify` to verify the bundled file hashes.
