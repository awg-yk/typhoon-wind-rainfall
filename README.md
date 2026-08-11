# 上陸台風雨風マップ

https://awg-yk.github.io/typhoon-wind-rainfall/

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
- `data/pressure/*.json` … 台風ごとのJRA-3Q海面更正気圧グリッド（`scripts/
  build_pressure_json.py` で生成、気圧配置モードで開いたときのみ読み込み）
- `data/stations_network.json` … AMeDAS＋気象台等の拡張観測網（風976地点・
  雨1669地点、`scripts/build_station_network.py` で生成、起動時に読み込み）
- `data/storms_obs/*.json` … 台風ごとのAMeDAS観測網の風・雨データ
  （`scripts/convert_amedas_csv.py` で生成、風/雨モードで開いたときのみ
  読み込み。無い台風は旧156地点網にフォールバック）
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
  保存されます。`data/raw_amedas/` と次に説明する `data/storms_obs/` はデータ量が
  大きい（全台風分で数百MB）ため `.gitignore` に入れてあり、リポジトリには含めて
  いません。両スクリプトを手元で実行すれば再生成できます。
- `scripts/convert_amedas_csv.py` … `data/raw_amedas/*.csv` を `data/storms_obs/
  <台風コード>_<wind|rain>.json`（`{times:[...], values:[...]}`。`values` は
  `data/stations_network.json` の地点順に対応する配列。風は `[風速m/s, 風向(度)]`、
  雨は降水量mmの配列）に変換するスクリプト。obsdlのCSVは地点によって列幅が違ったり
  （雨は「現象なし情報」列の有無で3列/4列）、別地点なのに同じ地点名が複数あったり
  する（例: 筑波山・白浜）ため、列名ではなく各列の見出し行の並び（空欄/風向/品質情報/
  均質番号など）のパターンから地点の区切りを判定しています。1台風分（風976地点・
  雨1669地点・216時間）で実データ検証済みです。
  ```bash
  python3 scripts/convert_amedas_csv.py --codes 1912,1915
  python3 scripts/convert_amedas_csv.py --all   # data/raw_amedas/ にある分すべて
  ```
  手元での`git`操作が難しい場合は、`notebooks/convert_amedas_csv_colab.ipynb`
  （Google Drive上のCSVを読み込み、変換して、GitHub Personal Access Tokenで
  直接pushまで行うColab版）を使ってください。

  `data/storms_obs/*.json` は（`data/raw_amedas/`とは違い）`.gitignore`
  対象外で、リポジトリにコミットする運用です。風/雨モードのフロントエンド
  表示に使うためです（下記）。全台風分では数百MBになる見込みですが、
  GitHub Pagesからの配信自体はファイル単位の静的配信なので問題ありません。
- **フロントエンド（`index.html`）でのAMeDAS観測網表示**: 「風 Wind」「雨
  Rain」モードは、その台風に `data/storms_obs/<コード>_{wind,rain}.json`
  があればAMeDAS観測網（風976地点・雨1669地点、`data/stations_network.json`）
  を優先して使い、無ければ従来の `data/storms/<コード>.json` 内の
  `wind`/`rain`（旧156地点網）にフォールバックします。風と雨で地点網が
  異なるため、地点マーカーは3種類（旧156地点／AMeDAS風976地点／AMeDAS雨
  1669地点）を別レイヤーとして地図上に用意し、表示モードに応じて切り替えます。
