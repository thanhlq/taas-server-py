""" Contains common types used in the EWS library. """
from foundation.serialization import BaseModel

class LegalBusinessType(BaseModel):
    """ Represents a business type in the EWS library. """
    name: str # Unique name of the business type
    description: str

class BusinessType(BaseModel):
    """ Represents a business type in the EWS library. """
    name: str # Unique name of the business type
    description: str
    legal_business_type: LegalBusinessType # The legal business type associated with this business type

class IndustryType(BaseModel):
    """ Represents an industry type in the EWS library. """
    name: str # Unique name of the industry type
    description: str
    category: str # The category of the industry type


