""" Static industry taxonomy used by the EWS onboarding / KYB flows. """

from ews.common.types import IndustryType

# Source: taas-specs/docs/business/financial-transactions-database/industry.md
# The source is a scraped DOM carrying display labels only, so ``name`` is a
# derived camelCase key ("&" spelled out) — keep it stable once persisted.
INDUSTRY_TYPES: list[IndustryType] = [
    # ── Professional Services ──
    IndustryType(
        name='accountingAndTaxServices',
        description='Accounting & Tax Services',
        category='Professional Services',
    ),
    IndustryType(
        name='advertisingAndMarketing',
        description='Advertising & Marketing',
        category='Professional Services',
    ),
    IndustryType(
        name='bailBonds',
        description='Bail Bonds',
        category='Professional Services',
    ),
    IndustryType(
        name='bankruptcyConsulting',
        description='Bankruptcy Consulting',
        category='Professional Services',
    ),
    IndustryType(
        name='businessConsulting',
        description='Business Consulting',
        category='Professional Services',
    ),
    IndustryType(
        name='commercialPhotography',
        description='Commercial Photography',
        category='Professional Services',
    ),
    IndustryType(
        name='computerRepairServices',
        description='Computer Repair Services',
        category='Professional Services',
    ),
    IndustryType(
        name='creativeAndDesignServices',
        description='Creative & Design Services',
        category='Professional Services',
    ),
    IndustryType(
        name='creditCounselingAndRepair',
        description='Credit Counseling & Repair',
        category='Professional Services',
    ),
    IndustryType(
        name='debtResolutionServices',
        description='Debt Resolution Services',
        category='Professional Services',
    ),
    IndustryType(
        name='doorToDoorSales',
        description='Door-to-Door Sales',
        category='Professional Services',
    ),
    IndustryType(
        name='employmentServices',
        description='Employment Services',
        category='Professional Services',
    ),
    IndustryType(
        name='engineeringAndArchitecture',
        description='Engineering & Architecture',
        category='Professional Services',
    ),
    IndustryType(
        name='governmentServices',
        description='Government Services',
        category='Professional Services',
    ),
    IndustryType(
        name='leadGenerationServices',
        description='Lead Generation Services',
        category='Professional Services',
    ),
    IndustryType(
        name='legalServices',
        description='Legal Services',
        category='Professional Services',
    ),
    IndustryType(
        name='mortgageConsulting',
        description='Mortgage Consulting',
        category='Professional Services',
    ),
    IndustryType(
        name='otherDirectMarketing',
        description='Other Direct Marketing',
        category='Professional Services',
    ),
    IndustryType(
        name='printingAndPublishing',
        description='Printing & Publishing',
        category='Professional Services',
    ),
    IndustryType(
        name='professionalMiscellaneous',
        description='Professional Miscellaneous',
        category='Professional Services',
    ),
    IndustryType(
        name='realEstateServices',
        description='Real Estate Services',
        category='Professional Services',
    ),
    IndustryType(
        name='securityAndProtectionServices',
        description='Security & Protection Services',
        category='Professional Services',
    ),
    IndustryType(
        name='subscriptionMarketing',
        description='Subscription Marketing',
        category='Professional Services',
    ),
    IndustryType(
        name='telemarketingServices',
        description='Telemarketing Services',
        category='Professional Services',
    ),
    IndustryType(
        name='testingLaboratories',
        description='Testing Laboratories',
        category='Professional Services',
    ),
    IndustryType(
        name='travelMarketingServices',
        description='Travel Marketing Services',
        category='Professional Services',
    ),
    IndustryType(
        name='warrantyServices',
        description='Warranty Services',
        category='Professional Services',
    ),

    # ── Regulated Industries ──
    IndustryType(
        name='adultContent',
        description='Adult Content',
        category='Regulated Industries',
    ),
    IndustryType(
        name='alcoholAndSpirits',
        description='Alcohol & Spirits',
        category='Regulated Industries',
    ),
    IndustryType(
        name='cannabisProducts',
        description='Cannabis Products',
        category='Regulated Industries',
    ),
    IndustryType(
        name='cBDAndHempProducts',
        description='CBD & Hemp Products',
        category='Regulated Industries',
    ),
    IndustryType(
        name='eCigarettesAndVapes',
        description='E-Cigarettes & Vapes',
        category='Regulated Industries',
    ),
    IndustryType(
        name='firearmsAndAmmunition',
        description='Firearms & Ammunition',
        category='Regulated Industries',
    ),
    IndustryType(
        name='pharmacies',
        description='Pharmacies',
        category='Regulated Industries',
    ),
    IndustryType(
        name='smokingAccessories',
        description='Smoking Accessories',
        category='Regulated Industries',
    ),
    IndustryType(
        name='supplementsAndNutraceuticals',
        description='Supplements & Nutraceuticals',
        category='Regulated Industries',
    ),
    IndustryType(
        name='tobaccoAndCigars',
        description='Tobacco & Cigars',
        category='Regulated Industries',
    ),

    # ── Wholesale, Manufacturing & Industrial ──
    IndustryType(
        name='agricultureAndFarming',
        description='Agriculture & Farming',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='agricultureServices',
        description='Agriculture Services',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='farmEquipmentAndMachinery',
        description='Farm Equipment & Machinery',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='farmSupplies',
        description='Farm Supplies',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='hardwareEquipmentAndSupplies',
        description='Hardware Equipment & Supplies',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='industrialEquipmentAndSupplies',
        description='Industrial Equipment & Supplies',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='livestockProductionAndFishing',
        description='Livestock Production & Fishing',
        category='Wholesale, Manufacturing & Industrial',
    ),
    IndustryType(
        name='lumberAndBuildingMaterials',
        description='Lumber & Building Materials',
        category='Wholesale, Manufacturing & Industrial',
    ),

    # ── Transportation & Logistics ──
    IndustryType(
        name='airlineCarriers',
        description='Airline Carriers',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='autoDealerships',
        description='Auto Dealerships',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='autoRepairAndMaintenance',
        description='Auto Repair & Maintenance',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='cruisesAndMarineTravel',
        description='Cruises & Marine Travel',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='marineAndBoating',
        description='Marine & Boating',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='movingAndRelocationServices',
        description='Moving & Relocation Services',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='parkingFacilities',
        description='Parking Facilities',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='publicTransit',
        description='Public Transit',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='recreationalAndUtilityVehicles',
        description='Recreational & Utility Vehicles',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='shippingAndCourierServices',
        description='Shipping & Courier Services',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='storageAndWarehousing',
        description='Storage & Warehousing',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='taxisAndRideServices',
        description='Taxis & Ride Services',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='transportationMiscellaneous',
        description='Transportation Miscellaneous',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='truckingAndFreight',
        description='Trucking & Freight',
        category='Transportation & Logistics',
    ),
    IndustryType(
        name='usedVehicleSalesAndService',
        description='Used Vehicle Sales & Service',
        category='Transportation & Logistics',
    ),

    # ── Entertainment & Recreation ──
    IndustryType(
        name='amusementAndThemeParks',
        description='Amusement & Theme Parks',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='arcadeAndGaming',
        description='Arcade & Gaming',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='countryClubs',
        description='Country Clubs',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='eventTicketing',
        description='Event Ticketing',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='fitnessClubs',
        description='Fitness Clubs',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='fortuneTellers',
        description='Fortune Tellers',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='lotteryAndGaming',
        description='Lottery & Gaming',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='movieTheaters',
        description='Movie Theaters',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='musiciansAndBands',
        description='Musicians & Bands',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='onlineGambling',
        description='Online Gambling',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='outdoorRecreationServices',
        description='Outdoor Recreation Services',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='recreationalCamps',
        description='Recreational Camps',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='sportsBettingAndFantasy',
        description='Sports Betting & Fantasy',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='sportsAndSocialClubs',
        description='Sports & Social Clubs',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='theaterAndPerformingArts',
        description='Theater & Performing Arts',
        category='Entertainment & Recreation',
    ),
    IndustryType(
        name='touristAttractions',
        description='Tourist Attractions',
        category='Entertainment & Recreation',
    ),

    # ── Personal Services ──
    IndustryType(
        name='animalServicesAndBreeding',
        description='Animal Services & Breeding',
        category='Personal Services',
    ),
    IndustryType(
        name='childcareServices',
        description='Childcare Services',
        category='Personal Services',
    ),
    IndustryType(
        name='cleaningServices',
        description='Cleaning Services',
        category='Personal Services',
    ),
    IndustryType(
        name='datingServices',
        description='Dating Services',
        category='Personal Services',
    ),
    IndustryType(
        name='funeralAndMemorialServices',
        description='Funeral & Memorial Services',
        category='Personal Services',
    ),
    IndustryType(
        name='healthAndBeautySpa',
        description='Health & Beauty Spa',
        category='Personal Services',
    ),
    IndustryType(
        name='laundryAndDryCleaning',
        description='Laundry & Dry Cleaning',
        category='Personal Services',
    ),
    IndustryType(
        name='massageServices',
        description='Massage Services',
        category='Personal Services',
    ),
    IndustryType(
        name='personalCounseling',
        description='Personal Counseling',
        category='Personal Services',
    ),
    IndustryType(
        name='petCareAndGrooming',
        description='Pet Care & Grooming',
        category='Personal Services',
    ),
    IndustryType(
        name='photographyServices',
        description='Photography Services',
        category='Personal Services',
    ),
    IndustryType(
        name='salonsAndBarbers',
        description='Salons & Barbers',
        category='Personal Services',
    ),
    IndustryType(
        name='tailoringAndAlterations',
        description='Tailoring & Alterations',
        category='Personal Services',
    ),
    IndustryType(
        name='wellnessCoaching',
        description='Wellness Coaching',
        category='Personal Services',
    ),

    # ── Retail ──
    IndustryType(
        name='antiquesAndUsedGoods',
        description='Antiques & Used Goods',
        category='Retail',
    ),
    IndustryType(
        name='autoPartsAndAccessories',
        description='Auto Parts & Accessories',
        category='Retail',
    ),
    IndustryType(
        name='bicycleSalesAndService',
        description='Bicycle Sales & Service',
        category='Retail',
    ),
    IndustryType(
        name='booksAndMedia',
        description='Books & Media',
        category='Retail',
    ),
    IndustryType(
        name='clothingAndAccessories',
        description='Clothing & Accessories',
        category='Retail',
    ),
    IndustryType(
        name='departmentAndDiscountStores',
        description='Department & Discount Stores',
        category='Retail',
    ),
    IndustryType(
        name='electronicsAndAppliances',
        description='Electronics & Appliances',
        category='Retail',
    ),
    IndustryType(
        name='flowersAndFlorist',
        description='Flowers & Florist',
        category='Retail',
    ),
    IndustryType(
        name='furnitureAndHomeGoods',
        description='Furniture & Home Goods',
        category='Retail',
    ),
    IndustryType(
        name='gardenAndOutdoorSupply',
        description='Garden & Outdoor Supply',
        category='Retail',
    ),
    IndustryType(
        name='giftsAndSouvenirs',
        description='Gifts & Souvenirs',
        category='Retail',
    ),
    IndustryType(
        name='hardwareStores',
        description='Hardware Stores',
        category='Retail',
    ),
    IndustryType(
        name='healthAndBeautyProducts',
        description='Health & Beauty Products',
        category='Retail',
    ),
    IndustryType(
        name='hobbyToysAndGames',
        description='Hobby, Toys & Games',
        category='Retail',
    ),
    IndustryType(
        name='jewelryAndWatches',
        description='Jewelry & Watches',
        category='Retail',
    ),
    IndustryType(
        name='miscellaneousRetail',
        description='Miscellaneous Retail',
        category='Retail',
    ),
    IndustryType(
        name='musicalInstruments',
        description='Musical Instruments',
        category='Retail',
    ),
    IndustryType(
        name='officeAndSchoolSupplies',
        description='Office & School Supplies',
        category='Retail',
    ),
    IndustryType(
        name='onlineAuctions',
        description='Online Auctions',
        category='Retail',
    ),
    IndustryType(
        name='onlineMarketplace',
        description='Online Marketplace',
        category='Retail',
    ),
    IndustryType(
        name='petSupplies',
        description='Pet Supplies',
        category='Retail',
    ),
    IndustryType(
        name='preciousMetalsAndGems',
        description='Precious Metals & Gems',
        category='Retail',
    ),
    IndustryType(
        name='softwareAndApplications',
        description='Software & Applications',
        category='Retail',
    ),
    IndustryType(
        name='sportingGoods',
        description='Sporting Goods',
        category='Retail',
    ),

    # ── Construction Services ──
    IndustryType(
        name='applianceRepair',
        description='Appliance Repair',
        category='Construction Services',
    ),
    IndustryType(
        name='carpentryServices',
        description='Carpentry Services',
        category='Construction Services',
    ),
    IndustryType(
        name='constructionMaterials',
        description='Construction Materials',
        category='Construction Services',
    ),
    IndustryType(
        name='constructionMiscellaneous',
        description='Construction Miscellaneous',
        category='Construction Services',
    ),
    IndustryType(
        name='electricalContracting',
        description='Electrical Contracting',
        category='Construction Services',
    ),
    IndustryType(
        name='generalContracting',
        description='General Contracting',
        category='Construction Services',
    ),
    IndustryType(
        name='handymanAndRepairServices',
        description='Handyman & Repair Services',
        category='Construction Services',
    ),
    IndustryType(
        name='hVACServices',
        description='HVAC Services',
        category='Construction Services',
    ),
    IndustryType(
        name='landscapingServices',
        description='Landscaping Services',
        category='Construction Services',
    ),
    IndustryType(
        name='masonryAndTileWork',
        description='Masonry & Tile Work',
        category='Construction Services',
    ),
    IndustryType(
        name='paintingServices',
        description='Painting Services',
        category='Construction Services',
    ),
    IndustryType(
        name='pestControl',
        description='Pest Control',
        category='Construction Services',
    ),
    IndustryType(
        name='plumbingServices',
        description='Plumbing Services',
        category='Construction Services',
    ),
    IndustryType(
        name='propertyMaintenance',
        description='Property Maintenance',
        category='Construction Services',
    ),
    IndustryType(
        name='roofingServices',
        description='Roofing Services',
        category='Construction Services',
    ),
    IndustryType(
        name='telecomEquipment',
        description='Telecom Equipment',
        category='Construction Services',
    ),
    IndustryType(
        name='telecommunicationServices',
        description='Telecommunication Services',
        category='Construction Services',
    ),
    IndustryType(
        name='utilities',
        description='Utilities',
        category='Construction Services',
    ),

    # ── Education ──
    IndustryType(
        name='artsInstruction',
        description='Arts Instruction',
        category='Education',
    ),
    IndustryType(
        name='collegesAndUniversities',
        description='Colleges & Universities',
        category='Education',
    ),
    IndustryType(
        name='educationConsulting',
        description='Education Consulting',
        category='Education',
    ),
    IndustryType(
        name='educationMiscellaneous',
        description='Education Miscellaneous',
        category='Education',
    ),
    IndustryType(
        name='primaryAndSecondarySchools',
        description='Primary & Secondary Schools',
        category='Education',
    ),
    IndustryType(
        name='professionalTraining',
        description='Professional Training',
        category='Education',
    ),
    IndustryType(
        name='tutoringServices',
        description='Tutoring Services',
        category='Education',
    ),
    IndustryType(
        name='vocationalTraining',
        description='Vocational Training',
        category='Education',
    ),

    # ── Healthcare & Medical ──
    IndustryType(
        name='assistedLivingAndCare',
        description='Assisted Living & Care',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='chiropractors',
        description='Chiropractors',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='dentistsAndOrthodontists',
        description='Dentists & Orthodontists',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='doctorsAndPhysicians',
        description='Doctors & Physicians',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='eyeCareSpecialists',
        description='Eye Care Specialists',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='homeHealthcare',
        description='Home Healthcare',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='hospitals',
        description='Hospitals',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='medicalAndDentalLabs',
        description='Medical & Dental Labs',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='medicalEquipmentAndSupplies',
        description='Medical Equipment & Supplies',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='medicalMiscellaneous',
        description='Medical Miscellaneous',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='mentalHealthServices',
        description='Mental Health Services',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='nutritionists',
        description='Nutritionists',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='opticiansAndEyewear',
        description='Opticians & Eyewear',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='specialtyMedicalCare',
        description='Specialty Medical Care',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='telemedicineServices',
        description='Telemedicine Services',
        category='Healthcare & Medical',
    ),
    IndustryType(
        name='veterinaryServices',
        description='Veterinary Services',
        category='Healthcare & Medical',
    ),

    # ── Food & Beverage ──
    IndustryType(
        name='bakeries',
        description='Bakeries',
        category='Food & Beverage',
    ),
    IndustryType(
        name='barsAndNightclubs',
        description='Bars & Nightclubs',
        category='Food & Beverage',
    ),
    IndustryType(
        name='beerWineAndSpiritsStores',
        description='Beer, Wine & Spirits Stores',
        category='Food & Beverage',
    ),
    IndustryType(
        name='cafesAndCoffeeShops',
        description='Cafés & Coffee Shops',
        category='Food & Beverage',
    ),
    IndustryType(
        name='cateringAndEventServices',
        description='Catering & Event Services',
        category='Food & Beverage',
    ),
    IndustryType(
        name='convenienceStores',
        description='Convenience Stores',
        category='Food & Beverage',
    ),
    IndustryType(
        name='fastFoodAndQuickService',
        description='Fast Food & Quick Service',
        category='Food & Beverage',
    ),
    IndustryType(
        name='groceryStores',
        description='Grocery Stores',
        category='Food & Beverage',
    ),
    IndustryType(
        name='meatAndSeafoodShops',
        description='Meat & Seafood Shops',
        category='Food & Beverage',
    ),
    IndustryType(
        name='restaurants',
        description='Restaurants',
        category='Food & Beverage',
    ),
    IndustryType(
        name='specialtyFoodStores',
        description='Specialty Food Stores',
        category='Food & Beverage',
    ),

    # ── Financial Services ──
    IndustryType(
        name='banksAndCreditUnions',
        description='Banks & Credit Unions',
        category='Financial Services',
    ),
    IndustryType(
        name='crowdfunding',
        description='Crowdfunding',
        category='Financial Services',
    ),
    IndustryType(
        name='cryptocurrencies',
        description='Cryptocurrencies',
        category='Financial Services',
    ),
    IndustryType(
        name='currencyExchange',
        description='Currency Exchange',
        category='Financial Services',
    ),
    IndustryType(
        name='debtCollection',
        description='Debt Collection',
        category='Financial Services',
    ),
    IndustryType(
        name='digitalAssetsAndNFTs',
        description='Digital Assets & NFTs',
        category='Financial Services',
    ),
    IndustryType(
        name='digitalWallets',
        description='Digital Wallets',
        category='Financial Services',
    ),
    IndustryType(
        name='financialServicesMiscellaneous',
        description='Financial Services Miscellaneous',
        category='Financial Services',
    ),
    IndustryType(
        name='insurance',
        description='Insurance',
        category='Financial Services',
    ),
    IndustryType(
        name='investmentSecurities',
        description='Investment Securities',
        category='Financial Services',
    ),
    IndustryType(
        name='investmentServices',
        description='Investment Services',
        category='Financial Services',
    ),
    IndustryType(
        name='loanRepaymentNonFinancialInstitution',
        description='Loan Repayment (Non-Financial Institution)',
        category='Financial Services',
    ),
    IndustryType(
        name='moneyOrders',
        description='Money Orders',
        category='Financial Services',
    ),
    IndustryType(
        name='moneyTransferServices',
        description='Money Transfer Services',
        category='Financial Services',
    ),
    IndustryType(
        name='paymentProcessing',
        description='Payment Processing',
        category='Financial Services',
    ),
    IndustryType(
        name='titleAndPaydayLoans',
        description='Title & Payday Loans',
        category='Financial Services',
    ),

    # ── Travel & Lodging ──
    IndustryType(
        name='campingAndRVParks',
        description='Camping & RV Parks',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='hotelsAndMotels',
        description='Hotels & Motels',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='resorts',
        description='Resorts',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='timeshares',
        description='Timeshares',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='travelAgenciesAndTours',
        description='Travel Agencies & Tours',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='travelAndLodgingMiscellaneous',
        description='Travel & Lodging Miscellaneous',
        category='Travel & Lodging',
    ),
    IndustryType(
        name='vacationRentals',
        description='Vacation Rentals',
        category='Travel & Lodging',
    ),

    # ── Nonprofits & Charities ──
    IndustryType(
        name='charitableOrganizations',
        description='Charitable Organizations',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='civicAndSocialAssociations',
        description='Civic & Social Associations',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='communityServiceGroups',
        description='Community Service Groups',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='nonprofitMiscellaneous',
        description='Nonprofit Miscellaneous',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='philanthropicFoundations',
        description='Philanthropic Foundations',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='politicalAndAdvocacyGroups',
        description='Political & Advocacy Groups',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='professionalOrganizations',
        description='Professional Organizations',
        category='Nonprofits & Charities',
    ),
    IndustryType(
        name='religiousOrganizations',
        description='Religious Organizations',
        category='Nonprofits & Charities',
    ),

    # ── Digital Products ──
    IndustryType(
        name='cloudStorageAndBackup',
        description='Cloud Storage & Backup',
        category='Digital Products',
    ),
    IndustryType(
        name='digitalArtAndImages',
        description='Digital Art & Images',
        category='Digital Products',
    ),
    IndustryType(
        name='digitalMediaDownloads',
        description='Digital Media Downloads',
        category='Digital Products',
    ),
    IndustryType(
        name='digitalProductsMiscellaneous',
        description='Digital Products Miscellaneous',
        category='Digital Products',
    ),
    IndustryType(
        name='digitalPublishing',
        description='Digital Publishing',
        category='Digital Products',
    ),
    IndustryType(
        name='eBooksAndAudiobooks',
        description='eBooks & Audiobooks',
        category='Digital Products',
    ),
    IndustryType(
        name='gamesAndVirtualGoods',
        description='Games & Virtual Goods',
        category='Digital Products',
    ),
    IndustryType(
        name='mobileApplications',
        description='Mobile Applications',
        category='Digital Products',
    ),
    IndustryType(
        name='softwareAsAService',
        description='Software as a Service',
        category='Digital Products',
    ),
    IndustryType(
        name='streamingServices',
        description='Streaming Services',
        category='Digital Products',
    ),
    IndustryType(
        name='userGeneratedContent',
        description='User Generated Content',
        category='Digital Products',
    ),
    IndustryType(
        name='webHostingAndDomains',
        description='Web Hosting & Domains',
        category='Digital Products',
    ),
]