- `scripts/download_jra3q_pressure.py` … ERA5との精度比較のため、気象庁
  第3次長期再解析
  [JRA-3Q](https://jra.kishou.go.jp/JRA-3Q/index_ja.html) の海面更正気圧
  （気圧配置。`anl_surf` の `prmsl-msl-an-gauss`）を、上陸・通過台風
  （`landfallJP=true`、221台風）の経路がかかる月ぶんまとめて
  [NCAR/UCAR GDEX](https://gdex.ucar.edu/datasets/d640000/) からダウンロードする
  スクリプト。必要な月（185ヶ月）は本リポジトリの `data/index.json`・
  `data/storms/*.json` から自動計算します。GDEXは過去分(`d640000`)と近似リアル
  タイム分(`d640001`)の2データセットに分かれており、月ごとにまず`d640000`を試し、
  d640001が対象の月（2023年12月以降）だけフォールバックします。
  `pip install xarray netCDF4` が必要です。

  **方式**: GDEXの静的ファイルサーバーから月ごとの全球ファイル（約84MB）を普通に
  ダウンロードし、ローカルで日本周辺（既定: 北緯15〜50度・東経115〜155度、
  `--north`/`--south`/`--west`/`--east`で変更可）だけを切り出して約4.8MBで保存、
  元の全球ファイルは即削除します。全185ヶ月で通信量は約15GBですが、**保持するのは
  1GB弱**で、ディスクのピーク使用量も全球1ファイル分だけです。

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
  ```
  全185ヶ月のうち184ヶ月は日本域切り出し済みで合計1GB弱。`data/raw_jra3q/` に保存され、既存
  ファイルはスキップされる（途中で止まっても再実行で再開可能）ので、時間を分けて
  実行しても問題ありません。手元の環境からGDEXへのHTTPS接続がブロックされる場合は
  `notebooks/jra3q_colab_download.ipynb`（Google Colab上で実行し、ブラウザ経由で
  PCにダウンロードする版）を使ってください。

  以前は`198310`（1983年10月）が静的ファイルサーバー・OPeNDAPどちらの
  経路でも`500 Internal Server Error`/`DAP server error`となり恒久的な
  欠損として扱っていましたが、2026-08-11の再取得では正常に取得できました
  （GDEX側の一時的な問題だった模様）。台風8310（1983年10号）の気圧配置
  データは`data/pressure/8310.json`として揃っています。
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
  python3 scripts/build_pressure_json.py --raw-dir /path/to/185個のncファイル
  python3 scripts/build_pressure_json.py --raw-dir ... --codes 1919,1915  # 特定の台風だけ
  ```
  手元での`git`操作が難しい場合は、`notebooks/build_pressure_json_colab.ipynb`
  （Google Drive上の.ncファイルを読み込み、変換して、GitHub Personal Access
  Tokenで直接pushまで行うColab版）を使ってください。

## 絞り込み機能

左パネルの「絞り込み ▾」ボタンを押すと条件が開きます。

- **上陸・通過(日本)のみ**（チェックボックス）: チェックすると
  `data/index.json` の `landfallJP`（[デジタル台風](https://agora.ex.nii.ac.jp/digital-typhoon/disaster/landfall-full/)
  の記録に基づき日本に上陸・通過したか）が `true` の台風だけに絞り込みます。
  初期状態は未チェック（全1954台風を表示）です。

年のプルダウンで年を選ぶと、その年の台風が号数順に横のプルダウンに並びます
（絞り込みで対象がいない年はグレーアウトします）。

## 機能

- 左パネルの年・台風番号プルダウンで台風を選んで切り替え
- 観測データがない台風（`hasObs=false`）は経路のみのシンプルな表示になり、風/雨の
  切り替えボタンは無効化されます
- 台風の経路線をクリックすると、その地点の時刻まで再生位置がジャンプします
- 左パネルの「風 / 雨 / 気圧」ボタンで、全国観測地点・気圧配置の表示を切り替え可能
  - 風：矢印（吹いていく方向、長さと色は風速）。`data/storms_obs/<コード>_wind.json`
    があればAMeDAS観測網（976地点）、無ければ旧156地点網を使用
  - 雨：丸（大きさと色は1時間降水量）。同様にAMeDAS観測網（1669地点）が
    あれば優先、無ければ旧156地点網にフォールバック
  - 気圧：JRA-3Q再解析の海面更正気圧から作図した等圧線（4hPa間隔、20hPa毎は太線）。
    `data/pressure/<台風コード>.json` がある台風のみ表示されます（`scripts/
    build_pressure_json.py` 参照）。観測データのない台風（`hasObs=false`）でも
    気圧配置は独立したデータのため表示可能です
- 下部のスライダー・再生ボタンで時間を進めると、台風の中心と観測地点の表示が
  同時に動きます
- 左パネルに台風の中心気圧・階級・位置を表示

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

## 対象台風の選定（landfallJP + damaging）

データ収集（AMeDAS観測網・JRA-3Q気圧配置）の対象は、以下いずれかを
満たす台風です（`data/index.json` の各エントリのフラグ）:

- **`landfallJP: true`** — 日本に上陸・通過した台風（221台風）。
  [デジタル台風](https://agora.ex.nii.ac.jp/digital-typhoon/disaster/landfall-full/)
  のベストトラック解析に基づく判定。
- **`damaging: true`** — 上陸・通過はしていないものの日本国内で大きな
  被害を出した台風（70台風、`landfallJP=true`のものを除く）。
  [デジタル台風 災害データベース](https://agora.ex.nii.ac.jp/cgi-bin/dt/disaster.pl?lang=ja&basin=wnp&sort=dead_or_missing&order=dec&stype=number)
  の死者・行方不明者数ランキング（上位204台風）のうち、`landfallJP`で
  拾えていなかったものを追加。元データと選定方法は
  `data/damage_storm_codes.json` に記録してあります。

`scripts/fetch_amedas_obsdl.py --landfall-only`・
`scripts/download_jra3q_pressure.py`・`scripts/build_pressure_json.py`
（`--codes`未指定時）はいずれもこの `landfallJP OR damaging` を対象に
自動的に含めるようになっています。フロントエンド側は対応不要です
（`data/storms_obs/`・`data/pressure/` にファイルさえあれば、
`landfallJP`かどうかに関係なく年/台風プルダウンから選んで表示されます。
「上陸・通過(日本)のみ」フィルタは表示の絞り込みであって、データの
有無とは独立しています）。

## 現状・引き継ぎ事項（次のセッション向け）

### 0. TYDB被害データのカバレッジ拡大（`data/tydb_damage/`） — 完了（2026-08-10）

`scripts/fetch_tydb_damage.py`は元々`landfallJP=true`または`damaging=true`
の291台風だけを対象にしていましたが、TYDB自体はこれ以外の台風にも
ページを持っていることがあります（上陸・通過しておらず`damaging`
フラグも立っていないのに被害の記録がある台風、例: 5111/MARGE, 1951年）。
`--all`オプション（`data/index.json`の全台風、約1954件を試し、ページが
無い台風は404が返るだけで`{"notFound": true}`として記録・スキップされる
ので全件試すのが安全）で再取得し、TYDBに実際のページがある台風は
291→855まで増えました。ただしそのうち約400台風は、TYDBのページ・
表自体はあるものの**全項目が0**（死者・行方不明者/負傷者/全壊/...
すべて0）で、実質「被害なし」でした（`list_damage_gaps.py`の
`has_real_damage_table()`はこれを除外するよう修正済み）。**実際に
何らかの被害件数がある台風は455台風**です。

```bash
python3 scripts/fetch_tydb_damage.py --all   # Colabでは③のセルが既定でこれ
```

このうち気圧配置・AMeDAS観測網データがまだ無いものは次のコマンドで
確認できます:

```bash
python3 scripts/list_damage_gaps.py            # 人が読む形式のレポート
python3 scripts/list_damage_gaps.py --kind obs # --codes にそのまま渡せるカンマ区切り
```

2026-08-10時点（初回計測）: 実質被害455台風中、気圧配置が無いもの188台風、
風データが無いもの207台風、雨データが無いもの174台風。「風データが無い」
の判定は、AMeDAS観測網ファイルに実際の値が1つも無く、かつ旧156地点網
（`data/storms/<コード>.json`の`wind`/`rain`）にも値が無い場合のみを
指します（フロントエンドの`dataHasAnyValue()`/`currentObsSource()`の
フォールバックと同じ判定）。1961年より前の台風は気象庁が風速をまだ
電子化していないため、このスクリプトが「欠落」として挙げても取得
できるデータが存在しない場合があります（後述の1./2.の取得手順を試した
上で、それでも埋まらなければ元データ不在と判断してください）。

### 1. AMeDAS観測網データ（`data/storms_obs/`） — 完了（2026-08-11）

`scripts/list_damage_gaps.py --kind obs`が挙げていた台風分のAMeDAS
風・雨データをColabで取得・push済みです。次のコマンドで`--codes`に
直接渡す形で実行しました:

```bash
python3 scripts/fetch_amedas_obsdl.py --codes $(python3 scripts/list_damage_gaps.py --kind obs) --kind wind,rain --sleep 1.0
```

（`--sleep`はデフォルト3秒のリクエスト間隔を短縮するオプション。obsdl側に
明記されたレート制限が無いため1秒に縮めて実行した。`fetch_amedas_obsdl.py`
参照。）

2026-08-11時点: 雨データの欠落は0台風。風データの欠落は51台風のみで、
いずれも1951〜1960年の台風（気象庁が風速をまだ電子化していない時代）
のため、これ以上取得できるデータはありません。

対応方法（Colabだけで完結、まだ欠落が残っている場合の再実行用）:
`notebooks/fetch_and_convert_amedas_colab.ipynb`をColabで上から実行して
ください（④のセルが上記コマンドを実行する形に更新済みです。取得→
変換→pushまで自動）。既に取得済みの台風は自動スキップされるので、
再実行すれば追加分だけが処理されます。GitHubへのpushで`getpass`の
トークン入力がうまくいかない場合は、`google.colab.userdata`（Colabの
「シークレット」機能）でトークンを渡す方式に切り替えてください。

### 2. JRA-3Q気圧データ（`data/pressure/`） — ほぼ完了（2026-08-11、残り1台風）

`scripts/list_damage_gaps.py --kind pressure`が挙げていた188台風分の
気圧配置データをColabで取得・push済みです（`8310`＝1983年台風10号は
以前GDEX側のサーバーエラーが恒久的と見られていましたが、今回の再取得で
正常に取得できました）。**残り1台風`8422`（1984年台風22号 VANESSA）の
みが未取得**です。

```bash
python3 scripts/list_damage_gaps.py --kind pressure
```

対応方法: `notebooks/jra3q_colab_download.ipynb`→
`notebooks/build_pressure_json_colab.ipynb`の順にColabで再実行してく
ださい（どちらも`list_damage_gaps.py --kind pressure`の出力を`--codes`
に渡す形なので、今は`8422`の月だけが対象になります）。8310の例からも、
一度失敗した月がGDEX側の一時的な問題で、再実行すれば取得できることが
あります。何度か再実行しても取得できない場合は、8310の旧記述と同様に
「元データ不在」として運用してください（フロントエンドは気圧配置
データが無い台風でも、等圧線を表示しないだけで経路・風・雨の表示には
影響しません）。

### 3. フロントエンドの実ブラウザでの見た目確認 — 完了（2026-08-07）

以前のセッションではサンドボックスからLeaflet CDN
（cdnjs.cloudflare.com）へアクセスできず未確認でしたが、このセッションで
`npm pack leaflet@1.9.4` により取得したLeafletをテスト用に一時的に
ローカルvendorし（コミットはしていません。本番の`index.html`は引き続き
CDN参照のまま）、Playwright（Chromium）で実際に描画確認しました。
GSIのタイルCDN（cyberjapandata.gsi.go.jp）もサンドボックスからは
到達不可のため背景地図タイルは表示されませんが、Leaflet自体・オーバー
レイ（経路線、観測マーカー、等圧線）の描画ロジックはタイルの有無に
依存しないため問題なく検証できました。確認結果:
- 風モード: AMeDAS観測網（1999年 台風9918号 BARTなど）で風向風速の矢印
  マーカーが日本全国に正しい位置・色分けで表示されることを確認。
- 雨モード: 同様に降水量の丸マーカー（大きさ・色分け）が正しく表示され
  ることを確認。
- 気圧配置モード: 等圧線（20hPa太線・4hPa細線、白色ライン、hPaラベル）
  が滑らかに描画されることを確認。
- 観測データが無い古い台風（1954年 台風1号など）を選択した場合、
  経路のみが表示され「観測データなし・経路のみ」と正しく案内される
  ことを確認（旧156地点網／新AMeDAS網どちらのデータも無い場合の
  フォールバック表示）。
- モード切替ボタン（風/雨/気圧）・年/台風選択・タイムラインスライダー
  などのUI操作もJSエラーなく動作。

残タスクとしては、実際のタイル表示（地図の見た目）とマーカーの
パフォーマンス（976/1669地点同時表示時の描画速度）は、外部ネットワーク
制限のない環境でのみ確認可能です。

## 被害状況の都道府県別マップ

「被害 Damage」モード（風/雨の切り替えボタンの隣）を選ぶと、実際の
国土地理院地図の上に都道府県ごとの被害の色分け（choropleth）が重なって
表示されます。色分けは `data/tydb_damage/<コード>.json` の都道府県別
被害件数（`damageTier()`、index.html内）に基づく、件数の多寡を問わない
固定5段階のルールです（相対比較や加重スコアではありません）。各都道府県
は、該当する条件のうち最も重い区分の色になります。

| 色 | 条件 |
| --- | --- |
| 赤紫（最も濃い） | 死者・行方不明者 1人以上 |
| 赤 | 全壊（全壊/流失/焼失）1棟以上、または負傷者 1人以上 |
| 濃い橙 | 半壊（半壊/半焼）1棟以上 |
| 橙 | 一部破損 1棟以上 |
| 黄 | 浸水（床上/床下）1棟以上、または非住家 1棟以上 |
| グレー | 被害報告なし |

（時系列ではなく、台風ごとの最終的な被害の比較です。）都道府県に
カーソルを合わせると、死者・行方不明者、負傷者、全壊などの実数の内訳が
ツールチップで表示されます（色分けは上記の基準ですが、ツールチップは
加工していない実数です）。

境界ポリゴン（`data/japan_prefectures.geojson`、実際の緯度経度）は、
CC-BY 4.0ライセンスの [japan-choropleth](https://www.npmjs.com/package/japan-choropleth)
（Copyright (c) 2026 Kyodo News、元データは国土交通省 国土数値情報
「[行政区域データ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html)」
CC-BY 4.0）から座標データのみを抽出してvendorしたものです。
