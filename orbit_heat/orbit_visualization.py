from __future__ import annotations

import os
from typing import Iterable, Sequence, Tuple

import FreeCAD
import Part

import numpy as np

from ThermalAnalysis.orbit_heat import orbit_core, orbit_attitude


KM_TO_MM = 1.0  # 1 km = 1 mm スケール
EARTH_RADIUS_KM = 6371.0
# 地球テクスチャの向き合わせ: 球そのものを回転させる（2軸まで指定可）。
# 回転軸 (x,y,z): (1,0,0)=X軸（赤道）, (0,1,0)=Y軸（赤道）, (0,0,1)=北極軸（経度方向）
# 1回目 → 2回目の順で適用。不要な軸は 0.0 にすると無効。
EARTH_TEXTURE_ROTATION_AXIS = (1, 0, 0)
EARTH_TEXTURE_ROTATION_DEG = -90.0
EARTH_TEXTURE_ROTATION_AXIS_2 = (0, 0, 1)
EARTH_TEXTURE_ROTATION_DEG_2 = 180.0


def _get_default_font_path() -> str:
    """ShapeString 用のデフォルトフォントパスを返す。"""
    if os.name == "nt":
        return os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if os.path.isfile(path):
            return path
    return ""


def _create_pole_cone_fallback(
    doc: FreeCAD.Document,
    group,
    text: str,
    position_mm: FreeCAD.Vector,
) -> None:
    """テキストが使えない場合、円錐で北(N)・南(S)を区別する。N=上向き、S=下向き。"""
    try:
        radius = 400.0
        height = 800.0
        cone = Part.makeCone(radius, radius * 0.3, height)
        obj = doc.addObject("Part::Feature", "PoleLabel_{}".format(text))
        obj.Shape = cone
        obj.Label = text
        # N は +Z 向き、S は -Z 向きになるよう回転
        if text.upper() == "S":
            obj.Placement = FreeCAD.Placement(
                position_mm,
                FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 180),
            )
        else:
            obj.Placement = FreeCAD.Placement(position_mm, FreeCAD.Rotation())
        if hasattr(obj, "ViewObject"):
            obj.ViewObject.ShapeColor = (1.0, 1.0, 0.0)
        group.addObject(obj)
    except Exception as e:
        FreeCAD.Console.PrintWarning("OrbitHeat: 極マーカー代替表示でエラー: {}\n".format(e))


