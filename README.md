<h1 align="center">Let's Play DnD</h1>

<p align="center">
  <strong>在线体验：</strong>
  <a href="https://rosemarysun.com/letsplaydnd/">https://rosemarysun.com/letsplaydnd/</a>
</p>

## 描述

LetsPlayDnD 是一个基于 Web 的龙与地下城（D&D 5e）辅助跑团项目。玩家可以在浏览器中注册登录，使用**咨询城主**查询规则，并在**游戏存档**中进行带上下文的多轮对话。项目内置 RAG（检索增强生成）系统，支持中英文双语：界面语言与咨询语言可切换，游戏存档内部语言在创建时锁定。

本仓库主要供学习与参考；体验完整功能请优先使用上方在线实例。

当前功能以账号系统、UI 与咨询（Consult）流程为主；游戏主流程（`game_zh` / `game_en`）仍在开发中。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3、Flask |
| 前端 | 原生 HTML / CSS / JavaScript |
| 账号与存档 | SQLite（`account.db`、各存档 `chat.db`） |
| LLM | OpenAI 兼容 API（默认 DeepSeek），用户自带 API Key |
| RAG | Chroma、sentence-transformers、PyMuPDF |
| Embedding | `BAAI/bge-small-zh-v1.5`（中文）、`BAAI/bge-small-en-v1.5`（英文） |

## 技术说明

### 环境要求

- Python 3.10+
- 可访问 Hugging Face（下载 embedding 模型）
- 用户侧需配置可用的 DeepSeek（或兼容 OpenAI 的）API Key

### 安装

```bash
git clone <仓库地址>
cd LetsPlayDnD

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

预下载 RAG 模型（推荐，避免首次咨询时才下载）：

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); SentenceTransformer('BAAI/bge-small-en-v1.5'); print('ok')"
```

构建向量库（需自备中英文 D&D 规则书，修改 `RAG/build_index.py` 中的路径与集合名 `dnd_rules_zh` / `dnd_rules_en`，分别运行两次得到双语向量库。如果确认只使用一种语言，也可以仅运行一次）：

```bash
python RAG/build_index.py
```

### 配置

在项目根目录创建 `.env`（具体模型、是否使用thinking可自行调整）：

```env
FLASK_SECRET_KEY=用随机长字符串替换
DEEPSEEK_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_THINKING_ENABLED=true
DEEPSEEK_REASONING_EFFORT=medium
```

`FLASK_SECRET_KEY` 可用以下命令生成：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 启动

```bash
source venv/bin/activate
python server.py
```

默认监听 `http://0.0.0.0:5000`。浏览器访问 `http://localhost:5000/login.html` 注册或登录；API Key 在设置中由用户自行填写。

### 项目结构（概要）

```
server.py              Flask 入口
UI/                    前端静态资源
System/
  consult/             咨询城主逻辑
  game/                游戏存档逻辑（game.py 共享 IO，game_zh / game_en 流程）
  api_client.py        LLM 调用封装
RAG/                   索引构建与检索
Prompts/               提示词（consult / game）
Tools/                 Function calling 工具定义
Account/               用户数据（Git 忽略，仅 .gitkeep）
Templates/user/        新用户目录模板
```

## 注意事项

**部署路径**  
前端请求使用相对路径（如 `api/me`、`login.html`），便于挂在子路径下；不要在 JS 里写以 `/` 开头的绝对 URL。

**不要提交敏感与本地数据**  
`.gitignore` 已忽略 `.env`、`account.db`、`Account/*`（保留 `Account/.gitkeep`）、`RAG/vector_db/`。向量库与账号数据请勿提交到 Git。

**RAG 向量库不在 Git 里**  
中英文规则索引位于 `RAG/vector_db/`，需在本机运行 `RAG/build_index.py` 生成；仓库 clone 后不会自带向量库。

**Embedding 模型不在 requirements.txt 里**  
`pip install -r requirements.txt` 只安装 Python 包。首次使用 RAG 前需预下载模型（见下方「安装」），否则会在线拉取且较慢。

**小内存环境装依赖**  
`sentence-transformers` 依赖 PyTorch。若本机/服务器内存较小且无 Swap，`pip install` 可能在下载 torch 时被系统 `Killed`；可尝试增加 Swap 或先安装 CPU 版 torch。

**Chroma 单次写入上限**  
`build_index.py` 若一次 `add` 过多 chunk 会报错，需分批写入（例如每批 5000 条）。

**咨询 vs 游戏语言**  
主页/咨询城主界面语言随用户设置变化（若没有立刻改变，刷新生效）；游戏存档的 `in_game_language` 则在创建时确定，之后切换界面语言不会改变该存档内部的语言设置。

**密钥与 API Key**  
`FLASK_SECRET_KEY` 用于 Session 与用户 API Key 加密。更换密钥后，已存的加密 API Key 需用户在设置里重新填写。

**规则书 PDF**  
索引脚本需本地 PDF（版权原因不入库）。`build_index.py` 中的 PDF 路径请在本机自行配置，勿将个人路径提交到公开仓库。

**RAG 懒加载**  
`consult` 在真正检索时才 `import RAG`，避免打开咨询页就加载 embedding；同一进程内首次检索仍可能较慢。


如有问题或建议，欢迎通过 Issue 反馈。