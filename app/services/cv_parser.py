import fitz  # PyMuPDF
import docx
import io
from fastapi import UploadFile
from typing import IO

def _extract_text_from_pdf(file_stream: IO[bytes]) -> str:
    """Helper function to extract text from a PDF file stream."""
    try:
        # Open PDF from a byte stream
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        
        # --- THIS IS THE FIX ---
        # Instead of 'text += ...', we append each page's text to a list.
        # This prevents mashing all pages into one single line.
        text_pages = []
        for page in doc:
            text_pages.append(page.get_text())
        doc.close()
        
        # We join all pages with a newline, ensuring page breaks
        # are treated as separators.
        return "\n".join(text_pages)
        # --- END OF FIX ---

    except Exception as e:
        print(f"Error parsing PDF: {e}")
        raise ValueError("Could not parse PDF file.")

def _extract_text_from_docx(file_stream: IO[bytes]) -> str:
    """Helper function to extract text from a DOCX file stream."""
    try:
        # Open DOCX from a file stream
        doc = docx.Document(file_stream)
        # This function is already correct.
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print(f"Error parsing DOCX: {e}")
        raise ValueError("Could not parse DOCX file.")

def parse_cv(file_stream: IO[bytes], content_type: str) -> str:
    """
    Parses a CV file stream based on its MIME type.
    
    This is the main function called by the candidates route.
    """
    if content_type == "application/pdf":
        return _extract_text_from_pdf(file_stream)
    elif content_type in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword" # For older .doc, though python-docx primarily handles .docx
    ]:
        return _extract_text_from_docx(file_stream)
    else:
        raise ValueError(f"Unsupported file type: {content_type}")