def _create_pole_text_label(
    doc: FreeCAD.Document,
    group,
    text: str,
    position_mm: FreeCAD.Vector,
    size_mm: float = 500.0,
    rotation_z_deg: float = 0.0,
) -> None:
    """北極/南極に「N」「S」などのテキストラベルを 3D 形状で追加する。"""
    font = _get_default_font_path()
    if not font or not os.path.isfile(font):
        FreeCAD.Console.PrintWarning("OrbitHeat: フォントが見つかりません。N/Sラベルをスキップします。\n")
        return

    def _make_extruded_label(ss):
        """ShapeString の形状を押し出して立体にする。FreeCAD では shape.extrude(vector) を使用。"""
        if ss.isNull():
            return None
        depth = max(1.0, size_mm * 0.15)
        vec = FreeCAD.Vector(0, 0, depth)
        try:
            # Part.makeExtrude はないため、TopoShape の extrude() メソッドを使用
            ext = ss.extrude(vec)
            return ext if ext and not ext.isNull() else None
        except Exception:
            return None

    ss = None
    # 1) Part.ShapeString を試す（引数は String, FontFile, Size[mm]。バージョンにより順序が違う場合あり）
    if hasattr(Part, "ShapeString"):
        try:
            ss = Part.ShapeString(str(text), font, size_mm)
        except Exception:
            try:
                ss = Part.ShapeString(font, str(text), size_mm)
            except Exception as e:
                FreeCAD.Console.PrintWarning("OrbitHeat: Part.ShapeString でエラー: {}\n".format(e))
                ss = None
        if ss and (ss.isNull() or (not getattr(ss, "Faces", None) and not getattr(ss, "Wires", None) and not getattr(ss, "Edges", None))):
            ss = None

    # 2) 失敗時は Draft の makeShapeString / make_shape_string を試す
    if ss is None and font:
        try:
            import Draft
            make_ss = getattr(Draft, "make_shape_string", None) or getattr(Draft, "makeShapeString", None)
            if make_ss:
                try:
                    dss = make_ss(String=str(text), FontFile=font, Size=size_mm)
                except (TypeError, Exception):
                    try:
                        dss = make_ss(str(text), font, size_mm)
                    except (TypeError, Exception):
                        dss = None
                if dss and getattr(dss, "Shape", None) and not getattr(dss.Shape, "isNull", lambda: True)():
                    ss = dss.Shape
                    doc.removeObject(dss.Name)
        except Exception as e:
            FreeCAD.Console.PrintWarning("OrbitHeat: Draft.ShapeString でエラー: {}\n".format(e))

    if ss is None:
        # テキストが使えない場合は円錐で北/南を区別（北=上向き、南=下向き）
        _create_pole_cone_fallback(doc, group, text, position_mm)
        return

    ext = _make_extruded_label(ss)
    if ext is None:
        try:
            ext = ss  # 押し出し失敗時は2D形状のまま表示
        except Exception:
            return
    try:
        name = "PoleLabel_{}".format(text)
        while doc.getObject(name):
            name = name + "_"
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = ext
        obj.Label = text
        rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), rotation_z_deg)
        obj.Placement = FreeCAD.Placement(position_mm, rot)
        if hasattr(obj, "ViewObject"):
            obj.ViewObject.ShapeColor = (1.0, 1.0, 0.0)  # 黄色で視認しやすく
        group.addObject(obj)
    except Exception as e:
        FreeCAD.Console.PrintWarning("OrbitHeat: ラベルオブジェクトの追加に失敗: {}\n".format(e))


def _ensure_group(doc: FreeCAD.Document) -> FreeCAD.DocumentObjectGroup:
    """OrbitVisualization グループを取得または作成。"""
    group = doc.getObject("OrbitVisualization")
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", "OrbitVisualization")
    return group


def _clear_group(group: FreeCAD.DocumentObjectGroup) -> None:
    """グループ配下オブジェクトを削除。"""
    doc = group.Document
    for obj in list(getattr(group, "Group", []) or []):
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass


def _vector_km_to_mm(v_km) -> FreeCAD.Vector:
    return FreeCAD.Vector(
        float(v_km[0]) * KM_TO_MM,
        float(v_km[1]) * KM_TO_MM,
        float(v_km[2]) * KM_TO_MM,
    )


def _get_earth_texture_path() -> str:
    """地球テクスチャ画像の絶対パスを返す。複数候補を試す。"""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "earth_texture.jpg"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "earth_texture.jpg"),
    ]
    try:
        import FreeCAD as _fc
        cwd = getattr(_fc, "getUserAppDataDir", lambda: "")()
        if cwd:
            candidates.append(os.path.join(cwd, "Mod", "ThermalAnalysis", "orbit_heat", "earth_texture.jpg"))
    except Exception:
        pass
    for p in candidates:
        abs_path = os.path.normpath(os.path.abspath(p))
        if os.path.isfile(abs_path):
            return abs_path
    return os.path.normpath(candidates[0])


def _apply_earth_texture_pivy(obj, texture_path: str) -> bool:
    """
    pivy (Coin3D) の SoTexture2 で地球オブジェクトにテクスチャを適用する。
    ViewProviderPartExt など getRootNode が無い環境では RootNode プロパティや getBackRoot を試す。
    Returns True if applied successfully.
    """
    try:
        from pivy import coin
        vo = obj.ViewObject
        if vo is None:
            return False
        # ViewProviderPartExt には getRootNode が無いため、getattr で参照せずに取得する
        root = getattr(vo, "RootNode", None)
        if root is None:
            for name in ("getBackRoot", "getFrontRoot", "getRootNode"):
                getter = getattr(vo, name, None)
                if getter is not None and callable(getter):
                    try:
                        root = getter()
                        if root is not None:
                            break
                    except Exception:
                        continue
        if root is None:
            return False
        path_for_coin = texture_path.replace("\\", "/")
        tex = coin.SoTexture2()
        tex.filename.setValue(path_for_coin)
        coords = coin.SoTextureCoordinateSphere()
        root.insertChild(tex, 0)
        root.insertChild(coords, 1)
        return True
    except Exception as e:
        try:
            FreeCAD.Console.PrintWarning(
                "Earth texture (pivy): {}\n".format(e)
            )
        except Exception:
            pass
        return False


