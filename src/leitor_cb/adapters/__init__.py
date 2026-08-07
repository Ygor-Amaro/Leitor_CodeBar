"""Adaptadores de entrada e saída — CLI e interface gráfica de recorte.

É a única camada que conhece `argparse` e OpenCV GUI.
"""

from .seletor_roi import SeletorRoiOpenCv

__all__ = ["SeletorRoiOpenCv"]
