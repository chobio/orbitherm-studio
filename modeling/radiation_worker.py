# radiation_worker.py
# FreeCAD に依存しない輻射ビューファクター用ワーカー（multiprocessing 用）。
# 子プロセスで FreeCAD を読み込まないため、このモジュールのみ import する。

import math
import random


def ray_triangle_intersect(origin, direction, v0, v1, v2):
    """
    Möller–Trumbore: レイと三角形の交差。
    origin/direction, v0,v1,v2 は (x,y,z) または長さ3のシーケンス。戻り値は t (>0) または None。
    """
    eps = 1e-9
    o = (float(origin[0]), float(origin[1]), float(origin[2]))
    d = (float(direction[0]), float(direction[1]), float(direction[2]))
    p0 = (float(v0[0]), float(v0[1]), float(v0[2]))
    p1 = (float(v1[0]), float(v1[1]), float(v1[2]))
    p2 = (float(v2[0]), float(v2[1]), float(v2[2]))
    e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    h = (
        d[1] * e2[2] - d[2] * e2[1],
        d[2] * e2[0] - d[0] * e2[2],
        d[0] * e2[1] - d[1] * e2[0],
    )
    a = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
    if -eps < a < eps:
        return None
    f = 1.0 / a
    s = (o[0] - p0[0], o[1] - p0[1], o[2] - p0[2])
    u = f * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
    if u < 0 or u > 1:
        return None
    q = (
        s[1] * e1[2] - s[2] * e1[1],
        s[2] * e1[0] - s[0] * e1[2],
        s[0] * e1[1] - s[1] * e1[0],
    )
    v = f * (d[0] * q[0] + d[1] * q[1] + d[2] * q[2])
    if v < 0 or u + v > 1:
        return None
    t = f * (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2])
    return t if t > eps else None


def random_hemisphere_direction(normal):
    """法線方向を上とした半球上でコサイン重み付きランダム方向を返す。(dx,dy,dz) 単位ベクトル。"""
    nx = float(normal[0])
    ny = float(normal[1])
    nz = float(normal[2])
    u = random.random()
    v = random.random()
    theta = math.acos(math.sqrt(u))
    phi = 2.0 * math.pi * v
    dx = math.sin(theta) * math.cos(phi)
    dy = math.sin(theta) * math.sin(phi)
    dz = math.cos(theta)
    if abs(nz) < 0.999:
        ax, ay, az = -ny, nx, 0.0
    else:
        ax, ay, az = 0.0, -nz, ny
    alen = math.sqrt(ax * ax + ay * ay + az * az)
    if alen < 1e-18:
        return (dx, dy, dz)
    ax, ay, az = ax / alen, ay / alen, az / alen
    bx = ay * nz - az * ny
    by = az * nx - ax * nz
    bz = ax * ny - ay * nx
    wx = ax * dx + bx * dy + nx * dz
    wy = ay * dx + by * dy + ny * dz
    wz = az * dx + bz * dy + nz * dz
    wlen = math.sqrt(wx * wx + wy * wy + wz * wz)
    if wlen < 1e-18:
        return (nx, ny, nz)
    return (wx / wlen, wy / wlen, wz / wlen)


def worker_view_factor_one_patch(patches_serialized, patch_index, rays_per_patch, seed):
    """
    1パッチ分のモンテカルロビューファクターを計算する（multiprocessing ワーカー用）。
    patches_serialized: list of dict, 各要素は "center", "normal", "triangles" を持つ。
      center, normal は長さ3のシーケンス。triangles は (N, 3, 3) の配列（NumPy または list）。
    戻り値: list of int, 長さ len(patches_serialized)。hits[j] = パッチ patch_index から発射したレイがパッチ j に当たった回数。
    """
    random.seed(seed)
    n = len(patches_serialized)
    hits = [0] * n
    pi = patches_serialized[patch_index]
    center = pi["center"]
    normal = pi["normal"]
    eps_origin = 0.01
    for _ in range(rays_per_patch):
        direction = random_hemisphere_direction(normal)
        origin_off = (
            center[0] + normal[0] * eps_origin,
            center[1] + normal[1] * eps_origin,
            center[2] + normal[2] * eps_origin,
        )
        t_min = None
        j_hit = None
        for j in range(n):
            if j == patch_index:
                continue
            tri_arr = patches_serialized[j]["triangles"]
            for idx in range(len(tri_arr)):
                tri = tri_arr[idx]
                v0, v1, v2 = tri[0], tri[1], tri[2]
                t = ray_triangle_intersect(origin_off, direction, v0, v1, v2)
                if t is not None and (t_min is None or t < t_min):
                    t_min = t
                    j_hit = j
        if j_hit is not None:
            hits[j_hit] += 1
    return hits
