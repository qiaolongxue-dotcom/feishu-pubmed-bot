import requests
import datetime
import time
import json

# ================= 配置区 (请修改以下信息) =================
# 1. 飞书机器人的 Webhook 地址
# 如何获取：飞书群 -> 设置 -> 群机器人 -> 添加 -> 自定义机器人 -> 复制 Webhook 地址
import os
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK", "你的默认备用地址")

# 2. 搜索关键词配置
# 将关键词拆分为列表，用于后续计算匹配度评分
KEYWORDS_LIST = [
    "Smooth muscle",
    "Phenotypic switching",
    "Endothelial cells",
    "Erectile dysfunction",
    "Cerium oxide nanozymes",
    "Diabetes"
]
# 自动生成 PubMed 查询语句 (逻辑 OR)
SEARCH_KEYWORD = "(" + " OR ".join([f'"{k}"' for k in KEYWORDS_LIST]) + ")"

# 3. 限制配置
MAX_FETCH_RESULTS = 50   # 每次API获取的候选池大小 (建议大一些，以便筛选出高匹配度的)
DAILY_LIMIT = 10         # 每日最大推送数量
HISTORY_FILE = "pubmed_history.json"  # 本地历史记录文件

# 4. 目标期刊列表 (泌尿外科教授关注的高分/核心期刊)
TARGET_JOURNALS = [
    "CA-A Cancer Journal for Clinicians",
    "New England Journal of Medicine",
    "The Lancet",
    "British Medical Journal",
    "Journal of the American Medical Association",
    "Nature Medicine",
    "Science Translational Medicine",
    "Cell Reports Medicine",
    "Cell",
    "Molecular Cancer",
    "Annual Review of Immunology",
    "Journal of Hepatology",
    "Molecular Neurodegeneration",
    "Cellular & Molecular Immunology",
    "Experimental & Molecular Medicine",
    "Immunity",
    "Molecular Biomedicine",
    "Journal of Biomedical Science",
    "Intensive Care Medicine",
    "Journal of Clinical Oncology",
    "European Urology",
    "Gastroenterology",
    "Journal of Neuroinflammation",
    "Journal of Allergy & Clinical Immunology",
    "Clinical Reviews in Allergy & Immunology",
    "Genome Medicine",
    "Diabetologia",
    "Journal of Translational Medicine",
    "Science",
    "Nature",
    "Nature Communications",
    "Science Advances",
    "Journal of Advanced Research",
    "National Science Review",
    "BMC Medicine",
    "Military Medical Research",
    "Cell Death & Differentiation",
    "Cell Research",
    "Science Bulletin",
    "Asian Journal of Pharmaceutical Sciences",
    "Acta Pharmacologica Sinica",
    "Translational Neurodegeneration",
    "Chinese Medical Journal",
    "Phenomics",
    "Nature Reviews Urology",
    "European Urology",
    "Journal of Clinical Oncology",
    "Cell Death & Disease",
    "Clinical Cancer Research",
    "Oncogene",
    "American Journal of Pathology",
    "Journal of Urology",
    "British Journal of Cancer",
    "Apoptosis"
]

# ================= 工具函数区 =================
import xml.etree.ElementTree as ET
import os

def load_history():
    """读取历史记录，处理每日限额"""
    today_str = datetime.date.today().isoformat()
    default_history = {"date": today_str, "count": 0, "sent_ids": []}
    
    if not os.path.exists(HISTORY_FILE):
        return default_history
        
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            # 如果日期不是今天，重置计数，但保留旧ID做去重（可选，这里为了简单只做本日去重/计数重置）
            # 也可以选择做全量去重，防止隔日重复推荐。这里策略是：长期去重。
            if history.get("date") != today_str:
                # 新的一天，重置计数，保留sent_ids以防止重复推荐旧文
                history["date"] = today_str
                history["count"] = 0
                # 如果 sent_ids 太大可以清理，这里暂且保留
            return history
    except Exception:
        return default_history

