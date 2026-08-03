from .types import LegalBusinessType

# Static list of business types
# Source: taas-specs/docs/business/financial-transactions-database/business types
# ``name`` keeps the upstream option value verbatim (camelCase) so it stays
# comparable with the payment provider's enum; ``description`` is the option
# label shown to the user. The source's disabled "--" placeholder is omitted —
# an empty selection is not a business type.
LEGAL_BUSINESS_TYPES: list[LegalBusinessType] = [
    LegalBusinessType(name='llc', description='LLC'),
    LegalBusinessType(name='partnership', description='Partnership'),
    LegalBusinessType(name='publicCorporation', description='Public corporation'),
    LegalBusinessType(name='soleProprietorship', description='Sole proprietorship'),
    LegalBusinessType(name='trust', description='Trust'),
    LegalBusinessType(name='privateCorporation', description='Private corporation'),
    LegalBusinessType(
        name='unincorporatedAssociation', description='Unincorporated association'
    ),
    LegalBusinessType(
        name='unincorporatedNonProfit', description='Unincorporated non-profit'
    ),
    LegalBusinessType(
        name='incorporatedNonProfit', description='Incorporated non-profit'
    ),
    LegalBusinessType(name='governmentEntity', description='Government entity'),
]
