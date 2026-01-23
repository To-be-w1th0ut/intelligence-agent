"""LLM-based project analyzer."""

from dataclasses import dataclass
from typing import Optional, Union

from openai import OpenAI
import httpx

from ..config import AnalyzerConfig
from ..collectors.github import GitHubProject
from ..collectors.hackernews import HNStory


@dataclass
class ProjectAnalysis:
    """Analysis result for a project."""
    title: str
    url: str
    source: str  # "github" or "hackernews"
    summary: str
    highlights: list[str]  # Key innovation points
    tech_stack: list[str]
    target_audience: str
    potential: str  # Growth potential assessment
    raw_data: dict  # Original project data


class LLMAnalyzer:
    """Analyzes projects using LLM."""
    
    SYSTEM_PROMPT = """你是一个技术趋势分析专家。你的任务是分析开源项目，识别其真正的价值。
不要只是翻译 Readme，要思考：这个项目解决了什么核心问题？和现有方案比有什么不同？

请用简洁、专业的中文回复，格式如下：

## 摘要
[1-2句话描述核心功能，强调"解决了什么痛点"]

## 核心亮点
- [创新点 (如：比X快10倍，或支持Y特性)]
- [技术优势]
- [应用场景]

## 技术栈
[主要语言/框架]

## 竞品对比
[一句话对比同类项目 (如：类似 Lodash 但更轻量)]

## 适合人群
[谁最需要它？]

## 发展潜力
[简短评估：是玩具项目还是生产级神器？]
"""

    def __init__(self, config: AnalyzerConfig):
        self.config = config
        self.client = None
        if config.enabled and config.api_key:
            self.client = OpenAI(
                api_key=config.api_key,
                base_url=config.api_base if config.api_base else None,
                http_client=httpx.Client(http2=True),
            )
            # print(f"DEBUG: Initialized OpenAI Client with Base URL: {self.client.base_url}")
    
    def analyze_image(self, prompt: str, image_base64: str) -> str:
        """Analyze an image using the configured LLM model."""
        if not self.client:
            return "❌ AI Agent not configured"
            
        try:
            # Use configured model (GLM-4.7 supports multimodal according to docs)
            response = self.client.chat.completions.create(
                model=self.config.model,  # Use GLM-4.7 from config
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt or "请分析这张图片，告诉我图片中的内容"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.6,
                max_tokens=2048,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ Vision API Error: {e}")
            return f"图片分析失败: {str(e)}"

    def analyze(
        self, 
        projects: list[Union[GitHubProject, HNStory]]
    ) -> list[ProjectAnalysis]:
        """Analyze a list of projects."""
        if not self.config.enabled or not self.client:
            # Return basic analysis without LLM
            return [self._basic_analysis(p) for p in projects]
        
        results = []
        for project in projects:
            try:
                analysis = self._analyze_single(project)
                results.append(analysis)
            except Exception as e:
                print(f"Error analyzing project: {e}")
                results.append(self._basic_analysis(project))
        
        return results
    
    def _analyze_single(
        self, 
        project: Union[GitHubProject, HNStory]
    ) -> ProjectAnalysis:
        """Analyze a single project using LLM."""
        # Build prompt based on project type
        if isinstance(project, GitHubProject):
            user_prompt = self._build_github_prompt(project)
            source = "github"
            title = project.name
            url = project.url
            raw_data = {
                "name": project.name,
                "description": project.description,
                "language": project.language,
                "stars": project.stars,
                "stars_today": project.stars_today,
            }
        else:
            user_prompt = self._build_hn_prompt(project)
            source = "hackernews"
            title = project.title
            url = project.url or project.hn_url
            raw_data = {
                "title": project.title,
                "score": project.score,
                "comments": project.comments,
            }
        
        # Call LLM
        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=1024,
            )
        except Exception as api_error:
            print(f"  ❌ LLM API Error for {title}: {api_error}")
            raise
        
        # Debug: Print response object details
        content = response.choices[0].message.content if response.choices else ""
        if not content or len(content.strip()) < 10:
            print(f"  ⚠️ LLM returned empty for {title}, using fallback")
            return self._basic_analysis(project)
        
        # Parse response
        analysis = self._parse_llm_response(content or "")
        
        return ProjectAnalysis(
            title=title,
            url=url,
            source=source,
            summary=analysis.get("summary", ""),
            highlights=analysis.get("highlights", []),
            tech_stack=analysis.get("tech_stack", []),
            target_audience=analysis.get("target_audience", ""),
            potential=analysis.get("potential", ""),
            raw_data=raw_data,
        )
    
    def _build_github_prompt(self, project: GitHubProject) -> str:
        """Build prompt for GitHub project with README context."""
        readme_snippet = project.readme_content or "无详细说明"
        
        return f"""请深度分析这个 GitHub 项目：

项目名称：{project.name}
项目地址：{project.url}
描述：{project.description or '无'}
编程语言：{project.language or '未知'}
Star 数：{project.stars:,}
今日新增：{project.stars_today:,}

以下是 README 的前 3000 个字符：
---
{readme_snippet}
---

请忽略 README 中的安装步骤、贡献指南等无关信息，重点挖掘：核心功能、技术亮点、解决的痛点。
如果 README 内容太少或无关，请根据描述尽力分析。
"""

    def _build_hn_prompt(self, story: HNStory) -> str:
        """Build prompt for Hacker News story."""
        return f"""请分析这个 Hacker News 热门内容：

标题：{story.title}
链接：{story.url or '(Ask HN / Show HN)'}
得分：{story.score}
评论数：{story.comments}
HN 讨论：{story.hn_url}
"""

    def _parse_llm_response(self, content: str) -> dict:
        """Parse LLM response into structured data."""
        result = {
            "summary": "",
            "highlights": [],
            "tech_stack": [],
            "competitors": "",  # New field
            "target_audience": "",
            "potential": "",
        }
        
        current_section = None
        lines = content.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("## 摘要"):
                current_section = "summary"
            elif line.startswith("## 核心亮点") or line.startswith("## 亮点"):
                current_section = "highlights"
            elif line.startswith("## 技术栈"):
                current_section = "tech_stack"
            elif line.startswith("## 竞品对比"):
                current_section = "competitors"
            elif line.startswith("## 适合人群"):
                current_section = "target_audience"
            elif line.startswith("## 发展潜力"):
                current_section = "potential"
            elif current_section:
                if current_section == "highlights":
                    if line.startswith("- "):
                        result["highlights"].append(line[2:])
                elif current_section == "tech_stack":
                    # Split by comma
                    techs = [t.strip() for t in line.split(",") if t.strip()]
                    result["tech_stack"].extend(techs)
                elif current_section in ("summary", "competitors", "target_audience", "potential"):
                    if current_section == "competitors" and result["competitors"]:
                         result["competitors"] += " " + line
                    elif result[current_section]:
                        result[current_section] += " " + line
                    else:
                        result[current_section] = line
        
        return result
    
    def _basic_analysis(
        self, 
        project: Union[GitHubProject, HNStory]
    ) -> ProjectAnalysis:
        """Create basic analysis without LLM - try to generate Chinese summary."""
        if isinstance(project, GitHubProject):
            # Try to generate a simple Chinese summary
            summary = self._generate_basic_chinese_summary(project)
            
            # Infer potential based on stars
            if project.stars >= 10000:
                potential = "🌟 成熟项目，社区活跃"
            elif project.stars >= 1000:
                potential = "📈 快速成长中"
            elif project.stars_today >= 100:
                potential = "🔥 新星项目，值得关注"
            else:
                potential = "🌱 早期项目"
            
            # Infer audience based on language
            lang = project.language or ""
            if lang.lower() in ["python", "jupyter notebook"]:
                audience = "AI/数据开发者"
            elif lang.lower() in ["typescript", "javascript"]:
                audience = "前端/全栈开发者"
            elif lang.lower() in ["go", "rust"]:
                audience = "后端/基础设施开发者"
            else:
                audience = "开发者"
            
            return ProjectAnalysis(
                title=project.name,
                url=project.url,
                source="github",
                summary=summary,
                highlights=[f"⭐ {project.stars:,} Stars", f"📈 今日 +{project.stars_today}"],
                tech_stack=[project.language] if project.language else [],
                target_audience=audience,
                potential=potential,
                raw_data={"name": project.name, "stars": project.stars},
            )
        else:
            # Hacker News story
            if project.score >= 500:
                potential = "🔥 热门话题"
            elif project.score >= 100:
                potential = "📈 值得一读"
            else:
                potential = "🌱 新鲜资讯"
                
            return ProjectAnalysis(
                title=project.title,
                url=project.url or project.hn_url,
                source="hackernews",
                summary=project.title,
                highlights=[f"🔥 {project.score} 分", f"💬 {project.comments} 评论"],
                tech_stack=[],
                target_audience="技术社区",
                potential=potential,
                raw_data={"title": project.title, "score": project.score},
            )
    
    def _generate_basic_chinese_summary(self, project: GitHubProject) -> str:
        """Generate a Chinese summary for a project using local translation."""
        lang = project.language or "开源"
        
        if not project.description:
            return f"一个 {lang} 项目，⭐ {project.stars:,}，今日 +{project.stars_today}"
        
        description = project.description
        
        # Check if description is already Chinese (contains CJK characters)
        def contains_chinese(text):
            return any('\u4e00' <= char <= '\u9fff' for char in text)
        
        if contains_chinese(description):
            return f"[{lang}] {description}"
        
        # Try local translation
        try:
            import translators as ts
            translated = ts.translate_text(
                description[:200],  # Limit length for speed
                translator='bing',  # Use Bing (fast and reliable)
                from_language='en',
                to_language='zh-CN'
            )
            if translated:
                return f"[{lang}] {translated}"
        except Exception as e:
            print(f"  ⚠️ Translation failed: {e}")
        
        # Ultimate fallback: English with language tag
        return f"[{lang}] {description}"
