import requests
import datetime
import time
import json

# ================= 配置区 (请修改以下信息) =================
# 1. 飞书机器人的 Webhook 地址
# 如何获取：飞书群 -> 设置 -> 群机器人 -> 添加 -> 自定义机器人 -> 复制 Webhook 地址
FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/09da27da-8f4d-42c3-94c2-0a3c8aea1677"

# 2. 搜索关键词
SEARCH_KEYWORD = "Cancer Immunotherapy"

# 3.每次获取的最大文献数量
MAX_RESULTS = 5
# ========================================================

def search_pubmed(keyword, max_results=5):
    """
    在 PubMed 搜索关键词，返回最新的文献 ID 列表
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": keyword,
        "retmode": "json",
        "retmax": max_results,
        "sort": "date" # 按日期排序
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        return id_list
    except Exception as e:
        print(f"[Error] PubMed 搜索失败: {e}")
        return []

def get_article_details(id_list):
    """
    根据文献 ID 获取详细信息（标题、链接、摘要片段）
    """
    if not id_list:
        return []

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    ids = ",".join(id_list)
    params = {
        "db": "pubmed",
        "id": ids,
        "retmode": "json"
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        result = data.get("result", {})
        
        articles = []
        for uid in id_list:
            if uid in result:
                item = result[uid]
                title = item.get("title", "No Title")
                # 获取作者列表，取前3个
                authors = [a.get("name", "") for a in item.get("authors", [])]
                author_str = ", ".join(authors[:3]) + ("..." if len(authors) > 3 else "")
                
                pub_date = item.get("pubdate", "")
                article_url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
                
                articles.append({
                    "title": title,
                    "authors": author_str,
                    "date": pub_date,
                    "url": article_url
                })
        return articles
    except Exception as e:
        print(f"[Error] 获取文献详情失败: {e}")
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
                "content": f"📄 **[{article['title']}]({article['url']})**"
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

    # 1. 搜索
    ids = search_pubmed(SEARCH_KEYWORD, MAX_RESULTS)
    if not ids:
        print("未找到相关文献。")
        return
    
    print(f"✅ 找到 {len(ids)} 篇最新文献 ID: {ids}")

    # 2. 获取详情
    articles = get_article_details(ids)
    
    # 3. 打印或发送
    if "YOUR_FEISHU_WEBHOOK" in FEISHU_WEBHOOK_URL:
        # 如果没配置 webhook，直接打印
        print("\n--- 预览模式 (未配置 Webhook) ---")
        for i, art in enumerate(articles, 1):
            print(f"{i}. {art['title']}")
            print(f"   Link: {art['url']}\n")
    else:
        # 发送飞书
        send_feishu_card(FEISHU_WEBHOOK_URL, SEARCH_KEYWORD, articles)

if __name__ == "__main__":
    main()
