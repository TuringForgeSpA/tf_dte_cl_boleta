# -*- coding: utf-8 -*-
"""Amplía el cliente SII del núcleo a las boletas (39/41).

Ruta real: models/sii_client.py

La integración con facturacion_electronica sigue en tf_dte_cl
(models/sii_client.py); aquí solo se habilitan los tipos y se arma el
Reporte de Consumo de Folios (RCOF), que el SII ya no pide en producción
(Res. Ex. N° 53 de 2022) pero sí en la certificación de boletas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.tf_dte_cl.models import sii_client as core

_logger = logging.getLogger(__name__)

BOLETA_DTE_TYPES = frozenset({39, 41})

try:  # la librería es la del núcleo (external_dependencies de tf_dte_cl)
    from facturacion_electronica.envio import Envio as _FeEnvio
except ImportError:  # pragma: no cover
    _FeEnvio = None


@dataclass
class ConsumptionResult:
    ok: bool
    xml: str = ''
    filename: str = ''
    message: str = ''


class TfDteClSiiClient(models.AbstractModel):
    _inherit = 'tf_dte_cl.sii.client'

    @api.model
    def _tf_dte_cl_supported_dte_types(self):
        return super()._tf_dte_cl_supported_dte_types() | BOLETA_DTE_TYPES

    @api.model
    def tf_dte_cl_build_consumption(self, payload: dict) -> ConsumptionResult:
        """Arma y firma un RCOF (ConsumoFolio_v10) sin transmitirlo.

        ``payload``: ``Emisor``, ``firma_electronica``, ``FchInicio``, ``FchFinal``,
        ``SecEnvio`` y ``Documento`` = ``[{'TipoDTE': 39, 'documentos': [{'Folio',
        'Fecha', 'TasaImp', 'MntNeto', 'MntIVA', 'MntExe', 'MntTotal'}]}]``.
        """
        self._tf_dte_cl_check_library()
        if _FeEnvio is None:
            raise UserError(self.env._('La librería facturacion_electronica no está disponible.'))
        payload = core.clean_payload(payload)
        self._tf_dte_cl_check_payload(payload)
        for group in payload.get('Documento') or []:
            if group.get('TipoDTE') not in BOLETA_DTE_TYPES:
                raise UserError(self.env._('El consumo de folios solo informa boletas (39 y 41).'))
        vals = {
            'Emisor': payload['Emisor'],
            'firma_electronica': payload['firma_electronica'],
            'test': True,  # solo se arma y firma; el archivo se sube en el sitio del SII
            'ConsumoFolios': [{
                'FchInicio': payload['FchInicio'],
                'FchFinal': payload['FchFinal'],
                'SecEnvio': payload.get('SecEnvio') or 1,
                'Documento': payload['Documento'],
            }],
        }
        try:
            results = _FeEnvio(vals).do_consumo_folios_send()
        except Exception as error:  # noqa: BLE001
            _logger.exception('facturacion_electronica: falló el consumo de folios')
            return ConsumptionResult(ok=False, message=core.short_message(error))
        result = results[0] if results else {}
        if not result.get('sii_xml_request'):
            return ConsumptionResult(ok=False, message=self.env._('La librería no generó el consumo de folios.'))
        return ConsumptionResult(ok=True, xml=result['sii_xml_request'],
                                 filename=result.get('sii_send_filename') or 'CF.xml')
