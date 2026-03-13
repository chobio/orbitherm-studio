from __future__ import annotations

import sys
import os

_user_site = r"c:\users\yamaguchi\appdata\roaming\python\python311\site-packages"
if _user_site not in sys.path:
    sys.path.append(_user_site)

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

Loader = None
EarthSatellite = None
wgs84 = None
almanac = None

# FreeCAD/shiboken2 の sys.stderr は __class__ を露出せず、skyfield/iokit.py の
# sys.stderr.__class__.__name__ 参照で AttributeError になる。import 中だけラッパーに差し替える。
class _StderrWrapper:
    """sys.stderr のラッパー。__class__.__name__ を安全に返す（skyfield iokit 用）。"""
    def __init__(self, real):
        self._real = real
    def write(self, *a, **k):
        return self._real.write(*a, **k)
    def flush(self, *a, **k):
        return self._real.flush(*a, **k)
    def __getattr__(self, name):
        return getattr(self._real, name)

_real_stderr = sys.stderr
sys.stderr = _StderrWrapper(_real_stderr)
try:
    try:
        from skyfield.api import Loader, EarthSatellite
        from skyfield.api import wgs84
        from skyfield import almanac
        # Time.utc はプロパティ(CalendarTuple)。一部コードが .utc() と呼ぶと 'CalendarTuple' is not callable になるため、
        # .utc を「参照時は tuple 互換、呼び出し時は同じ tuple を返す」ラッパーに差し替える。
        try:
            from skyfield.timelib import Time
            _utc_prop = getattr(Time, "utc", None)
            if _utc_prop is not None and hasattr(_utc_prop, "fget"):
                _utc_fget = _utc_prop.fget
                class _UtcCompat(tuple):
                    __slots__ = ()
                    def __call__(self):
                        return self
                def _utc_getter(self):
                    v = _utc_fget(self)
                    if v is None:
                        return None
                    try:
                        t = tuple(v) if not isinstance(v, tuple) else v
                    except (TypeError, ValueError):
                        t = (v,) if not hasattr(v, "__iter__") else tuple(iter(v))
                    return _UtcCompat(t)
                Time.utc = property(_utc_getter)
        except Exception:
            pass
    except Exception:
        Loader = None
        EarthSatellite = None
        wgs84 = None
        almanac = None
finally:
    sys.stderr = _real_stderr

# Skyfield の BSP 等を保存する書き込み可能なディレクトリ（Loader(".") は FreeCAD 起動時に書き込み不可のことがある）
_SKYFIELD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skyfield_data")
if Loader is not None:
    try:
        os.makedirs(_SKYFIELD_DIR, exist_ok=True)
    except Exception:
        _SKYFIELD_DIR = "."

_TS = Loader(_SKYFIELD_DIR).timescale() if Loader else None

# 軌道計算と描画で得た熱入力データ（「熱入力 CSV を保存」で保存するまで保持）
_last_heat_data = None  # (times, heat_array, meta) or None


def set_last_heat_data(times, heat_array, meta) -> None:
    """最後に計算した熱入力データを保持する。"""
    global _last_heat_data
    _last_heat_data = (times, heat_array, meta)


def get_last_heat_data():
    """保持している熱入力データを返す。(times, heat_array, meta) または None。"""
    return _last_heat_data


# 軌道コマ送り用: 最後に描画した軌道の状態 (times, positions_display_mm, attitude_mode, orbit_input, heat_array)
_last_orbit_state = None


def set_last_orbit_state(times, positions_display_mm, attitude_mode, orbit_input, heat_array) -> None:
    """軌道コマ送り用に、最後に描画した軌道の状態を保持する。"""
    global _last_orbit_state
    _last_orbit_state = (times, positions_display_mm, attitude_mode, orbit_input, heat_array)


def get_last_orbit_state():
    """保持している軌道状態を返す。無い場合は None。"""
    return _last_orbit_state


@dataclass
class OrbitInput:
    satellite: Optional[EarthSatellite]
    periods: int
    divisions_per_period: int
    epoch_year: int = 2024
    epoch_month: int = 1
    epoch_day: int = 1
    kepler_elements: Optional[Dict] = None  # a_km, ecc, inc_deg, raan_deg, argp_deg, m_deg (M0)


@dataclass
class EnvironmentParams:
    solar_constant: float
    albedo: float
    earth_ir: float


