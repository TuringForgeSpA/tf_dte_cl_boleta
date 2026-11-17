# -*- coding: utf-8 -*-
"""Consulta pública de boletas electrónicas.

Ruta real: controllers/main.py

El SII exige que el sitio de consulta de la boleta esté impreso en la boleta y
disponible en la web. Esta página es pública (sin inicio de sesión) y:

* exige los cuatro datos impresos: tipo, folio, fecha de emisión y monto total
  (más el RUT del emisor), con coincidencia exacta;
* entrega solo el PDF de esa boleta aceptada (y su XML, si la compañía lo
  habilita); nunca lista, busca por aproximación ni revela por qué no encontró;
* limita los intentos por IP;
* lee con sudo únicamente el registro encontrado.
"""
import base64

from odoo import http
from odoo.http import content_disposition, request

from odoo.addons.tf_dte_cl.models.res_partner import normalize_rut

INVOICE_REPORT = 'account.account_invoices'


class TfDteClBoletaPublic(http.Controller):

    def _tf_dte_cl_default_rut(self):
        companies = request.env['res.company'].sudo().search([('tf_dte_cl_boleta_partner_id', '!=', False)])
        return normalize_rut(companies.vat) if len(companies) == 1 else ''

    def _tf_dte_cl_render(self, values, status=200):
        values.setdefault('emitter_rut', self._tf_dte_cl_default_rut())
        response = request.render('tf_dte_cl_boleta.public_consult', values)
        response.status_code = status
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @http.route('/boleta', type='http', auth='public', methods=['GET'], sitemap=False)
    def consult_form(self, **kwargs):
        return self._tf_dte_cl_render({})

    @http.route('/boleta', type='http', auth='public', methods=['POST'], sitemap=False)
    def consult(self, emitter_rut='', doc_type='39', folio='', emission_date='', total='', file_type='pdf',
                **kwargs):
        values = {
            'emitter_rut': emitter_rut, 'doc_type': doc_type, 'folio': folio,
            'emission_date': emission_date, 'total': total,
        }
        ip = request.httprequest.remote_addr or 'desconocida'
        if not request.env['tf_dte_cl_boleta.consult.attempt'].sudo()._tf_dte_cl_register(ip):
            values['error'] = 'Demasiadas consultas. Intente nuevamente en unos minutos.'
            return self._tf_dte_cl_render(values, status=429)
        total = str(total or '').replace('.', '').replace('$', '').strip()
        move = request.env['account.move'].sudo()._tf_dte_cl_boleta_public_lookup(
            emitter_rut, doc_type, folio, emission_date, total,
        )
        if not move:
            values['error'] = 'No se encontró una boleta con esos datos. Revise que coincidan con la boleta impresa.'
            return self._tf_dte_cl_render(values, status=404)
        label = 'boleta_T%sF%s' % (move.tf_dte_cl_document_type, move.tf_dte_cl_folio)
        if file_type == 'xml' and move.company_id.tf_dte_cl_boleta_public_xml and move.tf_dte_cl_xml_file:
            return request.make_response(base64.b64decode(move.tf_dte_cl_xml_file), headers=[
                ('Content-Type', 'application/xml; charset=ISO-8859-1'),
                ('Content-Disposition', content_disposition(label + '.xml')),
                ('X-Content-Type-Options', 'nosniff'),
                ('Cache-Control', 'no-store'),
            ])
        pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(INVOICE_REPORT, move.ids)[0]
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', content_disposition(label + '.pdf', disposition_type='inline')),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'no-store'),
        ])