def _create_earth_sphere(doc: FreeCAD.Document, group) -> None:
    sphere = doc.addObject("Part::Sphere", "Earth")
    sphere.Radius = EARTH_RADIUS_KM * KM_TO_MM
    # テクスチャの向きは球の Placement 回転で合わせる（2軸まで、順に適用）
    r1 = FreeCAD.Rotation(
        FreeCAD.Vector(EARTH_TEXTURE_ROTATION_AXIS[0], EARTH_TEXTURE_ROTATION_AXIS[1], EARTH_TEXTURE_ROTATION_AXIS[2]),
        EARTH_TEXTURE_ROTATION_DEG,
    )
    r2 = FreeCAD.Rotation(
        FreeCAD.Vector(EARTH_TEXTURE_ROTATION_AXIS_2[0], EARTH_TEXTURE_ROTATION_AXIS_2[1], EARTH_TEXTURE_ROTATION_AXIS_2[2]),
        EARTH_TEXTURE_ROTATION_DEG_2,
    )
    if abs(EARTH_TEXTURE_ROTATION_DEG) > 1e-6 or abs(EARTH_TEXTURE_ROTATION_DEG_2) > 1e-6:
        sphere.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), r1 * r2)
    if hasattr(sphere, "ViewObject"):
        sphere.ViewObject.ShapeColor = (1.0, 1.0, 1.0)
        sphere.ViewObject.Transparency = 0
        texture_path = _get_earth_texture_path()
        try:
            FreeCAD.Console.PrintMessage(
                "Earth texture path: {} (exists: {})\n".format(
                    texture_path, os.path.isfile(texture_path)
                )
            )
        except Exception:
            pass
        if os.path.isfile(texture_path):
            applied = False
            if hasattr(sphere.ViewObject, "TextureImage"):
                try:
                    sphere.ViewObject.TextureImage = texture_path
                    applied = True
                except Exception as ex:
                    try:
                        FreeCAD.Console.PrintWarning(
                            "Earth texture (TextureImage): {}\n".format(ex)
                        )
                    except Exception:
                        pass
            if not applied:
                applied = _apply_earth_texture_pivy(sphere, texture_path)
            if not applied:
                try:
                    FreeCAD.Console.PrintWarning(
                        "Earth texture could not be applied (path: {})\n".format(texture_path)
                    )
                except Exception:
                    pass
        else:
            try:
                FreeCAD.Console.PrintWarning(
                    "Earth texture file not found: {}\n".format(texture_path)
                )
            except Exception:
                pass
    group.addObject(sphere)