def normalize_inputs(params: Dict) -> Tuple[OrbitInput, EnvironmentParams]:
    """GUI からの dict を OrbitInput / EnvironmentParams に変換する。"""
    mode = params.get("mode", "tle")
    periods = int(params.get("periods", 1))
    divisions = int(params.get("divisions_per_period", 24))
    epoch_year = int(params.get("epoch_year", 2024))
    epoch_month = int(params.get("epoch_month", 1))
    epoch_day = int(params.get("epoch_day", 1))

    if mode == "tle":
        if EarthSatellite is None or _TS is None:
            raise RuntimeError("skyfield がインポートできません。`pip install skyfield` を実行してください。")
        line1 = params.get("tle_line1", "")
        line2 = params.get("tle_line2", "")
        if not line1 or not line2:
            raise ValueError("TLE Line1/Line2 を入力してください。")
        sat = EarthSatellite(line1, line2, "ORBIT", _TS)
        orbit_input = OrbitInput(
            satellite=sat,
            periods=periods,
            divisions_per_period=divisions,
            epoch_year=epoch_year,
            epoch_month=epoch_month,
            epoch_day=epoch_day,
            kepler_elements=None,
        )
    else:
        # Kepler 要素
        a_km = float(params.get("a_km", 7000.0))
        ecc = float(params.get("ecc", 0.0))
        inc_deg = float(params.get("inc_deg", 51.6))
        raan_deg = float(params.get("raan_deg", 0.0))
        argp_deg = float(params.get("argp_deg", 0.0))
        m_deg = float(params.get("m_deg", 0.0))
        orbit_input = OrbitInput(
            satellite=None,
            periods=periods,
            divisions_per_period=divisions,
            epoch_year=epoch_year,
            epoch_month=epoch_month,
            epoch_day=epoch_day,
            kepler_elements={
                "a_km": a_km,
                "ecc": ecc,
                "inc_deg": inc_deg,
                "raan_deg": raan_deg,
                "argp_deg": argp_deg,
                "m_deg": m_deg,
            },
        )

    env = EnvironmentParams(
        solar_constant=float(params.get("solar_constant", 1358.0)),
        albedo=float(params.get("albedo", 0.3)),
        earth_ir=float(params.get("earth_ir", 237.0)),
    )
    return orbit_input, env


# 地球の重力定数 [km³/s²]。Kepler 周期・平均運動に使用。
_MU_EARTH_KM3_S2 = 398600.4418


def _orbit_period_seconds(orbit: OrbitInput) -> float:
    """軌道周期 [s] を求める。TLE の場合は no_kozai から、Kepler の場合は a から計算。"""
    if orbit.kepler_elements is not None:
        a_km = float(orbit.kepler_elements["a_km"])
        if not (np.isfinite(a_km) and a_km > 0):
            raise ValueError(
                "Kepler 要素の長半径 a (semi-major axis) は正の有限値で入力してください。"
                "現在の値: {}".format(a_km)
            )
        return float(2.0 * np.pi * np.sqrt((a_km ** 3) / _MU_EARTH_KM3_S2))
    sat = orbit.satellite
    if sat is None:
        return 5400.0
    try:
        no_kozai = sat.model.no_kozai  # rad/min
        period_minutes = (2.0 * np.pi) / no_kozai
        return float(period_minutes * 60.0)
    except Exception:
        return 5400.0


def get_orbit_period_seconds(orbit: OrbitInput) -> float:
    """軌道周期 [s] を返す（可視化などで使用）。"""
    return _orbit_period_seconds(orbit)


_EARTH_RADIUS_KM = 6371.0


