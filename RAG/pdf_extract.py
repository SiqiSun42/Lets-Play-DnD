import fitz

def load_pdf(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

if __name__ == "__main__":
    text = load_pdf("/Users/siqisun/学习/4.研一Summer/DnD Rule Books/城主指南.pdf")
    print(f"总字符数:{len(text)}")
    print(text[:500])