def _create_earth_axis(doc: FreeCAD.Document, group) -> None:
    """地軸（Z 軸）と北極・南極マーカーを追加。軌道の傾斜が分かるようにする。"""
    r_mm = EARTH_RADIUS_KM * KM_TO_MM
    axis_len = r_mm * 1.5  # 地表より少し伸ばす
    north = FreeCAD.Vector(0, 0, axis_len)
    south = FreeCAD.Vector(0, 0, -axis_len)
    line = Part.makeLine(south, north)
    axis_obj = doc.addObject("Part::Feature", "EarthAxis")
    axis_obj.Shape = line
    if hasattr(axis_obj, "ViewObject"):
        axis_obj.ViewObject.LineColor = (0.6, 0.8, 1.0)
        if hasattr(axis_obj.ViewObject, "LineWidth"):
            axis_obj.ViewObject.LineWidth = 2.0
    group.addObject(axis_obj)
    # 北極マーカー（小さな球）
    np_marker = doc.addObject("Part::Sphere", "NorthPole")
    np_marker.Radius = 200.0
    np_marker.Placement = FreeCAD.Placement(north, FreeCAD.Rotation())
    if hasattr(np_marker, "ViewObject"):
        np_marker.ViewObject.ShapeColor = (1.0, 1.0, 1.0)
    group.addObject(np_marker)
    # 南極マーカー
    sp_marker = doc.addObject("Part::Sphere", "SouthPole")
    sp_marker.Radius = 200.0
    sp_marker.Placement = FreeCAD.Placement(south, FreeCAD.Rotation())
    if hasattr(sp_marker, "ViewObject"):
        sp_marker.ViewObject.ShapeColor = (0.7, 0.7, 0.8)
    group.addObject(sp_marker)

    # 北極・南極の向きが分かるよう「N」「S」ラベルを追加
    label_offset = 600.0  # マーカー球の外側に配置
    label_size = 500.0
    _create_pole_text_label(
        doc, group, "N",
        FreeCAD.Vector(0, 0, axis_len + label_offset),
        size_mm=label_size,
        rotation_z_deg=0,
    )
    _create_pole_text_label(
        doc, group, "S",
        FreeCAD.Vector(0, 0, -axis_len - label_offset),
        size_mm=label_size,
        rotation_z_deg=180,  # -Z 側から見て正しく読めるように
    )


def _create_equator(doc: FreeCAD.Document, group) -> None:
    """赤道の線（XY 平面の円）を追加。"""
    r_mm = EARTH_RADIUS_KM * KM_TO_MM
    n_pts = 64
    pts = []
    for i in range(n_pts + 1):
        t = 2.0 * np.pi * i / n_pts
        pts.append(FreeCAD.Vector(r_mm * np.cos(t), r_mm * np.sin(t), 0.0))
    wire = Part.makePolygon(pts)
    obj = doc.addObject("Part::Feature", "Equator")
    obj.Shape = wire
    if hasattr(obj, "ViewObject"):
        obj.ViewObject.LineColor = (0.4, 0.6, 0.4)
    group.addObject(obj)


def _create_orbit_polyline(
    doc: FreeCAD.Document, group, positions_km: Sequence[Tuple[float, float, float]]
) -> None:
    if len(positions_km) == 0:
        return
    pts = [_vector_km_to_mm(p) for p in positions_km]
    # 同一点のみの場合は makePolygon が不正になるためスキップ
    if len(pts) > 1:
        first = pts[0]
        if all(p.distanceToPoint(first) < 1e-6 for p in pts[1:]):
            FreeCAD.Console.PrintWarning(
                "OrbitHeat: 軌道点が1点のため、軌道線をスキップしました。"
                "Kepler の長半径 a が正の値か確認してください。\n"
            )
            return
    # 1周で閉じる: 先頭を末尾に追加
    if len(pts) > 1:
        pts.append(pts[0])
    wire = Part.makePolygon(pts)
    obj = doc.addObject("Part::Feature", "OrbitPath")
    obj.Shape = wire
    if hasattr(obj, "ViewObject"):
        obj.ViewObject.LineColor = (0.0, 1.0, 1.0)  # シアン（軌道専用。他ワークベンチの黄線と区別）
        if hasattr(obj.ViewObject, "LineWidth"):
            obj.ViewObject.LineWidth = 2.0
    group.addObject(obj)


def _create_spacecraft_marker(
    doc: FreeCAD.Document,
    group,
    position_km,
    attitude_mode: orbit_attitude.AttitudeMode,
    sun_dir_from_earth_km=None,
) -> None:
    """軌道上の宇宙機マーカー（小さな立方体）を1つ配置。地球中心には置かない。"""
    box = doc.addObject("Part::Box", "Spacecraft")
    size_mm = 500.0
    box.Length = size_mm
    box.Width = size_mm
    box.Height = size_mm
    pos_mm = _vector_km_to_mm(position_km)
    # 地球中心付近なら軌道上の適当な位置に寄せる（中心に立方体を描かない）
    if pos_mm.Length < (EARTH_RADIUS_KM * KM_TO_MM) * 0.5:
        return
    rot = orbit_attitude.compute_attitude(
        position_km, mode=attitude_mode, sun_dir_km=sun_dir_from_earth_km
    )
    box.Placement = FreeCAD.Placement(pos_mm, rot)
    if hasattr(box, "ViewObject"):
        box.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
    group.addObject(box)


