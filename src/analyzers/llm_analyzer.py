"""LLM-based project analyzer."""

from dataclasses import dataclass
from typing import Optional, Union

from openai import OpenAI

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
    
    SYSTEM_PROMPT = """你是一个技术项目分析专家。你的任务是分析开源项目或技术文章，提取关键信息。
请用简洁的中文回复，格式如下：

## 摘要
[1-2句话描述这个项目/文章做什么]

## 亮点
- [亮点1]
- [亮点2]
- [亮点3]

## 技术栈
[列出主要技术，用逗号分隔]

## 适合人群
[这个项目适合什么样的开发者/用户]

## 发展潜力
[简短评估其发展前景]
"""

    def __init__(self, config: AnalyzerConfig):
        self.config = config
        self.client = None
        if config.enabled and config.api_key:
            self.client = OpenAI(
                api_key=config.api_key,
                base_url=config.api_base if config.api_base else None,
            )
    
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
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        
        content = response.choices[0].message.content
        
        # Parse response
        analysis = self._parse_llm_response(content)
        
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
        """Build prompt for GitHub project."""
        return f"""请分析这个 GitHub 项目：

项目名称：{project.name}
项目地址：{project.url}
描述：{project.description or '无'}
编程语言：{project.language or '未知'}
Star 数：{project.stars:,}
今日新增 Star：{project.stars_today:,}
Fork 数：{project.forks:,}
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
            elif line.startswith("## 亮点"):
                current_section = "highlights"
            elif line.startswith("## 技术栈"):
                current_section = "tech_stack"
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
                elif current_section in ("summary", "target_audience", "potential"):
                    if result[current_section]:
                        result[current_section] += " " + line
                    else:
                        result[current_section] = line
        
        return result
    
    def _basic_analysis(
        self, 
        project: Union[GitHubProject, HNStory]
    ) -> ProjectAnalysis:
        """Create basic analysis without LLM."""
        if isinstance(project, GitHubProject):
            return ProjectAnalysis(
                title=project.name,
                url=project.url,
                source="github",
                summary=project.description or "无描述",
                highlights=[f"⭐ {project.stars:,} Stars", f"📈 今日 +{project.stars_today}"],
                tech_stack=[project.language] if project.language else [],
                target_audience="开发者",
                potential="待分析",
                raw_data={"name": project.name, "stars": project.stars},
            )
        else:
            return ProjectAnalysis(
                title=project.title,
                url=project.url or project.hn_url,
                source="hackernews",
                summary=project.title,
                highlights=[f"🔥 {project.score} 分", f"💬 {project.comments} 评论"],
                tech_stack=[],
                target_audience="技术社区",
                potential="待分析",
                raw_data={"title": project.title, "score": project.score},
            )