def save_history(history):
    """保存历史记录"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[Warning] 无法保存历史记录: {e}")


def search_pubmed(keyword, max_results=50):
    """
    在 PubMed 搜索关键词，并限定在 TARGET_JOURNALS 定义的期刊范围内
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    # 构建期刊限定查询语句: ("Journal A"[Journal] OR "Journal B"[Journal] ...)
    # 注意：如果期刊列表为空，则不进行筛选
    if TARGET_JOURNALS:
        journal_terms = [f'"{j}"[Journal]' for j in TARGET_JOURNALS]
        journal_query = " OR ".join(journal_terms)
        final_term = f"({keyword}) AND ({journal_query})"
    else:
        final_term = keyword

    print(f"🔍 正在检索 {len(TARGET_JOURNALS)} 本指定期刊...")

    params = {
        "db": "pubmed",
        "term": final_term,
        "retmode": "json",
        "retmax": max_results,
        "sort": "date" # 按日期排序
    }
    
    try:
        # 使用 POST 请求防止 URL 过长
        response = requests.post(base_url, data=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        return id_list
    except Exception as e:
        print(f"[Error] PubMed 搜索失败: {e}")
        return []

def get_details_and_rank(id_list):
    """
    使用 efetch 获取详细信息（含摘要），根据关键词匹配度排序
    """
    if not id_list:
        return []

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ids = ",".join(id_list)
    params = {
        "db": "pubmed",
        "id": ids,
        "retmode": "xml"  # 获取 XML 以便提取 Abstract
    }

    print("📥 正在下载文献详情并分析匹配度...")

    try:
        response = requests.post(base_url, data=params, timeout=30)
        response.raise_for_status()
        
        # 解析 XML
        root = ET.fromstring(response.content)
        articles = []
        
        for pubmed_article in root.findall(".//PubmedArticle"):
            try:
                medline = pubmed_article.find("MedlineCitation")
                article = medline.find("Article")
                
                # 1. 基础信息
                pmid = medline.find("PMID").text
                title = article.find("ArticleTitle").text or "No Title"
                
                # 2. 摘要提取
                abstract_text = ""
                abstract = article.find("Abstract")
                if abstract is not None:
                    # 摘要可能分段，合并所有 AbstractText
                    texts = [elem.text for elem in abstract.findall("AbstractText") if elem.text]
                    abstract_text = " ".join(texts)
                
                # 3. 作者
                author_list = article.find("AuthorList")
                authors = []
                if author_list is not None:
                    for au in author_list.findall("Author"):
                        last = au.find("LastName")
                        initial = au.find("Initials")
                        name = ""
                        if last is not None: name += last.text
                        if initial is not None: name += " " + initial.text
                        if name: authors.append(name)
                
                author_str = ", ".join(authors[:3]) + ("..." if len(authors) > 3 else "")
                
                # 4. 日期 (尝试获取 PubDate)
                journal_issue = article.find("Journal/JournalIssue/PubDate")
                pub_date = "Unknown Date"
                if journal_issue is not None:
                    year = journal_issue.find("Year")
                    month = journal_issue.find("Month")
                    if year is not None:
                        pub_date = year.text
                        if month is not None: pub_date += f"-{month.text}"

                # 5. 计算匹配度分数
                # 组合标题和摘要进行检索
                full_text = (title + " " + abstract_text).lower()
                score = 0
                matched_keywords = []
                for kw in KEYWORDS_LIST:
                    if kw.lower() in full_text:
                        score += 1
                        matched_keywords.append(kw)
                
                article_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                
                articles.append({
                    "id": pmid,
                    "title": title,
                    "authors": author_str,
                    "date": pub_date,
                    "url": article_url,
                    "score": score,
                    "matches": matched_keywords
                })
                
            except Exception as e:
                # 单个文章解析失败不影响整体
                continue

        # 排序：优先按分数（降序），其次按日期（如果不规范则忽略），最后原序
        # 这里主要按分数降序
        articles.sort(key=lambda x: x["score"], reverse=True)
        return articles

    except Exception as e:
        print(f"[Error] 获取/解析文献详情失败: {e}")
        return []

def send_feishu_card(webhook_url, keyword, articles):
    """
    发送飞书交互式卡片消息
    """
    if not articles:
        print("没有文章需要发送。")
        return

    # 构建卡片内容
    elements = []
    for article in articles:
        # 文章标题 + 链接
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"📄 **[{article['title']}]({article['url']})**\nCorrelation Score: {article['score']} 🔥"
            }
        })
        # 作者和日期
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"👤 作者: {article['authors']}\n📅 日期: {article['date']}"
            }
        })
        # 分割线
        elements.append({"tag": "hr"})

    # 飞书卡片结构
    card_content = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "blue",
                "title": {
                    "content": f"🔬 PubMed 最新文献推送: {keyword}",
                    "tag": "plain_text"
                }
            },
            "elements": elements,
            "config": {
                "wide_screen_mode": True
            }
        }
    }

    try:
        response = requests.post(webhook_url, json=card_content)
        response.raise_for_status()
        res_json = response.json()
        if res_json.get("code") == 0:
            print("✅ 飞书消息发送成功！")
        else:
            print(f"❌ 飞书发送失败: {res_json}")
    except Exception as e:
        print(f"[Error] Webhook 调用异常: {e}")

