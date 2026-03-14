# Orbitherm Studio — モジュール構成図
<!-- 公式ブランド名: Orbitherm Studio / 内部パッケージ名: ThermalAnalysis -->

最終更新: 2026-03-13

---

## ディレクトリ構造

```
ThermalAnalysis/                         ← FreeCAD Mod ルート（Orbitherm Studio）
│
├── InitGui.py                           ← FreeCAD エントリポイント
│   ├── ワークベンチ登録・ツールバー/メニュー定義
│   ├── ホバーコールバック・ツリーフィルター（インフラ）
│   ├── [ローカルクラス定義 ← 互換用、後で import * に上書き]
│   └── from ThermalAnalysis.gui.commands import *  ← 登録直前で上書き
│
├── gui/                                 ── UI・コマンド層
│   ├── __init__.py                      ← 全パブリック名を再エクスポート
│   ├── commands.py                      ← FreeCAD コマンドクラス（正規の定義源）
│   │   ├── ThermalAnalysis_Modeling_*  （モデリング系 14 コマンド）
│   │   ├── ThermalAnalysis_Post_*      （ポスト処理 1 コマンド）
│   │   ├── ThermalAnalysis_Orbit_*     （軌道熱 6 コマンド）
│   │   └── _LegacyRadiationCommandAlias
│   ├── panels.py                        ← Qt ダイアログ・タスクパネル群
│   │   ├── PrepareModelDialog
│   │   ├── EditPropertiesTaskPanel
│   │   ├── MaterialEditorDialog
│   │   ├── BulkPropertiesDialog
│   │   ├── RadiationParamsDialog
│   │   ├── ThermalModelExportDialog
│   │   ├── PostProcessingDialog
│   │   ├── DisplayOptionsDialog
│   │   ├── DisplayParametersSettingsDialog
│   │   ├── SubdivideSurfaceDialog
│   │   └── DefeaturingDialog
│   ├── orbit_gui.py                     ← OrbitEnvironmentDialog
│   └── orbit_step_dialog.py             ← OrbitStepDialog
│
├── modeling/                            ── ジオメトリ・モデル生成層
│   ├── core.py                          ← メッシュ準備・熱物性・コンダクタンス・輻射計算
│   ├── calculation.py                   ← 熱容量・コンダクタンス計算ロジック
│   ├── materials.py                     ← マテリアルライブラリ
│   ├── defeaturing.py                   ← 形状簡略化
│   ├── freecad_utils.py                 ← FreeCAD ユーティリティ
│   ├── radiation_worker.py              ← 輻射ビューファクター並列計算
│   └── gui_panels.py                    ← [互換シム] from gui.panels import *
│
├── orbit_heat/                          ── 軌道熱計算層
│   ├── orbit_core.py                    ← 軌道計算・熱入力・CSV 出力
│   ├── orbit_attitude.py                ← 衛星姿勢計算
│   ├── orbit_radiation.py               ← 面ごと熱入力・輻射モデルへの適用
│   ├── orbit_visualization.py           ← 軌道 3D 可視化
│   ├── orbit_gui.py                     ← [互換シム] from gui.orbit_gui import *
│   ├── orbit_step_dialog.py             ← [互換シム] from gui.orbit_step_dialog import *
│   └── orbit_heat_bridge.py             ← [互換シム] from bridge.orbit_heat_bridge import *
│
├── post/                                ── 結果可視化層
│   └── __init__.py                      ← modeling/core.py の可視化関数へのラッパー群
│
├── bridge/                              ── 外部ソルバー連携層
│   ├── __init__.py                      ← 全エクスポート名を再エクスポート
│   ├── orbit_heat_bridge.py             ← 輻射モデル → 軌道熱の面リスト変換
│   └── exporter.py                      ← ソルバー向けファイル出力ラッパー
│       ├── export_thermal_model_inp()   → modeling/core.py
│       ├── export_nodes_and_conductance_dat() → modeling/core.py
│       ├── export_radiation_dat()       → modeling/core.py
│       ├── export_heat_array_csv()      → orbit_heat/orbit_core.py
│       └── export_face_heat_csv()       → orbit_heat/orbit_radiation.py
│
└── solver/                              ── 外部ソルバー（変更しない）
    └── __init__.py
```

---

## 依存関係フロー

```
                    ┌─────────────────────────────┐
                    │         InitGui.py           │
                    │  (ワークベンチ・登録・インフラ)  │
                    └──────────┬──────────────────┘
                               │ import *
                               ▼
              ┌────────────────────────────────────┐
              │             gui/                   │
              │  commands.py  panels.py  orbit_gui │
              └───┬───────────────┬────────────────┘
                  │ calls         │ opens dialog
                  ▼               ▼
     ┌────────────────┐   ┌──────────────────────┐
     │  modeling/     │   │    orbit_heat/        │
     │  core.py 他    │   │  orbit_core.py 他     │
     └───────┬────────┘   └──────────┬───────────┘
             │                       │
             └───────────┬───────────┘
                         ▼
              ┌─────────────────────┐
              │      bridge/        │
              │  exporter.py        │  ← ファイル交換の一本化
              │  orbit_heat_bridge  │  ← モデル↔軌道熱の橋渡し
              └─────────────────────┘
                         │ ファイル出力
                         ▼
              ┌─────────────────────┐
              │   外部ソルバー       │
              │  (.inp / .dat / CSV) │
              └─────────────────────┘
```

---

## 層の役割まとめ

| 層 | 主な責務 |
|---|---|
| **`gui/`** | Qt ダイアログ + FreeCAD コマンドクラス（ユーザー操作の受け口） |
| **`modeling/`** | メッシュ生成・熱物性・コンダクタンス・輻射の計算と FreeCAD ドキュメント操作 |
| **`orbit_heat/`** | 軌道力学・太陽熱入力・可視化の計算 |
| **`post/`** | 計算結果の 3D ビュー表示（`modeling/core.py` の可視化関数のラッパー） |
| **`bridge/`** | ① 輻射モデル↔軌道熱の接続 ② ソルバー向けファイル出力の一本化 |

---

## 互換シムについて

以下のファイルは移行後の互換性維持のため残してある薄いシム（`import *` のみ）。
将来的には削除予定。

| シムファイル | 正規の定義先 |
|---|---|
| `modeling/gui_panels.py` | `gui/panels.py` |
| `orbit_heat/orbit_gui.py` | `gui/orbit_gui.py` |
| `orbit_heat/orbit_step_dialog.py` | `gui/orbit_step_dialog.py` |
| `orbit_heat/orbit_heat_bridge.py` | `bridge/orbit_heat_bridge.py` |
| `InitGui.py` 内ローカルクラス定義 | `gui/commands.py` |
