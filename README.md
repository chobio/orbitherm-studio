# Orbitherm Studio

FreeCAD-based thermal modeling workbench for spacecraft and engineering systems.

FreeCADベースの宇宙機・工学システム向け熱解析モデリング環境

---

## 概要

**Orbitherm Studio** は、FreeCAD 上で熱ネットワークモデルを構築するワークベンチです。
ノード・コンダクタ・放射モデルの作成から、軌道熱入力の計算、外部ソルバーへのエクスポートまでを統合した環境を提供します。

FreeCAD の Workbench 一覧には **Orbitherm** として表示されます。

> ソルバー側は **Orbitherm Solver**（別リポジトリ）が担当します。
> Orbitherm Solver は SINDA ライクな熱ネットワークソルバーで、定常解析・過渡解析に対応します。

---

## 構成

- **modeling** — 熱モデル構築・コンダクタンス計算
  - モデル準備、面プロパティ編集、熱容量・伝熱・輻射コンダクタンス計算、エクスポート、可視化
- **orbit_heat** — 軌道熱計算
  - 軌道計算と描画、熱入力 CSV、輻射モデルへの軌道熱適用
- **bridge** — 外部ソルバー連携・ファイル出力
- **post** — ポスト処理・結果可視化
- **solver** — ソルバー連携（Orbitherm Solver との接続領域）

---

## インストール

1. この `orbitherm-studio` フォルダを FreeCAD の Mod ディレクトリに配置します。
   - ユーザー Mod: `%APPDATA%\FreeCAD\Mod\orbitherm-studio`（Windows）
   - または FreeCAD インストール先の `Mod/orbitherm-studio`
2. FreeCAD を起動し、ワークベンチ一覧から **Orbitherm** を選択します。

---

## 使い方

- **モデリング**: ツールバー「Modeling」またはメニュー「Modeling」から、
  モデル準備・プロパティ編集・コンダクタンス計算・エクスポートなどを実行します。
- **軌道熱**: ツールバー「Orbit Heat」またはメニュー「Orbit Heat」から、
  軌道計算と描画・熱入力 CSV 保存・輻射モデルに軌道熱を適用 などを実行します。
- **ポスト処理**: ポストメニューから解析結果の可視化を行います。

---

## ブランド体系

| 名称 | 用途 |
|---|---|
| **Orbitherm** | 親ブランド名 |
| **Orbitherm Studio** | FreeCAD ワークベンチ（本ワークベンチ） |
| **Orbitherm Solver** | SINDAライク熱ネットワークソルバー |

### GitHub リポジトリ名（予定）
- `orbitherm-studio` — 本ワークベンチ
- `orbitherm-solver` — ソルバー

### Python パッケージ名（予定）
- `orbitherm_studio`
- `orbitherm_solver`

---

## 移行状況

旧名称 `RadiationAnalysis` および `OrbitHeatWorkbench` は本ワークベンチに統合済みです。
コマンド登録名 `ThermalAnalysis_*` は内部互換性のため現在も使用されますが、
将来的に `Orbitherm_*` プレフィックスへ段階移行予定です。

旧 `RadiationAnalysis_*` コマンドへのエイリアスは互換維持のため引き続き登録されます。
