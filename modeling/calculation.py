from typing import Optional

import numpy as np


def calc_thermal_capacity(
    area_m2: float,
    thickness_m: float,
    density_kg_per_m3: float,
    specific_heat_j_per_kg_k: float,
) -> float:
    """
    面積[m2]・厚み[m]・密度[kg/m3]・比熱[J/kgK] から熱容量[J/K]を計算する。
    """
    return area_m2 * thickness_m * density_kg_per_m3 * specific_heat_j_per_kg_k


def calc_conductance(
    thermal_conductivity_w_per_m_k: float,
    thickness_m: float,
    shared_length_m: float,
    distance_m: float,
) -> Optional[float]:
    """
    熱伝導率[W/mK]・代表厚み[m]・共有稜線長さ[m]・ノード間距離[m]から
    伝熱コンダクタンス[W/K]を計算する。

    distance_m が 0 以下の場合は None を返して、呼び出し側で無視できるようにする。
    """
    if distance_m <= 0.0:
        return None

    contact_area_m2 = shared_length_m * thickness_m
    return thermal_conductivity_w_per_m_k * contact_area_m2 / distance_m


def calc_radiation_factor(
    emissivity: float,
    view_factor: float,
    area_m2: float,
) -> float:
    """
    輻射コンダクタンスの係数（ステファン・ボルツマン定数 σ を除いた部分）を計算する。
    R' = ε × Vf × A [m²]
    熱流 Q = σ × R' × (T_i^4 - T_j^4) のときの R' に相当する。
    """
    return emissivity * view_factor * area_m2


def calculate_radiative_conductance(
    F: np.ndarray,
    A: np.ndarray,
    eps: np.ndarray,
    tau: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    生の形態係数から、多重反射を考慮した灰色体の輻射コンダクタンス行列を算出する（ゲプハルト法）。

    モンテカルロなどで得られた形態係数 F_ij は数値誤差を含むため相反定理が厳密には成り立たず、
    また灰色体（ε < 1）では多重反射を考慮する必要がある。本関数はこれらを扱い、
    対称化された輻射コンダクタンス行列 R を返す。

    熱流は Q_ij = σ * R_ij * (T_i^4 - T_j^4) の形で用いることを想定（σ はステファン・ボルツマン定数）。

    Parameters
    ----------
    F : np.ndarray, shape (N, N)
        生の形態係数行列。F[i,j] はノード i から j への形態係数。
    A : np.ndarray, shape (N,)
        各ノードの面積 [m²] ベクトル。
    eps : np.ndarray, shape (N,)
        各ノードの赤外放射率（0 < eps <= 1）ベクトル。
    tau : np.ndarray, shape (N,), optional
        各ノードの透過率（0 <= τ <= 1）。省略時は 0（不透明）として ρ = 1 - ε。

    Returns
    -------
    R : np.ndarray, shape (N, N)
        対称な輻射コンダクタンス行列。対角成分は 0。単位は [m²]（σ をかけると [W/K] 相当）。
    """
    F = np.asarray(F, dtype=float)
    A = np.asarray(A, dtype=float)
    eps = np.asarray(eps, dtype=float)
    N = F.shape[0]
    if A.shape != (N,) or eps.shape != (N,):
        raise ValueError("A, eps の形状は (N,) である必要があります。")

    if tau is not None:
        tau = np.asarray(tau, dtype=float)
        if tau.shape != (N,):
            raise ValueError("tau の形状は (N,) である必要があります。")
    else:
        tau = np.zeros(N)

    # 1. 反射率 ρ = max(0, 1 - ε - τ)。透過率 0 のときは従来通り ρ = 1 - ε
    rho = np.maximum(0.0, 1.0 - eps - tau)
    R_ref = np.diag(rho)

    # 2. 放射率の対角行列 E
    E = np.diag(eps)

    # 3. ゲプハルト行列 G = (I - F @ R_ref)^{-1} @ F @ E
    I = np.eye(N)
    # (I - F @ R_ref) @ G = F @ E を解く（逆行列より安定）
    G = np.linalg.solve(I - F @ R_ref, F @ E)

    # 4. 非対称コンダクタンス C_ij = A_i * ε_i * G_ij  =>  C = A_diag @ E @ G
    A_diag = np.diag(A)
    C = A_diag @ E @ G

    # 5. 対称化（相反定理の強制・誤差吸収）と対角を 0 に
    R = (C + C.T) / 2.0
    np.fill_diagonal(R, 0.0)

    return R


# ----- テスト用サンプル（N=3） -----
if __name__ == "__main__":
    N = 3
    # ダミーの形態係数行列（行和が1に近い例）
    F = np.array([
        [0.0, 0.5, 0.5],
        [0.4, 0.0, 0.6],
        [0.4, 0.6, 0.0],
    ], dtype=float)
    A = np.array([1.0, 1.2, 0.8])  # m²
    eps = np.array([0.9, 0.85, 0.88])

    R = calculate_radiative_conductance(F, A, eps)
    print("F (形態係数):")
    print(F)
    print("\nA:", A)
    print("eps:", eps)
    print("\nR (輻射コンダクタンス行列, 対称・対角0):")
    print(R)
    print("\nR の対称性 (R - R.T の最大要素):", np.abs(R - R.T).max())
    print("R の対角:", np.diag(R))

