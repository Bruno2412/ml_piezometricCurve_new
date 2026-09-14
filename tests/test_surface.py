# -*- coding: utf-8 -*-
"""
Tests unitaires pour les fonctions de surface/rendu géospatial de
piezo_core.py : build_piezo_surface (interpolation), surface_to_png_overlay
et draw_nappe_2d_figure (rendu matplotlib pour la carte Theis / le Digital
Twin).

Portée volontairement pragmatique pour le rendu graphique : on ne compare
pas d'images pixel à pixel (fragile, coûteux), on vérifie que les fonctions
s'exécutent sans erreur, renvoient des objets du bon type/de la bonne forme,
et respectent quelques invariants numériques (bornes, formes de tableaux).

Lancer avec :
    pytest tests/test_surface.py -v
"""

import matplotlib
matplotlib.use("Agg")  # backend non interactif : indispensable en CI/headless

import matplotlib.pyplot as plt
import numpy as np
import pytest

import piezo_core as core


# ─────────────────────────────────────────────────────────────────────────
# build_piezo_surface
# ─────────────────────────────────────────────────────────────────────────

def _three_point_coords():
    return [
        {"lon": 4.80, "lat": 45.70},
        {"lon": 4.90, "lat": 45.75},
        {"lon": 4.85, "lat": 45.80},
    ]


class TestBuildPiezoSurface:
    def test_returns_grids_of_requested_size(self):
        coords = _three_point_coords()
        values = [100.0, 102.0, 101.0]
        GLon, GLat, GZ = core.build_piezo_surface(coords, values, n=50)
        assert GLon.shape == (50, 50)
        assert GLat.shape == (50, 50)
        assert GZ.shape == (50, 50)

    def test_grid_covers_points_with_margin(self):
        coords = _three_point_coords()
        values = [100.0, 102.0, 101.0]
        GLon, GLat, _ = core.build_piezo_surface(coords, values, n=30, margin_ratio=0.3)
        lons = [c["lon"] for c in coords]
        lats = [c["lat"] for c in coords]
        # La grille doit déborder au-delà du bounding box des points sources.
        assert GLon.min() < min(lons)
        assert GLon.max() > max(lons)
        assert GLat.min() < min(lats)
        assert GLat.max() > max(lats)

    def test_interpolated_value_at_centroid_is_within_source_value_range(self):
        # Avec seulement 3 points sources, griddata(method='linear')
        # renvoie NaN en dehors du triangle qu'ils forment (convex hull) :
        # un point proche d'un sommet mais légèrement à l'extérieur du
        # triangle serait donc NaN, ce qui n'est pas un bug. On vérifie
        # plutôt un point sûrement à l'intérieur du triangle : son centroïde.
        coords = _three_point_coords()
        values = [100.0, 200.0, 300.0]
        GLon, GLat, GZ = core.build_piezo_surface(coords, values, n=200, margin_ratio=0.05)
        centroid_lon = sum(c["lon"] for c in coords) / 3
        centroid_lat = sum(c["lat"] for c in coords) / 3
        dist = (GLon - centroid_lon) ** 2 + (GLat - centroid_lat) ** 2
        iy, ix = np.unravel_index(np.argmin(dist), dist.shape)
        assert not np.isnan(GZ[iy, ix])
        assert min(values) <= GZ[iy, ix] <= max(values)

    def test_points_outside_the_source_triangle_are_nan(self):
        # Documente le comportement réel (attendu) de griddata en mode
        # 'linear' : hors du triangle formé par les 3 points sources,
        # la valeur interpolée est NaN (pas d'extrapolation). Les coins
        # de la grille (ajoutés par margin_ratio) tombent typiquement
        # dans ce cas — l'app affichera donc des zones vides à ces coins.
        coords = _three_point_coords()
        values = [100.0, 200.0, 300.0]
        GLon, GLat, GZ = core.build_piezo_surface(coords, values, n=50, margin_ratio=0.3)
        assert np.isnan(GZ[0, 0])  # coin de la grille, hors du triangle source

    def test_handles_collinear_source_points_via_nearest_fallback(self):
        # Points sources colinéaires (même longitude) : la triangulation
        # Delaunay requise par method='linear' est impossible (QhullError).
        # build_piezo_surface() doit se replier sur method='nearest'
        # plutôt que de planter.
        coords = [
            {"lon": 4.80, "lat": 45.70},
            {"lon": 4.80, "lat": 45.75},
            {"lon": 4.80, "lat": 45.80},
        ]
        values = [100.0, 101.0, 102.0]
        GLon, GLat, GZ = core.build_piezo_surface(coords, values, n=20)
        assert GLon.shape == (20, 20)
        assert np.isfinite(GLon).all()
        assert not np.isnan(GZ).any()  # 'nearest' ne produit jamais de NaN
        assert set(np.unique(GZ)) <= set(values)

    def test_more_than_three_points_is_accepted(self):
        coords = _three_point_coords() + [{"lon": 4.95, "lat": 45.72}]
        values = [100.0, 102.0, 101.0, 103.0]
        GLon, GLat, GZ = core.build_piezo_surface(coords, values, n=25)
        assert GLon.shape == (25, 25)


