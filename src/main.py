"""LinkedIn Lead Qualifier Actor - Main entry point.

This actor scrapes LinkedIn profiles, scores them against qualification criteria,
and returns only the leads that meet your specified requirements.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from apify import Actor

from .models import (
    QualificationCriteria,
    ScoringWeights,
    ProcessingStats,
)
from .linkedin_scraper import LinkedInScraper
from .scoring_engine import LeadScoringEngine


async def main() -> None:
    """Main entry point for the LinkedIn Lead Qualifier Actor."""
    start_time = time.time()

    async with Actor:
        # Get and validate input
        actor_input = await Actor.get_input() or {}
        
        # Debug: Log the received input
        Actor.log.info(f'Received input: {actor_input}')
        
        # Validate required input - prioritize start_urls format
        profile_urls = actor_input.get('start_urls', [])
        
        # If start_urls format, extract URLs from objects
        if isinstance(profile_urls, list) and profile_urls and isinstance(profile_urls[0], dict):
            profile_urls = [item.get('url', '') for item in profile_urls if item.get('url')]
        
        # Fallback to alternative input formats
        if not profile_urls:
            profile_urls = (
                actor_input.get('profileUrls', []) or
                actor_input.get('profile_urls', []) or
                actor_input.get('urls', []) or
                []
            )
        
        if not profile_urls:
            Actor.log.error('No LinkedIn profile URLs provided in input')
            Actor.log.error('Expected input format: {"start_urls": [{"url": "https://www.linkedin.com/in/profile/"}]}')
            await Actor.exit(exit_code=1)
        
        Actor.log.info(f'Starting LinkedIn Lead Qualifier with {len(profile_urls)} profiles')
        
        # Parse qualification criteria
        criteria_input = actor_input.get('qualificationCriteria', {})
        criteria = QualificationCriteria(
            target_job_titles=criteria_input.get('targetJobTitles', []),
            target_industries=criteria_input.get('targetIndustries', []),
            target_locations=criteria_input.get('targetLocations', []),
            min_experience_years=criteria_input.get('minExperienceYears', 0),
            target_company_sizes=criteria_input.get('targetCompanySizes', []),
            required_skills=criteria_input.get('requiredSkills', []),
        )
        
        # Parse scoring weights
        weights_input = actor_input.get('scoringWeights', {})
        weights = ScoringWeights(
            job_title_weight=weights_input.get('jobTitleWeight', 0.25),
            industry_weight=weights_input.get('industryWeight', 0.20),
            location_weight=weights_input.get('locationWeight', 0.15),
            experience_weight=weights_input.get('experienceWeight', 0.20),
            company_size_weight=weights_input.get('companySizeWeight', 0.10),
            skills_weight=weights_input.get('skillsWeight', 0.10),
        )
        
        # Validate weights
        try:
            if not weights.validate():
                Actor.log.warning('Scoring weights do not sum to 1.0, normalizing...')
                # Normalize weights
                total = (weights.job_title_weight + weights.industry_weight + 
                        weights.location_weight + weights.experience_weight + 
                        weights.company_size_weight + weights.skills_weight)
                if total > 0:
                    weights.job_title_weight /= total
                    weights.industry_weight /= total
                    weights.location_weight /= total
                    weights.experience_weight /= total
                    weights.company_size_weight /= total
                    weights.skills_weight /= total
        except Exception as e:
            Actor.log.error(f'Invalid scoring weights: {e}')
            await Actor.exit(exit_code=1)
        
        # Parse filtering options
        filtering_input = actor_input.get('filteringOptions', {})
        min_score = filtering_input.get('minQualificationScore', 60)
        max_results = filtering_input.get('maxResults', 100)
        include_breakdown = filtering_input.get('includeScoreBreakdown', True)
        
        # Parse processing options
        processing_input = actor_input.get('processingOptions', {})
        linkedin_cookie = processing_input.get('linkedinCookie')
        max_concurrency = processing_input.get('maxConcurrency', 5)
        request_delay = processing_input.get('requestDelay', 2.0)
        retry_attempts = processing_input.get('retryAttempts', 3)
        headless = processing_input.get('headless', True)
        
        # Log configuration
        Actor.log.info(f'Qualification criteria: {len(criteria.target_job_titles)} job titles, '
                      f'{len(criteria.target_industries)} industries, '
                      f'{len(criteria.target_locations)} locations')
        Actor.log.info(f'Minimum score threshold: {min_score}')
        Actor.log.info(f'Processing with concurrency: {max_concurrency}, delay: {request_delay}s')
        
        # Initialize components
        scraper = LinkedInScraper(
            max_concurrency=max_concurrency,
            request_delay=request_delay,
            retry_attempts=retry_attempts,
            headless=headless,
            linkedin_cookie=linkedin_cookie,
        )
        
        scoring_engine = LeadScoringEngine(criteria, weights)
        
        # Initialize statistics
        stats = ProcessingStats(total_profiles=len(profile_urls))
        
        try:
            # Scrape profiles
            Actor.log.info('Starting profile extraction...')
            profiles = await scraper.scrape_profiles(profile_urls)
            
            stats.successful_extractions = len([p for p in profiles if p.is_valid])
            stats.failed_extractions = len([p for p in profiles if not p.is_valid])
            
            Actor.log.info(f'Extracted {stats.successful_extractions} valid profiles, '
                          f'{stats.failed_extractions} failed')
            
            # Score and qualify leads
            Actor.log.info('Scoring and qualifying leads...')
            qualified_leads = []
            total_scores = []
            
            for profile in profiles:
                if not profile.is_valid:
                    continue
                
                qualified_lead = scoring_engine.qualify_lead(profile, min_score)
                if qualified_lead:
                    qualified_leads.append(qualified_lead)
                    total_scores.append(qualified_lead.total_score)
                    
                    # Respect max results limit
                    if len(qualified_leads) >= max_results:
                        Actor.log.info(f'Reached maximum results limit of {max_results}')
                        break
            
            stats.qualified_leads = len(qualified_leads)
            if total_scores:
                stats.average_score = sum(total_scores) / len(total_scores)
            
            # Output results
            Actor.log.info(f'Qualified {stats.qualified_leads} leads with average score {stats.average_score:.1f}')
            
            # Store qualified leads in dataset
            dataset_items = []
            for lead in qualified_leads:
                try:
                    lead_data = lead.to_dict()
                    
                    # Optionally exclude detailed breakdown to reduce output size
                    if not include_breakdown:
                        # Keep only essential scoring info
                        essential_keys = [
                            'url', 'name', 'headline', 'current_position', 'current_company',
                            'location', 'industry', 'experience_years', 'skills', 'total_score',
                            'qualification_reasons', 'scraped_at', 'qualified_at'
                        ]
                        lead_data = {k: v for k, v in lead_data.items() if k in essential_keys}
                    
                    dataset_items.append(lead_data)
                except Exception as e:
                    Actor.log.error(f"Error serializing lead data: {str(e)}")
                    # Add minimal data for failed serialization
                    dataset_items.append({
                        'url': lead.profile.url,
                        'error': f"Serialization failed: {str(e)}",
                        'total_score': lead.total_score
                    })
            
            # Push all results to dataset
            if dataset_items:
                await Actor.push_data(dataset_items)
                Actor.log.info(f'Saved {len(dataset_items)} qualified leads to dataset')
            else:
                Actor.log.warning('No leads met the qualification criteria')
            
            # Calculate final statistics
            stats.processing_time_seconds = time.time() - start_time
            
            # Log final statistics
            final_stats = stats.to_dict()
            Actor.log.info('Processing completed successfully')
            Actor.log.info(f'Final statistics: {final_stats}')
            
            # Store statistics as metadata
            await Actor.set_value('PROCESSING_STATS', final_stats)
            
        except Exception as e:
            Actor.log.error(f'Error during processing: {str(e)}')
            stats.processing_time_seconds = time.time() - start_time
            await Actor.set_value('PROCESSING_STATS', stats.to_dict())
            raise