def _kepler_position_km(orbit: OrbitInput, t_seconds: float) -> np.ndarray:
    """
    Kepler 要素から時刻 t_seconds（基準日 0:00 UTC からの経過秒）の位置 [km] を ECI で返す。
    戻り値は (3,) の ndarray。
    """
    k = orbit.kepler_elements
    if k is None:
        raise ValueError("kepler_elements がありません")
    a = float(k["a_km"])
    e = float(k["ecc"])
    inc = np.radians(float(k["inc_deg"]))
    raan = np.radians(float(k["raan_deg"]))
    argp = np.radians(float(k["argp_deg"]))
    m0 = np.radians(float(k["m_deg"]))
    n = np.sqrt(_MU_EARTH_KM3_S2 / (a ** 3))
    M = m0 + n * float(t_seconds)
    M = (M % (2.0 * np.pi)) - np.pi
    E = M
    for _ in range(20):
        E = E - (E - e * np.sin(E) - M) / (1.0 - e * np.cos(E))
    nu = 2.0 * np.arctan2(
        np.sqrt(1.0 + e) * np.sin(E / 2.0),
        np.sqrt(1.0 - e) * np.cos(E / 2.0),
    )
    r = a * (1.0 - e * np.cos(E))
    c_nu_om = np.cos(nu + argp)
    s_nu_om = np.sin(nu + argp)
    c_raan = np.cos(raan)
    s_raan = np.sin(raan)
    ci = np.cos(inc)
    si = np.sin(inc)
    x = r * (c_nu_om * c_raan - s_nu_om * ci * s_raan)
    y = r * (c_nu_om * s_raan + s_nu_om * ci * c_raan)
    z = r * (s_nu_om * si)
    return np.array([x, y, z], dtype=float)


def is_in_earth_shadow(orbit: OrbitInput, t_seconds: float) -> bool:
    """
    衛星が地球影（日陰）内にあるかどうかを 1 時刻で判定する。
    太陽→地球の延長上に衛星があり、かつ地球の円盤で隠れる場合に True。
    TLE の場合は Skyfield の is_sunlit() を使用。Kepler の場合は幾何判定。
    """
    if Loader is None or _TS is None:
        return False
    try:
        ts = _TS
        eph = Loader(_SKYFIELD_DIR)("de421.bsp")
        earth, sun = eph["earth"], eph["sun"]
        t = ts.utc(orbit.epoch_year, orbit.epoch_month, orbit.epoch_day, 0, 0, float(t_seconds))

        if orbit.kepler_elements is not None:
            # Kepler: 幾何判定（太陽方向・衛星位置は同一 ICRF 想定）
            sun_vec = earth.at(t).observe(sun).position.km
            # earth.observe(sun) = Earth→Sun。影はその反対側 = Sun→Earth 方向
            sun_to_earth = -np.squeeze(np.asarray(sun_vec))
            sat_pos = _kepler_position_km(orbit, float(t_seconds))
            n_se = np.linalg.norm(sun_to_earth) + 1e-30
            proj = np.dot(sat_pos, sun_to_earth) / n_se
            perp = sat_pos - (sun_to_earth / n_se) * proj
            # 影 = 衛星が地球の太陽と反対側にあり、円盤内 (proj > 0)
            return bool(proj > 0 and np.linalg.norm(perp) < _EARTH_RADIUS_KM)
        else:
            # TLE: Skyfield の is_sunlit を使用（確実な判定）
            return not orbit.satellite.at(t).is_sunlit(eph)
    except Exception:
        return False


def build_time_grid(orbit: OrbitInput) -> np.ndarray:
    """1 周期あたり divisions_per_period 分割の基本時刻配列 [s] を periods 分だけ生成。"""
    period_s = _orbit_period_seconds(orbit)
    base_div = orbit.divisions_per_period
    dt = period_s / base_div
    n_total = base_div * orbit.periods + 1
    times = np.linspace(0.0, period_s * orbit.periods, n_total)
    # 安全のため丸め
    return times.astype(float)


def refine_with_eclipse_events(orbit: OrbitInput, times: np.ndarray) -> np.ndarray:
    """地球影への出入り時刻を times にマージしてソート。_almanac_function に依存しないスキャン方式。"""
    if Loader is None or _TS is None:
        return times
    t_min = float(np.min(times))
    t_max = float(np.max(times))
    if t_max <= t_min:
        return times
    # 細かくスキャンして陰→陽・陽→陰の境界を検出（ステップは最大 30 秒程度）
    step = min(30.0, (t_max - t_min) / 200.0)
    step = max(step, 0.5)
    scan_times = np.arange(t_min, t_max + step * 0.5, step)
    prev_shadow = None
    boundary_seconds = []
    for t_sec in scan_times:
        in_shadow = is_in_earth_shadow(orbit, float(t_sec))
        if prev_shadow is not None and in_shadow != prev_shadow:
            # 境界を二分法で粗く補間（オプション: 精度を上げるなら反復）
            t_lo, t_hi = (t_sec - step, t_sec) if in_shadow else (t_sec, t_sec + step)
            for _ in range(8):
                t_mid = (t_lo + t_hi) * 0.5
                if is_in_earth_shadow(orbit, t_mid) == in_shadow:
                    t_lo = t_mid
                else:
                    t_hi = t_mid
            boundary_seconds.append((t_lo + t_hi) * 0.5)
        prev_shadow = in_shadow
    if not boundary_seconds:
        return times
    all_times = np.unique(np.concatenate([np.asarray(times, dtype=float), np.array(boundary_seconds)]))
    all_times.sort()
    return all_times