def main():
    print(f"🚀 开始运行 PubMed 监控脚本...")
    print(f"🔍 关键词: {SEARCH_KEYWORD}")
    
    # 0. 检查配置
    if "YOUR_FEISHU_WEBHOOK" in FEISHU_WEBHOOK_URL:
        print("⚠️  警告: 请先在脚本中配置 'FEISHU_WEBHOOK_URL' 才能发送消息。")
        print("   (本次运行仅会在控制台打印结果)")

    # 1. 检查今日额度
    history = load_history()
    today_count = history["count"]
    remaining_quota = DAILY_LIMIT - today_count
    
    print(f"📅 今日已推送: {today_count} 篇, 剩余额度: {remaining_quota} 篇")
    
    if remaining_quota <= 0:
        print("🚫 今日配额已用完，停止运行。")
        return

    # 2. 搜索 ID (获取多一点以便排序)
    ids = search_pubmed(SEARCH_KEYWORD, MAX_FETCH_RESULTS)
    if not ids:
        print("未找到相关文献。")
        return
    
    # 过滤掉已经发送过的 ID
    existing_ids = set(history["sent_ids"])
    new_ids = [uid for uid in ids if uid not in existing_ids]
    
    if not new_ids:
        print("所有搜索到的文献均已推送过。")
        return

    print(f"✅ 找到 {len(new_ids)} 篇未推送的候选文献，准备获取详情并排序...")

    # 3. 获取详情并根据关键词匹配度排序
    ranked_articles = get_details_and_rank(new_ids)
    
    # 4. 截取 Top N (不超过剩余配额)
    final_articles = ranked_articles[:remaining_quota]
    
    if not final_articles:
        print("没有可发送的文章。")
        return

    print(f"🔝 精选 Top {len(final_articles)} 篇 (按关键词匹配度):")
    for art in final_articles:
        print(f"   [{art['score']}pts] {art['title'][:50]}...")

    # 5. 发送 或 打印
    if "YOUR_FEISHU_WEBHOOK" in FEISHU_WEBHOOK_URL:
        # 如果没配置 webhook，直接打印
        print("\n--- 预览模式 (未配置 Webhook) ---")
        for i, art in enumerate(final_articles, 1):
            print(f"{i}. [Score:{art['score']}] {art['title']}")
            print(f"   Link: {art['url']}\n")
    else:
        # 发送飞书
        send_feishu_card(FEISHU_WEBHOOK_URL, " | ".join(KEYWORDS_LIST[:2])+"...", final_articles)
        
        # 6. 更新历史记录
        history["count"] += len(final_articles)
        # 将新发送的 ID 加入历史，防止重复
        # 注意：这里我们只保留 ID，如果文件过大可以考虑清理旧 ID，目前暂不处理
        history["sent_ids"].extend([art["id"] for art in final_articles])
        save_history(history)
        print("💾 历史记录已更新。")

if __name__ == "__main__":
    main()

