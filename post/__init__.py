# -*- coding: utf-8 -*-
"""
Orbitherm Studio — Post サブパッケージ (ThermalAnalysis.post)。
解析結果の表示・後処理関数をここから参照できる。
実装は modeling/core.py に存在し、このモジュールはラッパーとして再エクスポートする。
"""


def visualize_active_side():
    """アクティブ面の表示色を更新する。"""
    from orbitherm_studio.modeling import core
    return core.visualize_active_side()


def visualize_property_contour(prop_name, prop_label):
    """指定プロパティ（吸収率・放射率・透過率）のコンター表示を適用する。"""
    from orbitherm_studio.modeling import core
    return core.visualize_property_contour(prop_name, prop_label)


def restore_default_display():
    """面の表示色をデフォルトに戻す。"""
    from orbitherm_studio.modeling import core
    return core.restore_default_display()


def parse_thermal_out(filepath):
    """熱解析 .out ファイルを解析し、(time, node_temperatures) のリストを返す。"""
    from orbitherm_studio.modeling import core
    return core.parse_thermal_out(filepath)


def visualize_temperature_contour(temperatures_by_node_id, t_min, t_max):
    """ノード温度辞書を受け取り、3D ビューにコンター表示する。"""
    from orbitherm_studio.modeling import core
    return core.visualize_temperature_contour(temperatures_by_node_id, t_min, t_max)


def get_node_visibility():
    """ノードの表示状態 (visible, has_nodes) を返す。"""
    from orbitherm_studio.modeling import core
    return core.get_node_visibility()


def set_node_visibility(visible):
    """ノードの表示/非表示を切り替える。"""
    from orbitherm_studio.modeling import core
    return core.set_node_visibility(visible)


def get_conduction_conductance_visibility():
    """伝熱コンダクタンス線の表示状態 (visible, has_items) を返す。"""
    from orbitherm_studio.modeling import core
    return core.get_conduction_conductance_visibility()


def set_conduction_conductance_visibility(visible):
    """伝熱コンダクタンス線の表示/非表示を切り替える。"""
    from orbitherm_studio.modeling import core
    return core.set_conduction_conductance_visibility(visible)


def get_radiation_conductance_visibility():
    """輻射コンダクタンス線の表示状態 (visible, has_items) を返す。"""
    from orbitherm_studio.modeling import core
    return core.get_radiation_conductance_visibility()


def set_radiation_conductance_visibility(visible):
    """輻射コンダクタンス線の表示/非表示を切り替える。"""
    from orbitherm_studio.modeling import core
    return core.set_radiation_conductance_visibility(visible)


# ---------------------------------------------------------------------------
# Persistent Coin3D label display  (canonical entry points)
# ---------------------------------------------------------------------------

def show_face_labels(doc=None):
    """面番号ラベルを 3D ビューに表示する（Coin3D SoText2）。"""
    from orbitherm_studio.post import display_labels
    return display_labels.show_face_labels(doc)


def clear_face_labels():
    """面番号ラベルを 3D ビューから削除する。"""
    from orbitherm_studio.post import display_labels
    return display_labels.clear_face_labels()


def show_node_labels(doc=None):
    """ノード番号ラベルを 3D ビューに表示する（Coin3D SoText2）。"""
    from orbitherm_studio.post import display_labels
    return display_labels.show_node_labels(doc)


def clear_node_labels():
    """ノード番号ラベルを 3D ビューから削除する。"""
    from orbitherm_studio.post import display_labels
    return display_labels.clear_node_labels()


def is_face_labels_visible():
    """面番号ラベルが現在表示中かどうかを返す。"""
    from orbitherm_studio.post import display_labels
    return display_labels.is_face_labels_visible()


def is_node_labels_visible():
    """ノード番号ラベルが現在表示中かどうかを返す。"""
    from orbitherm_studio.post import display_labels
    return display_labels.is_node_labels_visible()