def _create_sun_vector(
    doc: FreeCAD.Document,
    group,
    sun_dir_from_earth_km: Tuple[float, float, float],
    length_km: float = 30000.0,
) -> None:
    """地球中心から太陽方向へのベクトル線を描画。"""
    direction = _vector_km_to_mm(sun_dir_from_earth_km)
    if direction.Length == 0:
        return
    direction.normalize()
    end_point = direction.multiply(length_km * KM_TO_MM)
    line = Part.makeLine(FreeCAD.Vector(0, 0, 0), end_point)
    obj = doc.addObject("Part::Feature", "SunVector")
    obj.Shape = line
    if hasattr(obj, "ViewObject"):
        obj.ViewObject.LineColor = (1.0, 0.8, 0.0)
    group.addObject(obj)


def _create_earth_shadow_cylinder(
    doc: FreeCAD.Document,
    group,
    sun_dir_from_earth_km: Tuple[float, float, float],
    length_km: float = 50000.0,
) -> None:
    """
    地球影を目視するため、地球から太陽と逆方向に伸びる半透明の円筒を描画する。
    円筒の半径は地球半径と同一（影の断面が地球の断面と一致する簡易表示）。
    """
    sun_vec = _vector_km_to_mm(sun_dir_from_earth_km)
    if sun_vec.Length < 1e-6:
        return
    shadow_dir = FreeCAD.Vector(-sun_vec.x, -sun_vec.y, -sun_vec.z)
    shadow_dir.normalize()
    radius_mm = EARTH_RADIUS_KM * KM_TO_MM
    height_mm = length_km * KM_TO_MM
    try:
        cylinder = Part.makeCylinder(radius_mm, height_mm)
        # Part.makeCylinder は Z 軸方向。影は -sun 方向なので (0,0,1) を shadow_dir に合わせる
        rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), shadow_dir)
        obj = doc.addObject("Part::Feature", "EarthShadowCylinder")
        obj.Shape = cylinder
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), rot)
        if hasattr(obj, "ViewObject"):
            obj.ViewObject.ShapeColor = (0.15, 0.15, 0.25)
            obj.ViewObject.Transparency = 75
        group.addObject(obj)
    except Exception as e:
        FreeCAD.Console.PrintWarning("OrbitHeat: 地球影円筒の作成に失敗: {}\n".format(e))


def compute_orbit_positions_km(orbit: orbit_core.OrbitInput, times: Iterable[float]):
    """
    与えられた OrbitInput / 時刻配列から衛星位置 [km] 配列を計算。
    """
    return orbit_core.compute_positions_km(orbit, times)


