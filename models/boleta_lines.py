# -*- coding: utf-8 -*-
"""Reglas de montos y receptor de las boletas (sin dependencias de Odoo).

Ruta real: models/boleta_lines.py

Fuente: SII, "Formato boletas electrónicas de ventas y servicios" v4.2
(2025-09-08), y EnvioBOLETA_v11.xsd.

* Sin IndMntNeto, el detalle (PrcItem, DescuentoMonto, MontoItem) es bruto, con IVA.
* MntNeto: suma de los ítems afectos dividida por (1 + tasa IVA). IVA: tasa
  aplicada al neto. MntTotal = MntNeto + IVA + MntExe. Se calcula el neto
  redondeado y el IVA como diferencia, para que el total sea exactamente la
  suma de los montos de línea.
* RUTRecep: 66666666-6 para boletas de ventas y servicios sin cliente
  identificado.
* Ley 21.713: sobre 135 UF son obligatorios RUTRecep, RznSocRecep y MedioPago.
  facturacion_electronica 0.24.0 no transmite MedioPago, por lo que esas boletas
  se bloquean.
"""
from __future__ import annotations

from decimal import Decimal

from odoo.addons.tf_dte_cl.models.dte_lines import LineInfo, iva_rate, round_half_up

BOLETA_TYPES = ('39', '41')
AFFECTED_BOLETA = '39'
EXEMPT_BOLETA = '41'
CREDIT_NOTE_TYPE = '61'
GENERIC_RUT = '66666666-6'
ANONYMOUS_NAME = 'Consumidor final'
# IndServicio 3: boleta de ventas y servicios (no periódicos ni domiciliarios).
IND_SERVICIO_SALES = 3
DEFAULT_IVA_RATE = 19.0

# Ley 21.713: umbral en UF desde el que la boleta exige receptor y medio de pago.
UF_LIMIT = 135
# Criterio tf_dte_cl: valor de UF bajo el cual se asume que una boleta no puede
# superar el umbral, para no exigir la UF registrada en ventas pequeñas.
# Con 30.000 pesos por UF, el control empieza en boletas de 4.050.000 pesos.
UF_FLOOR = 30000


def gross_totals(lines: list[LineInfo]) -> dict:
    """Totales de un documento con montos brutos (``subtotal`` de cada línea con IVA)."""
    affected = sum(round_half_up(line.subtotal) for line in lines if line.iva)
    exempt = sum(round_half_up(line.subtotal) for line in lines if line.is_exempt)
    rate = iva_rate(lines) or DEFAULT_IVA_RATE
    net = round_half_up(Decimal(affected) / (1 + Decimal(str(rate)) / 100)) if affected else 0
    return {
        'net': net,
        'iva': affected - net,
        'exempt': exempt,
        'total': affected + exempt,
        'rate': rate,
    }


def gross_line_errors(doc_type: str, lines: list[LineInfo], has_adjustments: bool = False) -> list[str]:
    """Errores propios de un documento con montos brutos (boleta o nota sobre boleta)."""
    errors = []
    for line in lines:
        prefix = 'línea "%s": ' % line.label
        if any(not tax.price_include for tax in line.iva):
            errors.append(prefix + 'en boletas el IVA debe estar incluido en el precio '
                                   '(use el impuesto de IVA incluido configurado para boletas)')
        if line.additional:
            errors.append(prefix + 'las boletas no admiten impuestos adicionales (ILA y similares)')
        if doc_type == EXEMPT_BOLETA and line.taxes:
            errors.append(prefix + 'una boleta exenta (41) no lleva impuestos')
    if doc_type == AFFECTED_BOLETA and lines and not any(line.iva for line in lines):
        errors.append('una boleta electrónica (39) debe tener al menos una línea con IVA; '
                      'si todo es exento, use una boleta exenta (41)')
    if has_adjustments:
        errors.append('las boletas no admiten descuentos o recargos globales; aplique el descuento en cada línea')
    return errors


def exceeds_uf_limit(total: int, uf_value: float | None) -> bool | None:
    """Si el total supera 135 UF. ``None`` si hace falta el valor de la UF para decidirlo."""
    if total <= UF_LIMIT * UF_FLOOR:
        return False
    if not uf_value:
        return None
    return total > UF_LIMIT * uf_value
