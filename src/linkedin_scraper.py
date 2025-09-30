"""LinkedIn profile scraper with rate limiting and error handling."""

from __future__ import annotations

import asyncio
import re
from typing import List, Optional
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
        request_delay: float = 2.0,
        retry_attempts: int = 3,
        headless: bool = True,
    ):
        self.max_concurrency = max_concurrency
        self.request_delay = request_delay
        self.retry_attempts = retry_attempts
        self.headless = headless
        self.crawler: Optional[PlaywrightCrawler] = None
        
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
                    '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ],
            },
            request_handler_timeout=60,
        )
        
        @self.crawler.router.default_handler
        async def profile_handler(context: PlaywrightCrawlingContext) -> None:
            """Handle LinkedIn profile scraping."""
            try:
                profile = await self._extract_profile_data(context.page, context.request.url)
                await context.push_data(profile)
            except Exception as e:
                Actor.log.error(f"Error processing {context.request.url}: {str(e)}")
                # Push error data for tracking
                error_profile = LinkedInProfile(
                    url=context.request.url,
                    is_valid=False,
                    extraction_errors=[str(e)]
                )
                await context.push_data(error_profile)
    
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
        
        # Add delay between requests
        start_requests = []
        for i, url in enumerate(valid_urls):
            start_requests.append({
                'url': url,
                'userData': {'delay': i * self.request_delay}
            })
        
        # Run crawler
        await self.crawler.run(start_requests)
        
        # Get results from dataset
        dataset = await Actor.open_dataset()
        results = []
        
        async for item in dataset.iterate_items():
            if isinstance(item, dict):
                # Convert dict back to LinkedInProfile
                profile = LinkedInProfile(**item)
                results.append(profile)
            else:
                results.append(item)
        
        Actor.log.info(f"Successfully scraped {len([r for r in results if r.is_valid])} profiles")
        return results
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((PlaywrightTimeoutError, Exception))
    )
    async def _extract_profile_data(self, page: Page, url: str) -> LinkedInProfile:
        """Extract data from a LinkedIn profile page."""
        profile = LinkedInProfile(url=url)
        
        try:
            # Wait for page to load
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Add random delay to mimic human behavior
            await asyncio.sleep(1 + (hash(url) % 3))
            
            # Extract name
            try:
                name_selector = 'h1.text-heading-xlarge, h1[data-anonymize="person-name"]'
                name_element = await page.wait_for_selector(name_selector, timeout=10000)
                if name_element:
                    profile.name = await name_element.text_content()
                    profile.name = profile.name.strip() if profile.name else None
            except Exception as e:
                profile.extraction_errors.append(f"Name extraction failed: {str(e)}")
            
            # Extract headline
            try:
                headline_selector = '.text-body-medium.break-words, .pv-text-details__left-panel .text-body-medium'
                headline_element = await page.query_selector(headline_selector)
                if headline_element:
                    profile.headline = await headline_element.text_content()
                    profile.headline = profile.headline.strip() if profile.headline else None
            except Exception as e:
                profile.extraction_errors.append(f"Headline extraction failed: {str(e)}")
            
            # Extract current position and company
            try:
                experience_section = await page.query_selector('#experience')
                if experience_section:
                    # Look for the first experience item
                    first_job = await experience_section.query_selector('.pvs-entity')
                    if first_job:
                        # Position title
                        position_element = await first_job.query_selector('.mr1.t-bold span[aria-hidden="true"]')
                        if position_element:
                            profile.current_position = await position_element.text_content()
                            profile.current_position = profile.current_position.strip() if profile.current_position else None
                        
                        # Company name
                        company_element = await first_job.query_selector('.t-14.t-normal span[aria-hidden="true"]')
                        if company_element:
                            profile.current_company = await company_element.text_content()
                            profile.current_company = profile.current_company.strip() if profile.current_company else None
            except Exception as e:
                profile.extraction_errors.append(f"Experience extraction failed: {str(e)}")
            
            # Extract location
            try:
                location_selector = '.text-body-small.inline.t-black--light.break-words'
                location_element = await page.query_selector(location_selector)
                if location_element:
                    profile.location = await location_element.text_content()
                    profile.location = profile.location.strip() if profile.location else None
            except Exception as e:
                profile.extraction_errors.append(f"Location extraction failed: {str(e)}")
            
            # Extract connections count
            try:
                connections_selector = '.t-black--light.t-normal'
                connections_elements = await page.query_selector_all(connections_selector)
                for element in connections_elements:
                    text = await element.text_content()
                    if text and ('connection' in text.lower() or 'follower' in text.lower()):
                        profile.connections = text.strip()
                        break
            except Exception as e:
                profile.extraction_errors.append(f"Connections extraction failed: {str(e)}")
            
            # Extract about section
            try:
                about_section = await page.query_selector('#about')
                if about_section:
                    about_text = await about_section.query_selector('.full-width .break-words')
                    if about_text:
                        profile.about = await about_text.text_content()
                        profile.about = profile.about.strip() if profile.about else None
            except Exception as e:
                profile.extraction_errors.append(f"About extraction failed: {str(e)}")
            
            # Extract skills
            try:
                skills_section = await page.query_selector('#skills')
                if skills_section:
                    skill_elements = await skills_section.query_selector_all('.mr1.hoverable-link-text.t-bold span[aria-hidden="true"]')
                    for skill_element in skill_elements[:10]:  # Limit to first 10 skills
                        skill_text = await skill_element.text_content()
                        if skill_text:
                            profile.skills.append(skill_text.strip())
            except Exception as e:
                profile.extraction_errors.append(f"Skills extraction failed: {str(e)}")
            
            # Extract education
            try:
                education_section = await page.query_selector('#education')
                if education_section:
                    edu_elements = await education_section.query_selector_all('.mr1.hoverable-link-text.t-bold span[aria-hidden="true"]')
                    for edu_element in edu_elements[:3]:  # Limit to first 3 education entries
                        edu_text = await edu_element.text_content()
                        if edu_text:
                            profile.education.append(edu_text.strip())
            except Exception as e:
                profile.extraction_errors.append(f"Education extraction failed: {str(e)}")
            
            # Estimate experience years from headline or about
            try:
                profile.experience_years = self._estimate_experience_years(profile)
            except Exception as e:
                profile.extraction_errors.append(f"Experience estimation failed: {str(e)}")
            
            # Extract industry from headline or about
            try:
                profile.industry = self._extract_industry(profile)
            except Exception as e:
                profile.extraction_errors.append(f"Industry extraction failed: {str(e)}")
            
            # Estimate company size (this would require additional logic or external data)
            profile.company_size = "Unknown"
            
            # Mark as valid if we got basic info
            profile.is_valid = bool(profile.name or profile.headline or profile.current_position)
            
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
