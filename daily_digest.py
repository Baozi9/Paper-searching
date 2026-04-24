from __future__ import annotations

import html
import json
import os
import re
import textwrap
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "sent_items.json"
REPORT_DIR = ROOT / "reports"
REPORT_FILE = REPORT_DIR / "latest.md"

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "3"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "20"))
REQUEST_TIMEOUT = 25

RSS_FEEDS = {
    "Nature": ["https://www.nature.com/nature.rss"],
    "Nature Methods": ["https://www.nature.com/nmeth.rss"],
    "Nature Biotechnology": ["https://www.nature.com/nbt.rss"],
    "Nature Medicine": ["https://www.nature.com/nm.rss"],
    "Nature Communications": ["https://www.nature.com/ncomms.rss"],
    "Science": ["https://www.science.org/action/showFeed?feed=rss&jc=science&type=etoc"],
    "Science Advances": ["https://www.science.org/action/showFeed?feed=rss&jc=sciadv&type=etoc"],
    "Cell": ["https://www.cell.com/cell/inpress.rss", "https://www.cell.com/cell/current.rss"],
    "Cell Reports": ["https://www.cell.com/cell-reports/inpress.rss", "https://www.cell.com/cell-reports/current.rss"],
    "Cell Metabolism": ["https://www.cell.com/cell-metabolism/inpress.rss", "https://www.cell.com/cell-metabolism/current.rss"],
    "Cancer Cell": ["https://www.cell.com/cancer-cell/inpress.rss", "https://www.cell.com/cancer-cell/current.rss"],
    "Immunity": ["https://www.cell.com/immunity/inpress.rss", "https://www.cell.com/immunity/current.rss"],
    "Neuron": ["https://www.cell.com/neuron/inpress.rss", "https://www.cell.com/neuron/current.rss"],
    "Molecular Cell": ["https://www.cell.com/molecular-cell/inpress.rss", "https://www.cell.com/molecular-cell/current.rss"],
}

PUBMED_JOURNALS = [
    "Nature",
    "Nature methods",
    "Nature biotechnology",
    "Nature medicine",
    "Nature communications",
    "Science",
    "Science advances",
    "Cell",
    "Cell reports",
    "Cell metabolism",
    "Cancer cell",
    "Immunity",
    "Neuron",
    "Molecular cell",
]

