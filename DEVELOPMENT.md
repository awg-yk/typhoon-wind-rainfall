# 開発者向けドキュメント

一般的な使い方は [README.md](README.md) を参照してください。ここには
データの作り方・スクリプトの詳細・作業記録など、開発・保守に必要な
技術的な情報をまとめています。

## ローカルで開く

このツールはデータをネットワーク経由で読み込む方式（`fetch`）のため、
`index.html` を直接ダブルクリックする方法は動きません（ブラウザの制限で
`file://` からの読み込みがブロックされます）。ローカルで確認したい場合は、
このフォルダで簡易サーバーを立てて開いてください。

```bash
python3 -m http.server 8000
```

その後ブラウザで `http://localhost:8000/` を開きます。

### GitHub Pages で公開する

1. このリポジトリを GitHub にプッシュします。
2. リポジトリの **Settings → Pages** で、公開ブランチとルートフォルダを
   指定します。
3. しばらくすると `https://<ユーザー名>.github.io/<リポジトリ名>/` で
   公開されます。相対パスで読み込むため、追加設定は不要です。

## フォルダの中身

- `index.html` … 可視化ツール本体（これを開く）
- `data/stations.json` … 観測地点（156地点）の名前・座標（数KB、起動時に読み込み）
- `data/index.json` … 1951〜2026年の気象庁ベストトラック全台風（1954個）の名前・年・
  最盛期階級・通過月・日本上陸/通過フラグ・観測データ有無を収めた一覧（タブ表示・
  絞り込み用）
- `data/storms/*.json` … 台風ごとの経路本体（1954ファイル）。このうち142個は観測
  風・観測雨量データも含む（`wind`/`rain`/`times` フィールドあり）。該当タブを開
  いたときに必要な分だけ読み込みます
- `data/pressure/*.json` … 台風ごとのJRA-3Q海面更正気圧グリッド（`scripts/
  build_pressure_json.py` で生成、気圧配置モードで開いたときのみ読み込み）
- `data/stations_network.json` … AMeDAS＋気象台等の拡張観測網（風976地点・
  雨1669地点、`scripts/build_station_network.py` で生成、起動時に読み込み）
- `data/storms_obs/*.json` … 台風ごとのAMeDAS観測網の風・雨データ
  （`scripts/convert_amedas_csv.py` で生成、風/雨モードで開いたときのみ
  読み込み。無い台風は旧156地点網にフォールバック）
- `data/tydb_damage/*.json` … 台風ごとの被害データ（防災科研 台風データベース
  TYDB由来。`scripts/fetch_tydb_damage.py` で生成、被害モードで開いたときのみ
  読み込み）
- `bst_landfall_only.txt` … 観測データ付き142台風の元になった気象庁ベストトラック
  抜粋（参考保存用）