# ─────────────────────────────────────────────────────────────────────────
# surface_to_png_overlay
# ─────────────────────────────────────────────────────────────────────────

class TestSurfaceToPngOverlay:
    def _make_grid(self, n=20):
        coords = _three_point_coords()
        values = [100.0, 102.0, 101.0]
        return core.build_piezo_surface(coords, values, n=n)

    def test_returns_png_bytes_and_bounds(self):
        GLon, GLat, GZ = self._make_grid()
        png_bytes, bounds = core.surface_to_png_overlay(GLon, GLat, GZ)
        assert isinstance(png_bytes, bytes)
        assert png_bytes.startswith(b"\x89PNG")
        assert len(png_bytes) > 0

    def test_bounds_match_grid_extent(self):
        GLon, GLat, GZ = self._make_grid()
        _, bounds = core.surface_to_png_overlay(GLon, GLat, GZ)
        (lat_min, lon_min), (lat_max, lon_max) = bounds
        assert lat_min == pytest.approx(GLat.min())
        assert lat_max == pytest.approx(GLat.max())
        assert lon_min == pytest.approx(GLon.min())
        assert lon_max == pytest.approx(GLon.max())

    def test_accepts_custom_cmap_and_alpha(self):
        GLon, GLat, GZ = self._make_grid()
        png_bytes, _ = core.surface_to_png_overlay(GLon, GLat, GZ, cmap="viridis", alpha=0.3)
        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 0

    def test_does_not_leak_open_figures(self):
        GLon, GLat, GZ = self._make_grid()
        n_before = len(plt.get_fignums())
        core.surface_to_png_overlay(GLon, GLat, GZ)
        # La fonction doit fermer sa propre figure (plt.close(fig)).
        assert len(plt.get_fignums()) == n_before


# ─────────────────────────────────────────────────────────────────────────
# draw_nappe_2d_figure
# ─────────────────────────────────────────────────────────────────────────

class TestDrawNappe2dFigure:
    def _default_kwargs(self, **overrides):
        kwargs = dict(
            Q=100.0, S=0.05, K=1e-4, thickness=10.0,
            distance=150.0, time_days=180.0, Area=1000.0, niveau_base=100.0,
        )
        kwargs.update(overrides)
        return kwargs

    def test_returns_a_matplotlib_figure(self):
        fig = core.draw_nappe_2d_figure(**self._default_kwargs())
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_axes_limits_scale_with_distance(self):
        fig_close = core.draw_nappe_2d_figure(**self._default_kwargs(distance=10.0))
        size_close = fig_close.axes[0].get_xlim()[1]
        plt.close(fig_close)

        fig_far = core.draw_nappe_2d_figure(**self._default_kwargs(distance=1000.0))
        size_far = fig_far.axes[0].get_xlim()[1]
        plt.close(fig_far)

        assert size_far > size_close

    def test_handles_zero_injection_without_error(self):
        # Q=0 : la branche de calcul de l'impact est court-circuitée
        # (if T > 0 and S > 0 and time_days > 0 and Q > 0), doit quand
        # même produire une figure valide (niveau plat = niveau_base).
        fig = core.draw_nappe_2d_figure(**self._default_kwargs(Q=0.0))
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_handles_zero_time_days_without_error(self):
        fig = core.draw_nappe_2d_figure(**self._default_kwargs(time_days=0.0))
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_does_not_leak_open_figures_beyond_the_one_returned(self):
        n_before = len(plt.get_fignums())
        fig = core.draw_nappe_2d_figure(**self._default_kwargs())
        assert len(plt.get_fignums()) == n_before + 1
        plt.close(fig)
        assert len(plt.get_fignums()) == n_before

    def test_title_contains_expected_parameters(self):
        fig = core.draw_nappe_2d_figure(**self._default_kwargs(Q=42.0, time_days=90.0))
        title = fig.axes[0].get_title()
        assert "t=90" in title
        assert "Q=42.0" in title
        plt.close(fig)
