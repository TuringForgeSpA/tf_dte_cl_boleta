# -*- coding: utf-8 -*-
{
    'name': 'Facturación electrónica SII Chile - Boletas',
    'summary': 'Boletas electrónicas 39 y 41 (y sus notas de crédito) desde Contabilidad.',
    'version': '18.0.1.1.0',
    'description': 'Boletas electrónicas ante el SII de Chile sobre tf_dte_cl. Ver README.md.',
    'category': 'Accounting/Localizations/EDI',
    'license': 'LGPL-3',
    'author': 'TF',
    'depends': ['tf_dte_cl'],
    'data': [
        'security/ir.model.access.csv',
        'data/res_partner_data.xml',
        'data/document_type_data.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/boleta_set_wizard_views.xml',
        'views/public_consult_templates.xml',
        'report/report_templates.xml',
    ],
    'post_init_hook': '_tf_dte_cl_boleta_post_init',
    'installable': True,
    'application': False,
}
