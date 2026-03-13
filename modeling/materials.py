import json
import os
from typing import Dict, List, Optional


def get_materials_filepath() -> str:
    """
    materials.json ファイルへの絶対パスを返す。
    Workbench フォルダ直下に配置された JSON を前提とする。
    """
    addon_dir = os.path.dirname(__file__)
    return os.path.join(addon_dir, "materials.json")


def _default_materials() -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    materials.json が存在しない場合に使用するデフォルト構造。
    """
    return {
        "optical_materials": {
            "黒体塗装": {
                "solar_absorptivity": 0.95,
                "infrared_emissivity": 0.95,
                "transmittance": 0.0,
            }
        },
        "physical_materials": {
            "アルミニウム": {
                "thickness": 0.001,
                "density": 2700.0,
                "specific_heat": 900.0,
                "thermal_conductivity": 167.0,
            }
        },
    }


def load_materials() -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    materials.json を読み込んで辞書として返す。
    存在しない場合はデフォルト値で作成してから返す。
    """
    filepath = get_materials_filepath()
    if not os.path.exists(filepath):
        data = _default_materials()
        save_materials(data)
        return data

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_materials(data: Dict[str, Dict[str, Dict[str, float]]]) -> None:
    """
    マテリアルデータ（辞書）を materials.json に保存する。
    """
    filepath = get_materials_filepath()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# === 公開 API: 名前一覧取得 ===


def list_optical_names() -> List[str]:
    materials = load_materials()
    return list(materials.get("optical_materials", {}).keys())


def list_physical_names() -> List[str]:
    materials = load_materials()
    return list(materials.get("physical_materials", {}).keys())


# === 公開 API: 個別取得 ===


def get_optical(name: str) -> Optional[Dict[str, float]]:
    materials = load_materials()
    return materials.get("optical_materials", {}).get(name)


def get_physical(name: str) -> Optional[Dict[str, float]]:
    materials = load_materials()
    return materials.get("physical_materials", {}).get(name)


# === 公開 API: 追加・更新・削除 ===


def upsert_optical(
    name: str,
    solar_absorptivity: float,
    infrared_emissivity: float,
    transmittance: float = 0.0,
) -> None:
    materials = load_materials()
    optical = materials.setdefault("optical_materials", {})
    optical[name] = {
        "solar_absorptivity": float(solar_absorptivity),
        "infrared_emissivity": float(infrared_emissivity),
        "transmittance": max(0.0, min(1.0, float(transmittance))),
    }
    save_materials(materials)


def delete_optical(name: str) -> None:
    materials = load_materials()
    optical = materials.get("optical_materials", {})
    if name in optical:
        del optical[name]
        save_materials(materials)


def upsert_physical(
    name: str,
    thickness: float,
    density: float,
    specific_heat: float,
    thermal_conductivity: float,
) -> None:
    materials = load_materials()
    physical = materials.setdefault("physical_materials", {})
    physical[name] = {
        "thickness": float(thickness),
        "density": float(density),
        "specific_heat": float(specific_heat),
        "thermal_conductivity": float(thermal_conductivity),
    }
    save_materials(materials)


def delete_physical(name: str) -> None:
    materials = load_materials()
    physical = materials.get("physical_materials", {})
    if name in physical:
        del physical[name]
        save_materials(materials)

