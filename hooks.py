# -*- coding: utf-8 -*-
"""Hooks de instalación de tf_dte_cl_boleta.

Ruta real: hooks.py
"""
import logging

_logger = logging.getLogger(__name__)


def _tf_dte_cl_boleta_post_init(env):
    """Deja cada compañía lista para emitir boletas: cliente anónimo, IVA incluido y lista de precios.

    Solo crea lo que falta; una compañía sin IVA 19 % de ventas con código SII 14
    queda sin el impuesto, que se crea después desde Ajustes.
    """
    for company in env['res.company'].search([]):
        try:
            with env.cr.savepoint():
                company._tf_dte_cl_boleta_setup()
        except Exception:  # noqa: BLE001 - una compañía mal configurada no debe impedir la instalación
            _logger.warning('No se pudo preparar la compañía %s para boletas.', company.name, exc_info=True)
