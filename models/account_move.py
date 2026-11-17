# -*- coding: utf-8 -*-
"""Boletas 39/41 y notas de crédito sobre boletas en account.move.

Ruta real: models/account_move.py

Distingue tres casos, según el diario y las referencias:

* Boleta (diario 39 o 41): montos brutos, receptor anónimo o identificado,
  envío por la API REST del SII (EnvioBOLETA).
* Nota de crédito sobre una boleta (diario 61 con referencia a 39/41): montos
  brutos (MntBruto), receptor como en la boleta; viaja en un EnvioDTE normal.
* Resto: sin cambios respecto del núcleo.
"""
from __future__ import annotations

import dataclasses
import re
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.tf_dte_cl.models.dte_lines import build_detail, round_half_up
from odoo.addons.tf_dte_cl.models.res_partner import is_valid_rut, normalize_rut

from .boleta_lines import (
    ANONYMOUS_NAME,
    BOLETA_TYPES,
    CREDIT_NOTE_TYPE,
    GENERIC_RUT,
    IND_SERVICIO_SALES,
    UF_LIMIT,
    exceeds_uf_limit,
    gross_line_errors,
    gross_totals,
)

IVA_CODE = '14'
# Set de pruebas de boletas del SII: cada boleta referencia su caso con
# CodRef "SET" y RazonRef "CASO-n" (observaciones generales del set).
SET_CODREF = 'SET'
SET_CASE_RE = re.compile(r'^CASO-\d{1,3}$')
# Unidades que el set exige con una grafía distinta del nombre estándar de Odoo.
SII_UOM_NAMES = {'kg': 'Kg'}
ACCEPTED_STATES = ('accepted', 'accepted_objections')


