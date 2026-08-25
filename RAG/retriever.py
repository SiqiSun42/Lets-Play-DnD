import os
from sentence_transformers import SentenceTransformer
import chromadb

VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db")
TOP_K = 3
THRESHOLD = 0.5

_LANG_CONFIG = {
    "zh": {
        "model": "BAAI/bge-small-zh-v1.5",
        "collection": "dnd_rules_zh",
        "empty": "未找到足够相关的规则。",
    },
    "en": {
        "model": "BAAI/bge-small-en-v1.5",
        "collection": "dnd_rules_en",
        "empty": "No sufficiently relevant rules found.",
    },
}

_client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
_models = {}
_collections = {}

def _normalize_lang(language: str) -> str:
    lang = (language or "zh-CN").lower()
    if lang.startswith("en"):
        return "en"
    return "zh"

def _get_model(lang_key: str):
    if lang_key not in _models:
        _models[lang_key] = SentenceTransformer(_LANG_CONFIG[lang_key]["model"])
    return _models[lang_key]

def _get_collection(lang_key: str):
    if lang_key not in _collections:
        _collections[lang_key] = _client.get_collection(
            _LANG_CONFIG[lang_key]["collection"]
        )
    return _collections[lang_key]

# 检索函数
def search_rules(query:str, language: str = "zh-CN", top_k: int = TOP_K, threshold = THRESHOLD) -> str:
    """检索与查询最相关的文本。
    query: 查询词（自然语言或者关键词）
    language: 语言（zh-CN / en），决定用哪套模型和向量库
    top_k: 返回的文本块数量
    threshold: 相似度阈值
    返回：拼接后的规则相关文本，块之间用分隔线隔开
    """
    # 1. 确定语言
    lang_key = _normalize_lang(language)
    _model = _get_model(lang_key)
    _collection = _get_collection(lang_key)

    # 2.把查询词转换为向量
    query_embedding = _model.encode([query]).tolist()

    # 3. 在向量库中检索top_k
    results = _collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "distances"]
    )

    # 4.提取文本块
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    # 5.将距离转换为相似度分数，并进行过滤
    filtered = []
    for doc, dist in zip(documents, distances):
        similarity = 1 / (1 + dist)
        if similarity >= threshold:
            filtered.append(f"\n{doc}")
            #filtered.append(f"[相似度: {similarity:.2f}]\n{doc}")

    if not filtered:
        return _LANG_CONFIG[lang_key]["empty"]

    return "\n\n---\n\n".join(filtered)

def main():
    while True:
        query = input("\n 查询词(输入q退出)")
        if query.lower() == "q":
            break
        result = search_rules(query, language="zh-CN", top_k=TOP_K, threshold=THRESHOLD)
        print("\n" + "="*50)
        print(result)
        print("="*50)

if __name__ == "__main__":
    main()