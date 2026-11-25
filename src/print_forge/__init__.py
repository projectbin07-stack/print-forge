"""print-forge: parametric generators for small FDM batch products.

Every generator builds its solid so that it is closed and consistently wound by construction
(no mesh booleans), then validates it for printing on the beds in the shared printer registry
(Bambu Lab P1S, P1P, X1 Carbon, A1 and A1 mini).
"""

__version__ = "0.2.0"
