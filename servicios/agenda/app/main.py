"""Servicio de agenda y citas (persona A).

RF5 y RF6 (horarios y bloqueos), RF7 y RF8 (disponibilidad), RF9 a RF13 (reservar, reprogramar, cancelar,
desenlace y estados) y RF20 (agenda del día). Es el único servicio que escribe en cita.
"""

from medicitas_comun import crear_app

from . import bloqueos, citas, disponibilidad, horarios

app = crear_app("agenda")

# Un router por grupo de requisitos; cada uno vive en su archivo.
app.include_router(horarios.router)
app.include_router(bloqueos.router)
app.include_router(disponibilidad.router)
app.include_router(citas.router)
# Siguientes: reprogramar, cancelar y desenlace (RF10 a RF13), agenda del día (RF20).
