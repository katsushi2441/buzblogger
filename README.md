# BuzBlogger

AI-powered marketing tool that analyzes trending topics, matches related AIxEC products, and automatically generates blog-style posts for AIxSNS.

## What It Does

1. Fetches trending Togetter posts.
2. Matches each topic with related AIxEC products.
3. Uses Claude Code to choose the best topic/product combination.
4. Generates a Japanese marketing article.
5. Posts the article to AIxSNS as `buzblogger`.

## Main Scripts

- `scripts/buzblogger_pipeline.py` - full pipeline runner
- `scripts/fetch_togetter.py` - collects trend candidates
- `scripts/find_related_products.py` - maps candidates to AIxEC products
- `scripts/claude_buzblogger.py` - generates article JSON with Claude Code
- `scripts/post_buzblog.py` - posts generated content to AIxSNS

## Runtime Files

Generated data is intentionally not committed:

- `tasks/togetter_candidates.json`
- `tasks/togetter_with_products.json`
- `tasks/buzblog_post.generated.json`
- `tasks/buzblog_post.claude_raw.json`
- `storage/posted_urls.txt`
- `storage/autonomous/*.log`

Only `tasks/buzblog_post.schema.json` is committed because it defines the Claude structured output schema.

## Usage

```bash
python3 scripts/buzblogger_pipeline.py --dry-run
python3 scripts/buzblogger_pipeline.py
```

Claude Code must be available through `claude` in `PATH`, or set `CLAUDE_BIN`.
