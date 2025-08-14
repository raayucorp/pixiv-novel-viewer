import json
import traceback
from urllib.parse import quote
import atexit
import time
import asyncio # Flaskとrequests-html/seleniumの非同期処理の互換性のために必要

import requests
from flask import Flask, render_template, request, redirect, url_for
from bs4 import BeautifulSoup

# selenium関連のライブラリをインポート
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
# ↓↓↓ 前回追加し忘れたimport文 ↓↓↓
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


app = Flask(__name__)

# --- 定数定義 ---
SEARCH_API_URL = "https://www.pixiv.net/ajax/search/novels/{}?word={}&order=date_d&mode=all&p={}"
NOVEL_PAGE_URL = "https://www.pixiv.net/novel/show.php?id={}"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
}

# --- Selenium WebDriverの初期設定 ---
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--window-size=1920x1080")
chrome_options.add_argument(f"user-agent={HEADERS['User-Agent']}")

try:
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)
except Exception:
    print("Default ChromeService failed, falling back to WebDriverManager...")
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)

print("ChromeDriver is ready.")


# --- ルーティング ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/search')
def search():
    query = request.args.get('q', '')
    page = request.args.get('p', 1, type=int)

    if not query:
        return redirect(url_for('index'))

    encoded_query = quote(query)
    api_url = SEARCH_API_URL.format(encoded_query, encoded_query, page)

    try:
        response = requests.get(api_url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        if data.get('error'):
            return render_template('error.html', message=f"APIエラー: {data.get('message', '不明なエラー')}")

        novels = data['body']['novel']['data']
        total = data['body']['novel']['total']
        has_next = (page * 60) < total

    except Exception as e:
        traceback.print_exc()
        return render_template('error.html', message=f"検索中にエラーが発生しました: {e}")

    return render_template('search.html', 
        novels=novels, 
        query=query, 
        current_page=page, 
        has_next=has_next,
        total=total
    )


@app.route('/novel/<novel_id>')
def novel(novel_id):
    """小説の本文を表示するページ（Seleniumによるページめくり対応版）"""
    page_url = NOVEL_PAGE_URL.format(novel_id)
    all_pages_html = [] # 全ページの本文HTMLを格納するリスト
    
    try:
        print(f"Fetching novel ID: {novel_id}")
        driver.get(page_url)

        # --- タイトルと作者名の取得（最初のページで一度だけ行う） ---
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "title")))
        title_string = driver.title.replace(' - pixiv', '')
        parts = title_string.split(' - ')
        title = parts[0].strip()
        user_name = parts[1].replace('の小説', '').strip() if len(parts) > 1 else "不明"

        page_count = 1
        while True:
            print(f"Processing page {page_count}...")
            # 本文コンテナが表示されるまで待機
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "main.sc-8d5ac044-7")))

            soup = BeautifulSoup(driver.page_source, 'lxml')
            
            novel_body_container = soup.find('main', class_='sc-8d5ac044-7')
            if novel_body_container:
                if page_count > 1:
                    all_pages_html.append(f'<hr style="margin: 2em 0; border-top: 1px dashed #ccc;"><p style="text-align:center; color:#888;">- {page_count} -</p>')
                
                content_tags = novel_body_container.find_all(['h2', 'p'])
                for tag in content_tags:
                    for span in tag.find_all('span', class_='text-count'):
                        span.unwrap()
                    all_pages_html.append(str(tag))

            # --- 「次へ」ボタンを探してクリック ---
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, 'div[direction="next"] button')
                if next_button.is_enabled():
                    next_button.click()
                    page_count += 1
                    time.sleep(1.5) # ページ遷移とJSの再描画を確実に待つ
                else:
                    print("Next button is disabled. Reached the last page.")
                    break
            except NoSuchElementException:
                print("Next button not found. Reached the last page.")
                break

        content = "".join(all_pages_html)
        if not content.strip():
            raise ValueError("本文コンテンツの取得に失敗しました。")

    except Exception as e:
        traceback.print_exc()
        return render_template('error.html', message=f"ページの解析に失敗しました: {e}")

    return render_template('novel.html', 
        title=title, 
        user_name=user_name, 
        content=content
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=False) # デプロイを考慮し、通常はFalse

# アプリケーション終了時にブラウザを閉じる
atexit.register(lambda: driver.quit())
