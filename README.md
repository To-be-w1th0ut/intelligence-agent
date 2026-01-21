# Intelligence Agent 🚀

自动发现 GitHub Trending / Hacker News 热门项目，通过 AI 分析后推送至飞书/钉钉机器人。

## ✨ 功能特点

- 📥 **多源采集** - GitHub Trending、Hacker News
- 🤖 **AI 分析** - 使用 LLM 提取项目亮点、技术栈
- 📤 **多端推送** - 支持飞书、钉钉 Webhook 机器人
- ⏰ **定时调度** - 支持 cron 表达式定时执行
- 🎨 **富文本消息** - 精美的卡片式消息展示

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

### 飞书机器人

1. 打开飞书群 → 设置 → 群机器人 → 添加机器人
2. 选择「自定义机器人」
3. 复制 Webhook 地址到 `config.yaml`

### 钉钉机器人

1. 打开钉钉群 → 设置 → 智能群助手 → 添加机器人
2. 选择「自定义」机器人
3. 安全设置选择「加签」，复制 Secret
4. 复制 Webhook 地址和 Secret 到 `config.yaml`

## 🐳 Docker 部署

```bash
# 构建镜像
docker build -t intelligence-agent .

# 运行
docker run -v $(pwd)/config.yaml:/app/config.yaml intelligence-agent
```

