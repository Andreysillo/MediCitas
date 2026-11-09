"""Servicio de plataforma y administración (persona B).

RF1 (alta de clínicas), RF2 a RF4 (usuarios, catálogo de servicios y profesionales), RF14 (pacientes),
RF15 (notas clínicas) y RF16 (historial del paciente). Escribe en la bitácora, dentro de la misma transacción,
cada lectura o escritura de notas y datos de contacto (RF18).
"""

from medicitas_comun import crear_app

from . import alta

app = crear_app("plataforma")

# Cada grupo de requisitos va en su propio router dentro de app/, y se registra aquí:
app.include_router(alta.router)
