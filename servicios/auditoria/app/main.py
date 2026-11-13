"""Servicio de auditoría y reportes.

RF19 (consulta de la bitácora, solo para el administrador de la clínica) y RF21 (citas por estado en un rango).
Solo lee: la bitácora la escriben los otros servicios en sus propias transacciones (RF18).
"""

from medicitas_comun import crear_app

from . import bitacora, reportes

app = crear_app("auditoria")

app.include_router(bitacora.router)   # RF19  GET /bitacora
app.include_router(reportes.router)   # RF21  GET /reportes/citas-por-estado
