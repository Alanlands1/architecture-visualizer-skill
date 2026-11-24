#!/usr/bin/env python3
"""Best-effort text extraction helper for PDF, DOCX, PPTX, Markdown and TXT."""
import argparse
from pathlib import Path

def extract(p):
    ext=p.suffix.lower()
    if ext in {'.txt','.md','.markdown'}: return p.read_text(encoding='utf-8',errors='replace')
    if ext=='.docx':
        from docx import Document
        d=Document(p); chunks=[x.text for x in d.paragraphs]
        for t in d.tables:
            for r in t.rows: chunks.append(' | '.join(c.text for c in r.cells))
        return '\n'.join(x for x in chunks if x.strip())
    if ext=='.pptx':
        from pptx import Presentation
        prs=Presentation(p); chunks=[]
        for i,s in enumerate(prs.slides,1):
            chunks.append(f'## Slide {i}')
            for sh in s.shapes:
                if getattr(sh,'has_text_frame',False) and sh.text.strip(): chunks.append(sh.text)
                if getattr(sh,'has_table',False):
                    for r in sh.table.rows: chunks.append(' | '.join(c.text for c in r.cells))
        return '\n'.join(chunks)
    if ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(str(p)); return '\n'.join(f'## Page {i}\n{page.extract_text() or ""}' for i,page in enumerate(reader.pages,1))
    raise ValueError(f'Unsupported format: {ext}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input',type=Path); ap.add_argument('--out',type=Path); a=ap.parse_args()
    text=extract(a.input); out=a.out or a.input.with_suffix('.txt'); out.write_text(text,encoding='utf-8'); print(f'Extracted text to {out} ({len(text)} characters)')
    if not text.strip() and a.input.suffix.lower()=='.pdf': print('WARNING: No extractable PDF text; this may be a scanned document requiring OCR.')
if __name__=='__main__': main()
