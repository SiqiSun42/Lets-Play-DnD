import os
import pymupdf
from sentence_transformers import SentenceTransformer
import chromadb 
import re

# 导入文件
PDF_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "DnD Rule Books")
)
PDF_FILENAMES = ["玩家手册.pdf", "怪物图鉴.pdf", "城主指南.pdf"]
PDF_PATHS = [os.path.join(PDF_DIR, f) for f in PDF_FILENAMES]
VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db")
# 参数
BATCH_SIZE = 5000 # 英文版向量化有7270块，超过Chroma的默认batch 5461；中文版是3081，其实不需要
MAX_CHUNK_SIZE = 700
CHUNK_OVERLAP = 200  # 相邻 chunk 重叠字数；下一步起点 = 当前起点 + (MAX_CHUNK_SIZE - CHUNK_OVERLAP)
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5" # 中文版: BAAI/bge-small-zh-v1.5；英文版: BAAI/bge-small-en-v1.5

# ==================== 工具函数 ====================

def load_pdf(filepath):
    """读取一个PDF文件, 返回全部内容"""
    doc = pymupdf.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def _is_cjk(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def clean_pdf_text(text):
    text = re.sub(r"(\w)-\n(?!\n)(\w)", r"\1\2", text)

    paragraphs = []
    current = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            continue

        if not current:
            current = stripped
        elif _is_cjk(current[-1]) and _is_cjk(stripped[0]):
            current += stripped
        else:
            current += " " + stripped

    if current:
        paragraphs.append(current)

    return "\n\n".join(paragraphs)


def split_long_with_overlap(text, max_chunk_size, overlap):
    """超长文本滑动窗口切分。例如 size=700、overlap=200 时，块起点为 0, 500, 1000, ..."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chunk_size:
        return [text]

    overlap = max(0, min(int(overlap), max_chunk_size - 1))
    step = max_chunk_size - overlap
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        piece = text[start: start + max_chunk_size].strip()
        if piece:
            chunks.append(piece)
        if start + max_chunk_size >= n:
            break
        start += step
    return chunks


def split_text(text, max_chunk_size=500, overlap=CHUNK_OVERLAP):
    """按照自然段落分割文本, 并合并短块, 切割长块, 确保每块的大小约等于max_chunk_size个字符。
    超长段落按 overlap 做滑动窗口叠加，减轻硬切丢上下文（城主指南这类无\\n\\n文本尤其需要）。"""
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
                # 超长段：滑动窗口硬切，相邻块保留 overlap 字
                chunks.extend(
                    split_long_with_overlap(para, max_chunk_size, overlap)
                )

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

SKIP_CLEAN_FILENAMES = {"城主指南.pdf"}


def report_text_stats(text, max_chunk_size=MAX_CHUNK_SIZE, title="文本结构统计"):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    lengths = [len(p) for p in paragraphs]
    total_chars = sum(lengths)
    n = len(paragraphs)

    print("=" * 50)
    print(title)
    print(f"总字符数: {total_chars}")
    print(f"段落数(按\\n\\n): {n}")
    if n:
        avg = total_chars / n
        lengths_sorted = sorted(lengths)
        p50 = lengths_sorted[n // 2]
        p90 = lengths_sorted[int(n * 0.9)]
        p99 = lengths_sorted[min(n - 1, int(n * 0.99))]
        over = sum(1 for x in lengths if x > max_chunk_size)
        under_50 = sum(1 for x in lengths if x < 50)
        under_100 = sum(1 for x in lengths if x < 100)
        print(f"段落平均字数: {avg:.1f}")
        print(f"最短/最长: {lengths_sorted[0]} / {lengths_sorted[-1]}")
        print(f"中位数 P50: {p50}")
        print(f"P90: {p90}")
        print(f"P99: {p99}")
        print(f"短于50字: {under_50} ({under_50 / n * 100:.1f}%)")
        print(f"短于100字: {under_100} ({under_100 / n * 100:.1f}%)")
        print(f"长于max_chunk_size({max_chunk_size}): {over} ({over / n * 100:.1f}%)")

    chunks = split_text(text, max_chunk_size, overlap=CHUNK_OVERLAP)
    chunk_lens = [len(c) for c in chunks]
    print("-" * 50)
    print(
        f"按当前 split_text(max={max_chunk_size}, overlap={CHUNK_OVERLAP}) 分块后"
    )
    print(f"块数: {len(chunks)}")
    if chunk_lens:
        print(f"块平均字数: {sum(chunk_lens) / len(chunk_lens):.1f}")
        print(f"块最短/最长: {min(chunk_lens)} / {max(chunk_lens)}")
        hard_cut = sum(1 for p in paragraphs if len(p) > max_chunk_size)
        print(f"会被硬切的超长段落数: {hard_cut}")
    print("=" * 50)


def main():
    parts = []
    for path in PDF_PATHS:
        filename = os.path.basename(path)
        file_text = load_pdf(path)
        if filename in SKIP_CLEAN_FILENAMES:
            print(f"[跳过 clean] {filename}")
        else:
            print(f"[应用 clean] {filename}")
            file_text = clean_pdf_text(file_text)
        report_text_stats(
            file_text,
            MAX_CHUNK_SIZE,
            title=f"单本统计: {filename}",
        )
        parts.append(file_text)

    text = "\n\n".join(parts)
    report_text_stats(text, MAX_CHUNK_SIZE, title="三本拼接后统计")

    # 2.分块（超长段带 CHUNK_OVERLAP 滑动重叠）
    chunks = split_text(text, MAX_CHUNK_SIZE, overlap=CHUNK_OVERLAP)

    # 3. 加载模型
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    # 4. 向量化
    embeddings = model.encode(chunks, show_progress_bar=True)

    # 5. 存入 Chroma: 记得切换zh/en
    chroma_client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
    collection = chroma_client.get_or_create_collection("dnd_rules_zh")

    existing_ids = collection.get()["ids"]
    if existing_ids:
        collection.delete(ids=existing_ids)
        print(f"已清理 {len(existing_ids)} 条旧数据")

    # 6. 存入 Chroma。英文版会溢出，所以需要分批处理
    total = len(chunks)
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        collection.add(
            documents=chunks[start:end],
            embeddings=embeddings[start:end].tolist(),
            ids=[str(i) for i in range(start, end)],
        )
        print(f"已写入 {end}/{total}")


if __name__ == "__main__":
    main()
    
