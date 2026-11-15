from fastapi import Depends, HTTPException
from medicitas_comun import Sesion, sesion_de_clinica


def admin_de_clinica(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol != "ADM_CLINICA":
        raise HTTPException(403, "Solo el administrador de clÃ­nica accede a la bitÃ¡cora y a los reportes")
    return sesion
