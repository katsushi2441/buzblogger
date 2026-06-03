# buzblogger RQDB4AI Jobs

buzblogger固有のjobコードはbuzbloggerリポジトリ配下に置く。

RQDB4AI本体にはbuzblogger固有のPythonファイル、設定、説明を書かない。

## Job code

- `/home/kojima/work/buzblogger/buzblogger_jobs.py`

## 方針

- RQDB4AIはキュー管理とPython callable実行だけを担当する。
- buzbloggerの業務ロジックはbuzblogger側が持つ。
- はてな投稿、AIxSNS投稿、Claude実行などはbuzblogger側の責務。
- enqueue成功を投稿成功として扱わない。
- 実投稿件数はbuzblogger側の処理結果またはreportを正とする。