def create_orbit_scene(
    orbit: orbit_core.OrbitInput,
    times: Iterable[float],
    attitude_mode: orbit_attitude.AttitudeMode = "nadir",
    heat_array=None,
    orbit_display_scale: float = 1.0,
    shadow_length_km: float = 10000.0,
) -> None:
    """
    FreeCAD ドキュメント上に地球・地軸・赤道・軌道（1周）・太陽ベクトルを可視化する。
    orbit_display_scale: 実際の軌道高度の何倍で表示するか（1=実寸、2=2倍の距離で表示など）。
    shadow_length_km: 地球影（日陰）円筒の表示長 [km]。
    計算点 times に対応する表示用位置を保存し、コマ送りダイアログで使用する。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise RuntimeError("アクティブなドキュメントがありません。")

    times_arr = np.asarray(list(times), dtype=float)
    if len(times_arr) == 0:
        return

    group = _ensure_group(doc)
    _clear_group(group)

    scale = max(0.1, float(orbit_display_scale))

    # 軌道は1周分のみ、可視化用に十分な点数で
    period_s = orbit_core.get_orbit_period_seconds(orbit)
    n_div = max(72, orbit.divisions_per_period)
    times_1period = np.linspace(0.0, period_s, n_div + 1)
    positions_km = np.asarray(compute_orbit_positions_km(orbit, times_1period), dtype=float)
    if len(positions_km) == 0:
        return
    positions = positions_km * scale

    # 計算点 times に対応する表示用位置 [mm]（コマ送り用）
    positions_calc_km = np.asarray(compute_orbit_positions_km(orbit, times_arr), dtype=float)
    if len(positions_calc_km) == 0:
        positions_calc_km = positions_km[:1] * scale
    else:
        positions_calc_km = positions_calc_km * scale
    positions_display_mm = [
        _vector_km_to_mm(positions_calc_km[i]) for i in range(len(positions_calc_km))
    ]

    # 地球
    _create_earth_sphere(doc, group)

    # 地軸・北極・南極
    _create_earth_axis(doc, group)

    # 赤道
    _create_equator(doc, group)

    # 先頭フレーム（t=0）の太陽方向（影の向き・衛星・SunVector で使用）
    t0 = float(times_arr[0])
    sun_dir = orbit_core.sun_direction_from_earth(orbit, t0)
    # 地球影を目視する半透明円筒（地球から太陽と逆方向へ）
    _create_earth_shadow_cylinder(doc, group, sun_dir, length_km=shadow_length_km)

    # 軌道（1周・閉じた線）
    _create_orbit_polyline(doc, group, positions)

    # 衛星マーカーと太陽ベクトル
    pos0_km = (float(positions_calc_km[0][0]), float(positions_calc_km[0][1]), float(positions_calc_km[0][2]))
    _create_spacecraft_marker(doc, group, pos0_km, attitude_mode, sun_dir_from_earth_km=sun_dir)
    _create_sun_vector(doc, group, sun_dir)

    doc.recompute()

    # コマ送り用に状態を保存
    orbit_core.set_last_orbit_state(
        times_arr, positions_display_mm, attitude_mode, orbit, heat_array
    )

    try:
        import FreeCADGui
        FreeCADGui.SendMsgToActiveView("ViewFit")
    except Exception:
        pass


def update_scene_frame(doc: FreeCAD.Document, frame_index: int) -> None:
    """
    軌道コマ送り用。OrbitVisualization 内の Spacecraft と SunVector を
    frame_index に対応する位置・太陽方向・姿勢で更新する。
    """
    state = orbit_core.get_last_orbit_state()
    if not state:
        return
    times, positions_display_mm, attitude_mode, orbit_input, heat_array = state
    if frame_index < 0 or frame_index >= len(times):
        return
    group = doc.getObject("OrbitVisualization")
    if not group or not hasattr(group, "Group"):
        return
    t_sec = float(times[frame_index])
    sun_dir = orbit_core.sun_direction_from_earth(orbit_input, t_sec)
    pos_mm = positions_display_mm[frame_index]
    if hasattr(pos_mm, "x"):
        pos_tuple = (pos_mm.x, pos_mm.y, pos_mm.z)
    else:
        pos_tuple = (float(pos_mm[0]), float(pos_mm[1]), float(pos_mm[2]))
    # Placement は mm、姿勢計算は km（KM_TO_MM=1 なので同じ値）
    rot = orbit_attitude.compute_attitude(
        (pos_tuple[0] / KM_TO_MM, pos_tuple[1] / KM_TO_MM, pos_tuple[2] / KM_TO_MM),
        mode=attitude_mode, sun_dir_km=sun_dir
    )
    for obj in group.Group:
        if obj.Name == "Spacecraft":
            obj.Placement = FreeCAD.Placement(FreeCAD.Vector(*pos_tuple), rot)
        elif obj.Name == "SunVector":
            direction = _vector_km_to_mm(sun_dir)
            if direction.Length > 0:
                direction.normalize()
                end_pt = direction.multiply(30000.0 * 1.0)
                line = Part.makeLine(FreeCAD.Vector(0, 0, 0), end_pt)
                obj.Shape = line
    doc.recompute()

