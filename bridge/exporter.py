# -*- coding: utf-8 -*-
"""
bridge/exporter.py
ソルバー向けファイル出力のブリッジ層。
実装は modeling/core.py および orbit_heat/orbit_core.py, orbit_radiation.py に存在し、
このモジュールは外部ソルバーとのファイル交換インターフェースを一箇所に集約する。
"""


def export_thermal_model_inp(filepath, options_data=None, control_data=None, default_initial_temperature=20.0):
    """
    ノード・伝熱・輻射コンダクタンスを熱解析ソルバー用 .inp で一括出力する。

    Parameters
    ----------
    filepath : str
        出力ファイルパス
    options_data : dict, optional
        HEADER OPTIONS DATA の KEY=VALUE ペア（例: {"OUTPUT.DQ": "TRUE"}）
    control_data : dict, optional
        HEADER CONTROL DATA の KEY=VALUE ペア（例: {"ANALYSIS": "STEADY"}）
    default_initial_temperature : float, optional
        初期温度 [℃]（デフォルト: 20.0）
    """
    from ThermalAnalysis.modeling import core
    return core.export_thermal_model_inp(
        filepath,
        options_data=options_data,
        control_data=control_data,
        default_initial_temperature=default_initial_temperature,
    )


def export_nodes_and_conductance_dat(filepath):
    """
    ノードリストと伝熱コンダクタンスリストを .dat 形式で出力する。

    Parameters
    ----------
    filepath : str
        出力ファイルパス
    """
    from ThermalAnalysis.modeling import core
    return core.export_nodes_and_conductance_dat(filepath)


def export_radiation_dat(filepath):
    """
    輻射コンダクタンスリストを .dat 形式で出力する。

    Parameters
    ----------
    filepath : str
        出力ファイルパス
    """
    from ThermalAnalysis.modeling import core
    return core.export_radiation_dat(filepath)


def export_heat_array_csv(filepath, times, heat_array, meta):
    """
    軌道熱入力配列を CSV 形式で出力する。

    Parameters
    ----------
    filepath : str
        出力ファイルパス
    times : array-like
        時刻列 [s]
    heat_array : np.ndarray
        面ごとの熱入力配列 (n_times × n_surfaces)
    meta : dict
        列名などのメタデータ（"columns" キーに面名リスト）
    """
    from ThermalAnalysis.orbit_heat import orbit_core
    return orbit_core.export_heat_array_csv(filepath, times, heat_array, meta)


def export_face_heat_csv(filepath, results):
    """
    面ごと熱入力計算結果を CSV 形式で出力する。

    Parameters
    ----------
    filepath : str
        出力ファイルパス
    results : list[dict]
        orbit_radiation.compute_face_heat_inputs の戻り値
    """
    from ThermalAnalysis.orbit_heat import orbit_radiation
    return orbit_radiation.export_face_heat_csv(filepath, results)
