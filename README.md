# Intelligence Agent 🤖

**AI 驱动的智能信息聚合机器人** - 自动监控 GitHub Trending、Hacker News 热门项目，通过 LLM 深度分析后推送至飞书/钉钉。支持关键词过滤、定时任务、WebSocket 交互式聊天。

## ✨ 核心特性

- 🔥 **智能采集** - GitHub Trending 多语言监控、Hacker News 首页热榜
- 🧠 **AI 深度分析** - 使用 GPT-4 / Claude / GLM-4 提取项目亮点、技术栈、应用场景
- 💬 **交互式聊天** - 飞书 WebSocket 机器人，支持 @机器人 实时问答
- 📊 **关键词过滤** - 自定义关键词，只推送你关注的技术领域
- 📢 **多端推送** - 飞书、钉钉 Webhook 机器人，支持富文本卡片
- ⏰ **定时调度** - Cron 表达式配置，每日定时推送技术趋势
- 🐳 **开箱即用** - Docker 一键部署，配置简单，5 分钟即可运行

## 🚀 快速开始

### 1. 安装依赖

```bash
cd intelligence-agent
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置模板
cp config.example.yaml config.yaml

# 编辑配置
vim config.yaml
```

配置项说明：

| 配置项 | 说明 |
|--------|------|
| `collectors.github.languages` | 关注的编程语言 |
| `collectors.github.since` | 时间范围：daily/weekly/monthly |
| `analyzer.api_key` | OpenAI API Key |
| `notifiers.feishu.webhook_url` | 飞书机器人 Webhook |
| `notifiers.dingtalk.webhook_url` | 钉钉机器人 Webhook |

### 3. 运行

```bash
# 单次运行
python -m src.main run

# 试运行（不发送通知）
python -m src.main run --dry-run

# 测试采集器
python -m src.main test-collector --collector github

# 测试通知
python -m src.main test-notify

# 定时运行
python -m src.main schedule
```

## 📱 机器人配置指南

### 方式一：飞书 WebSocket 机器人（推荐，支持交互聊天）

1. 访问 [飞书开放平台](https://open.feishu.cn/app)，创建应用
2. 启用「机器人」能力，获取 App ID 和 App Secret
3. 配置权限 -> `im:message` 和 `im:message:group_at_msg`
4. 发布应用，在飞书中搜索并添加机器人到群聊
5. 在 `config.yaml` 中配置 `app_id` 和 `app_secret`
6. 运行 `python -m src.main chat` 启动交互模式

### 方式二：飞书 Webhook 机器人（简单推送）

1. 打开飞书群 → 设置 → 群机器人 → 添加机器人
2. 选择「自定义机器人」
3. 复制 Webhook 地址到 `config.yaml`

### 方式三：钉钉机器人

1. 打开钉钉群 → 设置 → 智能群助手 → 添加机器人
2. 选择「自定义」机器人
3. 安全设置选择「加签」，复制 Secret
4. 复制 Webhook 地址和 Secret 到 `config.yaml`

## 🐳 Docker 部署

```bash
# 克隆仓库
git clone https://github.com/To-be-w1th0ut/intelligence-agent.git
cd intelligence-agent

# 配置文件
cp config.example.yaml config.yaml
vim config.yaml

# 构建镜像
docker build -t intelligence-agent .

# 运行（定时推送模式）
docker run -v $(pwd)/config.yaml:/app/config.yaml intelligence-agent schedule

# 运行（交互聊天模式）
docker run -v $(pwd)/config.yaml:/app/config.yaml intelligence-agent chat
```

## 📋 使用场景

- 📰 **每日技术趋势** - 每天早上自动推送 GitHub 热门项目
- 🎯 **技术栈追踪** - 关注特定技术（如 AI、区块链、Web3）的最新动态
- 💼 **团队情报共享** - 在团队群中分享行业热点和开源项目
- 🔬 **竞品监控** - 监控竞争对手或相关领域的开源项目
- 🤖 **智能问答** - @飞书机器人 实时询问技术问题

## 🛠️ 技术栈

- **采集**: requests, BeautifulSoup4
- **分析**: OpenAI SDK (支持 GPT-4/Claude/GLM-4 等多种模型)
- **推送**: 飞书开放平台 SDK, 钉钉机器人 API
- **调度**: APScheduler (Cron 表达式)
- **部署**: Docker, Docker Compose

## 📝 配置示例

```yaml
collectors:
  github:
    enabled: true
    languages: [python, typescript, go, rust]
    since: daily  # daily/weekly/monthly
    limit: 10
    keywords: [AI, LLM, agent]  # 可选：关键词过滤

analyzer:
  enabled: true
  api_key: ${OPENAI_API_KEY}
  api_base: https://api.openai.com/v1  # 或中转 API
  model: gpt-4o-mini

schedule:
  enabled: true
  cron: "0 9 * * *"  # 每天早上 9 点

notifiers:
  feishu:
    enabled: true
    app_id: your_app_id
    app_secret: your_app_secret
```