def compute_heat_array(
    orbit: OrbitInput, env: EnvironmentParams, times: np.ndarray
) -> Tuple[np.ndarray, Dict]:
    """各時刻での簡易熱入力 [W/m2] を計算して 2D 配列として返す。日陰は is_in_earth_shadow で判定。"""
    times_arr = np.asarray(times, dtype=float)
    q_solar = np.full_like(times_arr, env.solar_constant, dtype=float)
    q_albedo = np.full_like(times_arr, env.solar_constant * env.albedo * 0.3, dtype=float)
    q_ir = np.full_like(times_arr, env.earth_ir, dtype=float)

    for i, t_sec in enumerate(times_arr):
        if is_in_earth_shadow(orbit, float(t_sec)):
            q_solar[i] = 0.0
            q_albedo[i] *= 0.5

    heat_array = np.vstack([q_solar, q_albedo, q_ir]).T
    meta = {
        "columns": ["q_solar", "q_albedo", "q_earth_ir"],
    }
    return heat_array, meta


def export_heat_array_csv(
    filepath: str, times: Iterable[float], heat_array: np.ndarray, meta: Dict
) -> None:
    """HEAT ARRAY を CSV 形式で出力する。"""
    cols = meta.get("columns", [])
    header = ["index", "t_sec"] + cols
    lines = []
    times = np.asarray(times, dtype=float)
    for idx, (t, row) in enumerate(zip(times, heat_array)):
        fields = [str(idx), f"{t:.6f}"] + [f"{float(v):.6f}" for v in row]
        lines.append(",".join(fields))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        f.write("\n".join(lines))


def compute_positions_km(orbit: OrbitInput, times: Sequence[float]) -> np.ndarray:
    """
    各時刻における衛星位置ベクトル [km] を返す。

    戻り値の形状は (N, 3) で、地球中心慣性座標系を仮定する。
    """
    times_list = list(times)
    if orbit.kepler_elements is not None:
        out = np.array([_kepler_position_km(orbit, float(t)) for t in times_list], dtype=float)
        return out
    if EarthSatellite is None or _TS is None:
        raise RuntimeError("skyfield がインポートできません。`pip install skyfield` を実行してください。")
    sat = orbit.satellite
    ts = _TS
    y, m, d = orbit.epoch_year, orbit.epoch_month, orbit.epoch_day
    try:
        t_list = ts.utc(y, m, d, 0, 0, times_list)
        sat_at_t = sat.at(t_list)
        sat_vec = sat_at_t.position.km  # shape (3, N)
        return sat_vec.T  # (N, 3)
    except (TypeError, AttributeError) as e:
        if "CalendarTuple" in str(e) or "not callable" in str(e):
            out = []
            for t_sec in times_list:
                ti = ts.utc(y, m, d, 0, 0, float(t_sec))
                pos = sat.at(ti).position.km
                out.append(np.squeeze(np.asarray(pos)))
            return np.array(out)
        raise


def sun_direction_from_earth(orbit: OrbitInput, t_seconds: float) -> Tuple[float, float, float]:
    """
    地球中心から太陽への方向ベクトル [km] を返す（大きさは任意）。

    t_seconds は orbit の基準日 (epoch_year/month/day) 0:00:00 UTC からの経過秒数。
    """
    if Loader is None or _TS is None:
        # 方角が取れない場合は、X 方向を仮の太陽方向とする。
        return (1.0, 0.0, 0.0)
    ts = _TS
    eph = Loader(_SKYFIELD_DIR)("de421.bsp")
    earth, sun = eph["earth"], eph["sun"]
    t = ts.utc(orbit.epoch_year, orbit.epoch_month, orbit.epoch_day, 0, 0, float(t_seconds))
    sun_vec = earth.at(t).observe(sun).position.km
    # 方向だけ使いたいので、正規化に近い形でそのまま返す
    return (float(sun_vec[0]), float(sun_vec[1]), float(sun_vec[2]))

