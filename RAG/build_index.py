import os
import fitz
from sentence_transformers import SentenceTransformer
import chromadb 

# 导入文件
PDF_DIR = "/Users/siqisun/学习/4.研一Summer/DnD Rule Books/"
PDF_FILENAMES = ["城主指南.pdf", "玩家手册.pdf", "怪物图鉴.pdf"]
# 路径
PDF_PATHS = [os.path.join(PDF_DIR, f) for f in PDF_FILENAMES]
VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db")
# 参数
MAX_CHUNK_SIZE = 500
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# ==================== 工具函数 ====================

def load_pdf(filepath):
    """读取一个PDF文件, 返回全部内容"""
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def split_text(text, max_chunk_size=500):
    """按照自然段落分割文本, 并合并短块, 切割长块, 确保每块的大小约等于max_chunk_size个字符"""
    raw_paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current_chunk) + len(para) < max_chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            if len(para) <= max_chunk_size:
                current_chunk = para + "\n\n"
            else:
                for start in range(0, len(para), max_chunk_size):
                    chunk = para[start: start + max_chunk_size].strip()
                    chunks.append(chunk)

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def main():
    # 1.加载文件，转化为字符
    text = ""
    for path in PDF_PATHS:
        file_text = load_pdf(path)
        filename = os.path.basename(path)
        text += file_text + "\n\n"

    # 2.分块
    chunks = split_text(text, MAX_CHUNK_SIZE)

    # 3. 加载模型
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    # 4. 向量化
    embeddings = model.encode(chunks, show_progress_bar=True)

    # 5. 存入 Chroma
    chroma_client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
    collection = chroma_client.get_or_create_collection("dnd_rules_zh")

    existing_ids = collection.get()["ids"]
    if existing_ids:
        collection.delete(ids=existing_ids)
        print(f"已清理 {len(existing_ids)} 条旧数据")

    collection.add(
        documents=chunks,
        embeddings=embeddings.tolist(),
        ids=[str(i) for i in range(len(chunks))]
    )


if __name__ == "__main__":
    main()
    
