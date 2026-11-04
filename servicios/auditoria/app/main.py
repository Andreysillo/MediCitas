"""Servicio de auditoría y reportes.

RF19 (consulta de la bitácora, solo para el administrador de la clínica) y RF21 (citas por estado en un rango).
Solo lee: la bitácora la escriben los otros servicios en sus propias transacciones (RF18).
"""

from medicitas_comun import crear_app

app = crear_app("auditoria")

# Cada grupo de requisitos va en su propio router dentro de app/, y se registra aquí:
# app.include_router(bitacora.router)
