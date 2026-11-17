# -*- coding: utf-8 -*-
"""Referencias de una nota de crédito a una boleta.

Ruta real: models/reference.py

* Una nota de crédito puede anular (CodRef 1) una boleta 39 o 41.
* facturacion_electronica 0.24.0 reconoce una nota sobre boleta
  (``Documento.es_nc_boleta``) comparando el primer TpoDocRef con números: con
  el código como texto ('39') no la reconoce y exige comuna y giro del receptor,
  que un consumidor anónimo no tiene. Por eso TpoDocRef se envía como número.
"""
from odoo import api, models

from .boleta_lines import BOLETA_TYPES


class TfDteClReference(models.Model):
    _inherit = 'tf_dte_cl.reference'

    @api.model
    def _tf_dte_cl_cancellable_types(self):
        return tuple(super()._tf_dte_cl_cancellable_types()) + BOLETA_TYPES

    def _tf_dte_cl_payload(self, dte_type):
        payload = super()._tf_dte_cl_payload(dte_type)
        for item in payload:
            if str(item.get('TpoDocRef')) in BOLETA_TYPES:
                item['TpoDocRef'] = int(item['TpoDocRef'])
        return payload
