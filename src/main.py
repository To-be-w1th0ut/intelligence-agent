"""Intelligence Agent - Main entry point."""

import sys
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Config
from .collectors import GitHubCollector, HackerNewsCollector
from .analyzers import LLMAnalyzer
from .notifiers import FeishuNotifier, DingtalkNotifier
from .bot import FeishuBot

console = Console()


def run_pipeline(config: Config, dry_run: bool = False):
    """Run the full collection -> analysis -> notification pipeline."""
    console.print("\n[bold blue]🚀 Intelligence Agent Starting...[/bold blue]\n")
    
    all_projects = []
    
    # Step 1: Collect from GitHub
    if config.collectors.github.enabled:
        console.print("[yellow]📥 Collecting GitHub Trending...[/yellow]")
        with GitHubCollector(config.collectors.github) as collector:
            projects = collector.collect()
            console.print(f"   Found {len(projects)} projects")
            all_projects.extend(projects)
    
    # Step 2: Collect from Hacker News
    if config.collectors.hackernews.enabled:
        console.print("[yellow]📥 Collecting Hacker News...[/yellow]")
        with HackerNewsCollector(config.collectors.hackernews) as collector:
            stories = collector.collect()
            console.print(f"   Found {len(stories)} stories")
            all_projects.extend(stories)
    
    if not all_projects:
        console.print("[red]❌ No projects collected![/red]")
        return
    
    # Step 3: Analyze with LLM
    console.print("[yellow]🤖 Analyzing with AI...[/yellow]")
    analyzer = LLMAnalyzer(config.analyzer)
    analyses = analyzer.analyze(all_projects)
    console.print(f"   Analyzed {len(analyses)} items")
    
    # Display results
    _display_results(analyses)
    
    if dry_run:
        console.print("\n[yellow]⚠️ Dry run mode - skipping notifications[/yellow]")
        return
    
    # Step 4: Send notifications
    console.print("\n[yellow]📤 Sending notifications...[/yellow]")
    
    if config.notifiers.feishu.enabled:
        with FeishuNotifier(config.notifiers.feishu) as notifier:
            # Use Bot API if chat_id is configured, otherwise Webhook
            chat_id = config.notifiers.feishu.default_chat_id
            notifier.send(analyses, chat_id=chat_id)
    
    if config.notifiers.dingtalk.enabled:
        with DingtalkNotifier(config.notifiers.dingtalk) as notifier:
            notifier.send(analyses)
    
    console.print("\n[bold green]✅ Pipeline completed![/bold green]")


def _display_results(analyses):
    """Display analysis results in a table."""
    table = Table(title="📊 Analysis Results")
    table.add_column("Source", style="cyan")
    table.add_column("Title", style="green", max_width=40)
    table.add_column("Summary", max_width=50)
    
    for analysis in analyses[:10]:
        source_emoji = "🐙" if analysis.source == "github" else "📰"
        table.add_row(
            f"{source_emoji} {analysis.source}",
            analysis.title[:40],
            analysis.summary[:50] + "..." if len(analysis.summary) > 50 else analysis.summary,
        )
    
    console.print(table)


@click.group()
@click.option("--config", "-c", "config_path", help="Path to config file")
@click.pass_context
def cli(ctx, config_path: Optional[str]):
    """Intelligence Agent - Discover trending projects and get notified."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load(config_path)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Run without sending notifications")
@click.pass_context
def run(ctx, dry_run: bool):
    """Run the pipeline once."""
    config = ctx.obj["config"]
    run_pipeline(config, dry_run=dry_run)


@cli.command()
@click.pass_context
def schedule(ctx):
    """Run the pipeline on schedule."""
    config = ctx.obj["config"]
    
    if not config.schedule.enabled:
        console.print("[yellow]⚠️ Schedule not enabled in config[/yellow]")
        return
    
    scheduler = BlockingScheduler()
    
    # Parse cron expression
    cron_parts = config.schedule.cron.split()
    trigger = CronTrigger(
        minute=cron_parts[0],
        hour=cron_parts[1],
        day=cron_parts[2],
        month=cron_parts[3],
        day_of_week=cron_parts[4],
    )
    
    scheduler.add_job(
        run_pipeline,
        trigger,
        args=[config],
        id="intelligence_agent",
        name="Intelligence Agent Pipeline",
    )
    
    console.print(f"[green]🕐 Scheduled with cron: {config.schedule.cron}[/green]")
    console.print("[yellow]Press Ctrl+C to exit[/yellow]")
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped[/yellow]")


@cli.command()
@click.option("--collector", type=click.Choice(["github", "hackernews"]))
@click.pass_context
def test_collector(ctx, collector: Optional[str]):
    """Test collectors without full pipeline."""
    config = ctx.obj["config"]
    
    if collector == "github" or collector is None:
        console.print("[yellow]Testing GitHub collector...[/yellow]")
        with GitHubCollector(config.collectors.github) as c:
            projects = c.collect()
            for p in projects[:5]:
                console.print(f"  • {p.name} ⭐ {p.stars}")
    
    if collector == "hackernews" or collector is None:
        console.print("[yellow]Testing Hacker News collector...[/yellow]")
        with HackerNewsCollector(config.collectors.hackernews) as c:
            stories = c.collect()
            for s in stories[:5]:
                console.print(f"  • {s.title[:50]}... 🔥 {s.score}")


@cli.command()
@click.pass_context
def test_notify(ctx):
    """Send test notifications."""
    config = ctx.obj["config"]
    
    if config.notifiers.feishu.enabled:
        console.print("[yellow]Testing Feishu...[/yellow]")
        with FeishuNotifier(config.notifiers.feishu) as n:
            if n.send_test():
                console.print("[green]✅ Feishu test passed[/green]")
            else:
                console.print("[red]❌ Feishu test failed[/red]")
    
    if config.notifiers.dingtalk.enabled:
        console.print("[yellow]Testing DingTalk...[/yellow]")
        with DingtalkNotifier(config.notifiers.dingtalk) as n:
            if n.send_test():
                console.print("[green]✅ DingTalk test passed[/green]")
            else:
                console.print("[red]❌ DingTalk test failed[/red]")



@cli.command()
@click.pass_context
def chat(ctx):
    """Start the chat bot (Feishu WebSocket) with optional scheduler."""
    config = ctx.obj["config"]
    
    if not config.notifiers.feishu.app_id or not config.notifiers.feishu.app_secret:
        console.print("[red]❌ Feishu App ID and Secret required in config![/red]")
        return

    # Start Scheduler if enabled
    if config.schedule.enabled:
        console.print(f"[green]🕐 Starting Scheduler (Cron: {config.schedule.cron})[/green]")
        scheduler = BackgroundScheduler()
        
        # Parse cron expression
        cron_parts = config.schedule.cron.split()
        trigger = CronTrigger(
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4],
        )
        
        scheduler.add_job(
            run_pipeline,
            trigger,
            args=[config],
            id="intelligence_agent_bg",
            name="Intelligence Agent Daily Report",
        )
        scheduler.start()

    # Start Bot (Blocking)
    bot = FeishuBot(config)
    try:
        bot.start()
    except KeyboardInterrupt:
        if config.schedule.enabled:
            scheduler.shutdown()
        console.print("\n[yellow]Bot stopped[/yellow]")


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
