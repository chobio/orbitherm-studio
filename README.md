# ThermalAnalysis ワークベンチ

FreeCAD 用の熱解析ワークベンチです。輻射・伝熱モデルの作成と軌道熱解析を一つのワークベンチで利用できます。

## 構成

- **modeling** — 熱モデル・コンダクタンス（旧 RadiationAnalysis の輻射・伝熱機能）
  - モデル準備、面プロパティ編集、熱容量・伝熱・輻射コンダクタンス計算、エクスポート、可視化
- **orbit_heat** — 軌道熱（旧 OrbitHeatWorkbench）
  - 軌道計算と描画、熱入力 CSV、輻射モデルへの軌道熱適用
- **solver** — ソルバー（予定・プレースホルダ）
- **post** — ポスト処理（予定・プレースホルダ）

## インストール

1. この `ThermalAnalysis` フォルダを FreeCAD の Mod ディレクトリに配置します。
   - ユーザー Mod: `%APPDATA%\FreeCAD\Mod\ThermalAnalysis`（Windows）
   - または FreeCAD インストール先の `Mod/ThermalAnalysis`
2. FreeCAD を起動し、ワークベンチ一覧から「熱解析」を選択します。

## 使い方

- **モデリング**: ツールバー「モデリング」またはメニュー「モデリング」から、モデル準備・プロパティ編集・コンダクタンス計算・エクスポートなどを実行します。
- **軌道熱**: ツールバー「軌道熱」またはメニュー「軌道熱」から、軌道計算と描画・熱入力 CSV 保存・輻射モデルに軌道熱を適用 などを実行します。

旧 RadiationAnalysis / OrbitHeatWorkbench は本ワークベンチに統合済みのため、併用する必要はありません。