HEADERS = {
    "User-Agent": "paper-wechat-digest/1.0 (+https://github.com/) Mozilla/5.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


@dataclass
class Paper:
    title: str
    journal: str
    published: str
    link: str
    abstract: str = ""
    doi: str = ""
    source: str = "rss"
    ai_summary: str = ""

    @property
    def key(self) -> str:
        if self.doi:
            return self.doi.lower().strip()
        if self.link:
            return self.link.strip()
        return re.sub(r"\s+", " ", self.title.lower()).strip()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_doi(*values: str) -> str:
    pattern = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
    for value in values:
        if not value:
            continue
        match = pattern.search(value)
        if match:
            return match.group(0).rstrip(".);").lower()
    return ""


def parse_entry_date(entry) -> datetime | None:
    for field in ("published", "updated", "created"):
        value = entry.get(field)
        if value:
            try:
                dt = date_parser.parse(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def is_recent(dt: datetime | None) -> bool:
    if dt is None:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)


def get_keywords() -> list[str]:
    raw = os.getenv("KEYWORDS", "").strip()
    if not raw:
        return []
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def passes_keywords(paper: Paper, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = f"{paper.title} {paper.abstract} {paper.journal}".lower()
    return any(keyword in text for keyword in keywords)


def likely_research_article(title: str) -> bool:
    bad_prefixes = (
        "editorial",
        "correction",
        "erratum",
        "retraction",
        "news",
        "podcast",
        "this week in",
        "research highlight",
        "comment",
        "perspective",
    )
    lower = title.lower().strip()
    return not any(lower.startswith(prefix) for prefix in bad_prefixes)


def fetch_rss_papers() -> list[Paper]:
    papers: list[Paper] = []
    for journal, urls in RSS_FEEDS.items():
        for url in urls:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                if resp.status_code >= 400:
                    print(f"[WARN] RSS failed {journal}: {resp.status_code} {url}")
                    continue
                feed = feedparser.parse(resp.content)
            except Exception as exc:
                print(f"[WARN] RSS exception {journal}: {exc}")
                continue

            for entry in feed.entries[:50]:
                title = clean_text(entry.get("title"))
                if not title or not likely_research_article(title):
                    continue
                abstract = clean_text(entry.get("summary") or entry.get("description"))
                link = entry.get("link", "")
                published_dt = parse_entry_date(entry)
                if not is_recent(published_dt):
                    continue
                published = published_dt.date().isoformat() if published_dt else clean_text(entry.get("published"))
                doi = extract_doi(link, abstract, title)
                papers.append(Paper(title=title, journal=journal, published=published, link=link, abstract=abstract, doi=doi, source="rss"))
    return papers


def pubmed_query() -> str:
    end = datetime.now().date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    journal_part = " OR ".join(f'"{j}"[Journal]' for j in PUBMED_JOURNALS)
    date_part = f'("{start:%Y/%m/%d}"[Date - Publication] : "{end:%Y/%m/%d}"[Date - Publication])'
    return f"({journal_part}) AND {date_part}"


def fetch_pubmed_ids() -> list[str]:
    query = pubmed_query()
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": "80",
        "sort": "pub+date",
    }
    api_key = os.getenv("NCBI_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key
    try:
        resp = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        print(f"[WARN] PubMed search failed: {exc}")
        return []


def text_from(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return clean_text(" ".join(elem.itertext()))


def fetch_pubmed_papers() -> list[Paper]:
    ids = fetch_pubmed_ids()
    if not ids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
    }
    api_key = os.getenv("NCBI_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key
    try:
        resp = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print(f"[WARN] PubMed fetch failed: {exc}")
        return []

    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        title = text_from(article.find(".//ArticleTitle"))
        journal = text_from(article.find(".//Journal/Title"))
        abstract = clean_text(" ".join(text_from(x) for x in article.findall(".//Abstract/AbstractText")))
        pmid = text_from(article.find(".//PMID"))
        doi = ""
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType", "").lower() == "doi":
                doi = clean_text(aid.text)
        year = text_from(article.find(".//JournalIssue/PubDate/Year"))
        month = text_from(article.find(".//JournalIssue/PubDate/Month"))
        day = text_from(article.find(".//JournalIssue/PubDate/Day"))
        published = " ".join(x for x in [year, month, day] if x) or datetime.now().date().isoformat()
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
        if title and likely_research_article(title):
            papers.append(Paper(title=title, journal=journal or "PubMed", published=published, link=link, abstract=abstract, doi=doi, source="pubmed"))
    return papers


def dedupe(papers: Iterable[Paper]) -> list[Paper]:
    seen: set[str] = set()
    result: list[Paper] = []
    for paper in papers:
        key = paper.key
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"sent_keys": []}
    return {"sent_keys": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_with_llm(paper: Paper) -> str:
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if not (base_url and api_key and model):
        return ""

    prompt = f"""
你是科研文献助理。请根据论文标题和摘要，用中文输出 4 行，避免夸大，不要编造。
格式：
一句话总结：...
新技术/新方法：...
新研究内容：...
科研灵感：...

标题：{paper.title}
期刊：{paper.journal}
摘要：{paper.abstract[:2500]}
""".strip()

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出中文精简分析。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return clean_text(data["choices"][0]["message"]["content"])
    except Exception as exc:
        print(f"[WARN] LLM summary failed for {paper.title[:60]}: {exc}")
        return ""


def simple_takeaway(paper: Paper) -> str:
    if paper.abstract:
        return textwrap.shorten(paper.abstract, width=260, placeholder="...")
    return "暂无摘要。建议点开原文查看。"


def build_report(papers: list[Paper], keywords: list[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 今日 CNS 文献简报",
        "",
        f"生成时间：{now}",
        f"检索范围：近 {LOOKBACK_DAYS} 天",
        f"关键词：{', '.join(keywords) if keywords else '未设置，收集全部候选论文'}",
        f"新增论文：{len(papers)} 篇",
        "",
    ]

    if not papers:
        lines.append("今天没有筛选到新的候选论文。")
        return "\n".join(lines)

    for idx, paper in enumerate(papers, 1):
        lines.extend([
            f"## {idx}. {paper.title}",
            "",
            f"- 期刊：{paper.journal}",
            f"- 日期：{paper.published or '未知'}",
            f"- DOI：{paper.doi or '未获取'}",
            f"- 来源：{paper.source}",
            f"- 链接：{paper.link}",
            "",
        ])
        if paper.ai_summary:
            lines.extend([paper.ai_summary, ""])
        else:
            lines.extend([f"摘要精简：{simple_takeaway(paper)}", ""])
    return "\n".join(lines)


def push_serverchan(title: str, markdown: str) -> None:
    sendkey = os.getenv("SERVERCHAN_SENDKEY", "").strip()
    if not sendkey:
        return
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = {"title": title, "desp": markdown[:32000]}
    resp = requests.post(url, data=data, timeout=REQUEST_TIMEOUT)
    print(f"[INFO] ServerChan response: {resp.status_code} {resp.text[:200]}")


def push_wecom(markdown: str) -> None:
    webhook = os.getenv("WECOM_WEBHOOK", "").strip()
    if not webhook:
        return
    # WeCom markdown message content length is limited, so keep it short.
    content = markdown[:3900]
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    resp = requests.post(webhook, json=payload, timeout=REQUEST_TIMEOUT)
    print(f"[INFO] WeCom response: {resp.status_code} {resp.text[:200]}")


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    keywords = get_keywords()
    state = load_state()
    sent_keys = set(state.get("sent_keys", []))

    print("[INFO] Fetching RSS papers...")
    papers = fetch_rss_papers()
    print(f"[INFO] RSS candidates: {len(papers)}")

    # Be polite to NCBI; this project only makes two PubMed calls per run.
    time.sleep(0.4)
    print("[INFO] Fetching PubMed papers...")
    papers.extend(fetch_pubmed_papers())
    print(f"[INFO] Total candidates before dedupe: {len(papers)}")

    papers = dedupe(papers)
    papers = [p for p in papers if passes_keywords(p, keywords)]
    papers = [p for p in papers if p.key not in sent_keys]
    papers = papers[:MAX_ITEMS]

    for paper in papers:
        paper.ai_summary = summarize_with_llm(paper)

    report = build_report(papers, keywords)
    REPORT_FILE.write_text(report, encoding="utf-8")

    if papers:
        title = f"今日 CNS 文献简报：{len(papers)} 篇新论文"
    else:
        title = "今日 CNS 文献简报：暂无新论文"
    push_serverchan(title, report)
    push_wecom(report)

    for paper in papers:
        sent_keys.add(paper.key)
    state["sent_keys"] = list(sent_keys)[-2000:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"[INFO] Done. New papers: {len(papers)}")


if __name__ == "__main__":
    main()
