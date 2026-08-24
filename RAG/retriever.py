import os
import readline
from sentence_transformers import SentenceTransformer
import chromadb

VCVECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db")
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
TOP_K = 3
THRESHOLD = 0.5

_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

_client = chromadb.PersistentClient(path=VCVECTOR_DB_PATH)
_collection = _client.get_collection("dnd_rules_zh")

# 检索函数
def search_rules(query:str, top_k: int = TOP_K, threshold = THRESHOLD) -> str:
    """检索与查询最相关的文本。
    query: 查询词（自然语言或者关键词）
    top_k: 返回的文本块数量
    threshold: 相似度阈值
    返回：拼接后的规则相关文本，块之间用分隔线隔开
    """
    # 1.把查询词转换为向量
    query_embedding = _model.encode([query]).tolist()
    # 2. 在向量库中检索top_k
    results = _collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "distances"]
    )
    # 3.提取文本块
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    # 4.将距离转换为相似度分数，并进行过滤
    filtered = []
    for doc, dist in zip(documents, distances):
        similarity = 1 / (1 + dist)
        if similarity >= threshold:
            filtered.append(f"\n{doc}")
            #filtered.append(f"[相似度: {similarity:.2f}]\n{doc}")

    if not filtered:
        return "未找到足够相关的规则。"

    return "\n\n---\n\n".join(filtered)

def main():
    while True:
        query = input("\n 查询词(输入q退出)")
        if query.lower() == "q":
            break
        result = search_rules(query, TOP_K, THRESHOLD)
        print("\n" + "="*50)
        print(result)
        print("="*50)

if __name__ == "__main__":
    main()