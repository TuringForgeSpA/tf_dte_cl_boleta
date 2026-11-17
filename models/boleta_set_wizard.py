# -*- coding: utf-8 -*-
"""Set de pruebas de boletas: un único sobre EnvioBOLETA y su consumo de folios.

Ruta real: models/boleta_set_wizard.py

Instrucciones del SII (correo «Proceso Certificación de Boletas Electrónicas»):
generar las boletas del set con un CAF de 5 folios, enviar el set **en un solo
archivo (sobre)** y el RCOF asociado **por UPLOAD** en ambiente de certificación,
y pedir la revisión informando el Track ID. Plazo: 24 horas desde la descarga
del CAF.

El asistente solo arma y firma los dos archivos; el usuario los sube en el
sitio de certificación del SII. Ninguna boleta del set se envía sola.
"""
from __future__ import annotations

import base64

from odoo import fields, models
from odoo.exceptions import UserError

from .boleta_lines import BOLETA_TYPES, gross_totals


class TfDteClBoletaSetWizard(models.TransientModel):
    _name = 'tf_dte_cl_boleta.set.wizard'
    _description = 'Set de certificación de boletas'

    move_ids = fields.Many2many('account.move', string='Boletas del set', required=True)
    sec_envio = fields.Integer(
        string='Secuencia del consumo de folios', default=1, required=True,
        help='SecEnvio del RCOF: 1 la primera vez; súbala si repite el envío del mismo día.',
    )
    envelope_file = fields.Binary(string='Sobre de boletas', readonly=True, attachment=False)
    envelope_filename = fields.Char(readonly=True)
    rcof_file = fields.Binary(string='Consumo de folios (RCOF)', readonly=True, attachment=False)
    rcof_filename = fields.Char(readonly=True)

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'account.move' and 'move_ids' in fields_list:
            values['move_ids'] = [(6, 0, self.env.context.get('active_ids') or [])]
        return values

    # ------------------------------------------------------------------
    def _tf_dte_cl_check_moves(self):
        _ = self.env._
        moves = self.move_ids
        if not moves:
            raise UserError(_('Seleccione las boletas del set.'))
        if len(moves.company_id) != 1:
            raise UserError(_('Las boletas del set deben ser de una sola compañía.'))
        company = moves.company_id
        if company.tf_dte_cl_environment != 'certificacion':
            raise UserError(_('El set de pruebas solo se arma en ambiente de certificación.'))
        problems = []
        for move in moves:
            label = move.tf_dte_cl_title or move.name
            if move.tf_dte_cl_document_type not in BOLETA_TYPES:
                problems.append(_('%s no es una boleta', label))
            elif not move.tf_dte_cl_boleta_set_case:
                problems.append(_('%s no tiene caso del set', label))
            elif not move.tf_dte_cl_xml_file:
                problems.append(_('%s no está firmada', label))
        cases = moves.mapped(lambda move: (move.tf_dte_cl_boleta_set_case or '').strip())
        if len(set(cases)) != len(cases):
            problems.append(_('hay casos repetidos'))
        dates = set(moves.mapped('tf_dte_cl_emission_date'))
        if len(dates) != 1:
            problems.append(_('todas las boletas del set deben tener la misma fecha de emisión'))
        if problems:
            raise UserError(_('No se puede armar el set: %s.', '; '.join(problems)))
        return company

    def _tf_dte_cl_sorted_moves(self):
        return self.move_ids.sorted(lambda move: (move.tf_dte_cl_document_type, move.tf_dte_cl_folio))

    def _tf_dte_cl_envelope_payload(self, company):
        moves = self._tf_dte_cl_sorted_moves()
        groups = []
        for doc_type in BOLETA_TYPES:
            typed = moves.filtered(lambda move, dt=doc_type: move.tf_dte_cl_document_type == dt)
            if typed:
                groups.append({
                    'TipoDTE': int(doc_type),
                    'documentos': [{
                        'NroDTE': index,
                        'Folio': move.tf_dte_cl_folio,
                        'sii_xml_request': base64.b64decode(move.tf_dte_cl_xml_file).decode('ISO-8859-1'),
                    } for index, move in enumerate(typed, start=1)],
                })
        first = moves[0]
        payload = dict(first._tf_dte_cl_base_payload(), Documento=groups)
        payload['ID'] = 'TFSETBOL%s' % self.id
        payload['filename'] = 'EnvioBOLETA_SET_%s.xml' % first.tf_dte_cl_emission_date
        return payload

    def _tf_dte_cl_consumption_payload(self, company):
        moves = self._tf_dte_cl_sorted_moves()
        date = moves[0].tf_dte_cl_emission_date
        groups = []
        for doc_type in BOLETA_TYPES:
            typed = moves.filtered(lambda move, dt=doc_type: move.tf_dte_cl_document_type == dt)
            if not typed:
                continue
            documents = []
            for move in typed:
                totals = gross_totals(move._tf_dte_cl_line_infos())
                documents.append({
                    'Folio': move.tf_dte_cl_folio,
                    'TasaImp': totals['rate'],
                    'MntNeto': totals['net'],
                    'MntIVA': totals['iva'],
                    'MntExe': totals['exempt'],
                    'MntTotal': move.tf_dte_cl_total_amount,
                })
            groups.append({'TipoDTE': int(doc_type), 'documentos': documents})
        return dict(moves[0]._tf_dte_cl_base_payload(), FchInicio=date, FchFinal=date,
                    SecEnvio=self.sec_envio, Documento=groups)

    def action_generate(self):
        """Arma y firma el sobre único y el RCOF del set."""
        self.ensure_one()
        company = self._tf_dte_cl_check_moves()
        client = self.env['tf_dte_cl.sii.client']
        envelope = client.tf_dte_cl_build_envelope(self._tf_dte_cl_envelope_payload(company))
        if not envelope.ok:
            raise UserError(self.env._('Error al armar el sobre del set: %s', envelope.message))
        consumption = client.tf_dte_cl_build_consumption(self._tf_dte_cl_consumption_payload(company))
        if not consumption.ok:
            raise UserError(self.env._('Error al armar el consumo de folios: %s', consumption.message))
        self.write({
            'envelope_file': base64.b64encode(envelope.xml.encode('ISO-8859-1')),
            'envelope_filename': envelope.filename,
            'rcof_file': base64.b64encode(consumption.xml.encode('ISO-8859-1')),
            'rcof_filename': consumption.filename,
        })
        for move in self.move_ids:
            move._tf_dte_cl_log(self.env._(
                'Incluida en el sobre del set de pruebas %s (para subir en el sitio de certificación del SII).',
                envelope.filename,
            ))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
