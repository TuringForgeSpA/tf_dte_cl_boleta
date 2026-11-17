# -*- coding: utf-8 -*-
"""Boletas 39/41 y notas de crédito sobre boletas, con el SII simulado.

Ruta real: tests/test_boleta.py
"""
import base64
from datetime import date
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged

from odoo.addons.tf_dte_cl.models import sii_client as sc
from odoo.addons.tf_dte_cl.tests.common import CUSTOMER_RUT, TfDteClCommon
from odoo.addons.tf_dte_cl_boleta.models.boleta_lines import GENERIC_RUT


@tagged('post_install', '-at_install', 'tf_dte_cl_boleta')
class TestBoleta(TfDteClCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company._tf_dte_cl_boleta_setup()
        cls.tax_included = cls.company.tf_dte_cl_boleta_tax_id
        cls.anonymous = env.ref('tf_dte_cl_boleta.partner_tf_dte_cl_boleta_anonymous')
        cls.journal_39 = cls._create_sale_journal('TF39', '39')
        cls.journal_41 = cls._create_sale_journal('TF41', '41')
        cls.caf_39 = cls.create_caf('39', 1, 50)
        cls.caf_41 = cls.create_caf('41', 1, 50)
        cls.exempt_product = env['product.product'].create({
            'name': 'Servicio exento', 'type': 'service', 'list_price': 3000, 'taxes_id': [Command.clear()],
        })
        cls.consumer = env['res.partner'].create({
            'name': 'Juana Pérez', 'vat': CUSTOMER_RUT, 'country_id': cls.chile.id, 'email': 'juana@example.cl',
        })

    # --- utilidades -------------------------------------------------------
    def create_boleta(self, journal=None, partner=None, product=None, quantity=1, price=None):
        """Boleta creada como desde la pantalla: precio e impuestos los calcula el diario."""
        line = {'product_id': (product or self.product).id, 'quantity': quantity}
        if price is not None:
            line['price_unit'] = price
        values = {
            'move_type': 'out_invoice',
            'journal_id': (journal or self.journal_39).id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [Command.create(line)],
        }
        if partner:
            values['partner_id'] = partner.id
        return self.env['account.move'].create(values)

    def post(self, move):
        with self.fake_sii() as fake:
            move.action_post()
        return fake

    def sent_document(self, fake):
        return fake.last_sign_payload['Documento'][0]['documentos'][0]

    # --- configuración ----------------------------------------------------
    def test_setup_creates_included_tax_and_pricelist(self):
        self.assertTrue(self.tax_included.price_include)
        self.assertEqual(self.tax_included.tf_dte_cl_sii_code, '14')
        self.assertEqual(self.company.tf_dte_cl_boleta_partner_id, self.anonymous)
        self.assertTrue(self.company.tf_dte_cl_boleta_pricelist_id)
        # Volver a ejecutarlo no duplica nada.
        self.company._tf_dte_cl_boleta_setup()
        self.assertEqual(self.company.tf_dte_cl_boleta_tax_id, self.tax_included)

    # --- precio y receptor ------------------------------------------------
    def test_price_with_iva_and_included_tax(self):
        move = self.create_boleta()
        line = move.invoice_line_ids
        self.assertEqual(line.price_unit, 11900)                 # 10.000 neto + IVA
        self.assertEqual(line.tax_ids, self.tax_included)
        self.assertEqual(move.amount_total, 11900)
        self.assertEqual(move.partner_id, self.anonymous)       # cliente por defecto al publicar o en pantalla

    def test_public_pricelist_price(self):
        self.env['product.pricelist.item'].create({
            'pricelist_id': self.company.tf_dte_cl_boleta_pricelist_id.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'fixed',
            'fixed_price': 9990,
        })
        move = self.create_boleta()
        self.assertEqual(move.invoice_line_ids.price_unit, 9990)
        self.assertEqual(move.amount_total, 9990)

    def test_pricelist_formula_rule_adds_iva(self):
        # Una regla por porcentaje parte del precio de venta neto: no se toma como precio con IVA.
        self.env['product.pricelist.item'].create({
            'pricelist_id': self.company.tf_dte_cl_boleta_pricelist_id.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'percentage',
            'percent_price': 10,
        })
        self.assertEqual(self.create_boleta().invoice_line_ids.price_unit, 11900)

    def test_exempt_boleta_price_without_iva(self):
        move = self.create_boleta(journal=self.journal_41)
        self.assertEqual(move.invoice_line_ids.price_unit, 10000)

    def test_fractional_line_total_blocked(self):
        move = self.create_boleta(price=9990)
        move.invoice_line_ids.discount = 15                      # 8.491,5 con IVA
        with self.assertUserError('monto entero en pesos'):
            self.post(move)

    def test_invalid_rut_is_not_anonymous(self):
        partner = self.env['res.partner'].create({'name': 'Sin país', 'vat': '12345678-0'})
        move = self.create_boleta(partner=partner)
        with self.assertUserError('no es válido'):
            self.post(move)

    def test_anonymous_boleta_payload(self):
        move = self.create_boleta(quantity=2)
        fake = self.post(move)
        self.assertEqual(move.tf_dte_cl_state, 'signed')
        self.assertEqual((move.tf_dte_cl_document_type, move.tf_dte_cl_folio), ('39', 1))
        self.assertEqual(move.tf_dte_cl_title, 'Boleta electrónica N° 1')
        self.assertEqual(move.tf_dte_cl_receiver_rut, GENERIC_RUT)
        document = self.sent_document(fake)
        self.assertEqual(fake.last_sign_payload['Documento'][0]['TipoDTE'], 39)
        self.assertEqual(document['Encabezado']['IdDoc']['IndServicio'], 3)
        self.assertEqual(document['Encabezado']['Receptor'], {'RUTRecep': GENERIC_RUT, 'RznSocRecep': 'Consumidor final'})
        item = document['Detalle'][0]
        self.assertEqual((item['PrcItem'], item['MontoItem']), (11900, 23800))
        self.assertEqual(item['Impuesto'], [{'CodImp': 14, 'TasaImp': 19.0, 'price_include': True}])
        # Neto = round(23.800 / 1,19) = 20.000 e IVA por diferencia.
        self.assertEqual((document['MntNeto'], document['MntIVA'], document['MntTotal']), (20000, 3800, 23800))
        self.assertEqual(move.tf_dte_cl_total_amount, 23800)

    def test_identified_receiver(self):
        move = self.create_boleta(partner=self.consumer)
        fake = self.post(move)
        receiver = self.sent_document(fake)['Encabezado']['Receptor']
        self.assertEqual((receiver['RUTRecep'], receiver['RznSocRecep']), (CUSTOMER_RUT, 'Juana Pérez'))
        self.assertEqual(move.tf_dte_cl_receiver_rut, CUSTOMER_RUT)

    def test_exempt_boleta(self):
        move = self.create_boleta(journal=self.journal_41, product=self.exempt_product, quantity=2)
        fake = self.post(move)
        self.assertEqual((move.tf_dte_cl_document_type, move.tf_dte_cl_state), ('41', 'signed'))
        document = self.sent_document(fake)
        self.assertEqual(document['Detalle'][0]['IndExe'], 1)
        self.assertNotIn('MntIVA', document)
        self.assertEqual(move.tf_dte_cl_total_amount, 6000)

    def test_exempt_boleta_rejects_iva(self):
        move = self.create_boleta(journal=self.journal_41)
        with self.assertUserError('no lleva impuestos'):
            self.post(move)

    def test_affected_boleta_needs_iva(self):
        move = self.create_boleta(product=self.exempt_product)
        with self.assertUserError('boleta exenta (41)'):
            self.post(move)

    def test_invoice_still_rejects_included_tax(self):
        move = self.create_invoice(taxes=self.tax_included)
        with self.assertUserError('no puede estar incluido en el precio'):
            with self.fake_sii():
                move.action_post()

    # --- Ley 21.713 -------------------------------------------------------
    def test_uf_limit(self):
        big = 5_000_000
        move = self.create_boleta(price=big)
        with self.assertUserError('valor de la UF'):
            self.post(move)
        clf = self.env.ref('base.CLF')
        clf.active = True
        self.env['res.currency.rate'].create({
            'currency_id': clf.id, 'name': date(2000, 1, 1), 'rate': 1 / 30000.0, 'company_id': self.company.id,
        })
        move = self.create_boleta(price=big)
        with self.assertUserError('supera 135 UF'):
            self.post(move)
        move = self.create_boleta(price=4_000_000)
        self.post(move)
        self.assertEqual(move.tf_dte_cl_state, 'signed')

    # --- envío por la API REST --------------------------------------------
    def test_send_and_query_use_api(self):
        payloads = []
        client_class = type(self.env['tf_dte_cl.sii.client'])
        with self.fake_sii():
            move = self.create_boleta()
            move.action_post()
            original_send = client_class.tf_dte_cl_send_envelope
            original_query = client_class.tf_dte_cl_query_upload

            def send(client, payload):
                payloads.append(('send', payload))
                return original_send(client, payload)

            def query(client, payload):
                payloads.append(('query', payload))
                return original_query(client, payload)

            with patch.object(client_class, 'tf_dte_cl_send_envelope', send), \
                    patch.object(client_class, 'tf_dte_cl_query_upload', query):
                self.assertEqual(move._tf_dte_cl_send(), 'sent')
                self.assertEqual(move._tf_dte_cl_query(), 'accepted')
        self.assertEqual([kind for kind, _payload in payloads], ['send', 'query'])
        self.assertTrue(all(payload.get('api') for _kind, payload in payloads))

    def test_invoice_does_not_use_api(self):
        with self.fake_sii():
            move = self.create_invoice()
            move.action_post()
        self.assertEqual(move._tf_dte_cl_api_payload(), {})

    # --- nota de crédito sobre boleta -------------------------------------
    def test_credit_note_on_boleta(self):
        with self.fake_sii():
            boleta = self.create_boleta()
            boleta.action_post()
            boleta._tf_dte_cl_send()
            boleta._tf_dte_cl_query()
            refund = boleta._reverse_moves([{'ref': 'Devolución'}], cancel=False)
        self.assertEqual(refund.journal_id, self.journal_61)
        self.assertEqual(refund.tf_dte_cl_reference_ids.document_type_id.code, '39')
        refund.tf_dte_cl_reference_ids.code = '1'                 # anula la boleta
        fake = self.post(refund)
        self.assertEqual((refund.tf_dte_cl_document_type, refund.tf_dte_cl_state), ('61', 'signed'))
        document = self.sent_document(fake)
        self.assertEqual(document['Encabezado']['IdDoc']['MntBruto'], 1)
        self.assertEqual(document['Encabezado']['Receptor']['RUTRecep'], GENERIC_RUT)
        self.assertEqual(document['Referencia'][0]['TpoDocRef'], 39)      # número: la librería la reconoce
        self.assertEqual((document['MntNeto'], document['MntIVA'], document['MntTotal']), (10000, 1900, 11900))
        self.assertEqual(refund._tf_dte_cl_api_payload(), {})     # la nota va por el envío normal

    def test_credit_note_on_mixed_boleta_blocked(self):
        with self.fake_sii():
            boleta = self.env['account.move'].create({
                'move_type': 'out_invoice', 'journal_id': self.journal_39.id,
                'invoice_date': fields.Date.context_today(self.env.user),
                'invoice_line_ids': [Command.create({'product_id': self.product.id}),
                                     Command.create({'product_id': self.exempt_product.id})],
            })
            boleta.action_post()
            boleta.write({'tf_dte_cl_state': 'accepted'})
            refund = boleta._reverse_moves([{'ref': 'Devolución'}], cancel=False)
        with self.assertUserError('no puede mezclar líneas afectas y exentas'):
            self.post(refund)

    # --- set de pruebas de certificación --------------------------------
    def test_set_case_reference_and_no_send(self):
        move = self.create_boleta()
        move.tf_dte_cl_boleta_set_case = 'CASO-1'
        fake = self.post(move)
        self.assertEqual(self.sent_document(fake)['Referencia'],
                         [{'NroLinRef': 1, 'CodRef': 'SET', 'RazonRef': 'CASO-1'}])
        with self.fake_sii() as fake:
            self.assertEqual(move._tf_dte_cl_send(), 'signed')
            self.env['account.move']._cron_tf_dte_cl_send()
        self.assertEqual(fake.calls['send'], 0)          # el set no se envía solo
        self.assertEqual(move.tf_dte_cl_state, 'signed')

    def test_set_case_rules(self):
        move = self.create_boleta()
        with self.assertRaises(ValidationError):
            move.tf_dte_cl_boleta_set_case = 'caso 1'
        self.company.tf_dte_cl_environment = 'produccion'
        with self.assertRaises(ValidationError):
            move.tf_dte_cl_boleta_set_case = 'CASO-1'
        self.company.tf_dte_cl_environment = 'certificacion'
        invoice = self.create_invoice()
        with self.assertRaises(ValidationError):
            invoice.tf_dte_cl_boleta_set_case = 'CASO-1'

    def test_uom_kg_is_informed_as_set_requires(self):
        kg = self.env.ref('uom.product_uom_kgm')
        rice = self.env['product.product'].create({
            'name': 'Arroz', 'list_price': 588.24, 'uom_id': kg.id, 'uom_po_id': kg.id,
            'taxes_id': [Command.set(self.tax_iva.ids)],
        })
        move = self.create_boleta(product=rice, quantity=5, price=700)
        fake = self.post(move)
        self.assertEqual(self.sent_document(fake)['Detalle'][0]['UnmdItem'], 'Kg')

    # --- consulta pública -------------------------------------------------
    def test_public_lookup(self):
        move = self.create_boleta()
        self.post(move)
        Move = self.env['account.move'].sudo()
        args = (self.company.vat, '39', move.tf_dte_cl_folio, move.tf_dte_cl_emission_date, 11900)
        self.assertFalse(Move._tf_dte_cl_boleta_public_lookup(*args))   # aún no aceptada
        move.tf_dte_cl_state = 'accepted'
        self.assertEqual(Move._tf_dte_cl_boleta_public_lookup(*args), move)
        self.assertFalse(Move._tf_dte_cl_boleta_public_lookup(self.company.vat, '39', move.tf_dte_cl_folio,
                                                              move.tf_dte_cl_emission_date, 11901))
        self.assertFalse(Move._tf_dte_cl_boleta_public_lookup(CUSTOMER_RUT, *args[1:]))
        self.assertFalse(Move._tf_dte_cl_boleta_public_lookup(self.company.vat, '33', *args[2:]))
        self.assertFalse(Move._tf_dte_cl_boleta_public_lookup(self.company.vat, '39', 'x', None, 'y'))

    def test_verify_url_printed(self):
        self.company.tf_dte_cl_boleta_verify_url = 'https://turingforge.cl/boleta/'
        move = self.create_boleta()
        self.post(move)
        self.assertEqual(move._tf_dte_cl_verify_url(), 'turingforge.cl/boleta')
        html = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', move.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn('turingforge.cl/boleta', html)
        invoice = self.create_invoice()
        self.assertEqual(invoice._tf_dte_cl_verify_url(), 'www.sii.cl')

    # --- impresión --------------------------------------------------------
    def test_report_anonymous(self):
        move = self.create_boleta()
        self.post(move)
        html = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', move.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Boleta electrónica', html)
        self.assertIn('IVA 19% incluido', html)
        self.assertIn('Fecha emisión', html)
        self.assertNotIn('Consumidor final', html)              # sin receptor identificado
        self.assertNotIn('CEDIBLE', html)
        thermal = self.env['ir.actions.report']._render_qweb_html('tf_dte_cl.report_move_dte_thermal', move.ids)[0]
        thermal = thermal.decode() if isinstance(thermal, bytes) else thermal
        self.assertIn('IVA 19% incluido', thermal)
        self.assertNotIn('Consumidor final', thermal)

    def test_report_identified(self):
        move = self.create_boleta(partner=self.consumer)
        self.post(move)
        html = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', move.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Juana Pérez', html)


