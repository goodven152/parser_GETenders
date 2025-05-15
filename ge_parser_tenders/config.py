START_URL = "https://tenders.procurement.gov.ge/public/?lang=ge"
PAGE_ROWS = 4  # number of tenders shown at once after search
KEYWORDS_GEO = [
    "თუჯის სარქველი",
    "ფლიანეცებს შორის მბრუნავი სარქველი",
    "ორმაგი ექსცენტრიული მბრუნავი სარქველი",
    "მილტუჩა ჩამკეტი რეზინის სარქველით",
    "მილტუჩა ჩამკეტი მეტალის სარქველით",
    "ჰიდრანტი მიწისქვეშა ორმაგი საკეტი",
    "დანისებრი სარქველი",
]

import re
KEYWORDS_RE = re.compile("|".join(map(re.escape, KEYWORDS_GEO)), flags=re.I)
