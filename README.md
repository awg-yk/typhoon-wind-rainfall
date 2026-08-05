# 上陸台風雨風マップ

https://awg-yk.github.io/typhoon_landfall_wind-rainfall/

台風経路・観測風 可視化ツール

## 使い方

### ローカルで開く
このツールはデータをネットワーク経由で読み込む方式（`fetch`）に変更したため、
`index.html` を直接ダブルクリックする方法は動きません（ブラウザの制限で
`file://` からの読み込みがブロックされます）。ローカルで確認したい場合は、
このフォルダで簡易サーバーを立てて開いてください。

```bash
python3 -m http.server 8000
```

その後ブラウザで `http://localhost:8000/` を開きます。
（普段はGitHub Pagesで公開して使う想定なので、公開後は特に意識する必要は
ありません。）

### GitHub Pages で公開する
1. このリポジトリを GitHub にプッシュします。
2. リポジトリの **Settings → Pages** で、公開ブランチ（例: `main`）とルート
   フォルダを指定します。
3. しばらくすると `https://<ユーザー名>.github.io/<リポジトリ名>/` で公開されます。
   相対パスで読み込むため、追加設定は不要です。

## フォルダの中身

- `index.html` … 可視化ツール本体（これを開く）
- `data/stations.json` … 観測地点（156地点）の名前・座標（数KB、起動時に読み込み）
- `data/index.json` … 1951〜2026年の気象庁ベストトラック全台風（1954個）の名前・年・
  最盛期階級・通過月・日本上陸/通過フラグ・観測データ有無を収めた一覧（タブ表示・
  絞り込み用）
- `data/storms/*.json` … 台風ごとの経路本体（1954ファイル）。このうち142個は観測
  風・観測雨量データも含む（`wind`/`rain`/`times` フィールドあり）。該当タブを開
  いたときに必要な分だけ読み込みます
- `bst_landfall_only.txt` … 観測データ付き142台風の元になった気象庁ベストトラック
  抜粋（参考保存用）
- `wind_csv/*.csv`（142個） … 各台風の全国観測風データの元データ（参考保存用）
- `rain_csv/*.csv`（142個） … 各台風の全国観測雨量データの元データ（参考保存用）
- `scripts/build_all_storms.py` … 気象庁ベストトラック全件テキスト
  （[typhoon-track-finder](https://github.com/awg-yk/typhoon-track-finder) の
  `bst_all.txt`）から `data/storms/*.json`・`data/index.json` を再生成するスクリプト。
  既存の観測風・雨データは上書きせず保持したまま経路のみ同期します。
  `python3 scripts/build_all_storms.py <bst_all.txtのパス>`
- `data/raw/stations_wind.csv` / `stations_rain.csv` … 観測網の元データ（風・雨それぞれの
  観測地点一覧。気象台等＋アメダス、計2802地点）
- `scripts/build_station_network.py` … 上記2つのCSVから `data/stations_network.json`
  （地点名・座標・`prec_no`/`block_no` を風/雨別に整理したもの）を生成するスクリプト。
  `python3 scripts/build_station_network.py`
- `scripts/fetch_amedas_obsdl.py` … 台風ごとの発生〜消滅日（JST）に合わせて、気象庁
  「[過去の気象データ・ダウンロード](https://www.data.jma.go.jp/gmd/risk/obsdl/index.php)」
  （obsdl）から風・雨の時別値をまとめて取得するスクリプト。地点をバッチ化して
  リクエスト数を抑えており（全130台風・全地点で約2,600リクエスト）、1地点1日ずつ
  取得する方式（数百万リクエスト）より大幅に高速です。POST形式・地点バッチ化ロジック
  は動作実績のある
  [weather-station-finder の Colab ノートブック](https://github.com/awg-yk/weather-station-finder/blob/main/notebooks/jma_bulk_download.ipynb)
  を移植しています。
  ```bash
  pip install requests
  python3 scripts/fetch_amedas_obsdl.py --landfall-only --kind wind,rain
  # 特定の台風だけ: --codes 1912,1915
  # 実際に取得せずリクエスト数だけ確認: --dry-run
  ```
  取得結果は `data/raw_amedas/<台風コード>_<wind|rain>.csv`（気象庁の生CSV形式）に
  保存されます。このCSVを既存の `data/storms/*.json` の `wind`/`rain` 形式に変換する
  処理は未実装です（実際のCSVの列構成を確認してから実装する必要があるため）。

## 絞り込み機能

上部タブ横の「絞り込み」ボタンから、種別（日本上陸・通過／それ以外も含む全て）・
観測データ有無・年・強さ（階級）・月・台風名で表示する台風を絞り込めます
（`data/index.json` に事前計算済みの `maxGrade`（最盛期の階級）・`months`（経路が
該当した月）・`landfallJP`（解析時刻の前後1時間以内に日本へ上陸/通過したか）・
`hasObs`（気象台等の観測風・雨データがあるか）を追加して実現しています）。
初期状態では `landfallJP=true` の台風のみを表示します（観測データが無い遠方の
台風で一覧が埋まらないようにするため）。日本近辺を通らない台風も含めて全件見たい
場合は「その他(遠方含む全て)」にチェックしてください。

## 機能

- 上部タブ（横スクロール可）または右側のプルダウン・矢印ボタンで台風を選んで切り替え
- 観測データがない台風（`hasObs=false`）は経路のみのシンプルな表示になり、風/雨の
  切り替えボタンは無効化されます
- 台風の経路線をクリックすると、その地点の時刻まで再生位置がジャンプします
- 右側パネルの「風 / 雨」ボタンで、全国観測地点の表示を切り替え可能
  - 風：矢印（吹いていく方向、長さと色は風速）
  - 雨：丸（大きさと色は1時間降水量）
- 下部のスライダー・再生ボタンで時間を進めると、台風の中心と観測地点の表示が
  同時に動きます
- 右側パネルに台風の中心気圧・階級・位置を表示

## 注意

- CSVの観測地点の緯度経度は気象庁公開データ等をもとに作成した概略値です。
- 台風経路データは気象庁ベストトラック形式を解析したものです。ベストトラックの
  時刻はUTC（Zタイム）で記録されているため、JST（Iタイム）の観測風データと
  時刻を揃えるための+9時間の変換を `index.html` 側のJSで行っています
  （`data/storms/*.json` 自体の値は元データのまま変更していません）。
- 「階級」のうちコード1・7は気象庁の公式な階級区分表で明確な区分名が確認できな
  かったため、便宜上「熱帯低気圧」として表示しています。
- データは台風ごとに分割し、選択したタブの分だけ読み込む方式にしています。
  最初の表示（地図・タブ・最初の台風）が数秒以内に出るようにするための工夫です。
