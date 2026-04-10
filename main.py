import json
import datetime
import requests
import feedparser
import google.generativeai as genai
import time
import os

def load_config():
    """設定を読み込む（環境変数を優先、なければconfig.json）"""
    config_file_data = {}
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config_file_data = json.load(f)
    except Exception as e:
        print(f"Warning: Could not read config.json: {e}")

    # 環境変数 (GitHub Secrets) を優先し、なければ config.json から取得
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL") or config_file_data.get("discord_webhook_url")
    gemini_key = os.environ.get("GEMINI_API_KEY") or config_file_data.get("gemini_api_key")
    gemini_model = os.environ.get("GEMINI_MODEL") or config_file_data.get("gemini_model") or "gemini-1.5-flash"
    
    # RSSのURLリスト
    rss_config = config_file_data.get("rss", {
        "zenn": "https://zenn.dev/topics/game/feed",
        "reddit": "https://www.reddit.com/r/gamedev/.rss",
        "qiita": "https://qiita.com/tags/game/feed"
    })

    return webhook_url, gemini_key, gemini_model, rss_config

def get_rss_items(source_name, url, limit=40):
    """RSSから記事情報を取得する"""
    feed = feedparser.parse(url)
    items = []
    if not feed.entries:
        return []
        
    for entry in feed.entries[:limit]:
        items.append({
            "source": source_name,
            "title": getattr(entry, 'title', 'No Title'),
            "link": getattr(entry, 'link', '')
        })
    return items

def summarize_with_gemini(api_key, model_name, articles):
    """Gemini APIを使用して選別・要約を行う"""
    genai.configure(api_key=api_key)
    
    print(f"Using model: {model_name}")
    
    # 文字列のリスト内包表記での f-string 修正
    article_text = "\n".join([f"- [{a['source']}] {a['title']} (URL: {a['link']})" for a in articles])
    
    prompt = f"""
あなたは世界最高峰のゲーム開発ニュース編集者です。
以下の大量の記事リストから、ゲーム開発者にとって極めて重要、あるいは刺激的なものを「ちょうど15件」厳選し、読者の注目ポイントを明確にして出力してください。

## 出力形式 (必ず以下のマークダウンを厳守し、各記事の間には空行を入れてください):
# [目を引く魅力的なタイトルにリライト]
> (出典: [ソース名])
-# [内容の要約と、開発者が注目すべきポイントを2〜3文で簡潔に。]
[URL]

## 記述ルール:
- タイトルには `# ` を使い、見出しとして目立たせてください。
- 出典には `> ` を使い、引用形式にしてください。
- 要約には `-# ` を使い、サブテキスト（小文字）として記述してください。
- 全体のトーンはプロフェッショナルかつ熱量のあるものにすること。

## 記事リスト:
{article_text}
"""
    
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        return response.text if response and response.text else "Geminiからの応答が空でした。"
    except Exception as e:
        return f"Gemini API実行エラー: {e}"

def split_message(text, limit=1900):
    """メッセージをDiscordの制限内に分割する"""
    chunks = []
    lines = text.split('\n')
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def post_to_discord(webhook_url, content):
    """Discordに投稿する（分割投稿対応）"""
    chunks = split_message(content)
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        if total > 1:
            chunk = f"`Page {i}/{total}`\n" + chunk
        payload = {"content": chunk}
        response = requests.post(webhook_url, json=payload)
        if response.status_code not in [200, 204]:
            print(f"Failed to post chunk {i}. Status: {response.status_code}")
        if i < total:
            time.sleep(1)

def main():
    # 1. 設定読み込み
    webhook_url, gemini_key, gemini_model, rss_urls = load_config()
    
    if not webhook_url or not gemini_key:
        print("Error: Webhook URL or Gemini API Key is missing.")
        return

    # 2. 情報を取得
    print("Fetching articles...")
    all_articles = []
    for name, url in rss_urls.items():
        all_articles.extend(get_rss_items(name.capitalize(), url))

    if not all_articles:
        print("Error: No articles found.")
        return

    # 3. Geminiで選別・要約
    print(f"Analyzing {len(all_articles)} articles. Selecting top 15 using {gemini_model}...")
    summary_report = summarize_with_gemini(gemini_key, gemini_model, all_articles)

    # 4. メッセージ整形
    today = datetime.date.today().strftime("%Y-%m-%d")
    full_content = f"📰 **AI厳選：今日のゲーム開発トレンド Top 15（{today}）**\n\n" + summary_report

    # 5. Discordに投稿
    print("Posting to Discord...")
    post_to_discord(webhook_url, full_content)

if __name__ == "__main__":
    main()