- `wind_csv/*.csv`（142個） … 各台風の全国観測風データの元データ（参考保存用）
- `rain_csv/*.csv`（142個） … 各台風の全国観測雨量データの元データ（参考保存用）
- `scripts/build_all_storms.py` … 気象庁ベストトラック全件テキスト
  （[typhoon-track-finder](https://github.com/awg-yk/typhoon-track-finder) の
  `bst_all.txt`）から `data/storms/*.json`・`data/index.json` を再生成するスクリプト。
  既存の観測風・雨データは上書きせず保持したまま経路のみ同期します。
  `python3 scripts/build_all_storms.py <bst_all.txtのパス>`
- `data/raw/digitaltyphoon_landfall.csv` … 国立情報学研究所「デジタル台風」の
  [台風の上陸](https://agora.ex.nii.ac.jp/digital-typhoon/disaster/landfall-full/)
  一覧（1951〜2025年、上陸/再上陸/通過の記録）
- `scripts/apply_digitaltyphoon_landfall.py` … 上記CSVを正とし、全台風の
  `landfallJP`（日本に上陸・通過したか）を確定するスクリプト。気象庁ベストトラック
  の上陸マーカーは1991年以降にしか記録がなく、それ以前は
  `scripts/estimate_pre1991_landfall.py`（観測地点への近接で推定）で代用していたが、
  こちらのほうが正確なため優先して上書きする。実際の上陸日時・都道府県・地点も
  `data/storms/*.json` の `landfallEvents` に保存する。
  `python3 scripts/apply_digitaltyphoon_landfall.py`
- `data/raw/stations_wind.csv` / `stations_rain.csv` … 観測網の元データ（風・雨それぞれの
  観測地点一覧。気象台等＋アメダス、計2802地点）
- `scripts/build_station_network.py` … 上記2つのCSVから `data/stations_network.json`
  （地点名・座標・`prec_no`/`block_no` を風/雨別に整理したもの）を生成するスクリプト。
  `python3 scripts/build_station_network.py`
- `scripts/fetch_amedas_obsdl.py` … 台風ごとの発生〜消滅日（JST）に合わせて、気象庁
  「[過去の気象データ・ダウンロード](https://www.data.jma.go.jp/gmd/risk/obsdl/index.php)」
  （obsdl）から風・雨の時別値をまとめて取得するスクリプト。地点をバッチ化して
  リクエスト数を抑えており、1地点1日ずつ取得する方式（数百万リクエスト）より
  大幅に高速です。POST形式・地点バッチ化ロジックは動作実績のある
  [weather-station-finder の Colab ノートブック](https://github.com/awg-yk/weather-station-finder/blob/main/notebooks/jma_bulk_download.ipynb)
  を移植しています。
  ```bash
  pip install requests
  python3 scripts/fetch_amedas_obsdl.py --landfall-only --kind wind,rain
  # 特定の台風だけ: --codes 1912,1915
  # 実際に取得せずリクエスト数だけ確認: --dry-run
  # リクエスト間隔を短縮したい場合（既定3秒）: --sleep 1.0
  ```
  取得結果は `data/raw_amedas/<台風コード>_<wind|rain>.csv`（気象庁の生CSV形式）に
  保存されます。`data/raw_amedas/` と次に説明する `data/storms_obs/` はデータ量が
  大きい（全台風分で数百MB）ため `.gitignore` に入れてあり、リポジトリには含めて
  いません。両スクリプトを手元で実行すれば再生成できます。
- `scripts/convert_amedas_csv.py` … `data/raw_amedas/*.csv` を `data/storms_obs/
  <台風コード>_<wind|rain>.json`（`{times:[...], values:[...]}`。`values` は
  `data/stations_network.json` の地点順に対応する配列。風は `[風速m/s, 風向(度)]`、
  雨は降水量mmの配列）に変換するスクリプト。obsdlのCSVは地点によって列幅が違ったり
  （雨は「現象なし情報」列の有無で3列/4列）、別地点なのに同じ地点名が複数あったり
  する（例: 筑波山・白浜）ため、列名ではなく各列の見出し行の並び（空欄/風向/品質情報/
  均質番号など）のパターンから地点の区切りを判定しています。
  ```bash
  python3 scripts/convert_amedas_csv.py --codes 1912,1915
  python3 scripts/convert_amedas_csv.py --all   # data/raw_amedas/ にある分すべて
  ```
  手元での`git`操作が難しい場合は、`notebooks/convert_amedas_csv_colab.ipynb`
  （Google Drive上のCSVを読み込み、変換して、GitHub Personal Access Tokenで
  直接pushまで行うColab版）を使ってください。

  `data/storms_obs/*.json` は（`data/raw_amedas/`とは違い）`.gitignore`
  対象外で、リポジトリにコミットする運用です。風/雨モードのフロントエンド
  表示に使うためです。GitHub Pagesからの配信自体はファイル単位の静的配信なので
  データ量が大きくても問題ありません。
- **フロントエンド（`index.html`）でのAMeDAS観測網表示**: 「風 Wind」「雨
  Rain」モードは、その台風に `data/storms_obs/<コード>_{wind,rain}.json`
  があればAMeDAS観測網（風976地点・雨1669地点、`data/stations_network.json`）
  を優先して使い、無ければ従来の `data/storms/<コード>.json` 内の
  `wind`/`rain`（旧156地点網）にフォールバックします。風と雨で地点網が
  異なるため、地点マーカーは3種類（旧156地点／AMeDAS風976地点／AMeDAS雨
  1669地点）を別レイヤーとして地図上に用意し、表示モードに応じて切り替えます。
- `scripts/fetch_tydb_damage.py` … [防災科研 台風データベース（TYDB）](https://tydb.bosai.go.jp/TYDB/)
  の台風ごとのページから、「気象の状況」の要約文と、「被害の状況」の
  都道府県別被害統計表（死者・行方不明者、負傷者、全壊・半壊・一部破損、
  床上・床下浸水、非住家、情報元）を抽出し `data/tydb_damage/<台風コード>.json`
  として保存するスクリプト。
  ```bash
  pip install requests beautifulsoup4
  python3 scripts/fetch_tydb_damage.py --landfall-only  # landfallJP/damagingのみ
  python3 scripts/fetch_tydb_damage.py --all             # 全台風を試す（推奨）
  ```
  `--all`は`data/index.json`の全台風（約1954件）を試します。TYDBにページが
  無い台風は404が返るだけで`{"notFound": true}`として記録・スキップされる
  ので、全件試すのが安全です（サンドボックス環境からはtydb.bosai.go.jpへの
  通信がブロックされるため、`notebooks/fetch_tydb_damage_colab.ipynb`を
  使ってください）。
- `scripts/list_damage_gaps.py` … TYDBに実際の被害データ（合計または
  都道府県別のいずれかに1件以上の非ゼロ値）がある台風のうち、気圧配置・
  AMeDAS観測網データがまだ無いものを一覧するスクリプト。
  ```bash
  python3 scripts/list_damage_gaps.py            # 人が読む形式のレポート
  python3 scripts/list_damage_gaps.py --kind obs # --codes にそのまま渡せるカンマ区切り
  python3 scripts/list_damage_gaps.py --kind pressure
  python3 scripts/list_damage_gaps.py --kind wind
  python3 scripts/list_damage_gaps.py --kind rain
  ```
  「風データが無い」の判定は、AMeDAS観測網ファイルに実際の値が1つも無く、
  かつ旧156地点網にも値が無い場合のみを指します。1961年より前の台風は
  気象庁が風速をまだ電子化していないため、この判定で「欠落」として
  挙がっても取得できるデータが存在しない場合があります。
- `scripts/mark_damaging_from_tydb.py` … TYDBに実際の被害データがある台風
  のうち、`landfallJP`でも従来の`damaging`でもまだ拾えていなかったものに
  機械的に`damaging: true`を付与するスクリプト（`data/index.json`を更新）。
  これをしないと、フロントエンドの「上陸・通過や被害のあった台風のみ」
  フィルタや、後述のAMeDAS/JRA-3Qスクリプトの既定対象（`landfallJP OR
  damaging`）からその台風が漏れてしまいます。
  ```bash
  python3 scripts/mark_damaging_from_tydb.py --dry-run  # 変更内容だけ確認
  python3 scripts/mark_damaging_from_tydb.py            # 実行
  ```
- `scripts/download_jra3q_pressure.py` … 気象庁第3次長期再解析
  [JRA-3Q](https://jra.kishou.go.jp/JRA-3Q/index_ja.html) の海面更正気圧
  （気圧配置。`anl_surf` の `prmsl-msl-an-gauss`）を、対象台風の経路が
  かかる月ぶんまとめて [NCAR/UCAR GDEX](https://gdex.ucar.edu/datasets/d640000/)
  からダウンロードするスクリプト。必要な月は`data/index.json`・
  `data/storms/*.json`から自動計算します（track時刻はUTCなので、
  `build_pressure_json.py`と同じ+9h JST変換をしてから月を決定 —
  そうしないと、末尾がJSTで翌月にまたがる台風の月を取り漏らします）。
  GDEXは過去分(`d640000`)と近似リアルタイム分(`d640001`)の2データセットに
  分かれており、月ごとにまず`d640000`を試し、d640001が対象の月
  （2023年12月以降）だけフォールバックします。
  `pip install xarray netCDF4` が必要です。

  **方式**: GDEXの静的ファイルサーバーから月ごとの全球ファイル（約84MB）を普通に
  ダウンロードし、ローカルで日本周辺（既定: 北緯15〜50度・東経115〜155度、
  `--north`/`--south`/`--west`/`--east`で変更可）だけを切り出して約4.8MBで保存、
  元の全球ファイルは即削除します。保持するのは切り出し後のファイルのみで、
  ディスクのピーク使用量も全球1ファイル分だけです。

  一見無駄ですが、サーバー側で切り出す「賢い」方法は2つとも使えませんでした:
  - **NCSS**（THREDDSのサーバー側切り出し）… 大半の月がタイムアウトし成功率1割以下
  - **OPeNDAP**（必要な範囲だけ読む）… 単発では13.5秒・4.8MBで成功したが、4並列で
    504、逐次でも504、5日ずつに分割しても504、最後はメタデータを開くだけの最小
    リクエストすら失敗する状態に（`--method opendap` で今も選べます）

  一方**静的ファイルサーバーは一度も失敗していません**（リクエストごとの計算をせず
  バイトを返すだけのため）。通信量と引き換えに確実さを取っています。
  ```bash
  pip install xarray netCDF4
  python3 scripts/download_jra3q_pressure.py --dry-run   # 対象月・件数だけ確認
  python3 scripts/download_jra3q_pressure.py             # 海面更正気圧のみ取得（日本域）
  python3 scripts/download_jra3q_pressure.py --include-surface-pressure  # 地上気圧も
  python3 scripts/download_jra3q_pressure.py --workers 4 # 静的サーバーは並列に耐える
  python3 scripts/download_jra3q_pressure.py --codes 1919,1915  # 特定の台風だけ
  ```
  取得済みファイルは`data/raw_jra3q/`（既定）に保存され、既存ファイルは
  スキップされる（途中で止まっても再実行で再開可能）ので、時間を分けて
  実行しても問題ありません。手元の環境からGDEXへのHTTPS接続がブロックされる場合は
  `notebooks/jra3q_colab_download.ipynb`（Google Colab上で実行し、Google Driveの
  `MyDrive/jra3q_pressure_japan`に直接保存する版）を使ってください。
- `scripts/build_pressure_json.py` … 上記でダウンロードした月別netCDF
  ファイル（`data/raw_jra3q/` などローカルの保存先）を、台風ごとの経路期間に
  合わせて `data/pressure/<台風コード>.json`（`{lat:[...], lon:[...],
  times:[...JST...], values:[[[hPa整数,...]...]...]}`）に切り出すスクリプト。
  格子は既定で間引き（`--stride 2`、緯度経度とも半分の解像度）、値は整数hPaに
  丸めてファイルサイズを抑えています（等圧線の描画には十分な精度）。生の
  netCDFファイルは大きすぎるためリポジトリには含めず、この変換後のJSONだけを
  コミットします。該当月のnetCDFファイルが無い台風は変換時にスキップされ
  `data/pressure/<コード>.json` が存在しません（フロントエンドはその場合、
  気圧モードで等圧線を表示しないだけで、経路・風・雨の表示には影響しません）。
  ```bash
  pip install xarray netCDF4
  python3 scripts/build_pressure_json.py --raw-dir /path/to/ncファイル群
  python3 scripts/build_pressure_json.py --raw-dir ... --codes 1919,1915  # 特定の台風だけ
  ```
  手元での`git`操作が難しい場合は、`notebooks/build_pressure_json_colab.ipynb`
  （Google Driveの`MyDrive/jra3q_pressure_japan`から.ncファイルを読み込み、
  変換して、GitHub Personal Access Tokenで直接pushまで行うColab版）を
  使ってください。

## 対象台風の選定（landfallJP + damaging）

データ収集（AMeDAS観測網・JRA-3Q気圧配置）の対象は、以下いずれかを
満たす台風です（`data/index.json` の各エントリのフラグ）:

- **`landfallJP: true`** — 日本に上陸・通過した台風（221台風）。
  [デジタル台風](https://agora.ex.nii.ac.jp/digital-typhoon/disaster/landfall-full/)
  のベストトラック解析に基づく判定。
- **`damaging: true`** — 上陸・通過はしていないものの日本国内で大きな
  被害を出した台風（257台風、`landfallJP=true`のものを除く）。内訳は
  2つ:
  - 70台風: [デジタル台風 災害データベース](https://agora.ex.nii.ac.jp/cgi-bin/dt/disaster.pl?lang=ja&basin=wnp&sort=dead_or_missing&order=dec&stype=number)
    の死者・行方不明者数ランキング（上位204台風）のうち、`landfallJP`で
    拾えていなかったもの。元データと選定方法は
    `data/damage_storm_codes.json` に記録。
  - 187台風: `fetch_tydb_damage.py --all`（TYDBの全台風試行）で見つかった、
    実際に何らかの被害件数（死者・行方不明者/負傷者/全壊/...のいずれか
    非ゼロ）があるTYDB被害テーブルを持つ台風のうち、上記2つでまだ
    拾えていなかったもの。`scripts/mark_damaging_from_tydb.py`で機械的に
    付与。

`scripts/fetch_amedas_obsdl.py --landfall-only`・
`scripts/download_jra3q_pressure.py`・`scripts/build_pressure_json.py`
（`--codes`未指定時）はいずれもこの `landfallJP OR damaging` を対象に
自動的に含めるようになっています。フロントエンド側は対応不要です
（`data/storms_obs/`・`data/pressure/` にファイルさえあれば、
`landfallJP`かどうかに関係なく年/台風プルダウンから選んで表示されます。
「上陸・通過(日本)のみ」フィルタは表示の絞り込みであって、データの
有無とは独立しています）。

## データ整備の状況（2026-08-12時点）

被害データのある455台風について、取得可能なデータの整備は完了しています。

| データ | 状況 |
| --- | --- |
| TYDB被害データ（`data/tydb_damage/`） | 455/455 |
| 雨データ（`data/storms_obs/`） | 455/455 |
| 気圧配置（`data/pressure/`） | 455/455 |
| 風データ（`data/storms_obs/`） | 404/455（残り51台風は1951〜1960年で、気象庁が風速をまだ電子化していない時代のため元データ自体が存在しません） |

進捗確認・再取得の手順は上記「フォルダの中身」の各スクリプトを参照
してください。新しく被害データを広げた場合の典型的な流れ:

1. `python3 scripts/fetch_tydb_damage.py --all`（TYDB被害データを広げる）
2. `python3 scripts/mark_damaging_from_tydb.py`（新しく見つかった台風を`damaging: true`に）
3. `python3 scripts/list_damage_gaps.py`（気圧配置・風雨データの不足を確認）
4. `fetch_amedas_obsdl.py`・`download_jra3q_pressure.py`＋`build_pressure_json.py`
   を、`list_damage_gaps.py`の出力する`--codes`で実行（Colabノートブック推奨）

## フロントエンドの実ブラウザでの確認（2026-08-07）

サンドボックス環境からはLeaflet CDN（cdnjs.cloudflare.com）・GSIタイル
CDN（cyberjapandata.gsi.go.jp）へのアクセスがブロックされているため、
確認時は `npm pack leaflet@1.9.4` で取得したLeafletを一時的にローカル
vendorし（本番の`index.html`は引き続きCDN参照のまま）、Playwright
（Chromium）で描画確認しました。背景地図タイル自体はサンドボックスから
到達できず表示されませんが、Leaflet自体・オーバーレイ（経路線、観測
マーカー、等圧線）の描画ロジックはタイルの有無に依存しないため問題なく
検証できています。確認済みの項目:

- 風モード: AMeDAS観測網で風向風速の矢印マーカーが正しい位置・色分けで表示
- 雨モード: 降水量の丸マーカー（大きさ・色分け）が正しく表示
- 気圧配置モード: 等圧線（20hPa太線・4hPa細線）が滑らかに描画
- 被害モード: 都道府県ごとの色分け・ホバーツールチップが正しく表示
- 観測データが無い古い台風を選択した場合、経路のみが表示され
  「観測データなし・経路のみ」と正しく案内される
- モード切替ボタン・年/台風選択・タイムラインスライダーなどのUI操作も
  JSエラーなく動作

実際のタイル表示（地図の見た目）とマーカーのパフォーマンス（976/1669
地点同時表示時の描画速度）は、外部ネットワーク制限のない環境でのみ
確認可能です。

## 被害状況の都道府県別マップ（実装メモ）

「被害 Damage」モードは、実際の国土地理院地図の上に都道府県ごとの
被害の色分け（choropleth）を重ねます。色分けは `data/tydb_damage/
<コード>.json` の都道府県別被害件数（`damageTier()`、index.html内）に
基づく、件数の多寡を問わない固定5段階のルールです（相対比較や加重
スコアではありません）。各都道府県は、該当する条件のうち最も重い
区分の色になります。ルールの詳細と色の対応はREADME.mdを参照して
ください。

境界ポリゴン（`data/japan_prefectures.geojson`、実際の緯度経度）は、
CC-BY 4.0ライセンスの [japan-choropleth](https://www.npmjs.com/package/japan-choropleth)
（Copyright (c) 2026 Kyodo News、元データは国土交通省 国土数値情報
「[行政区域データ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html)」
CC-BY 4.0）から座標データのみを抽出してvendorしたものです。
