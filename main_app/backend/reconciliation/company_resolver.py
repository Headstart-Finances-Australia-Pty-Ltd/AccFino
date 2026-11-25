"""
company_resolver.py
-------------------------------------------------------------------------------
Resolves the 'Who' column for each bank transaction.

Architecture
------------
  CompanyResolver.resolve(description, debit, credit)
    -
    -- 1. HOME COMPANY CHECK   - user's own company - - Internal
    -- 2. ENTITY EXTRACTION    - parse description into a clean entity name
    -      -- Prefix patterns  (Transfer To, Direct Credit, OSKO, BPAY -)
    -      -- Card patterns    (MERCHANT CITY AU Card xx####)
    -      -- Star patterns    (UBER*EATS, APPLE*BILL)
    -      -- Plain fallback   (Harsh Singh Savings - Harsh Singh)
    -- 3. ALIAS DB LOOKUP      - match extracted entity against company DB
    -      (Uxt - "UXT Pty Ltd", ato - "Australian Taxation Office")
    -- 4. FULL DESC DB LOOKUP  - card/plain descriptions searched in full
    -- 5. RETURN EXTRACTED     - fallback: return parsed entity name as-is

Design principles
-----------------
  - Never crashes - every step wrapped in try/except
  - Longer aliases win over shorter (specificity)
  - Short aliases (-4 chars) use word-boundary matching (prevents "ing"-ING inside "SINGH")
  - Transfer To / Direct Credit descriptions only search the extracted entity
    (prevents CommBank alias matching in "Transfer To Harsh Singh - Macq CommBank App")
  - Masked account numbers (xx####) are recognised and skipped
  - No external dependencies - pure Python stdlib + optional DB
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


# ------------------------------------------------------------------------------
# SECTION 1 - Compiled patterns
# ------------------------------------------------------------------------------

# -- 1a. Transaction prefixes - words before the entity name ----------------
# Each alternative ends BEFORE the entity name begins.
# Order matters: longer/more-specific first so they win over "to\s+".
_PREFIX = re.compile(
    r"""^(?:
        # -- Transfer variants ----------------------------------------------
        (?:fast\s+)?transfer\s+(?:to|from)\s+          |
        tfr\s+(?:to|from)\s+                            |
        trf\s+(?:to|from)\s+                            |
        internet\s+transfer\s+(?:to|from)\s+            |
        online\s+transfer\s+(?:to|from)\s+              |
        eft\s+(?:to|from)\s+                            |
        pexa\s+(?:transfer|settlement)\s+               |
        pay\s+anyone\s+(?:to\s+)?                       |

        # -- Payment / received ---------------------------------------------
        payment\s+(?:to|from)\s+                        |
        paid\s+(?:to|by)\s+                             |
        received\s+from\s+                              |

        # -- Direct credit / debit ------------------------------------------
        direct\s+credit\s+(?:\d{3,10}\s+)?             |
        direct\s+debit\s+(?:\d{3,10}\s+)?              |
        direct\s+entry\s+(?:\d{3,10}\s+)?              |

        # -- OSKO / NPP -----------------------------------------------------
        osko\s+(?:to|from|payment|credit|debit)\s+      |
        osko\s+                                         |
        npp\s+(?:to|from)\s+                            |

        # -- BPAY -----------------------------------------------------------
        bpay\s+(?:ref(?:erence)?\s+)?(?:\d+\s+)?        |
        bpay\s+(?:to\s+)?                               |
        b-?pay\s+(?:ref\s+)?\d+\s+                     |

        # -- PAYG / Tax -----------------------------------------------------
        payg\s+(?:withholding|instalment|tax)\s+        |
        payg\s+\w+\s+                                   |
        bas\s+payment\s+(?:to\s+)?                      |

        # -- Salary / payroll / super ---------------------------------------
        salary\s+(?:payment\s+)?(?:to\s+)?              |
        wages?\s+(?:payment\s+)?(?:to\s+)?              |
        payroll\s+(?:to\s+)?                            |
        superannuation\s+(?:contribution\s+)?(?:to\s+)? |
        super\s+contribution\s+(?:to\s+)?               |

        # -- Return / refund ------------------------------------------------
        return\s+                                        |
        refund\s+(?:from\s+)?                           |

        # -- Bare To / From (Macquarie, some CBA) --------------------------
        # Must be followed by a word char - avoids matching "Towards" etc.
        (?:^to\s+)(?=\w)                                |
        (?:^from\s+)(?=\w)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# -- 1b. Suffix noise - everything FROM this point is noise -----------------
_SUFFIX = re.compile(
    r"""(?:
        # Invoice / reference numbers
        \s+inv(?:oice)?[-\s]*\d+\w*                     |   # INV0100, INV-0059
        \s+ref[-:\s]*\d{4,}                             |   # Ref: 123456

        # Macquarie receipt format
        \s+-\s+receipt\s+number:.*$                     |   # "- Receipt number: 66168851 BSB: ..."
        \s+bsb:\s*\d+.*$                                |   # "BSB: 182512 A/C: ..."
        \s+payment\s+description:.*$                    |   # "Payment description: Wise"
        \s+a\/c:\s*\d+.*$                               |

        # CommBank app noise
        \s+commbank\b.*                                  |   # "CommBank App savings"
        \s+from\s+commbank\s+app\b.*                    |   # "from CommBank App salary"
        \s+app\s+(?:savings|salary|wages?|payroll|transfer|innomesh).*$ |

        # PayID noise
        \s+payid\b.*                                    |   # "PayID Email from CommBank"
        \s+via\s+payid\b.*                              |

        # Bank / account suffixes
        \s*[--]\s*(-:macq|macquarie|westpac|anz|nab|cba|commbank|stgeorge|
                      ing|amp|boq|bendigo|suncorp|hsbc|citibank|ubank)\b.* |
        \s+bsb\b.*                                      |
        \s+a\/c\b.*                                     |
        \s+account\s+\d+.*$                             |

        # Card / date noise
        \s+value\s+date\b.*                             |   # "Value Date: 14/06/2025"
        \s+card\s+xx\w*\b.*                             |   # "Card xx0174"

        # Credit-to-account (UXT pattern)
        \s+credit\s+to\s+account\b.*                    |   # "CREDIT TO ACCOUNT INV-0059"

        # Trailing numbers / codes
        \s+\d{6,}\s*$                                   |   # trailing 6+ digit numbers
        \s+\(\w+\)\s*$                                      # trailing (code)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# -- 1c. Card transaction: MERCHANT [SUBURB] AU|US|GB Card xx#### -----------
_CARD = re.compile(
    r"^(.+?)\s+(?:\w+\s+)?(?:AU|US|GB|NZ|SG|CA|EU|UK)\s+Card\s+xx",
    re.IGNORECASE,
)

# -- 1d. Merchant*Reference: UBER*EATS, APPLE*COM/BILL ----------------------
_STAR = re.compile(r"^([^*\s][^*]{1,50}?)\s*\*\s*\S")

# -- 1e. Leading digit noise (BSB/account at start) -------------------------
_LEADING_DIGITS = re.compile(r"^\d[\d\s]{3,8}\s+")

# -- 1f. Trailing noise from any extracted name -----------------------------
_TRAIL = re.compile(
    r"""(?:
        \s*[\-#@/]\s*$                                  |   # trailing punctuation
        \s+(?:au|pty\.?\s*ltd\.?|pty|ltd|limited|
               inc\.?|llc|llp|corp\.?|co\.)\s*$        |   # legal suffixes
        \s+(?:sydney|melbourne|brisbane|perth|
               adelaide|canberra|hobart|darwin)\s*$     |   # city names
        \s+pty\s*$                                          # standalone pty
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# -- 1g. Plain-description tail noise ---------------------------------------
_PLAIN_TAIL = re.compile(
    r"""\s+(?:
        savings|saving|
        direct|
        transfer|
        payment|
        account|
        banking|
        mobile|
        app|
        online
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# -- 1h. Descriptions that have no extractable entity ----------------------
_EMPTY_DESC = re.compile(
    r"""^(?:
        transfer\s+from\s+commbank(?:\s+app)?  |
        transfer\s+from\s+cba                  |
        internet\s+banking\s+transfer          |
        misc(?:ellaneous)?\s+payment           |
        eft\s+payment                          |
        bank\s+fee                             |
        monthly\s+fee                          |
        annual\s+fee                           |
        interest\s+charged                     |
        debit\s+interest                       |
        credit\s+interest                      |
        atm\s+withdrawal                       |
        cash\s+withdrawal                      |
        \d+                                        # pure digits
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# -- 1i. Masked account number patterns - not a company name ----------------
_MASKED_ACCOUNT = re.compile(r"^xx\d+", re.IGNORECASE)


# ------------------------------------------------------------------------------
# SECTION 2 - Entity extraction
# ------------------------------------------------------------------------------

def _clean(raw: str) -> str:
    """Apply all noise-stripping passes to a raw extracted string."""
    if not raw:
        return ""
    raw = _LEADING_DIGITS.sub("", raw).strip()
    raw = _SUFFIX.split(raw)[0].strip()
    raw = _TRAIL.sub("", raw).strip()
    raw = re.sub(r"\s+\d+\s*$", "", raw).strip()   # trailing standalone digits
    raw = re.sub(r"\s{2,}", " ", raw).strip()       # collapse whitespace
    return raw


def _valid(raw: str) -> bool:
    """Return True if raw looks like a real entity name."""
    if not raw or len(raw) < 2:
        return False
    if raw.isdigit():
        return False
    if _MASKED_ACCOUNT.match(raw):
        return False
    # Reject single-char tokens
    if len(raw) == 1:
        return False
    # Reject single ALL-CAPS tokens -2 chars (too ambiguous)
    if raw == raw.upper() and len(raw) <= 2 and " " not in raw:
        return False
    return True


def extract_entity(desc: str) -> str:
    """
    Parse a bank statement description and return the entity name.

    Tries strategies in order:
      1. Prefix  - Transfer To X, Direct Credit BSB X, OSKO To X, etc.
      2. Card    - MERCHANT SUBURB AU Card xx####
      3. Star    - MERCHANT*REFERENCE
      4. Plain   - Harsh Singh Savings  -  Harsh Singh

    Returns "" if nothing extractable found.
    """
    text = (desc or "").strip()
    if not text:
        return ""

    # -- Strategy 1: Prefix -------------------------------------------------
    try:
        m = _PREFIX.match(text)
        if m:
            raw = _clean(text[m.end():])
            if _valid(raw):
                return raw.title()
    except Exception:
        pass

    # -- Strategy 2: Card transaction ---------------------------------------
    try:
        m2 = _CARD.match(text)
        if m2:
            raw = m2.group(1).strip()
            # Strip trailing reference codes preceded by space (not 7-ELEVEN / JB HI-FI)
            raw = re.sub(r"\s+[-#]\w+$", "", raw).strip()
            # Strip trailing standalone numbers
            raw = re.sub(r"\s+\d+\s*$", "", raw).strip()
            # Strip trailing ALL-CAPS suburb (SOUTHBANK, AUBURN, HOMEBUSH)
            raw = re.sub(r"\s+[A-Z][A-Z0-9]{2,}$", "", raw).strip()
            # Strip .COM domain suffixes
            raw = re.sub(r"\.com.*$", "", raw, flags=re.IGNORECASE).strip()
            raw = _TRAIL.sub("", raw).strip()
            if _valid(raw):
                return raw.title()
    except Exception:
        pass

    # -- Strategy 3: Merchant*Reference -------------------------------------
    try:
        m3 = _STAR.match(text)
        if m3:
            raw = _TRAIL.sub("", m3.group(1).strip()).strip()
            if _valid(raw):
                return raw.title()
    except Exception:
        pass

    # -- Strategy 4: Plain name fallback ------------------------------------
    try:
        if not _EMPTY_DESC.match(text) and not _PREFIX.match(text):
            raw = _PLAIN_TAIL.sub("", text).strip()
            raw = _TRAIL.sub("", raw).strip()
            # Remove trailing standalone digit clusters
            raw = re.sub(r"\s+\d+\s*$", "", raw).strip()
            if _valid(raw) and len(raw) >= 4:
                return raw.title()
    except Exception:
        pass

    return ""


# ------------------------------------------------------------------------------
# SECTION 3 - Alias DB lookup
# ------------------------------------------------------------------------------

def _alias_lookup(text: str, cache: dict) -> str:
    """
    Search alias cache against text.
    - Longer aliases checked first (specificity wins)
    - Aliases -4 chars use word-boundary matching (stops "ing" - ING inside "SINGH")
    - Never raises - returns "" on any error
    """
    if not text or not cache:
        return ""
    try:
        for alias in sorted(cache.keys(), key=len, reverse=True):
            if alias not in text:
                continue
            if len(alias) <= 4:
                if not re.search(r"\b" + re.escape(alias) + r"\b", text):
                    continue
            return cache[alias]
    except Exception:
        pass
    return ""


# ------------------------------------------------------------------------------
# SECTION 4 - Home company alias generation
# ------------------------------------------------------------------------------

def _home_aliases(name: str, extra: list) -> set:
    """
    Auto-generate search aliases from the user's registered company name.

    "Headstart Finances Australia Pty Ltd"
      -> {"headstart finances australia pty ltd",
          "headstart finances australia",
          "headstart finances",
          "hfa"}   (acronym)

    Single-word aliases are only kept when >= 7 characters (long enough to
    be unambiguous). Short single words like "good", "aus", "tech" match
    too many unrelated bank descriptions and must not be used.
    """
    if not name:
        return set()

    aliases: set = set()
    n = name.strip().lower()
    aliases.add(n)

    # Strip legal suffixes to get clean trading name
    for suffix in [" pty ltd", " pty. ltd.", " limited", " ltd",
                   " pty", " co.", " inc.", " llc", " llp",
                   " incorporated", " corporation", " corp."]:
        if n.endswith(suffix):
            clean = n[:-len(suffix)].strip()
            aliases.add(clean)

    # Generic words — never use as standalone identifiers
    _GENERIC = {"pty","ltd","the","and","for","with","aus","pty.",
               "australia","australian","finances","financial","services",
               "group","holdings","solutions","consulting","management",
               "technology","technologies","enterprises","investments",
               "capital","global","international","national","digital",
               "systems","network","networks","media","health","care",
               "property","properties","construction"}

    words = [w for w in n.split() if len(w) >= 2 and w not in _GENERIC]

    if words:
        if len(words) == 1:
            # Single meaningful word: use only if >= 5 chars
            # e.g. 'Prama' from 'Prama AI', 'Headstart' from 'Headstart Australia Pty Ltd'
            if len(words[0]) >= 5:
                aliases.add(words[0])
        else:
            # Multiple meaningful words: use first 2 (safest)
            aliases.add(" ".join(words[:2]))
            if len(words) >= 3:
                aliases.add(" ".join(words[:3]))

    # Acronym from capital letters in original name (min 3 chars to be safe)
    try:
        acronym = "".join(c for c in name if c.isupper()).lower()
        if len(acronym) >= 3:
            aliases.add(acronym)
    except Exception:
        pass

    # User-supplied extras
    for e in (extra or []):
        try:
            aliases.add(e.strip().lower())
        except Exception:
            pass

    return {a for a in aliases if a and len(a) >= 3}


# ------------------------------------------------------------------------------
# SECTION 5 - CompanyResolver
# ------------------------------------------------------------------------------

class CompanyResolver:
    """
    Resolves the 'Who' field for a bank transaction description.

    Usage
    -----
        resolver = CompanyResolver(db=session, home_company="Headstart Finances Australia Pty Ltd")
        who, is_internal = resolver.resolve("Transfer To Headstart Finances...")
        # - ("Headstart Finances Australia Pty Ltd", True)

    Resolution steps
    ----------------
      1. Home company check    - - Internal if matches
      2. Entity extraction     - parse clean name from description
      3. Alias DB lookup       - map extracted entity to canonical company name
      4. Full-desc DB lookup   - for card/plain descriptions, search full text
      5. Return extracted name - use parsed entity as-is if DB has no match
      6. Return ""             - genuinely unresolvable

    Fault tolerance
    ---------------
      Every step is wrapped individually. DB failure gracefully falls through
      to the next step. Never raises an exception.
    """

    def __init__(
        self,
        db=None,
        home_company: str = "",
        home_aliases_extra: Optional[list] = None,
    ):
        self.db = db
        self.home_company = (home_company or "").strip()
        self._alias_cache: dict = {}
        self._cache_loaded = False

        # Pre-compute home company aliases
        self._home_aliases: set = set()
        try:
            if self.home_company:
                self._home_aliases = _home_aliases(
                    self.home_company, home_aliases_extra or []
                )
        except Exception:
            pass

    # -- Load alias DB into memory ------------------------------------------
    def _load_alias_cache(self):
        """Load all approved company aliases from DB. Called once, cached."""
        if self._cache_loaded:
            return
        self._cache_loaded = True   # set first so a DB error doesn't retry
        if not self.db:
            return
        try:
            try:
                from db_app.models.company import Company, CompanyAlias
            except ImportError:
                return  # company model not available - skip DB lookup
            rows = (
                self.db
                .query(CompanyAlias.alias, Company.name)
                .join(Company, CompanyAlias.company_id == Company.id)
                .filter(Company.approved == True)
                .order_by(CompanyAlias.priority.desc())
                .all()
            )
            for alias, name in rows:
                if alias and name:
                    self._alias_cache[alias.strip().lower()] = name
        except Exception:
            pass   # DB unavailable - continue without alias cache

    # -- Main resolver ------------------------------------------------------
    def resolve(
        self,
        description: str,
        debit:  float = 0.0,
        credit: float = 0.0,
    ) -> Tuple[str, bool]:
        """
        Returns (who_name, is_internal).

        Parameters
        ----------
        description : raw bank statement description text
        debit       : debit amount (unused currently, reserved for future scoring)
        credit      : credit amount (unused currently, reserved for future scoring)

        Returns
        -------
        (who, is_internal)
            who         - company/person name, or "" if unresolvable
            is_internal - True if this transaction involves the user's own company
        """
        try:
            return self._resolve_inner(description)
        except Exception:
            return "", False   # absolute fallback - never crash the pipeline

    def _resolve_inner(self, description: str) -> Tuple[str, bool]:
        desc = (description or "").strip()
        if not desc:
            return "", False

        desc_lower = desc.lower()

        # -- Step 1: Home company -------------------------------------------
        # Use word-boundary matching for short aliases (< 8 chars) to prevent
        # "aus" matching inside "because", or "ing" inside "savings".
        # Long aliases use simple substring match (fast enough, specific enough).
        try:
            if self.home_company and self._home_aliases:
                for alias in sorted(self._home_aliases, key=len, reverse=True):
                    if len(alias) < 8:
                        if re.search(r"\b" + re.escape(alias) + r"\b", desc_lower):
                            return self.home_company, True
                    else:
                        if alias in desc_lower:
                            return self.home_company, True
        except Exception:
            pass

        # -- Step 2: Extract clean entity name -----------------------------
        extracted = ""
        try:
            extracted = extract_entity(desc)
        except Exception:
            pass

        is_prefix_desc = False
        try:
            is_prefix_desc = bool(_PREFIX.match(desc))
        except Exception:
            pass

        # -- Step 3: Alias DB - search extracted entity --------------------
        self._load_alias_cache()
        if extracted:
            try:
                match = _alias_lookup(extracted.lower(), self._alias_cache)
                if match:
                    return match, False
            except Exception:
                pass

        # -- Step 4: Alias DB - search full description --------------------
        # For card/plain/star descriptions only (not Transfer To / Direct Credit -
        # those have a clean extracted entity that already avoided false matches)
        if not is_prefix_desc:
            try:
                match = _alias_lookup(desc_lower, self._alias_cache)
                if match:
                    return match, False
            except Exception:
                pass
        else:
            # For prefix descriptions, also search the full description
            # but only if extracted entity gave no result
            # (catches "Transfer To Wise..." where "wise" alias is in full desc)
            if not extracted:
                try:
                    match = _alias_lookup(desc_lower, self._alias_cache)
                    if match:
                        return match, False
                except Exception:
                    pass

        # -- Step 5: Return extracted entity -------------------------------
        if extracted:
            return extracted, False

        return "", False

    # -- Auto-capture new companies -----------------------------------------
    def capture_new_company(self, who: str, description: str):
        """
        Save a newly-seen entity to the company DB as pending.
        Admin can approve it in the Company DB admin page.
        Never raises.
        """
        if not who or not who.strip() or not self.db:
            return
        try:
            try:
                from db_app.models.company import Company
            except ImportError:
                return  # company model not available
            exists = (
                self.db.query(Company)
                .filter(Company.name.ilike(f"%{who}%"))
                .first()
            )
            if not exists:
                self.db.add(Company(
                    name=who,
                    short_name=who[:50],
                    category="Unknown",
                    country="AU",
                    approved=False,
                ))
                self.db.commit()
        except Exception:
            pass


# ------------------------------------------------------------------------------
# SECTION 6 - Convenience wrapper
# ------------------------------------------------------------------------------

def resolve_who(
    description: str,
    home_company: str = "",
    db=None,
    debit:  float = 0.0,
    credit: float = 0.0,
) -> Tuple[str, bool]:
    """
    Stateless one-shot resolver. Use CompanyResolver directly when processing
    many rows (shared alias cache = much faster).
    """
    return CompanyResolver(db=db, home_company=home_company).resolve(
        description, debit, credit
    )
