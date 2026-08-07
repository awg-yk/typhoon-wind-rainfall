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

  **既知の欠損**: `198310`（1983年10月）のみ、静的ファイルサーバー・OPeNDAP
  どちらの経路でも `500 Internal Server Error` / `DAP server error`（GDEX側で
  元データの取得自体がタイムアウトしている）となり取得できていません。何度
  リトライしても同じ理由で失敗するため、一時的な混雑ではなくGDEX側のこの
  ファイル固有の問題とみられます。そのため台風8310（1983年10号）の気圧配置
  データのみ欠けています。将来GDEX側で直っていれば再取得できます。
- `scripts/build_pressure_json.py` … 上記でダウンロードした月別netCDF
  ファイル（`data/raw_jra3q/` などローカルの保存先）を、台風ごとの経路期間に
  合わせて `data/pressure/<台風コード>.json`（`{lat:[...], lon:[...],
  times:[...JST...], values:[[[hPa整数,...]...]...]}`）に切り出すスクリプト。
  格子は既定で間引き（`--stride 2`、緯度経度とも半分の解像度）、値は整数hPaに
  丸めてファイルサイズを抑えています（等圧線の描画には十分な精度）。生の
  netCDFファイルは大きすぎるためリポジトリには含めず、この変換後のJSONだけを
  コミットします。上記の欠損月をまたぐ台風（8310）は変換時にスキップされ
  `data/pressure/8310.json` は存在しません（フロントエンドはその場合、気圧
  モードで等圧線を表示しないだけで、経路・風・雨の表示には影響しません）。
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
- **月**（プルダウン）: 経路が該当した月（`data/index.json` の `months`）で絞り込みます。

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

## 現状・引き継ぎ事項（次のセッション向け）

冒頭で挙げた4つの改善（①全台風収録 ②観測網拡張 ③JRA-3Qへの切替 ④絞り込み
機能）はいずれも実装済みです。ただし以下は未完了・要作業です。

### 1. AMeDAS観測網データ（`data/storms_obs/`）がまだ全台風分揃っていない

現時点（このセッション終了時点）で `data/storms_obs/` には130台風分
（うち上陸・通過台風`landfallJP=true`の221台風中106台風分）のみpush済み。
**残り115台風分は未変換・未pushです。**

対応方法（このセッション内で確立済みの手順）:
1. 手元PCで `python3 scripts/fetch_amedas_obsdl.py --landfall-only --kind wind,rain`
   を実行し、まだ取得していない台風のCSVを `data/raw_amedas/` に取得
   （既存ファイルはスキップされるので再実行で差分だけ取れます）
2. `data/raw_amedas/` の中身をGoogle Driveにアップロード
3. `notebooks/convert_amedas_csv_colab.ipynb` をColabで実行し、変換・push
   （GitHubへのpushには手元の`git`操作ではなくColab上でPersonal Access
   Tokenを使う方式を確立済み。**Colabの `getpass` は稀にマスク表示の
   ドット文字列をそのまま値として拾ってしまう不具合があったため、
   `google.colab.userdata`（Colabの「シークレット」機能）でトークンを
   渡す方式を推奨**）

### 2. JRA-3Q気圧データ（`data/pressure/`）は220/221台風分で完了

残り1台風（`8310`、1983年台風10号）だけ、GDEX側のサーバーエラー
（`500 Internal Server Error` / `DAP server error`、元データ取得の
タイムアウト）が静的ファイル配信・OPeNDAPどちらの経路でも再現し、
リトライでは解決できないことを確認済み。GDEX側の状況が変わらない限り
このまま欠損として運用する想定（詳細は上記「フォルダの中身」の
`download_jra3q_pressure.py` の項を参照）。

### 3. フロントエンドの実ブラウザでの見た目確認が未実施

このセッションの作業環境（サンドボックス）からはLeaflet CDN
（cdnjs.cloudflare.com）へのHTTPSアクセスがブロックされており、
`index.html` を実際にブラウザで開いての見た目確認ができていません。
気圧配置モード（等圧線描画・平滑化・白色ライン・hPaラベル）とAMeDAS
観測網モード（風/雨、976/1669地点のマーカー切り替え）は、ロジックの
単体テスト（Node.jsでの構文チェック・データ整合性チェック）のみ実施
済みです。次のセッションでは、ローカルまたはブラウザにアクセスできる
環境で `python3 -m http.server 8000` を立てて実際に開き、以下を
確認することを推奨します。
- 風/雨モードでAMeDAS観測網のマーカーが正しい位置・値で表示されるか
  （特に976/1669という多数マーカーでのパフォーマンス）
- 気圧配置モードの等圧線の見た目（平滑化の効き具合、ラベルの可読性）
- 旧156地点網へのフォールバックが正しく機能するか（`data/storms_obs/`
  が無い台風を選んだ場合）
