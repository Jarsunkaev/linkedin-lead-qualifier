"""LinkedIn profile scraper with 2024-2025 structure support and multi-layered extraction."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from apify import Actor
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import LinkedInProfile


class LinkedInScraper:
    """Scraper for LinkedIn profiles with anti-detection and rate limiting."""
    
    def __init__(
        self,
        max_concurrency: int = 5,
        request_delay: float = 3.0,  # Increased from 2.0 based on research
        retry_attempts: int = 3,
        headless: bool = True,
        linkedin_cookie: Optional[str] = None,
    ):
        self.max_concurrency = max_concurrency
        self.request_delay = request_delay
        self.retry_attempts = retry_attempts
        self.headless = headless
        self.linkedin_cookie = linkedin_cookie or 'AQEDAUBl5DYEK-2pAAABmaFpohEAAAGZxXYmEU0AZzAJ5YtjBl1iIkVDitCxnG-F-djtN88Uit__qdxwtVbRXYY2CtGZSiyqOwPSZG0Hg697vb14cpPwmFTIFKFg6xkRQ9GXr86n4a-05Uie07LHsMZq'
        self.crawler: Optional[PlaywrightCrawler] = None
        self.results: List[LinkedInProfile] = []
        self.last_request_time = 0
        
        # Multi-layered extraction strategies
        self.extraction_strategies = {
            'json_ld': self._extract_from_json_ld,
            'css_selectors': self._extract_with_css_selectors,
            'content_based': self._extract_from_content
        }
        
        # 2024-2025 LinkedIn selector mappings
        self.selectors = {
            'name': [
                'h1[data-anonymize="person-name"]',  # Most reliable
                'h1.text-heading-xlarge',
                '.pv-text-details__left-panel h1',
                '.ph5.pb5 h1',
                '.pv-top-card .pv-top-card__information h1',
                'h1'  # Generic fallback
            ],
            'headline': [
                '[data-anonymize="headline"]',
                '.text-body-medium.break-words',
                '.pv-text-details__left-panel .text-body-medium',
                '.pv-top-card__headline'
            ],
            'location': [
                '[data-anonymize="location"]',
                '.text-body-small.inline.t-black--light.break-words',
                '.pv-text-details__left-panel .text-body-small',
                '.pv-top-card__location'
            ],
            'experience_container': [
                '[data-field="experience"] .pvs-entity',
                '.pv-profile-section[data-section="experience"] .pv-entity',
                '#experience .pvs-list__item',
                '.experience-section .pv-entity'
            ],
            'job_title': [
                '.mr1.t-bold span[aria-hidden="true"]',
                '.pvs-entity__caption-wrapper h3',
                '.pv-entity__summary-info h3'
            ],
            'company_name': [
                '.t-14.t-normal span[aria-hidden="true"]',
                '.pvs-entity__caption-wrapper .t-14',
                '.pv-entity__secondary-title'
            ]
        }
        
    async def initialize(self) -> None:
        """Initialize the crawler with proper configuration."""
        self.crawler = PlaywrightCrawler(
            max_requests_per_crawl=10000,
            headless=self.headless,
            browser_launch_options={
                'args': [
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-blink-features=AutomationControlled',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ],
            },
            request_handler_timeout=timedelta(seconds=60),
        )
        
        @self.crawler.router.default_handler
        async def profile_handler(context: PlaywrightCrawlingContext) -> None:
            """Handle LinkedIn profile scraping."""
            try:
                profile = await self._extract_profile_data(context.page, context.request.url)
                self.results.append(profile)
            except Exception as e:
                Actor.log.error(f"Error processing {context.request.url}: {str(e)}")
                # Add error profile to results
                error_profile = LinkedInProfile(
                    url=context.request.url,
                    is_valid=False,
                    extraction_errors=[str(e)]
                )
                self.results.append(error_profile)
    
    def validate_linkedin_url(self, url: str) -> bool:
        """Validate if URL is a proper LinkedIn profile URL."""
        try:
            parsed = urlparse(url)
            return (
                parsed.netloc in ['www.linkedin.com', 'linkedin.com'] and
                '/in/' in parsed.path and
                len(parsed.path.split('/')) >= 3
            )
        except Exception:
            return False
    
    async def scrape_profiles(self, profile_urls: List[str]) -> List[LinkedInProfile]:
        """Scrape multiple LinkedIn profiles with rate limiting."""
        if not self.crawler:
            await self.initialize()
        
        # Validate URLs
        valid_urls = [url for url in profile_urls if self.validate_linkedin_url(url)]
        invalid_count = len(profile_urls) - len(valid_urls)
        
        if invalid_count > 0:
            Actor.log.warning(f"Skipped {invalid_count} invalid LinkedIn URLs")
        
        if not valid_urls:
            Actor.log.error("No valid LinkedIn URLs provided")
            return []
        
        Actor.log.info(f"Starting to scrape {len(valid_urls)} LinkedIn profiles")
        
        # Use simple URLs for crawler (crawlee will handle Request creation)
        start_requests = valid_urls
        
        # Store results in a list instead of dataset to avoid conflicts
        self.results = []
        
        # Run crawler
        await self.crawler.run(start_requests)
        
        Actor.log.info(f"Successfully scraped {len([r for r in self.results if r.is_valid])} profiles")
        return self.results
    
    async def _respect_rate_limit(self) -> None:
        """Enforce minimum delay between requests based on 2024 research."""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        
        if elapsed < self.request_delay:
            delay = self.request_delay - elapsed
            Actor.log.debug(f"Rate limiting: waiting {delay:.2f} seconds")
            await asyncio.sleep(delay)
        
        self.last_request_time = time.time()

    def _safe_extract(self, page_content: str, selectors: List[str], field_name: str) -> Optional[str]:
        """Safely extract data with hierarchical fallback selectors."""
        for i, selector in enumerate(selectors):
            try:
                # Use page.query_selector instead of BeautifulSoup for better performance
                if selector.startswith('script[type="application/ld+json"]'):
                    continue  # Handle JSON-LD separately
                
                # This will be handled by the page object in the calling method
                Actor.log.debug(f"Trying selector {i+1}/{len(selectors)} for {field_name}: {selector}")
                return None  # Placeholder - actual extraction in _extract_profile_data
            except Exception as e:
                Actor.log.warning(f"Selector failed for {field_name}: {selector} - {str(e)}")
                continue
        
        Actor.log.warning(f"All selectors failed for {field_name}")
        return None

    def _extract_from_json_ld(self, page_content: str) -> Dict[str, Any]:
        """Extract profile data from JSON-LD structured data (most reliable method)."""
        data = {}
        
        # Find JSON-LD script tags
        json_ld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(json_ld_pattern, page_content, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            try:
                json_data = json.loads(match.strip())
                
                # Handle single object
                if isinstance(json_data, dict):
                    if json_data.get('@type') == 'Person':
                        data.update(self._parse_person_json_ld(json_data))
                
                # Handle @graph array
                elif isinstance(json_data, dict) and '@graph' in json_data:
                    for item in json_data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Person':
                            data.update(self._parse_person_json_ld(item))
                            break
                
                # Handle array of objects
                elif isinstance(json_data, list):
                    for item in json_data:
                        if isinstance(item, dict) and item.get('@type') == 'Person':
                            data.update(self._parse_person_json_ld(item))
                            break
                            
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                Actor.log.debug(f"Failed to parse JSON-LD: {str(e)}")
                continue
        
        if data:
            Actor.log.info(f"JSON-LD extraction successful: {list(data.keys())}")
        
        return data

    def _parse_person_json_ld(self, person_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Person schema from JSON-LD data."""
        extracted = {}
        
        # Name
        if 'name' in person_data:
            extracted['name'] = person_data['name']
        
        # Job title
        if 'jobTitle' in person_data:
            extracted['current_position'] = person_data['jobTitle']
        
        # Company
        if 'worksFor' in person_data:
            works_for = person_data['worksFor']
            if isinstance(works_for, dict) and 'name' in works_for:
                extracted['current_company'] = works_for['name']
            elif isinstance(works_for, str):
                extracted['current_company'] = works_for
        
        # Location
        if 'address' in person_data:
            address = person_data['address']
            if isinstance(address, dict):
                location_parts = []
                for key in ['addressLocality', 'addressRegion', 'addressCountry']:
                    if key in address:
                        location_parts.append(address[key])
                if location_parts:
                    extracted['location'] = ', '.join(location_parts)
            elif isinstance(address, str):
                extracted['location'] = address
        
        # Education
        if 'alumniOf' in person_data:
            alumni = person_data['alumniOf']
            if isinstance(alumni, list):
                extracted['education'] = [
                    item.get('name', str(item)) if isinstance(item, dict) else str(item)
                    for item in alumni
                ]
            elif isinstance(alumni, dict) and 'name' in alumni:
                extracted['education'] = [alumni['name']]
        
        return extracted

    async def _extract_with_css_selectors(self, page: Page) -> Dict[str, Any]:
        """Extract profile data using CSS selectors with hierarchical fallback."""
        data = {}
        
        # Extract name
        for selector in self.selectors['name']:
            try:
                element = await page.query_selector(selector)
                if element:
                    name = await element.text_content()
                    if name and name.strip():
                        data['name'] = name.strip()
                        break
            except Exception:
                continue
        
        # Extract headline
        for selector in self.selectors['headline']:
            try:
                element = await page.query_selector(selector)
                if element:
                    headline = await element.text_content()
                    if headline and headline.strip():
                        data['headline'] = headline.strip()
                        break
            except Exception:
                continue
        
        # Extract location
        for selector in self.selectors['location']:
            try:
                element = await page.query_selector(selector)
                if element:
                    location = await element.text_content()
                    if location and location.strip():
                        data['location'] = location.strip()
                        break
            except Exception:
                continue
        
        # Extract experience (current job)
        try:
            for container_selector in self.selectors['experience_container']:
                containers = await page.query_selector_all(container_selector)
                if containers and len(containers) > 0:
                    first_job = containers[0]
                    
                    # Extract job title
                    for title_selector in self.selectors['job_title']:
                        title_element = await first_job.query_selector(title_selector)
                        if title_element:
                            title = await title_element.text_content()
                            if title and title.strip():
                                data['current_position'] = title.strip()
                                break
                    
                    # Extract company name
                    for company_selector in self.selectors['company_name']:
                        company_element = await first_job.query_selector(company_selector)
                        if company_element:
                            company = await company_element.text_content()
                            if company and company.strip():
                                data['current_company'] = company.strip()
                                break
                    
                    break  # Found experience section
        except Exception as e:
            Actor.log.debug(f"Experience extraction failed: {str(e)}")
        
        return data

    def _extract_from_content(self, page_content: str) -> Dict[str, Any]:
        """Extract profile data using content-based patterns (last resort)."""
        data = {}
        
        # Extract name using regex patterns
        name_patterns = [
            r'<h1[^>]*>([^<]+)</h1>',
            r'"name"\s*:\s*"([^"]+)"',
            r'<title>([^|]+)\s*\|',
        ]
        
        for pattern in name_patterns:
            match = re.search(pattern, page_content, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name.split()) >= 2:  # Basic validation
                    data['name'] = name
                    break
        
        return data

    def _validate_profile_data(self, data: Dict[str, Any]) -> bool:
        """Validate extracted profile data quality."""
        # Check required fields
        if not data.get('name'):
            return False
        
        # Validate name format
        name = data.get('name', '')
        if len(name.split()) < 2 or len(name) < 3:
            return False
        
        # Validate headline if present
        headline = data.get('headline', '')
        if headline and len(headline) > 200:  # LinkedIn headline limit
            return False
        
        return True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((PlaywrightTimeoutError, Exception))
    )
    async def _extract_profile_data(self, page: Page, url: str) -> LinkedInProfile:
        """Extract data from LinkedIn profile using multi-layered approach."""
        profile = LinkedInProfile(url=url)
        
        try:
            # Respect rate limiting
            await self._respect_rate_limit()
            
            # Set LinkedIn authentication cookie
            if self.linkedin_cookie:
                Actor.log.info("Setting LinkedIn authentication cookie")
                await page.context.add_cookies([{
                    'name': 'li_at',
                    'value': self.linkedin_cookie,
                    'domain': '.linkedin.com',
                    'path': '/',
                    'httpOnly': True,
                    'secure': True
                }])
            else:
                Actor.log.warning("No LinkedIn cookie provided - may encounter access restrictions")
            
            # Set additional headers to avoid detection
            await page.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            })
            
            # Navigate directly with authentication cookie
            Actor.log.info(f"Accessing LinkedIn profile with authentication: {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Check for LinkedIn blocks/redirects
            current_url = page.url
            page_title = await page.title()
            
            Actor.log.info(f"Page loaded - URL: {current_url}")
            Actor.log.info(f"Page title: {page_title}")
            
            if any(block_indicator in current_url for block_indicator in [
                'linkedin.com/authwall', 'linkedin.com/checkpoint', 
                'linkedin.com/login', 'linkedin.com/uas/login'
            ]) or 'join linkedin' in page_title.lower():
                Actor.log.warning(f"LinkedIn access blocked - redirected to: {current_url}")
                Actor.log.warning(f"Page title indicates login required: {page_title}")
                # Don't raise exception, continue with limited extraction
            
            # Wait for content with timeout
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except PlaywrightTimeoutError:
                Actor.log.warning("Page load timeout - proceeding with extraction")
            
            # Get page content for multi-strategy extraction
            page_content = await page.content()
            
            # Multi-layered extraction
            extracted_data = {}
            
            # Strategy 1: JSON-LD (most reliable)
            try:
                json_ld_data = self._extract_from_json_ld(page_content)
                extracted_data.update(json_ld_data)
                Actor.log.info(f"JSON-LD extracted: {list(json_ld_data.keys())}")
            except Exception as e:
                Actor.log.warning(f"JSON-LD extraction failed: {str(e)}")
            
            # Strategy 2: CSS Selectors (fallback)
            try:
                css_data = await self._extract_with_css_selectors(page)
                # Only add fields not already extracted
                for key, value in css_data.items():
                    if key not in extracted_data and value:
                        extracted_data[key] = value
                Actor.log.info(f"CSS selectors extracted: {list(css_data.keys())}")
            except Exception as e:
                Actor.log.warning(f"CSS selector extraction failed: {str(e)}")
            
            # Strategy 3: Content-based (last resort)
            if not extracted_data.get('name'):
                try:
                    content_data = self._extract_from_content(page_content)
                    for key, value in content_data.items():
                        if key not in extracted_data and value:
                            extracted_data[key] = value
                    Actor.log.info(f"Content-based extracted: {list(content_data.keys())}")
                except Exception as e:
                    Actor.log.warning(f"Content-based extraction failed: {str(e)}")
            
            # Map extracted data to profile object
            if extracted_data.get('name'):
                profile.name = extracted_data['name']
            if extracted_data.get('headline'):
                profile.headline = extracted_data['headline']
            if extracted_data.get('current_position'):
                profile.current_position = extracted_data['current_position']
            if extracted_data.get('current_company'):
                profile.current_company = extracted_data['current_company']
            if extracted_data.get('location'):
                profile.location = extracted_data['location']
            if extracted_data.get('education'):
                profile.education = extracted_data['education']
            
            # Estimate additional fields
            profile.experience_years = self._estimate_experience_years(profile)
            profile.industry = self._extract_industry(profile)
            
            # Validate profile
            profile.is_valid = self._validate_profile_data(extracted_data)
            
            if profile.is_valid:
                Actor.log.info(f"Successfully extracted profile: {profile.name}")
            else:
                Actor.log.warning(f"Profile validation failed for: {url}")
            
            
        except Exception as e:
            profile.is_valid = False
            profile.extraction_errors.append(f"General extraction error: {str(e)}")
            Actor.log.error(f"Failed to extract profile data from {url}: {str(e)}")
        
        return profile
    
    def _estimate_experience_years(self, profile: LinkedInProfile) -> Optional[int]:
        """Estimate years of experience from profile data."""
        if not profile.headline and not profile.about:
            return None
        
        text = f"{profile.headline or ''} {profile.about or ''}"
        
        # Look for explicit year mentions
        year_patterns = [
            r'(\d+)\+?\s*years?\s*(?:of\s*)?experience',
            r'(\d+)\+?\s*years?\s*in',
            r'(\d+)\+?\s*yrs?\s*(?:of\s*)?experience',
        ]
        
        for pattern in year_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                try:
                    return int(matches[0])
                except ValueError:
                    continue
        
        # Fallback: estimate based on seniority keywords
        if any(word in text.lower() for word in ['senior', 'lead', 'principal', 'director']):
            return 8
        elif any(word in text.lower() for word in ['manager', 'supervisor']):
            return 5
        elif any(word in text.lower() for word in ['junior', 'associate', 'entry']):
            return 2
        
        return None
    
    def _extract_industry(self, profile: LinkedInProfile) -> Optional[str]:
        """Extract industry from profile data."""
        if not profile.headline and not profile.about:
            return None
        
        text = f"{profile.headline or ''} {profile.about or ''}"
        
        # Common industry keywords
        industry_keywords = {
            'technology': ['software', 'tech', 'programming', 'developer', 'engineer', 'IT'],
            'finance': ['finance', 'banking', 'investment', 'financial', 'accounting'],
            'healthcare': ['healthcare', 'medical', 'health', 'pharmaceutical', 'biotech'],
            'marketing': ['marketing', 'advertising', 'digital marketing', 'brand'],
            'sales': ['sales', 'business development', 'account management'],
            'consulting': ['consulting', 'consultant', 'advisory'],
            'education': ['education', 'teaching', 'academic', 'university'],
            'retail': ['retail', 'e-commerce', 'commerce'],
            'manufacturing': ['manufacturing', 'production', 'industrial'],
        }
        
        text_lower = text.lower()
        for industry, keywords in industry_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return industry.title()
        
        return None