@tagged('post_install', '-at_install', 'tf_dte_cl_boleta')
class TestBoletaLibrary(TfDteClCommon):
    """Firma y sobre con facturacion_electronica real (sin red).

    La librería valida cada DTE y cada sobre contra los XSD del SII
    (EnvioBOLETA_v11.xsd, EnvioDTE_v10.xsd) antes de devolverlos.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sc.fe is None:
            cls.skipTest(cls, 'facturacion_electronica no está instalada')
        cls.company._tf_dte_cl_boleta_setup()
        cls.journal_39 = cls._create_sale_journal('TL39', '39')
        cls.create_caf('39', 1, 50)

    def xml_of(self, record) -> str:
        return base64.b64decode(record.tf_dte_cl_xml_file).decode('ISO-8859-1')

    def test_boleta_and_credit_note_with_library(self):
        boleta = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.journal_39.id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [Command.create({'product_id': self.product.id, 'quantity': 2})],
        })
        boleta.action_post()
        self.assertEqual(boleta.tf_dte_cl_state, 'signed', boleta.tf_dte_cl_error)
        xml = self.xml_of(boleta)
        for fragment in ('<TipoDTE>39</TipoDTE>', '<IndServicio>3</IndServicio>', '<RUTRecep>66666666-6</RUTRecep>',
                         '<MntNeto>20000</MntNeto>', '<IVA>3800</IVA>', '<MntTotal>23800</MntTotal>',
                         '<MontoItem>23800</MontoItem>'):
            self.assertIn(fragment, xml)
        envelope = boleta.tf_dte_cl_envelope_id._tf_dte_cl_xml_text()
        self.assertIn('<EnvioBOLETA', envelope)
        self.assertIn('<RutReceptor>60803000-K</RutReceptor>', envelope)

        boleta.write({'tf_dte_cl_state': 'accepted'})
        refund = boleta._reverse_moves([{'ref': 'Devolución'}], cancel=False)
        refund.tf_dte_cl_reference_ids.code = '1'
        refund.action_post()
        self.assertEqual(refund.tf_dte_cl_state, 'signed', refund.tf_dte_cl_error)
        xml = self.xml_of(refund)
        for fragment in ('<TipoDTE>61</TipoDTE>', '<MntBruto>1</MntBruto>', '<TpoDocRef>39</TpoDocRef>',
                         '<MntTotal>23800</MntTotal>'):
            self.assertIn(fragment, xml)
        self.assertIn('<EnvioDTE', refund.tf_dte_cl_envelope_id._tf_dte_cl_xml_text())

    def test_certification_set_with_library(self):
        moves = self.env['account.move']
        for case, quantity in (('CASO-1', 1), ('CASO-2', 3)):
            move = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'journal_id': self.journal_39.id,
                'invoice_date': fields.Date.context_today(self.env.user),
                'tf_dte_cl_boleta_set_case': case,
                'invoice_line_ids': [Command.create({'product_id': self.product.id, 'quantity': quantity})],
            })
            move.action_post()
            self.assertEqual(move.tf_dte_cl_state, 'signed', move.tf_dte_cl_error)
            self.assertIn('<CodRef>SET</CodRef>', self.xml_of(move))
            moves |= move
        wizard = self.env['tf_dte_cl_boleta.set.wizard'].with_context(
            active_model='account.move', active_ids=moves.ids).create({})
        wizard.action_generate()
        envelope = base64.b64decode(wizard.envelope_file).decode('ISO-8859-1')
        self.assertEqual(envelope.count('<DTE '), 2)
        self.assertIn('<EnvioBOLETA', envelope)
        self.assertIn('<RazonRef>CASO-2</RazonRef>', envelope)
        rcof = base64.b64decode(wizard.rcof_file).decode('ISO-8859-1')
        for fragment in ('<ConsumoFolios', '<TipoDocumento>39</TipoDocumento>', '<FoliosEmitidos>2</FoliosEmitidos>',
                         '<MntTotal>47600</MntTotal>', '<SecEnvio>1</SecEnvio>'):
            self.assertIn(fragment, rcof)

    def test_certification_set_rejects_cases(self):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': self.journal_39.id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [Command.create({'product_id': self.product.id})],
        })
        move.action_post()
        wizard = self.env['tf_dte_cl_boleta.set.wizard'].create({'move_ids': [Command.set(move.ids)]})
        with self.assertRaisesRegex(Exception, 'no tiene caso del set'):
            wizard.action_generate()


@tagged('post_install', '-at_install', 'tf_dte_cl_boleta')
class TestBoletaPublicPage(HttpCase):

    def csrf(self):
        response = self.url_open('/boleta')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Consulta de boletas', response.text)
        return response.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]

    def test_not_found_and_rate_limit(self):
        token = self.csrf()
        data = {'csrf_token': token, 'emitter_rut': '76086428-5', 'doc_type': '39', 'folio': '999',
                'emission_date': '2026-11-17', 'total': '1000'}
        statuses = [self.url_open('/boleta', data=data).status_code for _i in range(11)]
        self.assertEqual(statuses[:10], [404] * 10)
        self.assertEqual(statuses[10], 429)

    def test_found_returns_only_that_boleta(self):
        company = self.env.company
        company.write({'vat': '76086428-5', 'tf_dte_cl_environment': 'certificacion'})
        journal = self.env['account.journal'].create({
            'name': 'Boletas web', 'code': 'BWEB', 'type': 'sale', 'tf_dte_cl_document_type': '39',
        })
        partner = self.env.ref('tf_dte_cl_boleta.partner_tf_dte_cl_boleta_anonymous')
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': journal.id, 'partner_id': partner.id,
            'invoice_date': '2026-11-17',
            'invoice_line_ids': [(0, 0, {'name': 'Cambio de aceite', 'quantity': 1, 'price_unit': 19900,
                                         'tax_ids': [(5, 0, 0)]})],
        })
        move.write({
            'state': 'posted', 'tf_dte_cl_document_type': '39', 'tf_dte_cl_folio': 7,
            'tf_dte_cl_emission_date': '2026-11-17', 'tf_dte_cl_total_amount': 19900,
            'tf_dte_cl_state': 'accepted',
        })
        token = self.csrf()
        data = {'csrf_token': token, 'emitter_rut': '76.086.428-5', 'doc_type': '39', 'folio': '7',
                'emission_date': '2026-11-17', 'total': '19.900'}
        response = self.url_open('/boleta', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response.headers['Content-Type'])
        self.assertIn('boleta_T39F7.pdf', response.headers['Content-Disposition'])
        # El XML no se entrega si la compañía no lo habilitó.
        response = self.url_open('/boleta', data=dict(data, file_type='xml'))
        self.assertIn('application/pdf', response.headers['Content-Type'])
