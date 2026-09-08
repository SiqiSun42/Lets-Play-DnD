import os
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
import readline

VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db")
TOP_K = 3
RERANK_THRESHOLD = 0.3
THRESHOLD = 0.5

_LANG_CONFIG = {
    "zh": {
        "model": "BAAI/bge-small-zh-v1.5",
        "rerank_model": "BAAI/bge-reranker-base",  # 新增
        "collection": "dnd_rules_zh",
        "empty": "未找到足够相关的规则。",
    },
    "en": {
        "model": "BAAI/bge-small-en-v1.5",
        "rerank_model": "BAAI/bge-reranker-base",  # 英文也可用这个
        "collection": "dnd_rules_en",
        "empty": "No sufficiently relevant rules found.",
    },
}

_client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
_models = {}
_collections = {}
_rerank_models = {}

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

def _get_rerank_model(lang_key: str):
    if lang_key not in _rerank_models:
        _rerank_models[lang_key] = CrossEncoder(_LANG_CONFIG[lang_key]["rerank_model"])
    return _rerank_models[lang_key]

# 检索函数
def search_rules(query:str, language: str = "zh-CN", top_k: int = TOP_K, threshold = THRESHOLD, rerank_threshold = RERANK_THRESHOLD, use_rerank: bool = False) -> str:
    """检索与查询最相关的文本。
    query: 查询词（自然语言或者关键词）
    language: 语言（zh-CN / en），决定用哪套模型和向量库
    top_k: 返回的文本块数量
    threshold: 相似度阈值
    rerank_threshold: Rerank分数阈值
    use_rerank: 是否使用CrossEncoder重排（默认False，节省性能）
    返回：拼接后的规则相关文本，块之间用分隔线隔开
    """
    # 1. 语言
    lang_key = _normalize_lang(language)
    _model = _get_model(lang_key)
    _collection = _get_collection(lang_key)

    # 2.把查询词转换为向量
    query_embedding = _model.encode([query]).tolist()

    if use_rerank:
        # 3. 初始检索更多候选（用top_k的3倍）
        initial_k = max(top_k * 3, 9)
        results = _collection.query(
            query_embeddings=query_embedding,
            n_results=initial_k,
            include=["documents", "distances"]
        )

        documents = results.get("documents", [[]])[0]

        # 4.Rerank排序
        rerank_model = _get_rerank_model(lang_key)
        rerank_scores = rerank_model.predict([[query, doc] for doc in documents])

        # 按rerank分数排序，取top_k
        ranked_docs = sorted(zip(documents, rerank_scores), key=lambda x: x[1], reverse=True)

        # 5.过滤低于阈值的文本块
        filtered = []
        for doc, score in ranked_docs[:top_k]:
            if score >= rerank_threshold:
                filtered.append(f"[Rerank分数: {score:.2f}]\n{doc}")
    else:
        # 原来的逻辑（向量检索，不rerank）
        results = _collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            include=["documents", "distances"]
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # 直接返回top_k即可
        filtered = []
        for doc, dist in zip(documents, distances):
            similarity = 1 / (1 + dist) # 将 Chroma 返回的 L2 距离映射到 (0,1] 区间作为相似度分数。效果比余弦相似度好。
            if similarity >= threshold:
                filtered.append(f"[距离分数: {similarity:.2f}]\n{doc}")
    if not filtered:
        return _LANG_CONFIG[lang_key]["empty"]

    return "\n\n---\n\n".join(filtered)

def main():
    while True:
        query = input("\n 查询词(输入q退出)")
        if query.lower() == "q":
            break
        result = search_rules(query, language="zh-CN", top_k=TOP_K, threshold=THRESHOLD, rerank_threshold=RERANK_THRESHOLD, use_rerank=True)
        print("\n" + "="*50)
        print(result)
        print("="*50)

if __name__ == "__main__":
    main()