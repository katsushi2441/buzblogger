#!/usr/bin/env python3
"""Find AIxEC products/books related to each Togetter buzz candidate.

Candidates with no matching products are dropped.
Output: tasks/togetter_with_products.json
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "tasks" / "togetter_candidates.json"
OUT = ROOT / "tasks" / "togetter_with_products.json"

AIXEC_API = "https://aixec.exbridge.jp/api.php"

# タイトルキーワード → AIxEC検索キーワードのマッピング（広め・おおらかに）
KEYWORD_GENRE_MAP = [
    (["AI", "人工知能", "ChatGPT", "Claude", "LLM", "機械学習", "自動化", "生成AI", "Gemini", "GPT", "Copilot", "テック", "Tech"], "AI"),
    (["プログラミング", "コード", "Python", "エンジニア", "開発", "ソフトウェア", "システム", "アプリ", "IT", "GitHub", "プログラム"], "プログラミング"),
    (["GPU", "RTX", "グラフィック", "NVIDIA", "ゲーミングPC", "ゲーミング", "ゲーム", "ゲームPC", "PC", "パソコン", "ノートPC", "スペック", "メモリ", "SSD", "スマホ", "スマートフォン", "充電", "バッテリー", "ガジェット", "家電", "デバイス"], "ゲーミングPC"),
    (["副業", "フリーランス", "在宅", "稼ぐ", "収入", "収益化", "電子書籍", "印税", "ライター", "クラウドソーシング"], "副業"),
    (["投資", "NISA", "株", "資産", "配当", "FX", "お金", "貯金", "節約", "コスト", "費用", "借金", "ローン", "手数料", "小銭", "硬貨", "銀行", "課金", "貢ぐ", "課金", "散財", "浪費"], "投資 NISA"),
    (["暗号資産", "ビットコイン", "仮想通貨", "ブロックチェーン", "NFT", "DeFi", "Web3", "DAO"], "ブロックチェーン"),
    (["健康", "医療", "病気", "薬", "サプリ", "睡眠", "ダイエット", "食事", "栄養", "救急", "病院", "診察", "症状", "怒り", "感情", "メンタル", "ストレス", "イライラ"], "健康 サプリ"),
    (["起業", "経営", "ビジネス", "マーケティング", "マーケ", "UX", "設計", "戦略", "コスパ", "仕事", "職場", "社長", "会社", "転職", "キャリア", "サービス", "飲食", "外食"], "起業 経営"),
    (["本", "書籍", "読書", "出版", "漫画", "マンガ", "アニメ", "作家", "編集", "作文", "言葉", "国語", "文章", "学歴", "受験", "大学", "教育", "勉強", "学習", "学校", "教師", "コナン", "タイ", "海外", "外国", "話題", "SNS", "バズ", "Twitter", "X"], "人気書籍"),
    (["工具", "DIY", "電動工具", "マキタ", "HiKOKI"], "工具 DIY"),
    (["コスメ", "美容", "スキンケア", "メイク", "化粧", "シャンプー", "ヘアケア", "洗髪", "香り", "香水", "爆買い"], "美容 コスメ"),
    (["トレカ", "カード", "ポケモン", "遊戯王"], "トレカ"),
]

# マッチなし時のフォールバックジャンル（とにかく1件は投稿）
FALLBACK_GENRE = "人気書籍"


def detect_genres(title: str) -> list[str]:
    genres = []
    for keywords, genre in KEYWORD_GENRE_MAP:
        if any(kw in title for kw in keywords):
            if genre not in genres:
                genres.append(genre)
    return genres[:3]  # 最大3ジャンル


def search_products(keyword: str, limit: int = 3) -> list[dict]:
    params = urlencode({"path": "products", "q": keyword, "limit": limit})
    url = f"{AIXEC_API}?{params}"
    req = Request(url, headers={"User-Agent": "buzblogger/1.0"})
    try:
        with urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data.get("items") or []
    except Exception as e:
        print(f"  search error ({keyword}): {e}")
        return []


def fetch_ranking_products(limit: int = 6) -> list[dict]:
    """人気ランキングトップの商品をフォールバック用に取得する"""
    params = urlencode({"path": "products", "sort": "popular", "limit": limit})
    url = f"{AIXEC_API}?{params}"
    req = Request(url, headers={"User-Agent": "buzblogger/1.0"})
    try:
        with urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data.get("items") or []
    except Exception as e:
        print(f"  ranking fetch error: {e}")
        return []


def main():
    if not CANDIDATES.exists():
        raise SystemExit(f"not found: {CANDIDATES}")

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    results = []

    for item in candidates:
        title = item.get("title", "")
        genres = detect_genres(title)
        print(f"\n[{item['point']}] {title[:50]}")
        print(f"  genres: {genres}")

        if not genres:
            print(f"  → no genre match, fallback to '{FALLBACK_GENRE}'")
            genres = [FALLBACK_GENRE]

        found_products = []
        seen_ids: set = set()
        for genre_kw in genres:
            products = search_products(genre_kw, limit=3)
            for p in products:
                pid = p.get("id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    go_params = urlencode({
                        "to": "rakuten",
                        "kw": p.get("name", "")[:50],
                        "pid": pid,
                        "from": "buzblogger",
                    })
                    found_products.append({
                        "id": pid,
                        "name": p.get("name", ""),
                        "maker": p.get("maker", ""),
                        "price": p.get("sale_price"),
                        "genre_kw": genre_kw,
                        "go_url": f"https://aixec.exbridge.jp/go.php?{go_params}",
                    })
            if len(found_products) >= 6:
                break

        if not found_products:
            print("  → no products found, fallback to ranking top")
            found_products = fetch_ranking_products(limit=6)
            if found_products:
                # go_url を付与
                for p in found_products:
                    if not p.get("go_url"):
                        go_params = urlencode({
                            "to": "rakuten",
                            "kw": p.get("name", "")[:50],
                            "pid": p.get("id", ""),
                            "from": "buzblogger",
                        })
                        p["go_url"] = f"https://aixec.exbridge.jp/go.php?{go_params}"
                print(f"  → ranking fallback: {len(found_products)} products")
            else:
                print("  → ranking fallback also empty, skip")
                continue
        else:
            print(f"  → {len(found_products)} products found")
            for p in found_products[:3]:
                print(f"     ・{p['name'][:50]}")

        results.append({
            **item,
            "genres": genres,
            "products": found_products[:6],
        })

    print(f"\ncandidates with products: {len([r for r in results if r['products']])}/{len(candidates)}")
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