class AccountMove(models.Model):
    _inherit = 'account.move'

    tf_dte_cl_is_boleta = fields.Boolean(string='Es boleta', compute='_compute_tf_dte_cl_is_boleta')
    tf_dte_cl_company_environment = fields.Selection(related='company_id.tf_dte_cl_environment')
    tf_dte_cl_boleta_set_case = fields.Char(
        string='Caso del set de pruebas', copy=False,
        help='Solo en ambiente de certificación, por ejemplo CASO-1. La boleta se informa con '
             'CodRef SET y este caso como RazonRef, y no se envía sola: se envía con el asistente '
             '«Set de certificación de boletas», que arma un único sobre y el consumo de folios.',
    )

    @api.constrains('tf_dte_cl_boleta_set_case', 'company_id', 'journal_id')
    def _check_tf_dte_cl_boleta_set_case(self):
        for move in self.filtered('tf_dte_cl_boleta_set_case'):
            if move.company_id.tf_dte_cl_environment != 'certificacion':
                raise ValidationError(self.env._('El caso del set de pruebas solo se usa en ambiente de certificación.'))
            if move.journal_id.tf_dte_cl_document_type not in BOLETA_TYPES:
                raise ValidationError(self.env._('El caso del set de pruebas solo aplica a boletas.'))
            if not SET_CASE_RE.match(move.tf_dte_cl_boleta_set_case.strip()):
                raise ValidationError(self.env._('Escriba el caso tal como aparece en el set, por ejemplo CASO-1.'))

    @api.depends('journal_id.tf_dte_cl_document_type', 'tf_dte_cl_document_type', 'move_type')
    def _compute_tf_dte_cl_is_boleta(self):
        for move in self:
            move.tf_dte_cl_is_boleta = bool(move._tf_dte_cl_boleta_type())

    # ------------------------------------------------------------------
    # Clasificación
    # ------------------------------------------------------------------
    def _tf_dte_cl_current_type(self) -> str | bool:
        self.ensure_one()
        return self.tf_dte_cl_document_type or self._tf_dte_cl_get_document_type()

    def _tf_dte_cl_boleta_type(self) -> str | bool:
        """'39' o '41' si el documento es una boleta; si no, False."""
        self.ensure_one()
        doc_type = self.tf_dte_cl_document_type or (
            self.move_type == 'out_invoice' and self.journal_id.tf_dte_cl_document_type
        )
        return doc_type if doc_type in BOLETA_TYPES else False

    def _tf_dte_cl_is_boleta_note(self) -> bool:
        """Nota de crédito cuya primera referencia es una boleta.

        Se mira solo la primera, como la librería (``Documento.es_nc_boleta``).
        """
        self.ensure_one()
        first = self.tf_dte_cl_reference_ids[:1]
        return self._tf_dte_cl_current_type() == CREDIT_NOTE_TYPE and first.document_type_id.code in BOLETA_TYPES

    def _tf_dte_cl_gross_mode(self) -> bool:
        self.ensure_one()
        return bool(self._tf_dte_cl_boleta_type()) or self._tf_dte_cl_is_boleta_note()

    # ------------------------------------------------------------------
    # Puntos de extensión del núcleo
    # ------------------------------------------------------------------
    def _tf_dte_cl_invoice_document_types(self):
        return tuple(super()._tf_dte_cl_invoice_document_types()) + BOLETA_TYPES

    def _tf_dte_cl_allows_price_include(self):
        return self._tf_dte_cl_gross_mode() or super()._tf_dte_cl_allows_price_include()

    def _tf_dte_cl_api_payload(self):
        if self._tf_dte_cl_boleta_type():
            return {'api': True}
        return super()._tf_dte_cl_api_payload()

    def _tf_dte_cl_identified_receiver(self):
        """Cliente con RUT válido y distinto del genérico, o un registro vacío (consumidor anónimo)."""
        self.ensure_one()
        commercial = self._tf_dte_cl_get_receiver().commercial_partner_id
        rut = normalize_rut(commercial.vat)
        if commercial and is_valid_rut(rut) and rut != GENERIC_RUT:
            return commercial
        return commercial.browse()

    def _tf_dte_cl_receiver_errors(self):
        if self._tf_dte_cl_gross_mode():
            # Consumidor anónimo (sin RUT: 66666666-6) o identificado por su RUT y nombre.
            # Un RUT mal digitado no debe convertir la boleta en anónima sin aviso.
            commercial = self._tf_dte_cl_get_receiver().commercial_partner_id
            if commercial.vat and not is_valid_rut(commercial.vat):
                return [self.env._('el RUT %s no es válido; corríjalo o quítelo para emitir al consumidor final',
                                   commercial.vat)]
            return []
        return super()._tf_dte_cl_receiver_errors()

    def _tf_dte_cl_receiver_rut(self):
        if self._tf_dte_cl_gross_mode():
            identified = self._tf_dte_cl_identified_receiver()
            return normalize_rut(identified.vat) if identified else GENERIC_RUT
        return super()._tf_dte_cl_receiver_rut()

    def _tf_dte_cl_receiver_payload(self):
        if not self._tf_dte_cl_gross_mode():
            return super()._tf_dte_cl_receiver_payload()
        identified = self._tf_dte_cl_identified_receiver()
        if not identified:
            return {'RUTRecep': GENERIC_RUT, 'RznSocRecep': ANONYMOUS_NAME}
        partner = self._tf_dte_cl_get_receiver()
        return {
            'RUTRecep': normalize_rut(identified.vat),
            'RznSocRecep': (identified.name or '')[:100],
            'DirRecep': ', '.join(filter(None, [partner.street, partner.street2]))[:70],
            'CmnaRecep': (partner.tf_dte_cl_comuna_id.name or '')[:20],
            'CiudadRecep': (partner.city or '')[:20],
        }

    def _tf_dte_cl_print_receiver(self):
        if self._tf_dte_cl_gross_mode():
            return bool(self._tf_dte_cl_identified_receiver())
        return super()._tf_dte_cl_print_receiver()

    def _tf_dte_cl_line_infos(self):
        infos = super()._tf_dte_cl_line_infos()
        if not self._tf_dte_cl_gross_mode():
            return infos
        # Montos brutos: MontoItem es el total de la línea con IVA (price_total).
        lines = self._tf_dte_cl_product_lines()
        return [
            dataclasses.replace(info, subtotal=line.price_total,
                                uom=SII_UOM_NAMES.get((info.uom or '').lower(), info.uom))
            for info, line in zip(infos, lines)
        ]

    def _tf_dte_cl_specific_errors(self):
        errors = super()._tf_dte_cl_specific_errors()
        if not self._tf_dte_cl_gross_mode():
            return errors
        _ = self.env._
        doc_type = self._tf_dte_cl_current_type()
        adjustments = [adj for adj in self._tf_dte_cl_global_adjustments() if adj.amount]
        errors += gross_line_errors(doc_type, self._tf_dte_cl_line_infos(), bool(adjustments))
        errors += self._tf_dte_cl_fractional_line_errors()
        if self._tf_dte_cl_is_boleta_note():
            totals = gross_totals(self._tf_dte_cl_line_infos())
            if totals['iva'] and totals['exempt']:
                # La librería solo informa MntBruto sin montos exentos: con ambos, las líneas
                # con IVA incluido se leerían como netas.
                errors.append(_('una nota de crédito sobre una boleta no puede mezclar líneas afectas y exentas; '
                                'emita una nota para las afectas y otra para las exentas'))
        if self._tf_dte_cl_boleta_type():
            if self.tf_dte_cl_reference_ids:
                errors.append(_('las boletas no llevan referencias en esta versión; quítelas de la pestaña '
                                'Referencias SII'))
            errors += self._tf_dte_cl_uf_errors()
        return errors

    def _tf_dte_cl_fractional_line_errors(self) -> list[str]:
        """Montos brutos: cada línea debe sumar pesos enteros.

        Odoo redondea el total de un documento con IVA incluido sobre la suma sin redondear
        de las líneas, mientras el DTE suma los MontoItem ya redondeados: con totales de
        línea fraccionarios (descuentos en %, cantidades decimales) ambos pueden diferir en
        un peso y la emisión se bloquearía con un mensaje poco claro.
        """
        errors = []
        for line in self._tf_dte_cl_product_lines():
            raw = line.quantity * line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if abs(raw - round(raw)) > 0.0001:
                errors.append(self.env._(
                    'línea "%(line)s": el total con IVA (%(amount)s) debe ser un monto entero en pesos; '
                    'ajuste el precio, la cantidad o el descuento',
                    line=(line.name or '').split('\n')[0][:60], amount=round(raw, 2),
                ))
        return errors

    def _tf_dte_cl_uf_errors(self) -> list[str]:
        """Ley 21.713: sobre 135 UF la boleta exige medio de pago, que la librería no transmite."""
        self.ensure_one()
        total = round_half_up(self.amount_total)
        date = self._tf_dte_cl_get_emission_date()
        exceeds = exceeds_uf_limit(total, None)
        if exceeds is False:
            return []
        uf_value = self.company_id._tf_dte_cl_uf_value(date)
        exceeds = exceeds_uf_limit(total, uf_value)
        if exceeds is None:
            return [self.env._(
                'para verificar el límite de %(limit)s UF de la Ley 21.713 registre el valor de la UF '
                '(moneda CLF) a la fecha %(date)s', limit=UF_LIMIT, date=date,
            )]
        if exceeds:
            return [self.env._(
                'el total supera %s UF: la Ley 21.713 exige informar el medio de pago, que este módulo aún '
                'no transmite; emita una factura', UF_LIMIT,
            )]
        return []

    def _tf_dte_cl_document_values(self):
        if not self._tf_dte_cl_gross_mode():
            return super()._tf_dte_cl_document_values()
        infos = self._tf_dte_cl_line_infos()
        totals = gross_totals(infos)
        if self._tf_dte_cl_boleta_type():
            values = {'IdDoc': {'IndServicio': IND_SERVICIO_SALES}, 'Detalle': build_detail(infos)}
        else:
            values = super()._tf_dte_cl_document_values()
            if totals['iva'] and not totals['exempt']:
                # Formato DTE, campo MntBruto: las líneas de detalle vienen con IVA incluido.
                values['IdDoc']['MntBruto'] = 1
        if totals['iva']:
            values['TasaIVA'] = totals['rate']
            values.update({'MntNeto': totals['net'], 'MntIVA': totals['iva'], 'MntTotal': totals['total']})
        return values

    def _tf_dte_cl_expected_amounts(self):
        if not self._tf_dte_cl_gross_mode():
            return super()._tf_dte_cl_expected_amounts()
        totals = gross_totals(self._tf_dte_cl_line_infos())
        by_code = defaultdict(float)
        for line in self.line_ids.filtered('tax_line_id'):
            by_code[line.tax_line_id.tf_dte_cl_sii_code] += line.balance
        iva = abs(by_code.get(IVA_CODE, 0.0))
        return {
            'MntNeto': self.amount_total - totals['exempt'] - iva,
            'MntExe': totals['exempt'],
            'MntIVA': iva,
            'MntTotal': self.amount_total,
        }

    def _tf_dte_cl_print_totals(self):
        if not self._tf_dte_cl_gross_mode():
            return super()._tf_dte_cl_print_totals()
        _ = self.env._
        totals = gross_totals(self._tf_dte_cl_line_infos())
        rows = []
        if totals['iva']:
            rows.append((_('Monto neto'), totals['net']))
        if totals['exempt']:
            rows.append((_('Monto exento'), totals['exempt']))
        if totals['iva']:
            rows.append((_('IVA %s%% incluido') % ('%g' % totals['rate']).replace('.', ','), totals['iva']))
        rows.append((_('Total'), totals['total']))
        return rows

    def _tf_dte_cl_full_document(self, folio):
        document = super()._tf_dte_cl_full_document(folio)
        if self._tf_dte_cl_boleta_type() and self.tf_dte_cl_boleta_set_case:
            document['Referencia'] = [{
                'NroLinRef': 1, 'CodRef': SET_CODREF, 'RazonRef': self.tf_dte_cl_boleta_set_case.strip(),
            }]
        return document

    # ------------------------------------------------------------------
    # Boletas del set de pruebas: no se envían solas
    # ------------------------------------------------------------------
    def _tf_dte_cl_send(self):
        if self.tf_dte_cl_boleta_set_case:
            # El SII exige el set completo en un solo sobre, junto con el consumo de folios:
            # se genera con el asistente y se sube en el sitio de certificación.
            return self.tf_dte_cl_state
        return super()._tf_dte_cl_send()

    @api.model
    def _cron_tf_dte_cl_send(self, limit=50):
        moves = self.search([
            ('state', '=', 'posted'),
            ('tf_dte_cl_state', '=', 'signed'),
            ('tf_dte_cl_boleta_set_case', '=', False),
        ], order='id', limit=limit)
        moves._tf_dte_cl_run_each('_tf_dte_cl_send_and_sync')

    # ------------------------------------------------------------------
    # Consulta pública (controllers/main.py)
    # ------------------------------------------------------------------
    @api.model
    def _tf_dte_cl_boleta_public_lookup(self, emitter_rut, doc_type, folio, emission_date, total):
        """La boleta aceptada que coincide exactamente con los cuatro datos impresos, o vacío.

        Se llama con sudo desde la página pública: no devuelve nada si algún dato no
        coincide, y nunca más de un documento.
        """
        rut = normalize_rut(emitter_rut)
        if doc_type not in BOLETA_TYPES or not rut:
            return self.browse()
        try:
            folio = int(folio)
            total = int(total)
            emission_date = fields.Date.to_date(emission_date)
        except (TypeError, ValueError):
            return self.browse()
        if folio <= 0 or total < 0 or not emission_date:
            return self.browse()
        moves = self.search([
            ('move_type', '=', 'out_invoice'),
            ('tf_dte_cl_document_type', '=', doc_type),
            ('tf_dte_cl_folio', '=', folio),
            ('tf_dte_cl_emission_date', '=', emission_date),
            ('tf_dte_cl_total_amount', '=', total),
            ('tf_dte_cl_state', 'in', list(ACCEPTED_STATES)),
        ], limit=5).filtered(lambda move: normalize_rut(move.company_id.vat) == rut)
        return moves if len(moves) == 1 else self.browse()

    def _tf_dte_cl_verify_url(self):
        if self._tf_dte_cl_boleta_type():
            return self.company_id._tf_dte_cl_boleta_verify_url()
        return super()._tf_dte_cl_verify_url()

    # ------------------------------------------------------------------
    # Cliente por defecto
    # ------------------------------------------------------------------
    def _tf_dte_cl_boleta_default_partner(self):
        self.ensure_one()
        return self.company_id.tf_dte_cl_boleta_partner_id

    def _tf_dte_cl_needs_boleta_partner(self) -> bool:
        self.ensure_one()
        return (not self.partner_id and self.move_type == 'out_invoice'
                and self.journal_id.tf_dte_cl_document_type in BOLETA_TYPES)

    def _tf_dte_cl_set_boleta_partner(self) -> None:
        for move in self:
            if move._tf_dte_cl_needs_boleta_partner():
                partner = move._tf_dte_cl_boleta_default_partner()
                if partner:
                    move.partner_id = partner

    @api.onchange('journal_id')
    def _onchange_tf_dte_cl_boleta_journal(self):
        self._tf_dte_cl_set_boleta_partner()

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._tf_dte_cl_set_boleta_partner()
        return moves

    def _post(self, soft=True):
        self._tf_dte_cl_set_boleta_partner()
        return super()._post(soft=soft)
